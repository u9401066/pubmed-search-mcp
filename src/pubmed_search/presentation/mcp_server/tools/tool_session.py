"""Session and cache helpers shared across MCP tools.

Design:
    This module acts as a thin shared state bridge for session caching and
    search-history recording. Tool modules use it to avoid duplicating common
    cache interactions while keeping the session manager itself elsewhere.

    ``get_session_manager()`` resolves per tenant. When a registry is installed
    the returned manager belongs to the tenant bound to the current request, so
    concurrent agents never share cached articles, search history, ``last``
    PMIDs, or artifacts. Tool modules call the same accessor as before and need
    no awareness of tenancy.

Maintenance:
    Keep this file as a small adapter layer. If session behavior grows more
    complex, move logic into dedicated session services rather than expanding
    global state patterns here.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pubmed_search.application.session.registry import SessionManagerRegistry

logger = logging.getLogger(__name__)

_session_manager = None
_session_registry: SessionManagerRegistry | None = None
_strategy_generator = None


def set_session_manager(session_manager):
    """Install a single shared session manager, disabling per-tenant routing.

    This is the single-caller mode used by stdio installs, tests, and the Python
    SDK. Call :func:`set_session_registry` afterwards to re-enable per-tenant
    isolation.
    """
    global _session_manager, _session_registry
    _session_manager = session_manager
    _session_registry = None


def set_session_registry(registry: SessionManagerRegistry | None) -> None:
    """Install the per-tenant session manager registry.

    Args:
        registry: Registry that resolves a manager for the current tenant, or
            ``None`` to fall back to the single shared manager.
    """
    global _session_registry
    _session_registry = registry


def get_session_registry() -> SessionManagerRegistry | None:
    """Return the installed per-tenant registry, if any."""
    return _session_registry


def set_strategy_generator(generator):
    """Set the strategy generator for intelligent query generation."""
    global _strategy_generator
    _strategy_generator = generator


def get_session_manager() -> Any:
    """Get the session manager for the tenant bound to the current request."""
    if _session_registry is not None:
        return _session_registry.for_tenant()
    return _session_manager


def get_strategy_generator():
    """Get the current strategy generator."""
    return _strategy_generator


def check_cache(query: str, limit: int | None = None) -> list[dict] | None:
    session_manager = get_session_manager()
    if not session_manager:
        return None

    try:
        return session_manager.find_cached_search(query, limit)
    except Exception as exc:
        logger.warning("Cache lookup failed (%s)", type(exc).__name__)
        return None


def _cache_results(results: list, query: str | None = None):
    session_manager = get_session_manager()
    if session_manager and results and not results[0].get("error"):
        try:
            session_manager.add_to_cache(results, _skip_save=bool(query))
            if query:
                pmids = [r.get("pmid") for r in results if r.get("pmid")]
                session_manager.add_search_record(query, pmids)
            logger.debug("Cached %s articles", len(results))
        except Exception as exc:
            logger.warning("Failed to cache results (%s)", type(exc).__name__)


def _record_search_only(results: list, query: str):
    session_manager = get_session_manager()
    if not session_manager or not results:
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
            session_manager.add_search_record(query, pmids)
            logger.debug("Recorded search with %s PMIDs", len(pmids))
        except Exception as exc:
            logger.warning("Failed to record search (%s)", type(exc).__name__)


def get_last_search_pmids() -> list[str]:
    session_manager = get_session_manager()
    if not session_manager:
        return []

    try:
        session = session_manager.get_or_create_session()
        if session.search_history:
            last_search = session.search_history[-1]
            if isinstance(last_search, dict):
                return last_search.get("pmids", [])
            return last_search.pmids
        return []
    except Exception as exc:
        logger.warning("Failed to get last search PMIDs (%s)", type(exc).__name__)
        return []


__all__ = [
    "_cache_results",
    "_record_search_only",
    "check_cache",
    "get_last_search_pmids",
    "get_session_manager",
    "get_session_registry",
    "get_strategy_generator",
    "set_session_manager",
    "set_session_registry",
    "set_strategy_generator",
]
