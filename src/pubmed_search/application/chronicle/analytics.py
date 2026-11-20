"""Analytics projections over stored chronicle revisions.

These replace the standalone timeline analysis tools. Because chronicles are
persisted, analysis and comparison read stored snapshots instead of re-running a
search every time, and comparison can additionally report *shared evidence*
between topics - something a per-call timeline could never do.
"""

from __future__ import annotations

import math
from statistics import median
from typing import TYPE_CHECKING, Any

from pubmed_search.domain.entities.chronicle import resolve_chronicle_membership

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
    except (TypeError, ValueError, OverflowError):
        return None
    return score if math.isfinite(score) and 0.0 <= score <= 1.0 else None


def _maximum_stored_citations(entry: ChronicleEntry) -> int | None:
    counts = (article.citation_count for article in entry.evidence.all_articles)
    return max((n for n in counts if isinstance(n, int) and not isinstance(n, bool) and n >= 0), default=None)


def entry_max_citations(entry: ChronicleEntry) -> int:
    """Retain the numeric zero fallback used in historical ranking keys."""
    return _maximum_stored_citations(entry) or 0


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


def _recorded_score_components(entry: ChronicleEntry) -> list[dict[str, Any]] | None:
    """Expose the original scoring inputs when this revision retained them."""
    score = entry.provenance.get("landmark_score")
    diagnostics = score.get("diagnostics") if isinstance(score, dict) else None
    hits = diagnostics.get("component_hits") if isinstance(diagnostics, dict) else None
    if not isinstance(hits, list) or landmark_importance_score(entry) is None:
        return None
    components = []
    for hit in hits:
        if (
            not isinstance(hit, dict)
            or not isinstance(hit.get("component"), str)
            or not isinstance(hit.get("policy"), str)
        ):
            continue
        components.append(
            {
                "component": hit["component"],
                "policy": hit["policy"],
                # The scorer gives unavailable citation inputs a zero contribution.
                "raw_value": None if hit["policy"] == "none" else hit.get("raw_value"),
                "weight": hit.get("weight"),
                "weighted_score": hit.get("weighted_score"),
            }
        )
    return components or None


def _observed_max_citations(entry: ChronicleEntry, components: list[dict[str, Any]] | None) -> int | None:
    maximum = _maximum_stored_citations(entry)
    if maximum != 0 or entry.provenance.get("citation_count_observed") is True:
        return maximum
    # Earlier timeline events defaulted missing counts to zero. A retained
    # zero-valued citation-count input is independent evidence for a real zero.
    if any(
        hit["component"] == "citation_impact" and hit["policy"] == "citation_count" and hit["raw_value"] == 0
        for hit in components or []
    ):
        return 0
    return None


def _landmark_row(entry: ChronicleEntry) -> dict[str, Any]:
    importance = landmark_importance_score(entry)
    components = _recorded_score_components(entry)
    observed = _observed_max_citations(entry, components)
    selection_signal = "chronological_display_order_then_entry_id"
    if importance is not None:
        selection_signal = "landmark_importance_score"
    elif observed:
        selection_signal = "citation_count"
    return {
        "entry_id": entry.entry_id,
        "year": entry.year,
        "title": entry.title,
        "landmark_importance_score": importance,
        "score_components": components,
        "ranking_basis": "provenance.landmark_importance_score"
        if importance is not None
        else "citation_count_fallback",
        "selection_signal": selection_signal,
        "milestone_detection_confidence": round(entry.confidence, 3),
        "confidence_semantics": "milestone_detection_confidence_not_scientific_importance",
        "citations": entry_max_citations(entry),
        "observed_max_citations": observed,
        "evidence_ids": [article.evidence_id for article in entry.evidence.all_articles],
    }


def _branch_representatives(snapshot: ChronicleSnapshot, global_ids: set[str]) -> list[dict[str, Any]]:
    membership = resolve_chronicle_membership(snapshot)
    rows = []
    for branch_index, member_indices in enumerate(membership.branch_entry_indices):
        members = (snapshot.entries[i] for i in member_indices)
        ranked = sorted((member for member in members if not member.evidence.is_empty), key=landmark_rank_key)
        if not ranked:
            continue
        branch = snapshot.branches[branch_index]
        entry = ranked[0]
        basis = "sole_direct_entry"
        if len(ranked) > 1:
            first, second = landmark_rank_key(entry), landmark_rank_key(ranked[1])
            if first[:2] != second[:2]:
                basis = "landmark_importance_score"
            elif first[2] != second[2]:
                basis = "citation_count"
            else:
                basis = "chronological_display_order_then_entry_id"
        rows.append(
            {
                "branch_index": branch_index,
                "branch_id": branch.branch_id,
                "branch_name": branch.name,
                "entry_id": entry.entry_id,
                "year": entry.year,
                "evidence_ids": [article.evidence_id for article in entry.evidence.all_articles],
                "observed_max_citations": _observed_max_citations(entry, _recorded_score_components(entry)),
                "selection_basis": basis,
                "in_global_landmarks": entry.entry_id in global_ids,
            }
        )
    return rows


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
            "median_citations": median(citations) if citations else None,
            "source_distribution": _distribution([a.source for a in articles]),
        },
        "landmark_entries": [_landmark_row(entry) for entry in landmarks],
        "branch_representatives": _branch_representatives(snapshot, {entry.entry_id for entry in landmarks}),
        "landmark_ranking": {
            "primary": "provenance.landmark_importance_score",
            "fallback": "maximum evidence citation_count when importance is unavailable",
            "excluded": "milestone detection confidence",
            "scope": "entries_in_this_revision",
            "branch_representatives": (
                "One reading sample per branch with evidence-backed, resolved direct members. Selection basis gives the final "
                "criterion over the next ranked member. Historical influence requires separate evidence."
            ),
            "tie_breakers": ["maximum evidence citation_count", "chronological display order", "entry_id"],
            "interpretation": (
                "These are candidates for historical review. A composite can include milestone detection confidence "
                "as a weighted input. Database agreement measures retrieval overlap. Missing citation counts can "
                "rank as zero. Citation metrics describe the available snapshot. Contemporary reception requires dated evidence."
            ),
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
