"""
Scoring and diagnostics helpers for ImageQueryAdvisor.

The scorer consumes policy tables from advisor_policy and returns structured,
explainable diagnostics that describe why a recommendation was made.
"""

from __future__ import annotations

import re
from typing import Any

from .advisor_policy import (
    COLLECTION_POLICIES,
    IMAGE_TYPE_POLICIES,
    POST_2020_KEYWORDS,
    QUERY_CLEANUP_RULES,
    STRONG_IMAGE_TYPE_CODES,
    SUITABILITY_RULES,
    SUITABILITY_THRESHOLD,
    TYPE_SUITABILITY_CAP,
    TYPE_SUITABILITY_WEIGHT,
    YEAR_PATTERN,
)


def _match_keywords(query_lower: str, keywords: frozenset[str]) -> tuple[str, ...]:
    return tuple(sorted(keyword for keyword in keywords if keyword in query_lower))


def _make_feature_hit(
    *,
    category: str,
    rule: str,
    reason: str,
    matched_terms: tuple[str, ...] = (),
    score_delta: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hit: dict[str, Any] = {
        "category": category,
        "rule": rule,
        "reason": reason,
        "matched_terms": list(matched_terms),
    }
    if score_delta is not None:
        hit["score_delta"] = round(score_delta, 3)
    if metadata:
        hit["metadata"] = metadata
    return hit


def score_image_suitability(query_lower: str) -> tuple[float, list[dict[str, Any]]]:
    """Compute suitability score and explainable feature hits."""
    score = 0.0
    feature_hits: list[dict[str, Any]] = []

    for rule in SUITABILITY_RULES:
        matched = _match_keywords(query_lower, rule.keywords)
        if not matched:
            continue

        contribution = min(len(matched) * rule.score_per_hit, rule.max_contribution) * rule.direction
        score += contribution
        feature_hits.append(
            _make_feature_hit(
                category="suitability",
                rule=rule.name,
                reason=rule.reason,
                matched_terms=matched,
                score_delta=contribution,
                metadata={"hits": len(matched)},
            )
        )

    strong_type_hits: dict[str, tuple[str, ...]] = {}
    total_strong_hits = 0
    for policy in IMAGE_TYPE_POLICIES:
        if policy.image_type not in STRONG_IMAGE_TYPE_CODES:
            continue
        matched = _match_keywords(query_lower, policy.keywords)
        if matched:
            strong_type_hits[policy.image_type] = matched
            total_strong_hits += len(matched)

    if total_strong_hits:
        matched_terms = tuple(
            dict.fromkeys(
                term
                for terms in strong_type_hits.values()
                for term in terms
            )
        )
        contribution = min(total_strong_hits * TYPE_SUITABILITY_WEIGHT, TYPE_SUITABILITY_CAP)
        score += contribution
        feature_hits.append(
            _make_feature_hit(
                category="suitability",
                rule="typed_image_context",
                reason="強影像類型詞彙",
                matched_terms=matched_terms,
                score_delta=contribution,
                metadata={
                    "type_hits": {code: len(terms) for code, terms in strong_type_hits.items()},
                    "hits": total_strong_hits,
                },
            )
        )

    return max(-1.0, min(1.0, score)), feature_hits


def recommend_image_type(
    query_lower: str,
) -> tuple[str | None, str, str | None, dict[str, int], list[dict[str, Any]]]:
    """Recommend image type from policy table with diagnostics."""
    scores: dict[str, int] = {}
    feature_hits: list[dict[str, Any]] = []

    for policy in IMAGE_TYPE_POLICIES:
        matched = _match_keywords(query_lower, policy.keywords)
        scores[policy.image_type] = len(matched)
        if matched:
            feature_hits.append(
                _make_feature_hit(
                    category="image_type",
                    rule=policy.image_type,
                    reason=policy.reason,
                    matched_terms=matched,
                    metadata={"hits": len(matched), "coarse_category": policy.coarse_category},
                )
            )

    if not scores or max(scores.values()) == 0:
        return (
            None,
            "未偵測到特定影像類型關鍵字，不指定 image_type（搜尋所有類型）",
            None,
            scores,
            feature_hits,
        )

    best_policy = max(IMAGE_TYPE_POLICIES, key=lambda policy: scores[policy.image_type])
    return (
        best_policy.image_type,
        best_policy.reason,
        best_policy.coarse_category,
        scores,
        feature_hits,
    )


def recommend_collection(
    query_lower: str,
) -> tuple[str | None, str, dict[str, int], list[dict[str, Any]]]:
    """Recommend collection using ordered collection policies."""
    scores: dict[str, int] = {}
    feature_hits: list[dict[str, Any]] = []

    for policy in COLLECTION_POLICIES:
        matched = _match_keywords(query_lower, policy.keywords)
        scores[policy.collection] = len(matched)
        if matched:
            feature_hits.append(
                _make_feature_hit(
                    category="collection",
                    rule=policy.collection,
                    reason=policy.reason,
                    matched_terms=matched,
                    metadata={"hits": len(matched), "threshold": policy.min_hits},
                )
            )

    for policy in COLLECTION_POLICIES:
        if scores.get(policy.collection, 0) >= policy.min_hits:
            return policy.collection, policy.reason, scores, feature_hits

    return None, "", scores, feature_hits


def check_temporal_relevance(query_lower: str) -> tuple[str | None, dict[str, Any] | None]:
    """Detect Open-i temporal limitations from policy data."""
    for keyword in sorted(POST_2020_KEYWORDS):
        if keyword in query_lower:
            warning = (
                f"Open-i 索引凍結於 ~2020，查詢含 '{keyword}' 可能找不到相關結果。"
                "較新主題建議用 Europe PMC 全文搜尋"
            )
            hit = _make_feature_hit(
                category="temporal",
                rule="post_2020_keyword",
                reason="查詢命中新近主題詞",
                matched_terms=(keyword,),
            )
            return warning, hit

    year_match = YEAR_PATTERN.search(query_lower)
    if year_match:
        year = year_match.group(1)
        warning = f"Open-i 索引凍結於 ~2020，查詢含 '{year}' 年份的文獻可能尚未索引"
        hit = _make_feature_hit(
            category="temporal",
            rule="recent_year",
            reason="查詢命中新年份",
            matched_terms=(year,),
        )
        return warning, hit

    return None, None


def enhance_query(query_lower: str) -> tuple[str, list[dict[str, Any]]]:
    """Remove non-image noise terms and report what was removed."""
    enhanced = query_lower
    feature_hits: list[dict[str, Any]] = []

    for rule in QUERY_CLEANUP_RULES:
        matches = tuple(dict.fromkeys(match.group(0) for match in rule.pattern.finditer(enhanced)))
        if matches:
            feature_hits.append(
                _make_feature_hit(
                    category="enhancement",
                    rule=rule.name,
                    reason="移除可能降低影像搜尋精度的噪音詞",
                    matched_terms=matches,
                )
            )
        enhanced = rule.pattern.sub("", enhanced)

    enhanced = re.sub(r"\s+", " ", enhanced).strip()
    return enhanced or query_lower, feature_hits


def build_diagnostics(
    *,
    suitability_score: float,
    suitability_hits: list[dict[str, Any]],
    image_type_scores: dict[str, int],
    image_type_hits: list[dict[str, Any]],
    collection_scores: dict[str, int],
    collection_hits: list[dict[str, Any]],
    temporal_hit: dict[str, Any] | None,
    enhancement_hits: list[dict[str, Any]],
    non_english_info: dict[str, Any],
    explicit_image_type: str | None,
    recommended_type: str | None,
) -> dict[str, Any]:
    """Assemble a stable diagnostics payload for downstream consumers."""
    feature_hits = [*suitability_hits, *image_type_hits, *collection_hits]
    if temporal_hit is not None:
        feature_hits.append(temporal_hit)
    feature_hits.extend(enhancement_hits)

    if non_english_info.get("is_non_english"):
        feature_hits.append(
            _make_feature_hit(
                category="language",
                rule="non_english_query",
                reason="Open-i 需要英文醫學術語查詢",
                metadata={"detected_script": non_english_info.get("detected_script", "Unknown")},
            )
        )

    if explicit_image_type and recommended_type and explicit_image_type != recommended_type:
        feature_hits.append(
            _make_feature_hit(
                category="validation",
                rule="image_type_mismatch",
                reason="顯式 image_type 與查詢語意不一致",
                matched_terms=(explicit_image_type, recommended_type),
            )
        )

    return {
        "suitability_score": round(suitability_score, 3),
        "suitability_threshold": SUITABILITY_THRESHOLD,
        "image_type_scores": image_type_scores,
        "collection_scores": collection_scores,
        "feature_hits": feature_hits,
        "non_english": non_english_info if non_english_info.get("is_non_english") else None,
    }
