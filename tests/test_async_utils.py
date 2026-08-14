"""Tests for async_utils.py — RateLimiter, CircuitBreaker, retry, batch_process, gather."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from pubmed_search.infrastructure.sources.base_client import BaseAPIClient
from pubmed_search.shared.async_utils import (
    CircuitBreaker,
    RateLimiter,
    RateLimitPolicy,
    RequestExecutionPolicy,
    RetryableOperationError,
    RetryPolicy,
    batch_process,
    close_shared_async_client,
    gather_with_errors,
    get_rate_limiter,
    get_shared_async_client,
    get_transport_kernel,
    parse_retry_after,
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

    @pytest.mark.asyncio
    async def test_waited_token_time_is_not_counted_twice(self, monkeypatch):
        """A 1-per-3s limiter must not emit pairs at t=3, t=6, ... ."""
        from pubmed_search.shared import async_utils

        clock = [0.0]

        async def advance(delay: float) -> None:
            clock[0] += delay

        monkeypatch.setattr(async_utils, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        monkeypatch.setattr(async_utils, "asyncio", SimpleNamespace(sleep=advance))
        limiter = RateLimiter(rate=1.0, per=3.0)
        acquired_at: list[float] = []

        for _ in range(5):
            await limiter.acquire()
            acquired_at.append(clock[0])

        assert acquired_at == [0.0, 3.0, 6.0, 9.0, 12.0]


class TestGetRateLimiter:
    async def test_creates_new(self):
        # Use unique name to avoid conflicts
        rl = get_rate_limiter("test_unique_abc", rate=5.0)
        assert isinstance(rl, RateLimiter)

    async def test_reuses_existing(self):
        rl1 = get_rate_limiter("test_reuse_xyz", rate=5.0)
        rl2 = get_rate_limiter("test_reuse_xyz", rate=5.0)
        assert rl1 is rl2


# ============================================================
# gather_with_errors
# ============================================================


class TestGatherWithErrors:
    @pytest.mark.asyncio
    async def test_all_success_preserves_input_order(self):
        async def task(n, delay):
            await asyncio.sleep(delay)
            return n * 2

        results = await gather_with_errors(task(1, 0.02), task(2, 0.01), task(3, 0))
        assert results == [2, 4, 6]

    @pytest.mark.asyncio
    async def test_with_exceptions_returned_in_input_order(self):
        async def ok():
            return "ok"

        async def fail():
            raise ValueError("bad")

        results = await gather_with_errors(ok(), fail(), return_exceptions=True)
        assert results[0] == "ok"
        assert isinstance(results[1], ValueError)

    @pytest.mark.asyncio
    async def test_failure_cancels_and_drains_unfinished_children(self):
        child_started = asyncio.Event()
        child_cleaned_up = asyncio.Event()

        async def wait_forever():
            child_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                child_cleaned_up.set()

        async def fail_after_child_starts():
            await child_started.wait()
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            await gather_with_errors(wait_forever(), fail_after_child_starts())

        assert child_cleaned_up.is_set()

    @pytest.mark.asyncio
    async def test_caller_cancellation_is_propagated_after_child_cleanup(self):
        child_started = asyncio.Event()
        child_cleaned_up = asyncio.Event()

        async def wait_forever():
            child_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                child_cleaned_up.set()

        parent = asyncio.create_task(gather_with_errors(wait_forever(), return_exceptions=True))
        await asyncio.wait_for(child_started.wait(), timeout=1)
        parent.cancel()

        with pytest.raises(asyncio.CancelledError):
            await parent

        assert child_cleaned_up.is_set()

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

    async def test_is_open_property(self):
        cb = CircuitBreaker()
        assert cb.is_open is False

        cb._state = "open"
        cb._last_failure_time = time.monotonic()
        assert cb.is_open is True

    async def test_state_property(self):
        cb = CircuitBreaker()
        assert cb.state == "closed"


# ============================================================
# Shared Async HTTP Client
# ============================================================


class TestSharedAsyncClient:
    @pytest.mark.asyncio
    async def test_get_shared_async_client_returns_httpx_client(self):
        import httpx

        client = get_shared_async_client()
        assert isinstance(client, httpx.AsyncClient)
        assert not client.is_closed

    @pytest.mark.asyncio
    async def test_get_shared_async_client_returns_same_instance(self):
        client1 = get_shared_async_client()
        client2 = get_shared_async_client()
        assert client1 is client2

    @pytest.mark.asyncio
    async def test_get_shared_async_client_follows_redirects(self):
        client = get_shared_async_client()
        assert client.follow_redirects is True

    @pytest.mark.asyncio
    async def test_close_shared_async_client(self):
        client = get_shared_async_client()
        assert not client.is_closed
        await close_shared_async_client()
        assert client.is_closed

    @pytest.mark.asyncio
    async def test_get_shared_async_client_recreates_after_close(self):
        client1 = get_shared_async_client()
        await close_shared_async_client()
        client2 = get_shared_async_client()
        assert client2 is not client1
        assert not client2.is_closed
        # Clean up
        await close_shared_async_client()


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


# ============================================================
# TransportExecutionKernel
# ============================================================


class TestTransportKernel:
    @pytest.mark.asyncio
    async def test_parse_retry_after_seconds(self):
        assert parse_retry_after("3") == 3.0

    @pytest.mark.asyncio
    async def test_retries_retryable_operation_error(self):
        kernel = get_transport_kernel()
        attempts = 0

        async def flaky():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RetryableOperationError("rate limited", retry_after=0.0, status_code=429)
            return "ok"

        result = await kernel.execute(
            flaky,
            policy=RequestExecutionPolicy(
                service_name="test-kernel",
                timeout=1.0,
                retry=RetryPolicy(max_attempts=2, base_delay=0.01, max_delay=0.01, jitter=False),
                rate_limit=RateLimitPolicy(name="test-kernel-rate", rate=100.0, per=1.0),
            ),
        )

        assert result == "ok"
        assert attempts == 2

    @pytest.mark.asyncio
    async def test_retry_log_never_serializes_exception_message(self, caplog: pytest.LogCaptureFixture):
        kernel = get_transport_kernel()
        private_url = "https://provider.invalid/search?query=private-phenotype&apiKey=SENTINEL"

        async def always_retry():
            raise RetryableOperationError(private_url, retry_after=0.0, status_code=429)

        with caplog.at_level("WARNING", logger="pubmed_search.shared.async_utils"):
            with pytest.raises(RetryableOperationError):
                await kernel.execute(
                    always_retry,
                    policy=RequestExecutionPolicy(
                        service_name="redaction-test",
                        timeout=1.0,
                        retry=RetryPolicy(max_attempts=2, base_delay=0.0, max_delay=0.0, jitter=False),
                    ),
                )

        assert "RetryableOperationError" in caplog.text
        assert "private-phenotype" not in caplog.text
        assert "SENTINEL" not in caplog.text

    @pytest.mark.asyncio
    async def test_non_retryable_error_propagates(self):
        kernel = get_transport_kernel()

        async def fail_fast():
            raise ValueError("bad input")

        with pytest.raises(ValueError):
            await kernel.execute(
                fail_fast,
                policy=RequestExecutionPolicy(
                    service_name="test-kernel-fail",
                    timeout=1.0,
                    retry=RetryPolicy(max_attempts=2, base_delay=0.01, max_delay=0.01, jitter=False),
                ),
            )

    @pytest.mark.asyncio
    async def test_total_timeout_caps_retry_backoff(self):
        kernel = get_transport_kernel()
        attempts = 0

        async def always_retry():
            nonlocal attempts
            attempts += 1
            raise RetryableOperationError("slow retry", retry_after=0.05, status_code=429)

        started = time.monotonic()
        with pytest.raises(asyncio.TimeoutError, match="total timeout"):
            await kernel.execute(
                always_retry,
                policy=RequestExecutionPolicy(
                    service_name="test-kernel-budget",
                    timeout=1.0,
                    total_timeout=0.01,
                    retry=RetryPolicy(max_attempts=4, base_delay=0.05, max_delay=0.05, jitter=False),
                    rate_limit=RateLimitPolicy(name="test-kernel-budget-rate", rate=100.0, per=1.0),
                ),
            )

        assert attempts == 1
        assert time.monotonic() - started < 0.05


class TestSharedUpstreamBudget:
    """Parallel fan-out must draw from one budget per upstream, not one each."""

    class _StubClient(BaseAPIClient):
        _service_name = "Budget Stub"

        def __init__(self, min_interval: float = 0.01) -> None:
            super().__init__(base_url="https://example.invalid", min_interval=min_interval)

    async def test_two_clients_of_one_service_use_the_same_limiter(self, monkeypatch):
        used: list[int] = []
        original = RateLimiter.acquire

        async def spy(limiter: RateLimiter) -> None:
            used.append(id(limiter))
            await original(limiter)

        monkeypatch.setattr(RateLimiter, "acquire", spy)

        # Both clients must stay alive: freeing the first would let CPython reuse
        # its address, which would mask an id-keyed limiter.
        first = self._StubClient()
        second = self._StubClient()
        await first._rate_limit()
        await second._rate_limit()

        assert len(used) == 2
        assert len(set(used)) == 1, "each client got its own budget, so the real request rate doubles"

    async def test_a_slower_client_lowers_the_shared_budget(self):
        fast = get_rate_limiter("shared-budget-test", rate=1.0, per=0.1, conservative=True)
        slow = get_rate_limiter("shared-budget-test", rate=1.0, per=5.0, conservative=True)

        assert slow is fast
        assert fast.per == 5.0

    async def test_a_faster_client_cannot_raise_the_shared_budget(self):
        slow = get_rate_limiter("raise-budget-test", rate=1.0, per=5.0, conservative=True)
        faster = get_rate_limiter("raise-budget-test", rate=1.0, per=0.1, conservative=True)

        assert faster is slow
        assert slow.per == 5.0, "a client with an API key must not lift the limit for everyone"

    async def test_transport_kernel_cannot_raise_an_existing_shared_budget(self):
        kernel = get_transport_kernel()
        slow = kernel._resolve_rate_limiter(
            RequestExecutionPolicy(
                service_name="kernel-shared-budget",
                rate_limit=RateLimitPolicy(name="kernel-shared-budget", rate=1.0, per=5.0),
            )
        )
        faster = kernel._resolve_rate_limiter(
            RequestExecutionPolicy(
                service_name="kernel-shared-budget",
                rate_limit=RateLimitPolicy(name="kernel-shared-budget", rate=1.0, per=0.1),
            )
        )

        assert slow is not None
        assert faster is slow
        assert slow.per == 5.0

    async def test_primitives_are_not_shared_across_event_loops(self):
        first = get_rate_limiter("loop-scope-test", rate=1.0, per=1.0)
        second = await asyncio.to_thread(
            lambda: asyncio.run(_resolve_limiter("loop-scope-test")),
        )
        assert second is not first


async def _resolve_limiter(name: str) -> RateLimiter:
    return get_rate_limiter(name, rate=1.0, per=1.0)


class TestRateLimiterBoundaries:
    """A zero or negative budget used to divide by zero deep inside acquire()."""

    @pytest.mark.parametrize(("rate", "per"), [(1.0, 0.0), (0.0, 1.0), (-1.0, 1.0), (1.0, -1.0), (0.0, 0.0)])
    def test_non_positive_budget_is_rejected_at_construction(self, rate, per):
        with pytest.raises(ValueError, match="positive budget"):
            RateLimiter(rate=rate, per=per)

    def test_smallest_usable_budget_is_accepted(self):
        assert RateLimiter(rate=1e-6, per=1e-6).rate == 1e-6

    async def test_cooldown_of_zero_is_a_no_op(self):
        limiter = RateLimiter(rate=100.0, per=1.0)
        await limiter.apply_cooldown(0)
        await asyncio.wait_for(limiter.acquire(), timeout=1)

    async def test_server_cooldown_delays_the_next_acquire(self):
        limiter = RateLimiter(rate=100.0, per=1.0)
        await limiter.apply_cooldown(0.05)
        started = time.monotonic()
        await limiter.acquire()
        assert time.monotonic() - started >= 0.04
