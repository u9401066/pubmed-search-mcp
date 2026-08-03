"""Assemble chronicle snapshots from timeline evidence.

The assembler is the only place that knows how to translate the existing
timeline/lineage-tree model into the chronicle source of truth. Keeping the
mapping here means the projectors, narrator, differ, and audit all read a single
consistent structure.
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Any

from pubmed_search.domain.entities.chronicle import (
    ChronicleBranch,
    ChronicleEntry,
    ChronicleEntryStatus,
    ChronicleEntryType,
    ChronicleInputScope,
    ChronicleSnapshot,
    EvidenceArticle,
    EvidenceBundle,
    utc_now_iso,
)
from pubmed_search.domain.entities.timeline import MilestoneType

from .graph import build_chronicle_graph

if TYPE_CHECKING:
    from pubmed_search.domain.entities.research_tree import ResearchBranch, ResearchTree
    from pubmed_search.domain.entities.timeline import ResearchTimeline, TimelineEvent

#: Milestone types that map onto a non-default chronicle entry type.
_MILESTONE_TO_ENTRY_TYPE: dict[MilestoneType, ChronicleEntryType] = {
    MilestoneType.GUIDELINE: ChronicleEntryType.GUIDELINE,
    MilestoneType.CONSENSUS: ChronicleEntryType.GUIDELINE,
    MilestoneType.SAFETY_ALERT: ChronicleEntryType.SAFETY,
    MilestoneType.WITHDRAWAL: ChronicleEntryType.SAFETY,
    MilestoneType.LABEL_UPDATE: ChronicleEntryType.SAFETY,
    MilestoneType.META_ANALYSIS: ChronicleEntryType.EVIDENCE_SHIFT,
    MilestoneType.SYSTEMATIC_REVIEW: ChronicleEntryType.EVIDENCE_SHIFT,
    MilestoneType.CONTROVERSY: ChronicleEntryType.CONTROVERSY,
    MilestoneType.MECHANISM_DISCOVERY: ChronicleEntryType.METHOD,
    MilestoneType.PRECLINICAL: ChronicleEntryType.METHOD,
    MilestoneType.OTHER: ChronicleEntryType.BACKGROUND,
}

#: Human-readable claim templates keyed by chronicle entry type.
_CLAIM_TEMPLATES: dict[ChronicleEntryType, str] = {
    ChronicleEntryType.MILESTONE: "{year}: {label} for {topic}, evidenced by {citation}.",
    ChronicleEntryType.EVIDENCE_SHIFT: "{year}: evidence synthesis ({label}) reframed {topic}, per {citation}.",
    ChronicleEntryType.GUIDELINE: "{year}: guidance ({label}) codified practice for {topic}, per {citation}.",
    ChronicleEntryType.SAFETY: "{year}: a safety signal ({label}) was reported for {topic} in {citation}.",
    ChronicleEntryType.METHOD: "{year}: a methodological advance ({label}) was reported for {topic} in {citation}.",
    ChronicleEntryType.CONTROVERSY: "{year}: {label} became contested for {topic}, see {citation}.",
    ChronicleEntryType.BACKGROUND: "{year}: background work on {topic} reported in {citation}.",
}


def _slugify(value: str) -> str:
    """Return a lowercase, hyphen-separated slug for *value*."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:60] or "chronicle"


def derive_chronicle_id(topic: str, scope_key: str = "") -> str:
    """Return a stable chronicle identifier for *topic*.

    The same topic (and optional scope discriminator) always maps to the same
    chronicle so later runs create new revisions instead of new chronicles.

    Args:
        topic: Research topic label.
        scope_key: Optional discriminator, e.g. a serialized filter set.

    Returns:
        A slug plus short digest, e.g. ``remimazolam-9f2b1c4d``.
    """
    digest = hashlib.sha256(f"{topic.strip().lower()}|{scope_key}".encode()).hexdigest()[:8]
    return f"{_slugify(topic)}-{digest}"


def _derive_entry_id(chronicle_id: str, event: TimelineEvent) -> str:
    """Return a revision-stable entry ID for *event*."""
    seed = f"{chronicle_id}|{event.pmid}|{event.milestone_type.value}|{event.year}"
    return f"entry-{hashlib.sha256(seed.encode()).hexdigest()[:12]}"


def _entry_type_for(event: TimelineEvent) -> ChronicleEntryType:
    """Map a timeline milestone type onto a chronicle entry type."""
    return _MILESTONE_TO_ENTRY_TYPE.get(event.milestone_type, ChronicleEntryType.MILESTONE)


def _citation_label(article: EvidenceArticle) -> str:
    """Return a compact inline citation label for *article*."""
    if article.pmid:
        return f"PMID:{article.pmid}"
    if article.doi:
        return f"DOI:{article.doi}"
    return article.title[:60]


def _build_evidence_article(event: TimelineEvent) -> EvidenceArticle:
    """Convert a timeline event's source article into evidence."""
    metadata = event.metadata if isinstance(event.metadata, dict) else {}
    landmark = event.landmark_score
    rcr = None
    if landmark is not None and isinstance(landmark.diagnostics, dict):
        raw_rcr = landmark.diagnostics.get("rcr")
        if isinstance(raw_rcr, (int, float)):
            rcr = float(raw_rcr)

    return EvidenceArticle(
        title=event.title,
        pmid=event.pmid or None,
        doi=event.doi,
        pmcid=metadata.get("pmcid"),
        year=event.year,
        source=str(metadata.get("source") or "pubmed"),
        journal=event.journal,
        article_type=metadata.get("publication_type") or event.milestone_label,
        citation_count=event.citation_count or None,
        rcr=rcr,
        claim_excerpt=event.description,
    )


def _build_summary_claim(topic: str, event: TimelineEvent, article: EvidenceArticle) -> str:
    """Render the one-sentence, citation-bearing claim for an entry."""
    entry_type = _entry_type_for(event)
    template = _CLAIM_TEMPLATES[entry_type]
    return template.format(
        year=event.year,
        label=event.milestone_label,
        topic=topic,
        citation=_citation_label(article),
    )


def _flatten_tree_branches(tree: ResearchTree | None) -> list[tuple[ResearchBranch, str | None]]:
    """Flatten a research tree into ``(branch, parent_branch_id)`` pairs."""
    if tree is None:
        return []

    flattened: list[tuple[ResearchBranch, str | None]] = []

    def _walk(branch: ResearchBranch, parent_id: str | None) -> None:
        flattened.append((branch, parent_id))
        for sub_branch in getattr(branch, "sub_branches", []) or []:
            _walk(sub_branch, branch.branch_id)

    for branch in tree.branches:
        _walk(branch, None)
    return flattened


def _entry_status(event: TimelineEvent, entry_type: ChronicleEntryType) -> ChronicleEntryStatus:
    """Choose the lifecycle status implied by the event's milestone type."""
    if entry_type is ChronicleEntryType.BACKGROUND:
        return ChronicleEntryStatus.BACKGROUND
    if entry_type is ChronicleEntryType.CONTROVERSY:
        return ChronicleEntryStatus.CONTESTED
    if event.milestone_type is MilestoneType.WITHDRAWAL:
        return ChronicleEntryStatus.SUPERSEDED
    return ChronicleEntryStatus.ACTIVE


def assemble_chronicle(
    *,
    topic: str,
    timeline: ResearchTimeline,
    tree: ResearchTree | None = None,
    scope: ChronicleInputScope | None = None,
    chronicle_id: str | None = None,
    revision: int = 1,
    created_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ChronicleSnapshot:
    """Build a :class:`ChronicleSnapshot` from timeline evidence.

    Args:
        topic: Research topic label used in claims and node labels.
        timeline: Chronologically sorted timeline that supplies the entries.
        tree: Optional lineage tree used to assign entries to branches.
        scope: How this revision was produced. Defaults to a topic-mode scope.
        chronicle_id: Reuse an existing chronicle ID; derived from *topic* when
            omitted.
        revision: Revision number for this snapshot.
        created_at: Creation timestamp of revision 1, preserved across updates.
        metadata: Free-form extras merged into the snapshot metadata.

    Returns:
        A fully populated snapshot with entries, branches, and provenance graph.
        The audit is left empty; run ``audit_chronicle`` to fill it.
    """
    resolved_id = chronicle_id or derive_chronicle_id(topic)
    input_scope = scope or ChronicleInputScope(mode="topic", query=topic)

    entries: list[ChronicleEntry] = []
    entry_by_pmid: dict[str, str] = {}

    for event in timeline.events:
        entry_type = _entry_type_for(event)
        article = _build_evidence_article(event)
        entry_id = _derive_entry_id(resolved_id, event)
        confidence = event.landmark_score.overall if event.landmark_score else event.confidence_score

        entries.append(
            ChronicleEntry(
                entry_id=entry_id,
                entry_type=entry_type,
                title=event.milestone_label or event.title,
                time_start=event.date_label,
                summary_claim=_build_summary_claim(topic, event, article),
                confidence=float(confidence or 0.0),
                status=_entry_status(event, entry_type),
                evidence=EvidenceBundle(
                    supporting_articles=[article],
                    source_coverage={article.source: 1},
                ),
                tags=[event.milestone_type.value, event.evidence_level.value],
                provenance={
                    "milestone_type": event.milestone_type.value,
                    "detection_confidence": event.confidence_score,
                    "landmark_tier": event.landmark_score.tier if event.landmark_score else None,
                },
            )
        )
        if event.pmid:
            entry_by_pmid[event.pmid] = entry_id

    branches: list[ChronicleBranch] = []
    for branch, parent_id in _flatten_tree_branches(tree):
        branch_entry_ids = [
            entry_by_pmid[event.pmid] for event in getattr(branch, "events", []) or [] if event.pmid in entry_by_pmid
        ]
        branches.append(
            ChronicleBranch(
                branch_id=branch.branch_id,
                name=branch.label,
                description=f"{branch.label} research line for {topic}",
                parent_branch_id=parent_id,
                entry_ids=branch_entry_ids,
            )
        )

    branch_by_entry = {entry_id: branch.branch_id for branch in branches for entry_id in branch.entry_ids}
    for entry in entries:
        entry.branch_id = branch_by_entry.get(entry.entry_id)

    timestamp = utc_now_iso()
    snapshot = ChronicleSnapshot(
        chronicle_id=resolved_id,
        topic=topic,
        revision=revision,
        input_scope=input_scope,
        entries=entries,
        branches=branches,
        created_at=created_at or timestamp,
        updated_at=timestamp,
        metadata={
            "total_timeline_events": timeline.total_events,
            "timeline_metadata": timeline.metadata,
            **(metadata or {}),
        },
    )
    snapshot.graph = build_chronicle_graph(snapshot)
    return snapshot


__all__ = ["assemble_chronicle", "derive_chronicle_id"]
