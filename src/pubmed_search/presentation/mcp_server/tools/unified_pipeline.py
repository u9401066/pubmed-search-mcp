"""
Unified Search — Pipeline Execution Module.

Handles parsing and execution of pipeline configs (YAML/JSON templates,
saved pipelines, custom DAGs).

Extracted from unified.py to keep each module under 400 lines.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ._common import ResponseFormatter

if TYPE_CHECKING:
    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)


def _parse_pipeline_config(text: str) -> dict:
    """Parse pipeline config from YAML or JSON string.

    Tries YAML first (superset of JSON), falls back to JSON.
    Uses yaml.safe_load to prevent arbitrary code execution.
    Raises ValueError if the result is not a dict.
    """
    import json as _json

    import yaml

    # YAML is a superset of JSON, so yaml.safe_load handles both.
    # We try YAML first; if it fails on edge cases, fall back to JSON.
    result = None
    try:
        result = yaml.safe_load(text)
        if isinstance(result, dict):
            return result
    except yaml.YAMLError:
        pass

    # Fallback: pure JSON
    try:
        result = _json.loads(text)
        if isinstance(result, dict):
            return result
    except _json.JSONDecodeError:
        pass

    msg = f"Pipeline config must be a YAML or JSON mapping (dict), got {type(result).__name__}"
    raise ValueError(msg)


async def _execute_pipeline_mode(
    pipeline_text: str,
    output_format: str,
    searcher: LiteratureSearcher,
) -> str:
    """Parse and execute a pipeline config, returning formatted results.

    Accepts:
    - "saved:<name>" — load a previously saved pipeline from PipelineStore
    - YAML or JSON string — inline pipeline config
    """
    from pubmed_search.application.pipeline.executor import PipelineExecutor
    from pubmed_search.application.pipeline.templates import build_pipeline_from_template
    from pubmed_search.application.pipeline.validator import parse_and_validate_config

    # ── Saved pipeline mode ──────────────────────────────────────────────
    stripped = pipeline_text.strip()
    if stripped.startswith("saved:"):
        pipeline_name = stripped[6:].strip()
        if not pipeline_name:
            return ResponseFormatter.error(
                'Missing pipeline name after "saved:"',
                suggestion='Use saved:<name>, e.g. pipeline="saved:weekly_remimazolam"',
                tool_name="unified_search",
            )
        from pubmed_search.presentation.mcp_server.tools.pipeline_tools import get_pipeline_store

        store = get_pipeline_store()  # PipelineStore | None
        if not store:
            return ResponseFormatter.error(
                "Pipeline store not initialized",
                suggestion="Server may not be fully started",
                tool_name="unified_search",
            )
        try:
            config, _meta = store.load(pipeline_name)
        except FileNotFoundError:
            return ResponseFormatter.error(
                f"Saved pipeline '{pipeline_name}' not found",
                suggestion="Use list_pipelines() to see available pipelines",
                tool_name="unified_search",
            )
        except ValueError as exc:
            return ResponseFormatter.error(
                f"Saved pipeline '{pipeline_name}' has errors: {exc}",
                tool_name="unified_search",
            )
    else:
        # ── Inline YAML/JSON mode ───────────────────────────────────────
        try:
            raw = _parse_pipeline_config(pipeline_text)
        except Exception as exc:
            return ResponseFormatter.error(
                f"Invalid pipeline config: {exc}",
                suggestion="Provide valid YAML or JSON for the pipeline parameter",
                example=('pipeline="template: pico\nparams:\n  P: ICU patients\n  I: remimazolam"'),
                tool_name="unified_search",
            )

        # Template mode
        if "template" in raw:
            template_name = raw["template"]
            template_params = raw.get("params", {})
            try:
                config = build_pipeline_from_template(template_name, template_params)
            except ValueError as exc:
                return ResponseFormatter.error(
                    f"Template error: {exc}",
                    suggestion="Check template name and required params",
                    tool_name="unified_search",
                )
        else:
            # Custom pipeline — use validator for auto-fix
            result = parse_and_validate_config(raw)
            if not result.valid:
                error_msg = "Pipeline config error:\n" + "\n".join(f"  ❌ {e}" for e in result.errors)
                if result.fixes:
                    error_msg += "\n\nAuto-fixes attempted:\n" + "\n".join(
                        f"  🔧 {f.field}: {f.reason}" for f in result.fixes
                    )
                return ResponseFormatter.error(error_msg, tool_name="unified_search")
            config = result.config  # type: ignore[assignment]
            if config is None:
                return ResponseFormatter.error(
                    "Failed to parse pipeline config",
                    tool_name="unified_search",
                )

    # Override output format if specified at top level
    if output_format:
        config.output.format = output_format  # type: ignore[assignment]

    # Execute
    from pubmed_search.infrastructure.sources import search_alternate_source

    executor = PipelineExecutor(
        searcher=searcher,
        alternate_search_fn=search_alternate_source,
    )
    try:
        articles, step_results = await executor.execute(config)
    except (ValueError, RuntimeError) as exc:
        return ResponseFormatter.error(
            f"Pipeline execution failed: {exc}",
            tool_name="unified_search",
        )

    from pubmed_search.application.pipeline.report_generator import generate_pipeline_report

    report = generate_pipeline_report(articles, step_results, config)

    # ── Auto-save report to workspace/global ─────────────────────────────
    _auto_save_pipeline_report(config, articles, report)

    return report


def _auto_save_pipeline_report(
    config: Any,
    articles: list,
    report: str,
) -> None:
    """Best-effort auto-save of pipeline report and run record."""
    from pubmed_search.presentation.mcp_server.tools.pipeline_tools import get_pipeline_store

    store = get_pipeline_store()
    if not store:
        return

    try:
        from datetime import datetime, timezone

        from pubmed_search.domain.entities.pipeline import PipelineRun

        now = datetime.now(timezone.utc)
        run_id = now.strftime("%Y%m%d_%H%M%S")
        pipeline_name = config.name or config.template or "unnamed"
        pipeline_name = pipeline_name.strip().lower().replace(" ", "_")

        # Save report markdown
        report_path = store.save_report(
            name=pipeline_name,
            run_id=run_id,
            report_markdown=report,
        )

        # Save run record (if pipeline exists in store)
        if store.exists(pipeline_name):
            pmids = [a.pmid for a in articles if hasattr(a, "pmid") and a.pmid]
            run = PipelineRun(
                run_id=run_id,
                pipeline_name=pipeline_name,
                started=now,
                finished=datetime.now(timezone.utc),
                status="success",
                article_count=len(articles),
                pmids=pmids,
            )
            store.save_run(pipeline_name, run)

        logger.info("Pipeline report saved: %s", report_path)
    except Exception:
        logger.warning("Failed to auto-save pipeline report", exc_info=True)
