"""Tests for executing saved pipelines through StoredPipelineRunner."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.pipeline.runner import StoredPipelineRunner
from pubmed_search.application.pipeline.store import PipelineStore
from pubmed_search.domain.entities.pipeline import PipelineConfig, PipelineStep

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def pipeline_store(tmp_path: Path) -> PipelineStore:
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    return PipelineStore(global_data_dir=global_dir, workspace_dir=workspace_dir)


class TestStoredPipelineRunner:
    async def test_execute_saved_template_pipeline_materializes_steps(self, pipeline_store: PipelineStore):
        pipeline_store.save(
            name="weekly_remi_template",
            config=PipelineConfig(
                template="pico",
                template_params={"P": "ICU patients", "I": "remimazolam"},
            ),
            scope="workspace",
        )

        runner = StoredPipelineRunner(
            store=pipeline_store,
            searcher=MagicMock(),
            alternate_search_fn=None,
        )

        with patch("pubmed_search.application.pipeline.runner.PipelineExecutor") as MockExec:
            mock_exec = MockExec.return_value
            mock_exec.execute = AsyncMock(return_value=([], {}))

            run = await runner.execute_saved_pipeline("weekly_remi_template")

        executed_config = mock_exec.execute.await_args.args[0]
        assert executed_config.name == "weekly_remi_template"
        assert len(executed_config.steps) > 0
        assert executed_config.steps[0].action == "pico"
        assert run.pipeline_name == "weekly_remi_template"
        assert len(pipeline_store.get_history("weekly_remi_template")) == 1

    async def test_execute_saved_pipeline_uses_unique_run_ids_with_same_timestamp(
        self, pipeline_store: PipelineStore
    ):
        pipeline_store.save(
            name="collision_test",
            config=PipelineConfig(
                name="collision_test",
                steps=[PipelineStep(id="s1", action="search", params={"query": "remimazolam"})],
            ),
            scope="workspace",
        )

        runner = StoredPipelineRunner(
            store=pipeline_store,
            searcher=MagicMock(),
            alternate_search_fn=None,
        )

        fixed_now = datetime(2026, 4, 22, 12, 0, 0, 123456, tzinfo=timezone.utc)

        with (
            patch("pubmed_search.application.pipeline.runner.PipelineExecutor") as mock_exec_cls,
            patch("pubmed_search.application.pipeline.runner.datetime") as mock_datetime,
        ):
            mock_exec = mock_exec_cls.return_value
            mock_exec.execute = AsyncMock(return_value=([], {}))
            mock_datetime.now.return_value = fixed_now

            first = await runner.execute_saved_pipeline("collision_test")
            second = await runner.execute_saved_pipeline("collision_test")

        assert first.run_id != second.run_id
        history = pipeline_store.get_history("collision_test", limit=10)
        assert {run.run_id for run in history} == {first.run_id, second.run_id}
