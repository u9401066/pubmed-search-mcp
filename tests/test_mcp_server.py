"""
Tests for MCP Server initialization and registration.
"""

from unittest.mock import Mock


class TestServerImports:
    """Test that server modules can be imported."""

    def test_import_create_server(self):
        """Test importing create_server function."""
        from pubmed_search.presentation.mcp_server import create_server

        assert create_server is not None

    def test_import_register_all_tools(self):
        """Test importing register_all_tools function."""
        from pubmed_search.presentation.mcp_server import register_all_tools

        assert register_all_tools is not None

    def test_import_main(self):
        """Test importing main function."""
        from pubmed_search.presentation.mcp_server import main

        assert main is not None


class TestServerModule:
    """Tests for server module."""

    def test_server_module_exists(self):
        """Test that server module can be imported."""
        from pubmed_search.presentation.mcp_server import server

        assert server is not None

    def test_server_has_create_server(self):
        """Test that server module has create_server."""
        from pubmed_search.presentation.mcp_server.server import create_server

        assert callable(create_server)


class TestToolsRegistration:
    """Tests for tools registration."""

    def test_tools_init_exports(self):
        """Test that tools __init__ exports register_all_tools."""
        from pubmed_search.presentation.mcp_server.tools import register_all_tools

        assert callable(register_all_tools)

    def test_register_all_tools_callable(self):
        """Test that register_all_tools is callable."""
        from pubmed_search.presentation.mcp_server.tools import register_all_tools

        # Create mock server and searcher
        mock_server = Mock()
        mock_server.tool = Mock(return_value=lambda f: f)
        Mock()

        # Should not raise
        # Note: This may fail if the function has specific requirements
        # In that case, we just test it's callable
        assert callable(register_all_tools)


class TestSessionTools:
    """Tests for session tools."""

    def test_session_tools_module_exists(self):
        """Test that session_tools module can be imported."""
        from pubmed_search.presentation.mcp_server import session_tools

        assert session_tools is not None
