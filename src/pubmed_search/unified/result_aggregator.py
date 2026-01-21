"""
ResultAggregator - Multi-Source Result Merging and Ranking

This module provides intelligent result aggregation from multiple academic sources:
1. Deduplication (DOI > PMID > Title fuzzy match)
2. Multi-dimensional ranking (relevance, quality, recency, impact, source_trust)
3. Score normalization and weighting

Architecture Decision:
    ResultAggregator operates on UnifiedArticle objects.
    It does NOT make API calls - purely processes existing results.

    Ranking uses a weighted multi-dimensional scoring system that can be
    customized for different use cases (systematic review vs quick lookup).

Example:
    >>> from pubmed_search.models import UnifiedArticle
    >>> from pubmed_search.unified import ResultAggregator, RankingConfig
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

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

# Import from sibling module
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from models.unified_article import UnifiedArticle


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


class DeduplicationStrategy(Enum):
    """
    Strategy for handling duplicate articles.

    STRICT: Only DOI/PMID exact matches are considered duplicates
    MODERATE: DOI/PMID + normalized title match
    AGGRESSIVE: Include fuzzy title matching (Levenshtein distance)
    """

    STRICT = "strict"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


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
    """

    # Dimension weights (should sum to 1.0)
    relevance_weight: float = 0.30
    quality_weight: float = 0.20
    recency_weight: float = 0.20
    impact_weight: float = 0.20
    source_trust_weight: float = 0.10

    # Deduplication settings
    dedup_strategy: DeduplicationStrategy = DeduplicationStrategy.MODERATE

    # Recency settings
    recency_half_life_years: float = 5.0  # Score halves every N years

    # Quality indicators
    quality_journal_weights: dict[str, float] = field(default_factory=dict)
    quality_article_type_weights: dict[str, float] = field(default_factory=dict)

    # Source trust levels (0-1)
    source_trust_levels: dict[str, float] = field(
        default_factory=lambda: {
            "pubmed": 1.0,
            "crossref": 0.9,
            "openalex": 0.85,
            "semantic_scholar": 0.85,
            "europe_pmc": 0.9,
            "core": 0.7,
        }
    )

    # Minimum score to include in results
    min_score: float = 0.0

    # Maximum results to return
    max_results: int | None = None

    @classmethod
    def default(cls) -> RankingConfig:
        """Get default balanced configuration."""
        return cls()

    @classmethod
    def impact_focused(cls) -> RankingConfig:
        """Get impact-focused configuration (emphasizes citations)."""
        return cls(
            relevance_weight=0.20,
            quality_weight=0.15,
            recency_weight=0.15,
            impact_weight=0.40,
            source_trust_weight=0.10,
        )

    @classmethod
    def recency_focused(cls) -> RankingConfig:
        """Get recency-focused configuration (emphasizes recent publications)."""
        return cls(
            relevance_weight=0.25,
            quality_weight=0.15,
            recency_weight=0.40,
            impact_weight=0.10,
            source_trust_weight=0.10,
            recency_half_life_years=3.0,
        )

    @classmethod
    def quality_focused(cls) -> RankingConfig:
        """Get quality-focused configuration (emphasizes journal quality)."""
        return cls(
            relevance_weight=0.20,
            quality_weight=0.40,
            recency_weight=0.15,
            impact_weight=0.15,
            source_trust_weight=0.10,
        )

    def normalized_weights(self) -> dict[str, float]:
        """Get normalized weights that sum to 1.0."""
        total = (
            self.relevance_weight
            + self.quality_weight
            + self.recency_weight
            + self.impact_weight
            + self.source_trust_weight
        )

        if total == 0:
            total = 1.0

        return {
            "relevance": self.relevance_weight / total,
            "quality": self.quality_weight / total,
            "recency": self.recency_weight / total,
            "impact": self.impact_weight / total,
            "source_trust": self.source_trust_weight / total,
        }


@dataclass
class AggregationStats:
    """Statistics from aggregation process."""

    total_input: int = 0
    unique_articles: int = 0
    duplicates_removed: int = 0
    merged_records: int = 0
    by_source: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_input": self.total_input,
            "unique_articles": self.unique_articles,
            "duplicates_removed": self.duplicates_removed,
            "merged_records": self.merged_records,
            "by_source": self.by_source,
        }


class ResultAggregator:
    """
    Aggregates and ranks results from multiple sources.

    Responsibilities:
    1. Deduplicate articles across sources
    2. Merge data from same article in different sources
    3. Calculate multi-dimensional ranking scores
    4. Sort and filter results

    Usage:
        aggregator = ResultAggregator()

        # Aggregate from multiple sources
        articles = aggregator.aggregate([
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

        # Deduplicate
        unique_articles = self._deduplicate(all_articles, strategy)

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

            # Calculate weighted final score
            final_score = (
                scores.get("relevance", 0.5) * weights["relevance"]
                + scores.get("quality", 0.5) * weights["quality"]
                + scores.get("recency", 0.5) * weights["recency"]
                + scores.get("impact", 0.5) * weights["impact"]
                + scores.get("source_trust", 0.5) * weights["source_trust"]
            )

            article._ranking_score = final_score
            article._relevance_score = scores.get("relevance", 0.5)
            article._quality_score = scores.get("quality", 0.5)

        # Sort by score (descending)
        sorted_articles = sorted(
            articles,
            key=lambda a: a._ranking_score or 0,
            reverse=True,
        )

        # Filter by minimum score
        if config.min_score > 0:
            sorted_articles = [
                a
                for a in sorted_articles
                if (a._ranking_score or 0) >= config.min_score
            ]

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

    def _deduplicate(
        self,
        articles: list[UnifiedArticle],
        strategy: DeduplicationStrategy,
    ) -> list[UnifiedArticle]:
        """
        Deduplicate articles using specified strategy.

        Priority for keeping articles:
        1. Articles with more identifiers
        2. Articles with more metadata
        3. Articles from higher-trust sources

        When duplicates are found, data is merged.
        """
        # Build index for deduplication
        doi_index: dict[str, list[UnifiedArticle]] = {}
        pmid_index: dict[str, list[UnifiedArticle]] = {}
        title_index: dict[str, list[UnifiedArticle]] = {}

        for article in articles:
            # Index by DOI
            if article.doi:
                normalized_doi = self._normalize_doi(article.doi)
                if normalized_doi not in doi_index:
                    doi_index[normalized_doi] = []
                doi_index[normalized_doi].append(article)

            # Index by PMID
            if article.pmid:
                if article.pmid not in pmid_index:
                    pmid_index[article.pmid] = []
                pmid_index[article.pmid].append(article)

            # Index by normalized title
            if strategy in (
                DeduplicationStrategy.MODERATE,
                DeduplicationStrategy.AGGRESSIVE,
            ):
                normalized_title = self._normalize_title(article.title)
                if (
                    normalized_title and len(normalized_title) > 20
                ):  # Skip very short titles
                    if normalized_title not in title_index:
                        title_index[normalized_title] = []
                    title_index[normalized_title].append(article)

        # Find and merge duplicates
        processed: set[int] = set()
        unique: list[UnifiedArticle] = []

        for article in articles:
            article_id = id(article)
            if article_id in processed:
                continue

            # Find all duplicates of this article
            duplicates: list[UnifiedArticle] = [article]

            # Check DOI matches
            if article.doi:
                normalized_doi = self._normalize_doi(article.doi)
                for dup in doi_index.get(normalized_doi, []):
                    if id(dup) != article_id and id(dup) not in processed:
                        duplicates.append(dup)

            # Check PMID matches
            if article.pmid:
                for dup in pmid_index.get(article.pmid, []):
                    if (
                        id(dup) not in [id(d) for d in duplicates]
                        and id(dup) not in processed
                    ):
                        duplicates.append(dup)

            # Check title matches (if enabled)
            if strategy in (
                DeduplicationStrategy.MODERATE,
                DeduplicationStrategy.AGGRESSIVE,
            ):
                normalized_title = self._normalize_title(article.title)
                if normalized_title and len(normalized_title) > 20:
                    for dup in title_index.get(normalized_title, []):
                        if (
                            id(dup) not in [id(d) for d in duplicates]
                            and id(dup) not in processed
                        ):
                            duplicates.append(dup)

            # Merge duplicates into primary article
            primary = self._select_primary(duplicates)
            for dup in duplicates:
                if id(dup) != id(primary):
                    primary.merge_from(dup)
                processed.add(id(dup))

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

        def score(article: UnifiedArticle) -> tuple:
            # Count identifiers
            id_count = sum(
                [
                    1
                    for x in [
                        article.pmid,
                        article.doi,
                        article.pmc,
                        article.openalex_id,
                        article.s2_id,
                        article.core_id,
                    ]
                    if x
                ]
            )

            # Count metadata completeness
            meta_count = sum(
                [
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
                ]
            )

            # Source trust
            trust = self._config.source_trust_levels.get(article.primary_source, 0.5)

            return (id_count, meta_count, trust)

        return max(articles, key=score)

    def _calculate_dimension_scores(
        self,
        article: UnifiedArticle,
        config: RankingConfig,
        query: str | None,
    ) -> dict[str, float]:
        """Calculate scores for each ranking dimension."""
        scores = {}

        # Relevance score (requires query)
        scores["relevance"] = self._calculate_relevance(article, query)

        # Quality score
        scores["quality"] = self._calculate_quality(article, config)

        # Recency score
        scores["recency"] = self._calculate_recency(article, config)

        # Impact score
        scores["impact"] = self._calculate_impact(article)

        # Source trust score
        scores["source_trust"] = self._calculate_source_trust(article, config)

        return scores

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
        title_overlap = (
            len(query_terms & title_terms) / len(query_terms) if query_terms else 0
        )

        # Check abstract match
        abstract_lower = article.abstract.lower() if article.abstract else ""
        abstract_terms = set(re.findall(r"\b\w{3,}\b", abstract_lower))
        abstract_overlap = (
            len(query_terms & abstract_terms) / len(query_terms) if query_terms else 0
        )

        # Check keyword/MeSH match
        keywords_lower = " ".join(article.keywords + article.mesh_terms).lower()
        keywords_terms = set(re.findall(r"\b\w{3,}\b", keywords_lower))
        keywords_overlap = (
            len(query_terms & keywords_terms) / len(query_terms) if query_terms else 0
        )

        # Weighted combination (title most important)
        relevance = (
            title_overlap * 0.5 + abstract_overlap * 0.3 + keywords_overlap * 0.2
        )

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
        - Journal (if weights provided)
        - Has peer review (assumed for journal articles)
        - Metadata completeness
        """
        score = 0.5  # Base score

        # Article type boost
        type_weights = {
            "meta-analysis": 0.3,
            "systematic-review": 0.25,
            "randomized-controlled-trial": 0.2,
            "clinical-trial": 0.15,
            "review": 0.1,
            "journal-article": 0.05,
        }
        article_type = article.article_type.value if article.article_type else "unknown"
        score += type_weights.get(article_type, 0)

        # Metadata completeness boost
        completeness = (
            sum(
                [
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
                ]
            )
            / 7
        )
        score += completeness * 0.1

        # Open access boost (small)
        if article.has_open_access:
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

        current_year = datetime.now().year
        age = current_year - article.year

        if age < 0:
            age = 0  # Future publication (preprint?)

        # Exponential decay
        half_life = config.recency_half_life_years
        score = 0.5 ** (age / half_life)

        return score

    def _calculate_impact(self, article: UnifiedArticle) -> float:
        """
        Calculate impact score based on citation metrics.

        Uses available metrics:
        - NIH percentile (best)
        - Relative Citation Ratio
        - Raw citation count
        """
        if not article.citation_metrics:
            return 0.3  # Unknown impact gets low-neutral score

        metrics = article.citation_metrics

        # Use NIH percentile if available (0-100 → 0-1)
        if metrics.nih_percentile is not None:
            return metrics.nih_percentile / 100

        # Use RCR if available (normalize: 2.0 = average, 4.0 = excellent)
        if metrics.relative_citation_ratio is not None:
            # Sigmoid-like transformation
            rcr = metrics.relative_citation_ratio
            score = rcr / (rcr + 2.0)  # 0 → 0, 2 → 0.5, 4 → 0.67, 10 → 0.83
            return min(score, 1.0)

        # Use raw citation count (log scale)
        if metrics.citation_count is not None:
            import math

            count = metrics.citation_count
            if count <= 0:
                return 0.1
            # Log transformation: 1 → 0.1, 10 → 0.4, 100 → 0.7, 1000 → 1.0
            score = math.log10(count + 1) / 3
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
        num_sources = len(article.sources)
        if num_sources > 1:
            boost = min(0.1 * (num_sources - 1), 0.2)  # Max 0.2 boost
            base_trust = min(base_trust + boost, 1.0)

        return base_trust

    @staticmethod
    def _normalize_doi(doi: str) -> str:
        """Normalize DOI for comparison."""
        doi = doi.lower().strip()
        for prefix in ["https://doi.org/", "http://doi.org/", "doi:"]:
            if doi.startswith(prefix):
                doi = doi[len(prefix) :]
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
        title = re.sub(r"\s+", " ", title).strip()

        return title


# Convenience functions


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
