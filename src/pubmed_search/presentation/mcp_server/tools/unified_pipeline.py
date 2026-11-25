"""
Unified Search — Pipeline Execution Module.

Handles parsing and execution of pipeline configs (YAML/JSON templates,
saved pipelines, custom DAGs).

Extracted from unified.py to keep each module under 400 lines.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from pubmed_search.application.pipeline.budgets import PIPELINE_EXHAUSTIVE_PREVIEW
from pubmed_search.application.pipeline.config_parser import (
    parse_pipeline_config_text as _parse_pipeline_config,
)
from pubmed_search.application.pipeline.executor import (
    PipelineOutcomeStatus,
    classify_pipeline_outcome,
    config_requests_exhaustive_retrieval,
    is_exhaustive_step,
    pipeline_outcome_message,
    run_uses_exhaustive_retrieval,
)
from pubmed_search.shared.credential_sanitizer import contains_credential_material

from ._common import ResponseFormatter

if TYPE_CHECKING:
    from pubmed_search.application.pipeline.store import PipelineStore
    from pubmed_search.domain.entities.pipeline import PipelineRun
    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)


@dataclass
class PipelineModeOutcome:
    """Typed execution envelope used by the unified-search run journal."""

    response: str
    status: Literal["completed", "partial", "failed"]
    articles: list[Any] = field(default_factory=list)
    step_results: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    plan: dict[str, Any] = field(default_factory=dict)
    response_format: Literal["markdown", "json"] = "markdown"
    # True when the run collected a complete PubMed record set (retrieval:
    # exhaustive); the response itself stays a bounded preview.
    exhaustive: bool = False


def _pipeline_failure(
    error: str,
    *,
    output_format: str,
    suggestion: str | None = None,
    example: str | None = None,
) -> PipelineModeOutcome:
    response_format: Literal["markdown", "json"] = "json" if output_format in {"json", "toon"} else "markdown"
    return PipelineModeOutcome(
        response=ResponseFormatter.error(
            error,
            suggestion=suggestion,
            example=example,
            tool_name="unified_search",
            output_format=response_format,
        ),
        status="failed",
        error=error,
        response_format=response_format,
    )


async def _execute_pipeline_mode_outcome(
    pipeline_text: str,
    output_format: str,
    searcher: LiteratureSearcher,
    *,
    pipeline_store: PipelineStore | None,
    dry_run: bool = False,
    stop_at: str = "",
) -> PipelineModeOutcome:
    """Parse and execute a pipeline config, returning formatted results.

    Accepts:
    - "saved:<name>" — load a previously saved pipeline from PipelineStore
    - YAML or JSON string — inline pipeline config
    """
    from pubmed_search.application.pipeline.budgets import PipelineExecutionPolicy
    from pubmed_search.application.pipeline.executor import PipelineExecutor
    from pubmed_search.application.pipeline.templates import materialize_pipeline_config
    from pubmed_search.application.pipeline.validator import parse_and_validate_config
    from pubmed_search.domain.entities.pipeline import PipelineConfig
    from pubmed_search.shared.settings import load_settings

    pipeline_name_override: str | None = None
    saved_config: PipelineConfig | None = None

    if contains_credential_material(pipeline_text):
        return _pipeline_failure(
            "Pipeline config contains credential material; use server environment configuration instead",
            suggestion="Remove provider keys, tokens, cookies, and secrets from pipeline parameters",
            output_format=output_format,
        )

    # ── Saved pipeline mode ──────────────────────────────────────────────
    stripped = pipeline_text.strip()
    if stripped.startswith("saved:"):
        pipeline_name = stripped[6:].strip()
        if not pipeline_name:
            return _pipeline_failure(
                'Missing pipeline name after "saved:"',
                suggestion='Use saved:<name>, e.g. pipeline="saved:weekly_remimazolam"',
                output_format=output_format,
            )
        if not pipeline_store:
            return _pipeline_failure(
                "Pipeline store not initialized",
                suggestion="Server may not be fully started",
                output_format=output_format,
            )
        try:
            config, _meta = pipeline_store.load(pipeline_name)
            pipeline_name_override = _meta.name
            saved_config = config
        except FileNotFoundError:
            return _pipeline_failure(
                "Saved pipeline was not found",
                suggestion="Use list_pipelines() to see available pipelines",
                output_format=output_format,
            )
        except ValueError:
            return _pipeline_failure(
                "Saved pipeline could not be loaded because its configuration is invalid or unsafe",
                output_format=output_format,
            )
    else:
        # ── Inline YAML/JSON mode ───────────────────────────────────────
        try:
            raw = _parse_pipeline_config(pipeline_text)
        except Exception as exc:
            return _pipeline_failure(
                f"Invalid pipeline config: {exc}",
                suggestion="Provide valid YAML or JSON for the pipeline parameter",
                example=('pipeline="template: pico\ntemplate_params:\n  P: ICU patients\n  I: remimazolam"'),
                output_format=output_format,
            )

        result = parse_and_validate_config(raw)
        if not result.valid:
            error_msg = "Pipeline config error:\n" + "\n".join(f"  ❌ {e}" for e in result.errors)
            return _pipeline_failure(error_msg, output_format=output_format)
        config = result.config  # type: ignore[assignment]
        if config is None:
            return _pipeline_failure(
                "Failed to parse pipeline config",
                output_format=output_format,
            )

    try:
        config = materialize_pipeline_config(config, default_name=pipeline_name_override or "")
    except ValueError as exc:
        return _pipeline_failure(
            f"Template error: {exc}",
            suggestion="Check template name and required params",
            output_format=output_format,
        )

    if contains_credential_material(json.dumps(asdict(config), ensure_ascii=False, default=str)):
        return _pipeline_failure(
            "Pipeline config contains credential material; use server environment configuration instead",
            suggestion="Remove provider keys, tokens, cookies, and secrets from pipeline parameters",
            output_format=output_format,
        )

    # Execute
    from pubmed_search.infrastructure.pubtator.semantic_adapter import get_semantic_enhancer
    from pubmed_search.infrastructure.sources import search_alternate_source_adapter

    settings = load_settings()
    executor = PipelineExecutor(
        searcher=searcher,
        alternate_search_adapter=search_alternate_source_adapter,
        semantic_enhancer_factory=get_semantic_enhancer,
        execution_policy=PipelineExecutionPolicy(
            run_timeout_seconds=settings.pipeline_run_timeout_seconds,
            max_external_calls=settings.pipeline_max_external_calls,
        ),
    )
    prepared_config = config
    prepare_config = getattr(executor, "prepare_config", None)
    if callable(prepare_config):
        maybe_prepared = prepare_config(config)
        if isinstance(maybe_prepared, PipelineConfig):
            prepared_config = maybe_prepared

    if config_requests_exhaustive_retrieval(prepared_config) and not dry_run and saved_config is None:
        return _pipeline_failure(
            "retrieval: exhaustive requires a saved pipeline so the complete record set and its "
            "search record can be persisted",
            suggestion='Save it first with save_pipeline(name="<name>", config="..."), then run '
            'unified_search(pipeline="saved:<name>"); dry_run=True still validates inline configs',
            output_format=output_format,
        )

    started_at = datetime.now(timezone.utc)
    stop_at_step = stop_at.strip() or None
    try:
        if dry_run:
            articles, step_results = executor.dry_run(prepared_config, stop_at=stop_at_step)
        else:
            articles, step_results = await executor.execute(prepared_config, stop_at=stop_at_step)
    except ValueError:
        return _pipeline_failure(
            "Pipeline validation failed",
            output_format=output_format,
        )
    except RuntimeError:
        return _pipeline_failure(
            "Pipeline execution failed",
            output_format=output_format,
        )

    status = classify_pipeline_outcome(articles, step_results)

    from pubmed_search.application.pipeline.report_generator import generate_pipeline_report

    report = generate_pipeline_report(articles, step_results, prepared_config)
    exhaustive_run = not dry_run and run_uses_exhaustive_retrieval(step_results)

    # ── Auto-save report to workspace/global ─────────────────────────────
    recorded_run = None
    if not dry_run:
        recorded_run = await asyncio.to_thread(
            _auto_save_pipeline_report,
            prepared_config,
            articles,
            report,
            pipeline_store=pipeline_store,
            status=status,
            pipeline_name_override=pipeline_name_override,
            started_at=started_at,
            step_results=step_results,
            saved_config=saved_config,
        )

    wants_json = output_format in {"json", "toon"} or prepared_config.output.format == "json"
    response_format: Literal["markdown", "json"] = "json" if wants_json else "markdown"
    if exhaustive_run:
        response = (
            _format_exhaustive_pipeline_json(
                articles=articles,
                step_results=step_results,
                config=prepared_config,
                run=recorded_run,
                status=status,
            )
            if wants_json
            else _format_exhaustive_pipeline_markdown(
                articles=articles,
                step_results=step_results,
                config=prepared_config,
                run=recorded_run,
                status=status,
            )
        )
    elif wants_json:
        response = _format_pipeline_json(
            articles=articles,
            step_results=step_results,
            config=prepared_config,
            dry_run=dry_run,
            stop_at=stop_at_step,
        )
    else:
        response = report

    return PipelineModeOutcome(
        response=response,
        status=status,
        articles=list(articles),
        step_results=dict(step_results),
        error=pipeline_outcome_message(status) if status == "failed" else None,
        plan={
            "mode": "pipeline",
            "name": prepared_config.name or "",
            "template": prepared_config.template,
            "dry_run": dry_run,
            "stop_at": stop_at_step,
            "steps": [
                {"id": step.id, "action": step.action, "inputs": list(step.inputs)} for step in prepared_config.steps
            ],
        },
        response_format=response_format,
        exhaustive=bool(
            exhaustive_run and recorded_run is not None and recorded_run.retrieval.get("exhaustive") is True
        ),
    )


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
                "status": "skipped"
                if result is None
                else "planned"
                if dry_run or result.metadata.get("dry_run") is True
                else ("ok" if result.ok else "error"),
                "article_count": len(result.articles) if result else 0,
                "pmid_count": len(result.pmids) if result else 0,
                "pmids": list(result.pmids) if result else [],
                "metadata": result.metadata if result else {},
                "error": result.error if result else None,
            }
        )

    data = {
        "type": "pipeline_result",
        "status": classify_pipeline_outcome(articles, step_results),
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
            "steps_executed": sum(
                1 for result in step_results.values() if not dry_run and result.metadata.get("dry_run") is not True
            ),
            "steps_planned": sum(
                1 for result in step_results.values() if dry_run or result.metadata.get("dry_run") is True
            ),
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
    *,
    pipeline_store: PipelineStore | None,
    status: PipelineOutcomeStatus = "completed",
    pipeline_name_override: str | None = None,
    started_at: datetime | None = None,
    step_results: dict[str, Any] | None = None,
    saved_config: Any = None,
) -> PipelineRun | None:
    """Best-effort auto-save of pipeline report and run record.

    Returns the persisted run for saved pipelines, otherwise ``None``.
    """
    if not pipeline_store:
        return None

    try:
        from pubmed_search.application.pipeline.run_recorder import PipelineRunRecorder

        now = datetime.now(timezone.utc)
        pipeline_name = pipeline_name_override or config.name or config.template or "unnamed"
        persist_run = bool(pipeline_store.exists(pipeline_name))
        run = PipelineRunRecorder(pipeline_store, on_recorded=_screening_observer(pipeline_store)).record(
            pipeline_name=pipeline_name,
            articles=list(articles),
            step_results=dict(step_results or {}),
            report=report,
            started=started_at or now,
            run_id=pipeline_store.create_run_id(pipeline_name, now),
            persist_run=persist_run,
            outcome=status,
            executed_config=config,
            saved_config=saved_config,
        )
        logger.info("Pipeline report saved")
        return run if persist_run else None
    except Exception as exc:
        # Pipeline errors can contain provider URLs or the original biomedical
        # query.  Operational logs only need the failure class; durable run
        # metadata carries a separately sanitized diagnostic.
        logger.warning("Failed to auto-save pipeline report (%s)", type(exc).__name__)
        return None


def _screening_observer(pipeline_store: PipelineStore) -> Any:
    """Return the run observer that feeds new records into screening (none yet)."""
    del pipeline_store
    return None


def _compact_article(article: Any) -> dict[str, Any]:
    title = str(getattr(article, "title", "") or "")
    return {
        "pmid": getattr(article, "pmid", None),
        "title": title if len(title) <= 300 else title[:297] + "...",
        "year": getattr(article, "year", None),
        "journal": getattr(article, "journal", None),
        "doi": getattr(article, "doi", None),
    }


def _compact_step(step: Any, result: Any, preview: int) -> dict[str, Any]:
    if result is None:
        return {"id": step.id, "action": step.action, "inputs": list(step.inputs), "status": "skipped"}
    metadata = result.metadata
    compact: dict[str, Any] = {
        "id": step.id,
        "action": step.action,
        "inputs": list(step.inputs),
        "status": "ok" if result.ok else "error",
        "article_count": len(result.articles),
        "pmid_count": len(result.pmids),
        "pmid_preview": list(result.pmids[:preview]),
        "error": result.error,
    }
    if isinstance(metadata.get("query"), str):
        compact["query"] = metadata["query"]
    if is_exhaustive_step(result):
        compact["retrieval"] = dict(metadata.get("retrieval") or {})
        history = dict(metadata.get("pubmed_history") or {})
        compact["physical_query"] = history.get("physical_query") or metadata.get("physical_query")
        translation = history.get("query_translation")
        compact["query_translation_chars"] = len(translation) if isinstance(translation, str) else 0
        provider_notes = {
            key: value
            for group in ("provider_errors", "provider_warnings")
            for key, value in dict(history.get(group) or {}).items()
            if value
        }
        if provider_notes:
            compact["provider_notes"] = provider_notes
    if metadata.get("source_errors"):
        compact["source_errors"] = list(metadata["source_errors"])[:5]
    return compact


def _exhaustive_next_steps(run: Any) -> dict[str, str]:
    if run is None:
        return {}
    name, run_id = run.pipeline_name, run.run_id
    return {
        "page_records": (
            f'get_pipeline_history(name="{name}", run_id="{run_id}", view="records", offset=0, limit=100)'
        ),
        "history": f'get_pipeline_history(name="{name}")',
    }


def _format_exhaustive_pipeline_json(
    *,
    articles: list[Any],
    step_results: dict[str, Any],
    config: Any,
    run: Any,
    status: PipelineOutcomeStatus,
) -> str:
    """Return a bounded summary; the complete record set stays in the run artifact."""
    from pubmed_search.application.pipeline.run_recorder import retrieval_summary

    preview = min(config.output.limit, PIPELINE_EXHAUSTIVE_PREVIEW)
    final_pmids = run.pmids if run is not None else []
    data = {
        "type": "pipeline_result",
        "status": status,
        "pipeline": {
            "name": config.name or "",
            "template": config.template,
            "dry_run": False,
            "output": {
                "format": config.output.format,
                "limit": config.output.limit,
                "ranking": config.output.ranking,
            },
        },
        "retrieval": run.retrieval if run is not None else retrieval_summary(step_results, len(final_pmids)),
        "run": None
        if run is None
        else {
            "run_id": run.run_id,
            "pipeline": run.pipeline_name,
            "status": run.status,
            "record_basis": run.record_basis,
            "record_count": len(run.pmids),
            "new_count": len(run.new_pmids),
            "removed_count": len(run.removed_pmids),
            "artifacts": dict(run.artifacts),
        },
        "summary": {
            "record_count": len(final_pmids),
            "steps_executed": len(step_results),
            "steps_failed": sum(1 for result in step_results.values() if not result.ok),
        },
        "steps": [_compact_step(step, step_results.get(step.id), preview) for step in config.steps],
        "articles_preview": [_compact_article(article) for article in articles[:preview]],
        "preview": {
            "shown": min(len(articles), preview),
            "record_count": len(final_pmids),
            "ranking": config.output.ranking,
            "note": "Bounded preview; read or export the complete record set from the run artifact.",
        },
        "next": _exhaustive_next_steps(run),
    }
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _format_exhaustive_pipeline_markdown(
    *,
    articles: list[Any],
    step_results: dict[str, Any],
    config: Any,
    run: Any,
    status: PipelineOutcomeStatus,
) -> str:
    """Render the same bounded summary as Markdown."""
    from pubmed_search.shared.markdown import escape_markdown_text

    preview = min(config.output.limit, PIPELINE_EXHAUSTIVE_PREVIEW)
    title = escape_markdown_text(config.name or "pipeline")
    parts = [f"# Exhaustive PubMed retrieval: {title}", ""]
    parts.append(f"- Status: {status}")
    for step in config.steps:
        result = step_results.get(step.id)
        if result is None or not is_exhaustive_step(result):
            continue
        retrieval = dict(result.metadata.get("retrieval") or {})
        exhaustive_label = "yes" if retrieval.get("exhaustive") else "no"
        parts.append(
            f"- Step `{step.id}`: PubMed count {retrieval.get('total_count')}, retrieved "
            f"{retrieval.get('retrieved_count')}, exhaustive {exhaustive_label} "
            f"(cap {retrieval.get('cap')}), metadata {retrieval.get('metadata_count', 0)}"
        )
        if result.error:
            parts.append(f"  - Warning: {escape_markdown_text(result.error)}")
    record_count = len(run.pmids) if run is not None else 0
    if run is not None:
        parts.append(
            f"- Run `{run.run_id}`: {record_count} records persisted "
            f"({len(run.new_pmids)} new, {len(run.removed_pmids)} removed vs previous comparable run)"
        )
    parts.append("")
    shown = min(len(articles), preview)
    parts.append(f"## Preview ({shown} of {record_count}, ranking: {config.output.ranking})")
    parts.append("")
    for index, article in enumerate(articles[:preview], start=1):
        compact = _compact_article(article)
        year = compact["year"] or "n.d."
        parts.append(f"{index}. PMID {compact['pmid']} - {escape_markdown_text(compact['title'])} ({year})")
    next_steps = _exhaustive_next_steps(run)
    if next_steps:
        parts.append("")
        parts.append("## Next")
        parts.extend(f"- {key}: `{value}`" for key, value in next_steps.items())
    return "\n".join(parts)
