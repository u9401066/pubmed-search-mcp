"""
Tests for core module - exceptions and async utilities.

Python 3.12+ features tested:
- Type parameter syntax
- ExceptionGroup
- asyncio.TaskGroup
- Modern dataclass features
"""

import pytest
import asyncio


class TestExceptionHierarchy:
    """Tests for unified exception hierarchy."""
    
    def test_base_exception_creation(self):
        """PubMedSearchError should be creatable with context."""
        from pubmed_search.shared.exceptions import PubMedSearchError, ErrorContext
        
        ctx = ErrorContext(tool_name="test_tool", suggestion="Try again")
        err = PubMedSearchError("Test error", context=ctx)
        
        assert str(err) == "Test error"
        assert err.context.tool_name == "test_tool"
        assert err.context.suggestion == "Try again"
    
    def test_error_to_dict(self):
        """Error should serialize to dict."""
        from pubmed_search.shared.exceptions import PubMedSearchError, ErrorContext
        
        ctx = ErrorContext(tool_name="test", suggestion="hint")
        err = PubMedSearchError("Test", context=ctx)
        
        d = err.to_dict()
        assert d["error"] == "Test"
        assert d["tool"] == "test"
        assert d["suggestion"] == "hint"
    
    def test_error_to_agent_message(self):
        """Error should format for agent consumption."""
        from pubmed_search.shared.exceptions import PubMedSearchError, ErrorContext
        
        ctx = ErrorContext(suggestion="Try X", example="do_something()")
        err = PubMedSearchError("Failed", context=ctx, retryable=True)
        
        msg = err.to_agent_message()
        # Check that message contains key info
        assert "Failed" in msg
        assert "Try X" in msg
        assert "do_something()" in msg
    
    def test_invalid_pmid_error(self):
        """InvalidPMIDError should have correct defaults."""
        from pubmed_search.shared.exceptions import InvalidPMIDError
        
        err = InvalidPMIDError("abc123")
        
        assert "abc123" in str(err)
        assert err.context.suggestion is not None
        assert err.context.example is not None
        assert not err.retryable
    
    def test_rate_limit_error(self):
        """RateLimitError should be retryable."""
        from pubmed_search.shared.exceptions import RateLimitError
        
        err = RateLimitError(retry_after=5.0)
        
        assert err.retryable
        assert err.context.retry_after == 5.0
    
    def test_is_retryable_error(self):
        """is_retryable_error should detect retryable errors."""
        from pubmed_search.shared.exceptions import (
            is_retryable_error,
            RateLimitError,
            InvalidPMIDError,
            NetworkError,
        )
        
        assert is_retryable_error(RateLimitError())
        assert is_retryable_error(NetworkError())
        assert not is_retryable_error(InvalidPMIDError("x"))
        
        # Check string detection
        assert is_retryable_error(Exception("rate limit exceeded"))
        assert is_retryable_error(Exception("Too Many Requests"))
        assert not is_retryable_error(Exception("Invalid input"))
    
    def test_get_retry_delay(self):
        """get_retry_delay should use exponential backoff."""
        from pubmed_search.shared.exceptions import get_retry_delay, RateLimitError
        
        # First attempt
        delay0 = get_retry_delay(Exception("error"), 0)
        assert 1.0 <= delay0 <= 1.2  # base + jitter
        
        # Second attempt (exponential)
        delay1 = get_retry_delay(Exception("error"), 1)
        assert delay1 > delay0
        
        # With retry_after hint
        err = RateLimitError(retry_after=10.0)
        delay = get_retry_delay(err, 0)
        assert delay >= 10.0


class TestRateLimiter:
    """Tests for RateLimiter."""
    
    @pytest.mark.asyncio
    async def test_rate_limiter_basic(self):
        """RateLimiter should control request rate."""
        from pubmed_search.shared.async_utils import RateLimiter
        
        limiter = RateLimiter(rate=10.0, per=1.0)
        
        # First request should be immediate
        start = asyncio.get_event_loop().time()
        await limiter.acquire()
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed < 0.1
    
    @pytest.mark.asyncio
    async def test_rate_limiter_context_manager(self):
        """RateLimiter should work as context manager."""
        from pubmed_search.shared.async_utils import RateLimiter
        
        limiter = RateLimiter(rate=10.0)
        
        async with limiter:
            pass  # Should not raise
    
    def test_get_rate_limiter(self):
        """get_rate_limiter should return singleton per API."""
        from pubmed_search.shared.async_utils import get_rate_limiter
        
        limiter1 = get_rate_limiter("ncbi")
        limiter2 = get_rate_limiter("ncbi")
        limiter3 = get_rate_limiter("europe_pmc")
        
        assert limiter1 is limiter2
        assert limiter1 is not limiter3


class TestAsyncRetry:
    """Tests for async_retry decorator."""
    
    @pytest.mark.asyncio
    async def test_retry_success(self):
        """async_retry should return on success."""
        from pubmed_search.shared.async_utils import async_retry
        
        call_count = 0
        
        @async_retry(max_attempts=3)
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = await succeed()
        assert result == "success"
        assert call_count == 1
    
    @pytest.mark.asyncio
    async def test_retry_on_retryable_error(self):
        """async_retry should retry on retryable errors."""
        from pubmed_search.shared.async_utils import async_retry
        
        call_count = 0
        
        @async_retry(max_attempts=3)
        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("rate limit exceeded")
            return "success"
        
        result = await fail_then_succeed()
        assert result == "success"
        assert call_count == 2
    
    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable(self):
        """async_retry should not retry non-retryable errors."""
        from pubmed_search.shared.async_utils import async_retry
        
        call_count = 0
        
        @async_retry(max_attempts=3)
        async def fail_immediately():
            nonlocal call_count
            call_count += 1
            raise ValueError("Invalid input")
        
        with pytest.raises(ValueError):
            await fail_immediately()
        
        assert call_count == 1


class TestGatherWithErrors:
    """Tests for gather_with_errors."""
    
    @pytest.mark.asyncio
    async def test_gather_all_success(self):
        """gather_with_errors should collect all successes."""
        from pubmed_search.shared.async_utils import gather_with_errors
        
        async def succeed(val: int) -> int:
            return val * 2
        
        results = await gather_with_errors(
            succeed(1),
            succeed(2),
            succeed(3),
        )
        
        assert results == [2, 4, 6]
    
    @pytest.mark.asyncio
    async def test_gather_with_exceptions(self):
        """gather_with_errors should collect exceptions when requested."""
        from pubmed_search.shared.async_utils import gather_with_errors
        
        async def succeed() -> str:
            return "ok"
        
        async def fail() -> str:
            raise ValueError("bad")
        
        results = await gather_with_errors(
            succeed(),
            fail(),
            succeed(),
            return_exceptions=True,
        )
        
        assert len(results) == 3
        assert isinstance(results[1], ValueError)


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_closed(self):
        """CircuitBreaker should allow requests when closed."""
        from pubmed_search.shared.async_utils import CircuitBreaker
        
        breaker = CircuitBreaker(failure_threshold=3)
        
        async with breaker:
            pass  # Should not raise
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_on_failures(self):
        """CircuitBreaker should open after threshold failures."""
        from pubmed_search.shared.async_utils import CircuitBreaker
        from pubmed_search.shared.exceptions import RateLimitError
        
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        
        # Simulate failures
        for _ in range(2):
            try:
                async with breaker:
                    raise Exception("fail")
            except Exception:
                pass
        
        # Circuit should be open now
        with pytest.raises(RateLimitError):
            async with breaker:
                pass


class TestBatchProcess:
    """Tests for batch_process."""
    
    @pytest.mark.asyncio
    async def test_batch_process_basic(self):
        """batch_process should process items in batches."""
        from pubmed_search.shared.async_utils import batch_process
        
        processed = []
        
        async def processor(item: int) -> int:
            processed.append(item)
            return item * 2
        
        results = await batch_process(
            [1, 2, 3, 4, 5],
            processor,
            batch_size=2,
        )
        
        assert len(results) == 5
        assert all(isinstance(r, int) for r in results)


class TestErrorContext:
    """Tests for ErrorContext dataclass."""
    
    def test_error_context_slots(self):
        """ErrorContext should use slots for efficiency."""
        from pubmed_search.shared.exceptions import ErrorContext
        
        ctx = ErrorContext(tool_name="test")
        # slots means no __dict__
        assert not hasattr(ctx, "__dict__") or len(ctx.__dict__) == 0
    
    def test_error_context_frozen(self):
        """ErrorContext should be immutable."""
        from pubmed_search.shared.exceptions import ErrorContext
        
        ctx = ErrorContext(tool_name="test")
        with pytest.raises(AttributeError):
            ctx.tool_name = "changed"  # type: ignore
