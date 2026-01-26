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

__all__ = [
    "UnifiedArticle",
    "ArticleType",
    "OpenAccessStatus",
    "Author",
    "OpenAccessLink",
    "CitationMetrics",
    "SourceMetadata",
]
