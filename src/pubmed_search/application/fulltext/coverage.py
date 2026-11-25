"""Per-source fulltext coverage facts and sanitized failure classification.

Design:
    ``get_fulltext`` reports, for every retrieval source, whether it was
    attempted, completed, failed (with a typed reason), skipped because the
    request deadline elapsed, or completed with a notable non-error outcome.
    Agents use these facts to decide whether absence of fulltext is evidence
    or merely an incomplete check, so a local cache problem, an upstream outage,
    a rate limit, a timeout and the overall deadline must never collapse into
    one generic "unavailable" bucket.

Maintenance:
    Classification relies only on shared exception types and duck-typed,
    already-sanitized attributes (``status_code``, ``retry_after``, ``reason``)
    so this application module never imports infrastructure. Messages are
    fixed strings plus numbers; upstream exception text is never rendered.
"""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass
from typing import Literal

from pubmed_search.shared.async_utils import RetryableOperationError
from pubmed_search.shared.exceptions import ParseError, RateLimitError

from .cache import FulltextCacheError

_SOURCE_KEY_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")

FulltextSourceErrorCode = Literal[
    "source_unavailable",
    "upstream_retries_exhausted",
    "rate_limited",
    "upstream_http_error",
    "upstream_connection_error",
    "timeout",
    "deadline_exceeded",
    "invalid_response",
    "cache_error",
]
FulltextSourceNoticeCode = Literal["no_body", "front_matter_only", "superseded"]
FulltextSkipReason = Literal["deadline"]

_GENERIC_UNAVAILABLE = "The upstream source was unavailable during this request."


def require_source_key(source: str) -> str:
    """Reject display labels and unstable aliases in coverage fields."""
    if not isinstance(source, str) or _SOURCE_KEY_RE.fullmatch(source) is None:
        msg = "Fulltext coverage sources must use stable lowercase underscore keys"
        raise ValueError(msg)
    return source


@dataclass(frozen=True, slots=True)
class FulltextSourceError:
    """Sanitized source failure safe to expose in an MCP response."""

    source: str
    code: FulltextSourceErrorCode = "source_unavailable"
    message: str = _GENERIC_UNAVAILABLE
    retry_after: float | None = None
    status_code: int | None = None

    def __post_init__(self) -> None:
        require_source_key(self.source)

    def to_dict(self) -> dict[str, str | float | int]:
        payload: dict[str, str | float | int] = {"source": self.source, "code": self.code, "message": self.message}
        if self.retry_after is not None:
            payload["retry_after_seconds"] = self.retry_after
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        return payload


@dataclass(frozen=True, slots=True)
class FulltextSourceNotice:
    """A completed or superseded check whose outcome the agent must not misread."""

    source: str
    code: FulltextSourceNoticeCode
    message: str

    def __post_init__(self) -> None:
        require_source_key(self.source)

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class FulltextSkippedSource:
    """A policy source that was not started; it was neither checked nor failed."""

    source: str
    reason: FulltextSkipReason = "deadline"
    message: str = "Not attempted: the get_fulltext deadline elapsed before this source started."

    def __post_init__(self) -> None:
        require_source_key(self.source)

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "reason": self.reason, "message": self.message}


NOTICE_MESSAGES: dict[FulltextSourceNoticeCode, str] = {
    "no_body": "Completed, but this source provided no article body.",
    "front_matter_only": (
        "The publisher does not allow XML download from PMC; only front matter was returned, "
        "so it is not presented as fulltext."
    ),
    "superseded": "Stopped waiting after another source gave a definitive answer first.",
}


def make_notice(source: str, code: FulltextSourceNoticeCode) -> FulltextSourceNotice:
    """Build a notice with its canonical, fixed message."""
    return FulltextSourceNotice(source=source, code=code, message=NOTICE_MESSAGES[code])


def deadline_exceeded(source: str, deadline_seconds: float | None) -> FulltextSourceError:
    """Report a source cancelled by the overall request deadline."""
    budget = f" ({_seconds(deadline_seconds)}s)" if deadline_seconds is not None else ""
    return FulltextSourceError(
        source=source,
        code="deadline_exceeded",
        message=f"Stopped at the get_fulltext deadline{budget} before this source finished.",
    )


def classify_source_failure(source: str, error: BaseException) -> FulltextSourceError:
    """Map one sanitized exception to a typed, user-safe source error."""
    if isinstance(error, FulltextCacheError):
        return FulltextSourceError(
            source=source,
            code="cache_error",
            message="The local fulltext cache could not serve this request; upstream status is unknown.",
        )
    if isinstance(error, ParseError):
        return _invalid_response(source)
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return _timeout(source)
    status_code = _int_attribute(error, "status_code")
    retry_after = _retry_after(error)
    if isinstance(error, RateLimitError) or status_code == 429:
        return _rate_limited(source, retry_after, status_code)
    if isinstance(error, RetryableOperationError):
        suffix = f" (HTTP {status_code})" if status_code is not None else ""
        return FulltextSourceError(
            source=source,
            code="upstream_retries_exhausted",
            message=f"The upstream source kept failing after retries{suffix}.",
            retry_after=retry_after,
            status_code=status_code,
        )
    reason = getattr(error, "reason", None)
    if reason == "timeout":
        return _timeout(source)
    if reason == "transport":
        return FulltextSourceError(
            source=source,
            code="upstream_connection_error",
            message="The connection to the upstream source failed (for example reset or hung up).",
        )
    if reason in {"invalid_response", "too_large"}:
        return _invalid_response(source)
    if status_code is not None:
        return FulltextSourceError(
            source=source,
            code="upstream_http_error",
            message=f"The upstream source returned HTTP {status_code}.",
            status_code=status_code,
        )
    return FulltextSourceError(source=source)


def classify_link_discovery_error(
    source: str,
    *,
    kind: object,
    status_code: object,
) -> FulltextSourceError:
    """Translate a downloader link-source error into the same vocabulary."""
    status = status_code if isinstance(status_code, int) and not isinstance(status_code, bool) else None
    if status == 429:
        return _rate_limited(source, None, status)
    if kind == "timeout":
        return _timeout(source)
    if kind == "transport":
        return FulltextSourceError(
            source=source,
            code="upstream_connection_error",
            message="The connection to the upstream source failed (for example reset or hung up).",
        )
    if kind == "retryable":
        suffix = f" (HTTP {status})" if status is not None else ""
        return FulltextSourceError(
            source=source,
            code="upstream_retries_exhausted",
            message=f"The upstream source kept failing after retries{suffix}.",
            status_code=status,
        )
    if kind == "validation":
        return _invalid_response(source)
    if kind == "http" and status is not None:
        return FulltextSourceError(
            source=source,
            code="upstream_http_error",
            message=f"The upstream source returned HTTP {status}.",
            status_code=status,
        )
    return FulltextSourceError(source=source)


def _rate_limited(source: str, retry_after: float | None, status_code: int | None) -> FulltextSourceError:
    cooldown = f" (cooldown {_seconds(retry_after)}s)" if retry_after is not None else ""
    return FulltextSourceError(
        source=source,
        code="rate_limited",
        message=f"Rate limited by the upstream source{cooldown}; retry after the cooldown.",
        retry_after=retry_after,
        status_code=status_code,
    )


def _timeout(source: str) -> FulltextSourceError:
    return FulltextSourceError(
        source=source,
        code="timeout",
        message="The upstream source did not answer within its timeout.",
    )


def _invalid_response(source: str) -> FulltextSourceError:
    return FulltextSourceError(
        source=source,
        code="invalid_response",
        message="The upstream source returned a response that could not be used.",
    )


def _int_attribute(error: BaseException, name: str) -> int | None:
    value = getattr(error, name, None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _retry_after(error: BaseException) -> float | None:
    value = getattr(error, "retry_after", None)
    if value is None:
        # The shared cooldown a client applied after exhausting its retries.
        value = getattr(error, "cooldown_seconds", None)
    if value is None and isinstance(error, RateLimitError):
        value = error.context.retry_after
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _seconds(value: float | None) -> str:
    return f"{value:.0f}" if value is not None else "?"


__all__ = [
    "FulltextSkippedSource",
    "FulltextSourceError",
    "FulltextSourceErrorCode",
    "FulltextSourceNotice",
    "FulltextSourceNoticeCode",
    "classify_link_discovery_error",
    "classify_source_failure",
    "deadline_exceeded",
    "make_notice",
    "require_source_key",
]
