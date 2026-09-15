"""Heuristic prioritization from citation, retrieval and publication metadata.

Weights and thresholds are local heuristics, not calibrated scientific quality
or benchmark performance. Database overlap measures retrieval coverage rather
than independent verification, and RCR alone does not establish a percentile.
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
    0-1 prioritization score whose usefulness requires task-specific evaluation.

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
        raw_weights = DEFAULT_WEIGHTS.copy() if weights is None else dict(weights)
        if not raw_weights or any(key not in DEFAULT_WEIGHTS for key in raw_weights):
            raise ValueError("weights must contain known landmark components")
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0
            for value in raw_weights.values()
        ):
            raise ValueError("weights must be finite and non-negative")
        total = sum(raw_weights.values())
        if not math.isfinite(total) or total <= 0:
            raise ValueError("weights must have a finite positive sum")
        self.weights = {key: value / total for key, value in raw_weights.items()}

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
        milestone_confidence = min(1.0, self._nonnegative_number(milestone_confidence) or 0.0)
        evidence_level_score = min(1.0, self._nonnegative_number(evidence_level_score) or 0.0)

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

            numeric = self._nonnegative_number(raw_value)
            if numeric is None:
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

        Database overlap is a retrieval heuristic, not independent validation.
        """
        if isinstance(source_count, bool) or not isinstance(source_count, int) or source_count <= 0:
            return 0.0, {"policy": "source_agreement_lookup", "raw_value": 0, "reason": "No known source coverage"}
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
            numeric = self._nonnegative_number(raw_value)
            if numeric is None:
                continue
            if policy.max_value is None:
                continue
            return self._normalize_log_score(numeric, policy.max_value), {
                "policy": policy.name,
                "raw_value": numeric,
                "reason": policy.reason,
            }

        # Fallback: estimate from total citations and publication age
        raw_citations = metrics.get("citation_count")
        if raw_citations is None:
            raw_citations = article.get("citation_count")
        citations = self._nonnegative_number(raw_citations)
        year = self._nonnegative_number(article.get("year") or article.get("pub_year"))
        if citations is not None and year is not None and year.is_integer():
            current_year = datetime.now(tz=timezone.utc).year
            if 1000 <= year <= current_year:
                age = max(1, current_year - int(year))
                estimated_velocity = citations / age
                return self._normalize_log_score(estimated_velocity, MAX_VELOCITY_FOR_NORMALIZATION), {
                    "policy": "estimated_from_citations_and_age",
                    "raw_value": round(estimated_velocity, 3),
                    "reason": "Estimated citations per year from publication age",
                }

        return 0.0, {"policy": "none", "raw_value": 0.0, "reason": "沒有可用的 velocity 指標"}

    @staticmethod
    def _nonnegative_number(value: Any) -> float | None:
        """Treat malformed/nonfinite provider metrics as unavailable, preserving zero."""
        if isinstance(value, bool) or value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) and number >= 0 else None

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
