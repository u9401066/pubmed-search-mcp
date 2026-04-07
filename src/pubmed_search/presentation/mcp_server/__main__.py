"""
Allow running MCP server as module: uv run python -m pubmed_search.presentation.mcp_server
"""

from __future__ import annotations

from .server import main

if __name__ == "__main__":
    main()
