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
from .figure import ArticleFigure, ArticleFiguresResult
from .image import ImageResult, ImageSource
from .research_tree import ResearchBranch, ResearchTree
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
    # Figure entities
    "ArticleFigure",
    "ArticleFiguresResult",
    # Image entities
    "ImageResult",
    "ImageSource",
    # Timeline entities
    "TimelineEvent",
    "ResearchTimeline",
    "TimelinePeriod",
    "MilestoneType",
    "EvidenceLevel",
    # Research Tree entities
    "ResearchBranch",
    "ResearchTree",
]
