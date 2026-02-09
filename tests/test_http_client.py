"""
Tests for HTTP client module.

Target: http/client.py coverage from 16% to 90%+
"""

import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from pubmed_search.infrastructure.http.client import (
    _build_opener,
    _config,
    _get_domain,
    _rate_limit,
    _rate_limits,
    configure_client,
    configure_proxy,
    get_proxy_status,
    http_get,
    http_get_safe,
    http_post,
    http_post_safe,
    set_rate_limit,
    with_retry,
)
from pubmed_search.shared.exceptions import (
    NetworkError,
    ParseError,
    RateLimitError,
    ServiceUnavailableError,
)


# =============================================================================
# Configuration Tests
# =============================================================================


class TestConfiguration:
    """Tests for configuration functions."""

    def setup_method(self):
        """Reset config before each test."""
        _config["http_proxy"] = None
        _config["https_proxy"] = None
        _config["timeout"] = 30.0
        _config["max_retries"] = 3
        _config["retry_base_delay"] = 1.0

    def test_configure_proxy_explicit(self):
        """Test explicit proxy configuration."""
        configure_proxy(http_proxy="http://proxy:8080", https_proxy="https://proxy:8080")
        assert _config["http_proxy"] == "http://proxy:8080"
        assert _config["https_proxy"] == "https://proxy:8080"

    def test_configure_proxy_from_env(self):
        """Test proxy configuration from environment."""
        with patch.dict("os.environ", {"HTTP_PROXY": "http://env-proxy:8080"}):
            configure_proxy()
            assert _config["http_proxy"] == "http://env-proxy:8080"

    def test_configure_proxy_explicit_overrides_env(self):
        """Test explicit config overrides environment."""
        with patch.dict("os.environ", {"HTTP_PROXY": "http://env-proxy:8080"}):
            configure_proxy(http_proxy="http://explicit:8080")
            assert _config["http_proxy"] == "http://explicit:8080"

    def test_get_proxy_status(self):
        """Test get_proxy_status returns current config."""
        _config["http_proxy"] = "http://test:8080"
        _config["https_proxy"] = "https://test:8080"
        status = get_proxy_status()
        assert status["http_proxy"] == "http://test:8080"
        assert status["https_proxy"] == "https://test:8080"

    def test_configure_client_timeout(self):
        """Test configure_client sets timeout."""
        configure_client(timeout=60.0)
        assert _config["timeout"] == 60.0

    def test_configure_client_user_agent(self):
        """Test configure_client sets user agent."""
        configure_client(user_agent="test-agent/1.0")
        assert _config["user_agent"] == "test-agent/1.0"

    def test_configure_client_email(self):
        """Test configure_client sets contact email."""
        configure_client(contact_email="test@example.com")
        assert _config["contact_email"] == "test@example.com"

    def test_configure_client_partial(self):
        """Test configure_client with partial settings."""
        original_timeout = _config["timeout"]
        configure_client(user_agent="new-agent")
        assert _config["user_agent"] == "new-agent"
        assert _config["timeout"] == original_timeout  # Unchanged


# =============================================================================
# Rate Limiting Tests
# =============================================================================


class TestRateLimiting:
    """Tests for rate limiting functions."""

    def test_get_domain(self):
        """Test domain extraction from URL."""
        assert _get_domain("https://api.example.com/path") == "api.example.com"
        assert _get_domain("http://localhost:8080/api") == "localhost:8080"

    def test_set_rate_limit_new_domain(self):
        """Test set_rate_limit for new domain."""
        set_rate_limit("new-domain.com", 2.0)
        assert _rate_limits["new-domain.com"]["interval"] == 2.0

    def test_set_rate_limit_existing_domain(self):
        """Test set_rate_limit updates existing domain."""
        _rate_limits["existing.com"] = {"last_request": 0, "interval": 1.0}
        set_rate_limit("existing.com", 5.0)
        assert _rate_limits["existing.com"]["interval"] == 5.0

    def test_rate_limit_creates_entry(self):
        """Test _rate_limit creates entry for new domain."""
        domain = "rate-test-domain.com"
        if domain in _rate_limits:
            del _rate_limits[domain]
        _rate_limit(domain, min_interval=0.1)
        assert domain in _rate_limits


# =============================================================================
# http_get Tests
# =============================================================================


class TestHttpGet:
    """Tests for http_get function."""

    @patch("pubmed_search.infrastructure.http.client._build_opener")
    def test_http_get_success_json(self, mock_build_opener):
        """Test successful JSON response."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"key": "value"}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_response
        mock_build_opener.return_value = mock_opener

        result = http_get("https://api.test.com/data", rate_limit_interval=0)
        assert result == {"key": "value"}

    @patch("pubmed_search.infrastructure.http.client._build_opener")
    def test_http_get_success_text(self, mock_build_opener):
        """Test successful text response."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"plain text response"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_response
        mock_build_opener.return_value = mock_opener

        result = http_get("https://api.test.com/data", expect_json=False, rate_limit_interval=0)
        assert result == "plain text response"

    @patch("pubmed_search.infrastructure.http.client._build_opener")
    def test_http_get_rate_limit_error(self, mock_build_opener):
        """Test rate limit error handling."""
        mock_error = urllib.error.HTTPError(
            "https://api.test.com", 429, "Too Many Requests", {"Retry-After": "5"}, None
        )
        mock_opener = MagicMock()
        mock_opener.open.side_effect = mock_error
        mock_build_opener.return_value = mock_opener

        with pytest.raises(RateLimitError):
            http_get("https://api.test.com/data", rate_limit_interval=0)

    @patch("pubmed_search.infrastructure.http.client._build_opener")
    def test_http_get_server_error(self, mock_build_opener):
        """Test server error handling."""
        mock_error = urllib.error.HTTPError(
            "https://api.test.com", 503, "Service Unavailable", {}, None
        )
        mock_opener = MagicMock()
        mock_opener.open.side_effect = mock_error
        mock_build_opener.return_value = mock_opener

        with pytest.raises(ServiceUnavailableError):
            http_get("https://api.test.com/data", rate_limit_interval=0)

    @patch("pubmed_search.infrastructure.http.client._build_opener")
    def test_http_get_client_error(self, mock_build_opener):
        """Test client error handling."""
        mock_error = urllib.error.HTTPError(
            "https://api.test.com", 404, "Not Found", {}, None
        )
        mock_opener = MagicMock()
        mock_opener.open.side_effect = mock_error
        mock_build_opener.return_value = mock_opener

        with pytest.raises(NetworkError):
            http_get("https://api.test.com/data", rate_limit_interval=0)

    @patch("pubmed_search.infrastructure.http.client._build_opener")
    def test_http_get_url_error(self, mock_build_opener):
        """Test URL error handling."""
        mock_error = urllib.error.URLError("Connection refused")
        mock_opener = MagicMock()
        mock_opener.open.side_effect = mock_error
        mock_build_opener.return_value = mock_opener

        with pytest.raises(NetworkError):
            http_get("https://api.test.com/data", rate_limit_interval=0)

    @patch("pubmed_search.infrastructure.http.client._build_opener")
    def test_http_get_json_decode_error(self, mock_build_opener):
        """Test JSON decode error handling."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"not valid json"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_response
        mock_build_opener.return_value = mock_opener

        with pytest.raises(ParseError):
            http_get("https://api.test.com/data", expect_json=True, rate_limit_interval=0)

    @patch("pubmed_search.infrastructure.http.client._build_opener")
    def test_http_get_with_headers(self, mock_build_opener):
        """Test http_get with custom headers."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"key": "value"}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_response
        mock_build_opener.return_value = mock_opener

        result = http_get(
            "https://api.test.com/data",
            headers={"Authorization": "Bearer token"},
            rate_limit_interval=0,
        )
        assert result == {"key": "value"}


# =============================================================================
# http_get_safe Tests
# =============================================================================


class TestHttpGetSafe:
    """Tests for http_get_safe function."""

    @patch("pubmed_search.infrastructure.http.client.http_get")
    def test_http_get_safe_success(self, mock_http_get):
        """Test http_get_safe returns result on success."""
        mock_http_get.return_value = {"key": "value"}
        result = http_get_safe("https://api.test.com/data")
        assert result == {"key": "value"}

    @patch("pubmed_search.infrastructure.http.client.http_get")
    def test_http_get_safe_error_returns_none(self, mock_http_get):
        """Test http_get_safe returns None on error."""
        mock_http_get.side_effect = NetworkError("Connection failed")
        result = http_get_safe("https://api.test.com/data")
        assert result is None


# =============================================================================
# http_post Tests
# =============================================================================


class TestHttpPost:
    """Tests for http_post function."""

    @patch("pubmed_search.infrastructure.http.client._build_opener")
    def test_http_post_json_data(self, mock_build_opener):
        """Test POST with JSON data."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"success": true}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_response
        mock_build_opener.return_value = mock_opener

        result = http_post(
            "https://api.test.com/data",
            json_data={"key": "value"},
            rate_limit_interval=0,
        )
        assert result == {"success": True}

    @patch("pubmed_search.infrastructure.http.client._build_opener")
    def test_http_post_form_data(self, mock_build_opener):
        """Test POST with form data."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"success": true}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_response
        mock_build_opener.return_value = mock_opener

        result = http_post(
            "https://api.test.com/data",
            data={"key": "value"},
            rate_limit_interval=0,
        )
        assert result == {"success": True}

    @patch("pubmed_search.infrastructure.http.client._build_opener")
    def test_http_post_no_data(self, mock_build_opener):
        """Test POST without data."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"success": true}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_response
        mock_build_opener.return_value = mock_opener

        result = http_post("https://api.test.com/data", rate_limit_interval=0)
        assert result == {"success": True}

    @patch("pubmed_search.infrastructure.http.client._build_opener")
    def test_http_post_rate_limit_error(self, mock_build_opener):
        """Test POST rate limit error."""
        mock_error = urllib.error.HTTPError(
            "https://api.test.com", 429, "Too Many Requests", {"Retry-After": "5"}, None
        )
        mock_opener = MagicMock()
        mock_opener.open.side_effect = mock_error
        mock_build_opener.return_value = mock_opener

        with pytest.raises(RateLimitError):
            http_post("https://api.test.com/data", json_data={}, rate_limit_interval=0)

    @patch("pubmed_search.infrastructure.http.client._build_opener")
    def test_http_post_server_error(self, mock_build_opener):
        """Test POST server error."""
        mock_error = urllib.error.HTTPError(
            "https://api.test.com", 500, "Internal Server Error", {}, None
        )
        mock_opener = MagicMock()
        mock_opener.open.side_effect = mock_error
        mock_build_opener.return_value = mock_opener

        with pytest.raises(ServiceUnavailableError):
            http_post("https://api.test.com/data", json_data={}, rate_limit_interval=0)


# =============================================================================
# http_post_safe Tests
# =============================================================================


class TestHttpPostSafe:
    """Tests for http_post_safe function."""

    @patch("pubmed_search.infrastructure.http.client.http_post")
    def test_http_post_safe_success(self, mock_http_post):
        """Test http_post_safe returns result on success."""
        mock_http_post.return_value = {"success": True}
        result = http_post_safe("https://api.test.com/data", json_data={})
        assert result == {"success": True}

    @patch("pubmed_search.infrastructure.http.client.http_post")
    def test_http_post_safe_error_returns_none(self, mock_http_post):
        """Test http_post_safe returns None on error."""
        mock_http_post.side_effect = NetworkError("Connection failed")
        result = http_post_safe("https://api.test.com/data", json_data={})
        assert result is None


# =============================================================================
# with_retry Decorator Tests
# =============================================================================


class TestWithRetry:
    """Tests for with_retry decorator."""

    def test_retry_success_first_try(self):
        """Test function succeeds on first try."""
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        def succeeds():
            nonlocal call_count
            call_count += 1
            return "success"

        result = succeeds()
        assert result == "success"
        assert call_count == 1

    def test_retry_success_after_retries(self):
        """Test function succeeds after retries."""
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        def fails_then_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise NetworkError("Temporary failure")
            return "success"

        result = fails_then_succeeds()
        assert result == "success"
        assert call_count == 3

    def test_retry_rate_limit_honors_retry_after(self):
        """Test retry honors Retry-After header."""
        call_count = 0

        @with_retry(max_retries=2, base_delay=0.01)
        def rate_limited():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RateLimitError("Rate limited", retry_after=0.01)
            return "success"

        result = rate_limited()
        assert result == "success"
        assert call_count == 2

    def test_retry_exhausted_raises(self):
        """Test raises after max retries exhausted."""

        @with_retry(max_retries=2, base_delay=0.01)
        def always_fails():
            raise NetworkError("Always fails")

        with pytest.raises(NetworkError):
            always_fails()

    def test_retry_service_unavailable(self):
        """Test retry on service unavailable."""
        call_count = 0

        @with_retry(max_retries=2, base_delay=0.01)
        def service_unavailable():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ServiceUnavailableError("Service down", service="test")
            return "success"

        result = service_unavailable()
        assert result == "success"


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_build_opener_no_proxy(self):
        """Test _build_opener without proxy."""
        _config["http_proxy"] = None
        _config["https_proxy"] = None
        opener = _build_opener()
        assert opener is not None

    def test_build_opener_with_proxy(self):
        """Test _build_opener with proxy."""
        _config["http_proxy"] = "http://proxy:8080"
        _config["https_proxy"] = "https://proxy:8080"
        opener = _build_opener()
        assert opener is not None
