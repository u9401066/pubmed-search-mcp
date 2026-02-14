"""
Cache Infrastructure

Provides caching layers for expensive API calls.
"""

from __future__ import annotations

from pubmed_search.infrastructure.cache.entity_cache import (
    EntityCache,
    get_entity_cache,
)

__all__ = [
    "EntityCache",
    "get_entity_cache",
]
