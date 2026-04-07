"""Tests for executing saved pipelines through StoredPipelineRunner."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.pipeline.runner import StoredPipelineRunner
from pubmed_search.application.pipeline.store import PipelineStore
from pubmed_search.domain.entities.pipeline import PipelineConfig

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
