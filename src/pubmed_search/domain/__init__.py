"""
Domain Layer - Core Business Logic

Contains:
- entities: Core domain entities (Article, Citation)
"""

from .entities import (
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
