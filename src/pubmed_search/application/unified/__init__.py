"""Reusable unified-search application service contracts.

This package keeps the Python SDK and MCP adapter on the same request shape
without making application code import MCP presentation modules. Runtime source
execution is injected by adapters.
"""

from __future__ import annotations

from .service import (
    UnifiedSearchRunner,
    UnifiedSearchRunRequest,
    UnifiedSearchService,
)

__all__ = ["UnifiedSearchRunRequest", "UnifiedSearchRunner", "UnifiedSearchService"]
