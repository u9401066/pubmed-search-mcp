"""
ResultAggregator - Multi-Source Result Merging and Ranking

This module provides intelligent result aggregation from multiple academic sources:
1. Deduplication (DOI > PMID > Title fuzzy match) using Union-Find for O(n) complexity
2. Multi-dimensional ranking (relevance, quality, recency, impact, source_trust)
3. Score normalization and weighting

Architecture Decision:
    ResultAggregator operates on UnifiedArticle objects.
    It does NOT make API calls - purely processes existing results.

    Ranking uses a weighted multi-dimensional scoring system that can be
    customized for different use cases (systematic review vs quick lookup).

Example:
    >>> from pubmed_search.domain.entities import UnifiedArticle
    >>> from pubmed_search.application.search import ResultAggregator, RankingConfig
    >>>
    >>> aggregator = ResultAggregator()
    >>> articles = aggregator.aggregate([
    ...     article_from_pubmed,
    ...     article_from_crossref,
    ...     article_from_openalex,
    ... ])
    >>>
    >>> # With custom ranking
    >>> config = RankingConfig(impact_weight=0.4, recency_weight=0.3)
    >>> ranked = aggregator.rank(articles, config)
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pubmed_search.domain.entities.article import UnifiedArticle

# Lazy import to avoid circular dependency
_UnifiedArticle = None


def _get_unified_article() -> type[UnifiedArticle]:
    """Lazy import UnifiedArticle to avoid circular imports."""
    global _UnifiedArticle
    if _UnifiedArticle is None:
        from pubmed_search.domain.entities.article import UnifiedArticle

        _UnifiedArticle = UnifiedArticle
    return _UnifiedArticle


# =============================================================================
# Constants
# =============================================================================

# Article type quality weights (higher = better quality evidence)
ARTICLE_TYPE_WEIGHTS: dict[str, float] = {
    "meta-analysis": 0.30,
    "systematic-review": 0.25,
    "randomized-controlled-trial": 0.20,
    "clinical-trial": 0.15,
    "review": 0.10,
    "journal-article": 0.05,
    "preprint": 0.02,
    "other": 0.0,
    "unknown": 0.0,
}

# Default source trust levels
DEFAULT_SOURCE_TRUST: dict[str, float] = {
    "pubmed": 1.0,
    "crossref": 0.9,
    "openalex": 0.85,
    "semantic_scholar": 0.85,
    "europe_pmc": 0.9,
    "core": 0.7,
    "arxiv": 0.6,
    "medrxiv": 0.65,
    "biorxiv": 0.65,
}


# =============================================================================
# Enums
# =============================================================================


class RankingDimension(Enum):
    """
    Ranking dimensions for multi-dimensional scoring.

    Each dimension contributes to the final ranking score.
    Weights can be customized via RankingConfig.
    """

    RELEVANCE = "relevance"  # How well does it match the query?
    QUALITY = "quality"  # Publication quality indicators
    RECENCY = "recency"  # How recent is the publication?
    IMPACT = "impact"  # Citation metrics, field influence
    SOURCE_TRUST = "source_trust"  # Trust level of data source
    ENTITY_MATCH = "entity_match"  # Phase 3: PubTator3 entity matching


class DeduplicationStrategy(Enum):
    """
    Strategy for handling duplicate articles.

    STRICT: Only DOI/PMID exact matches are considered duplicates
    MODERATE: DOI/PMID + normalized title match
    AGGRESSIVE: Include fuzzy title matching (shorter title threshold)
    """

    STRICT = "strict"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class RankingConfig:
    """
    Configuration for result ranking.

    Weights must sum to 1.0 (will be normalized if not).

    Presets:
    - DEFAULT: Balanced weights
    - IMPACT_FOCUSED: Emphasizes citation metrics
    - RECENCY_FOCUSED: Emphasizes recent publications
    - QUALITY_FOCUSED: Emphasizes publication quality
    - ENTITY_FOCUSED: Emphasizes PubTator3 entity matching (Phase 3)
    """

    # Dimension weights (should sum to 1.0)
    relevance_weight: float = 0.25
    quality_weight: float = 0.20
    recency_weight: float = 0.15
    impact_weight: float = 0.20
    source_trust_weight: float = 0.10
    entity_match_weight: float = 0.10  # Phase 3: PubTator3 entity match

    # Deduplication settings
    dedup_strategy: DeduplicationStrategy = DeduplicationStrategy.MODERATE

    # Recency settings
    recency_half_life_years: float = 5.0  # Score halves every N years

    # Quality indicators (optional custom weights)
    quality_journal_weights: dict[str, float] = field(default_factory=dict)
    quality_article_type_weights: dict[str, float] = field(default_factory=dict)

    # Source trust levels (0-1)
    source_trust_levels: dict[str, float] = field(default_factory=lambda: DEFAULT_SOURCE_TRUST.copy())

    # Minimum score to include in results
    min_score: float = 0.0

    # Maximum results to return
    max_results: int | None = None

    # Title match minimum length (for deduplication)
    title_min_length: int = 20

    # Phase 3: Entity context for entity_match scoring
    matched_entities: list[str] = field(default_factory=list)

    @classmethod
    def default(cls) -> RankingConfig:
        """Get default balanced configuration."""
        return cls()

    @classmethod
    def impact_focused(cls) -> RankingConfig:
        """Get impact-focused configuration (emphasizes citations)."""
        return cls(
            relevance_weight=0.20,
            quality_weight=0.10,
            recency_weight=0.10,
            impact_weight=0.40,
            source_trust_weight=0.10,
            entity_match_weight=0.10,
        )

    @classmethod
    def recency_focused(cls) -> RankingConfig:
        """Get recency-focused configuration (emphasizes recent publications)."""
        return cls(
            relevance_weight=0.20,
            quality_weight=0.10,
            recency_weight=0.40,
            impact_weight=0.10,
            source_trust_weight=0.10,
            entity_match_weight=0.10,
            recency_half_life_years=3.0,
        )

    @classmethod
    def quality_focused(cls) -> RankingConfig:
        """Get quality-focused configuration (emphasizes journal quality)."""
        return cls(
            relevance_weight=0.20,
            quality_weight=0.35,
            recency_weight=0.10,
            impact_weight=0.15,
            source_trust_weight=0.10,
            entity_match_weight=0.10,
        )

    @classmethod
    def entity_focused(cls) -> RankingConfig:
        """Get entity-focused configuration (emphasizes PubTator3 entity matching)."""
        return cls(
            relevance_weight=0.20,
            quality_weight=0.15,
            recency_weight=0.10,
            impact_weight=0.15,
            source_trust_weight=0.10,
            entity_match_weight=0.30,
        )

    def normalized_weights(self) -> dict[str, float]:
        """Get normalized weights that sum to 1.0."""
        total = (
            self.relevance_weight
            + self.quality_weight
            + self.recency_weight
            + self.impact_weight
            + self.source_trust_weight
            + self.entity_match_weight
        )

        if total == 0:
            total = 1.0

        return {
            "relevance": self.relevance_weight / total,
            "quality": self.quality_weight / total,
            "recency": self.recency_weight / total,
            "impact": self.impact_weight / total,
            "source_trust": self.source_trust_weight / total,
            "entity_match": self.entity_match_weight / total,
        }

    def get_article_type_weight(self, article_type: str) -> float:
        """Get weight for article type, using custom or default."""
        if self.quality_article_type_weights:
            return self.quality_article_type_weights.get(article_type, 0.0)
        return ARTICLE_TYPE_WEIGHTS.get(article_type, 0.0)


@dataclass
class AggregationStats:
    """Statistics from aggregation process."""

    total_input: int = 0
    unique_articles: int = 0
    duplicates_removed: int = 0
    merged_records: int = 0
    by_source: dict[str, int] = field(default_factory=dict)
    dedup_by_doi: int = 0
    dedup_by_pmid: int = 0
    dedup_by_title: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_input": self.total_input,
            "unique_articles": self.unique_articles,
            "duplicates_removed": self.duplicates_removed,
            "merged_records": self.merged_records,
            "by_source": self.by_source,
            "dedup_by_doi": self.dedup_by_doi,
            "dedup_by_pmid": self.dedup_by_pmid,
            "dedup_by_title": self.dedup_by_title,
        }


# =============================================================================
# Union-Find for O(n) Deduplication
# =============================================================================


class UnionFind:
    """
    Union-Find (Disjoint Set Union) data structure for efficient deduplication.

    Time Complexity:
    - find: O(α(n)) ≈ O(1) amortized (inverse Ackermann)
    - union: O(α(n)) ≈ O(1) amortized

    This replaces the O(n²) nested loop in the original implementation.
    """

    def __init__(self, n: int):
        """Initialize with n elements (0 to n-1)."""
        self.parent = list(range(n))
        self.rank = [0] * n
        self.size = [1] * n

    def find(self, x: int) -> int:
        """Find root with path compression."""
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: int, y: int) -> bool:
        """
        Union by rank. Returns True if x and y were in different sets.
        """
        px, py = self.find(x), self.find(y)
        if px == py:
            return False

        # Union by rank
        if self.rank[px] < self.rank[py]:
            px, py = py, px
        self.parent[py] = px
        self.size[px] += self.size[py]

        if self.rank[px] == self.rank[py]:
            self.rank[px] += 1

        return True

    def get_groups(self) -> dict[int, list[int]]:
        """Get all groups as {root: [members]}."""
        groups: dict[int, list[int]] = {}
        for i in range(len(self.parent)):
            root = self.find(i)
            if root not in groups:
                groups[root] = []
            groups[root].append(i)
        return groups


# =============================================================================
# ResultAggregator
# =============================================================================


class ResultAggregator:
    """
    Aggregates and ranks results from multiple sources.

    Responsibilities:
    1. Deduplicate articles across sources (O(n) with Union-Find)
    2. Merge data from same article in different sources
    3. Calculate multi-dimensional ranking scores
    4. Sort and filter results

    Usage:
        aggregator = ResultAggregator()

        # Aggregate from multiple sources
        articles, stats = aggregator.aggregate([
            pubmed_results,
            crossref_results,
            openalex_results,
        ])

        # Rank with custom config
        config = RankingConfig.impact_focused()
        ranked = aggregator.rank(articles, config)
    """

    def __init__(self, config: RankingConfig | None = None):
        """
        Initialize ResultAggregator.

        Args:
            config: Default ranking configuration (can be overridden per call)
        """
        self._config = config or RankingConfig.default()

    def aggregate(
        self,
        article_lists: list[list[UnifiedArticle]],
        dedup_strategy: DeduplicationStrategy | None = None,
    ) -> tuple[list[UnifiedArticle], AggregationStats]:
        """
        Aggregate articles from multiple sources.

        Deduplicates and merges articles, preserving the best data from each source.
        Uses Union-Find algorithm for O(n) deduplication.

        Args:
            article_lists: List of article lists from different sources
            dedup_strategy: Override default deduplication strategy

        Returns:
            Tuple of (deduplicated articles, aggregation statistics)
        """
        strategy = dedup_strategy or self._config.dedup_strategy
        stats = AggregationStats()

        # Flatten input
        all_articles: list[UnifiedArticle] = []
        for articles in article_lists:
            all_articles.extend(articles)
            for article in articles:
                source = article.primary_source
                stats.by_source[source] = stats.by_source.get(source, 0) + 1

        stats.total_input = len(all_articles)

        if not all_articles:
            return [], stats

        # Deduplicate using Union-Find
        unique_articles = self._deduplicate_union_find(all_articles, strategy, stats)

        stats.unique_articles = len(unique_articles)
        stats.duplicates_removed = stats.total_input - stats.unique_articles

        return unique_articles, stats

    def rank(
        self,
        articles: list[UnifiedArticle],
        config: RankingConfig | None = None,
        query: str | None = None,
    ) -> list[UnifiedArticle]:
        """
        Rank articles using multi-dimensional scoring.

        Args:
            articles: Articles to rank
            config: Ranking configuration (uses default if not provided)
            query: Original query (used for relevance scoring)

        Returns:
            Sorted list of articles (highest score first)
        """
        config = config or self._config
        weights = config.normalized_weights()

        # Calculate scores for each article
        for article in articles:
            scores = self._calculate_dimension_scores(article, config, query)

            # Calculate weighted final score (including entity_match)
            final_score = (
                scores.get("relevance", 0.5) * weights["relevance"]
                + scores.get("quality", 0.5) * weights["quality"]
                + scores.get("recency", 0.5) * weights["recency"]
                + scores.get("impact", 0.5) * weights["impact"]
                + scores.get("source_trust", 0.5) * weights["source_trust"]
                + scores.get("entity_match", 0.5) * weights["entity_match"]
            )

            # Store scores in article (UnifiedArticle has these fields)
            article.ranking_score = final_score
            article.relevance_score = scores.get("relevance", 0.5)
            article.quality_score = scores.get("quality", 0.5)

        # Sort by score (descending)
        sorted_articles = sorted(
            articles,
            key=lambda a: getattr(a, "ranking_score", 0) or 0,
            reverse=True,
        )

        # Filter by minimum score
        if config.min_score > 0:
            sorted_articles = [a for a in sorted_articles if (getattr(a, "ranking_score", 0) or 0) >= config.min_score]

        # Limit results
        if config.max_results:
            sorted_articles = sorted_articles[: config.max_results]

        return sorted_articles

    def aggregate_and_rank(
        self,
        article_lists: list[list[UnifiedArticle]],
        config: RankingConfig | None = None,
        query: str | None = None,
    ) -> tuple[list[UnifiedArticle], AggregationStats]:
        """
        Convenience method: aggregate and rank in one call.

        Args:
            article_lists: List of article lists from different sources
            config: Ranking configuration
            query: Original query for relevance scoring

        Returns:
            Tuple of (ranked articles, aggregation statistics)
        """
        articles, stats = self.aggregate(article_lists)
        ranked = self.rank(articles, config, query)
        return ranked, stats

    # =========================================================================
    # Deduplication (Union-Find based)
    # =========================================================================

    def _deduplicate_union_find(
        self,
        articles: list[UnifiedArticle],
        strategy: DeduplicationStrategy,
        stats: AggregationStats,
    ) -> list[UnifiedArticle]:
        """
        Deduplicate articles using Union-Find for O(n) complexity.

        Algorithm:
        1. Build indexes (DOI, PMID, Title) - O(n)
        2. For each index, union articles with same key - O(n × α(n))
        3. Get groups and merge - O(n)

        Total: O(n) instead of O(n²)
        """
        n = len(articles)
        if n == 0:
            return []

        uf = UnionFind(n)

        # Build indexes and union
        doi_to_idx: dict[str, int] = {}
        pmid_to_idx: dict[str, int] = {}
        title_to_idx: dict[str, int] = {}

        min_title_len = self._config.title_min_length
        use_title = strategy in (
            DeduplicationStrategy.MODERATE,
            DeduplicationStrategy.AGGRESSIVE,
        )

        # Adjust title threshold for aggressive mode
        if strategy == DeduplicationStrategy.AGGRESSIVE:
            min_title_len = 15

        for i, article in enumerate(articles):
            # DOI matching
            if article.doi:
                normalized_doi = self._normalize_doi(article.doi)
                if normalized_doi in doi_to_idx:
                    if uf.union(i, doi_to_idx[normalized_doi]):
                        stats.dedup_by_doi += 1
                else:
                    doi_to_idx[normalized_doi] = i

            # PMID matching
            if article.pmid:
                if article.pmid in pmid_to_idx:
                    if uf.union(i, pmid_to_idx[article.pmid]):
                        stats.dedup_by_pmid += 1
                else:
                    pmid_to_idx[article.pmid] = i

            # Title matching (if enabled)
            if use_title and article.title:
                normalized_title = self._normalize_title(article.title)
                if len(normalized_title) >= min_title_len:
                    if normalized_title in title_to_idx:
                        if uf.union(i, title_to_idx[normalized_title]):
                            stats.dedup_by_title += 1
                    else:
                        title_to_idx[normalized_title] = i

        # Get groups and merge
        groups = uf.get_groups()
        unique: list[UnifiedArticle] = []

        for member_indices in groups.values():
            if len(member_indices) == 1:
                unique.append(articles[member_indices[0]])
            else:
                # Multiple duplicates - select primary and merge
                duplicates = [articles[i] for i in member_indices]
                primary = self._select_primary(duplicates)

                for dup in duplicates:
                    if dup is not primary:
                        primary.merge_from(dup)
                        stats.merged_records += 1

                unique.append(primary)

        return unique

    def _select_primary(self, articles: list[UnifiedArticle]) -> UnifiedArticle:
        """
        Select the primary article from duplicates.

        Prefers articles with:
        1. More identifiers
        2. More complete metadata
        3. Higher source trust
        """

        def score(article: UnifiedArticle) -> tuple[int, int, float]:
            # Count identifiers
            id_count = sum(
                1
                for x in [
                    article.pmid,
                    article.doi,
                    article.pmc,
                    getattr(article, "openalex_id", None),
                    getattr(article, "s2_id", None),
                    getattr(article, "core_id", None),
                ]
                if x
            )

            # Count metadata completeness
            meta_count = sum(
                1
                for x in [
                    article.abstract,
                    article.journal,
                    article.year,
                    article.volume,
                    article.issue,
                    article.pages,
                ]
                if x
            )

            # Source trust
            trust = self._config.source_trust_levels.get(article.primary_source, 0.5)

            return (id_count, meta_count, trust)

        return max(articles, key=score)

    # =========================================================================
    # Scoring Functions
    # =========================================================================

    def _calculate_dimension_scores(
        self,
        article: UnifiedArticle,
        config: RankingConfig,
        query: str | None,
    ) -> dict[str, float]:
        """Calculate scores for each ranking dimension."""
        return {
            "relevance": self._calculate_relevance(article, query),
            "quality": self._calculate_quality(article, config),
            "recency": self._calculate_recency(article, config),
            "impact": self._calculate_impact(article),
            "source_trust": self._calculate_source_trust(article, config),
            "entity_match": self._calculate_entity_match(article, config),
        }

    def _calculate_relevance(
        self,
        article: UnifiedArticle,
        query: str | None,
    ) -> float:
        """
        Calculate relevance score based on query match.

        Without query, returns 0.5 (neutral).
        """
        if not query:
            return 0.5

        query_lower = query.lower()
        query_terms = set(re.findall(r"\b\w{3,}\b", query_lower))

        if not query_terms:
            return 0.5

        # Check title match
        title_lower = article.title.lower() if article.title else ""
        title_terms = set(re.findall(r"\b\w{3,}\b", title_lower))
        title_overlap = len(query_terms & title_terms) / len(query_terms)

        # Check abstract match
        abstract_lower = article.abstract.lower() if article.abstract else ""
        abstract_terms = set(re.findall(r"\b\w{3,}\b", abstract_lower))
        abstract_overlap = len(query_terms & abstract_terms) / len(query_terms)

        # Check keyword/MeSH match
        keywords = getattr(article, "keywords", []) or []
        mesh_terms = getattr(article, "mesh_terms", []) or []
        keywords_lower = " ".join(keywords + mesh_terms).lower()
        keywords_terms = set(re.findall(r"\b\w{3,}\b", keywords_lower))
        keywords_overlap = len(query_terms & keywords_terms) / len(query_terms)

        # Weighted combination (title most important)
        relevance = title_overlap * 0.5 + abstract_overlap * 0.3 + keywords_overlap * 0.2

        return min(relevance, 1.0)

    def _calculate_quality(
        self,
        article: UnifiedArticle,
        config: RankingConfig,
    ) -> float:
        """
        Calculate quality score based on publication indicators.

        Factors:
        - Article type (meta-analysis > RCT > review > other)
        - Has peer review (assumed for journal articles)
        - Metadata completeness
        - Open access (small boost)
        """
        score = 0.5  # Base score

        # Article type boost
        article_type = (
            article.article_type.value if hasattr(article, "article_type") and article.article_type else "unknown"
        )
        score += config.get_article_type_weight(article_type)

        # Metadata completeness boost
        completeness = (
            sum(
                1
                for x in [
                    article.abstract,
                    article.doi,
                    article.journal,
                    article.volume,
                    article.issue,
                    article.pages,
                    article.year,
                ]
                if x
            )
            / 7
        )
        score += completeness * 0.1

        # Open access boost (small)
        if getattr(article, "has_open_access", False):
            score += 0.05

        return min(score, 1.0)

    def _calculate_recency(
        self,
        article: UnifiedArticle,
        config: RankingConfig,
    ) -> float:
        """
        Calculate recency score based on publication year.

        Uses exponential decay with configurable half-life.
        """
        if not article.year:
            return 0.3  # Unknown year gets low score

        current_year = datetime.now(tz=timezone.utc).year
        age = current_year - article.year

        age = max(age, 0)  # Future publication (preprint?)

        # Exponential decay
        half_life = config.recency_half_life_years
        return float(0.5 ** (age / half_life))

    def _calculate_impact(self, article: UnifiedArticle) -> float:
        """
        Calculate impact score based on citation metrics.

        Uses available metrics:
        - NIH percentile (best)
        - Relative Citation Ratio
        - Raw citation count
        """
        metrics = getattr(article, "citation_metrics", None)
        if not metrics:
            return 0.3  # Unknown impact gets low-neutral score

        # Use NIH percentile if available (0-100 → 0-1)
        nih_percentile = getattr(metrics, "nih_percentile", None)
        if nih_percentile is not None:
            return float(nih_percentile) / 100

        # Use RCR if available (normalize: 2.0 = average, 4.0 = excellent)
        rcr = getattr(metrics, "relative_citation_ratio", None)
        if rcr is not None:
            # Sigmoid-like transformation
            rcr_val = float(rcr)
            score = rcr_val / (rcr_val + 2.0)  # 0 → 0, 2 → 0.5, 4 → 0.67, 10 → 0.83
            return min(score, 1.0)

        # Use raw citation count (log scale)
        citation_count = getattr(metrics, "citation_count", None)
        if citation_count is not None:
            if citation_count <= 0:
                return 0.1
            # Log transformation: 1 → 0.1, 10 → 0.4, 100 → 0.7, 1000 → 1.0
            score = math.log10(float(citation_count) + 1) / 3
            return min(score, 1.0)

        return 0.3

    def _calculate_source_trust(
        self,
        article: UnifiedArticle,
        config: RankingConfig,
    ) -> float:
        """
        Calculate source trust score.

        Based on configured trust levels for each data source.
        Multi-source articles get boosted trust.
        """
        base_trust = config.source_trust_levels.get(article.primary_source, 0.5)

        # Boost for multi-source verification
        sources = getattr(article, "sources", []) or []
        num_sources = len(sources)
        if num_sources > 1:
            boost = min(0.1 * (num_sources - 1), 0.2)  # Max 0.2 boost
            base_trust = min(base_trust + boost, 1.0)

        return base_trust

    def _calculate_entity_match(
        self,
        article: UnifiedArticle,
        config: RankingConfig,
    ) -> float:
        """
        Calculate entity match score based on PubTator3 resolved entities.

        Phase 3: Checks if article's title/abstract/keywords contain
        the resolved entity names from semantic enhancement.

        If no entities were resolved (fallback mode), returns neutral score.
        """
        # If no matched entities provided, return neutral score
        if not config.matched_entities:
            return 0.5

        # Combine article text fields for matching
        article_text = ""
        if article.title:
            article_text += article.title.lower() + " "
        if article.abstract:
            article_text += article.abstract.lower() + " "

        # Check keywords/MeSH terms
        keywords = getattr(article, "keywords", []) or []
        mesh_terms = getattr(article, "mesh_terms", []) or []
        article_text += " ".join(keywords + mesh_terms).lower()

        if not article_text.strip():
            return 0.5

        # Count entity matches
        matched_count = 0
        total_entities = len(config.matched_entities)

        for entity_name in config.matched_entities:
            entity_lower = entity_name.lower()
            if entity_lower in article_text:
                matched_count += 1

        # Calculate score (0-1)
        if total_entities == 0:
            return 0.5

        # Base score from match ratio
        match_ratio = matched_count / total_entities

        # Boost if article mentions most/all entities
        if match_ratio >= 0.8:
            return min(1.0, 0.7 + match_ratio * 0.3)
        if match_ratio >= 0.5:
            return 0.5 + match_ratio * 0.3
        return 0.3 + match_ratio * 0.4

    # =========================================================================
    # Utility Methods
    # =========================================================================

    @staticmethod
    def _normalize_doi(doi: str) -> str:
        """Normalize DOI for comparison."""
        doi = doi.lower().strip()
        for prefix in ["https://doi.org/", "http://doi.org/", "doi:"]:
            doi = doi.removeprefix(prefix)
        return doi

    @staticmethod
    def _normalize_title(title: str) -> str:
        """Normalize title for comparison."""
        if not title:
            return ""

        # Lowercase
        title = title.lower()

        # Remove punctuation
        title = re.sub(r"[^\w\s]", "", title)

        # Remove extra whitespace
        return re.sub(r"\s+", " ", title).strip()


# =============================================================================
# Convenience Functions
# =============================================================================


def aggregate_results(
    article_lists: list[list[UnifiedArticle]],
    config: RankingConfig | None = None,
) -> tuple[list[UnifiedArticle], AggregationStats]:
    """
    Aggregate results from multiple sources.

    Args:
        article_lists: List of article lists from different sources
        config: Ranking configuration

    Returns:
        Tuple of (deduplicated articles, statistics)
    """
    aggregator = ResultAggregator(config)
    return aggregator.aggregate(article_lists)


def rank_results(
    articles: list[UnifiedArticle],
    config: RankingConfig | None = None,
    query: str | None = None,
) -> list[UnifiedArticle]:
    """
    Rank articles using multi-dimensional scoring.

    Args:
        articles: Articles to rank
        config: Ranking configuration
        query: Original query for relevance scoring

    Returns:
        Sorted list of articles
    """
    aggregator = ResultAggregator(config)
    return aggregator.rank(articles, config, query)
