"""Session and cache helpers shared across MCP tools.

Design:
    This module acts as a thin shared state bridge for session caching and
    search-history recording. Tool modules use it to avoid duplicating common
    cache interactions while keeping the session manager itself elsewhere.

Maintenance:
    Keep this file as a small adapter layer. If session behavior grows more
    complex, move logic into dedicated session services rather than expanding
    global state patterns here.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

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


def check_cache(query: str, limit: int | None = None) -> list[dict] | None:
    if not _session_manager:
        return None

    try:
        return _session_manager.find_cached_search(query, limit)
    except Exception as exc:
        logger.warning("Cache lookup failed: %s", exc)
        return None


def _cache_results(results: list, query: str | None = None):
    if _session_manager and results and not results[0].get("error"):
        try:
            _session_manager.add_to_cache(results, _skip_save=bool(query))
            if query:
                pmids = [r.get("pmid") for r in results if r.get("pmid")]
                _session_manager.add_search_record(query, pmids)
            logger.debug("Cached %s articles", len(results))
        except Exception as exc:
            logger.warning("Failed to cache results: %s", exc)


def _record_search_only(results: list, query: str):
    if not _session_manager or not results:
        return

    first = results[0]
    if isinstance(first, dict):
        if first.get("error"):
            return
        pmids = [r.get("pmid") for r in results if r.get("pmid")]
    else:
        if getattr(first, "error", None):
            return
        pmids = [getattr(r, "pmid", None) for r in results if getattr(r, "pmid", None)]

    if pmids:
        try:
            _session_manager.add_search_record(query, pmids)
            logger.debug("Recorded search '%s' with %s PMIDs", query, len(pmids))
        except Exception as exc:
            logger.warning("Failed to record search: %s", exc)


def get_last_search_pmids() -> list[str]:
    if not _session_manager:
        return []

    try:
        session = _session_manager.get_or_create_session()
        if session.search_history:
            last_search = session.search_history[-1]
            if isinstance(last_search, dict):
                return last_search.get("pmids", [])
            return last_search.pmids
        return []
    except Exception as exc:
        logger.warning("Failed to get last search PMIDs: %s", exc)
        return []


__all__ = [
    "_cache_results",
    "_record_search_only",
    "check_cache",
    "get_last_search_pmids",
    "get_session_manager",
    "get_strategy_generator",
    "set_session_manager",
    "set_strategy_generator",
]