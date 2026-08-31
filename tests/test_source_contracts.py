from __future__ import annotations

import asyncio
from typing import Any, cast

import httpx
import pytest

from pubmed_search.shared import source_contracts
from pubmed_search.shared.async_utils import RetryableOperationError
from pubmed_search.shared.source_contracts import (
    SourceAdapterCall,
    SourceAdapterError,
    SourceAdapterResult,
    execute_source_adapter_call,
    gather_source_adapter_calls,
    normalize_source_adapter_error,
    validate_source_adapter_result,
)


def _valid_result() -> SourceAdapterResult[str]:
    return SourceAdapterResult(
        source="pubmed",
        operation="search",
        items=["article"],
        total_count=1,
        status="ok",
    )


@pytest.mark.asyncio
async def test_gather_source_adapter_calls_soft_times_out_straggler() -> None:
    async def _fast() -> SourceAdapterResult[str]:
        return SourceAdapterResult(
            source="fast",
            operation="search",
            items=["ok"],
            total_count=1,
        )

    async def _slow() -> SourceAdapterResult[str]:
        await asyncio.Event().wait()
        return SourceAdapterResult(
            source="slow",
            operation="search",
            items=["never"],
            total_count=1,
        )

    results = await asyncio.wait_for(
        gather_source_adapter_calls(
            [
                SourceAdapterCall(source="fast", operation="search", execute=_fast),
                SourceAdapterCall(source="slow", operation="search", execute=_slow),
            ],
            per_call_timeout=0.01,
        ),
        timeout=0.1,
    )

    assert len(results) == 2
    assert results[0].status == "ok"
    assert results[0].items == ["ok"]
    assert results[1].status == "error"
    assert results[1].errors[0].kind == "timeout"
    assert results[1].errors[0].retryable is True
    assert "0.01s" in results[1].errors[0].message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "wrong_result",
    [
        pytest.param([], id="list"),
        pytest.param(object(), id="item"),
        pytest.param(None, id="none"),
        pytest.param(([{"title": "must not be accepted"}], 1), id="two-tuple"),
        pytest.param(([{"title": "must not be accepted"}], 1, {}), id="three-tuple"),
    ],
)
async def test_non_source_adapter_result_fails_closed(wrong_result: object) -> None:
    async def invalid_adapter() -> SourceAdapterResult[Any]:
        return cast("Any", wrong_result)

    result = await execute_source_adapter_call(
        SourceAdapterCall(
            source="pubmed",
            operation="search",
            execute=invalid_adapter,
        )
    )

    assert result.status == "error"
    assert result.items == []
    assert result.total_count == 0
    assert result.errors[0].kind == "unexpected"


def test_legacy_source_outcome_coercers_are_not_public_contracts() -> None:
    assert not hasattr(source_contracts, "_coerce_source_adapter_outcome")
    assert not hasattr(source_contracts, "TwoItemSourceAdapterOutcome")
    assert not hasattr(source_contracts, "ThreeItemSourceAdapterOutcome")
    assert not hasattr(source_contracts, "_require_source_adapter_result")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("source", "openalex", id="wrong-source"),
        pytest.param("operation", "fetch", id="wrong-operation"),
        pytest.param("total_count", -1, id="negative-total"),
        pytest.param("total_count", True, id="boolean-total"),
        pytest.param("total_count", 0, id="total-smaller-than-items"),
        pytest.param("items", ("article",), id="non-list-items"),
        pytest.param("status", "success", id="unknown-status"),
        pytest.param("errors", (), id="non-list-errors"),
        pytest.param("metadata", {1: "value"}, id="non-string-metadata-key"),
    ],
)
def test_result_validator_rejects_invalid_identity_counts_and_runtime_types(field: str, value: object) -> None:
    result = _valid_result()
    setattr(result, field, cast("Any", value))

    with pytest.raises((TypeError, ValueError)):
        validate_source_adapter_result(
            result,
            expected_source="pubmed",
            expected_operation="search",
        )


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(
            SourceAdapterResult(source="pubmed", operation="search", status="ok"),
            id="ok-without-items",
        ),
        pytest.param(
            SourceAdapterResult(
                source="pubmed",
                operation="search",
                items=["article"],
                total_count=1,
                status="empty",
            ),
            id="empty-with-items",
        ),
        pytest.param(
            SourceAdapterResult(
                source="pubmed",
                operation="search",
                items=["article"],
                total_count=1,
                status="partial",
            ),
            id="partial-without-errors",
        ),
        pytest.param(
            SourceAdapterResult(
                source="pubmed",
                operation="search",
                items=["article"],
                total_count=1,
                status="error",
                errors=[
                    SourceAdapterError(
                        source="pubmed",
                        operation="search",
                        message="failed",
                        kind="unexpected",
                    )
                ],
            ),
            id="error-with-items",
        ),
    ],
)
def test_result_validator_rejects_incoherent_status_items_and_errors(result: SourceAdapterResult[str]) -> None:
    with pytest.raises(ValueError):
        validate_source_adapter_result(
            result,
            expected_source="pubmed",
            expected_operation="search",
        )


def test_result_validator_accepts_all_coherent_status_shapes() -> None:
    error = SourceAdapterError(
        source="pubmed",
        operation="search",
        message="one upstream page failed",
        kind="transport",
        retryable=True,
    )
    results = [
        _valid_result(),
        SourceAdapterResult.empty(source="pubmed", operation="search"),
        SourceAdapterResult(
            source="pubmed",
            operation="search",
            items=["article"],
            total_count=1,
            status="partial",
            errors=[error],
        ),
        SourceAdapterResult.failure(source="pubmed", operation="search", error=error),
    ]

    for result in results:
        assert (
            validate_source_adapter_result(
                result,
                expected_source="pubmed",
                expected_operation="search",
            )
            is result
        )

    validation_error = SourceAdapterError(
        source="medrxiv",
        operation="search",
        message="Preprint source rejected unsupported query syntax",
        kind="validation",
    )
    validation_result = SourceAdapterResult.failure(
        source="medrxiv",
        operation="search",
        error=validation_error,
    )
    assert (
        validate_source_adapter_result(
            validation_result,
            expected_source="medrxiv",
            expected_operation="search",
        )
        is validation_result
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("source", "openalex", id="wrong-source"),
        pytest.param("operation", "fetch", id="wrong-operation"),
        pytest.param("message", 7, id="non-string-message"),
        pytest.param("kind", "parse", id="unknown-kind"),
        pytest.param("retryable", 1, id="non-boolean-retryable"),
        pytest.param("status_code", True, id="boolean-status-code"),
    ],
)
def test_result_validator_rejects_invalid_nested_error_identity_and_types(field: str, value: object) -> None:
    error = SourceAdapterError(
        source="pubmed",
        operation="search",
        message="upstream failed",
        kind="unexpected",
    )
    object.__setattr__(error, field, value)
    result = SourceAdapterResult(
        source="pubmed",
        operation="search",
        status="error",
        errors=[error],
    )

    with pytest.raises(TypeError):
        validate_source_adapter_result(
            result,
            expected_source="pubmed",
            expected_operation="search",
        )


@pytest.mark.asyncio
async def test_gather_fails_closed_on_result_provenance_mismatch() -> None:
    async def wrong_source() -> SourceAdapterResult[str]:
        return SourceAdapterResult.empty(source="openalex", operation="search")

    results = await gather_source_adapter_calls(
        [SourceAdapterCall(source="pubmed", operation="search", execute=wrong_source)]
    )

    assert len(results) == 1
    assert results[0].source == "pubmed"
    assert results[0].operation == "search"
    assert results[0].status == "error"
    assert results[0].errors[0].source == "pubmed"
    assert results[0].errors[0].operation == "search"
    assert results[0].errors[0].message == "Source adapter failed"


class TestNormalizeSourceAdapterError:
    def test_retryable_operation_error(self):
        error = RetryableOperationError("rate limited", retry_after=2.5, status_code=429)

        normalized = normalize_source_adapter_error("core", "search", error)

        assert normalized.kind == "retryable"
        assert normalized.retryable is True
        assert normalized.status_code == 429
        assert normalized.message == "Upstream request failed"

    def test_http_status_error(self):
        request = httpx.Request("GET", "https://example.org")
        response = httpx.Response(503, request=request)
        error = httpx.HTTPStatusError("server error", request=request, response=response)

        normalized = normalize_source_adapter_error("openalex", "search", error)

        assert normalized.kind == "http"
        assert normalized.retryable is True
        assert normalized.status_code == 503
        assert normalized.message == "Upstream returned HTTP 503"

    def test_timeout_exception(self):
        request = httpx.Request("GET", "https://example.org")
        error = httpx.ReadTimeout("timed out", request=request)

        normalized = normalize_source_adapter_error("europe_pmc", "search", error)

        assert normalized.kind == "timeout"
        assert normalized.retryable is True
        assert normalized.status_code is None
        assert normalized.message == "Upstream request timed out"

    def test_builtin_timeout_exception(self):
        normalized = normalize_source_adapter_error(
            "openalex",
            "search",
            TimeoutError("upstream timed out"),
        )

        assert normalized.kind == "timeout"
        assert normalized.retryable is True
        assert normalized.status_code is None
        assert normalized.message == "Upstream request timed out"

    def test_request_error(self):
        request = httpx.Request("GET", "https://example.org")
        error = httpx.ConnectError("connection failed", request=request)

        normalized = normalize_source_adapter_error("semantic_scholar", "search", error)

        assert normalized.kind == "transport"
        assert normalized.retryable is True
        assert normalized.status_code is None
        assert normalized.message == "Upstream transport failed"

    def test_request_error_does_not_expose_query_or_credentials(self):
        request = httpx.Request(
            "GET",
            "https://api.example.test/search?query=rare-patient-phenotype&api_key=SENTINEL",
        )
        error = httpx.ConnectError(
            "failed https://api.example.test/search?query=rare-patient-phenotype&api_key=SENTINEL Bearer SECRET-TOKEN",
            request=request,
        )

        normalized = normalize_source_adapter_error("semantic_scholar", "search", error)

        assert normalized.message == "Upstream transport failed"
        assert "rare-patient-phenotype" not in normalized.message
        assert "SENTINEL" not in normalized.message
        assert "SECRET-TOKEN" not in normalized.message

    def test_unexpected_error_does_not_expose_url_secret_or_local_path(self):
        error = RuntimeError(
            "failed https://api.example.test/private?token=SENTINEL while reading /home/researcher/private-query.json"
        )

        normalized = normalize_source_adapter_error("core", "search", error)

        assert normalized.kind == "unexpected"
        assert normalized.message == "Source adapter failed"
        assert "api.example.test" not in normalized.message
        assert "SENTINEL" not in normalized.message
        assert "/home/researcher" not in normalized.message
