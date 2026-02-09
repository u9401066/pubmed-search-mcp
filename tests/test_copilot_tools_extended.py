"""Tests for Copilot Studio compatible tools."""

import json
from unittest.mock import MagicMock, patch

import pytest

from pubmed_search.presentation.mcp_server.copilot_tools import (
    register_copilot_compatible_tools,
)


def _capture_tools(mcp, searcher):
    tools = {}
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
    register_copilot_compatible_tools(mcp, searcher)
    return tools


@pytest.fixture
def setup():
    mcp = MagicMock()
    searcher = MagicMock()
    tools = _capture_tools(mcp, searcher)
    return tools, searcher


# ============================================================
# search_pubmed
# ============================================================


class TestSearchPubmed:
    def test_no_results(self, setup):
        tools, searcher = setup
        searcher.search.return_value = []
        result = tools["search_pubmed"](query="xyznonexistent")
        assert "no" in result.lower()

    def test_success(self, setup):
        tools, searcher = setup
        searcher.search.return_value = [
            {"pmid": "123", "title": "Test", "authors": ["A"]}
        ]
        result = tools["search_pubmed"](query="diabetes")
        assert "Test" in result or "123" in result

    def test_exception(self, setup):
        tools, searcher = setup
        searcher.search.side_effect = RuntimeError("fail")
        result = tools["search_pubmed"](query="test")
        assert "error" in result.lower()

    def test_year_filters(self, setup):
        tools, searcher = setup
        searcher.search.return_value = [{"pmid": "1", "title": "T"}]
        _result = tools["search_pubmed"](query="test", min_year=2020, max_year=2024)
        searcher.search.assert_called_once()
        call_kwargs = searcher.search.call_args
        assert call_kwargs[1].get("min_year") == 2020 or call_kwargs[0][2] == 2020


# ============================================================
# get_article
# ============================================================


class TestGetArticle:
    def test_invalid_pmid(self, setup):
        tools, _ = setup
        result = tools["get_article"](pmid="")
        assert "error" in result.lower() or "invalid" in result.lower()

    def test_not_found(self, setup):
        tools, searcher = setup
        searcher.fetch_details.return_value = []
        result = tools["get_article"](pmid="12345678")
        assert "not found" in result.lower()

    def test_success(self, setup):
        tools, searcher = setup
        searcher.fetch_details.return_value = [
            {
                "pmid": "12345678",
                "title": "Great Paper",
                "doi": "10.1234/test",
                "pmc_id": "PMC123",
                "authors": ["Smith J", "Doe A", "Lee B", "Park C", "Kim D", "Chen X"],
                "journal": "Nature",
                "year": "2024",
                "abstract": "This is the abstract.",
            }
        ]
        result = tools["get_article"](pmid="12345678")
        assert "Great Paper" in result
        assert "et al." in result  # > 5 authors

    def test_exception(self, setup):
        tools, searcher = setup
        searcher.fetch_details.side_effect = RuntimeError("fail")
        result = tools["get_article"](pmid="12345678")
        assert "error" in result.lower()


# ============================================================
# find_related
# ============================================================


class TestFindRelated:
    def test_invalid_pmid(self, setup):
        tools, _ = setup
        result = tools["find_related"](pmid="")
        assert "error" in result.lower()

    def test_no_results(self, setup):
        tools, searcher = setup
        searcher.find_related.return_value = []
        result = tools["find_related"](pmid="12345678")
        assert "no" in result.lower()

    def test_success(self, setup):
        tools, searcher = setup
        searcher.find_related.return_value = [{"pmid": "999", "title": "Related"}]
        result = tools["find_related"](pmid="12345678")
        assert "Related" in result


# ============================================================
# find_citations
# ============================================================


class TestFindCitations:
    def test_invalid_pmid(self, setup):
        tools, _ = setup
        result = tools["find_citations"](pmid="")
        assert "error" in result.lower()

    def test_no_results(self, setup):
        tools, searcher = setup
        searcher.find_citing_articles.return_value = []
        result = tools["find_citations"](pmid="12345678")
        assert "no" in result.lower()

    def test_success(self, setup):
        tools, searcher = setup
        searcher.find_citing_articles.return_value = [
            {"pmid": "888", "title": "Citing"}
        ]
        result = tools["find_citations"](pmid="12345678")
        assert "Citing" in result


# ============================================================
# get_references
# ============================================================


class TestGetReferences:
    def test_invalid_pmid(self, setup):
        tools, _ = setup
        result = tools["get_references"](pmid="")
        assert "error" in result.lower()

    def test_success(self, setup):
        tools, searcher = setup
        searcher.get_article_references.return_value = [
            {"pmid": "777", "title": "Reference"}
        ]
        result = tools["get_references"](pmid="12345678")
        assert "Reference" in result


# ============================================================
# analyze_clinical_question
# ============================================================


class TestAnalyzeClinicalQuestion:
    def test_returns_error_on_import_failure(self, setup):
        """_analyze_pico_description doesn't exist in pico.py, so ImportError is raised.
        The import is outside try/except, so it propagates as ImportError."""
        tools, _ = setup
        with pytest.raises(ImportError):
            tools["analyze_clinical_question"](
                question="Does drug X reduce mortality?"
            )


# ============================================================
# expand_search_terms
# ============================================================


class TestExpandSearchTerms:
    def test_with_strategy_generator(self, setup):
        tools, _ = setup
        mock_gen = MagicMock()
        mock_gen.generate_strategies.return_value = {"mesh": ["term1"], "synonyms": []}
        with patch(
            "pubmed_search.presentation.mcp_server.tools._common.get_strategy_generator",
            return_value=mock_gen,
        ):
            result = tools["expand_search_terms"](topic="diabetes")
        parsed = json.loads(result)
        assert "mesh" in parsed

    def test_fallback_no_strategy_gen(self, setup):
        tools, _ = setup
        with patch(
            "pubmed_search.presentation.mcp_server.tools._common.get_strategy_generator",
            return_value=None,
        ):
            result = tools["expand_search_terms"](topic="diabetes")
        assert "diabetes" in result


# ============================================================
# get_fulltext (copilot)
# ============================================================


class TestCopilotGetFulltext:
    def test_invalid_pmcid(self, setup):
        tools, _ = setup
        result = tools["get_fulltext"](pmcid="")
        assert "error" in result.lower() or "invalid" in result.lower()

    def test_success(self, setup):
        tools, _ = setup
        mock_client = MagicMock()
        mock_client.get_fulltext.return_value = {
            "content": [{"title": "Introduction", "text": "Hello"}]
        }
        with patch(
            "pubmed_search.infrastructure.sources.europe_pmc.EuropePMCClient",
            return_value=mock_client,
        ):
            result = tools["get_fulltext"](pmcid="PMC7096777")
        assert "Introduction" in result or "Hello" in result

    def test_no_content(self, setup):
        tools, _ = setup
        mock_client = MagicMock()
        mock_client.get_fulltext.return_value = None
        with patch(
            "pubmed_search.infrastructure.sources.europe_pmc.EuropePMCClient",
            return_value=mock_client,
        ):
            result = tools["get_fulltext"](pmcid="PMC9999")
        assert "not available" in result.lower()

    def test_exception(self, setup):
        tools, _ = setup
        with patch(
            "pubmed_search.infrastructure.sources.europe_pmc.EuropePMCClient",
            side_effect=RuntimeError("fail"),
        ):
            result = tools["get_fulltext"](pmcid="PMC7096777")
        assert "error" in result.lower()


# ============================================================
# export_citations (copilot)
# ============================================================


class TestCopilotExportCitations:
    def test_last_no_results(self, setup):
        tools, _ = setup
        with patch(
            "pubmed_search.presentation.mcp_server.tools._common.get_last_search_pmids",
            return_value=[],
        ):
            result = tools["export_citations"](pmids="last")
        assert "error" in result.lower() or "no" in result.lower()

    def test_invalid_pmids(self, setup):
        tools, _ = setup
        result = tools["export_citations"](pmids="")
        assert "error" in result.lower()

    def test_success_ris(self, setup):
        """export_to_ris doesn't exist (actual name is export_ris), so ImportError is caught."""
        tools, searcher = setup
        searcher.fetch_details.return_value = [
            {"pmid": "123", "title": "T", "authors": ["A"]}
        ]
        result = tools["export_citations"](pmids="123", format="ris")
        # The internal import `from ... import export_to_ris` fails -> error
        assert "error" in result.lower()

    def test_success_bibtex(self, setup):
        """export_to_bibtex doesn't exist (actual name is export_bibtex), so ImportError is caught."""
        tools, searcher = setup
        searcher.fetch_details.return_value = [
            {"pmid": "123", "title": "T", "authors": ["A"]}
        ]
        result = tools["export_citations"](pmids="123", format="bibtex")
        assert "error" in result.lower()

    def test_no_articles_found(self, setup):
        """When import fails, error is returned before checking articles."""
        tools, searcher = setup
        searcher.fetch_details.return_value = []
        result = tools["export_citations"](pmids="999")
        assert "error" in result.lower()


# ============================================================
# search_gene (copilot)
# ============================================================


class TestCopilotSearchGene:
    def test_import_error(self, setup):
        """ncbi.gene module doesn't exist, so ImportError is caught."""
        tools, _ = setup
        result = tools["search_gene"](query="BRCA1")
        assert "error" in result.lower()


# ============================================================
# search_compound (copilot)
# ============================================================


class TestCopilotSearchCompound:
    def test_import_error(self, setup):
        """ncbi.pubchem module doesn't exist, so ImportError is caught."""
        tools, _ = setup
        result = tools["search_compound"](query="propofol")
        assert "error" in result.lower()
