"""Assemble chronicle snapshots from timeline evidence.

The assembler is the only place that knows how to translate the existing
timeline/lineage-tree model into the chronicle source of truth. Keeping the
mapping here means the projectors, narrator, differ, and audit all read a single
consistent structure.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
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
    ChronicleEntryType.MILESTONE: (
        "{year}: a publication categorized as {label} concerning {topic} was indexed ({citation})."
    ),
    ChronicleEntryType.EVIDENCE_SHIFT: (
        "{year}: an evidence-synthesis publication categorized as {label} concerning {topic} was indexed ({citation})."
    ),
    ChronicleEntryType.GUIDELINE: (
        "{year}: a guidance publication categorized as {label} concerning {topic} was indexed ({citation})."
    ),
    ChronicleEntryType.SAFETY: (
        "{year}: a safety-related publication categorized as {label} concerning {topic} was indexed ({citation})."
    ),
    ChronicleEntryType.METHOD: (
        "{year}: a mechanism or preclinical publication categorized as {label} concerning {topic} was indexed "
        "({citation})."
    ),
    ChronicleEntryType.CONTROVERSY: (
        "{year}: a publication categorized as {label} concerning {topic} was indexed ({citation})."
    ),
    ChronicleEntryType.BACKGROUND: "{year}: a background publication concerning {topic} was indexed ({citation}).",
}


def _slugify(value: str) -> str:
    """Return a lowercase, hyphen-separated slug for *value*."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:60] or "chronicle"


def canonical_topic_key(value: str) -> str:
    """Return the canonical identity key shared by topic lookup and IDs."""
    return " ".join(unicodedata.normalize("NFC", value).split()).casefold()


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
    canonical_topic = canonical_topic_key(topic)
    digest = hashlib.sha256(f"{canonical_topic}|{scope_key}".encode()).hexdigest()[:8]
    return f"{_slugify(canonical_topic)}-{digest}"


def _derive_entry_id(chronicle_id: str, event: TimelineEvent) -> str:
    """Return an evidence-identity-based ID stable across reclassification."""
    if event.pmid and event.pmid.strip():
        evidence_identity = f"pmid:{event.pmid.strip()}"
    elif event.doi and event.doi.strip():
        evidence_identity = f"doi:{event.doi.strip().casefold()}"
    else:
        # Publication year and classifier outputs are deliberately excluded:
        # either can be corrected between revisions without changing the paper.
        bibliographic_identity = "|".join(
            (
                canonical_topic_key(event.title),
                canonical_topic_key(event.first_author or ""),
                canonical_topic_key(event.journal or ""),
            )
        )
        evidence_identity = f"bibliographic:{bibliographic_identity}"
    seed = f"{chronicle_id}|{evidence_identity}"
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
        year=event.year or None,
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
        year=event.year if event.year > 0 else "Undated",
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


def _entry_status(entry_type: ChronicleEntryType) -> ChronicleEntryStatus:
    """Choose the lifecycle status implied by the entry type."""
    if entry_type is ChronicleEntryType.BACKGROUND:
        return ChronicleEntryStatus.BACKGROUND
    if entry_type is ChronicleEntryType.CONTROVERSY:
        return ChronicleEntryStatus.CONTESTED
    return ChronicleEntryStatus.ACTIVE


def _bounded_metadata_strings(metadata: dict[str, Any], key: str, *, limit: int = 64) -> list[str]:
    """Copy a bounded string-list metadata field into durable provenance."""
    raw = metadata.get(key) or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple, set)):
        return []
    values: list[str] = []
    for value in raw:
        text = str(value).strip()
        if text:
            values.append(text[:256])
        if len(values) >= limit:
            break
    return values


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
    entry_id_overrides: dict[str, str] | None = None,
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
        entry_id_overrides: Optional evidence-ID to historical entry-ID map,
            used when continuing chronicles created by older ID algorithms.

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
        entry_id = (entry_id_overrides or {}).get(article.evidence_id) or _derive_entry_id(resolved_id, event)
        confidence = event.confidence_score
        event_metadata = event.metadata if isinstance(event.metadata, dict) else {}
        detection = event_metadata.get("milestone_detection")
        detection_details = dict(detection) if isinstance(detection, dict) else {}
        landmark_score = event.landmark_score.to_dict() if event.landmark_score else None

        entries.append(
            ChronicleEntry(
                entry_id=entry_id,
                entry_type=entry_type,
                title=event.milestone_label or event.title,
                time_start=event.date_label,
                summary_claim=_build_summary_claim(topic, event, article),
                confidence=float(confidence or 0.0),
                status=_entry_status(entry_type),
                evidence=EvidenceBundle(
                    supporting_articles=[article],
                    source_coverage={article.source: 1},
                ),
                tags=[event.milestone_type.value, event.evidence_level.value],
                provenance={
                    "milestone_type": event.milestone_type.value,
                    # ``confidence`` retains its historical field name on the
                    # domain entity, but its semantics are explicitly milestone
                    # detection confidence. Landmark importance is independent.
                    "detection_confidence": event.confidence_score,
                    "milestone_detection_confidence": event.confidence_score,
                    "confidence_semantics": "milestone_detection_confidence",
                    "milestone_detection": detection_details,
                    "landmark_importance_score": event.landmark_score.overall if event.landmark_score else None,
                    "landmark_score": landmark_score,
                    "landmark_tier": event.landmark_score.tier if event.landmark_score else None,
                    "earliest_observed_in_scope": bool(event_metadata.get("earliest_observed_in_scope")),
                    "earliest_observed_scope_note": event_metadata.get("earliest_observed_scope_note"),
                    "mesh_terms": _bounded_metadata_strings(event_metadata, "mesh_terms"),
                    "keywords": _bounded_metadata_strings(event_metadata, "keywords"),
                    "publication_types": _bounded_metadata_strings(event_metadata, "publication_types"),
                },
            )
        )
        if event.pmid:
            entry_by_pmid[event.pmid] = entry_id

    tree_metadata = tree.metadata if tree is not None and isinstance(tree.metadata, dict) else {}
    raw_branch_metadata = tree_metadata.get("branch_metadata")
    branch_metadata = raw_branch_metadata if isinstance(raw_branch_metadata, dict) else {}
    raw_lineage_diagnostics = tree_metadata.get("lineage_diagnostics")
    lineage_diagnostics = raw_lineage_diagnostics if isinstance(raw_lineage_diagnostics, dict) else {}
    raw_memberships = lineage_diagnostics.get("event_signal_memberships")
    membership_rows = raw_memberships if isinstance(raw_memberships, list) else []
    membership_by_event_index: dict[int, dict[str, Any]] = {}
    for row in membership_rows:
        if not isinstance(row, dict):
            continue
        event_index = row.get("event_index")
        if isinstance(event_index, int) and not isinstance(event_index, bool) and event_index >= 0:
            membership_by_event_index[event_index] = row

    branches: list[ChronicleBranch] = []
    for branch, parent_id in _flatten_tree_branches(tree):
        branch_entry_ids = [
            entry_by_pmid[event.pmid] for event in getattr(branch, "events", []) or [] if event.pmid in entry_by_pmid
        ]
        raw_details = branch_metadata.get(branch.branch_id)
        details = raw_details if isinstance(raw_details, dict) else {}
        basis = str(details.get("basis") or "research_stage_fallback")
        signal = details.get("signal")
        tags = [f"lineage_basis:{basis}"]
        if signal:
            tags.append(f"lineage_signal:{signal}")
        branches.append(
            ChronicleBranch(
                branch_id=branch.branch_id,
                name=branch.label,
                description=str(details.get("description") or f"{branch.label} research line for {topic}"),
                parent_branch_id=parent_id,
                entry_ids=branch_entry_ids,
                confidence=float(details.get("confidence") or 0.65),
                tags=tags,
            )
        )

    branch_by_entry = {entry_id: branch.branch_id for branch in branches for entry_id in branch.entry_ids}
    branch_details_by_id = {branch.branch_id: branch for branch in branches}
    for event_index, entry in enumerate(entries):
        entry.branch_id = branch_by_entry.get(entry.entry_id)
        chronicle_branch = branch_details_by_id.get(entry.branch_id or "")
        if chronicle_branch is not None:
            entry.provenance["lineage_basis"] = next(
                (tag.split(":", 1)[1] for tag in chronicle_branch.tags if tag.startswith("lineage_basis:")),
                None,
            )
            entry.provenance["lineage_signal"] = next(
                (tag.split(":", 1)[1] for tag in chronicle_branch.tags if tag.startswith("lineage_signal:")),
                None,
            )
            entry.provenance["lineage_confidence"] = chronicle_branch.confidence

        if lineage_diagnostics.get("basis") == "topic_signals":
            membership = membership_by_event_index.get(event_index, {})
            raw_primary = membership.get("primary_signal")
            primary_signal = dict(raw_primary) if isinstance(raw_primary, dict) else None
            raw_matched = membership.get("matched_signals")
            matched_signals = (
                [dict(signal) for signal in raw_matched if isinstance(signal, dict)]
                if isinstance(raw_matched, list)
                else []
            )
            raw_secondary = membership.get("secondary_branch_ids")
            secondary_branch_ids: list[str] = []
            if isinstance(raw_secondary, list):
                for branch_id in raw_secondary:
                    if not isinstance(branch_id, str):
                        continue
                    normalized_branch_id = branch_id.strip()
                    if normalized_branch_id and normalized_branch_id not in secondary_branch_ids:
                        secondary_branch_ids.append(normalized_branch_id)
            primary_branch_id = str(primary_signal.get("branch_id") or "") if primary_signal else ""
            entry.provenance.update(
                {
                    "lineage_assignment_semantics": lineage_diagnostics.get("assignment_semantics"),
                    "lineage_primary_signal": primary_signal,
                    "lineage_matched_signals": matched_signals,
                    "lineage_matched_signal_count": len(matched_signals),
                    "lineage_overlap": bool(secondary_branch_ids),
                    "lineage_secondary_branch_ids": secondary_branch_ids,
                    "lineage_cross_links": [
                        {
                            "relationship": "also_matches_topic_signal",
                            "primary_branch_id": primary_branch_id or None,
                            "secondary_branch_id": branch_id,
                        }
                        for branch_id in secondary_branch_ids
                    ],
                }
            )

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
            "lineage_diagnostics": lineage_diagnostics,
            **(metadata or {}),
        },
    )
    snapshot.graph = build_chronicle_graph(snapshot)
    return snapshot


__all__ = ["assemble_chronicle", "canonical_topic_key", "derive_chronicle_id"]
