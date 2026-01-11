"""
HTTP Client Module - Unified HTTP client with proxy support.

This module provides a centralized HTTP client that:
- Supports HTTP/HTTPS proxy configuration
- Handles rate limiting
- Provides consistent error handling
- Works across all data sources

Usage:
    from pubmed_search.http_client import http_get, http_post, configure_proxy
    
    # Configure proxy (optional)
    configure_proxy("http://proxy:8080")
    
    # Make requests
    response = http_get("https://api.example.com/data")
"""

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# Global configuration
_config = {
    "http_proxy": None,
    "https_proxy": None,
    "timeout": 30.0,
    "user_agent": "pubmed-search-mcp/1.0",
    "contact_email": "pubmed-search-mcp@example.com",
}

# Rate limiting state per domain
_rate_limits: dict[str, dict] = {}


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
    _config["http_proxy"] = (
        http_proxy 
        or os.environ.get("HTTP_PROXY") 
        or os.environ.get("http_proxy")
    )
    _config["https_proxy"] = (
        https_proxy 
        or os.environ.get("HTTPS_PROXY") 
        or os.environ.get("https_proxy")
    )
    
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
) -> dict | str | None:
    """
    Make HTTP GET request with proxy support.
    
    Args:
        url: The URL to request
        headers: Additional headers
        expect_json: Parse response as JSON
        rate_limit_interval: Minimum seconds between requests to same domain
        timeout: Request timeout (uses global default if None)
        
    Returns:
        Parsed JSON dict, response string, or None on error
    """
    domain = _get_domain(url)
    _rate_limit(domain, rate_limit_interval)
    
    # Build request
    request = urllib.request.Request(url)
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
        logger.error(f"HTTP error {e.code}: {e.reason} for {url}")
        return None
    except urllib.error.URLError as e:
        logger.error(f"URL error: {e.reason} for {url}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return None
    except Exception as e:
        logger.error(f"Request error: {e}")
        return None


def http_post(
    url: str,
    data: dict | None = None,
    json_data: dict | None = None,
    headers: dict[str, str] | None = None,
    expect_json: bool = True,
    rate_limit_interval: float = 0.5,
    timeout: float | None = None,
) -> dict | str | None:
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
        Parsed JSON dict, response string, or None on error
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
    
    request = urllib.request.Request(url, data=encoded_data, method="POST")
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
        logger.error(f"HTTP error {e.code}: {e.reason} for {url}")
        return None
    except urllib.error.URLError as e:
        logger.error(f"URL error: {e.reason} for {url}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return None
    except Exception as e:
        logger.error(f"Request error: {e}")
        return None


# Initialize from environment on module load
configure_proxy()
