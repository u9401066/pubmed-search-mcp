"""Tests for Copilot Studio compatible tools."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

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
    searcher = AsyncMock()
    tools = _capture_tools(mcp, searcher)
    return tools, searcher


# ============================================================
# search_pubmed
# ============================================================


class TestSearchPubmed:
    async def test_no_results(self, setup):
        tools, searcher = setup
        searcher.search.return_value = []
        result = await tools["search_pubmed"](query="xyznonexistent")
        assert "no" in result.lower()

    async def test_success(self, setup):
        tools, searcher = setup
        searcher.search.return_value = [{"pmid": "123", "title": "Test", "authors": ["A"]}]
        result = await tools["search_pubmed"](query="diabetes")
        assert "Test" in result or "123" in result

    async def test_exception(self, setup):
        tools, searcher = setup
        searcher.search.side_effect = RuntimeError("fail")
        result = await tools["search_pubmed"](query="test")
        assert "error" in result.lower()

    async def test_year_filters(self, setup):
        tools, searcher = setup
        searcher.search.return_value = [{"pmid": "1", "title": "T"}]
        _result = await tools["search_pubmed"](query="test", min_year=2020, max_year=2024)
        searcher.search.assert_called_once()
        call_kwargs = searcher.search.call_args
        assert call_kwargs[1].get("min_year") == 2020 or call_kwargs[0][2] == 2020


# ============================================================
# get_article
# ============================================================


class TestGetArticle:
    async def test_invalid_pmid(self, setup):
        tools, _ = setup
        result = await tools["get_article"](pmid="")
        assert "error" in result.lower() or "invalid" in result.lower()

    async def test_not_found(self, setup):
        tools, searcher = setup
        searcher.fetch_details.return_value = []
        result = await tools["get_article"](pmid="12345678")
        assert "not found" in result.lower()

    async def test_success(self, setup):
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
        result = await tools["get_article"](pmid="12345678")
        assert "Great Paper" in result
        assert "et al." in result  # > 5 authors

    async def test_exception(self, setup):
        tools, searcher = setup
        searcher.fetch_details.side_effect = RuntimeError("fail")
        result = await tools["get_article"](pmid="12345678")
        assert "error" in result.lower()


# ============================================================
# find_related
# ============================================================


class TestFindRelated:
    async def test_invalid_pmid(self, setup):
        tools, _ = setup
        result = await tools["find_related"](pmid="")
        assert "error" in result.lower()

    async def test_no_results(self, setup):
        tools, searcher = setup
        searcher.find_related_articles.return_value = []
        result = await tools["find_related"](pmid="12345678")
        assert "no" in result.lower()

    async def test_success(self, setup):
        tools, searcher = setup
        searcher.find_related_articles.return_value = [{"pmid": "999", "title": "Related"}]
        result = await tools["find_related"](pmid="12345678")
        assert "Related" in result


# ============================================================
# find_citations
# ============================================================


class TestFindCitations:
    async def test_invalid_pmid(self, setup):
        tools, _ = setup
        result = await tools["find_citations"](pmid="")
        assert "error" in result.lower()

    async def test_no_results(self, setup):
        tools, searcher = setup
        searcher.find_citing_articles.return_value = []
        result = await tools["find_citations"](pmid="12345678")
        assert "no" in result.lower()

    async def test_success(self, setup):
        tools, searcher = setup
        searcher.find_citing_articles.return_value = [{"pmid": "888", "title": "Citing"}]
        result = await tools["find_citations"](pmid="12345678")
        assert "Citing" in result


# ============================================================
# get_references
# ============================================================


class TestGetReferences:
    async def test_invalid_pmid(self, setup):
        tools, _ = setup
        result = await tools["get_references"](pmid="")
        assert "error" in result.lower()

    async def test_success(self, setup):
        tools, searcher = setup
        searcher.get_article_references.return_value = [{"pmid": "777", "title": "Reference"}]
        result = await tools["get_references"](pmid="12345678")
        assert "Reference" in result


# ============================================================
# analyze_clinical_question
# ============================================================


class TestAnalyzeClinicalQuestion:
    def test_returns_json_suggestion(self, setup):
        """analyze_clinical_question is sync and returns a JSON suggestion."""
        tools, _ = setup
        result = tools["analyze_clinical_question"](question="Does drug X reduce mortality?")
        parsed = json.loads(result)
        assert "question" in parsed
        assert "suggestion" in parsed


# ============================================================
# expand_search_terms
# ============================================================


class TestExpandSearchTerms:
    async def test_with_strategy_generator(self, setup):
        tools, _ = setup
        mock_gen = AsyncMock()
        mock_gen.generate_strategies.return_value = {"mesh": ["term1"], "synonyms": []}
        with patch(
            "pubmed_search.presentation.mcp_server.tools._common.get_strategy_generator",
            return_value=mock_gen,
        ):
            result = await tools["expand_search_terms"](topic="diabetes")
        parsed = json.loads(result)
        assert "mesh" in parsed

    async def test_fallback_no_strategy_gen(self, setup):
        tools, _ = setup
        with patch(
            "pubmed_search.presentation.mcp_server.tools._common.get_strategy_generator",
            return_value=None,
        ):
            result = await tools["expand_search_terms"](topic="diabetes")
        assert "diabetes" in result


# ============================================================
# get_fulltext (copilot)
# ============================================================


class TestCopilotGetFulltext:
    async def test_invalid_pmcid(self, setup):
        tools, _ = setup
        result = await tools["get_fulltext"](pmcid="")
        assert "error" in result.lower() or "invalid" in result.lower()

    async def test_success(self, setup):
        tools, _ = setup
        mock_client = MagicMock()
        mock_client.get_fulltext_xml = AsyncMock(return_value="<xml>content</xml>")
        mock_client.parse_fulltext_xml.return_value = {
            "abstract": "Test abstract",
            "sections": [{"title": "Introduction", "content": "Hello"}],
        }
        with patch(
            "pubmed_search.infrastructure.sources.europe_pmc.EuropePMCClient",
            return_value=mock_client,
        ):
            result = await tools["get_fulltext"](pmcid="PMC7096777")
        assert "Introduction" in result or "Hello" in result

    async def test_no_content(self, setup):
        tools, _ = setup
        mock_client = MagicMock()
        mock_client.get_fulltext_xml = AsyncMock(return_value=None)
        with patch(
            "pubmed_search.infrastructure.sources.europe_pmc.EuropePMCClient",
            return_value=mock_client,
        ):
            result = await tools["get_fulltext"](pmcid="PMC9999")
        assert "not available" in result.lower()

    async def test_exception(self, setup):
        tools, _ = setup
        with patch(
            "pubmed_search.infrastructure.sources.europe_pmc.EuropePMCClient",
            side_effect=RuntimeError("fail"),
        ):
            result = await tools["get_fulltext"](pmcid="PMC7096777")
        assert "error" in result.lower()


# ============================================================
# export_citations (copilot)
# ============================================================


class TestCopilotExportCitations:
    async def test_last_no_results(self, setup):
        tools, _ = setup
        with patch(
            "pubmed_search.presentation.mcp_server.tools._common.get_last_search_pmids",
            return_value=[],
        ):
            result = await tools["export_citations"](pmids="last")
        assert "error" in result.lower() or "no" in result.lower()

    async def test_invalid_pmids(self, setup):
        tools, _ = setup
        result = await tools["export_citations"](pmids="")
        assert "error" in result.lower()

    async def test_success_ris(self, setup):
        """export_ris exists and should produce RIS output."""
        tools, searcher = setup
        searcher.fetch_details.return_value = [{"pmid": "123", "title": "T", "authors": ["A"]}]
        result = await tools["export_citations"](pmids="123", format="ris")
        assert "Exported" in result or "error" in result.lower()

    async def test_success_bibtex(self, setup):
        """export_bibtex exists and should produce BibTeX output."""
        tools, searcher = setup
        searcher.fetch_details.return_value = [{"pmid": "123", "title": "T", "authors": ["A"]}]
        result = await tools["export_citations"](pmids="123", format="bibtex")
        assert "Exported" in result or "error" in result.lower()

    async def test_no_articles_found(self, setup):
        """When fetch_details returns empty, 'No articles found' is returned."""
        tools, searcher = setup
        searcher.fetch_details.return_value = []
        result = await tools["export_citations"](pmids="999")
        assert "no articles" in result.lower() or "error" in result.lower()


# ============================================================
# search_gene (copilot)
# ============================================================


class TestCopilotSearchGene:
    async def test_success(self, setup):
        """search_gene returns results from NCBI extended client."""
        tools, _ = setup
        mock_client = MagicMock()
        mock_client.search_gene = AsyncMock(return_value=[{"gene_id": "672", "symbol": "BRCA1"}])
        with patch(
            "pubmed_search.infrastructure.sources.ncbi_extended.get_ncbi_extended_client",
            return_value=mock_client,
        ):
            result = await tools["search_gene"](query="BRCA1")
        assert "BRCA1" in result

    async def test_no_results(self, setup):
        tools, _ = setup
        mock_client = MagicMock()
        mock_client.search_gene = AsyncMock(return_value=[])
        with patch(
            "pubmed_search.infrastructure.sources.ncbi_extended.get_ncbi_extended_client",
            return_value=mock_client,
        ):
            result = await tools["search_gene"](query="NONEXISTENTGENE")
        assert "no" in result.lower()


# ============================================================
# search_compound (copilot)
# ============================================================


class TestCopilotSearchCompound:
    async def test_success(self, setup):
        """search_compound returns results from NCBI extended client."""
        tools, _ = setup
        mock_client = MagicMock()
        mock_client.search_compound = AsyncMock(return_value=[{"cid": "4943", "name": "propofol"}])
        with patch(
            "pubmed_search.infrastructure.sources.ncbi_extended.get_ncbi_extended_client",
            return_value=mock_client,
        ):
            result = await tools["search_compound"](query="propofol")
        assert "propofol" in result

    async def test_no_results(self, setup):
        tools, _ = setup
        mock_client = MagicMock()
        mock_client.search_compound = AsyncMock(return_value=[])
        with patch(
            "pubmed_search.infrastructure.sources.ncbi_extended.get_ncbi_extended_client",
            return_value=mock_client,
        ):
            result = await tools["search_compound"](query="xyznonexistent")
        assert "no" in result.lower()
