"""Tests for Discovery MCP tools — find_related, find_citing, etc."""

from unittest.mock import MagicMock, patch

import pytest

from pubmed_search.presentation.mcp_server.tools.discovery import (
    register_discovery_tools,
    _detect_ambiguous_terms,
    _format_ambiguity_hint,
)


def _capture_tools(mcp, searcher):
    tools = {}
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
    register_discovery_tools(mcp, searcher)
    return tools


# ============================================================
# Helper functions
# ============================================================


class TestDetectAmbiguousTerms:
    def test_no_ambiguity(self):
        result = _detect_ambiguous_terms("diabetes treatment guidelines")
        assert result == []

    def test_detects_journal(self):
        result = _detect_ambiguous_terms("anesthesiology")
        assert len(result) > 0
        assert result[0]["journal"] == "Anesthesiology"

    def test_not_ambiguous_with_context(self):
        result = _detect_ambiguous_terms(
            "anesthesiology and intensive care management of critical patients"
        )
        assert result == []  # Too many other terms


class TestFormatAmbiguityHint:
    def test_empty(self):
        assert _format_ambiguity_hint([], "test") == ""

    def test_with_hints(self):
        terms = [{"term": "lancet", "journal": "The Lancet", "hint": "lancet[ta]"}]
        result = _format_ambiguity_hint(terms, "lancet")
        assert "Tip" in result
        assert "lancet[ta]" in result


# ============================================================
# Registered tools
# ============================================================


@pytest.fixture
def setup():
    mcp = MagicMock()
    searcher = MagicMock()
    tools = _capture_tools(mcp, searcher)
    return tools, searcher


class TestFindRelatedArticles:
    def test_invalid_pmid(self, setup):
        tools, _ = setup
        result = tools["find_related_articles"](pmid="")
        assert "error" in result.lower()

    def test_no_results(self, setup):
        tools, searcher = setup
        searcher.get_related_articles.return_value = []
        result = tools["find_related_articles"](pmid="12345678")
        assert "no" in result.lower()

    def test_error_in_results(self, setup):
        tools, searcher = setup
        searcher.get_related_articles.return_value = [{"error": "Not found"}]
        result = tools["find_related_articles"](pmid="12345678")
        assert "error" in result.lower() or "Not found" in result

    def test_success(self, setup):
        tools, searcher = setup
        searcher.get_related_articles.return_value = [
            {"pmid": "999", "title": "Related Paper", "authors": ["A B"]}
        ]
        result = tools["find_related_articles"](pmid="12345678")
        assert "Related" in result

    def test_exception(self, setup):
        tools, searcher = setup
        searcher.get_related_articles.side_effect = RuntimeError("fail")
        result = tools["find_related_articles"](pmid="12345678")
        assert "error" in result.lower()


class TestFindCitingArticles:
    def test_invalid_pmid(self, setup):
        tools, _ = setup
        result = tools["find_citing_articles"](pmid="abc")
        assert "error" in result.lower()

    def test_no_results(self, setup):
        tools, searcher = setup
        searcher.get_citing_articles.return_value = []
        result = tools["find_citing_articles"](pmid="12345678")
        assert "no" in result.lower()

    def test_error_result(self, setup):
        tools, searcher = setup
        searcher.get_citing_articles.return_value = [{"error": "PMC not indexed"}]
        result = tools["find_citing_articles"](pmid="12345678")
        assert "error" in result.lower() or "PMC" in result

    def test_success(self, setup):
        tools, searcher = setup
        searcher.get_citing_articles.return_value = [
            {"pmid": "888", "title": "Citing Paper"}
        ]
        result = tools["find_citing_articles"](pmid="12345678")
        assert "Citing" in result

    def test_exception(self, setup):
        tools, searcher = setup
        searcher.get_citing_articles.side_effect = RuntimeError("fail")
        result = tools["find_citing_articles"](pmid="12345678")
        assert "error" in result.lower()


class TestGetArticleReferences:
    def test_invalid_pmid(self, setup):
        tools, _ = setup
        result = tools["get_article_references"](pmid="invalid!")
        assert "error" in result.lower()

    def test_no_results(self, setup):
        tools, searcher = setup
        searcher.get_article_references.return_value = []
        result = tools["get_article_references"](pmid="12345678")
        assert "no" in result.lower()

    def test_success(self, setup):
        tools, searcher = setup
        searcher.get_article_references.return_value = [
            {"pmid": "777", "title": "Reference Paper"}
        ]
        result = tools["get_article_references"](pmid="12345678")
        assert "Reference" in result
        assert "bibliography" in result.lower() or "cited BY" in result

    def test_exception(self, setup):
        tools, searcher = setup
        searcher.get_article_references.side_effect = RuntimeError("fail")
        result = tools["get_article_references"](pmid="12345678")
        assert "error" in result.lower()


class TestFetchArticleDetails:
    def test_no_pmids(self, setup):
        tools, _ = setup
        result = tools["fetch_article_details"](pmids="")
        assert "error" in result.lower()

    def test_not_found(self, setup):
        tools, searcher = setup
        searcher.fetch_details.return_value = []
        result = tools["fetch_article_details"](pmids="12345678")
        assert "no" in result.lower()

    def test_error_result(self, setup):
        tools, searcher = setup
        searcher.fetch_details.return_value = [{"error": "Bad PMID"}]
        result = tools["fetch_article_details"](pmids="12345678")
        assert "error" in result.lower() or "Bad PMID" in result

    def test_success(self, setup):
        tools, searcher = setup
        searcher.fetch_details.return_value = [
            {"pmid": "123", "title": "Detail Paper", "authors": ["A"]}
        ]
        result = tools["fetch_article_details"](pmids="123")
        assert "Detail Paper" in result

    def test_multiple_pmids(self, setup):
        tools, searcher = setup
        searcher.fetch_details.return_value = [
            {"pmid": "1", "title": "P1"},
            {"pmid": "2", "title": "P2"},
        ]
        result = tools["fetch_article_details"](pmids="1,2")
        assert "P1" in result and "P2" in result


class TestGetCitationMetrics:
    def test_no_pmids(self, setup):
        tools, _ = setup
        result = tools["get_citation_metrics"](pmids="")
        assert "error" in result.lower()

    def test_last_no_session(self, setup):
        tools, searcher = setup
        with patch(
            "pubmed_search.presentation.mcp_server.tools._common.get_last_search_pmids",
            return_value=[],
        ):
            result = tools["get_citation_metrics"](pmids="last")
        assert "error" in result.lower() or "no" in result.lower()

    def test_no_metrics(self, setup):
        tools, searcher = setup
        searcher.get_citation_metrics.return_value = {}
        result = tools["get_citation_metrics"](pmids="12345678")
        assert "no" in result.lower()

    def test_success(self, setup):
        tools, searcher = setup
        searcher.get_citation_metrics.return_value = {
            "12345678": {
                "pmid": "12345678",
                "title": "Metrics Paper",
                "year": 2020,
                "journal": "Nature",
                "citation_count": 100,
                "relative_citation_ratio": 5.5,
                "nih_percentile": 95.0,
                "citations_per_year": 25.0,
                "apt": 0.8,
            }
        }
        result = tools["get_citation_metrics"](pmids="12345678")
        assert "100" in result
        assert "5.50" in result  # RCR

    def test_filter_by_citations(self, setup):
        tools, searcher = setup
        searcher.get_citation_metrics.return_value = {
            "1": {"pmid": "1", "citation_count": 10, "title": "Low"},
            "2": {"pmid": "2", "citation_count": 100, "title": "High"},
        }
        result = tools["get_citation_metrics"](pmids="1,2", min_citations=50)
        assert "No articles match" not in result or "High" in result

    def test_exception(self, setup):
        tools, searcher = setup
        searcher.get_citation_metrics.side_effect = RuntimeError("fail")
        result = tools["get_citation_metrics"](pmids="12345678")
        assert "error" in result.lower()
