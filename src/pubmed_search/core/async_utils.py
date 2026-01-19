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
- Retry with exponential backoff
"""

from __future__ import annotations

import asyncio
import time
import logging
from dataclasses import dataclass, field
from typing import TypeVar, Callable, Awaitable, Any
from collections.abc import Sequence
from functools import wraps

from .exceptions import (
    RateLimitError,
    is_retryable_error,
    get_retry_delay,
)

logger = logging.getLogger(__name__)

T = TypeVar('T')


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
    per: float = 1.0   # period in seconds
    _tokens: float = field(init=False)
    _last_update: float = field(init=False)
    _lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)
    
    def __post_init__(self) -> None:
        self._tokens = self.rate
        self._last_update = time.monotonic()
    
    async def acquire(self) -> None:
        """Acquire a token, waiting if necessary."""
        async with self._lock:
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
    
    async def __aenter__(self) -> RateLimiter:
        await self.acquire()
        return self
    
    async def __aexit__(self, *args: Any) -> None:
        pass


# Global rate limiters for different APIs
_rate_limiters: dict[str, RateLimiter] = {}


def get_rate_limiter(api_name: str, rate: float = 3.0) -> RateLimiter:
    """Get or create a rate limiter for an API."""
    if api_name not in _rate_limiters:
        _rate_limiters[api_name] = RateLimiter(rate=rate)
    return _rate_limiters[api_name]


# =============================================================================
# Retry Decorator
# =============================================================================

def async_retry(
    max_attempts: int = 3,
    retryable_check: Callable[[Exception], bool] = is_retryable_error,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """
    Decorator for async functions with automatic retry.
    
    Uses exponential backoff with jitter.
    
    Example:
        @async_retry(max_attempts=3)
        async def fetch_data(pmid: str) -> dict:
            ...
    """
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            last_error: Exception | None = None
            
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    
                    if not retryable_check(e):
                        raise
                    
                    if attempt < max_attempts - 1:
                        delay = get_retry_delay(e, attempt)
                        logger.warning(
                            f"Retry {attempt + 1}/{max_attempts} for {func.__name__}: "
                            f"{e} (waiting {delay:.1f}s)"
                        )
                        await asyncio.sleep(delay)
            
            # Should not reach here, but for type safety
            if last_error:
                raise last_error
            raise RuntimeError("Unexpected retry loop exit")
        
        return wrapper
    return decorator


# =============================================================================
# Parallel Execution with TaskGroup (Python 3.11+)
# =============================================================================

async def gather_with_errors[T](
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
        async def safe_run(coro: Awaitable[T], index: int) -> None:
            try:
                result = await coro
                results.append(result)
            except Exception as e:
                results.append(e)
        
        async with asyncio.TaskGroup() as tg:
            for i, coro in enumerate(coros):
                tg.create_task(safe_run(coro, i))
    else:
        # Fail fast on any exception
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(coro) for coro in coros]
        results = [task.result() for task in tasks]
    
    return results


async def batch_process[T, R](
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
        batch = items[i:i + batch_size]
        
        async def process_with_limit(item: T) -> R:
            if rate_limiter:
                await rate_limiter.acquire()
            return await processor(item)
        
        batch_results = await gather_with_errors(
            *[process_with_limit(item) for item in batch],
            return_exceptions=True
        )
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
    
    States:
    - CLOSED: Normal operation
    - OPEN: Failing, reject requests immediately
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
    def is_open(self) -> bool:
        """Check if circuit is open (rejecting requests)."""
        if self._state == "open":
            # Check if recovery timeout passed
            if self._last_failure_time:
                if time.monotonic() - self._last_failure_time > self.recovery_timeout:
                    return False  # Move to half-open
            return True
        return False
    
    async def __aenter__(self) -> CircuitBreaker:
        async with self._lock:
            if self.is_open:
                raise RateLimitError(
                    "Circuit breaker is open",
                    retry_after=self.recovery_timeout
                )
            
            if self._state == "open":
                self._state = "half_open"
                self._half_open_calls = 0
            
            if self._state == "half_open":
                if self._half_open_calls >= self.half_open_max_calls:
                    raise RateLimitError(
                        "Circuit breaker is half-open (max calls reached)",
                        retry_after=self.recovery_timeout / 2
                    )
                self._half_open_calls += 1
        
        return self
    
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        async with self._lock:
            if exc_val is not None:
                self._failure_count += 1
                self._last_failure_time = time.monotonic()
                
                if self._failure_count >= self.failure_threshold:
                    self._state = "open"
                    logger.warning(
                        f"Circuit breaker opened after {self._failure_count} failures"
                    )
            else:
                # Success
                if self._state == "half_open":
                    self._state = "closed"
                    self._failure_count = 0
                    logger.info("Circuit breaker closed (recovered)")
                elif self._state == "closed":
                    self._failure_count = max(0, self._failure_count - 1)


# =============================================================================
# Connection Pool
# =============================================================================

class AsyncConnectionPool[T]:
    """
    Generic async connection pool.
    
    Uses Python 3.12 type parameter syntax.
    
    Example:
        pool = AsyncConnectionPool(
            factory=create_http_client,
            max_size=10
        )
        async with pool.acquire() as client:
            await client.get(url)
    """
    
    def __init__(
        self,
        factory: Callable[[], Awaitable[T]],
        max_size: int = 10,
        min_size: int = 2,
    ) -> None:
        self._factory = factory
        self._max_size = max_size
        self._min_size = min_size
        self._pool: asyncio.Queue[T] = asyncio.Queue(maxsize=max_size)
        self._size = 0
        self._lock = asyncio.Lock()
    
    async def _create_connection(self) -> T:
        """Create a new connection."""
        return await self._factory()
    
    async def acquire(self) -> T:
        """Acquire a connection from the pool."""
        # Try to get from pool first
        try:
            return self._pool.get_nowait()
        except asyncio.QueueEmpty:
            pass
        
        # Create new if under max size
        async with self._lock:
            if self._size < self._max_size:
                self._size += 1
                return await self._create_connection()
        
        # Wait for available connection
        return await self._pool.get()
    
    async def release(self, conn: T) -> None:
        """Release a connection back to the pool."""
        try:
            self._pool.put_nowait(conn)
        except asyncio.QueueFull:
            # Pool is full, discard connection
            async with self._lock:
                self._size -= 1


# =============================================================================
# Utility Functions
# =============================================================================

async def timeout_with_fallback[T](
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
