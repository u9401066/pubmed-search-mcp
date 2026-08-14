"""Tests for executing saved pipelines through StoredPipelineRunner."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.pipeline.runner import StoredPipelineRunner
from pubmed_search.application.pipeline.store import PipelineStore
from pubmed_search.domain.entities.pipeline import PipelineConfig, PipelineStep, StepResult

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

        page_search = AsyncMock()
        runner = StoredPipelineRunner(
            store=pipeline_store,
            searcher=MagicMock(),
            alternate_search_fn=None,
            alternate_search_page_fn=page_search,
        )

        with patch("pubmed_search.application.pipeline.runner.PipelineExecutor") as MockExec:
            mock_exec = MockExec.return_value
            mock_exec.execute = AsyncMock(return_value=([], {}))

            run = await runner.execute_saved_pipeline("weekly_remi_template")

        executed_config = mock_exec.execute.await_args.args[0]
        assert executed_config.name == "weekly_remi_template"
        assert len(executed_config.steps) > 0
        assert executed_config.steps[0].action == "pico"
        assert MockExec.call_args.kwargs["alternate_search_page_fn"] is page_search
        assert run.pipeline_name == "weekly_remi_template"
        assert run.status == "success"
        assert len(pipeline_store.get_history("weekly_remi_template")) == 1

    @pytest.mark.parametrize(
        ("step_result", "expected_status"),
        [
            (
                StepResult(
                    step_id="search",
                    action="search",
                    metadata={"source_errors": [{"source": "openalex", "status": "rate_limited"}]},
                ),
                "partial",
            ),
            (
                StepResult(
                    step_id="search",
                    action="search",
                    error="All selected search sources failed",
                ),
                "error",
            ),
        ],
    )
    async def test_saved_run_history_uses_structured_step_outcome(
        self,
        pipeline_store: PipelineStore,
        step_result: StepResult,
        expected_status: str,
    ) -> None:
        pipeline_store.save(
            name="status_test",
            config=PipelineConfig(
                name="status_test",
                steps=[PipelineStep(id="search", action="search", params={"query": "remimazolam"})],
            ),
            scope="workspace",
        )
        runner = StoredPipelineRunner(store=pipeline_store, searcher=MagicMock(), alternate_search_fn=None)

        with patch("pubmed_search.application.pipeline.runner.PipelineExecutor") as executor_cls:
            executor_cls.return_value.execute = AsyncMock(return_value=([], {"search": step_result}))
            run = await runner.execute_saved_pipeline("status_test")

        assert run.status == expected_status
        assert run.error_message
        history = pipeline_store.get_history("status_test")
        assert history[-1].status == expected_status
        assert history[-1].error_message == run.error_message

    async def test_execute_saved_pipeline_uses_unique_run_ids_with_same_timestamp(self, pipeline_store: PipelineStore):
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

    async def test_failed_saved_pipeline_does_not_log_or_persist_raw_exception(
        self,
        pipeline_store: PipelineStore,
        caplog,
    ):
        sentinel_query = "PRIVATE_QUERY_SENTINEL"
        sentinel_secret = "TOPSECRET_SENTINEL"
        pipeline_store.save(
            name="safe_failure",
            config=PipelineConfig(
                name="safe_failure",
                steps=[PipelineStep(id="s1", action="search", params={"query": "safe topic"})],
            ),
            scope="workspace",
        )
        runner = StoredPipelineRunner(store=pipeline_store, searcher=MagicMock(), alternate_search_fn=None)

        with patch("pubmed_search.application.pipeline.runner.PipelineExecutor") as executor_cls:
            executor_cls.return_value.execute = AsyncMock(
                side_effect=RuntimeError(f"failed {sentinel_query} token={sentinel_secret}")
            )
            with pytest.raises(RuntimeError, match="Unexpected upstream error") as error:
                await runner.execute_saved_pipeline("safe_failure")

        history = pipeline_store.get_history("safe_failure")
        assert history[-1].status == "error"
        assert history[-1].error_message == "Unexpected upstream error (RuntimeError)"
        combined = f"{caplog.text}\n{error.value}\n{history[-1].error_message}"
        assert sentinel_query not in combined
        assert sentinel_secret not in combined
