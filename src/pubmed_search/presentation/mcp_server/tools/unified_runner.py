"""MCP adapter for the application-owned unified-search use case.

This module owns only tool-boundary validation, progress adaptation, durable
session state, response formatting, and artifact persistence.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any, Literal, cast

from pubmed_search.application.search.query_analyzer import QueryAnalyzer
from pubmed_search.application.session.artifact_envelope import build_unified_search_artifact_envelope
from pubmed_search.application.unified.execution import execute_unified_search
from pubmed_search.application.unified.planning import build_unified_search_plan
from pubmed_search.application.unified.request import (
    normalize_unified_search_request,
    validate_unified_search_input_envelope,
)
from pubmed_search.application.unified.use_case import SourceSelectionError, UnifiedSearchUseCase
from pubmed_search.infrastructure.pubtator.semantic_adapter import get_semantic_enhancer
from pubmed_search.infrastructure.sources.registry import get_source_registry
from pubmed_search.infrastructure.sources.unified_broker import UnifiedSourceBroker
from pubmed_search.infrastructure.sources.unified_enrichment import UnifiedEnrichmentAdapter
from pubmed_search.presentation.mcp_server.session_tools import notify_session_resources_updated
from pubmed_search.shared.credential_sanitizer import redact_credential_assignments

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
from .unified_formatting import _format_as_json, _format_unified_results
from .unified_pipeline import _execute_pipeline_mode_outcome

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcp.server.mcpserver import Context

    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

    from .pipeline_tools import PipelineToolRuntime

logger = logging.getLogger(__name__)
_REJECTED_INPUT_PREVIEW_CHARS = 256


def _bounded_rejected_input(field_name: str, value: Any) -> Any:
    """Return a credential-free, bounded value for a rejected run journal."""
    if not isinstance(value, str):
        if isinstance(value, bool | float) or value is None:
            return value
        if isinstance(value, int):
            bit_length = value.bit_length()
            return value if bit_length <= 64 else f"[rejected {field_name}: integer_bits={bit_length}]"
        return f"[rejected {field_name}: type={type(value).__name__}]"
    redacted = redact_credential_assignments(value)
    if len(redacted) <= _REJECTED_INPUT_PREVIEW_CHARS:
        return redacted
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"[rejected {field_name}: length={len(value)}, sha256={digest}]"


def _rejected_request_snapshot(**values: Any) -> dict[str, Any]:
    """Build a bounded replay snapshot without retaining rejected raw input."""
    return {name: _bounded_rejected_input(name, value) for name, value in values.items() if value is not None}


def _search_run_hint(run: dict[str, Any] | None) -> str:
    """Return a truthful bounded recovery hint for an error response."""
    handoff = compact_search_run_handoff(run)
    if handoff is None:
        return ""
    if handoff.get("history_available") is False:
        return " Durable search history was unavailable; recovery is not guaranteed."
    run_id = str(handoff["run_id"])
    return f' Inspect with read_session(request={{"action":"search_run","run_id":"{run_id}"}}).'


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


async def persist_unified_search_artifact(
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
            source_errors=execution.source_errors,
            source_metadata=dict(getattr(execution, "source_metadata", {}) or {}),
            enrichment_metadata=dict(getattr(execution, "enrichment_metadata", {}) or {}),
            source_statuses=dict(getattr(execution, "source_statuses", {}) or {}),
            counts_first=False,
            compact_output=False,
            include_analysis=True,
            include_rank_scores=True,
            include_next_tools=True,
            include_section_provenance=True,
            max_response_chars=None,
            output_format=primary_format,
            search_run_handoff=search_run_handoff,
            result_filter_counts=dict(getattr(execution, "result_filter_counts", {}) or {}),
            clinical_trials_coverage=execution.clinical_trials_coverage,
            prefetched_trials=execution.prefetched_trials,
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
    return await persist_tool_artifact(
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
    limit: int = 10,
    sources: str | None = None,
    ranking: Literal["balanced", "impact", "recency", "quality"] = "balanced",
    output_format: Literal["markdown", "json", "toon"] = "markdown",
    filters: str | None = None,
    options: str | None = None,
    pipeline: str | None = None,
    dry_run: bool = False,
    stop_at: str = "",
    ctx: Context | None = None,
    analyzer_factory: Callable[[], Any] = QueryAnalyzer,
    enhancer_factory: Callable[[], Any] = get_semantic_enhancer,
    source_registry_factory: Callable[[], Any] = get_source_registry,
    search_functions: Any | None = None,
    pipeline_runtime: PipelineToolRuntime | None = None,
) -> str:
    """Run unified_search with the same behavior as the MCP tool."""

    async def _progress(progress: float, total: float, message: str) -> None:
        await safe_report_progress(ctx, progress, total, message)

    journal: SearchRunJournal | None = None
    try:
        try:
            validate_unified_search_input_envelope(
                query=query,
                limit=limit,
                sources=sources,
                ranking=ranking,
                output_format=output_format,
                filters=filters,
                options=options,
                pipeline=pipeline,
                stop_at=stop_at,
            )
        except ValueError as exc:
            safe_request = _rejected_request_snapshot(
                query=query,
                limit=limit,
                sources=sources,
                ranking=ranking,
                output_format=output_format,
                filters=filters,
                options=options,
                pipeline=pipeline,
                dry_run=dry_run,
                stop_at=stop_at,
            )
            safe_query = str(safe_request.get("query") or "[rejected query]")
            journal = await SearchRunJournal.start(query=safe_query, request=safe_request)
            failed_run = await journal.fail(exc, stage="validation", retryable=False)
            await notify_session_resources_updated(ctx)
            response_format = output_format if output_format in {"markdown", "json", "toon"} else "markdown"
            response = ResponseFormatter.error(
                str(exc),
                suggestion=(
                    "Remove credential material, reduce oversized inputs, or correct the requested output/ranking mode."
                    f"{_search_run_hint(failed_run)}"
                ),
                tool_name="unified_search",
                output_format=response_format,
            )
            return _attach_search_run_to_error(response, output_format=response_format, run=failed_run)

        query_fingerprint = hashlib.sha256(query.encode("utf-8", errors="replace")).hexdigest()[:12]
        logger.info(
            "Unified search: query_sha256=%s, query_length=%s, limit=%s, ranking='%s'",
            query_fingerprint,
            len(query),
            limit,
            ranking,
        )

        if pipeline:
            pipeline_store = pipeline_runtime.store_for_current_tenant() if pipeline_runtime is not None else None
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
            await journal.plan_pipeline(pipeline, dry_run=dry_run, stop_at=stop_at)
            pipeline_outcome = await _execute_pipeline_mode_outcome(
                pipeline,
                output_format,
                searcher,
                pipeline_store=pipeline_store,
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

        registry = source_registry_factory()
        source_broker = UnifiedSourceBroker(
            searcher=searcher,
            search_functions_override=search_functions,
        )
        use_case = UnifiedSearchUseCase(
            planner=build_unified_search_plan,
            executor=execute_unified_search,
            source_broker=source_broker,
            enrichment=UnifiedEnrichmentAdapter(),
            analyzer_factory=analyzer_factory,
            enhancer_factory=enhancer_factory,
            source_registry_factory=lambda: registry,
        )
        plan_recorded = False

        async def _record_plan(plan: Any) -> None:
            nonlocal plan_recorded
            await journal.plan(plan)
            plan_recorded = True

        try:
            outcome = await use_case.execute(
                request,
                progress=_progress,
                plan_observer=_record_plan,
            )
        except SourceSelectionError as selection_error:
            failed_run = await journal.fail(selection_error, stage="planning", retryable=False)
            await notify_session_resources_updated(ctx)
            available_sources = registry.list_unified_sources()
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
            if plan_recorded:
                raise
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

        plan = outcome.plan
        execution = outcome.execution
        await journal.record_execution(execution, plan)

        expected_status = classify_search_run_status(execution)
        provisional_run = journal.provisional_run(expected_status)
        provisional_handoff = compact_search_run_handoff(provisional_run)

        await _progress(9, 10, "Formatting output...")
        if is_structured_output_format(request.output_format):
            primary_format = cast("Literal['json', 'toon']", request.output_format)
            artifact = await persist_unified_search_artifact(
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
                source_errors=execution.source_errors,
                source_metadata=execution.source_metadata,
                enrichment_metadata=execution.enrichment_metadata,
                source_statuses=execution.source_statuses,
                counts_first=request.counts_first,
                compact_output=request.compact_output,
                include_analysis=request.show_analysis,
                include_rank_scores=request.include_rank_scores,
                include_next_tools=request.include_next_tools,
                include_section_provenance=request.include_section_provenance,
                output_format=request.output_format,
                artifact_manifest=artifact,
                search_run_handoff=search_run_handoff,
                result_filter_counts=execution.result_filter_counts,
                clinical_trials_coverage=execution.clinical_trials_coverage,
                prefetched_trials=execution.prefetched_trials,
            )

        markdown_response = await _format_unified_results(
            execution.ranked,
            plan.analysis,
            execution.stats,
            request.show_analysis,
            execution.pubmed_total_count,
            plan.icd_matches,
            include_trials=request.include_clinical_trials,
            include_rank_scores=request.include_rank_scores,
            original_query=plan.analysis.original_query,
            enhanced_entities=plan.matched_entity_names or None,
            relaxation_result=execution.relaxation_result,
            deep_search_metrics=execution.deep_search_metrics,
            prefetched_trials=execution.prefetched_trials,
            clinical_trials_coverage=execution.clinical_trials_coverage,
            source_api_counts=execution.source_api_counts or None,
            source_disagreement=execution.source_disagreement,
            reproducibility_score=execution.reproducibility_score,
            source_errors=execution.source_errors,
            source_metadata=execution.source_metadata,
            enrichment_metadata=execution.enrichment_metadata,
            counts_first=request.counts_first,
            result_filter_counts=execution.result_filter_counts,
        )
        # Markdown rendering can add a typed adjunct-format failure. Refresh
        # the provisional terminal state before embedding it in the artifact.
        expected_status = classify_search_run_status(execution)
        provisional_run = journal.provisional_run(expected_status)
        provisional_handoff = compact_search_run_handoff(provisional_run)
        artifact = await persist_unified_search_artifact(
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


__all__ = ["persist_unified_search_artifact", "run_unified_search"]
