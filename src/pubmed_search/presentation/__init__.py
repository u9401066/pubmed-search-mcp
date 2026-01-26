"""
Presentation Layer - User Interface and External APIs

Contains:
- mcp_server: Model Context Protocol server and tools
- api: REST API (for Copilot Studio)
"""

from .mcp_server import create_server, main

# Alias for consistency
create_mcp_server = create_server

__all__ = [
    "create_server",
    "create_mcp_server",
    "main",
]
