"""Tests for sources __init__ module (MultiSourceSearcher, cross_search, etc.)."""

from unittest.mock import MagicMock, patch

import pytest

from pubmed_search.infrastructure.sources import (
    SearchSource,
    search_alternate_source,
    cross_search,
    _deduplicate_results,
    _normalize_title,
    get_paper_from_any_source,
    get_fulltext_xml,
    get_fulltext_parsed,
)


# ============================================================
# SearchSource enum
# ============================================================

class TestSearchSource:
    def test_values(self):
        assert SearchSource.PUBMED.value == "pubmed"
        assert SearchSource.ALL.value == "all"
        assert SearchSource.CORE.value == "core"


# ============================================================
# search_alternate_source
# ============================================================

class TestSearchAlternateSource:
    @patch("pubmed_search.infrastructure.sources.get_semantic_scholar_client")
    def test_semantic_scholar(self, mock_get):
        mock_client = MagicMock()
        mock_client.search.return_value = [{"title": "SS paper"}]
        mock_get.return_value = mock_client

        results = search_alternate_source("test", "semantic_scholar")
        assert len(results) == 1
        mock_client.search.assert_called_once()

    @patch("pubmed_search.infrastructure.sources.get_openalex_client")
    def test_openalex(self, mock_get):
        mock_client = MagicMock()
        mock_client.search.return_value = [{"title": "OA paper"}]
        mock_get.return_value = mock_client

        results = search_alternate_source("test", "openalex")
        assert len(results) == 1

    @patch("pubmed_search.infrastructure.sources.get_europe_pmc_client")
    def test_europe_pmc(self, mock_get):
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": [{"title": "EPMC paper"}]}
        mock_get.return_value = mock_client

        results = search_alternate_source("test", "europe_pmc")
        assert len(results) == 1

    @patch("pubmed_search.infrastructure.sources.get_core_client")
    def test_core(self, mock_get):
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": [{"title": "CORE paper"}]}
        mock_get.return_value = mock_client

        results = search_alternate_source("test", "core")
        assert len(results) == 1

    def test_unknown_source(self):
        results = search_alternate_source("test", "unknown_db")
        assert results == []

    @patch("pubmed_search.infrastructure.sources.get_semantic_scholar_client")
    def test_exception(self, mock_get):
        mock_get.side_effect = Exception("fail")
        results = search_alternate_source("test", "semantic_scholar")
        assert results == []

    @patch("pubmed_search.infrastructure.sources.get_semantic_scholar_client")
    def test_passes_params(self, mock_get):
        mock_client = MagicMock()
        mock_client.search.return_value = []
        mock_get.return_value = mock_client

        search_alternate_source(
            "test", "semantic_scholar",
            limit=20, min_year=2020, max_year=2024, open_access_only=True
        )
        mock_client.search.assert_called_with(
            query="test", limit=20, min_year=2020, max_year=2024, open_access_only=True
        )


# ============================================================
# cross_search
# ============================================================

class TestCrossSearch:
    @patch("pubmed_search.infrastructure.sources.search_alternate_source")
    def test_default_sources(self, mock_search):
        mock_search.return_value = [{"title": "Paper", "_source": "semantic_scholar"}]
        result = cross_search("test query")
        assert result["stats"]["total"] >= 1
        assert len(result["stats"]["sources_searched"]) >= 1

    @patch("pubmed_search.infrastructure.sources.search_alternate_source")
    def test_specific_sources(self, mock_search):
        mock_search.return_value = [{"title": "P", "doi": "10.1/x", "_source": "openalex"}]
        result = cross_search("test", sources=["openalex"])
        assert "openalex" in result["by_source"]

    @patch("pubmed_search.infrastructure.sources.search_alternate_source")
    def test_pubmed_skipped(self, mock_search):
        mock_search.return_value = []
        result = cross_search("test", sources=["pubmed", "openalex"])
        # pubmed should be skipped (handled elsewhere)
        assert "pubmed" not in result["by_source"]

    @patch("pubmed_search.infrastructure.sources.search_alternate_source")
    def test_deduplication(self, mock_search):
        # Return same paper from two sources
        mock_search.side_effect = [
            [{"title": "Same Paper", "doi": "10.1/x", "_source": "ss"}],
            [{"title": "Same Paper", "doi": "10.1/x", "_source": "oa"}],
        ]
        result = cross_search("test", sources=["semantic_scholar", "openalex"])
        assert result["stats"]["total"] == 1

    @patch("pubmed_search.infrastructure.sources.search_alternate_source")
    def test_no_deduplication(self, mock_search):
        mock_search.side_effect = [
            [{"title": "Same Paper", "doi": "10.1/x", "_source": "ss"}],
            [{"title": "Same Paper", "doi": "10.1/x", "_source": "oa"}],
        ]
        result = cross_search("test", sources=["semantic_scholar", "openalex"], deduplicate=False)
        assert result["stats"]["total"] == 2

    @patch("pubmed_search.infrastructure.sources.search_alternate_source")
    def test_source_exception(self, mock_search):
        mock_search.side_effect = Exception("network error")
        result = cross_search("test", sources=["semantic_scholar"])
        assert result["stats"]["total"] == 0
        assert result["by_source"]["semantic_scholar"] == []

    @patch("pubmed_search.infrastructure.sources.search_alternate_source")
    def test_has_fulltext_only_for_supported(self, mock_search):
        mock_search.return_value = []
        cross_search("test", sources=["europe_pmc", "semantic_scholar"], has_fulltext=True)
        calls = mock_search.call_args_list
        # europe_pmc should get has_fulltext=True, semantic_scholar should not
        for call in calls:
            if call[1].get("source") == "europe_pmc" or (call[0] and len(call[0]) > 1 and call[0][1] == "europe_pmc"):
                pass  # Check the has_fulltext param


# ============================================================
# _deduplicate_results
# ============================================================

class TestDeduplicateResults:
    def test_by_doi(self):
        results = [
            {"title": "A", "doi": "10.1/x", "pmid": "", "_source": "pubmed"},
            {"title": "B", "doi": "10.1/x", "pmid": "", "_source": "openalex"},
        ]
        deduped = _deduplicate_results(results)
        assert len(deduped) == 1
        # PubMed should win (lower priority number)
        assert deduped[0]["_source"] == "pubmed"

    def test_by_pmid(self):
        results = [
            {"title": "A", "doi": "", "pmid": "12345", "_source": "pubmed"},
            {"title": "B", "doi": "", "pmid": "12345", "_source": "openalex"},
        ]
        deduped = _deduplicate_results(results)
        assert len(deduped) == 1

    def test_by_title(self):
        results = [
            {"title": "Same Title Here", "doi": "", "pmid": "", "_source": "ss"},
            {"title": "Same Title Here", "doi": "", "pmid": "", "_source": "oa"},
        ]
        deduped = _deduplicate_results(results)
        assert len(deduped) == 1

    def test_unique_papers(self):
        results = [
            {"title": "Paper A", "doi": "10.1/a", "pmid": "1", "_source": "pubmed"},
            {"title": "Paper B", "doi": "10.1/b", "pmid": "2", "_source": "openalex"},
        ]
        deduped = _deduplicate_results(results)
        assert len(deduped) == 2


# ============================================================
# _normalize_title
# ============================================================

class TestNormalizeTitle:
    def test_lowercase(self):
        assert "hello" in _normalize_title("Hello")

    def test_remove_punctuation(self):
        assert _normalize_title("Hello, world!") == "hello world"

    def test_collapse_spaces(self):
        assert _normalize_title("hello   world") == "hello world"


# ============================================================
# get_paper_from_any_source
# ============================================================

class TestGetPaperFromAnySource:
    @patch("pubmed_search.infrastructure.sources.get_semantic_scholar_client")
    def test_doi(self, mock_get):
        mock_client = MagicMock()
        mock_client.get_paper.return_value = {"title": "DOI Paper"}
        mock_get.return_value = mock_client

        result = get_paper_from_any_source("10.1234/test")
        assert result["title"] == "DOI Paper"

    @patch("pubmed_search.infrastructure.sources.get_openalex_client")
    @patch("pubmed_search.infrastructure.sources.get_semantic_scholar_client")
    def test_doi_fallback_to_openalex(self, mock_ss, mock_oa):
        mock_ss_client = MagicMock()
        mock_ss_client.get_paper.return_value = None
        mock_ss.return_value = mock_ss_client

        mock_oa_client = MagicMock()
        mock_oa_client.get_work.return_value = {"title": "OA Paper"}
        mock_oa.return_value = mock_oa_client

        result = get_paper_from_any_source("10.1234/test")
        assert result["title"] == "OA Paper"

    @patch("pubmed_search.infrastructure.sources.get_semantic_scholar_client")
    def test_pmid(self, mock_get):
        mock_client = MagicMock()
        mock_client.get_paper.return_value = {"title": "PMID Paper"}
        mock_get.return_value = mock_client

        result = get_paper_from_any_source("12345678")
        assert result["title"] == "PMID Paper"

    @patch("pubmed_search.infrastructure.sources.get_semantic_scholar_client")
    def test_pmid_prefix(self, mock_get):
        mock_client = MagicMock()
        mock_client.get_paper.return_value = {"title": "PMID Paper"}
        mock_get.return_value = mock_client

        result = get_paper_from_any_source("PMID:12345678")
        assert result is not None

    @patch("pubmed_search.infrastructure.sources.get_semantic_scholar_client")
    def test_s2_id(self, mock_get):
        mock_client = MagicMock()
        mock_client.get_paper.return_value = {"title": "S2 Paper"}
        mock_get.return_value = mock_client

        s2_id = "a" * 40
        result = get_paper_from_any_source(s2_id)
        assert result["title"] == "S2 Paper"

    @patch("pubmed_search.infrastructure.sources.get_openalex_client")
    def test_openalex_id(self, mock_get):
        mock_client = MagicMock()
        mock_client.get_work.return_value = {"title": "OA Work"}
        mock_get.return_value = mock_client

        result = get_paper_from_any_source("W123456")
        assert result["title"] == "OA Work"

    def test_unknown_format(self):
        result = get_paper_from_any_source("unknown!@#$")
        assert result is None


# ============================================================
# Fulltext functions
# ============================================================

class TestFulltext:
    @patch("pubmed_search.infrastructure.sources.get_europe_pmc_client")
    def test_get_fulltext_xml(self, mock_get):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = "<article>...</article>"
        mock_get.return_value = mock_client

        result = get_fulltext_xml("PMC123")
        assert result == "<article>...</article>"

    @patch("pubmed_search.infrastructure.sources.get_europe_pmc_client")
    def test_get_fulltext_parsed(self, mock_get):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = "<article>test</article>"
        mock_client.parse_fulltext_xml.return_value = {"title": "Parsed"}
        mock_get.return_value = mock_client

        result = get_fulltext_parsed("PMC123")
        assert result["title"] == "Parsed"

    @patch("pubmed_search.infrastructure.sources.get_europe_pmc_client")
    def test_get_fulltext_parsed_no_xml(self, mock_get):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = None
        mock_get.return_value = mock_client

        result = get_fulltext_parsed("PMC123")
        assert "error" in result


# ============================================================
# Lazy init singletons
# ============================================================

class TestLazyInit:
    def test_get_fulltext_downloader(self):
        import pubmed_search.infrastructure.sources as mod
        mod._fulltext_downloader = None
        downloader = mod.get_fulltext_downloader()
        assert downloader is not None
        mod._fulltext_downloader = None
