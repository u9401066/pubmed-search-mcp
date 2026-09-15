"""Tests for pipeline MCP tools.

Coverage targets:
- save_pipeline: YAML parsing, validation, store integration
- list_pipelines: empty, with data, tag/scope filtering
- load_pipeline: saved name, "saved:" prefix, "file:" prefix, not found
- delete_pipeline: success, not found
- get_pipeline_history: success, empty, not found
- schedule_pipeline / unschedule_pipeline: scheduler-backed create/update/remove flow
- Error cases: store not initialized, invalid YAML, unfixable configs
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from pubmed_search.application.pipeline import (
    PipelineConfig,
    PipelineOutput,
    PipelineStep,
    ScheduleEntry,
    ValidationResult,
)
from pubmed_search.application.pipeline.store import PipelineHistoryError, _config_to_dict
from pubmed_search.domain.entities.pipeline import PipelineMeta, PipelineRun, PipelineScope
from pubmed_search.presentation.mcp_server.tools.pipeline_tools import (
    PipelineToolRuntime,
    register_pipeline_tools,
)
from pubmed_search.shared.tenancy import TenantIdentity, bind_tenant

if TYPE_CHECKING:
    from pathlib import Path

# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture()
def runtime():
    """A fresh server-scoped dependency container for every test."""
    return PipelineToolRuntime(base_store=None)


@pytest.fixture()
def mock_store(runtime):
    """A MagicMock PipelineStore."""
    store = MagicMock()
    runtime.base_store = store
    return store


@pytest.fixture()
def mock_scheduler(runtime):
    """A scheduler bound to the test server runtime."""
    scheduler = MagicMock()
    runtime.scheduler = scheduler
    return scheduler


@pytest.fixture()
def real_store(tmp_path: Path, runtime):
    """A real PipelineStore with tmp dirs."""
    from pubmed_search.application.pipeline.store import PipelineStore

    global_dir = tmp_path / "global"
    global_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    store = PipelineStore(global_data_dir=global_dir, workspace_dir=workspace_dir)
    runtime.base_store = store
    return store


@pytest.fixture()
def mcp(runtime):
    """A mock MCP server to capture registered tools."""
    mock_mcp = MagicMock()
    registered_tools = {}

    def mock_tool_decorator():
        def decorator(func):
            registered_tools[func.__name__] = func
            return func

        return decorator

    mock_mcp.tool = mock_tool_decorator
    register_pipeline_tools(mock_mcp, runtime=runtime)
    return registered_tools


# =========================================================================
# Tool Registration
# =========================================================================


class TestToolRegistration:
    """Tests that only single-purpose pipeline tools are registered."""

    def test_all_tools_registered(self, mcp):
        expected = {
            "save_pipeline",
            "list_pipelines",
            "load_pipeline",
            "delete_pipeline",
            "get_pipeline_history",
            "schedule_pipeline",
            "unschedule_pipeline",
        }
        assert set(mcp.keys()) == expected


# =========================================================================
# Server-scoped runtime
# =========================================================================


class TestPipelineRuntime:
    """Tests for explicit server-scoped dependencies."""

    def test_process_global_dependency_accessors_are_not_exposed(self):
        from pubmed_search.presentation.mcp_server.tools import pipeline_tools

        removed_api = (
            "get_pipeline_store",
            "set_pipeline_store",
            "get_pipeline_scheduler",
            "set_pipeline_scheduler",
        )
        assert all(not hasattr(pipeline_tools, name) for name in removed_api)

    def test_dependencies_are_empty_initially(self, runtime):
        assert runtime.store_for_current_tenant() is None
        assert runtime.scheduler is None

    def test_dependencies_are_owned_by_runtime(self, runtime):
        store = MagicMock()
        scheduler = MagicMock()
        runtime.base_store = store
        runtime.scheduler = scheduler
        assert runtime.store_for_current_tenant() is store
        assert runtime.scheduler is scheduler


# =========================================================================
# save_pipeline
# =========================================================================


class TestSavePipeline:
    """Tests for save_pipeline tool."""

    def test_save_success(self, mcp, mock_store):
        meta = PipelineMeta(
            name="test_pipe",
            scope=PipelineScope.WORKSPACE,
            config_hash="abc12345",
            step_count=2,
        )
        result = ValidationResult(
            valid=True,
            config=PipelineConfig(
                steps=[PipelineStep(id="s1", action="search"), PipelineStep(id="s2", action="details")]
            ),
        )
        mock_store.save.return_value = (meta, result)

        output = mcp["save_pipeline"](
            name="test_pipe",
            config="steps:\n  - id: s1\n    action: search\n  - id: s2\n    action: details",
        )
        assert "✅" in output
        assert "test_pipe" in output
        assert "saved:test_pipe" in output

    def test_save_no_store(self, mcp):
        output = mcp["save_pipeline"](name="x", config="template: pico")
        assert "not initialized" in output.lower()

    def test_save_invalid_yaml(self, mcp, mock_store):
        output = mcp["save_pipeline"](name="x", config="[invalid: yaml:")
        assert "Invalid YAML" in output or "Error" in output or "error" in output.lower()

    def test_save_non_dict_yaml(self, mcp, mock_store):
        output = mcp["save_pipeline"](name="x", config="- just\n- a\n- list")
        assert "dict" in output.lower() or "object" in output.lower()

    def test_save_validation_error(self, mcp, mock_store):
        """Config with unfixable errors should show error message."""
        # Empty steps config will fail validation in parse_and_validate_config
        output = mcp["save_pipeline"](name="x", config="steps: []")
        assert "error" in output.lower() or "failed" in output.lower()

    def test_save_with_tags(self, mcp, mock_store):
        meta = PipelineMeta(
            name="tagged",
            scope=PipelineScope.GLOBAL,
            tags=["a", "b"],
            config_hash="x",
        )
        result = ValidationResult(
            valid=True,
            config=PipelineConfig(template="pico", template_params={"P": "ICU", "I": "remimazolam"}),
        )
        mock_store.save.return_value = (meta, result)

        output = mcp["save_pipeline"](
            name="tagged",
            config="template: pico\ntemplate_params:\n  P: ICU\n  I: remimazolam",
            tags=["a", "b"],
        )
        assert "tagged" in output
        mock_store.save.assert_called_once_with(
            name="tagged",
            config=result.config,
            tags=["a", "b"],
            description="",
            scope="auto",
        )

    def test_save_rejects_csv_tags_without_coercion(self, mcp, mock_store):
        output = mcp["save_pipeline"](
            name="tagged",
            config="template: pico",
            tags="a,b",
        )

        assert "JSON array" in output
        mock_store.save.assert_not_called()

    def test_save_store_value_error(self, mcp, mock_store):
        mock_store.save.side_effect = ValueError("bad config")
        output = mcp["save_pipeline"](
            name="bad",
            config="steps:\n  - id: s1\n    action: search",
        )
        assert "bad config" in output


# =========================================================================
# list_pipelines
# =========================================================================


class TestListPipelines:
    """Tests for list_pipelines tool."""

    def test_list_empty(self, mcp, mock_store):
        mock_store.list_pipelines.return_value = []
        output = mcp["list_pipelines"]()
        assert "No saved pipelines" in output

    def test_list_with_data(self, mcp, mock_store):
        mock_store.list_pipelines.return_value = [
            PipelineMeta(
                name="pipe1",
                scope=PipelineScope.WORKSPACE,
                description="desc1",
                tags=["tag1"],
                run_count=3,
            ),
            PipelineMeta(
                name="pipe2",
                scope=PipelineScope.GLOBAL,
                description="desc2",
                tags=[],
                run_count=0,
            ),
        ]
        output = mcp["list_pipelines"]()
        assert "pipe1" in output
        assert "pipe2" in output
        assert "2 total" in output
        assert "workspace" in output

    def test_list_no_store(self, mcp):
        output = mcp["list_pipelines"]()
        assert "not initialized" in output.lower()

    def test_list_with_tag_filter(self, mcp, mock_store):
        mock_store.list_pipelines.return_value = []
        output = mcp["list_pipelines"](tag="sedation")
        assert "sedation" in output
        mock_store.list_pipelines.assert_called_once_with(tag="sedation", scope="")

    def test_list_with_scope_filter(self, mcp, mock_store):
        mock_store.list_pipelines.return_value = []
        mcp["list_pipelines"](scope="global")
        mock_store.list_pipelines.assert_called_once_with(tag="", scope="global")


# =========================================================================
# load_pipeline
# =========================================================================


class TestLoadPipeline:
    """Tests for load_pipeline tool."""

    def test_load_by_name(self, mcp, mock_store):
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search", params={"query": "test"})],
            output=PipelineOutput(limit=20, ranking="balanced"),
        )
        meta = PipelineMeta(
            name="loaded",
            scope=PipelineScope.WORKSPACE,
            description="Test desc",
            tags=["test"],
        )
        mock_store.load.return_value = (config, meta)

        output = mcp["load_pipeline"](source="loaded")
        assert "loaded" in output
        assert "search" in output
        assert "saved:loaded" in output

    def test_load_with_saved_prefix(self, mcp, mock_store):
        config = PipelineConfig(template="pico")
        meta = PipelineMeta(name="prefixed", scope=PipelineScope.GLOBAL)
        mock_store.load.return_value = (config, meta)

        mcp["load_pipeline"](source="saved:prefixed")
        mock_store.load.assert_called_once_with("saved:prefixed")

    def test_load_from_file(self, mcp, mock_store):
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search")],
        )
        result = ValidationResult(valid=True, config=config)
        mock_store.load_from_path.return_value = (config, result)

        output = mcp["load_pipeline"](source="file:path/to/pipe.yaml")
        assert "file" in output.lower()
        mock_store.load_from_path.assert_called_once_with("path/to/pipe.yaml")

    def test_authenticated_service_cannot_load_pipeline_from_server_file(self, mcp, mock_store):
        identity = TenantIdentity.for_principal("remote-team", source="auth")

        with bind_tenant(identity):
            output = mcp["load_pipeline"](source="file:path/to/pipe.yaml")

        assert "cannot read pipeline files" in output.lower()
        mock_store.load_from_path.assert_not_called()

    def test_load_not_found(self, mcp, mock_store):
        private_path = "/srv/private/tenant-a/pipelines/nonexistent.yaml"
        mock_store.load.side_effect = FileNotFoundError(private_path)
        output = mcp["load_pipeline"](source="nonexistent")
        assert "saved pipeline was not found" in output.lower()
        assert private_path not in output

    def test_missing_file_does_not_expose_host_path(self, mcp, mock_store):
        private_path = "/srv/private/tenant-a/pipelines/secret.yaml"
        mock_store.load_from_path.side_effect = FileNotFoundError(private_path)

        output = mcp["load_pipeline"](source="file:requested.yaml")

        assert "pipeline file was not found or is not accessible" in output.lower()
        assert private_path not in output

    def test_load_no_store(self, mcp):
        output = mcp["load_pipeline"](source="x")
        assert "not initialized" in output.lower()

    def test_load_validation_error(self, mcp, mock_store):
        mock_store.load.side_effect = ValueError("unfixable error")
        output = mcp["load_pipeline"](source="broken")
        assert "unfixable" in output.lower() or "error" in output.lower()


# =========================================================================
# delete_pipeline
# =========================================================================


class TestDeletePipeline:
    """Tests for delete_pipeline tool."""

    def test_delete_success(self, mcp, mock_store):
        mock_store.delete.return_value = (PipelineScope.WORKSPACE, 3)
        output = mcp["delete_pipeline"](name="deleteme")
        assert "🗑️" in output
        assert "deleteme" in output
        assert "3" in output

    def test_delete_not_found(self, mcp, mock_store):
        mock_store.delete.side_effect = FileNotFoundError("not found")
        output = mcp["delete_pipeline"](name="nonexistent")
        assert "not found" in output.lower()

    def test_delete_no_store(self, mcp):
        output = mcp["delete_pipeline"](name="x")
        assert "not initialized" in output.lower()


# =========================================================================
# get_pipeline_history
# =========================================================================


class TestGetPipelineHistory:
    """Tests for get_pipeline_history tool."""

    def test_history_with_data(self, mcp, mock_store):
        mock_store.exists.return_value = True
        runs = [
            PipelineRun(
                run_id="run_002",
                pipeline_name="hist",
                started=datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
                status="success",
                article_count=10,
                new_pmids=["111", "222"],
                removed_pmids=["333"],
            ),
            PipelineRun(
                run_id="run_001",
                pipeline_name="hist",
                started=datetime(2024, 6, 14, 10, 0, tzinfo=timezone.utc),
                status="success",
                article_count=8,
            ),
        ]
        mock_store.get_history.return_value = runs
        mock_store.count_history.return_value = 5

        output = mcp["get_pipeline_history"](name="hist")
        assert "hist" in output
        assert "run_002" not in output  # run_id is not displayed directly
        assert "10" in output  # article_count
        mock_store.count_history.assert_called_once_with("hist")

    def test_history_empty(self, mcp, mock_store):
        mock_store.exists.return_value = True
        mock_store.get_history.return_value = []
        output = mcp["get_pipeline_history"](name="empty")
        assert "no execution history" in output.lower()

    def test_corrupt_history_is_not_reported_as_empty(self, mcp, mock_store):
        mock_store.exists.return_value = True
        mock_store.get_history.side_effect = PipelineHistoryError(
            "private-token at /srv/private/pipeline_runs/bad.json"
        )

        output = mcp["get_pipeline_history"](name="corrupt")

        assert "stored record is invalid" in output
        assert "no execution history" not in output.lower()
        assert "private-token" not in output
        assert "/srv/private" not in output
        mock_store.count_history.assert_not_called()

    def test_history_not_found(self, mcp, mock_store):
        mock_store.exists.return_value = False
        output = mcp["get_pipeline_history"](name="nonexistent")
        assert "not found" in output.lower()

    def test_history_no_store(self, mcp):
        output = mcp["get_pipeline_history"](name="x")
        assert "not initialized" in output.lower()


# =========================================================================
# schedule_pipeline
# =========================================================================


class TestSchedulePipeline:
    """Tests for scheduler-backed schedule_pipeline."""

    def test_set_schedule(self, mcp, mock_scheduler):
        mock_scheduler.schedule.return_value = ScheduleEntry(
            pipeline_name="test",
            cron="0 9 * * 1",
            next_run=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc),
        )

        output = mcp["schedule_pipeline"](name="test", cron="0 9 * * 1")

        assert "Schedule set" in output
        assert "0 9 * * 1" in output
        mock_scheduler.schedule.assert_called_once_with("test", "0 9 * * 1", diff_mode=True, notify=True)

    def test_remove_schedule(self, mcp, mock_scheduler):
        mock_scheduler.unschedule.return_value = ScheduleEntry(
            pipeline_name="my_pipe",
            cron="0 9 * * 1",
            last_status="success",
        )

        output = mcp["unschedule_pipeline"](name="my_pipe")

        assert "Schedule removed" in output
        mock_scheduler.unschedule.assert_called_once_with("my_pipe")

    def test_no_scheduler(self, mcp):
        output = mcp["schedule_pipeline"](name="test", cron="0 9 * * 1")
        assert "not initialized" in output.lower()

    def test_missing_saved_pipeline_does_not_expose_store_path(self, mcp, mock_scheduler):
        private_path = "/srv/private/pipelines/test.yaml"
        mock_scheduler.schedule.side_effect = FileNotFoundError(private_path)

        output = mcp["schedule_pipeline"](name="test", cron="0 9 * * 1")

        assert "saved pipeline 'test' was not found" in output.lower()
        assert private_path not in output

    def test_scheduler_runtime_failures_are_query_safe(self, mcp, mock_scheduler):
        secret = "token=private-scheduler-token"
        mock_scheduler.schedule.side_effect = RuntimeError(secret)

        schedule_output = mcp["schedule_pipeline"](name="test", cron="0 9 * * 1")

        assert "could not create or update" in schedule_output.lower()
        assert secret not in schedule_output

        mock_scheduler.unschedule.side_effect = RuntimeError(secret)
        unschedule_output = mcp["unschedule_pipeline"](name="test")

        assert "could not remove" in unschedule_output.lower()
        assert secret not in unschedule_output


# =========================================================================
# _config_to_display_dict
# =========================================================================


class TestConfigToDisplayDict:
    """Display uses the canonical config serializer with explicit defaults."""

    def test_step_config_display(self):
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search", params={"query": "test"})],
            output=PipelineOutput(limit=10, ranking="impact"),
        )
        d = _config_to_dict(config, include_output_defaults=True)
        assert "steps" in d
        assert d["output"] == {"format": "markdown", "limit": 10, "ranking": "impact"}

    def test_template_config_display(self):
        config = PipelineConfig(
            template="pico",
            template_params={"query": "test"},
        )
        d = _config_to_dict(config, include_output_defaults=True)
        assert d["template"] == "pico"
        assert "steps" not in d

    def test_always_includes_output(self):
        """Display mode includes defaults omitted from compact stored config."""
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search")],
        )
        d = _config_to_dict(config, include_output_defaults=True)
        assert "output" in d

    def test_display_includes_json_format_globals_and_variables(self):
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search")],
            output=PipelineOutput(format="json", limit=10, ranking="impact"),
            globals={"sources": ["pubmed"]},
            variables={"topic": "remimazolam"},
        )
        d = _config_to_dict(config, include_output_defaults=True)
        assert d["output"] == {"format": "json", "limit": 10, "ranking": "impact"}
        assert d["globals"] == {"sources": ["pubmed"]}
        assert d["variables"] == {"topic": "remimazolam"}


# =========================================================================
# Integration: Real Store + Tools
# =========================================================================


class TestToolsIntegration:
    """Integration tests using real PipelineStore."""

    def test_save_and_load_roundtrip(self, mcp, real_store):
        config_yaml = "steps:\n  - id: s1\n    action: search\n    params:\n      query: test"
        save_output = mcp["save_pipeline"](name="roundtrip", config=config_yaml)
        assert "✅" in save_output

        load_output = mcp["load_pipeline"](source="roundtrip")
        assert "search" in load_output
        assert "roundtrip" in load_output

    def test_save_list_delete_cycle(self, mcp, real_store):
        config_yaml = "template: pico\ntemplate_params:\n  P: ICU\n  I: remimazolam"
        mcp["save_pipeline"](name="cycle_test", config=config_yaml)

        list_output = mcp["list_pipelines"]()
        assert "cycle_test" in list_output

        delete_output = mcp["delete_pipeline"](name="cycle_test")
        assert "🗑️" in delete_output

        list_output2 = mcp["list_pipelines"]()
        assert "No saved pipelines" in list_output2

    def test_save_rejects_retired_action_alias(self, mcp, real_store):
        config_yaml = "steps:\n  - id: s1\n    action: find\n    params:\n      query: test"
        output = mcp["save_pipeline"](name="rejected", config=config_yaml)

        assert "unknown action" in output.lower()
        assert "find" in output
