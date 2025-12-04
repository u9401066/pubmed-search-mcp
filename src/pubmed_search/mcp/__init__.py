"""
PubMed Search MCP Server

This module provides a Model Context Protocol (MCP) server for PubMed search.

Usage as standalone server:
    python -m pubmed_search.mcp
    
Or in mcp.json:
    {
        "servers": {
            "pubmed-search": {
                "type": "stdio",
                "command": "python",
                "args": ["-m", "pubmed_search.mcp"]
            }
        }
    }

Usage for integration:
    from pubmed_search.mcp import create_server, register_all_tools
    
    # Option 1: Create standalone server
    server = create_server(email="your@email.com")
    server.run()
    
    # Option 2: Register tools to existing server
    from pubmed_search import LiteratureSearcher
    searcher = LiteratureSearcher(email="your@email.com")
    register_all_tools(your_mcp_server, searcher)
"""

from .server import create_server, main
from .tools import register_all_tools

__all__ = ["create_server", "register_all_tools", "main"]
