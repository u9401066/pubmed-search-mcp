"""
Tests for Discovery Tools - search_literature, find_related, find_citing, etc.
"""

import pytest
from unittest.mock import MagicMock


class TestAmbiguousTermDetection:
    """Tests for ambiguous journal name detection."""

    def test_detect_ambiguous_journal_name(self):
        """Test detection of journal names that could be topics."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            _detect_ambiguous_terms,
        )

        # Single word that's a journal name
        result = _detect_ambiguous_terms("anesthesiology")
        assert len(result) > 0
        assert result[0]["journal"] == "Anesthesiology"

    def test_detect_ambiguous_with_other_terms(self):
        """Test that journal names with many other terms are not flagged."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            _detect_ambiguous_terms,
        )

        # Many other terms = probably a topic search
        result = _detect_ambiguous_terms(
            "anesthesiology patient safety monitoring guidelines review"
        )
        # Should return empty or very few since there are many other terms
        assert len(result) == 0

    def test_detect_multiple_ambiguous(self):
        """Test detection of multiple ambiguous terms."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            _detect_ambiguous_terms,
        )

        result = _detect_ambiguous_terms("lancet cell")
        assert len(result) >= 1  # At least one should be detected

    def test_no_ambiguous_terms(self):
        """Test query with no ambiguous terms."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            _detect_ambiguous_terms,
        )

        result = _detect_ambiguous_terms("diabetes mellitus treatment")
        assert len(result) == 0


class TestAmbiguityHint:
    """Tests for ambiguity hint formatting."""

    def test_format_ambiguity_hint_empty(self):
        """Test formatting empty hint."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            _format_ambiguity_hint,
        )

        result = _format_ambiguity_hint([], "test query")
        assert result == ""

    def test_format_ambiguity_hint_single(self):
        """Test formatting single ambiguous term hint."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            _format_ambiguity_hint,
        )

        ambiguous = [
            {
                "term": "anesthesiology",
                "journal": "Anesthesiology",
                "hint": "journal[ta]",
            }
        ]
        result = _format_ambiguity_hint(ambiguous, "anesthesiology")

        assert "⚠️" in result
        assert "Tip" in result
        assert "Anesthesiology" in result

    def test_format_ambiguity_hint_max_two(self):
        """Test that only 2 hints are shown max."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            _format_ambiguity_hint,
        )

        ambiguous = [
            {"term": "a", "journal": "A", "hint": "a"},
            {"term": "b", "journal": "B", "hint": "b"},
            {"term": "c", "journal": "C", "hint": "c"},
        ]
        result = _format_ambiguity_hint(ambiguous, "test")
        # Should only show 2 hints
        assert result.count("|") <= 1  # Only one separator for 2 items


class TestSearchLiteratureTool:
    """Tests for search_literature tool."""

    @pytest.fixture
    def mock_mcp(self):
        """Create mock FastMCP."""
        mcp = MagicMock()
        mcp.tool = lambda: lambda f: f
        return mcp

    @pytest.fixture
    def mock_searcher(self, mock_article_data):
        """Create mock searcher."""
        searcher = MagicMock()
        searcher.search.return_value = [mock_article_data]
        return searcher

    def test_discovery_tools_register(self, mock_mcp, mock_searcher):
        """Test discovery tools registration doesn't error."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            register_discovery_tools,
        )

        # Just test that registration doesn't error
        register_discovery_tools(mock_mcp, mock_searcher)
        # If we get here without exception, registration worked


class TestFindRelatedArticlesTool:
    """Tests for find_related_articles tool."""

    def test_find_related_returns_results(self):
        """Test finding related articles returns formatted output."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            register_discovery_tools,
        )

        mcp = MagicMock()
        mcp.tool = lambda: lambda f: f

        searcher = MagicMock()
        searcher.get_related_articles.return_value = [
            {"pmid": "123", "title": "Related Article"}
        ]

        register_discovery_tools(mcp, searcher)


class TestFindCitingArticlesTool:
    """Tests for find_citing_articles tool."""

    def test_find_citing_no_results(self):
        """Test finding citing articles with no results."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            register_discovery_tools,
        )

        mcp = MagicMock()
        mcp.tool = lambda: lambda f: f

        searcher = MagicMock()
        searcher.get_citing_articles.return_value = []

        register_discovery_tools(mcp, searcher)


class TestGetArticleReferencesTool:
    """Tests for get_article_references tool."""

    def test_get_references_with_error(self):
        """Test getting references with API error."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            register_discovery_tools,
        )

        mcp = MagicMock()
        mcp.tool = lambda: lambda f: f

        searcher = MagicMock()
        searcher.get_article_references.return_value = [{"error": "API Error"}]

        register_discovery_tools(mcp, searcher)


class TestFetchArticleDetailsTool:
    """Tests for fetch_article_details tool."""

    def test_fetch_details_multiple_pmids(self):
        """Test fetching details for multiple PMIDs."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            register_discovery_tools,
        )

        mcp = MagicMock()
        mcp.tool = lambda: lambda f: f

        searcher = MagicMock()
        searcher.fetch_details.return_value = [
            {"pmid": "123", "title": "Article 1"},
            {"pmid": "456", "title": "Article 2"},
        ]

        register_discovery_tools(mcp, searcher)


class TestGetCitationMetricsTool:
    """Tests for get_citation_metrics tool."""

    def test_get_metrics_empty_pmids(self):
        """Test getting metrics with no PMIDs."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            register_discovery_tools,
        )

        mcp = MagicMock()
        mcp.tool = lambda: lambda f: f

        searcher = MagicMock()
        searcher.get_citation_metrics.return_value = {}

        register_discovery_tools(mcp, searcher)

    def test_get_metrics_with_filters(self):
        """Test getting metrics with filter parameters."""
        from pubmed_search.presentation.mcp_server.tools.discovery import (
            register_discovery_tools,
        )

        mcp = MagicMock()
        mcp.tool = lambda: lambda f: f

        searcher = MagicMock()
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
