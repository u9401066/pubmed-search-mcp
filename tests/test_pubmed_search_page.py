"""Regression contracts for the sole typed PubMed search-page API."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.infrastructure.ncbi.search import SearchMixin


class _Searcher(SearchMixin):
    """Minimal SearchMixin host with injected Entrez operations."""


def _searcher(
    *,
    ids: list[str] | None = None,
    total: int = 0,
    articles: list[dict[str, Any]] | None = None,
) -> _Searcher:
    searcher = _Searcher()
    searcher._search_ids = AsyncMock(  # type: ignore[method-assign]
        return_value=(list(ids or []), total, "", "")
    )
    searcher.fetch_details = AsyncMock(return_value=list(articles or []))  # type: ignore[method-assign]
    return searcher


@pytest.mark.asyncio
async def test_empty_search_is_a_successful_typed_page_without_pseudo_article() -> None:
    searcher = _searcher(total=0)

    page = await searcher.search_page("rare query", limit=5)

    assert isinstance(page, SourceSearchPage)
    assert page.source == "pubmed"
    assert page.items == []
    assert page.total == 0
    assert page.query == "rare query"
    assert page.metadata["logical_query"] == "rare query"
    assert page.metadata["physical_query"] == "rare query"
    assert page.metadata["query_executed"] is True
    assert page.metadata["materialized_count"] == 0


@pytest.mark.asyncio
async def test_page_keeps_total_and_filter_provenance_outside_article_rows() -> None:
    article = {"pmid": "12345", "title": "Evidence"}
    searcher = _searcher(ids=["12345"], total=42, articles=[article])

    page = await searcher.search_page(
        "therapy",
        limit=1,
        min_year=2020,
        max_year=2024,
        species="humans",
        language="english",
    )

    assert page.items == [article]
    assert "_search_metadata" not in page.items[0]
    assert page.total == 42
    assert page.metadata["bounded"] is True
    assert page.metadata["requested_limit"] == 1
    assert page.metadata["date_contract"] == "publication_year"
    assert "2020/01/01:2024/12/31[dp]" in str(page.query)
    assert '"Humans"[MeSH]' in str(page.query)
    assert "eng[la]" in str(page.query)


@pytest.mark.asyncio
async def test_nonzero_provider_total_with_no_materialized_rows_remains_success_empty() -> None:
    searcher = _searcher(ids=["12345"], total=7, articles=[])

    page = await searcher.search_page("query", limit=1)

    assert page.items == []
    assert page.total == 7
    assert page.metadata["bounded"] is True
    assert page.metadata["materialized_count"] == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"age_group": "senior"},
        {"age_group": "Young Adult"},
        {"sex": "unknown"},
        {"species": "human"},
        {"language": "eng"},
        {"language": "English"},
        {"clinical_query": "treatment"},
        {"strategy": "newest"},
        {"detail_level": "brief"},
        {"min_year": 2025, "max_year": 2024},
        {"max_year": 2101},
        {"limit": True},
    ],
)
@pytest.mark.asyncio
async def test_invalid_low_level_inputs_fail_before_provider_io(kwargs: dict[str, Any]) -> None:
    searcher = _searcher()

    with pytest.raises(ValueError):
        await searcher.search_page("query", **kwargs)

    searcher._search_ids.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_retired_precise_date_arguments_are_not_accepted() -> None:
    searcher = _searcher()

    with pytest.raises(TypeError):
        await searcher.search_page("query", date_from="2024/01/01")  # type: ignore[call-arg]

    searcher._search_ids.assert_not_awaited()  # type: ignore[attr-defined]


def test_retired_article_list_search_method_is_absent() -> None:
    assert "search" not in SearchMixin.__dict__
    assert not hasattr(_Searcher(), "search")
