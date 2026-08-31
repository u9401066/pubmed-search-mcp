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

import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field

from pubmed_search.application.pipeline.config_parser import (
    MAX_PIPELINE_CONFIG_CHARS,
    parse_pipeline_config_text,
)
from pubmed_search.application.pipeline.store import PipelineHistoryError
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

    config_dict = _config_to_display_dict(config)
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


def _delete_pipeline_impl(*, runtime: PipelineToolRuntime, tool_name: str, name: str) -> str:
    store = runtime.store_for_current_tenant()
    if not store:
        return _store_unavailable(tool_name)

    scheduler = runtime.scheduler if current_tenant_id() == DEFAULT_TENANT_ID else None
    scheduled_entry = None
    if scheduler is not None:
        try:
            scheduled_entry = scheduler.get_schedule(name)
        except Exception as exc:  # Schedule inspection must not block deletion.
            logger.warning("Unable to inspect pipeline schedule before deletion (%s)", type(exc).__name__)

    try:
        scope, run_count = store.delete(name)
    except FileNotFoundError:
        return ResponseFormatter.error(
            f"Pipeline '{name}' not found",
            suggestion="Use list_pipelines() to see available pipelines",
            tool_name=tool_name,
        )
    except ValueError as exc:
        return ResponseFormatter.error(str(exc), tool_name=tool_name)

    schedule_cleanup_failed = False
    if scheduler is not None:
        try:
            scheduler.unschedule(name)
        except Exception as exc:  # The pipeline is already deleted; report partial cleanup truthfully.
            schedule_cleanup_failed = True
            logger.warning("Pipeline deleted but live schedule cleanup failed (%s)", type(exc).__name__)

    parts = [f'🗑️ Pipeline "{name}" deleted.']
    parts.append(f"  - Configuration permanently removed (from {scope.value} scope)")
    parts.append(f"  - {run_count} execution history record(s) permanently removed")
    if scheduled_entry is not None:
        parts.append("  - Process schedule removed")
    if schedule_cleanup_failed:
        parts.append("  - ⚠️ Configuration was deleted, but live schedule cleanup failed; restart the scheduler")
    return "\n".join(parts)


def _get_pipeline_history_impl(
    *,
    runtime: PipelineToolRuntime,
    tool_name: str,
    name: str,
    limit: int = 5,
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

    try:
        runs = store.get_history(name, limit=limit)
    except PipelineHistoryError as exc:
        logger.warning("Pipeline history read failed (%s)", type(exc).__name__)
        return ResponseFormatter.error(
            "Pipeline execution history is unavailable because a stored record is invalid",
            suggestion="Repair or remove the invalid run record, then retry",
            tool_name=tool_name,
        )

    if not runs:
        return (
            f'📊 Pipeline "{name}" has no execution history yet.\n\n💡 Execute: unified_search(pipeline="saved:{name}")'
        )

    total_runs = store.count_history(name)

    parts = [
        f'📊 Execution History for "{name}" (showing {len(runs)} of {total_runs}):',
        "",
        "| # | Date | Articles | New | Removed | Status |",
        "|---|------|----------|-----|---------|--------|",
    ]

    for index, run in enumerate(runs):
        date_str = run.started.strftime("%Y-%m-%d %H:%M") if run.started else "unknown"
        status_icon = "✅ OK" if run.status == "success" else f"❌ {run.status}"
        new_str = f"+{len(run.new_pmids)}" if run.new_pmids else "+0"
        removed_str = f"-{len(run.removed_pmids)}" if run.removed_pmids else "-0"
        run_num = total_runs - index
        parts.append(f"| {run_num} | {date_str} | {run.article_count} | {new_str} | {removed_str} | {status_icon} |")

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

    return "\n".join(parts)


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

        Loads from one of three sources:
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
    def delete_pipeline(name: PipelineName) -> str:
        """Permanently delete a saved pipeline configuration and execution history.

        For the default tenant, any process-level schedule is removed only
        after the stored pipeline deletion succeeds. Isolated tenants never
        mutate the shared process scheduler.

        Args:
            name: Name of the saved pipeline to delete.

        Returns:
            Confirmation of deletion.
        """
        return _delete_pipeline_impl(
            runtime=runtime,
            tool_name="delete_pipeline",
            name=name,
        )

    # ── Tool 5: get_pipeline_history ─────────────────────────────────────

    @mcp.tool()
    def get_pipeline_history(
        name: PipelineName,
        limit: Annotated[int, Field(ge=1, le=100)] = 5,
    ) -> str:
        """Get execution history for a saved pipeline.

        Shows past execution results with diff analysis: which articles are new
        compared to the previous run.

        Args:
            name: Name of the saved pipeline.
            limit: Maximum number of history entries to return (default: 5).

        Returns:
            Execution history with date, article count, new/removed articles, status.
        """
        return _get_pipeline_history_impl(
            runtime=runtime,
            tool_name="get_pipeline_history",
            name=name,
            limit=limit,
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


def _config_to_display_dict(config) -> dict:
    """Convert PipelineConfig to a display-friendly dict."""
    data: dict = {}

    if config.name:
        data["name"] = config.name

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

    if getattr(config, "globals", None):
        data["globals"] = config.globals
    if getattr(config, "variables", None):
        data["variables"] = config.variables

    output = config.output
    data["output"] = {
        **({"format": output.format} if output.format != "markdown" else {}),
        "limit": output.limit,
        "ranking": output.ranking,
    }

    return data
