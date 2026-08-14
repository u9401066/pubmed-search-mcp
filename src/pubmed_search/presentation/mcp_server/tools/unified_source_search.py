"""
Unified Search — Source Search & Deep Search Module.

Contains per-source search functions (_search_pubmed, _search_openalex, etc.),
deep multi-strategy search execution, and auto-relaxation logic.

Extracted from unified.py to keep each module under 400 lines.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Literal, NoReturn, cast

from pubmed_search.application.search.semantic_enhancer import (
    EnhancedQuery,
    SearchPlan,
)
from pubmed_search.domain.services.article_mapper import (
    article_from_core,
    article_from_europe_pmc,
    article_from_openalex,
    article_from_preprint,
    article_from_pubmed,
    article_from_scopus,
    article_from_semantic_scholar,
    article_from_web_of_science,
)
from pubmed_search.infrastructure.sources import (
    get_core_client,
    get_europe_pmc_client,
    get_last_alternate_source_error,
    get_openalex_client,
    get_scopus_client,
    get_semantic_scholar_client,
    get_web_of_science_client,
    search_alternate_source,
    search_alternate_source_page,
)
from pubmed_search.infrastructure.sources.base_client import APIRequestError
from pubmed_search.shared.async_utils import RetryableOperationError
from pubmed_search.shared.source_contracts import (
    SourceAdapterError,
    SourceAdapterResult,
    normalize_source_adapter_error,
)

from .unified_helpers import (
    RelaxationResult,
    SearchDepthMetrics,
    StrategyResult,
    _generate_relaxation_steps,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from pubmed_search.application.search.source_models import SourceSearchPage
    from pubmed_search.domain.entities.article import UnifiedArticle
    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)
DEEP_SEARCH_STRATEGY_TIMEOUT_SECONDS = 25.0
DEEP_SEARCH_MAX_CONCURRENCY = 4
DEEP_SEARCH_PER_SOURCE_CONCURRENCY = 1
ProviderRetrievalMode = Literal["auto", "semantic", "systematic"]


def _raise_if_semantic_scholar_rate_limited(error: SourceAdapterError | None) -> None:
    if error and error.status_code == 429:
        raise RetryableOperationError(error.message, status_code=error.status_code)


def _sanitized_search_exception(service: str, error: Exception) -> Exception:
    """Return a query-safe exception while preserving retry metadata."""

    if isinstance(error, RetryableOperationError):
        return RetryableOperationError(
            f"{service} search failed",
            retry_after=error.retry_after,
            status_code=error.status_code,
        )
    if isinstance(error, APIRequestError):
        return APIRequestError(service, status_code=error.status_code)
    return APIRequestError(service)


def _raise_sanitized_search_error(service: str, error: Exception) -> NoReturn:
    """Raise a query-safe error while preserving retry metadata."""

    raise _sanitized_search_exception(service, error) from None


def _require_result_list(value: object, *, service: str) -> list[Any]:
    """Validate one provider result list without exposing its response body."""

    if isinstance(value, list):
        return value
    raise APIRequestError(service)


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
                strict=True,
                **step.advanced_filters,
            )
            step.result_count = len(articles)
            result.steps_tried.append(step)

            if articles:
                result.successful_step = step
                result.relaxed_query = step.query
                result.total_results = total_count or len(articles)
                result.articles = articles
                logger.info(f"Auto-relaxation succeeded at level {step.level} ({step.action}): {len(articles)} results")
                return result

            logger.debug(f"Relaxation level {step.level} ({step.action}): still 0 results")

        except Exception as exc:
            logger.warning("Relaxation level %s failed (%s)", step.level, type(exc).__name__)
            step.result_count = 0
            result.steps_tried.append(step)

    # All steps tried, still 0 results
    return result


# ============================================================================
# Deep Multi-Strategy Search
# ============================================================================


def _allocate_deep_strategy_budgets(
    strategies: list[SearchPlan],
    *,
    per_source_limit: int,
) -> list[int]:
    """Allocate one public per-source limit across that source's strategies.

    ``unified_search(limit=N)`` promises a source budget, not ``N`` requests
    for every semantic variant.  Allocation is stable because callers sort by
    priority before invoking this helper; any remainder goes to earlier
    (higher-priority) strategies.
    """

    if per_source_limit < 1:
        msg = "per_source_limit must be positive"
        raise ValueError(msg)

    indices_by_source: dict[str, list[int]] = {}
    for index, strategy in enumerate(strategies):
        indices_by_source.setdefault(strategy.source, []).append(index)

    budgets = [0] * len(strategies)
    for indices in indices_by_source.values():
        base, remainder = divmod(per_source_limit, len(indices))
        for position, index in enumerate(indices):
            budgets[index] = base + (1 if position < remainder else 0)
    return budgets


def _default_deep_search_functions(searcher: LiteratureSearcher) -> dict[str, Any]:
    """Return the same typed source adapters used by shallow execution."""

    return {
        "pubmed": lambda query, limit, min_year, max_year, options: _search_pubmed_adapter(
            searcher,
            query,
            limit,
            min_year,
            max_year,
            options,
        ),
        "europe_pmc": _search_europe_pmc_adapter,
        "openalex": _search_openalex_adapter,
        "semantic_scholar": _search_semantic_scholar_adapter,
        "core": _search_core_adapter,
        "scopus": _search_scopus_adapter,
        "web_of_science": _search_web_of_science_adapter,
        "arxiv": _search_arxiv_adapter,
        "medrxiv": _search_medrxiv_adapter,
        "biorxiv": _search_biorxiv_adapter,
    }


def _coerce_deep_adapter_result(
    *,
    source: str,
    outcome: Any,
) -> SourceAdapterResult[UnifiedArticle]:
    """Keep injected legacy tuple runners compatible at the typed seam."""

    if isinstance(outcome, SourceAdapterResult):
        return outcome
    if isinstance(outcome, tuple) and len(outcome) == 2:
        articles = list(outcome[0])
        total = outcome[1] if isinstance(outcome[1], int) and not isinstance(outcome[1], bool) else None
        return SourceAdapterResult(
            source=source,
            operation="deep_search",
            items=articles,
            total_count=total if total is not None else len(articles),
            status="ok" if articles else "empty",
            metadata={"total_available": total},
        )
    msg = f"Deep-search adapter for '{source}' must return SourceAdapterResult"
    raise TypeError(msg)


def _require_deep_runner(runners: Mapping[str, Any], source: str) -> Any:
    runner = runners.get(source)
    if runner is None:
        msg = f"No deep-search adapter is registered for source '{source}'"
        raise ValueError(msg)
    return runner


async def _execute_deep_search(
    searcher: LiteratureSearcher,
    enhanced_query: EnhancedQuery,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict,
    *,
    strategies: list[SearchPlan] | None = None,
    search_functions: Mapping[str, Any] | None = None,
    max_concurrency: int = DEEP_SEARCH_MAX_CONCURRENCY,
    per_source_concurrency: int = DEEP_SEARCH_PER_SOURCE_CONCURRENCY,
    strategy_timeout: float = DEEP_SEARCH_STRATEGY_TIMEOUT_SECONDS,
) -> tuple[
    list[list[UnifiedArticle]],
    SearchDepthMetrics,
    int | None,
    dict[str, tuple[int, int | None]],
    list[SourceAdapterError],
]:
    """
    Execute true deep search using ALL strategies from SemanticEnhancer.

    This is the core of "deep search" - we don't just throw keywords at API,
    we execute multiple semantically-aware strategies in parallel.

    Args:
        searcher: PubMed searcher instance
        enhanced_query: Result from SemanticEnhancer with entities and strategies
        limit: Max aggregate results requested from each source
        min_year, max_year: Year filters
        advanced_filters: Additional PubMed filters

    Returns:
        Tuple of (all_results, depth_metrics, pubmed_total_count, source_api_counts, source_errors)
    """
    import time

    metrics = SearchDepthMetrics()

    # Populate metrics from enhanced_query
    metrics.entities_resolved = len(enhanced_query.entities)
    metrics.mesh_terms_used = len([e for e in enhanced_query.entities if e.mesh_id])
    metrics.synonyms_expanded = len([t for t in enhanced_query.expanded_terms if t.source != "original"])

    all_results: list[list[UnifiedArticle]] = []
    pubmed_total_count: int | None = None
    source_errors: list[SourceAdapterError] = []
    # Execute each strategy.  EnhancedQuery is still accepted for backwards
    # compatibility, while the planner normally supplies its finalized list.
    strategies = (
        strategies
        or enhanced_query.strategies
        or [
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
    )
    metrics.strategies_generated = len(strategies)

    # Sort by priority (highest first)
    strategies = sorted(strategies, key=lambda s: s.priority, reverse=True)
    strategy_budgets = _allocate_deep_strategy_budgets(strategies, per_source_limit=limit)
    runners = dict(search_functions or _default_deep_search_functions(searcher))
    global_semaphore = asyncio.Semaphore(max(1, max_concurrency))
    source_semaphores = {
        source: asyncio.Semaphore(max(1, per_source_concurrency)) for source in {s.source for s in strategies}
    }
    attempt_started = [False] * len(strategies)

    async def execute_strategy(
        index: int,
        strategy: SearchPlan,
        allocated_limit: int,
    ) -> tuple[StrategyResult, list[UnifiedArticle], list[SourceAdapterError]]:
        """Execute one typed adapter attempt and retain exact provenance."""
        start_time = time.perf_counter()
        if allocated_limit <= 0:
            return (
                StrategyResult(
                    strategy_name=strategy.name,
                    query=strategy.query,
                    source=strategy.source,
                    articles_count=0,
                    expected_precision=strategy.expected_precision,
                    expected_recall=strategy.expected_recall,
                    status="skipped_budget",
                    allocated_limit=0,
                    query_executed=False,
                    metadata={"skip_reason": "per_source_budget_exhausted"},
                ),
                [],
                [],
            )

        try:
            runner = _require_deep_runner(runners, strategy.source)
            options = dict(advanced_filters)
            options["_retrieval_mode"] = "auto"
            # Acquire the source gate first so queued variants from one
            # provider cannot occupy every global slot and starve other APIs.
            async with source_semaphores[strategy.source], global_semaphore:
                attempt_started[index] = True
                raw_outcome = await runner(
                    strategy.query,
                    allocated_limit,
                    min_year,
                    max_year,
                    options,
                )
            adapter_result = _coerce_deep_adapter_result(source=strategy.source, outcome=raw_outcome)
        except Exception as exc:
            logger.warning("Strategy '%s' failed (%s)", strategy.name, type(exc).__name__)
            source_error = normalize_source_adapter_error(strategy.source, "deep_search", exc)
            adapter_result = SourceAdapterResult.failure(
                source=strategy.source,
                operation="deep_search",
                error=source_error,
                metadata={
                    "logical_query": strategy.query,
                    "physical_query": None,
                    "query_executed": attempt_started[index],
                },
            )

        metadata = dict(adapter_result.metadata)
        metadata.setdefault("logical_query", strategy.query)
        metadata.setdefault("query_executed", adapter_result.status != "error")
        if "physical_query" not in metadata:
            metadata["physical_query"] = (
                metadata.get("canonical_query") or strategy.query if metadata["query_executed"] else None
            )
        metadata["allocated_limit"] = allocated_limit
        if adapter_result.errors:
            metadata["errors"] = [
                {
                    "kind": error.kind,
                    "retryable": error.retryable,
                    "status_code": error.status_code,
                    "message": error.message,
                }
                for error in adapter_result.errors
            ]

        articles = list(adapter_result.items[:allocated_limit])
        if len(adapter_result.items) > allocated_limit:
            warnings = metadata.setdefault("warnings", [])
            if isinstance(warnings, list):
                warnings.append(
                    "Adapter returned more items than its allocated deep-search budget; results were clipped"
                )
        raw_total = metadata.get("total_available")
        if "total_available" not in metadata and adapter_result.status != "error":
            # ``total_count`` is part of the typed adapter contract.  Adapter
            # metadata may add provider-specific detail, but deep execution
            # must not require the same count to be duplicated there.
            raw_total = adapter_result.total_count
            metadata["total_available"] = raw_total
        total_available = raw_total if isinstance(raw_total, int) and not isinstance(raw_total, bool) else None

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        result = StrategyResult(
            strategy_name=strategy.name,
            query=strategy.query,
            source=strategy.source,
            articles_count=len(articles),
            expected_precision=strategy.expected_precision,
            expected_recall=strategy.expected_recall,
            execution_time_ms=elapsed_ms,
            status=adapter_result.status,
            allocated_limit=allocated_limit,
            total_available=total_available,
            physical_query=metadata.get("physical_query") if isinstance(metadata.get("physical_query"), str) else None,
            query_executed=metadata.get("query_executed") is True,
            metadata=metadata,
        )

        return result, articles, list(adapter_result.errors)

    # The timeout encloses semaphore wait plus I/O, so queued lower-priority
    # variants cannot extend the broker's wall-clock budget indefinitely.
    tasks = [
        asyncio.wait_for(execute_strategy(index, strategy, strategy_budgets[index]), timeout=strategy_timeout)
        for index, strategy in enumerate(strategies)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for index, (strategy, result) in enumerate(zip(strategies, results)):
        if isinstance(result, BaseException):
            if isinstance(result, asyncio.CancelledError):
                source_error = SourceAdapterError(
                    source=strategy.source,
                    operation="deep_search",
                    message="Strategy was cancelled",
                    kind="timeout",
                    retryable=True,
                )
            elif isinstance(result, Exception):
                source_error = normalize_source_adapter_error(strategy.source, "deep_search", result)
            else:
                raise result
            source_errors.append(source_error)
            metrics.strategy_results.append(
                StrategyResult(
                    strategy_name=strategy.name,
                    query=strategy.query,
                    source=strategy.source,
                    articles_count=0,
                    expected_precision=strategy.expected_precision,
                    expected_recall=strategy.expected_recall,
                    execution_time_ms=strategy_timeout * 1000,
                    status="error",
                    allocated_limit=strategy_budgets[index],
                    physical_query=None,
                    query_executed=attempt_started[index],
                    metadata={
                        "logical_query": strategy.query,
                        "physical_query": None,
                        "query_executed": attempt_started[index],
                        "allocated_limit": strategy_budgets[index],
                        "errors": [
                            {
                                "kind": source_error.kind,
                                "retryable": source_error.retryable,
                                "status_code": source_error.status_code,
                                "message": source_error.message,
                            }
                        ],
                    },
                )
            )
            metrics.strategies_executed += 1
            continue

        strategy_result, articles, attempt_errors = result
        metrics.strategy_results.append(strategy_result)
        if strategy_result.status != "skipped_budget":
            metrics.strategies_executed += 1
        source_errors.extend(attempt_errors)

        if (
            strategy_result.source == "pubmed"
            and strategy_result.total_available is not None
            and pubmed_total_count is None
        ):
            pubmed_total_count = strategy_result.total_available

        if articles:
            all_results.append(articles)
            metrics.strategies_with_results += 1

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

    # Aggregate bounded per-source counts. Totals from different query
    # variants are not additive; only expose one when exactly one attempt ran.
    source_api_counts: dict[str, tuple[int, int | None]] = {}
    for source in {strategy.source for strategy in strategies}:
        source_attempts = [
            result
            for result in metrics.strategy_results
            if result.source == source and result.status != "skipped_budget"
        ]
        returned = sum(result.articles_count for result in source_attempts)
        total_available = source_attempts[0].total_available if len(source_attempts) == 1 else None
        source_api_counts[source] = (returned, total_available)

    return all_results, metrics, pubmed_total_count, source_api_counts, source_errors


# ============================================================================
# Source Search Functions
# ============================================================================


async def _search_europe_pmc(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    *,
    strict: bool = False,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search Europe PMC and convert to UnifiedArticle.

    Europe PMC's normalized format is close to PubMed, but deterministic mapping
    lives in domain/services/article_mapper.py behind the compatibility wrapper.
    """
    try:
        if strict:
            result = await get_europe_pmc_client().search(
                query=query,
                limit=limit,
                min_year=min_year,
                max_year=max_year,
                strict=True,
            )
            results = result.get("results", [])
        else:
            results = await search_alternate_source(
                query=query,
                source="europe_pmc",
                limit=limit,
                min_year=min_year,
                max_year=max_year,
            )

        articles = []
        for r in results:
            try:
                article = article_from_europe_pmc(r)
                articles.append(article)
            except Exception as exc:
                logger.warning("Failed to convert Europe PMC result (%s)", type(exc).__name__)
                if strict:
                    raise APIRequestError("Europe PMC") from None

        raw_total = result.get("hit_count") if strict else None
        total_count = raw_total if isinstance(raw_total, int) and not isinstance(raw_total, bool) else None
        return articles, total_count
    except Exception as exc:
        logger.warning("Europe PMC search failed (%s)", type(exc).__name__)
        if strict:
            _raise_sanitized_search_error("Europe PMC", exc)
        return [], None


async def _search_europe_pmc_adapter(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict[str, Any],
) -> SourceAdapterResult[UnifiedArticle]:
    """Search Europe PMC once while preserving counts and continuation metadata."""

    try:
        result = await get_europe_pmc_client().search(
            query=query,
            limit=limit,
            min_year=min_year,
            max_year=max_year,
            strict=True,
        )
        results = _require_result_list(result.get("results", []), service="Europe PMC")
        articles = [article_from_europe_pmc(item) for item in results if isinstance(item, dict)]
        raw_total = result.get("hit_count")
        total_count = raw_total if isinstance(raw_total, int) and not isinstance(raw_total, bool) else None
        next_cursor = result.get("next_cursor")
        continuation_available = bool(next_cursor) and (total_count is None or len(articles) < total_count)
        return SourceAdapterResult(
            source="europe_pmc",
            operation="search",
            items=articles,
            total_count=total_count if total_count is not None else len(articles),
            status="ok" if articles else "empty",
            metadata={
                "total_available": total_count,
                "requested_mode": str(advanced_filters.get("_retrieval_mode", "auto")),
                "provider_mode": "keyword",
                "logical_query": query,
                "physical_query": query,
                "query_executed": True,
                "continuation_available": continuation_available,
                "next_cursor": str(next_cursor) if continuation_available else None,
                "warnings": [],
            },
        )
    except Exception as exc:
        logger.warning("Europe PMC search failed (%s)", type(exc).__name__)
        _raise_sanitized_search_error("Europe PMC", exc)


async def _search_pubmed(
    searcher: LiteratureSearcher,
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    strict: bool = False,
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
    result = await _search_pubmed_adapter(
        searcher,
        query,
        limit,
        min_year,
        max_year,
        advanced_filters,
        fail_on_error=strict,
    )
    if result.errors and strict:
        _raise_sanitized_search_error("PubMed", APIRequestError("PubMed"))
    return result.items, result.metadata.get("total_available")


async def _search_pubmed_adapter(
    searcher: LiteratureSearcher,
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict[str, Any],
    *,
    fail_on_error: bool = True,
) -> SourceAdapterResult[UnifiedArticle]:
    """Search PubMed while retaining the exact query executed by NCBI.

    ``SearchMixin`` returns this safe execution metadata with its legacy list
    payload.  Keeping extraction at the adapter boundary avoids teaching the
    MCP orchestration layer how PubMed compiles filters or corrections.
    """

    metadata: dict[str, Any] = {
        "total_available": None,
        "requested_mode": str(advanced_filters.get("_retrieval_mode", "auto")),
        "provider_mode": "keyword",
        "logical_query": query,
        "physical_query": None,
        "query_executed": False,
        "warnings": [],
    }
    search_filters = {key: value for key, value in advanced_filters.items() if not key.startswith("_")}
    try:
        raw_results = await searcher.search(
            query=query,
            limit=limit,
            min_year=min_year,
            max_year=max_year,
            **search_filters,
        )
        results = [dict(item) if isinstance(item, dict) else item for item in raw_results]

        if results and isinstance(results[0], dict):
            raw_metadata = results[0].pop("_search_metadata", None)
            if isinstance(raw_metadata, dict):
                raw_total = raw_metadata.get("total_count")
                metadata["total_available"] = (
                    raw_total if isinstance(raw_total, int) and not isinstance(raw_total, bool) else None
                )
                raw_physical_query = raw_metadata.get("physical_query")
                raw_executed = raw_metadata.get("query_executed") is True
                metadata["query_executed"] = raw_executed
                metadata["physical_query"] = (
                    raw_physical_query if raw_executed and isinstance(raw_physical_query, str) else None
                )
            if not results[0]:
                results = results[1:]

        if fail_on_error and any(isinstance(item, dict) and "error" in item for item in results):
            _raise_sanitized_search_error("PubMed", APIRequestError("PubMed"))

        articles = [
            article_from_pubmed(item) for item in results if isinstance(item, dict) and item and "error" not in item
        ]
        total_available = metadata["total_available"]
        return SourceAdapterResult(
            source="pubmed",
            operation="search",
            items=articles,
            total_count=total_available if isinstance(total_available, int) else len(articles),
            status="ok" if articles else "empty",
            metadata=metadata,
        )
    except Exception as exc:
        logger.warning("PubMed search failed (%s)", type(exc).__name__)
        return SourceAdapterResult.failure(
            source="pubmed",
            operation="search",
            error=normalize_source_adapter_error(
                "pubmed",
                "search",
                _sanitized_search_exception("PubMed", exc),
            ),
            metadata=metadata,
        )


async def _search_openalex(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    *,
    strict: bool = False,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search OpenAlex and convert to UnifiedArticle.

    Returns:
        Tuple of (articles, total_count).
    """
    try:
        page = await search_alternate_source_page(
            query=query,
            source="openalex",
            limit=limit,
            min_year=min_year,
            max_year=max_year,
        )

        articles = [article_from_openalex(provider_dto) for provider_dto in page.items]
        return articles, page.total
    except Exception as exc:
        logger.warning("OpenAlex search failed (%s)", type(exc).__name__)
        if strict:
            _raise_sanitized_search_error("OpenAlex", exc)
        return [], None


async def _search_semantic_scholar(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    *,
    strict: bool = False,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search Semantic Scholar and convert to UnifiedArticle.

    Returns:
        Tuple of (articles, total_count).
    """
    try:
        page = await search_alternate_source_page(
            query=query,
            source="semantic_scholar",
            limit=limit,
            min_year=min_year,
            max_year=max_year,
        )
        source_error = get_last_alternate_source_error("semantic_scholar")
        _raise_if_semantic_scholar_rate_limited(source_error)

        articles = [article_from_semantic_scholar(provider_dto) for provider_dto in page.items]
        return articles, page.total
    except Exception as exc:
        logger.warning("Semantic Scholar search failed (%s)", type(exc).__name__)
        if strict or isinstance(exc, RetryableOperationError):
            _raise_sanitized_search_error("Semantic Scholar", exc)
        return [], None


def _page_adapter_result(
    *,
    source: str,
    logical_query: str,
    page: SourceSearchPage[dict[str, Any]],
    mapper: Callable[[dict[str, Any]], UnifiedArticle],
    requested_mode: ProviderRetrievalMode,
    unsupported_filters: list[str] | None = None,
) -> SourceAdapterResult[UnifiedArticle]:
    """Map one raw provider page exactly once and retain safe provenance."""

    articles = [mapper(provider_dto) for provider_dto in page.items]
    warnings = list(page.warnings)
    if unsupported_filters:
        warnings.append(f"{source} does not apply PubMed-only filter(s): {', '.join(sorted(unsupported_filters))}")
    metadata: dict[str, Any] = {
        "total_available": page.total,
        "requested_mode": requested_mode,
        "provider_mode": page.mode,
        "logical_query": logical_query,
        "physical_query": page.metadata.get("physical_query") or page.query or logical_query,
        "query_executed": True,
        "canonical_query": page.query,
        "continuation_available": bool(page.next_token is not None or page.cursor),
        "warnings": warnings,
    }
    if page.next_token is not None:
        metadata["next_token"] = page.next_token
    if page.cursor:
        metadata["cursor"] = page.cursor
    if page.cost is not None:
        metadata["cost_usd"] = page.cost
    for key in (
        "pages_fetched",
        "bounded",
        "sort",
        "offset",
        "rate_limit",
        "logical_query",
        "physical_query",
    ):
        if key in page.metadata:
            metadata[key] = page.metadata[key]

    return SourceAdapterResult(
        source=source,
        operation="search",
        items=articles,
        total_count=page.total if page.total is not None else len(articles),
        status="ok" if articles else "empty",
        metadata=metadata,
    )


async def _search_openalex_adapter(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    options: dict[str, Any],
) -> SourceAdapterResult[UnifiedArticle]:
    """Run the OpenAlex capability selected by the unified broker."""

    requested_mode = str(options.get("_retrieval_mode", "auto"))
    if requested_mode not in {"auto", "semantic", "systematic"}:
        raise ValueError(f"Unsupported OpenAlex retrieval mode: {requested_mode}")
    retrieval_mode = cast("ProviderRetrievalMode", requested_mode)
    client = get_openalex_client()
    if retrieval_mode == "semantic":
        page = await client.search_semantic_page(
            query,
            limit=limit,
            min_year=min_year,
            max_year=max_year,
        )
    elif retrieval_mode == "systematic":
        page = await client.search_cursor(
            query,
            max_results=limit,
            max_pages=max(1, (limit + 99) // 100),
            min_year=min_year,
            max_year=max_year,
            sort="publication_date:asc",
        )
        page.mode = "systematic"
    else:
        page = await search_alternate_source_page(
            query=query,
            source="openalex",
            limit=limit,
            min_year=min_year,
            max_year=max_year,
        )

    unsupported = [key for key in options if not key.startswith("_")]
    return _page_adapter_result(
        source="openalex",
        logical_query=query,
        page=page,
        mapper=article_from_openalex,
        requested_mode=retrieval_mode,
        unsupported_filters=unsupported,
    )


async def _search_semantic_scholar_adapter(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    options: dict[str, Any],
) -> SourceAdapterResult[UnifiedArticle]:
    """Run relevance or deterministic bulk search behind unified_search."""

    requested_mode = str(options.get("_retrieval_mode", "auto"))
    if requested_mode not in {"auto", "semantic", "systematic"}:
        raise ValueError(f"Unsupported Semantic Scholar retrieval mode: {requested_mode}")
    retrieval_mode = cast("ProviderRetrievalMode", requested_mode)
    if retrieval_mode == "systematic":
        from pubmed_search.infrastructure.sources.semantic_scholar import (
            compile_semantic_scholar_bulk_query,
        )

        physical_query = compile_semantic_scholar_bulk_query(query)
        page = await get_semantic_scholar_client().bulk_search(
            physical_query,
            max_results=limit,
            max_pages=max(1, (limit + 999) // 1_000),
            min_year=min_year,
            max_year=max_year,
            sort="paperId",
        )
        page.metadata["logical_query"] = query
        page.metadata["physical_query"] = physical_query
    else:
        page = await search_alternate_source_page(
            query=query,
            source="semantic_scholar",
            limit=limit,
            min_year=min_year,
            max_year=max_year,
        )
        if retrieval_mode == "semantic":
            page.warnings.append("Semantic Scholar has no native semantic mode contract; relevance search was used")

    source_error = get_last_alternate_source_error("semantic_scholar")
    _raise_if_semantic_scholar_rate_limited(source_error)
    unsupported = [key for key in options if not key.startswith("_")]
    return _page_adapter_result(
        source="semantic_scholar",
        logical_query=query,
        page=page,
        mapper=article_from_semantic_scholar,
        requested_mode=retrieval_mode,
        unsupported_filters=unsupported,
    )


async def _search_core(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    *,
    strict: bool = False,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search CORE and convert to UnifiedArticle.

    Returns:
        Tuple of (articles, total_count).
    """
    try:
        client = get_core_client()
        if strict:
            result = await client.search(
                query=query,
                limit=limit,
                year_from=min_year,
                year_to=max_year,
                strict=True,
            )
        else:
            result = await client.search(
                query=query,
                limit=limit,
                year_from=min_year,
                year_to=max_year,
            )

        articles = []
        for r in result.get("results", []):
            articles.append(article_from_core(r))

        return articles, result.get("total_hits")
    except Exception as exc:
        logger.warning("CORE search failed (%s)", type(exc).__name__)
        if strict:
            _raise_sanitized_search_error("CORE", exc)
        return [], None


async def _search_core_adapter(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict[str, Any],
) -> SourceAdapterResult[UnifiedArticle]:
    """Search CORE with the exact provider-compiled query in provenance."""

    metadata: dict[str, Any] = {
        "total_available": None,
        "requested_mode": str(advanced_filters.get("_retrieval_mode", "auto")),
        "provider_mode": "keyword",
        "logical_query": query,
        "physical_query": None,
        "query_executed": False,
        "warnings": [],
    }
    try:
        client = get_core_client()
        physical_query = client.compile_query(
            query,
            year_from=min_year,
            year_to=max_year,
        )
    except Exception as exc:
        return SourceAdapterResult.failure(
            source="core",
            operation="search",
            error=normalize_source_adapter_error(
                "core",
                "search",
                _sanitized_search_exception("CORE", exc),
            ),
            metadata=metadata,
        )

    metadata["physical_query"] = physical_query
    metadata["query_executed"] = True
    try:
        result = await client.search(
            query=query,
            limit=limit,
            year_from=min_year,
            year_to=max_year,
            strict=True,
        )
        raw_results = _require_result_list(result.get("results", []), service="CORE")
        articles = [article_from_core(item) for item in raw_results if isinstance(item, dict)]
        raw_total = result.get("total_hits")
        total_available = raw_total if isinstance(raw_total, int) and not isinstance(raw_total, bool) else None
        metadata["total_available"] = total_available
        return SourceAdapterResult(
            source="core",
            operation="search",
            items=articles,
            total_count=total_available if total_available is not None else len(articles),
            status="ok" if articles else "empty",
            metadata=metadata,
        )
    except Exception as exc:
        logger.warning("CORE search failed (%s)", type(exc).__name__)
        return SourceAdapterResult.failure(
            source="core",
            operation="search",
            error=normalize_source_adapter_error(
                "core",
                "search",
                _sanitized_search_exception("CORE", exc),
            ),
            metadata=metadata,
        )


async def _search_scopus(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    *,
    strict: bool = False,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search Scopus and convert to UnifiedArticle."""
    try:
        if strict:
            results = await get_scopus_client().search(
                query=query,
                limit=limit,
                min_year=min_year,
                max_year=max_year,
                strict=True,
            )
        else:
            results = await search_alternate_source(
                query=query,
                source="scopus",
                limit=limit,
                min_year=min_year,
                max_year=max_year,
            )

        articles = []
        for r in results:
            articles.append(article_from_scopus(r))

        return articles, None
    except Exception as exc:
        logger.warning("Scopus search failed (%s)", type(exc).__name__)
        if strict:
            _raise_sanitized_search_error("Scopus", exc)
        return [], None


async def _search_scopus_adapter(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict[str, Any],
) -> SourceAdapterResult[UnifiedArticle]:
    """Run the implemented one-page Scopus keyword contract with provenance."""

    client = get_scopus_client()
    base_metadata: dict[str, Any] = {
        "total_available": None,
        "requested_mode": str(advanced_filters.get("_retrieval_mode", "auto")),
        "provider_mode": "keyword",
        "logical_query": query,
        "continuation_available": None,
        "warnings": [],
    }
    try:
        physical_query = client.compile_query(
            query,
            min_year=min_year,
            max_year=max_year,
            open_access_only=False,
        )
    except Exception as exc:
        metadata = {**base_metadata, "physical_query": None, "query_executed": False}
        return SourceAdapterResult.failure(
            source="scopus",
            operation="search",
            error=normalize_source_adapter_error(
                "scopus",
                "search",
                _sanitized_search_exception("Scopus", exc),
            ),
            metadata=metadata,
        )

    try:
        results = await client.search(
            query=query,
            limit=limit,
            min_year=min_year,
            max_year=max_year,
            strict=True,
        )
        articles = [article_from_scopus(item) for item in results]
        return SourceAdapterResult(
            source="scopus",
            operation="search",
            items=articles,
            total_count=len(articles),
            status="ok" if articles else "empty",
            metadata={
                **base_metadata,
                "physical_query": physical_query,
                "query_executed": True,
            },
        )
    except Exception as exc:
        logger.warning("Scopus search failed (%s)", type(exc).__name__)
        return SourceAdapterResult.failure(
            source="scopus",
            operation="search",
            error=normalize_source_adapter_error(
                "scopus",
                "search",
                _sanitized_search_exception("Scopus", exc),
            ),
            metadata={
                **base_metadata,
                "physical_query": physical_query,
                "query_executed": True,
            },
        )


async def _search_web_of_science(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    *,
    strict: bool = False,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search Web of Science and convert to UnifiedArticle."""
    try:
        if strict:
            results = await get_web_of_science_client().search(
                query=query,
                limit=limit,
                min_year=min_year,
                max_year=max_year,
                strict=True,
            )
        else:
            results = await search_alternate_source(
                query=query,
                source="web_of_science",
                limit=limit,
                min_year=min_year,
                max_year=max_year,
            )

        articles = []
        for r in results:
            articles.append(article_from_web_of_science(r))

        return articles, None
    except Exception as exc:
        logger.warning("Web of Science search failed (%s)", type(exc).__name__)
        if strict:
            _raise_sanitized_search_error("Web of Science", exc)
        return [], None


async def _search_web_of_science_adapter(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict[str, Any],
) -> SourceAdapterResult[UnifiedArticle]:
    """Run the implemented one-page Web of Science keyword contract with provenance."""

    client = get_web_of_science_client()
    base_metadata: dict[str, Any] = {
        "total_available": None,
        "requested_mode": str(advanced_filters.get("_retrieval_mode", "auto")),
        "provider_mode": "keyword",
        "logical_query": query,
        "continuation_available": None,
        "warnings": [],
    }
    try:
        physical_query = client.compile_query(
            query,
            min_year=min_year,
            max_year=max_year,
            open_access_only=False,
        )
    except Exception as exc:
        metadata = {**base_metadata, "physical_query": None, "query_executed": False}
        return SourceAdapterResult.failure(
            source="web_of_science",
            operation="search",
            error=normalize_source_adapter_error(
                "web_of_science",
                "search",
                _sanitized_search_exception("Web of Science", exc),
            ),
            metadata=metadata,
        )

    try:
        results = await client.search(
            query=query,
            limit=limit,
            min_year=min_year,
            max_year=max_year,
            strict=True,
        )
        articles = [article_from_web_of_science(item) for item in results]
        return SourceAdapterResult(
            source="web_of_science",
            operation="search",
            items=articles,
            total_count=len(articles),
            status="ok" if articles else "empty",
            metadata={
                **base_metadata,
                "physical_query": physical_query,
                "query_executed": True,
            },
        )
    except Exception as exc:
        logger.warning("Web of Science search failed (%s)", type(exc).__name__)
        return SourceAdapterResult.failure(
            source="web_of_science",
            operation="search",
            error=normalize_source_adapter_error(
                "web_of_science",
                "search",
                _sanitized_search_exception("Web of Science", exc),
            ),
            metadata={
                **base_metadata,
                "physical_query": physical_query,
                "query_executed": True,
            },
        )


# ============================================================================
# Preprint Source Runners (arXiv / medRxiv / bioRxiv)
# ============================================================================


def _filter_preprints_by_year(
    articles: list[UnifiedArticle],
    min_year: int | None,
    max_year: int | None,
) -> list[UnifiedArticle]:
    """Apply year-range filter client-side (preprint APIs do not all support it)."""
    if min_year is None and max_year is None:
        return articles
    result: list[UnifiedArticle] = []
    for art in articles:
        if art.year is None:
            result.append(art)
            continue
        if min_year is not None and art.year < min_year:
            continue
        if max_year is not None and art.year > max_year:
            continue
        result.append(art)
    return result


async def _search_preprint_source(
    source: str,
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    *,
    strict: bool = False,
) -> tuple[list[UnifiedArticle], int | None]:
    """Shared runner for arxiv / medrxiv / biorxiv."""
    result = await _search_preprint_source_adapter(source, query, limit, min_year, max_year, {})
    if result.errors and strict:
        _raise_sanitized_search_error(source, APIRequestError(source))
    return result.items, None


async def _search_preprint_source_adapter(
    source: str,
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict[str, Any],
) -> SourceAdapterResult[UnifiedArticle]:
    """Search one preprint source with provider and local-filter provenance."""

    from pubmed_search.infrastructure.sources.preprints import (
        ARXIV_MEDICAL_CATEGORIES,
        PreprintSearcher,
        compile_arxiv_query,
        default_rxiv_date_range,
    )

    from_date: str | None = None
    to_date: str | None = None
    if source == "arxiv":
        compiled_query = compile_arxiv_query(query, ARXIV_MEDICAL_CATEGORIES)
        local_filter: dict[str, Any] = {
            "year_range": {"min": min_year, "max": max_year},
        }
    else:
        from_date, to_date = default_rxiv_date_range()
        compiled_query = f"details/{source}/{from_date}/{to_date}/0"
        local_filter = {
            "query_mode": "all_terms_case_insensitive",
            "year_range": {"min": min_year, "max": max_year},
        }

    metadata: dict[str, Any] = {
        "total_available": None,
        "requested_mode": str(advanced_filters.get("_retrieval_mode", "auto")),
        "provider_mode": "keyword" if source == "arxiv" else "date_feed_with_local_keyword_filter",
        "logical_query": query,
        "physical_query": None,
        "query_executed": False,
        "local_filter": local_filter,
        "warnings": [],
    }
    try:
        searcher = PreprintSearcher()
        metadata["physical_query"] = compiled_query
        metadata["query_executed"] = True
        results = await searcher.search(
            query=query,
            sources=[source],
            limit=limit,
            categories=ARXIV_MEDICAL_CATEGORIES if source == "arxiv" else None,
            from_date=from_date,
            to_date=to_date,
            strict=True,
        )
        by_source = results.get("by_source")
        if not isinstance(by_source, dict):
            _raise_sanitized_search_error(source, APIRequestError(source))
        items = _require_result_list(by_source.get(source, []), service=source)
        articles = [article_from_preprint(item) for item in items if isinstance(item, dict)]
        articles = _filter_preprints_by_year(articles, min_year, max_year)
        # The unified preprint seam currently has no trustworthy corpus total.
        return SourceAdapterResult(
            source=source,
            operation="search",
            items=articles,
            total_count=len(articles),
            status="ok" if articles else "empty",
            metadata=metadata,
        )
    except Exception as exc:
        logger.warning("%s search failed (%s)", source, type(exc).__name__)
        return SourceAdapterResult.failure(
            source=source,
            operation="search",
            error=normalize_source_adapter_error(
                source,
                "search",
                _sanitized_search_exception(source, exc),
            ),
            metadata=metadata,
        )


async def _search_arxiv_adapter(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict[str, Any],
) -> SourceAdapterResult[UnifiedArticle]:
    return await _search_preprint_source_adapter("arxiv", query, limit, min_year, max_year, advanced_filters)


async def _search_medrxiv_adapter(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict[str, Any],
) -> SourceAdapterResult[UnifiedArticle]:
    return await _search_preprint_source_adapter("medrxiv", query, limit, min_year, max_year, advanced_filters)


async def _search_biorxiv_adapter(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict[str, Any],
) -> SourceAdapterResult[UnifiedArticle]:
    return await _search_preprint_source_adapter("biorxiv", query, limit, min_year, max_year, advanced_filters)


async def _search_arxiv(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    *,
    strict: bool = False,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search arXiv preprints and convert to UnifiedArticle."""
    return await _search_preprint_source("arxiv", query, limit, min_year, max_year, strict=strict)


async def _search_medrxiv(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    *,
    strict: bool = False,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search medRxiv preprints and convert to UnifiedArticle."""
    return await _search_preprint_source("medrxiv", query, limit, min_year, max_year, strict=strict)


async def _search_biorxiv(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    *,
    strict: bool = False,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search bioRxiv preprints and convert to UnifiedArticle."""
    return await _search_preprint_source("biorxiv", query, limit, min_year, max_year, strict=strict)
