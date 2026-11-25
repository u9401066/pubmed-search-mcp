"""Classify transient upstream failures once for every provider path.

A transient failure is one where repeating the *identical* request later can
succeed: a dropped or refused connection, a DNS hiccup, a socket or request
timeout, HTTP 408/425/429/5xx, or an upstream that reports itself temporarily
unavailable. Bio.Entrez surfaces most of these as ``urllib.error.URLError``
(or bare ``http.client``/``socket`` errors while reading a response); httpx
clients raise their own transport classes.

The classification keeps only a coarse kind and the exception *class name*.
Exception messages are never retained: urllib and httpx messages can embed the
request URL, which carries the user's query, the NCBI contact email and an API
key.
"""

from __future__ import annotations

import asyncio
import http.client
import socket
import ssl
from dataclasses import dataclass
from typing import Any, Literal
from urllib.error import HTTPError, URLError

TransientFailureKind = Literal["timeout", "transport", "http", "retryable"]
"""Subset of ``SourceAdapterErrorKind`` that is always retryable."""

RETRYABLE_HTTP_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})

TRANSIENT_MESSAGE_MARKERS = (
    "rate limit",
    "too many requests",
    "temporarily unavailable",
    "service unavailable",
    "backend failed",
    "connection reset",
    "timeout",
    "database is not supported",
)
"""Upstream-reported transient conditions (NCBI returns several as HTTP 200 errors)."""

_TRANSIENT_SSL_ERRORS = (ssl.SSLEOFError, ssl.SSLZeroReturnError, ssl.SSLSyscallError)
_TRANSPORT_ERRORS = (ConnectionError, socket.gaierror, http.client.IncompleteRead, *_TRANSIENT_SSL_ERRORS)
_PROGRAMMING_ERRORS = (ValueError, TypeError, LookupError, AttributeError, AssertionError, NotImplementedError)


def is_programming_error(error: BaseException) -> bool:
    """Return whether *error* is a caller/programming bug that retrying cannot fix."""
    return isinstance(error, _PROGRAMMING_ERRORS)


@dataclass(frozen=True, slots=True)
class TransientFailure:
    """Query-safe description of one transient upstream failure."""

    kind: TransientFailureKind
    upstream_type: str
    status_code: int | None = None


def classify_transient_error(error: BaseException) -> TransientFailure | None:
    """Return the transient failure class of *error*, or ``None`` if it is not transient.

    Programming errors, malformed provider payloads, certificate failures and
    non-retryable HTTP statuses are deliberately *not* transient.
    """
    upstream_type = type(error).__name__
    if isinstance(error, HTTPError):
        # HTTPError subclasses URLError; only retryable statuses are transient.
        code = error.code if isinstance(error.code, int) else None
        if code in RETRYABLE_HTTP_STATUS_CODES:
            return TransientFailure("http", upstream_type, code)
        return None
    if isinstance(error, URLError):
        return _classify_url_error(error)
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return TransientFailure("timeout", upstream_type)
    if isinstance(error, ssl.SSLCertVerificationError):
        return None
    if isinstance(error, _TRANSPORT_ERRORS):
        return TransientFailure("transport", upstream_type)

    explicit_kind = getattr(error, "failure_kind", None)
    status_code = _status_code(error)
    if explicit_kind in {"timeout", "transport", "http", "retryable"}:
        explicit_type = getattr(error, "upstream_type", None)
        return TransientFailure(
            explicit_kind,
            explicit_type if isinstance(explicit_type, str) and explicit_type else upstream_type,
            status_code,
        )

    # Sanitized provider errors (APIRequestError) keep only a coarse reason.
    coarse_reason = getattr(error, "reason", None)
    if coarse_reason == "timeout":
        return TransientFailure("timeout", upstream_type, status_code)
    if coarse_reason == "transport":
        return TransientFailure("transport", upstream_type, status_code)

    httpx_failure = _classify_httpx_error(error)
    if httpx_failure is not None:
        return httpx_failure

    from pubmed_search.shared.async_utils import RetryableOperationError
    from pubmed_search.shared.exceptions import RateLimitError

    if isinstance(error, RateLimitError):
        return TransientFailure("http", upstream_type, 429)
    if isinstance(error, RetryableOperationError):
        kind: TransientFailureKind = "http" if status_code in RETRYABLE_HTTP_STATUS_CODES else "retryable"
        return TransientFailure(kind, upstream_type, status_code)

    if is_programming_error(error):
        # A ValueError mentioning "timeout" is a caller bug, not an outage.
        return None
    message = str(error).lower()
    if any(marker in message for marker in TRANSIENT_MESSAGE_MARKERS):
        # e.g. Bio.Entrez RuntimeError for NCBI "Search Backend failed".
        return TransientFailure("retryable", upstream_type, status_code)
    return None


def _classify_url_error(error: URLError) -> TransientFailure | None:
    upstream_type = type(error).__name__
    reason: Any = error.reason
    if isinstance(reason, BaseException):
        if isinstance(reason, (asyncio.TimeoutError, TimeoutError)):
            return TransientFailure("timeout", upstream_type)
        if isinstance(reason, ssl.SSLCertVerificationError):
            return None
        if isinstance(reason, OSError):
            # ConnectionError, socket.gaierror (DNS), SSL EOF and other socket errors.
            return TransientFailure("transport", upstream_type)
        return None
    if isinstance(reason, str) and "timed out" in reason.lower():
        return TransientFailure("timeout", upstream_type)
    # String reasons such as "unknown url type" or "no host given" are caller bugs.
    return None


def _classify_httpx_error(error: BaseException) -> TransientFailure | None:
    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx is a runtime dependency
        return None
    upstream_type = type(error).__name__
    if isinstance(error, httpx.TimeoutException):
        return TransientFailure("timeout", upstream_type)
    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
        if status_code in RETRYABLE_HTTP_STATUS_CODES:
            return TransientFailure("http", upstream_type, status_code)
        return None
    if isinstance(error, httpx.RequestError):
        return TransientFailure("transport", upstream_type)
    return None


def _status_code(error: BaseException) -> int | None:
    value = getattr(error, "status_code", None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


__all__ = [
    "RETRYABLE_HTTP_STATUS_CODES",
    "TRANSIENT_MESSAGE_MARKERS",
    "TransientFailure",
    "TransientFailureKind",
    "classify_transient_error",
    "is_programming_error",
]
