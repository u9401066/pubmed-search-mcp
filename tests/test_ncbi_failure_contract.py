"""Regression coverage for the strict NCBI infrastructure failure contract."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from pubmed_search.application.timeline.timeline_builder import TimelineBuilder, TimelineRetrievalError
from pubmed_search.infrastructure.ncbi.base import (
    NCBIInfrastructureError,
    raise_ncbi_infrastructure_error,
)
from pubmed_search.infrastructure.ncbi.search import SearchMixin
from pubmed_search.infrastructure.sources.unified_broker import _search_pubmed_adapter

PRIVATE_UPSTREAM_VALUE = "patient-query api_key=super-secret"


def _make_failure(operation: str = "search", *, retryable: bool = False) -> NCBIInfrastructureError:
    upstream = RuntimeError(PRIVATE_UPSTREAM_VALUE)
    try:
        raise_ncbi_infrastructure_error(operation, upstream)
    except NCBIInfrastructureError as exc:
        exc.retryable = retryable
        return exc


def test_ncbi_error_is_safe_but_retains_diagnostic_cause(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    upstream = RuntimeError(PRIVATE_UPSTREAM_VALUE)

    with pytest.raises(NCBIInfrastructureError) as exc_info:
        raise_ncbi_infrastructure_error("fetch_details", upstream)

    failure = exc_info.value
    assert str(failure) == "NCBI fetch_details failed"
    assert failure.operation == "fetch_details"
    assert failure.upstream_type == "RuntimeError"
    assert failure.__cause__ is upstream
    assert PRIVATE_UPSTREAM_VALUE not in str(failure)
    assert PRIVATE_UPSTREAM_VALUE not in caplog.text
    assert "RuntimeError" in caplog.text


@pytest.mark.asyncio
async def test_search_raises_typed_failure_instead_of_article_row() -> None:
    class _Searcher(SearchMixin):
        pass

    searcher = _Searcher()
    searcher._search_ids = AsyncMock(side_effect=RuntimeError(PRIVATE_UPSTREAM_VALUE))  # type: ignore[method-assign]

    with pytest.raises(NCBIInfrastructureError) as exc_info:
        await searcher.search_page("sensitive query")

    assert exc_info.value.operation == "search"
    assert exc_info.value.upstream_type == "RuntimeError"
    assert PRIVATE_UPSTREAM_VALUE not in str(exc_info.value)


@pytest.mark.asyncio
async def test_unified_pubmed_adapter_maps_outage_to_typed_error_not_empty() -> None:
    searcher = MagicMock()
    searcher.search_page = AsyncMock(side_effect=_make_failure(retryable=True))

    outcome = await _search_pubmed_adapter(searcher, "query", 5, None, None, {})

    assert outcome.status == "error"
    assert outcome.items == []
    assert outcome.errors[0].source == "pubmed"
    assert outcome.errors[0].operation == "search"
    assert outcome.errors[0].kind == "retryable"
    assert outcome.errors[0].retryable is True
    assert PRIVATE_UPSTREAM_VALUE not in outcome.errors[0].message


@pytest.mark.asyncio
async def test_timeline_wraps_pubmed_outage_without_upstream_value() -> None:
    searcher = MagicMock()
    searcher.search_page = AsyncMock(side_effect=_make_failure())
    builder = TimelineBuilder(searcher)

    with pytest.raises(TimelineRetrievalError) as exc_info:
        await builder.build_timeline("topic", include_all=True)

    assert str(exc_info.value) == "PubMed search failed"
    assert isinstance(exc_info.value.__cause__, NCBIInfrastructureError)
    assert PRIVATE_UPSTREAM_VALUE not in str(exc_info.value)
