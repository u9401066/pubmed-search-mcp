"""
Domain Entities

Core business objects for academic search.
"""

from __future__ import annotations

from .article import (
    ArticleType,
    Author,
    CitationMetrics,
    OpenAccessLink,
    OpenAccessStatus,
    SourceMetadata,
    UnifiedArticle,
)
from .image import ImageResult, ImageSource
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
    # Image entities (v0.3.1)
    "ImageResult",
    "ImageSource",
    # Timeline entities (v0.2.8)
    "TimelineEvent",
    "ResearchTimeline",
    "TimelinePeriod",
    "MilestoneType",
    "EvidenceLevel",
]
