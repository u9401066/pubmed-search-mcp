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
from typing import Any

import httpx
from typing_extensions import Self

from pubmed_search.shared.async_utils import CircuitBreaker

logger = logging.getLogger(__name__)


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
        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            headers=headers or {},
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30.0,
            ),
        )
        self._circuit_breaker = circuit_breaker or CircuitBreaker(failure_threshold=10, recovery_timeout=60.0)

    async def _rate_limit(self) -> None:
        """Enforce minimum interval between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
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

        for attempt in range(self._MAX_RETRIES + 1):
            await self._rate_limit()
            try:
                async with self._circuit_breaker:
                    response = await self._execute_request(full_url, method=method, data=data, headers=headers)

                    # Handle expected error codes (e.g., 404 = not found)
                    expected = self._handle_expected_status(response, full_url)
                    if expected is not _CONTINUE:
                        return expected

                    # Handle 429 rate limiting
                    if response.status_code == 429:
                        if attempt < self._MAX_RETRIES:
                            retry_after = self._get_retry_after(response, attempt)
                            logger.warning(
                                f"{self._service_name}: Rate limited (429), "
                                f"retry {attempt + 1}/{self._MAX_RETRIES} in {retry_after:.1f}s"
                            )
                            await asyncio.sleep(retry_after)
                            continue
                        logger.warning(f"{self._service_name}: Rate limit exceeded after retries")
                        return None

                    response.raise_for_status()
                    return self._parse_response(response, expect_json)

            except httpx.HTTPStatusError as e:
                logger.exception(
                    f"{self._service_name} HTTP error {e.response.status_code}: {e.response.reason_phrase}"
                )
                return None
            except httpx.RequestError as e:
                if attempt < self._MAX_RETRIES:
                    logger.warning(f"{self._service_name} request error (attempt {attempt + 1}): {e}")
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                logger.exception(f"{self._service_name} request failed: {e}")
                return None
            except Exception as e:
                # RateLimitError from circuit breaker should propagate
                from pubmed_search.shared.exceptions import RateLimitError

                if isinstance(e, RateLimitError):
                    logger.warning(f"{self._service_name}: Circuit breaker open, skipping request")
                    return None
                logger.exception(f"{self._service_name} request failed: {e}")
                return None

        return None

    async def _execute_request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Execute the actual HTTP request. Override for custom behavior."""
        if method == "POST" and data:
            return await self._client.post(url, json=data, headers=headers or {})
        return await self._client.get(url, headers=headers or {})

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
        try:
            return float(response.headers.get("Retry-After", 2 ** (attempt + 1)))
        except (ValueError, TypeError):
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
