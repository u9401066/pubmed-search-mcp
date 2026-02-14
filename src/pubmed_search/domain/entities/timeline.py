"""
Timeline Entities - Research Timeline Domain Model

This module defines the core entities for the Research Timeline feature,
enabling temporal evolution analysis of scientific research.

Key Entities:
    - TimelineEvent: Individual milestone in research history
    - ResearchTimeline: Complete timeline with metadata
    - MilestoneType: Categorization of research milestones

Architecture:
    Uses dataclasses for consistency with UnifiedArticle.
    All entities are immutable and serializable.

Example:
    >>> event = TimelineEvent(
    ...     pmid="12345678",
    ...     year=2020,
    ...     milestone_type=MilestoneType.FDA_APPROVAL,
    ...     title="FDA approves drug X for condition Y",
    ...     milestone_label="FDA Approval"
    ... )
    >>> timeline = ResearchTimeline(topic="remimazolam", events=[event])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any


class MilestoneType(Enum):
    """
    Categories of research milestones.

    Organized by typical research progression:
    1. Discovery/Preclinical
    2. Clinical Development
    3. Regulatory
    4. Post-Market
    5. Knowledge Evolution
    """

    # Discovery Phase
    FIRST_REPORT = "first_report"  # First scientific report
    MECHANISM_DISCOVERY = "mechanism_discovery"  # Mechanism of action
    PRECLINICAL = "preclinical"  # Animal studies

    # Clinical Development
    PHASE_1 = "phase_1"  # First-in-human
    PHASE_2 = "phase_2"  # Dose-finding
    PHASE_3 = "phase_3"  # Pivotal trials
    PHASE_4 = "phase_4"  # Post-marketing

    # Regulatory Milestones
    FDA_APPROVAL = "fda_approval"  # US FDA
    EMA_APPROVAL = "ema_approval"  # European EMA
    REGULATORY_APPROVAL = "regulatory_approval"  # Generic regulatory

    # Knowledge Evolution
    META_ANALYSIS = "meta_analysis"  # Evidence synthesis
    SYSTEMATIC_REVIEW = "systematic_review"  # Systematic evidence
    GUIDELINE = "guideline"  # Clinical guideline
    CONSENSUS = "consensus"  # Expert consensus

    # Post-Market Events
    SAFETY_ALERT = "safety_alert"  # Safety concerns
    LABEL_UPDATE = "label_update"  # Indication changes
    WITHDRAWAL = "withdrawal"  # Market withdrawal

    # General
    LANDMARK_STUDY = "landmark_study"  # High-impact study
    CONTROVERSY = "controversy"  # Scientific debate
    BREAKTHROUGH = "breakthrough"  # Major advancement
    OTHER = "other"  # Uncategorized


class EvidenceLevel(Enum):
    """Evidence level (simplified Oxford CEBM)."""

    LEVEL_1 = "1"  # Systematic reviews, RCTs
    LEVEL_2 = "2"  # RCTs, cohort studies
    LEVEL_3 = "3"  # Case-control, case series
    LEVEL_4 = "4"  # Case reports, expert opinion
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TimelineEvent:
    """
    A single event/milestone in the research timeline.

    Represents a significant moment in the research evolution,
    extracted from a scientific article.

    Attributes:
        pmid: PubMed ID of the source article
        year: Publication year
        month: Publication month (optional)
        milestone_type: Category of the milestone
        title: Article or event title
        milestone_label: Short label for visualization
        description: Extended description (optional)
        evidence_level: Evidence quality level
        citation_count: Number of citations (impact proxy)
        journal: Source journal
        first_author: First author name
        doi: Digital Object Identifier
        confidence_score: Confidence in milestone detection (0-1)
        metadata: Additional source-specific data
    """

    pmid: str
    year: int
    milestone_type: MilestoneType
    title: str
    milestone_label: str

    # Optional fields
    month: int | None = None
    description: str | None = None
    evidence_level: EvidenceLevel = EvidenceLevel.UNKNOWN
    citation_count: int = 0
    journal: str | None = None
    first_author: str | None = None
    doi: str | None = None
    confidence_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def date_label(self) -> str:
        """Return formatted date label."""
        if self.month:
            return f"{self.year}-{self.month:02d}"
        return str(self.year)

    @property
    def sort_key(self) -> tuple[int, int, str]:
        """Return sort key for chronological ordering."""
        return (self.year, self.month or 0, self.pmid)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "pmid": self.pmid,
            "year": self.year,
            "month": self.month,
            "milestone_type": self.milestone_type.value,
            "title": self.title,
            "milestone_label": self.milestone_label,
            "description": self.description,
            "evidence_level": self.evidence_level.value,
            "citation_count": self.citation_count,
            "journal": self.journal,
            "first_author": self.first_author,
            "doi": self.doi,
            "confidence_score": self.confidence_score,
            "date_label": self.date_label,
        }


@dataclass
class TimelinePeriod:
    """
    A period/phase in the research timeline.

    Groups events into meaningful phases for visualization.
    """

    name: str
    start_year: int
    end_year: int
    events: list[TimelineEvent] = field(default_factory=list)
    description: str | None = None

    @property
    def event_count(self) -> int:
        """Return number of events in this period."""
        return len(self.events)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "start_year": self.start_year,
            "end_year": self.end_year,
            "event_count": self.event_count,
            "description": self.description,
            "events": [e.to_dict() for e in self.events],
        }


@dataclass
class ResearchTimeline:
    """
    Complete research timeline for a topic.

    Aggregates all timeline events and provides analysis methods.

    Attributes:
        topic: Research topic/drug/gene name
        events: List of timeline events (chronologically sorted)
        periods: Optional grouping into phases
        metadata: Additional timeline metadata
        created_at: Timeline creation timestamp
    """

    topic: str
    events: list[TimelineEvent] = field(default_factory=list)
    periods: list[TimelinePeriod] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: date = field(default_factory=date.today)

    def __post_init__(self) -> None:
        """Sort events chronologically."""
        self.events = sorted(self.events, key=lambda e: e.sort_key)

    @property
    def total_events(self) -> int:
        """Return total number of events."""
        return len(self.events)

    @property
    def year_range(self) -> tuple[int, int] | None:
        """Return (start_year, end_year) or None if empty."""
        if not self.events:
            return None
        years = [e.year for e in self.events]
        return (min(years), max(years))

    @property
    def duration_years(self) -> int:
        """Return timeline duration in years."""
        range_ = self.year_range
        if not range_:
            return 0
        return range_[1] - range_[0] + 1

    @property
    def milestone_summary(self) -> dict[str, int]:
        """Count events by milestone type."""
        summary: dict[str, int] = {}
        for event in self.events:
            key = event.milestone_type.value
            summary[key] = summary.get(key, 0) + 1
        return summary

    def get_events_by_type(self, milestone_type: MilestoneType) -> list[TimelineEvent]:
        """Filter events by milestone type."""
        return [e for e in self.events if e.milestone_type == milestone_type]

    def get_events_in_year(self, year: int) -> list[TimelineEvent]:
        """Get all events in a specific year."""
        return [e for e in self.events if e.year == year]

    def get_events_in_range(self, start: int, end: int) -> list[TimelineEvent]:
        """Get events within a year range (inclusive)."""
        return [e for e in self.events if start <= e.year <= end]

    def get_landmark_events(self, min_citations: int = 100) -> list[TimelineEvent]:
        """Get high-impact landmark events."""
        return [e for e in self.events if e.citation_count >= min_citations]

    def to_dict(self) -> dict[str, Any]:
        """Convert timeline to dictionary."""
        return {
            "topic": self.topic,
            "total_events": self.total_events,
            "year_range": self.year_range,
            "duration_years": self.duration_years,
            "milestone_summary": self.milestone_summary,
            "events": [e.to_dict() for e in self.events],
            "periods": [p.to_dict() for p in self.periods],
            "created_at": self.created_at.isoformat(),
        }

    def to_mermaid(self) -> str:
        """
        Generate Mermaid timeline diagram.

        Returns:
            Mermaid timeline syntax for visualization.
        """
        lines = ["timeline", f"    title {self.topic} Research Timeline"]

        # Group events by year
        events_by_year: dict[int, list[TimelineEvent]] = {}
        for event in self.events:
            if event.year not in events_by_year:
                events_by_year[event.year] = []
            events_by_year[event.year].append(event)

        # Generate timeline sections
        for year in sorted(events_by_year.keys()):
            year_events = events_by_year[year]
            lines.append(f"    section {year}")
            for event in year_events:
                # Escape special characters in label
                label = event.milestone_label.replace(":", " -")
                lines.append(f"        {label}")

        return "\n".join(lines)

    def to_json_timeline(self) -> dict[str, Any]:
        """
        Generate JSON format for timeline.js or similar libraries.

        Returns:
            JSON-compatible dict for timeline visualization.
        """
        events_json = []
        for event in self.events:
            events_json.append(
                {
                    "start_date": {
                        "year": event.year,
                        "month": event.month or 1,
                    },
                    "text": {
                        "headline": event.milestone_label,
                        "text": f"<p>{event.title}</p>" + (f"<p><em>{event.journal}</em></p>" if event.journal else ""),
                    },
                    "group": event.milestone_type.value,
                    "unique_id": event.pmid,
                }
            )

        return {
            "title": {
                "text": {
                    "headline": f"{self.topic} Research Timeline",
                    "text": f"<p>{self.total_events} events from {self.year_range[0] if self.year_range else 'N/A'} to {self.year_range[1] if self.year_range else 'N/A'}</p>",
                }
            },
            "events": events_json,
        }


# Type alias for pattern-based milestone detection
MilestonePattern = dict[str, str | list[str] | MilestoneType]
