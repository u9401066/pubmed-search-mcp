"""
SemanticEnhancer - Deep Query Understanding via PubTator3

Resolves biomedical terms through an injected PubTator-compatible port and
builds baseline, MeSH-constrained, entity and broad retrieval variants.
The unified planner chooses whether to use this optional enhancement; resolver
failure preserves baseline search. Expected precision/recall fields are static
planning hints, not measurements against relevance judgments.

"""

from __future__ import annotations

import asyncio
import hmac
import logging
import secrets
from dataclasses import dataclass, field
from typing import Any, Protocol

from pubmed_search.shared.tenancy import current_tenant_id

logger = logging.getLogger(__name__)
_ENTITY_CACHE_KEY_SECRET = secrets.token_bytes(32)


def _entity_cache_key(term: str) -> str:
    """Return an opaque, tenant-scoped key for one terminology lookup."""

    normalized = term.casefold().strip()
    payload = f"{current_tenant_id()}\0{normalized}".encode()
    digest = hmac.digest(_ENTITY_CACHE_KEY_SECRET, payload, "sha256").hex()
    return f"entity:v2:{digest}"


# =============================================================================
# Ports and Data Classes
# =============================================================================


@dataclass(frozen=True, slots=True)
class ResolvedEntity:
    """Application-owned normalized biomedical entity."""

    original_text: str
    resolved_name: str
    entity_type: str
    entity_id: str
    mesh_id: str | None = None
    ncbi_id: str | None = None

    def to_search_term(self) -> str:
        """Generate a PubMed search expression for this entity."""
        if self.mesh_id:
            return f'"{self.resolved_name}"[MeSH Terms]'
        if self.entity_type == "gene" and self.ncbi_id:
            return f"{self.resolved_name}[Gene Name]"
        return f'"{self.resolved_name}"'


class EntityResolverPort(Protocol):
    """Resolve one term through an outer biomedical terminology adapter."""

    async def resolve_entity(self, text: str) -> ResolvedEntity | None:
        """Return a normalized entity, or ``None`` when not resolved."""


class EntityCachePort(Protocol):
    """Minimal cache contract used by semantic enhancement."""

    def get(self, key: str) -> Any | None:
        """Return a cached entity if present."""

    def set(self, key: str, value: Any) -> None:
        """Store one resolved entity."""


@dataclass
class ExpandedTerm:
    """A search term with its expansion source."""

    term: str
    source: str  # "original", "mesh", "pubtator", "synonym"
    confidence: float = 1.0
    mesh_id: str | None = None

    def to_pubmed_query(self, field: str | None = None) -> str:
        """Convert to PubMed query format."""
        if self.mesh_id:
            return f'"{self.term}"[MeSH Terms]'
        if field:
            return f'"{self.term}"[{field}]'
        return f'"{self.term}"'


@dataclass
class SearchPlan:
    """A search strategy with query and metadata."""

    name: str  # "original", "mesh_expanded", "entity_semantic", "fulltext"
    query: str  # Actual search query
    source: str  # Target source: "pubmed", "europe_pmc", "core"
    priority: int = 1  # Higher = execute first
    expected_precision: float = 0.5  # Estimated precision
    expected_recall: float = 0.5  # Estimated recall

    def __lt__(self, other: SearchPlan) -> bool:
        """Sort by priority (descending)."""
        return self.priority > other.priority


@dataclass
class EnhancedQuery:
    """
    Result of semantic enhancement.

    Contains all information needed for deep+wide search.
    """

    # Original query
    original_query: str

    # Resolved biomedical entities
    entities: list[ResolvedEntity] = field(default_factory=list)

    # Expanded search terms
    expanded_terms: list[ExpandedTerm] = field(default_factory=list)

    # Generated search strategies
    strategies: list[SearchPlan] = field(default_factory=list)

    # Detected PICO elements (enhanced)
    pico_elements: dict[str, list[str]] = field(default_factory=dict)

    # Spell corrections (from espell)
    spell_corrections: list[str] = field(default_factory=list)

    # Enhancement metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_entities(self) -> bool:
        """Check if any entities were resolved."""
        return len(self.entities) > 0

    @property
    def primary_mesh_terms(self) -> list[str]:
        """Get primary MeSH terms from resolved entities."""
        return [e.mesh_id for e in self.entities if e.mesh_id]

    def get_best_strategy(self) -> SearchPlan | None:
        """Get highest priority strategy."""
        if not self.strategies:
            return None
        return max(self.strategies, key=lambda s: s.priority)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "original_query": self.original_query,
            "entities": [
                {
                    "text": e.original_text,
                    "resolved_name": e.resolved_name,
                    "type": e.entity_type,
                    "mesh_id": e.mesh_id,
                }
                for e in self.entities
            ],
            "expanded_terms": [
                {
                    "term": t.term,
                    "source": t.source,
                    "mesh_id": t.mesh_id,
                }
                for t in self.expanded_terms
            ],
            "strategies": [
                {
                    "name": s.name,
                    "query": s.query,
                    "source": s.source,
                    "priority": s.priority,
                }
                for s in self.strategies
            ],
            "pico_elements": self.pico_elements,
            "spell_corrections": self.spell_corrections,
        }


# =============================================================================
# SemanticEnhancer
# =============================================================================


class SemanticEnhancer:
    """
    Enhances queries with semantic understanding via PubTator3.

    For queries selected by the unified planner, optional enhancement provides:
    1. Entity resolution (PubTator3) - Standardize biomedical terms
    2. Term expansion (MeSH, synonyms) - Broaden coverage
    3. Strategy generation - Multiple search approaches

    Simple lookups and explicit provider requests can bypass enhancement.
    Baseline retrieval remains available when the resolver fails or times out.

    Usage:
        enhancer = SemanticEnhancer(entity_resolver=resolver)
        enhanced = await enhancer.enhance("propofol sedation ICU")

        for strategy in enhanced.strategies:
            results = await search(strategy.query, source=strategy.source)
    """

    # Entity types to resolve
    ENTITY_TYPES = ["chemical", "disease", "gene", "species", "variant"]

    # Stop words to skip during entity resolution
    STOP_WORDS = {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "in",
        "on",
        "at",
        "for",
        "to",
        "of",
        "and",
        "or",
        "with",
        "study",
        "studies",
        "trial",
        "trials",
        "patient",
        "patients",
        "effect",
        "effects",
        "treatment",
        "treatments",
        "therapy",
        "outcome",
        "outcomes",
        "result",
        "results",
        "analysis",
    }

    def __init__(
        self,
        entity_resolver: EntityResolverPort,
        entity_cache: EntityCachePort | None = None,
        timeout: float = 5.0,
    ):
        """
        Initialize SemanticEnhancer.

        Args:
            entity_resolver: Outer adapter for PubTator-style entity resolution
            entity_cache: Optional tenant-safe entity cache adapter
            timeout: Maximum time for enhancement (seconds)
        """
        self._resolver = entity_resolver
        self._cache = entity_cache
        self._timeout = timeout

    async def enhance(self, query: str) -> EnhancedQuery:
        """
        Enhance a query with semantic understanding.

        This is the main entry point. Every search query should go through
        this method to get deep semantic understanding.

        Args:
            query: User's search query

        Returns:
            EnhancedQuery with entities, expanded terms, and strategies
        """
        enhanced = EnhancedQuery(original_query=query)

        try:
            # Run the asynchronous enhancement phase with a bounded timeout.
            # Phase 1: Entity resolution + term extraction
            entities, terms = await asyncio.wait_for(
                self._resolve_and_expand(query),
                timeout=self._timeout,
            )
            enhanced.entities = entities
            enhanced.expanded_terms = terms

            # Phase 2: Generate search strategies
            enhanced.strategies = self._generate_strategies(query, entities, terms)

            # Add metadata
            enhanced.metadata["enhancement_version"] = "1.0"
            enhanced.metadata["entity_count"] = len(entities)
            enhanced.metadata["term_count"] = len(terms)
            enhanced.metadata["strategy_count"] = len(enhanced.strategies)

        except (asyncio.TimeoutError, TimeoutError):
            logger.warning("Semantic enhancement timed out (query_length=%s)", len(query))
            # Fall back to basic enhancement
            enhanced = self._basic_enhancement(query)
            enhanced.metadata["timeout"] = True

        except Exception as exc:
            logger.warning("Semantic enhancement failed (%s)", type(exc).__name__)
            # Fall back to basic enhancement
            enhanced = self._basic_enhancement(query)
            enhanced.metadata["error"] = type(exc).__name__

        return enhanced

    async def _resolve_and_expand(
        self,
        query: str,
    ) -> tuple[list[ResolvedEntity], list[ExpandedTerm]]:
        """
        Resolve entities and expand terms.

        Uses PubTator3 for entity resolution with optional caching.
        """
        cache = self._cache

        # Extract candidate terms from query
        candidates = self._extract_candidates(query)

        entities: list[ResolvedEntity] = []
        expanded_terms: list[ExpandedTerm] = []

        # Add original query terms
        for candidate in candidates[:10]:  # Limit candidates
            expanded_terms.append(
                ExpandedTerm(
                    term=candidate,
                    source="original",
                    confidence=1.0,
                )
            )

        # Resolve entities in parallel
        async def resolve_one(term: str) -> ResolvedEntity | None:
            # Check cache first
            cache_key = _entity_cache_key(term)
            if cache is not None:
                cached = cache.get(cache_key)
                if cached is not None:
                    return cached  # type: ignore[no-any-return]

            # Resolve via PubTator3
            entity = await self._resolver.resolve_entity(term)

            # Cache result
            if cache is not None and entity:
                cache.set(cache_key, entity)

            return entity

        # Run resolutions in parallel (limited concurrency)
        tasks = [resolve_one(term) for term in candidates[:5]]  # Top 5 terms
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, ResolvedEntity):
                entities.append(result)

                # Add expanded term from entity
                expanded_terms.append(
                    ExpandedTerm(
                        term=result.resolved_name,
                        source="pubtator",
                        confidence=0.9,
                        mesh_id=result.mesh_id,
                    )
                )

        return entities, expanded_terms

    def _extract_candidates(self, query: str) -> list[str]:
        """
        Extract candidate terms for entity resolution.

        Returns terms ordered by likely importance (longer, more specific first).
        """
        import re

        # Field names and Boolean operators are syntax, not biomedical entities.
        query = re.sub(r"\[[^\]]*\]", " ", query)
        # Extract quoted phrases first
        quoted = re.findall(r'"([^"]+)"', query)

        # Extract remaining words
        unquoted = re.sub(r'"[^"]+"', "", query)
        words = re.findall(r"\b[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*\b", unquoted)

        # Filter stop words
        words = [w for w in words if len(w) >= 2 and w.lower() not in self.STOP_WORDS and w.lower() != "not"]

        # Build candidate list: quoted phrases + long words + short words
        candidates = []
        candidates.extend(quoted)
        candidates.extend([w for w in words if len(w) >= 5])
        candidates.extend([w for w in words if len(w) < 5])

        # Remove duplicates while preserving order
        seen = set()
        unique = []
        for c in candidates:
            c_lower = c.lower()
            if c_lower not in seen:
                seen.add(c_lower)
                unique.append(c)

        return unique

    def _generate_strategies(
        self,
        query: str,
        entities: list[ResolvedEntity],
        terms: list[ExpandedTerm],
    ) -> list[SearchPlan]:
        """
        Generate multiple search strategies for deep+wide search.

        Always generates multiple strategies to ensure comprehensive coverage.
        """
        strategies: list[SearchPlan] = []

        # Strategy 1: Original query (baseline)
        strategies.append(
            SearchPlan(
                name="original",
                query=query,
                source="pubmed",
                priority=1,
                expected_precision=0.7,
                expected_recall=0.5,
            )
        )

        # Strategy 2: MeSH expanded (if entities have MeSH IDs)
        mesh_terms = [e for e in entities if e.mesh_id]
        if mesh_terms:
            mesh_query = self._build_mesh_query(query, mesh_terms)
            strategies.append(
                SearchPlan(
                    name="mesh_expanded",
                    query=mesh_query,
                    source="pubmed",
                    priority=2,
                    expected_precision=0.8,
                    expected_recall=0.7,
                )
            )

        # Strategy 3: Entity-based semantic search (via PubTator3 IDs)
        if entities:
            entity_query = self._build_entity_query(entities)
            strategies.append(
                SearchPlan(
                    name="entity_semantic",
                    query=entity_query,
                    source="pubmed",
                    priority=3,
                    expected_precision=0.9,
                    expected_recall=0.4,
                )
            )

        # Strategy 4: Full-text search on Europe PMC
        strategies.append(
            SearchPlan(
                name="fulltext_epmc",
                query=query,
                source="europe_pmc",
                priority=1,
                expected_precision=0.5,
                expected_recall=0.8,
            )
        )

        # Strategy 5: Broad title/abstract search
        broad_query = self._build_broad_query(terms)
        if broad_query and broad_query != query:
            strategies.append(
                SearchPlan(
                    name="broad_tiab",
                    query=broad_query,
                    source="pubmed",
                    priority=0,
                    expected_precision=0.4,
                    expected_recall=0.9,
                )
            )

        return sorted(strategies)

    def _build_mesh_query(
        self,
        original_query: str,
        mesh_entities: list[ResolvedEntity],
    ) -> str:
        """Build query with MeSH term expansion."""
        mesh_parts = []
        for entity in mesh_entities:
            if entity.mesh_id:
                mesh_parts.append(f'"{entity.resolved_name}"[MeSH Terms]')

        if not mesh_parts:
            return original_query

        # Keep the user's complete constraints. Removing resolved words from
        # a Boolean expression can leave dangling AND/NOT or change its scope.
        # Entity-only and broad strategies provide separate recall variants.
        mesh_clause = " OR ".join(mesh_parts)
        return f"({mesh_clause}) AND ({original_query})"

    def _build_entity_query(self, entities: list[ResolvedEntity]) -> str:
        """Build query using resolved entity names."""
        parts = []
        for entity in entities:
            parts.append(entity.to_search_term())
        return " AND ".join(parts)

    def _build_broad_query(self, terms: list[ExpandedTerm]) -> str:
        """Build broad query for high recall."""
        # Use OR for expanded terms
        unique_terms = []
        seen = set()

        for term in terms:
            if term.term.lower() not in seen:
                seen.add(term.term.lower())
                unique_terms.append(f'"{term.term}"[Title/Abstract]')

        if len(unique_terms) <= 1:
            return unique_terms[0] if unique_terms else ""

        return " OR ".join(unique_terms[:5])  # Limit to 5 terms

    def _basic_enhancement(self, query: str) -> EnhancedQuery:
        """
        Fallback enhancement when PubTator3 is unavailable.

        Still generates multiple strategies for deep+wide search,
        just without entity resolution.
        """
        enhanced = EnhancedQuery(original_query=query)

        # Extract and add original terms
        candidates = self._extract_candidates(query)
        enhanced.expanded_terms = [ExpandedTerm(term=c, source="original", confidence=1.0) for c in candidates[:10]]

        # Generate basic strategies
        enhanced.strategies = [
            SearchPlan(
                name="original",
                query=query,
                source="pubmed",
                priority=1,
                expected_precision=0.6,
                expected_recall=0.5,
            ),
            SearchPlan(
                name="fulltext_epmc",
                query=query,
                source="europe_pmc",
                priority=1,
                expected_precision=0.5,
                expected_recall=0.7,
            ),
        ]

        enhanced.metadata["fallback"] = True
        return enhanced


__all__ = [
    "EnhancedQuery",
    "EntityCachePort",
    "EntityResolverPort",
    "ExpandedTerm",
    "ResolvedEntity",
    "SearchPlan",
    "SemanticEnhancer",
]
