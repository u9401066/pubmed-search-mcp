"""
Pipeline Tools — MCP tools for pipeline persistence & management.

Single-purpose tools:
- save_pipeline: Save a pipeline configuration for reuse
- list_pipelines: List all saved pipeline configurations
- load_pipeline: Load a pipeline from name, file, or URL
- delete_pipeline: Delete a saved pipeline configuration
- get_pipeline_history: Get execution history for a pipeline
- schedule_pipeline: Schedule a saved pipeline for periodic execution
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field

from pubmed_search.application.pipeline.config_parser import (
    MAX_PIPELINE_CONFIG_CHARS,
    parse_pipeline_config_text,
)
from pubmed_search.application.pipeline.prisma_s import (
    render_prisma_s_csv,
    render_prisma_s_markdown,
    strategy_fingerprint,
)
from pubmed_search.application.pipeline.store import (
    PipelineDeletionError,
    PipelineHistoryError,
    ScreeningLogPresentError,
    _config_to_dict,
)
from pubmed_search.application.pipeline.validator import (
    MAX_PIPELINE_TAGS,
    PIPELINE_NAME_PATTERN,
    PIPELINE_TAG_PATTERN,
    parse_and_validate_config,
    validate_pipeline_name,
    validate_pipeline_tags,
)
from pubmed_search.presentation.mcp_server.tenancy import durable_storage_denied
from pubmed_search.presentation.mcp_server.tools._common import ResponseFormatter
from pubmed_search.shared.tenancy import DEFAULT_TENANT_ID, current_tenant, current_tenant_id, tenant_data_dir

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from pubmed_search.application.pipeline.store import PipelineStore
    from pubmed_search.domain.entities.pipeline import PipelineRun
    from pubmed_search.infrastructure.scheduling import APSPipelineScheduler

logger = logging.getLogger(__name__)

PipelineName = Annotated[str, Field(strict=True, min_length=1, max_length=64, pattern=PIPELINE_NAME_PATTERN)]
PipelineTag = Annotated[str, Field(strict=True, min_length=1, max_length=64, pattern=PIPELINE_TAG_PATTERN)]
PipelineTags = Annotated[list[PipelineTag], Field(max_length=MAX_PIPELINE_TAGS)]
PipelineConfigText = Annotated[str, Field(min_length=1, max_length=MAX_PIPELINE_CONFIG_CHARS)]
PipelineSource = Annotated[str, Field(min_length=1, max_length=4096)]
SaveScope = Literal["auto", "workspace", "global"]
ListScope = Literal["", "workspace", "global"]
CronExpression = Annotated[str, Field(strict=True, min_length=1, max_length=200)]
RunId = Annotated[str, Field(strict=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]
HistoryView = Literal["runs", "records", "run", "prisma_s"]
MAX_PRISMA_S_RUNS = 20


@dataclass(slots=True)
class PipelineToolRuntime:
    """Server-scoped pipeline dependencies plus request-time tenant routing.

    Every MCP server owns one runtime.  Registered tool closures retain that
    exact instance, so constructing another server in the same process cannot
    replace its store, scheduler, or derived tenant-store cache.
    """

    base_store: PipelineStore | None
    scheduler: APSPipelineScheduler | None = None
    _tenant_stores: dict[str, PipelineStore] = field(default_factory=dict, init=False, repr=False)
    _tenant_stores_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def store_for_current_tenant(self) -> PipelineStore | None:
        """Resolve this server's store for the tenant bound to the request."""
        base = self.base_store
        if base is None:
            return None

        tenant_id = current_tenant_id()
        if tenant_id == DEFAULT_TENANT_ID:
            return base

        root = tenant_data_dir(base.global_data_dir)
        if root is None:
            return None

        with self._tenant_stores_lock:
            scoped = self._tenant_stores.get(tenant_id)
            if scoped is None:
                scoped = base.rebased(root)
                self._tenant_stores[tenant_id] = scoped
            return scoped


def _store_unavailable(tool_name: str) -> str:
    """Explain why no pipeline store is available to this caller."""
    return durable_storage_denied(tool_name) or ResponseFormatter.error(
        "Pipeline store not initialized",
        suggestion="Server may not be fully started",
        tool_name=tool_name,
    )


def _save_pipeline_impl(
    *,
    runtime: PipelineToolRuntime,
    tool_name: str,
    name: str,
    config: str,
    tags: list[str] | None = None,
    description: str = "",
    scope: str = "auto",
) -> str:
    store = runtime.store_for_current_tenant()
    if not store:
        return _store_unavailable(tool_name)

    denied = durable_storage_denied(tool_name)
    if denied:
        return denied

    try:
        canonical_name = validate_pipeline_name(name)
        tag_list = validate_pipeline_tags(tags)
        raw_data = parse_pipeline_config_text(config)
    except (TypeError, ValueError) as exc:
        return ResponseFormatter.error(
            str(exc),
            suggestion="Provide a bounded YAML/JSON mapping without aliases, unsafe tags, or credentials",
            tool_name=tool_name,
        )

    result = parse_and_validate_config(raw_data)

    if not result.valid:
        error_msg = "Pipeline config validation failed:\n" + "\n".join(f"  ❌ {e}" for e in result.errors)
        return ResponseFormatter.error(error_msg, tool_name=tool_name)

    pipeline_config = result.config
    if pipeline_config is None:
        return ResponseFormatter.error("Failed to parse pipeline config", tool_name=tool_name)

    try:
        meta, _validation = store.save(
            name=canonical_name,
            config=pipeline_config,
            tags=tag_list,
            description=description,
            scope=scope,
        )
    except ValueError as exc:
        return ResponseFormatter.error(str(exc), tool_name=tool_name)

    parts = [f'✅ Pipeline "{meta.name}" saved successfully.', ""]
    parts.append("📋 Metadata:")
    parts.append(f"  Name: {meta.name}")
    parts.append(f"  Scope: {meta.scope.value}")
    if meta.description:
        parts.append(f"  Description: {meta.description}")
    if meta.tags:
        parts.append(f"  Tags: {', '.join(meta.tags)}")
    if pipeline_config.template:
        parts.append(f"  Template: {pipeline_config.template}")
    elif pipeline_config.steps:
        step_summary = " → ".join(step.action for step in pipeline_config.steps)
        parts.append(f"  Steps: {meta.step_count} ({step_summary})")
    parts.append(f"  Config hash: {meta.config_hash}")

    parts.append("")
    parts.append("💡 Usage:")
    parts.append(f'  • Execute: unified_search(pipeline="saved:{meta.name}")')
    parts.append(f'  • View: load_pipeline(source="{meta.name}")')
    return "\n".join(parts)


def _list_pipelines_impl(
    *,
    runtime: PipelineToolRuntime,
    tool_name: str,
    tag: str = "",
    scope: str = "",
) -> str:
    store = runtime.store_for_current_tenant()
    if not store:
        return _store_unavailable(tool_name)

    pipelines = store.list_pipelines(tag=tag, scope=scope)

    if not pipelines:
        msg = "No saved pipelines found."
        if tag:
            msg += f" (filtered by tag: '{tag}')"
        if scope:
            msg += f" (filtered by scope: '{scope}')"
        return msg + '\n\n💡 Create one: save_pipeline(name="...", config="...")'

    ws_count = sum(1 for pipeline in pipelines if pipeline.scope.value == "workspace")
    gl_count = sum(1 for pipeline in pipelines if pipeline.scope.value == "global")

    scope_desc = []
    if ws_count:
        scope_desc.append(f"{ws_count} workspace")
    if gl_count:
        scope_desc.append(f"{gl_count} global")

    parts = [
        f"📦 Saved Pipelines ({len(pipelines)} total, {' + '.join(scope_desc)}):",
        "",
        "| Name | Scope | Description | Tags | Runs |",
        "|------|-------|-------------|------|------|",
    ]

    for pipeline in pipelines:
        tags_str = ", ".join(pipeline.tags) if pipeline.tags else "-"
        desc = (
            (pipeline.description[:40] + "...")
            if pipeline.description and len(pipeline.description) > 43
            else (pipeline.description or "-")
        )
        parts.append(f"| {pipeline.name} | {pipeline.scope.value} | {desc} | {tags_str} | {pipeline.run_count} |")

    schedules = {entry.pipeline_name: entry for entry in store.list_schedules()}
    for pipeline in pipelines:
        entry = schedules.get(pipeline.name)
        if entry is not None and entry.last_new_count > 0:
            last_run = entry.last_run.isoformat() if entry.last_run else "unknown"
            parts.append("")
            parts.append(
                f"🔔 {entry.last_new_count} new articles in the last scheduled run ({last_run})"
                f' — get_pipeline_history(name="{pipeline.name}")'
            )

    parts.append("")
    parts.append('💡 Load: load_pipeline(source="<name>")')
    parts.append('💡 Execute: unified_search(pipeline="saved:<name>")')
    return "\n".join(parts)


def _load_pipeline_impl(*, runtime: PipelineToolRuntime, tool_name: str, source: str) -> str:
    source = source.strip()
    if source.startswith("file:") and current_tenant().is_authenticated:
        return ResponseFormatter.error(
            "Authenticated service callers cannot read pipeline files from the server filesystem",
            suggestion="Save the pipeline in your tenant store and load it by name",
            example='load_pipeline(source="saved:my_pipeline")',
            tool_name=tool_name,
        )

    store = runtime.store_for_current_tenant()
    if not store:
        return _store_unavailable(tool_name)

    try:
        if source.startswith("file:"):
            filepath = source[5:]
            config, _validation = store.load_from_path(filepath)
            source_type = "file"
            meta = None
        else:
            config, meta = store.load(source)
            source_type = "saved"
    except FileNotFoundError:
        message = (
            "Pipeline file was not found or is not accessible"
            if source.startswith("file:")
            else "Saved pipeline was not found"
        )
        return ResponseFormatter.error(
            message,
            suggestion="Use list_pipelines() to see available pipelines",
            tool_name=tool_name,
        )
    except ValueError as exc:
        return ResponseFormatter.error(str(exc), tool_name=tool_name)

    import yaml

    config_dict = _config_to_dict(config, include_output_defaults=True)
    yaml_str = yaml.safe_dump(config_dict, allow_unicode=True, default_flow_style=False, sort_keys=False)

    parts: list[str] = []
    if meta:
        parts.append(f"📄 Pipeline: {meta.name}")
        parts.append(f"📍 Source: {source_type} ({meta.scope.value})")
        if meta.description:
            parts.append(f"📝 {meta.description}")
        if meta.tags:
            parts.append(f"🏷️ Tags: {', '.join(meta.tags)}")
    else:
        parts.append(f"📄 Pipeline loaded from {source_type}")

    parts.append("")
    parts.append("---")
    parts.append(yaml_str.rstrip())
    parts.append("---")

    parts.append("")
    if meta:
        parts.append(f'💡 Execute: unified_search(pipeline="saved:{meta.name}")')
        parts.append(f'💡 Edit & re-save: save_pipeline(name="{meta.name}", config="<modified yaml>")')
    else:
        parts.append('💡 Execute: unified_search(pipeline="<yaml above>")')
        parts.append('💡 Save: save_pipeline(name="<name>", config="<yaml above>")')

    return "\n".join(parts)


def _screening_decision_summary(store: PipelineStore, name: str) -> dict[str, int] | None:
    """Count screening decisions without creating a log; ``None`` when there is no log."""
    from .pipeline_screening import screening_service

    db_path = store.screening_db_path(name)
    if not isinstance(db_path, Path) or not db_path.is_file():
        return None
    return screening_service(store, name).decision_summary()


def _counted(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _screening_loss(summary: dict[str, Any]) -> str:
    return f"{_counted(summary['decisions'], 'decision')} on {_counted(summary['pmids'], 'PMID')}"


def _screening_log_refusal(tool_name: str, name: str, summary: dict[str, Any]) -> str:
    return ResponseFormatter.error(
        f"Pipeline '{name}' was not deleted: its screening log holds {_screening_loss(summary)} "
        f"from {_counted(summary['reviewers'], 'reviewer label')}, which deletion would permanently destroy. "
        "Nothing was removed.",
        suggestion=(
            "Export the screening log first (page through pipeline_screening log; flow gives PRISMA counts), "
            "then repeat with delete_screening_log=true to delete the pipeline together with its decisions"
        ),
        example=(
            f'pipeline_screening(request={{"action": "log", "pipeline": "{name}", "offset": 0, "limit": 100}}); '
            f'delete_pipeline(name="{name}", delete_screening_log=true)'
        ),
        tool_name=tool_name,
    )


def _delete_pipeline_impl(
    *,
    runtime: PipelineToolRuntime,
    tool_name: str,
    name: str,
    delete_screening_log: bool = False,
) -> str:
    store = runtime.store_for_current_tenant()
    if not store:
        return _store_unavailable(tool_name)

    # Screening decisions are human work: refuse early with counts. The store
    # repeats the check atomically with the deletion, so a decision recorded
    # after this pre-check still blocks it.
    summary: dict[str, int] | None = None
    if store.exists(name):
        try:
            summary = _screening_decision_summary(store, name)
        except (OSError, ValueError, sqlite3.Error) as exc:
            logger.warning("Pipeline screening log could not be inspected before deletion (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                f"Pipeline '{name}' was not deleted: its screening log could not be inspected. Nothing was removed.",
                suggestion="Check data directory availability and retry",
                tool_name=tool_name,
            )
        if summary is not None and summary["decisions"] > 0 and not delete_screening_log:
            return _screening_log_refusal(tool_name, name, summary)

    scheduler = runtime.scheduler if current_tenant_id() == DEFAULT_TENANT_ID else None
    scheduled_entry = None
    if scheduler is not None:
        try:
            scheduled_entry = scheduler.get_schedule(name)
        except Exception as exc:  # Schedule inspection must not block deletion.
            logger.warning("Unable to inspect pipeline schedule before deletion (%s)", type(exc).__name__)

    from .pipeline_screening import screening_log_at

    try:
        # An empty (or opted-in) log goes with the pipeline; decisions without opt-in refuse.
        deletion = store.delete(name, delete_screening_log=delete_screening_log, screening_log=screening_log_at)
    except FileNotFoundError:
        return ResponseFormatter.error(
            f"Pipeline '{name}' not found",
            suggestion="Use list_pipelines() to see available pipelines",
            tool_name=tool_name,
        )
    except ScreeningLogPresentError as exc:
        return _screening_log_refusal(
            tool_name, name, exc.summary or summary or {"decisions": 0, "pmids": 0, "reviewers": 0}
        )
    except PipelineDeletionError as exc:
        logger.warning("Pipeline deletion stopped early (%s)", type(exc.__cause__).__name__)
        return ResponseFormatter.error(
            str(exc),
            suggestion="Retry delete_pipeline once other processes have released the files",
            tool_name=tool_name,
        )
    except OSError as exc:
        logger.warning("Pipeline deletion failed (%s)", type(exc).__name__)
        return ResponseFormatter.error(
            f"Pipeline '{name}' could not be fully deleted ({type(exc).__name__})",
            suggestion="Check data directory availability, then retry delete_pipeline to finish",
            tool_name=tool_name,
        )
    except ValueError as exc:
        return ResponseFormatter.error(str(exc), tool_name=tool_name)
    removed_log = deletion.screening_log or summary

    schedule_cleanup_failed = False
    if scheduler is not None:
        try:
            scheduler.unschedule(name)
        except Exception as exc:  # The pipeline is already deleted; report partial cleanup truthfully.
            schedule_cleanup_failed = True
            logger.warning("Pipeline deleted but live schedule cleanup failed (%s)", type(exc).__name__)

    parts = [f'🗑️ Pipeline "{name}" deleted.']
    parts.append(f"  - Configuration permanently removed (from {deletion.scope.value} scope)")
    parts.append(f"  - {deletion.run_count} execution history record(s) and run record sets permanently removed")
    if removed_log is not None:
        parts.append(f"  - Screening log permanently removed: {_screening_loss(removed_log)}")
    if scheduled_entry is not None and not schedule_cleanup_failed:
        parts.append("  - Process schedule removed")
    if schedule_cleanup_failed:
        parts.append("  - ⚠️ Configuration was deleted, but live schedule cleanup failed; restart the scheduler")
    return "\n".join(parts)


def _history_unavailable(tool_name: str) -> str:
    return ResponseFormatter.error(
        "Pipeline execution history is unavailable because a stored record is invalid",
        suggestion="Repair or remove the invalid run record, then retry",
        tool_name=tool_name,
    )


def _retrieval_cells(run: PipelineRun) -> tuple[str, str]:
    """Return (mode, PubMed total) cells for one run row."""
    retrieval = run.retrieval or {}
    if retrieval.get("mode") in {"exhaustive", "mixed"}:
        if retrieval.get("mode") == "mixed":
            label = "mixed (not exhaustive)"
        else:
            label = "exhaustive" if retrieval.get("exhaustive") else "exhaustive (incomplete)"
        total = retrieval.get("total_count")
        return label, "-" if total is None else str(total)
    if run.record_version >= 2:
        return "bounded", "-"
    return "legacy", "-"


def _render_history_runs(name: str, runs: list[PipelineRun], total_runs: int) -> str:
    parts = [
        f'📊 Execution History for "{name}" (showing {len(runs)} of {total_runs}):',
        "",
        "| # | Run ID | Date (UTC) | Records | Mode | PubMed total | New | Removed | Strategy | Status |",
        "|---|--------|------------|---------|------|--------------|-----|---------|----------|--------|",
    ]

    for index, run in enumerate(runs):
        date_str = run.started.strftime("%Y-%m-%d %H:%M") if run.started else "unknown"
        status_icon = "✅ OK" if run.status == "success" else f"❌ {run.status}"
        new_str = f"+{len(run.new_pmids)}" if run.new_pmids else "+0"
        removed_str = f"-{len(run.removed_pmids)}" if run.removed_pmids else "-0"
        run_num = total_runs - index
        mode, total = _retrieval_cells(run)
        strategy = _strategy_cell(run)
        parts.append(
            f"| {run_num} | `{run.run_id}` | {date_str} | {run.article_count} | {mode} | {total} "
            f"| {new_str} | {removed_str} | {strategy} | {status_icon} |"
        )

    latest = runs[0]
    if latest.new_pmids:
        parts.append("")
        parts.append(f"Latest new articles (run #{total_runs}):")
        for article_index, pmid in enumerate(latest.new_pmids[:5]):
            article_info = next((article for article in latest.top_articles if article.get("pmid") == pmid), None)
            if article_info:
                title = article_info.get("title", "")[:60]
                year = article_info.get("year", "")
                parts.append(f'  {article_index + 1}. PMID {pmid} - "{title}" ({year})')
            else:
                parts.append(f"  {article_index + 1}. PMID {pmid}")

        parts.append("")
        pmid_str = ",".join(latest.new_pmids[:10])
        parts.append(f'💡 Full details: fetch_article_details(pmids="{pmid_str}")')
    if latest.artifacts.get("records"):
        parts.append(
            f'💡 Page the full record set: get_pipeline_history(name="{name}", run_id="{latest.run_id}", '
            'view="records", offset=0, limit=100)'
        )
        parts.append(f'💡 Export for screening: prepare_export(pipeline_run="{name}@{latest.run_id}", format="ris")')
    if len({_strategy_cell(run) for run in runs if run.config_hash}) > 1:
        parts.append("⚠️ These runs used different strategy versions (see the Strategy column).")
    parts.append(f'💡 PRISMA-S search record: get_pipeline_history(name="{name}", view="prisma_s")')

    return "\n".join(parts)


def _strategy_cell(run: PipelineRun) -> str:
    """Config hash plus executed-query fingerprint distinguish strategy versions."""
    if not run.config_hash:
        return "—"
    query_hash = strategy_fingerprint(run)
    return f"`{run.config_hash}`" + (f" / q:`{query_hash[:8]}`" if query_hash else "")


def _render_run_detail(run: PipelineRun) -> str:
    """Return one run's provenance record as JSON (large PMID lists summarized)."""
    payload = run.to_dict()
    for key in ("pmids", "new_pmids", "removed_pmids"):
        values = payload.pop(key)
        payload[f"{key[:-1]}_count" if key == "pmids" else f"{key}_count"] = len(values)
        payload[f"{key}_preview"] = values[:20]
    payload["strategy_fingerprint"] = strategy_fingerprint(run)
    payload["type"] = "pipeline_run"
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _render_prisma_s(name: str, runs: list[PipelineRun], *, truncated: bool) -> str:
    parts = [render_prisma_s_markdown(runs, title=name)]
    if truncated:
        parts.append(
            f"\nShowing the {len(runs)} most recent runs (PRISMA-S view is capped at {MAX_PRISMA_S_RUNS}); "
            "pass run_id for an older run."
        )
    parts.append("\n### CSV\n")
    parts.append("```csv")
    parts.append(render_prisma_s_csv(runs).rstrip("\n"))
    parts.append("```")
    return "\n".join(parts)


def _render_run_records(
    store: PipelineStore,
    name: str,
    run: PipelineRun,
    *,
    offset: int,
    limit: int,
) -> str:
    """Return one bounded JSON page of a run's persisted record set."""
    records = store.load_run_records(name, run.run_id) if run.artifacts.get("records") else []
    if records:
        rows = records[offset : offset + limit]
        page = [
            {
                "pmid": str(row.get("pmid")),
                "title": str(row.get("title") or "")[:300],
                "year": str(row.get("year") or ""),
                "journal": str(row.get("journal") or ""),
                "doi": str(row.get("doi") or ""),
                "metadata_missing": bool(row.get("metadata_missing")),
            }
            for row in rows
        ]
        total = len(records)
    else:
        page = [{"pmid": pmid} for pmid in run.pmids[offset : offset + limit]]
        total = len(run.pmids)
    next_offset = offset + limit if offset + limit < total else None
    return json.dumps(
        {
            "type": "pipeline_run_records",
            "pipeline": name,
            "run_id": run.run_id,
            "record_basis": run.record_basis,
            "retrieval": run.retrieval,
            "total": total,
            "offset": offset,
            "limit": limit,
            "records": page,
            "next_offset": next_offset,
        },
        ensure_ascii=False,
    )


def _get_pipeline_history_impl(
    *,
    runtime: PipelineToolRuntime,
    tool_name: str,
    name: str,
    limit: int = 5,
    run_id: str | None = None,
    view: str = "runs",
    offset: int = 0,
) -> str:
    store = runtime.store_for_current_tenant()
    if not store:
        return _store_unavailable(tool_name)

    if not store.exists(name):
        return ResponseFormatter.error(
            f"Pipeline '{name}' not found",
            suggestion="Use list_pipelines() to see available pipelines",
            tool_name=tool_name,
        )

    if view in {"records", "run"} or (view == "prisma_s" and run_id is not None):
        try:
            run = store.get_run(name, run_id)
        except FileNotFoundError:
            return ResponseFormatter.error(
                "Pipeline run was not found",
                suggestion=f'Use get_pipeline_history(name="{name}") to list run IDs',
                tool_name=tool_name,
            )
        except PipelineHistoryError as exc:
            logger.warning("Pipeline history read failed (%s)", type(exc).__name__)
            return _history_unavailable(tool_name)
        except ValueError as exc:
            return ResponseFormatter.error(str(exc), tool_name=tool_name)
        if view == "run":
            return _render_run_detail(run)
        if view == "prisma_s":
            return _render_prisma_s(name, [run], truncated=False)
        return _render_run_records(store, name, run, offset=offset, limit=limit)

    history_limit = min(limit, MAX_PRISMA_S_RUNS) if view == "prisma_s" else limit
    try:
        runs = store.get_history(name, limit=history_limit)
    except PipelineHistoryError as exc:
        logger.warning("Pipeline history read failed (%s)", type(exc).__name__)
        return _history_unavailable(tool_name)

    if runs and view == "prisma_s":
        return _render_prisma_s(name, runs, truncated=limit > MAX_PRISMA_S_RUNS)
    if not runs:
        return (
            f'📊 Pipeline "{name}" has no execution history yet.\n\n💡 Execute: unified_search(pipeline="saved:{name}")'
        )

    return _render_history_runs(name, runs, store.count_history(name))


def _schedule_pipeline_impl(
    *,
    runtime: PipelineToolRuntime,
    tool_name: str,
    name: str,
    cron: str,
    diff_mode: bool = True,
    notify: bool = True,
) -> str:
    scheduler = runtime.scheduler
    if not scheduler:
        return ResponseFormatter.error(
            "Pipeline scheduler not initialized",
            suggestion="Server may not be fully started",
            tool_name=tool_name,
        )
    if current_tenant_id() != DEFAULT_TENANT_ID:
        # The scheduler is a single process-wide instance bound to the default
        # tenant's store. Scheduling here would run another tenant's pipeline.
        return ResponseFormatter.error(
            "Scheduling is not available for isolated tenants",
            suggestion="Run the pipeline on demand, or schedule it from an external scheduler",
            tool_name=tool_name,
        )

    try:
        pipeline_name = validate_pipeline_name(name)
    except ValueError as exc:
        return ResponseFormatter.error(str(exc), tool_name=tool_name)
    if not cron.strip():
        return ResponseFormatter.error(
            "cron is required when creating or updating a schedule",
            suggestion=f'Use unschedule_pipeline(name="{pipeline_name}") to remove a schedule',
            tool_name=tool_name,
        )

    try:
        entry = scheduler.schedule(
            pipeline_name,
            cron,
            diff_mode=diff_mode,
            notify=notify,
        )
        next_run = entry.next_run.isoformat() if entry.next_run else "pending scheduler startup"
        return "\n".join(
            [
                f'⏰ Schedule set for "{entry.pipeline_name}":',
                f"  Cron: {entry.cron}",
                f"  Timezone: {entry.timezone}",
                f"  Next run: {next_run}",
                f"  Diff mode: {'on' if entry.diff_mode else 'off'}",
                f"  Notify: {'on' if entry.notify else 'off'}",
                "",
                f'💡 Remove: unschedule_pipeline(name="{entry.pipeline_name}")',
                f'💡 History: get_pipeline_history(name="{entry.pipeline_name}")',
            ]
        )
    except FileNotFoundError:
        return ResponseFormatter.error(
            f"Saved pipeline '{pipeline_name}' was not found",
            suggestion="Use list_pipelines() to see available pipelines",
            tool_name=tool_name,
        )
    except ValueError as exc:
        return ResponseFormatter.error(str(exc), tool_name=tool_name)
    except RuntimeError:
        return ResponseFormatter.error(
            "Pipeline scheduler could not create or update the schedule",
            tool_name=tool_name,
        )


def _unschedule_pipeline_impl(*, runtime: PipelineToolRuntime, tool_name: str, name: str) -> str:
    scheduler = runtime.scheduler
    if not scheduler:
        return ResponseFormatter.error(
            "Pipeline scheduler not initialized",
            suggestion="Server may not be fully started",
            tool_name=tool_name,
        )
    if current_tenant_id() != DEFAULT_TENANT_ID:
        return ResponseFormatter.error(
            "Scheduling is not available for isolated tenants",
            suggestion="Manage the schedule from the default local tenant or an external scheduler",
            tool_name=tool_name,
        )

    try:
        pipeline_name = validate_pipeline_name(name)
    except ValueError as exc:
        return ResponseFormatter.error(str(exc), tool_name=tool_name)
    try:
        removed = scheduler.unschedule(pipeline_name)
    except ValueError as exc:
        return ResponseFormatter.error(str(exc), tool_name=tool_name)
    except RuntimeError:
        return ResponseFormatter.error(
            "Pipeline scheduler could not remove the schedule",
            tool_name=tool_name,
        )
    if removed is None:
        return ResponseFormatter.error(
            f"No active schedule found for '{pipeline_name}'",
            suggestion=f'Create one with schedule_pipeline(name="{pipeline_name}", cron="0 9 * * 1")',
            tool_name=tool_name,
        )
    return "\n".join(
        [
            f'🗓️ Schedule removed for "{removed.pipeline_name}".',
            f"  Previous cron: {removed.cron}",
            f"  Last status: {removed.last_status}",
        ]
    )


def register_pipeline_tools(mcp: MCPServer, *, runtime: PipelineToolRuntime) -> None:
    """Register pipeline tools bound to one server-scoped runtime."""

    # ── Tool 1: save_pipeline ────────────────────────────────────────────

    @mcp.tool()
    def save_pipeline(
        name: PipelineName,
        config: PipelineConfigText,
        tags: PipelineTags | None = None,
        description: Annotated[str, Field(max_length=2000)] = "",
        scope: SaveScope = "auto",
    ) -> str:
        """Save a pipeline configuration for later reuse.

        The config format is identical to unified_search's pipeline parameter
        (YAML or JSON). Saved pipelines can be loaded later by name:
            unified_search(pipeline="saved:weekly_remimazolam")

        Args:
            name: Unique identifier (alphanumeric + hyphens/underscores, max 64 chars).
                  Overwrites if name already exists (upsert semantics).
            config: Pipeline YAML/JSON string. Same format as unified_search pipeline param.
            tags: Bounded array of canonical tags (e.g., ["anesthesia", "sedation"]).
            description: Human-readable description of the pipeline's purpose.
            scope: Storage scope - "workspace" (project-level, git-trackable),
                   "global" (user-level, cross-project), or "auto" (workspace if
                   available, otherwise global). Default: "auto".

        Returns:
            Confirmation with pipeline metadata.
        """
        return _save_pipeline_impl(
            runtime=runtime,
            tool_name="save_pipeline",
            name=name,
            config=config,
            tags=tags,
            description=description,
            scope=scope,
        )

    # ── Tool 2: list_pipelines ───────────────────────────────────────────

    @mcp.tool()
    def list_pipelines(
        tag: Annotated[str, Field(max_length=100)] = "",
        scope: ListScope = "",
    ) -> str:
        """List all saved pipeline configurations.

        Args:
            tag: Filter by tag (e.g., "sedation"). Empty = show all.
            scope: Filter by scope: "workspace", "global", or "" (show all).

        Returns:
            Table of saved pipelines with name, scope, description, tags.
        """
        return _list_pipelines_impl(
            runtime=runtime,
            tool_name="list_pipelines",
            tag=tag,
            scope=scope,
        )

    # ── Tool 3: load_pipeline ────────────────────────────────────────────

    @mcp.tool()
    def load_pipeline(
        source: PipelineSource,
    ) -> str:
        """Load a pipeline configuration for review or editing.

        Loads from either source:
        - Saved name: "weekly_remimazolam" or "saved:weekly_remimazolam"
        - Local-only file: "file:path/to/pipeline.yaml" (disabled for authenticated service callers)

        The returned YAML can be reviewed, modified, and then:
        - Executed directly: unified_search(pipeline="<yaml>")
        - Saved with changes: save_pipeline(name="...", config="<yaml>")

        Args:
            source: Pipeline source identifier (see above).

        Returns:
            Full pipeline YAML content + metadata.
        """
        return _load_pipeline_impl(
            runtime=runtime,
            tool_name="load_pipeline",
            source=source,
        )

    # ── Tool 4: delete_pipeline ──────────────────────────────────────────

    @mcp.tool()
    def delete_pipeline(name: PipelineName, delete_screening_log: bool = False) -> str:
        """Permanently delete a saved pipeline and its execution history.

        Run records and their record sets are removed with the pipeline. A
        screening log that holds decisions is human work: deletion is refused
        (nothing is removed) and reports how many decisions/PMIDs would be
        lost, unless delete_screening_log=true. Export the log first with
        pipeline_screening(request={"action":"log", ...}). A log without
        decisions is removed with the pipeline. The decision check is atomic
        with the deletion, so a decision recorded meanwhile still blocks it.
        If a file is locked (for example by another process on Windows),
        deletion stops with the pipeline intact and can simply be retried.

        For the default tenant, any process-level schedule is removed only
        after the stored pipeline deletion succeeds. Isolated tenants never
        mutate the shared process scheduler.

        Args:
            name: Name of the saved pipeline to delete.
            delete_screening_log: Also delete screening decisions recorded for
                this pipeline (default false: refuse when decisions exist).

        Returns:
            Confirmation of deletion, or a refusal that removed nothing.
        """
        return _delete_pipeline_impl(
            runtime=runtime,
            tool_name="delete_pipeline",
            name=name,
            delete_screening_log=delete_screening_log,
        )

    # ── Tool 5: get_pipeline_history ─────────────────────────────────────

    @mcp.tool()
    def get_pipeline_history(
        name: PipelineName,
        limit: Annotated[int, Field(ge=1, le=100)] = 5,
        run_id: RunId | None = None,
        view: HistoryView = "runs",
        offset: Annotated[int, Field(ge=0, le=10_000)] = 0,
    ) -> str:
        """Get execution history, a run's search record, or its persisted record set.

        view="runs" (default) lists recent runs with run ID, record count,
        retrieval mode, PubMed total, new/removed records versus the previous
        comparable run, strategy hash (config hash / executed-query hash) and
        status, so runs from different strategy versions are distinguishable.
        view="run" returns one run's provenance as JSON: database/platform,
        logical and executed queries, PubMed query translation, counts,
        filters, UTC timestamps, server version and the immutable config
        snapshot. view="prisma_s" renders a PRISMA-S search-strategy table
        (Markdown + CSV) for run_id or the latest runs (at most 20).
        view="records" returns one JSON page (offset/limit) of a run's complete
        record set. run_id defaults to the latest run.

        Args:
            name: Name of the saved pipeline.
            limit: Runs to list, or records per page for view="records" (1-100).
            run_id: Run to read (default: latest run).
            view: "runs", "run", "prisma_s", or "records".
            offset: Record offset for view="records".

        Returns:
            Markdown history/PRISMA-S table, or JSON for view="run"/"records".
        """
        return _get_pipeline_history_impl(
            runtime=runtime,
            tool_name="get_pipeline_history",
            name=name,
            limit=limit,
            run_id=run_id,
            view=view,
            offset=offset,
        )

    # ── Tool 6: schedule_pipeline ────────────────────────────────────────

    @mcp.tool()
    def schedule_pipeline(
        name: PipelineName,
        cron: CronExpression,
        diff_mode: bool = True,
        notify: bool = True,
    ) -> str:
        """Schedule a saved pipeline for periodic execution.

        Args:
            name: Saved pipeline name.
            cron: Required 5-field cron expression. Example: "0 9 * * 1" (Mon 9am).
            diff_mode: When True, store diff-mode preference with the schedule.
            notify: When True, store notify preference with the schedule.

        Returns:
            Schedule confirmation or removal result.
        """
        return _schedule_pipeline_impl(
            runtime=runtime,
            tool_name="schedule_pipeline",
            name=name,
            cron=cron,
            diff_mode=diff_mode,
            notify=notify,
        )

    # ── Tool 7: unschedule_pipeline ──────────────────────────────────────

    @mcp.tool()
    def unschedule_pipeline(name: PipelineName) -> str:
        """Remove the active schedule for a saved pipeline.

        Args:
            name: Saved pipeline name whose schedule will be removed.

        Returns:
            Removed schedule metadata, or a native MCP error when none exists.
        """
        return _unschedule_pipeline_impl(runtime=runtime, tool_name="unschedule_pipeline", name=name)
