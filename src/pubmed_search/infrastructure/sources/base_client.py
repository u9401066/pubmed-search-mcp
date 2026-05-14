"""
Base API Client - Common HTTP request pattern with retry, rate limiting, and circuit breaker.

Eliminates duplicated _make_request() across 8 source clients by providing
a reusable base class with:
- Automatic retry on 429 (rate limit) with Retry-After support
- Rate limiting (configurable interval between requests)
- Circuit breaker for fault tolerance
- Consistent error handling and logging
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextvars import ContextVar
from typing import Any

import httpx
from typing_extensions import Self

from pubmed_search.shared.async_utils import (
    CircuitBreaker,
    RequestExecutionPolicy,
    RetryableOperationError,
    create_async_http_client,
    get_rate_limiter,
    get_transport_kernel,
    parse_retry_after,
)
from pubmed_search.shared.source_contracts import SourceExecutionSettings, build_request_execution_policy

logger = logging.getLogger(__name__)

_ASYNCIO_COMPAT = asyncio
_FALLBACK_RATE_LIMIT_COOLDOWN_SECONDS = 30.0


class BaseAPIClient:
    """
    Base class for external API clients.

    Provides common infrastructure:
    - httpx.AsyncClient management
    - Rate limiting with configurable interval
    - Retry on 429 with exponential backoff
    - Circuit breaker for fault tolerance
    - Consistent error handling

    Subclasses should set `_service_name` and can override:
    - `_prepare_request()`: Add service-specific headers/params
    - `_handle_response()`: Custom response processing
    - `_is_expected_error()`: Handle service-specific status codes (e.g., 404)

    Example:
        class MyClient(BaseAPIClient):
            _service_name = "MyAPI"

            def __init__(self):
                super().__init__(base_url="https://api.example.com", min_interval=0.1)

            async def get_item(self, item_id: str) -> dict | None:
                return await self._make_request(f"/items/{item_id}")
    """

    _service_name: str = "API"
    _MAX_RETRIES: int = 3

    def __init__(
        self,
        base_url: str = "",
        timeout: float = 30.0,
        min_interval: float = 0.1,
        headers: dict[str, str] | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        """
        Initialize base client.

        Args:
            base_url: Base URL for the API (optional, can pass full URLs)
            timeout: Request timeout in seconds
            min_interval: Minimum seconds between requests (rate limiting)
            headers: Default headers for all requests
            circuit_breaker: Optional circuit breaker for fault tolerance.
                             If None, a default one is created (threshold=10, recovery=60s).
        """
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._min_interval = min_interval
        self._last_request_time = 0.0
        self._rate_limiter_name = f"source:{self._service_name.lower()}:{id(self)}"
        self._client = create_async_http_client(
            timeout=self._timeout,
            headers=headers or {},
            follow_redirects=True,
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=30.0,
        )
        self._circuit_breaker = circuit_breaker or CircuitBreaker(failure_threshold=10, recovery_timeout=60.0)
        self._transport_kernel = get_transport_kernel()
        self._last_retryable_error: ContextVar[RetryableOperationError | None] = ContextVar(
            f"{self._service_name.lower().replace(' ', '_')}_last_retryable_error_{id(self)}",
            default=None,
        )

    @property
    def last_retryable_error(self) -> RetryableOperationError | None:
        """Return the most recent exhausted retryable error, if any."""
        return self._last_retryable_error.get()

    def _build_execution_policy(self) -> RequestExecutionPolicy:
        return build_request_execution_policy(
            SourceExecutionSettings(
                service_name=self._service_name,
                timeout=self._timeout,
                min_interval=self._min_interval,
                max_attempts=self._MAX_RETRIES + 1,
                rate_limit_name=self._rate_limiter_name,
                circuit_breaker=self._circuit_breaker,
            )
        )

    async def _rate_limit(self) -> None:
        """Compatibility wrapper around the shared rate limiter."""
        if self._min_interval <= 0:
            self._last_request_time = time.time()
            return

        limiter = get_rate_limiter(self._rate_limiter_name, rate=1.0, per=self._min_interval)
        await limiter.acquire()
        self._last_request_time = time.time()

    def _build_url(self, url: str) -> str:
        """Build full URL from path or full URL."""
        if url.startswith(("http://", "https://")):
            return url
        return f"{self._base_url}{url}"

    async def _make_request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        expect_json: bool = True,
    ) -> dict[str, Any] | str | None:
        """
        Make HTTP request with retry on 429 and circuit breaker protection.

        Args:
            url: Full URL or path (appended to base_url)
            method: HTTP method (GET or POST)
            data: JSON body for POST requests
            headers: Additional headers for this request
            expect_json: If True, parse response as JSON; otherwise return text

        Returns:
            Parsed JSON dict, response text, or None on error
        """
        full_url = self._build_url(url)

        policy = self._build_execution_policy()

        async def perform_request() -> dict[str, Any] | str | None:
            response = await self._execute_request(
                full_url,
                method=method,
                data=data,
                params=params,
                headers=headers,
            )

            expected = self._handle_expected_status(response, full_url)
            if expected is not _CONTINUE:
                return expected

            if response.status_code in policy.retry.retryable_status_codes:
                retry_after = parse_retry_after(response.headers.get("Retry-After"))
                raise RetryableOperationError(
                    f"HTTP {response.status_code}",
                    retry_after=retry_after,
                    status_code=response.status_code,
                )

            response.raise_for_status()
            return self._parse_response(response, expect_json)

        try:
            self._last_retryable_error.set(None)
            return await self._transport_kernel.execute(perform_request, policy=policy)
        except RetryableOperationError as e:
            self._last_retryable_error.set(e)
            await self._handle_exhausted_retryable_error(e, policy)
            return None
        except httpx.HTTPStatusError as e:
            logger.exception(f"{self._service_name} HTTP error {e.response.status_code}: {e.response.reason_phrase}")
            return None
        except httpx.RequestError as e:
            logger.exception(f"{self._service_name} request failed: {e}")
            return None
        except Exception as e:
            from pubmed_search.shared.exceptions import RateLimitError

            if isinstance(e, RateLimitError):
                retryable_error = RetryableOperationError(
                    str(e) or f"{self._service_name} rate limited",
                    retry_after=getattr(getattr(e, "context", None), "retry_after", None),
                )
                self._last_retryable_error.set(retryable_error)
                logger.warning("%s: Circuit breaker open or rate limited, skipping request", self._service_name)
                return None
            logger.exception(f"{self._service_name} request failed: {e}")
            return None

    async def _handle_exhausted_retryable_error(
        self,
        error: RetryableOperationError,
        policy: RequestExecutionPolicy,
    ) -> None:
        """Handle an exhausted retryable response without noisy tracebacks."""
        if error.status_code == 429:
            cooldown = error.retry_after or _FALLBACK_RATE_LIMIT_COOLDOWN_SECONDS
            await self._apply_rate_limit_cooldown(policy, cooldown)
            logger.warning(
                "%s rate limited by upstream API after retries; returning empty response and cooling down for %.0fs",
                self._service_name,
                min(cooldown, policy.retry.retry_after_cap),
            )
            return

        logger.warning(
            "%s transient request failed after retries: %s",
            self._service_name,
            error,
        )

    @staticmethod
    async def _apply_rate_limit_cooldown(policy: RequestExecutionPolicy, cooldown: float) -> None:
        """Apply a bounded cooldown to the shared limiter after exhausted 429s."""
        if cooldown <= 0 or policy.rate_limit is None:
            return

        limiter = get_rate_limiter(
            policy.rate_limit.name,
            rate=policy.rate_limit.rate,
            per=policy.rate_limit.per,
        )
        await limiter.apply_cooldown(min(cooldown, policy.retry.retry_after_cap))

    async def _execute_request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Execute the actual HTTP request. Override for custom behavior."""
        if method == "POST" and data:
            return await self._client.post(url, json=data, params=params, headers=headers or {})
        return await self._client.get(url, params=params, headers=headers or {})

    def _handle_expected_status(self, response: httpx.Response, url: str) -> dict[str, Any] | str | None:
        """
        Handle expected non-200 status codes that shouldn't trigger retry.

        Override in subclasses for service-specific behavior.
        Return a value to short-circuit (e.g., None for 404).
        Return the sentinel _CONTINUE to continue normal processing.

        Default: no special handling.
        """
        return _CONTINUE  # type: ignore[return-value]

    def _parse_response(self, response: httpx.Response, expect_json: bool) -> dict[str, Any] | str:
        """Parse response body. Override for custom extraction logic."""
        if expect_json:
            return response.json()
        return response.text

    @staticmethod
    def _get_retry_after(response: httpx.Response, attempt: int) -> float:
        """Extract Retry-After from response headers, with exponential backoff fallback."""
        retry_after = parse_retry_after(response.headers.get("Retry-After"))
        if retry_after is not None:
            return retry_after
        return float(2 ** (attempt + 1))

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


# Sentinel object to indicate "continue normal processing" from _handle_expected_status
_CONTINUE = object()
