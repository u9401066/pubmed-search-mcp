"""
Tests for Unified Search MCP Tool (Phase 2.0)

This tests the unified search gateway which provides:
- Single entry point for multi-source search
- Automatic query analysis and source dispatch
- Result aggregation and ranking
"""

import pytest
from unittest.mock import Mock
from mcp.server.fastmcp import FastMCP


class TestUnifiedImports:
    """Test that unified module can be imported."""
    
    def test_import_register_function(self):
        """Test importing register_unified_search_tools."""
        from pubmed_search.mcp_server.tools.unified import register_unified_search_tools
        assert callable(register_unified_search_tools)
    
    def test_import_dispatch_strategy(self):
        """Test importing DispatchStrategy."""
        from pubmed_search.mcp_server.tools.unified import DispatchStrategy
        assert DispatchStrategy is not None


class TestDispatchStrategy:
    """Tests for DispatchStrategy class."""
    
    @pytest.fixture
    def analyzer(self):
        """Create a QueryAnalyzer for testing."""
        from pubmed_search.unified import QueryAnalyzer
        return QueryAnalyzer()
    
    def test_simple_lookup_uses_pubmed_only(self, analyzer):
        """Simple PMID lookup should only use PubMed."""
        from pubmed_search.mcp_server.tools.unified import DispatchStrategy
        
        analysis = analyzer.analyze("PMID:12345678")
        sources = DispatchStrategy.get_sources(analysis)
        
        assert "pubmed" in sources
        assert len(sources) == 1  # PubMed only for direct lookup
    
    def test_simple_query_uses_pubmed_only(self, analyzer):
        """Simple keyword search should use PubMed only."""
        from pubmed_search.mcp_server.tools.unified import DispatchStrategy
        
        analysis = analyzer.analyze("diabetes treatment")
        sources = DispatchStrategy.get_sources(analysis)
        
        assert "pubmed" in sources
    
    def test_complex_comparison_uses_multiple_sources(self, analyzer):
        """Complex comparison queries should use multiple sources."""
        from pubmed_search.mcp_server.tools.unified import DispatchStrategy
        
        analysis = analyzer.analyze("remimazolam vs propofol for ICU sedation")
        sources = DispatchStrategy.get_sources(analysis)
        
        # Should include multiple sources for comparison
        assert "pubmed" in sources
        assert len(sources) >= 2  # At least PubMed + one more
    
    def test_moderate_query_uses_crossref(self, analyzer):
        """Moderate queries should use CrossRef for enrichment."""
        from pubmed_search.mcp_server.tools.unified import DispatchStrategy
        
        # A moderate complexity query
        analysis = analyzer.analyze("machine learning anesthesia prediction models")
        sources = DispatchStrategy.get_sources(analysis)
        
        assert "pubmed" in sources
    
    def test_get_ranking_config_returns_config(self, analyzer):
        """get_ranking_config should return a RankingConfig."""
        from pubmed_search.mcp_server.tools.unified import DispatchStrategy
        from pubmed_search.unified.result_aggregator import RankingConfig
        
        analysis = analyzer.analyze("test query")
        config = DispatchStrategy.get_ranking_config(analysis)
        
        assert isinstance(config, RankingConfig)
    
    def test_comparison_query_uses_impact_ranking(self, analyzer):
        """Comparison queries should use impact-focused ranking."""
        from pubmed_search.mcp_server.tools.unified import DispatchStrategy
        
        analysis = analyzer.analyze("drug A vs drug B effectiveness")
        config = DispatchStrategy.get_ranking_config(analysis)
        
        # Impact focused should have higher impact weight
        assert config.impact_weight > config.recency_weight


class TestToolRegistration:
    """Tests for MCP tool registration."""
    
    def test_registration_adds_unified_search(self):
        """register_unified_search_tools should add unified_search tool."""
        from pubmed_search.mcp_server.tools.unified import register_unified_search_tools
        
        mcp = FastMCP(name="test")
        mock_searcher = Mock()
        
        register_unified_search_tools(mcp, mock_searcher)
        
        tool_names = [t.name for t in mcp._tool_manager._tools.values()]
        assert "unified_search" in tool_names
    
    def test_registration_adds_analyze_query(self):
        """register_unified_search_tools should add analyze_search_query tool."""
        from pubmed_search.mcp_server.tools.unified import register_unified_search_tools
        
        mcp = FastMCP(name="test")
        mock_searcher = Mock()
        
        register_unified_search_tools(mcp, mock_searcher)
        
        tool_names = [t.name for t in mcp._tool_manager._tools.values()]
        assert "analyze_search_query" in tool_names
    
    def test_unified_search_tool_has_description(self):
        """unified_search tool should have a description."""
        from pubmed_search.mcp_server.tools.unified import register_unified_search_tools
        
        mcp = FastMCP(name="test")
        mock_searcher = Mock()
        
        register_unified_search_tools(mcp, mock_searcher)
        
        unified_tool = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "unified_search":
                unified_tool = tool
                break
        
        assert unified_tool is not None
        assert unified_tool.description is not None
        assert len(unified_tool.description) > 0


class TestIntegrationWithServer:
    """Integration tests with full MCP server."""
    
    def test_unified_tools_in_full_server(self):
        """Unified tools should be registered in full server."""
        from pubmed_search.mcp_server import create_server
        
        mcp = create_server()
        tool_names = [t.name for t in mcp._tool_manager._tools.values()]
        
        assert "unified_search" in tool_names
        assert "analyze_search_query" in tool_names
    
    def test_server_has_expected_tool_count(self):
        """Server should have expected number of tools including unified."""
        from pubmed_search.mcp_server import create_server
        
        mcp = create_server()
        tool_count = len(mcp._tool_manager._tools)
        
        # v0.1.21: Consolidated from 35+ to ~21-25 tools
        # Many tools integrated into unified_search
        assert tool_count >= 21


class TestSourceSearchFunctions:
    """Tests for internal source search functions."""
    
    def test_search_pubmed_with_mock(self):
        """_search_pubmed should work with mock searcher."""
        from pubmed_search.mcp_server.tools.unified import _search_pubmed
        
        mock_searcher = Mock()
        mock_searcher.search.return_value = []
        
        results = _search_pubmed(
            searcher=mock_searcher,
            query="test query",
            limit=10,
            min_year=2020,
            max_year=2024,
        )
        
        # Returns tuple of (articles, total_count)
        assert results == ([], None)
        mock_searcher.search.assert_called_once()
    
    def test_search_pubmed_handles_exception(self):
        """_search_pubmed should handle exceptions gracefully."""
        from pubmed_search.mcp_server.tools.unified import _search_pubmed
        
        mock_searcher = Mock()
        mock_searcher.search.side_effect = Exception("API error")
        
        results = _search_pubmed(
            searcher=mock_searcher,
            query="test query",
            limit=10,
            min_year=None,
            max_year=None,
        )
        
        # Should return empty tuple, not raise
        assert results == ([], None)


class TestFormatFunctions:
    """Tests for output formatting functions."""
    
    def test_format_as_json_returns_valid_json(self):
        """_format_as_json should return valid JSON."""
        import json
        from pubmed_search.mcp_server.tools.unified import _format_as_json
        from pubmed_search.unified.result_aggregator import AggregationStats
        from pubmed_search.unified import QueryAnalyzer
        
        analyzer = QueryAnalyzer()
        analysis = analyzer.analyze("test query")
        stats = AggregationStats(
            total_input=10,
            unique_articles=8,
            duplicates_removed=2,
        )
        
        result = _format_as_json([], analysis, stats)
        
        # Should be valid JSON
        parsed = json.loads(result)
        assert "analysis" in parsed
        assert "statistics" in parsed
        assert "articles" in parsed
