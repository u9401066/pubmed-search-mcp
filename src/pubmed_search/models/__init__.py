"""
Unified Data Models for Academic Search

This module provides standardized data structures for representing
academic articles from multiple sources (PubMed, CrossRef, OpenAlex, etc.)
"""

from .unified_article import (
    UnifiedArticle,
    Author,
    OpenAccessLink,
    CitationMetrics,
    SourceMetadata,
)

__all__ = [
    "UnifiedArticle",
    "Author",
    "OpenAccessLink",
    "CitationMetrics",
    "SourceMetadata",
]
