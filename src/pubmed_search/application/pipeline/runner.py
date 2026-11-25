"""Application service for executing persisted pipelines and storing run artifacts."""

from __future__ import annotations

import asyncio
import logging
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pubmed_search.application.pipeline.executor import PipelineExecutor
from pubmed_search.application.pipeline.report_generator import generate_pipeline_report
from pubmed_search.application.pipeline.run_recorder import PipelineRunRecorder
from pubmed_search.application.pipeline.templates import materialize_pipeline_config
from pubmed_search.domain.entities.pipeline import PipelineRun

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from pubmed_search.application.pipeline.budgets import PipelineExecutionPolicy
    from pubmed_search.application.pipeline.executor import (
        AlternateSearchAdapterFn,
    )
    from pubmed_search.application.pipeline.run_recorder import RunObserver
    from pubmed_search.application.pipeline.store import PipelineStore

logger = logging.getLogger(__name__)


class StoredPipelineRunner:
    """Execute a saved pipeline by name and persist its run metadata."""

    def __init__(
        self,
        *,
        store: PipelineStore,
        searcher: Any,
        alternate_search_adapter: AlternateSearchAdapterFn | None = None,
        semantic_enhancer_factory: Callable[[], Any] | None = None,
        execution_policy: PipelineExecutionPolicy | None = None,
        execution_context: Callable[[], AbstractContextManager[None]] | None = None,
        run_observer: RunObserver | None = None,
        mesh_correction: Any = None,
    ) -> None:
        self._store = store
        self._searcher = searcher
        self._alternate_search_adapter = alternate_search_adapter
        self._semantic_enhancer_factory = semantic_enhancer_factory
        self._execution_policy = execution_policy
        self._execution_context = execution_context or nullcontext
        self._run_observer = run_observer
        self._mesh_correction = mesh_correction

    async def execute_saved_pipeline(self, name: str, *, diff_mode: bool = False) -> PipelineRun:
        """Execute one saved pipeline and persist report plus run history.

        Opt-in diff reports compare against the previous successful run, or
        identify a baseline when none exists. Partial runs never prove removals.
        Manual callers retain the existing report format by default.
        """
        saved_config, meta = self._store.load(name)
        config = materialize_pipeline_config(saved_config, default_name=meta.name)
        # Everything this run writes stays in the scope its pipeline was loaded from.
        store = self._store.pinned_to(meta.scope)

        executor = PipelineExecutor(
            searcher=self._searcher,
            alternate_search_adapter=self._alternate_search_adapter,
            semantic_enhancer_factory=self._semantic_enhancer_factory,
            execution_policy=self._execution_policy,
            mesh_correction=self._mesh_correction,
        )
        recorder = PipelineRunRecorder(store, on_recorded=self._run_observer)

        started = datetime.now(timezone.utc)
        run_id = store.create_run_id(meta.name, started)

        try:
            with self._execution_context():
                articles, step_results = await executor.execute(config)
            report = generate_pipeline_report(articles, step_results, config)
            # Persisting a large record set and the SQLite screening observer
            # are blocking file I/O; keep them off the scheduler's event loop.
            return await asyncio.to_thread(
                recorder.record,
                pipeline_name=meta.name,
                articles=articles,
                step_results=step_results,
                report=report,
                started=started,
                run_id=run_id,
                diff_mode=diff_mode,
                executed_config=config,
                saved_config=saved_config,
            )
        except Exception as exc:
            from pubmed_search.shared.source_contracts import normalize_source_adapter_error

            safe_error = normalize_source_adapter_error("pipeline", "execute_saved", exc)
            safe_message = (
                f"Unexpected upstream error ({type(exc).__name__})"
                if safe_error.kind == "unexpected"
                else safe_error.message
            )
            logger.error(  # noqa: TRY400 - traceback may contain the saved query
                "Saved pipeline execution failed (%s)",
                type(exc).__name__,
            )
            failed_run = PipelineRun(
                run_id=run_id,
                pipeline_name=meta.name,
                started=started,
                finished=datetime.now(timezone.utc),
                status="error",
                error_message=safe_message,
            )
            store.save_run(meta.name, failed_run)
            raise RuntimeError(safe_message) from None
