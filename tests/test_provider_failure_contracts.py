"""Strict failure contracts for provider methods used by MCP/application flows."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.infrastructure.sources.base_client import APIRequestError
from pubmed_search.infrastructure.sources.clinical_trials import ClinicalTrialsClient
from pubmed_search.infrastructure.sources.core import COREClient
from pubmed_search.infrastructure.sources.europe_pmc import EuropePMCClient
from pubmed_search.infrastructure.sources.openalex import OpenAlexClient
from pubmed_search.infrastructure.sources.preprints import ArXivClient, MedBioRxivClient
from pubmed_search.infrastructure.sources.semantic_scholar import SemanticScholarClient
from pubmed_search.shared.async_utils import RetryableOperationError

PRIVATE_MARKERS = (
    "provider-secret-83d9",
    "https://private.example/patient?q=provider-secret-83d9",
    "/srv/private/provider-secret-83d9.json",
)
PRIVATE_FAILURE = RuntimeError(" | ".join(PRIVATE_MARKERS))


ProviderCall = Callable[[], Awaitable[Any]]


async def _assert_sanitized_failure(
    client: Any,
    call: ProviderCall,
    caplog: pytest.LogCaptureFixture,
    *,
    request_method: str = "_make_request",
) -> None:
    caplog.clear()
    with patch.object(client, request_method, new=AsyncMock(side_effect=PRIVATE_FAILURE)):
        with pytest.raises(APIRequestError) as exc_info:
            await call()

    public_text = str(exc_info.value)
    for marker in PRIVATE_MARKERS:
        assert marker not in public_text
        assert marker not in caplog.text


@pytest.mark.asyncio
async def test_provider_failures_are_typed_and_do_not_leak_private_input(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every active provider boundary must fail closed with a safe message."""

    caplog.set_level(logging.DEBUG)
    clients_and_calls: list[tuple[Any, ProviderCall]] = []
    europe_pmc = EuropePMCClient()
    core = COREClient()
    semantic_scholar = SemanticScholarClient()
    openalex = OpenAlexClient()
    arxiv = ArXivClient()
    rxiv = MedBioRxivClient()
    clients_and_calls.extend(
        [
            (europe_pmc, lambda: europe_pmc.get_citations("MED", "123")),
            (core, lambda: core.search("query")),
            (semantic_scholar, lambda: semantic_scholar.get_citations("paper")),
            (openalex, lambda: openalex.get_citations("W1")),
            (arxiv, lambda: arxiv.search("query")),
            (rxiv, lambda: rxiv.search_medrxiv("query")),
        ]
    )

    try:
        for client, call in clients_and_calls:
            await _assert_sanitized_failure(client, call, caplog)
    finally:
        for client, _call in clients_and_calls:
            await client.close()

    clinical_trials = ClinicalTrialsClient()
    try:
        await _assert_sanitized_failure(
            clinical_trials,
            lambda: clinical_trials.search("query"),
            caplog,
            request_method="_execute_request",
        )
    finally:
        await clinical_trials.close()


@pytest.mark.asyncio
async def test_retryable_provider_failure_keeps_metadata_but_not_raw_message() -> None:
    client = EuropePMCClient()
    try:
        upstream = RetryableOperationError(
            " | ".join(PRIVATE_MARKERS),
            retry_after=7.0,
            status_code=503,
        )
        with patch.object(client, "_make_request", new=AsyncMock(side_effect=upstream)):
            with pytest.raises(RetryableOperationError) as exc_info:
                await client.get_references("MED", "123")

        assert str(exc_info.value) == "Europe PMC request failed"
        assert exc_info.value.retry_after == 7.0
        assert exc_info.value.status_code == 503
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_empty_payloads_remain_successful_empty_results() -> None:
    europe_pmc = EuropePMCClient()
    core = COREClient()
    semantic_scholar = SemanticScholarClient()
    openalex = OpenAlexClient()
    arxiv = ArXivClient()
    rxiv = MedBioRxivClient()
    try:
        with patch.object(
            europe_pmc,
            "_make_request",
            new=AsyncMock(return_value={"hitCount": 0, "resultList": {"result": []}}),
        ):
            assert (await europe_pmc.search("query"))["results"] == []
        with patch.object(
            core,
            "_make_request",
            new=AsyncMock(return_value={"totalHits": 0, "results": []}),
        ):
            assert (await core.search("query"))["results"] == []
        with patch.object(
            semantic_scholar,
            "_make_request",
            new=AsyncMock(return_value={"data": []}),
        ):
            assert await semantic_scholar.get_citations("paper") == []
        with patch.object(openalex, "_make_request", new=AsyncMock(return_value={"results": []})):
            assert await openalex.get_citations("W1") == []
        with patch.object(
            arxiv,
            "_make_request",
            new=AsyncMock(return_value='<feed xmlns="http://www.w3.org/2005/Atom"></feed>'),
        ):
            assert await arxiv.search("query") == []
        with patch.object(rxiv, "_make_request", new=AsyncMock(return_value={"collection": []})):
            assert await rxiv.search_biorxiv("query") == []
    finally:
        for client in (europe_pmc, core, semantic_scholar, openalex, arxiv, rxiv):
            await client.close()


@pytest.mark.asyncio
async def test_clinical_trials_404_is_not_found_but_other_failures_are_not_empty() -> None:
    client = ClinicalTrialsClient()
    not_found = MagicMock(status_code=404)
    try:
        with patch.object(client, "_execute_request", new=AsyncMock(return_value=not_found)):
            assert await client.get_study("NCT00000000") is None

        with patch.object(client, "_execute_request", new=AsyncMock(side_effect=APIRequestError("ClinicalTrials.gov"))):
            with pytest.raises(APIRequestError):
                await client.get_study("NCT00000000")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_schema_drift_is_not_reported_as_no_results() -> None:
    clients_and_calls: list[tuple[Any, ProviderCall]] = []
    europe_pmc = EuropePMCClient()
    core = COREClient()
    semantic_scholar = SemanticScholarClient()
    openalex = OpenAlexClient()
    rxiv = MedBioRxivClient()
    clients_and_calls.extend(
        [
            (europe_pmc, lambda: europe_pmc.search("query")),
            (core, lambda: core.search("query")),
            (semantic_scholar, lambda: semantic_scholar.get_citations("paper")),
            (openalex, lambda: openalex.get_citations("W1")),
            (rxiv, lambda: rxiv.search_medrxiv("query")),
        ]
    )
    try:
        for client, call in clients_and_calls:
            with patch.object(client, "_make_request", new=AsyncMock(return_value={})):
                with pytest.raises(APIRequestError):
                    await call()
    finally:
        for client, _call in clients_and_calls:
            await client.close()
