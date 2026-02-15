"""Tests for pipeline report auto-save functionality.

Coverage targets:
- PipelineStore.save_report: workspace & global scope, directory creation
- PipelineStore._reports_dir_for: scope resolution
- _auto_save_pipeline_report: end-to-end auto-save from unified.py
- Workspace directory auto-detection in tool_registry
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from pubmed_search.application.pipeline.store import PipelineStore
from pubmed_search.domain.entities.pipeline import (
    PipelineConfig,
    PipelineOutput,
    PipelineScope,
)

if TYPE_CHECKING:
    from pathlib import Path


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture()
def global_store(tmp_path: Path) -> PipelineStore:
    """PipelineStore with only global scope (no workspace)."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    return PipelineStore(global_data_dir=global_dir)


@pytest.fixture()
def workspace_store(tmp_path: Path) -> PipelineStore:
    """PipelineStore with both global and workspace scope."""
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    return PipelineStore(global_data_dir=global_dir, workspace_dir=workspace_dir)


@pytest.fixture()
def sample_report() -> str:
    """A sample pipeline report markdown."""
    return (
        "# Pipeline Report\n\n"
        "## Executive Summary\n\n"
        "| Metric | Value |\n"
        "|--------|-------|\n"
        "| Articles | 10 |\n"
    )


@pytest.fixture()
def sample_config() -> PipelineConfig:
    """A sample pipeline config."""
    return PipelineConfig(
        name="test-pipeline",
        template="comprehensive",
        output=PipelineOutput(),
    )


# =========================================================================
# PipelineStore.save_report — Global scope
# =========================================================================


class TestSaveReportGlobal:
    """Tests for save_report when pipeline is in global scope."""

    def test_save_report_creates_file(self, global_store: PipelineStore, sample_report: str, tmp_path: Path):
        """Report file should be created at expected path."""
        # First save a pipeline so it exists
        config = PipelineConfig(template="comprehensive")
        global_store.save(name="my-pipe", config=config)

        path = global_store.save_report("my-pipe", "20260215_120000", sample_report)

        assert path.exists()
        assert path.name == "20260215_120000.md"
        assert "pipeline_reports" in str(path)
        assert "my-pipe" in str(path)

    def test_save_report_content_matches(self, global_store: PipelineStore, sample_report: str):
        """Saved report content should match input."""
        config = PipelineConfig(template="comprehensive")
        global_store.save(name="content-test", config=config)

        path = global_store.save_report("content-test", "run_001", sample_report)
        content = path.read_text(encoding="utf-8")

        assert content == sample_report

    def test_save_report_creates_subdirectory(self, global_store: PipelineStore, sample_report: str):
        """Should create the pipeline name subdirectory automatically."""
        config = PipelineConfig(template="pico")
        global_store.save(name="new-pipe", config=config)

        path = global_store.save_report("new-pipe", "run_001", sample_report)
        assert path.parent.name == "new-pipe"
        assert path.parent.exists()

    def test_save_multiple_reports(self, global_store: PipelineStore, sample_report: str):
        """Multiple reports for the same pipeline should coexist."""
        config = PipelineConfig(template="comprehensive")
        global_store.save(name="multi-run", config=config)

        p1 = global_store.save_report("multi-run", "run_001", sample_report)
        p2 = global_store.save_report("multi-run", "run_002", "# Report 2")

        assert p1.exists()
        assert p2.exists()
        assert p1 != p2


# =========================================================================
# PipelineStore.save_report — Workspace scope
# =========================================================================


class TestSaveReportWorkspace:
    """Tests for save_report when pipeline is in workspace scope."""

    def test_save_report_in_workspace(self, workspace_store: PipelineStore, sample_report: str, tmp_path: Path):
        """Report should be saved under workspace/.pubmed-search/pipeline_reports/."""
        config = PipelineConfig(template="comprehensive")
        workspace_store.save(name="ws-pipe", config=config, scope="workspace")

        path = workspace_store.save_report("ws-pipe", "run_001", sample_report)

        assert path.exists()
        assert ".pubmed-search" in str(path)
        assert "pipeline_reports" in str(path)
        # Should be under workspace dir, not global
        assert str(tmp_path / "workspace") in str(path)

    def test_workspace_report_is_git_trackable(self, workspace_store: PipelineStore, sample_report: str):
        """Reports in workspace scope should be in a git-trackable location."""
        config = PipelineConfig(template="pico")
        workspace_store.save(name="git-pipe", config=config, scope="workspace")

        path = workspace_store.save_report("git-pipe", "run_001", sample_report)

        # Path should be relative to workspace
        assert ".pubmed-search" in str(path)
        assert path.suffix == ".md"


# =========================================================================
# PipelineStore._reports_dir_for
# =========================================================================


class TestReportsDirFor:
    """Tests for _reports_dir_for helper."""

    def test_global_scope(self, global_store: PipelineStore, tmp_path: Path):
        d = global_store._reports_dir_for(PipelineScope.GLOBAL)
        assert "pipeline_reports" in str(d)
        assert str(tmp_path / "global") in str(d)

    def test_workspace_scope_with_workspace_dir(self, workspace_store: PipelineStore, tmp_path: Path):
        d = workspace_store._reports_dir_for(PipelineScope.WORKSPACE)
        assert ".pubmed-search" in str(d)
        assert str(tmp_path / "workspace") in str(d)

    def test_workspace_scope_without_workspace_dir_falls_back(self, global_store: PipelineStore):
        """When no workspace_dir, workspace scope falls back to global."""
        d = global_store._reports_dir_for(PipelineScope.WORKSPACE)
        assert "pipeline_reports" in str(d)


# =========================================================================
# _auto_save_pipeline_report
# =========================================================================


class TestAutoSavePipelineReport:
    """Tests for the auto-save function in unified.py."""

    def test_auto_save_with_named_pipeline(self, workspace_store: PipelineStore):
        """Auto-save should create report for named pipeline."""
        from pubmed_search.presentation.mcp_server.tools.pipeline_tools import set_pipeline_store

        set_pipeline_store(workspace_store)

        # Save a pipeline first
        config = PipelineConfig(name="auto-test", template="comprehensive")
        workspace_store.save(name="auto-test", config=config, scope="workspace")

        from pubmed_search.presentation.mcp_server.tools.unified import _auto_save_pipeline_report

        mock_article = MagicMock()
        mock_article.pmid = "12345678"

        _auto_save_pipeline_report(config, [mock_article], "# Test Report")

        # Verify report file exists
        reports_dir = workspace_store._reports_dir_for(PipelineScope.WORKSPACE) / "auto-test"
        report_files = list(reports_dir.glob("*.md"))
        assert len(report_files) == 1
        assert report_files[0].read_text(encoding="utf-8") == "# Test Report"

        # Cleanup
        set_pipeline_store(None)

    def test_auto_save_with_template_only(self, global_store: PipelineStore):
        """Auto-save should work even for template-only configs (no saved pipeline)."""
        from pubmed_search.presentation.mcp_server.tools.pipeline_tools import set_pipeline_store

        set_pipeline_store(global_store)

        config = PipelineConfig(template="comprehensive")

        from pubmed_search.presentation.mcp_server.tools.unified import _auto_save_pipeline_report

        _auto_save_pipeline_report(config, [], "# Template Report")

        # Should still save the report (under template name)
        reports_dir = global_store._reports_dir_for(PipelineScope.GLOBAL) / "comprehensive"
        report_files = list(reports_dir.glob("*.md"))
        assert len(report_files) == 1

        set_pipeline_store(None)

    def test_auto_save_no_store_does_nothing(self):
        """When no store is available, auto-save should silently do nothing."""
        from pubmed_search.presentation.mcp_server.tools.pipeline_tools import set_pipeline_store

        set_pipeline_store(None)

        config = PipelineConfig(template="pico")

        from pubmed_search.presentation.mcp_server.tools.unified import _auto_save_pipeline_report

        # Should not raise
        _auto_save_pipeline_report(config, [], "# Report")

    def test_auto_save_records_run_for_saved_pipeline(self, workspace_store: PipelineStore):
        """Auto-save should also create a PipelineRun record if pipeline exists."""
        from pubmed_search.presentation.mcp_server.tools.pipeline_tools import set_pipeline_store

        set_pipeline_store(workspace_store)

        config = PipelineConfig(name="run-test", template="comprehensive")
        workspace_store.save(name="run-test", config=config, scope="workspace")

        from pubmed_search.presentation.mcp_server.tools.unified import _auto_save_pipeline_report

        mock_article = MagicMock()
        mock_article.pmid = "99999999"

        _auto_save_pipeline_report(config, [mock_article], "# Run Report")

        # Verify run record was saved
        history = workspace_store.get_history("run-test")
        assert len(history) == 1
        assert history[0].article_count == 1
        assert "99999999" in history[0].pmids

        set_pipeline_store(None)

    def test_auto_save_handles_errors_gracefully(self, workspace_store: PipelineStore):
        """Auto-save failures should be caught, not propagate to user."""
        from pubmed_search.presentation.mcp_server.tools.pipeline_tools import set_pipeline_store

        # Use a store that will fail on save_report
        broken_store = MagicMock()
        broken_store.save_report.side_effect = OSError("disk full")
        set_pipeline_store(broken_store)

        config = PipelineConfig(name="broken", template="comprehensive")

        from pubmed_search.presentation.mcp_server.tools.unified import _auto_save_pipeline_report

        # Should not raise
        _auto_save_pipeline_report(config, [], "# Report")

        set_pipeline_store(None)


# =========================================================================
# Workspace auto-detection
# =========================================================================


class TestWorkspaceDetection:
    """Tests for workspace_dir auto-detection in tool_registry."""

    def test_env_var_takes_precedence(self, tmp_path: Path):
        """PUBMED_WORKSPACE_DIR env var should be used if set."""
        ws_path = str(tmp_path / "my-workspace")

        with patch.dict("os.environ", {"PUBMED_WORKSPACE_DIR": ws_path}):
            import os

            assert os.environ.get("PUBMED_WORKSPACE_DIR") == ws_path

    def test_cwd_with_git_is_detected(self, tmp_path: Path):
        """CWD with .git should be auto-detected as workspace."""
        (tmp_path / ".git").mkdir()

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            from pathlib import Path as P

            cwd = P.cwd()
            markers = (".git", "pyproject.toml", "package.json", ".pubmed-search")
            assert any((cwd / m).exists() for m in markers)

    def test_cwd_without_markers_not_detected(self, tmp_path: Path):
        """CWD without project markers should not be used as workspace."""
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            from pathlib import Path as P

            cwd = P.cwd()
            markers = (".git", "pyproject.toml", "package.json", ".pubmed-search")
            assert not any((cwd / m).exists() for m in markers)
