"""
Shared utilities and exceptions.

The shared package intentionally keeps root exports lazy. Importing a specific
submodule, for example ``pubmed_search.shared.async_utils``, should not also
load settings/pydantic or every shared helper.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # Exceptions
    "PubMedSearchError": ("pubmed_search.shared.exceptions", "PubMedSearchError"),
    "ErrorContext": ("pubmed_search.shared.exceptions", "ErrorContext"),
    "ErrorSeverity": ("pubmed_search.shared.exceptions", "ErrorSeverity"),
    "ErrorCategory": ("pubmed_search.shared.exceptions", "ErrorCategory"),
    "APIError": ("pubmed_search.shared.exceptions", "APIError"),
    "RateLimitError": ("pubmed_search.shared.exceptions", "RateLimitError"),
    "NetworkError": ("pubmed_search.shared.exceptions", "NetworkError"),
    "ServiceUnavailableError": ("pubmed_search.shared.exceptions", "ServiceUnavailableError"),
    "ValidationError": ("pubmed_search.shared.exceptions", "ValidationError"),
    "InvalidPMIDError": ("pubmed_search.shared.exceptions", "InvalidPMIDError"),
    "InvalidQueryError": ("pubmed_search.shared.exceptions", "InvalidQueryError"),
    "InvalidParameterError": ("pubmed_search.shared.exceptions", "InvalidParameterError"),
    "DataError": ("pubmed_search.shared.exceptions", "DataError"),
    "NotFoundError": ("pubmed_search.shared.exceptions", "NotFoundError"),
    "ParseError": ("pubmed_search.shared.exceptions", "ParseError"),
    "ConfigurationError": ("pubmed_search.shared.exceptions", "ConfigurationError"),
    "create_error_group": ("pubmed_search.shared.exceptions", "create_error_group"),
    "is_retryable_error": ("pubmed_search.shared.exceptions", "is_retryable_error"),
    "get_retry_delay": ("pubmed_search.shared.exceptions", "get_retry_delay"),
    # Async utilities
    "RateLimiter": ("pubmed_search.shared.async_utils", "RateLimiter"),
    "get_rate_limiter": ("pubmed_search.shared.async_utils", "get_rate_limiter"),
    "gather_with_errors": ("pubmed_search.shared.async_utils", "gather_with_errors"),
    "batch_process": ("pubmed_search.shared.async_utils", "batch_process"),
    "CircuitBreaker": ("pubmed_search.shared.async_utils", "CircuitBreaker"),
    "get_shared_async_client": ("pubmed_search.shared.async_utils", "get_shared_async_client"),
    "close_shared_async_client": ("pubmed_search.shared.async_utils", "close_shared_async_client"),
    "timeout_with_fallback": ("pubmed_search.shared.async_utils", "timeout_with_fallback"),
    # Article identity
    "canonical_article_key": ("pubmed_search.shared.article_identity", "canonical_article_key"),
    "normalize_article_doi": ("pubmed_search.shared.article_identity", "normalize_article_doi"),
    "normalize_article_title": ("pubmed_search.shared.article_identity", "normalize_article_title"),
    # Settings
    "AppSettings": ("pubmed_search.shared.settings", "AppSettings"),
    "get_settings": ("pubmed_search.shared.settings", "get_settings"),
    "load_settings": ("pubmed_search.shared.settings", "load_settings"),
    "reset_settings_cache": ("pubmed_search.shared.settings", "reset_settings_cache"),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *_LAZY_EXPORTS])
