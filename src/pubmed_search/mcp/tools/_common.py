"""
Common utilities for MCP tools.

Shared functions:
- Session manager and strategy generator setup
- Result caching and cache lookup
- Output formatting
"""

import logging
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# Global references (set by server.py after initialization)
_session_manager = None
_strategy_generator = None


def set_session_manager(session_manager):
    """Set the session manager for automatic caching."""
    global _session_manager
    _session_manager = session_manager


def set_strategy_generator(generator):
    """Set the strategy generator for intelligent query generation."""
    global _strategy_generator
    _strategy_generator = generator


def get_session_manager():
    """Get the current session manager."""
    return _session_manager


def get_strategy_generator():
    """Get the current strategy generator."""
    return _strategy_generator


def check_cache(query: str, limit: int = None) -> Optional[List[Dict]]:
    """
    Check if search results exist in cache.
    
    Args:
        query: Search query string
        limit: Required number of results
        
    Returns:
        Cached results if found, None otherwise
    """
    if not _session_manager:
        return None
    
    try:
        return _session_manager.find_cached_search(query, limit)
    except Exception as e:
        logger.warning(f"Cache lookup failed: {e}")
        return None


def _cache_results(results: list, query: str = None):
    """Cache search results if session manager is available."""
    if _session_manager and results and not results[0].get('error'):
        try:
            _session_manager.add_to_cache(results)
            if query:
                pmids = [r.get('pmid') for r in results if r.get('pmid')]
                _session_manager.add_search_record(query, pmids)
            logger.debug(f"Cached {len(results)} articles")
        except Exception as e:
            logger.warning(f"Failed to cache results: {e}")


def _record_search_only(results: list, query: str):
    """Record search in history without caching article details.
    
    Used for filtered searches where we don't want to pollute the cache
    but still want to support 'last' export feature.
    """
    if _session_manager and results and not results[0].get('error'):
        try:
            pmids = [r.get('pmid') for r in results if r.get('pmid')]
            _session_manager.add_search_record(query, pmids)
            logger.debug(f"Recorded search '{query}' with {len(pmids)} PMIDs")
        except Exception as e:
            logger.warning(f"Failed to record search: {e}")


def get_last_search_pmids() -> List[str]:
    """Get PMIDs from the most recent search.
    
    Returns:
        List of PMIDs from last search, or empty list if none.
    """
    if not _session_manager:
        return []
    
    try:
        session = _session_manager.get_or_create_session()
        if session.search_history:
            last_search = session.search_history[-1]
            return last_search.pmids
        return []
    except Exception as e:
        logger.warning(f"Failed to get last search PMIDs: {e}")
        return []


def format_search_results(results: list, include_doi: bool = True) -> str:
    """Format search results for display."""
    if not results:
        return "No results found."
        
    if "error" in results[0]:
        return f"Error searching PubMed: {results[0]['error']}"
        
    formatted_output = f"Found {len(results)} results:\n\n"
    for i, paper in enumerate(results, 1):
        formatted_output += f"{i}. **{paper['title']}**\n"
        authors = paper.get('authors', [])
        formatted_output += f"   Authors: {', '.join(authors[:3])}{' et al.' if len(authors) > 3 else ''}\n"
        journal = paper.get('journal', 'Unknown Journal')
        year = paper.get('year', '')
        volume = paper.get('volume', '')
        pages = paper.get('pages', '')
        
        journal_info = f"{journal} ({year})"
        if volume:
            journal_info += f"; {volume}"
            if pages:
                journal_info += f": {pages}"
        formatted_output += f"   Journal: {journal_info}\n"
        formatted_output += f"   PMID: {paper.get('pmid', '')}"
        
        if include_doi and paper.get('doi'):
            formatted_output += f" | DOI: {paper['doi']}"
        if paper.get('pmc_id'):
            formatted_output += f" | PMC: {paper['pmc_id']} 📄"
        
        formatted_output += "\n"
        
        abstract = paper.get('abstract', '')
        if abstract:
            formatted_output += f"   Abstract: {abstract[:200]}...\n"
        formatted_output += "\n"
        
    return formatted_output
