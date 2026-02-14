"""
Domain Layer - Core Business Logic

Contains:
- entities: Core domain entities (Article, Citation)
"""

from __future__ import annotations

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
    "ArticleType",
    "Author",
    "CitationMetrics",
    "OpenAccessLink",
    "OpenAccessStatus",
    "SourceMetadata",
    "UnifiedArticle",
]
