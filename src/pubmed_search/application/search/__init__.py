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
    AnalyzedQuery,
    QueryAnalyzer,
    QueryComplexity,
    QueryIntent,
)
from .query_validator import (
    QueryValidationResult,
    QueryValidator,
    validate_query,
)
from .result_aggregator import (
    AggregationStats,
    RankingConfig,
    RankingDimension,
    ResultAggregator,
)
from .semantic_enhancer import (
    EnhancedQuery,
    ExpandedTerm,
    SearchPlan,
    SemanticEnhancer,
    enhance_query,
    get_semantic_enhancer,
)

__all__ = [
    # Query Analysis
    "QueryAnalyzer",
    "QueryComplexity",
    "QueryIntent",
    "AnalyzedQuery",
    # Semantic Enhancement (Phase 3)
    "SemanticEnhancer",
    "EnhancedQuery",
    "ExpandedTerm",
    "SearchPlan",
    "enhance_query",
    "get_semantic_enhancer",
    # Query Validation
    "QueryValidator",
    "QueryValidationResult",
    "validate_query",
    # Result Aggregation
    "ResultAggregator",
    "RankingConfig",
    "RankingDimension",
    "AggregationStats",
]
