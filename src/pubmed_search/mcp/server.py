"""
PubMed Search MCP Server

A standalone Model Context Protocol server for PubMed literature search.
Can be used independently or integrated into other MCP servers.
"""

import logging
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..entrez import LiteratureSearcher
from .tools import register_search_tools

logger = logging.getLogger(__name__)

SERVER_INSTRUCTIONS = """
PubMed Search MCP Server - Literature search tools for medical research.

Available tools:
- search_literature: Search PubMed with various filters and date options
- find_related_articles: Find articles related to a given PMID
- find_citing_articles: Find articles that cite a given PMID
- fetch_article_details: Get detailed information for PMIDs
- generate_search_queries: Generate multiple queries for parallel searching
- merge_search_results: Merge and deduplicate parallel search results
- expand_search_queries: Expand search with synonyms, related concepts, etc.

Workflow for comprehensive search:
1. generate_search_queries(topic="your topic")
2. Execute search_literature in parallel for each query
3. merge_search_results to combine and deduplicate
4. If more results needed: expand_search_queries then repeat
"""

DEFAULT_EMAIL = "pubmed-search@example.com"


def create_server(
    email: str = DEFAULT_EMAIL,
    api_key: Optional[str] = None,
    name: str = "pubmed-search"
) -> FastMCP:
    """
    Create and configure the PubMed Search MCP server.
    
    Args:
        email: Email address for NCBI Entrez API (required by NCBI).
        api_key: Optional NCBI API key for higher rate limits.
        name: Server name.
        
    Returns:
        Configured FastMCP server instance.
    """
    logger.info("Initializing PubMed Search MCP Server...")
    
    # Initialize searcher
    searcher = LiteratureSearcher(email=email, api_key=api_key)
    
    # Create MCP server
    mcp = FastMCP(name, instructions=SERVER_INSTRUCTIONS)
    
    # Register tools
    logger.info("Registering search tools...")
    register_search_tools(mcp, searcher)
    
    logger.info("PubMed Search MCP Server initialized successfully")
    
    return mcp


def main():
    """Run the MCP server."""
    import os
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Get email from args or environment
    if len(sys.argv) > 1:
        email = sys.argv[1]
    else:
        email = os.environ.get("NCBI_EMAIL", DEFAULT_EMAIL)
    
    # Get API key from args or environment
    if len(sys.argv) > 2:
        api_key = sys.argv[2]
    else:
        api_key = os.environ.get("NCBI_API_KEY")
    
    # Create and run server
    server = create_server(email=email, api_key=api_key)
    server.run()


if __name__ == "__main__":
    main()
