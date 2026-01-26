"""
Tests for MCP Server and related components.
"""

from unittest.mock import MagicMock


class TestMCPServerInit:
    """Tests for MCP server initialization."""
    
    def test_server_module_imports(self):
        """Test that server module can be imported."""
        from pubmed_search.mcp_server import server
        assert server is not None
    
    def test_literature_searcher_creation(self):
        """Test LiteratureSearcher creation with email."""
        from pubmed_search.entrez import LiteratureSearcher
        
        searcher = LiteratureSearcher(email="test@example.com")
        assert searcher is not None
    
    def test_literature_searcher_has_mixins(self):
        """Test that LiteratureSearcher has all expected mixins."""
        from pubmed_search.entrez import LiteratureSearcher
        
        searcher = LiteratureSearcher(email="test@example.com")
        
        # Check for expected methods from mixins
        assert hasattr(searcher, 'get_related_articles')
        assert hasattr(searcher, 'get_citing_articles')
        assert hasattr(searcher, 'get_article_references')
        assert hasattr(searcher, 'get_citation_metrics')
        assert hasattr(searcher, 'search_with_history')
        assert hasattr(searcher, 'fetch_batch_from_history')


class TestSessionTools:
    """Tests for session tools."""
    
    def test_session_tools_module_imports(self):
        """Test that session_tools module can be imported."""
        from pubmed_search.mcp_server import session_tools
        assert session_tools is not None
    
    def test_register_session_tools(self):
        """Test registering session tools."""
        from pubmed_search.mcp_server.session_tools import register_session_tools
        
        mcp = MagicMock()
        mcp.tool = lambda: lambda f: f
        
        session_manager = MagicMock()
        
        # Should not raise
        register_session_tools(mcp, session_manager)


class TestToolRegistration:
    """Tests for tool registration."""
    
    def test_all_tools_registered(self):
        """Test that all tools are registered."""
        from pubmed_search.mcp_server.tools import (
            register_discovery_tools,
            register_strategy_tools,
            register_pico_tools,
            register_export_tools,
            register_unified_search_tools,
            register_europe_pmc_tools,
        )
        
        mcp = MagicMock()
        mcp.tool = lambda: lambda f: f
        
        searcher = MagicMock()
        
        # All should run without error
        register_discovery_tools(mcp, searcher)
        register_strategy_tools(mcp, searcher)
        register_pico_tools(mcp)
        register_export_tools(mcp, searcher)
        register_unified_search_tools(mcp, searcher)
        register_europe_pmc_tools(mcp)
    
    def test_register_all_tools_function(self):
        """Test register_all_tools aggregator function."""
        from pubmed_search.mcp_server.tools import register_all_tools
        
        mcp = MagicMock()
        mcp.tool = lambda: lambda f: f
        
        searcher = MagicMock()
        
        # Should run without error
        register_all_tools(mcp, searcher)


class TestServerHTTPMode:
    """Tests for HTTP server mode."""
    
    def test_run_server_module_imports(self):
        """Test that run_server can be imported."""
        # Just test import doesn't fail
        try:
            import run_server
        except ImportError:
            pass  # OK if not in path
    
    def test_server_has_fastmcp(self):
        """Test that FastMCP is available."""
        from mcp.server.fastmcp import FastMCP
        assert FastMCP is not None


class TestToolsInit:
    """Tests for tools __init__ module."""
    
    def test_tools_init_exports(self):
        """Test that tools __init__ exports expected functions."""
        from pubmed_search.mcp_server import tools
        
        assert hasattr(tools, 'register_all_tools')
        assert hasattr(tools, 'set_session_manager')
        assert hasattr(tools, 'set_strategy_generator')


class TestEntrezInit:
    """Tests for entrez __init__ module."""
    
    def test_entrez_init_exports(self):
        """Test that entrez __init__ exports LiteratureSearcher."""
        from pubmed_search.entrez import LiteratureSearcher
        
        assert LiteratureSearcher is not None
    
    def test_literature_searcher_inheritance(self):
        """Test LiteratureSearcher has correct inheritance."""
        from pubmed_search.entrez import LiteratureSearcher
        
        # Check MRO includes all mixins
        mro_names = [cls.__name__ for cls in LiteratureSearcher.__mro__]
        
        assert 'EntrezBase' in mro_names
        assert 'CitationMixin' in mro_names
        assert 'BatchMixin' in mro_names
        assert 'ICiteMixin' in mro_names


class TestExportsInit:
    """Tests for exports __init__ module."""
    
    def test_exports_init_exports(self):
        """Test that exports __init__ exports expected functions."""
        from pubmed_search.exports import (
            export_articles,
            get_fulltext_links,
            summarize_access,
            SUPPORTED_FORMATS
        )
        
        assert export_articles is not None
        assert get_fulltext_links is not None
        assert summarize_access is not None
        assert "ris" in SUPPORTED_FORMATS
        assert "bibtex" in SUPPORTED_FORMATS
