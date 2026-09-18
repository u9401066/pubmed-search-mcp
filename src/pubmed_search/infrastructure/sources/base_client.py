"""
Base API Client - Common HTTP request pattern with retry, rate limiting, and circuit breaker.

Eliminates duplicated _make_request() across 8 source clients by providing
a reusable base class with:
- Automatic retry on 429 (rate limit) with Retry-After support
- Rate limiting (configurable interval between requests)
- Circuit breaker for fault tolerance
- Bounded streaming across redirect chains
- Consistent error handling and logging
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any, NoReturn

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

_FALLBACK_RATE_LIMIT_COOLDOWN_SECONDS = 30.0
MAX_API_RESPONSE_BYTES = 16 * 1024 * 1024
_RESPONSE_STREAM_CHUNK_BYTES = 64 * 1024
_MAX_REDIRECTS = 20


class APIRequestError(RuntimeError):
    """Sanitized upstream failure without URL, body, query, or credentials."""

    def __init__(self, service_name: str, *, status_code: int | None = None) -> None:
        suffix = f" with HTTP {status_code}" if status_code is not None else ""
        super().__init__(f"{service_name} request failed{suffix}")
        self.service_name = service_name
        self.status_code = status_code


class ProviderSchemaError(APIRequestError):
    """Typed, sanitized failure for an invalid upstream response payload."""


class APIResponseTooLargeError(APIRequestError):
    """Sanitized failure for an upstream response that exceeds the byte cap."""

    def __init__(self, service_name: str, *, max_bytes: int) -> None:
        super().__init__(service_name)
        self.max_bytes = max_bytes
        self.args = (f"{service_name} response exceeded the {max_bytes}-byte limit",)


def raise_provider_schema_error(service_name: str) -> NoReturn:
    """Raise a sanitized error when an upstream payload violates its schema."""

    raise ProviderSchemaError(service_name) from None


def raise_sanitized_retryable_error(service_name: str, error: RetryableOperationError) -> NoReturn:
    """Preserve retry metadata without exposing an upstream exception message."""

    raise RetryableOperationError(
        f"{service_name} request failed",
        retry_after=error.retry_after,
        status_code=error.status_code,
    ) from None


class BaseAPIClient:
    """
    Base class for external API clients.

    Provides common infrastructure:
    - httpx.AsyncClient management
    - Rate limiting with configurable interval
    - Retry on 429 with exponential backoff
    - Circuit breaker for fault tolerance
    - Content-Length preflight and a decoded-response byte cap
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
        concurrency_limit: int | None = None,
        concurrency_name: str | None = None,
        follow_redirects: bool = True,
        max_response_bytes: int = MAX_API_RESPONSE_BYTES,
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
            concurrency_limit: Shared in-flight operation limit for this service.
                               None uses two slots; explicit source limits are preserved.
            follow_redirects: Whether the transport may follow HTTP redirects.
            max_response_bytes: Per-request byte budget across the complete
                                redirect chain. Values may lower, but never
                                exceed, the process-wide hard cap.
        """
        if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int):
            raise TypeError("max_response_bytes must be an integer")
        if not 1 <= max_response_bytes <= MAX_API_RESPONSE_BYTES:
            raise ValueError(f"max_response_bytes must be between 1 and {MAX_API_RESPONSE_BYTES}")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._min_interval = min_interval
        self._concurrency_limit = concurrency_limit if concurrency_limit is not None else 2
        self._follow_redirects = follow_redirects
        self._max_response_bytes = max_response_bytes
        # Keyed by upstream service, never by object identity: every client for
        # the same API must draw from one shared budget, otherwise a parallel
        # fan-out multiplies our real request rate by the number of instances.
        self._rate_limiter_name = f"source:{self._service_name.lower()}"
        self._concurrency_name = concurrency_name or self._rate_limiter_name
        self._client = create_async_http_client(
            timeout=self._timeout,
            headers=headers or {},
            follow_redirects=follow_redirects,
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=30.0,
        )
        # Fault tolerance stays per instance: an open breaker must not stop
        # unrelated callers, and the shared rate limiter above is what keeps us
        # inside the upstream budget.
        self._circuit_breaker = circuit_breaker or CircuitBreaker(failure_threshold=10, recovery_timeout=60.0)
        self._transport_kernel = get_transport_kernel()
        self._last_rate_limit_headers: ContextVar[dict[str, str] | None] = ContextVar(
            f"{self._service_name.lower().replace(' ', '_')}_last_rate_headers_{id(self)}",
            default=None,
        )

    @property
    def last_rate_limit_headers(self) -> dict[str, str]:
        """Return task-local, allowlisted upstream budget headers."""

        return dict(self._last_rate_limit_headers.get() or {})

    def _build_execution_policy(self) -> RequestExecutionPolicy:
        return build_request_execution_policy(
            SourceExecutionSettings(
                service_name=self._service_name,
                timeout=self._timeout,
                min_interval=self._min_interval,
                max_attempts=self._MAX_RETRIES + 1,
                rate_limit_name=self._rate_limiter_name,
                circuit_breaker=self._circuit_breaker,
                concurrency_limit=self._concurrency_limit,
                concurrency_name=self._concurrency_name,
            )
        )

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
            Parsed JSON, response text, or ``None`` only when a subclass
            explicitly classifies a provider status as an expected absence.
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
            self._last_rate_limit_headers.set(
                {
                    key.lower(): value
                    for key, value in response.headers.items()
                    if key.lower() == "retry-after"
                    or key.lower().startswith("x-ratelimit-")
                    or key.lower().startswith("ratelimit-")
                }
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
            self._last_rate_limit_headers.set(None)
            return await self._transport_kernel.execute(perform_request, policy=policy)
        except RetryableOperationError as e:
            await self._handle_exhausted_retryable_error(e, policy)
            raise_sanitized_retryable_error(self._service_name, e)
        except httpx.HTTPStatusError as e:
            logger.warning(
                "%s HTTP error %s",
                self._service_name,
                e.response.status_code,
            )
            raise APIRequestError(self._service_name, status_code=e.response.status_code) from None
        except httpx.RequestError as e:
            # httpx exception strings commonly include the complete request
            # URL. Provider queries and contact emails are private request
            # data in a multi-tenant service, so log only the exception class.
            logger.warning("%s request failed (%s)", self._service_name, type(e).__name__)
            raise APIRequestError(self._service_name) from None
        except APIResponseTooLargeError:
            logger.warning(
                "%s response exceeded the configured byte limit",
                self._service_name,
            )
            raise
        except APIRequestError:
            raise
        except Exception as e:
            from pubmed_search.shared.exceptions import RateLimitError

            if isinstance(e, RateLimitError):
                retryable_error = RetryableOperationError(
                    f"{self._service_name} request failed",
                    retry_after=getattr(getattr(e, "context", None), "retry_after", None),
                )
                logger.warning("%s: Circuit breaker open or rate limited, skipping request", self._service_name)
                raise retryable_error from None
            logger.warning("%s request failed (%s)", self._service_name, type(e).__name__)
            raise APIRequestError(self._service_name) from None

    async def _handle_exhausted_retryable_error(
        self,
        error: RetryableOperationError,
        policy: RequestExecutionPolicy,
    ) -> None:
        """Handle an exhausted retryable response without noisy tracebacks."""
        if error.status_code == 429:
            cooldown = error.retry_after if error.retry_after is not None else _FALLBACK_RATE_LIMIT_COOLDOWN_SECONDS
            await self._apply_rate_limit_cooldown(policy, cooldown)
            logger.warning(
                "%s rate limited by upstream API after retries; applying a %.0fs shared cooldown before failure",
                self._service_name,
                cooldown,
            )
            return

        logger.warning(
            "%s transient request failed after retries (status=%s)",
            self._service_name,
            error.status_code,
        )

    @staticmethod
    async def _apply_rate_limit_cooldown(policy: RequestExecutionPolicy, cooldown: float) -> None:
        """Preserve upstream cooldowns without increasing a shared rate budget."""
        if cooldown <= 0 or policy.rate_limit is None:
            return

        limiter = get_rate_limiter(
            policy.rate_limit.name,
            rate=policy.rate_limit.rate,
            per=policy.rate_limit.per,
            conservative=True,
        )
        await limiter.apply_cooldown(cooldown)

    async def _execute_request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Execute and buffer a request without ever reading an unbounded body.

        The byte budget covers decoded bytes from every response in the
        redirect chain.  This prevents both ordinary oversized payloads and
        compressed responses from exhausting process memory before parsing.
        """
        if method not in {"GET", "POST"}:
            raise ValueError("Source requests support GET and POST only")
        if method == "POST":
            request = self._client.build_request(
                "POST",
                url,
                json=data,
                params=params,
                headers=headers or {},
            )
        else:
            request = self._client.build_request(
                "GET",
                url,
                params=params,
                headers=headers or {},
            )

        history: list[httpx.Response] = []
        bytes_read = 0
        for _redirect_count in range(_MAX_REDIRECTS + 1):
            streamed = await self._client.send(request, stream=True, follow_redirects=False)
            try:
                body = await self._read_response_body(
                    streamed,
                    remaining_bytes=self._max_response_bytes - bytes_read,
                )
                bytes_read += len(body)
                response = self._buffered_response(streamed, body=body, history=history)
                next_request = streamed.next_request
            finally:
                await streamed.aclose()

            if not self._follow_redirects or next_request is None:
                response.next_request = next_request
                return response

            if (request.url.scheme, request.url.host, request.url.port) != (
                next_request.url.scheme,
                next_request.url.host,
                next_request.url.port,
            ):
                for name in tuple(next_request.headers):
                    if name.lower() in {
                        "authorization",
                        "proxy-authorization",
                        "cookie",
                        "x-api-key",
                        "x-apikey",
                        "api-key",
                        "x-els-apikey",
                        "x-els-insttoken",
                    }:
                        next_request.headers.pop(name, None)
            history.append(response)
            request = next_request

        raise httpx.TooManyRedirects(
            f"Exceeded maximum allowed redirects ({_MAX_REDIRECTS})",
            request=request,
        )

    async def _read_response_body(
        self,
        response: httpx.Response,
        *,
        remaining_bytes: int,
    ) -> bytes:
        """Read one decoded response stream under the remaining hard budget."""
        declared_length = self._declared_response_length(response)
        if declared_length is not None and declared_length > remaining_bytes:
            raise APIResponseTooLargeError(
                self._service_name,
                max_bytes=self._max_response_bytes,
            )

        body = bytearray()
        chunk_size = min(_RESPONSE_STREAM_CHUNK_BYTES, max(1, remaining_bytes + 1))
        async for chunk in response.aiter_bytes(chunk_size):
            if len(body) + len(chunk) > remaining_bytes:
                raise APIResponseTooLargeError(
                    self._service_name,
                    max_bytes=self._max_response_bytes,
                )
            body.extend(chunk)
        return bytes(body)

    @staticmethod
    def _declared_response_length(response: httpx.Response) -> int | None:
        """Return a valid declared length, otherwise defer to streaming checks."""
        value = response.headers.get("content-length")
        if value is None:
            return None
        try:
            length = int(value)
        except ValueError:
            return None
        return length if length >= 0 else None

    @staticmethod
    def _buffered_response(
        response: httpx.Response,
        *,
        body: bytes,
        history: list[httpx.Response],
    ) -> httpx.Response:
        """Build a normal in-memory response from already-decoded safe bytes."""
        headers = httpx.Headers(response.headers)
        # ``aiter_bytes`` has already decoded transfer/content encodings.  If
        # these headers survived, the replacement Response would decode the
        # buffered bytes a second time.
        headers.pop("content-encoding", None)
        headers.pop("transfer-encoding", None)
        headers["content-length"] = str(len(body))
        return httpx.Response(
            response.status_code,
            headers=headers,
            content=body,
            request=response.request,
            extensions=response.extensions,
            history=list(history),
        )

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
