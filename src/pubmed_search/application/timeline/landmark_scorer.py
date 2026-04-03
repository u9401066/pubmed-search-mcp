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

from .landmark_policy import (
    CITATION_IMPACT_POLICIES,
    CITATION_VELOCITY_POLICIES,
    DEFAULT_WEIGHTS,
    EVIDENCE_LEVEL_SCORES,
    MAX_CITATIONS_FOR_NORMALIZATION,
    MAX_RCR_FOR_NORMALIZATION,
    MAX_VELOCITY_FOR_NORMALIZATION,
    SOURCE_AGREEMENT_SCORES,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_WEIGHTS",
    "MAX_RCR_FOR_NORMALIZATION",
    "MAX_VELOCITY_FOR_NORMALIZATION",
    "MAX_CITATIONS_FOR_NORMALIZATION",
    "SOURCE_AGREEMENT_SCORES",
    "EVIDENCE_LEVEL_SCORES",
    "LandmarkScorer",
    "evidence_level_to_score",
]


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
        citation_impact, citation_impact_diag = self._compute_citation_impact(article, metrics)
        source_agreement, source_agreement_diag = self._compute_source_agreement(source_count)
        citation_velocity, citation_velocity_diag = self._compute_citation_velocity(article, metrics)

        component_hits = [
            self._component_hit("citation_impact", citation_impact, citation_impact_diag),
            self._component_hit("source_agreement", source_agreement, source_agreement_diag),
            self._component_hit(
                "milestone_confidence",
                milestone_confidence,
                {
                    "policy": "passthrough",
                    "raw_value": milestone_confidence,
                    "reason": "直接使用 milestone detector 的信心分數",
                },
            ),
            self._component_hit(
                "evidence_quality",
                evidence_level_score,
                {
                    "policy": "passthrough",
                    "raw_value": evidence_level_score,
                    "reason": "直接使用 evidence level 對應分數",
                },
            ),
            self._component_hit("citation_velocity", citation_velocity, citation_velocity_diag),
        ]

        overall = sum(hit["weighted_score"] for hit in component_hits)
        diagnostics = {
            "weights": {name: round(weight, 3) for name, weight in self.weights.items()},
            "component_hits": component_hits,
        }

        return LandmarkScore(
            overall=min(1.0, overall),
            citation_impact=citation_impact,
            source_agreement=source_agreement,
            milestone_confidence=milestone_confidence,
            evidence_quality=evidence_level_score,
            citation_velocity=citation_velocity,
            diagnostics=diagnostics,
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

    def _compute_citation_impact(
        self, article: dict[str, Any], metrics: dict[str, Any]
    ) -> tuple[float, dict[str, Any]]:
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
        for policy in CITATION_IMPACT_POLICIES:
            raw_value = metrics.get(policy.metric_key)
            if raw_value is None:
                for key in policy.article_fallback_keys:
                    raw_value = article.get(key)
                    if raw_value is not None:
                        break

            if raw_value is None:
                continue

            numeric = float(raw_value)
            if numeric <= 0:
                continue

            if policy.mode == "percentile":
                score = min(1.0, numeric / 100.0)
            else:
                if policy.max_value is None:
                    continue
                score = self._normalize_log_score(numeric, policy.max_value)

            return score, {
                "policy": policy.name,
                "raw_value": numeric,
                "reason": policy.reason,
            }

        return 0.0, {"policy": "none", "raw_value": 0.0, "reason": "沒有可用的 citation 指標"}

    def _compute_source_agreement(self, source_count: int) -> tuple[float, dict[str, Any]]:
        """
        Compute source agreement score (0-1).

        Articles found in more independent sources are more likely
        to be genuinely important. This provides cross-validation
        that pure citation metrics cannot.
        """
        if source_count >= 5:
            return 1.0, {
                "policy": "source_agreement_lookup",
                "raw_value": source_count,
                "reason": "5 個以上來源視為完全跨庫一致",
            }
        score = SOURCE_AGREEMENT_SCORES.get(source_count, 0.1)
        return score, {
            "policy": "source_agreement_lookup",
            "raw_value": source_count,
            "reason": "使用來源數量對照表進行跨庫一致性加權",
        }

    def _compute_citation_velocity(
        self, article: dict[str, Any], metrics: dict[str, Any]
    ) -> tuple[float, dict[str, Any]]:
        """
        Compute citation velocity score (0-1).

        High velocity = actively cited, growing impact.
        This helps identify "rising stars" that may not yet have
        high total citations but are rapidly gaining influence.
        """
        for policy in CITATION_VELOCITY_POLICIES:
            raw_value = metrics.get(policy.metric_key)
            if raw_value is None:
                continue
            numeric = float(raw_value)
            if numeric <= 0:
                continue
            if policy.max_value is None:
                continue
            return self._normalize_log_score(numeric, policy.max_value), {
                "policy": policy.name,
                "raw_value": numeric,
                "reason": policy.reason,
            }

        # Fallback: estimate from total citations and publication age
        citations = metrics.get("citation_count") or article.get("citation_count", 0)
        year = article.get("year") or article.get("pub_year")
        if citations and year:
            try:
                current_year = datetime.now(tz=timezone.utc).year
                age = max(1, current_year - int(year))
                estimated_velocity = float(int(citations)) / age
                return self._normalize_log_score(estimated_velocity, MAX_VELOCITY_FOR_NORMALIZATION), {
                    "policy": "estimated_from_citations_and_age",
                    "raw_value": round(estimated_velocity, 3),
                    "reason": "用引用數與論文年齡估算 citations_per_year",
                }
            except (ValueError, TypeError):
                pass

        return 0.0, {"policy": "none", "raw_value": 0.0, "reason": "沒有可用的 velocity 指標"}

    def _normalize_log_score(self, value: float, max_value: float) -> float:
        """Normalize a positive metric with log scaling."""
        return min(1.0, math.log2(1 + value) / math.log2(1 + max_value))

    def _component_hit(self, component: str, score: float, diagnostic: dict[str, Any]) -> dict[str, Any]:
        """Build per-component diagnostics for explainable scoring."""
        weight = self.weights.get(component, 0.0)
        return {
            "component": component,
            "policy": diagnostic.get("policy", "unknown"),
            "raw_value": diagnostic.get("raw_value", 0.0),
            "normalized_score": round(score, 3),
            "weight": round(weight, 3),
            "weighted_score": round(weight * score, 3),
            "reason": diagnostic.get("reason", ""),
        }


def evidence_level_to_score(level: str) -> float:
    """Convert evidence level string to numeric score (0-1)."""
    return EVIDENCE_LEVEL_SCORES.get(level, 0.0)
