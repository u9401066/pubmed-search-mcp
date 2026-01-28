"""
Application Layer - Use Cases and Business Logic Orchestration

Contains:
- search: Search use cases (query analysis, result aggregation)
- discovery: Citation discovery
- export: Citation export services
- session: Session management
- timeline: Research timeline building (v0.2.8)
"""

from .export.formats import SUPPORTED_FORMATS, export_articles
from .export.links import (
    get_fulltext_links,
    get_fulltext_links_with_lookup,
    summarize_access,
)
from .search.query_analyzer import (
    AnalyzedQuery,
    QueryAnalyzer,
    QueryComplexity,
    QueryIntent,
)
from .search.result_aggregator import RankingConfig, ResultAggregator
from .timeline import MilestoneDetector, TimelineBuilder

__all__ = [
    # Search
    "QueryAnalyzer",
    "QueryComplexity",
    "QueryIntent",
    "AnalyzedQuery",
    "ResultAggregator",
    "RankingConfig",
    # Export
    "export_articles",
    "SUPPORTED_FORMATS",
    "get_fulltext_links",
    "get_fulltext_links_with_lookup",
    "summarize_access",
    # Timeline (v0.2.8)
    "TimelineBuilder",
    "MilestoneDetector",
]
