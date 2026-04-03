"""Tests for Europe PMC MCP tools — get_fulltext, get_text_mined_terms, helpers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import toons

from pubmed_search.infrastructure.sources.fulltext_download import (
    FulltextResult,
    PDFLink,
    PDFSource,
)
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

    @pytest.mark.asyncio
    async def test_reports_progress_and_logs(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "Test Article",
                "sections": [{"title": "Introduction", "content": "Hello world"}],
            }
        )
        ctx = AsyncMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_fulltext"](pmcid="PMC7096777", ctx=ctx)
        assert "Test Article" in result
        assert ctx.report_progress.await_count >= 3
        assert ctx.log.await_count >= 1

    @pytest.mark.asyncio
    async def test_json_contract(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "Structured Article",
                "sections": [{"title": "Introduction", "content": "Hello world"}],
            }
        )
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_fulltext"](pmcid="PMC7096777", output_format="json")

        parsed = json.loads(result)
        assert parsed["tool"] == "get_fulltext"
        assert parsed["fulltext_available"] is True
        assert parsed["content_sections"][0]["title"] == "Introduction"
        assert parsed["source_counts"]
        assert parsed["next_tools"]
        assert parsed["next_commands"]
        assert parsed["section_provenance"]["content"]["surfacing_source"] == "Europe PMC"

    @pytest.mark.asyncio
    async def test_extended_sources_extracts_institutional_pdf_text(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = None

        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = {"is_oa": False}

        mock_core = AsyncMock()
        mock_core.search.return_value = {"results": []}

        mock_downloader = MagicMock()
        mock_downloader.get_fulltext = AsyncMock(
            return_value=FulltextResult(
                text_content="Institutional PDF text",
                pdf_links=[
                    PDFLink(
                        url="https://resolver.example.edu/openurl?id=1",
                        source=PDFSource.INSTITUTIONAL_RESOLVER,
                        access_type="subscription",
                        is_direct_pdf=False,
                    ),
                    PDFLink(
                        url="https://publisher.example.edu/paper.pdf",
                        source=PDFSource.INSTITUTIONAL_RESOLVER,
                        access_type="subscription",
                        is_direct_pdf=True,
                    ),
                ],
                source_used=PDFSource.INSTITUTIONAL_RESOLVER,
                content_type="pdf",
            )
        )
        mock_downloader.close = AsyncMock()

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
                return_value=mock_client,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
                return_value=mock_unpaywall,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
                return_value=mock_core,
            ),
            patch(
                "pubmed_search.infrastructure.sources.fulltext_download.FulltextDownloader",
                return_value=mock_downloader,
            ),
        ):
            result = await tools["get_fulltext"](doi="10.1234/test", extended_sources=True)

        mock_downloader.get_fulltext.assert_awaited_once_with(
            pmid=None,
            pmcid=None,
            doi="10.1234/test",
            strategy="extract_text",
        )
        assert "Institutional PDF text" in result
        assert "publisher.example.edu/paper.pdf" in result
        assert "Institutional" in result

    @pytest.mark.asyncio
    async def test_toon_contract(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "Structured Article",
                "sections": [{"title": "Introduction", "content": "Hello world"}],
            }
        )
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_fulltext"](pmcid="PMC7096777", output_format="toon")

        parsed = toons.loads(result)
        assert parsed["tool"] == "get_fulltext"
        assert parsed["fulltext_available"] is True
        assert parsed["content_sections"][0]["title"] == "Introduction"
        assert parsed["section_provenance"]["content"]["canonical_host"] == "PubMed Central"


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

    @pytest.mark.asyncio
    async def test_reports_progress(self, tools):
        mock_client = AsyncMock()
        mock_client.get_text_mined_terms.return_value = [
            {"semantic_type": "GENE_PROTEIN", "term": "BRCA1"},
        ]
        ctx = AsyncMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_text_mined_terms"](pmid="12345678", ctx=ctx)
        assert "BRCA1" in result
        assert ctx.report_progress.await_count >= 2

    @pytest.mark.asyncio
    async def test_json_contract(self, tools):
        mock_client = AsyncMock()
        mock_client.get_text_mined_terms.return_value = [
            {"semantic_type": "GENE_PROTEIN", "term": "BRCA1"},
            {"semantic_type": "GENE_PROTEIN", "term": "BRCA1"},
            {"semantic_type": "DISEASE", "term": "Breast Cancer"},
        ]
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_text_mined_terms"](pmid="12345678", output_format="json")

        parsed = json.loads(result)
        assert parsed["tool"] == "get_text_mined_terms"
        assert parsed["annotation_count"] == 3
        assert any(group["semantic_type"] == "GENE_PROTEIN" for group in parsed["term_groups"])
        assert parsed["next_tools"]
        assert parsed["section_provenance"]["annotations"]["surfacing_source"] == "Europe PMC"

    @pytest.mark.asyncio
    async def test_toon_contract(self, tools):
        mock_client = AsyncMock()
        mock_client.get_text_mined_terms.return_value = [
            {"semantic_type": "CHEMICAL", "term": "Propofol"},
        ]
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await tools["get_text_mined_terms"](pmid="12345678", output_format="toon")

        parsed = toons.loads(result)
        assert parsed["tool"] == "get_text_mined_terms"
        assert parsed["annotation_count"] == 1
        assert parsed["term_groups"][0]["terms"][0]["term"] == "Propofol"
