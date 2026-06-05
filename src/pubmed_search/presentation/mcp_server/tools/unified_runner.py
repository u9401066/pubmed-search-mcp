"""Reusable runtime runner for the MCP unified_search implementation.

This module is still in presentation because it formats MCP-compatible strings,
persists MCP session artifacts, and can report FastMCP progress. The stable
Python SDK imports it lazily only when a caller actually runs unified search
without injecting a custom runner.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal, Union, cast

from pubmed_search.application.search.query_analyzer import QueryAnalyzer
from pubmed_search.application.search.semantic_enhancer import get_semantic_enhancer
from pubmed_search.application.session.artifact_envelope import build_unified_search_artifact_envelope
from pubmed_search.application.timeline import TimelineBuilder, build_research_tree
from pubmed_search.infrastructure.sources.registry import SourceSelectionError, get_source_registry

from .agent_output import is_structured_output_format
from .artifact_memory import artifact_markdown_note, artifact_persistence_enabled, persist_tool_artifact
from .tool_response import ResponseFormatter
from .tool_runtime import safe_report_progress
from .unified_execution import execute_unified_search
from .unified_formatting import _format_as_json, _format_unified_results
from .unified_pipeline import _execute_pipeline_mode
from .unified_planning import build_unified_search_plan
from .unified_request import normalize_unified_search_request
from .unified_source_search import (
    _search_arxiv,
    _search_biorxiv,
    _search_core,
    _search_europe_pmc,
    _search_medrxiv,
    _search_openalex,
    _search_pubmed,
    _search_scopus,
    _search_semantic_scholar,
    _search_web_of_science,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcp.server.fastmcp import Context

    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)


def persist_unified_search_artifact(
    *,
    request: Any,
    plan: Any,
    execution: Any,
    markdown_response: str | None = None,
    primary_format: Literal["json", "toon"] = "json",
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
            counts_first=False,
            compact_output=False,
            include_analysis=True,
            include_similarity_scores=True,
            include_next_tools=True,
            include_section_provenance=True,
            max_response_chars=None,
            output_format=primary_format,
        )
    except Exception as exc:
        logger.warning("Failed to prepare unified_search artifact payload: %s", exc)
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
    logger.info("Unified search: query='%s', limit=%s, ranking='%s'", query, limit, ranking)

    async def _progress(progress: float, total: float, message: str) -> None:
        await safe_report_progress(ctx, progress, total, message)

    try:
        if pipeline:
            return await _execute_pipeline_mode(
                pipeline,
                output_format,
                searcher,
                dry_run=dry_run,
                stop_at=stop_at,
            )

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
        except ValueError:
            return ResponseFormatter.error(
                "Empty query",
                suggestion="Provide a search query",
                example='unified_search(query="machine learning in anesthesia")',
                tool_name="unified_search",
                output_format=output_format,
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
            available_sources = source_registry_factory().list_unified_sources()
            return ResponseFormatter.error(
                str(selection_error),
                suggestion=(
                    f"Available sources: {', '.join(selection_error.available_sources)}"
                    if selection_error.available_sources
                    else f"Available sources: {', '.join(available_sources)}"
                ),
                example='unified_search(query="...", sources="auto,-semantic_scholar")',
                tool_name="unified_search",
                output_format=output_format,
            )
        except ValueError as exc:
            return ResponseFormatter.error(
                str(exc),
                suggestion="Unset PUBMED_SEARCH_DISABLED_SOURCES or specify an enabled source",
                example='unified_search(query="...", sources="pubmed")',
                tool_name="unified_search",
                output_format=output_format,
            )

        execution = await execute_unified_search(
            plan,
            searcher,
            progress=_progress,
            ctx=ctx,
            search_functions=search_functions
            or {
                "pubmed": lambda search_query, search_limit, min_year, max_year, advanced_filters: _search_pubmed(
                    searcher,
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                    **advanced_filters,
                ),
                "openalex": lambda search_query, search_limit, min_year, max_year, _advanced_filters: _search_openalex(
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                ),
                "europe_pmc": lambda search_query,
                search_limit,
                min_year,
                max_year,
                _advanced_filters: _search_europe_pmc(
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                ),
                "semantic_scholar": lambda search_query,
                search_limit,
                min_year,
                max_year,
                _advanced_filters: _search_semantic_scholar(
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                ),
                "core": lambda search_query, search_limit, min_year, max_year, _advanced_filters: _search_core(
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                ),
                "scopus": lambda search_query, search_limit, min_year, max_year, _advanced_filters: _search_scopus(
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                ),
                "web_of_science": lambda search_query,
                search_limit,
                min_year,
                max_year,
                _advanced_filters: _search_web_of_science(
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                ),
                "arxiv": lambda search_query, search_limit, min_year, max_year, _advanced_filters: _search_arxiv(
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                ),
                "medrxiv": lambda search_query, search_limit, min_year, max_year, _advanced_filters: _search_medrxiv(
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                ),
                "biorxiv": lambda search_query, search_limit, min_year, max_year, _advanced_filters: _search_biorxiv(
                    search_query,
                    search_limit,
                    min_year,
                    max_year,
                ),
            },
            timeline_builder_cls=timeline_builder_cls,
            research_tree_builder=research_tree_builder,
        )

        await _progress(9, 10, "Formatting output...")
        if is_structured_output_format(request.output_format):
            primary_format = cast("Literal['json', 'toon']", request.output_format)
            artifact = persist_unified_search_artifact(
                request=request,
                plan=plan,
                execution=execution,
                primary_format=primary_format,
            )
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
                counts_first=request.counts_first,
                compact_output=request.compact_output,
                include_analysis=request.show_analysis,
                include_similarity_scores=request.include_similarity_scores,
                include_next_tools=request.include_next_tools,
                include_section_provenance=request.include_section_provenance,
                output_format=request.output_format,
                artifact_manifest=artifact,
            )

        markdown_response = await _format_unified_results(
            execution.ranked,
            plan.analysis,
            execution.stats,
            request.show_analysis,
            execution.pubmed_total_count,
            plan.icd_matches,
            include_trials=True,
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
            research_context_preview=execution.research_context_preview,
            counts_first=request.counts_first,
        )
        artifact = persist_unified_search_artifact(
            request=request,
            plan=plan,
            execution=execution,
            markdown_response=markdown_response,
        )
        return markdown_response + artifact_markdown_note(artifact)

    except Exception as exc:
        logger.exception("Unified search failed: %s", exc)
        return f"Error: Unified search failed - {exc!s}"


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
