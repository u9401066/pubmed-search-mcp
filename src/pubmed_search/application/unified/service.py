"""Application-level unified-search service facade.

The service owns the stable request shape used by external Python callers. It
does not import MCP, FastMCP, tool modules, or settings. Adapters inject the
actual runtime runner so the MCP surface and SDK can evolve without binding
callers to presentation internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from collections.abc import Awaitable


@dataclass(frozen=True)
class UnifiedSearchRunRequest:
    """Stable application request for a unified literature search."""

    query: str
    limit: int | str = 10
    sources: str | None = None
    ranking: Literal["balanced", "impact", "recency", "quality"] = "balanced"
    output_format: Literal["markdown", "json", "toon"] = "json"
    filters: str | None = None
    options: str | None = None
    pipeline: str | None = None
    dry_run: bool = False
    stop_at: str = ""

    def to_runner_kwargs(self) -> dict[str, Any]:
        """Return keyword arguments expected by a runtime unified-search runner."""
        return {
            "query": self.query,
            "limit": self.limit,
            "sources": self.sources,
            "ranking": self.ranking,
            "output_format": self.output_format,
            "filters": self.filters,
            "options": self.options,
            "pipeline": self.pipeline,
            "dry_run": self.dry_run,
            "stop_at": self.stop_at,
        }


class UnifiedSearchRunner(Protocol):
    """Runtime adapter callable for unified search execution."""

    def __call__(self, **kwargs: Any) -> Awaitable[str]:
        """Run unified search and return the serialized response payload."""


class UnifiedSearchService:
    """Small application facade around an injected unified-search runner."""

    def __init__(self, runner: UnifiedSearchRunner) -> None:
        self._runner = runner

    async def search(self, request: UnifiedSearchRunRequest) -> str:
        """Run a unified search using the configured runtime adapter."""
        return await self._runner(**request.to_runner_kwargs())


def make_noop_unified_search_runner(message: str) -> UnifiedSearchRunner:
    """Create a runner that reports why unified search is unavailable."""

    async def _runner(**_kwargs: Any) -> str:
        return message

    return _runner


__all__ = [
    "UnifiedSearchRunRequest",
    "UnifiedSearchRunner",
    "UnifiedSearchService",
    "make_noop_unified_search_runner",
]
