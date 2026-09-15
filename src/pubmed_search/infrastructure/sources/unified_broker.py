"""
Unified Search — Source Search & Deep Search Module.

Contains typed per-source adapters, deep multi-strategy execution, and
auto-relaxation logic.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, Literal, NoReturn, cast

from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.application.unified.helpers import (
    RelaxationResult,
    SearchDepthMetrics,
    StrategyResult,
    _generate_relaxation_steps,
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
    get_openalex_client,
    get_semantic_scholar_client,
    search_alternate_source_adapter,
)
from pubmed_search.infrastructure.sources.base_client import APIRequestError
from pubmed_search.shared.async_utils import RetryableOperationError
from pubmed_search.shared.source_contracts import (
    SourceAdapterError,
    SourceAdapterResult,
    normalize_source_adapter_error,
    validate_source_adapter_mapping_result,
    validate_source_adapter_result,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from pubmed_search.application.search.semantic_enhancer import EnhancedQuery, SearchPlan
    from pubmed_search.domain.entities.article import UnifiedArticle
    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)
DEEP_SEARCH_STRATEGY_TIMEOUT_SECONDS = 25.0
DEEP_SEARCH_MAX_CONCURRENCY = 4
DEEP_SEARCH_PER_SOURCE_CONCURRENCY = 1
ProviderRetrievalMode = Literal["auto", "semantic", "systematic"]

# This name table is the single source of truth for every adapter that can be
# dispatched by unified_search.  Resolve the functions lazily from module
# globals so tests and offline harnesses can replace an adapter without
# rebuilding a second provider map in the MCP wrapper or runner.
_DEFAULT_SEARCH_ADAPTER_NAMES: dict[str, str] = {
    "pubmed": "_search_pubmed_adapter",
    "europe_pmc": "_search_europe_pmc_adapter",
    "openalex": "_search_openalex_adapter",
    "semantic_scholar": "_search_semantic_scholar_adapter",
    "core": "_search_core_adapter",
    "scopus": "_search_scopus_adapter",
    "web_of_science": "_search_web_of_science_adapter",
    "arxiv": "_search_arxiv_adapter",
    "medrxiv": "_search_medrxiv_adapter",
    "biorxiv": "_search_biorxiv_adapter",
}


def _raise_if_semantic_scholar_rate_limited(error: SourceAdapterError | None) -> None:
    if error and error.status_code == 429:
        raise RetryableOperationError(error.message, status_code=error.status_code)


def _sanitized_search_exception(service: str, error: Exception) -> Exception:
    """Return a query-safe exception while preserving retry metadata."""

    if isinstance(error, TimeoutError):
        return TimeoutError(f"{service} search timed out")
    if isinstance(error, RetryableOperationError):
        return RetryableOperationError(
            f"{service} search failed",
            retry_after=error.retry_after,
            status_code=error.status_code,
        )
    if getattr(error, "retryable", False):
        raw_retry_after = getattr(error, "retry_after", None)
        raw_status_code = getattr(error, "status_code", None)
        return RetryableOperationError(
            f"{service} search failed",
            retry_after=float(raw_retry_after) if isinstance(raw_retry_after, (int, float)) else None,
            status_code=raw_status_code if isinstance(raw_status_code, int) else None,
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
            adapter_result = validate_source_adapter_result(
                await _search_pubmed_adapter(
                    searcher,
                    step.query,
                    limit,
                    step.min_year,
                    step.max_year,
                    step.advanced_filters,
                ),
                expected_source="pubmed",
                expected_operation="search",
            )
            if adapter_result.status in {"error", "partial"}:
                # A typed adapter failure is a completed call, not a confirmed
                # zero-result response.  PubMed currently emits only ``error``
                # here; treating a future partial envelope as incomplete keeps
                # auto-relaxation fail-closed instead of silently discarding its
                # provenance error and overstating search coverage.
                step.result_count = len(adapter_result.items)
                step.status = "error"
                step.error = adapter_result.errors[0]
                result.steps_tried.append(step)
                logger.warning(
                    "Relaxation level %s returned an incomplete adapter result (%s)",
                    step.level,
                    adapter_result.status,
                )
                continue
            articles = adapter_result.items
            raw_total = adapter_result.metadata.get("total_available")
            total_count = raw_total if isinstance(raw_total, int) and not isinstance(raw_total, bool) else None
            step.result_count = len(articles)
            step.status = "ok" if articles else "empty"
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
            step.status = "error"
            step.error = normalize_source_adapter_error("pubmed", "auto_relax", exc)
            result.steps_tried.append(step)

    # Every planned step was attempted. Callers distinguish confirmed empty
    # responses from failed requests via each step's status/error.
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


def build_default_search_functions(searcher: LiteratureSearcher) -> dict[str, Any]:
    """Build the canonical source-runner map for shallow and deep execution.

    PubMed is the only adapter that needs the request-scoped
    :class:`LiteratureSearcher`; every other adapter owns its infrastructure
    client internally.  Keeping this assembly in one function prevents the
    MCP registration wrapper, SDK runner, and deep-search fallback from
    drifting as providers are added or renamed.
    """

    runners: dict[str, Any] = {}
    for source, adapter_name in _DEFAULT_SEARCH_ADAPTER_NAMES.items():
        adapter = globals().get(adapter_name)
        if not callable(adapter):
            msg = f"Unified-search adapter '{adapter_name}' for source '{source}' is not callable"
            raise TypeError(msg)
        runners[source] = partial(adapter, searcher) if source == "pubmed" else adapter
    return runners


@dataclass(slots=True)
class UnifiedSourceBroker:
    """Canonical source-runner adapter for :class:`UnifiedSearchUseCase`."""

    searcher: LiteratureSearcher
    search_functions_override: Mapping[str, Any] | None = None

    def build_search_functions(self) -> dict[str, Any]:
        """Bind one request-scoped PubMed searcher into the source catalog."""
        if self.search_functions_override is not None:
            return dict(self.search_functions_override)
        return build_default_search_functions(self.searcher)

    async def execute_deep_search(
        self,
        enhanced_query: EnhancedQuery,
        limit: int,
        min_year: int | None,
        max_year: int | None,
        advanced_filters: dict[str, Any],
        *,
        strategies: list[SearchPlan],
    ) -> tuple[
        list[list[UnifiedArticle]],
        SearchDepthMetrics,
        int | None,
        dict[str, tuple[int, int | None]],
        list[SourceAdapterError],
    ]:
        """Execute the canonical bounded deep-search strategy set."""
        return await _execute_deep_search(
            self.searcher,
            enhanced_query,
            limit,
            min_year,
            max_year,
            advanced_filters,
            strategies=strategies,
            search_functions=self.build_search_functions(),
        )

    async def auto_relax(
        self,
        query: str,
        limit: int,
        min_year: int | None,
        max_year: int | None,
        advanced_filters: dict[str, Any],
    ) -> RelaxationResult | None:
        """Run the bounded PubMed relaxation policy through this broker."""
        return await _auto_relax_search(
            self.searcher,
            query,
            limit,
            min_year,
            max_year,
            advanced_filters,
        )

    async def search_related_trials(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        """Run the optional ClinicalTrials.gov adjunct through infrastructure."""
        from pubmed_search.infrastructure.sources.clinical_trials import search_related_trials

        return await search_related_trials(query, limit=limit)


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
    strategies: list[SearchPlan],
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
    if not strategies:
        raise ValueError("Deep search requires at least one finalized strategy")
    metrics.strategies_generated = len(strategies)

    # Sort by priority (highest first)
    strategies = sorted(strategies, key=lambda s: s.priority, reverse=True)
    strategy_budgets = _allocate_deep_strategy_budgets(strategies, per_source_limit=limit)
    runners = dict(build_default_search_functions(searcher) if search_functions is None else search_functions)
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
            adapter_result = cast(
                "SourceAdapterResult[UnifiedArticle]",
                validate_source_adapter_result(
                    raw_outcome,
                    expected_source=strategy.source,
                    expected_operation="search",
                ),
            )
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
        metrics.heuristic_recall_proxy = 1 - combined_recall

        # Average precision (weighted by articles found)
        total_articles = sum(sr.articles_count for sr in metrics.strategy_results)
        if total_articles > 0:
            weighted_precision = sum(sr.expected_precision * sr.articles_count for sr in metrics.strategy_results)
            metrics.heuristic_precision_proxy = weighted_precision / total_articles
    else:
        metrics.heuristic_recall_proxy = 0.0
        metrics.heuristic_precision_proxy = 0.0

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


async def _search_europe_pmc_adapter(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict[str, Any],
) -> SourceAdapterResult[UnifiedArticle]:
    """Search Europe PMC through the sole alternate-source adapter seam."""

    return await _search_keyword_alternate_adapter(
        source="europe_pmc",
        mapper=article_from_europe_pmc,
        query=query,
        limit=limit,
        min_year=min_year,
        max_year=max_year,
        advanced_filters=advanced_filters,
    )


async def _search_pubmed_adapter(
    searcher: LiteratureSearcher,
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict[str, Any],
) -> SourceAdapterResult[UnifiedArticle]:
    """Search PubMed through its sole typed provider-page contract."""

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
        page = await searcher.search_page(
            query=query,
            limit=limit,
            min_year=min_year,
            max_year=max_year,
            **search_filters,
        )
        if (
            not isinstance(page, SourceSearchPage)
            or page.source != "pubmed"
            or not isinstance(page.items, list)
            or any(not isinstance(item, dict) for item in page.items)
        ):
            _raise_sanitized_search_error("PubMed", APIRequestError("PubMed"))
        if any(not str(item.get("pmid") or "").strip() for item in page.items):
            _raise_sanitized_search_error("PubMed", APIRequestError("PubMed"))
        return _page_adapter_result(
            source="pubmed",
            logical_query=query,
            page=page,
            mapper=article_from_pubmed,
            requested_mode=cast("ProviderRetrievalMode", advanced_filters.get("_retrieval_mode", "auto")),
        )
    except Exception as exc:
        logger.warning("PubMed search failed (%s)", type(exc).__name__)
        execution_metadata = getattr(exc, "execution_metadata", None)
        if isinstance(execution_metadata, dict):
            raw_executed = execution_metadata.get("query_executed") is True
            raw_physical_query = execution_metadata.get("physical_query")
            metadata["query_executed"] = raw_executed
            metadata["physical_query"] = (
                raw_physical_query if raw_executed and isinstance(raw_physical_query, str) else None
            )
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
        "provider_metadata": dict(page.metadata),
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
        next_token=page.next_token,
        cursor=page.cursor,
        cost=page.cost,
        provenance={
            "logical_query": logical_query,
            "physical_query": page.metadata.get("physical_query") or page.query or logical_query,
            "provider_mode": page.mode,
            "provider_metadata": dict(page.metadata),
        },
    )


def _mapping_adapter_result_to_articles(
    *,
    source: str,
    logical_query: str,
    outcome: SourceAdapterResult[dict[str, Any]],
    mapper: Callable[[dict[str, Any]], UnifiedArticle],
    requested_mode: ProviderRetrievalMode,
    unsupported_filters: list[str] | None = None,
) -> SourceAdapterResult[UnifiedArticle]:
    """Map the shared raw-DTO adapter contract without losing its envelope."""
    raw = validate_source_adapter_mapping_result(
        outcome,
        expected_source=source,
        expected_operation="search",
    )
    warnings = list(raw.metadata.get("warnings") or [])
    if unsupported_filters:
        warnings.append(f"{source} does not apply PubMed-only filter(s): {', '.join(sorted(unsupported_filters))}")
    provenance_execution = raw.provenance.get("query_executed")
    query_executed = provenance_execution if isinstance(provenance_execution, bool) else raw.status != "error"
    physical_query = raw.provenance.get("physical_query")
    if physical_query is None and query_executed:
        physical_query = logical_query
    metadata = {
        **dict(raw.metadata),
        "requested_mode": requested_mode,
        "provider_mode": raw.provenance.get("provider_mode"),
        "logical_query": logical_query,
        "physical_query": physical_query,
        "query_executed": query_executed,
        "continuation_available": bool(raw.next_token is not None or raw.cursor),
        "warnings": warnings,
    }
    mapped = SourceAdapterResult(
        source=raw.source,
        operation=raw.operation,
        items=[mapper(provider_dto) for provider_dto in raw.items],
        total_count=raw.total_count,
        status=raw.status,
        errors=list(raw.errors),
        metadata=metadata,
        next_token=raw.next_token,
        cursor=raw.cursor,
        cost=raw.cost,
        provenance=dict(raw.provenance),
    )
    return cast(
        "SourceAdapterResult[UnifiedArticle]",
        validate_source_adapter_result(
            mapped,
            expected_source=source,
            expected_operation="search",
        ),
    )


async def _search_keyword_alternate_adapter(
    *,
    source: Literal["europe_pmc", "core", "scopus", "web_of_science"],
    mapper: Callable[[dict[str, Any]], UnifiedArticle],
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict[str, Any],
) -> SourceAdapterResult[UnifiedArticle]:
    """Map one canonical keyword-source result without a duplicate client path."""

    requested_mode = advanced_filters.get("_retrieval_mode", "auto")
    if requested_mode != "auto":
        raise ValueError(f"{source} supports only the canonical auto retrieval mode")
    outcome = await search_alternate_source_adapter(
        query=query,
        source=source,
        limit=limit,
        min_year=min_year,
        max_year=max_year,
    )
    unsupported = [key for key in advanced_filters if not key.startswith("_")]
    return _mapping_adapter_result_to_articles(
        source=source,
        logical_query=query,
        outcome=outcome,
        mapper=mapper,
        requested_mode="auto",
        unsupported_filters=unsupported,
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
        outcome = await search_alternate_source_adapter(
            query=query,
            source="openalex",
            limit=limit,
            min_year=min_year,
            max_year=max_year,
        )
        unsupported = [key for key in options if not key.startswith("_")]
        return _mapping_adapter_result_to_articles(
            source="openalex",
            logical_query=query,
            outcome=outcome,
            mapper=article_from_openalex,
            requested_mode=retrieval_mode,
            unsupported_filters=unsupported,
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
        outcome = await search_alternate_source_adapter(
            query=query,
            source="semantic_scholar",
            limit=limit,
            min_year=min_year,
            max_year=max_year,
        )
        for source_error in outcome.errors:
            _raise_if_semantic_scholar_rate_limited(source_error)
        if retrieval_mode == "semantic":
            warnings = outcome.metadata.setdefault("warnings", [])
            if isinstance(warnings, list):
                warnings.append("Semantic Scholar has no native semantic mode contract; relevance search was used")
        unsupported = [key for key in options if not key.startswith("_")]
        return _mapping_adapter_result_to_articles(
            source="semantic_scholar",
            logical_query=query,
            outcome=outcome,
            mapper=article_from_semantic_scholar,
            requested_mode=retrieval_mode,
            unsupported_filters=unsupported,
        )
    unsupported = [key for key in options if not key.startswith("_")]
    return _page_adapter_result(
        source="semantic_scholar",
        logical_query=query,
        page=page,
        mapper=article_from_semantic_scholar,
        requested_mode=retrieval_mode,
        unsupported_filters=unsupported,
    )


async def _search_core_adapter(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict[str, Any],
) -> SourceAdapterResult[UnifiedArticle]:
    """Search CORE through the sole alternate-source adapter seam."""

    return await _search_keyword_alternate_adapter(
        source="core",
        mapper=article_from_core,
        query=query,
        limit=limit,
        min_year=min_year,
        max_year=max_year,
        advanced_filters=advanced_filters,
    )


async def _search_scopus_adapter(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict[str, Any],
) -> SourceAdapterResult[UnifiedArticle]:
    """Search Scopus through the sole alternate-source adapter seam."""

    return await _search_keyword_alternate_adapter(
        source="scopus",
        mapper=article_from_scopus,
        query=query,
        limit=limit,
        min_year=min_year,
        max_year=max_year,
        advanced_filters=advanced_filters,
    )


async def _search_web_of_science_adapter(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict[str, Any],
) -> SourceAdapterResult[UnifiedArticle]:
    """Search Web of Science through the sole alternate-source adapter seam."""

    return await _search_keyword_alternate_adapter(
        source="web_of_science",
        mapper=article_from_web_of_science,
        query=query,
        limit=limit,
        min_year=min_year,
        max_year=max_year,
        advanced_filters=advanced_filters,
    )


# ============================================================================
# Preprint Source Runners (arXiv / medRxiv / bioRxiv)
# ============================================================================


@dataclass(frozen=True)
class _PreprintYearFilterResult:
    """Auditable result of the provider-local preprint year filter."""

    articles: list[UnifiedArticle]
    retrieved_count: int
    excluded_out_of_range_count: int
    excluded_unknown_year_count: int


def _filter_preprints_by_year(
    articles: list[UnifiedArticle],
    min_year: int | None,
    max_year: int | None,
) -> _PreprintYearFilterResult:
    """Apply a fail-closed year range and report every local exclusion."""

    retrieved_count = len(articles)
    if min_year is None and max_year is None:
        return _PreprintYearFilterResult(
            articles=articles,
            retrieved_count=retrieved_count,
            excluded_out_of_range_count=0,
            excluded_unknown_year_count=0,
        )
    result: list[UnifiedArticle] = []
    excluded_out_of_range_count = 0
    excluded_unknown_year_count = 0
    for art in articles:
        if art.year is None:
            # An explicit hard range cannot truthfully include an item whose
            # year is unknown. Keep the exclusion visible in source metadata.
            excluded_unknown_year_count += 1
            continue
        if min_year is not None and art.year < min_year:
            excluded_out_of_range_count += 1
            continue
        if max_year is not None and art.year > max_year:
            excluded_out_of_range_count += 1
            continue
        result.append(art)
    return _PreprintYearFilterResult(
        articles=result,
        retrieved_count=retrieved_count,
        excluded_out_of_range_count=excluded_out_of_range_count,
        excluded_unknown_year_count=excluded_unknown_year_count,
    )


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
        compile_rxiv_local_terms,
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
        "coverage": {
            "corpus_total_known": False,
            "provider_window": (
                {"kind": "provider_query", "from": None, "to": None}
                if source == "arxiv"
                else {"kind": "rolling_date_feed", "from": from_date, "to": to_date}
            ),
            "provider_result_limit": limit,
            "keyword_filter": "provider_query" if source == "arxiv" else "local_all_terms_case_insensitive",
        },
        "warnings": [],
    }
    if source != "arxiv":
        try:
            compile_rxiv_local_terms(query)
        except ValueError:
            metadata["warnings"] = [
                "medRxiv/bioRxiv date-feed filtering accepts plain terms only; Boolean or grouped syntax was not executed."
            ]
            return SourceAdapterResult.failure(
                source=source,
                operation="search",
                error=SourceAdapterError(
                    source=source,
                    operation="search",
                    message="Preprint source rejected unsupported query syntax",
                    kind="validation",
                ),
                metadata=metadata,
            )
    try:
        searcher = PreprintSearcher()
        metadata["physical_query"] = compiled_query
        metadata["query_executed"] = True
        try:
            results = await searcher.search(
                query=query,
                sources=[source],
                limit=limit,
                categories=ARXIV_MEDICAL_CATEGORIES if source == "arxiv" else None,
                from_date=from_date,
                to_date=to_date,
            )
        finally:
            await searcher.close()
        by_source = results.get("by_source")
        if not isinstance(by_source, dict):
            _raise_sanitized_search_error(source, APIRequestError(source))
        items = _require_result_list(by_source.get(source, []), service=source)
        mapped_articles = [article_from_preprint(item) for item in items if isinstance(item, dict)]
        year_filter = _filter_preprints_by_year(mapped_articles, min_year, max_year)
        articles = year_filter.articles
        metadata["local_filter_outcome"] = {
            "retrieved": year_filter.retrieved_count,
            "excluded_out_of_range": year_filter.excluded_out_of_range_count,
            "excluded_unknown_year": year_filter.excluded_unknown_year_count,
            "eligible": len(articles),
        }
        metadata["warnings"] = [
            "Preprint corpus total is unavailable; coverage is bounded by the provider window and result limit."
        ]
        if year_filter.excluded_unknown_year_count:
            metadata["warnings"].append(
                "Preprints with unknown publication year were excluded because an explicit year range was requested."
            )
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
