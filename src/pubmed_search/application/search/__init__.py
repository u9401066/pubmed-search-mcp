"""
Search application exports.

The search package exposes query analysis, validation, ranking, aggregation,
and semantic enhancement. Exports are lazy so local-only utilities such as
``QueryAnalyzer`` do not import multi-source HTTP clients.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # Query analysis
    "QueryAnalyzer": ("pubmed_search.application.search.query_analyzer", "QueryAnalyzer"),
    "QueryComplexity": ("pubmed_search.application.search.query_analyzer", "QueryComplexity"),
    "QueryIntent": ("pubmed_search.application.search.query_analyzer", "QueryIntent"),
    "AnalyzedQuery": ("pubmed_search.application.search.query_analyzer", "AnalyzedQuery"),
    # Semantic enhancement
    "SemanticEnhancer": ("pubmed_search.application.search.semantic_enhancer", "SemanticEnhancer"),
    "EnhancedQuery": ("pubmed_search.application.search.semantic_enhancer", "EnhancedQuery"),
    "ExpandedTerm": ("pubmed_search.application.search.semantic_enhancer", "ExpandedTerm"),
    "SearchPlan": ("pubmed_search.application.search.semantic_enhancer", "SearchPlan"),
    "enhance_query": ("pubmed_search.application.search.semantic_enhancer", "enhance_query"),
    "get_semantic_enhancer": ("pubmed_search.application.search.semantic_enhancer", "get_semantic_enhancer"),
    # Query validation
    "QueryValidator": ("pubmed_search.application.search.query_validator", "QueryValidator"),
    "QueryValidationResult": ("pubmed_search.application.search.query_validator", "QueryValidationResult"),
    "validate_query": ("pubmed_search.application.search.query_validator", "validate_query"),
    # Result aggregation
    "ResultAggregator": ("pubmed_search.application.search.result_aggregator", "ResultAggregator"),
    "RankingConfig": ("pubmed_search.application.search.result_aggregator", "RankingConfig"),
    "RankingDimension": ("pubmed_search.application.search.result_aggregator", "RankingDimension"),
    "AggregationStats": ("pubmed_search.application.search.result_aggregator", "AggregationStats"),
    # Ranking algorithms
    "BM25Corpus": ("pubmed_search.application.search.ranking_algorithms", "BM25Corpus"),
    "bm25_score": ("pubmed_search.application.search.ranking_algorithms", "bm25_score"),
    "bm25_score_normalized": ("pubmed_search.application.search.ranking_algorithms", "bm25_score_normalized"),
    "RRFResult": ("pubmed_search.application.search.ranking_algorithms", "RRFResult"),
    "reciprocal_rank_fusion": ("pubmed_search.application.search.ranking_algorithms", "reciprocal_rank_fusion"),
    "MMRResult": ("pubmed_search.application.search.ranking_algorithms", "MMRResult"),
    "mmr_diversify": ("pubmed_search.application.search.ranking_algorithms", "mmr_diversify"),
    "SourceDisagreement": ("pubmed_search.application.search.ranking_algorithms", "SourceDisagreement"),
    "analyze_source_disagreement": (
        "pubmed_search.application.search.ranking_algorithms",
        "analyze_source_disagreement",
    ),
    # Reproducibility
    "ReproducibilityScore": ("pubmed_search.application.search.reproducibility", "ReproducibilityScore"),
    "calculate_reproducibility": ("pubmed_search.application.search.reproducibility", "calculate_reproducibility"),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *_LAZY_EXPORTS])
