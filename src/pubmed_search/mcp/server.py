"""
PubMed Search MCP Server

A standalone Model Context Protocol server for PubMed literature search.
Can be used independently or integrated into other MCP servers.

Features:
- Literature search with various filters
- Article caching to avoid redundant API calls
- Research session management for Agent context
- Reading list management
"""

import logging
import os
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from ..entrez import LiteratureSearcher
from ..session import SessionManager
from .tools import register_search_tools
from .session_tools import register_session_tools, register_session_resources

logger = logging.getLogger(__name__)

SERVER_INSTRUCTIONS = """
PubMed Search MCP Server - Literature search tools for medical research.

## Core Search Tools
- search_literature: Search PubMed with various filters and date options
- find_related_articles: Find articles related to a given PMID
- find_citing_articles: Find articles that cite a given PMID
- fetch_article_details: Get detailed information for PMIDs
- generate_search_queries: Generate multiple queries for parallel searching
- merge_search_results: Merge and deduplicate parallel search results
- expand_search_queries: Expand search with synonyms, related concepts, etc.

## Session Management (maintain context across conversations)
- get_session_status: Check current session and cached articles
- start_research_session: Begin a new research topic
- list_sessions / switch_session: Manage multiple research projects
- get_cached_article / check_cached_pmids: Retrieve cached data (no API call)
- add_to_reading_list / get_reading_list: Prioritize articles to read
- exclude_article: Mark articles as not relevant
- get_search_history: Review past searches

## Resources (session state for Agent context)
- session://current - Current session summary
- session://reading-list - Prioritized reading list
- session://cache-stats - Cache statistics

## Recommended Workflow
1. get_session_status() - Check existing context
2. start_research_session(topic) - If new topic
3. generate_search_queries(topic) then search in parallel
4. merge_search_results to combine
5. add_to_reading_list for important articles
6. Cached articles can be retrieved without API calls
"""

DEFAULT_EMAIL = "pubmed-search@example.com"
DEFAULT_DATA_DIR = os.path.expanduser("~/.pubmed-search-mcp")


def create_server(
    email: str = DEFAULT_EMAIL,
    api_key: Optional[str] = None,
    name: str = "pubmed-search",
    disable_security: bool = False,
    data_dir: Optional[str] = None
) -> FastMCP:
    """
    Create and configure the PubMed Search MCP server.
    
    Args:
        email: Email address for NCBI Entrez API (required by NCBI).
        api_key: Optional NCBI API key for higher rate limits.
        name: Server name.
        disable_security: Disable DNS rebinding protection (needed for remote access).
        data_dir: Directory for session data persistence. Default: ~/.pubmed-search-mcp
        
    Returns:
        Configured FastMCP server instance.
    """
    logger.info("Initializing PubMed Search MCP Server...")
    
    # Initialize searcher
    searcher = LiteratureSearcher(email=email, api_key=api_key)
    
    # Initialize session manager
    session_data_dir = data_dir or DEFAULT_DATA_DIR
    session_manager = SessionManager(data_dir=session_data_dir)
    logger.info(f"Session data directory: {session_data_dir}")
    
    # Configure transport security
    # Disable DNS rebinding protection for remote access
    if disable_security:
        transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )
        logger.info("DNS rebinding protection disabled for remote access")
    else:
        transport_security = None
    
    # Create MCP server
    mcp = FastMCP(name, instructions=SERVER_INSTRUCTIONS, transport_security=transport_security)
    
    # Set session manager for automatic caching in search tools
    from .tools import set_session_manager
    set_session_manager(session_manager)
    
    # Register tools
    logger.info("Registering search tools...")
    register_search_tools(mcp, searcher)
    
    # Register session tools and resources
    logger.info("Registering session tools...")
    register_session_tools(mcp, session_manager)
    register_session_resources(mcp, session_manager)
    
    # Store references for later use (e.g., updating cache after search)
    mcp._session_manager = session_manager
    mcp._searcher = searcher
    
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
