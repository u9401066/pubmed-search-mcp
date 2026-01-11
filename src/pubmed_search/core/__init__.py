"""
Core module for PubMed Search MCP.

Provides:
- Unified exception hierarchy
- Async utilities for efficient API calls
- Caching utilities
- Type definitions

Python 3.12+ features:
- Type parameter syntax (PEP 695)
- ExceptionGroup support (PEP 654)
- asyncio.TaskGroup (PEP 654)
- @override decorator support
"""

from .exceptions import (
    # Base
    PubMedSearchError,
    ErrorContext,
    ErrorSeverity,
    ErrorCategory,
    # API errors
    APIError,
    RateLimitError,
    NetworkError,
    ServiceUnavailableError,
    # Validation errors
    ValidationError,
    InvalidPMIDError,
    InvalidQueryError,
    InvalidParameterError,
    # Data errors
    DataError,
    NotFoundError,
    ParseError,
    # Configuration errors
    ConfigurationError,
    # Utilities
    create_error_group,
    is_retryable_error,
    get_retry_delay,
)

from .async_utils import (
    # Rate limiting
    RateLimiter,
    get_rate_limiter,
    # Retry
    async_retry,
    # Parallel execution
    gather_with_errors,
    batch_process,
    # Fault tolerance
    CircuitBreaker,
    # Connection pooling
    AsyncConnectionPool,
    # Utilities
    timeout_with_fallback,
)

__all__ = [
    # Exceptions
    "PubMedSearchError",
    "ErrorContext",
    "ErrorSeverity",
    "ErrorCategory",
    "APIError",
    "RateLimitError",
    "NetworkError",
    "ServiceUnavailableError",
    "ValidationError",
    "InvalidPMIDError",
    "InvalidQueryError",
    "InvalidParameterError",
    "DataError",
    "NotFoundError",
    "ParseError",
    "ConfigurationError",
    "create_error_group",
    "is_retryable_error",
    "get_retry_delay",
    # Async utilities
    "RateLimiter",
    "get_rate_limiter",
    "async_retry",
    "gather_with_errors",
    "batch_process",
    "CircuitBreaker",
    "AsyncConnectionPool",
    "timeout_with_fallback",
]
