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
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import httpx

    from pubmed_search.shared.async_utils import CircuitBreaker, RequestExecutionPolicy
else:

    class _HttpxProxy:
        def __getattr__(self, name: str) -> Any:
            import httpx as httpx_module

            return getattr(httpx_module, name)

    httpx = _HttpxProxy()

logger = logging.getLogger(__name__)

AdapterItem = TypeVar("AdapterItem")
SourceAdapterStatus = Literal["ok", "empty", "partial", "error"]
SourceAdapterErrorKind = Literal["http", "timeout", "transport", "retryable", "validation", "unexpected"]
_SOURCE_ADAPTER_STATUSES = frozenset({"ok", "empty", "partial", "error"})
_SOURCE_ADAPTER_ERROR_KINDS = frozenset({"http", "timeout", "transport", "retryable", "validation", "unexpected"})


@dataclass(frozen=True)
class SourceExecutionSettings:
    """Declarative execution settings shared by source adapters."""

    service_name: str
    timeout: float | None = None
    total_timeout: float | None = None
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
    from pubmed_search.shared.async_utils import (
        CircuitBreakerPolicy,
        RateLimitPolicy,
        RequestExecutionPolicy,
        RetryPolicy,
    )

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
        total_timeout=settings.total_timeout
        or _derive_total_timeout(settings.timeout, settings.max_attempts, settings.max_delay),
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


def _derive_total_timeout(timeout: float | None, max_attempts: int, max_delay: float) -> float | None:
    """Derive a bounded end-to-end budget for adapter calls.

    The per-attempt timeout still caps a single network operation. This helper
    keeps retries useful but prevents retry/backoff amplification from turning
    a nominal 15-30s source timeout into multi-minute waits.
    """
    if timeout is None:
        return None
    if max_attempts <= 1:
        return timeout
    return max(timeout, min(timeout * 2, timeout + max_delay))


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
    next_token: str | int | None = None
    cursor: str | None = None
    cost: float | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

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
    execute: Callable[[], Awaitable[SourceAdapterResult[AdapterItem]]]


def normalize_source_adapter_error(
    source: str,
    operation: str,
    error: Exception,
) -> SourceAdapterError:
    """Map raw exceptions into a consistent adapter error contract."""
    from pubmed_search.shared.async_utils import RetryableOperationError

    if isinstance(error, RetryableOperationError):
        return SourceAdapterError(
            source=source,
            operation=operation,
            message="Upstream request failed",
            kind="retryable",
            retryable=True,
            status_code=error.status_code,
        )

    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
        return SourceAdapterError(
            source=source,
            operation=operation,
            message=f"Upstream returned HTTP {status_code}",
            kind="http",
            retryable=status_code in {408, 425, 429, 500, 502, 503, 504},
            status_code=status_code,
        )

    if isinstance(error, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
        return SourceAdapterError(
            source=source,
            operation=operation,
            message="Upstream request timed out",
            kind="timeout",
            retryable=True,
        )

    if isinstance(error, httpx.RequestError):
        return SourceAdapterError(
            source=source,
            operation=operation,
            message="Upstream transport failed",
            kind="transport",
            retryable=True,
        )

    return SourceAdapterError(
        source=source,
        operation=operation,
        message="Source adapter failed",
        kind="unexpected",
        retryable=False,
    )


def format_source_adapter_error(error: SourceAdapterError) -> str:
    """Render a concise source-scoped error string for user-facing summaries."""
    return f"{error.source}: {error.message}"


def validate_source_adapter_result(
    outcome: object,
    *,
    expected_source: str,
    expected_operation: str,
) -> SourceAdapterResult[Any]:
    """Validate one adapter result and its exact invocation provenance.

    Generic type parameters are erased at runtime, so this boundary validates
    the envelope rather than attempting to guess an adapter's item class.  It
    deliberately rejects malformed or contradictory envelopes instead of
    coercing them into a plausible result.
    """
    if not isinstance(expected_source, str) or not expected_source.strip():
        msg = "expected_source must be a non-empty string"
        raise TypeError(msg)
    if not isinstance(expected_operation, str) or not expected_operation.strip():
        msg = "expected_operation must be a non-empty string"
        raise TypeError(msg)
    if not isinstance(outcome, SourceAdapterResult):
        msg = "Source adapter execute() must return SourceAdapterResult"
        raise TypeError(msg)

    if not isinstance(outcome.source, str) or not outcome.source.strip():
        msg = "SourceAdapterResult.source must be a non-empty string"
        raise TypeError(msg)
    if outcome.source != expected_source:
        msg = f"SourceAdapterResult.source must match expected source '{expected_source}'"
        raise TypeError(msg)
    if not isinstance(outcome.operation, str) or not outcome.operation.strip():
        msg = "SourceAdapterResult.operation must be a non-empty string"
        raise TypeError(msg)
    if outcome.operation != expected_operation:
        msg = f"SourceAdapterResult.operation must match expected operation '{expected_operation}'"
        raise TypeError(msg)
    if not isinstance(outcome.items, list):
        msg = "SourceAdapterResult.items must be a list"
        raise TypeError(msg)
    if not isinstance(outcome.total_count, int) or isinstance(outcome.total_count, bool):
        msg = "SourceAdapterResult.total_count must be an integer"
        raise TypeError(msg)
    if outcome.total_count < 0:
        msg = "SourceAdapterResult.total_count must be nonnegative"
        raise ValueError(msg)
    if outcome.total_count < len(outcome.items):
        msg = "SourceAdapterResult.total_count must be at least the number of returned items"
        raise ValueError(msg)
    if not isinstance(outcome.status, str) or outcome.status not in _SOURCE_ADAPTER_STATUSES:
        msg = "SourceAdapterResult.status must be one of: ok, empty, partial, error"
        raise TypeError(msg)
    if not isinstance(outcome.errors, list):
        msg = "SourceAdapterResult.errors must be a list"
        raise TypeError(msg)
    if not isinstance(outcome.metadata, dict) or not all(isinstance(key, str) for key in outcome.metadata):
        msg = "SourceAdapterResult.metadata must be a dictionary with string keys"
        raise TypeError(msg)
    if outcome.next_token is not None and (
        isinstance(outcome.next_token, bool) or not isinstance(outcome.next_token, (str, int))
    ):
        msg = "SourceAdapterResult.next_token must be a string, integer, or None"
        raise TypeError(msg)
    if outcome.cursor is not None and (not isinstance(outcome.cursor, str) or not outcome.cursor):
        msg = "SourceAdapterResult.cursor must be a non-empty string or None"
        raise TypeError(msg)
    if outcome.cost is not None:
        if isinstance(outcome.cost, bool) or not isinstance(outcome.cost, (int, float)):
            msg = "SourceAdapterResult.cost must be a finite nonnegative number or None"
            raise TypeError(msg)
        if not math.isfinite(outcome.cost) or outcome.cost < 0:
            msg = "SourceAdapterResult.cost must be a finite nonnegative number or None"
            raise ValueError(msg)
    if not isinstance(outcome.provenance, dict) or not all(isinstance(key, str) for key in outcome.provenance):
        msg = "SourceAdapterResult.provenance must be a dictionary with string keys"
        raise TypeError(msg)

    for error in outcome.errors:
        if not isinstance(error, SourceAdapterError):
            msg = "SourceAdapterResult.errors must contain only SourceAdapterError values"
            raise TypeError(msg)
        if not isinstance(error.source, str) or error.source != expected_source:
            msg = "SourceAdapterError.source must match its parent result and expected source"
            raise TypeError(msg)
        if not isinstance(error.operation, str) or error.operation != expected_operation:
            msg = "SourceAdapterError.operation must match its parent result and expected operation"
            raise TypeError(msg)
        if not isinstance(error.message, str) or not error.message.strip():
            msg = "SourceAdapterError.message must be a non-empty string"
            raise TypeError(msg)
        if not isinstance(error.kind, str) or error.kind not in _SOURCE_ADAPTER_ERROR_KINDS:
            msg = "SourceAdapterError.kind is invalid"
            raise TypeError(msg)
        if not isinstance(error.retryable, bool):
            msg = "SourceAdapterError.retryable must be a boolean"
            raise TypeError(msg)
        if error.status_code is not None and (
            not isinstance(error.status_code, int) or isinstance(error.status_code, bool)
        ):
            msg = "SourceAdapterError.status_code must be an integer or None"
            raise TypeError(msg)

    if outcome.status == "ok" and (not outcome.items or outcome.errors):
        msg = "SourceAdapterResult with status 'ok' requires items and forbids errors"
        raise ValueError(msg)
    if outcome.status == "empty" and (outcome.items or outcome.errors):
        msg = "SourceAdapterResult with status 'empty' forbids items and errors"
        raise ValueError(msg)
    if outcome.status == "partial" and (not outcome.items or not outcome.errors):
        msg = "SourceAdapterResult with status 'partial' requires both items and errors"
        raise ValueError(msg)
    if outcome.status == "error" and (outcome.items or not outcome.errors):
        msg = "SourceAdapterResult with status 'error' requires errors and forbids items"
        raise ValueError(msg)

    return outcome


def validate_source_adapter_mapping_result(
    outcome: object,
    *,
    expected_source: str,
    expected_operation: str,
) -> SourceAdapterResult[dict[str, Any]]:
    """Validate an adapter envelope whose items must be provider DTO mappings."""
    validated = validate_source_adapter_result(
        outcome,
        expected_source=expected_source,
        expected_operation=expected_operation,
    )
    if any(not isinstance(item, dict) for item in validated.items):
        msg = "SourceAdapterResult.items must contain only provider DTO dictionaries"
        raise TypeError(msg)
    return cast("SourceAdapterResult[dict[str, Any]]", validated)


async def execute_source_adapter_call(call: SourceAdapterCall[AdapterItem]) -> SourceAdapterResult[AdapterItem]:
    """Execute a typed adapter call and normalize failures at the boundary."""
    try:
        outcome = await call.execute()
        return validate_source_adapter_result(
            outcome,
            expected_source=call.source,
            expected_operation=call.operation,
        )
    except Exception as error:  # noqa: BLE001 - adapter boundary intentionally normalizes arbitrary source failures
        normalized = normalize_source_adapter_error(call.source, call.operation, error)
        logger.warning(
            "Source adapter call failed: %s.%s (%s)",
            call.source,
            call.operation,
            normalized.kind,
        )
        return SourceAdapterResult.failure(
            source=call.source,
            operation=call.operation,
            error=normalized,
        )


async def _execute_source_adapter_call_with_timeout(
    call: SourceAdapterCall[AdapterItem],
    *,
    timeout: float,
) -> SourceAdapterResult[AdapterItem]:
    """Execute one adapter call with a soft per-source timeout."""
    try:
        return await asyncio.wait_for(execute_source_adapter_call(call), timeout=timeout)
    except asyncio.TimeoutError:
        return SourceAdapterResult.failure(
            source=call.source,
            operation=call.operation,
            error=SourceAdapterError(
                source=call.source,
                operation=call.operation,
                message=f"Source adapter timed out after {timeout:.2f}s",
                kind="timeout",
                retryable=True,
            ),
        )


async def gather_source_adapter_calls(
    calls: list[SourceAdapterCall[AdapterItem]],
    *,
    per_call_timeout: float | None = None,
) -> list[SourceAdapterResult[AdapterItem]]:
    """Execute adapter calls concurrently and always return normalized results."""
    if not calls:
        return []
    if per_call_timeout is None:
        return await asyncio.gather(*(execute_source_adapter_call(call) for call in calls))
    return await asyncio.gather(
        *(_execute_source_adapter_call_with_timeout(call, timeout=per_call_timeout) for call in calls)
    )
