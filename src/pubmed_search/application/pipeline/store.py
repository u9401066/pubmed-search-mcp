"""
PipelineStore — Dual-scope CRUD for pipeline configurations.

Storage model:
- Workspace scope: {workspace}/.pubmed-search/pipelines/{name}.yaml
- Global scope:    ~/.pubmed-search-mcp/pipelines/{name}.yaml

Resolution order: workspace → global (load), auto-detect (save).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from pubmed_search.application.pipeline.validator import (
    compute_config_hash,
    parse_and_validate_config,
    validate_and_fix,
    validate_pipeline_name,
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
_SAFE_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

# MCP SDK v2 runs synchronous tools in AnyIO worker threads. Pipeline metadata
# uses read-modify-write JSON transactions, so every store instance in this
# process must share one re-entrant transaction boundary. Service deployments
# intentionally remain single-process/single-replica until this file storage is
# replaced with a transactional shared backend.
_PIPELINE_PERSISTENCE_LOCK = threading.RLock()


def _config_to_dict(config: PipelineConfig) -> dict[str, Any]:
    """Convert PipelineConfig to a serializable dict."""
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
    if out.format != "markdown" or out.limit != 20 or out.ranking != "balanced":
        data["output"] = {}
        if out.format != "markdown":
            data["output"]["format"] = out.format
        if out.limit != 20:
            data["output"]["limit"] = out.limit
        if out.ranking != "balanced":
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

        # Ensure directories exist
        self._global_pipelines_dir.mkdir(parents=True, exist_ok=True)
        self._global_runs_dir.mkdir(parents=True, exist_ok=True)

        if self._workspace_dir:
            self._workspace_pipelines_dir.mkdir(parents=True, exist_ok=True)
            self._workspace_runs_dir.mkdir(parents=True, exist_ok=True)

    def rebased(self, global_data_dir: str | Path) -> PipelineStore:
        """Return an equivalent store rooted at a different global directory.

        Used to give each tenant its own global pipeline scope. The derived
        store deliberately has no workspace scope: a checkout-wide workspace
        directory is shared state and therefore cannot belong to one tenant.

        Args:
            global_data_dir: New global data directory for the derived store.

        Returns:
            A new :class:`PipelineStore` sharing this store's workspace scope.
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
                    logger.warning("Pipeline index at %s is not a JSON object; rebuilding", path)
                    dirty = True
                else:
                    for name, meta in data.items():
                        try:
                            index[name] = PipelineMeta.from_dict(meta)
                        except (AttributeError, TypeError, ValueError):
                            logger.warning("Dropping malformed pipeline index entry %s from %s", name, path)
                            dirty = True
            except (OSError, TypeError, ValueError):
                logger.warning("Failed to load index at %s; rebuilding from pipeline files", path)
                dirty = True

        pipelines_dir = self._pipelines_dir_for(scope)
        yaml_names = {candidate.stem for candidate in pipelines_dir.glob("*.yaml") if candidate.is_file()}

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
            raw_text = path.read_text(encoding="utf-8")
            if contains_credential_material(raw_text):
                return None
            raw_data = yaml.safe_load(raw_text)
            if not isinstance(raw_data, dict):
                return None
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
        except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
            logger.warning("Unable to rebuild pipeline metadata (%s)", type(exc).__name__)
            return None

    def _save_index(self, scope: PipelineScope, index: dict[str, PipelineMeta]) -> None:
        """Save the metadata index for a scope."""
        path = self._index_path_for(scope)
        data = {name: meta.to_dict() for name, meta in index.items()}
        atomic_write_json(path, data)

    @staticmethod
    def _normalize_name(name: str, *, allow_saved_prefix: bool = False) -> str:
        """Return one filesystem-safe pipeline name for every CRUD path."""
        candidate = name.strip().lower()
        if allow_saved_prefix:
            candidate = candidate.removeprefix("saved:")
        if "/" in candidate or "\\" in candidate or re.match(r"^[a-z]:", candidate):
            msg = f"Unsafe pipeline name: {name}"
            raise ValueError(msg)
        normalized, _ = validate_pipeline_name(candidate)
        return normalized

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

        Validates + auto-fixes the config before saving.

        Args:
            name: Pipeline name (will be normalized).
            config: Pipeline configuration.
            tags: Optional tags.
            description: Optional description.
            scope: "workspace", "global", or "auto".

        Returns:
            (PipelineMeta, ValidationResult) — metadata + any fixes applied.

        Raises:
            ValueError: If name is invalid or config has unfixable errors.
        """
        # Normalize name
        if "/" in name or "\\" in name or re.match(r"^[a-zA-Z]:", name.strip()):
            msg = f"Unsafe pipeline name: {name}"
            raise ValueError(msg)
        name, name_fixes = validate_pipeline_name(name)

        # Validate + auto-fix config
        result = validate_and_fix(config)
        result.fixes = name_fixes + result.fixes

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
        atomic_write_text(
            yaml_path,
            yaml.dump(config_dict, allow_unicode=True, default_flow_style=False, sort_keys=False),
        )

        # Update index
        now = datetime.now(timezone.utc)

        existing = index.get(name)
        meta = PipelineMeta(
            name=name,
            scope=resolved_scope,
            description=description,
            tags=tags or [],
            config_hash=compute_config_hash(config),
            step_count=len(config.steps) if config.steps else 0,
            created=existing.created if existing else now,
            updated=now,
            run_count=existing.run_count if existing else 0,
        )
        index[name] = meta
        self._save_index(resolved_scope, index)

        logger.info("Saved pipeline '%s' to %s scope", name, resolved_scope.value)
        return meta, result

    @synchronized
    def load(self, name: str) -> tuple[PipelineConfig, PipelineMeta]:
        """Load a pipeline by name (workspace → global fallback).

        Returns:
            (PipelineConfig, PipelineMeta)

        Raises:
            FileNotFoundError: If pipeline not found in any scope.
        """
        name = self._normalize_name(name, allow_saved_prefix=True)

        # Try workspace first
        if self._workspace_dir:
            ws_path = self._workspace_pipelines_dir / f"{name}.yaml"
            if ws_path.exists():
                return self._load_from_file(ws_path, PipelineScope.WORKSPACE, name)

        # Then global
        global_path = self._global_pipelines_dir / f"{name}.yaml"
        if global_path.exists():
            return self._load_from_file(global_path, PipelineScope.GLOBAL, name)

        msg = (
            f"Pipeline '{name}' not found. "
            f"Searched: workspace (.pubmed-search/pipelines/) and "
            f"global (~/.pubmed-search-mcp/pipelines/)"
        )
        raise FileNotFoundError(msg)

    def _load_from_file(self, path: Path, scope: PipelineScope, name: str) -> tuple[PipelineConfig, PipelineMeta]:
        """Load and validate a pipeline from a YAML file."""
        raw_text = path.read_text(encoding="utf-8")
        if contains_credential_material(raw_text):
            msg = "Pipeline config contains credential material; use server environment configuration instead"
            raise ValueError(msg)
        raw_data = yaml.safe_load(raw_text)

        if not isinstance(raw_data, dict):
            msg = f"Pipeline file '{path}' is not a valid YAML dict"
            raise ValueError(msg)  # noqa: TRY004 — malformed YAML content, not type error

        result = parse_and_validate_config(raw_data)

        if not result.valid:
            msg = f"Pipeline '{name}' has unfixable errors: {'; '.join(result.errors)}"
            raise ValueError(msg)

        config = result.config
        if config is None:
            msg = f"Pipeline '{name}' parsed but no config returned"
            raise ValueError(msg)

        if result.has_fixes:
            # Auto-save fixes back to file
            logger.info(
                "Auto-fixed %d issue(s) in pipeline '%s': %s",
                len(result.fixes),
                name,
                result.summary(),
            )
            config_dict = _config_to_dict(config)
            atomic_write_text(
                path,
                yaml.dump(config_dict, allow_unicode=True, default_flow_style=False, sort_keys=False),
            )

        # Get or create metadata
        index = self._load_index(scope)
        meta = index.get(name)
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

        raw_text = filepath.read_text(encoding="utf-8")
        raw_data = yaml.safe_load(raw_text)

        if not isinstance(raw_data, dict):
            msg = f"Pipeline file '{filepath}' is not a valid YAML dict"
            raise ValueError(msg)  # noqa: TRY004 — malformed YAML content, not type error

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
    def delete(self, name: str) -> tuple[PipelineScope, int]:
        """Delete a pipeline and its history.

        Searches workspace first, then global.

        Args:
            name: Pipeline name.

        Returns:
            (scope_where_deleted, run_count_deleted)

        Raises:
            FileNotFoundError: If pipeline not found.
        """
        name = self._normalize_name(name, allow_saved_prefix=True)

        # Try workspace first
        if self._workspace_dir:
            ws_yaml = self._workspace_pipelines_dir / f"{name}.yaml"
            if ws_yaml.exists():
                return self._delete_from_scope(name, PipelineScope.WORKSPACE)

        # Then global
        global_yaml = self._global_pipelines_dir / f"{name}.yaml"
        if global_yaml.exists():
            return self._delete_from_scope(name, PipelineScope.GLOBAL)

        msg = f"Pipeline '{name}' not found"
        raise FileNotFoundError(msg)

    def _delete_from_scope(self, name: str, scope: PipelineScope) -> tuple[PipelineScope, int]:
        """Delete pipeline + history from a specific scope."""
        pipelines_dir = self._pipelines_dir_for(scope)
        runs_dir = self._runs_dir_for(scope) / name

        # Remove YAML file
        yaml_path = pipelines_dir / f"{name}.yaml"
        if yaml_path.exists():
            yaml_path.unlink()

        # Remove run history
        run_count = 0
        if runs_dir.exists():
            for f in runs_dir.iterdir():
                f.unlink()
                run_count += 1
            runs_dir.rmdir()

        # Update index
        index = self._load_index(scope)
        index.pop(name, None)
        self._save_index(scope, index)
        self.delete_schedule(name)

        logger.info("Deleted pipeline '%s' from %s scope (%d runs)", name, scope.value, run_count)
        return scope, run_count

    # ── Schedule Persistence ────────────────────────────────────────────

    @synchronized
    def save_schedule(self, entry: ScheduleEntry) -> None:
        """Persist schedule metadata in the global schedules index."""
        normalized_name = self._normalize_name(entry.pipeline_name, allow_saved_prefix=True)
        if normalized_name != entry.pipeline_name:
            entry = replace(entry, pipeline_name=normalized_name)
        schedules = self._load_schedules()
        schedules[entry.pipeline_name] = entry
        self._save_schedules(schedules)

    @synchronized
    def get_schedule(self, name: str) -> ScheduleEntry | None:
        """Get persisted schedule metadata for one pipeline."""
        return self._load_schedules().get(self._normalize_name(name, allow_saved_prefix=True))

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
        normalized_name = self._normalize_name(name, allow_saved_prefix=True)
        schedules = self._load_schedules()
        removed = schedules.pop(normalized_name, None)
        if removed is None:
            return False
        self._save_schedules(schedules)
        return True

    def _load_schedules(self) -> dict[str, ScheduleEntry]:
        """Load persisted schedule metadata from disk."""
        path = self._global_schedules_path
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to load schedules at %s, starting fresh", path)
            return {}
        return {name: ScheduleEntry.from_dict(entry) for name, entry in data.items()}

    def _save_schedules(self, schedules: dict[str, ScheduleEntry]) -> None:
        """Persist schedule metadata to disk."""
        path = self._global_schedules_path
        data = {name: entry.to_dict() for name, entry in schedules.items()}
        atomic_write_json(path, data)

    # ── Run History ──────────────────────────────────────────────────────

    @synchronized
    def save_run(self, name: str, run: PipelineRun) -> None:
        """Save an execution record for a pipeline."""
        name = self._normalize_name(name, allow_saved_prefix=True)
        run_id = self._validate_run_id(run.run_id)
        # Find which scope the pipeline lives in
        scope = self._find_pipeline_scope(name)
        runs_dir = self._runs_dir_for(scope) / name
        runs_dir.mkdir(parents=True, exist_ok=True)

        # Save run record
        run_path = runs_dir / f"{run_id}.json"
        atomic_write_json(run_path, run.to_dict())

        # Update run count in index
        index = self._load_index(scope)
        if name in index:
            index[name].run_count += 1
            self._save_index(scope, index)

        # Prune old history
        self._prune_history(runs_dir)

        logger.info("Saved run '%s' for pipeline '%s'", run.run_id, name)

    @synchronized
    def get_history(self, name: str, limit: int = 5) -> list[PipelineRun]:
        """Get execution history for a pipeline.

        Returns:
            List of PipelineRun, newest first.
        """
        name = self._normalize_name(name, allow_saved_prefix=True)
        scope = self._find_pipeline_scope(name)
        runs_dir = self._runs_dir_for(scope) / name

        if not runs_dir.exists():
            return []

        # Load all run files, sorted by name (timestamp-based) descending
        run_files = sorted(runs_dir.glob("*.json"), reverse=True)

        runs: list[PipelineRun] = []
        for f in run_files[:limit]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                runs.append(PipelineRun.from_dict(data))
            except Exception:
                logger.warning("Failed to load run file %s", f)

        return runs

    @synchronized
    def get_latest_run(self, name: str) -> PipelineRun | None:
        """Get the most recent execution for a pipeline."""
        history = self.get_history(name, limit=1)
        return history[0] if history else None

    @synchronized
    def count_history(self, name: str) -> int:
        """Count persisted execution records without exposing store paths."""
        normalized_name = self._normalize_name(name, allow_saved_prefix=True)
        scope = self._find_pipeline_scope(normalized_name)
        runs_dir = self._runs_dir_for(scope) / normalized_name
        if not runs_dir.exists():
            return 0
        return sum(1 for path in runs_dir.glob("*.json") if path.is_file())

    def _find_pipeline_scope(self, name: str) -> PipelineScope:
        """Find which scope a pipeline lives in."""
        name = self._normalize_name(name, allow_saved_prefix=True)
        if self._workspace_dir:
            ws_path = self._workspace_pipelines_dir / f"{name}.yaml"
            if ws_path.exists():
                return PipelineScope.WORKSPACE

        global_path = self._global_pipelines_dir / f"{name}.yaml"
        if global_path.exists():
            return PipelineScope.GLOBAL

        # Default to global if not found (e.g., for creating runs before save)
        return PipelineScope.GLOBAL

    def _prune_history(self, runs_dir: Path) -> None:
        """Keep only the most recent _MAX_HISTORY runs."""
        run_files = sorted(runs_dir.glob("*.json"))
        if len(run_files) > _MAX_HISTORY:
            for f in run_files[: len(run_files) - _MAX_HISTORY]:
                f.unlink()

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
        name = self._normalize_name(name, allow_saved_prefix=True)
        run_id = self._validate_run_id(run_id)
        scope = self._find_pipeline_scope(name)
        reports_dir = self._reports_dir_for(scope) / name
        reports_dir.mkdir(parents=True, exist_ok=True)

        report_path = reports_dir / f"{run_id}.md"
        atomic_write_text(report_path, report_markdown)

        logger.info("Saved report for pipeline '%s' run '%s' at %s", name, run_id, report_path)
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
        """Check if a pipeline exists in any scope."""
        name = self._normalize_name(name, allow_saved_prefix=True)
        if self._workspace_dir and (self._workspace_pipelines_dir / f"{name}.yaml").exists():
            return True
        return (self._global_pipelines_dir / f"{name}.yaml").exists()

    @synchronized
    def create_run_id(self, name: str, started: datetime | None = None) -> str:
        """Create a collision-resistant run id for persisted pipeline artifacts.

        Run history and reports are both keyed by ``run_id`` on disk. Using only
        second-level timestamps can overwrite artifacts when multiple executions
        begin in the same second, so this method uses microseconds and checks the
        target directories before returning.
        """
        normalized_name = self._normalize_name(name, allow_saved_prefix=True)
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
