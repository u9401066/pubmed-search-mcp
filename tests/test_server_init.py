"""
Tests for MCP Server and related components.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


class TestServerHTTPMode:
    """Tests for HTTP server mode."""

    async def test_run_server_uses_unix_like_temp_dir_for_exports(self):
        """run_server export directory should follow the current temp directory."""
        import run_server

        with patch("run_server.tempfile.gettempdir", return_value="/var/folders/test-temp"):
            assert run_server._default_export_dir() == str(Path("/var/folders/test-temp") / "pubmed_exports")

    async def test_run_server_uses_windows_like_temp_dir_for_exports(self):
        """run_server export helper should not hardcode a POSIX-only /tmp path."""
        import run_server

        with patch("run_server.tempfile.gettempdir", return_value=r"C:\Temp\pubmed"):
            assert run_server._default_export_dir() == str(Path(r"C:\Temp\pubmed") / "pubmed_exports")


class TestToolsInit:
    """Tests for tools __init__ module."""

    async def test_tools_init_exports(self):
        """Test that tools __init__ exports expected functions."""
        from pubmed_search.presentation.mcp_server import tools

        assert hasattr(tools, "register_all_tools")
        assert not hasattr(tools, "set_session_manager")
        assert not hasattr(tools, "set_strategy_generator")
