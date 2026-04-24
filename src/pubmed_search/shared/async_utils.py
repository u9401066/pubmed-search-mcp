"""
Async Utilities for Efficient API Calls.

Python 3.12+ features used:
- asyncio.TaskGroup for structured concurrency (3.11+)
- Type parameter syntax for generic classes
- Modern async patterns

Provides:
- Parallel API calls with TaskGroup
- Rate limiting with token bucket
- Connection pooling
- Circuit breaker for fault tolerance
- Shared transport/resilience kernel for external I/O execution

Note:
    The transport kernel centralizes retry, timeout, Retry-After,
    rate limiting, circuit breaker, and concurrency bulkhead policies.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any, TypeVar

from typing_extensions import Self

from .exceptions import (
    RateLimitError,
    is_retryable_error,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True)
class RetryPolicy:
    """Retry policy for external operations."""

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    jitter: bool = True
    respect_retry_after: bool = True
    retry_after_cap: float = 120.0
    retryable_status_codes: frozenset[int] = field(
        default_factory=lambda: frozenset({408, 425, 429, 500, 502, 503, 504})
    )
    retryable_messages: tuple[str, ...] = (
        "rate limit",
        "too many requests",
        "temporarily unavailable",
        "service unavailable",
        "backend failed",
        "connection reset",
        "timeout",
        "database is not supported",
    )
    retry_on_timeouts: bool = True
    retry_on_transport_errors: bool = True


@dataclass(frozen=True)
class RateLimitPolicy:
    """Rate limiting policy for a named external service."""

    name: str
    rate: float
    per: float = 1.0


@dataclass(frozen=True)
class CircuitBreakerPolicy:
    """Circuit breaker policy for a named external service."""

    name: str
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 3


@dataclass(frozen=True)
class RequestExecutionPolicy:
    """Unified execution policy for external operations."""

    service_name: str
    timeout: float | None = None
    total_timeout: float | None = None
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    rate_limit: RateLimitPolicy | None = None
    circuit_breaker: CircuitBreaker | None = None
    circuit_breaker_policy: CircuitBreakerPolicy | None = None
    concurrency_limit: int | None = None
    concurrency_name: str | None = None


class OperationBudgetExceeded(asyncio.TimeoutError):
    """Raised when the overall execution budget is exhausted."""


class RetryableOperationError(Exception):
    """Signal that an operation should be retried by the transport kernel."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.status_code = status_code


def parse_retry_after(value: str | None) -> float | None:
    """Parse Retry-After header values in seconds or HTTP-date form."""
    if not value:
        return None

    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        pass

    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)

    delay = (retry_at - datetime.now(tz=timezone.utc)).total_seconds()
    return max(0.0, delay)


# =============================================================================
# Rate Limiter (Token Bucket Algorithm)
# =============================================================================


@dataclass
class RateLimiter:
    """
    Token bucket rate limiter for API calls.

    NCBI allows:
    - Without API key: 3 requests/second
    - With API key: 10 requests/second

    Example:
        limiter = RateLimiter(rate=10, per=1.0)
        async with limiter:
            await make_api_call()
    """

    rate: float = 3.0  # requests per period
    per: float = 1.0  # period in seconds
    _tokens: float = field(init=False)
    _last_update: float = field(init=False)
    _cooldown_until: float = field(init=False, default=0.0)
    _lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        self._tokens = self.rate
        self._last_update = time.monotonic()

    async def acquire(self) -> None:
        """Acquire a token, waiting if necessary."""
        async with self._lock:
            now = time.monotonic()

            if now < self._cooldown_until:
                wait_time = self._cooldown_until - now
                logger.debug(f"Rate limiter cooldown: waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
                now = time.monotonic()

            elapsed = now - self._last_update
            self._tokens = min(self.rate, self._tokens + elapsed * (self.rate / self.per))
            self._last_update = now

            if self._tokens < 1:
                wait_time = (1 - self._tokens) * (self.per / self.rate)
                logger.debug(f"Rate limit: waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
                self._tokens = 0
            else:
                self._tokens -= 1

    async def apply_cooldown(self, retry_after: float) -> None:
        """Apply a server-directed cooldown window such as Retry-After."""
        if retry_after <= 0:
            return

        async with self._lock:
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + retry_after)

    def reconfigure(self, *, rate: float, per: float = 1.0) -> None:
        """Update limiter throughput for an existing shared limiter."""
        self.rate = rate
        self.per = per
        self._tokens = min(self._tokens, self.rate)

    async def __aenter__(self) -> Self:
        await self.acquire()
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


# Global rate limiters for different APIs
_rate_limiters: dict[str, RateLimiter] = {}
_circuit_breakers: dict[str, CircuitBreaker] = {}
_bulkheads: dict[str, asyncio.Semaphore] = {}


def _registry_key(name: str) -> str:
    """Isolate asyncio primitives per event loop to avoid cross-loop reuse."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return f"{name}:global"
    return f"{name}:loop-{id(loop)}"


def get_rate_limiter(api_name: str, rate: float = 3.0, per: float = 1.0) -> RateLimiter:
    """Get or create a rate limiter for an API."""
    key = _registry_key(api_name)
    if key not in _rate_limiters:
        _rate_limiters[key] = RateLimiter(rate=rate, per=per)
    else:
        limiter = _rate_limiters[key]
        if limiter.rate != rate or limiter.per != per:
            limiter.reconfigure(rate=rate, per=per)
    return _rate_limiters[key]


def get_circuit_breaker(
    name: str,
    *,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
    half_open_max_calls: int = 3,
) -> CircuitBreaker:
    """Get or create a shared circuit breaker for a service."""
    key = _registry_key(name)
    breaker = _circuit_breakers.get(key)
    if breaker is None:
        breaker = CircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            half_open_max_calls=half_open_max_calls,
        )
        _circuit_breakers[key] = breaker
    return breaker


def get_bulkhead(name: str, limit: int) -> asyncio.Semaphore:
    """Get or create a shared concurrency limiter for a service."""
    key = _registry_key(name)
    semaphore = _bulkheads.get(key)
    if semaphore is None:
        semaphore = asyncio.Semaphore(limit)
        _bulkheads[key] = semaphore
    return semaphore


def create_async_http_client(
    *,
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
    follow_redirects: bool = True,
    max_connections: int = 20,
    max_keepalive_connections: int = 10,
    keepalive_expiry: float = 30.0,
) -> Any:
    """Create a configured httpx.AsyncClient with consistent transport defaults."""
    import httpx

    return httpx.AsyncClient(
        timeout=timeout,
        headers=headers or {},
        follow_redirects=follow_redirects,
        limits=httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
            keepalive_expiry=keepalive_expiry,
        ),
    )


class TransportExecutionKernel:
    """Unified execution kernel for resilient external operations."""

    async def execute(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        policy: RequestExecutionPolicy,
        should_retry: Callable[[BaseException], bool] | None = None,
    ) -> T:
        attempts = max(1, policy.retry.max_attempts)
        deadline = self._build_deadline(policy.total_timeout)

        for attempt in range(attempts):
            limiter = self._resolve_rate_limiter(policy)
            breaker = self._resolve_circuit_breaker(policy)
            bulkhead = self._resolve_bulkhead(policy)

            self._raise_if_budget_exhausted(policy, deadline)

            if limiter is not None:
                await self._await_with_budget(
                    limiter.acquire(),
                    policy=policy,
                    deadline=deadline,
                    phase="rate limit wait",
                )

            try:
                async with self._bulkhead_context(bulkhead), self._breaker_context(breaker):
                    return await self._execute_operation_with_budget(operation, policy=policy, deadline=deadline)
            except OperationBudgetExceeded:
                raise
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                retry_after = self._extract_retry_after(exc)
                if limiter is not None and retry_after is not None:
                    capped_retry_after = min(retry_after, policy.retry.retry_after_cap)
                    await limiter.apply_cooldown(capped_retry_after)

                if attempt + 1 >= attempts or not self._is_retryable(exc, policy.retry, should_retry):
                    raise

                delay = self._compute_retry_delay(policy.retry, attempt, retry_after)
                logger.warning(
                    "%s attempt %s/%s failed: %s; retrying in %.2fs",
                    policy.service_name,
                    attempt + 1,
                    attempts,
                    exc,
                    delay,
                )
                await self._sleep_with_budget(delay, policy=policy, deadline=deadline)

        raise RuntimeError(f"{policy.service_name} transport execution exhausted unexpectedly")

    @staticmethod
    def _build_deadline(total_timeout: float | None) -> float | None:
        if total_timeout is None:
            return None
        return time.monotonic() + total_timeout

    @staticmethod
    def _remaining_budget(deadline: float | None) -> float | None:
        if deadline is None:
            return None
        return deadline - time.monotonic()

    @classmethod
    def _raise_if_budget_exhausted(
        cls,
        policy: RequestExecutionPolicy,
        deadline: float | None,
    ) -> None:
        remaining = cls._remaining_budget(deadline)
        if remaining is None or remaining > 0:
            return
        raise OperationBudgetExceeded(cls._budget_message(policy, "overall execution budget"))

    @staticmethod
    def _budget_message(policy: RequestExecutionPolicy, phase: str) -> str:
        if policy.total_timeout is None:
            return f"{policy.service_name} timed out during {phase}"
        return (
            f"{policy.service_name} exceeded total timeout of {policy.total_timeout:.2f}s "
            f"during {phase}"
        )

    @classmethod
    async def _await_with_budget(
        cls,
        awaitable: Awaitable[T],
        *,
        policy: RequestExecutionPolicy,
        deadline: float | None,
        phase: str,
    ) -> T:
        remaining = cls._remaining_budget(deadline)
        if remaining is None:
            return await awaitable
        if remaining <= 0:
            raise OperationBudgetExceeded(cls._budget_message(policy, phase))
        try:
            return await asyncio.wait_for(awaitable, timeout=remaining)
        except asyncio.TimeoutError as exc:
            raise OperationBudgetExceeded(cls._budget_message(policy, phase)) from exc

    @classmethod
    async def _execute_operation_with_budget(
        cls,
        operation: Callable[[], Awaitable[T]],
        *,
        policy: RequestExecutionPolicy,
        deadline: float | None,
    ) -> T:
        remaining = cls._remaining_budget(deadline)
        timeout = policy.timeout
        if remaining is not None:
            if remaining <= 0:
                raise OperationBudgetExceeded(cls._budget_message(policy, "operation"))
            timeout = remaining if timeout is None else min(timeout, remaining)

        if timeout is None:
            return await operation()

        try:
            return await asyncio.wait_for(operation(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            remaining_after_timeout = cls._remaining_budget(deadline)
            if remaining_after_timeout is not None and remaining_after_timeout <= 0:
                raise OperationBudgetExceeded(cls._budget_message(policy, "operation")) from exc
            raise

    @classmethod
    async def _sleep_with_budget(
        cls,
        delay: float,
        *,
        policy: RequestExecutionPolicy,
        deadline: float | None,
    ) -> None:
        remaining = cls._remaining_budget(deadline)
        if remaining is None:
            await asyncio.sleep(delay)
            return
        if remaining <= 0 or delay > remaining:
            raise OperationBudgetExceeded(cls._budget_message(policy, "retry backoff"))
        await asyncio.sleep(delay)

    @staticmethod
    def _resolve_rate_limiter(policy: RequestExecutionPolicy) -> RateLimiter | None:
        rate_policy = policy.rate_limit
        if rate_policy is None:
            return None
        return get_rate_limiter(rate_policy.name, rate=rate_policy.rate, per=rate_policy.per)

    @staticmethod
    def _resolve_circuit_breaker(policy: RequestExecutionPolicy) -> CircuitBreaker | None:
        if policy.circuit_breaker is not None:
            return policy.circuit_breaker

        breaker_policy = policy.circuit_breaker_policy
        if breaker_policy is None:
            return None

        return get_circuit_breaker(
            breaker_policy.name,
            failure_threshold=breaker_policy.failure_threshold,
            recovery_timeout=breaker_policy.recovery_timeout,
            half_open_max_calls=breaker_policy.half_open_max_calls,
        )

    @staticmethod
    def _resolve_bulkhead(policy: RequestExecutionPolicy) -> asyncio.Semaphore | None:
        if policy.concurrency_limit is None:
            return None
        name = policy.concurrency_name or policy.service_name
        return get_bulkhead(name, policy.concurrency_limit)

    @staticmethod
    @asynccontextmanager
    async def _bulkhead_context(semaphore: asyncio.Semaphore | None) -> AsyncIterator[None]:
        if semaphore is None:
            yield
            return

        async with semaphore:
            yield

    @staticmethod
    @asynccontextmanager
    async def _breaker_context(breaker: CircuitBreaker | None) -> AsyncIterator[None]:
        if breaker is None:
            yield
            return

        async with breaker:
            yield

    @staticmethod
    def _extract_retry_after(error: BaseException) -> float | None:
        if isinstance(error, RetryableOperationError):
            return error.retry_after

        if isinstance(error, RateLimitError) and error.context.retry_after:
            return float(error.context.retry_after)

        retry_after = getattr(error, "retry_after", None)
        if isinstance(retry_after, (int, float)):
            return float(retry_after)

        return None

    @staticmethod
    def _is_retryable(
        error: BaseException,
        retry_policy: RetryPolicy,
        should_retry: Callable[[BaseException], bool] | None,
    ) -> bool:
        if isinstance(error, RetryableOperationError):
            return True

        if isinstance(error, RateLimitError):
            return True

        if should_retry is not None and should_retry(error):
            return True

        if retry_policy.retry_on_timeouts and isinstance(error, (asyncio.TimeoutError, TimeoutError)):
            return True

        try:
            import httpx
        except Exception:  # noqa: BLE001
            httpx = None  # type: ignore[assignment]

        if httpx is not None:
            if retry_policy.retry_on_timeouts and isinstance(error, httpx.TimeoutException):
                return True
            if retry_policy.retry_on_transport_errors and isinstance(error, httpx.RequestError):
                return True

        error_str = str(error).lower()
        if any(message in error_str for message in retry_policy.retryable_messages):
            return True

        return is_retryable_error(error if isinstance(error, Exception) else Exception(str(error)))

    @staticmethod
    def _compute_retry_delay(retry_policy: RetryPolicy, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None and retry_policy.respect_retry_after:
            return float(min(retry_after, retry_policy.retry_after_cap))

        delay = min(retry_policy.base_delay * (2**attempt), retry_policy.max_delay)
        if retry_policy.jitter:
            delay = random.uniform(delay / 2, delay)  # noqa: S311
        return float(delay)


_transport_kernel: TransportExecutionKernel | None = None


def get_transport_kernel() -> TransportExecutionKernel:
    """Get the shared transport execution kernel."""
    global _transport_kernel
    if _transport_kernel is None:
        _transport_kernel = TransportExecutionKernel()
    return _transport_kernel


# =============================================================================
# Parallel Execution with TaskGroup (Python 3.11+)
# =============================================================================


async def gather_with_errors(
    *coros: Awaitable[T],
    return_exceptions: bool = False,
) -> list[T | Exception]:
    """
    Execute coroutines in parallel using TaskGroup.

    Python 3.11+ TaskGroup provides structured concurrency:
    - All tasks are properly cancelled on failure
    - Exceptions are properly propagated
    - Resources are cleaned up

    Args:
        *coros: Coroutines to execute
        return_exceptions: If True, return exceptions instead of raising

    Returns:
        List of results (or exceptions if return_exceptions=True)

    Example:
        results = await gather_with_errors(
            fetch_pmid("123"),
            fetch_pmid("456"),
            return_exceptions=True
        )
    """
    results: list[T | Exception] = []

    if return_exceptions:
        # Collect all results, including exceptions
        async def safe_run(coro: Awaitable[T]) -> None:
            try:
                result = await coro
                results.append(result)
            except Exception as e:  # noqa: BLE001
                results.append(e)

        async with asyncio.TaskGroup() as tg:  # type: ignore[attr-defined]
            for coro in coros:
                tg.create_task(safe_run(coro))
    else:
        # Fail fast on any exception
        async with asyncio.TaskGroup() as tg:  # type: ignore[attr-defined]
            tasks = [tg.create_task(coro) for coro in coros]
        results = [task.result() for task in tasks]

    return results


async def batch_process(
    items: Sequence[T],
    processor: Callable[[T], Awaitable[R]],
    batch_size: int = 10,
    rate_limiter: RateLimiter | None = None,
) -> list[R | Exception]:
    """
    Process items in batches with rate limiting.

    Args:
        items: Items to process
        processor: Async function to process each item
        batch_size: Number of items per batch
        rate_limiter: Optional rate limiter

    Returns:
        List of results (exceptions for failed items)

    Example:
        results = await batch_process(
            pmids,
            fetch_article_details,
            batch_size=10,
            rate_limiter=ncbi_limiter
        )
    """
    all_results: list[R | Exception] = []

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]

        async def process_with_limit(item: T) -> R:
            if rate_limiter:
                await rate_limiter.acquire()
            return await processor(item)

        batch_results = await gather_with_errors(*[process_with_limit(item) for item in batch], return_exceptions=True)
        all_results.extend(batch_results)

        # Small delay between batches
        if i + batch_size < len(items):
            await asyncio.sleep(0.1)

    return all_results


# =============================================================================
# Circuit Breaker Pattern
# =============================================================================


@dataclass
class CircuitBreaker:
    """
    Circuit breaker for fault tolerance.

    Protects against cascading failures when external APIs are down.
    Used by BaseAPIClient to automatically stop calling failing services.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Service is failing, reject requests immediately
    - HALF_OPEN: Testing if service recovered

    Example:
        breaker = CircuitBreaker(failure_threshold=5)

        async with breaker:
            result = await risky_api_call()
    """

    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 3

    _failure_count: int = field(init=False, default=0)
    _last_failure_time: float | None = field(init=False, default=None)
    _state: str = field(init=False, default="closed")
    _half_open_calls: int = field(init=False, default=0)
    _lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)

    @property
    def state(self) -> str:
        """Current circuit breaker state."""
        return self._state

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (rejecting requests)."""
        if self._state != "open":
            return False
        # Check if recovery timeout passed
        return not (self._last_failure_time and time.monotonic() - self._last_failure_time > self.recovery_timeout)

    async def __aenter__(self) -> Self:
        async with self._lock:
            if self.is_open:
                raise RateLimitError("Circuit breaker is open", retry_after=self.recovery_timeout)

            if self._state == "open":
                self._state = "half_open"
                self._half_open_calls = 0

            if self._state == "half_open":
                if self._half_open_calls >= self.half_open_max_calls:
                    raise RateLimitError(
                        "Circuit breaker is half-open (max calls reached)",
                        retry_after=self.recovery_timeout / 2,
                    )
                self._half_open_calls += 1

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        async with self._lock:
            if exc_val is not None:
                self._failure_count += 1
                self._last_failure_time = time.monotonic()

                if self._failure_count >= self.failure_threshold:
                    self._state = "open"
                    logger.warning(f"Circuit breaker opened after {self._failure_count} failures")
            # Success
            elif self._state == "half_open":
                self._state = "closed"
                self._failure_count = 0
                logger.info("Circuit breaker closed (recovered)")
            elif self._state == "closed":
                self._failure_count = max(0, self._failure_count - 1)


# =============================================================================
# Shared Async HTTP Client
# =============================================================================

_shared_async_client: Any | None = None


def get_shared_async_client() -> Any:
    """
    Get a shared httpx.AsyncClient singleton for general-purpose HTTP requests.

    Replaces per-call ``httpx.AsyncClient(...)`` creation in tools like
    vision_search, openurl, and pdf download.  A single long-lived client
    reuses TCP connections, saving TLS-handshake and DNS-lookup overhead
    on repeated calls.

    The client is configured with:
    - follow_redirects=True (needed by most callers)
    - 30 s default timeout (override per-request with ``timeout=`` kwarg)
    - Connection pool limits matching BaseAPIClient

    Returns:
        A reusable ``httpx.AsyncClient`` instance.

    Example::

        client = get_shared_async_client()
        response = await client.get(url, timeout=10.0)
    """
    global _shared_async_client

    if _shared_async_client is None or _shared_async_client.is_closed:
        _shared_async_client = create_async_http_client(
            timeout=30.0,
            follow_redirects=True,
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=30.0,
        )
    return _shared_async_client


async def close_shared_async_client() -> None:
    """Close the shared async HTTP client (call on shutdown)."""
    global _shared_async_client
    if _shared_async_client is not None and not _shared_async_client.is_closed:
        await _shared_async_client.aclose()
        _shared_async_client = None


# =============================================================================
# Utility Functions
# =============================================================================


async def timeout_with_fallback(
    coro: Awaitable[T],
    timeout: float,
    fallback: T | Callable[[], T],
) -> T:
    """
    Execute coroutine with timeout and fallback.

    Args:
        coro: Coroutine to execute
        timeout: Timeout in seconds
        fallback: Value or callable to return on timeout

    Returns:
        Result or fallback value
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        if callable(fallback):
            return fallback()
        return fallback
