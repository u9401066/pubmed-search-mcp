"""
Session Management MCP Tools

Tools for managing research sessions, article caching, and reading lists.
Enables Agent to maintain context across conversations.
"""

import json
import logging
from typing import Optional, List

from mcp.server.fastmcp import FastMCP

from ..session import SessionManager

logger = logging.getLogger(__name__)


def register_session_tools(mcp: FastMCP, session_manager: SessionManager):
    """Register session management tools."""
    
    @mcp.tool()
    def get_session_status() -> str:
        """
        Get current research session status and context.
        
        Use this at the START of conversations to restore context,
        or to check what articles have been searched/cached.
        
        Returns:
            Session summary including:
            - Current topic
            - Cached article count
            - Recent searches
            - Reading list
        """
        logger.info("Getting session status")
        summary = session_manager.get_session_summary()
        
        if summary.get("status") == "no_active_session":
            return json.dumps({
                "status": "no_active_session",
                "message": "No active research session. Use start_research_session to begin.",
                "hint": "Call start_research_session(topic='your research topic')"
            }, indent=2, ensure_ascii=False)
        
        return json.dumps(summary, indent=2, ensure_ascii=False)
    
    @mcp.tool()
    def start_research_session(topic: str) -> str:
        """
        Start a new research session with a topic.
        
        Each session tracks:
        - Searched articles (cached to avoid re-fetching)
        - Search history
        - Reading list with priorities
        - Notes and annotations
        
        Args:
            topic: Research topic (e.g., "remimazolam ICU sedation dosing")
            
        Returns:
            New session details
        """
        logger.info(f"Starting research session: {topic}")
        session = session_manager.create_session(topic)
        
        return json.dumps({
            "status": "session_created",
            "session_id": session.session_id,
            "topic": session.topic,
            "created_at": session.created_at,
            "message": f"Research session started for: {topic}",
            "next_steps": [
                "Use search_literature to find articles",
                "Articles will be automatically cached",
                "Use add_to_reading_list to prioritize articles",
                "Use get_cached_article to retrieve without API call"
            ]
        }, indent=2, ensure_ascii=False)
    
    @mcp.tool()
    def list_sessions() -> str:
        """
        List all research sessions.
        
        Shows all previous sessions with their topics and article counts.
        Use switch_session to change to a different session.
        
        Returns:
            List of sessions with summaries
        """
        logger.info("Listing sessions")
        sessions = session_manager.list_sessions()
        
        if not sessions:
            return json.dumps({
                "sessions": [],
                "message": "No sessions found. Use start_research_session to create one."
            }, indent=2, ensure_ascii=False)
        
        return json.dumps({
            "session_count": len(sessions),
            "sessions": sessions
        }, indent=2, ensure_ascii=False)
    
    @mcp.tool()
    def switch_session(session_id: str) -> str:
        """
        Switch to a different research session.
        
        Args:
            session_id: ID of the session to switch to
            
        Returns:
            Session details after switching
        """
        logger.info(f"Switching to session: {session_id}")
        session = session_manager.switch_session(session_id)
        
        if not session:
            return json.dumps({
                "error": f"Session {session_id} not found",
                "hint": "Use list_sessions to see available sessions"
            }, indent=2, ensure_ascii=False)
        
        return json.dumps({
            "status": "switched",
            "session_id": session.session_id,
            "topic": session.topic,
            "cached_articles": len(session.article_cache),
            "searches": len(session.search_history)
        }, indent=2, ensure_ascii=False)
    
    @mcp.tool()
    def get_cached_article(pmid: str) -> str:
        """
        Get article from session cache (no API call needed).
        
        If the article was searched before in this session, returns
        cached data immediately without calling NCBI API.
        
        Args:
            pmid: PubMed ID
            
        Returns:
            Cached article data or cache miss message
        """
        logger.info(f"Getting cached article: {pmid}")
        cached, missing = session_manager.get_from_cache([pmid])
        
        if cached:
            article = cached[0]
            return json.dumps({
                "status": "cache_hit",
                "pmid": pmid,
                "article": article
            }, indent=2, ensure_ascii=False)
        
        return json.dumps({
            "status": "cache_miss",
            "pmid": pmid,
            "message": "Article not in cache. Use fetch_article_details to retrieve.",
            "hint": f"fetch_article_details(pmids='{pmid}')"
        }, indent=2, ensure_ascii=False)
    
    @mcp.tool()
    def check_cached_pmids(pmids: str) -> str:
        """
        Check which PMIDs are already cached (avoid redundant API calls).
        
        Before fetching article details, use this to see which are already cached.
        Only fetch the missing ones.
        
        Args:
            pmids: Comma-separated list of PMIDs
            
        Returns:
            Lists of cached and missing PMIDs
        """
        pmid_list = [p.strip() for p in pmids.split(",")]
        logger.info(f"Checking cache for {len(pmid_list)} PMIDs")
        
        cached, missing = session_manager.get_from_cache(pmid_list)
        
        return json.dumps({
            "total": len(pmid_list),
            "cached_count": len(cached),
            "missing_count": len(missing),
            "cached_pmids": [a.get('pmid') for a in cached],
            "missing_pmids": missing,
            "recommendation": f"Fetch only {len(missing)} missing articles" if missing else "All articles cached!"
        }, indent=2, ensure_ascii=False)
    
    @mcp.tool()
    def add_to_reading_list(
        pmid: str, 
        priority: int = 3,
        notes: str = ""
    ) -> str:
        """
        Add article to reading list with priority.
        
        Args:
            pmid: PubMed ID
            priority: 1 (highest) to 5 (lowest), default 3
            notes: Optional notes about why this article is important
            
        Returns:
            Updated reading list status
        """
        logger.info(f"Adding to reading list: {pmid} (priority={priority})")
        session_manager.add_to_reading_list(pmid, priority, notes)
        
        session = session_manager.get_current_session()
        return json.dumps({
            "status": "added",
            "pmid": pmid,
            "priority": priority,
            "notes": notes,
            "reading_list_total": len(session.reading_list) if session else 0
        }, indent=2, ensure_ascii=False)
    
    @mcp.tool()
    def get_reading_list() -> str:
        """
        Get current reading list sorted by priority.
        
        Returns:
            Reading list with priorities and statuses
        """
        logger.info("Getting reading list")
        session = session_manager.get_current_session()
        
        if not session:
            return json.dumps({
                "error": "No active session",
                "hint": "Use start_research_session first"
            }, indent=2, ensure_ascii=False)
        
        # Sort by priority
        sorted_list = sorted(
            session.reading_list.items(),
            key=lambda x: (x[1].get('priority', 5), x[1].get('added_at', ''))
        )
        
        items = []
        for pmid, info in sorted_list:
            # Try to get title from cache
            cached = session.article_cache.get(pmid, {})
            items.append({
                "pmid": pmid,
                "title": cached.get('title', 'Not cached'),
                "priority": info.get('priority', 3),
                "status": info.get('status', 'unread'),
                "notes": info.get('notes', '')
            })
        
        return json.dumps({
            "count": len(items),
            "reading_list": items
        }, indent=2, ensure_ascii=False)
    
    @mcp.tool()
    def exclude_article(pmid: str, reason: str = "") -> str:
        """
        Mark an article as not relevant (excluded from future results).
        
        Args:
            pmid: PubMed ID
            reason: Optional reason for exclusion
            
        Returns:
            Confirmation
        """
        logger.info(f"Excluding article: {pmid}")
        session_manager.exclude_article(pmid)
        
        session = session_manager.get_current_session()
        return json.dumps({
            "status": "excluded",
            "pmid": pmid,
            "reason": reason,
            "total_excluded": len(session.excluded_pmids) if session else 0
        }, indent=2, ensure_ascii=False)
    
    @mcp.tool()
    def get_search_history() -> str:
        """
        Get search history for current session.
        
        Shows all searches performed with their results count.
        Useful for understanding what has been searched.
        
        Returns:
            Search history with queries and result counts
        """
        logger.info("Getting search history")
        session = session_manager.get_current_session()
        
        if not session:
            return json.dumps({
                "error": "No active session",
                "searches": []
            }, indent=2, ensure_ascii=False)
        
        return json.dumps({
            "session_topic": session.topic,
            "search_count": len(session.search_history),
            "searches": [
                {
                    "query": s.get('query'),
                    "timestamp": s.get('timestamp'),
                    "result_count": s.get('result_count'),
                    "filters": s.get('filters', {})
                }
                for s in session.search_history[-20:]  # Last 20 searches
            ]
        }, indent=2, ensure_ascii=False)


def register_session_resources(mcp: FastMCP, session_manager: SessionManager):
    """Register session-related MCP Resources."""
    
    @mcp.resource("session://current")
    def get_current_session_resource() -> str:
        """
        Current research session context.
        
        This resource provides the Agent with current session state
        for maintaining context across conversations.
        """
        summary = session_manager.get_session_summary()
        return json.dumps(summary, indent=2, ensure_ascii=False)
    
    @mcp.resource("session://reading-list")
    def get_reading_list_resource() -> str:
        """Reading list for current session."""
        session = session_manager.get_current_session()
        if not session:
            return json.dumps({"reading_list": []})
        
        return json.dumps({
            "topic": session.topic,
            "reading_list": session.reading_list
        }, indent=2, ensure_ascii=False)
    
    @mcp.resource("session://cache-stats")
    def get_cache_stats_resource() -> str:
        """Article cache statistics."""
        session = session_manager.get_current_session()
        if not session:
            return json.dumps({"cached_articles": 0})
        
        return json.dumps({
            "cached_articles": len(session.article_cache),
            "cached_pmids": list(session.article_cache.keys())
        }, indent=2, ensure_ascii=False)
