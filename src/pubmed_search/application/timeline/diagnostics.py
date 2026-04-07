"""
Diagnostics builders for research timeline workflows.

Transforms per-event milestone and landmark explainability into a stable,
presentation-friendly timeline diagnostics payload.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pubmed_search.domain.entities.timeline import TimelineEvent


def build_timeline_diagnostics(
    events: list[TimelineEvent],
    *,
    source: str,
    retrieved_count: int,
    filtered_count: int,
    candidate_count: int,
    include_all: bool,
    highlight_landmarks: bool,
) -> dict[str, Any]:
    """Assemble a stable diagnostics payload for timeline outputs."""
    strategy_counts: Counter[str] = Counter()
    policy_counts: Counter[str] = Counter()
    sample_matches: list[dict[str, Any]] = []
    component_usage: Counter[str] = Counter()

    landmark_count = 0
    notable_count = 0

    for event in events:
        detection = _event_detection(event)
        strategy = detection.get("strategy")
        policy = detection.get("policy")
        if isinstance(strategy, str):
            strategy_counts[strategy] += 1
        if isinstance(policy, str):
            policy_counts[policy] += 1
        if detection and len(sample_matches) < 5:
            sample = {
                "pmid": event.pmid,
                "label": event.milestone_label,
                "strategy": strategy,
                "policy": policy,
            }
            matched_value = detection.get("matched_value")
            if isinstance(matched_value, str) and matched_value:
                sample["matched_value"] = matched_value
            sample_matches.append(sample)

        score = event.landmark_score
        if not score:
            continue
        if score.tier == "landmark":
            landmark_count += 1
        if score.overall >= 0.5:
            notable_count += 1

        diagnostics = score.diagnostics or {}
        component_hits = diagnostics.get("component_hits", [])
        if isinstance(component_hits, list):
            for hit in component_hits:
                if not isinstance(hit, dict):
                    continue
                component = hit.get("component")
                weighted_score = hit.get("weighted_score", 0)
                if isinstance(component, str) and weighted_score:
                    component_usage[component] += 1

    return {
        "search": {
            "source": source,
            "retrieved_articles": retrieved_count,
            "articles_after_filters": filtered_count,
            "milestone_candidates": candidate_count,
            "events_emitted": len(events),
            "include_all": include_all,
        },
        "milestone_detection": {
            "strategy_counts": dict(sorted(strategy_counts.items())),
            "top_policies": _top_counts(policy_counts),
            "sample_matches": sample_matches,
        },
        "landmark_scoring": {
            "enabled": highlight_landmarks,
            "landmarks_detected": landmark_count,
            "notable_or_higher": notable_count,
            "component_usage": dict(sorted(component_usage.items())),
        },
    }


def _event_detection(event: TimelineEvent) -> dict[str, Any]:
    metadata = event.metadata or {}
    detection = metadata.get("milestone_detection", {})
    return detection if isinstance(detection, dict) else {}


def _top_counts(counter: Counter[str], limit: int = 5) -> list[dict[str, Any]]:
    items = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [{"policy": policy, "count": count} for policy, count in items[:limit]]
