"""
Unified Exception Hierarchy for PubMed Search MCP.

Python 3.12+ features used:
- ExceptionGroup for multi-error handling
- Modern type annotations
- @override decorator compatibility

Exception Hierarchy:
    PubMedSearchError (base)
    ├── APIError
    │   ├── RateLimitError
    │   ├── NetworkError
    │   └── ServiceUnavailableError
    ├── ValidationError
    │   ├── InvalidPMIDError
    │   ├── InvalidQueryError
    │   └── InvalidParameterError
    ├── DataError
    │   ├── NotFoundError
    │   └── ParseError
    └── ConfigurationError
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from enum import Enum, auto


class ErrorSeverity(Enum):
    """Severity levels for errors."""
    WARNING = auto()      # Recoverable, can continue
    ERROR = auto()        # Failed but can retry
    CRITICAL = auto()     # Cannot continue
    TRANSIENT = auto()    # Temporary, should retry automatically


class ErrorCategory(Enum):
    """Categories for error classification."""
    API = "api"
    VALIDATION = "validation"
    DATA = "data"
    CONFIGURATION = "config"
    NETWORK = "network"


@dataclass(frozen=True, slots=True)
class ErrorContext:
    """
    Rich context for error messages.
    
    Uses Python 3.10+ slots for memory efficiency.
    """
    tool_name: str | None = None
    operation: str | None = None
    input_value: Any = None
    suggestion: str | None = None
    example: str | None = None
    retry_after: float | None = None
    related_errors: tuple[Exception, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)


class PubMedSearchError(Exception):
    """
    Base exception for all PubMed Search errors.
    
    Provides:
    - Structured error context
    - Severity classification
    - Retry guidance
    - Agent-friendly formatting
    """
    
    __slots__ = ('context', 'severity', 'category', 'retryable')
    
    def __init__(
        self,
        message: str,
        *,
        context: ErrorContext | None = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        category: ErrorCategory = ErrorCategory.API,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.context = context or ErrorContext()
        self.severity = severity
        self.category = category
        self.retryable = retryable
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "error": str(self),
            "category": self.category.value,
            "severity": self.severity.name.lower(),
            "retryable": self.retryable,
        }
        if self.context.tool_name:
            result["tool"] = self.context.tool_name
        if self.context.suggestion:
            result["suggestion"] = self.context.suggestion
        if self.context.example:
            result["example"] = self.context.example
        if self.context.retry_after:
            result["retry_after_seconds"] = self.context.retry_after
        return result
    
    def to_agent_message(self) -> str:
        """Format for Agent consumption (Markdown)."""
        parts = [f"❌ **Error**: {self}"]
        
        if self.context.suggestion:
            parts.append(f"💡 **Suggestion**: {self.context.suggestion}")
        if self.context.example:
            parts.append(f"📝 **Example**: `{self.context.example}`")
        if self.retryable:
            if self.context.retry_after:
                parts.append(f"🔄 Retry after {self.context.retry_after:.1f} seconds")
            else:
                parts.append("🔄 This error is retryable")
        
        return "\n".join(parts)


# =============================================================================
# API Errors
# =============================================================================

class APIError(PubMedSearchError):
    """Base class for API-related errors."""
    
    def __init__(
        self,
        message: str,
        *,
        context: ErrorContext | None = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(
            message,
            context=context,
            severity=ErrorSeverity.ERROR,
            category=ErrorCategory.API,
            retryable=retryable,
        )


class RateLimitError(APIError):
    """Raised when API rate limit is exceeded."""
    
    def __init__(
        self,
        message: str = "API rate limit exceeded",
        *,
        retry_after: float = 1.0,
        context: ErrorContext | None = None,
    ) -> None:
        ctx = context or ErrorContext()
        # Merge retry_after into context
        ctx = ErrorContext(
            tool_name=ctx.tool_name,
            operation=ctx.operation,
            input_value=ctx.input_value,
            suggestion=ctx.suggestion or "Wait and retry the request",
            example=ctx.example,
            retry_after=retry_after,
            related_errors=ctx.related_errors,
            metadata=ctx.metadata,
        )
        super().__init__(message, context=ctx, retryable=True)
        self.severity = ErrorSeverity.TRANSIENT


class NetworkError(APIError):
    """Raised for network connectivity issues."""
    
    def __init__(
        self,
        message: str = "Network connection failed",
        *,
        context: ErrorContext | None = None,
    ) -> None:
        super().__init__(message, context=context, retryable=True)


class ServiceUnavailableError(APIError):
    """Raised when the external service is temporarily unavailable."""
    
    def __init__(
        self,
        message: str = "Service temporarily unavailable",
        *,
        service: str = "NCBI",
        context: ErrorContext | None = None,
    ) -> None:
        super().__init__(f"{service}: {message}", context=context, retryable=True)
        self.severity = ErrorSeverity.TRANSIENT


# =============================================================================
# Validation Errors
# =============================================================================

class ValidationError(PubMedSearchError):
    """Base class for validation errors."""
    
    def __init__(
        self,
        message: str,
        *,
        context: ErrorContext | None = None,
    ) -> None:
        super().__init__(
            message,
            context=context,
            severity=ErrorSeverity.WARNING,
            category=ErrorCategory.VALIDATION,
            retryable=False,
        )


class InvalidPMIDError(ValidationError):
    """Raised when PMID format is invalid."""
    
    def __init__(
        self,
        pmid: Any,
        *,
        context: ErrorContext | None = None,
    ) -> None:
        ctx = context or ErrorContext()
        ctx = ErrorContext(
            tool_name=ctx.tool_name,
            operation=ctx.operation,
            input_value=pmid,
            suggestion="PMID should be a numeric string (e.g., '12345678')",
            example='fetch_article_details(pmids="12345678")',
            retry_after=ctx.retry_after,
            related_errors=ctx.related_errors,
            metadata=ctx.metadata,
        )
        super().__init__(f"Invalid PMID format: {pmid!r}", context=ctx)


class InvalidQueryError(ValidationError):
    """Raised when search query is invalid."""
    
    def __init__(
        self,
        query: str | None,
        reason: str = "Query cannot be empty",
        *,
        context: ErrorContext | None = None,
    ) -> None:
        ctx = context or ErrorContext()
        ctx = ErrorContext(
            tool_name=ctx.tool_name,
            operation=ctx.operation,
            input_value=query,
            suggestion=ctx.suggestion or "Provide a valid search query",
            example=ctx.example or 'unified_search(query="diabetes treatment")',
            retry_after=ctx.retry_after,
            related_errors=ctx.related_errors,
            metadata=ctx.metadata,
        )
        super().__init__(f"Invalid query: {reason}", context=ctx)


class InvalidParameterError(ValidationError):
    """Raised when a parameter value is invalid."""
    
    def __init__(
        self,
        param_name: str,
        value: Any,
        expected: str,
        *,
        context: ErrorContext | None = None,
    ) -> None:
        ctx = context or ErrorContext()
        ctx = ErrorContext(
            tool_name=ctx.tool_name,
            operation=ctx.operation,
            input_value=value,
            suggestion=f"Expected {expected}",
            example=ctx.example,
            retry_after=ctx.retry_after,
            related_errors=ctx.related_errors,
            metadata=ctx.metadata,
        )
        super().__init__(
            f"Invalid parameter '{param_name}': {value!r} (expected {expected})",
            context=ctx
        )


# =============================================================================
# Data Errors
# =============================================================================

class DataError(PubMedSearchError):
    """Base class for data-related errors."""
    
    def __init__(
        self,
        message: str,
        *,
        context: ErrorContext | None = None,
    ) -> None:
        super().__init__(
            message,
            context=context,
            severity=ErrorSeverity.ERROR,
            category=ErrorCategory.DATA,
            retryable=False,
        )


class NotFoundError(DataError):
    """Raised when requested data is not found."""
    
    def __init__(
        self,
        resource: str,
        identifier: str | None = None,
        *,
        context: ErrorContext | None = None,
    ) -> None:
        msg = f"{resource} not found"
        if identifier:
            msg = f"{resource} not found: {identifier}"
        
        ctx = context or ErrorContext()
        ctx = ErrorContext(
            tool_name=ctx.tool_name,
            operation=ctx.operation,
            input_value=identifier,
            suggestion=ctx.suggestion or "Check the identifier and try again",
            example=ctx.example,
            retry_after=ctx.retry_after,
            related_errors=ctx.related_errors,
            metadata=ctx.metadata,
        )
        super().__init__(msg, context=ctx)


class ParseError(DataError):
    """Raised when data parsing fails."""
    
    def __init__(
        self,
        message: str,
        *,
        source: str | None = None,
        context: ErrorContext | None = None,
    ) -> None:
        full_msg = f"Parse error: {message}"
        if source:
            full_msg = f"Parse error ({source}): {message}"
        super().__init__(full_msg, context=context)


# =============================================================================
# Configuration Errors
# =============================================================================

class ConfigurationError(PubMedSearchError):
    """Raised for configuration-related errors."""
    
    def __init__(
        self,
        message: str,
        *,
        context: ErrorContext | None = None,
    ) -> None:
        super().__init__(
            message,
            context=context,
            severity=ErrorSeverity.CRITICAL,
            category=ErrorCategory.CONFIGURATION,
            retryable=False,
        )


# =============================================================================
# Multi-Error Handling (Python 3.11+ ExceptionGroup)
# =============================================================================

def create_error_group(
    message: str,
    errors: list[Exception],
) -> ExceptionGroup[Exception]:
    """
    Create an ExceptionGroup from multiple errors.
    
    Python 3.11+ feature for handling multiple concurrent errors.
    
    Example:
        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(fetch_from_source_a())
                tg.create_task(fetch_from_source_b())
        except* APIError as eg:
            # Handle all API errors
            for exc in eg.exceptions:
                log_error(exc)
    """
    return ExceptionGroup(message, errors)


def is_retryable_error(error: Exception) -> bool:
    """Check if an error should be retried."""
    if isinstance(error, PubMedSearchError):
        return error.retryable
    
    # Check for common transient error messages
    error_str = str(error).lower()
    transient_patterns = [
        "rate limit",
        "too many requests",
        "temporarily unavailable",
        "service unavailable",
        "backend failed",
        "connection reset",
        "timeout",
        "database is not supported",  # NCBI transient
    ]
    return any(pattern in error_str for pattern in transient_patterns)


def get_retry_delay(error: Exception, attempt: int) -> float:
    """
    Calculate retry delay with exponential backoff.
    
    Args:
        error: The exception that occurred
        attempt: Current attempt number (0-based)
    
    Returns:
        Delay in seconds before next retry
    """
    base_delay = 1.0
    
    # Check for specific retry-after in error
    if isinstance(error, PubMedSearchError) and error.context.retry_after:
        base_delay = error.context.retry_after
    
    # Exponential backoff with jitter
    import random
    delay = base_delay * (2 ** attempt)
    jitter = random.uniform(0, 0.1 * delay)
    
    # Cap at 30 seconds
    return min(delay + jitter, 30.0)
