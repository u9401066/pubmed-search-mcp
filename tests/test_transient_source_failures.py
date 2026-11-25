"""Transient provider failures stay retryable all the way to the agent.

Regression for the 2026-11-25 Claude Code harness pilot (finding F2): a
transient NCBI ``URLError`` during
``unified_search(query=<boolean>, sources="pubmed", limit=30,
filters="age_group:adult", output_format="json")`` was not retried, then
surfaced as ``kind="unexpected"``, ``retryable=false``, an empty
``retryable_sources`` and a ``next_tools`` entry for query rewriting. The
identical call succeeded on rerun. Only the Entrez/network boundary is faked.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import socket
import ssl
import time
from email.message import Message
from typing import Any, NoReturn
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError, URLError

import httpx
import pytest

from pubmed_search.application.search.query_analyzer import AnalyzedQuery, QueryComplexity, QueryIntent
from pubmed_search.application.search.semantic_enhancer import SemanticEnhancer
from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.infrastructure.ncbi.base import (
    NCBIInfrastructureError,
    execute_entrez_operation,
    raise_ncbi_infrastructure_error,
)
from pubmed_search.infrastructure.sources import search_alternate_source_adapter
from pubmed_search.infrastructure.sources.base_client import APIRequestError
from pubmed_search.infrastructure.sources.unified_broker import _search_pubmed_adapter
from pubmed_search.presentation.mcp_server.tools.unified_runner import run_unified_search
from pubmed_search.shared.async_utils import RetryableOperationError
from pubmed_search.shared.exceptions import is_retryable_error
from pubmed_search.shared.source_contracts import normalize_source_adapter_error
from pubmed_search.shared.transient_errors import classify_transient_error

PILOT_QUERY = (
    "(bispectral index OR processed EEG OR patient state index OR spectral entropy) AND "
    "(post-anesthesia care unit OR PACU OR emergence from general anesthesia) AND "
    "(emergence delirium OR recovery of consciousness OR length of stay)"
)
PRIVATE_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?term=bispectral"
    "&email=person%40example.org&api_key=SENTINEL-KEY"
)


def _dns_failure() -> URLError:
    return URLError(socket.gaierror(11001, f"getaddrinfo failed for {PRIVATE_URL}"))


def _connection_reset() -> URLError:
    return URLError(
        ConnectionResetError(10054, f"An existing connection was forcibly closed by the remote host {PRIVATE_URL}")
    )


def _http_error(status: int) -> HTTPError:
    return HTTPError(PRIVATE_URL, status, "upstream reason", Message(), None)


TRANSIENT_NETWORK_FAILURES = [
    pytest.param(_dns_failure, "transport", id="urlerror-dns"),
    pytest.param(_connection_reset, "transport", id="urlerror-connection-reset"),
    pytest.param(lambda: URLError(TimeoutError("timed out")), "timeout", id="urlerror-socket-timeout"),
    pytest.param(lambda: URLError("timed out"), "timeout", id="urlerror-timeout-text"),
    pytest.param(
        lambda: http.client.RemoteDisconnected("Remote end closed connection without response"),
        "transport",
        id="remote-disconnected",
    ),
    pytest.param(lambda: http.client.IncompleteRead(b"<eSearchResult>"), "transport", id="incomplete-read"),
    pytest.param(lambda: ssl.SSLEOFError(8, "EOF occurred in violation of protocol"), "transport", id="ssl-eof"),
    pytest.param(lambda: TimeoutError("timed out"), "timeout", id="socket-timeout"),
]

NON_TRANSIENT_FAILURES = [
    pytest.param(lambda: ValueError("query failed PubMed syntax validation"), id="validation"),
    pytest.param(lambda: TypeError("NCBI returned an invalid article collection"), id="schema"),
    pytest.param(lambda: URLError("unknown url type: htps"), id="urlerror-caller-bug"),
    pytest.param(
        lambda: URLError(ssl.SSLCertVerificationError(1, "certificate verify failed")),
        id="urlerror-certificate",
    ),
    pytest.param(lambda: _http_error(400), id="http-400"),
    pytest.param(lambda: ValueError("timeout must be positive"), id="programming-error-mentioning-timeout"),
]


class _ComparisonAnalyzer:
    """The pilot query was analysed as moderate/comparison."""

    def analyze(self, query: str) -> AnalyzedQuery:
        return AnalyzedQuery(
            original_query=query,
            normalized_query=query,
            complexity=QueryComplexity.MODERATE,
            intent=QueryIntent.COMPARISON,
        )


class _NullResolver:
    async def resolve_entity(self, _text: str) -> None:
        return None


def _offline_enhancer() -> SemanticEnhancer:
    return SemanticEnhancer(entity_resolver=_NullResolver())


def _raise_ncbi(upstream: Exception) -> NoReturn:
    """Raise exactly what LiteratureSearcher.search_page raises for *upstream*."""
    raise_ncbi_infrastructure_error(
        "search",
        upstream,
        execution_metadata={"physical_query": PILOT_QUERY, "query_executed": True},
    )


def _failing_page(failure: Any) -> AsyncMock:
    searcher = AsyncMock()

    async def search_page(**_kwargs: Any) -> SourceSearchPage[dict[str, Any]]:
        _raise_ncbi(failure())

    searcher.search_page.side_effect = search_page
    return searcher


async def _run_pilot_call(searcher: AsyncMock, *, output_format: str = "json") -> str:
    with patch(
        "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
        new_callable=AsyncMock,
        return_value=[],
    ):
        return await run_unified_search(
            searcher=searcher,
            query=PILOT_QUERY,
            sources="pubmed",
            limit=30,
            filters="age_group:adult",
            output_format=output_format,  # type: ignore[arg-type]
            analyzer_factory=_ComparisonAnalyzer,
            enhancer_factory=_offline_enhancer,
        )


# ---------------------------------------------------------------------------
# Classification and the Entrez transport kernel
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("failure", "kind"), TRANSIENT_NETWORK_FAILURES)
def test_network_failures_are_classified_transient_without_their_message(failure: Any, kind: str) -> None:
    transient = classify_transient_error(failure())

    assert transient is not None
    assert transient.kind == kind
    assert "SENTINEL" not in repr(transient)
    assert is_retryable_error(failure()) is True


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
def test_retryable_http_statuses_are_transient(status: int) -> None:
    transient = classify_transient_error(_http_error(status))

    assert transient is not None
    assert (transient.kind, transient.status_code) == ("http", status)


@pytest.mark.parametrize("failure", NON_TRANSIENT_FAILURES)
def test_programming_and_permanent_errors_are_not_transient(failure: Any) -> None:
    assert classify_transient_error(failure()) is None


@pytest.mark.parametrize(("failure", "_kind"), TRANSIENT_NETWORK_FAILURES)
async def test_entrez_operation_retries_a_transient_network_failure(failure: Any, _kind: str) -> None:
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise failure()
        return "esearch-ok"

    assert await execute_entrez_operation(operation, max_attempts=3, base_delay=0.01) == "esearch-ok"
    assert calls == 2


@pytest.mark.parametrize("failure", NON_TRANSIENT_FAILURES)
async def test_entrez_operation_does_not_retry_programming_errors(failure: Any) -> None:
    calls = 0
    expected = type(failure())

    async def operation() -> NoReturn:
        nonlocal calls
        calls += 1
        raise failure()

    with pytest.raises(expected):
        await execute_entrez_operation(operation, max_attempts=3, base_delay=0.01)
    assert calls == 1


async def test_entrez_retries_stay_inside_the_total_timeout_budget() -> None:
    calls = 0

    async def operation() -> NoReturn:
        nonlocal calls
        calls += 1
        raise _connection_reset()

    started = time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        # A 4-8 s backoff cannot fit in a 0.5 s total budget: fail fast, no sleep.
        await execute_entrez_operation(operation, timeout=0.5, total_timeout=0.5, max_attempts=3, base_delay=8.0)
    assert calls == 1
    assert time.monotonic() - started < 2.0


# ---------------------------------------------------------------------------
# NCBI boundary -> PubMed adapter -> shared adapter error contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("failure", "kind"), TRANSIENT_NETWORK_FAILURES)
def test_ncbi_boundary_marks_network_failures_retryable(failure: Any, kind: str) -> None:
    with pytest.raises(NCBIInfrastructureError) as caught:
        _raise_ncbi(failure())

    error = caught.value
    assert error.retryable is True
    assert error.failure_kind == kind
    assert "SENTINEL" not in str(error)
    assert "person%40example.org" not in str(error)


def test_ncbi_boundary_keeps_http_503_after_exhausted_retries_retryable() -> None:
    with pytest.raises(NCBIInfrastructureError) as caught:
        _raise_ncbi(RetryableOperationError("NCBI HTTP 503", status_code=503))

    assert (caught.value.retryable, caught.value.failure_kind, caught.value.status_code) == (True, "http", 503)


def test_ncbi_backend_unavailable_message_is_retryable() -> None:
    with pytest.raises(NCBIInfrastructureError) as caught:
        _raise_ncbi(RuntimeError("Search Backend failed: Database is not supported"))

    assert (caught.value.retryable, caught.value.failure_kind) == (True, "retryable")


async def test_pubmed_adapter_reports_the_pilot_urlerror_as_retryable_transport() -> None:
    searcher = _failing_page(_dns_failure)

    result = await _search_pubmed_adapter(searcher, PILOT_QUERY, 30, None, None, {"age_group": "adult"})

    assert result.status == "error"
    (error,) = result.errors
    assert (error.kind, error.retryable) == ("transport", True)
    assert error.message == "Upstream transport failed (URLError)"
    assert result.metadata["query_executed"] is True


@pytest.mark.parametrize(
    ("failure", "kind", "message"),
    [
        (lambda: URLError(TimeoutError("timed out")), "timeout", "Upstream request timed out (URLError)"),
        (
            lambda: RetryableOperationError("NCBI HTTP 503", status_code=503),
            "retryable",
            "Upstream request failed (HTTP 503)",
        ),
        (
            lambda: RuntimeError("Search Backend failed: temporarily unavailable"),
            "retryable",
            "Upstream service temporarily unavailable",
        ),
    ],
)
async def test_pubmed_adapter_names_each_transient_class(failure: Any, kind: str, message: str) -> None:
    result = await _search_pubmed_adapter(_failing_page(failure), PILOT_QUERY, 30, None, None, {})

    (error,) = result.errors
    assert (error.kind, error.retryable, error.message) == (kind, True, message)


@pytest.mark.parametrize("failure", NON_TRANSIENT_FAILURES)
async def test_pubmed_adapter_keeps_programming_errors_unexpected(failure: Any) -> None:
    result = await _search_pubmed_adapter(_failing_page(failure), PILOT_QUERY, 30, None, None, {})

    (error,) = result.errors
    assert (error.kind, error.retryable, error.message) == ("unexpected", False, "Source adapter failed")


@pytest.mark.parametrize(("reason", "kind"), [("transport", "transport"), ("timeout", "timeout")])
async def test_httpx_backed_sources_on_the_same_broker_path_are_retryable(reason: str, kind: str) -> None:
    client = AsyncMock()
    client.search.side_effect = APIRequestError("Europe PMC", reason=reason)  # type: ignore[arg-type]

    with patch("pubmed_search.infrastructure.sources.get_europe_pmc_client", return_value=client):
        result = await search_alternate_source_adapter("bispectral index", "europe_pmc")

    (error,) = result.errors
    assert (error.kind, error.retryable) == (kind, True)


@pytest.mark.parametrize("reason", [None, "invalid_response", "too_large"])
async def test_httpx_backed_sources_keep_permanent_failures_unexpected(reason: str | None) -> None:
    client = AsyncMock()
    client.search.side_effect = APIRequestError("Europe PMC", reason=reason)  # type: ignore[arg-type]

    with patch("pubmed_search.infrastructure.sources.get_europe_pmc_client", return_value=client):
        result = await search_alternate_source_adapter("bispectral index", "europe_pmc")

    (error,) = result.errors
    assert (error.kind, error.retryable) == ("unexpected", False)


def test_raw_stdlib_and_httpx_failures_normalize_identically() -> None:
    request = httpx.Request("GET", PRIVATE_URL)
    stdlib = normalize_source_adapter_error("pubmed", "search", _connection_reset())
    via_httpx = normalize_source_adapter_error("openalex", "search", httpx.ConnectError(PRIVATE_URL, request=request))

    assert (stdlib.kind, stdlib.retryable) == (via_httpx.kind, via_httpx.retryable) == ("transport", True)
    assert stdlib.message == "Upstream transport failed (URLError)"
    assert via_httpx.message == "Upstream transport failed (ConnectError)"


# ---------------------------------------------------------------------------
# End to end: the pilot call through run_unified_search
# ---------------------------------------------------------------------------


async def test_pilot_transient_failure_is_retryable_and_next_tools_repeat_the_same_call() -> None:
    searcher = _failing_page(_dns_failure)

    raw = await _run_pilot_call(searcher)
    payload = json.loads(raw)

    status = payload["search_status"]
    assert status["state"] == "failed"
    assert status["failed_sources"] == ["pubmed"]
    assert status["retryable_sources"] == ["pubmed"]
    (error,) = payload["source_errors"]
    assert (error["source"], error["kind"], error["retryable"]) == ("pubmed", "transport", True)
    assert error["message"] == "Upstream transport failed (URLError)"
    assert "repeat the same unified_search call" in error["suggestion"]

    first = payload["next_tools"][0]
    assert first["tool"] == "unified_search"
    assert first["command"] == (
        f'unified_search(query="{PILOT_QUERY}", limit=30, sources="pubmed", '
        'filters="age_group:adult", output_format="json")'
    )
    assert "transient" in first["reason"]
    assert payload["next_commands"][0] == first["command"]
    assert "generate_search_queries" not in {tool["tool"] for tool in payload["next_tools"]}
    assert payload["broadening"]["blocked_reason"] == "exact_tier_failed"
    for secret in ("SENTINEL", "person%40example.org", "getaddrinfo failed for"):
        assert secret not in raw


async def test_pilot_transient_failure_markdown_tells_the_agent_to_repeat_the_call() -> None:
    raw = await _run_pilot_call(_failing_page(_connection_reset), output_format="markdown")

    assert "**Source warnings**: pubmed error: Transient upstream failure, not a query problem" in raw
    assert "SENTINEL" not in raw


async def test_non_transient_failure_keeps_the_existing_next_tools() -> None:
    raw = await _run_pilot_call(_failing_page(lambda: TypeError("NCBI returned an invalid article collection")))
    payload = json.loads(raw)

    (error,) = payload["source_errors"]
    assert (error["kind"], error["retryable"]) == ("unexpected", False)
    assert "suggestion" not in error
    assert payload["search_status"]["retryable_sources"] == []
    assert [tool["tool"] for tool in payload["next_tools"]] == ["generate_search_queries"]


async def test_transient_failure_with_partial_results_still_puts_the_retry_first() -> None:
    pages: list[Any] = [
        SourceSearchPage(
            source="pubmed",
            items=[{"pmid": "40279265", "title": "Electroencephalogram correlates of delayed emergence"}],
            total=1,
            query=PILOT_QUERY,
        ),
    ]

    async def search_page(**_kwargs: Any) -> SourceSearchPage[dict[str, Any]]:
        if pages:
            return pages.pop(0)
        _raise_ncbi(_connection_reset())

    searcher = AsyncMock()
    searcher.search_page.side_effect = search_page

    with patch(
        "pubmed_search.infrastructure.sources.unified_broker._search_europe_pmc_adapter",
        new=AsyncMock(side_effect=APIRequestError("Europe PMC", reason="timeout")),
    ):
        raw = await run_unified_search(
            searcher=searcher,
            query=PILOT_QUERY,
            sources="pubmed,europe_pmc",
            limit=30,
            output_format="json",
            options="shallow,no_relax",
            analyzer_factory=_ComparisonAnalyzer,
            enhancer_factory=_offline_enhancer,
        )
    payload = json.loads(raw)

    assert payload["search_status"]["state"] == "partial"
    assert payload["search_status"]["retryable_sources"] == ["europe_pmc"]
    assert payload["next_tools"][0]["command"] == (
        f'unified_search(query="{PILOT_QUERY}", limit=30, sources="pubmed,europe_pmc", '
        'options="shallow,no_relax", output_format="json")'
    )
    # Partial results keep the ordinary follow-ups after the retry.
    assert "generate_search_queries" in {tool["tool"] for tool in payload["next_tools"]}
