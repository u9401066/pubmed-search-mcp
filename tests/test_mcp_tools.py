"""
Tests for MCP Tools.
"""

from unittest.mock import Mock


class TestCommonTools:
    """Tests for common tool utilities."""

    async def test_format_search_results_empty(self):
        """Test formatting empty results."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            format_search_results,
        )

        result = format_search_results([])
        assert "No results found" in result

    async def test_format_search_results_with_error(self):
        """Test formatting results with error."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            format_search_results,
        )

        result = format_search_results([{"error": "API failed"}])
        assert "Error" in result

    async def test_format_search_results_success(self, mock_article_data):
        """Test formatting successful results."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            format_search_results,
        )

        result = format_search_results([mock_article_data])

        assert "Found 1 results" in result
        assert mock_article_data["title"] in result
        assert mock_article_data["pmid"] in result

    async def test_set_session_manager(self):
        """Test setting session manager."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            set_session_manager,
        )

        mock_manager = Mock()
        set_session_manager(mock_manager)

        # Import again to check
        from pubmed_search.presentation.mcp_server.tools import _common

        assert _common._session_manager == mock_manager

    async def test_set_strategy_generator(self):
        """Test setting strategy generator."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            get_strategy_generator,
            set_strategy_generator,
        )

        mock_generator = Mock()
        set_strategy_generator(mock_generator)

        assert get_strategy_generator() == mock_generator


class TestDiscoveryTools:
    """Tests for discovery tools (search, related, citing)."""

    async def test_discovery_module_exists(self):
        """Test that discovery module can be imported."""
        from pubmed_search.presentation.mcp_server.tools import discovery

        assert discovery is not None


class TestStrategyTools:
    """Tests for strategy tools (generate queries, expand)."""

    async def test_strategy_module_exists(self):
        """Test that strategy module can be imported."""
        from pubmed_search.presentation.mcp_server.tools import strategy

        assert strategy is not None


class TestPicoTools:
    """Tests for PICO parsing tools."""

    async def test_pico_module_exists(self):
        """Test that pico module can be imported."""
        from pubmed_search.presentation.mcp_server.tools import pico

        assert pico is not None


class TestMergeTools:
    """Tests for merge/dedup tools."""

    async def test_merge_module_exists(self):
        """Test that merge module can be imported."""
        from pubmed_search.presentation.mcp_server.tools import merge

        assert merge is not None
