"""Revision deltas between two chronicle snapshots.

A chronicle is only useful over time if you can see what changed. The differ
reports added, retired, and updated entries, plus evidence and branch churn, so
an agent can summarise "what is new since last month" without re-reading both
revisions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pubmed_search.domain.entities.chronicle import ChronicleEntry, ChronicleSnapshot


def _entry_summary(entry: ChronicleEntry) -> dict[str, Any]:
    """Return the compact entry shape used inside delta reports."""
    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "year": entry.year,
        "entry_type": entry.entry_type.value,
        "status": entry.status.value,
        "branch_id": entry.branch_id,
        "evidence_ids": [article.evidence_id for article in entry.evidence.all_articles],
    }


def _entry_changes(before: ChronicleEntry, after: ChronicleEntry) -> dict[str, Any]:
    """Return the field-level changes between two versions of one entry."""
    changes: dict[str, Any] = {}
    if before.status is not after.status:
        changes["status"] = {"from": before.status.value, "to": after.status.value}
    if before.branch_id != after.branch_id:
        changes["branch_id"] = {"from": before.branch_id, "to": after.branch_id}
    if round(before.confidence, 3) != round(after.confidence, 3):
        changes["confidence"] = {"from": round(before.confidence, 3), "to": round(after.confidence, 3)}

    before_evidence = {article.evidence_id for article in before.evidence.all_articles}
    after_evidence = {article.evidence_id for article in after.evidence.all_articles}
    if before_evidence != after_evidence:
        changes["evidence"] = {
            "added": sorted(after_evidence - before_evidence),
            "removed": sorted(before_evidence - after_evidence),
        }
    return changes


def diff_chronicles(before: ChronicleSnapshot, after: ChronicleSnapshot) -> dict[str, Any]:
    """Compare two revisions of the same chronicle.

    Args:
        before: The earlier revision.
        after: The later revision.

    Returns:
        A JSON-ready delta report describing added/retired/updated entries,
        branch churn, evidence churn, and the audit status transition.

    Raises:
        ValueError: If the two snapshots belong to different chronicles.
    """
    if before.chronicle_id != after.chronicle_id:
        msg = f"Cannot diff different chronicles: {before.chronicle_id} vs {after.chronicle_id}"
        raise ValueError(msg)

    before_index = before.entry_index
    after_index = after.entry_index

    added = [_entry_summary(after_index[key]) for key in after_index.keys() - before_index.keys()]
    retired = [_entry_summary(before_index[key]) for key in before_index.keys() - after_index.keys()]

    updated: list[dict[str, Any]] = []
    for key in before_index.keys() & after_index.keys():
        changes = _entry_changes(before_index[key], after_index[key])
        if changes:
            updated.append({"entry_id": key, "title": after_index[key].title, "changes": changes})

    added.sort(key=lambda item: (item["year"] or 0, item["entry_id"]))
    retired.sort(key=lambda item: (item["year"] or 0, item["entry_id"]))
    updated.sort(key=lambda item: item["entry_id"])

    before_branches = {branch.branch_id for branch in before.branches}
    after_branches = {branch.branch_id for branch in after.branches}
    before_evidence = {article.evidence_id for article in before.evidence_articles}
    after_evidence = {article.evidence_id for article in after.evidence_articles}

    return {
        "chronicle_id": after.chronicle_id,
        "topic": after.topic,
        "from_revision": before.revision,
        "to_revision": after.revision,
        "entries": {
            "added": added,
            "retired": retired,
            "updated": updated,
            "unchanged": len(before_index.keys() & after_index.keys()) - len(updated),
        },
        "branches": {
            "added": sorted(after_branches - before_branches),
            "removed": sorted(before_branches - after_branches),
        },
        "evidence": {
            "added": sorted(after_evidence - before_evidence),
            "removed": sorted(before_evidence - after_evidence),
            "total_before": len(before_evidence),
            "total_after": len(after_evidence),
        },
        "audit": {"from": before.audit.status, "to": after.audit.status},
        "unresolved_warnings": after.audit.warnings,
    }


__all__ = ["diff_chronicles"]
