"""Exact provider-query provenance regressions for unified search adapters."""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.infrastructure.ncbi.search import SearchMixin
from pubmed_search.infrastructure.sources.unified_broker import (
    _search_core_adapter,
    _search_preprint_source_adapter,
    _search_pubmed_adapter,
)
from pubmed_search.presentation.mcp_server.tools.unified_runner import run_unified_search
from pubmed_search.shared.source_contracts import SourceAdapterResult

PRIVATE_QUERY = "private-patient-marker-8d3e"


class _SearchMixinHarness(SearchMixin):
    """Small no-network harness for the infrastructure query compiler."""

    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.executed_queries: list[str] = []

    async def _search_ids(self, query: str, _retmax: int, _sort: str):
        self.executed_queries.append(query)
        if self.failure is not None:
            raise self.failure
        return [], 0, "", ""

    async def fetch_details(self, _ids: list[str]):
        return []


@pytest.mark.asyncio
async def test_pubmed_filtered_compiled_query_reaches_unified_source_metadata() -> None:
    searcher = _SearchMixinHarness()
    compiled_query = f'({PRIVATE_QUERY}) AND 2020/01/01:2100/12/31[dp] AND "Female"[MeSH]'

    result = await run_unified_search(
        searcher=searcher,  # type: ignore[arg-type]
        query=PRIVATE_QUERY,
        sources="pubmed",
        filters="year:2020-,sex:female",
        output_format="json",
        options="shallow,no_relax,no_analysis,no_scores",
    )

    metadata = json.loads(result)["source_metadata"]["pubmed"]
    assert searcher.executed_queries == [compiled_query]
    assert metadata["logical_query"] == PRIVATE_QUERY
    assert metadata["physical_query"] == compiled_query
    assert metadata["query_executed"] is True


@pytest.mark.asyncio
async def test_pubmed_failure_preserves_attempted_query_without_logging_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    searcher = _SearchMixinHarness(failure=RuntimeError(f"upstream failed for {PRIVATE_QUERY}"))
    expected_query = f'({PRIVATE_QUERY}) AND 2021/01/01:2100/12/31[dp] AND "Male"[MeSH]'

    result = await _search_pubmed_adapter(
        searcher,  # type: ignore[arg-type]
        PRIVATE_QUERY,
        5,
        2021,
        None,
        {"sex": "male"},
    )

    assert result.status == "error"
    assert result.metadata["physical_query"] == expected_query
    assert result.metadata["query_executed"] is True
    assert PRIVATE_QUERY not in result.errors[0].message
    assert PRIVATE_QUERY not in caplog.text


@pytest.mark.asyncio
async def test_pubmed_failure_without_execution_reports_null_physical_query(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    searcher = MagicMock()
    searcher.search_page = AsyncMock(side_effect=RuntimeError(f"preflight failed for {PRIVATE_QUERY}"))

    result = await _search_pubmed_adapter(searcher, PRIVATE_QUERY, 5, None, None, {})

    assert result.status == "error"
    assert result.metadata["physical_query"] is None
    assert result.metadata["query_executed"] is False
    assert PRIVATE_QUERY not in result.errors[0].message
    assert PRIVATE_QUERY not in caplog.text


@pytest.mark.asyncio
async def test_core_year_filters_use_provider_compiled_physical_query() -> None:
    physical_query = f'{PRIVATE_QUERY} AND yearPublished>="2020" AND yearPublished<="2024"'
    raw_result = SourceAdapterResult.empty(source="core", operation="search")
    raw_result.provenance = {
        "logical_query": PRIVATE_QUERY,
        "physical_query": physical_query,
        "provider_mode": "keyword",
        "query_executed": True,
    }

    with patch(
        "pubmed_search.infrastructure.sources.unified_broker.search_alternate_source_adapter",
        new=AsyncMock(return_value=raw_result),
    ) as adapter_search:
        result = await _search_core_adapter(PRIVATE_QUERY, 10, 2020, 2024, {})

    assert result.status == "empty"
    assert result.metadata["physical_query"] == physical_query
    assert result.metadata["query_executed"] is True
    adapter_search.assert_awaited_once_with(
        query=PRIVATE_QUERY,
        source="core",
        limit=10,
        min_year=2020,
        max_year=2024,
    )


@pytest.mark.asyncio
async def test_arxiv_records_rewritten_query_and_local_year_filter() -> None:
    searcher = MagicMock()
    searcher.close = AsyncMock()
    searcher.search = AsyncMock(return_value={"by_source": {"arxiv": []}})

    with patch(
        "pubmed_search.infrastructure.sources.preprints.PreprintSearcher",
        return_value=searcher,
    ):
        result = await _search_preprint_source_adapter(
            "arxiv",
            "cancer:(therapy)",
            10,
            2020,
            2024,
            {},
        )

    assert result.status == "empty"
    assert result.metadata["physical_query"].startswith("all:cancer  therapy ")
    assert "cat:q-bio*" in result.metadata["physical_query"]
    assert result.metadata["local_filter"] == {"year_range": {"min": 2020, "max": 2024}}
    assert result.metadata["query_executed"] is True


@pytest.mark.asyncio
async def test_rxiv_records_date_request_and_explicit_local_filters() -> None:
    searcher = MagicMock()
    searcher.close = AsyncMock()
    searcher.search = AsyncMock(return_value={"by_source": {"medrxiv": []}})

    with (
        patch(
            "pubmed_search.infrastructure.sources.preprints.PreprintSearcher",
            return_value=searcher,
        ),
        patch(
            "pubmed_search.infrastructure.sources.preprints.default_rxiv_date_range",
            return_value=("2025-01-01", "2025-04-01"),
        ),
    ):
        result = await _search_preprint_source_adapter(
            "medrxiv",
            PRIVATE_QUERY,
            10,
            2020,
            None,
            {},
        )

    assert result.status == "empty"
    assert result.metadata["physical_query"] == "details/medrxiv/2025-01-01/2025-04-01/0"
    assert result.metadata["local_filter"] == {
        "query_mode": "all_terms_case_insensitive",
        "year_range": {"min": 2020, "max": None},
    }
    assert result.metadata["query_executed"] is True
    searcher.search.assert_awaited_once_with(
        query=PRIVATE_QUERY,
        sources=["medrxiv"],
        limit=10,
        categories=None,
        from_date="2025-01-01",
        to_date="2025-04-01",
    )
