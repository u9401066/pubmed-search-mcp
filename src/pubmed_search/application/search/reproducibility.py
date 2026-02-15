"""
Reproducibility Score — Quantifying Search Reproducibility.

This module calculates a reproducibility index for literature searches,
addressing a critical gap in evidence-based medicine: the ability to
verify and replicate systematic searches.

PRISMA 2020 guidelines (Page et al., BMJ 2021) require transparent,
reproducible search strategies. This module provides machine-readable
reproducibility metrics that no existing tool offers.

Key Metrics:
    - deterministic: Whether results are fully deterministic (no LLM/randomness)
    - query_formality: How structured the query is (MeSH > free text)
    - source_coverage: Fraction of queried sources that responded
    - result_stability: Expected temporal stability of results
    - audit_completeness: Whether full audit trail is available
    - overall_score: Weighted composite score (0-1)

Architecture:
    Stateless functions called after search completion.
    Input: search context (query, sources, results).
    Output: ReproducibilityScore dataclass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pubmed_search.domain.entities.article import UnifiedArticle


# =============================================================================
# Constants
# =============================================================================

# Component weights for overall score
_WEIGHT_DETERMINISTIC = 0.25
_WEIGHT_QUERY_FORMALITY = 0.20
_WEIGHT_SOURCE_COVERAGE = 0.20
_WEIGHT_RESULT_STABILITY = 0.15
_WEIGHT_AUDIT = 0.20

# MeSH field tags that indicate structured queries
_MESH_PATTERNS = re.compile(
    r"\[MeSH(?:\s*Terms)?\]|\[MeSH\s*Major\s*Topic\]|\[Majr\]|\[tiab\]|\[Title/Abstract\]|\[tw\]",
    re.IGNORECASE,
)

# Boolean operator patterns
_BOOLEAN_PATTERN = re.compile(r"\b(AND|OR|NOT)\b")

# All known sources we can query
_ALL_SOURCES = {
    "pubmed",
    "europe_pmc",
    "openalex",
    "semantic_scholar",
    "core",
    "crossref",
}

# Source stability tiers (how often a source's results change)
_SOURCE_STABILITY: dict[str, float] = {
    "pubmed": 0.95,  # Very stable, archival
    "europe_pmc": 0.90,  # Stable, mirrors PubMed + extras
    "crossref": 0.92,  # DOI metadata very stable
    "openalex": 0.80,  # Updates frequently (weekly snapshots)
    "semantic_scholar": 0.75,  # AI-driven, may rerank
    "core": 0.70,  # Aggregator, harvesting changes
}


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ReproducibilityScore:
    """
    Reproducibility metrics for a literature search.

    Each component is scored 0-1, where 1.0 = fully reproducible.
    """

    # Core metrics
    deterministic: bool  # True if zero randomness (no LLM, no sampling)
    query_formality: float  # 0-1, how structured the query is
    source_coverage: float  # 0-1, fraction of queried sources that responded
    result_stability: float  # 0-1, expected temporal stability
    audit_completeness: float  # 0-1, completeness of audit trail

    # Overall composite score
    overall_score: float

    # Diagnostics
    query_features: dict[str, bool] = field(default_factory=dict)
    sources_queried: list[str] = field(default_factory=list)
    sources_responded: list[str] = field(default_factory=list)
    sources_failed: list[str] = field(default_factory=list)
    timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "overall_score": round(self.overall_score, 3),
            "deterministic": self.deterministic,
            "query_formality": round(self.query_formality, 3),
            "source_coverage": round(self.source_coverage, 3),
            "result_stability": round(self.result_stability, 3),
            "audit_completeness": round(self.audit_completeness, 3),
            "query_features": self.query_features,
            "sources_queried": self.sources_queried,
            "sources_responded": self.sources_responded,
            "sources_failed": self.sources_failed,
        }

    @property
    def grade(self) -> str:
        """Human-readable reproducibility grade."""
        if self.overall_score >= 0.9:
            return "A"  # Excellent reproducibility
        if self.overall_score >= 0.8:
            return "B"  # Good reproducibility
        if self.overall_score >= 0.6:
            return "C"  # Moderate reproducibility
        if self.overall_score >= 0.4:
            return "D"  # Poor reproducibility
        return "F"  # Not reproducible


# =============================================================================
# Main Function
# =============================================================================


def calculate_reproducibility(
    query: str,
    sources_queried: list[str],
    sources_responded: list[str],
    articles: list[UnifiedArticle],
    *,
    used_llm: bool = False,
    used_sampling: bool = False,
    has_audit_trail: bool = True,
    has_dedup_stats: bool = True,
    has_source_counts: bool = True,
) -> ReproducibilityScore:
    """
    Calculate reproducibility score for a completed search.

    Args:
        query: The search query that was executed
        sources_queried: List of source names that were queried
        sources_responded: List of source names that returned results
        articles: Final result set
        used_llm: Whether any LLM was used in the pipeline
        used_sampling: Whether random sampling was used
        has_audit_trail: Whether full API call trace is available
        has_dedup_stats: Whether deduplication statistics are available
        has_source_counts: Whether per-source count data is available

    Returns:
        ReproducibilityScore with all metrics
    """
    # 1. Deterministic: no LLM, no randomness
    deterministic = not used_llm and not used_sampling

    # 2. Query formality
    query_formality, query_features = _score_query_formality(query)

    # 3. Source coverage
    source_coverage = _score_source_coverage(sources_queried, sources_responded)

    # 4. Result stability
    result_stability = _score_result_stability(sources_responded, articles)

    # 5. Audit completeness
    audit_completeness = _score_audit_completeness(
        has_audit_trail=has_audit_trail,
        has_dedup_stats=has_dedup_stats,
        has_source_counts=has_source_counts,
        has_query_analysis=bool(query_features),
        has_results=len(articles) > 0,
    )

    # Overall composite score
    det_score = 1.0 if deterministic else 0.3  # LLM = major reproducibility hit
    overall = (
        det_score * _WEIGHT_DETERMINISTIC
        + query_formality * _WEIGHT_QUERY_FORMALITY
        + source_coverage * _WEIGHT_SOURCE_COVERAGE
        + result_stability * _WEIGHT_RESULT_STABILITY
        + audit_completeness * _WEIGHT_AUDIT
    )

    sources_failed = [s for s in sources_queried if s not in sources_responded]

    return ReproducibilityScore(
        deterministic=deterministic,
        query_formality=query_formality,
        source_coverage=source_coverage,
        result_stability=result_stability,
        audit_completeness=audit_completeness,
        overall_score=overall,
        query_features=query_features,
        sources_queried=sources_queried,
        sources_responded=sources_responded,
        sources_failed=sources_failed,
    )


# =============================================================================
# Component Scorers
# =============================================================================


def _score_query_formality(query: str) -> tuple[float, dict[str, bool]]:
    """
    Score how formal/structured the query is.

    MeSH-tagged queries > Boolean queries > free text.

    Returns:
        (score 0-1, feature dict)
    """
    features: dict[str, bool] = {}

    # Check for MeSH field tags
    has_mesh = bool(_MESH_PATTERNS.search(query))
    features["has_mesh_tags"] = has_mesh

    # Check for Boolean operators
    has_boolean = bool(_BOOLEAN_PATTERN.search(query))
    features["has_boolean_operators"] = has_boolean

    # Check for quoted phrases
    has_quotes = '"' in query
    features["has_quoted_phrases"] = has_quotes

    # Check for field tags (e.g., [au], [ti], [la])
    has_field_tags = bool(re.search(r"\[\w+\]", query))
    features["has_field_tags"] = has_field_tags

    # Check for date/year restrictions
    has_date = bool(re.search(r"\d{4}(?:/\d{2})?(?:\[dp\]|\[edat\])?", query))
    features["has_date_restriction"] = has_date

    # Score calculation
    score = 0.3  # Base score for any query
    if has_mesh:
        score += 0.3  # MeSH = major formality boost
    if has_boolean:
        score += 0.15
    if has_quotes:
        score += 0.1
    if has_field_tags:
        score += 0.1
    if has_date:
        score += 0.05

    return min(score, 1.0), features


def _score_source_coverage(
    queried: list[str],
    responded: list[str],
) -> float:
    """
    Score what fraction of queried sources successfully responded.

    Accounts for:
    - Coverage ratio (responded / queried)
    - Diversity bonus (more sources queried = better)
    """
    if not queried:
        return 0.5  # Unknown

    coverage_ratio = len(responded) / len(queried)

    # Diversity bonus: querying more sources is better for reproducibility
    diversity = min(len(queried) / max(len(_ALL_SOURCES), 1), 1.0)
    diversity_bonus = diversity * 0.1  # Up to 0.1 bonus

    return min(coverage_ratio + diversity_bonus, 1.0)


def _score_result_stability(
    sources_responded: list[str],
    articles: list[UnifiedArticle],
) -> float:
    """
    Estimate temporal stability of results.

    Based on:
    - Source stability tiers (PubMed very stable, Semantic Scholar less so)
    - Multi-source verification (articles in 2+ sources are more stable)
    """
    if not sources_responded:
        return 0.5

    # Average source stability
    stabilities = [_SOURCE_STABILITY.get(s, 0.5) for s in sources_responded]
    avg_stability = sum(stabilities) / len(stabilities)

    # Multi-source verification bonus
    if articles:
        multi_source_count = sum(
            1
            for a in articles
            if len(getattr(a, "sources", []) or []) > 1
        )
        multi_source_ratio = multi_source_count / len(articles)
        verification_bonus = multi_source_ratio * 0.1  # Up to 0.1 bonus
    else:
        verification_bonus = 0.0

    return min(avg_stability + verification_bonus, 1.0)


def _score_audit_completeness(
    *,
    has_audit_trail: bool,
    has_dedup_stats: bool,
    has_source_counts: bool,
    has_query_analysis: bool,
    has_results: bool,
) -> float:
    """
    Score completeness of the audit trail.

    A fully auditable search should have:
    - Complete API call trace
    - Deduplication statistics
    - Per-source result counts
    - Query analysis details
    - Non-empty results
    """
    components = [
        (has_audit_trail, 0.3),
        (has_dedup_stats, 0.2),
        (has_source_counts, 0.2),
        (has_query_analysis, 0.2),
        (has_results, 0.1),
    ]

    return sum(weight for present, weight in components if present)
