"""Regression tests for legacy unified-search empty/error semantics."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.infrastructure.sources.base_client import APIRequestError
from pubmed_search.presentation.mcp_server.tools.unified_source_search import (
    _search_arxiv,
    _search_biorxiv,
    _search_core,
    _search_europe_pmc,
    _search_medrxiv,
    _search_pubmed,
    _search_scopus,
    _search_web_of_science,
)
from pubmed_search.shared.source_contracts import SourceAdapterCall, gather_source_adapter_calls

PRIVATE_QUERY = "private-patient-marker-7f0a"
LegacyRunner = Callable[
    [str, int, int | None, int | None],
    Awaitable[tuple[list[UnifiedArticle], int | None]],
]


async def _gather_strict_runner(source: str, runner: LegacyRunner):
    async def execute() -> tuple[list[UnifiedArticle], int | None]:
        return await runner(PRIVATE_QUERY, 5, None, None, strict=True)  # type: ignore[call-arg]

    return (await gather_source_adapter_calls([SourceAdapterCall(source=source, operation="search", execute=execute)]))[
        0
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "runner", "client_getter", "empty_payload"),
    [
        (
            "europe_pmc",
            _search_europe_pmc,
            "pubmed_search.presentation.mcp_server.tools.unified_source_search.get_europe_pmc_client",
            {"results": [], "hit_count": 0},
        ),
        (
            "core",
            _search_core,
            "pubmed_search.presentation.mcp_server.tools.unified_source_search.get_core_client",
            {"results": [], "total_hits": 0},
        ),
        (
            "scopus",
            _search_scopus,
            "pubmed_search.presentation.mcp_server.tools.unified_source_search.get_scopus_client",
            [],
        ),
        (
            "web_of_science",
            _search_web_of_science,
            "pubmed_search.presentation.mcp_server.tools.unified_source_search.get_web_of_science_client",
            [],
        ),
    ],
)
async def test_strict_legacy_provider_outage_is_error_and_empty_is_empty(
    source: str,
    runner: LegacyRunner,
    client_getter: str,
    empty_payload: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    client = MagicMock()
    client.search = AsyncMock(side_effect=RuntimeError(f"outage for {PRIVATE_QUERY}"))

    with patch(client_getter, return_value=client):
        failed = await _gather_strict_runner(source, runner)

    assert failed.status == "error"
    assert failed.items == []
    assert len(failed.errors) == 1
    assert PRIVATE_QUERY not in failed.errors[0].message
    assert PRIVATE_QUERY not in caplog.text
    assert client.search.await_args.kwargs["strict"] is True

    client.search = AsyncMock(return_value=empty_payload)
    with patch(client_getter, return_value=client):
        empty = await _gather_strict_runner(source, runner)

    assert empty.status == "empty"
    assert empty.items == []
    assert empty.errors == []
    assert client.search.await_args.kwargs["strict"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "runner"),
    [
        ("arxiv", _search_arxiv),
        ("medrxiv", _search_medrxiv),
        ("biorxiv", _search_biorxiv),
    ],
)
async def test_strict_preprint_outage_is_error_and_empty_is_empty(
    source: str,
    runner: LegacyRunner,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    searcher = MagicMock()
    searcher.search = AsyncMock(side_effect=RuntimeError(f"outage for {PRIVATE_QUERY}"))
    target = "pubmed_search.infrastructure.sources.preprints.PreprintSearcher"

    with patch(target, return_value=searcher):
        failed = await _gather_strict_runner(source, runner)

    assert failed.status == "error"
    assert PRIVATE_QUERY not in failed.errors[0].message
    assert PRIVATE_QUERY not in caplog.text
    assert searcher.search.await_args.kwargs["strict"] is True

    searcher.search = AsyncMock(return_value={"by_source": {source: []}, "errors": []})
    with patch(target, return_value=searcher):
        empty = await _gather_strict_runner(source, runner)

    assert empty.status == "empty"
    assert empty.errors == []
    assert searcher.search.await_args.kwargs["strict"] is True


@pytest.mark.asyncio
async def test_strict_pubmed_error_sentinel_is_error_and_real_empty_is_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    searcher = MagicMock()
    searcher.search = AsyncMock(return_value=[{"error": f"transport failed for {PRIVATE_QUERY}"}])

    async def failed_execute() -> tuple[list[UnifiedArticle], int | None]:
        return await _search_pubmed(searcher, PRIVATE_QUERY, 5, None, None, strict=True)

    failed = (
        await gather_source_adapter_calls(
            [SourceAdapterCall(source="pubmed", operation="search", execute=failed_execute)]
        )
    )[0]
    assert failed.status == "error"
    assert PRIVATE_QUERY not in failed.errors[0].message
    assert PRIVATE_QUERY not in caplog.text

    searcher.search = AsyncMock(return_value=[])

    async def empty_execute() -> tuple[list[UnifiedArticle], int | None]:
        return await _search_pubmed(searcher, PRIVATE_QUERY, 5, None, None, strict=True)

    empty = (
        await gather_source_adapter_calls(
            [SourceAdapterCall(source="pubmed", operation="search", execute=empty_execute)]
        )
    )[0]
    assert empty.status == "empty"
    assert empty.errors == []


@pytest.mark.asyncio
async def test_legacy_http_clients_strictly_distinguish_transport_failure_from_empty() -> None:
    from pubmed_search.infrastructure.sources.core import COREClient
    from pubmed_search.infrastructure.sources.europe_pmc import EuropePMCClient
    from pubmed_search.infrastructure.sources.preprints import ArXivClient, MedBioRxivClient
    from pubmed_search.infrastructure.sources.scopus import ScopusClient
    from pubmed_search.infrastructure.sources.web_of_science import WebOfScienceClient

    europe_pmc = EuropePMCClient()
    core = COREClient()
    arxiv = ArXivClient()
    rxiv = MedBioRxivClient()
    scopus = ScopusClient(api_key="test-key")
    web_of_science = WebOfScienceClient(api_key="test-key")
    try:
        with patch.object(europe_pmc, "_make_request", new=AsyncMock(return_value=None)):
            with pytest.raises(APIRequestError):
                await europe_pmc.search(PRIVATE_QUERY, strict=True)
        with patch.object(
            europe_pmc,
            "_make_request",
            new=AsyncMock(return_value={"hitCount": 0, "resultList": {"result": []}}),
        ):
            assert (await europe_pmc.search(PRIVATE_QUERY, strict=True))["results"] == []

        with patch.object(core, "_make_request", new=AsyncMock(return_value=None)):
            with pytest.raises(APIRequestError):
                await core.search(PRIVATE_QUERY, strict=True)
        with patch.object(
            core,
            "_make_request",
            new=AsyncMock(return_value={"totalHits": 0, "results": []}),
        ):
            assert (await core.search(PRIVATE_QUERY, strict=True))["results"] == []

        with patch.object(arxiv, "_make_request", new=AsyncMock(return_value=None)):
            with pytest.raises(APIRequestError):
                await arxiv.search(PRIVATE_QUERY, strict=True)
        empty_feed = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        with patch.object(arxiv, "_make_request", new=AsyncMock(return_value=empty_feed)):
            assert await arxiv.search(PRIVATE_QUERY, strict=True) == []

        with patch.object(rxiv, "_make_request", new=AsyncMock(return_value=None)):
            with pytest.raises(APIRequestError):
                await rxiv.search_medrxiv(PRIVATE_QUERY, strict=True)
        with patch.object(rxiv, "_make_request", new=AsyncMock(return_value={"collection": []})):
            assert await rxiv.search_biorxiv(PRIVATE_QUERY, strict=True) == []

        scopus._official_client.search_documents = AsyncMock(return_value=None)  # type: ignore[method-assign]
        with pytest.raises(APIRequestError):
            await scopus.search(PRIVATE_QUERY, strict=True)
        scopus_response = MagicMock()
        scopus_response.entries.return_value = []
        scopus._official_client.search_documents = AsyncMock(  # type: ignore[method-assign]
            return_value=scopus_response
        )
        assert await scopus.search(PRIVATE_QUERY, strict=True) == []

        web_of_science._official_client.search_documents = AsyncMock(  # type: ignore[method-assign]
            return_value=None
        )
        with pytest.raises(APIRequestError):
            await web_of_science.search(PRIVATE_QUERY, strict=True)
        web_of_science_response = MagicMock()
        web_of_science_response.hits = []
        web_of_science._official_client.search_documents = AsyncMock(  # type: ignore[method-assign]
            return_value=web_of_science_response
        )
        assert await web_of_science.search(PRIVATE_QUERY, strict=True) == []
    finally:
        await europe_pmc.close()
        await core.close()
        await arxiv.close()
        await rxiv.close()
        await scopus.close()
        await web_of_science.close()
