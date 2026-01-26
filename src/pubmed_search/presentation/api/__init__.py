"""
HTTP API for MCP-to-MCP communication.

Provides REST endpoints for other MCP servers to directly access
cached article data without going through the Agent.
"""

from .server import create_api_server, run_api_server

__all__ = ["create_api_server", "run_api_server"]
