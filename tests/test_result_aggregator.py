"""
Tests for ResultAggregator - Multi-Source Result Merging and Ranking

This test module provides comprehensive coverage for:
1. UnionFind data structure
2. Deduplication strategies (STRICT, MODERATE, AGGRESSIVE)
3. Multi-dimensional ranking (relevance, quality, recency, impact, source_trust)
4. RankingConfig presets and customization
5. AggregationStats tracking
6. Edge cases and error handling
"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from pubmed_search.application.search.result_aggregator import (
    ARTICLE_TYPE_WEIGHTS,
    DEFAULT_SOURCE_TRUST,
    AggregationStats,
    DeduplicationStrategy,
    RankingConfig,
    RankingDimension,
    ResultAggregator,
    UnionFind,
    aggregate_results,
    rank_results,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_article():
    """Create a mock UnifiedArticle for testing."""

    def _create(
        title: str = "Test Article",
        pmid: str | None = None,
        doi: str | None = None,
        pmc: str | None = None,
        abstract: str | None = None,
        journal: str | None = None,
        year: int | None = None,
        volume: str | None = None,
        issue: str | None = None,
        pages: str | None = None,
        primary_source: str = "pubmed",
        article_type: str | None = None,
        keywords: list[str] | None = None,
        mesh_terms: list[str] | None = None,
        citation_metrics: object | None = None,
        sources: list[str] | None = None,
        has_open_access: bool = False,
    ):
        article = MagicMock()
        article.title = title
        article.pmid = pmid
        article.doi = doi
        article.pmc = pmc
        article.abstract = abstract
        article.journal = journal
        article.year = year
        article.volume = volume
        article.issue = issue
        article.pages = pages
        article.primary_source = primary_source
        article.keywords = keywords or []
        article.mesh_terms = mesh_terms or []
        article.citation_metrics = citation_metrics
        article.sources = sources or [primary_source]
        article.has_open_access = has_open_access

        # Mock article_type as enum-like
        if article_type:
            type_mock = MagicMock()
            type_mock.value = article_type
            article.article_type = type_mock
        else:
            article.article_type = None

        # Mock merge_from method
        article.merge_from = MagicMock()

        # Initialize scoring attributes
        article._ranking_score = None
        article._relevance_score = None
        article._quality_score = None

        return article

    return _create


@pytest.fixture
def sample_articles(mock_article):
    """Create sample articles for testing."""
    return [
        mock_article(
            title="Machine Learning in Healthcare",
            pmid="12345678",
            doi="10.1000/example1",
            abstract="This study explores machine learning applications in healthcare.",
            journal="Nature Medicine",
            year=2024,
            primary_source="pubmed",
            article_type="journal-article",
        ),
        mock_article(
            title="Deep Learning for Drug Discovery",
            pmid="23456789",
            doi="10.1000/example2",
            abstract="Deep learning methods for pharmaceutical research.",
            journal="Science",
            year=2023,
            primary_source="crossref",
            article_type="review",
        ),
        mock_article(
            title="Clinical Trial of New Treatment",
            pmid="34567890",
            doi="10.1000/example3",
            abstract="A randomized controlled trial of new therapy.",
            journal="NEJM",
            year=2022,
            primary_source="pubmed",
            article_type="randomized-controlled-trial",
        ),
    ]


# =============================================================================
# UnionFind Tests
# =============================================================================


class TestUnionFind:
    """Tests for UnionFind data structure."""

    def test_init(self):
        """Test initialization."""
        uf = UnionFind(5)
        assert len(uf.parent) == 5
        assert uf.parent == [0, 1, 2, 3, 4]
        assert uf.rank == [0, 0, 0, 0, 0]
        assert uf.size == [1, 1, 1, 1, 1]

    def test_find_self(self):
        """Test find returns self for initial elements."""
        uf = UnionFind(3)
        assert uf.find(0) == 0
        assert uf.find(1) == 1
        assert uf.find(2) == 2

    def test_union_two_elements(self):
        """Test union of two elements."""
        uf = UnionFind(3)

        # First union should succeed
        assert uf.union(0, 1) is True

        # They should now have the same root
        assert uf.find(0) == uf.find(1)

    def test_union_same_set(self):
        """Test union of elements in same set returns False."""
        uf = UnionFind(3)
        uf.union(0, 1)

        # Trying to union again should return False
        assert uf.union(0, 1) is False
        assert uf.union(1, 0) is False

    def test_union_multiple(self):
        """Test multiple unions."""
        uf = UnionFind(5)

        uf.union(0, 1)
        uf.union(2, 3)
        uf.union(1, 3)

        # 0, 1, 2, 3 should all be in same set
        root = uf.find(0)
        assert uf.find(1) == root
        assert uf.find(2) == root
        assert uf.find(3) == root

        # 4 should be separate
        assert uf.find(4) == 4

    def test_path_compression(self):
        """Test path compression works."""
        uf = UnionFind(4)
        uf.union(0, 1)
        uf.union(1, 2)
        uf.union(2, 3)

        # Find with path compression
        root = uf.find(3)

        # After find, all should point directly to root
        assert uf.parent[3] == root

    def test_get_groups(self):
        """Test get_groups returns correct groupings."""
        uf = UnionFind(5)

        uf.union(0, 1)
        uf.union(2, 3)

        groups = uf.get_groups()

        # Should have 3 groups: {0,1}, {2,3}, {4}
        assert len(groups) == 3

        # Check group sizes
        sizes = sorted([len(g) for g in groups.values()])
        assert sizes == [1, 2, 2]

    def test_get_groups_all_separate(self):
        """Test get_groups with all separate elements."""
        uf = UnionFind(3)
        groups = uf.get_groups()

        assert len(groups) == 3
        for members in groups.values():
            assert len(members) == 1

    def test_get_groups_all_united(self):
        """Test get_groups with all elements in one group."""
        uf = UnionFind(4)
        uf.union(0, 1)
        uf.union(1, 2)
        uf.union(2, 3)

        groups = uf.get_groups()
        assert len(groups) == 1
        assert len(list(groups.values())[0]) == 4


# =============================================================================
# RankingConfig Tests
# =============================================================================


class TestRankingConfig:
    """Tests for RankingConfig."""

    def test_default_config(self):
        """Test default configuration."""
        config = RankingConfig.default()

        assert config.relevance_weight == 0.25
        assert config.quality_weight == 0.20
        assert config.recency_weight == 0.15
        assert config.impact_weight == 0.20
        assert config.source_trust_weight == 0.10
        assert config.entity_match_weight == 0.10
        assert config.dedup_strategy == DeduplicationStrategy.MODERATE

    def test_impact_focused_config(self):
        """Test impact-focused configuration."""
        config = RankingConfig.impact_focused()

        assert config.impact_weight == 0.40
        assert config.relevance_weight == 0.20

    def test_recency_focused_config(self):
        """Test recency-focused configuration."""
        config = RankingConfig.recency_focused()

        assert config.recency_weight == 0.40
        assert config.recency_half_life_years == 3.0

    def test_quality_focused_config(self):
        """Test quality-focused configuration."""
        config = RankingConfig.quality_focused()

        assert config.quality_weight == 0.35

    def test_normalized_weights(self):
        """Test weights normalization."""
        config = RankingConfig()
        weights = config.normalized_weights()

        # Should sum to 1.0
        assert abs(sum(weights.values()) - 1.0) < 0.001

    def test_normalized_weights_custom(self):
        """Test normalization with custom weights."""
        config = RankingConfig(
            relevance_weight=1.0,
            quality_weight=1.0,
            recency_weight=1.0,
            impact_weight=1.0,
            source_trust_weight=1.0,
            entity_match_weight=1.0,
        )
        weights = config.normalized_weights()

        # Each should be 1/6 ≈ 0.167 (6 weights now)
        expected = 1.0 / 6.0
        assert abs(weights["relevance"] - expected) < 0.001
        assert abs(sum(weights.values()) - 1.0) < 0.001

    def test_normalized_weights_zero_total(self):
        """Test normalization with all zero weights."""
        config = RankingConfig(
            relevance_weight=0,
            quality_weight=0,
            recency_weight=0,
            impact_weight=0,
            source_trust_weight=0,
            entity_match_weight=0,
        )
        weights = config.normalized_weights()

        # When total=0, code sets total=1.0, so each weight = 0/1 = 0
        assert all(w == 0.0 for w in weights.values())

    def test_get_article_type_weight_default(self):
        """Test default article type weights."""
        config = RankingConfig()

        assert config.get_article_type_weight("meta-analysis") == 0.30
        assert config.get_article_type_weight("review") == 0.10
        assert config.get_article_type_weight("unknown-type") == 0.0

    def test_get_article_type_weight_custom(self):
        """Test custom article type weights."""
        config = RankingConfig(quality_article_type_weights={"custom-type": 0.99})

        assert config.get_article_type_weight("custom-type") == 0.99
        assert config.get_article_type_weight("meta-analysis") == 0.0  # Not in custom

    def test_source_trust_levels(self):
        """Test source trust levels."""
        config = RankingConfig()

        assert config.source_trust_levels["pubmed"] == 1.0
        assert config.source_trust_levels["core"] == 0.7


# =============================================================================
# AggregationStats Tests
# =============================================================================


class TestAggregationStats:
    """Tests for AggregationStats."""

    def test_default_values(self):
        """Test default values."""
        stats = AggregationStats()

        assert stats.total_input == 0
        assert stats.unique_articles == 0
        assert stats.duplicates_removed == 0
        assert stats.merged_records == 0
        assert stats.by_source == {}
        assert stats.dedup_by_doi == 0
        assert stats.dedup_by_pmid == 0
        assert stats.dedup_by_title == 0

    def test_to_dict(self):
        """Test to_dict conversion."""
        stats = AggregationStats(
            total_input=100,
            unique_articles=80,
            duplicates_removed=20,
            merged_records=15,
            by_source={"pubmed": 50, "crossref": 50},
            dedup_by_doi=10,
            dedup_by_pmid=5,
            dedup_by_title=5,
        )

        result = stats.to_dict()

        assert result["total_input"] == 100
        assert result["unique_articles"] == 80
        assert result["by_source"] == {"pubmed": 50, "crossref": 50}


# =============================================================================
# ResultAggregator Tests
# =============================================================================


class TestResultAggregator:
    """Tests for ResultAggregator."""

    def test_init_default_config(self):
        """Test initialization with default config."""
        aggregator = ResultAggregator()
        assert aggregator._config is not None

    def test_init_custom_config(self):
        """Test initialization with custom config."""
        config = RankingConfig.impact_focused()
        aggregator = ResultAggregator(config)

        assert aggregator._config.impact_weight == 0.40

    # =========================================================================
    # Aggregation Tests
    # =========================================================================

    def test_aggregate_empty_lists(self):
        """Test aggregation with empty lists."""
        aggregator = ResultAggregator()
        articles, stats = aggregator.aggregate([[], []])

        assert articles == []
        assert stats.total_input == 0
        assert stats.unique_articles == 0

    def test_aggregate_single_source(self, sample_articles):
        """Test aggregation from single source."""
        aggregator = ResultAggregator()
        articles, stats = aggregator.aggregate([sample_articles])

        assert len(articles) == 3
        assert stats.total_input == 3
        assert stats.unique_articles == 3
        assert stats.duplicates_removed == 0

    def test_aggregate_multiple_sources_no_duplicates(self, mock_article):
        """Test aggregation from multiple sources without duplicates."""
        source1 = [mock_article(pmid="111", doi="10.1/a")]
        source2 = [mock_article(pmid="222", doi="10.1/b")]

        aggregator = ResultAggregator()
        articles, stats = aggregator.aggregate([source1, source2])

        assert len(articles) == 2
        assert stats.total_input == 2
        assert stats.duplicates_removed == 0
        assert "pubmed" in stats.by_source

    def test_aggregate_dedup_by_doi(self, mock_article):
        """Test deduplication by DOI."""
        same_doi = "10.1000/same"
        source1 = [mock_article(pmid="111", doi=same_doi, primary_source="pubmed")]
        source2 = [mock_article(pmid="222", doi=same_doi, primary_source="crossref")]

        aggregator = ResultAggregator()
        articles, stats = aggregator.aggregate([source1, source2])

        assert len(articles) == 1
        assert stats.total_input == 2
        assert stats.duplicates_removed == 1
        assert stats.dedup_by_doi == 1

    def test_aggregate_dedup_by_pmid(self, mock_article):
        """Test deduplication by PMID."""
        same_pmid = "12345678"
        source1 = [mock_article(pmid=same_pmid, doi="10.1/a", primary_source="pubmed")]
        source2 = [
            mock_article(pmid=same_pmid, doi="10.1/b", primary_source="europe_pmc")
        ]

        aggregator = ResultAggregator()
        articles, stats = aggregator.aggregate([source1, source2])

        assert len(articles) == 1
        assert stats.dedup_by_pmid == 1

    def test_aggregate_dedup_by_title_moderate(self, mock_article):
        """Test deduplication by title with MODERATE strategy."""
        same_title = "Machine Learning Applications in Medical Diagnosis"
        source1 = [mock_article(title=same_title, pmid="111", primary_source="pubmed")]
        source2 = [mock_article(title=same_title, pmid="222", primary_source="core")]

        config = RankingConfig(dedup_strategy=DeduplicationStrategy.MODERATE)
        aggregator = ResultAggregator(config)
        articles, stats = aggregator.aggregate([source1, source2])

        assert len(articles) == 1
        assert stats.dedup_by_title == 1

    def test_aggregate_strict_no_title_match(self, mock_article):
        """Test STRICT strategy doesn't use title matching."""
        same_title = "Machine Learning Applications in Medical Diagnosis"
        source1 = [mock_article(title=same_title, pmid="111")]
        source2 = [mock_article(title=same_title, pmid="222")]

        config = RankingConfig(dedup_strategy=DeduplicationStrategy.STRICT)
        aggregator = ResultAggregator(config)
        articles, stats = aggregator.aggregate([source1, source2])

        # Should NOT deduplicate by title in STRICT mode
        assert len(articles) == 2
        assert stats.dedup_by_title == 0

    def test_aggregate_title_too_short(self, mock_article):
        """Test short titles are not used for deduplication."""
        short_title = "ML"  # Too short
        source1 = [mock_article(title=short_title, pmid="111")]
        source2 = [mock_article(title=short_title, pmid="222")]

        aggregator = ResultAggregator()
        articles, stats = aggregator.aggregate([source1, source2])

        # Should NOT deduplicate by short title
        assert len(articles) == 2

    def test_aggregate_merge_called(self, mock_article):
        """Test merge_from is called for duplicates."""
        same_doi = "10.1/same"
        article1 = mock_article(pmid="111", doi=same_doi, primary_source="pubmed")
        article2 = mock_article(pmid="222", doi=same_doi, primary_source="crossref")

        aggregator = ResultAggregator()
        articles, stats = aggregator.aggregate([[article1], [article2]])

        # merge_from should be called on the primary article
        assert stats.merged_records == 1

    def test_aggregate_doi_normalization(self, mock_article):
        """Test DOI normalization during deduplication."""
        source1 = [mock_article(doi="https://doi.org/10.1000/test")]
        source2 = [mock_article(doi="10.1000/test")]  # Same DOI, different format

        aggregator = ResultAggregator()
        articles, stats = aggregator.aggregate([source1, source2])

        assert len(articles) == 1
        assert stats.dedup_by_doi == 1

    # =========================================================================
    # Ranking Tests
    # =========================================================================

    def test_rank_empty(self):
        """Test ranking empty list."""
        aggregator = ResultAggregator()
        ranked = aggregator.rank([])

        assert ranked == []

    def test_rank_single_article(self, mock_article):
        """Test ranking single article."""
        article = mock_article(title="Test", year=2024)

        aggregator = ResultAggregator()
        ranked = aggregator.rank([article])

        assert len(ranked) == 1
        assert ranked[0]._ranking_score is not None

    def test_rank_multiple_articles(self, sample_articles):
        """Test ranking multiple articles."""
        aggregator = ResultAggregator()
        ranked = aggregator.rank(sample_articles)

        assert len(ranked) == 3

        # Should be sorted by score (descending)
        scores = [a._ranking_score for a in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_rank_with_query(self, mock_article):
        """Test ranking with query for relevance."""
        article1 = mock_article(
            title="Machine Learning in Healthcare",
            abstract="Deep learning for diagnosis",
        )
        article2 = mock_article(
            title="Cooking Recipes",
            abstract="How to make pasta",
        )

        aggregator = ResultAggregator()
        ranked = aggregator.rank([article1, article2], query="machine learning")

        # article1 should rank higher due to relevance
        assert ranked[0].title == "Machine Learning in Healthcare"

    def test_rank_min_score_filter(self, mock_article):
        """Test min_score filtering."""
        articles = [
            mock_article(title="High Quality", year=2024),
            mock_article(title="Low Quality", year=1990),
        ]

        config = RankingConfig(min_score=0.6)
        aggregator = ResultAggregator(config)
        ranked = aggregator.rank(articles)

        # Some articles may be filtered out
        for article in ranked:
            assert article._ranking_score >= 0.6

    def test_rank_max_results(self, sample_articles):
        """Test max_results limiting."""
        config = RankingConfig(max_results=2)
        aggregator = ResultAggregator(config)
        ranked = aggregator.rank(sample_articles)

        assert len(ranked) == 2

    def test_rank_custom_config(self, mock_article):
        """Test ranking with custom config."""
        # Recent article
        article1 = mock_article(year=datetime.now().year)
        # Old article
        article2 = mock_article(year=2000)

        # Use recency-focused config
        config = RankingConfig.recency_focused()
        aggregator = ResultAggregator(config)
        ranked = aggregator.rank([article1, article2])

        # Recent article should rank higher
        assert ranked[0].year == datetime.now().year

    # =========================================================================
    # Scoring Tests
    # =========================================================================

    def test_calculate_relevance_no_query(self, mock_article):
        """Test relevance without query returns 0.5."""
        aggregator = ResultAggregator()
        article = mock_article()

        score = aggregator._calculate_relevance(article, None)
        assert score == 0.5

    def test_calculate_relevance_title_match(self, mock_article):
        """Test relevance with title match."""
        aggregator = ResultAggregator()
        article = mock_article(title="Machine Learning Applications in Healthcare")

        # Query terms: machine, learning, healthcare (3 words)
        # Title terms: machine, learning, applications, healthcare (4 words)
        # Overlap: 3/3 = 100% title match
        score = aggregator._calculate_relevance(article, "machine learning healthcare")
        assert score >= 0.5  # Should be high due to title match

    def test_calculate_relevance_abstract_match(self, mock_article):
        """Test relevance with abstract match."""
        aggregator = ResultAggregator()
        article = mock_article(
            title="Study Results",
            abstract="This paper discusses machine learning techniques for diagnosis",
        )

        # Query: machine, learning, diagnosis (3 words, all >= 3 chars)
        score = aggregator._calculate_relevance(article, "machine learning diagnosis")
        assert score >= 0.3  # Abstract match contributes to score

    def test_calculate_quality_meta_analysis(self, mock_article):
        """Test quality score for meta-analysis."""
        aggregator = ResultAggregator()
        article = mock_article(article_type="meta-analysis")

        score = aggregator._calculate_quality(article, RankingConfig())
        assert score > 0.7  # Meta-analysis gets high score

    def test_calculate_quality_preprint(self, mock_article):
        """Test quality score for preprint."""
        aggregator = ResultAggregator()
        article = mock_article(article_type="preprint")

        score = aggregator._calculate_quality(article, RankingConfig())
        assert score < 0.7  # Preprint gets lower score

    def test_calculate_quality_open_access_boost(self, mock_article):
        """Test open access gives small quality boost."""
        aggregator = ResultAggregator()
        config = RankingConfig()

        article_oa = mock_article(has_open_access=True)
        article_closed = mock_article(has_open_access=False)

        score_oa = aggregator._calculate_quality(article_oa, config)
        score_closed = aggregator._calculate_quality(article_closed, config)

        assert score_oa > score_closed

    def test_calculate_recency_current_year(self, mock_article):
        """Test recency for current year."""
        aggregator = ResultAggregator()
        article = mock_article(year=datetime.now().year)

        score = aggregator._calculate_recency(article, RankingConfig())
        assert score > 0.9  # Recent should be high

    def test_calculate_recency_old_article(self, mock_article):
        """Test recency for old article."""
        aggregator = ResultAggregator()
        article = mock_article(year=2000)

        score = aggregator._calculate_recency(article, RankingConfig())
        assert score < 0.3  # Old should be low

    def test_calculate_recency_no_year(self, mock_article):
        """Test recency without year."""
        aggregator = ResultAggregator()
        article = mock_article(year=None)

        score = aggregator._calculate_recency(article, RankingConfig())
        assert score == 0.3  # Default for unknown

    def test_calculate_impact_no_metrics(self, mock_article):
        """Test impact without citation metrics."""
        aggregator = ResultAggregator()
        article = mock_article(citation_metrics=None)

        score = aggregator._calculate_impact(article)
        assert score == 0.3  # Default for unknown

    def test_calculate_impact_with_nih_percentile(self, mock_article):
        """Test impact with NIH percentile."""
        aggregator = ResultAggregator()

        metrics = MagicMock()
        metrics.nih_percentile = 80
        article = mock_article(citation_metrics=metrics)

        score = aggregator._calculate_impact(article)
        assert score == 0.8  # 80/100

    def test_calculate_impact_with_rcr(self, mock_article):
        """Test impact with RCR."""
        aggregator = ResultAggregator()

        metrics = MagicMock()
        metrics.nih_percentile = None
        metrics.relative_citation_ratio = 4.0
        article = mock_article(citation_metrics=metrics)

        score = aggregator._calculate_impact(article)
        assert 0.6 < score < 0.7  # RCR 4.0 → ~0.67

    def test_calculate_impact_with_citation_count(self, mock_article):
        """Test impact with citation count."""
        aggregator = ResultAggregator()

        metrics = MagicMock()
        metrics.nih_percentile = None
        metrics.relative_citation_ratio = None
        metrics.citation_count = 100
        article = mock_article(citation_metrics=metrics)

        score = aggregator._calculate_impact(article)
        assert 0.6 < score < 0.8  # log10(101)/3 ≈ 0.67

    def test_calculate_source_trust(self, mock_article):
        """Test source trust calculation."""
        aggregator = ResultAggregator()
        config = RankingConfig()

        article_pubmed = mock_article(primary_source="pubmed")
        article_core = mock_article(primary_source="core")

        score_pubmed = aggregator._calculate_source_trust(article_pubmed, config)
        score_core = aggregator._calculate_source_trust(article_core, config)

        assert score_pubmed > score_core  # PubMed more trusted

    def test_calculate_source_trust_multi_source_boost(self, mock_article):
        """Test multi-source verification boost."""
        aggregator = ResultAggregator()
        config = RankingConfig()

        # Use a source with trust < 1.0 so boost is visible
        article_single = mock_article(primary_source="core", sources=["core"])
        article_multi = mock_article(
            primary_source="core",
            sources=["core", "crossref", "openalex"],
        )

        score_single = aggregator._calculate_source_trust(article_single, config)
        score_multi = aggregator._calculate_source_trust(article_multi, config)

        # core trust = 0.7, with 2 extra sources boost = 0.2, so multi = 0.9
        assert score_multi > score_single

    # =========================================================================
    # Primary Selection Tests
    # =========================================================================

    def test_select_primary_more_identifiers(self, mock_article):
        """Test primary selection prefers more identifiers."""
        aggregator = ResultAggregator()

        article1 = mock_article(pmid="111", doi=None, pmc=None)
        article2 = mock_article(pmid="222", doi="10.1/x", pmc="PMC123")

        primary = aggregator._select_primary([article1, article2])

        assert primary.pmid == "222"  # Has more identifiers

    def test_select_primary_more_metadata(self, mock_article):
        """Test primary selection prefers more metadata."""
        aggregator = ResultAggregator()

        article1 = mock_article(pmid="111", abstract=None, journal=None)
        article2 = mock_article(pmid="222", abstract="Full abstract", journal="Nature")

        primary = aggregator._select_primary([article1, article2])

        assert primary.pmid == "222"

    # =========================================================================
    # Utility Method Tests
    # =========================================================================

    def test_normalize_doi(self):
        """Test DOI normalization."""
        assert ResultAggregator._normalize_doi("10.1000/test") == "10.1000/test"
        assert (
            ResultAggregator._normalize_doi("https://doi.org/10.1000/test")
            == "10.1000/test"
        )
        assert (
            ResultAggregator._normalize_doi("http://doi.org/10.1000/TEST")
            == "10.1000/test"
        )
        assert ResultAggregator._normalize_doi("doi:10.1000/test") == "10.1000/test"
        assert ResultAggregator._normalize_doi("  10.1000/test  ") == "10.1000/test"

    def test_normalize_title(self):
        """Test title normalization."""
        assert ResultAggregator._normalize_title("Hello World") == "hello world"
        assert ResultAggregator._normalize_title("Hello, World!") == "hello world"
        assert (
            ResultAggregator._normalize_title("  Multiple   Spaces  ")
            == "multiple spaces"
        )
        assert ResultAggregator._normalize_title("") == ""
        assert ResultAggregator._normalize_title(None) == ""

    # =========================================================================
    # Convenience Function Tests
    # =========================================================================

    def test_aggregate_and_rank(self, sample_articles):
        """Test aggregate_and_rank convenience method."""
        aggregator = ResultAggregator()
        articles, stats = aggregator.aggregate_and_rank([sample_articles])

        assert len(articles) == 3
        assert stats.total_input == 3

        # Should be ranked
        scores = [a._ranking_score for a in articles]
        assert scores == sorted(scores, reverse=True)


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_aggregate_results(self, mock_article):
        """Test aggregate_results function."""
        source1 = [mock_article(pmid="111")]
        source2 = [mock_article(pmid="222")]

        articles, stats = aggregate_results([source1, source2])

        assert len(articles) == 2
        assert stats.total_input == 2

    def test_rank_results(self, mock_article):
        """Test rank_results function."""
        articles = [
            mock_article(year=2024),
            mock_article(year=2020),
        ]

        ranked = rank_results(articles)

        assert len(ranked) == 2
        assert ranked[0]._ranking_score >= ranked[1]._ranking_score


# =============================================================================
# Constants Tests
# =============================================================================


class TestConstants:
    """Tests for module constants."""

    def test_article_type_weights(self):
        """Test article type weights are defined."""
        assert "meta-analysis" in ARTICLE_TYPE_WEIGHTS
        assert "journal-article" in ARTICLE_TYPE_WEIGHTS
        assert (
            ARTICLE_TYPE_WEIGHTS["meta-analysis"]
            > ARTICLE_TYPE_WEIGHTS["journal-article"]
        )

    def test_default_source_trust(self):
        """Test default source trust levels."""
        assert "pubmed" in DEFAULT_SOURCE_TRUST
        assert "core" in DEFAULT_SOURCE_TRUST
        assert DEFAULT_SOURCE_TRUST["pubmed"] > DEFAULT_SOURCE_TRUST["core"]


class TestRankingDimension:
    """Tests for RankingDimension enum."""

    def test_enum_values(self):
        """Test enum values."""
        assert RankingDimension.RELEVANCE.value == "relevance"
        assert RankingDimension.QUALITY.value == "quality"
        assert RankingDimension.RECENCY.value == "recency"
        assert RankingDimension.IMPACT.value == "impact"
        assert RankingDimension.SOURCE_TRUST.value == "source_trust"


class TestDeduplicationStrategy:
    """Tests for DeduplicationStrategy enum."""

    def test_enum_values(self):
        """Test enum values."""
        assert DeduplicationStrategy.STRICT.value == "strict"
        assert DeduplicationStrategy.MODERATE.value == "moderate"
        assert DeduplicationStrategy.AGGRESSIVE.value == "aggressive"
