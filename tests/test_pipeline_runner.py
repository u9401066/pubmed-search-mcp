"""Tests for executing saved pipelines through StoredPipelineRunner."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.pipeline.runner import StoredPipelineRunner
from pubmed_search.application.pipeline.store import PipelineStore
from pubmed_search.domain.entities.article import UnifiedArticle
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
    async def test_saved_report_diff_lists_changes_with_bounded_new_articles(
        self, pipeline_store: PipelineStore, tmp_path: Path
    ) -> None:
        pipeline_store.save(
            name="changes",
            config=PipelineConfig(steps=[PipelineStep(id="search", action="search", params={"query": "topic"})]),
        )
        baseline = [
            UnifiedArticle(pmid=str(number), title=f"Paper {number}", primary_source="pubmed") for number in (1, 2)
        ]
        current = [
            UnifiedArticle(pmid=str(number), title=f"Paper {number}", primary_source="pubmed")
            for number in [1, *range(3, 25)]
        ]
        runner = StoredPipelineRunner(store=pipeline_store, searcher=AsyncMock())
        with patch(
            "pubmed_search.application.pipeline.runner.PipelineExecutor.execute", new_callable=AsyncMock
        ) as execute:
            execute.side_effect = [(baseline, {}), (current, {})]
            await runner.execute_saved_pipeline("changes", diff_mode=True)
            run = await runner.execute_saved_pipeline("changes", diff_mode=True)

        report = next(tmp_path.rglob(f"{run.run_id}.md")).read_text(encoding="utf-8")
        changes = report.split("## Changes since previous successful run", 1)[1]
        assert run.new_pmids == [str(number) for number in range(3, 25)]
        assert run.removed_pmids == ["2"]
        assert "- PMID 3: Paper 3" in changes
        assert "- PMID 22: Paper 22" in changes
        assert "- PMID 23:" not in changes
        assert "+2 more" in changes
        assert "### Removed PMIDs (1)\n\n- PMID 2" in changes
        assert "baseline" not in changes.lower()

    @pytest.mark.parametrize("diff_mode", [True, False])
    async def test_saved_report_diff_baseline_is_opt_in(
        self, pipeline_store: PipelineStore, tmp_path: Path, diff_mode: bool
    ) -> None:
        pipeline_store.save(
            name="baseline",
            config=PipelineConfig(
                name="baseline",
                steps=[PipelineStep(id="search", action="search", params={"query": "topic"})],
            ),
            scope="workspace",
        )
        runner = StoredPipelineRunner(store=pipeline_store, searcher=AsyncMock())
        with patch(
            "pubmed_search.application.pipeline.runner.PipelineExecutor.execute", new_callable=AsyncMock
        ) as execute:
            execute.return_value = ([], {})
            run = (
                await runner.execute_saved_pipeline("baseline", diff_mode=True)
                if diff_mode
                else await runner.execute_saved_pipeline("baseline")
            )

        report = next(tmp_path.rglob(f"{run.run_id}.md")).read_text(encoding="utf-8")
        if diff_mode:
            assert "## Changes since previous successful run" in report
            assert "This run is the baseline; there is no previous successful run." in report
        else:
            assert "## Changes since previous successful run" not in report

    async def test_execute_saved_pipeline_binds_full_execution_context(self, pipeline_store: PipelineStore):
        pipeline_store.save(
            name="runtime_bound",
            config=PipelineConfig(
                name="runtime_bound",
                steps=[PipelineStep(id="expand", action="expand", params={"topic": "interleukin 6"})],
            ),
            scope="workspace",
        )
        events: list[str] = []

        @contextmanager
        def execution_context():
            events.append("enter")
            try:
                yield
            finally:
                events.append("exit")

        runner = StoredPipelineRunner(
            store=pipeline_store,
            searcher=MagicMock(),
            execution_context=execution_context,
        )

        async def execute(_config: PipelineConfig):
            assert events == ["enter"]
            return [], {}

        with patch("pubmed_search.application.pipeline.runner.PipelineExecutor") as executor_cls:
            executor_cls.return_value.execute = AsyncMock(side_effect=execute)
            await runner.execute_saved_pipeline("runtime_bound")

        assert events == ["enter", "exit"]

    async def test_execute_saved_template_pipeline_materializes_steps(self, pipeline_store: PipelineStore):
        pipeline_store.save(
            name="weekly_remi_template",
            config=PipelineConfig(
                template="pico",
                template_params={"P": "ICU patients", "I": "remimazolam"},
            ),
            scope="workspace",
        )

        adapter_search = AsyncMock()
        runner = StoredPipelineRunner(
            store=pipeline_store,
            searcher=MagicMock(),
            alternate_search_adapter=adapter_search,
        )

        with patch("pubmed_search.application.pipeline.runner.PipelineExecutor") as MockExec:
            mock_exec = MockExec.return_value
            mock_exec.execute = AsyncMock(return_value=([], {}))

            run = await runner.execute_saved_pipeline("weekly_remi_template")

        executed_config = mock_exec.execute.await_args.args[0]
        assert executed_config.name == "weekly_remi_template"
        assert len(executed_config.steps) > 0
        assert executed_config.steps[0].action == "pico"
        assert MockExec.call_args.kwargs["alternate_search_adapter"] is adapter_search
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
        runner = StoredPipelineRunner(store=pipeline_store, searcher=MagicMock())

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
        runner = StoredPipelineRunner(store=pipeline_store, searcher=MagicMock())

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
