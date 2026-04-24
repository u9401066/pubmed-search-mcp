"""
Entrez Base Module - Configuration and Shared Utilities

Provides base class with Entrez configuration and common functionality.
Includes rate limiting to respect NCBI API limits.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
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
_MISSING = object()
DEFAULT_ENTREZ_TOOL = "pubmed-search-mcp"


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
