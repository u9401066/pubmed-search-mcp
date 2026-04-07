"""
Cache infrastructure exports.

Design:
    This package exposes the shared cache substrate and the common entity cache
    wrapper used by multiple infrastructure clients.

Maintenance:
    Keep this file focused on re-exporting stable cache primitives. Detailed
    cache behavior belongs in the substrate and wrapper modules themselves.
"""

from __future__ import annotations

from pubmed_search.infrastructure.cache.entity_cache import (
    EntityCache,
    get_entity_cache,
)
from pubmed_search.shared.cache_substrate import (
    CacheStats,
    CacheStore,
    JsonFileCacheBackend,
    MemoryCacheBackend,
)

__all__ = [
    "CacheStats",
    "CacheStore",
    "EntityCache",
    "get_entity_cache",
    "JsonFileCacheBackend",
    "MemoryCacheBackend",
]
