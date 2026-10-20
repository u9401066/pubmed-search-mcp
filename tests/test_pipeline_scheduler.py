"""Tests for APScheduler-backed pipeline scheduling."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from pubmed_search.application.pipeline.runner import StoredPipelineRunner
from pubmed_search.application.pipeline.store import PipelineStore
from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.domain.entities.pipeline import PipelineConfig, PipelineRun, PipelineStep, StepResult
from pubmed_search.infrastructure.scheduling import APSPipelineScheduler
from pubmed_search.shared.settings import AppSettings

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def pipeline_store(tmp_path: Path) -> PipelineStore:
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    store = PipelineStore(global_data_dir=global_dir, workspace_dir=workspace_dir)
    store.save(
        "weekly_remi",
        PipelineConfig(steps=[PipelineStep(id="s1", action="search", params={"query": "remimazolam"})]),
    )
    return store


@pytest.fixture()
def scheduler_settings() -> AppSettings:
    return AppSettings(
        PUBMED_SCHEDULER_TIMEZONE="UTC",
        PUBMED_SCHEDULER_ENABLED=True,
    )


@pytest.fixture()
def mock_runner() -> AsyncMock:
    runner = AsyncMock()
    runner.execute_saved_pipeline = AsyncMock(
        return_value=PipelineRun(
            run_id="run_001",
            pipeline_name="weekly_remi",
            started=datetime.now(timezone.utc),
            finished=datetime.now(timezone.utc),
            status="success",
            article_count=3,
            pmids=["1", "2", "3"],
        )
    )
    return runner


class TestAPSPipelineScheduler:
    @pytest.mark.parametrize("outcome", ["success", "partial", "error", "exception"])
    async def test_real_scheduled_runs_persist_safe_notifications_and_reset_when_disabled(
        self,
        pipeline_store: PipelineStore,
        scheduler_settings: AppSettings,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        outcome: str,
    ) -> None:
        runner = StoredPipelineRunner(store=pipeline_store, searcher=AsyncMock())
        scheduler = APSPipelineScheduler(store=pipeline_store, runner=runner, settings=scheduler_settings)
        scheduler.schedule("weekly_remi", "0 9 * * 1")
        schedule_path = pipeline_store.global_data_dir / "schedules.json"
        legacy = json.loads(schedule_path.read_text(encoding="utf-8"))
        for key in ("last_run_id", "last_new_count", "last_removed_count"):
            legacy["weekly_remi"].pop(key)
        schedule_path.write_text(json.dumps(legacy), encoding="utf-8")
        restored = pipeline_store.get_schedule("weekly_remi")
        assert restored is not None
        assert (restored.last_run_id, restored.last_new_count, restored.last_removed_count) == (None, 0, 0)

        baseline = [UnifiedArticle(pmid="1", title="Original", primary_source="pubmed")]
        current = [UnifiedArticle(pmid="2", title="New", primary_source="pubmed")]
        steps = {}
        if outcome == "partial":
            steps = {
                "s1": StepResult(step_id="s1", action="search", metadata={"source_errors": [{"source": "pubmed"}]})
            }
        elif outcome == "error":
            current = []
            steps = {"s1": StepResult(step_id="s1", action="search", error="upstream failed")}

        caplog.set_level(logging.INFO, logger="pubmed_search.infrastructure.scheduling.pipeline_scheduler")
        with patch(
            "pubmed_search.application.pipeline.runner.PipelineExecutor.execute", new_callable=AsyncMock
        ) as execute:
            execute.return_value = (baseline, {})
            await scheduler._execute_job("weekly_remi")
            baseline_run = pipeline_store.get_latest_run("weekly_remi", successful_only=True)
            assert baseline_run is not None
            baseline_report = next(tmp_path.rglob(f"{baseline_run.run_id}.md")).read_text(encoding="utf-8")
            assert "This run is the baseline" in baseline_report
            caplog.clear()
            if outcome == "exception":
                execute.side_effect = RuntimeError("private query token=secret")
            else:
                execute.return_value = (current, steps)
            await scheduler._execute_job("weekly_remi")

            entry = pipeline_store.get_schedule("weekly_remi")
            run = pipeline_store.get_latest_run("weekly_remi")
            assert entry is not None and run is not None
            assert entry.last_status == ("error" if outcome == "exception" else outcome)
            assert entry.last_new_count == (1 if outcome in {"success", "partial"} else 0)
            assert entry.last_removed_count == (1 if outcome == "success" else 0)
            assert entry.last_run_id == (None if outcome == "exception" else run.run_id)
            assert run.removed_pmids == (["1"] if outcome == "success" else [])
            notices = [record.getMessage() for record in caplog.records if record.levelno == logging.INFO]
            assert notices == [
                f"Scheduled pipeline weekly_remi: new={entry.last_new_count} removed={entry.last_removed_count}"
            ]
            assert "secret" not in caplog.text
            if outcome != "exception":
                report = next(tmp_path.rglob(f"{run.run_id}.md")).read_text(encoding="utf-8")
                assert ("### Removed PMIDs" in report) is (outcome == "success")

            scheduler.schedule("weekly_remi", "0 9 * * 1", notify=False)
            disabled = pipeline_store.get_schedule("weekly_remi")
            assert disabled is not None
            assert (disabled.last_run_id, disabled.last_new_count, disabled.last_removed_count) == (None, 0, 0)
            caplog.clear()
            execute.side_effect = None
            execute.return_value = (current, {})
            await scheduler._execute_job("weekly_remi")
            disabled = pipeline_store.get_schedule("weekly_remi")
            assert disabled is not None
            assert (disabled.last_run_id, disabled.last_new_count, disabled.last_removed_count) == (None, 0, 0)
            assert not [record for record in caplog.records if record.levelno == logging.INFO]
            if outcome == "partial":
                latest = pipeline_store.get_latest_run("weekly_remi", successful_only=True)
                assert latest is not None
                assert latest.new_pmids == ["2"]
                assert latest.removed_pmids == ["1"]

    def test_schedule_persists_entry(
        self,
        pipeline_store: PipelineStore,
        mock_runner: AsyncMock,
        scheduler_settings: AppSettings,
    ):
        scheduler = APSPipelineScheduler(store=pipeline_store, runner=mock_runner, settings=scheduler_settings)

        entry = scheduler.schedule("weekly_remi", "0 9 * * 1", diff_mode=False, notify=True)

        assert entry.pipeline_name == "weekly_remi"
        assert entry.cron == "0 9 * * 1"
        assert entry.diff_mode is False
        assert pipeline_store.get_schedule("weekly_remi") is not None

    def test_unschedule_removes_entry(
        self,
        pipeline_store: PipelineStore,
        mock_runner: AsyncMock,
        scheduler_settings: AppSettings,
    ):
        scheduler = APSPipelineScheduler(store=pipeline_store, runner=mock_runner, settings=scheduler_settings)
        scheduler.schedule("weekly_remi", "0 9 * * 1")

        removed = scheduler.unschedule("weekly_remi")

        assert removed is not None
        assert pipeline_store.get_schedule("weekly_remi") is None

    async def test_execute_job_updates_success_status(
        self,
        pipeline_store: PipelineStore,
        mock_runner: AsyncMock,
        scheduler_settings: AppSettings,
    ):
        scheduler = APSPipelineScheduler(store=pipeline_store, runner=mock_runner, settings=scheduler_settings)
        scheduler.schedule("weekly_remi", "0 9 * * 1")

        await scheduler._execute_job("weekly_remi")

        entry = pipeline_store.get_schedule("weekly_remi")
        assert entry is not None
        assert entry.last_status == "success"
        assert entry.last_error is None
        mock_runner.execute_saved_pipeline.assert_awaited_once_with("weekly_remi", diff_mode=True)

    async def test_execute_job_updates_error_status(
        self,
        pipeline_store: PipelineStore,
        scheduler_settings: AppSettings,
    ):
        runner = AsyncMock()
        private_detail = "/srv/private/pipelines/weekly_remi.yaml?token=scheduler-secret"
        runner.execute_saved_pipeline = AsyncMock(side_effect=RuntimeError(private_detail))
        scheduler = APSPipelineScheduler(store=pipeline_store, runner=runner, settings=scheduler_settings)
        scheduler.schedule("weekly_remi", "0 9 * * 1")

        await scheduler._execute_job("weekly_remi")

        entry = pipeline_store.get_schedule("weekly_remi")
        assert entry is not None
        assert entry.last_status == "error"
        assert entry.last_error == "Scheduled pipeline execution failed"
        assert private_detail not in entry.last_error

    async def test_execute_job_preserves_partial_runner_status(
        self,
        pipeline_store: PipelineStore,
        scheduler_settings: AppSettings,
    ):
        runner = AsyncMock()
        runner.execute_saved_pipeline = AsyncMock(
            return_value=PipelineRun(
                run_id="run_partial",
                pipeline_name="weekly_remi",
                started=datetime.now(timezone.utc),
                finished=datetime.now(timezone.utc),
                status="partial",
                error_message="partial at /srv/private/pipeline.yaml token=scheduler-secret",
            )
        )
        scheduler = APSPipelineScheduler(store=pipeline_store, runner=runner, settings=scheduler_settings)
        scheduler.schedule("weekly_remi", "0 9 * * 1")

        await scheduler._execute_job("weekly_remi")

        entry = pipeline_store.get_schedule("weekly_remi")
        assert entry is not None
        assert entry.last_status == "partial"
        assert entry.last_error == "Pipeline execution completed partially"
        assert "private" not in entry.last_error
        assert "secret" not in entry.last_error

    async def test_execute_job_does_not_persist_failed_run_diagnostics(
        self,
        pipeline_store: PipelineStore,
        scheduler_settings: AppSettings,
    ):
        runner = AsyncMock()
        runner.execute_saved_pipeline = AsyncMock(
            return_value=PipelineRun(
                run_id="run_error",
                pipeline_name="weekly_remi",
                started=datetime.now(timezone.utc),
                finished=datetime.now(timezone.utc),
                status="error",
                error_message="failed at /srv/private/pipeline.yaml?token=scheduler-secret",
            )
        )
        scheduler = APSPipelineScheduler(store=pipeline_store, runner=runner, settings=scheduler_settings)
        scheduler.schedule("weekly_remi", "0 9 * * 1")

        await scheduler._execute_job("weekly_remi")

        entry = pipeline_store.get_schedule("weekly_remi")
        assert entry is not None
        assert entry.last_status == "error"
        assert entry.last_error == "Pipeline execution failed"

    def test_invalid_cron_raises(
        self,
        pipeline_store: PipelineStore,
        mock_runner: AsyncMock,
        scheduler_settings: AppSettings,
    ):
        scheduler = APSPipelineScheduler(store=pipeline_store, runner=mock_runner, settings=scheduler_settings)

        with pytest.raises(ValueError, match="Invalid cron expression"):
            scheduler.schedule("weekly_remi", "bad cron")


@pytest.mark.asyncio
async def test_unscheduling_during_run_does_not_resurrect_schedule(pipeline_store, mock_runner, scheduler_settings):
    scheduler = APSPipelineScheduler(store=pipeline_store, runner=mock_runner, settings=scheduler_settings)
    scheduler.schedule("weekly_remi", "0 9 * * 1")
    result = mock_runner.execute_saved_pipeline.return_value

    async def execute(name, *, diff_mode=False):
        scheduler.unschedule(name)
        return result

    mock_runner.execute_saved_pipeline.side_effect = execute
    await scheduler._execute_job("weekly_remi")
    assert pipeline_store.get_schedule("weekly_remi") is None
