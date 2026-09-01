"""Server-scoped session dependencies and cache helpers for MCP tools.

Every :class:`PubMedMCPServer` binds its immutable runtime at the tool-call
boundary.  The binding is context-local, so interleaved calls made through two
server instances cannot redirect session, tenant-registry, or strategy access
to whichever server happened to be constructed last.
"""

from __future__ import annotations

import logging
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from pubmed_search.application.citation_network import CitationTaskSupervisor

from .tool_runtime import HostCallbackRuntime

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pubmed_search.application.session.manager import SessionManager
    from pubmed_search.application.session.registry import SessionManagerRegistry
    from pubmed_search.infrastructure.sources.runtime import SourceRuntime

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolSessionRuntime:
    """Dependencies owned by one MCP server instance."""

    session_manager: SessionManager | None = None
    session_registry: SessionManagerRegistry | None = None
    strategy_generator: Any | None = None
    source_runtime: SourceRuntime | None = None
    host_callbacks: HostCallbackRuntime = field(default_factory=HostCallbackRuntime)
    citation_tasks: CitationTaskSupervisor = field(default_factory=CitationTaskSupervisor)

    def manager_for_current_tenant(self) -> SessionManager | None:
        """Resolve the active tenant without mutating the server runtime."""
        if self.session_registry is not None:
            return self.session_registry.for_tenant()
        return self.session_manager


_ACTIVE_RUNTIME: ContextVar[ToolSessionRuntime | None] = ContextVar(
    "pubmed_mcp_tool_session_runtime",
    default=None,
)


@contextmanager
def bind_tool_session_runtime(runtime: ToolSessionRuntime) -> Iterator[None]:
    """Bind *runtime* for exactly one tool invocation and restore afterwards."""
    token: Token[ToolSessionRuntime | None] = _ACTIVE_RUNTIME.set(runtime)
    try:
        with ExitStack() as stack:
            if runtime.source_runtime is not None:
                from pubmed_search.infrastructure.sources.runtime import bind_source_runtime
                from pubmed_search.shared.async_utils import bind_shared_async_client_runtime

                stack.enter_context(bind_source_runtime(runtime.source_runtime))
                stack.enter_context(bind_shared_async_client_runtime(runtime.source_runtime.shared_http))
            yield
    finally:
        _ACTIVE_RUNTIME.reset(token)


def get_tool_session_runtime() -> ToolSessionRuntime:
    """Return the runtime bound to the current execution context."""
    runtime = _ACTIVE_RUNTIME.get()
    if runtime is None:
        runtime = ToolSessionRuntime()
        _ACTIVE_RUNTIME.set(runtime)
    return runtime


def set_session_manager(session_manager):
    """Install an ambient context-local manager for direct helper invocation.

    Server registration never calls this function. Production tool invocations
    are always wrapped in :func:`bind_tool_session_runtime`; this setter exists
    only for code that deliberately invokes internal helpers outside a server.
    """
    _ACTIVE_RUNTIME.set(
        replace(
            get_tool_session_runtime(),
            session_manager=session_manager,
            session_registry=None,
        )
    )


def set_session_registry(registry: SessionManagerRegistry | None) -> None:
    """Install the per-tenant session manager registry.

    Args:
        registry: Registry that resolves a manager for the current tenant, or
            ``None`` to fall back to the single shared manager.
    """
    _ACTIVE_RUNTIME.set(replace(get_tool_session_runtime(), session_registry=registry))


def get_session_registry() -> SessionManagerRegistry | None:
    """Return the installed per-tenant registry, if any."""
    return get_tool_session_runtime().session_registry


def set_strategy_generator(generator):
    """Set the strategy generator for intelligent query generation."""
    _ACTIVE_RUNTIME.set(replace(get_tool_session_runtime(), strategy_generator=generator))


def get_session_manager() -> Any:
    """Get the session manager for the tenant bound to the current request."""
    return get_tool_session_runtime().manager_for_current_tenant()


def get_strategy_generator():
    """Get the current strategy generator."""
    return get_tool_session_runtime().strategy_generator


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
    if session_manager and results:
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
        pmids = [r.get("pmid") for r in results if r.get("pmid")]
    else:
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
    "bind_tool_session_runtime",
    "get_last_search_pmids",
    "get_session_manager",
    "get_session_registry",
    "get_strategy_generator",
    "get_tool_session_runtime",
    "ToolSessionRuntime",
]
