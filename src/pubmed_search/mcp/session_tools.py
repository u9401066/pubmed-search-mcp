"""
Session Infrastructure - INTERNAL ONLY

All session/cache/reading-list functionality is INTERNAL.
No tools exposed - these work transparently behind search tools.

Design Principle:
- Agent only uses SEARCH tools
- Session, cache, reading list are infrastructure
- Important articles are tracked internally when Agent uses find_related_articles
"""

import logging

from mcp.server.fastmcp import FastMCP

from ..session import SessionManager

logger = logging.getLogger(__name__)


def register_session_tools(mcp: FastMCP, session_manager: SessionManager):
    """
    NO PUBLIC TOOLS - session management is internal.
    
    The session_manager is used internally by search tools:
    - search_literature auto-caches results
    - find_related_articles tracks the source PMID as "important"
    - Results are auto-filtered against excluded articles
    
    Agent doesn't need to know about sessions or caches.
    """
    pass  # No tools to register


def register_session_resources(mcp: FastMCP, session_manager: SessionManager):
    """
    Resources for debugging/monitoring only.
    Agent doesn't need to use these for normal operation.
    """
    
    @mcp.resource("session://context")
    def get_research_context() -> str:
        """Internal: Current research context (for debugging)."""
        import json
        session = session_manager.get_current_session()
        if not session:
            return json.dumps({"active": False})
        
        return json.dumps({
            "active": True,
            "cached_articles": len(session.article_cache),
            "searches": len(session.search_history)
        })
