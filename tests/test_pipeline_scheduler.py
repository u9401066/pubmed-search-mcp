"""Tests for APScheduler-backed pipeline scheduling."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from pubmed_search.application.pipeline.store import PipelineStore
from pubmed_search.domain.entities.pipeline import PipelineConfig, PipelineRun, PipelineStep
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
        mock_runner.execute_saved_pipeline.assert_awaited_once_with("weekly_remi")

    async def test_execute_job_updates_error_status(
        self,
        pipeline_store: PipelineStore,
        scheduler_settings: AppSettings,
    ):
        runner = AsyncMock()
        runner.execute_saved_pipeline = AsyncMock(side_effect=RuntimeError("boom"))
        scheduler = APSPipelineScheduler(store=pipeline_store, runner=runner, settings=scheduler_settings)
        scheduler.schedule("weekly_remi", "0 9 * * 1")

        await scheduler._execute_job("weekly_remi")

        entry = pipeline_store.get_schedule("weekly_remi")
        assert entry is not None
        assert entry.last_status == "error"
        assert entry.last_error == "boom"

    def test_invalid_cron_raises(
        self,
        pipeline_store: PipelineStore,
        mock_runner: AsyncMock,
        scheduler_settings: AppSettings,
    ):
        scheduler = APSPipelineScheduler(store=pipeline_store, runner=mock_runner, settings=scheduler_settings)

        with pytest.raises(ValueError, match="Invalid cron expression"):
            scheduler.schedule("weekly_remi", "bad cron")
