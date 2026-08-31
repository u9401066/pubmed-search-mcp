"""
Entrez Base Module - Configuration and Shared Utilities

Provides base class with Entrez configuration and common functionality.
Includes rate limiting to respect NCBI API limits.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from enum import Enum
from typing import TYPE_CHECKING, Any, NoReturn, TypeVar

from Bio import Entrez

from pubmed_search.shared.async_utils import (
    CircuitBreakerPolicy,
    RateLimitPolicy,
    RequestExecutionPolicy,
    RetryPolicy,
    get_transport_kernel,
)
from pubmed_search.shared.exceptions import APIError, ErrorContext, is_retryable_error

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

T = TypeVar("T")
_MISSING = object()
DEFAULT_ENTREZ_TOOL = "pubmed-search-mcp"
logger = logging.getLogger(__name__)


class NCBIInfrastructureError(APIError):
    """Sanitized failure raised by the NCBI infrastructure boundary.

    The public message is deliberately independent of the upstream exception
    value, which may contain a query, URL, credential, or response fragment.
    ``upstream_type`` and the chained cause remain available for diagnostics
    without turning an outage into an article-shaped compatibility row.
    """

    def __init__(
        self,
        operation: str,
        *,
        upstream_type: str,
        retryable: bool,
        retry_after: float | None = None,
        status_code: int | None = None,
        execution_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.operation = operation
        self.upstream_type = upstream_type
        self.retry_after = retry_after
        self.status_code = status_code
        self.execution_metadata = dict(execution_metadata or {})
        super().__init__(
            f"NCBI {operation} failed",
            context=ErrorContext(
                operation=operation,
                retry_after=retry_after,
                metadata={"upstream_type": upstream_type, **self.execution_metadata},
            ),
            retryable=retryable,
        )


class NCBIProviderSchemaError(NCBIInfrastructureError):
    """Typed, query-safe failure for a malformed NCBI response payload."""

    def __init__(self, operation: str) -> None:
        super().__init__(
            operation,
            upstream_type="ProviderSchemaError",
            retryable=False,
        )


def raise_ncbi_infrastructure_error(
    operation: str,
    error: Exception,
    *,
    execution_metadata: dict[str, Any] | None = None,
) -> NoReturn:
    """Raise one query-safe NCBI failure while retaining diagnostic lineage."""
    if isinstance(error, NCBIInfrastructureError):
        upstream_type = error.upstream_type
        retryable = error.retryable
        retry_after = error.retry_after
        status_code = error.status_code
        inherited_metadata = error.execution_metadata
    else:
        upstream_type = type(error).__name__
        retryable = is_retryable_error(error)
        raw_retry_after = getattr(error, "retry_after", None)
        retry_after = float(raw_retry_after) if isinstance(raw_retry_after, (int, float)) else None
        raw_status_code = getattr(error, "status_code", None)
        status_code = raw_status_code if isinstance(raw_status_code, int) else None
        inherited_metadata = {}

    merged_metadata = {**inherited_metadata, **(execution_metadata or {})}

    logger.warning("NCBI %s failed (%s)", operation, upstream_type)
    raise NCBIInfrastructureError(
        operation,
        upstream_type=upstream_type,
        retryable=retryable,
        retry_after=retry_after,
        status_code=status_code,
        execution_metadata=merged_metadata,
    ) from error


class SearchStrategy(Enum):
    """Search strategy options for literature search."""

    RECENT = "recent"
    MOST_CITED = "most_cited"
    RELEVANCE = "relevance"
    IMPACT = "impact"
    AGENT_DECIDED = "agent_decided"


_entrez_runtime_lock = threading.Lock()

_NCBI_RETRYABLE_MESSAGES = (
    "database is not supported",
    "backend failed",
    "temporarily unavailable",
    "service unavailable",
    "rate limit",
    "too many requests",
    "server error",
)


def build_ncbi_execution_policy(
    *,
    api_key: str | None = None,
    service_name: str = "ncbi-entrez",
    timeout: float = 45.0,
    total_timeout: float | None = None,
    max_attempts: int = 3,
    base_delay: float = 1.0,
) -> RequestExecutionPolicy:
    """Build the shared transport policy used by all Entrez operations."""
    rate = 10.0 if api_key else 3.0

    return RequestExecutionPolicy(
        service_name=service_name,
        timeout=timeout,
        total_timeout=total_timeout or _derive_total_timeout(timeout, max_attempts),
        retry=RetryPolicy(
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=max(base_delay * 8, 30.0),
            retryable_messages=_NCBI_RETRYABLE_MESSAGES,
        ),
        rate_limit=RateLimitPolicy(name="ncbi-entrez", rate=1.0, per=1.0 / rate),
        circuit_breaker_policy=CircuitBreakerPolicy(
            name="ncbi-entrez",
            failure_threshold=8,
            recovery_timeout=60.0,
            half_open_max_calls=2,
        ),
    )


def run_entrez_callable(
    entrez_module: Any,
    callable_obj: Any,
    *args: Any,
    email: str | None,
    api_key: str | None,
    tool: str = DEFAULT_ENTREZ_TOOL,
    **kwargs: Any,
) -> Any:
    """Execute a Bio.Entrez callable with isolated runtime configuration."""

    with _entrez_runtime_lock:
        snapshot = {
            "email": getattr(entrez_module, "email", _MISSING),
            "api_key": getattr(entrez_module, "api_key", _MISSING),
            "tool": getattr(entrez_module, "tool", _MISSING),
            "max_tries": getattr(entrez_module, "max_tries", _MISSING),
            "sleep_between_tries": getattr(entrez_module, "sleep_between_tries", _MISSING),
        }

        entrez_module.email = email
        entrez_module.api_key = api_key
        entrez_module.tool = tool
        entrez_module.max_tries = 1
        entrez_module.sleep_between_tries = 0
        try:
            return callable_obj(*args, **kwargs)
        finally:
            for attr, value in snapshot.items():
                if value is _MISSING:
                    with contextlib.suppress(AttributeError):
                        delattr(entrez_module, attr)
                    continue
                setattr(entrez_module, attr, value)


async def execute_entrez_operation(
    operation: Callable[[], Awaitable[T]],
    *,
    api_key: str | None = None,
    service_name: str = "ncbi-entrez",
    timeout: float = 45.0,
    total_timeout: float | None = None,
    max_attempts: int = 3,
    base_delay: float = 1.0,
) -> T:
    """Execute an Entrez operation through the shared transport kernel."""
    policy = build_ncbi_execution_policy(
        api_key=api_key,
        service_name=service_name,
        timeout=timeout,
        total_timeout=total_timeout,
        max_attempts=max_attempts,
        base_delay=base_delay,
    )
    return await get_transport_kernel().execute(operation, policy=policy)


class EntrezBase:
    """
    Base class for Entrez API interactions.

    Handles configuration and provides shared utilities for all Entrez operations.

    Attributes:
        email: Email address required by NCBI Entrez API.
        api_key: Optional NCBI API key for higher rate limits.
    """

    def __init__(self, email: str = "your.email@example.com", api_key: str | None = None):
        """
        Initialize Entrez configuration.

        Args:
            email: Email address required by NCBI Entrez API.
            api_key: Optional NCBI API key for higher rate limits (10/sec vs 3/sec).
        """
        # NOTE: Entrez global state (email, api_key, tool) is intentionally NOT set here.
        # run_entrez_callable() snapshot-sets-restores per call with a threading lock,
        # which is safe under concurrent asyncio tasks. Setting globals in __init__ was
        # a no-op in the face of that mechanism and created race conditions under
        # concurrent instantiation.
        self._email = email
        self._api_key = api_key
        self._tool = DEFAULT_ENTREZ_TOOL
        self._transport_kernel = get_transport_kernel()

    def _build_entrez_policy(
        self,
        *,
        service_name: str = "ncbi-entrez",
        timeout: float = 45.0,
        total_timeout: float | None = None,
        max_attempts: int = 3,
        base_delay: float = 1.0,
    ) -> RequestExecutionPolicy:
        return build_ncbi_execution_policy(
            api_key=self._api_key,
            service_name=service_name,
            timeout=timeout,
            total_timeout=total_timeout,
            max_attempts=max_attempts,
            base_delay=base_delay,
        )

    async def _execute_entrez_call(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        service_name: str = "ncbi-entrez",
        timeout: float = 45.0,
        total_timeout: float | None = None,
        max_attempts: int = 3,
        base_delay: float = 1.0,
    ) -> T:
        return await self._transport_kernel.execute(
            operation,
            policy=self._build_entrez_policy(
                service_name=service_name,
                timeout=timeout,
                total_timeout=total_timeout,
                max_attempts=max_attempts,
                base_delay=base_delay,
            ),
        )

    async def _rate_limited_call(self, func, *args, **kwargs):
        """Execute an Entrez call through the shared transport kernel."""

        async def call() -> Any:
            return await asyncio.to_thread(
                run_entrez_callable,
                Entrez,
                func,
                *args,
                email=self._email,
                api_key=self._api_key,
                tool=self._tool,
                **kwargs,
            )

        return await self._execute_entrez_call(call)

    @property
    def email(self) -> str:
        """Get configured email."""
        return self._email

    @property
    def api_key(self) -> str | None:
        """Get configured API key."""
        return self._api_key


def _derive_total_timeout(timeout: float, max_attempts: int) -> float:
    """Cap end-to-end Entrez waits so retries do not amplify into minutes."""
    if max_attempts <= 1:
        return timeout
    return max(timeout, min(timeout * 2, timeout + 30.0))
