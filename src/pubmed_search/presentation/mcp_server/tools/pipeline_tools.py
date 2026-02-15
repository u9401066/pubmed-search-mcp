"""
Pipeline Tools — MCP tools for pipeline persistence & management.

Tools (Phase 1):
- save_pipeline: Save a pipeline configuration for reuse
- list_pipelines: List all saved pipeline configurations
- load_pipeline: Load a pipeline from name, file, or URL
- delete_pipeline: Delete a saved pipeline configuration

Tools (Phase 3 — stub):
- get_pipeline_history: Get execution history for a pipeline

Tools (Phase 4 — stub):
- schedule_pipeline: Schedule a saved pipeline for periodic execution
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import yaml

from pubmed_search.application.pipeline.validator import parse_and_validate_config
from pubmed_search.presentation.mcp_server.tools._common import ResponseFormatter

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from pubmed_search.application.pipeline.store import PipelineStore

logger = logging.getLogger(__name__)

# Module-level store reference (set by register function)
_pipeline_store: PipelineStore | None = None


def set_pipeline_store(store: PipelineStore) -> None:
    """Set the PipelineStore instance for tools."""
    global _pipeline_store
    _pipeline_store = store


def get_pipeline_store() -> PipelineStore | None:
    """Get the current PipelineStore."""
    return _pipeline_store


def register_pipeline_tools(mcp: FastMCP) -> None:
    """Register all 6 pipeline management MCP tools."""

    # ── Tool 1: save_pipeline ────────────────────────────────────────────

    @mcp.tool()
    def save_pipeline(
        name: str,
        config: str,
        tags: str = "",
        description: str = "",
        scope: str = "auto",
    ) -> str:
        """Save a pipeline configuration for later reuse.

        The config format is identical to unified_search's pipeline parameter
        (YAML or JSON). Saved pipelines can be loaded later by name:
            unified_search(pipeline="saved:weekly_remimazolam")

        Args:
            name: Unique identifier (alphanumeric + hyphens/underscores, max 64 chars).
                  Overwrites if name already exists (upsert semantics).
            config: Pipeline YAML/JSON string. Same format as unified_search pipeline param.
            tags: Comma-separated tags for filtering (e.g., "anesthesia,sedation").
            description: Human-readable description of the pipeline's purpose.
            scope: Storage scope - "workspace" (project-level, git-trackable),
                   "global" (user-level, cross-project), or "auto" (workspace if
                   available, otherwise global). Default: "auto".

        Returns:
            Confirmation with pipeline metadata.
        """
        store = get_pipeline_store()
        if not store:
            return ResponseFormatter.error(
                "Pipeline store not initialized",
                suggestion="Server may not be fully started",
                tool_name="save_pipeline",
            )

        # Parse YAML/JSON config
        try:
            raw_data = yaml.safe_load(config)
            if not isinstance(raw_data, dict):
                return ResponseFormatter.error(
                    "Config must be a YAML or JSON object (dict)",
                    suggestion="Provide a valid pipeline config",
                    example='save_pipeline(name="my_search", config="template: comprehensive\\ntemplate_params:\\n  query: remimazolam")',
                    tool_name="save_pipeline",
                )
        except yaml.YAMLError as exc:
            return ResponseFormatter.error(
                f"Invalid YAML: {exc}",
                suggestion="Check YAML syntax (indentation, colons, quotes)",
                tool_name="save_pipeline",
            )

        # Build PipelineConfig from raw data via validator
        result = parse_and_validate_config(raw_data)

        if not result.valid:
            error_msg = "Pipeline config validation failed:\n" + "\n".join(f"  ❌ {e}" for e in result.errors)
            if result.fixes:
                error_msg += "\n\nAuto-fixes attempted:\n" + "\n".join(
                    f"  🔧 {f.field}: {f.reason}" for f in result.fixes
                )
            return ResponseFormatter.error(error_msg, tool_name="save_pipeline")

        pipeline_config = result.config
        if pipeline_config is None:
            return ResponseFormatter.error("Failed to parse pipeline config", tool_name="save_pipeline")

        # Parse tags
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        try:
            meta, validation = store.save(
                name=name,
                config=pipeline_config,
                tags=tag_list,
                description=description,
                scope=scope,
            )
        except ValueError as exc:
            return ResponseFormatter.error(str(exc), tool_name="save_pipeline")

        # Build response
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
            step_summary = " → ".join(s.action for s in pipeline_config.steps)
            parts.append(f"  Steps: {meta.step_count} ({step_summary})")
        parts.append(f"  Config hash: {meta.config_hash}")

        if validation.has_fixes:
            parts.append("")
            parts.append(f"🔧 Auto-fixed {len(validation.fixes)} issue(s):")
            for fix in validation.fixes:
                parts.append(f"  [{fix.severity.value}] {fix.field}: {fix.reason}")

        parts.append("")
        parts.append("💡 Usage:")
        parts.append(f'  • Execute: unified_search(pipeline="saved:{meta.name}")')
        parts.append(f'  • View: load_pipeline(source="{meta.name}")')

        return "\n".join(parts)

    # ── Tool 2: list_pipelines ───────────────────────────────────────────

    @mcp.tool()
    def list_pipelines(
        tag: str = "",
        scope: str = "",
    ) -> str:
        """List all saved pipeline configurations.

        Args:
            tag: Filter by tag (e.g., "sedation"). Empty = show all.
            scope: Filter by scope: "workspace", "global", or "" (show all).

        Returns:
            Table of saved pipelines with name, scope, description, tags.
        """
        store = get_pipeline_store()
        if not store:
            return ResponseFormatter.error("Pipeline store not initialized", tool_name="list_pipelines")

        pipelines = store.list_pipelines(tag=tag, scope=scope)

        if not pipelines:
            msg = "No saved pipelines found."
            if tag:
                msg += f" (filtered by tag: '{tag}')"
            if scope:
                msg += f" (filtered by scope: '{scope}')"
            return msg + '\n\n💡 Create one: save_pipeline(name="...", config="...")'

        # Count per scope
        ws_count = sum(1 for p in pipelines if p.scope.value == "workspace")
        gl_count = sum(1 for p in pipelines if p.scope.value == "global")

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

        for p in pipelines:
            tags_str = ", ".join(p.tags) if p.tags else "-"
            desc = (p.description[:40] + "...") if p.description and len(p.description) > 43 else (p.description or "-")
            parts.append(f"| {p.name} | {p.scope.value} | {desc} | {tags_str} | {p.run_count} |")

        parts.append("")
        parts.append('💡 Load: load_pipeline(source="<name>")')
        parts.append('💡 Execute: unified_search(pipeline="saved:<name>")')

        return "\n".join(parts)

    # ── Tool 3: load_pipeline ────────────────────────────────────────────

    @mcp.tool()
    def load_pipeline(
        source: str,
    ) -> str:
        """Load a pipeline configuration for review or editing.

        Loads from one of three sources:
        - Saved name: "weekly_remimazolam" or "saved:weekly_remimazolam"
        - Local file: "file:path/to/pipeline.yaml"

        The returned YAML can be reviewed, modified, and then:
        - Executed directly: unified_search(pipeline="<yaml>")
        - Saved with changes: save_pipeline(name="...", config="<yaml>")

        Args:
            source: Pipeline source identifier (see above).

        Returns:
            Full pipeline YAML content + metadata.
        """
        store = get_pipeline_store()
        if not store:
            return ResponseFormatter.error("Pipeline store not initialized", tool_name="load_pipeline")

        source = source.strip()

        try:
            # File path source
            if source.startswith("file:"):
                filepath = source[5:]
                config, result = store.load_from_path(filepath)
                source_type = "file"
                meta = None
            else:
                # Saved pipeline (with or without "saved:" prefix)
                config, meta = store.load(source)
                source_type = "saved"
                result = None

        except FileNotFoundError as exc:
            return ResponseFormatter.error(
                str(exc),
                suggestion="Use list_pipelines() to see available pipelines",
                tool_name="load_pipeline",
            )
        except ValueError as exc:
            return ResponseFormatter.error(str(exc), tool_name="load_pipeline")

        # Format output
        config_dict = _config_to_display_dict(config)
        yaml_str = yaml.dump(config_dict, allow_unicode=True, default_flow_style=False, sort_keys=False)

        parts = []
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

        if result and result.has_fixes:
            parts.append("")
            parts.append(f"🔧 Auto-fixed {len(result.fixes)} issue(s):")
            for fix in result.fixes:
                parts.append(f"  [{fix.severity.value}] {fix.field}: {fix.reason}")

        parts.append("")
        if meta:
            parts.append(f'💡 Execute: unified_search(pipeline="saved:{meta.name}")')
            parts.append(f'💡 Edit & re-save: save_pipeline(name="{meta.name}", config="<modified yaml>")')
        else:
            parts.append('💡 Execute: unified_search(pipeline="<yaml above>")')
            parts.append('💡 Save: save_pipeline(name="<name>", config="<yaml above>")')

        return "\n".join(parts)

    # ── Tool 4: delete_pipeline ──────────────────────────────────────────

    @mcp.tool()
    def delete_pipeline(name: str) -> str:
        """Delete a saved pipeline configuration and its execution history.

        Args:
            name: Name of the saved pipeline to delete.

        Returns:
            Confirmation of deletion.
        """
        store = get_pipeline_store()
        if not store:
            return ResponseFormatter.error("Pipeline store not initialized", tool_name="delete_pipeline")

        try:
            scope, run_count = store.delete(name)
        except FileNotFoundError:
            return ResponseFormatter.error(
                f"Pipeline '{name}' not found",
                suggestion="Use list_pipelines() to see available pipelines",
                tool_name="delete_pipeline",
            )

        parts = [f'🗑️ Pipeline "{name}" deleted.']
        parts.append(f"  - Configuration removed (from {scope.value} scope)")
        if run_count:
            parts.append(f"  - {run_count} execution history record(s) removed")

        return "\n".join(parts)

    # ── Tool 5: get_pipeline_history ─────────────────────────────────────

    @mcp.tool()
    def get_pipeline_history(
        name: str,
        limit: int = 5,
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
        store = get_pipeline_store()
        if not store:
            return ResponseFormatter.error("Pipeline store not initialized", tool_name="get_pipeline_history")

        if not store.exists(name):
            return ResponseFormatter.error(
                f"Pipeline '{name}' not found",
                suggestion="Use list_pipelines() to see available pipelines",
                tool_name="get_pipeline_history",
            )

        runs = store.get_history(name, limit=limit)

        if not runs:
            return f'📊 Pipeline "{name}" has no execution history yet.\n\n💡 Execute: unified_search(pipeline="saved:{name}")'

        total_runs = sum(1 for _ in (store._runs_dir_for(store._find_pipeline_scope(name)) / name).glob("*.json"))

        parts = [
            f'📊 Execution History for "{name}" (showing {len(runs)} of {total_runs}):',
            "",
            "| # | Date | Articles | New | Removed | Status |",
            "|---|------|----------|-----|---------|--------|",
        ]

        for i, run in enumerate(runs):
            date_str = run.started.strftime("%Y-%m-%d %H:%M") if run.started else "unknown"
            status_icon = "✅ OK" if run.status == "success" else f"❌ {run.status}"
            new_str = f"+{len(run.new_pmids)}" if run.new_pmids else "+0"
            removed_str = f"-{len(run.removed_pmids)}" if run.removed_pmids else "-0"
            run_num = total_runs - i
            parts.append(
                f"| {run_num} | {date_str} | {run.article_count} | {new_str} | {removed_str} | {status_icon} |"
            )

        # Show latest new articles if available
        latest = runs[0]
        if latest.new_pmids:
            parts.append("")
            parts.append(f"Latest new articles (run #{total_runs}):")
            for j, pmid in enumerate(latest.new_pmids[:5]):
                # Try to find article info in top_articles
                article_info = next(
                    (a for a in latest.top_articles if a.get("pmid") == pmid),
                    None,
                )
                if article_info:
                    title = article_info.get("title", "")[:60]
                    year = article_info.get("year", "")
                    parts.append(f'  {j + 1}. PMID {pmid} - "{title}" ({year})')
                else:
                    parts.append(f"  {j + 1}. PMID {pmid}")

            parts.append("")
            pmid_str = ",".join(latest.new_pmids[:10])
            parts.append(f'💡 Full details: fetch_article_details(pmids="{pmid_str}")')

        return "\n".join(parts)

    # ── Tool 6: schedule_pipeline (Phase 4 stub) ─────────────────────────

    @mcp.tool()
    def schedule_pipeline(
        name: str,
        cron: str = "",
        diff_mode: bool = True,
        notify: bool = True,
    ) -> str:
        """Schedule a saved pipeline for periodic execution.

        ⚠️ Scheduling is planned for Phase 4 and not yet implemented.
        Currently, you can manually re-execute saved pipelines:
            unified_search(pipeline="saved:<name>")

        Args:
            name: Saved pipeline name.
            cron: Cron expression (5-field). Examples: "0 9 * * 1" (Mon 9am).
            diff_mode: When True, only report articles not seen in previous run.
            notify: When True, emit MCP resource notification on new results.

        Returns:
            Status message about scheduling availability.
        """
        return (
            "⚠️ Pipeline scheduling is planned for Phase 4 and not yet implemented.\n\n"
            "In the meantime, you can:\n"
            f'  • Execute manually: unified_search(pipeline="saved:{name}")\n'
            f'  • Check history: get_pipeline_history(name="{name}")\n'
            f"  • Set up OS-level scheduling (cron/Task Scheduler) to run:\n"
            f"    uv run python -m pubmed_search.cli run-pipeline {name}\n"
        )


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

    out = config.output
    data["output"] = {
        "format": out.format,
        "limit": out.limit,
        "ranking": out.ranking,
    }

    return data
