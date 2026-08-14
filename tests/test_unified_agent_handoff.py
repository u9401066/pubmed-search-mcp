"""Structured unified-search outcome and recovery contract."""

from __future__ import annotations

import json

from pubmed_search.application.search.query_analyzer import QueryAnalyzer
from pubmed_search.application.search.result_aggregator import AggregationStats
from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.presentation.mcp_server.tools.unified_execution import _source_error_payload
from pubmed_search.presentation.mcp_server.tools.unified_formatting import _format_as_json
from pubmed_search.shared.source_contracts import SourceAdapterError


def test_structured_result_exposes_partial_bounded_status_and_recovery_handoff() -> None:
    article = UnifiedArticle(title="Stable result", primary_source="pubmed", pmid="12345")
    payload = json.loads(
        _format_as_json(
            [article],
            QueryAnalyzer().analyze("cancer biomarkers"),
            AggregationStats(total_input=1, unique_articles=1),
            source_api_counts={"pubmed": (1, 100), "semantic_scholar": (0, None)},
            source_errors=[
                {
                    "source": "semantic_scholar",
                    "status": "rate_limited",
                    "message": "HTTP 429",
                    "retryable": True,
                }
            ],
            source_metadata={
                "pubmed": {"continuation_available": True},
                "semantic_scholar": {"continuation_available": False},
            },
            output_format="json",
            search_run_handoff={
                "run_id": "run-123",
                "status": "partial",
                "recoverable": True,
                "inspect": {
                    "tool": "read_session",
                    "arguments": {"action": "search_run", "run_id": "run-123"},
                },
            },
        )
    )

    assert payload["search_status"] == {
        "state": "partial",
        "bounded": True,
        "exhaustive": False,
        "returned": 1,
        "attempted_sources": ["pubmed", "semantic_scholar"],
        "successful_sources": ["pubmed"],
        "failed_sources": ["semantic_scholar"],
        "retryable_sources": ["semantic_scholar"],
        "continuation_available_sources": ["pubmed"],
        "unknown_completeness_sources": ["semantic_scholar"],
    }
    assert payload["search_run"]["run_id"] == "run-123"
    assert payload["search_run"]["inspect"]["tool"] == "read_session"


def test_empty_success_is_distinct_from_failed_search() -> None:
    payload = json.loads(
        _format_as_json(
            [],
            QueryAnalyzer().analyze("intentionally absent topic"),
            AggregationStats(),
            source_api_counts={"pubmed": (0, 0)},
            source_metadata={"pubmed": {"continuation_available": False}},
            output_format="json",
        )
    )

    assert payload["search_status"]["state"] == "empty"
    assert payload["search_status"]["failed_sources"] == []


def test_rate_limit_status_is_provider_agnostic() -> None:
    payload = _source_error_payload(
        SourceAdapterError(
            source="openalex",
            operation="search",
            message="HTTP 429",
            kind="http",
            retryable=True,
            status_code=429,
        )
    )

    assert payload["status"] == "rate_limited"
    assert payload["status_code"] == 429
    assert "shared cooldown" in payload["suggestion"]


def test_valid_empty_source_plus_failed_source_is_partial_not_all_failed() -> None:
    payload = json.loads(
        _format_as_json(
            [],
            QueryAnalyzer().analyze("rare bounded topic"),
            AggregationStats(),
            source_api_counts={"pubmed": (0, 0), "openalex": (0, None)},
            source_errors=[
                {
                    "source": "openalex",
                    "status": "rate_limited",
                    "message": "HTTP 429",
                    "retryable": True,
                }
            ],
            source_statuses={"pubmed": "empty", "openalex": "error"},
            output_format="json",
        )
    )

    assert payload["search_status"]["state"] == "partial"
    assert payload["search_status"]["successful_sources"] == ["pubmed"]
    assert payload["search_status"]["failed_sources"] == ["openalex"]
