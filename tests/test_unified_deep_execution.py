"""Deterministic deep-search broker and recovery-provenance regressions."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from pubmed_search.application.search.query_analyzer import AnalyzedQuery, QueryComplexity, QueryIntent
from pubmed_search.application.search.result_aggregator import RankingConfig
from pubmed_search.application.search.semantic_enhancer import EnhancedQuery, SearchPlan
from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.infrastructure.sources.registry import get_source_registry
from pubmed_search.presentation.mcp_server.tools.unified_execution import execute_unified_search
from pubmed_search.presentation.mcp_server.tools.unified_planning import UnifiedSearchPlan, _build_deep_strategies
from pubmed_search.presentation.mcp_server.tools.unified_request import normalize_unified_search_request
from pubmed_search.presentation.mcp_server.tools.unified_runner import persist_unified_search_artifact
from pubmed_search.presentation.mcp_server.tools.unified_source_search import _execute_deep_search
from pubmed_search.shared.source_contracts import SourceAdapterError, SourceAdapterResult


async def _ignore_progress(_current: float, _total: float, _message: str) -> None:
    return None


def _strategy(name: str, source: str, priority: int) -> SearchPlan:
    return SearchPlan(
        name=name,
        query=name,
        source=source,
        priority=priority,
        expected_precision=0.5,
        expected_recall=0.5,
    )


@pytest.mark.asyncio
async def test_deep_search_enforces_per_source_budget_and_fair_parallelism() -> None:
    strategies = [
        _strategy("pubmed-high", "pubmed", 3),
        _strategy("pubmed-mid", "pubmed", 2),
        _strategy("pubmed-low", "pubmed", 1),
        _strategy("openalex", "openalex", 1),
    ]
    started = {"pubmed": asyncio.Event(), "openalex": asyncio.Event()}
    release = asyncio.Event()
    allocated: dict[str, list[int]] = defaultdict(list)
    active: dict[str, int] = defaultdict(int)
    max_active: dict[str, int] = defaultdict(int)
    global_active = 0
    max_global_active = 0

    def make_runner(source: str):
        async def run(
            query: str,
            limit: int,
            _min_year: int | None,
            _max_year: int | None,
            _options: dict[str, object],
        ) -> SourceAdapterResult[UnifiedArticle]:
            nonlocal global_active, max_global_active
            allocated[source].append(limit)
            active[source] += 1
            global_active += 1
            max_active[source] = max(max_active[source], active[source])
            max_global_active = max(max_global_active, global_active)
            started[source].set()
            try:
                await release.wait()
                articles = [
                    UnifiedArticle(title=f"{source}-{query}-{index}", primary_source=source) for index in range(limit)
                ]
                return SourceAdapterResult(
                    source=source,
                    operation="search",
                    items=articles,
                    total_count=100,
                    status="ok",
                    metadata={
                        "logical_query": query,
                        "physical_query": f"compiled:{query}",
                        "query_executed": True,
                        "provider_mode": "keyword",
                        "total_available": 100,
                    },
                )
            finally:
                active[source] -= 1
                global_active -= 1

        return run

    task = asyncio.create_task(
        _execute_deep_search(
            AsyncMock(),
            EnhancedQuery(original_query="topic", strategies=strategies),
            limit=5,
            min_year=None,
            max_year=None,
            advanced_filters={},
            strategies=strategies,
            search_functions={"pubmed": make_runner("pubmed"), "openalex": make_runner("openalex")},
            max_concurrency=2,
            per_source_concurrency=1,
            strategy_timeout=1.0,
        )
    )
    await asyncio.wait_for(asyncio.gather(started["pubmed"].wait(), started["openalex"].wait()), timeout=0.5)
    release.set()
    _results, metrics, _pubmed_total, counts, errors = await task

    assert sorted(allocated["pubmed"]) == [1, 2, 2]
    assert allocated["openalex"] == [5]
    assert sum(allocated["pubmed"]) == 5
    assert counts == {"pubmed": (5, None), "openalex": (5, 100)}
    assert max_active == {"pubmed": 1, "openalex": 1}
    assert max_global_active == 2
    assert metrics.strategies_executed == 4
    assert errors == []


@pytest.mark.asyncio
async def test_deep_source_status_is_partial_for_empty_success_plus_failed_attempt() -> None:
    query = "precision medicine"
    request = normalize_unified_search_request(
        query=query,
        sources="pubmed",
        options="no_relax,no_analysis,no_scores",
    )
    analysis = AnalyzedQuery(
        original_query=query,
        normalized_query=query,
        complexity=QueryComplexity.COMPLEX,
        intent=QueryIntent.EXPLORATION,
    )
    strategies = [_strategy("exact", "pubmed", 2), _strategy("broad", "pubmed", 1)]
    enhanced = EnhancedQuery(original_query=query, strategies=strategies)
    plan = UnifiedSearchPlan(
        request=request,
        query=query,
        provider_neutral_query=query,
        analysis=analysis,
        icd_matches=[],
        enhanced_query=enhanced,
        deep_strategies=strategies,
        matched_entity_names=[],
        user_sources=["pubmed"],
        dispatch_sources=["pubmed"],
        ranking_config=RankingConfig.default(),
        effective_min_year=None,
        effective_max_year=None,
    )

    async def run(
        strategy_query: str,
        _limit: int,
        _min_year: int | None,
        _max_year: int | None,
        _options: dict[str, object],
    ) -> SourceAdapterResult[UnifiedArticle]:
        metadata = {
            "logical_query": strategy_query,
            "physical_query": f"compiled:{strategy_query}",
            "query_executed": True,
            "provider_mode": "keyword",
            "total_available": 0,
        }
        if strategy_query == "exact":
            return SourceAdapterResult.empty(source="pubmed", operation="search", metadata=metadata)
        return SourceAdapterResult.failure(
            source="pubmed",
            operation="search",
            error=SourceAdapterError(
                source="pubmed",
                operation="search",
                message="Request timed out",
                kind="timeout",
                retryable=True,
            ),
            metadata=metadata,
        )

    execution = await execute_unified_search(
        plan,
        AsyncMock(),
        progress=_ignore_progress,
        search_functions={"pubmed": run},
    )

    assert execution.source_statuses == {"pubmed": "partial"}
    assert execution.source_api_counts == {"pubmed": (0, None)}
    assert execution.source_errors[0]["kind"] == "timeout"
    metadata = execution.source_metadata["pubmed"]
    assert metadata["budget"] == {"per_source_limit": 10, "allocated": 10, "returned": 0}
    assert [attempt["status"] for attempt in metadata["attempts"]] == ["empty", "error"]
    assert metadata["physical_queries"] == ["compiled:exact", "compiled:broad"]
    assert metadata["attempts"][1]["metadata"]["errors"][0]["retryable"] is True


@pytest.mark.asyncio
async def test_deep_search_uses_typed_total_count_without_metadata_duplication() -> None:
    strategy = _strategy("typed-total", "openalex", 1)

    async def run(*_args, **_kwargs) -> SourceAdapterResult[UnifiedArticle]:
        return SourceAdapterResult(
            source="openalex",
            operation="search",
            items=[UnifiedArticle(title="One result", primary_source="openalex")],
            total_count=37,
            status="ok",
            metadata={"physical_query": "compiled query", "query_executed": True},
        )

    _results, metrics, _pubmed_total, counts, errors = await _execute_deep_search(
        AsyncMock(),
        EnhancedQuery(original_query="topic", strategies=[strategy]),
        limit=5,
        min_year=None,
        max_year=None,
        advanced_filters={},
        strategies=[strategy],
        search_functions={"openalex": run},
    )

    assert counts == {"openalex": (1, 37)}
    assert metrics.strategy_results[0].total_available == 37
    assert metrics.strategy_results[0].metadata["total_available"] == 37
    assert errors == []


def _simple_plan(*, explicit_sources: bool, limit: int = 10) -> UnifiedSearchPlan:
    query = "precision medicine"
    request = normalize_unified_search_request(
        query=query,
        limit=limit,
        sources="pubmed" if explicit_sources else None,
        options="shallow,no_analysis,no_scores",
    )
    analysis = AnalyzedQuery(
        original_query=query,
        normalized_query=query,
        complexity=QueryComplexity.SIMPLE,
        intent=QueryIntent.EXPLORATION,
    )
    return UnifiedSearchPlan(
        request=request,
        query=query,
        provider_neutral_query=query,
        analysis=analysis,
        icd_matches=[],
        enhanced_query=None,
        deep_strategies=[],
        matched_entity_names=[],
        user_sources=["pubmed"] if explicit_sources else None,
        dispatch_sources=["pubmed"],
        ranking_config=RankingConfig.default(),
        effective_min_year=None,
        effective_max_year=None,
    )


@pytest.mark.asyncio
async def test_auto_simple_all_error_runs_one_bounded_fallback_without_relaxing() -> None:
    pubmed_error = SourceAdapterResult.failure(
        source="pubmed",
        operation="search",
        error=SourceAdapterError(
            source="pubmed",
            operation="search",
            message="Request timed out",
            kind="timeout",
            retryable=True,
        ),
    )
    europe_pmc = AsyncMock(
        return_value=SourceAdapterResult.empty(
            source="europe_pmc",
            operation="search",
            metadata={
                "logical_query": "precision medicine",
                "physical_query": "precision medicine",
                "query_executed": True,
            },
        )
    )
    openalex = AsyncMock()

    with patch(
        "pubmed_search.presentation.mcp_server.tools.unified_execution._auto_relax_search",
        new_callable=AsyncMock,
    ) as auto_relax:
        execution = await execute_unified_search(
            _simple_plan(explicit_sources=False, limit=100),
            AsyncMock(),
            progress=_ignore_progress,
            search_functions={
                "pubmed": AsyncMock(return_value=pubmed_error),
                "europe_pmc": europe_pmc,
                "openalex": openalex,
            },
        )

    europe_pmc.assert_awaited_once()
    assert europe_pmc.await_args.args[1] == 20
    openalex.assert_not_awaited()
    auto_relax.assert_not_awaited()
    assert execution.source_statuses == {"pubmed": "error", "europe_pmc": "empty"}
    assert execution.source_metadata["europe_pmc"]["fallback_reason"] == "all_auto_primary_sources_failed"
    assert execution.source_metadata["europe_pmc"]["fallback_from"] == ["pubmed"]


@pytest.mark.asyncio
async def test_explicit_failed_source_does_not_fallback_or_auto_relax() -> None:
    pubmed_error = SourceAdapterResult.failure(
        source="pubmed",
        operation="search",
        error=SourceAdapterError(
            source="pubmed",
            operation="search",
            message="Request timed out",
            kind="timeout",
            retryable=True,
        ),
    )
    europe_pmc = AsyncMock()

    with patch(
        "pubmed_search.presentation.mcp_server.tools.unified_execution._auto_relax_search",
        new_callable=AsyncMock,
    ) as auto_relax:
        execution = await execute_unified_search(
            _simple_plan(explicit_sources=True),
            AsyncMock(),
            progress=_ignore_progress,
            search_functions={"pubmed": AsyncMock(return_value=pubmed_error), "europe_pmc": europe_pmc},
        )

    europe_pmc.assert_not_awaited()
    auto_relax.assert_not_awaited()
    assert execution.source_statuses == {"pubmed": "error"}


@pytest.mark.asyncio
async def test_deep_strategy_timeout_is_normalized_without_hanging() -> None:
    strategy = _strategy("slow", "pubmed", 1)

    async def slow(*_args, **_kwargs):
        await asyncio.Event().wait()

    _results, metrics, _pubmed_total, counts, errors = await _execute_deep_search(
        AsyncMock(),
        EnhancedQuery(original_query="slow", strategies=[strategy]),
        limit=3,
        min_year=None,
        max_year=None,
        advanced_filters={},
        strategies=[strategy],
        search_functions={"pubmed": slow},
        strategy_timeout=0.01,
    )

    assert counts == {"pubmed": (0, None)}
    assert metrics.strategy_results[0].status == "error"
    assert metrics.strategy_results[0].query_executed is True
    assert len(errors) == 1
    assert errors[0].kind == "timeout"
    assert errors[0].retryable is True


@pytest.mark.asyncio
async def test_parent_cancellation_cancels_inflight_deep_adapter() -> None:
    strategy = _strategy("cancel", "pubmed", 1)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def never_returns(*_args, **_kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    task = asyncio.create_task(
        _execute_deep_search(
            AsyncMock(),
            EnhancedQuery(original_query="cancel", strategies=[strategy]),
            limit=3,
            min_year=None,
            max_year=None,
            advanced_filters={},
            strategies=[strategy],
            search_functions={"pubmed": never_returns},
            strategy_timeout=10.0,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(cancelled.wait(), timeout=0.5)


def test_deep_planner_keeps_pubmed_field_syntax_out_of_other_sources() -> None:
    pubmed_query = '("Essential Hypertension"[MeSH] OR I10) treatment'
    neutral_query = '("Essential Hypertension" OR I10) treatment'
    enhanced = EnhancedQuery(
        original_query=pubmed_query,
        strategies=[
            SearchPlan(name="pubmed", query=pubmed_query, source="pubmed"),
            SearchPlan(name="epmc", query=pubmed_query, source="europe_pmc"),
        ],
    )

    strategies = _build_deep_strategies(
        query=pubmed_query,
        provider_neutral_query=neutral_query,
        enhanced_query=enhanced,
        dispatch_sources=["pubmed", "europe_pmc", "openalex"],
        registry=get_source_registry(),
    )
    queries = {strategy.source: strategy.query for strategy in strategies}

    assert queries["pubmed"] == pubmed_query
    assert queries["europe_pmc"] == neutral_query
    assert queries["openalex"] == neutral_query


def test_persisted_results_receive_the_same_source_metadata_as_live_json() -> None:
    source_metadata = {
        "pubmed": {
            "provider_mode": "deep_strategy",
            "attempts": [{"strategy": "exact", "status": "empty"}],
        }
    }
    execution = SimpleNamespace(
        ranked=[],
        stats=SimpleNamespace(),
        relaxation_result=None,
        deep_search_metrics=None,
        source_api_counts={"pubmed": (0, 0)},
        source_disagreement=None,
        reproducibility_score=None,
        research_context_data=None,
        source_errors=[],
        source_metadata=source_metadata,
    )
    envelope = SimpleNamespace(files={"results.json": {}}, summary={}, metadata={})

    with (
        patch(
            "pubmed_search.presentation.mcp_server.tools.unified_runner.artifact_persistence_enabled",
            return_value=True,
        ),
        patch(
            "pubmed_search.presentation.mcp_server.tools.unified_runner._format_as_json",
            return_value='{"tool":"unified_search"}',
        ) as formatter,
        patch(
            "pubmed_search.presentation.mcp_server.tools.unified_runner.build_unified_search_artifact_envelope",
            return_value=envelope,
        ),
        patch(
            "pubmed_search.presentation.mcp_server.tools.unified_runner.persist_tool_artifact",
            return_value={"artifact_id": "artifact-1"},
        ),
    ):
        manifest = persist_unified_search_artifact(
            request=SimpleNamespace(),
            plan=SimpleNamespace(analysis=SimpleNamespace()),
            execution=execution,
        )

    assert manifest == {"artifact_id": "artifact-1"}
    assert formatter.call_args.kwargs["source_metadata"] == source_metadata
