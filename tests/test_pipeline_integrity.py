"""Integrity tests for bounded pipeline parsing, budgets, and tenant deletion."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from pubmed_search.application.pipeline.budgets import (
    PIPELINE_ACTION_LIMITS,
    PIPELINE_OUTPUT_LIMIT,
    PIPELINE_TEMPLATE_LIMITS,
    PipelineExecutionPolicy,
    validate_pipeline_budgets,
)
from pubmed_search.application.pipeline.config_parser import (
    MAX_PIPELINE_CONFIG_CHARS,
    MAX_PIPELINE_CONFIG_DEPTH,
    MAX_PIPELINE_CONFIG_NODES,
    parse_pipeline_config_text,
)
from pubmed_search.application.pipeline.executor import PipelineExecutor
from pubmed_search.application.pipeline.store import PipelineStore
from pubmed_search.application.pipeline.templates import build_pipeline_from_template
from pubmed_search.application.pipeline.validator import parse_and_validate_config
from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.domain.entities.pipeline import PipelineConfig, PipelineScope, PipelineStep, ScheduleEntry
from pubmed_search.presentation.mcp_server.tools.pipeline_tools import (
    PipelineToolRuntime,
    register_pipeline_tools,
)
from pubmed_search.shared.tenancy import TenantIdentity, bind_tenant

if TYPE_CHECKING:
    from pathlib import Path


def _registered_pipeline_tools(
    store: object | None = None,
    scheduler: object | None = None,
) -> dict[str, object]:
    mcp = MagicMock()
    registered: dict[str, object] = {}

    def tool():
        def decorator(function):
            registered[function.__name__] = function
            return function

        return decorator

    mcp.tool = tool
    register_pipeline_tools(
        mcp,
        runtime=PipelineToolRuntime(base_store=store, scheduler=scheduler),  # type: ignore[arg-type]
    )
    return registered


class TestBoundedPipelineConfigParser:
    def test_unified_inline_parser_is_the_application_parser(self):
        from pubmed_search.presentation.mcp_server.tools.unified_pipeline import _parse_pipeline_config

        assert _parse_pipeline_config is parse_pipeline_config_text

    def test_rejects_oversized_text(self):
        with pytest.raises(ValueError, match="maximum length"):
            parse_pipeline_config_text("x" * (MAX_PIPELINE_CONFIG_CHARS + 1))

    def test_rejects_yaml_alias_before_expansion(self):
        with pytest.raises(ValueError, match="aliases are not supported"):
            parse_pipeline_config_text("params: &shared\n  query: cancer\ncopy: *shared\n")

    def test_rejects_unsafe_yaml_tag(self):
        with pytest.raises(ValueError, match="Invalid pipeline YAML/JSON"):
            parse_pipeline_config_text('payload: !!python/object/apply:os.system ["id"]')

    def test_rejects_excessive_json_depth(self):
        nested: object = "leaf"
        for _ in range(MAX_PIPELINE_CONFIG_DEPTH):
            nested = {"child": nested}

        with pytest.raises(ValueError, match="maximum depth"):
            parse_pipeline_config_text(json.dumps(nested))

    def test_rejects_excessive_json_nodes(self):
        payload = {"nodes": list(range(MAX_PIPELINE_CONFIG_NODES))}

        with pytest.raises(ValueError, match="maximum node count"):
            parse_pipeline_config_text(json.dumps(payload))

    def test_rejects_excessive_yaml_depth_during_composition(self):
        lines = [f"{'  ' * depth}level_{depth}:" for depth in range(MAX_PIPELINE_CONFIG_DEPTH + 1)]
        lines.append(f"{'  ' * (MAX_PIPELINE_CONFIG_DEPTH + 1)}leaf")

        with pytest.raises(ValueError, match="maximum depth"):
            parse_pipeline_config_text("\n".join(lines))

    def test_rejects_excessive_yaml_nodes_during_composition(self):
        payload = "nodes:\n" + "  - value\n" * MAX_PIPELINE_CONFIG_NODES

        with pytest.raises(ValueError, match="maximum node count"):
            parse_pipeline_config_text(payload)

    def test_store_file_path_uses_same_bounded_parser(self, tmp_path: Path):
        store = PipelineStore(global_data_dir=tmp_path / "store")
        path = tmp_path / "oversized.yaml"
        path.write_text("x" * (MAX_PIPELINE_CONFIG_CHARS + 1), encoding="utf-8")

        with pytest.raises(ValueError, match="maximum length"):
            store.load_from_path(path)

    def test_save_tool_uses_same_alias_policy(self, tmp_path: Path):
        tools = _registered_pipeline_tools(PipelineStore(global_data_dir=tmp_path / "store"))

        output = tools["save_pipeline"](  # type: ignore[operator]
            name="alias_bomb",
            config="params: &shared\n  query: cancer\ncopy: *shared\n",
        )

        assert "aliases are not supported" in output


@pytest.mark.parametrize(
    ("template", "base_params", "requested_limit"),
    [
        ("pico", {"P": "ICU", "I": "remimazolam", "C": "propofol", "O": "mortality"}, 1),
        (
            "pico",
            {"P": "ICU", "I": "remimazolam", "C": "propofol", "O": "mortality"},
            PIPELINE_TEMPLATE_LIMITS["pico"].maximum,
        ),
        ("comprehensive", {"query": "CRISPR"}, PIPELINE_TEMPLATE_LIMITS["comprehensive"].maximum),
        ("exploration", {"pmid": "12345678"}, PIPELINE_TEMPLATE_LIMITS["exploration"].maximum),
        ("gene_drug", {"term": "BRCA1"}, PIPELINE_TEMPLATE_LIMITS["gene_drug"].maximum),
    ],
)
def test_every_generated_template_respects_executor_budgets(
    template: str,
    base_params: dict[str, object],
    requested_limit: object,
):
    config = build_pipeline_from_template(template, {**base_params, "limit": requested_limit})

    validate_pipeline_budgets(config)
    PipelineExecutor().dry_run(config)
    assert 1 <= config.output.limit <= PIPELINE_OUTPUT_LIMIT.maximum
    for step in config.steps:
        if step.action in PIPELINE_ACTION_LIMITS and "limit" in step.params:
            budget = PIPELINE_ACTION_LIMITS[step.action]
            assert budget.minimum <= step.params["limit"] <= budget.maximum


@pytest.mark.parametrize(
    ("template", "base_params"),
    [
        ("pico", {"P": "ICU", "I": "remimazolam"}),
        ("comprehensive", {"query": "CRISPR"}),
        ("exploration", {"pmid": "12345678"}),
        ("gene_drug", {"term": "BRCA1"}),
    ],
)
@pytest.mark.parametrize("invalid_limit", ["20", 1.0, True, None])
def test_every_template_rejects_non_integer_explicit_limits(
    template: str,
    base_params: dict[str, object],
    invalid_limit: object,
):
    with pytest.raises(ValueError, match="limit"):
        build_pipeline_from_template(template, {**base_params, "limit": invalid_limit})


@pytest.mark.parametrize(
    ("template", "base_params"),
    [
        ("pico", {"P": "ICU", "I": "remimazolam"}),
        ("comprehensive", {"query": "CRISPR"}),
        ("exploration", {"pmid": "12345678"}),
        ("gene_drug", {"term": "BRCA1"}),
    ],
)
def test_template_limits_outside_exact_budget_are_rejected(template: str, base_params: dict[str, object]):
    budget = PIPELINE_TEMPLATE_LIMITS[template]
    for invalid_limit in (budget.minimum - 1, budget.maximum + 1):
        with pytest.raises(ValueError, match="limit"):
            build_pipeline_from_template(template, {**base_params, "limit": invalid_limit})


def test_custom_step_limit_is_rejected_during_semantic_validation():
    result = parse_and_validate_config(
        {
            "steps": [
                {
                    "id": "search",
                    "action": "search",
                    "params": {"query": "cancer", "limit": PIPELINE_ACTION_LIMITS["search"].maximum + 1},
                }
            ]
        }
    )

    assert result.valid is False
    assert any("Pipeline search limit must be between" in error for error in result.errors)


def test_output_limit_above_shared_budget_is_rejected():
    result = parse_and_validate_config(
        {
            "steps": [{"id": "search", "action": "search", "params": {"query": "cancer"}}],
            "output": {"limit": PIPELINE_OUTPUT_LIMIT.maximum + 1},
        }
    )

    assert result.valid is False
    assert result.config is None
    assert any("output.limit" in error for error in result.errors)


class TestAggregatePipelineExecutionBudget:
    async def test_parallel_steps_reserve_external_call_quota_atomically(self):
        searcher = MagicMock()
        searcher.search_page = AsyncMock(
            return_value=SourceSearchPage(
                source="pubmed",
                items=[
                    {
                        "pmid": "12345678",
                        "title": "Quota bounded article",
                        "authors": [],
                        "journal": "Test Journal",
                        "year": "2024",
                    }
                ],
                total=1,
                query="first query",
            )
        )
        executor = PipelineExecutor(
            searcher=searcher,
            execution_policy=PipelineExecutionPolicy(
                run_timeout_seconds=5,
                max_external_calls=1,
            ),
        )
        config = PipelineConfig(
            steps=[
                PipelineStep(
                    id="first",
                    action="search",
                    params={"query": "first query", "sources": ["pubmed"]},
                    on_error="skip",
                ),
                PipelineStep(
                    id="second",
                    action="search",
                    params={"query": "second query", "sources": ["pubmed"]},
                    on_error="skip",
                ),
            ]
        )

        articles, results = await executor.execute(config)

        assert searcher.search_page.await_count == 1
        assert [article.pmid for article in articles] == ["12345678"]
        failed = [result for result in results.values() if not result.ok]
        assert len(failed) == 1
        assert failed[0].metadata["source_errors"][0]["terminal_reason"] == ("external_call_quota_exhausted")
        run_budget = results["second"].metadata["run_budget"]
        assert run_budget["external_calls_used"] == 1
        assert run_budget["external_calls_remaining"] == 0
        assert run_budget["exhausted_reason"] == "external_call_quota_exhausted"

    async def test_deadline_cancels_current_and_future_steps_with_typed_metadata(self):
        provider_started = asyncio.Event()
        provider_cancelled = asyncio.Event()

        async def never_finishes(**_kwargs):
            provider_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                provider_cancelled.set()

        searcher = MagicMock()
        searcher.search_page = AsyncMock(side_effect=never_finishes)
        executor = PipelineExecutor(
            searcher=searcher,
            execution_policy=PipelineExecutionPolicy(
                run_timeout_seconds=0.01,
                max_external_calls=5,
            ),
        )
        config = PipelineConfig(
            steps=[
                PipelineStep(
                    id="search",
                    action="search",
                    params={"query": "deadline", "sources": ["pubmed"]},
                    on_error="skip",
                ),
                PipelineStep(
                    id="metrics",
                    action="metrics",
                    inputs=["search"],
                    on_error="skip",
                ),
            ]
        )

        articles, results = await executor.execute(config)

        assert provider_started.is_set()
        assert provider_cancelled.is_set()
        assert articles == []
        assert results["search"].error == "Pipeline run deadline exhausted"
        assert results["metrics"].error == "Pipeline run deadline exhausted"
        assert results["search"].metadata["terminal_reason"] == "deadline_exhausted"
        run_budget = results["metrics"].metadata["run_budget"]
        assert run_budget["external_calls_used"] == 1
        assert run_budget["exhausted_reason"] == "deadline_exhausted"


class TestTenantSafePipelineDeletion:
    def test_default_tenant_deletes_then_unschedules(self, tmp_path: Path):
        events: list[str] = []
        store = MagicMock()
        store.global_data_dir = tmp_path
        store.delete.side_effect = lambda _name: events.append("delete") or (PipelineScope.GLOBAL, 2)
        scheduler = MagicMock()
        scheduler.get_schedule.return_value = ScheduleEntry(pipeline_name="shared", cron="0 9 * * 1")
        scheduler.unschedule.side_effect = lambda _name: events.append("unschedule")
        output = _registered_pipeline_tools(store, scheduler)["delete_pipeline"](  # type: ignore[operator]
            name="shared"
        )

        assert events == ["delete", "unschedule"]
        assert "2 execution history" in output
        assert "Process schedule removed" in output

    def test_non_default_tenant_never_touches_process_scheduler(self, tmp_path: Path):
        base_store = MagicMock()
        base_store.global_data_dir = tmp_path
        tenant_store = MagicMock()
        tenant_store.delete.return_value = (PipelineScope.GLOBAL, 0)
        base_store.rebased.return_value = tenant_store
        scheduler = MagicMock()
        identity = TenantIdentity.for_principal("research-team")

        with bind_tenant(identity):
            output = _registered_pipeline_tools(base_store, scheduler)["delete_pipeline"](  # type: ignore[operator]
                name="shared"
            )

        tenant_store.delete.assert_called_once_with("shared")
        scheduler.get_schedule.assert_not_called()
        scheduler.unschedule.assert_not_called()
        assert "permanently removed" in output

    def test_missing_pipeline_does_not_unschedule(self, tmp_path: Path):
        store = MagicMock()
        store.global_data_dir = tmp_path
        store.delete.side_effect = FileNotFoundError("missing")
        scheduler = MagicMock()
        scheduler.get_schedule.return_value = ScheduleEntry(pipeline_name="missing", cron="0 9 * * 1")
        output = _registered_pipeline_tools(store, scheduler)["delete_pipeline"](  # type: ignore[operator]
            name="missing"
        )

        scheduler.unschedule.assert_not_called()
        assert "not found" in output.lower()

    def test_delete_reports_live_schedule_cleanup_failure_truthfully(self, tmp_path: Path):
        store = MagicMock()
        store.global_data_dir = tmp_path
        store.delete.return_value = (PipelineScope.GLOBAL, 0)
        scheduler = MagicMock()
        scheduler.get_schedule.return_value = ScheduleEntry(pipeline_name="shared", cron="0 9 * * 1")
        scheduler.unschedule.side_effect = RuntimeError("private detail")
        output = _registered_pipeline_tools(store, scheduler)["delete_pipeline"](  # type: ignore[operator]
            name="shared"
        )

        assert "Configuration permanently removed" in output
        assert "live schedule cleanup failed" in output
        assert "private detail" not in output
