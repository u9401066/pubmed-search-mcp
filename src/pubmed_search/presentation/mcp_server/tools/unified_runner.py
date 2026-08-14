"""Reusable runtime runner for the MCP unified_search implementation.

This module is still in presentation because it formats MCP-compatible strings,
persists MCP session artifacts, and can report MCPServer progress. The stable
Python SDK imports it lazily only when a caller actually runs unified search
without injecting a custom runner.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any, Literal, Union, cast

from pubmed_search.application.search.query_analyzer import QueryAnalyzer
from pubmed_search.application.search.semantic_enhancer import get_semantic_enhancer
from pubmed_search.application.session.artifact_envelope import build_unified_search_artifact_envelope
from pubmed_search.application.timeline import TimelineBuilder, build_research_tree
from pubmed_search.infrastructure.sources.registry import SourceSelectionError, get_source_registry
from pubmed_search.presentation.mcp_server.session_tools import notify_session_resources_updated
from pubmed_search.shared.credential_sanitizer import contains_credential_material

from .agent_output import is_structured_output_format, serialize_structured_payload
from .artifact_memory import artifact_markdown_note, artifact_persistence_enabled, persist_tool_artifact
from .search_run_journal import (
    SearchRunJournal,
    classify_search_run_status,
    compact_search_run_handoff,
    search_run_markdown_note,
)
from .tool_response import ResponseFormatter
from .tool_runtime import safe_report_progress
from .unified_execution import execute_unified_search
from .unified_formatting import _format_as_json, _format_unified_results
from .unified_pipeline import _execute_pipeline_mode_outcome
from .unified_planning import build_unified_search_plan
from .unified_request import normalize_unified_search_request
from .unified_source_search import (
    _search_arxiv_adapter,
    _search_biorxiv_adapter,
    _search_core_adapter,
    _search_europe_pmc_adapter,
    _search_medrxiv_adapter,
    _search_openalex_adapter,
    _search_pubmed_adapter,
    _search_scopus_adapter,
    _search_semantic_scholar_adapter,
    _search_web_of_science_adapter,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcp.server.mcpserver import Context

    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)


def _search_run_hint(run: dict[str, Any] | None) -> str:
    """Return a truthful bounded recovery hint for an error response."""
    handoff = compact_search_run_handoff(run)
    if handoff is None:
        return ""
    if handoff.get("history_available") is False:
        return " Durable search history was unavailable; recovery is not guaranteed."
    run_id = str(handoff["run_id"])
    return f' Inspect with read_session(action="search_run", run_id="{run_id}").'


def _attach_search_run_to_error(
    response: str,
    *,
    output_format: str,
    run: dict[str, Any] | None,
) -> str:
    """Attach recovery metadata without corrupting JSON or TOON responses."""
    handoff = compact_search_run_handoff(run)
    if handoff is None:
        return response
    if not is_structured_output_format(output_format):
        return response + search_run_markdown_note(run)
    try:
        if output_format == "toon":
            import toons

            payload = toons.loads(response)
        else:
            payload = json.loads(response)
    except (TypeError, ValueError):
        return response
    if not isinstance(payload, dict):
        return response
    payload["search_run"] = handoff
    return serialize_structured_payload(payload, output_format)


def persist_unified_search_artifact(
    *,
    request: Any,
    plan: Any,
    execution: Any,
    markdown_response: str | None = None,
    primary_format: Literal["json", "toon"] = "json",
    search_run_id: str | None = None,
    search_run_handoff: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Persist the already-computed unified_search response as a session artifact."""
    if not artifact_persistence_enabled():
        return None

    try:
        structured_payload = _format_as_json(
            execution.ranked,
            plan.analysis,
            execution.stats,
            execution.relaxation_result,
            execution.deep_search_metrics,
            source_api_counts=execution.source_api_counts or None,
            source_disagreement=execution.source_disagreement,
            reproducibility_score=execution.reproducibility_score,
            research_context=execution.research_context_data,
            source_errors=execution.source_errors,
            source_metadata=dict(getattr(execution, "source_metadata", {}) or {}),
            source_statuses=dict(getattr(execution, "source_statuses", {}) or {}),
            counts_first=False,
            compact_output=False,
            include_analysis=True,
            include_similarity_scores=True,
            include_next_tools=True,
            include_section_provenance=True,
            max_response_chars=None,
            output_format=primary_format,
            search_run_handoff=search_run_handoff,
        )
    except Exception as exc:
        logger.warning("Failed to prepare unified_search artifact payload (%s)", type(exc).__name__)
        return None
    primary_file = f"results.{primary_format}"
    envelope = build_unified_search_artifact_envelope(
        request=request,
        plan=plan,
        execution=execution,
        structured_payload=structured_payload,
        markdown_response=markdown_response,
        primary_format=primary_format,
    )
    if search_run_id:
        envelope.metadata["search_run_id"] = search_run_id
        envelope.summary["search_run_id"] = search_run_id
    return persist_tool_artifact(
        tool="unified_search",
        kind="search_results",
        files=envelope.files,
        primary_file=primary_file,
        summary=envelope.summary,
        metadata=envelope.metadata,
    )


async def run_unified_search(
    *,
    searcher: LiteratureSearcher,
    query: str,
    limit: Union[int, str] = 10,
    sources: Union[str, None] = None,
    ranking: Literal["balanced", "impact", "recency", "quality"] = "balanced",
    output_format: Literal["markdown", "json", "toon"] = "markdown",
    filters: Union[str, None] = None,
    options: Union[str, None] = None,
    pipeline: Union[str, None] = None,
    dry_run: bool = False,
    stop_at: str = "",
    ctx: Context | None = None,
    analyzer_factory: Callable[[], Any] = QueryAnalyzer,
    enhancer_factory: Callable[[], Any] = get_semantic_enhancer,
    source_registry_factory: Callable[[], Any] = get_source_registry,
    timeline_builder_cls: Any = TimelineBuilder,
    research_tree_builder: Callable[[Any], Any] = build_research_tree,
    search_functions: Any | None = None,
) -> str:
    """Run unified_search with the same behavior as the MCP tool."""
    query_fingerprint = hashlib.sha256(query.encode("utf-8", errors="replace")).hexdigest()[:12]
    logger.info(
        "Unified search: query_sha256=%s, query_length=%s, limit=%s, ranking='%s'",
        query_fingerprint,
        len(query),
        limit,
        ranking,
    )

    async def _progress(progress: float, total: float, message: str) -> None:
        await safe_report_progress(ctx, progress, total, message)

    journal: SearchRunJournal | None = None
    try:
        if pipeline:
            journal = await SearchRunJournal.start(
                query=query,
                request={
                    "query": query,
                    "limit": limit,
                    "sources": sources,
                    "ranking": ranking,
                    "output_format": output_format,
                    "filters": filters,
                    "options": options,
                    "pipeline": pipeline,
                    "dry_run": dry_run,
                    "stop_at": stop_at,
                },
            )
            if contains_credential_material(pipeline):
                validation_error = (
                    "pipeline appears to contain credential material; remove secrets and use server environment "
                    "configuration"
                )
                failed_run = await journal.fail(validation_error, stage="validation", retryable=False)
                await notify_session_resources_updated(ctx)
                response = ResponseFormatter.error(
                    validation_error,
                    suggestion=f"Use provider credentials from server settings, then retry.{_search_run_hint(failed_run)}",
                    tool_name="unified_search",
                    output_format=output_format,
                )
                return _attach_search_run_to_error(response, output_format=output_format, run=failed_run)
            await journal.plan_pipeline(pipeline, dry_run=dry_run, stop_at=stop_at)
            pipeline_outcome = await _execute_pipeline_mode_outcome(
                pipeline,
                output_format,
                searcher,
                dry_run=dry_run,
                stop_at=stop_at,
            )
            await journal.record_pipeline_outcome(pipeline_outcome)
            completed_run = await journal.complete_pipeline(pipeline_outcome)
            await notify_session_resources_updated(ctx)
            handoff = compact_search_run_handoff(completed_run)
            if pipeline_outcome.response_format == "json":
                try:
                    payload = json.loads(pipeline_outcome.response)
                except (TypeError, ValueError):
                    payload = None
                if isinstance(payload, dict):
                    payload["search_run"] = handoff
                    payload["search_status"] = {
                        "state": pipeline_outcome.status,
                        "bounded": True,
                        "exhaustive": False,
                        "mode": "pipeline",
                    }
                    target_format = output_format if output_format in {"json", "toon"} else "json"
                    return serialize_structured_payload(payload, target_format)
            return pipeline_outcome.response + search_run_markdown_note(completed_run)

        try:
            request = normalize_unified_search_request(
                query=query,
                limit=limit,
                sources=sources,
                ranking=ranking,
                output_format=output_format,
                filters=filters,
                options=options,
                pipeline=pipeline,
            )
        except ValueError as exc:
            journal = await SearchRunJournal.start(
                query=query,
                request={
                    "query": query,
                    "limit": limit,
                    "sources": sources,
                    "ranking": ranking,
                    "output_format": output_format,
                    "filters": filters,
                    "options": options,
                    "dry_run": dry_run,
                    "stop_at": stop_at,
                },
            )
            failed_run = await journal.fail(exc, stage="validation", retryable=False)
            await notify_session_resources_updated(ctx)
            run_hint = _search_run_hint(failed_run)
            response = ResponseFormatter.error(
                str(exc),
                suggestion=(
                    f"Provide a search query.{run_hint}"
                    if str(exc) == "Empty query"
                    else (
                        "Correct the invalid limit, filters, options, or retrieval-mode combination and retry."
                        f"{run_hint}"
                    )
                ),
                example='unified_search(query="machine learning in anesthesia")',
                tool_name="unified_search",
                output_format=output_format,
            )
            return _attach_search_run_to_error(response, output_format=output_format, run=failed_run)

        journal = await SearchRunJournal.start(
            query=request.query,
            request={
                "query": request.query,
                "limit": request.limit,
                "sources": request.sources,
                "ranking": request.ranking,
                "output_format": request.output_format,
                "filters": filters,
                "options": options,
                "dry_run": dry_run,
                "stop_at": stop_at,
            },
        )

        try:
            plan = await build_unified_search_plan(
                request,
                progress=_progress,
                analyzer_factory=analyzer_factory,
                enhancer_factory=enhancer_factory,
                source_registry_factory=source_registry_factory,
            )
        except SourceSelectionError as selection_error:
            failed_run = await journal.fail(selection_error, stage="planning", retryable=False)
            await notify_session_resources_updated(ctx)
            available_sources = source_registry_factory().list_unified_sources()
            run_hint = _search_run_hint(failed_run)
            response = ResponseFormatter.error(
                str(selection_error),
                suggestion=(
                    f"Available sources: {', '.join(selection_error.available_sources)}.{run_hint}"
                    if selection_error.available_sources
                    else f"Available sources: {', '.join(available_sources)}.{run_hint}"
                ),
                example='unified_search(query="...", sources="auto,-semantic_scholar")',
                tool_name="unified_search",
                output_format=output_format,
            )
            return _attach_search_run_to_error(response, output_format=output_format, run=failed_run)
        except ValueError as exc:
            failed_run = await journal.fail(exc, stage="planning", retryable=False)
            await notify_session_resources_updated(ctx)
            run_hint = _search_run_hint(failed_run)
            response = ResponseFormatter.error(
                str(exc),
                suggestion=f"Unset PUBMED_SEARCH_DISABLED_SOURCES or specify an enabled source.{run_hint}",
                example='unified_search(query="...", sources="pubmed")',
                tool_name="unified_search",
                output_format=output_format,
            )
            return _attach_search_run_to_error(response, output_format=output_format, run=failed_run)

        await journal.plan(plan)

        execution = await execute_unified_search(
            plan,
            searcher,
            progress=_progress,
            ctx=ctx,
            search_functions=search_functions
            or {
                "pubmed": lambda search_query,
                search_limit,
                min_year,
                max_year,
                advanced_filters: _search_pubmed_adapter(
                    searcher,
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                    advanced_filters,
                ),
                "openalex": lambda search_query,
                search_limit,
                min_year,
                max_year,
                advanced_filters: _search_openalex_adapter(
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                    advanced_filters,
                ),
                "europe_pmc": lambda search_query,
                search_limit,
                min_year,
                max_year,
                advanced_filters: _search_europe_pmc_adapter(
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                    advanced_filters,
                ),
                "semantic_scholar": lambda search_query,
                search_limit,
                min_year,
                max_year,
                advanced_filters: _search_semantic_scholar_adapter(
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                    advanced_filters,
                ),
                "core": lambda search_query, search_limit, min_year, max_year, advanced_filters: _search_core_adapter(
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                    advanced_filters,
                ),
                "scopus": lambda search_query,
                search_limit,
                min_year,
                max_year,
                advanced_filters: _search_scopus_adapter(
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                    advanced_filters,
                ),
                "web_of_science": lambda search_query,
                search_limit,
                min_year,
                max_year,
                advanced_filters: _search_web_of_science_adapter(
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                    advanced_filters,
                ),
                "arxiv": lambda search_query, search_limit, min_year, max_year, advanced_filters: _search_arxiv_adapter(
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                    advanced_filters,
                ),
                "medrxiv": lambda search_query,
                search_limit,
                min_year,
                max_year,
                advanced_filters: _search_medrxiv_adapter(
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                    advanced_filters,
                ),
                "biorxiv": lambda search_query,
                search_limit,
                min_year,
                max_year,
                advanced_filters: _search_biorxiv_adapter(
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                    advanced_filters,
                ),
            },
            timeline_builder_cls=timeline_builder_cls,
            research_tree_builder=research_tree_builder,
        )
        await journal.record_execution(execution, plan)

        expected_status = classify_search_run_status(execution)
        provisional_run = journal.provisional_run(expected_status)
        provisional_handoff = compact_search_run_handoff(provisional_run)

        await _progress(9, 10, "Formatting output...")
        if is_structured_output_format(request.output_format):
            primary_format = cast("Literal['json', 'toon']", request.output_format)
            artifact = persist_unified_search_artifact(
                request=request,
                plan=plan,
                execution=execution,
                primary_format=primary_format,
                search_run_id=journal.run_id,
                search_run_handoff=provisional_handoff,
            )
            if artifact_persistence_enabled() and artifact is None:
                journal.warnings.append("Search artifact persistence failed")
            completed_run = await journal.complete(execution, artifact=artifact)
            await notify_session_resources_updated(ctx)
            search_run_handoff = compact_search_run_handoff(completed_run)
            return _format_as_json(
                execution.ranked,
                plan.analysis,
                execution.stats,
                execution.relaxation_result,
                execution.deep_search_metrics,
                source_api_counts=execution.source_api_counts or None,
                source_disagreement=execution.source_disagreement,
                reproducibility_score=execution.reproducibility_score,
                research_context=execution.research_context_data,
                source_errors=execution.source_errors,
                source_metadata=execution.source_metadata,
                source_statuses=execution.source_statuses,
                counts_first=request.counts_first,
                compact_output=request.compact_output,
                include_analysis=request.show_analysis,
                include_similarity_scores=request.include_similarity_scores,
                include_next_tools=request.include_next_tools,
                include_section_provenance=request.include_section_provenance,
                output_format=request.output_format,
                artifact_manifest=artifact,
                search_run_handoff=search_run_handoff,
            )

        markdown_response = await _format_unified_results(
            execution.ranked,
            plan.analysis,
            execution.stats,
            request.show_analysis,
            execution.pubmed_total_count,
            plan.icd_matches,
            include_trials=request.include_clinical_trials,
            include_similarity_scores=request.include_similarity_scores,
            original_query=plan.analysis.original_query,
            enhanced_entities=plan.matched_entity_names or None,
            relaxation_result=execution.relaxation_result,
            deep_search_metrics=execution.deep_search_metrics,
            prefetched_trials=execution.prefetched_trials,
            source_api_counts=execution.source_api_counts or None,
            source_disagreement=execution.source_disagreement,
            reproducibility_score=execution.reproducibility_score,
            source_errors=execution.source_errors,
            source_metadata=execution.source_metadata,
            research_context_preview=execution.research_context_preview,
            counts_first=request.counts_first,
        )
        artifact = persist_unified_search_artifact(
            request=request,
            plan=plan,
            execution=execution,
            markdown_response=markdown_response,
            search_run_id=journal.run_id,
            search_run_handoff=provisional_handoff,
        )
        if artifact_persistence_enabled() and artifact is None:
            journal.warnings.append("Search artifact persistence failed")
        completed_run = await journal.complete(execution, artifact=artifact)
        await notify_session_resources_updated(ctx)
        return markdown_response + artifact_markdown_note(artifact) + search_run_markdown_note(completed_run)

    except asyncio.CancelledError:
        if journal is not None:
            await journal.cancel()
            await notify_session_resources_updated(ctx)
        raise
    except Exception as exc:
        if journal is not None:
            failed_run = await journal.fail(exc, stage="execution", retryable=True)
            await notify_session_resources_updated(ctx)
        else:
            failed_run = None
        # Never attach the raw traceback here: analyzer/provider exceptions can
        # embed the original query or credentials in their message.
        logger.error("Unified search failed (%s)", type(exc).__name__)  # noqa: TRY400 - traceback may leak query
        run_hint = _search_run_hint(failed_run)
        response = ResponseFormatter.error(
            "Unified search could not be completed.",
            suggestion=f"Review source availability and retry.{run_hint}",
            tool_name="unified_search",
            output_format=output_format,
        )
        return _attach_search_run_to_error(response, output_format=output_format, run=failed_run)


def make_mcp_unified_search_runner(
    searcher: LiteratureSearcher,
    *,
    ctx: Context | None = None,
) -> Callable[..., Any]:
    """Return a runner compatible with `UnifiedSearchService`."""

    async def _runner(**kwargs: Any) -> str:
        return await run_unified_search(searcher=searcher, ctx=ctx, **kwargs)

    return _runner


__all__ = ["make_mcp_unified_search_runner", "persist_unified_search_artifact", "run_unified_search"]
