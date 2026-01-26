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

from .async_utils import (
    # Connection pooling
    AsyncConnectionPool,
    # Fault tolerance
    CircuitBreaker,
    # Rate limiting
    RateLimiter,
    # Retry
    async_retry,
    batch_process,
    # Parallel execution
    gather_with_errors,
    get_rate_limiter,
    # Utilities
    timeout_with_fallback,
)
from .exceptions import (
    # API errors
    APIError,
    # Configuration errors
    ConfigurationError,
    # Data errors
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
    # Base
    PubMedSearchError,
    RateLimitError,
    ServiceUnavailableError,
    # Validation errors
    ValidationError,
    # Utilities
    create_error_group,
    get_retry_delay,
    is_retryable_error,
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
