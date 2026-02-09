"""
Tests for Phase 3: PubTator3 Deep+Wide Search Integration

Tests:
- SemanticEnhancer entity resolution and query expansion
- EntityCache TTL and LRU eviction
- PubTatorClient API interaction (mocked)
- ResultAggregator entity_match scoring
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pubmed_search.application.search.semantic_enhancer import (
    EnhancedQuery,
    ExpandedTerm,
    SearchStrategy,
    SemanticEnhancer,
    enhance_query,
)
from pubmed_search.application.search.result_aggregator import (
    RankingConfig,
    RankingDimension,
    ResultAggregator,
)
from pubmed_search.infrastructure.cache.entity_cache import (
    EntityCache,
    reset_entity_cache,
)
from pubmed_search.infrastructure.pubtator.models import (
    EntityMatch,
    PubTatorEntity,
    RelationMatch,
)


# =============================================================================
# SemanticEnhancer Tests
# =============================================================================


class TestSemanticEnhancer:
    """Tests for SemanticEnhancer."""

    @pytest.fixture
    def enhancer(self):
        """Create enhancer with mocked client."""
        return SemanticEnhancer(use_cache=False, timeout=5.0)

    def test_extract_candidates_basic(self, enhancer):
        """Test candidate term extraction."""
        candidates = enhancer._extract_candidates("propofol sedation ICU patients")
        
        # Should extract meaningful terms
        assert "propofol" in candidates
        assert "sedation" in candidates
        assert "patients" not in candidates  # Stop word
        
    def test_extract_candidates_quoted(self, enhancer):
        """Test extraction of quoted phrases."""
        candidates = enhancer._extract_candidates('"type 2 diabetes" treatment')
        
        # Quoted phrases should be first
        assert candidates[0] == "type 2 diabetes"
        assert "treatment" not in candidates  # Stop word

    def test_extract_candidates_filters_stop_words(self, enhancer):
        """Test stop word filtering."""
        candidates = enhancer._extract_candidates("the effect of treatment on patients")
        
        # Should not contain stop words
        stop_words = {"the", "of", "on", "treatment", "effect", "patients"}
        for word in stop_words:
            assert word.lower() not in [c.lower() for c in candidates]

    def test_basic_enhancement_fallback(self, enhancer):
        """Test basic enhancement when PubTator3 unavailable."""
        enhanced = enhancer._basic_enhancement("propofol mechanism action")
        
        assert isinstance(enhanced, EnhancedQuery)
        assert enhanced.original_query == "propofol mechanism action"
        assert len(enhanced.expanded_terms) > 0
        assert len(enhanced.strategies) >= 2  # At least original + fulltext
        assert enhanced.metadata.get("fallback") is True

    def test_generate_strategies(self, enhancer):
        """Test strategy generation."""
        entities = [
            PubTatorEntity(
                original_text="propofol",
                resolved_name="Propofol",
                entity_type="chemical",
                entity_id="@CHEMICAL_Propofol",
                mesh_id="D015742",
            )
        ]
        terms = [
            ExpandedTerm(term="propofol", source="original"),
            ExpandedTerm(term="Propofol", source="pubtator", mesh_id="D015742"),
        ]
        
        strategies = enhancer._generate_strategies("propofol sedation", entities, terms)
        
        # Should have multiple strategies
        assert len(strategies) >= 2
        
        # Should include original and mesh_expanded
        strategy_names = [s.name for s in strategies]
        assert "original" in strategy_names
        assert "mesh_expanded" in strategy_names

    def test_build_mesh_query(self, enhancer):
        """Test MeSH query building."""
        entities = [
            PubTatorEntity(
                original_text="propofol",
                resolved_name="Propofol",
                entity_type="chemical",
                entity_id="@CHEMICAL_Propofol",
                mesh_id="D015742",
            )
        ]
        
        query = enhancer._build_mesh_query("propofol sedation", entities)
        
        # Should include MeSH term
        assert '"Propofol"[MeSH Terms]' in query
        # Should also include remaining query
        assert "sedation" in query


class TestSemanticEnhancerAsync:
    """Async tests for SemanticEnhancer."""

    @pytest.fixture
    def mock_pubtator_client(self):
        """Create mocked PubTator3 client."""
        client = AsyncMock()
        client.resolve_entity = AsyncMock(return_value=PubTatorEntity(
            original_text="propofol",
            resolved_name="Propofol",
            entity_type="chemical",
            entity_id="@CHEMICAL_Propofol",
            mesh_id="D015742",
        ))
        return client

    @pytest.mark.asyncio
    async def test_enhance_with_entities(self, mock_pubtator_client):
        """Test enhancement with mocked entity resolution."""
        enhancer = SemanticEnhancer(
            pubtator_client=mock_pubtator_client,
            use_cache=False,
            timeout=5.0,
        )
        
        enhanced = await enhancer.enhance("propofol sedation")
        
        assert isinstance(enhanced, EnhancedQuery)
        assert enhanced.original_query == "propofol sedation"
        # Should have at least one entity
        assert len(enhanced.entities) >= 1
        # Should have strategies
        assert len(enhanced.strategies) >= 2

    @pytest.mark.asyncio
    async def test_enhance_timeout_fallback(self):
        """Test timeout handling."""
        # Create enhancer with very short timeout
        async def slow_resolve(*args, **kwargs):
            await asyncio.sleep(10)  # Simulate slow API
            return None
            
        client = AsyncMock()
        client.resolve_entity = slow_resolve
        
        enhancer = SemanticEnhancer(
            pubtator_client=client,
            use_cache=False,
            timeout=0.1,  # Very short timeout
        )
        
        enhanced = await enhancer.enhance("test query")
        
        # Should fall back to basic enhancement
        assert enhanced.metadata.get("timeout") is True or enhanced.metadata.get("fallback") is True


# =============================================================================
# EntityCache Tests
# =============================================================================


class TestEntityCache:
    """Tests for EntityCache."""

    @pytest.fixture
    def cache(self):
        """Create fresh cache."""
        return EntityCache(max_size=100, ttl=3600)

    def test_basic_set_get(self, cache):
        """Test basic cache operations."""
        cache.set("key1", "value1")
        
        assert cache.get("key1") == "value1"
        assert cache.get("nonexistent") is None

    def test_case_insensitive_keys(self, cache):
        """Test that keys are case-insensitive."""
        cache.set("Propofol", "value1")
        
        assert cache.get("propofol") == "value1"
        assert cache.get("PROPOFOL") == "value1"

    def test_lru_eviction(self):
        """Test LRU eviction when max size reached."""
        cache = EntityCache(max_size=3, ttl=3600)
        
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        
        # Access 'a' to make it recently used
        cache.get("a")
        
        # Add new item - should evict 'b' (least recently used)
        cache.set("d", 4)
        
        assert cache.get("a") == 1  # Still there (was accessed)
        assert cache.get("b") is None  # Evicted
        assert cache.get("c") == 3
        assert cache.get("d") == 4

    def test_ttl_expiration(self):
        """Test TTL-based expiration."""
        import time
        
        cache = EntityCache(max_size=100, ttl=0.1)  # 100ms TTL
        cache.set("key", "value")
        
        assert cache.get("key") == "value"
        
        time.sleep(0.15)  # Wait for expiration
        
        assert cache.get("key") is None  # Expired

    def test_stats(self, cache):
        """Test cache statistics."""
        cache.set("key1", "value1")
        
        cache.get("key1")  # Hit
        cache.get("key1")  # Hit
        cache.get("key2")  # Miss
        
        assert cache.stats.hits == 2
        assert cache.stats.misses == 1
        assert cache.stats.hit_rate == 2/3

    @pytest.mark.asyncio
    async def test_get_or_fetch(self, cache):
        """Test get-or-fetch pattern."""
        fetch_count = 0
        
        async def fetch_fn():
            nonlocal fetch_count
            fetch_count += 1
            return "fetched_value"
        
        # First call - should fetch
        result1 = await cache.get_or_fetch("key", fetch_fn)
        assert result1 == "fetched_value"
        assert fetch_count == 1
        
        # Second call - should use cache
        result2 = await cache.get_or_fetch("key", fetch_fn)
        assert result2 == "fetched_value"
        assert fetch_count == 1  # No additional fetch

    def test_cleanup_expired(self):
        """Test cleanup of expired entries."""
        import time
        
        cache = EntityCache(max_size=100, ttl=0.1)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        time.sleep(0.15)
        
        removed = cache.cleanup_expired()
        assert removed == 2
        assert len(cache) == 0


# =============================================================================
# ResultAggregator Entity Match Tests
# =============================================================================


class TestResultAggregatorEntityMatch:
    """Tests for ResultAggregator entity_match scoring."""

    @pytest.fixture
    def mock_article(self):
        """Create mock article."""
        article = MagicMock()
        article.title = "Propofol for ICU sedation: a randomized trial"
        article.abstract = "We studied propofol versus dexmedetomidine for sedation in ICU patients."
        article.primary_source = "pubmed"
        article.sources = [MagicMock(source="pubmed")]
        article.keywords = []
        article.mesh_terms = ["Propofol", "Intensive Care Units"]
        article.year = 2023
        article.citation_metrics = None
        article.doi = None
        article.article_type = None
        article._ranking_score = None
        article._relevance_score = None
        article._quality_score = None
        return article

    def test_entity_match_scoring_with_entities(self, mock_article):
        """Test entity_match scoring when entities are matched."""
        config = RankingConfig(
            matched_entities=["Propofol", "ICU", "Sedation"]
        )
        
        aggregator = ResultAggregator(config)
        score = aggregator._calculate_entity_match(mock_article, config)
        
        # Should have high score since article mentions all entities
        assert score > 0.7

    def test_entity_match_scoring_no_entities(self, mock_article):
        """Test entity_match scoring when no entities configured."""
        config = RankingConfig(matched_entities=[])
        
        aggregator = ResultAggregator(config)
        score = aggregator._calculate_entity_match(mock_article, config)
        
        # Should return neutral score
        assert score == 0.5

    def test_entity_match_partial_match(self, mock_article):
        """Test entity_match with partial entity matches."""
        config = RankingConfig(
            matched_entities=["Propofol", "Ketamine", "Dexmedetomidine"]
        )
        
        aggregator = ResultAggregator(config)
        score = aggregator._calculate_entity_match(mock_article, config)
        
        # Should have moderate score (mentions 2 of 3)
        assert 0.4 < score < 0.8

    def test_ranking_dimension_includes_entity_match(self):
        """Test that entity_match is in ranking dimensions."""
        assert RankingDimension.ENTITY_MATCH.value == "entity_match"

    def test_ranking_config_default_weights(self):
        """Test default ranking config includes entity_match."""
        config = RankingConfig.default()
        weights = config.normalized_weights()
        
        assert "entity_match" in weights
        assert weights["entity_match"] > 0

    def test_ranking_config_entity_focused(self):
        """Test entity-focused ranking config."""
        config = RankingConfig.entity_focused()
        weights = config.normalized_weights()
        
        # Entity match should have highest weight
        assert weights["entity_match"] >= 0.25


# =============================================================================
# PubTatorEntity Model Tests
# =============================================================================


class TestPubTatorModels:
    """Tests for PubTator3 data models."""

    def test_entity_match_mesh_id(self):
        """Test MeSH ID extraction from EntityMatch."""
        match = EntityMatch(
            entity_id="@CHEMICAL_Propofol",
            name="Propofol",
            type="chemical",
            identifier="D015742",
            score=0.95,
        )
        
        assert match.mesh_id == "D015742"

    def test_entity_match_no_mesh(self):
        """Test when no MeSH ID available."""
        match = EntityMatch(
            entity_id="@GENE_BRCA1",
            name="BRCA1",
            type="gene",
            identifier="672",  # Gene ID, not MeSH
            score=0.90,
        )
        
        assert match.mesh_id is None

    def test_entity_match_to_pubmed_query(self):
        """Test PubMed query generation from entity."""
        match = EntityMatch(
            entity_id="@CHEMICAL_Propofol",
            name="Propofol",
            type="chemical",
            identifier="D015742",
            score=0.95,
        )
        
        query = match.to_pubmed_query()
        assert query == '"Propofol"[MeSH Terms]'

    def test_pubtator_entity_to_search_term(self):
        """Test search term generation from PubTatorEntity."""
        entity = PubTatorEntity(
            original_text="propofol",
            resolved_name="Propofol",
            entity_type="chemical",
            entity_id="@CHEMICAL_Propofol",
            mesh_id="D015742",
        )
        
        term = entity.to_search_term()
        assert term == '"Propofol"[MeSH Terms]'

    def test_pubtator_entity_gene_search_term(self):
        """Test gene search term generation."""
        entity = PubTatorEntity(
            original_text="BRCA1",
            resolved_name="BRCA1",
            entity_type="gene",
            entity_id="@GENE_BRCA1",
            ncbi_id="672",
        )
        
        term = entity.to_search_term()
        assert "BRCA1" in term
        assert "[Gene Name]" in term

    def test_relation_match(self):
        """Test RelationMatch model."""
        relation = RelationMatch(
            source_entity="@CHEMICAL_Propofol",
            source_name="Propofol",
            relation_type="treat",
            target_entity="@DISEASE_Insomnia",
            target_name="Insomnia",
            evidence_count=15,
            pmids=["12345678", "23456789"],
        )
        
        assert relation.relation_type == "treat"
        assert len(relation.get_evidence_pmids(limit=1)) == 1


# =============================================================================
# Integration Tests
# =============================================================================


class TestPhase3Integration:
    """Integration tests for Phase 3 components."""

    @pytest.fixture(autouse=True)
    def reset_caches(self):
        """Reset global caches before each test."""
        reset_entity_cache()
        yield
        reset_entity_cache()

    def test_semantic_enhancer_to_ranking_config(self):
        """Test that SemanticEnhancer entities flow to RankingConfig."""
        # Simulate enhancement result
        enhanced = EnhancedQuery(
            original_query="propofol sedation",
            entities=[
                PubTatorEntity(
                    original_text="propofol",
                    resolved_name="Propofol",
                    entity_type="chemical",
                    entity_id="@CHEMICAL_Propofol",
                    mesh_id="D015742",
                )
            ],
        )
        
        # Extract entity names (as unified_search does)
        matched_entity_names = [e.resolved_name for e in enhanced.entities]
        
        # Create ranking config with entities
        config = RankingConfig(matched_entities=matched_entity_names)
        
        assert config.matched_entities == ["Propofol"]

    def test_enhanced_query_to_search_strategies(self):
        """Test conversion of EnhancedQuery to search strategies."""
        enhanced = EnhancedQuery(
            original_query="propofol sedation",
            entities=[
                PubTatorEntity(
                    original_text="propofol",
                    resolved_name="Propofol",
                    entity_type="chemical",
                    entity_id="@CHEMICAL_Propofol",
                    mesh_id="D015742",
                )
            ],
            strategies=[
                SearchStrategy(
                    name="original",
                    query="propofol sedation",
                    source="pubmed",
                    priority=1,
                ),
                SearchStrategy(
                    name="mesh_expanded",
                    query='"Propofol"[MeSH Terms] AND sedation',
                    source="pubmed",
                    priority=2,
                ),
            ],
        )
        
        # Get best strategy
        best = enhanced.get_best_strategy()
        assert best.name == "mesh_expanded"  # Higher priority
        assert best.priority == 2

    @pytest.mark.asyncio
    async def test_convenience_function(self):
        """Test enhance_query convenience function."""
        # This will use fallback since no real PubTator3 connection
        enhanced = await enhance_query("test query")
        
        assert isinstance(enhanced, EnhancedQuery)
        assert enhanced.original_query == "test query"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
