"""
Entrez Base Module - Configuration and Shared Utilities

Provides base class with Entrez configuration and common functionality.
Includes rate limiting to respect NCBI API limits.
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import TYPE_CHECKING, Any, TypeVar

from Bio import Entrez

from pubmed_search.shared.async_utils import (
    CircuitBreakerPolicy,
    RateLimitPolicy,
    RequestExecutionPolicy,
    RetryPolicy,
    get_rate_limiter,
    get_transport_kernel,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

T = TypeVar("T")


class SearchStrategy(Enum):
    """Search strategy options for literature search."""

    RECENT = "recent"
    MOST_CITED = "most_cited"
    RELEVANCE = "relevance"
    IMPACT = "impact"
    AGENT_DECIDED = "agent_decided"


# Global rate limiter state
_last_request_time = 0.0
_min_request_interval = 0.34  # ~3 requests/second (NCBI limit without API key)
_rate_lock = asyncio.Lock()

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
    max_attempts: int = 3,
    base_delay: float = 1.0,
) -> RequestExecutionPolicy:
    """Build the shared transport policy used by all Entrez operations."""
    rate = 10.0 if api_key else 3.0

    return RequestExecutionPolicy(
        service_name=service_name,
        timeout=timeout,
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


async def execute_entrez_operation(
    operation: Callable[[], Awaitable[T]],
    *,
    api_key: str | None = None,
    service_name: str = "ncbi-entrez",
    timeout: float = 45.0,
    max_attempts: int = 3,
    base_delay: float = 1.0,
) -> T:
    """Execute an Entrez operation through the shared transport kernel."""
    policy = build_ncbi_execution_policy(
        api_key=api_key,
        service_name=service_name,
        timeout=timeout,
        max_attempts=max_attempts,
        base_delay=base_delay,
    )
    return await get_transport_kernel().execute(operation, policy=policy)


async def _rate_limit():
    """Compatibility wrapper around the shared NCBI rate limiter."""
    global _last_request_time
    async with _rate_lock:
        limiter = get_rate_limiter("ncbi-entrez", rate=1.0 / _min_request_interval, per=1.0)
        await limiter.acquire()
        _last_request_time = time.time()


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
        global _min_request_interval

        Entrez.email = email  # type: ignore[assignment]
        if api_key:
            Entrez.api_key = api_key  # type: ignore[assignment]
            _min_request_interval = 0.1  # 10 requests/second with API key
        else:
            _min_request_interval = 0.34  # ~3 requests/second without API key

        Entrez.max_tries = 1
        Entrez.sleep_between_tries = 0

        self._email = email
        self._api_key = api_key
        self._transport_kernel = get_transport_kernel()

    def _build_entrez_policy(
        self,
        *,
        service_name: str = "ncbi-entrez",
        timeout: float = 45.0,
        max_attempts: int = 3,
        base_delay: float = 1.0,
    ) -> RequestExecutionPolicy:
        return build_ncbi_execution_policy(
            api_key=self._api_key,
            service_name=service_name,
            timeout=timeout,
            max_attempts=max_attempts,
            base_delay=base_delay,
        )

    async def _execute_entrez_call(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        service_name: str = "ncbi-entrez",
        timeout: float = 45.0,
        max_attempts: int = 3,
        base_delay: float = 1.0,
    ) -> T:
        return await self._transport_kernel.execute(
            operation,
            policy=self._build_entrez_policy(
                service_name=service_name,
                timeout=timeout,
                max_attempts=max_attempts,
                base_delay=base_delay,
            ),
        )

    async def _rate_limited_call(self, func, *args, **kwargs):
        """Execute an Entrez call through the shared transport kernel."""

        async def call() -> Any:
            return await asyncio.to_thread(func, *args, **kwargs)

        return await self._execute_entrez_call(call)

    @property
    def email(self) -> str:
        """Get configured email."""
        return self._email

    @property
    def api_key(self) -> str | None:
        """Get configured API key."""
        return self._api_key
