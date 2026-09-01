"""Tests for first-class preprint integration into unified_search.

Verifies:
- article_from_preprint maps arXiv/medRxiv/bioRxiv payloads to UnifiedArticle.
- arxiv/medrxiv/biorxiv are selectable via sources= in the unified registry.
- _search_arxiv_adapter/_search_medrxiv_adapter/_search_biorxiv_adapter runners use PreprintSearcher
  and produce UnifiedArticle objects.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pubmed_search.application.unified.request import normalize_unified_search_request
from pubmed_search.domain.entities.article import (
    ArticleType,
    OpenAccessStatus,
    UnifiedArticle,
)
from pubmed_search.domain.services.article_mapper import article_from_preprint
from pubmed_search.infrastructure.sources.registry import get_source_registry
from pubmed_search.infrastructure.sources.unified_broker import (
    _search_arxiv_adapter,
    _search_biorxiv_adapter,
    _search_medrxiv_adapter,
)

# ---------------------------------------------------------------------------
# article_from_preprint mapper
# ---------------------------------------------------------------------------


class TestArticleFromPreprint:
    def test_arxiv_payload(self):
        data = {
            "id": "2301.12345",
            "title": "An arXiv Paper",
            "abstract": "Abstract text.",
            "authors": ["Alice", "Bob"],
            "published": "2023-01-15",
            "source": "arxiv",
            "categories": ["q-bio.QM"],
            "pdf_url": "https://arxiv.org/pdf/2301.12345.pdf",
            "doi": "10.1000/test",
            "source_url": "https://arxiv.org/abs/2301.12345",
        }
        art = article_from_preprint(data)
        assert isinstance(art, UnifiedArticle)
        assert art.title == "An arXiv Paper"
        assert art.arxiv_id == "2301.12345"
        assert art.doi == "10.1000/test"
        assert art.year == 2023
        assert art.article_type == ArticleType.PREPRINT
        assert art.oa_status == OpenAccessStatus.GREEN
        assert art.is_open_access is True
        assert art.primary_source == "arxiv"
        assert art.journal == "arXiv (preprint)"
        assert any(link.host_type == "preprint" and link.is_best for link in art.oa_links)
        assert len(art.authors) == 2

    def test_medrxiv_payload(self):
        data = {
            "id": "10.1101/2023.05.01.12345",
            "title": "A medRxiv Paper",
            "abstract": "Med abstract.",
            "authors": ["Carol"],
            "published": "2023-05-01",
            "source": "medrxiv",
            "categories": [],
            "pdf_url": "https://www.medrxiv.org/content/10.1101/2023.05.01.12345v1.full.pdf",
            "doi": "10.1101/2023.05.01.12345",
            "source_url": "https://www.medrxiv.org/content/10.1101/2023.05.01.12345v1",
        }
        art = article_from_preprint(data)
        assert art.arxiv_id is None  # only arxiv sets this
        assert art.doi == "10.1101/2023.05.01.12345"
        assert art.journal == "medRxiv (preprint)"
        assert art.primary_source == "medrxiv"
        assert art.article_type == ArticleType.PREPRINT

    def test_biorxiv_payload(self):
        data = {
            "title": "A bioRxiv Paper",
            "authors": [],
            "published": "2022-12-31",
            "source": "biorxiv",
            "pdf_url": "",
            "source_url": "https://www.biorxiv.org/content/10.1101/x",
        }
        art = article_from_preprint(data)
        assert art.journal == "bioRxiv (preprint)"
        assert art.primary_source == "biorxiv"
        assert art.year == 2022
        # No pdf_url, but source_url present
        assert any(link.host_type == "preprint" for link in art.oa_links)


# ---------------------------------------------------------------------------
# Registry exposes preprint sources for unified_search
# ---------------------------------------------------------------------------


class TestRegistryPreprintExposure:
    def test_preprint_sources_selectable(self):
        registry = get_source_registry()
        for key in ("arxiv", "medrxiv", "biorxiv"):
            definition = registry.get(key)
            assert definition is not None
            assert definition.selectable_in_unified is True
            assert definition.supports_primary_search is True
            assert definition.category == "preprint"

    def test_resolve_unified_sources_accepts_preprints(self):
        registry = get_source_registry()
        selection = registry.resolve_unified_sources("arxiv,medrxiv", auto_sources=[])
        assert "arxiv" in selection.sources
        assert "medrxiv" in selection.sources


class TestUnifiedPreprintFilteringPolicy:
    def test_options_preprints_includes_detected_preprints(self):
        request = normalize_unified_search_request(query="test", options="preprints")
        assert request.exclude_detected_preprints is False

    def test_explicit_preprint_source_includes_detected_preprints(self):
        request = normalize_unified_search_request(query="test", sources="pubmed,medrxiv")
        assert request.exclude_detected_preprints is False

    def test_default_sources_exclude_only_detected_preprints(self):
        request = normalize_unified_search_request(query="test", sources="pubmed,europe_pmc")
        assert request.exclude_detected_preprints is True

    def test_canonical_option_includes_detected_preprints(self):
        request = normalize_unified_search_request(query="test", options="include_detected_preprints")
        assert request.exclude_detected_preprints is False


# ---------------------------------------------------------------------------
# Source runners use PreprintSearcher and emit UnifiedArticle
# ---------------------------------------------------------------------------


def _fake_preprint_payload(source: str) -> dict:
    return {
        "id": "fake-id" if source == "arxiv" else None,
        "title": f"{source} paper",
        "abstract": "abstract",
        "authors": ["X"],
        "published": "2024-03-15",
        "source": source,
        "categories": [],
        "pdf_url": "",
        "doi": "10.1234/fake" if source != "arxiv" else None,
        "source_url": f"https://{source}.example/abs/1",
    }


@pytest.mark.asyncio
async def test_search_arxiv_runner_uses_preprint_searcher():
    with patch(
        "pubmed_search.infrastructure.sources.preprints.PreprintSearcher.search",
        new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = {
            "by_source": {"arxiv": [_fake_preprint_payload("arxiv")]},
            "total": 1,
        }
        outcome = await _search_arxiv_adapter("ml", 5, None, None, {})
    mock_search.assert_awaited_once()
    assert outcome.total_count == 1
    assert len(outcome.items) == 1
    assert outcome.items[0].primary_source == "arxiv"
    assert outcome.items[0].article_type == ArticleType.PREPRINT


@pytest.mark.asyncio
async def test_search_medrxiv_runner():
    with patch(
        "pubmed_search.infrastructure.sources.preprints.PreprintSearcher.search",
        new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = {
            "by_source": {"medrxiv": [_fake_preprint_payload("medrxiv")]},
            "total": 1,
        }
        outcome = await _search_medrxiv_adapter("covid", 5, None, None, {})
    assert len(outcome.items) == 1
    assert outcome.items[0].primary_source == "medrxiv"


@pytest.mark.asyncio
async def test_search_biorxiv_runner_filters_by_year():
    payload_old = {**_fake_preprint_payload("biorxiv"), "published": "2010-01-01"}
    payload_new = _fake_preprint_payload("biorxiv")
    with patch(
        "pubmed_search.infrastructure.sources.preprints.PreprintSearcher.search",
        new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = {
            "by_source": {"biorxiv": [payload_old, payload_new]},
            "total": 2,
        }
        outcome = await _search_biorxiv_adapter("crispr", 5, min_year=2020, max_year=None, advanced_filters={})
    assert len(outcome.items) == 1
    assert outcome.items[0].year == 2024
    assert outcome.metadata["local_filter_outcome"] == {
        "retrieved": 2,
        "excluded_out_of_range": 1,
        "excluded_unknown_year": 0,
        "eligible": 1,
    }
    assert outcome.metadata["coverage"] == {
        "corpus_total_known": False,
        "provider_window": {
            "kind": "rolling_date_feed",
            "from": outcome.metadata["physical_query"].split("/")[2],
            "to": outcome.metadata["physical_query"].split("/")[3],
        },
        "provider_result_limit": 5,
        "keyword_filter": "local_all_terms_case_insensitive",
    }


@pytest.mark.asyncio
async def test_explicit_preprint_year_range_excludes_unknown_year_with_diagnostics():
    payload_unknown = {**_fake_preprint_payload("biorxiv"), "published": ""}
    payload_known = _fake_preprint_payload("biorxiv")
    with patch(
        "pubmed_search.infrastructure.sources.preprints.PreprintSearcher.search",
        new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = {
            "by_source": {"biorxiv": [payload_unknown, payload_known]},
            "total": 2,
        }
        outcome = await _search_biorxiv_adapter(
            "crispr",
            5,
            min_year=2020,
            max_year=2025,
            advanced_filters={},
        )

    assert [article.year for article in outcome.items] == [2024]
    assert outcome.metadata["local_filter_outcome"]["excluded_unknown_year"] == 1
    assert any("unknown publication year" in warning for warning in outcome.metadata["warnings"])


@pytest.mark.asyncio
async def test_arxiv_coverage_reports_provider_query_without_claiming_corpus_total():
    with patch(
        "pubmed_search.infrastructure.sources.preprints.PreprintSearcher.search",
        new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = {
            "by_source": {"arxiv": [_fake_preprint_payload("arxiv")]},
            "total": 1,
        }
        outcome = await _search_arxiv_adapter("ml", 5, None, None, {})

    assert outcome.metadata["coverage"] == {
        "corpus_total_known": False,
        "provider_window": {"kind": "provider_query", "from": None, "to": None},
        "provider_result_limit": 5,
        "keyword_filter": "provider_query",
    }
    assert outcome.metadata["local_filter_outcome"]["eligible"] == 1


@pytest.mark.asyncio
async def test_rxiv_boolean_syntax_fails_before_provider_io():
    with patch(
        "pubmed_search.infrastructure.sources.preprints.PreprintSearcher.search",
        new_callable=AsyncMock,
    ) as mock_search:
        outcome = await _search_biorxiv_adapter(
            "crispr AND therapy",
            5,
            None,
            None,
            {},
        )

    assert outcome.status == "error"
    assert outcome.errors[0].kind == "validation"
    assert outcome.errors[0].message == "Preprint source rejected unsupported query syntax"
    assert outcome.metadata["query_executed"] is False
    assert outcome.metadata["physical_query"] is None
    mock_search.assert_not_awaited()
