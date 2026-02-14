"""
Allow running MCP server as module: python -m pubmed_search.mcp
"""

from __future__ import annotations

from .server import main

if __name__ == "__main__":
    main()
