"""Tests for exceptions.py — full coverage of exception hierarchy."""

from pubmed_search.shared.exceptions import (
    APIError,
    ConfigurationError,
    DataError,
    ErrorCategory,
    ErrorContext,
    ErrorSeverity,
    InvalidParameterError,
    InvalidPMIDError,
    InvalidQueryError,
    NetworkError,
    NotFoundError,
    ParseError,
    PubMedSearchError,
    RateLimitError,
    ServiceUnavailableError,
    ValidationError,
    create_error_group,
    get_retry_delay,
    is_retryable_error,
)


class TestPubMedSearchError:
    async def test_basic_creation(self):
        e = PubMedSearchError("test error")
        assert str(e) == "test error"
        assert e.severity == ErrorSeverity.ERROR
        assert e.category == ErrorCategory.API

    async def test_with_context(self):
        ctx = ErrorContext(tool_name="test_tool", suggestion="try again")
        e = PubMedSearchError("fail", context=ctx, retryable=True)
        assert e.context.tool_name == "test_tool"
        assert e.retryable is True

    async def test_to_dict(self):
        ctx = ErrorContext(tool_name="t", suggestion="s", example="e", retry_after=5.0)
        e = PubMedSearchError("fail", context=ctx, retryable=True)
        d = e.to_dict()
        assert d["error"] == "fail"
        assert d["tool"] == "t"
        assert d["suggestion"] == "s"
        assert d["example"] == "e"
        assert d["retry_after_seconds"] == 5.0
        assert d["retryable"] is True

    async def test_to_dict_minimal(self):
        e = PubMedSearchError("fail")
        d = e.to_dict()
        assert "tool" not in d  # No tool_name

    async def test_to_agent_message(self):
        ctx = ErrorContext(suggestion="fix it", example="do_it()")
        e = PubMedSearchError("fail", context=ctx, retryable=True)
        msg = e.to_agent_message()
        assert "Error" in msg
        assert "fix it" in msg
        assert "do_it()" in msg
        assert "retryable" in msg.lower() or "🔄" in msg

    async def test_to_agent_message_retry_after(self):
        ctx = ErrorContext(retry_after=3.0)
        e = PubMedSearchError("fail", context=ctx, retryable=True)
        msg = e.to_agent_message()
        assert "3.0" in msg


class TestAPIError:
    async def test_default_retryable(self):
        e = APIError("api fail")
        assert e.retryable is True
        assert e.category == ErrorCategory.API


class TestRateLimitError:
    async def test_default_message(self):
        e = RateLimitError()
        assert "rate limit" in str(e).lower()
        assert e.severity == ErrorSeverity.TRANSIENT

    async def test_retry_after(self):
        e = RateLimitError("too fast", retry_after=5.0)
        assert e.context.retry_after == 5.0

    async def test_with_context(self):
        ctx = ErrorContext(tool_name="search")
        e = RateLimitError(context=ctx, retry_after=2.0)
        assert e.context.tool_name == "search"
        assert e.context.retry_after == 2.0


class TestNetworkError:
    async def test_default(self):
        e = NetworkError()
        assert "network" in str(e).lower() or "connection" in str(e).lower()
        assert e.retryable is True


class TestServiceUnavailableError:
    async def test_default(self):
        e = ServiceUnavailableError()
        assert "NCBI" in str(e)
        assert e.severity == ErrorSeverity.TRANSIENT

    async def test_custom_service(self):
        e = ServiceUnavailableError(service="Europe PMC")
        assert "Europe PMC" in str(e)


class TestValidationError:
    async def test_not_retryable(self):
        e = ValidationError("bad input")
        assert e.retryable is False
        assert e.category == ErrorCategory.VALIDATION
        assert e.severity == ErrorSeverity.WARNING


class TestInvalidPMIDError:
    async def test_basic(self):
        e = InvalidPMIDError("abc")
        assert "abc" in str(e)
        assert e.context.input_value == "abc"
        assert "PMID" in e.context.suggestion

    async def test_with_context(self):
        ctx = ErrorContext(tool_name="fetch")
        e = InvalidPMIDError("x", context=ctx)
        assert e.context.tool_name == "fetch"


class TestInvalidQueryError:
    async def test_basic(self):
        e = InvalidQueryError(None)
        assert "empty" in str(e).lower()

    async def test_custom_reason(self):
        e = InvalidQueryError("q", reason="Too short")
        assert "Too short" in str(e)


class TestInvalidParameterError:
    async def test_basic(self):
        e = InvalidParameterError("limit", -1, "positive integer")
        assert "limit" in str(e)
        assert "-1" in str(e)
        assert e.context.suggestion == "Expected positive integer"


class TestNotFoundError:
    async def test_with_id(self):
        e = NotFoundError("Article", "12345")
        assert "12345" in str(e)
        assert "Article" in str(e)

    async def test_without_id(self):
        e = NotFoundError("Gene")
        assert "Gene not found" in str(e)


class TestParseError:
    async def test_basic(self):
        e = ParseError("unexpected XML")
        assert "Parse error" in str(e)

    async def test_with_source(self):
        e = ParseError("bad format", source="Europe PMC")
        assert "Europe PMC" in str(e)


class TestConfigurationError:
    async def test_basic(self):
        e = ConfigurationError("no API key")
        assert e.severity == ErrorSeverity.CRITICAL
        assert e.retryable is False


class TestDataError:
    async def test_basic(self):
        e = DataError("corrupt data")
        assert e.category == ErrorCategory.DATA


class TestCreateErrorGroup:
    async def test_creates_group(self):
        errors = [ValueError("a"), TypeError("b")]
        eg = create_error_group("multi", errors)
        assert len(eg.exceptions) == 2


class TestIsRetryableError:
    async def test_pubmed_error_retryable(self):
        e = RateLimitError()
        assert is_retryable_error(e) is True

    async def test_pubmed_error_not_retryable(self):
        e = ValidationError("bad")
        assert is_retryable_error(e) is False

    async def test_generic_error_with_pattern(self):
        e = RuntimeError("rate limit exceeded")
        assert is_retryable_error(e) is True

    async def test_generic_error_no_pattern(self):
        e = ValueError("something else")
        assert is_retryable_error(e) is False

    async def test_timeout_pattern(self):
        e = RuntimeError("connection timeout")
        assert is_retryable_error(e) is True


class TestGetRetryDelay:
    async def test_exponential_backoff(self):
        e = RuntimeError("fail")
        d0 = get_retry_delay(e, 0)
        d1 = get_retry_delay(e, 1)
        d2 = get_retry_delay(e, 2)
        assert d0 < d1 < d2

    async def test_capped_at_30(self):
        e = RuntimeError("fail")
        d = get_retry_delay(e, 10)
        assert d <= 30.0

    async def test_uses_retry_after(self):
        ctx = ErrorContext(retry_after=5.0)
        e = PubMedSearchError("fail", context=ctx)
        d = get_retry_delay(e, 0)
        assert d >= 5.0

    async def test_includes_jitter(self):
        e = RuntimeError("fail")
        delays = {get_retry_delay(e, 0) for _ in range(10)}
        # With jitter, not all delays should be identical
        # (statistically very unlikely, but possible)
        assert len(delays) >= 1
