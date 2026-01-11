"""
Unified Search Gateway

This module provides intelligent query analysis and result aggregation
for multi-source academic search.

Key Components:
- QueryAnalyzer: Analyzes search queries to determine optimal strategy
- ResultAggregator: Combines and ranks results from multiple sources

Architecture:
    User Query
        │
        ▼
    ┌──────────────────┐
    │  QueryAnalyzer   │  ← Determines complexity, detects PICO
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐
    │  DispatchMatrix  │  ← Selects sources based on query type
    └────────┬─────────┘
             │
    ┌────────┴────────┐
    ▼        ▼        ▼
  PubMed  CrossRef  OpenAlex  ← Parallel queries
    │        │        │
    └────────┴────────┘
             │
             ▼
    ┌──────────────────┐
    │ ResultAggregator │  ← Dedup + Multi-dimensional ranking
    └────────┬─────────┘
             │
             ▼
    UnifiedArticle[]
"""

from .query_analyzer import (
    QueryAnalyzer,
    QueryComplexity,
    QueryIntent,
    AnalyzedQuery,
)
from .result_aggregator import (
    ResultAggregator,
    RankingConfig,
    RankingDimension,
)

__all__ = [
    # Query Analysis
    "QueryAnalyzer",
    "QueryComplexity",
    "QueryIntent",
    "AnalyzedQuery",
    # Result Aggregation
    "ResultAggregator",
    "RankingConfig",
    "RankingDimension",
]
