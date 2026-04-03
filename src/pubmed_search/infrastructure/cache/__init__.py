"""
Cache Infrastructure

Provides caching layers for expensive API calls.
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
