"""
PipelineStore — Dual-scope CRUD for pipeline configurations.

Storage model:
- Workspace scope: {workspace}/.pubmed-search/pipelines/{name}.yaml
- Global scope:    ~/.pubmed-search-mcp/pipelines/{name}.yaml

Resolution order: workspace → global (load), auto-detect (save).
"""

from __future__ import annotations

import copy
import json
import logging
import re
import shutil
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

import yaml

from pubmed_search.application.pipeline.config_parser import parse_pipeline_config_file
from pubmed_search.application.pipeline.validator import (
    compute_config_hash,
    parse_and_validate_config,
    validate_pipeline_config,
    validate_pipeline_name,
    validate_pipeline_tags,
)
from pubmed_search.domain.entities.pipeline import (
    PipelineConfig,
    PipelineMeta,
    PipelineRun,
    PipelineScope,
    ScheduleEntry,
    ValidationResult,
)
from pubmed_search.shared.credential_sanitizer import contains_credential_material
from pubmed_search.shared.file_io import atomic_write_json, atomic_write_text
from pubmed_search.shared.locking import synchronized

logger = logging.getLogger(__name__)

# Maximum execution history records per pipeline
_MAX_HISTORY = 100
_RUN_RECORDS_FILE = "records.jsonl"
_SAFE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

# MCP SDK v2 runs synchronous tools in AnyIO worker threads. Pipeline metadata
# uses read-modify-write JSON transactions, so every store instance in this
# process must share one re-entrant transaction boundary. Service deployments
# intentionally remain single-process/single-replica until this file storage is
# replaced with a transactional shared backend.
_PIPELINE_PERSISTENCE_LOCK = threading.RLock()


class PipelineHistoryError(RuntimeError):
    """A persisted pipeline run record could not be decoded safely."""


class ScreeningLogPresentError(ValueError):
    """Deletion would remove a screening log the caller did not explicitly opt to delete."""

    def __init__(self, message: str, *, summary: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.summary = summary


class PipelineDeletionError(RuntimeError):
    """Deletion stopped early; the pipeline still exists and a retry completes it."""


class RetirableScreeningLog(Protocol):
    """Screening-log operations deletion needs (implemented by the SQLite log)."""

    def retire(self, *, allow_decisions: bool) -> dict[str, Any]: ...

    def restore(self) -> None: ...


ScreeningLogFactory = Callable[[Path], RetirableScreeningLog]


@dataclass(frozen=True)
class PipelineDeletion:
    """What one successful deletion removed."""

    scope: PipelineScope
    run_count: int
    # Summary (decisions, PMIDs, reviewers, records) of a removed screening log.
    screening_log: dict[str, Any] | None = None


_SCREENING_LOG_SIDECARS = ("-journal", "-wal", "-shm", "")
WORKSPACE_DATA_DIRNAME = ".pubmed-search"
# Written once into a workspace data directory this store creates. Run record
# sets carry titles and abstracts and the screening log holds reviewers' work;
# neither should reach a project repository by accident.
WORKSPACE_GITIGNORE = """# Created by pubmed-search-mcp: local research data (saved pipelines, run record
# sets with titles/abstracts, screening decisions, reports). Ignored by default.
# To share saved pipeline definitions through git, replace this file, e.g. with:
#   /*
#   !/.gitignore
#   !/pipelines/
#   /pipelines/*
#   !/pipelines/*.yaml
*
"""


def _config_to_dict(config: PipelineConfig, *, include_output_defaults: bool = False) -> dict[str, Any]:
    """Serialize one canonical pipeline mapping, optionally including output defaults for display."""
    data: dict[str, Any] = {}

    if config.name:
        data["name"] = config.name

    if config.globals:
        data["globals"] = config.globals
    if config.variables:
        data["variables"] = config.variables

    if config.template:
        data["template"] = config.template
        if config.template_params:
            data["template_params"] = config.template_params
    elif config.steps:
        data["steps"] = [
            {
                "id": s.id,
                "action": s.action,
                **({"params": s.params} if s.params else {}),
                **({"inputs": s.inputs} if s.inputs else {}),
                **({"on_error": s.on_error} if s.on_error != "skip" else {}),
            }
            for s in config.steps
        ]

    # Output (only if non-default)
    out = config.output
    if include_output_defaults or out.format != "markdown" or out.limit != 20 or out.ranking != "balanced":
        data["output"] = {}
        if include_output_defaults or out.format != "markdown":
            data["output"]["format"] = out.format
        if include_output_defaults or out.limit != 20:
            data["output"]["limit"] = out.limit
        if include_output_defaults or out.ranking != "balanced":
            data["output"]["ranking"] = out.ranking

    return data


class PipelineStore:
    """Dual-scope CRUD for saved pipeline configurations.

    Args:
        global_data_dir: Path to global data directory (~/.pubmed-search-mcp)
        workspace_dir: Optional workspace root. If set, enables workspace scope.
    """

    def __init__(
        self,
        global_data_dir: str | Path,
        workspace_dir: str | Path | None = None,
    ) -> None:
        self._lock = _PIPELINE_PERSISTENCE_LOCK
        self._global_dir = Path(global_data_dir)
        self._workspace_dir = Path(workspace_dir) if workspace_dir else None
        # Set only on views returned by pinned_to(): name lookups use this scope.
        self._pinned_scope: PipelineScope | None = None

        # Ensure directories exist
        self._global_pipelines_dir.mkdir(parents=True, exist_ok=True)
        self._global_runs_dir.mkdir(parents=True, exist_ok=True)

        if self._workspace_dir:
            data_root = self._workspace_dir / WORKSPACE_DATA_DIRNAME
            created_root = not data_root.exists()
            self._workspace_pipelines_dir.mkdir(parents=True, exist_ok=True)
            self._workspace_runs_dir.mkdir(parents=True, exist_ok=True)
            if created_root:
                self._write_workspace_gitignore(data_root)

    @staticmethod
    def _write_workspace_gitignore(data_root: Path) -> None:
        """Ignore a newly created workspace data directory; never replace an existing file."""
        try:
            with (data_root / ".gitignore").open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(WORKSPACE_GITIGNORE)
        except FileExistsError:
            return
        except OSError as exc:
            logger.warning("Could not create the workspace data .gitignore (%s)", type(exc).__name__)

    def pinned_to(self, scope: PipelineScope) -> PipelineStore:
        """Return a view of this store whose name lookups always use ``scope``.

        A workspace pipeline shadows a same-name global one. A run persists
        through the view pinned to the scope its pipeline was loaded from, so
        its run record, record set, report, history pruning and screening log
        stay in that scope even if a same-name pipeline appears or disappears
        in the other scope meanwhile.
        """
        if scope == PipelineScope.WORKSPACE and not self._workspace_dir:
            msg = "Workspace scope requested but no workspace directory is configured"
            raise ValueError(msg)
        view = copy.copy(self)
        view._pinned_scope = scope  # noqa: SLF001 - a view of this class
        return view

    def _lookup_scopes(self) -> list[PipelineScope]:
        """Scopes searched for a pipeline name, in precedence order."""
        if self._pinned_scope is not None:
            return [self._pinned_scope]
        return [PipelineScope.WORKSPACE, PipelineScope.GLOBAL] if self._workspace_dir else [PipelineScope.GLOBAL]

    def rebased(self, global_data_dir: str | Path) -> PipelineStore:
        """Return an equivalent store rooted at a different global directory.

        Used to give each tenant its own global pipeline scope. The derived
        store deliberately has no workspace scope: a checkout-wide workspace
        directory is shared state and therefore cannot belong to one tenant.

        Args:
            global_data_dir: New global data directory for the derived store.

        Returns:
            A new :class:`PipelineStore` with an isolated global scope only.
        """
        return PipelineStore(global_data_dir=global_data_dir)

    @property
    def global_data_dir(self) -> Path:
        """Return the global data directory backing this store."""
        return self._global_dir

    # ── Directory helpers ────────────────────────────────────────────────

    @property
    def _global_pipelines_dir(self) -> Path:
        return self._global_dir / "pipelines"

    @property
    def _global_runs_dir(self) -> Path:
        return self._global_dir / "pipeline_runs"

    @property
    def _global_index_path(self) -> Path:
        return self._global_pipelines_dir / "_index.json"

    @property
    def _global_schedules_path(self) -> Path:
        return self._global_dir / "schedules.json"

    @property
    def _workspace_pipelines_dir(self) -> Path:
        if not self._workspace_dir:
            msg = "No workspace directory configured"
            raise RuntimeError(msg)
        return self._workspace_dir / ".pubmed-search" / "pipelines"

    @property
    def _workspace_runs_dir(self) -> Path:
        if not self._workspace_dir:
            msg = "No workspace directory configured"
            raise RuntimeError(msg)
        return self._workspace_dir / ".pubmed-search" / "pipeline_runs"

    @property
    def _workspace_index_path(self) -> Path:
        return self._workspace_pipelines_dir / "_index.json"

    def _resolve_scope(self, scope: str) -> PipelineScope:
        """Resolve 'auto' scope to workspace (if available) or global."""
        if scope == "workspace":
            if not self._workspace_dir:
                msg = "Workspace scope requested but no workspace directory is configured"
                raise ValueError(msg)
            return PipelineScope.WORKSPACE
        if scope == "global":
            return PipelineScope.GLOBAL
        if scope != "auto":
            raise ValueError("Pipeline scope must be auto, workspace, or global")
        # auto: prefer workspace
        if self._workspace_dir:
            return PipelineScope.WORKSPACE
        return PipelineScope.GLOBAL

    def _pipelines_dir_for(self, scope: PipelineScope) -> Path:
        if scope == PipelineScope.WORKSPACE:
            return self._workspace_pipelines_dir
        return self._global_pipelines_dir

    def _runs_dir_for(self, scope: PipelineScope) -> Path:
        if scope == PipelineScope.WORKSPACE:
            return self._workspace_runs_dir
        return self._global_runs_dir

    def _index_path_for(self, scope: PipelineScope) -> Path:
        if scope == PipelineScope.WORKSPACE:
            return self._workspace_index_path
        return self._global_index_path

    # ── Index management ─────────────────────────────────────────────────

    def _load_index(self, scope: PipelineScope) -> dict[str, PipelineMeta]:
        """Load and reconcile the rebuildable metadata index for a scope."""
        path = self._index_path_for(scope)
        index: dict[str, PipelineMeta] = {}
        dirty = False
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    logger.warning("Pipeline index is not a JSON object; rebuilding")
                    dirty = True
                else:
                    for name, meta in data.items():
                        try:
                            canonical_name = self._validate_name(name)
                            decoded = PipelineMeta.from_dict(meta)
                            if decoded.name != canonical_name:
                                logger.warning(
                                    "Dropping pipeline index entry whose metadata name does not match key %s",
                                    name,
                                )
                                dirty = True
                                continue
                            decoded.tags = validate_pipeline_tags(decoded.tags)
                            index[canonical_name] = decoded
                        except (AttributeError, TypeError, ValueError):
                            logger.warning("Dropping malformed pipeline index entry")
                            dirty = True
            except (OSError, TypeError, ValueError):
                logger.warning("Failed to load pipeline index; rebuilding from pipeline files")
                dirty = True

        pipelines_dir = self._pipelines_dir_for(scope)
        yaml_names: set[str] = set()
        for candidate in pipelines_dir.glob("*.yaml"):
            if not candidate.is_file():
                continue
            try:
                yaml_names.add(self._validate_name(candidate.stem))
            except ValueError:
                logger.warning("Ignoring pipeline file with a noncanonical name")

        for stale_name in set(index).difference(yaml_names):
            index.pop(stale_name, None)
            dirty = True

        for name in sorted(yaml_names.difference(index)):
            rebuilt = self._metadata_from_pipeline_file(pipelines_dir / f"{name}.yaml", scope, name)
            if rebuilt is not None:
                index[name] = rebuilt
                dirty = True

        if dirty:
            self._save_index(scope, index)
        return index

    def _metadata_from_pipeline_file(
        self,
        path: Path,
        scope: PipelineScope,
        name: str,
    ) -> PipelineMeta | None:
        """Best-effort metadata reconstruction for an orphaned YAML file."""
        try:
            raw_data = parse_pipeline_config_file(path)
            result = parse_and_validate_config(raw_data)
            config = result.config
            if not result.valid or config is None:
                return None
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            runs_dir = self._runs_dir_for(scope) / name
            return PipelineMeta(
                name=name,
                scope=scope,
                config_hash=compute_config_hash(config),
                step_count=len(config.steps) if config.steps else 0,
                created=modified,
                updated=modified,
                run_count=sum(1 for run_file in runs_dir.glob("*.json") if run_file.is_file())
                if runs_dir.is_dir()
                else 0,
            )
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("Unable to rebuild pipeline metadata (%s)", type(exc).__name__)
            return None

    def _save_index(self, scope: PipelineScope, index: dict[str, PipelineMeta]) -> None:
        """Save the metadata index for a scope."""
        path = self._index_path_for(scope)
        data = {name: meta.to_dict() for name, meta in index.items()}
        atomic_write_json(path, data)

    @staticmethod
    def _validate_name(name: str, *, allow_saved_prefix: bool = False) -> str:
        """Return a canonical name without rewriting caller-provided identity."""
        candidate = name
        if allow_saved_prefix:
            candidate = candidate.removeprefix("saved:")
        return validate_pipeline_name(candidate)

    @staticmethod
    def _validate_run_id(run_id: str) -> str:
        """Reject run identifiers that could escape their pipeline directory."""
        candidate = run_id.strip()
        if not _SAFE_RUN_ID_RE.fullmatch(candidate):
            msg = f"Unsafe pipeline run id: {run_id}"
            raise ValueError(msg)
        return candidate

    # ── Core CRUD ────────────────────────────────────────────────────────

    @synchronized
    def save(
        self,
        name: str,
        config: PipelineConfig,
        *,
        tags: list[str] | None = None,
        description: str = "",
        scope: str = "auto",
    ) -> tuple[PipelineMeta, ValidationResult]:
        """Save a pipeline configuration.

        Strictly validates the config without rewriting caller input.

        Args:
            name: Canonical pipeline name.
            config: Pipeline configuration.
            tags: Optional tags.
            description: Optional description.
            scope: "workspace", "global", or "auto".

        Returns:
            (PipelineMeta, ValidationResult) — metadata + validation result.

        Raises:
            ValueError: If name or config is invalid.
        """
        # Validate identity before an upsert: caller inputs are never rewritten
        # into an existing pipeline key.
        name = validate_pipeline_name(name)
        validated_tags = validate_pipeline_tags(tags)

        result = validate_pipeline_config(config)

        if not result.valid:
            msg = f"Pipeline config validation failed: {'; '.join(result.errors)}"
            raise ValueError(msg)

        config = result.config or config

        # Determine scope
        resolved_scope = self._resolve_scope(scope)
        pipelines_dir = self._pipelines_dir_for(resolved_scope)
        pipelines_dir.mkdir(parents=True, exist_ok=True)
        index = self._load_index(resolved_scope)

        # Save YAML file
        config_dict = _config_to_dict(config)
        serialized_config = yaml.safe_dump(config_dict, allow_unicode=True, sort_keys=False)
        if contains_credential_material(serialized_config):
            msg = "Pipeline config contains credential material; use server environment configuration instead"
            raise ValueError(msg)
        yaml_path = pipelines_dir / f"{name}.yaml"
        atomic_write_text(yaml_path, serialized_config)

        # Update index
        now = datetime.now(timezone.utc)

        existing = index.get(name)
        meta = PipelineMeta(
            name=name,
            scope=resolved_scope,
            description=description,
            tags=validated_tags,
            config_hash=compute_config_hash(config),
            step_count=len(config.steps) if config.steps else 0,
            created=existing.created if existing else now,
            updated=now,
            run_count=existing.run_count if existing else 0,
        )
        index[name] = meta
        self._save_index(resolved_scope, index)

        logger.info("Saved one pipeline to %s scope", resolved_scope.value)
        return meta, result

    @synchronized
    def load(self, name: str) -> tuple[PipelineConfig, PipelineMeta]:
        """Load a pipeline by name (workspace → global fallback).

        Returns:
            (PipelineConfig, PipelineMeta)

        Raises:
            FileNotFoundError: If pipeline not found in any scope.
        """
        name = self._validate_name(name, allow_saved_prefix=True)

        # Workspace first, then global (only the pinned scope for a pinned view).
        for scope in self._lookup_scopes():
            path = self._pipelines_dir_for(scope) / f"{name}.yaml"
            if path.exists():
                return self._load_from_file(path, scope, name)

        msg = (
            f"Pipeline '{name}' not found. "
            f"Searched: workspace (.pubmed-search/pipelines/) and "
            f"global (~/.pubmed-search-mcp/pipelines/)"
        )
        raise FileNotFoundError(msg)

    def _load_from_file(self, path: Path, scope: PipelineScope, name: str) -> tuple[PipelineConfig, PipelineMeta]:
        """Load and validate a pipeline from a YAML file."""
        raw_data = parse_pipeline_config_file(path)

        result = parse_and_validate_config(raw_data)

        if not result.valid:
            msg = f"Pipeline '{name}' has unfixable errors: {'; '.join(result.errors)}"
            raise ValueError(msg)

        config = result.config
        if config is None:
            msg = f"Pipeline '{name}' parsed but no config returned"
            raise ValueError(msg)

        # Get or create metadata, detecting supported manual YAML edits.
        index = self._load_index(scope)
        meta = index.get(name)
        current_hash = compute_config_hash(config)
        if meta is not None and meta.config_hash != current_hash:
            meta.config_hash = current_hash
            meta.step_count = len(config.steps)
            meta.updated = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            self._save_index(scope, index)
        if not meta:
            meta = PipelineMeta(
                name=name,
                scope=scope,
                config_hash=compute_config_hash(config),
                step_count=len(config.steps) if config.steps else 0,
                updated=datetime.now(timezone.utc),
            )
            index[name] = meta
            self._save_index(scope, index)

        return config, meta

    @synchronized
    def load_from_path(self, path: str | Path) -> tuple[PipelineConfig, ValidationResult]:
        """Load a pipeline from an arbitrary file path.

        Args:
            path: Absolute or relative file path.

        Returns:
            (PipelineConfig, ValidationResult)
        """
        filepath = Path(path)
        if not filepath.exists():
            msg = f"Pipeline file not found: {filepath}"
            raise FileNotFoundError(msg)

        raw_data = parse_pipeline_config_file(filepath)

        result = parse_and_validate_config(raw_data)
        if not result.valid:
            msg = f"Pipeline validation failed: {'; '.join(result.errors)}"
            raise ValueError(msg)

        return result.config, result  # type: ignore[return-value]

    @synchronized
    def list_pipelines(
        self,
        *,
        tag: str = "",
        scope: str = "",
    ) -> list[PipelineMeta]:
        """List all saved pipelines, optionally filtered.

        Args:
            tag: Filter by tag (case-insensitive).
            scope: Filter by "workspace", "global", or "" (all).

        Returns:
            List of PipelineMeta, sorted by updated date (newest first).
        """
        indexed_results: list[tuple[int, PipelineMeta]] = []

        scopes_to_check = []
        if scope == "workspace":
            if self._workspace_dir:
                scopes_to_check.append(PipelineScope.WORKSPACE)
        elif scope == "global":
            scopes_to_check.append(PipelineScope.GLOBAL)
        else:
            # All scopes
            if self._workspace_dir:
                scopes_to_check.append(PipelineScope.WORKSPACE)
            scopes_to_check.append(PipelineScope.GLOBAL)

        seen_names: set[str] = set()
        for s in scopes_to_check:
            index = self._load_index(s)
            for name, meta in index.items():
                if name in seen_names:
                    continue  # workspace already seen, skip global duplicate
                if tag and tag.lower() not in [t.lower() for t in meta.tags]:
                    continue
                indexed_results.append((len(indexed_results), meta))
                seen_names.add(name)

        # Sort by updated (newest first). Preserve newest save order when
        # consecutive writes share the same timestamp resolution.
        indexed_results.sort(
            key=lambda item: (
                item[1].updated or datetime.min.replace(tzinfo=timezone.utc),
                item[0],
            ),
            reverse=True,
        )
        return [meta for _, meta in indexed_results]

    @synchronized
    def delete(
        self,
        name: str,
        *,
        delete_screening_log: bool = False,
        screening_log: ScreeningLogFactory | None = None,
    ) -> PipelineDeletion:
        """Delete a pipeline and its history.

        Searches workspace first, then global. A screening log holds human
        work. With ``screening_log`` (a factory for the log at a path), the
        decision check and the log's retirement happen in one log
        transaction, so deletion refuses (nothing is removed) whenever the
        log holds decisions and ``delete_screening_log`` is false, even if a
        decision is recorded concurrently. Without a factory, any existing
        log makes deletion fail closed unless ``delete_screening_log`` is set.

        Removal order keeps every failure retryable: the screening log first
        (a locked log is restored and nothing else is touched), then run
        history and record artifacts, and the YAML/index last, so the
        pipeline exists until everything else is gone.

        Raises:
            FileNotFoundError: If pipeline not found.
            ScreeningLogPresentError: The screening log must not be deleted.
            PipelineDeletionError: A file could not be removed (e.g. locked on
                Windows); the pipeline still exists and a retry completes it.
        """
        name = self._validate_name(name)

        # Workspace first, then global (only the pinned scope for a pinned view).
        for scope in self._lookup_scopes():
            if (self._pipelines_dir_for(scope) / f"{name}.yaml").exists():
                return self._delete_from_scope(
                    name, scope, delete_screening_log=delete_screening_log, screening_log=screening_log
                )

        msg = f"Pipeline '{name}' not found"
        raise FileNotFoundError(msg)

    def _remove_screening_log(
        self,
        name: str,
        screening_db: Path,
        *,
        delete_screening_log: bool,
        screening_log: ScreeningLogFactory | None,
    ) -> dict[str, Any] | None:
        """Remove the screening log first; on any failure nothing else has been touched."""
        if not screening_db.is_file():
            return None
        refusal = f"Pipeline '{name}' has a screening log; refusing to delete it without explicit opt-in"
        log = None
        summary: dict[str, Any] | None = None
        if screening_log is None:
            if not delete_screening_log:
                raise ScreeningLogPresentError(refusal)
        else:
            log = screening_log(screening_db)
            try:
                summary = log.retire(allow_decisions=delete_screening_log)
            except Exception as exc:
                msg = (
                    f"Pipeline '{name}' was not deleted: its screening log could not be inspected "
                    f"({type(exc).__name__}). Nothing was removed."
                )
                raise PipelineDeletionError(msg) from exc
            if not summary.get("retired"):
                raise ScreeningLogPresentError(refusal, summary=summary)
        try:
            # The log belongs to this pipeline's identification history; leaving
            # it would silently reattach decisions to a future same-name strategy.
            for suffix in _SCREENING_LOG_SIDECARS:
                sidecar = screening_db.with_name(screening_db.name + suffix)
                if sidecar.is_file():
                    sidecar.unlink()
        except OSError as exc:
            if log is not None and screening_db.is_file():
                try:
                    log.restore()
                except Exception as restore_exc:  # the log stays retired; a retried delete finishes it
                    logger.warning("Screening log could not be restored (%s)", type(restore_exc).__name__)
            msg = (
                f"Pipeline '{name}' was not deleted: its screening log is in use by another process "
                f"({type(exc).__name__}). Nothing was removed; close other screening sessions and retry."
            )
            raise PipelineDeletionError(msg) from exc
        return summary

    def _delete_from_scope(
        self,
        name: str,
        scope: PipelineScope,
        *,
        delete_screening_log: bool = False,
        screening_log: ScreeningLogFactory | None = None,
    ) -> PipelineDeletion:
        """Delete pipeline + history from a specific scope, YAML last."""
        screening_db = self._scope_root(scope) / "pipeline_screening" / f"{name}.sqlite3"
        had_log = screening_db.is_file()
        removed_log = self._remove_screening_log(
            name, screening_db, delete_screening_log=delete_screening_log, screening_log=screening_log
        )
        log_note = "its screening log was removed, but " if had_log else ""
        pipelines_dir = self._pipelines_dir_for(scope)
        runs_dir = self._runs_dir_for(scope) / name

        run_count = 0
        try:
            artifacts_dir = self._artifacts_dir_for(scope) / name
            if artifacts_dir.is_dir() and not artifacts_dir.is_symlink():
                shutil.rmtree(artifacts_dir)
            if runs_dir.exists():
                for f in runs_dir.iterdir():
                    if f.is_dir() and not f.is_symlink():
                        shutil.rmtree(f)
                        continue
                    if f.suffix == ".json":
                        run_count += 1
                    f.unlink()
                runs_dir.rmdir()
            # The YAML goes last: until it is gone the pipeline still exists and
            # a retried deletion finds whatever is left.
            yaml_path = pipelines_dir / f"{name}.yaml"
            if yaml_path.exists():
                yaml_path.unlink()
        except OSError as exc:
            msg = (
                f"Pipeline '{name}' was only partly deleted: {log_note}some of its files are in use "
                f"({type(exc).__name__}). The pipeline still exists; retry delete_pipeline to finish."
            )
            raise PipelineDeletionError(msg) from exc

        # Update index
        index = self._load_index(scope)
        index.pop(name, None)
        self._save_index(scope, index)
        self.delete_schedule(name)

        logger.info("Deleted one pipeline from %s scope (%d runs)", scope.value, run_count)
        return PipelineDeletion(scope=scope, run_count=run_count, screening_log=removed_log)

    # ── Schedule Persistence ────────────────────────────────────────────

    @synchronized
    def save_schedule(self, entry: ScheduleEntry) -> None:
        """Persist schedule metadata in the global schedules index."""
        pipeline_name = self._validate_name(entry.pipeline_name)
        schedules = self._load_schedules()
        schedules[pipeline_name] = entry
        self._save_schedules(schedules)

    @synchronized
    def get_schedule(self, name: str) -> ScheduleEntry | None:
        """Get persisted schedule metadata for one pipeline."""
        return self._load_schedules().get(self._validate_name(name))

    @synchronized
    def list_schedules(self) -> list[ScheduleEntry]:
        """List all persisted schedules."""
        schedules = list(self._load_schedules().values())
        schedules.sort(
            key=lambda entry: ((entry.next_run or datetime.max.replace(tzinfo=timezone.utc)), entry.pipeline_name)
        )
        return schedules

    @synchronized
    def delete_schedule(self, name: str) -> bool:
        """Delete persisted schedule metadata if present."""
        normalized_name = self._validate_name(name)
        schedules = self._load_schedules()
        removed = schedules.pop(normalized_name, None)
        if removed is None:
            return False
        self._save_schedules(schedules)
        return True

    @synchronized
    def record_schedule_run(
        self,
        name: str,
        *,
        last_run: datetime | None,
        last_status: Literal["scheduled", "success", "partial", "error"],
        last_error: str | None,
        next_run: datetime | None,
        last_run_id: str | None = None,
        last_new_count: int = 0,
        last_removed_count: int = 0,
    ) -> None:
        """Update run status atomically without recreating a removed schedule."""
        name = self._validate_name(name)
        schedules = self._load_schedules()
        current = schedules.get(name)
        if current is None:
            return
        current.last_run = last_run
        current.last_status = last_status
        current.last_error = last_error
        current.next_run = next_run
        current.last_run_id = last_run_id if current.notify else None
        current.last_new_count = last_new_count if current.notify and last_status in {"success", "partial"} else 0
        current.last_removed_count = last_removed_count if current.notify and last_status == "success" else 0
        self._save_schedules(schedules)

    def _load_schedules(self) -> dict[str, ScheduleEntry]:
        """Load persisted schedule metadata from disk."""
        path = self._global_schedules_path
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to load pipeline schedules; starting fresh")
            return {}
        schedules: dict[str, ScheduleEntry] = {}
        if not isinstance(data, dict):
            logger.warning("Schedule index is not a JSON object")
            return schedules
        for name, raw_entry in data.items():
            try:
                canonical_name = self._validate_name(name)
                entry = ScheduleEntry.from_dict(raw_entry)
                if entry.pipeline_name != canonical_name:
                    logger.warning("Dropping schedule entry whose pipeline name does not match its key")
                    continue
                schedules[canonical_name] = entry
            except (AttributeError, TypeError, ValueError):
                logger.warning("Dropping malformed pipeline schedule entry")
        return schedules

    def _save_schedules(self, schedules: dict[str, ScheduleEntry]) -> None:
        """Persist schedule metadata to disk."""
        path = self._global_schedules_path
        data = {name: entry.to_dict() for name, entry in schedules.items()}
        atomic_write_json(path, data)

    # ── Run History ──────────────────────────────────────────────────────

    @synchronized
    def save_run(self, name: str, run: PipelineRun) -> None:
        """Save an execution record for a pipeline."""
        name = self._validate_name(name)
        run_id = self._validate_run_id(run.run_id)
        # Find which scope the pipeline lives in
        scope = self._find_pipeline_scope(name)
        runs_dir = self._runs_dir_for(scope) / name
        runs_dir.mkdir(parents=True, exist_ok=True)

        # Load before publishing so index reconstruction cannot count this run twice.
        index = self._load_index(scope)
        run_path = runs_dir / f"{run_id}.json"
        is_new = not run_path.exists()
        atomic_write_json(run_path, run.to_dict())

        # Replacing an existing run is not another execution.
        if name in index:
            index[name].run_count += int(is_new)
            self._save_index(scope, index)

        # Prune old history (in the scope this run was written to)
        self._prune_history(runs_dir, scope)

        logger.info("Saved one pipeline run")

    @synchronized
    def get_history(self, name: str, limit: int = 5) -> list[PipelineRun]:
        """Get execution history for a pipeline.

        Returns:
            List of PipelineRun, newest first.
        """
        name = self._validate_name(name)
        scope = self._find_pipeline_scope(name)
        runs_dir = self._runs_dir_for(scope) / name

        if not runs_dir.exists() or limit <= 0:
            return []

        # Load all run files, sorted by name (timestamp-based) descending
        run_files = sorted(runs_dir.glob("*.json"), reverse=True)

        runs: list[PipelineRun] = []
        for f in run_files[:limit]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                runs.append(PipelineRun.from_dict(data))
            except Exception as exc:
                logger.warning("Failed to load a pipeline run record (%s)", type(exc).__name__)
                raise PipelineHistoryError(
                    "Pipeline run history is unavailable because a stored record is invalid"
                ) from exc

        return runs

    @synchronized
    def get_latest_run(self, name: str, *, successful_only: bool = False) -> PipelineRun | None:
        """Get the latest run, optionally requiring a complete comparison baseline."""
        history = self.get_history(name, limit=_MAX_HISTORY if successful_only else 1)
        return next((run for run in history if not successful_only or run.status == "success"), None)

    @synchronized
    def count_history(self, name: str) -> int:
        """Count persisted execution records without exposing store paths."""
        normalized_name = self._validate_name(name)
        scope = self._find_pipeline_scope(normalized_name)
        runs_dir = self._runs_dir_for(scope) / normalized_name
        if not runs_dir.exists():
            return 0
        return sum(1 for path in runs_dir.glob("*.json") if path.is_file())

    def _find_pipeline_scope(self, name: str) -> PipelineScope:
        """Find which scope a pipeline lives in (always the pinned scope for a pinned view)."""
        name = self._validate_name(name)
        if self._pinned_scope is not None:
            return self._pinned_scope
        for scope in self._lookup_scopes():
            if (self._pipelines_dir_for(scope) / f"{name}.yaml").exists():
                return scope

        # Default to global if not found (e.g., for creating runs before save)
        return PipelineScope.GLOBAL

    def _prune_history(self, runs_dir: Path, scope: PipelineScope) -> None:
        """Keep only the most recent _MAX_HISTORY runs (and their record artifacts) of one scope."""
        run_files = sorted(runs_dir.glob("*.json"))
        if len(run_files) > _MAX_HISTORY:
            artifacts_dir = self._artifacts_dir_for(scope) / runs_dir.name
            for f in run_files[: len(run_files) - _MAX_HISTORY]:
                f.unlink()
                pruned_artifacts = artifacts_dir / f.stem
                if pruned_artifacts.is_dir() and not pruned_artifacts.is_symlink():
                    shutil.rmtree(pruned_artifacts)

    # ── Run record artifacts ─────────────────────────────────────────────

    def _scope_root(self, scope: PipelineScope) -> Path:
        if scope == PipelineScope.WORKSPACE:
            if not self._workspace_dir:
                msg = "No workspace directory configured"
                raise RuntimeError(msg)
            return self._workspace_dir / ".pubmed-search"
        return self._global_dir

    def _artifacts_dir_for(self, scope: PipelineScope) -> Path:
        return self._scope_root(scope) / "pipeline_artifacts"

    def screening_db_path(self, name: str) -> Path:
        """Return the screening-log database path for one saved pipeline."""
        name = self._validate_name(name)
        return self._scope_root(self._find_pipeline_scope(name)) / "pipeline_screening" / f"{name}.sqlite3"

    def scope_data_dir(self, name: str) -> Path:
        """Return the data root of the scope that owns ``name`` (for sibling stores)."""
        return self._scope_root(self._find_pipeline_scope(self._validate_name(name)))

    def _run_records_path(self, name: str, run_id: str) -> Path:
        name = self._validate_name(name)
        run_id = self._validate_run_id(run_id)
        scope = self._find_pipeline_scope(name)
        return self._artifacts_dir_for(scope) / name / run_id / _RUN_RECORDS_FILE

    @synchronized
    def save_run_records(self, name: str, run_id: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Persist the complete record set of one run as JSON Lines.

        Each line is one record keyed by ``pmid``; provider-native metadata is
        stored verbatim so exports use the same fields as ``prepare_export``.
        Returns a logical, host-path-free locator for the run record.
        """
        path = self._run_records_path(name, run_id)
        lines: list[str] = []
        for record in records:
            pmid = str(record.get("pmid") or "").strip()
            if not pmid.isdigit():
                msg = "Every run record must carry a canonical PMID"
                raise ValueError(msg)
            lines.append(json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str))
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))
        return {
            "kind": "pipeline_run_records",
            "format": "jsonl",
            "locator": f"pipeline_artifacts/{self._validate_name(name)}/{self._validate_run_id(run_id)}/{_RUN_RECORDS_FILE}",
            "scope": self._find_pipeline_scope(name).value,
            "count": len(lines),
        }

    @synchronized
    def load_run_records(self, name: str, run_id: str) -> list[dict[str, Any]]:
        """Load every persisted record of one run, in stored order."""
        path = self._run_records_path(name, run_id)
        if not path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or not str(row.get("pmid") or "").isdigit():
                msg = "Pipeline run record artifact is invalid"
                raise PipelineHistoryError(msg)
            rows.append(row)
        return rows

    @synchronized
    def get_run(self, name: str, run_id: str | None = None) -> PipelineRun:
        """Load one run by ID, or the newest run when ``run_id`` is omitted."""
        name = self._validate_name(name)
        if run_id is None:
            latest = self.get_history(name, limit=1)
            if not latest:
                msg = f"Pipeline '{name}' has no execution history"
                raise FileNotFoundError(msg)
            return latest[0]
        run_id = self._validate_run_id(run_id)
        path = self._runs_dir_for(self._find_pipeline_scope(name)) / name / f"{run_id}.json"
        if not path.is_file():
            msg = f"Pipeline run '{run_id}' was not found"
            raise FileNotFoundError(msg)
        try:
            return PipelineRun.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:
            raise PipelineHistoryError(
                "Pipeline run history is unavailable because a stored record is invalid"
            ) from exc

    # ── Utility ──────────────────────────────────────────────────────────

    @synchronized
    def save_report(
        self,
        name: str,
        run_id: str,
        report_markdown: str,
    ) -> Path:
        """Save a pipeline execution report as Markdown alongside the run record.

        The report is saved to:
        - Workspace: {workspace}/.pubmed-search/pipeline_reports/{name}/{run_id}.md
        - Global:    ~/.pubmed-search-mcp/pipeline_reports/{name}/{run_id}.md

        Returns:
            Path to the saved report file.
        """
        name = self._validate_name(name)
        run_id = self._validate_run_id(run_id)
        scope = self._find_pipeline_scope(name)
        reports_dir = self._reports_dir_for(scope) / name
        reports_dir.mkdir(parents=True, exist_ok=True)

        report_path = reports_dir / f"{run_id}.md"
        atomic_write_text(report_path, report_markdown)

        logger.info("Saved one pipeline run report")
        return report_path

    def _reports_dir_for(self, scope: PipelineScope) -> Path:
        """Get the reports directory for a specific scope."""
        if scope == PipelineScope.WORKSPACE:
            if not self._workspace_dir:
                msg = "Workspace reports requested but no workspace directory is configured"
                raise RuntimeError(msg)
            return self._workspace_dir / ".pubmed-search" / "pipeline_reports"
        return self._global_dir / "pipeline_reports"

    @synchronized
    def exists(self, name: str) -> bool:
        """Check if a pipeline exists in any scope (only the pinned scope for a pinned view)."""
        name = self._validate_name(name)
        return any((self._pipelines_dir_for(scope) / f"{name}.yaml").exists() for scope in self._lookup_scopes())

    @synchronized
    def shadowed_scopes(self, name: str) -> list[PipelineScope]:
        """Return every scope that holds ``name`` when more than one does (workspace wins)."""
        name = self._validate_name(name)
        scopes = [PipelineScope.WORKSPACE, PipelineScope.GLOBAL] if self._workspace_dir else [PipelineScope.GLOBAL]
        present = [scope for scope in scopes if (self._pipelines_dir_for(scope) / f"{name}.yaml").exists()]
        return present if len(present) > 1 else []

    @synchronized
    def create_run_id(self, name: str, started: datetime | None = None) -> str:
        """Create a collision-resistant run id for persisted pipeline artifacts.

        Run history and reports are both keyed by ``run_id`` on disk. Using only
        second-level timestamps can overwrite artifacts when multiple executions
        begin in the same second, so this method uses microseconds and checks the
        target directories before returning.
        """
        normalized_name = self._validate_name(name)
        started_at = started or datetime.now(timezone.utc)
        base_run_id = f"{started_at.strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:12]}"
        scope = self._find_pipeline_scope(normalized_name)
        runs_dir = self._runs_dir_for(scope) / normalized_name
        reports_dir = self._reports_dir_for(scope) / normalized_name

        candidate = base_run_id
        suffix = 1
        while (runs_dir / f"{candidate}.json").exists() or (reports_dir / f"{candidate}.md").exists():
            candidate = f"{base_run_id}_{suffix:02d}"
            suffix += 1

        return candidate
