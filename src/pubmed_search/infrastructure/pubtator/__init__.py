"""
PubTator3 API Integration

Provides entity resolution and relation queries via NCBI PubTator3 API.

Features:
- Entity autocomplete (Gene, Disease, Chemical, Species, Variant)
- Relation queries (treat, associate, cause, interact)
- Built-in rate limiting (3 req/sec)
- Async HTTP client with retry

Maintenance:
    Keep request choreography and API model details in the underlying client
    and model modules. This package export should remain a small, stable entry
    point for callers that need PubTator capabilities.
"""

from __future__ import annotations

from pubmed_search.infrastructure.pubtator.client import (
    PubTatorClient,
    get_pubtator_client,
)
from pubmed_search.infrastructure.pubtator.models import (
    EntityMatch,
    PubTatorEntity,
    RelationMatch,
)

__all__ = [
    "EntityMatch",
    "PubTatorClient",
    "PubTatorEntity",
    "RelationMatch",
    "get_pubtator_client",
]
