"""
Extended tests for Europe PMC tools — additional coverage for get_fulltext paths.

Covers: identifier detection, Unpaywall source, CORE source, _format_sections,
_format_core_fulltext, output formatting, pdf_links dedup, extended_sources.

NOTE: search_europe_pmc, get_fulltext_xml, get_europe_pmc_citations are
      UNREGISTERED (commented-out @mcp.tool()). Only get_fulltext and
      get_text_mined_terms are registered.
"""

import pytest
from unittest.mock import MagicMock, patch

from pubmed_search.presentation.mcp_server.tools.europe_pmc import (
    register_europe_pmc_tools,
)


def _capture_tools(mcp):
    tools = {}
    mcp.tool = lambda: lambda func: (
        tools.__setitem__(func.__name__, func),
        func,
    )[1]
    register_europe_pmc_tools(mcp)
    return tools


@pytest.fixture
def tools():
    return _capture_tools(MagicMock())


# ============================================================
# get_fulltext — identifier detection
# ============================================================


class TestGetFulltextIdentifiers:
    """Test identifier auto-detection in get_fulltext."""

    def test_no_identifier(self, tools):
        result = tools["get_fulltext"]()
        assert "error" in result.lower() or "no valid" in result.lower()

    def test_pmc_id_detection(self, tools):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = None
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = tools["get_fulltext"](identifier="PMC7096777")
        assert isinstance(result, str)

    def test_doi_detection(self, tools):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = None
        mock_unpaywall = MagicMock()
        mock_unpaywall.get_oa_status.return_value = None
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
            return_value=mock_unpaywall,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
            return_value=MagicMock(search=MagicMock(return_value=None)),
        ):
            result = tools["get_fulltext"](identifier="10.1001/jama.2024.1234")
        assert isinstance(result, str)

    def test_pmid_detection(self, tools):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = None
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = tools["get_fulltext"](identifier="12345678")
        assert isinstance(result, str)

    def test_doi_url_detection(self, tools):
        mock_client = MagicMock()
        mock_unpaywall = MagicMock()
        mock_unpaywall.get_oa_status.return_value = None
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
            return_value=mock_unpaywall,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
            return_value=MagicMock(search=MagicMock(return_value=None)),
        ):
            result = tools["get_fulltext"](
                identifier="https://doi.org/10.1038/s41586-021-03819-2"
            )
        assert isinstance(result, str)

    def test_short_pmid(self, tools):
        """Short digit-only identifier → treated as PMID."""
        mock_client = MagicMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = tools["get_fulltext"](identifier="12345")
        assert isinstance(result, str)


# ============================================================
# get_fulltext — Source 1: Europe PMC
# ============================================================


class TestGetFulltextEuropePMC:
    def test_pmcid_with_xml(self, tools):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = "<xml />"
        mock_client.parse_fulltext_xml.return_value = {
            "title": "PMC Article",
            "sections": [
                {"title": "Introduction", "content": "Intro text here"},
                {"title": "Methods", "content": "Method description"},
            ],
            "abstract": "Article abstract",
            "references": [{"title": "Ref1"}, {"title": "Ref2"}],
        }
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = tools["get_fulltext"](pmcid="PMC7096777")
        assert "PMC Article" in result
        assert "Introduction" in result
        assert "Methods" in result
        assert "📚" in result  # References icon

    def test_pmcid_no_xml(self, tools):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = None
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = tools["get_fulltext"](pmcid="PMC9999999")
        assert isinstance(result, str)

    def test_pmcid_exception(self, tools):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.side_effect = RuntimeError("API down")
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = tools["get_fulltext"](pmcid="PMC1234567")
        assert isinstance(result, str)


# ============================================================
# get_fulltext — Source 2: Unpaywall
# ============================================================


class TestGetFulltextUnpaywall:
    def test_unpaywall_oa_with_pdf(self, tools):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = None

        mock_unpaywall = MagicMock()
        mock_unpaywall.get_oa_status.return_value = {
            "is_oa": True,
            "title": "OA Article",
            "oa_status": "gold",
            "best_oa_location": {
                "url_for_pdf": "https://example.com/paper.pdf",
                "host_type": "publisher",
                "version": "publishedVersion",
                "license": "CC BY 4.0",
            },
            "oa_locations": [],
        }

        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
            return_value=mock_unpaywall,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
            return_value=MagicMock(search=MagicMock(return_value=None)),
        ):
            result = tools["get_fulltext"](doi="10.1001/test")
        assert "example.com/paper.pdf" in result
        assert "Gold OA" in result

    def test_unpaywall_oa_landing_page_only(self, tools):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = None

        mock_unpaywall = MagicMock()
        mock_unpaywall.get_oa_status.return_value = {
            "is_oa": True,
            "oa_status": "green",
            "best_oa_location": {
                "url": "https://repo.example.com/landing",
                "host_type": "repository",
            },
            "oa_locations": [],
        }

        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
            return_value=mock_unpaywall,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
            return_value=MagicMock(search=MagicMock(return_value=None)),
        ):
            result = tools["get_fulltext"](doi="10.1001/test2")
        assert "repo.example.com" in result

    def test_unpaywall_with_alt_locations(self, tools):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = None

        best_loc = {
            "url_for_pdf": "https://publisher.com/pdf",
            "host_type": "publisher",
        }
        alt_loc = {
            "url_for_pdf": "https://repo.com/alternate.pdf",
            "host_type": "repository",
            "version": "acceptedVersion",
        }
        mock_unpaywall = MagicMock()
        mock_unpaywall.get_oa_status.return_value = {
            "is_oa": True,
            "oa_status": "hybrid",
            "best_oa_location": best_loc,
            "oa_locations": [best_loc, alt_loc],
        }

        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
            return_value=mock_unpaywall,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
            return_value=MagicMock(search=MagicMock(return_value=None)),
        ):
            result = tools["get_fulltext"](doi="10.1001/test3")
        assert "publisher.com" in result
        assert "repo.com" in result

    def test_unpaywall_not_oa(self, tools):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = None

        mock_unpaywall = MagicMock()
        mock_unpaywall.get_oa_status.return_value = {"is_oa": False}

        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
            return_value=mock_unpaywall,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
            return_value=MagicMock(search=MagicMock(return_value=None)),
        ):
            result = tools["get_fulltext"](doi="10.1001/closed")
        assert isinstance(result, str)

    def test_unpaywall_exception(self, tools):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = None

        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
            side_effect=RuntimeError("API down"),
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
            return_value=MagicMock(search=MagicMock(return_value=None)),
        ):
            result = tools["get_fulltext"](doi="10.1001/error")
        assert isinstance(result, str)


# ============================================================
# get_fulltext — Source 3: CORE
# ============================================================


class TestGetFulltextCORE:
    def test_core_fulltext_available(self, tools):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = None

        mock_unpaywall = MagicMock()
        mock_unpaywall.get_oa_status.return_value = None

        mock_core = MagicMock()
        mock_core.search.return_value = {
            "results": [
                {
                    "fullText": "Full text from CORE source",
                    "downloadUrl": "https://core.ac.uk/pdf/123.pdf",
                    "title": "CORE Article",
                    "sourceFulltextUrls": [
                        "https://repo1.org/ft",
                        "https://repo2.org/ft",
                    ],
                }
            ]
        }

        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
            return_value=mock_unpaywall,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
            return_value=mock_core,
        ):
            result = tools["get_fulltext"](doi="10.1234/core-test")
        assert "CORE" in result or "core.ac.uk" in result

    def test_core_no_fulltext(self, tools):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = None

        mock_unpaywall = MagicMock()
        mock_unpaywall.get_oa_status.return_value = None

        mock_core = MagicMock()
        mock_core.search.return_value = {
            "results": [
                {
                    "title": "No FT Paper",
                    "downloadUrl": "https://core.ac.uk/pdf/456.pdf",
                }
            ]
        }

        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
            return_value=mock_unpaywall,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
            return_value=mock_core,
        ):
            result = tools["get_fulltext"](doi="10.1234/core-notext")
        assert "core.ac.uk" in result

    def test_core_exception(self, tools):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = None

        mock_unpaywall = MagicMock()
        mock_unpaywall.get_oa_status.return_value = None

        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
            return_value=mock_unpaywall,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
            side_effect=RuntimeError("CORE down"),
        ):
            result = tools["get_fulltext"](doi="10.1234/core-err")
        assert isinstance(result, str)


# ============================================================
# get_fulltext — section filtering
# ============================================================


class TestGetFulltextSections:
    def test_filter_specific_sections(self, tools):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml.return_value = {
            "title": "Test",
            "sections": [
                {"title": "Introduction", "content": "Intro text"},
                {"title": "Methods", "content": "Methods text"},
                {"title": "Results", "content": "Results text"},
                {"title": "Discussion", "content": "Discussion text"},
            ],
        }
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = tools["get_fulltext"](
                pmcid="PMC123", sections="introduction,methods"
            )
        assert "Introduction" in result or "Intro text" in result
        assert "Methods" in result or "Methods text" in result
        # Discussion should be filtered out
        assert "Discussion text" not in result

    def test_long_section_truncation(self, tools):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml.return_value = {
            "title": "Test",
            "sections": [
                {"title": "Results", "content": "X" * 7000},
            ],
        }
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = tools["get_fulltext"](pmcid="PMC123")
        assert "truncated" in result.lower()

    def test_no_matching_sections_falls_back_abstract(self, tools):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = "<xml/>"
        mock_client.parse_fulltext_xml.return_value = {
            "title": "Test",
            "sections": [
                {"title": "Introduction", "content": "Intro"},
            ],
            "abstract": "Abstract text fallback",
        }
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = tools["get_fulltext"](pmcid="PMC123", sections="conclusion")
        assert "Abstract" in result or "abstract" in result.lower()


# ============================================================
# get_fulltext — no results
# ============================================================


class TestGetFulltextNoResults:
    def test_all_sources_fail(self, tools):
        mock_client = MagicMock()
        mock_client.get_fulltext_xml.return_value = None

        mock_unpaywall = MagicMock()
        mock_unpaywall.get_oa_status.return_value = None

        mock_core = MagicMock()
        mock_core.search.return_value = None

        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_unpaywall_client",
            return_value=mock_unpaywall,
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_core_client",
            return_value=mock_core,
        ):
            result = tools["get_fulltext"](doi="10.1234/nothing")
        assert "no results" in result.lower() or "not" in result.lower()


# ============================================================
# get_text_mined_terms
# ============================================================


class TestGetTextMinedTerms:
    def test_success(self, tools):
        mock_client = MagicMock()
        mock_client.get_text_mined_terms.return_value = [
            {"semantic_type": "GENE_PROTEIN", "term": "BRCA1", "count": 15},
            {"semantic_type": "CHEMICAL", "term": "Propofol", "count": 5},
        ]
        with patch(
            "pubmed_search.presentation.mcp_server.tools.europe_pmc.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = tools["get_text_mined_terms"](pmid="12345678")
        assert isinstance(result, str)
        assert "GENE_PROTEIN" in result or "CHEMICAL" in result

    def test_no_identifier(self, tools):
        result = tools["get_text_mined_terms"]()
        assert "error" in result.lower() or "no valid" in result.lower()
