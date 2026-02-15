"""
Unified Search — Source Search & Deep Search Module.

Contains per-source search functions (_search_pubmed, _search_openalex, etc.),
deep multi-strategy search execution, and auto-relaxation logic.

Extracted from unified.py to keep each module under 400 lines.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from pubmed_search.application.search.semantic_enhancer import (
    EnhancedQuery,
    SearchPlan,
)
from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.infrastructure.sources import (
    get_core_client,
    search_alternate_source,
)

from .unified_helpers import (
    RelaxationResult,
    SearchDepthMetrics,
    StrategyResult,
    _generate_relaxation_steps,
)

if TYPE_CHECKING:
    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)


# ============================================================================
# Auto Search Relaxation
# ============================================================================


async def _auto_relax_search(
    searcher: LiteratureSearcher,
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict,
) -> RelaxationResult | None:
    """Progressively relax search query until results are found.

    Only re-searches PubMed (primary source) for efficiency.

    Returns:
        RelaxationResult if relaxation was attempted, None if no steps available.
    """
    steps = _generate_relaxation_steps(query, min_year, max_year, advanced_filters)

    if not steps:
        return None

    result = RelaxationResult(
        original_query=query,
        relaxed_query=query,
        steps_tried=[],
        successful_step=None,
        total_results=0,
    )

    for step in steps:
        try:
            articles, total_count = await _search_pubmed(
                searcher,
                step.query,
                limit,
                step.min_year,
                step.max_year,
                **step.advanced_filters,
            )
            step.result_count = len(articles)
            result.steps_tried.append(step)

            if articles:
                result.successful_step = step
                result.relaxed_query = step.query
                result.total_results = total_count or len(articles)
                logger.info(f"Auto-relaxation succeeded at level {step.level} ({step.action}): {len(articles)} results")
                return result

            logger.debug(f"Relaxation level {step.level} ({step.action}): still 0 results")

        except Exception as e:
            logger.warning(f"Relaxation level {step.level} failed: {e}")
            step.result_count = 0
            result.steps_tried.append(step)

    # All steps tried, still 0 results
    return result


# ============================================================================
# Deep Multi-Strategy Search
# ============================================================================


async def _execute_deep_search(
    searcher: LiteratureSearcher,
    enhanced_query: EnhancedQuery,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict,
) -> tuple[list[list[UnifiedArticle]], SearchDepthMetrics, int | None, dict[str, tuple[int, int | None]]]:
    """
    Execute true deep search using ALL strategies from SemanticEnhancer.

    This is the core of "deep search" - we don't just throw keywords at API,
    we execute multiple semantically-aware strategies in parallel.

    Args:
        searcher: PubMed searcher instance
        enhanced_query: Result from SemanticEnhancer with entities and strategies
        limit: Max results per strategy
        min_year, max_year: Year filters
        advanced_filters: Additional PubMed filters

    Returns:
        Tuple of (all_results, depth_metrics, pubmed_total_count, source_api_counts)
    """
    import time

    metrics = SearchDepthMetrics()

    # Populate metrics from enhanced_query
    metrics.entities_resolved = len(enhanced_query.entities)
    metrics.mesh_terms_used = len([e for e in enhanced_query.entities if e.mesh_id])
    metrics.synonyms_expanded = len([t for t in enhanced_query.expanded_terms if t.source != "original"])
    metrics.strategies_generated = len(enhanced_query.strategies)

    all_results: list[list[UnifiedArticle]] = []
    pubmed_total_count: int | None = None
    total_precision = 0.0
    total_recall = 0.0

    # Execute each strategy
    strategies = enhanced_query.strategies or [
        # Fallback: at least search original query
        SearchPlan(
            name="original",
            query=enhanced_query.original_query,
            source="pubmed",
            priority=1,
            expected_precision=0.5,
            expected_recall=0.5,
        )
    ]

    # Sort by priority (highest first)
    strategies = sorted(strategies, key=lambda s: s.priority, reverse=True)

    async def execute_strategy(
        strategy: SearchPlan,
    ) -> tuple[StrategyResult, list[UnifiedArticle], int | None]:
        """Execute one strategy and return results."""
        start_time = time.perf_counter()
        articles: list[UnifiedArticle] = []
        total_count: int | None = None

        try:
            if strategy.source == "pubmed":
                articles, total_count = await _search_pubmed(
                    searcher,
                    strategy.query,
                    limit,
                    min_year,
                    max_year,
                    **advanced_filters,
                )
            elif strategy.source == "europe_pmc":
                articles, total_count = await _search_europe_pmc(
                    strategy.query,
                    limit,
                    min_year,
                    max_year,
                )
            elif strategy.source == "openalex":
                articles, total_count = await _search_openalex(
                    strategy.query,
                    limit,
                    min_year,
                    max_year,
                )
            elif strategy.source == "core":
                articles, total_count = await _search_core(
                    strategy.query,
                    limit,
                    min_year,
                    max_year,
                )

        except Exception as e:
            logger.warning(f"Strategy '{strategy.name}' failed: {e}")

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        result = StrategyResult(
            strategy_name=strategy.name,
            query=strategy.query,
            source=strategy.source,
            articles_count=len(articles),
            expected_precision=strategy.expected_precision,
            expected_recall=strategy.expected_recall,
            execution_time_ms=elapsed_ms,
        )

        return result, articles, total_count

    # Execute all strategies in parallel
    tasks = [execute_strategy(s) for s in strategies]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Strategy execution error: {result}")
            continue

        # Type narrowing: result is now tuple, not Exception
        strategy_result, articles, total_count = result  # type: ignore[misc]
        metrics.strategy_results.append(strategy_result)
        metrics.strategies_executed += 1

        if articles:
            all_results.append(articles)
            metrics.strategies_with_results += 1
            total_precision += strategy_result.expected_precision
            total_recall += strategy_result.expected_recall

            # Keep first PubMed total count
            if total_count and pubmed_total_count is None:
                pubmed_total_count = total_count

    # Calculate combined metrics
    if metrics.strategies_with_results > 0:
        # Combined recall: 1 - (1-r1)(1-r2)... (probability of finding at least once)
        combined_recall = 1.0
        for sr in metrics.strategy_results:
            if sr.articles_count > 0:
                combined_recall *= 1 - sr.expected_recall
        metrics.estimated_recall = 1 - combined_recall

        # Average precision (weighted by articles found)
        total_articles = sum(sr.articles_count for sr in metrics.strategy_results)
        if total_articles > 0:
            weighted_precision = sum(sr.expected_precision * sr.articles_count for sr in metrics.strategy_results)
            metrics.estimated_precision = weighted_precision / total_articles
    else:
        metrics.estimated_recall = 0.0
        metrics.estimated_precision = 0.0

    metrics.calculate_depth_score()

    logger.info(
        f"Deep search: {metrics.strategies_executed} strategies, "
        f"{metrics.strategies_with_results} with results, "
        f"depth score: {metrics.depth_score:.0f}"
    )

    # Aggregate per-source API counts from strategies
    source_api_counts: dict[str, tuple[int, int | None]] = {}
    for sr in metrics.strategy_results:
        prev_returned, prev_total = source_api_counts.get(sr.source, (0, None))
        source_api_counts[sr.source] = (prev_returned + sr.articles_count, prev_total)

    return all_results, metrics, pubmed_total_count, source_api_counts


# ============================================================================
# Source Search Functions
# ============================================================================


async def _search_europe_pmc(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search Europe PMC and convert to UnifiedArticle.

    Europe PMC's normalized format is compatible with PubMed format,
    so we map a few fields and use from_pubmed() for conversion.
    """
    try:
        results = await search_alternate_source(
            query=query,
            source="europe_pmc",
            limit=limit,
            min_year=min_year,
            max_year=max_year,
        )

        articles = []
        for r in results:
            # Map Europe PMC fields to PubMed expected format
            if "pmc_id" in r and not r.get("pmc"):
                r["pmc"] = r["pmc_id"]
            if "journal_abbrev" in r and not r.get("source"):
                r["source"] = r["journal_abbrev"]
            # Mark as coming from Europe PMC for source tracking
            r["_source_origin"] = "europe_pmc"

            try:
                article = UnifiedArticle.from_pubmed(r)
                # Override primary source to reflect true origin
                article.primary_source = "europe_pmc"
                articles.append(article)
            except Exception as e:
                logger.warning(f"Failed to convert Europe PMC result: {e}")

        return articles, None
    except Exception as e:
        logger.exception(f"Europe PMC search failed: {e}")
        return [], None


async def _search_pubmed(
    searcher: LiteratureSearcher,
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    **advanced_filters,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search PubMed and convert to UnifiedArticle.

    Returns:
        Tuple of (articles, total_count) where total_count is the total
        number of matching articles in PubMed (not just returned count).

    Advanced Filters (passed via **advanced_filters):
        age_group: newborn, infant, child, adolescent, adult, aged, etc.
        sex: male, female
        species: humans, animals
        language: english, chinese, japanese, etc.
        clinical_query: therapy, diagnosis, prognosis, etiology
    """
    try:
        results = await searcher.search(
            query=query,
            limit=limit,
            min_year=min_year,
            max_year=max_year,
            **advanced_filters,  # Pass all advanced filters
        )

        # Extract total_count from metadata (if present)
        total_count = None
        if results and "_search_metadata" in results[0]:
            total_count = results[0]["_search_metadata"].get("total_count")
            del results[0]["_search_metadata"]
            # Remove empty dict if only metadata was present
            if not results[0] or results[0] == {}:
                results = results[1:] if len(results) > 1 else []

        articles = []
        for r in results:
            if r and "error" not in r:  # Skip error entries
                articles.append(UnifiedArticle.from_pubmed(r))

        return articles, total_count
    except Exception as e:
        logger.exception(f"PubMed search failed: {e}")
        return [], None


async def _search_openalex(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search OpenAlex and convert to UnifiedArticle.

    Returns:
        Tuple of (articles, total_count).
    """
    try:
        results = await search_alternate_source(
            query=query,
            source="openalex",
            limit=limit,
            min_year=min_year,
            max_year=max_year,
        )

        articles = []
        for r in results:
            articles.append(UnifiedArticle.from_openalex(r))

        # OpenAlex doesn't return total count in our current implementation
        return articles, None
    except Exception as e:
        logger.exception(f"OpenAlex search failed: {e}")
        return [], None


async def _search_semantic_scholar(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search Semantic Scholar and convert to UnifiedArticle.

    Returns:
        Tuple of (articles, total_count).
    """
    try:
        results = await search_alternate_source(
            query=query,
            source="semantic_scholar",
            limit=limit,
            min_year=min_year,
            max_year=max_year,
        )

        articles = []
        for r in results:
            articles.append(UnifiedArticle.from_semantic_scholar(r))

        # Semantic Scholar doesn't return total count in our current implementation
        return articles, None
    except Exception as e:
        logger.exception(f"Semantic Scholar search failed: {e}")
        return [], None


async def _search_core(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search CORE and convert to UnifiedArticle.

    Returns:
        Tuple of (articles, total_count).
    """
    try:
        client = get_core_client()
        result = await client.search(
            query=query,
            limit=limit,
            year_from=min_year,
            year_to=max_year,
        )

        articles = []
        for r in result.get("results", []):
            articles.append(UnifiedArticle.from_core(r))

        return articles, result.get("total_hits")
    except Exception as e:
        logger.exception(f"CORE search failed: {e}")
        return [], None
