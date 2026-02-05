"""
PubTator3 API Integration

Provides entity resolution and relation queries via NCBI PubTator3 API.

Features:
- Entity autocomplete (Gene, Disease, Chemical, Species, Variant)
- Relation queries (treat, associate, cause, interact)
- Built-in rate limiting (3 req/sec)
- Async HTTP client with retry
"""

from pubmed_search.infrastructure.pubtator.client import (
    PubTatorClient,
    get_pubtator_client,
)
from pubmed_search.infrastructure.pubtator.models import (
    EntityMatch,
    RelationMatch,
    PubTatorEntity,
)

__all__ = [
    "PubTatorClient",
    "get_pubtator_client",
    "EntityMatch",
    "RelationMatch",
    "PubTatorEntity",
]
