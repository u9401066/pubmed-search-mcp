"""Tests for Discovery MCP tools — find_related, find_citing, etc."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import toons

from pubmed_search.infrastructure.ncbi.base import NCBIInfrastructureError
from pubmed_search.presentation.mcp_server.tools.discovery import (
    register_discovery_tools,
)


def _capture_tools(mcp, searcher):
    tools = {}
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
    register_discovery_tools(mcp, searcher)
    return tools


# ============================================================
# Registered tools
# ============================================================


@pytest.fixture
def setup():
    mcp = MagicMock()
    searcher = AsyncMock()
    tools = _capture_tools(mcp, searcher)
    return tools, searcher


class TestFindRelatedArticles:
    async def test_invalid_pmid(self, setup):
        tools, _ = setup
        result = await tools["find_related_articles"](pmid="")
        assert "error" in result.lower()

    async def test_no_results(self, setup):
        tools, searcher = setup
        searcher.get_related_articles.return_value = []
        result = await tools["find_related_articles"](pmid="12345678")
        assert "no" in result.lower()

    async def test_source_exception_is_not_reported_as_empty(self, setup):
        tools, searcher = setup
        searcher.get_related_articles.side_effect = NCBIInfrastructureError(
            "related_articles", upstream_type="RuntimeError", retryable=False
        )
        result = await tools["find_related_articles"](pmid="12345678")
        assert "error" in result.lower()
        assert "PubMed related-article lookup failed" in result
        assert "No results" not in result

    async def test_success(self, setup):
        tools, searcher = setup
        searcher.get_related_articles.return_value = [{"pmid": "999", "title": "Related Paper", "authors": ["A B"]}]
        result = await tools["find_related_articles"](pmid="12345678")
        assert "Related" in result

    async def test_exception(self, setup):
        tools, searcher = setup
        searcher.get_related_articles.side_effect = RuntimeError("api_key=private-related")
        result = await tools["find_related_articles"](pmid="12345678")
        assert "PubMed related-article lookup failed" in result
        assert "private-related" not in result


class TestFindCitingArticles:
    async def test_invalid_pmid(self, setup):
        tools, _ = setup
        result = await tools["find_citing_articles"](pmid="abc")
        assert "error" in result.lower()

    async def test_no_results(self, setup):
        tools, searcher = setup
        searcher.get_citing_articles.return_value = []
        result = await tools["find_citing_articles"](pmid="12345678")
        assert "no" in result.lower()

    async def test_source_exception_is_not_reported_as_empty(self, setup):
        tools, searcher = setup
        searcher.get_citing_articles.side_effect = NCBIInfrastructureError(
            "citing_articles", upstream_type="RuntimeError", retryable=False
        )
        result = await tools["find_citing_articles"](pmid="12345678")
        assert "error" in result.lower()
        assert "PubMed citing-article lookup failed" in result
        assert "No results" not in result

    async def test_success(self, setup):
        tools, searcher = setup
        searcher.get_citing_articles.return_value = [{"pmid": "888", "title": "Citing Paper"}]
        result = await tools["find_citing_articles"](pmid="12345678")
        assert "Citing" in result

    async def test_exception(self, setup):
        tools, searcher = setup
        searcher.get_citing_articles.side_effect = RuntimeError("api_key=private-citing")
        result = await tools["find_citing_articles"](pmid="12345678")
        assert "PubMed citing-article lookup failed" in result
        assert "private-citing" not in result


class TestGetArticleReferences:
    async def test_invalid_pmid(self, setup):
        tools, _ = setup
        result = await tools["get_article_references"](pmid="invalid!")
        assert "error" in result.lower()

    async def test_no_results(self, setup):
        tools, searcher = setup
        searcher.get_article_references.return_value = []
        result = await tools["get_article_references"](pmid="12345678")
        assert "no" in result.lower()

    async def test_success(self, setup):
        tools, searcher = setup
        searcher.get_article_references.return_value = [{"pmid": "777", "title": "Reference Paper"}]
        result = await tools["get_article_references"](pmid="12345678")
        assert "Reference" in result
        assert "bibliography" in result.lower() or "cited BY" in result

    async def test_exception(self, setup):
        tools, searcher = setup
        searcher.get_article_references.side_effect = RuntimeError("api_key=private-references")
        result = await tools["get_article_references"](pmid="12345678")
        assert "PubMed article-reference lookup failed" in result
        assert "private-references" not in result


class TestFetchArticleDetails:
    async def test_no_pmids(self, setup):
        tools, _ = setup
        result = await tools["fetch_article_details"](pmids="")
        assert "error" in result.lower()

    async def test_not_found(self, setup):
        tools, searcher = setup
        searcher.fetch_details.return_value = []
        result = await tools["fetch_article_details"](pmids="12345678")
        assert "no" in result.lower()

    async def test_source_exception_is_not_reported_as_empty(self, setup):
        tools, searcher = setup
        searcher.fetch_details.side_effect = NCBIInfrastructureError(
            "fetch_details", upstream_type="RuntimeError", retryable=False
        )
        result = await tools["fetch_article_details"](pmids="12345678")
        assert "error" in result.lower()
        assert "PubMed article-detail lookup failed" in result
        assert "No results" not in result

    async def test_generic_exception_is_sanitized(self, setup):
        tools, searcher = setup
        searcher.fetch_details.side_effect = RuntimeError("api_key=private-details")

        result = await tools["fetch_article_details"](pmids="12345678")

        assert "PubMed article-detail lookup failed" in result
        assert "private-details" not in result

    async def test_success(self, setup):
        tools, searcher = setup
        searcher.fetch_details.return_value = [{"pmid": "123", "title": "Detail Paper", "authors": ["A"]}]
        result = await tools["fetch_article_details"](pmids="123")
        assert "Detail Paper" in result

    async def test_multiple_pmids(self, setup):
        tools, searcher = setup
        searcher.fetch_details.return_value = [
            {"pmid": "1", "title": "P1"},
            {"pmid": "2", "title": "P2"},
        ]
        result = await tools["fetch_article_details"](pmids="1,2")
        assert "P1" in result and "P2" in result

    async def test_json_contract(self, setup):
        tools, searcher = setup
        searcher.fetch_details.return_value = [
            {"pmid": "12345678", "title": "Detail Paper", "authors": ["A"], "doi": "10.1/test"}
        ]

        result = await tools["fetch_article_details"](pmids="12345678", output_format="json")
        parsed = json.loads(result)

        assert parsed["tool"] == "fetch_article_details"
        assert parsed["source_counts"][0]["source"] == "pubmed"
        assert parsed["next_tools"]
        assert any(item["tool"] == "get_fulltext" for item in parsed["next_tools"])
        assert parsed["next_commands"]
        assert parsed["section_provenance"]["articles"]["canonical_host"] == "PubMed"

    async def test_json_contract_no_results(self, setup):
        tools, searcher = setup
        searcher.fetch_details.return_value = []

        result = await tools["fetch_article_details"](pmids="12345678", output_format="json")
        parsed = json.loads(result)

        assert parsed["article_count"] == 0
        assert parsed["source_counts"][0]["returned"] == 0
        assert parsed["next_tools"][0]["tool"] == "unified_search"


class TestGetCitationMetrics:
    async def test_no_pmids(self, setup):
        tools, _ = setup
        result = await tools["get_citation_metrics"](pmids="")
        assert "error" in result.lower()

    async def test_last_no_session(self, setup):
        tools, searcher = setup
        with patch(
            "pubmed_search.presentation.mcp_server.tools._common.get_last_search_pmids",
            return_value=[],
        ):
            result = await tools["get_citation_metrics"](pmids="last")
        assert "error" in result.lower() or "no" in result.lower()

    async def test_no_metrics(self, setup):
        tools, searcher = setup
        searcher.get_citation_metrics.return_value = {}
        result = await tools["get_citation_metrics"](pmids="12345678")
        assert "no" in result.lower()

    async def test_success(self, setup):
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
        result = await tools["get_citation_metrics"](pmids="12345678")
        assert "100" in result
        assert "5.50" in result  # RCR

    async def test_filter_by_citations(self, setup):
        tools, searcher = setup
        searcher.get_citation_metrics.return_value = {
            "1": {"pmid": "1", "citation_count": 10, "title": "Low"},
            "2": {"pmid": "2", "citation_count": 100, "title": "High"},
        }
        result = await tools["get_citation_metrics"](pmids="1,2", min_citations=50)
        assert "No articles match" not in result or "High" in result

    async def test_exception(self, setup):
        tools, searcher = setup
        searcher.get_citation_metrics.side_effect = RuntimeError("fail")
        result = await tools["get_citation_metrics"](pmids="12345678")
        assert "error" in result.lower()

    @pytest.mark.parametrize(
        ("kwargs", "expected"),
        [
            ({"sort_by": "unknown_metric"}, "sort"),
            ({"min_citations": -1}, "citations"),
            ({"min_citations": True}, "citations"),
            ({"min_rcr": -0.1}, "rcr"),
            ({"min_rcr": True}, "rcr"),
            ({"min_percentile": 101}, "percentile"),
            ({"min_percentile": True}, "percentile"),
        ],
    )
    async def test_rejects_invalid_metric_controls_for_direct_callers(self, setup, kwargs, expected):
        tools, searcher = setup

        result = await tools["get_citation_metrics"](pmids="12345678", **kwargs)

        assert "error" in result.lower()
        assert expected in result.lower()
        searcher.get_citation_metrics.assert_not_awaited()

    async def test_rejects_pmid_batch_over_domain_limit(self, setup):
        tools, searcher = setup
        pmids = ",".join(str(index) for index in range(1, 1002))

        result = await tools["get_citation_metrics"](pmids=pmids)

        assert "error" in result.lower()
        assert "1000" in result
        searcher.get_citation_metrics.assert_not_awaited()

    async def test_icite_unavailable_is_not_rendered_as_no_results(self, setup):
        from pubmed_search.shared.exceptions import ServiceUnavailableError

        tools, searcher = setup
        searcher.get_citation_metrics.side_effect = ServiceUnavailableError(
            "request failed",
            service="NIH iCite",
        )

        result = await tools["get_citation_metrics"](pmids="12345678")

        assert "NIH iCite" in result
        assert "temporarily unavailable" in result
        assert "No results" not in result
        assert "Retryable" in result

    async def test_json_contract(self, setup):
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

        result = await tools["get_citation_metrics"](pmids="12345678", output_format="json")
        parsed = json.loads(result)

        assert parsed["tool"] == "get_citation_metrics"
        assert parsed["article_count"] == 1
        assert parsed["articles"][0]["pmid"] == "12345678"
        assert parsed["source_counts"][0]["source"] == "nih-icite"

    async def test_toon_contract(self, setup):
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

        result = await tools["get_citation_metrics"](pmids="12345678", output_format="toon")
        parsed = toons.loads(result)

        assert parsed["tool"] == "get_citation_metrics"
        assert parsed["article_count"] == 1
        assert parsed["next_tools"]
        assert parsed["section_provenance"]["articles"]["canonical_host"] == "NIH iCite"
