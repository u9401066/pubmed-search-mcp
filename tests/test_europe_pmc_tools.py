"""Tests for Europe PMC MCP tools — get_fulltext, get_text_mined_terms, helpers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.presentation.mcp_server.tools.europe_pmc import (
    register_europe_pmc_tools,
)


def _capture_tools(mcp):
    tools = {}
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
    register_europe_pmc_tools(mcp)
    return tools


@pytest.fixture
def tools():
    return _capture_tools(MagicMock())


# ============================================================
# get_fulltext
# ============================================================


class TestGetFulltext:
    @pytest.mark.asyncio
    async def test_no_identifier(self, tools):
        result = await tools["get_fulltext"]()
        assert "error" in result.lower() or "no valid" in result.lower()

    @pytest.mark.asyncio
    async def test_pmcid_success(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "Test Article",
                "sections": [{"title": "Introduction", "content": "Hello world"}],
                "abstract": "An abstract",
            }
        )
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_fulltext"](pmcid="PMC7096777")
        assert "Test Article" in result
        assert "Introduction" in result

    @pytest.mark.asyncio
    async def test_pmcid_no_xml(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = None
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_fulltext"](pmcid="PMC9999999")
        # Should still succeed if unpaywall / core have nothing either
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_doi_unpaywall_success(self, tools):
        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = {
            "is_oa": True,
            "title": "OA Paper",
            "oa_status": "gold",
            "best_oa_location": {
                "url_for_pdf": "https://example.com/paper.pdf",
                "host_type": "publisher",
                "version": "publishedVersion",
                "license": "cc-by",
            },
            "oa_locations": [],
        }
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
            return_value=mock_unpaywall,
        ):
            result = await tools["get_fulltext"](doi="10.1234/test")
        assert "example.com/paper.pdf" in result

    @pytest.mark.asyncio
    async def test_doi_core_fallback(self, tools):
        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = {"is_oa": False}

        mock_core = AsyncMock()
        mock_core.search.return_value = {
            "results": [
                {
                    "title": "CORE Paper",
                    "fullText": "Full text content here",
                    "downloadUrl": "https://core.ac.uk/download/pdf/123.pdf",
                }
            ]
        }
        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
                return_value=mock_unpaywall,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
                return_value=mock_core,
            ),
        ):
            result = await tools["get_fulltext"](doi="10.1234/test")
        assert "Full text content" in result or "core.ac.uk" in result

    @pytest.mark.asyncio
    async def test_pmid_identifier_auto_detect(self, tools):
        """Test auto-detection of PMID from identifier string."""
        result = await tools["get_fulltext"](identifier="12345678")
        # Should detect as PMID, result will depend on API but shouldn't crash
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_doi_identifier_auto_detect(self, tools):
        """Test auto-detection of DOI from identifier string."""
        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = {"is_oa": False}
        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
                return_value=mock_unpaywall,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
                return_value=MagicMock(search=AsyncMock(return_value={"results": []})),
            ),
        ):
            result = await tools["get_fulltext"](identifier="10.1038/s41586-021-03819-2")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_pmc_identifier_auto_detect(self, tools):
        """Test auto-detection of PMC ID from identifier string."""
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = None
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_fulltext"](identifier="PMC7096777")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_sections_filter(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "Filtered",
                "sections": [
                    {"title": "Introduction", "content": "Intro text"},
                    {"title": "Methods", "content": "Methods text"},
                    {"title": "Results", "content": "Results text"},
                ],
            }
        )
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_fulltext"](pmcid="PMC7096777", sections="introduction,results")
        assert "Intro text" in result or "Results text" in result

    @pytest.mark.asyncio
    async def test_europe_pmc_exception(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.side_effect = RuntimeError("API down")
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            # Should not crash, just log and continue to other sources
            result = await tools["get_fulltext"](pmcid="PMC7096777")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_no_results_at_all(self, tools):
        """When all sources fail, should return no results message."""
        result = await tools["get_fulltext"](pmid="99999999")
        assert "no" in result.lower() or "not" in result.lower()

    @pytest.mark.asyncio
    async def test_unpaywall_landing_page(self, tools):
        """Test unpaywall returning a landing page URL instead of PDF."""
        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = {
            "is_oa": True,
            "oa_status": "green",
            "best_oa_location": {
                "url": "https://example.com/article",
                "host_type": "repository",
            },
            "oa_locations": [],
        }
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
            return_value=mock_unpaywall,
        ):
            result = await tools["get_fulltext"](doi="10.1234/test")
        assert "example.com/article" in result


# ============================================================
# get_text_mined_terms
# ============================================================


class TestGetTextMinedTerms:
    @pytest.mark.asyncio
    async def test_no_ids(self, tools):
        result = await tools["get_text_mined_terms"]()
        assert "error" in result.lower() or "required" in result.lower()

    @pytest.mark.asyncio
    async def test_pmid_success(self, tools):
        mock_client = AsyncMock()
        mock_client.get_text_mined_terms.return_value = [
            {"semantic_type": "GENE_PROTEIN", "term": "BRCA1"},
            {"semantic_type": "GENE_PROTEIN", "term": "BRCA1"},
            {"semantic_type": "DISEASE", "term": "Breast Cancer"},
            {"semantic_type": "CHEMICAL", "term": "Tamoxifen"},
        ]
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_text_mined_terms"](pmid="12345678")
        assert "BRCA1" in result
        assert "Breast Cancer" in result
        assert "×2" in result  # BRCA1 appears twice

    @pytest.mark.asyncio
    async def test_pmcid_success(self, tools):
        mock_client = AsyncMock()
        mock_client.get_text_mined_terms.return_value = [
            {"semantic_type": "ORGANISM", "term": "Homo sapiens"},
        ]
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_text_mined_terms"](pmcid="PMC7096777")
        assert "Homo sapiens" in result

    @pytest.mark.asyncio
    async def test_semantic_type_filter(self, tools):
        mock_client = AsyncMock()
        mock_client.get_text_mined_terms.return_value = [
            {"semantic_type": "CHEMICAL", "term": "Propofol"},
        ]
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_text_mined_terms"](pmid="12345678", semantic_type="CHEMICAL")
        assert "Propofol" in result

    @pytest.mark.asyncio
    async def test_no_terms_found(self, tools):
        mock_client = AsyncMock()
        mock_client.get_text_mined_terms.return_value = []
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_text_mined_terms"](pmid="12345678")
        assert "no" in result.lower()

    @pytest.mark.asyncio
    async def test_exception(self, tools):
        mock_client = AsyncMock()
        mock_client.get_text_mined_terms.side_effect = RuntimeError("API error")
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_text_mined_terms"](pmid="12345678")
        assert "error" in result.lower()
