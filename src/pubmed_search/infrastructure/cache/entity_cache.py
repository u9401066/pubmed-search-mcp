"""Entity-focused cache wrapper built on the shared cache substrate.

Design:
    This module provides the common cache-aside pattern used for resolved
    entities and lightweight lookup results. It wraps CacheStore with
    normalized keys and an async-friendly get-or-fetch workflow.

Maintenance:
    Keep this wrapper simple. Changes to eviction, persistence, or statistics
    should usually happen in shared/cache_substrate.py rather than here.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, TypeVar

from pubmed_search.shared.cache_substrate import CacheStats, CacheStore, MemoryCacheBackend

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

T = TypeVar("T")


class EntityCache:
    """
    In-memory entity cache backed by the shared cache substrate.

    Example:
        cache = EntityCache(max_size=1000, ttl=3600)

        # Get or fetch pattern
        entity = await cache.get_or_fetch(
            "propofol",
            lambda: client.resolve_entity("propofol")
        )

        # Direct access
        cache.set("key", value)
        value = cache.get("key")
    """

    def __init__(
        self,
        max_size: int = 1000,
        ttl: float = 3600.0,  # 1 hour default
    ):
        """
        Initialize cache.

        Args:
            max_size: Maximum number of entries
            ttl: Time-to-live in seconds
        """
        self._store = CacheStore[Any](
            MemoryCacheBackend(max_entries=max_size),
            default_ttl=ttl,
            key_normalizer=self._normalize_key,
            name="entity-cache",
        )
        self._lock = asyncio.Lock()

    @property
    def stats(self) -> CacheStats:
        """Get cache statistics."""
        return self._store.stats

    def _normalize_key(self, key: str) -> str:
        """Normalize cache key."""
        return key.lower().strip()

    def get(self, key: str) -> Any | None:
        """
        Get value from cache (sync).

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        return self._store.get(key)

    def set(self, key: str, value: Any) -> None:
        """
        Set value in cache (sync).

        Args:
            key: Cache key
            value: Value to cache
        """
        self._store.set(key, value)

    async def get_or_fetch(
        self,
        key: str,
        fetch_func: Callable[[], Awaitable[T]],
    ) -> T | None:
        """
        Get from cache or fetch and cache result.

        This is the primary method for cache-aside pattern.
        Thread-safe with async lock.

        Args:
            key: Cache key
            fetch_func: Async function to fetch value if not cached

        Returns:
            Cached or freshly fetched value
        """
        return await self._store.get_or_fetch(key, fetch_func)

    def invalidate(self, key: str) -> bool:
        """
        Invalidate cache entry.

        Args:
            key: Cache key

        Returns:
            True if entry was removed
        """
        return self._store.invalidate(key)

    def clear(self) -> int:
        """
        Clear all cache entries.

        Returns:
            Number of entries cleared
        """
        return self._store.clear()

    def cleanup_expired(self) -> int:
        """
        Remove all expired entries.

        cachetools.TTLCache handles expiration lazily on access.
        This method triggers an explicit cleanup via expire().

        Returns:
            Number of entries removed
        """
        return self._store.cleanup_expired()

    def warmup(self, entries: dict[str, Any]) -> int:
        """Preload multiple entity values using the same substrate API."""
        return self._store.warmup(entries)

    def __len__(self) -> int:
        """Get number of cached entries."""
        return len(self._store)

    def __contains__(self, key: str) -> bool:
        """Check if a normalized key resolves to a live cache entry."""
        return key in self._store


# ==================== Singleton Factory ====================

_entity_cache: EntityCache | None = None


def get_entity_cache() -> EntityCache:
    """
    Get singleton entity cache.

    Returns:
        Shared EntityCache instance
    """
    global _entity_cache
    if _entity_cache is None:
        _entity_cache = EntityCache(max_size=1000, ttl=3600)
    return _entity_cache


def reset_entity_cache() -> None:
    """Reset singleton cache (for testing)."""
    global _entity_cache
    if _entity_cache is not None:
        _entity_cache.clear()
    _entity_cache = None
