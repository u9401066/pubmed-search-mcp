"""
Policy tables for landmark scoring.

The scorer consumes these policy definitions so that weights, normalization
limits, and source mappings can be tuned without changing core logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class MetricNormalizationPolicy:
    """Policy entry for normalizing a numeric metric into a 0-1 score."""

    name: str
    metric_key: str
    mode: Literal["percentile", "log"]
    max_value: float | None = None
    article_fallback_keys: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class ComponentWeightPolicy:
    """Policy entry for landmark score component weights."""

    component: str
    weight: float


DEFAULT_WEIGHT_POLICIES: tuple[ComponentWeightPolicy, ...] = (
    ComponentWeightPolicy("citation_impact", 0.35),
    ComponentWeightPolicy("source_agreement", 0.15),
    ComponentWeightPolicy("milestone_confidence", 0.20),
    ComponentWeightPolicy("evidence_quality", 0.15),
    ComponentWeightPolicy("citation_velocity", 0.15),
)

DEFAULT_WEIGHTS: dict[str, float] = {
    policy.component: policy.weight for policy in DEFAULT_WEIGHT_POLICIES
}

MAX_RCR_FOR_NORMALIZATION = 10.0
MAX_VELOCITY_FOR_NORMALIZATION = 50.0
MAX_CITATIONS_FOR_NORMALIZATION = 500.0

CITATION_IMPACT_POLICIES: tuple[MetricNormalizationPolicy, ...] = (
    MetricNormalizationPolicy(
        name="nih_percentile",
        metric_key="nih_percentile",
        mode="percentile",
        reason="優先使用 NIH percentile 直接映射到 0-1",
    ),
    MetricNormalizationPolicy(
        name="relative_citation_ratio",
        metric_key="relative_citation_ratio",
        mode="log",
        max_value=MAX_RCR_FOR_NORMALIZATION,
        reason="使用 RCR 做 field-normalized 對數正規化",
    ),
    MetricNormalizationPolicy(
        name="citation_count",
        metric_key="citation_count",
        mode="log",
        max_value=MAX_CITATIONS_FOR_NORMALIZATION,
        article_fallback_keys=("citation_count", "citations"),
        reason="缺少 field-normalized 指標時回退到原始引用數",
    ),
)

CITATION_VELOCITY_POLICIES: tuple[MetricNormalizationPolicy, ...] = (
    MetricNormalizationPolicy(
        name="citations_per_year",
        metric_key="citations_per_year",
        mode="log",
        max_value=MAX_VELOCITY_FOR_NORMALIZATION,
        reason="優先使用 iCite citations_per_year",
    ),
)

SOURCE_AGREEMENT_SCORES: dict[int, float] = {
    1: 0.1,
    2: 0.5,
    3: 0.75,
    4: 0.9,
}

EVIDENCE_LEVEL_SCORES: dict[str, float] = {
    "1": 1.0,
    "2": 0.75,
    "3": 0.50,
    "4": 0.25,
    "unknown": 0.0,
}
