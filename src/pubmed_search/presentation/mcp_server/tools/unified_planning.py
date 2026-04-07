"""Semantic analysis and source planning for unified_search.

Design:
    The planning stage transforms a normalized request into an executable
    search plan. It owns query analysis, semantic enhancement, ICD expansion,
    source selection, and ranking-configuration decisions.

Maintenance:
    Keep search-strategy decisions here and execution concerns in
    unified_execution.py. This separation is important because planning logic
    is reused by tests and by future non-MCP entry points.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pubmed_search.application.search.query_analyzer import AnalyzedQuery, QueryAnalyzer
from pubmed_search.application.search.result_aggregator import RankingConfig
from pubmed_search.application.search.semantic_enhancer import EnhancedQuery, get_semantic_enhancer
from pubmed_search.infrastructure.sources.registry import SourceSelectionError, get_source_registry

from .unified_helpers import DispatchStrategy, detect_and_expand_icd_codes

if TYPE_CHECKING:
    from .unified_request import UnifiedSearchRequest

logger = logging.getLogger(__name__)

ProgressReporter = Callable[[float, float, str], Awaitable[None]]


@dataclass
class UnifiedSearchPlan:
    """Planned search execution derived from a normalized request."""

    request: UnifiedSearchRequest
    query: str
    analysis: AnalyzedQuery
    icd_matches: list[dict[str, Any]]
    enhanced_query: EnhancedQuery | None
    matched_entity_names: list[str]
    user_sources: list[str] | None
    dispatch_sources: list[str]
    ranking_config: RankingConfig
    effective_min_year: int | None
    effective_max_year: int | None


async def build_unified_search_plan(
    request: UnifiedSearchRequest,
    *,
    progress: ProgressReporter,
    analyzer_factory: Callable[[], QueryAnalyzer] = QueryAnalyzer,
    enhancer_factory: Callable[[], Any] = get_semantic_enhancer,
    source_registry_factory: Callable[[], Any] = get_source_registry,
) -> UnifiedSearchPlan:
    """Analyze the query and resolve an execution plan."""
    query = request.query
    icd_matches: list[dict[str, Any]] = []
    expanded_query, icd_matches = detect_and_expand_icd_codes(query)
    if icd_matches:
        query = expanded_query
        logger.info("ICD codes detected: %s", [match["code"] for match in icd_matches])

    await progress(1, 10, "Analyzing query...")
    analyzer = analyzer_factory()
    analysis = analyzer.analyze(query)
    logger.info("Query analysis: complexity=%s, intent=%s", analysis.complexity.value, analysis.intent.value)

    enhanced_query: EnhancedQuery | None = None
    matched_entity_names: list[str] = []
    skip_enhancement = analysis.complexity.value == "simple" or analysis.intent.value == "lookup"

    if skip_enhancement:
        logger.info("Skipping semantic enhancement for simple/lookup query")
    else:
        try:
            await progress(2, 10, "Enhancing query with PubTator3...")
            enhancer = enhancer_factory()
            enhanced_query = await asyncio.wait_for(enhancer.enhance(query), timeout=3.0)
            if enhanced_query and enhanced_query.entities:
                matched_entity_names = [entity.resolved_name for entity in enhanced_query.entities]
                logger.info(
                    "Semantic enhancement: %s entities, %s strategies",
                    len(enhanced_query.entities),
                    len(enhanced_query.strategies),
                )
        except asyncio.TimeoutError:
            logger.warning("Semantic enhancement timeout - continuing without")
        except Exception as exc:
            logger.debug("Semantic enhancement skipped: %s", exc)

    registry = source_registry_factory()
    auto_sources = DispatchStrategy.get_sources(analysis)
    user_sources: list[str] | None = None

    if request.sources:
        selection = registry.resolve_unified_sources(request.sources, auto_sources=auto_sources)
        user_sources = list(selection.sources)
        logger.info(
            "User-specified sources resolved to %s (mode=%s, excluded=%s)",
            user_sources,
            selection.mode,
            list(selection.excluded),
        )

    dispatch_sources = user_sources or auto_sources
    if not dispatch_sources:
        msg = "No enabled sources are available for unified_search"
        raise ValueError(msg)

    await progress(3, 10, f"Sources: {', '.join(dispatch_sources)}")
    logger.info("Selected sources: %s", dispatch_sources)

    if request.ranking == "impact":
        ranking_config = RankingConfig.impact_focused()
    elif request.ranking == "recency":
        ranking_config = RankingConfig.recency_focused()
    elif request.ranking == "quality":
        ranking_config = RankingConfig.quality_focused()
    else:
        ranking_config = DispatchStrategy.get_ranking_config(analysis)

    if matched_entity_names:
        ranking_config.matched_entities = matched_entity_names

    return UnifiedSearchPlan(
        request=request,
        query=query,
        analysis=analysis,
        icd_matches=icd_matches,
        enhanced_query=enhanced_query,
        matched_entity_names=matched_entity_names,
        user_sources=user_sources,
        dispatch_sources=dispatch_sources,
        ranking_config=ranking_config,
        effective_min_year=request.min_year or analysis.year_from,
        effective_max_year=request.max_year or analysis.year_to,
    )


__all__ = ["UnifiedSearchPlan", "build_unified_search_plan", "ProgressReporter", "SourceSelectionError"]
