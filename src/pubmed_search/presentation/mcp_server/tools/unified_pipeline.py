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
    *,
    dry_run: bool = False,
    stop_at: str = "",
) -> str:
    """Parse and execute a pipeline config, returning formatted results.

    Accepts:
    - "saved:<name>" — load a previously saved pipeline from PipelineStore
    - YAML or JSON string — inline pipeline config
    """
    from pubmed_search.application.pipeline.executor import PipelineExecutor
    from pubmed_search.application.pipeline.templates import materialize_pipeline_config
    from pubmed_search.application.pipeline.validator import parse_and_validate_config
    from pubmed_search.domain.entities.pipeline import PipelineConfig

    pipeline_name_override: str | None = None

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
            pipeline_name_override = _meta.name
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

    try:
        config = materialize_pipeline_config(config)
    except ValueError as exc:
        return ResponseFormatter.error(
            f"Template error: {exc}",
            suggestion="Check template name and required params",
            tool_name="unified_search",
        )

    # Execute
    from pubmed_search.infrastructure.sources import search_alternate_source

    executor = PipelineExecutor(
        searcher=searcher,
        alternate_search_fn=search_alternate_source,
    )
    prepared_config = config
    prepare_config = getattr(executor, "prepare_config", None)
    if callable(prepare_config):
        maybe_prepared = prepare_config(config)
        if isinstance(maybe_prepared, PipelineConfig):
            prepared_config = maybe_prepared

    stop_at_step = stop_at.strip() or None
    try:
        if dry_run:
            articles, step_results = executor.dry_run(prepared_config, stop_at=stop_at_step)
        else:
            articles, step_results = await executor.execute(prepared_config, stop_at=stop_at_step)
    except (ValueError, RuntimeError) as exc:
        return ResponseFormatter.error(
            f"Pipeline execution failed: {exc}",
            tool_name="unified_search",
        )

    from pubmed_search.application.pipeline.report_generator import generate_pipeline_report

    report = generate_pipeline_report(articles, step_results, prepared_config)

    # ── Auto-save report to workspace/global ─────────────────────────────
    if not dry_run:
        _auto_save_pipeline_report(prepared_config, articles, report, pipeline_name_override=pipeline_name_override)

    if output_format == "json" or prepared_config.output.format == "json":
        return _format_pipeline_json(
            articles=articles,
            step_results=step_results,
            config=prepared_config,
            dry_run=dry_run,
            stop_at=stop_at_step,
        )

    return report


def _format_pipeline_json(
    *,
    articles: list[Any],
    step_results: dict[str, Any],
    config: Any,
    dry_run: bool = False,
    stop_at: str | None = None,
) -> str:
    """Return structured pipeline output for agent clients."""
    import json

    steps = []
    for step in config.steps:
        result = step_results.get(step.id)
        steps.append(
            {
                "id": step.id,
                "action": step.action,
                "inputs": list(step.inputs),
                "status": "skipped" if result is None else ("ok" if result.ok else "error"),
                "article_count": len(result.articles) if result else 0,
                "pmid_count": len(result.pmids) if result else 0,
                "pmids": list(result.pmids) if result else [],
                "metadata": result.metadata if result else {},
                "error": result.error if result else None,
            }
        )

    data = {
        "type": "pipeline_result",
        "pipeline": {
            "name": config.name or "",
            "template": config.template,
            "dry_run": dry_run,
            "stop_at": stop_at,
            "output": {
                "format": config.output.format,
                "limit": config.output.limit,
                "ranking": config.output.ranking,
            },
            "globals": config.globals,
            "variables": config.variables,
        },
        "summary": {
            "article_count": len(articles),
            "steps_executed": sum(1 for result in step_results.values() if result.ok),
            "steps_failed": sum(1 for result in step_results.values() if not result.ok),
        },
        "steps": steps,
        "articles": [_article_to_json(article) for article in articles],
    }
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _article_to_json(article: Any) -> dict[str, Any]:
    """Serialize either UnifiedArticle or a lightweight article-like test object."""
    to_dict = getattr(article, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
        if isinstance(value, dict):
            return value

    article_type = getattr(article, "article_type", None)
    article_type_value = getattr(article_type, "value", article_type)
    authors = getattr(article, "authors", None) or []
    author_names = []
    for author in authors:
        name = getattr(author, "display_name", None) or getattr(author, "full_name", None) or str(author)
        author_names.append(name)

    return {
        "pmid": getattr(article, "pmid", None),
        "doi": getattr(article, "doi", None),
        "pmc": getattr(article, "pmc", None),
        "title": getattr(article, "title", None),
        "abstract": getattr(article, "abstract", None),
        "journal": getattr(article, "journal", None),
        "year": getattr(article, "year", None),
        "article_type": article_type_value,
        "authors": author_names,
        "author_string": getattr(article, "author_string", None),
        "primary_source": getattr(article, "primary_source", None),
        "ranking_score": getattr(article, "ranking_score", None),
        "relevance_score": getattr(article, "relevance_score", None),
        "quality_score": getattr(article, "quality_score", None),
    }


def _auto_save_pipeline_report(
    config: Any,
    articles: list,
    report: str,
    pipeline_name_override: str | None = None,
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
        pipeline_name = pipeline_name_override or config.name or config.template or "unnamed"
        pipeline_name = pipeline_name.strip().lower().replace(" ", "_")
        run_id = store.create_run_id(pipeline_name, now)

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
