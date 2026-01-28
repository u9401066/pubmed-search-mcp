"""
Domain Entities

Core business objects for academic search.
"""

from .article import (
    ArticleType,
    Author,
    CitationMetrics,
    OpenAccessLink,
    OpenAccessStatus,
    SourceMetadata,
    UnifiedArticle,
)
from .timeline import (
    EvidenceLevel,
    MilestoneType,
    ResearchTimeline,
    TimelineEvent,
    TimelinePeriod,
)

__all__ = [
    # Article entities
    "UnifiedArticle",
    "ArticleType",
    "OpenAccessStatus",
    "Author",
    "OpenAccessLink",
    "CitationMetrics",
    "SourceMetadata",
    # Timeline entities (v0.2.8)
    "TimelineEvent",
    "ResearchTimeline",
    "TimelinePeriod",
    "MilestoneType",
    "EvidenceLevel",
]
