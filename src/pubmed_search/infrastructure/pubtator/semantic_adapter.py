"""Outer-layer composition for the semantic-enhancement application service."""

from __future__ import annotations

from pubmed_search.application.search.semantic_enhancer import SemanticEnhancer
from pubmed_search.infrastructure.cache import get_entity_cache
from pubmed_search.infrastructure.pubtator.client import get_pubtator_client
from pubmed_search.infrastructure.sources.runtime import get_source_runtime


def get_semantic_enhancer() -> SemanticEnhancer:
    """Return the runtime-owned enhancer with explicit resolver/cache adapters."""

    def _build() -> SemanticEnhancer:
        return SemanticEnhancer(
            entity_resolver=get_pubtator_client(),
            entity_cache=get_entity_cache(),
        )

    return get_source_runtime().get_or_create_client(("semantic_enhancer",), _build)


__all__ = ["get_semantic_enhancer"]
