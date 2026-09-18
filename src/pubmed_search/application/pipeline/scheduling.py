"""Dependency-ready task ownership for an already validated, bounded DAG.

The executor owns action behavior and error policy. This module owns when
steps start and cancellation of every task it creates. Provider rate limits
remain in the shared transport; a pipeline contains at most 20 steps.
"""

from __future__ import annotations

import asyncio
import copy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pubmed_search.application.pipeline.budgets import PipelineRunBudget
    from pubmed_search.domain.entities.pipeline import PipelineStep, StepResult


async def run_ready_steps(
    steps: list[PipelineStep],
    results: dict[str, StepResult],
    *,
    execute_step: Callable[[PipelineStep, dict[str, StepResult]], Awaitable[StepResult]],
    record_outcome: Callable[[PipelineStep, StepResult | BaseException], None],
    budget: PipelineRunBudget,
) -> None:
    """Start each step as soon as its own inputs complete, within one deadline.

    ``record_outcome`` stores typed results or raises the executor's abort error.
    An expired deadline leaves unfinished steps absent for the executor to mark
    as partial failures. Result ordering is restored by the executor afterward.
    """
    waiting = {step.id: step for step in steps}
    active: dict[asyncio.Task[StepResult], PipelineStep] = {}

    def consume_outcome(task: asyncio.Task[StepResult]) -> None:
        # Also retrieve late failures from cancellation-resistant providers.
        if not task.cancelled():
            task.exception()

    try:
        while waiting or active:
            remaining = budget.remaining_seconds()
            if remaining <= 0:
                budget.mark_deadline_exhausted()
                break
            for step_id, step in list(waiting.items()):
                if all(input_id in results for input_id in step.inputs):
                    inputs = copy.deepcopy({input_id: results[input_id] for input_id in step.inputs})
                    task = asyncio.ensure_future(execute_step(step, inputs))
                    task.add_done_callback(consume_outcome)
                    active[task] = step
                    del waiting[step_id]
            if not active:
                raise ValueError("Pipeline contains unresolved dependencies")

            done, _pending = await asyncio.wait(
                active, timeout=budget.remaining_seconds(), return_when=asyncio.FIRST_COMPLETED
            )
            if not done:
                budget.mark_deadline_exhausted()
                break
            # Consume all completed outcomes before scheduling more work. In
            # particular, an abort cannot launch a newly ready descendant.
            for task, step in list(active.items()):
                if task not in done:
                    continue
                del active[task]
                try:
                    outcome: StepResult | BaseException = task.result()
                except BaseException as exc:
                    outcome = exc
                record_outcome(step, outcome)
    finally:
        pending = [task for task in active if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            # Cleanup is bounded even for providers that suppress cancellation.
            await asyncio.wait(pending, timeout=0.1)
