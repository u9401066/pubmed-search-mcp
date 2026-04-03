"""Shared source adapter contracts and execution policy helpers.

This module keeps two concerns aligned across source integrations:

1. Execution lifecycle configuration for external providers.
2. Adapter-level success and error envelopes for orchestration layers.

The goal is to let search/fulltext/image orchestrators add a new source by
adding an adapter call rather than inventing new retry, timeout, or partial
failure behavior for every source family.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar, cast

import httpx

from pubmed_search.shared.async_utils import (
    CircuitBreaker,
    CircuitBreakerPolicy,
    RateLimitPolicy,
    RequestExecutionPolicy,
    RetryableOperationError,
    RetryPolicy,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

AdapterItem = TypeVar("AdapterItem")
SourceAdapterStatus = Literal["ok", "empty", "partial", "error"]
SourceAdapterErrorKind = Literal["http", "timeout", "transport", "retryable", "unexpected"]
TWO_ITEM_TUPLE_LEN = 2
THREE_ITEM_TUPLE_LEN = 3
TwoItemSourceAdapterOutcome = tuple[list[AdapterItem], dict[str, Any] | int]
ThreeItemSourceAdapterOutcome = tuple[list[AdapterItem], int, dict[str, Any]]


@dataclass(frozen=True)
class SourceExecutionSettings:
    """Declarative execution settings shared by source adapters."""

    service_name: str
    timeout: float | None = None
    min_interval: float | None = None
    max_attempts: int = 4
    base_delay: float = 1.0
    max_delay: float = 30.0
    rate_limit_name: str | None = None
    circuit_breaker: CircuitBreaker | None = None
    circuit_breaker_name: str | None = None
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 3
    concurrency_limit: int | None = None
    concurrency_name: str | None = None


def build_request_execution_policy(settings: SourceExecutionSettings) -> RequestExecutionPolicy:
    """Build a shared transport policy from declarative source settings."""
    rate_limit = None
    if settings.min_interval and settings.min_interval > 0:
        rate_limit = RateLimitPolicy(
            name=settings.rate_limit_name or settings.service_name,
            rate=1.0,
            per=settings.min_interval,
        )

    circuit_breaker_policy = None
    if settings.circuit_breaker is None:
        circuit_breaker_policy = CircuitBreakerPolicy(
            name=settings.circuit_breaker_name or settings.service_name,
            failure_threshold=settings.failure_threshold,
            recovery_timeout=settings.recovery_timeout,
            half_open_max_calls=settings.half_open_max_calls,
        )

    return RequestExecutionPolicy(
        service_name=settings.service_name,
        timeout=settings.timeout,
        retry=RetryPolicy(
            max_attempts=max(settings.max_attempts, 1),
            base_delay=settings.base_delay,
            max_delay=settings.max_delay,
        ),
        rate_limit=rate_limit,
        circuit_breaker=settings.circuit_breaker,
        circuit_breaker_policy=circuit_breaker_policy,
        concurrency_limit=settings.concurrency_limit,
        concurrency_name=settings.concurrency_name,
    )


@dataclass(frozen=True)
class SourceAdapterError:
    """Normalized error shape shared by adapter-based orchestrators."""

    source: str
    operation: str
    message: str
    kind: SourceAdapterErrorKind
    retryable: bool = False
    status_code: int | None = None


@dataclass
class SourceAdapterResult(Generic[AdapterItem]):
    """Normalized adapter result for orchestration and aggregation layers."""

    source: str
    operation: str
    items: list[AdapterItem] = field(default_factory=list)
    total_count: int = 0
    status: SourceAdapterStatus = "ok"
    errors: list[SourceAdapterError] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def empty(
        cls,
        *,
        source: str,
        operation: str,
        metadata: dict[str, Any] | None = None,
    ) -> SourceAdapterResult[AdapterItem]:
        """Build an empty-but-successful adapter result."""
        return cls(
            source=source,
            operation=operation,
            items=[],
            total_count=0,
            status="empty",
            metadata=dict(metadata or {}),
        )

    @classmethod
    def failure(
        cls,
        *,
        source: str,
        operation: str,
        error: SourceAdapterError,
        metadata: dict[str, Any] | None = None,
    ) -> SourceAdapterResult[AdapterItem]:
        """Build a failed adapter result without raising upstream."""
        return cls(
            source=source,
            operation=operation,
            items=[],
            total_count=0,
            status="error",
            errors=[error],
            metadata=dict(metadata or {}),
        )

    @property
    def has_items(self) -> bool:
        return bool(self.items)


@dataclass(frozen=True)
class SourceAdapterCall(Generic[AdapterItem]):
    """Single source adapter invocation descriptor."""

    source: str
    operation: str
    execute: Callable[
        [],
        Awaitable[
            SourceAdapterResult[AdapterItem]
            ^ TwoItemSourceAdapterOutcome
            | ThreeItemSourceAdapterOutcome
            | list[AdapterItem]
            | AdapterItem
            | None
        ],
    ]


def normalize_source_adapter_error(
    source: str,
    operation: str,
    error: Exception,
) -> SourceAdapterError:
    """Map raw exceptions into a consistent adapter error contract."""
    if isinstance(error, RetryableOperationError):
        return SourceAdapterError(
            source=source,
            operation=operation,
            message=str(error),
            kind="retryable",
            retryable=True,
            status_code=error.status_code,
        )

    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
        return SourceAdapterError(
            source=source,
            operation=operation,
            message=f"HTTP {status_code}: {error.response.reason_phrase}",
            kind="http",
            retryable=status_code in {408, 425, 429, 500, 502, 503, 504},
            status_code=status_code,
        )

    if isinstance(error, httpx.TimeoutException):
        return SourceAdapterError(
            source=source,
            operation=operation,
            message=str(error) or "Request timed out",
            kind="timeout",
            retryable=True,
        )

    if isinstance(error, httpx.RequestError):
        return SourceAdapterError(
            source=source,
            operation=operation,
            message=str(error),
            kind="transport",
            retryable=True,
        )

    return SourceAdapterError(
        source=source,
        operation=operation,
        message=str(error),
        kind="unexpected",
        retryable=False,
    )


def format_source_adapter_error(error: SourceAdapterError) -> str:
    """Render a concise source-scoped error string for user-facing summaries."""
    return f"{error.source}: {error.message}"


def _coerce_source_adapter_outcome(
    source: str,
    operation: str,
    outcome: (
        SourceAdapterResult[AdapterItem]
        | TwoItemSourceAdapterOutcome
        | ThreeItemSourceAdapterOutcome
        | list[AdapterItem]
        | AdapterItem
        | None
    ),
) -> SourceAdapterResult[AdapterItem]:
    if isinstance(outcome, SourceAdapterResult):
        if outcome.total_count == 0 and outcome.items:
            outcome.total_count = len(outcome.items)
        if not outcome.items and outcome.status == "ok":
            outcome.status = "empty"
        return outcome

    if outcome is None:
        return SourceAdapterResult.empty(source=source, operation=operation)

    items: list[AdapterItem]
    total_count: int | None = None
    metadata: dict[str, Any] = {}

    if isinstance(outcome, tuple):
        if len(outcome) == TWO_ITEM_TUPLE_LEN:
            two_item_outcome = cast("TwoItemSourceAdapterOutcome", outcome)
            items = list(two_item_outcome[0])
            second = two_item_outcome[1]
            if isinstance(second, dict):
                metadata = dict(second)
            else:
                total_count = int(second)
        elif len(outcome) == THREE_ITEM_TUPLE_LEN:
            three_item_outcome = cast("ThreeItemSourceAdapterOutcome", outcome)
            items = list(three_item_outcome[0])
            second = three_item_outcome[1]
            third = three_item_outcome[2]
            total_count = int(second)
            metadata = dict(third)
        else:
            msg = f"Unsupported adapter tuple outcome length: {len(outcome)}"
            raise ValueError(msg)
    elif isinstance(outcome, list):
        items = list(outcome)
    else:
        items = [outcome]

    resolved_total = total_count if total_count is not None else len(items)
    status: SourceAdapterStatus = "ok" if items else "empty"
    return SourceAdapterResult(
        source=source,
        operation=operation,
        items=items,
        total_count=resolved_total,
        status=status,
        metadata=metadata,
    )


async def execute_source_adapter_call(call: SourceAdapterCall[AdapterItem]) -> SourceAdapterResult[AdapterItem]:
    """Execute a single adapter call and normalize success or failure."""
    try:
        outcome = await call.execute()
        return _coerce_source_adapter_outcome(call.source, call.operation, outcome)
    except Exception as error:  # noqa: BLE001 - adapter boundary intentionally normalizes arbitrary source failures
        normalized = normalize_source_adapter_error(call.source, call.operation, error)
        logger.warning(
            "Source adapter call failed: %s.%s (%s)",
            call.source,
            call.operation,
            normalized.message,
        )
        return SourceAdapterResult.failure(
            source=call.source,
            operation=call.operation,
            error=normalized,
        )


async def gather_source_adapter_calls(
    calls: list[SourceAdapterCall[AdapterItem]],
) -> list[SourceAdapterResult[AdapterItem]]:
    """Execute adapter calls concurrently and always return normalized results."""
    if not calls:
        return []
    return await asyncio.gather(*(execute_source_adapter_call(call) for call in calls))
