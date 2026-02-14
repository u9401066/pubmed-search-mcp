"""
HTTP Client Module - Unified HTTP client with proxy support.

This module provides a centralized HTTP client that:
- Supports HTTP/HTTPS proxy configuration
- Handles rate limiting
- Provides consistent error handling with proper exceptions
- Automatic retry with exponential backoff
- Works across all data sources

Usage:
    from pubmed_search.infrastructure.http.client import http_get, http_post, configure_proxy

    # Configure proxy (optional)
    configure_proxy("http://proxy:8080")

    # Make requests (raises exceptions on error)
    response = http_get("https://api.example.com/data")

    # Safe version (returns None on error, for backward compatibility)
    response = http_get_safe("https://api.example.com/data")
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar

from pubmed_search.shared.exceptions import (
    NetworkError,
    ParseError,
    RateLimitError,
    ServiceUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Global configuration
_config: dict[str, Any] = {
    "http_proxy": None,
    "https_proxy": None,
    "timeout": 30.0,
    "user_agent": "pubmed-search-mcp/1.0",
    "contact_email": "pubmed-search-mcp@example.com",
    "max_retries": 3,
    "retry_base_delay": 1.0,
}

# Rate limiting state per domain
_rate_limits: dict[str, dict[str, float]] = {}


# =============================================================================
# Retry Decorator
# =============================================================================


def with_retry(
    max_retries: int | None = None,
    base_delay: float | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator for automatic retry with exponential backoff.

    Args:
        max_retries: Maximum retry attempts (default from config)
        base_delay: Base delay in seconds (default from config)

    Usage:
        @with_retry(max_retries=3)
        def fetch_data(url: str) -> dict:
            return http_get(url)
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            retries = max_retries if max_retries is not None else _config["max_retries"]
            delay = base_delay if base_delay is not None else _config["retry_base_delay"]
            last_error: Exception | None = None

            for attempt in range(retries + 1):
                try:
                    return func(*args, **kwargs)
                except RateLimitError as e:
                    last_error = e
                    wait_time = e.context.retry_after or (delay * (2**attempt))
                    if attempt < retries:
                        logger.warning(
                            f"Rate limited (attempt {attempt + 1}/{retries + 1}), retrying in {wait_time:.1f}s"
                        )
                        time.sleep(wait_time)
                    else:
                        raise
                except ServiceUnavailableError as e:
                    last_error = e
                    wait_time = delay * (2**attempt)
                    if attempt < retries:
                        logger.warning(
                            f"Service unavailable (attempt {attempt + 1}/{retries + 1}), retrying in {wait_time:.1f}s"
                        )
                        time.sleep(wait_time)
                    else:
                        raise
                except NetworkError as e:
                    last_error = e
                    wait_time = delay * (2**attempt)
                    if attempt < retries:
                        logger.warning(
                            f"Network error (attempt {attempt + 1}/{retries + 1}), retrying in {wait_time:.1f}s"
                        )
                        time.sleep(wait_time)
                    else:
                        raise

            # Should not reach here, but just in case
            if last_error:
                raise last_error
            raise RuntimeError("Unexpected retry loop exit")

        return wrapper

    return decorator


def configure_proxy(
    http_proxy: str | None = None,
    https_proxy: str | None = None,
) -> None:
    """
    Configure HTTP/HTTPS proxy settings.

    Args:
        http_proxy: HTTP proxy URL (e.g., "http://proxy:8080")
        https_proxy: HTTPS proxy URL (e.g., "https://proxy:8080")

    Also reads from environment variables:
        - HTTP_PROXY / http_proxy
        - HTTPS_PROXY / https_proxy
    """
    # Priority: explicit args > environment variables
    _config["http_proxy"] = http_proxy or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    _config["https_proxy"] = https_proxy or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")

    if _config["http_proxy"] or _config["https_proxy"]:
        logger.info(f"Proxy configured: HTTP={_config['http_proxy']}, HTTPS={_config['https_proxy']}")


def configure_client(
    timeout: float | None = None,
    user_agent: str | None = None,
    contact_email: str | None = None,
) -> None:
    """
    Configure HTTP client settings.

    Args:
        timeout: Request timeout in seconds
        user_agent: User-Agent header value
        contact_email: Contact email for API requests
    """
    if timeout is not None:
        _config["timeout"] = timeout
    if user_agent is not None:
        _config["user_agent"] = user_agent
    if contact_email is not None:
        _config["contact_email"] = contact_email


def get_proxy_status() -> dict[str, str | None]:
    """
    Get current proxy configuration status.

    Returns:
        Dict with http_proxy and https_proxy values
    """
    return {
        "http_proxy": _config["http_proxy"],
        "https_proxy": _config["https_proxy"],
    }


def _get_domain(url: str) -> str:
    """Extract domain from URL for rate limiting."""
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc


def _rate_limit(domain: str, min_interval: float = 0.5) -> None:
    """
    Apply rate limiting for a domain.

    Args:
        domain: The domain to rate limit
        min_interval: Minimum seconds between requests
    """
    if domain not in _rate_limits:
        _rate_limits[domain] = {"last_request": 0, "interval": min_interval}

    state = _rate_limits[domain]
    elapsed = time.time() - state["last_request"]
    if elapsed < state["interval"]:
        time.sleep(state["interval"] - elapsed)
    state["last_request"] = time.time()


def set_rate_limit(domain: str, min_interval: float) -> None:
    """
    Set rate limit for a specific domain.

    Args:
        domain: The domain (e.g., "api.semanticscholar.org")
        min_interval: Minimum seconds between requests
    """
    if domain not in _rate_limits:
        _rate_limits[domain] = {"last_request": 0, "interval": min_interval}
    else:
        _rate_limits[domain]["interval"] = min_interval


def _build_opener() -> urllib.request.OpenerDirector:
    """Build URL opener with proxy support."""
    handlers = []

    proxy_dict = {}
    if _config["http_proxy"]:
        proxy_dict["http"] = _config["http_proxy"]
    if _config["https_proxy"]:
        proxy_dict["https"] = _config["https_proxy"]

    if proxy_dict:
        proxy_handler = urllib.request.ProxyHandler(proxy_dict)
        handlers.append(proxy_handler)

    return urllib.request.build_opener(*handlers)


def http_get(
    url: str,
    headers: dict[str, str] | None = None,
    expect_json: bool = True,
    rate_limit_interval: float = 0.5,
    timeout: float | None = None,
) -> dict[str, Any] | str:
    """
    Make HTTP GET request with proxy support.

    Args:
        url: The URL to request
        headers: Additional headers
        expect_json: Parse response as JSON
        rate_limit_interval: Minimum seconds between requests to same domain
        timeout: Request timeout (uses global default if None)

    Returns:
        Parsed JSON dict or response string

    Raises:
        RateLimitError: When rate limited (HTTP 429)
        ServiceUnavailableError: When service is unavailable (HTTP 5xx)
        NetworkError: When network connection fails
        ParseError: When JSON parsing fails
    """
    domain = _get_domain(url)
    _rate_limit(domain, rate_limit_interval)

    # Build request
    request = urllib.request.Request(url)  # noqa: S310
    request.add_header("User-Agent", f"{_config['user_agent']} (mailto:{_config['contact_email']})")

    if expect_json:
        request.add_header("Accept", "application/json")

    if headers:
        for key, value in headers.items():
            request.add_header(key, value)

    # Make request with opener
    opener = _build_opener()
    request_timeout = timeout or _config["timeout"]

    try:
        with opener.open(request, timeout=request_timeout) as response:
            content = response.read().decode("utf-8")
            if expect_json:
                return json.loads(content)
            return content
    except urllib.error.HTTPError as e:
        logger.exception(f"HTTP error {e.code}: {e.reason} for {url}")
        if e.code == 429:
            # Try to extract Retry-After header
            retry_after = float(e.headers.get("Retry-After", 1.0))
            raise RateLimitError(
                f"Rate limited by {domain}",
                retry_after=retry_after,
            ) from e
        if e.code >= 500:
            raise ServiceUnavailableError(
                f"HTTP {e.code}: {e.reason}",
                service=domain,
            ) from e
        raise NetworkError(f"HTTP {e.code}: {e.reason} for {url}") from e
    except urllib.error.URLError as e:
        logger.exception(f"URL error: {e.reason} for {url}")
        raise NetworkError(f"Connection failed: {e.reason}") from e
    except json.JSONDecodeError as e:
        logger.exception(f"JSON decode error: {e}")
        raise ParseError("Invalid JSON response", source=domain) from e
    except TimeoutError as e:
        logger.exception(f"Timeout for {url}")
        raise NetworkError(f"Request timeout after {request_timeout}s") from e
    except Exception as e:
        logger.exception(f"Request error: {e}")
        raise NetworkError(f"Request failed: {e}") from e


def http_get_safe(
    url: str,
    headers: dict[str, str] | None = None,
    expect_json: bool = True,
    rate_limit_interval: float = 0.5,
    timeout: float | None = None,
) -> dict[str, Any] | str | None:
    """
    Safe version of http_get that returns None on error.

    For backward compatibility with existing code.
    Prefer http_get() for new code.
    """
    try:
        return http_get(url, headers, expect_json, rate_limit_interval, timeout)
    except Exception:
        return None


def http_post(
    url: str,
    data: dict[str, Any] | None = None,
    json_data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    expect_json: bool = True,
    rate_limit_interval: float = 0.5,
    timeout: float | None = None,
) -> dict[str, Any] | str:
    """
    Make HTTP POST request with proxy support.

    Args:
        url: The URL to request
        data: Form data (application/x-www-form-urlencoded)
        json_data: JSON data (application/json)
        headers: Additional headers
        expect_json: Parse response as JSON
        rate_limit_interval: Minimum seconds between requests
        timeout: Request timeout

    Returns:
        Parsed JSON dict or response string

    Raises:
        RateLimitError: When rate limited (HTTP 429)
        ServiceUnavailableError: When service is unavailable (HTTP 5xx)
        NetworkError: When network connection fails
        ParseError: When JSON parsing fails
    """
    domain = _get_domain(url)
    _rate_limit(domain, rate_limit_interval)

    # Build request
    if json_data:
        encoded_data = json.dumps(json_data).encode("utf-8")
        content_type = "application/json"
    elif data:
        encoded_data = urllib.parse.urlencode(data).encode("utf-8")
        content_type = "application/x-www-form-urlencoded"
    else:
        encoded_data = None
        content_type = None

    request = urllib.request.Request(url, data=encoded_data, method="POST")  # noqa: S310
    request.add_header("User-Agent", f"{_config['user_agent']} (mailto:{_config['contact_email']})")

    if content_type:
        request.add_header("Content-Type", content_type)

    if expect_json:
        request.add_header("Accept", "application/json")

    if headers:
        for key, value in headers.items():
            request.add_header(key, value)

    # Make request with opener
    opener = _build_opener()
    request_timeout = timeout or _config["timeout"]

    try:
        with opener.open(request, timeout=request_timeout) as response:
            content = response.read().decode("utf-8")
            if expect_json:
                return json.loads(content)
            return content
    except urllib.error.HTTPError as e:
        logger.exception(f"HTTP error {e.code}: {e.reason} for {url}")
        if e.code == 429:
            retry_after = float(e.headers.get("Retry-After", 1.0))
            raise RateLimitError(
                f"Rate limited by {domain}",
                retry_after=retry_after,
            ) from e
        if e.code >= 500:
            raise ServiceUnavailableError(
                f"HTTP {e.code}: {e.reason}",
                service=domain,
            ) from e
        raise NetworkError(f"HTTP {e.code}: {e.reason} for {url}") from e
    except urllib.error.URLError as e:
        logger.exception(f"URL error: {e.reason} for {url}")
        raise NetworkError(f"Connection failed: {e.reason}") from e
    except json.JSONDecodeError as e:
        logger.exception(f"JSON decode error: {e}")
        raise ParseError("Invalid JSON response", source=domain) from e
    except TimeoutError as e:
        logger.exception(f"Timeout for {url}")
        raise NetworkError(f"Request timeout after {request_timeout}s") from e
    except Exception as e:
        logger.exception(f"Request error: {e}")
        raise NetworkError(f"Request failed: {e}") from e


def http_post_safe(
    url: str,
    data: dict[str, Any] | None = None,
    json_data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    expect_json: bool = True,
    rate_limit_interval: float = 0.5,
    timeout: float | None = None,
) -> dict[str, Any] | str | None:
    """
    Safe version of http_post that returns None on error.

    For backward compatibility with existing code.
    Prefer http_post() for new code.
    """
    try:
        return http_post(url, data, json_data, headers, expect_json, rate_limit_interval, timeout)
    except Exception:
        return None


# Initialize from environment on module load
configure_proxy()
