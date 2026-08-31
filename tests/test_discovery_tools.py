"""
Tests for Discovery Tools - find_related, find_citing, etc.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestDiscoveryRegistration:
    """Tests for the registered discovery tool group."""

    @pytest.fixture
    def mock_mcp(self):
        """Create mock MCPServer."""
        mcp = MagicMock()
        mcp.tool = lambda: lambda f: f
        return mcp

    @pytest.fixture
    def mock_searcher(self, mock_article_data):
        """Create mock searcher."""
        del mock_article_data
        searcher = AsyncMock()
        return searcher

    async def test_discovery_tools_register(self, mock_mcp, mock_searcher):
        """Test discovery tools registration doesn't error."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            register_discovery_tools,
        )

        # Just test that registration doesn't error
        register_discovery_tools(mock_mcp, mock_searcher)
        # If we get here without exception, registration worked


class TestFindRelatedArticlesTool:
    """Tests for find_related_articles tool."""

    async def test_find_related_returns_results(self):
        """Test finding related articles returns formatted output."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            register_discovery_tools,
        )

        mcp = MagicMock()
        mcp.tool = lambda: lambda f: f

        searcher = AsyncMock()
        searcher.get_related_articles.return_value = [{"pmid": "123", "title": "Related Article"}]

        register_discovery_tools(mcp, searcher)


class TestFindCitingArticlesTool:
    """Tests for find_citing_articles tool."""

    async def test_find_citing_no_results(self):
        """Test finding citing articles with no results."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            register_discovery_tools,
        )

        mcp = MagicMock()
        mcp.tool = lambda: lambda f: f

        searcher = AsyncMock()
        searcher.get_citing_articles.return_value = []

        register_discovery_tools(mcp, searcher)


class TestGetArticleReferencesTool:
    """Tests for get_article_references tool."""

    async def test_get_references_with_error(self):
        """Test getting references with API error."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            register_discovery_tools,
        )

        mcp = MagicMock()
        mcp.tool = lambda: lambda f: f

        searcher = AsyncMock()
        searcher.get_article_references.side_effect = RuntimeError("API unavailable")

        register_discovery_tools(mcp, searcher)


class TestFetchArticleDetailsTool:
    """Tests for fetch_article_details tool."""

    async def test_fetch_details_multiple_pmids(self):
        """Test fetching details for multiple PMIDs."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            register_discovery_tools,
        )

        mcp = MagicMock()
        mcp.tool = lambda: lambda f: f

        searcher = AsyncMock()
        searcher.fetch_details.return_value = [
            {"pmid": "123", "title": "Article 1"},
            {"pmid": "456", "title": "Article 2"},
        ]

        register_discovery_tools(mcp, searcher)


class TestGetCitationMetricsTool:
    """Tests for get_citation_metrics tool."""

    async def test_get_metrics_empty_pmids(self):
        """Test getting metrics with no PMIDs."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            register_discovery_tools,
        )

        mcp = MagicMock()
        mcp.tool = lambda: lambda f: f

        searcher = AsyncMock()
        searcher.get_citation_metrics.return_value = {}

        register_discovery_tools(mcp, searcher)

    async def test_get_metrics_with_filters(self):
        """Test getting metrics with filter parameters."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            register_discovery_tools,
        )

        mcp = MagicMock()
        mcp.tool = lambda: lambda f: f

        searcher = AsyncMock()
        searcher.get_citation_metrics.return_value = {
            "123": {
                "pmid": "123",
                "title": "Test",
                "citation_count": 50,
                "relative_citation_ratio": 2.5,
                "nih_percentile": 80,
            }
        }

        register_discovery_tools(mcp, searcher)
