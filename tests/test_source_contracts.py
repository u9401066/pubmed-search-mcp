from __future__ import annotations

import httpx

from pubmed_search.shared.async_utils import RetryableOperationError
from pubmed_search.shared.source_contracts import (
    _coerce_source_adapter_outcome,
    normalize_source_adapter_error,
)


class TestCoerceSourceAdapterOutcome:
    def test_list_outcome(self):
        result = _coerce_source_adapter_outcome("openalex", "search", [{"title": "A"}])

        assert result.source == "openalex"
        assert result.operation == "search"
        assert result.items == [{"title": "A"}]
        assert result.total_count == 1
        assert result.metadata == {}
        assert result.status == "ok"

    def test_tuple_list_and_int_outcome(self):
        result = _coerce_source_adapter_outcome("core", "search", ([{"title": "A"}], 7))

        assert result.items == [{"title": "A"}]
        assert result.total_count == 7
        assert result.metadata == {}

    def test_tuple_list_and_metadata_outcome(self):
        result = _coerce_source_adapter_outcome(
            "semantic_scholar",
            "search",
            ([{"title": "A"}], {"cursor": "next-page"}),
        )

        assert result.items == [{"title": "A"}]
        assert result.total_count == 1
        assert result.metadata == {"cursor": "next-page"}

    def test_tuple_list_int_and_metadata_outcome(self):
        result = _coerce_source_adapter_outcome(
            "pubmed",
            "search",
            ([{"title": "A"}], 42, {"total_available": 42}),
        )

        assert result.items == [{"title": "A"}]
        assert result.total_count == 42
        assert result.metadata == {"total_available": 42}


class TestNormalizeSourceAdapterError:
    def test_retryable_operation_error(self):
        error = RetryableOperationError("rate limited", retry_after=2.5, status_code=429)

        normalized = normalize_source_adapter_error("core", "search", error)

        assert normalized.kind == "retryable"
        assert normalized.retryable is True
        assert normalized.status_code == 429
        assert normalized.message == "rate limited"

    def test_http_status_error(self):
        request = httpx.Request("GET", "https://example.org")
        response = httpx.Response(503, request=request)
        error = httpx.HTTPStatusError("server error", request=request, response=response)

        normalized = normalize_source_adapter_error("openalex", "search", error)

        assert normalized.kind == "http"
        assert normalized.retryable is True
        assert normalized.status_code == 503
        assert normalized.message == "HTTP 503: Service Unavailable"

    def test_timeout_exception(self):
        request = httpx.Request("GET", "https://example.org")
        error = httpx.ReadTimeout("timed out", request=request)

        normalized = normalize_source_adapter_error("europe_pmc", "search", error)

        assert normalized.kind == "timeout"
        assert normalized.retryable is True
        assert normalized.status_code is None
        assert normalized.message == "timed out"

    def test_request_error(self):
        request = httpx.Request("GET", "https://example.org")
        error = httpx.ConnectError("connection failed", request=request)

        normalized = normalize_source_adapter_error("semantic_scholar", "search", error)

        assert normalized.kind == "transport"
        assert normalized.retryable is True
        assert normalized.status_code is None
        assert normalized.message == "connection failed"
