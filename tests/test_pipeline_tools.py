"""Tests for pipeline MCP tools.

Coverage targets:
- save_pipeline: YAML parsing, validation, store integration
- list_pipelines: empty, with data, tag/scope filtering
- load_pipeline: saved name, "saved:" prefix, "file:" prefix, not found
- delete_pipeline: success, not found
- get_pipeline_history: success, empty, not found
- schedule_pipeline: Phase 4 stub
- Error cases: store not initialized, invalid YAML, unfixable configs
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from pubmed_search.domain.entities.pipeline import (
    PipelineConfig,
    PipelineMeta,
    PipelineOutput,
    PipelineRun,
    PipelineScope,
    PipelineStep,
    ValidationFix,
    ValidationResult,
)
from pubmed_search.presentation.mcp_server.tools.pipeline_tools import (
    _config_to_display_dict,
    get_pipeline_store,
    register_pipeline_tools,
    set_pipeline_store,
)

if TYPE_CHECKING:
    from pathlib import Path

# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture(autouse=True)
def _reset_store():
    """Reset the module-level store before/after each test."""
    set_pipeline_store(None)
    yield
    set_pipeline_store(None)


@pytest.fixture()
def mock_store():
    """A MagicMock PipelineStore."""
    store = MagicMock()
    set_pipeline_store(store)
    return store


@pytest.fixture()
def real_store(tmp_path: Path):
    """A real PipelineStore with tmp dirs."""
    from pubmed_search.application.pipeline.store import PipelineStore

    global_dir = tmp_path / "global"
    global_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    store = PipelineStore(global_data_dir=global_dir, workspace_dir=workspace_dir)
    set_pipeline_store(store)
    return store


@pytest.fixture()
def mcp():
    """A mock MCP server to capture registered tools."""
    mock_mcp = MagicMock()
    registered_tools = {}

    def mock_tool_decorator():
        def decorator(func):
            registered_tools[func.__name__] = func
            return func

        return decorator

    mock_mcp.tool = mock_tool_decorator
    register_pipeline_tools(mock_mcp)
    return registered_tools


# =========================================================================
# Tool Registration
# =========================================================================


class TestToolRegistration:
    """Tests that all 6 tools are registered."""

    def test_all_tools_registered(self, mcp):
        expected = {
            "save_pipeline",
            "list_pipelines",
            "load_pipeline",
            "delete_pipeline",
            "get_pipeline_history",
            "schedule_pipeline",
        }
        assert set(mcp.keys()) == expected


# =========================================================================
# set/get pipeline store
# =========================================================================


class TestStoreAccessors:
    """Tests for set_pipeline_store / get_pipeline_store."""

    def test_get_returns_none_initially(self):
        assert get_pipeline_store() is None

    def test_set_and_get(self):
        store = MagicMock()
        set_pipeline_store(store)
        assert get_pipeline_store() is store


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
        result = ValidationResult(valid=True, config=PipelineConfig(template="pico"))
        mock_store.save.return_value = (meta, result)

        output = mcp["save_pipeline"](
            name="tagged",
            config="template: pico",
            tags="a,b",
        )
        assert "tagged" in output

    def test_save_shows_auto_fixes(self, mcp, mock_store):
        meta = PipelineMeta(name="fixed", scope=PipelineScope.WORKSPACE, config_hash="x")
        result = ValidationResult(
            valid=True,
            fixes=[ValidationFix(field="step.action", original="find", corrected="search", reason="alias")],
            config=PipelineConfig(steps=[PipelineStep(id="s1", action="search")]),
        )
        mock_store.save.return_value = (meta, result)

        output = mcp["save_pipeline"](name="fixed", config="steps:\n  - id: s1\n    action: search")
        assert "Auto-fixed" in output or "🔧" in output

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
            output=PipelineOutput(format="markdown", limit=20, ranking="balanced"),
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

    def test_load_not_found(self, mcp, mock_store):
        mock_store.load.side_effect = FileNotFoundError("not found")
        output = mcp["load_pipeline"](source="nonexistent")
        assert "not found" in output.lower() or "Error" in output

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

        # Mock the _runs_dir_for and _find_pipeline_scope
        mock_runs_dir = MagicMock()
        mock_pipe_dir = MagicMock()
        mock_pipe_dir.glob.return_value = [MagicMock() for _ in range(5)]  # 5 total runs
        mock_runs_dir.__truediv__ = MagicMock(return_value=mock_pipe_dir)
        mock_store._runs_dir_for.return_value = mock_runs_dir
        mock_store._find_pipeline_scope.return_value = PipelineScope.WORKSPACE

        output = mcp["get_pipeline_history"](name="hist")
        assert "hist" in output
        assert "run_002" not in output  # run_id is not displayed directly
        assert "10" in output  # article_count

    def test_history_empty(self, mcp, mock_store):
        mock_store.exists.return_value = True
        mock_store.get_history.return_value = []
        output = mcp["get_pipeline_history"](name="empty")
        assert "no execution history" in output.lower()

    def test_history_not_found(self, mcp, mock_store):
        mock_store.exists.return_value = False
        output = mcp["get_pipeline_history"](name="nonexistent")
        assert "not found" in output.lower()

    def test_history_no_store(self, mcp):
        output = mcp["get_pipeline_history"](name="x")
        assert "not initialized" in output.lower()


# =========================================================================
# schedule_pipeline (stub)
# =========================================================================


class TestSchedulePipeline:
    """Tests for schedule_pipeline Phase 4 stub."""

    def test_stub_returns_message(self, mcp):
        output = mcp["schedule_pipeline"](name="test")
        assert "Phase 4" in output or "not yet implemented" in output

    def test_stub_includes_manual_alternatives(self, mcp):
        output = mcp["schedule_pipeline"](name="my_pipe")
        assert "my_pipe" in output
        assert "unified_search" in output or "manually" in output.lower()


# =========================================================================
# _config_to_display_dict
# =========================================================================


class TestConfigToDisplayDict:
    """Tests for _config_to_display_dict helper."""

    def test_step_config_display(self):
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search", params={"query": "test"})],
            output=PipelineOutput(format="json", limit=10, ranking="impact"),
        )
        d = _config_to_display_dict(config)
        assert "steps" in d
        assert d["output"]["format"] == "json"

    def test_template_config_display(self):
        config = PipelineConfig(
            template="pico",
            template_params={"query": "test"},
        )
        d = _config_to_display_dict(config)
        assert d["template"] == "pico"
        assert "steps" not in d

    def test_always_includes_output(self):
        """_config_to_display_dict always includes output (unlike _config_to_dict)."""
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search")],
        )
        d = _config_to_display_dict(config)
        assert "output" in d


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
        config_yaml = "template: pico\ntemplate_params:\n  query: test"
        mcp["save_pipeline"](name="cycle_test", config=config_yaml)

        list_output = mcp["list_pipelines"]()
        assert "cycle_test" in list_output

        delete_output = mcp["delete_pipeline"](name="cycle_test")
        assert "🗑️" in delete_output

        list_output2 = mcp["list_pipelines"]()
        assert "No saved pipelines" in list_output2

    def test_save_with_auto_fix(self, mcp, real_store):
        """Pipeline with 'find' action should be auto-fixed to 'search'."""
        config_yaml = "steps:\n  - id: s1\n    action: find\n    params:\n      query: test"
        output = mcp["save_pipeline"](name="autofixed", config=config_yaml)
        assert "✅" in output
        # The tool internally parses+validates before store.save,
        # so auto-fix applies at parse time. The save should still succeed.
        assert "autofixed" in output
        assert "search" in output  # action was fixed from 'find' to 'search'
