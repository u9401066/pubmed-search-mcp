"""Centralized runtime configuration parsed with Pydantic Settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_EMAIL = "pubmed-search@example.com"
DEFAULT_DATA_DIR = str(Path.home() / ".pubmed-search-mcp")
DEFAULT_HTTP_API_PORT = 8765
DEFAULT_FULLTEXT_INLINE_MAX_CHARS = 20_000
DEFAULT_TENANT_MAX_CONCURRENCY = 8


class AppSettings(BaseSettings):
    """Normalized settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    ncbi_email: str = Field(default=DEFAULT_EMAIL, alias="NCBI_EMAIL")
    ncbi_api_key: str | None = Field(default=None, alias="NCBI_API_KEY")

    data_dir: str = Field(default=DEFAULT_DATA_DIR, alias="PUBMED_DATA_DIR")
    workspace_dir: str | None = Field(default=None, alias="PUBMED_WORKSPACE_DIR")
    notes_dir: str | None = Field(default=None, alias="PUBMED_NOTES_DIR")
    http_api_port: int = Field(default=DEFAULT_HTTP_API_PORT, alias="PUBMED_HTTP_API_PORT")
    stdio_aux_http_enabled: bool = Field(default=False, alias="PUBMED_STDIO_AUX_HTTP")
    local_allow_container_bind: bool = Field(default=False, alias="PUBMED_LOCAL_ALLOW_CONTAINER_BIND")

    profiling_enabled: bool = Field(default=False, alias="PUBMED_PROFILING")
    disabled_sources_raw: str = Field(default="", alias="PUBMED_SEARCH_DISABLED_SOURCES")
    artifact_include_local_paths: bool = Field(default=False, alias="PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS")
    fulltext_inline_max_chars: int = Field(
        default=DEFAULT_FULLTEXT_INLINE_MAX_CHARS,
        alias="PUBMED_FULLTEXT_INLINE_MAX_CHARS",
    )

    # Multi-agent deployment: auth, tenant isolation, and per-tenant fairness.
    auth_tokens_raw: str = Field(default="", alias="PUBMED_AUTH_TOKENS")
    auth_required: bool = Field(default=False, alias="PUBMED_AUTH_REQUIRED")
    auth_issuer_url: str = Field(default="", alias="PUBMED_AUTH_ISSUER_URL")
    auth_resource_server_url: str = Field(default="", alias="PUBMED_AUTH_RESOURCE_SERVER_URL")
    server_mode: Literal["local", "service"] = Field(default="local", alias="PUBMED_SERVER_MODE")
    allowed_hosts_raw: str = Field(default="", alias="PUBMED_ALLOWED_HOSTS")
    allowed_origins_raw: str = Field(default="", alias="PUBMED_ALLOWED_ORIGINS")
    trusted_proxy_ips_raw: str = Field(default="", alias="PUBMED_TRUSTED_PROXY_IPS")
    tenant_isolation: bool = Field(default=True, alias="PUBMED_TENANT_ISOLATION")
    tenant_max_concurrency: int = Field(
        default=DEFAULT_TENANT_MAX_CONCURRENCY,
        alias="PUBMED_TENANT_MAX_CONCURRENCY",
    )

    crossref_email: str | None = Field(default=None, alias="CROSSREF_EMAIL")
    unpaywall_email: str | None = Field(default=None, alias="UNPAYWALL_EMAIL")
    openalex_api_key: str | None = Field(default=None, alias="OPENALEX_API_KEY")
    semantic_scholar_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SEMANTIC_SCHOLAR_API_KEY", "S2_API_KEY"),
    )
    core_api_key: str | None = Field(default=None, alias="CORE_API_KEY")

    openurl_enabled: bool = Field(default=True, alias="OPENURL_ENABLED")
    openurl_resolver: str = Field(default="", alias="OPENURL_RESOLVER")
    openurl_preset: str = Field(default="", alias="OPENURL_PRESET")

    # Institutional direct/EZproxy fulltext access (Phase 1 + Phase 2)
    institutional_direct_fetch: bool = Field(default=True, alias="INSTITUTIONAL_DIRECT_FETCH")
    ezproxy_enabled: bool = Field(default=False, alias="EZPROXY_ENABLED")
    ezproxy_host: str = Field(default="", alias="EZPROXY_HOST")
    ezproxy_cookie_file: str = Field(default="", alias="EZPROXY_COOKIE_FILE")
    ezproxy_cookie: str = Field(default="", alias="EZPROXY_COOKIE")

    scopus_enabled: bool = Field(default=False, alias="SCOPUS_ENABLED")
    scopus_api_key: str | None = Field(default=None, alias="SCOPUS_API_KEY")
    scopus_insttoken: str | None = Field(default=None, alias="SCOPUS_INSTTOKEN")

    web_of_science_enabled: bool = Field(default=False, alias="WEB_OF_SCIENCE_ENABLED")
    web_of_science_api_key: str | None = Field(default=None, alias="WEB_OF_SCIENCE_API_KEY")

    scheduler_enabled: bool = Field(default=True, alias="PUBMED_SCHEDULER_ENABLED")
    scheduler_timezone: str = Field(default="UTC", alias="PUBMED_SCHEDULER_TIMEZONE")
    scheduler_coalesce: bool = Field(default=True, alias="PUBMED_SCHEDULER_COALESCE")
    scheduler_max_instances: int = Field(default=1, alias="PUBMED_SCHEDULER_MAX_INSTANCES")
    scheduler_misfire_grace_seconds: int = Field(
        default=3600,
        alias="PUBMED_SCHEDULER_MISFIRE_GRACE_SECONDS",
    )

    @field_validator(
        "ncbi_email",
        "data_dir",
        "disabled_sources_raw",
        "openurl_resolver",
        "openurl_preset",
        "ezproxy_host",
        "ezproxy_cookie_file",
        "ezproxy_cookie",
        "scheduler_timezone",
        "auth_tokens_raw",
        "auth_issuer_url",
        "auth_resource_server_url",
        "allowed_hosts_raw",
        "allowed_origins_raw",
        "trusted_proxy_ips_raw",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator(
        "workspace_dir",
        "notes_dir",
        "crossref_email",
        "unpaywall_email",
        "openalex_api_key",
        "semantic_scholar_api_key",
        "core_api_key",
        "scopus_api_key",
        "scopus_insttoken",
        "web_of_science_api_key",
        mode="before",
    )
    @classmethod
    def _strip_optional_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("ncbi_api_key", mode="before")
    @classmethod
    def _strip_ncbi_api_key(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("server_mode", mode="before")
    @classmethod
    def _normalize_server_mode(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @property
    def disabled_sources(self) -> tuple[str, ...]:
        """Normalized disabled source keys from PUBMED_SEARCH_DISABLED_SOURCES."""
        return tuple(
            token.strip().lower().replace("-", "_") for token in self.disabled_sources_raw.split(",") if token.strip()
        )

    @staticmethod
    def _csv_values(raw: str) -> tuple[str, ...]:
        """Return non-empty comma-separated configuration values."""
        return tuple(value.strip() for value in raw.split(",") if value.strip())

    @property
    def allowed_hosts(self) -> tuple[str, ...]:
        """Host-header allowlist for MCP HTTP transports."""
        return self._csv_values(self.allowed_hosts_raw)

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        """Origin-header allowlist for MCP HTTP transports."""
        return self._csv_values(self.allowed_origins_raw)

    @property
    def trusted_proxy_ips(self) -> tuple[str, ...]:
        """Proxy addresses allowed to supply forwarded headers."""
        return self._csv_values(self.trusted_proxy_ips_raw)


def load_settings() -> AppSettings:
    """Load settings from the current environment without caching."""
    return AppSettings()


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Get cached application settings."""
    return load_settings()


def reset_settings_cache() -> None:
    """Clear the cached settings instance."""
    get_settings.cache_clear()
