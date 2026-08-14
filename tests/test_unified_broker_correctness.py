"""Regression contracts for unified-search planning and broker semantics."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from pubmed_search.application.search.query_analyzer import (
    AnalyzedQuery,
    QueryComplexity,
    QueryIntent,
)
from pubmed_search.application.search.reproducibility import calculate_reproducibility
from pubmed_search.application.search.semantic_enhancer import EnhancedQuery, SearchPlan
from pubmed_search.infrastructure.sources.registry import get_source_registry
from pubmed_search.presentation.mcp_server.tools.unified_helpers import SearchDepthMetrics
from pubmed_search.presentation.mcp_server.tools.unified_runner import run_unified_search
from pubmed_search.presentation.mcp_server.tools.unified_source_search import _execute_deep_search


class _StaticAnalyzer:
    def __init__(self, analysis: AnalyzedQuery) -> None:
        self._analysis = analysis

    def analyze(self, _query: str) -> AnalyzedQuery:
        return self._analysis


class _StaticEnhancer:
    def __init__(self, enhanced: EnhancedQuery) -> None:
        self._enhanced = enhanced

    async def enhance(self, _query: str) -> EnhancedQuery:
        return self._enhanced


def _analysis(query: str, *, complex_query: bool = False) -> AnalyzedQuery:
    return AnalyzedQuery(
        original_query=query,
        normalized_query=query,
        complexity=QueryComplexity.COMPLEX if complex_query else QueryComplexity.SIMPLE,
        intent=QueryIntent.SYSTEMATIC if complex_query else QueryIntent.EXPLORATION,
    )


def _enhanced(query: str) -> EnhancedQuery:
    return EnhancedQuery(
        original_query=query,
        strategies=[
            SearchPlan(
                name="original",
                query=query,
                source="pubmed",
            )
        ],
    )


async def _empty_search(*_args, **_kwargs):
    return [], 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sources", "options", "expected_sources"),
    [
        ("pubmed,openalex", "no_relax,no_analysis,no_scores", {"pubmed", "openalex"}),
        (
            "pubmed",
            "preprints,no_relax,no_analysis,no_scores",
            {"pubmed", "arxiv", "medrxiv", "biorxiv"},
        ),
    ],
)
async def test_deep_plan_preserves_every_requested_primary_source(
    sources: str,
    options: str,
    expected_sources: set[str],
) -> None:
    query = "systematic remimazolam versus propofol"
    deep_result = ([], SearchDepthMetrics(), None, {}, [])

    with (
        patch(
            "pubmed_search.presentation.mcp_server.tools.unified_execution._execute_deep_search",
            new_callable=AsyncMock,
            return_value=deep_result,
        ) as execute_deep,
        patch(
            "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        await run_unified_search(
            searcher=AsyncMock(),
            query=query,
            sources=sources,
            output_format="json",
            options=options,
            analyzer_factory=lambda: _StaticAnalyzer(_analysis(query, complex_query=True)),
            enhancer_factory=lambda: _StaticEnhancer(_enhanced(query)),
        )

    planned_sources = {strategy.source for strategy in execute_deep.await_args.kwargs["strategies"]}
    assert planned_sources == expected_sources


@pytest.mark.asyncio
async def test_deep_all_preserves_all_enabled_primary_sources() -> None:
    query = "systematic precision medicine review"
    registry = get_source_registry()
    expected_sources = {
        source
        for source in registry.list_unified_sources()
        if (definition := registry.get(source)) is not None and definition.supports_primary_search
    }

    with (
        patch(
            "pubmed_search.presentation.mcp_server.tools.unified_execution._execute_deep_search",
            new_callable=AsyncMock,
            return_value=([], SearchDepthMetrics(), None, {}, []),
        ) as execute_deep,
        patch(
            "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        await run_unified_search(
            searcher=AsyncMock(),
            query=query,
            sources="all",
            output_format="json",
            options="no_relax,no_analysis,no_scores",
            analyzer_factory=lambda: _StaticAnalyzer(_analysis(query, complex_query=True)),
            enhancer_factory=lambda: _StaticEnhancer(_enhanced(query)),
        )

    planned_sources = {strategy.source for strategy in execute_deep.await_args.kwargs["strategies"]}
    assert planned_sources == expected_sources


@pytest.mark.asyncio
async def test_deep_metrics_count_injected_source_baselines() -> None:
    query = "precision medicine"
    strategies = [
        SearchPlan(name="original", query=query, source="pubmed"),
        SearchPlan(name="source_baseline_openalex", query=query, source="openalex"),
    ]

    async def _empty_adapter(*_args, **_kwargs):
        return [], 0

    _results, metrics, _pubmed_total, counts, errors = await _execute_deep_search(
        AsyncMock(),
        _enhanced(query),
        limit=10,
        min_year=None,
        max_year=None,
        advanced_filters={},
        strategies=strategies,
        search_functions={"pubmed": _empty_adapter, "openalex": _empty_adapter},
    )

    assert metrics.strategies_generated == len(strategies)
    assert metrics.strategies_executed == len(strategies)
    assert set(counts) == {"pubmed", "openalex"}
    assert errors == []


@pytest.mark.asyncio
async def test_shallow_execution_calls_exactly_the_requested_primary_sources() -> None:
    calls: list[str] = []

    def _runner(source: str):
        async def _search(*_args, **_kwargs):
            calls.append(source)
            return [], 0

        return _search

    query = "precision medicine"
    with patch(
        "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
        new_callable=AsyncMock,
        return_value=[],
    ):
        await run_unified_search(
            searcher=AsyncMock(),
            query=query,
            sources="pubmed,openalex",
            output_format="json",
            options="shallow,no_relax,no_analysis,no_scores",
            analyzer_factory=lambda: _StaticAnalyzer(_analysis(query)),
            search_functions={"pubmed": _runner("pubmed"), "openalex": _runner("openalex")},
        )

    assert set(calls) == {"pubmed", "openalex"}
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_clinical_trials_prefetch_requires_explicit_markdown_opt_in() -> None:
    clinical_trials = AsyncMock(return_value=[{"nct_id": "NCT00000001"}])
    query = "diabetes"

    with patch(
        "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
        clinical_trials,
    ):
        for output_format in ("markdown", "json", "toon"):
            await run_unified_search(
                searcher=AsyncMock(),
                query=query,
                sources="pubmed",
                output_format=output_format,
                options="shallow,no_relax,no_analysis,no_scores",
                analyzer_factory=lambda: _StaticAnalyzer(_analysis(query)),
                search_functions={"pubmed": _empty_search},
            )

        await run_unified_search(
            searcher=AsyncMock(),
            query=query,
            sources="pubmed",
            output_format="markdown",
            options="trials,shallow,no_relax,no_analysis,no_scores",
            analyzer_factory=lambda: _StaticAnalyzer(_analysis(query)),
            search_functions={"pubmed": _empty_search},
        )

        await run_unified_search(
            searcher=AsyncMock(),
            query=query,
            sources="pubmed",
            output_format="json",
            options="trials,shallow,no_relax,no_analysis,no_scores",
            analyzer_factory=lambda: _StaticAnalyzer(_analysis(query)),
            search_functions={"pubmed": _empty_search},
        )

    assert clinical_trials.await_count == 1
    assert {call.args[0] for call in clinical_trials.await_args_list} == {query}


@pytest.mark.asyncio
async def test_auto_relax_reuses_the_successful_pubmed_result() -> None:
    query = "diabetes AND therapy"
    searcher = AsyncMock()
    searcher.search.side_effect = [
        [],
        [{"pmid": "12345", "title": "Relaxed Article", "authors": ["A B"]}],
    ]

    with patch(
        "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
        new_callable=AsyncMock,
        return_value=[],
    ):
        result = await run_unified_search(
            searcher=searcher,
            query=query,
            sources="pubmed",
            options="shallow,no_analysis,no_scores",
            analyzer_factory=lambda: _StaticAnalyzer(_analysis(query)),
        )

    assert searcher.search.await_count == 2
    assert "Relaxed Article" in result


@pytest.mark.asyncio
async def test_non_pubmed_source_does_not_trigger_pubmed_auto_relax() -> None:
    query = "precision medicine"
    searcher = AsyncMock()

    result = await run_unified_search(
        searcher=searcher,
        query=query,
        sources="openalex",
        output_format="json",
        options="shallow,no_analysis,no_scores",
        analyzer_factory=lambda: _StaticAnalyzer(_analysis(query)),
        search_functions={"openalex": _empty_search},
    )

    searcher.search.assert_not_awaited()
    assert json.loads(result)["articles"] == []


@pytest.mark.asyncio
async def test_preprint_option_respects_source_registry_kill_switch() -> None:
    query = "precision medicine"
    registry = get_source_registry()
    original_is_enabled = registry.is_enabled
    calls: list[str] = []

    def _is_enabled(source: str) -> bool:
        return source not in {"arxiv", "medrxiv"} and original_is_enabled(source)

    def _runner(source: str):
        async def _search(*_args, **_kwargs):
            calls.append(source)
            return [], 0

        return _search

    with patch.object(registry, "is_enabled", side_effect=_is_enabled):
        await run_unified_search(
            searcher=AsyncMock(),
            query=query,
            sources="pubmed",
            output_format="json",
            options="preprints,shallow,no_relax,no_analysis,no_scores",
            analyzer_factory=lambda: _StaticAnalyzer(_analysis(query)),
            source_registry_factory=lambda: registry,
            search_functions={
                "pubmed": _runner("pubmed"),
                "arxiv": _runner("arxiv"),
                "medrxiv": _runner("medrxiv"),
                "biorxiv": _runner("biorxiv"),
            },
        )

    assert set(calls) == {"pubmed", "biorxiv"}


@pytest.mark.asyncio
async def test_successful_empty_source_counts_as_responded_but_error_does_not() -> None:
    query = "precision medicine"

    async def _failed(*_args, **_kwargs):
        raise TimeoutError("upstream timed out")

    with (
        patch(
            "pubmed_search.application.search.reproducibility.calculate_reproducibility",
            wraps=calculate_reproducibility,
        ) as reproducibility,
        patch(
            "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        result = await run_unified_search(
            searcher=AsyncMock(),
            query=query,
            sources="pubmed,openalex",
            output_format="json",
            options="shallow,no_relax,no_scores",
            analyzer_factory=lambda: _StaticAnalyzer(_analysis(query)),
            search_functions={"pubmed": _empty_search, "openalex": _failed},
        )

    assert reproducibility.call_args.kwargs["sources_responded"] == ["pubmed"]
    payload = json.loads(result)
    assert payload["source_errors"][0]["source"] == "openalex"
    assert payload["source_errors"][0]["kind"] == "timeout"


@pytest.mark.asyncio
async def test_failed_systematic_leg_keeps_attempted_physical_query() -> None:
    query = "melanoma AND immunotherapy"

    async def _failed(*_args, **_kwargs):
        raise TimeoutError("upstream timed out")

    with patch(
        "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
        new_callable=AsyncMock,
        return_value=[],
    ):
        result = await run_unified_search(
            searcher=AsyncMock(),
            query=query,
            sources="semantic_scholar",
            output_format="json",
            options="systematic,no_analysis,no_scores",
            analyzer_factory=lambda: _StaticAnalyzer(_analysis(query)),
            search_functions={"semantic_scholar": _failed},
        )

    payload = json.loads(result)
    metadata = payload["source_metadata"]["semantic_scholar"]
    assert metadata["logical_query"] == query
    assert metadata["physical_query"] == "melanoma + immunotherapy"
    assert metadata["provider_mode"] == "bulk"
