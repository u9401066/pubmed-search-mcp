"""Browser-session assisted PDF fetch via a local broker.

This module intentionally does NOT read browser cookie stores directly.
Instead, it talks to a user-controlled local broker process that performs the
actual navigation/download inside an authenticated browser context.

Security model:
1. Explicit opt-in via configuration.
2. Broker endpoint must be local-only by default.
3. Target hosts must be explicitly allow-listed.
4. The MCP server never receives raw browser cookies.
5. The broker is asked to return only PDF content, subject to size limits.

Expected broker request payload:
    {
        "url": "https://publisher.example/article",
        "mode": "pdf",
        "follow_pdf_links": true,
        "max_bytes": 52428800,
        "article": {"doi": "10.1000/example"}
    }

Expected broker response forms:
1. Raw PDF response with Content-Type: application/pdf
2. JSON response containing base64-encoded PDF bytes:
    {
        "success": true,
        "content_b64": "JVBERi0xLjQ...",
        "content_type": "application/pdf",
        "final_url": "https://publisher.example/download.pdf"
    }
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_LOCAL_BROKER_HOSTS = {"127.0.0.1", "localhost", "::1"}
_DOI_REDIRECT_HOSTS = {"doi.org", "dx.doi.org"}
_DEFAULT_TIMEOUT = 45.0
_DEFAULT_MAX_BYTES = 50 * 1024 * 1024


def _coerce_bool(value: Any, *, default: bool) -> bool:
    """Convert common env/config representations to bool."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_float(value: Any, *, default: float) -> float:
    """Convert env/config values to float with a safe default."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, *, default: int) -> int:
    """Convert env/config values to int with a safe default."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_str(value: Any, *, default: str = "") -> str:
    """Convert env/config values to normalized strings."""
    if value is None:
        return default
    return str(value).strip()


def _coerce_hosts(value: Any) -> list[str]:
    """Normalize allow-list hosts from strings or arrays."""
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, list):
        items = value
    else:
        return []
    return [str(item).strip().lower() for item in items if str(item).strip()]


def _load_json_config_from_env() -> dict[str, Any]:
    """Load optional single-setting broker config from env JSON."""
    raw = os.environ.get("BROWSER_FETCH_CONFIG", "").strip()
    if not raw:
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Invalid BROWSER_FETCH_CONFIG JSON: %s", exc)
        return {}

    if not isinstance(data, dict):
        logger.warning("Ignoring BROWSER_FETCH_CONFIG because it is not a JSON object")
        return {}
    return data


def _env_or_config(env_name: str, config: dict[str, Any], config_key: str) -> Any:
    """Return a field from env when present, otherwise from JSON config."""
    if env_name in os.environ:
        return os.environ[env_name]
    return config.get(config_key)


@dataclass
class BrowserSessionConfig:
    """
    Configuration for browser-session assisted fetch.

    The feature is disabled unless all of the following are true:
    - enabled=True
    - broker_url is configured
    - token is configured
    - allowed_hosts contains at least one host pattern
    """

    enabled: bool = False
    auto_enabled: bool = False
    broker_url: str = ""
    token: str = ""
    allowed_hosts: list[str] = field(default_factory=list)
    timeout_seconds: float = _DEFAULT_TIMEOUT
    max_bytes: int = _DEFAULT_MAX_BYTES
    require_local_broker: bool = True
    verify_tls: bool = True

    @classmethod
    def from_env(cls) -> BrowserSessionConfig:
        """Load broker configuration from a JSON setting plus env overrides."""
        config = _load_json_config_from_env()
        allowed_hosts = _coerce_hosts(
            _env_or_config("BROWSER_FETCH_ALLOWED_HOSTS", config, "allowed_hosts")
        )

        return cls(
            enabled=_coerce_bool(
                _env_or_config("BROWSER_FETCH_ENABLED", config, "enabled"),
                default=False,
            ),
            auto_enabled=_coerce_bool(
                _env_or_config("BROWSER_FETCH_AUTO", config, "auto_enabled"),
                default=False,
            ),
            broker_url=_coerce_str(
                _env_or_config("BROWSER_FETCH_BROKER_URL", config, "broker_url")
            ),
            token=_coerce_str(_env_or_config("BROWSER_FETCH_TOKEN", config, "token")),
            allowed_hosts=allowed_hosts,
            timeout_seconds=_coerce_float(
                _env_or_config("BROWSER_FETCH_TIMEOUT", config, "timeout_seconds"),
                default=_DEFAULT_TIMEOUT,
            ),
            max_bytes=_coerce_int(
                _env_or_config("BROWSER_FETCH_MAX_BYTES", config, "max_bytes"),
                default=_DEFAULT_MAX_BYTES,
            ),
            require_local_broker=_coerce_bool(
                _env_or_config("BROWSER_FETCH_REQUIRE_LOCAL", config, "require_local_broker"),
                default=True,
            ),
            verify_tls=_coerce_bool(
                _env_or_config("BROWSER_FETCH_VERIFY_TLS", config, "verify_tls"),
                default=True,
            ),
        )

    @property
    def is_configured(self) -> bool:
        """Return True when the feature is explicitly and safely configured."""
        return bool(self.enabled and self.broker_url and self.token and self.allowed_hosts)

    def broker_is_local(self) -> bool:
        """Return True when the broker endpoint resolves to a local host."""
        parsed = urlparse(self.broker_url)
        return (parsed.hostname or "").lower() in _LOCAL_BROKER_HOSTS

    @property
    def auto_mode_enabled(self) -> bool:
        """Return True when broker fallback should auto-run without per-tool args."""
        return bool(self.auto_enabled and self.is_configured and (not self.require_local_broker or self.broker_is_local()))


@dataclass
class BrowserFetchResult:
    """Result of a browser-session mediated PDF fetch."""

    success: bool
    content: bytes | None = None
    content_type: str | None = None
    final_url: str | None = None
    status_code: int | None = None
    error: str | None = None

    @property
    def is_pdf(self) -> bool:
        """Return True when the fetched content looks like a PDF."""
        return bool(self.content and self.content[:4] == b"%PDF")


class BrowserSessionFetcher:
    """
    Client for a local browser-session fetch broker.

    The broker is responsible for opening the requested URL inside an already
    authenticated browser context and returning PDF bytes. This keeps cookie
    handling out of the MCP server process.
    """

    def __init__(self, config: BrowserSessionConfig | None = None):
        self._config = config or BrowserSessionConfig.from_env()

    @property
    def config(self) -> BrowserSessionConfig:
        """Expose the effective broker configuration."""
        return self._config

    def is_enabled(self) -> bool:
        """Return True when browser-session fetch is usable."""
        if not self._config.is_configured:
            return False
        return not self._config.require_local_broker or self._config.broker_is_local()

    def is_auto_enabled(self) -> bool:
        """Return True when auto mode should use the configured broker."""
        return self._config.auto_mode_enabled

    def allows_target(self, url: str) -> bool:
        """Check whether a target URL satisfies scheme and host allow-list rules."""
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()

        if parsed.scheme != "https":
            return False
        if not hostname:
            return False
        if hostname in _DOI_REDIRECT_HOSTS:
            return True

        return any(self._host_matches(hostname, pattern) for pattern in self._config.allowed_hosts)

    async def fetch_pdf(
        self,
        url: str,
        *,
        article: dict[str, Any] | None = None,
        source_hint: str | None = None,
    ) -> BrowserFetchResult:
        """
        Ask the local broker to fetch a PDF inside an authenticated browser session.

        Args:
            url: Target landing page or PDF URL.
            article: Optional article metadata for broker-side heuristics.
            source_hint: Human-readable hint such as "OpenURL" or "CrossRef".

        Returns:
            BrowserFetchResult with PDF bytes when successful.
        """
        if not self.is_enabled():
            return BrowserFetchResult(success=False, error="Browser-session fetch is not configured")

        if not self.allows_target(url):
            return BrowserFetchResult(success=False, error=f"Target host not allow-listed: {url}")

        payload = {
            "url": url,
            "mode": "pdf",
            "follow_pdf_links": True,
            "max_bytes": self._config.max_bytes,
            "article": article or {},
            "source_hint": source_hint,
        }
        headers = {
            "Authorization": f"Bearer {self._config.token}",
            "Content-Type": "application/json",
        }

        try:
            response = await self._post_to_broker(payload, headers)
        except Exception as exc:
            return BrowserFetchResult(success=False, error=str(exc))

        if response.status_code != 200:
            error_message = f"Broker HTTP {response.status_code}"
            final_url = None
            with contextlib.suppress(Exception):
                data = response.json()
                if isinstance(data, dict):
                    error_message = data.get("error") or error_message
                    final_url = data.get("final_url")
            return BrowserFetchResult(
                success=False,
                error=error_message,
                final_url=final_url,
                status_code=response.status_code,
            )

        content_type = response.headers.get("Content-Type", "")
        if "application/pdf" in content_type.lower():
            return BrowserFetchResult(
                success=True,
                content=response.content,
                content_type=content_type,
                final_url=str(response.url),
                status_code=response.status_code,
            )

        data = response.json()
        if not data.get("success"):
            return BrowserFetchResult(
                success=False,
                error=data.get("error", "Broker reported failure"),
                final_url=data.get("final_url"),
                status_code=response.status_code,
            )

        encoded = data.get("content_b64") or data.get("pdf_b64")
        if not encoded:
            return BrowserFetchResult(success=False, error="Broker response missing content_b64")

        try:
            content = base64.b64decode(encoded)
        except Exception as exc:
            return BrowserFetchResult(success=False, error=f"Invalid broker base64 payload: {exc}")

        return BrowserFetchResult(
            success=True,
            content=content,
            content_type=data.get("content_type", content_type or "application/pdf"),
            final_url=data.get("final_url") or str(response.url),
            status_code=data.get("status_code", response.status_code),
        )

    async def _post_to_broker(self, payload: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        """Send a single request to the local broker."""
        timeout = httpx.Timeout(self._config.timeout_seconds, connect=min(self._config.timeout_seconds, 10.0))
        async with httpx.AsyncClient(timeout=timeout, verify=self._config.verify_tls) as client:
            return await client.post(self._config.broker_url, json=payload, headers=headers)

    def _host_matches(self, hostname: str, pattern: str) -> bool:
        """Match exact hosts and wildcard subdomain patterns."""
        normalized = pattern.lower().strip()
        if not normalized:
            return False
        if normalized.startswith("*."):
            suffix = normalized[1:]
            return hostname.endswith(suffix)
        return hostname == normalized


_browser_session_config: BrowserSessionConfig | None = None
_browser_session_fetcher: BrowserSessionFetcher | None = None


def get_browser_session_config() -> BrowserSessionConfig:
    """Get the singleton browser-session configuration."""
    global _browser_session_config
    if _browser_session_config is None:
        _browser_session_config = BrowserSessionConfig.from_env()
    return _browser_session_config


def configure_browser_session_fetch(
    *,
    enabled: bool,
    auto_enabled: bool = False,
    broker_url: str,
    token: str,
    allowed_hosts: list[str],
    timeout_seconds: float = _DEFAULT_TIMEOUT,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    require_local_broker: bool = True,
    verify_tls: bool = True,
) -> None:
    """Programmatically configure browser-session fetch for tests or embedding."""
    global _browser_session_config, _browser_session_fetcher
    _browser_session_config = BrowserSessionConfig(
        enabled=enabled,
        auto_enabled=auto_enabled,
        broker_url=broker_url,
        token=token,
        allowed_hosts=[host.lower() for host in allowed_hosts],
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        require_local_broker=require_local_broker,
        verify_tls=verify_tls,
    )
    _browser_session_fetcher = BrowserSessionFetcher(_browser_session_config)


def get_browser_session_fetcher() -> BrowserSessionFetcher:
    """Get the singleton browser-session fetcher."""
    global _browser_session_fetcher
    if _browser_session_fetcher is None:
        _browser_session_fetcher = BrowserSessionFetcher(get_browser_session_config())
    return _browser_session_fetcher
