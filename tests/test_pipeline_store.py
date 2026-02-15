"""Tests for PipelineStore — dual-scope CRUD persistence.

Coverage targets:
- Save / Load / List / Delete CRUD cycle
- Dual-scope resolution (workspace → global)
- Index management (JSON metadata)
- Run history (save, get, prune)
- Name normalization on load
- File not found errors
- Auto-fix on load (validation re-applied)
- Workspace fallback when not configured
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest
import yaml

from pubmed_search.application.pipeline.store import PipelineStore, _config_to_dict
from pubmed_search.domain.entities.pipeline import (
    PipelineConfig,
    PipelineOutput,
    PipelineRun,
    PipelineScope,
    PipelineStep,
)

if TYPE_CHECKING:
    from pathlib import Path

# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture()
def global_dir(tmp_path: Path) -> Path:
    """Global data directory."""
    d = tmp_path / "global"
    d.mkdir()
    return d


@pytest.fixture()
def workspace_dir(tmp_path: Path) -> Path:
    """Workspace root directory."""
    d = tmp_path / "workspace"
    d.mkdir()
    return d


@pytest.fixture()
def store_dual(global_dir: Path, workspace_dir: Path) -> PipelineStore:
    """PipelineStore with both global and workspace scopes."""
    return PipelineStore(global_data_dir=global_dir, workspace_dir=workspace_dir)


@pytest.fixture()
def store_global_only(global_dir: Path) -> PipelineStore:
    """PipelineStore with global scope only (no workspace)."""
    return PipelineStore(global_data_dir=global_dir)


@pytest.fixture()
def simple_config() -> PipelineConfig:
    """A valid 2-step pipeline config."""
    return PipelineConfig(
        steps=[
            PipelineStep(id="s1", action="search", params={"query": "test"}),
            PipelineStep(id="s2", action="details", inputs=["s1"]),
        ]
    )


@pytest.fixture()
def template_config() -> PipelineConfig:
    """A template-based pipeline config."""
    return PipelineConfig(
        template="pico",
        template_params={"query": "remimazolam vs propofol"},
    )


# =========================================================================
# _config_to_dict helper
# =========================================================================


class TestConfigToDict:
    """Tests for _config_to_dict serialization."""

    def test_step_config(self, simple_config: PipelineConfig):
        d = _config_to_dict(simple_config)
        assert "steps" in d
        assert len(d["steps"]) == 2
        assert d["steps"][0]["action"] == "search"

    def test_template_config(self, template_config: PipelineConfig):
        d = _config_to_dict(template_config)
        assert d["template"] == "pico"
        assert "steps" not in d

    def test_output_omitted_when_defaults(self):
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search")],
        )
        d = _config_to_dict(config)
        assert "output" not in d

    def test_output_included_when_non_default(self):
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search")],
            output=PipelineOutput(format="json"),
        )
        d = _config_to_dict(config)
        assert "output" in d
        assert d["output"]["format"] == "json"

    def test_on_error_skip_omitted(self):
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search", on_error="skip")],
        )
        d = _config_to_dict(config)
        assert "on_error" not in d["steps"][0]

    def test_on_error_abort_included(self):
        config = PipelineConfig(
            steps=[PipelineStep(id="s1", action="search", on_error="abort")],
        )
        d = _config_to_dict(config)
        assert d["steps"][0]["on_error"] == "abort"


# =========================================================================
# Store Initialization
# =========================================================================


class TestStoreInit:
    """Tests for PipelineStore initialization."""

    def test_creates_global_dirs(self, global_dir: Path):
        PipelineStore(global_data_dir=global_dir)
        assert (global_dir / "pipelines").is_dir()
        assert (global_dir / "pipeline_runs").is_dir()

    def test_creates_workspace_dirs(self, global_dir: Path, workspace_dir: Path):
        PipelineStore(global_data_dir=global_dir, workspace_dir=workspace_dir)
        assert (workspace_dir / ".pubmed-search" / "pipelines").is_dir()
        assert (workspace_dir / ".pubmed-search" / "pipeline_runs").is_dir()

    def test_global_only_no_workspace_dirs(self, global_dir: Path, workspace_dir: Path):
        PipelineStore(global_data_dir=global_dir)
        assert not (workspace_dir / ".pubmed-search").exists()


# =========================================================================
# Save
# =========================================================================


class TestStoreSave:
    """Tests for PipelineStore.save()."""

    def test_save_creates_yaml_file(
        self, store_dual: PipelineStore, simple_config: PipelineConfig, workspace_dir: Path
    ):
        meta, result = store_dual.save("my_pipeline", simple_config)
        yaml_path = workspace_dir / ".pubmed-search" / "pipelines" / "my_pipeline.yaml"
        assert yaml_path.exists()
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        assert "steps" in data

    def test_save_returns_meta(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        meta, result = store_dual.save("test_pipe", simple_config, tags=["a", "b"], description="desc")
        assert meta.name == "test_pipe"
        assert meta.tags == ["a", "b"]
        assert meta.description == "desc"
        assert meta.step_count == 2
        assert meta.config_hash
        assert meta.scope == PipelineScope.WORKSPACE

    def test_save_updates_index(self, store_dual: PipelineStore, simple_config: PipelineConfig, workspace_dir: Path):
        store_dual.save("indexed", simple_config)
        index_path = workspace_dir / ".pubmed-search" / "pipelines" / "_index.json"
        assert index_path.exists()
        index = json.loads(index_path.read_text(encoding="utf-8"))
        assert "indexed" in index

    def test_save_global_scope(self, store_dual: PipelineStore, simple_config: PipelineConfig, global_dir: Path):
        meta, _ = store_dual.save("global_pipe", simple_config, scope="global")
        assert meta.scope == PipelineScope.GLOBAL
        yaml_path = global_dir / "pipelines" / "global_pipe.yaml"
        assert yaml_path.exists()

    def test_save_auto_scope_prefers_workspace(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        meta, _ = store_dual.save("auto_pipe", simple_config, scope="auto")
        assert meta.scope == PipelineScope.WORKSPACE

    def test_save_auto_scope_falls_back_global(self, store_global_only: PipelineStore, simple_config: PipelineConfig):
        meta, _ = store_global_only.save("auto_pipe", simple_config, scope="auto")
        assert meta.scope == PipelineScope.GLOBAL

    def test_save_normalizes_name(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        meta, result = store_dual.save("My Pipeline!!", simple_config)
        assert meta.name == "my_pipeline"
        assert result.has_fixes

    def test_save_upsert_preserves_created(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        meta1, _ = store_dual.save("upsert", simple_config)
        created1 = meta1.created
        meta2, _ = store_dual.save("upsert", simple_config)
        assert meta2.created == created1
        assert meta2.updated >= meta1.updated

    def test_save_invalid_config_raises(self, store_dual: PipelineStore):
        bad_config = PipelineConfig(steps=[])
        with pytest.raises(ValueError, match="validation failed"):
            store_dual.save("bad", bad_config)

    def test_save_template_config(self, store_dual: PipelineStore, template_config: PipelineConfig):
        meta, result = store_dual.save("template_pipe", template_config)
        assert meta.step_count == 0  # template, no explicit steps
        assert result.valid

    def test_save_with_validation_fixes(self, store_dual: PipelineStore):
        """Config with fixable issues should be saved with fixes applied."""
        config = PipelineConfig(
            steps=[PipelineStep(id="", action="find")]  # auto-gen id + alias fix
        )
        meta, result = store_dual.save("fixable", config)
        assert result.valid is True
        assert result.has_fixes


# =========================================================================
# Load
# =========================================================================


class TestStoreLoad:
    """Tests for PipelineStore.load()."""

    def test_load_saved_pipeline(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        store_dual.save("loadme", simple_config)
        config, meta = store_dual.load("loadme")
        assert len(config.steps) == 2
        assert meta.name == "loadme"

    def test_load_with_saved_prefix(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        store_dual.save("prefixed", simple_config)
        config, meta = store_dual.load("saved:prefixed")
        assert meta.name == "prefixed"

    def test_load_case_insensitive(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        store_dual.save("MyPipe", simple_config)
        config, meta = store_dual.load("mypipe")
        assert config is not None

    def test_load_workspace_priority(
        self, store_dual: PipelineStore, simple_config: PipelineConfig, global_dir: Path, workspace_dir: Path
    ):
        """Workspace pipeline should be found before global."""
        # Save to both scopes
        store_dual.save("shared", simple_config, scope="workspace")
        store_dual.save("shared", simple_config, scope="global")

        _, meta = store_dual.load("shared")
        assert meta.scope == PipelineScope.WORKSPACE

    def test_load_global_fallback(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        """If not in workspace, fall back to global."""
        store_dual.save("global_only", simple_config, scope="global")
        _, meta = store_dual.load("global_only")
        assert meta.scope == PipelineScope.GLOBAL

    def test_load_not_found_raises(self, store_dual: PipelineStore):
        with pytest.raises(FileNotFoundError, match="not found"):
            store_dual.load("nonexistent")

    def test_load_auto_fixes_saved_back(self, store_dual: PipelineStore, workspace_dir: Path):
        """If loaded file has fixable issues, fixes are saved back."""
        # Write a YAML with a fixable action alias
        yaml_path = workspace_dir / ".pubmed-search" / "pipelines" / "fixable.yaml"
        yaml_path.write_text(
            yaml.dump({"steps": [{"id": "s1", "action": "find"}]}),
            encoding="utf-8",
        )
        config, meta = store_dual.load("fixable")
        assert config.steps[0].action == "search"  # auto-fixed
        # Check that fix was saved back
        reloaded = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        assert reloaded["steps"][0]["action"] == "search"


# =========================================================================
# Load from Path
# =========================================================================


class TestStoreLoadFromPath:
    """Tests for PipelineStore.load_from_path()."""

    def test_load_from_file(self, store_dual: PipelineStore, tmp_path: Path):
        filepath = tmp_path / "test.yaml"
        filepath.write_text(
            yaml.dump({"steps": [{"id": "s1", "action": "search", "params": {"query": "test"}}]}),
            encoding="utf-8",
        )
        config, result = store_dual.load_from_path(filepath)
        assert config is not None
        assert result.valid is True

    def test_load_from_nonexistent_file(self, store_dual: PipelineStore):
        with pytest.raises(FileNotFoundError):
            store_dual.load_from_path("/nonexistent/path.yaml")

    def test_load_from_invalid_yaml(self, store_dual: PipelineStore, tmp_path: Path):
        filepath = tmp_path / "invalid.yaml"
        filepath.write_text("not: [valid: yaml:", encoding="utf-8")
        # yaml.safe_load may produce unexpected data → validation should catch it
        with pytest.raises((ValueError, Exception)):
            store_dual.load_from_path(filepath)


# =========================================================================
# List
# =========================================================================


class TestStoreList:
    """Tests for PipelineStore.list_pipelines()."""

    def test_list_empty(self, store_dual: PipelineStore):
        result = store_dual.list_pipelines()
        assert result == []

    def test_list_returns_saved(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        store_dual.save("pipe1", simple_config, tags=["tag1"])
        store_dual.save("pipe2", simple_config, tags=["tag2"])
        result = store_dual.list_pipelines()
        assert len(result) == 2

    def test_list_filter_by_tag(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        store_dual.save("pipe1", simple_config, tags=["sedation"])
        store_dual.save("pipe2", simple_config, tags=["other"])
        result = store_dual.list_pipelines(tag="sedation")
        assert len(result) == 1
        assert result[0].name == "pipe1"

    def test_list_filter_by_scope(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        store_dual.save("ws_pipe", simple_config, scope="workspace")
        store_dual.save("gl_pipe", simple_config, scope="global")
        ws_result = store_dual.list_pipelines(scope="workspace")
        gl_result = store_dual.list_pipelines(scope="global")
        assert len(ws_result) == 1
        assert ws_result[0].scope == PipelineScope.WORKSPACE
        assert len(gl_result) == 1
        assert gl_result[0].scope == PipelineScope.GLOBAL

    def test_list_sorted_newest_first(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        store_dual.save("pipe_old", simple_config)
        store_dual.save("pipe_new", simple_config)
        result = store_dual.list_pipelines()
        assert result[0].name == "pipe_new"

    def test_list_workspace_shadows_global(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        """Same name in workspace and global: only workspace shown."""
        store_dual.save("shared", simple_config, scope="workspace")
        store_dual.save("shared", simple_config, scope="global")
        result = store_dual.list_pipelines()
        assert len(result) == 1
        assert result[0].scope == PipelineScope.WORKSPACE


# =========================================================================
# Delete
# =========================================================================


class TestStoreDelete:
    """Tests for PipelineStore.delete()."""

    def test_delete_removes_yaml(self, store_dual: PipelineStore, simple_config: PipelineConfig, workspace_dir: Path):
        store_dual.save("deleteme", simple_config)
        yaml_path = workspace_dir / ".pubmed-search" / "pipelines" / "deleteme.yaml"
        assert yaml_path.exists()
        store_dual.delete("deleteme")
        assert not yaml_path.exists()

    def test_delete_removes_from_index(
        self, store_dual: PipelineStore, simple_config: PipelineConfig, workspace_dir: Path
    ):
        store_dual.save("indexed", simple_config)
        store_dual.delete("indexed")
        index_path = workspace_dir / ".pubmed-search" / "pipelines" / "_index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        assert "indexed" not in index

    def test_delete_not_found_raises(self, store_dual: PipelineStore):
        with pytest.raises(FileNotFoundError, match="not found"):
            store_dual.delete("nonexistent")

    def test_delete_returns_scope_and_count(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        store_dual.save("counted", simple_config)
        scope, count = store_dual.delete("counted")
        assert scope == PipelineScope.WORKSPACE
        assert count == 0  # no runs yet


# =========================================================================
# Exists
# =========================================================================


class TestStoreExists:
    """Tests for PipelineStore.exists()."""

    def test_exists_true(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        store_dual.save("existing", simple_config)
        assert store_dual.exists("existing") is True

    def test_exists_false(self, store_dual: PipelineStore):
        assert store_dual.exists("nonexistent") is False

    def test_exists_case_insensitive(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        store_dual.save("CamelCase", simple_config)
        assert store_dual.exists("camelcase") is True


# =========================================================================
# Run History
# =========================================================================


class TestStoreRunHistory:
    """Tests for PipelineStore run history methods."""

    def _make_run(self, name: str, run_id: str, **kwargs) -> PipelineRun:
        return PipelineRun(
            run_id=run_id,
            pipeline_name=name,
            started=kwargs.get("started", datetime.now(timezone.utc)),
            finished=kwargs.get("finished", datetime.now(timezone.utc)),
            status=kwargs.get("status", "success"),
            article_count=kwargs.get("article_count", 5),
            pmids=kwargs.get("pmids", ["12345678"]),
        )

    def test_save_and_get_history(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        store_dual.save("history_pipe", simple_config)
        run = self._make_run("history_pipe", "run_001")
        store_dual.save_run("history_pipe", run)

        history = store_dual.get_history("history_pipe")
        assert len(history) == 1
        assert history[0].run_id == "run_001"

    def test_history_limit(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        store_dual.save("limited", simple_config)
        for i in range(10):
            run = self._make_run("limited", f"run_{i:03d}")
            store_dual.save_run("limited", run)

        history = store_dual.get_history("limited", limit=3)
        assert len(history) == 3

    def test_history_newest_first(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        store_dual.save("ordered", simple_config)
        for i in range(5):
            run = self._make_run("ordered", f"run_{i:03d}")
            store_dual.save_run("ordered", run)

        history = store_dual.get_history("ordered")
        # Files sorted reverse by name → highest run_id first
        assert history[0].run_id > history[-1].run_id

    def test_get_latest_run(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        store_dual.save("latest", simple_config)
        store_dual.save_run("latest", self._make_run("latest", "run_001"))
        store_dual.save_run("latest", self._make_run("latest", "run_002"))

        latest = store_dual.get_latest_run("latest")
        assert latest is not None
        assert latest.run_id == "run_002"

    def test_get_latest_run_empty(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        store_dual.save("empty_history", simple_config)
        assert store_dual.get_latest_run("empty_history") is None

    def test_save_run_increments_count(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        store_dual.save("counted", simple_config)
        store_dual.save_run("counted", self._make_run("counted", "run_001"))

        pipelines = store_dual.list_pipelines()
        meta = next(p for p in pipelines if p.name == "counted")
        assert meta.run_count == 1

    def test_delete_with_runs(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        store_dual.save("with_runs", simple_config)
        store_dual.save_run("with_runs", self._make_run("with_runs", "run_001"))
        store_dual.save_run("with_runs", self._make_run("with_runs", "run_002"))

        scope, run_count = store_dual.delete("with_runs")
        assert run_count == 2

    def test_history_empty_for_nonexistent_dir(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        """get_history when run dir doesn't exist should return empty."""
        store_dual.save("no_runs", simple_config)
        history = store_dual.get_history("no_runs")
        assert history == []


# =========================================================================
# PipelineMeta Serialization
# =========================================================================


class TestPipelineMetaSerialization:
    """Tests for PipelineMeta.to_dict() and from_dict()."""

    def test_roundtrip(self, store_dual: PipelineStore, simple_config: PipelineConfig):
        store_dual.save("roundtrip", simple_config, tags=["a", "b"], description="test")
        _, meta1 = store_dual.load("roundtrip")
        d = meta1.to_dict()
        from pubmed_search.domain.entities.pipeline import PipelineMeta

        meta2 = PipelineMeta.from_dict(d)
        assert meta2.name == meta1.name
        assert meta2.scope == meta1.scope
        assert meta2.tags == meta1.tags


# =========================================================================
# PipelineRun Serialization
# =========================================================================


class TestPipelineRunSerialization:
    """Tests for PipelineRun.to_dict() and from_dict()."""

    def test_roundtrip(self):
        now = datetime.now(timezone.utc)
        run = PipelineRun(
            run_id="run_001",
            pipeline_name="test",
            started=now,
            finished=now,
            status="success",
            article_count=10,
            pmids=["12345678"],
            new_pmids=["12345678"],
            removed_pmids=[],
            error_message=None,
            top_articles=[{"pmid": "12345678", "title": "Test"}],
        )
        d = run.to_dict()
        run2 = PipelineRun.from_dict(d)
        assert run2.run_id == "run_001"
        assert run2.article_count == 10
        assert run2.pmids == ["12345678"]
        assert run2.new_pmids == ["12345678"]
        assert run2.top_articles == [{"pmid": "12345678", "title": "Test"}]

    def test_from_dict_with_defaults(self):
        run = PipelineRun.from_dict({"run_id": "minimal"})
        assert run.run_id == "minimal"
        assert run.pipeline_name == ""
        assert run.status == "success"
        assert run.pmids == []


# =========================================================================
# Scope Resolution Edge Cases
# =========================================================================


class TestScopeResolution:
    """Tests for _resolve_scope edge cases."""

    def test_workspace_without_workspace_dir(self, store_global_only: PipelineStore):
        """Requesting workspace without one configured should fall back."""
        scope = store_global_only._resolve_scope("workspace")
        assert scope == PipelineScope.GLOBAL

    def test_auto_with_workspace(self, store_dual: PipelineStore):
        scope = store_dual._resolve_scope("auto")
        assert scope == PipelineScope.WORKSPACE

    def test_auto_without_workspace(self, store_global_only: PipelineStore):
        scope = store_global_only._resolve_scope("auto")
        assert scope == PipelineScope.GLOBAL

    def test_global_always_global(self, store_dual: PipelineStore):
        scope = store_dual._resolve_scope("global")
        assert scope == PipelineScope.GLOBAL
