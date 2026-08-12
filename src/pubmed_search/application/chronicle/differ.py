"""Revision deltas between two chronicle snapshots.

A chronicle is only useful over time if you can see what changed. The differ
reports scope, entry, evidence-role, and branch-structure changes so an agent
can explain what is new without mistaking a changed search scope for retirement.
"""

from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING, Any

from .ordering import chronology_key

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pubmed_search.domain.entities.chronicle import (
        ChronicleBranch,
        ChronicleEntry,
        ChronicleSnapshot,
        EvidenceArticle,
        EvidenceBundle,
    )


def _normalize_topic(topic: str) -> str:
    """Return a normalization key suitable for continuity checks."""
    return " ".join(unicodedata.normalize("NFC", topic).split()).casefold()


def _mapping_changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return deterministic field-level changes between JSON-ready mappings."""
    return {
        key: {"from": before.get(key), "to": after.get(key)}
        for key in sorted(before.keys() | after.keys())
        if before.get(key) != after.get(key)
    }


def _evidence_roles(bundle: EvidenceBundle) -> dict[str, list[EvidenceArticle]]:
    """Return evidence articles keyed by their semantic role."""
    return {
        "supporting": bundle.supporting_articles,
        "contradicting": bundle.contradicting_articles,
        "updating": bundle.updating_articles,
    }


def _article_index(articles: Iterable[EvidenceArticle]) -> dict[str, EvidenceArticle]:
    """Index evidence articles by stable identifier."""
    return {article.evidence_id: article for article in articles}


def _article_updates(
    before: dict[str, EvidenceArticle],
    after: dict[str, EvidenceArticle],
) -> list[dict[str, Any]]:
    """Return metadata changes for evidence IDs present on both sides."""
    updates: list[dict[str, Any]] = []
    for evidence_id in sorted(before.keys() & after.keys()):
        changes = _mapping_changes(before[evidence_id].to_dict(), after[evidence_id].to_dict())
        if changes:
            updates.append({"evidence_id": evidence_id, "changes": changes})
    return updates


def _evidence_changes(before: EvidenceBundle, after: EvidenceBundle) -> dict[str, Any]:
    """Return union, role, article metadata, and bundle metadata changes."""
    before_roles = {role: _article_index(articles) for role, articles in _evidence_roles(before).items()}
    after_roles = {role: _article_index(articles) for role, articles in _evidence_roles(after).items()}
    before_all = _article_index(before.all_articles)
    after_all = _article_index(after.all_articles)

    role_deltas: dict[str, Any] = {}
    for role in _evidence_roles(before):
        before_role = before_roles[role]
        after_role = after_roles[role]
        updated = _article_updates(before_role, after_role)
        added_ids = sorted(after_role.keys() - before_role.keys())
        removed_ids = sorted(before_role.keys() - after_role.keys())
        if added_ids or removed_ids or updated:
            role_deltas[role] = {
                "added": added_ids,
                "removed": removed_ids,
                "added_articles": [after_role[evidence_id].to_dict() for evidence_id in added_ids],
                "removed_articles": [before_role[evidence_id].to_dict() for evidence_id in removed_ids],
                "updated": updated,
            }

    role_changes: list[dict[str, Any]] = []
    for evidence_id in sorted(before_all.keys() & after_all.keys()):
        roles_before = sorted(role for role, articles in before_roles.items() if evidence_id in articles)
        roles_after = sorted(role for role, articles in after_roles.items() if evidence_id in articles)
        if roles_before != roles_after:
            role_changes.append(
                {
                    "evidence_id": evidence_id,
                    "from": roles_before,
                    "to": roles_after,
                }
            )

    bundle_before = {
        "verification_summary": before.verification_summary,
        "source_coverage": before.source_coverage,
    }
    bundle_after = {
        "verification_summary": after.verification_summary,
        "source_coverage": after.source_coverage,
    }
    bundle_changes = _mapping_changes(bundle_before, bundle_after)
    added = sorted(after_all.keys() - before_all.keys())
    removed = sorted(before_all.keys() - after_all.keys())
    metadata_updates = _article_updates(before_all, after_all)

    if not (added or removed or role_deltas or role_changes or metadata_updates or bundle_changes):
        return {}
    return {
        # Preserve the original union-level keys for existing consumers.
        "added": added,
        "removed": removed,
        "roles": role_deltas,
        "role_changes": role_changes,
        "updated": metadata_updates,
        "bundle_metadata": bundle_changes,
    }


def _entry_summary(entry: ChronicleEntry) -> dict[str, Any]:
    """Return the compact entry shape used inside delta reports."""
    role_articles = _evidence_roles(entry.evidence)
    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "year": entry.year,
        "time_start": entry.time_start,
        "time_end": entry.time_end,
        "entry_type": entry.entry_type.value,
        "status": entry.status.value,
        "branch_id": entry.branch_id,
        "evidence_ids": sorted({article.evidence_id for article in entry.evidence.all_articles}),
        "evidence_by_role": {
            role: sorted(article.evidence_id for article in articles) for role, articles in role_articles.items()
        },
    }


def _entry_changes(before: ChronicleEntry, after: ChronicleEntry) -> dict[str, Any]:
    """Return all material field-level changes for one stable entry ID."""
    before_fields = {
        "title": before.title,
        "time_start": before.time_start,
        "time_end": before.time_end,
        "summary_claim": before.summary_claim,
        "entry_type": before.entry_type.value,
        "status": before.status.value,
        "branch_id": before.branch_id,
        "confidence": round(before.confidence, 3),
        "tags": list(before.tags),
        "provenance": before.provenance,
    }
    after_fields = {
        "title": after.title,
        "time_start": after.time_start,
        "time_end": after.time_end,
        "summary_claim": after.summary_claim,
        "entry_type": after.entry_type.value,
        "status": after.status.value,
        "branch_id": after.branch_id,
        "confidence": round(after.confidence, 3),
        "tags": list(after.tags),
        "provenance": after.provenance,
    }
    changes: dict[str, Any] = _mapping_changes(before_fields, after_fields)
    evidence_changes = _evidence_changes(before.evidence, after.evidence)
    if evidence_changes:
        changes["evidence"] = evidence_changes
    return changes


def _branch_summary(branch: ChronicleBranch) -> dict[str, Any]:
    """Return the complete branch structure used in delta details."""
    return branch.to_dict()


def _branch_changes(before: ChronicleBranch, after: ChronicleBranch) -> dict[str, Any]:
    """Return changes in branch labels, ancestry, membership, and confidence."""
    before_fields = before.to_dict()
    after_fields = after.to_dict()
    before_fields.pop("branch_id", None)
    after_fields.pop("branch_id", None)
    return _mapping_changes(before_fields, after_fields)


def diff_chronicles(before: ChronicleSnapshot, after: ChronicleSnapshot) -> dict[str, Any]:
    """Compare two forward revisions of the same continuous chronicle.

    Args:
        before: The earlier revision.
        after: The later revision.

    Returns:
        A JSON-ready delta report describing scope, entries, evidence roles and
        metadata, branch structure, and the audit status transition.

    Raises:
        ValueError: If identity/topic continuity fails or revisions are not
            strictly increasing.
    """
    if before.chronicle_id != after.chronicle_id:
        msg = f"Cannot diff different chronicles: {before.chronicle_id} vs {after.chronicle_id}"
        raise ValueError(msg)
    if _normalize_topic(before.topic) != _normalize_topic(after.topic):
        msg = f"Cannot diff a topic discontinuity: {before.topic!r} vs {after.topic!r}"
        raise ValueError(msg)
    if before.revision >= after.revision:
        msg = f"Chronicle diffs must be forward and strictly increasing: revision {before.revision} -> {after.revision}"
        raise ValueError(msg)

    before_scope = before.input_scope.to_dict()
    after_scope = after.input_scope.to_dict()
    scope_changes = _mapping_changes(before_scope, after_scope)
    scope_changed = bool(scope_changes)

    before_index = before.entry_index
    after_index = after.entry_index
    added_ids = after_index.keys() - before_index.keys()
    retired_ids = before_index.keys() - after_index.keys()
    added = [_entry_summary(after_index[key]) for key in added_ids]
    retired = [_entry_summary(before_index[key]) for key in retired_ids]

    updated: list[dict[str, Any]] = []
    for key in before_index.keys() & after_index.keys():
        changes = _entry_changes(before_index[key], after_index[key])
        if changes:
            updated.append({"entry_id": key, "title": after_index[key].title, "changes": changes})

    added.sort(key=lambda item: chronology_key(item["time_start"]))
    retired.sort(key=lambda item: chronology_key(item["time_start"]))
    updated.sort(key=lambda item: item["entry_id"])

    before_branches = {branch.branch_id: branch for branch in before.branches}
    after_branches = {branch.branch_id: branch for branch in after.branches}
    added_branch_ids = sorted(after_branches.keys() - before_branches.keys())
    removed_branch_ids = sorted(before_branches.keys() - after_branches.keys())
    updated_branches: list[dict[str, Any]] = []
    for branch_id in sorted(before_branches.keys() & after_branches.keys()):
        changes = _branch_changes(before_branches[branch_id], after_branches[branch_id])
        if changes:
            updated_branches.append(
                {
                    "branch_id": branch_id,
                    "name": after_branches[branch_id].name,
                    "changes": changes,
                }
            )

    before_evidence = _article_index(before.evidence_articles)
    after_evidence = _article_index(after.evidence_articles)
    added_evidence_ids = sorted(after_evidence.keys() - before_evidence.keys())
    removed_evidence_ids = sorted(before_evidence.keys() - after_evidence.keys())
    evidence_updates = _article_updates(before_evidence, after_evidence)

    scope_note = (
        "Input scope changed; added or missing entries may reflect retrieval scope rather than a research-state change."
        if scope_changed
        else (
            "Input parameters are unchanged, but the ranked/capped source result can still change as PubMed indexing, "
            "citation metrics, and ranking evolve. Absence is not evidence of retirement."
        )
    )
    return {
        "chronicle_id": after.chronicle_id,
        "topic": after.topic,
        "from_revision": before.revision,
        "to_revision": after.revision,
        "scope_changed": scope_changed,
        "scope": {
            "changed": scope_changed,
            "from": before_scope,
            "to": after_scope,
            "changes": scope_changes,
        },
        "interpretation": {
            "scope_changed": scope_changed,
            "retired_entries_are_conclusive": False,
            "absence_semantics": "not_observed_in_revision",
            "note": scope_note,
        },
        "entries": {
            "added": added,
            # Kept for backward compatibility. Consult scope_changed before
            # interpreting absence as true retirement from the research line.
            "retired": retired,
            "removed_from_view": retired,
            "not_observed_in_revision": retired,
            "updated": updated,
            "unchanged": len(before_index.keys() & after_index.keys()) - len(updated),
        },
        "branches": {
            "added": added_branch_ids,
            "removed": removed_branch_ids,
            "added_details": [_branch_summary(after_branches[key]) for key in added_branch_ids],
            "removed_details": [_branch_summary(before_branches[key]) for key in removed_branch_ids],
            "updated": updated_branches,
        },
        "evidence": {
            "added": added_evidence_ids,
            "removed": removed_evidence_ids,
            "added_details": [after_evidence[key].to_dict() for key in added_evidence_ids],
            "removed_details": [before_evidence[key].to_dict() for key in removed_evidence_ids],
            "updated": evidence_updates,
            "total_before": len(before_evidence),
            "total_after": len(after_evidence),
        },
        "audit": {"from": before.audit.status, "to": after.audit.status},
        "unresolved_warnings": after.audit.warnings,
    }


__all__ = ["diff_chronicles"]
