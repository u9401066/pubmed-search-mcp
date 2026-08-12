"""Analytics projections over stored chronicle revisions.

These replace the standalone timeline analysis tools. Because chronicles are
persisted, analysis and comparison read stored snapshots instead of re-running a
search every time, and comparison can additionally report *shared evidence*
between topics - something a per-call timeline could never do.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from .ordering import chronology_key

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pubmed_search.domain.entities.chronicle import ChronicleEntry, ChronicleSnapshot

#: How many landmark entries the milestone analysis reports.
LANDMARK_LIMIT = 5


def landmark_importance_score(entry: ChronicleEntry) -> float | None:
    """Return a validated scientific-importance score from provenance.

    ``ChronicleEntry.confidence`` is milestone *detection* confidence. It must
    never be reused as evidence that an entry is scientifically important.
    """
    raw_score = entry.provenance.get("landmark_importance_score")
    if raw_score is None or isinstance(raw_score, bool):
        return None
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        return None
    return score if math.isfinite(score) and 0.0 <= score <= 1.0 else None


def entry_max_citations(entry: ChronicleEntry) -> int:
    """Return the largest non-negative citation count in an entry's evidence."""
    counts = [article.citation_count for article in entry.evidence.all_articles]
    return max((count for count in counts if count is not None and count >= 0), default=0)


def landmark_rank_key(entry: ChronicleEntry) -> tuple[int, float, int, tuple[int, int, int, int, int], str]:
    """Sort by explicit landmark importance, with citations as fallback.

    Entries carrying a valid ``provenance.landmark_importance_score`` are ranked
    together by that score. Entries without one form a fallback tier ranked by
    citations. Detection confidence is intentionally absent from this key.
    """
    importance = landmark_importance_score(entry)
    citations = entry_max_citations(entry)
    return (
        0 if importance is not None else 1,
        -(importance or 0.0),
        -citations,
        chronology_key(entry),
        entry.entry_id,
    )


def _activity_by_year(snapshot: ChronicleSnapshot) -> dict[str, int]:
    """Count entries per year, ascending."""
    activity: dict[int, int] = {}
    for entry in snapshot.entries:
        if entry.year is not None:
            activity[entry.year] = activity.get(entry.year, 0) + 1
    return {str(year): count for year, count in sorted(activity.items())}


def _distribution(values: Sequence[str]) -> dict[str, int]:
    """Count occurrences of each value, ordered from most to least common."""
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _entry_digest(snapshot: ChronicleSnapshot, *, newest: bool) -> dict[str, Any] | None:
    """Return the earliest or latest entry as a compact dict."""
    dated = [entry for entry in snapshot.entries if entry.year is not None]
    if not dated:
        return None
    ordered = sorted(dated, key=chronology_key)
    entry = ordered[-1] if newest else ordered[0]
    return {
        "entry_id": entry.entry_id,
        "year": entry.year,
        "title": entry.title,
        "entry_type": entry.entry_type.value,
        "summary_claim": entry.summary_claim,
    }


def analyze_milestones(snapshot: ChronicleSnapshot) -> dict[str, Any]:
    """Summarize how milestones are distributed across a chronicle revision.

    Args:
        snapshot: The chronicle revision to analyze.

    Returns:
        A JSON-ready dict with entry-type and status distributions, per-year
        activity, branch coverage, evidence quality, landmark entries, and the
        audit status carried over from the snapshot.
    """
    articles = snapshot.evidence_articles
    citations = [a.citation_count for a in articles if a.citation_count is not None]
    year_range = snapshot.year_range

    landmarks = sorted(snapshot.entries, key=landmark_rank_key)[:LANDMARK_LIMIT]

    return {
        "projection": "milestones",
        "chronicle_id": snapshot.chronicle_id,
        "revision": snapshot.revision,
        "topic": snapshot.topic,
        "total_entries": len(snapshot.entries),
        "year_range": list(year_range) if year_range else None,
        "duration_years": (year_range[1] - year_range[0] + 1) if year_range else 0,
        "entry_type_distribution": _distribution([entry.entry_type.value for entry in snapshot.entries]),
        "status_distribution": _distribution([entry.status.value for entry in snapshot.entries]),
        "activity_by_year": _activity_by_year(snapshot),
        "branches": [
            {"branch_id": branch.branch_id, "name": branch.name, "entry_count": len(branch.entry_ids)}
            for branch in snapshot.branches
        ],
        "evidence_quality": {
            "total_articles": len(articles),
            "with_identifier": sum(1 for a in articles if a.has_identifier),
            "with_year": sum(1 for a in articles if a.year is not None),
            "with_citation_count": len(citations),
            "max_citations": max(citations) if citations else None,
            "median_citations": sorted(citations)[len(citations) // 2] if citations else None,
            "source_distribution": _distribution([a.source for a in articles]),
        },
        "landmark_entries": [
            {
                "entry_id": entry.entry_id,
                "year": entry.year,
                "title": entry.title,
                "landmark_importance_score": landmark_importance_score(entry),
                "ranking_basis": (
                    "provenance.landmark_importance_score"
                    if landmark_importance_score(entry) is not None
                    else "citation_count_fallback"
                ),
                "milestone_detection_confidence": round(entry.confidence, 3),
                "confidence_semantics": "milestone_detection_confidence_not_scientific_importance",
                "citations": entry_max_citations(entry),
                "evidence_ids": [a.evidence_id for a in entry.evidence.all_articles],
            }
            for entry in landmarks
        ],
        "landmark_ranking": {
            "primary": "provenance.landmark_importance_score",
            "fallback": "maximum evidence citation_count when importance is unavailable",
            "excluded": "milestone detection confidence",
        },
        "audit_status": snapshot.audit.status,
        "warnings": snapshot.audit.warnings,
    }


def compare_chronicles(snapshots: Sequence[ChronicleSnapshot]) -> dict[str, Any]:
    """Compare several chronicles side by side.

    Args:
        snapshots: Two or more chronicle revisions, one per topic.

    Returns:
        A JSON-ready dict with per-chronicle digests, cross-topic superlatives,
        and the evidence articles shared by more than one chronicle.

    Raises:
        ValueError: If fewer than two snapshots are supplied.
    """
    if len(snapshots) < 2:
        msg = "Need at least 2 chronicles to compare."
        raise ValueError(msg)

    entries: list[dict[str, Any]] = []
    evidence_owners: dict[str, list[str]] = {}

    for snapshot in snapshots:
        year_range = snapshot.year_range
        entries.append(
            {
                "chronicle_id": snapshot.chronicle_id,
                "topic": snapshot.topic,
                "revision": snapshot.revision,
                "total_entries": len(snapshot.entries),
                "evidence_articles": len(snapshot.evidence_articles),
                "year_range": list(year_range) if year_range else None,
                "duration_years": (year_range[1] - year_range[0] + 1) if year_range else 0,
                "entry_type_distribution": _distribution([entry.entry_type.value for entry in snapshot.entries]),
                "branch_names": [branch.name for branch in snapshot.branches if branch.entry_ids],
                "first_entry": _entry_digest(snapshot, newest=False),
                "latest_entry": _entry_digest(snapshot, newest=True),
                "audit_status": snapshot.audit.status,
            }
        )
        for article in snapshot.evidence_articles:
            evidence_owners.setdefault(article.evidence_id, []).append(snapshot.topic)

    shared_evidence = [
        {"evidence_id": evidence_id, "shared_by": sorted(set(topics))}
        for evidence_id, topics in evidence_owners.items()
        if len(set(topics)) > 1
    ]
    shared_evidence.sort(key=lambda item: (-len(item["shared_by"]), item["evidence_id"]))

    dated = [item for item in entries if item["year_range"]]
    return {
        "projection": "comparison",
        "chronicles": entries,
        "summary": {
            "earliest_research": min((item["year_range"][0] for item in dated), default=None),
            "latest_research": max((item["year_range"][1] for item in dated), default=None),
            "most_entries": max(entries, key=lambda item: item["total_entries"])["topic"],
            "longest_span": max(entries, key=lambda item: item["duration_years"])["topic"],
            "shared_evidence_count": len(shared_evidence),
        },
        "shared_evidence": shared_evidence,
    }


__all__ = [
    "LANDMARK_LIMIT",
    "analyze_milestones",
    "compare_chronicles",
    "entry_max_citations",
    "landmark_importance_score",
    "landmark_rank_key",
]
