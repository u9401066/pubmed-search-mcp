"""Central execution budgets for pipeline actions and generated templates."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from pubmed_search.shared.settings import (
    DEFAULT_PIPELINE_MAX_EXTERNAL_CALLS,
    DEFAULT_PIPELINE_RUN_TIMEOUT_SECONDS,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pubmed_search.domain.entities.pipeline import PipelineConfig


@dataclass(frozen=True)
class LimitBudget:
    """Allowed result-window range for one pipeline operation."""

    default: int
    maximum: int
    minimum: int = 1


PIPELINE_OUTPUT_LIMIT = LimitBudget(default=20, maximum=100)
PIPELINE_ACTION_LIMITS: Mapping[str, LimitBudget] = MappingProxyType(
    {
        "search": LimitBudget(default=50, maximum=100),
        "related": LimitBudget(default=20, maximum=50),
        "citing": LimitBudget(default=20, maximum=100),
        "references": LimitBudget(default=50, maximum=100),
    }
)

# Template limits are constrained so every generated fan-out action remains
# inside its own action budget without clipping caller input.
PIPELINE_TEMPLATE_LIMITS: Mapping[str, LimitBudget] = MappingProxyType(
    {
        "pico": LimitBudget(default=20, maximum=PIPELINE_ACTION_LIMITS["search"].maximum // 3),
        "comprehensive": LimitBudget(default=30, maximum=PIPELINE_ACTION_LIMITS["search"].maximum // 2),
        "exploration": LimitBudget(
            default=20,
            maximum=min(PIPELINE_ACTION_LIMITS[action].maximum for action in ("related", "citing", "references")),
        ),
        "gene_drug": LimitBudget(default=20, maximum=PIPELINE_ACTION_LIMITS["search"].maximum // 2),
    }
)

PipelineBudgetReason = Literal["deadline_exhausted", "external_call_quota_exhausted"]


@dataclass(frozen=True)
class PipelineExecutionPolicy:
    """Server-owned aggregate limits for one complete pipeline run."""

    run_timeout_seconds: float = DEFAULT_PIPELINE_RUN_TIMEOUT_SECONDS
    max_external_calls: int = DEFAULT_PIPELINE_MAX_EXTERNAL_CALLS

    def __post_init__(self) -> None:
        if isinstance(self.run_timeout_seconds, bool) or not isinstance(self.run_timeout_seconds, (int, float)):
            raise TypeError("Pipeline run timeout must be a number")
        if self.run_timeout_seconds <= 0:
            raise ValueError("Pipeline run timeout must be positive")
        if isinstance(self.max_external_calls, bool) or not isinstance(self.max_external_calls, int):
            raise TypeError("Pipeline external-call quota must be an integer")
        if self.max_external_calls < 1:
            raise ValueError("Pipeline external-call quota must be positive")


class PipelineBudgetExceededError(RuntimeError):
    """Raised when a run cannot begin another external operation."""

    def __init__(self, reason: PipelineBudgetReason) -> None:
        self.reason = reason
        message = (
            "Pipeline run deadline exhausted"
            if reason == "deadline_exhausted"
            else "Pipeline external-call quota exhausted"
        )
        super().__init__(message)


class PipelineRunBudget:
    """Parallel-safe aggregate deadline and external-call counter."""

    def __init__(self, policy: PipelineExecutionPolicy) -> None:
        self.policy = policy
        self._started = time.monotonic()
        self._deadline = self._started + float(policy.run_timeout_seconds)
        self._external_calls_used = 0
        self._exhausted_reason: PipelineBudgetReason | None = None
        self._lock = asyncio.Lock()

    def remaining_seconds(self) -> float:
        """Return remaining wall-clock budget, clamped only for scheduling."""
        return max(0.0, self._deadline - time.monotonic())

    async def reserve_external_call(self) -> None:
        """Atomically reserve one external call or fail before provider I/O."""
        async with self._lock:
            if self.remaining_seconds() <= 0:
                self._exhausted_reason = "deadline_exhausted"
                raise PipelineBudgetExceededError("deadline_exhausted")
            if self._external_calls_used >= self.policy.max_external_calls:
                self._exhausted_reason = "external_call_quota_exhausted"
                raise PipelineBudgetExceededError("external_call_quota_exhausted")
            self._external_calls_used += 1

    def mark_deadline_exhausted(self) -> None:
        """Record that the aggregate wait budget expired."""
        self._exhausted_reason = "deadline_exhausted"

    def snapshot(self) -> dict[str, Any]:
        """Return typed, query-safe run-budget metadata."""
        return {
            "run_timeout_seconds": float(self.policy.run_timeout_seconds),
            "max_external_calls": self.policy.max_external_calls,
            "external_calls_used": self._external_calls_used,
            "external_calls_remaining": max(0, self.policy.max_external_calls - self._external_calls_used),
            "deadline_remaining_seconds": self.remaining_seconds(),
            "exhausted_reason": self._exhausted_reason,
        }


def _parse_integer_limit(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{field} must be an integer"
        raise ValueError(msg)  # noqa: TRY004 - stable public validation exception
    return value


def validate_bounded_limit(value: Any, budget: LimitBudget, *, field: str) -> int:
    """Return an integer limit or fail closed outside an operation budget."""

    limit = _parse_integer_limit(value, field=field)
    if not budget.minimum <= limit <= budget.maximum:
        msg = f"{field} must be between {budget.minimum} and {budget.maximum}"
        raise ValueError(msg)
    return limit


def action_limit(action: str, value: Any | None = None) -> int:
    """Validate an explicit action limit or return that action's default."""

    budget = PIPELINE_ACTION_LIMITS[action]
    candidate = budget.default if value is None else value
    return validate_bounded_limit(candidate, budget, field=f"Pipeline {action} limit")


def validate_pipeline_budgets(config: PipelineConfig) -> None:
    """Reject a pipeline whose output or action limits cannot be executed safely."""

    validate_bounded_limit(config.output.limit, PIPELINE_OUTPUT_LIMIT, field="Pipeline output limit")
    for step in config.steps:
        if step.action not in PIPELINE_ACTION_LIMITS or "limit" not in step.params:
            continue
        action_limit(step.action, step.params["limit"])


__all__ = [
    "PIPELINE_ACTION_LIMITS",
    "DEFAULT_PIPELINE_MAX_EXTERNAL_CALLS",
    "DEFAULT_PIPELINE_RUN_TIMEOUT_SECONDS",
    "PIPELINE_OUTPUT_LIMIT",
    "PIPELINE_TEMPLATE_LIMITS",
    "LimitBudget",
    "PipelineBudgetExceededError",
    "PipelineExecutionPolicy",
    "PipelineRunBudget",
    "action_limit",
    "validate_bounded_limit",
    "validate_pipeline_budgets",
]
