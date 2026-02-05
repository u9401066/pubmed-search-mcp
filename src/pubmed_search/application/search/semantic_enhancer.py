"""
SemanticEnhancer - Deep Query Understanding via PubTator3

This module provides semantic understanding of biomedical queries using:
1. PubTator3 entity resolution (Gene, Disease, Chemical, Species, Variant)
2. MeSH term expansion via NCBI E-utilities
3. Synonym generation and query expansion

Architecture:
    SemanticEnhancer sits between QueryAnalyzer and MultiSourceSearcher.
    It enriches the analyzed query with standardized entities and expanded terms.

    Query Flow:
    User Query → QueryAnalyzer → SemanticEnhancer → MultiSourceSearcher
                      ↓                ↓                    ↓
                AnalyzedQuery → EnhancedQuery → SearchStrategies

Example:
    >>> enhancer = SemanticEnhancer()
    >>> enhanced = await enhancer.enhance("propofol sedation ICU")
    >>> enhanced.entities
    [PubTatorEntity(resolved_name="Propofol", entity_type="chemical", ...)]
    >>> enhanced.expanded_terms
    ["Propofol"[MeSH], "2,6-Diisopropylphenol", ...]
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from pubmed_search.infrastructure.pubtator import (
    PubTatorClient,
    get_pubtator_client,
    PubTatorEntity,
    EntityMatch,
)
from pubmed_search.infrastructure.cache import get_entity_cache

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


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
class SearchStrategy:
    """A search strategy with query and metadata."""
    
    name: str  # "original", "mesh_expanded", "entity_semantic", "fulltext"
    query: str  # Actual search query
    source: str  # Target source: "pubmed", "europe_pmc", "core"
    priority: int = 1  # Higher = execute first
    expected_precision: float = 0.5  # Estimated precision
    expected_recall: float = 0.5  # Estimated recall
    
    def __lt__(self, other: SearchStrategy) -> bool:
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
    entities: list[PubTatorEntity] = field(default_factory=list)
    
    # Expanded search terms
    expanded_terms: list[ExpandedTerm] = field(default_factory=list)
    
    # Generated search strategies
    strategies: list[SearchStrategy] = field(default_factory=list)
    
    # Detected PICO elements (enhanced)
    pico_elements: dict[str, list[str]] = field(default_factory=dict)
    
    # Cross-database term counts (from egquery)
    database_counts: dict[str, int] = field(default_factory=dict)
    
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
        return [
            e.mesh_id for e in self.entities 
            if e.mesh_id
        ]
    
    def get_best_strategy(self) -> SearchStrategy | None:
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
            "database_counts": self.database_counts,
            "spell_corrections": self.spell_corrections,
        }


# =============================================================================
# SemanticEnhancer
# =============================================================================


class SemanticEnhancer:
    """
    Enhances queries with semantic understanding via PubTator3.
    
    Every query goes through deep enhancement:
    1. Entity resolution (PubTator3) - Standardize biomedical terms
    2. Term expansion (MeSH, synonyms) - Broaden coverage
    3. Strategy generation - Multiple search approaches
    
    This is called for EVERY search, not just complex ones.
    The philosophy: "Every search is deep AND wide."
    
    Usage:
        enhancer = SemanticEnhancer()
        enhanced = await enhancer.enhance("propofol sedation ICU")
        
        for strategy in enhanced.strategies:
            results = await search(strategy.query, source=strategy.source)
    """
    
    # Entity types to resolve
    ENTITY_TYPES = ["chemical", "disease", "gene", "species", "variant"]
    
    # Stop words to skip during entity resolution
    STOP_WORDS = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been",
        "in", "on", "at", "for", "to", "of", "and", "or", "with",
        "study", "studies", "trial", "trials", "patient", "patients",
        "effect", "effects", "treatment", "treatments", "therapy",
        "outcome", "outcomes", "result", "results", "analysis",
    }
    
    def __init__(
        self,
        pubtator_client: PubTatorClient | None = None,
        use_cache: bool = True,
        timeout: float = 5.0,
    ):
        """
        Initialize SemanticEnhancer.
        
        Args:
            pubtator_client: PubTator3 client (uses singleton if not provided)
            use_cache: Whether to use entity cache
            timeout: Maximum time for enhancement (seconds)
        """
        self._client = pubtator_client
        self._use_cache = use_cache
        self._timeout = timeout
        
    async def _get_client(self) -> PubTatorClient:
        """Get PubTator3 client."""
        if self._client is None:
            self._client = get_pubtator_client()
        return self._client
        
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
            # Run enhancement phases in parallel (with timeout)
            async with asyncio.timeout(self._timeout):
                # Phase 1: Entity resolution + term extraction
                entities, terms = await self._resolve_and_expand(query)
                enhanced.entities = entities
                enhanced.expanded_terms = terms
                
                # Phase 2: Generate search strategies
                enhanced.strategies = self._generate_strategies(query, entities, terms)
                
                # Add metadata
                enhanced.metadata["enhancement_version"] = "1.0"
                enhanced.metadata["entity_count"] = len(entities)
                enhanced.metadata["term_count"] = len(terms)
                enhanced.metadata["strategy_count"] = len(enhanced.strategies)
                
        except TimeoutError:
            logger.warning(f"Enhancement timeout for query: {query[:50]}")
            # Fall back to basic enhancement
            enhanced = self._basic_enhancement(query)
            enhanced.metadata["timeout"] = True
            
        except Exception as e:
            logger.error(f"Enhancement failed: {e}")
            # Fall back to basic enhancement
            enhanced = self._basic_enhancement(query)
            enhanced.metadata["error"] = str(e)
            
        return enhanced
        
    async def _resolve_and_expand(
        self, 
        query: str,
    ) -> tuple[list[PubTatorEntity], list[ExpandedTerm]]:
        """
        Resolve entities and expand terms.
        
        Uses PubTator3 for entity resolution with optional caching.
        """
        client = await self._get_client()
        cache = get_entity_cache() if self._use_cache else None
        
        # Extract candidate terms from query
        candidates = self._extract_candidates(query)
        
        entities: list[PubTatorEntity] = []
        expanded_terms: list[ExpandedTerm] = []
        
        # Add original query terms
        for candidate in candidates[:10]:  # Limit candidates
            expanded_terms.append(ExpandedTerm(
                term=candidate,
                source="original",
                confidence=1.0,
            ))
        
        # Resolve entities in parallel
        async def resolve_one(term: str) -> PubTatorEntity | None:
            # Check cache first
            cache_key = f"entity:{term.lower()}"
            if cache:
                cached = cache.get(cache_key)
                if cached:
                    return cached
                    
            # Resolve via PubTator3
            entity = await client.resolve_entity(term)
            
            # Cache result
            if cache and entity:
                cache.set(cache_key, entity)
                
            return entity
            
        # Run resolutions in parallel (limited concurrency)
        tasks = [resolve_one(term) for term in candidates[:5]]  # Top 5 terms
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, PubTatorEntity):
                entities.append(result)
                
                # Add expanded term from entity
                expanded_terms.append(ExpandedTerm(
                    term=result.resolved_name,
                    source="pubtator",
                    confidence=0.9,
                    mesh_id=result.mesh_id,
                ))
                
        return entities, expanded_terms
        
    def _extract_candidates(self, query: str) -> list[str]:
        """
        Extract candidate terms for entity resolution.
        
        Returns terms ordered by likely importance (longer, more specific first).
        """
        import re
        
        # Extract quoted phrases first
        quoted = re.findall(r'"([^"]+)"', query)
        
        # Extract remaining words
        unquoted = re.sub(r'"[^"]+"', "", query)
        words = re.findall(r"\b[a-zA-Z]{3,}\b", unquoted)
        
        # Filter stop words
        words = [w for w in words if w.lower() not in self.STOP_WORDS]
        
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
        entities: list[PubTatorEntity],
        terms: list[ExpandedTerm],
    ) -> list[SearchStrategy]:
        """
        Generate multiple search strategies for deep+wide search.
        
        Always generates multiple strategies to ensure comprehensive coverage.
        """
        strategies: list[SearchStrategy] = []
        
        # Strategy 1: Original query (baseline)
        strategies.append(SearchStrategy(
            name="original",
            query=query,
            source="pubmed",
            priority=1,
            expected_precision=0.7,
            expected_recall=0.5,
        ))
        
        # Strategy 2: MeSH expanded (if entities have MeSH IDs)
        mesh_terms = [e for e in entities if e.mesh_id]
        if mesh_terms:
            mesh_query = self._build_mesh_query(query, mesh_terms)
            strategies.append(SearchStrategy(
                name="mesh_expanded",
                query=mesh_query,
                source="pubmed",
                priority=2,
                expected_precision=0.8,
                expected_recall=0.7,
            ))
            
        # Strategy 3: Entity-based semantic search (via PubTator3 IDs)
        if entities:
            entity_query = self._build_entity_query(entities)
            strategies.append(SearchStrategy(
                name="entity_semantic",
                query=entity_query,
                source="pubmed",
                priority=3,
                expected_precision=0.9,
                expected_recall=0.4,
            ))
            
        # Strategy 4: Full-text search on Europe PMC
        strategies.append(SearchStrategy(
            name="fulltext_epmc",
            query=query,
            source="europe_pmc",
            priority=1,
            expected_precision=0.5,
            expected_recall=0.8,
        ))
        
        # Strategy 5: Broad title/abstract search
        broad_query = self._build_broad_query(terms)
        if broad_query != query:
            strategies.append(SearchStrategy(
                name="broad_tiab",
                query=broad_query,
                source="pubmed",
                priority=0,
                expected_precision=0.4,
                expected_recall=0.9,
            ))
            
        return sorted(strategies)
        
    def _build_mesh_query(
        self, 
        original_query: str, 
        mesh_entities: list[PubTatorEntity],
    ) -> str:
        """Build query with MeSH term expansion."""
        mesh_parts = []
        for entity in mesh_entities:
            if entity.mesh_id:
                mesh_parts.append(f'"{entity.resolved_name}"[MeSH Terms]')
                
        if not mesh_parts:
            return original_query
            
        # Combine MeSH terms with OR, then AND with remaining query
        mesh_clause = " OR ".join(mesh_parts)
        
        # Try to identify non-entity parts of original query
        entity_names = {e.original_text.lower() for e in mesh_entities}
        entity_names.update({e.resolved_name.lower() for e in mesh_entities})
        
        remaining_words = []
        for word in original_query.split():
            if word.lower() not in entity_names:
                remaining_words.append(word)
                
        if remaining_words:
            remaining = " ".join(remaining_words)
            return f"({mesh_clause}) AND ({remaining})"
        else:
            return mesh_clause
            
    def _build_entity_query(self, entities: list[PubTatorEntity]) -> str:
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
        enhanced.expanded_terms = [
            ExpandedTerm(term=c, source="original", confidence=1.0)
            for c in candidates[:10]
        ]
        
        # Generate basic strategies
        enhanced.strategies = [
            SearchStrategy(
                name="original",
                query=query,
                source="pubmed",
                priority=1,
                expected_precision=0.6,
                expected_recall=0.5,
            ),
            SearchStrategy(
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


# =============================================================================
# Convenience Functions
# =============================================================================

_enhancer_instance: SemanticEnhancer | None = None


def get_semantic_enhancer() -> SemanticEnhancer:
    """Get singleton SemanticEnhancer instance."""
    global _enhancer_instance
    if _enhancer_instance is None:
        _enhancer_instance = SemanticEnhancer()
    return _enhancer_instance


async def enhance_query(query: str) -> EnhancedQuery:
    """
    Enhance a query with semantic understanding.
    
    Convenience function using singleton enhancer.
    
    Args:
        query: User's search query
        
    Returns:
        EnhancedQuery with entities, expanded terms, and strategies
    """
    enhancer = get_semantic_enhancer()
    return await enhancer.enhance(query)
