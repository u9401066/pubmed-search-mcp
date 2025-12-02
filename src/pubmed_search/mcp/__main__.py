"""
Allow running MCP server as module: python -m pubmed_search.mcp
"""

from .server import main

if __name__ == "__main__":
    main()
