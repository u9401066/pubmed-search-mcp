"""
Entity Cache

In-memory cache with TTL for entity resolution results.
Uses cachetools.TTLCache for LRU eviction and TTL expiration.

Features:
- Time-based expiration (TTL) via cachetools
- LRU eviction when max size reached
- Async-safe with locks
- Simple key-value interface
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar

from cachetools import TTLCache


logger = logging.getLogger(__name__)

T = TypeVar("T")


class EntityCache:
    """
    In-memory cache for entity resolution.

    Uses cachetools.TTLCache for LRU eviction and TTL-based expiration.
    Thread-safe for async usage via asyncio.Lock.

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
        self._cache: TTLCache[str, Any] = TTLCache(maxsize=max_size, ttl=ttl)
        self._lock = asyncio.Lock()
        self._stats = CacheStats()

    @property
    def stats(self) -> "CacheStats":
        """Get cache statistics."""
        return self._stats

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
        nkey = self._normalize_key(key)
        try:
            value = self._cache[nkey]
            self._stats.hits += 1
            return value
        except KeyError:
            self._stats.misses += 1
            return None

    def set(self, key: str, value: Any) -> None:
        """
        Set value in cache (sync).

        Args:
            key: Cache key
            value: Value to cache
        """
        nkey = self._normalize_key(key)
        self._cache[nkey] = value

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
        # Try cache first (no lock needed for read)
        value = self.get(key)
        if value is not None:
            logger.debug(f"Cache hit: {key}")
            return value

        # Fetch with lock to prevent thundering herd
        async with self._lock:
            # Double-check after acquiring lock
            value = self.get(key)
            if value is not None:
                return value

            # Fetch
            try:
                value = await fetch_func()
                if value is not None:
                    self.set(key, value)
                return value
            except Exception as e:
                logger.error(f"Fetch failed for {key}: {e}")
                return None

    def invalidate(self, key: str) -> bool:
        """
        Invalidate cache entry.

        Args:
            key: Cache key

        Returns:
            True if entry was removed
        """
        nkey = self._normalize_key(key)
        try:
            del self._cache[nkey]
            return True
        except KeyError:
            return False

    def clear(self) -> int:
        """
        Clear all cache entries.

        Returns:
            Number of entries cleared
        """
        count = len(self._cache)
        self._cache.clear()
        return count

    def cleanup_expired(self) -> int:
        """
        Remove all expired entries.

        cachetools.TTLCache handles expiration lazily on access.
        This method triggers an explicit cleanup via expire().

        Returns:
            Number of entries removed
        """
        expired = self._cache.expire()
        removed = len(expired)
        self._stats.expirations += removed
        return removed

    def __len__(self) -> int:
        """Get number of cached entries."""
        return len(self._cache)

    def __contains__(self, key: str) -> bool:
        """Check if key is in cache (may be expired)."""
        return self._normalize_key(key) in self._cache


@dataclass
class CacheStats:
    """Cache statistics."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expirations: int = 0

    @property
    def total_requests(self) -> int:
        """Total cache requests."""
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        """Cache hit rate (0-1)."""
        total = self.total_requests
        return self.hits / total if total > 0 else 0.0

    def reset(self) -> None:
        """Reset statistics."""
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.expirations = 0


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
