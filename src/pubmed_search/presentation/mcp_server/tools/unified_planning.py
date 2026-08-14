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
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from pubmed_search.application.search.query_analyzer import AnalyzedQuery, QueryAnalyzer
from pubmed_search.application.search.result_aggregator import RankingConfig
from pubmed_search.application.search.semantic_enhancer import EnhancedQuery, SearchPlan, get_semantic_enhancer
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
    provider_neutral_query: str
    analysis: AnalyzedQuery
    icd_matches: list[dict[str, Any]]
    enhanced_query: EnhancedQuery | None
    deep_strategies: list[SearchPlan]
    matched_entity_names: list[str]
    user_sources: list[str] | None
    dispatch_sources: list[str]
    ranking_config: RankingConfig
    effective_min_year: int | None
    effective_max_year: int | None


def _build_provider_neutral_icd_query(
    original_query: str,
    icd_matches: list[dict[str, Any]],
    *,
    semantic: bool,
) -> str:
    """Expand detected ICD codes without leaking PubMed field syntax.

    PubMed benefits from ``[MeSH]`` field tags, while other providers either
    interpret those characters literally or reject the query.  Keep the
    PubMed-specific query in ``UnifiedSearchPlan.query`` and compile this
    provider-neutral sibling for every non-PubMed search leg.
    """

    expanded = original_query
    for match in icd_matches:
        code = str(match["code"])
        mesh = str(match["mesh"])
        replacement = f"{mesh} ({code})" if semantic else f'("{mesh}" OR {code})'
        expanded = re.sub(
            rf"\b{re.escape(code)}\b",
            replacement,
            expanded,
            flags=re.IGNORECASE,
        )
    return expanded


def _build_deep_strategies(
    *,
    query: str,
    provider_neutral_query: str | None = None,
    enhanced_query: EnhancedQuery | None,
    dispatch_sources: list[str],
    registry: Any,
) -> list[SearchPlan]:
    """Preserve every planned primary source while retaining semantic variants.

    Semantic enhancement contributes query variants; it must not silently
    narrow the source set selected by the planner.  Each planned primary or
    preprint source therefore receives at least one baseline strategy.
    """
    if enhanced_query is None:
        return []

    primary_sources = [
        source
        for source in dispatch_sources
        if (definition := registry.get(source)) is not None and definition.supports_primary_search
    ]
    neutral_query = provider_neutral_query or query
    strategies = []
    for strategy in enhanced_query.strategies:
        if strategy.source not in primary_sources:
            continue
        # SemanticEnhancer currently receives the PubMed-shaped query.  Its
        # baseline Europe PMC strategy therefore carries that exact string as
        # well.  Copy (rather than mutate) such a baseline so PubMed field tags
        # never leak into a provider-neutral deep-search leg.
        if strategy.source != "pubmed" and strategy.query == query:
            strategies.append(replace(strategy, query=neutral_query))
        else:
            strategies.append(strategy)
    covered_sources = {strategy.source for strategy in strategies}

    for source in primary_sources:
        if source in covered_sources:
            continue
        strategies.append(
            SearchPlan(
                name=f"source_baseline_{source}",
                query=query if source == "pubmed" else neutral_query,
                source=source,
                priority=1,
                expected_precision=0.5,
                expected_recall=0.5,
            )
        )

    return strategies


def _apply_retrieval_capabilities(
    *,
    request: UnifiedSearchRequest,
    dispatch_sources: list[str],
    registry: Any,
) -> list[str]:
    """Validate or select sources for an explicit provider-native mode.

    With automatic source selection, unsupported primary adapters are removed
    and an enabled capable adapter is selected.  With an explicit source
    expression, capability mismatch is a user-facing error instead of a
    silent downgrade.
    """

    retrieval_mode = request.retrieval_mode
    if retrieval_mode == "auto":
        return dispatch_sources

    def supports(source: str) -> bool:
        definition = registry.get(source)
        if definition is None or not definition.supports_primary_search:
            return True
        return retrieval_mode in definition.capabilities.search_modes

    unsupported = [source for source in dispatch_sources if not supports(source)]
    if request.sources and unsupported:
        available = [
            source
            for source in registry.list_unified_sources()
            if (definition := registry.get(source)) is not None
            and definition.supports_primary_search
            and retrieval_mode in definition.capabilities.search_modes
        ]
        raise SourceSelectionError(
            f"Retrieval mode '{retrieval_mode}' is not supported by: {', '.join(unsupported)}",
            unavailable_sources=tuple(unsupported),
            available_sources=tuple(available),
        )

    selected = [source for source in dispatch_sources if supports(source)]
    if request.sources:
        return selected

    capable_primary = [
        source
        for source in registry.list_unified_sources()
        if (definition := registry.get(source)) is not None
        and definition.supports_primary_search
        and retrieval_mode in definition.capabilities.search_modes
    ]
    for source in capable_primary:
        if source not in selected:
            selected.append(source)
    if not any(
        (definition := registry.get(source)) is not None and definition.supports_primary_search for source in selected
    ):
        raise SourceSelectionError(
            f"No enabled source supports retrieval mode '{retrieval_mode}'",
            available_sources=tuple(registry.list_unified_sources()),
        )
    return selected


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
    provider_neutral_query = request.query
    icd_matches: list[dict[str, Any]] = []
    expanded_query, icd_matches = detect_and_expand_icd_codes(query)
    if icd_matches:
        query = expanded_query
        provider_neutral_query = _build_provider_neutral_icd_query(
            request.query,
            icd_matches,
            semantic=request.retrieval_mode == "semantic",
        )
        logger.info("ICD-aware search planning enabled for %s code(s)", len(icd_matches))

    await progress(1, 10, "Analyzing query...")
    analyzer = analyzer_factory()
    analysis = analyzer.analyze(query)
    logger.info("Query analysis: complexity=%s, intent=%s", analysis.complexity.value, analysis.intent.value)

    enhanced_query: EnhancedQuery | None = None
    matched_entity_names: list[str] = []
    # Explicit provider-native modes are a complete retrieval contract.  Do
    # not add an undeclared PubTator request or let process-wide entity-cache
    # state influence their ranking/query plan.
    skip_enhancement = (
        request.retrieval_mode != "auto" or analysis.complexity.value == "simple" or analysis.intent.value == "lookup"
    )

    if skip_enhancement:
        logger.info("Skipping semantic enhancement for the selected retrieval policy")
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
            logger.debug("Semantic enhancement skipped (%s)", type(exc).__name__)

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

    # options="preprints" → first-class merge of arXiv/medRxiv/bioRxiv into
    # main aggregation (deduped against published versions via DOI/title).
    # Only inject when the user didn't already select them explicitly.
    if request.include_preprints:
        preprint_keys = ("arxiv", "medrxiv", "biorxiv")
        for key in preprint_keys:
            if registry.is_enabled(key) and key not in dispatch_sources:
                dispatch_sources.append(key)

    dispatch_sources = _apply_retrieval_capabilities(
        request=request,
        dispatch_sources=dispatch_sources,
        registry=registry,
    )

    deep_strategies = _build_deep_strategies(
        query=query,
        provider_neutral_query=provider_neutral_query,
        enhanced_query=enhanced_query,
        dispatch_sources=dispatch_sources,
        registry=registry,
    )

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
        provider_neutral_query=provider_neutral_query,
        analysis=analysis,
        icd_matches=icd_matches,
        enhanced_query=enhanced_query,
        deep_strategies=deep_strategies,
        matched_entity_names=matched_entity_names,
        user_sources=user_sources,
        dispatch_sources=dispatch_sources,
        ranking_config=ranking_config,
        effective_min_year=request.min_year or analysis.year_from,
        effective_max_year=request.max_year or analysis.year_to,
    )


__all__ = [
    "UnifiedSearchPlan",
    "_apply_retrieval_capabilities",
    "_build_deep_strategies",
    "build_unified_search_plan",
    "ProgressReporter",
    "SourceSelectionError",
]
