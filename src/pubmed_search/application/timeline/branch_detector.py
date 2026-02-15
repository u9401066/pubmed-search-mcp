"""
Branch Detector - Organize Timeline Events into Research Branches

Groups timeline events by their milestone types into a tree structure, mapping
the natural research progression (Discovery → Clinical → Regulatory → etc.).

Branch detection uses MilestoneType as the primary signal:
- Each MilestoneType maps to a predefined branch category
- Clinical trials branch has sub-branches (Phase I/II vs Phase III/IV)
- Empty branches are omitted from the output
- Events within each branch are sorted chronologically

Architecture:
    Stateless module with a single public function `build_research_tree()`.
    Takes a ResearchTimeline (flat events) and reorganizes into a ResearchTree.
"""

from __future__ import annotations

from pubmed_search.domain.entities.research_tree import ResearchBranch, ResearchTree
from pubmed_search.domain.entities.timeline import (
    MilestoneType,
    ResearchTimeline,
    TimelineEvent,
)

# ─────────────────────────────────────────────────────────────────────
# Branch Category Definitions
# ─────────────────────────────────────────────────────────────────────

# Mapping from MilestoneType → branch_id
_TYPE_TO_BRANCH: dict[MilestoneType, str] = {
    # Discovery & Mechanism
    MilestoneType.FIRST_REPORT: "discovery",
    MilestoneType.MECHANISM_DISCOVERY: "discovery",
    MilestoneType.PRECLINICAL: "discovery",
    # Clinical Development
    MilestoneType.PHASE_1: "clinical",
    MilestoneType.PHASE_2: "clinical",
    MilestoneType.PHASE_3: "clinical",
    MilestoneType.PHASE_4: "clinical",
    # Regulatory
    MilestoneType.FDA_APPROVAL: "regulatory",
    MilestoneType.EMA_APPROVAL: "regulatory",
    MilestoneType.REGULATORY_APPROVAL: "regulatory",
    # Evidence Synthesis
    MilestoneType.META_ANALYSIS: "evidence",
    MilestoneType.SYSTEMATIC_REVIEW: "evidence",
    # Practice Guidelines
    MilestoneType.GUIDELINE: "practice",
    MilestoneType.CONSENSUS: "practice",
    # Safety & Pharmacovigilance
    MilestoneType.SAFETY_ALERT: "safety",
    MilestoneType.LABEL_UPDATE: "safety",
    MilestoneType.WITHDRAWAL: "safety",
    # Landmark / Breakthrough
    MilestoneType.LANDMARK_STUDY: "landmark",
    MilestoneType.BREAKTHROUGH: "landmark",
    MilestoneType.CONTROVERSY: "landmark",
    # General
    MilestoneType.OTHER: "general",
}

# Branch metadata (id → label, icon, display order)
_BRANCH_META: dict[str, tuple[str, str, int]] = {
    #                (label,                          icon,  order)
    "discovery": ("Discovery & Mechanism", "\U0001f52c", 1),
    "clinical": ("Clinical Development", "\U0001f3e5", 2),
    "regulatory": ("Regulatory Milestones", "\U0001f4cb", 3),
    "evidence": ("Evidence Synthesis", "\U0001f4ca", 4),
    "practice": ("Guidelines & Practice", "\U0001f4d6", 5),
    "safety": ("Safety & Pharmacovigilance", "\u26a0\ufe0f", 6),
    "landmark": ("Landmark Studies", "\U0001f3c6", 7),
    "general": ("Other Studies", "\U0001f4c4", 8),
}

# Clinical sub-branches
_CLINICAL_EARLY = {MilestoneType.PHASE_1, MilestoneType.PHASE_2}
_CLINICAL_LATE = {MilestoneType.PHASE_3, MilestoneType.PHASE_4}


def build_research_tree(timeline: ResearchTimeline) -> ResearchTree:
    """
    Organize a flat ResearchTimeline into a branching ResearchTree.

    Groups events by milestone type into predefined research branches.
    Clinical Development branch gets sub-branches (early vs late phase).
    Empty branches are automatically excluded.

    Args:
        timeline: Flat timeline with chronologically sorted events

    Returns:
        ResearchTree with thematic branches
    """
    # Step 1: Bucket events by branch_id
    buckets: dict[str, list[TimelineEvent]] = {}
    for event in timeline.events:
        branch_id = _TYPE_TO_BRANCH.get(event.milestone_type, "general")
        if branch_id not in buckets:
            buckets[branch_id] = []
        buckets[branch_id].append(event)

    # Step 2: Build branches
    branches: list[ResearchBranch] = []
    for branch_id, (label, icon, order) in _BRANCH_META.items():
        events = buckets.get(branch_id, [])
        if not events:
            continue

        if branch_id == "clinical":
            # Split clinical into early (Phase I/II) and late (Phase III/IV)
            branch = _build_clinical_branch(events, label, icon, order)
        else:
            branch = ResearchBranch(
                branch_id=branch_id,
                label=label,
                icon=icon,
                events=events,
                order=order,
            )

        branches.append(branch)

    return ResearchTree(
        topic=timeline.topic,
        branches=branches,
        total_articles=timeline.metadata.get("total_searched", len(timeline.events)),
        metadata={
            **timeline.metadata,
            "tree_branches": len([b for b in branches if not b.is_empty]),
        },
    )


def _build_clinical_branch(
    events: list[TimelineEvent],
    label: str,
    icon: str,
    order: int,
) -> ResearchBranch:
    """
    Build clinical development branch with Phase I/II and Phase III/IV sub-branches.

    Only creates sub-branches if there are events in both early and late phases.
    If all events are in one phase, they go directly on the branch without nesting.
    """
    early = [e for e in events if e.milestone_type in _CLINICAL_EARLY]
    late = [e for e in events if e.milestone_type in _CLINICAL_LATE]

    # Only create sub-branches if we have events in multiple phases
    has_multi_phase = bool(early) and bool(late)

    if has_multi_phase:
        sub_branches = []
        if early:
            sub_branches.append(
                ResearchBranch(
                    branch_id="clinical_early",
                    label="Phase I/II",
                    events=early,
                    order=1,
                )
            )
        if late:
            sub_branches.append(
                ResearchBranch(
                    branch_id="clinical_late",
                    label="Phase III/IV",
                    events=late,
                    order=2,
                )
            )
        return ResearchBranch(
            branch_id="clinical",
            label=label,
            icon=icon,
            sub_branches=sub_branches,
            order=order,
        )
    # All in one phase, keep flat
    return ResearchBranch(
        branch_id="clinical",
        label=label,
        icon=icon,
        events=events,
        order=order,
    )
