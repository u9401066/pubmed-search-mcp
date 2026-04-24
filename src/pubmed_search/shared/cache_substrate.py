"""Shared cache substrate with backend, TTL, and statistics primitives.

Design:
    This module provides the reusable cache foundation used by higher-level
    infrastructure caches. It separates storage backends, cache-store policy,
    expiration handling, and runtime statistics so feature modules can compose
    caching without reinventing invalidation or persistence behavior.

Maintenance:
    Keep cache semantics centralized here. When adding a backend or changing
    eviction behavior, update this substrate first and let wrappers such as
    EntityCache stay thin.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass
class CacheStats:
    """Runtime statistics for a cache store."""

    hits: int = 0
    misses: int = 0
    writes: int = 0
    invalidations: int = 0
    warmups: int = 0
    expirations: int = 0
    evictions: int = 0

    @property
    def total_requests(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        total = self.total_requests
        return self.hits / total if total else 0.0

    def reset(self) -> None:
        self.hits = 0
        self.misses = 0
        self.writes = 0
        self.invalidations = 0
        self.warmups = 0
        self.expirations = 0
        self.evictions = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "writes": self.writes,
            "invalidations": self.invalidations,
            "warmups": self.warmups,
            "expirations": self.expirations,
            "evictions": self.evictions,
            "total_requests": self.total_requests,
            "hit_rate": self.hit_rate,
        }


@dataclass
class StoredCacheEntry:
    """Serialized cache entry stored by a backend."""

    value: Any
    cached_at: str = field(default_factory=_utcnow_iso)
    expires_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_expired(self, *, now: datetime | None = None) -> bool:
        expires_at = _parse_datetime(self.expires_at)
        if expires_at is None:
            return False
        return (now or _utcnow()) >= expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "cached_at": self.cached_at,
            "expires_at": self.expires_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Any) -> StoredCacheEntry:
        if not isinstance(data, dict):
            return cls(value=data)

        if "value" not in data:
            raw_cached_at = data.get("cached_at")
            cached_at = raw_cached_at if isinstance(raw_cached_at, str) else _utcnow_iso()
            return cls(value=data, cached_at=cached_at)

        metadata = data.get("metadata")
        raw_cached_at = data.get("cached_at")
        cached_at = raw_cached_at if isinstance(raw_cached_at, str) else _utcnow_iso()
        raw_expires_at = data.get("expires_at")
        expires_at = raw_expires_at if isinstance(raw_expires_at, str) else None
        return cls(
            value=data.get("value"),
            cached_at=cached_at,
            expires_at=expires_at,
            metadata=metadata if isinstance(metadata, dict) else {},
        )


class CacheBackend(ABC):
    """Storage backend contract for cache stores."""

    @abstractmethod
    def get_entry(self, key: str) -> StoredCacheEntry | None:
        raise NotImplementedError

    @abstractmethod
    def set_entry(self, key: str, entry: StoredCacheEntry) -> int:
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def keys(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def items(self) -> list[tuple[str, StoredCacheEntry]]:
        raise NotImplementedError


class MemoryCacheBackend(CacheBackend):
    """In-memory backend with optional LRU-style max entry eviction."""

    def __init__(self, max_entries: int | None = None):
        self._entries: OrderedDict[str, StoredCacheEntry] = OrderedDict()
        self._max_entries = max_entries

    def get_entry(self, key: str) -> StoredCacheEntry | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        self._entries.move_to_end(key)
        return entry

    def set_entry(self, key: str, entry: StoredCacheEntry) -> int:
        if key in self._entries:
            del self._entries[key]
        self._entries[key] = entry

        evicted = 0
        while self._max_entries is not None and len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
            evicted += 1
        return evicted

    def delete(self, key: str) -> bool:
        if key not in self._entries:
            return False
        del self._entries[key]
        return True

    def clear(self) -> int:
        count = len(self._entries)
        self._entries.clear()
        return count

    def keys(self) -> list[str]:
        return list(self._entries.keys())

    def items(self) -> list[tuple[str, StoredCacheEntry]]:
        return list(self._entries.items())


class JsonFileCacheBackend(CacheBackend):
    """JSON file-backed cache backend."""

    def __init__(self, file_path: str | Path, max_entries: int | None = None):
        self._file_path = Path(file_path)
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        self._max_entries = max_entries
        self._entries: OrderedDict[str, StoredCacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not self._file_path.exists():
                return

            try:
                with self._file_path.open(encoding="utf-8") as handle:
                    raw = json.load(handle)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("Failed to load cache backend %s: %s", self._file_path, exc)
                return

            if not isinstance(raw, dict):
                logger.warning("Cache backend %s contained unexpected payload type", self._file_path)
                return

            for key, value in raw.items():
                self._entries[str(key)] = StoredCacheEntry.from_dict(value)

    def _save(self) -> None:
        payload = {key: entry.to_dict() for key, entry in self._entries.items()}
        tmp_path = self._file_path.with_name(f"{self._file_path.name}.tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            tmp_path.replace(self._file_path)
        except (OSError, TypeError, ValueError) as exc:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            logger.warning("Failed to persist cache backend %s: %s", self._file_path, exc)

    def get_entry(self, key: str) -> StoredCacheEntry | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return entry

    def set_entry(self, key: str, entry: StoredCacheEntry) -> int:
        with self._lock:
            if key in self._entries:
                del self._entries[key]
            self._entries[key] = entry

            evicted = 0
            while self._max_entries is not None and len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
                evicted += 1

            self._save()
            return evicted

    def delete(self, key: str) -> bool:
        with self._lock:
            if key not in self._entries:
                return False
            del self._entries[key]
            self._save()
            return True

    def clear(self) -> int:
        with self._lock:
            count = len(self._entries)
            if count:
                self._entries.clear()
                self._save()
            return count

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._entries.keys())

    def items(self) -> list[tuple[str, StoredCacheEntry]]:
        with self._lock:
            return list(self._entries.items())


class CacheStore(Generic[T]):
    """Unified cache abstraction used by article, entity, and session-adjacent caches."""

    def __init__(
        self,
        backend: CacheBackend,
        *,
        default_ttl: float | None = None,
        key_normalizer: Callable[[str], str] | None = None,
        serializer: Callable[[T], Any] | None = None,
        deserializer: Callable[[Any], T] | None = None,
        name: str = "cache",
    ):
        self._backend = backend
        self._default_ttl = default_ttl
        self._key_normalizer = key_normalizer or (lambda value: value.strip())
        self._serializer = serializer or (lambda value: value)
        self._deserializer = deserializer or (lambda value: value)
        self._lock = asyncio.Lock()
        self._stats = CacheStats()
        self._name = name

    @property
    def stats(self) -> CacheStats:
        return self._stats

    def _normalize_key(self, key: str) -> str:
        return self._key_normalizer(key)

    def _build_entry(
        self,
        value: T,
        *,
        ttl: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StoredCacheEntry:
        ttl_seconds = self._default_ttl if ttl is None else ttl
        expires_at = None
        if ttl_seconds is not None:
            expires_at = (_utcnow() + timedelta(seconds=ttl_seconds)).isoformat()

        return StoredCacheEntry(
            value=self._serializer(value),
            cached_at=_utcnow_iso(),
            expires_at=expires_at,
            metadata=metadata or {},
        )

    def get(self, key: str) -> T | None:
        nkey = self._normalize_key(key)
        entry = self._backend.get_entry(nkey)
        if entry is None:
            self._stats.misses += 1
            return None

        if entry.is_expired():
            self._backend.delete(nkey)
            self._stats.misses += 1
            self._stats.expirations += 1
            return None

        self._stats.hits += 1
        return self._deserializer(entry.value)

    def get_many(self, keys: list[str]) -> tuple[dict[str, T], list[str]]:
        cached: dict[str, T] = {}
        missing: list[str] = []

        for key in keys:
            value = self.get(key)
            if value is None:
                missing.append(key)
            else:
                cached[key] = value

        return cached, missing

    def set(
        self,
        key: str,
        value: T,
        *,
        ttl: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        nkey = self._normalize_key(key)
        evicted = self._backend.set_entry(nkey, self._build_entry(value, ttl=ttl, metadata=metadata))
        self._stats.writes += 1
        self._stats.evictions += evicted

    def warmup(
        self,
        entries: dict[str, T] | list[tuple[str, T]],
        *,
        ttl: float | None = None,
        metadata_factory: Callable[[str, T], dict[str, Any] | None] | None = None,
    ) -> int:
        pairs = entries.items() if isinstance(entries, dict) else entries
        warmed = 0
        evicted = 0

        for key, value in pairs:
            metadata = metadata_factory(key, value) if metadata_factory else None
            evicted += self._backend.set_entry(
                self._normalize_key(key),
                self._build_entry(value, ttl=ttl, metadata=metadata),
            )
            warmed += 1

        if warmed:
            self._stats.warmups += warmed
            self._stats.evictions += evicted
        return warmed

    def invalidate(self, key: str) -> bool:
        removed = self._backend.delete(self._normalize_key(key))
        if removed:
            self._stats.invalidations += 1
        return removed

    def clear(self) -> int:
        removed = self._backend.clear()
        if removed:
            self._stats.invalidations += removed
        return removed

    def cleanup_expired(self) -> int:
        removed = 0
        for key, entry in list(self._backend.items()):
            if entry.is_expired() and self._backend.delete(key):
                removed += 1

        if removed:
            self._stats.expirations += removed
        return removed

    def keys(self) -> list[str]:
        self.cleanup_expired()
        return self._backend.keys()

    def get_or_create(self, key: str, factory: Callable[[], T | None]) -> T | None:
        value = self.get(key)
        if value is not None:
            return value

        created = factory()
        if created is not None:
            self.set(key, created)
        return created

    async def get_or_fetch(self, key: str, fetch_func: Callable[[], Awaitable[T | None]]) -> T | None:
        value = self.get(key)
        if value is not None:
            return value

        async with self._lock:
            value = self.get(key)
            if value is not None:
                return value

            try:
                fetched = await fetch_func()
            except Exception:
                logger.exception("Cache fetch failed for %s (%s)", key, self._name)
                return None

            if fetched is not None:
                self.set(key, fetched)
            return fetched

    def snapshot(self) -> dict[str, Any]:
        return self._stats.snapshot()

    def __len__(self) -> int:
        return len(self.keys())

    def __contains__(self, key: str) -> bool:
        nkey = self._normalize_key(key)
        entry = self._backend.get_entry(nkey)
        if entry is None:
            return False
        if entry.is_expired():
            self._backend.delete(nkey)
            return False
        return True
