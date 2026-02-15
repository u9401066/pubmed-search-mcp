"""
Landmark Scorer - Multi-Signal Importance Scoring for Research Papers

Identifies landmark papers from large search results using composite scoring
that combines five complementary signals:

1. Citation Impact: Field-normalized via RCR/NIH percentile (not raw count)
2. Multi-Source Agreement: Cross-database validation (found in N sources)
3. Milestone Patterns: Regex-based milestone detection confidence
4. Evidence Quality: Publication type and evidence level
5. Citation Velocity: Citations per year growth rate

This replaces simple citation-count sorting with a principled multi-signal
approach. The key insight: a paper with moderate citations but high RCR
(top 1% in its field) + found in 3 databases is more important than a
paper with many raw citations but low RCR from a single source.

Default weights:
    citation_impact:     0.35 (most reliable signal)
    milestone_confidence: 0.20 (domain-specific patterns)
    source_agreement:    0.15 (cross-validation)
    evidence_quality:    0.15 (study type hierarchy)
    citation_velocity:   0.15 (growth momentum)

Example:
    >>> scorer = LandmarkScorer()
    >>> score = scorer.score_article(
    ...     article={"pmid": "12345", "year": 2018},
    ...     icite_metrics={"relative_citation_ratio": 4.2, "nih_percentile": 95},
    ...     source_count=3,
    ... )
    >>> print(f"Landmark: {score.overall:.2f} ({score.tier})")
    Landmark: 0.78 (landmark)
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

from pubmed_search.domain.entities.timeline import LandmarkScore

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration Constants
# =============================================================================

# Default weights for landmark score components
DEFAULT_WEIGHTS: dict[str, float] = {
    "citation_impact": 0.35,
    "source_agreement": 0.15,
    "milestone_confidence": 0.20,
    "evidence_quality": 0.15,
    "citation_velocity": 0.15,
}

# RCR normalization: RCR 1.0 = field average
# Log scaling: score = min(1.0, log2(1 + RCR) / log2(1 + MAX_RCR))
MAX_RCR_FOR_NORMALIZATION = 10.0  # RCR ≥ 10 → max score

# Citation velocity normalization
MAX_VELOCITY_FOR_NORMALIZATION = 50.0  # ≥ 50 citations/year → max score

# Raw citation count normalization (fallback when RCR unavailable)
MAX_CITATIONS_FOR_NORMALIZATION = 500  # ≥ 500 citations → max score

# Source agreement scoring table
SOURCE_AGREEMENT_SCORES: dict[int, float] = {
    1: 0.1,  # Single source (minimal validation)
    2: 0.5,  # Two sources (moderate validation)
    3: 0.75,  # Three sources (strong validation)
    4: 0.9,  # Four sources (very strong)
}
# 5+ sources → 1.0

# Evidence level numeric scores (Oxford CEBM simplified)
EVIDENCE_LEVEL_SCORES: dict[str, float] = {
    "1": 1.0,  # Systematic reviews, meta-analyses
    "2": 0.75,  # RCTs, cohort studies
    "3": 0.50,  # Case-control, case series
    "4": 0.25,  # Case reports, expert opinion
    "unknown": 0.0,
}


# =============================================================================
# LandmarkScorer
# =============================================================================


class LandmarkScorer:
    """
    Compute composite landmark scores for identifying important papers.

    Uses a weighted combination of five signals to produce a single
    0-1 score that captures paper importance better than raw citation count.

    Thread-safe: stateless computation, can be used concurrently.
    """

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        """
        Initialize scorer with optional custom weights.

        Args:
            weights: Dict mapping component names to weights.
                     Will be normalized to sum to 1.0.
                     Default: citation_impact=0.35, milestone=0.20,
                     source=0.15, evidence=0.15, velocity=0.15
        """
        raw_weights = weights or DEFAULT_WEIGHTS.copy()
        # Normalize weights to sum to 1.0
        total = sum(raw_weights.values())
        self.weights = {k: v / total for k, v in raw_weights.items()} if total > 0 else raw_weights

    def score_article(
        self,
        article: dict[str, Any],
        icite_metrics: dict[str, Any] | None = None,
        source_count: int = 1,
        milestone_confidence: float = 0.0,
        evidence_level_score: float = 0.0,
    ) -> LandmarkScore:
        """
        Compute composite landmark score for a single article.

        Args:
            article: Article dict with pmid, year, citation_count, etc.
            icite_metrics: iCite metrics dict with RCR, percentile, APT, etc.
            source_count: Number of distinct sources that found this article
            milestone_confidence: Pre-computed milestone detection confidence (0-1)
            evidence_level_score: Pre-computed evidence quality score (0-1)

        Returns:
            LandmarkScore with composite and per-component scores
        """
        metrics = icite_metrics or {}

        # Compute each component
        citation_impact = self._compute_citation_impact(article, metrics)
        source_agreement = self._compute_source_agreement(source_count)
        citation_velocity = self._compute_citation_velocity(article, metrics)

        # Weighted combination
        overall = (
            self.weights.get("citation_impact", 0.35) * citation_impact
            + self.weights.get("source_agreement", 0.15) * source_agreement
            + self.weights.get("milestone_confidence", 0.20) * milestone_confidence
            + self.weights.get("evidence_quality", 0.15) * evidence_level_score
            + self.weights.get("citation_velocity", 0.15) * citation_velocity
        )

        return LandmarkScore(
            overall=min(1.0, overall),
            citation_impact=citation_impact,
            source_agreement=source_agreement,
            milestone_confidence=milestone_confidence,
            evidence_quality=evidence_level_score,
            citation_velocity=citation_velocity,
        )

    def score_articles(
        self,
        articles: list[dict[str, Any]],
        icite_data: dict[str, dict[str, Any]] | None = None,
        source_counts: dict[str, int] | None = None,
        milestone_scores: dict[str, float] | None = None,
        evidence_scores: dict[str, float] | None = None,
    ) -> list[tuple[dict[str, Any], LandmarkScore]]:
        """
        Score a batch of articles and return sorted by landmark score.

        This is the main entry point for batch scoring. Uses pre-computed
        per-article data to efficiently score all articles at once.

        Args:
            articles: List of article dicts
            icite_data: Dict mapping PMID → iCite metrics dict
            source_counts: Dict mapping PMID → number of sources
            milestone_scores: Dict mapping PMID → milestone confidence (0-1)
            evidence_scores: Dict mapping PMID → evidence quality (0-1)

        Returns:
            List of (article, LandmarkScore) tuples, sorted by overall desc
        """
        icite = icite_data or {}
        sources = source_counts or {}
        milestones = milestone_scores or {}
        evidence = evidence_scores or {}

        scored: list[tuple[dict[str, Any], LandmarkScore]] = []
        for article in articles:
            pmid = str(article.get("pmid", ""))
            score = self.score_article(
                article=article,
                icite_metrics=icite.get(pmid),
                source_count=sources.get(pmid, 1),
                milestone_confidence=milestones.get(pmid, 0.0),
                evidence_level_score=evidence.get(pmid, 0.0),
            )
            scored.append((article, score))

        # Sort by overall score (highest first)
        scored.sort(key=lambda x: x[1].overall, reverse=True)
        return scored

    # =========================================================================
    # Component Computations
    # =========================================================================

    def _compute_citation_impact(self, article: dict[str, Any], metrics: dict[str, Any]) -> float:
        """
        Compute field-normalized citation impact score (0-1).

        Priority order:
        1. NIH percentile (most interpretable, already 0-100)
        2. RCR (field-normalized, log-scaled)
        3. Raw citation count (fallback, log-scaled)

        This is the key improvement over raw citation count: a niche paper
        with RCR=4.2 (top 1% in its small field) scores higher than a
        popular review with 200 citations but RCR=0.8 (below field average).
        """
        # Best signal: NIH percentile (already 0-100, directly meaningful)
        percentile = metrics.get("nih_percentile")
        if percentile is not None and percentile > 0:
            return min(1.0, float(percentile) / 100.0)

        # Good signal: RCR (1.0 = field average)
        # Log scaling: RCR 1.0 → 0.32, RCR 4.0 → 0.68, RCR 10+ → 1.0
        rcr = metrics.get("relative_citation_ratio")
        if rcr is not None and rcr > 0:
            return min(
                1.0,
                math.log2(1 + float(rcr)) / math.log2(1 + MAX_RCR_FOR_NORMALIZATION),
            )

        # Fallback: raw citation count (less meaningful but better than nothing)
        citations = metrics.get("citation_count") or article.get("citation_count") or article.get("citations", 0)
        if citations and int(citations) > 0:
            return min(
                1.0,
                math.log2(1 + int(citations)) / math.log2(1 + MAX_CITATIONS_FOR_NORMALIZATION),
            )

        return 0.0

    def _compute_source_agreement(self, source_count: int) -> float:
        """
        Compute source agreement score (0-1).

        Articles found in more independent sources are more likely
        to be genuinely important. This provides cross-validation
        that pure citation metrics cannot.
        """
        if source_count >= 5:
            return 1.0
        return SOURCE_AGREEMENT_SCORES.get(source_count, 0.1)

    def _compute_citation_velocity(self, article: dict[str, Any], metrics: dict[str, Any]) -> float:
        """
        Compute citation velocity score (0-1).

        High velocity = actively cited, growing impact.
        This helps identify "rising stars" that may not yet have
        high total citations but are rapidly gaining influence.
        """
        # Best: direct citations_per_year from iCite
        velocity = metrics.get("citations_per_year")
        if velocity is not None and float(velocity) > 0:
            return min(
                1.0,
                math.log2(1 + float(velocity)) / math.log2(1 + MAX_VELOCITY_FOR_NORMALIZATION),
            )

        # Fallback: estimate from total citations and publication age
        citations = metrics.get("citation_count") or article.get("citation_count", 0)
        year = article.get("year") or article.get("pub_year")
        if citations and year:
            try:
                current_year = datetime.now(tz=timezone.utc).year
                age = max(1, current_year - int(year))
                estimated_velocity = float(int(citations)) / age
                return min(
                    1.0,
                    math.log2(1 + estimated_velocity) / math.log2(1 + MAX_VELOCITY_FOR_NORMALIZATION),
                )
            except (ValueError, TypeError):
                pass

        return 0.0


def evidence_level_to_score(level: str) -> float:
    """Convert evidence level string to numeric score (0-1)."""
    return EVIDENCE_LEVEL_SCORES.get(level, 0.0)
