"""Regression tests for typed unified-search adapter empty/error semantics."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.infrastructure.sources.base_client import APIRequestError
from pubmed_search.infrastructure.sources.unified_broker import (
    _search_arxiv_adapter,
    _search_biorxiv_adapter,
    _search_core_adapter,
    _search_europe_pmc_adapter,
    _search_medrxiv_adapter,
    _search_pubmed_adapter,
    _search_scopus_adapter,
    _search_web_of_science_adapter,
)
from pubmed_search.shared.source_contracts import (
    SourceAdapterCall,
    SourceAdapterError,
    SourceAdapterResult,
    execute_source_adapter_call,
)

PRIVATE_QUERY = "private-patient-marker-7f0a"
AdapterRunner = Callable[
    [str, int, int | None, int | None, dict[str, Any]],
    Awaitable[SourceAdapterResult[UnifiedArticle]],
]


async def _gather_typed_runner(source: str, runner: AdapterRunner) -> SourceAdapterResult[UnifiedArticle]:
    async def execute() -> SourceAdapterResult[UnifiedArticle]:
        return await runner(PRIVATE_QUERY, 5, None, None, {})

    return await execute_source_adapter_call(SourceAdapterCall(source=source, operation="search", execute=execute))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "runner"),
    [
        (
            "europe_pmc",
            _search_europe_pmc_adapter,
        ),
        (
            "core",
            _search_core_adapter,
        ),
        (
            "scopus",
            _search_scopus_adapter,
        ),
        (
            "web_of_science",
            _search_web_of_science_adapter,
        ),
    ],
)
async def test_typed_provider_adapter_outage_is_error_and_empty_is_empty(
    source: str,
    runner: AdapterRunner,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    failed_raw = SourceAdapterResult.failure(
        source=source,
        operation="search",
        error=SourceAdapterError(
            source=source,
            operation="search",
            message="Provider search failed safely",
            kind="unexpected",
        ),
    )
    adapter_search = AsyncMock(return_value=failed_raw)

    with patch(
        "pubmed_search.infrastructure.sources.unified_broker.search_alternate_source_adapter",
        new=adapter_search,
    ):
        failed = await _gather_typed_runner(source, runner)

    assert failed.status == "error"
    assert failed.items == []
    assert len(failed.errors) == 1
    assert PRIVATE_QUERY not in failed.errors[0].message
    assert PRIVATE_QUERY not in caplog.text
    adapter_search.assert_awaited_once_with(
        query=PRIVATE_QUERY,
        source=source,
        limit=5,
        min_year=None,
        max_year=None,
    )

    empty_raw = SourceAdapterResult.empty(source=source, operation="search")
    with patch(
        "pubmed_search.infrastructure.sources.unified_broker.search_alternate_source_adapter",
        new=AsyncMock(return_value=empty_raw),
    ):
        empty = await _gather_typed_runner(source, runner)

    assert empty.status == "empty"
    assert empty.items == []
    assert empty.errors == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "runner"),
    [
        ("arxiv", _search_arxiv_adapter),
        ("medrxiv", _search_medrxiv_adapter),
        ("biorxiv", _search_biorxiv_adapter),
    ],
)
async def test_typed_preprint_adapter_outage_is_error_and_empty_is_empty(
    source: str,
    runner: AdapterRunner,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    searcher = MagicMock()
    searcher.close = AsyncMock()
    searcher.search = AsyncMock(side_effect=RuntimeError(f"outage for {PRIVATE_QUERY}"))
    target = "pubmed_search.infrastructure.sources.preprints.PreprintSearcher"

    with patch(target, return_value=searcher):
        failed = await _gather_typed_runner(source, runner)

    assert failed.status == "error"
    assert PRIVATE_QUERY not in failed.errors[0].message
    assert PRIVATE_QUERY not in caplog.text
    assert "strict" not in searcher.search.await_args.kwargs

    searcher.close = AsyncMock()
    searcher.search = AsyncMock(return_value={"by_source": {source: []}, "errors": []})
    with patch(target, return_value=searcher):
        empty = await _gather_typed_runner(source, runner)

    assert empty.status == "empty"
    assert empty.errors == []
    assert "strict" not in searcher.search.await_args.kwargs


@pytest.mark.asyncio
async def test_strict_pubmed_malformed_row_is_error_and_real_empty_is_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    searcher = MagicMock()
    searcher.search_page = AsyncMock(
        return_value=SourceSearchPage(
            source="pubmed",
            items=[{"unexpected_payload": PRIVATE_QUERY}],
            total=1,
            query=PRIVATE_QUERY,
        )
    )

    failed = await _search_pubmed_adapter(searcher, PRIVATE_QUERY, 5, None, None, {})
    assert failed.status == "error"
    assert PRIVATE_QUERY not in failed.errors[0].message
    assert PRIVATE_QUERY not in caplog.text

    searcher.search_page = AsyncMock(return_value=SourceSearchPage.empty("pubmed", query=PRIVATE_QUERY))

    empty = await _search_pubmed_adapter(searcher, PRIVATE_QUERY, 5, None, None, {})
    assert empty.status == "empty"
    assert empty.errors == []


@pytest.mark.asyncio
async def test_http_clients_strictly_distinguish_transport_failure_from_empty() -> None:
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
                await europe_pmc.search(PRIVATE_QUERY)
        with patch.object(
            europe_pmc,
            "_make_request",
            new=AsyncMock(return_value={"hitCount": 0, "resultList": {"result": []}}),
        ):
            assert (await europe_pmc.search(PRIVATE_QUERY))["results"] == []

        with patch.object(core, "_make_request", new=AsyncMock(return_value=None)):
            with pytest.raises(APIRequestError):
                await core.search(PRIVATE_QUERY)
        with patch.object(
            core,
            "_make_request",
            new=AsyncMock(return_value={"totalHits": 0, "results": []}),
        ):
            assert (await core.search(PRIVATE_QUERY))["results"] == []

        with patch.object(arxiv, "_make_request", new=AsyncMock(return_value=None)):
            with pytest.raises(APIRequestError):
                await arxiv.search(PRIVATE_QUERY)
        empty_feed = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        with patch.object(arxiv, "_make_request", new=AsyncMock(return_value=empty_feed)):
            assert await arxiv.search(PRIVATE_QUERY) == []

        with patch.object(rxiv, "_make_request", new=AsyncMock(return_value=None)):
            with pytest.raises(APIRequestError):
                await rxiv.search_medrxiv(PRIVATE_QUERY)
        with patch.object(rxiv, "_make_request", new=AsyncMock(return_value={"collection": []})):
            assert await rxiv.search_biorxiv(PRIVATE_QUERY) == []

        scopus._official_client.search_documents = AsyncMock(return_value=None)  # type: ignore[method-assign]
        with pytest.raises(APIRequestError):
            await scopus.search_page(PRIVATE_QUERY)
        scopus_response = MagicMock()
        scopus_response.entries.return_value = []
        scopus_response.search_results.total_results = 0
        scopus_response.search_results.start_index = 0
        scopus_response.search_results.items_per_page = 10
        scopus._official_client.search_documents = AsyncMock(  # type: ignore[method-assign]
            return_value=scopus_response
        )
        assert (await scopus.search_page(PRIVATE_QUERY)).items == []

        web_of_science._official_client.search_documents = AsyncMock(  # type: ignore[method-assign]
            return_value=None
        )
        with pytest.raises(APIRequestError):
            await web_of_science.search_page(PRIVATE_QUERY)
        web_of_science_response = MagicMock()
        web_of_science_response.hits = []
        web_of_science_response.metadata.total = 0
        web_of_science_response.metadata.page = 1
        web_of_science_response.metadata.limit = 10
        web_of_science._official_client.search_documents = AsyncMock(  # type: ignore[method-assign]
            return_value=web_of_science_response
        )
        assert (await web_of_science.search_page(PRIVATE_QUERY)).items == []
    finally:
        await europe_pmc.close()
        await core.close()
        await arxiv.close()
        await rxiv.close()
        await scopus.close()
        await web_of_science.close()
