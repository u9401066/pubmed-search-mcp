"""
Research Tree Entities - Branching Research Lineage Model

A Research Tree captures how a research field evolves into sub-topics over time.
Unlike a flat timeline (single line) or a Knowledge Graph (over-connected),
a tree preserves:
- Temporal ordering (parent ??child in time)
- Natural branching into sub-fields (Clinical, Safety, Guidelines, etc.)
- Hierarchical organization without cross-linkage noise

Key Entities:
    - ResearchBranch: A thematic branch (e.g., "Clinical Development")
    - ResearchTree: Complete tree with branches and metadata

Architecture:
    Dataclasses for consistency with other domain entities.
    ResearchBranch can have sub_branches for deeper nesting (e.g.,
    Clinical Dev ??Phase I, Phase II, Phase III).

Example:
    >>> branch = ResearchBranch(
    ...     branch_id="clinical",
    ...     label="Clinical Development",
    ...     icon="?",
    ...     events=[event1, event2],
    ... )
    >>> tree = ResearchTree(topic="remimazolam", branches=[branch])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .timeline import TimelineEvent

# Display constants
_TITLE_MAX_LEN = 60
_NOTABLE_THRESHOLD = 0.50


@dataclass
class ResearchBranch:
    """
    A thematic branch in the research tree.

    Represents a sub-field or category of research (e.g., "Safety",
    "Clinical Development"). Branches are ordered chronologically and
    can contain sub-branches for finer granularity.

    Attributes:
        branch_id: Unique identifier (e.g., "clinical", "safety")
        label: Human-readable name (e.g., "Clinical Development")
        icon: Emoji icon for display
        events: Timeline events in this branch (sorted chronologically)
        sub_branches: Optional child branches for deeper nesting
        order: Display order (lower = earlier in typical research flow)
    """

    branch_id: str
    label: str
    icon: str = ""
    events: list[TimelineEvent] = field(default_factory=list)
    sub_branches: list[ResearchBranch] = field(default_factory=list)
    order: int = 0

    def __post_init__(self) -> None:
        """Sort events chronologically."""
        self.events = sorted(self.events, key=lambda e: e.sort_key)
        self.sub_branches = sorted(self.sub_branches, key=lambda b: b.order)

    @property
    def total_events(self) -> int:
        """Total events including sub-branches."""
        return len(self.events) + sum(b.total_events for b in self.sub_branches)

    @property
    def all_events(self) -> list[TimelineEvent]:
        """All events including sub-branches, chronologically sorted."""
        all_ev = list(self.events)
        for sub in self.sub_branches:
            all_ev.extend(sub.all_events)
        return sorted(all_ev, key=lambda e: e.sort_key)

    @property
    def year_range(self) -> tuple[int, int] | None:
        """Year range of all events (including sub-branches)."""
        all_ev = self.all_events
        if not all_ev:
            return None
        years = [e.year for e in all_ev]
        return (min(years), max(years))

    @property
    def is_empty(self) -> bool:
        """Check if branch has no events at all."""
        return self.total_events == 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result: dict[str, Any] = {
            "branch_id": self.branch_id,
            "label": self.label,
            "icon": self.icon,
            "total_events": self.total_events,
            "year_range": self.year_range,
            "events": [e.to_dict() for e in self.events],
        }
        if self.sub_branches:
            result["sub_branches"] = [b.to_dict() for b in self.sub_branches if not b.is_empty]
        return result


@dataclass
class ResearchTree:
    """
    Complete research lineage tree for a topic.

    Organizes research evolution into thematic branches, each containing
    chronologically ordered events with optional sub-branches.

    Attributes:
        topic: Research topic name
        branches: Top-level thematic branches
        total_articles: Total articles searched
        metadata: Additional tree metadata
        created_at: Tree creation timestamp
    """

    topic: str
    branches: list[ResearchBranch] = field(default_factory=list)
    total_articles: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: date = field(default_factory=date.today)

    @property
    def total_events(self) -> int:
        """Total events across all branches."""
        return sum(b.total_events for b in self.branches)

    @property
    def active_branches(self) -> list[ResearchBranch]:
        """Branches that contain at least one event."""
        return [b for b in self.branches if not b.is_empty]

    @property
    def year_range(self) -> tuple[int, int] | None:
        """Overall year range."""
        all_ranges = [b.year_range for b in self.branches if b.year_range]
        if not all_ranges:
            return None
        return (min(r[0] for r in all_ranges), max(r[1] for r in all_ranges))

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "topic": self.topic,
            "total_events": self.total_events,
            "total_branches": len(self.active_branches),
            "year_range": self.year_range,
            "branches": [b.to_dict() for b in self.active_branches],
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }

    def to_text_tree(self) -> str:
        """
        Format as a human-readable ASCII tree.

        Example output:
            ## Research Tree: remimazolam
            **Period**: 2010 - 2024 | **Branches**: 5 | **Events**: 23
            ??? ? Discovery & Mechanism (2010-2016) [3 events]
            ??  ??? 2010: First synthesis (PMID: 123) 潃?潃?            ??  ??? 2016: Metabolism pathway (PMID: 456)
            ??? ? Clinical Development (2014-2023) [8 events]
            ??  ??? Phase I/II (2014-2019) [3 events]
            ??  ??  ??? 2014: First-in-human (PMID: 789)
            ??  ??? Phase III/IV (2020-2023) [5 events]
            ??      ??? 2020: Pivotal trial (PMID: 012) 潃?潃?            ??? ?? Safety (2018-2024) [4 events]
                ??? 2024: Post-marketing meta-analysis (PMID: 345)
        """
        lines: list[str] = []

        # Header
        yr = self.year_range
        period = f"{yr[0]} - {yr[1]}" if yr else "N/A"
        lines.append(f"## Research Tree: {self.topic}")
        lines.append(
            f"**Period**: {period} | **Branches**: {len(self.active_branches)} | **Events**: {self.total_events}"
        )

        # Landmark summary
        all_events = []
        for b in self.active_branches:
            all_events.extend(b.all_events)
        landmarks = [e for e in all_events if e.landmark_score and e.landmark_score.overall >= _NOTABLE_THRESHOLD]
        if landmarks:
            lines.append(f"**Landmark Papers**: {len(landmarks)} identified")

        lines.append("")

        # Branches
        active = self.active_branches
        for i, branch in enumerate(active):
            is_last_branch = i == len(active) - 1
            prefix = "??? " if is_last_branch else "??? "
            child_prefix = "    " if is_last_branch else "??  "

            yr_range = branch.year_range
            yr_str = f"({yr_range[0]}-{yr_range[1]})" if yr_range else ""
            lines.append(f"{prefix}{branch.icon} {branch.label} {yr_str} [{branch.total_events} events]")

            # Sub-branches
            if branch.sub_branches:
                non_empty_subs = [s for s in branch.sub_branches if not s.is_empty]
                for j, sub in enumerate(non_empty_subs):
                    is_last_sub = j == len(non_empty_subs) - 1
                    sub_prefix = "??? " if is_last_sub else "??? "
                    sub_child = "    " if is_last_sub else "??  "

                    sub_yr = sub.year_range
                    sub_yr_str = f"({sub_yr[0]}-{sub_yr[1]})" if sub_yr else ""
                    lines.append(f"{child_prefix}{sub_prefix}{sub.label} {sub_yr_str} [{sub.total_events} events]")

                    # Events in sub-branch
                    for k, event in enumerate(sub.events):
                        is_last_ev = k == len(sub.events) - 1
                        ev_prefix = "??? " if is_last_ev else "??? "
                        stars = (
                            f" {event.landmark_score.stars}"
                            if event.landmark_score and event.landmark_score.stars
                            else ""
                        )
                        title_short = event.title[:_TITLE_MAX_LEN] + (
                            "..." if len(event.title) > _TITLE_MAX_LEN else ""
                        )
                        lines.append(
                            f"{child_prefix}{sub_child}{ev_prefix}"
                            f"{event.year}: {title_short} "
                            f"(PMID: {event.pmid}){stars}"
                        )

                # Events directly on branch (not in any sub-branch)
                if branch.events:
                    for k, event in enumerate(branch.events):
                        is_last_ev = k == len(branch.events) - 1
                        ev_prefix = "??? " if is_last_ev else "??? "
                        stars = (
                            f" {event.landmark_score.stars}"
                            if event.landmark_score and event.landmark_score.stars
                            else ""
                        )
                        title_short = event.title[:_TITLE_MAX_LEN] + (
                            "..." if len(event.title) > _TITLE_MAX_LEN else ""
                        )
                        lines.append(
                            f"{child_prefix}{ev_prefix}{event.year}: {title_short} (PMID: {event.pmid}){stars}"
                        )
            else:
                # No sub-branches, show events directly
                for k, event in enumerate(branch.events):
                    is_last_ev = k == len(branch.events) - 1
                    ev_prefix = "??? " if is_last_ev else "??? "
                    stars = (
                        f" {event.landmark_score.stars}" if event.landmark_score and event.landmark_score.stars else ""
                    )
                    title_short = event.title[:_TITLE_MAX_LEN] + ("..." if len(event.title) > _TITLE_MAX_LEN else "")
                    lines.append(f"{child_prefix}{ev_prefix}{event.year}: {title_short} (PMID: {event.pmid}){stars}")

        return "\n".join(lines)

    def to_mermaid_mindmap(self) -> str:
        """
        Generate Mermaid mindmap syntax for tree visualization.

        Renders as a radial mindmap in Mermaid-compatible renderers.
        """
        lines = ["mindmap", f"  root(({self.topic}))"]

        for branch in self.active_branches:
            yr = branch.year_range
            yr_str = f" {yr[0]}-{yr[1]}" if yr else ""
            lines.append(f"    {branch.icon} {branch.label}{yr_str}")

            if branch.sub_branches:
                for sub in branch.sub_branches:
                    if sub.is_empty:
                        continue
                    sub_yr = sub.year_range
                    sub_yr_str = f" {sub_yr[0]}-{sub_yr[1]}" if sub_yr else ""
                    lines.append(f"      {sub.label}{sub_yr_str}")

                    for event in sub.events[:3]:  # Limit for readability
                        label = event.milestone_label.replace("(", "").replace(")", "")
                        lines.append(f"        {event.year}: {label}")
            else:
                for event in branch.events[:5]:  # Limit for readability
                    label = event.milestone_label.replace("(", "").replace(")", "")
                    lines.append(f"      {event.year}: {label}")

        return "\n".join(lines)
