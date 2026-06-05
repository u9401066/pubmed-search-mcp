"""
Application layer public exports.

Exports are lazy so importing one use-case subpackage does not initialize
unrelated search, timeline, source, or settings dependencies.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # Search
    "QueryAnalyzer": ("pubmed_search.application.search.query_analyzer", "QueryAnalyzer"),
    "QueryComplexity": ("pubmed_search.application.search.query_analyzer", "QueryComplexity"),
    "QueryIntent": ("pubmed_search.application.search.query_analyzer", "QueryIntent"),
    "AnalyzedQuery": ("pubmed_search.application.search.query_analyzer", "AnalyzedQuery"),
    "ResultAggregator": ("pubmed_search.application.search.result_aggregator", "ResultAggregator"),
    "RankingConfig": ("pubmed_search.application.search.result_aggregator", "RankingConfig"),
    # Export
    "export_articles": ("pubmed_search.application.export.formats", "export_articles"),
    "SUPPORTED_FORMATS": ("pubmed_search.application.export.formats", "SUPPORTED_FORMATS"),
    "get_fulltext_links": ("pubmed_search.application.export.links", "get_fulltext_links"),
    "get_fulltext_links_with_lookup": ("pubmed_search.application.export.links", "get_fulltext_links_with_lookup"),
    "summarize_access": ("pubmed_search.application.export.links", "summarize_access"),
    # Timeline
    "TimelineBuilder": ("pubmed_search.application.timeline", "TimelineBuilder"),
    "MilestoneDetector": ("pubmed_search.application.timeline", "MilestoneDetector"),
    # Unified search service contracts
    "UnifiedSearchRunRequest": ("pubmed_search.application.unified", "UnifiedSearchRunRequest"),
    "UnifiedSearchService": ("pubmed_search.application.unified", "UnifiedSearchService"),
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
