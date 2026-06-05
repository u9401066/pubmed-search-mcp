"""Research artifact envelopes and completeness audits.

The application layer owns the durable artifact contract. Presentation tools
can keep MCP responses compact while this module prepares complete files,
summary metadata, and local/source-count audits for later retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ARTIFACT_SCHEMA_VERSION = "research-artifact/v1"
DEFAULT_AUDIT_MODE = "source-counts"


@dataclass(frozen=True)
class ResearchArtifactEnvelope:
    """Files plus manifest metadata ready for ArtifactStore persistence."""

    files: dict[str, Any]
    primary_file: str
    summary: dict[str, Any]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class UnifiedSearchArtifactRequest:
    """Application-owned request snapshot for durable search artifacts."""

    query: str
    limit: int
    sources: Any
    ranking: Any
    output_format: str
    advanced_filters: dict[str, Any]
    deep_search: bool


@dataclass(frozen=True)
class UnifiedSearchArtifactPlan:
    """Application-owned search plan snapshot for durable artifacts."""

    request: UnifiedSearchArtifactRequest
    query: str
    analysis: Any
    icd_matches: list[Any]
    enhanced_query: Any
    matched_entity_names: list[str]
    user_sources: list[str]
    dispatch_sources: list[str]
    effective_min_year: int | None
    effective_max_year: int | None


@dataclass(frozen=True)
class UnifiedSearchArtifactExecution:
    """Application-owned execution snapshot for durable artifacts."""

    ranked: list[Any]
    stats: Any
    source_api_counts: dict[str, tuple[int, int | None]] | None
    source_errors: list[dict[str, Any]]
    deep_search_metrics: Any
    relaxation_result: Any
    source_disagreement: Any = None
    reproducibility_score: Any = None
    research_context_data: dict[str, Any] | None = None


@dataclass(frozen=True)
class UnifiedSearchArtifactInput:
    """Normalized input boundary for research artifact generation."""

    request: UnifiedSearchArtifactRequest
    plan: UnifiedSearchArtifactPlan
    execution: UnifiedSearchArtifactExecution


def normalize_unified_search_artifact_input(
    *,
    request: Any,
    plan: Any,
    execution: Any,
) -> UnifiedSearchArtifactInput:
    """Map tool/presentation DTOs into an application-owned artifact input."""
    if isinstance(request, UnifiedSearchArtifactRequest):
        normalized_request = request
    else:
        normalized_request = UnifiedSearchArtifactRequest(
            query=str(getattr(request, "query", "") or ""),
            limit=int(getattr(request, "limit", 0) or 0),
            sources=getattr(request, "sources", None),
            ranking=getattr(request, "ranking", ""),
            output_format=str(getattr(request, "output_format", "json") or "json"),
            advanced_filters=dict(getattr(request, "advanced_filters", {}) or {}),
            deep_search=bool(getattr(request, "deep_search", False)),
        )

    if isinstance(plan, UnifiedSearchArtifactPlan):
        normalized_plan = plan
    else:
        normalized_plan = UnifiedSearchArtifactPlan(
            request=normalized_request,
            query=str(getattr(plan, "query", "") or normalized_request.query),
            analysis=getattr(plan, "analysis", None),
            icd_matches=list(getattr(plan, "icd_matches", []) or []),
            enhanced_query=getattr(plan, "enhanced_query", None),
            matched_entity_names=[str(item) for item in (getattr(plan, "matched_entity_names", []) or [])],
            user_sources=[str(item) for item in (getattr(plan, "user_sources", []) or [])],
            dispatch_sources=[str(item) for item in (getattr(plan, "dispatch_sources", []) or [])],
            effective_min_year=getattr(plan, "effective_min_year", None),
            effective_max_year=getattr(plan, "effective_max_year", None),
        )

    if isinstance(execution, UnifiedSearchArtifactExecution):
        normalized_execution = execution
    else:
        normalized_execution = UnifiedSearchArtifactExecution(
            ranked=list(getattr(execution, "ranked", []) or []),
            stats=getattr(execution, "stats", None),
            source_api_counts=getattr(execution, "source_api_counts", None),
            source_errors=list(getattr(execution, "source_errors", []) or []),
            deep_search_metrics=getattr(execution, "deep_search_metrics", None),
            relaxation_result=getattr(execution, "relaxation_result", None),
            source_disagreement=getattr(execution, "source_disagreement", None),
            reproducibility_score=getattr(execution, "reproducibility_score", None),
            research_context_data=getattr(execution, "research_context_data", None),
        )

    return UnifiedSearchArtifactInput(
        request=normalized_request,
        plan=normalized_plan,
        execution=normalized_execution,
    )


def _value(value: Any) -> Any:
    """Return a JSON-friendly scalar for enums and simple objects."""
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str | int | float | bool):
        return enum_value
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            result = to_dict()
            return result if isinstance(result, dict) else {}
        except Exception:
            return {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def _list_attr(value: Any, attr: str) -> list[Any]:
    raw = getattr(value, attr, [])
    return list(raw) if isinstance(raw, list | tuple) else []


def _article_identifier(article: Any, name: str) -> str:
    raw = getattr(article, name, "")
    return str(raw or "").strip()


def _article_title(article: Any) -> str:
    return str(getattr(article, "title", "") or "").strip()


def _article_year(article: Any) -> int | str | None:
    year = getattr(article, "year", None)
    if year in ("", 0):
        return None
    return year


def _source_counts_payload(source_api_counts: dict[str, tuple[int, int | None]] | None) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for source, counts in (source_api_counts or {}).items():
        returned, total = counts
        payload[str(source)] = {
            "returned": int(returned or 0),
            "available": int(total) if isinstance(total, int) else None,
            "has_more": isinstance(total, int) and total > int(returned or 0),
        }
    return payload


def _strategy_result_payload(strategy_result: Any) -> dict[str, Any]:
    return {
        "name": str(getattr(strategy_result, "strategy_name", getattr(strategy_result, "name", "")) or ""),
        "query": str(getattr(strategy_result, "query", "") or ""),
        "source": str(getattr(strategy_result, "source", "") or ""),
        "articles_found": int(getattr(strategy_result, "articles_count", 0) or 0),
        "execution_time_ms": float(getattr(strategy_result, "execution_time_ms", 0.0) or 0.0),
    }


def _search_plan_payload(strategy: Any) -> dict[str, Any]:
    payload = {
        "name": str(getattr(strategy, "name", "") or ""),
        "query": str(getattr(strategy, "query", "") or ""),
        "source": str(getattr(strategy, "source", "") or ""),
        "priority": int(getattr(strategy, "priority", 0) or 0),
    }
    precision = getattr(strategy, "expected_precision", None)
    recall = getattr(strategy, "expected_recall", None)
    if precision is not None:
        payload["expected_precision"] = float(precision)
    if recall is not None:
        payload["expected_recall"] = float(recall)
    return payload


def _deep_search_payload(plan: Any, execution: Any) -> dict[str, Any]:
    enhanced_query = getattr(plan, "enhanced_query", None)
    metrics = getattr(execution, "deep_search_metrics", None)
    generated_strategies = [_search_plan_payload(strategy) for strategy in _list_attr(enhanced_query, "strategies")]
    executed_strategy_results = [_strategy_result_payload(result) for result in _list_attr(metrics, "strategy_results")]
    return {
        "enabled": bool(getattr(getattr(plan, "request", None), "deep_search", False)),
        "entities": _to_dict(enhanced_query).get("entities", []),
        "expanded_terms": _to_dict(enhanced_query).get("expanded_terms", []),
        "strategies_generated": int(getattr(metrics, "strategies_generated", len(generated_strategies)) or 0),
        "strategies_executed": int(getattr(metrics, "strategies_executed", len(executed_strategy_results)) or 0),
        "strategies_with_results": int(getattr(metrics, "strategies_with_results", 0) or 0),
        "depth_score": float(getattr(metrics, "depth_score", 0.0) or 0.0),
        "generated_strategies": generated_strategies,
        "strategy_results": executed_strategy_results,
    }


def _relaxation_payload(execution: Any) -> dict[str, Any] | None:
    relaxation = getattr(execution, "relaxation_result", None)
    if relaxation is None:
        return None
    successful = getattr(relaxation, "successful_step", None)
    return {
        "original_query": str(getattr(relaxation, "original_query", "") or ""),
        "relaxed_query": str(getattr(relaxation, "relaxed_query", "") or ""),
        "total_results": int(getattr(relaxation, "total_results", 0) or 0),
        "successful_level": getattr(successful, "level", None) if successful else None,
        "successful_action": getattr(successful, "action", None) if successful else None,
        "steps_tried": [
            {
                "level": getattr(step, "level", None),
                "action": getattr(step, "action", None),
                "description": str(getattr(step, "description", "") or ""),
                "query": str(getattr(step, "query", "") or ""),
                "result_count": int(getattr(step, "result_count", 0) or 0),
            }
            for step in _list_attr(relaxation, "steps_tried")
        ],
    }


def build_unified_search_query_strategy(*, request: Any, plan: Any, execution: Any) -> dict[str, Any]:
    """Serialize the reproducible search strategy for one unified_search run."""
    artifact_input = normalize_unified_search_artifact_input(request=request, plan=plan, execution=execution)
    request = artifact_input.request
    plan = artifact_input.plan
    execution = artifact_input.execution
    analysis = getattr(plan, "analysis", None)
    filters = {
        "min_year": getattr(plan, "effective_min_year", None),
        "max_year": getattr(plan, "effective_max_year", None),
        "advanced_filters": getattr(request, "advanced_filters", {}),
    }
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "tool": "unified_search",
        "original_query": str(getattr(analysis, "original_query", "") or getattr(request, "query", "")),
        "normalized_query": str(getattr(analysis, "normalized_query", "") or ""),
        "executed_query": str(getattr(plan, "query", "") or getattr(request, "query", "")),
        "analysis": _to_dict(analysis),
        "filters": filters,
        "requested_sources": getattr(request, "sources", None),
        "user_sources": list(getattr(plan, "user_sources", []) or []),
        "dispatch_sources": list(getattr(plan, "dispatch_sources", []) or []),
        "ranking": _value(getattr(request, "ranking", "")),
        "limit": int(getattr(request, "limit", 0) or 0),
        "icd_matches": list(getattr(plan, "icd_matches", []) or []),
        "matched_entity_names": list(getattr(plan, "matched_entity_names", []) or []),
        "source_counts": _source_counts_payload(getattr(execution, "source_api_counts", None)),
        "deep_search": _deep_search_payload(plan, execution),
        "relaxation": _relaxation_payload(execution),
    }


def _add_check(
    checks: list[dict[str, Any]],
    *,
    check: str,
    severity: Literal["pass", "info", "warn", "fail"],
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    checks.append(
        {
            "check": check,
            "severity": severity,
            "message": message,
            "details": details or {},
        }
    )


def audit_unified_search_artifact(*, request: Any, plan: Any, execution: Any) -> dict[str, Any]:
    """Build a local/source-count completeness audit for a unified_search run."""
    artifact_input = normalize_unified_search_artifact_input(request=request, plan=plan, execution=execution)
    request = artifact_input.request
    plan = artifact_input.plan
    execution = artifact_input.execution
    ranked = list(getattr(execution, "ranked", []) or [])
    stats = getattr(execution, "stats", None)
    source_counts = _source_counts_payload(getattr(execution, "source_api_counts", None))
    source_errors = list(getattr(execution, "source_errors", []) or [])
    checks: list[dict[str, Any]] = []

    expected_unique = getattr(stats, "unique_articles", None)
    requested_limit = int(getattr(request, "limit", 0) or 0)
    expected_unique_count = int(expected_unique or 0) if expected_unique is not None else None
    expected_returned_count = (
        min(expected_unique_count, requested_limit)
        if expected_unique_count is not None and requested_limit > 0
        else expected_unique_count
    )
    if expected_returned_count is not None and expected_returned_count != len(ranked):
        _add_check(
            checks,
            check="result_count_consistency",
            severity="warn",
            message="Ranked article count differs from expected returned count.",
            details={
                "ranked_count": len(ranked),
                "stats_unique_articles": expected_unique_count,
                "requested_limit": requested_limit,
                "expected_returned_count": expected_returned_count,
            },
        )
    else:
        _add_check(
            checks,
            check="result_count_consistency",
            severity="pass",
            message="Ranked article count matches expected returned count.",
            details={
                "ranked_count": len(ranked),
                "stats_unique_articles": expected_unique_count,
                "requested_limit": requested_limit,
            },
        )
        if expected_unique_count is not None and requested_limit > 0 and expected_unique_count > requested_limit:
            _add_check(
                checks,
                check="result_limit_applied",
                severity="info",
                message="The result set was intentionally capped by the requested limit.",
                details={
                    "returned": len(ranked),
                    "available_unique_articles": expected_unique_count,
                    "requested_limit": requested_limit,
                },
            )

    if source_counts:
        zero_sources = [source for source, counts in source_counts.items() if counts["returned"] == 0]
        _add_check(
            checks,
            check="source_counts_present",
            severity="pass",
            message="Per-source returned counts are present.",
            details={"sources": source_counts, "zero_return_sources": zero_sources},
        )
    else:
        _add_check(
            checks,
            check="source_counts_present",
            severity="warn",
            message="No per-source returned counts were captured for this artifact.",
        )

    if source_errors:
        _add_check(
            checks,
            check="source_errors",
            severity="warn",
            message="One or more upstream sources returned an error or partial failure.",
            details={"source_errors": source_errors},
        )
    else:
        _add_check(
            checks,
            check="source_errors",
            severity="pass",
            message="No source errors were reported.",
        )

    pmids = [_article_identifier(article, "pmid") for article in ranked if _article_identifier(article, "pmid")]
    duplicate_pmids = sorted({pmid for pmid in pmids if pmids.count(pmid) > 1})
    if duplicate_pmids:
        _add_check(
            checks,
            check="pmid_uniqueness",
            severity="warn",
            message="Duplicate PMIDs were found in the ranked result set.",
            details={"duplicate_pmids": duplicate_pmids},
        )
    else:
        _add_check(
            checks,
            check="pmid_uniqueness",
            severity="pass",
            message="No duplicate PMIDs were found in the ranked result set.",
            details={"pmid_count": len(pmids)},
        )

    missing_identifiers = [
        index
        for index, article in enumerate(ranked)
        if not (
            _article_identifier(article, "pmid")
            or _article_identifier(article, "doi")
            or _article_identifier(article, "pmc")
        )
    ]
    if missing_identifiers:
        _add_check(
            checks,
            check="missing_identifiers",
            severity="warn",
            message="Some ranked articles lack PMID, DOI, and PMC identifiers.",
            details={"article_indexes": missing_identifiers, "missing_count": len(missing_identifiers)},
        )
    else:
        _add_check(
            checks,
            check="missing_identifiers",
            severity="pass",
            message="Every ranked article has at least one stable identifier.",
        )

    missing_core_metadata = [
        index for index, article in enumerate(ranked) if not _article_title(article) or _article_year(article) is None
    ]
    if missing_core_metadata:
        _add_check(
            checks,
            check="core_metadata_presence",
            severity="info",
            message="Some ranked articles are missing title or year metadata.",
            details={"article_indexes": missing_core_metadata, "missing_count": len(missing_core_metadata)},
        )
    else:
        _add_check(
            checks,
            check="core_metadata_presence",
            severity="pass",
            message="Ranked articles have title and year metadata.",
        )

    deep = _deep_search_payload(plan, execution)
    if deep["enabled"] and deep["strategies_generated"] > deep["strategies_executed"]:
        _add_check(
            checks,
            check="deep_search_strategy_execution",
            severity="warn",
            message="Not all generated deep-search strategies were executed.",
            details={
                "strategies_generated": deep["strategies_generated"],
                "strategies_executed": deep["strategies_executed"],
            },
        )
    elif deep["enabled"]:
        _add_check(
            checks,
            check="deep_search_strategy_execution",
            severity="pass",
            message="Generated deep-search strategies were executed.",
            details={
                "strategies_generated": deep["strategies_generated"],
                "strategies_executed": deep["strategies_executed"],
            },
        )

    failures = sum(1 for item in checks if item["severity"] == "fail")
    warnings = sum(1 for item in checks if item["severity"] == "warn")
    status: Literal["pass", "warn", "fail"] = "fail" if failures else ("warn" if warnings else "pass")

    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "tool": "unified_search",
        "mode": DEFAULT_AUDIT_MODE,
        "status": status,
        "summary": {
            "status": status,
            "checks": len(checks),
            "warnings": warnings,
            "failures": failures,
        },
        "counts": {
            "requested_limit": int(getattr(request, "limit", 0) or 0),
            "ranked_articles": len(ranked),
            "pmid_count": len(pmids),
            "source_counts": source_counts,
            "total_input": int(getattr(stats, "total_input", 0) or 0),
            "unique_articles": int(getattr(stats, "unique_articles", len(ranked)) or 0),
            "duplicates_removed": int(getattr(stats, "duplicates_removed", 0) or 0),
        },
        "checks": checks,
    }


def build_unified_search_artifact_envelope(
    *,
    request: Any,
    plan: Any,
    execution: Any,
    structured_payload: str,
    markdown_response: str | None = None,
    primary_format: Literal["json", "toon"] = "json",
) -> ResearchArtifactEnvelope:
    """Build complete persisted files plus compact manifest fields."""
    artifact_input = normalize_unified_search_artifact_input(request=request, plan=plan, execution=execution)
    request = artifact_input.request
    plan = artifact_input.plan
    execution = artifact_input.execution
    primary_file = f"results.{primary_format}"
    query = str(getattr(getattr(plan, "analysis", None), "original_query", "") or getattr(request, "query", ""))
    source_summary = _source_counts_payload(getattr(execution, "source_api_counts", None))
    audit = audit_unified_search_artifact(request=request, plan=plan, execution=execution)
    strategy = build_unified_search_query_strategy(request=request, plan=plan, execution=execution)

    files: dict[str, Any] = {
        primary_file: structured_payload,
        "query_strategy.json": strategy,
        "audit.json": audit,
        "query.md": f"# Query\n\n{query}\n",
    }
    if markdown_response:
        files["response.md"] = markdown_response

    read_order = ["audit.json", "query_strategy.json", primary_file]
    if "response.md" in files:
        read_order.append("response.md")
    read_order.append("query.md")

    summary = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "query": query,
        "returned": len(list(getattr(execution, "ranked", []) or [])),
        "sources": source_summary,
        "source_errors": list(getattr(execution, "source_errors", []) or []),
        "audit": audit["summary"],
        "audit_status": audit["status"],
        "read_order": read_order,
        "token_offload": True,
        "agent_note": (
            "MCP response is a compact summary. Read artifact files for complete results, "
            "query strategy, and audit evidence."
        ),
    }
    metadata = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "artifact_role": "research_output",
        "audit_mode": DEFAULT_AUDIT_MODE,
        "output_format": getattr(request, "output_format", primary_format),
        "primary_format": primary_format,
        "ranking": _value(getattr(request, "ranking", "")),
        "limit": int(getattr(request, "limit", 0) or 0),
        "retrieval_contract": {
            "transport": "session-artifact",
            "addressing": "artifact_uri + artifact_file + offset + max_chars",
            "supports_paging": True,
        },
    }
    return ResearchArtifactEnvelope(files=files, primary_file=primary_file, summary=summary, metadata=metadata)


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "DEFAULT_AUDIT_MODE",
    "ResearchArtifactEnvelope",
    "UnifiedSearchArtifactExecution",
    "UnifiedSearchArtifactInput",
    "UnifiedSearchArtifactPlan",
    "UnifiedSearchArtifactRequest",
    "audit_unified_search_artifact",
    "build_unified_search_artifact_envelope",
    "build_unified_search_query_strategy",
    "normalize_unified_search_artifact_input",
]
