"""Tests for async_utils.py — RateLimiter, CircuitBreaker, retry, batch_process, gather."""

import asyncio
import time

import pytest

from pubmed_search.shared.async_utils import (
    AsyncConnectionPool,
    CircuitBreaker,
    RateLimiter,
    async_retry,
    batch_process,
    gather_with_errors,
    get_rate_limiter,
    timeout_with_fallback,
)
from pubmed_search.shared.exceptions import RateLimitError


# ============================================================
# RateLimiter
# ============================================================

class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_fast(self):
        rl = RateLimiter(rate=10.0, per=1.0)
        await rl.acquire()  # Should not block

    @pytest.mark.asyncio
    async def test_context_manager(self):
        rl = RateLimiter(rate=10.0)
        async with rl:
            pass  # Should not raise

    @pytest.mark.asyncio
    async def test_rate_limiting_kicks_in(self):
        rl = RateLimiter(rate=2.0, per=1.0)
        for _ in range(3):
            await rl.acquire()
        # After 3 acquires at rate=2, it should have waited for the 3rd

    @pytest.mark.asyncio
    async def test_tokens_replenish(self):
        rl = RateLimiter(rate=10.0, per=1.0)
        # Drain tokens
        for _ in range(10):
            await rl.acquire()
        # Wait a bit for replenish
        await asyncio.sleep(0.15)
        await rl.acquire()  # Should succeed


class TestGetRateLimiter:
    def test_creates_new(self):
        # Use unique name to avoid conflicts
        rl = get_rate_limiter("test_unique_abc", rate=5.0)
        assert isinstance(rl, RateLimiter)

    def test_reuses_existing(self):
        rl1 = get_rate_limiter("test_reuse_xyz", rate=5.0)
        rl2 = get_rate_limiter("test_reuse_xyz", rate=5.0)
        assert rl1 is rl2


# ============================================================
# async_retry
# ============================================================

class TestAsyncRetry:
    @pytest.mark.asyncio
    async def test_success_no_retry(self):
        call_count = 0

        @async_retry(max_attempts=3)
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_transient_error(self):
        call_count = 0

        @async_retry(max_attempts=3)
        async def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RateLimitError("rate limit", retry_after=0.01)
            return "recovered"

        result = await fail_twice()
        assert result == "recovered"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_non_retryable_error_not_retried(self):
        call_count = 0

        @async_retry(max_attempts=3)
        async def fail_permanent():
            nonlocal call_count
            call_count += 1
            raise ValueError("permanent error")

        with pytest.raises(ValueError):
            await fail_permanent()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self):
        call_count = 0

        @async_retry(max_attempts=2, retryable_check=lambda e: True)
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("always fails")

        with pytest.raises(RuntimeError):
            await always_fail()
        assert call_count == 2


# ============================================================
# gather_with_errors
# ============================================================

class TestGatherWithErrors:
    @pytest.mark.asyncio
    async def test_all_success(self):
        async def task(n):
            return n * 2

        results = await gather_with_errors(task(1), task(2), task(3))
        assert sorted(results) == [2, 4, 6]

    @pytest.mark.asyncio
    async def test_with_exceptions_returned(self):
        async def ok():
            return "ok"

        async def fail():
            raise ValueError("bad")

        results = await gather_with_errors(
            ok(), fail(), return_exceptions=True
        )
        assert any(isinstance(r, str) for r in results)
        assert any(isinstance(r, ValueError) for r in results)

    @pytest.mark.asyncio
    async def test_empty(self):
        results = await gather_with_errors()
        assert results == []


# ============================================================
# batch_process
# ============================================================

class TestBatchProcess:
    @pytest.mark.asyncio
    async def test_basic_processing(self):
        async def double(n):
            return n * 2

        results = await batch_process([1, 2, 3], double, batch_size=2)
        assert sorted(r for r in results if isinstance(r, int)) == [2, 4, 6]

    @pytest.mark.asyncio
    async def test_with_rate_limiter(self):
        rl = RateLimiter(rate=100.0)

        async def echo(n):
            return n

        results = await batch_process([1, 2, 3], echo, batch_size=2, rate_limiter=rl)
        assert len([r for r in results if isinstance(r, int)]) == 3

    @pytest.mark.asyncio
    async def test_handles_errors(self):
        async def maybe_fail(n):
            if n == 2:
                raise ValueError("bad")
            return n

        results = await batch_process([1, 2, 3], maybe_fail, batch_size=10)
        assert any(isinstance(r, ValueError) for r in results)
        assert any(r == 1 for r in results if isinstance(r, int))

    @pytest.mark.asyncio
    async def test_empty_items(self):
        async def echo(n):
            return n

        results = await batch_process([], echo)
        assert results == []


# ============================================================
# CircuitBreaker
# ============================================================

class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_closed_state_allows_calls(self):
        cb = CircuitBreaker(failure_threshold=3)
        async with cb:
            pass  # Should not raise

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)

        for _ in range(2):
            try:
                async with cb:
                    raise RuntimeError("fail")
            except RuntimeError:
                pass

        assert cb._state == "open"

    @pytest.mark.asyncio
    async def test_open_rejects_calls(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)

        try:
            async with cb:
                raise RuntimeError("fail")
        except RuntimeError:
            pass

        with pytest.raises(RateLimitError):
            async with cb:
                pass

    @pytest.mark.asyncio
    async def test_success_decrements_failure_count(self):
        cb = CircuitBreaker(failure_threshold=5)
        cb._failure_count = 3

        async with cb:
            pass  # Success

        assert cb._failure_count == 2

    @pytest.mark.asyncio
    async def test_half_open_recovery(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)

        try:
            async with cb:
                raise RuntimeError("fail")
        except RuntimeError:
            pass

        await asyncio.sleep(0.02)  # Wait past recovery timeout

        # Should move to half-open and allow a call
        async with cb:
            pass  # Success recovers

        assert cb._state == "closed"

    def test_is_open_property(self):
        cb = CircuitBreaker()
        assert cb.is_open is False

        cb._state = "open"
        cb._last_failure_time = time.monotonic()
        assert cb.is_open is True


# ============================================================
# AsyncConnectionPool
# ============================================================

class TestAsyncConnectionPool:
    @pytest.mark.asyncio
    async def test_acquire_creates_connection(self):
        async def factory():
            return "conn"

        pool = AsyncConnectionPool(factory, max_size=3)
        conn = await pool.acquire()
        assert conn == "conn"
        assert pool._size == 1

    @pytest.mark.asyncio
    async def test_release_returns_to_pool(self):
        async def factory():
            return "conn"

        pool = AsyncConnectionPool(factory, max_size=3)
        conn = await pool.acquire()
        await pool.release(conn)

        # Next acquire should reuse
        conn2 = await pool.acquire()
        assert conn2 == "conn"
        # Size shouldn't increase
        assert pool._size == 1


# ============================================================
# timeout_with_fallback
# ============================================================

class TestTimeoutWithFallback:
    @pytest.mark.asyncio
    async def test_success_returns_result(self):
        async def fast():
            return "ok"

        result = await timeout_with_fallback(fast(), timeout=1.0, fallback="default")
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_timeout_returns_fallback_value(self):
        async def slow():
            await asyncio.sleep(10)
            return "never"

        result = await timeout_with_fallback(slow(), timeout=0.01, fallback="default")
        assert result == "default"

    @pytest.mark.asyncio
    async def test_timeout_returns_callable_fallback(self):
        async def slow():
            await asyncio.sleep(10)

        result = await timeout_with_fallback(slow(), timeout=0.01, fallback=lambda: 42)
        assert result == 42
