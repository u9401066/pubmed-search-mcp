"""Exact provider-query provenance regressions for unified search adapters."""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.search.query_validator import QueryValidationResult
from pubmed_search.infrastructure.ncbi.search import SearchMixin
from pubmed_search.infrastructure.sources.core import COREClient
from pubmed_search.presentation.mcp_server.tools.unified_runner import run_unified_search
from pubmed_search.presentation.mcp_server.tools.unified_source_search import (
    _search_core_adapter,
    _search_preprint_source_adapter,
    _search_pubmed_adapter,
)

PRIVATE_QUERY = "private-patient-marker-8d3e"


class _SearchMixinHarness(SearchMixin):
    """Small no-network harness for the infrastructure query compiler."""

    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.executed_queries: list[str] = []

    async def _search_ids_with_retry(self, query: str, _retmax: int, _sort: str):
        self.executed_queries.append(query)
        if self.failure is not None:
            raise self.failure
        return [], 0, "", ""

    async def fetch_details(self, _ids: list[str]):
        return []


@pytest.mark.asyncio
async def test_pubmed_filtered_corrected_query_reaches_unified_source_metadata() -> None:
    searcher = _SearchMixinHarness()
    corrected_query = f'({PRIVATE_QUERY}) AND 2020/01/01:3000/12/31[dp] AND "Female"[MeSH]'

    with patch(
        "pubmed_search.application.search.query_validator.validate_query",
        return_value=QueryValidationResult(
            is_valid=False,
            errors=["repairable syntax"],
            corrected_query=corrected_query,
        ),
    ):
        result = await run_unified_search(
            searcher=searcher,  # type: ignore[arg-type]
            query=PRIVATE_QUERY,
            sources="pubmed",
            filters="year:2020-, sex:female",
            output_format="json",
            options="shallow,no_relax,no_analysis,no_scores",
        )

    metadata = json.loads(result)["source_metadata"]["pubmed"]
    assert searcher.executed_queries == [corrected_query]
    assert metadata["logical_query"] == PRIVATE_QUERY
    assert metadata["physical_query"] == corrected_query
    assert metadata["query_executed"] is True


@pytest.mark.asyncio
async def test_pubmed_failure_preserves_attempted_query_without_logging_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    searcher = _SearchMixinHarness(failure=RuntimeError(f"upstream failed for {PRIVATE_QUERY}"))
    expected_query = f'{PRIVATE_QUERY} AND 2021/01/01:3000/12/31[dp] AND "Male"[MeSH]'

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
    searcher.search = AsyncMock(side_effect=RuntimeError(f"preflight failed for {PRIVATE_QUERY}"))

    result = await _search_pubmed_adapter(searcher, PRIVATE_QUERY, 5, None, None, {})

    assert result.status == "error"
    assert result.metadata["physical_query"] is None
    assert result.metadata["query_executed"] is False
    assert PRIVATE_QUERY not in result.errors[0].message
    assert PRIVATE_QUERY not in caplog.text


@pytest.mark.asyncio
async def test_core_year_filters_use_provider_compiled_physical_query() -> None:
    client = MagicMock(spec=COREClient)
    client.compile_query.side_effect = COREClient.compile_query
    client.search = AsyncMock(return_value={"results": [], "total_hits": 0})

    with patch(
        "pubmed_search.presentation.mcp_server.tools.unified_source_search.get_core_client",
        return_value=client,
    ):
        result = await _search_core_adapter(PRIVATE_QUERY, 10, 2020, 2024, {})

    assert result.status == "empty"
    assert result.metadata["physical_query"] == (f'{PRIVATE_QUERY} AND yearPublished>="2020" AND yearPublished<="2024"')
    assert result.metadata["query_executed"] is True


@pytest.mark.asyncio
async def test_arxiv_records_rewritten_query_and_local_year_filter() -> None:
    searcher = MagicMock()
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
        strict=True,
    )
