"""Runtime contact email coordination for external source clients."""

from __future__ import annotations

_source_contact_email: str | None = None


def _normalize_contact_email(email: str | None) -> str | None:
    if email is None:
        return None
    normalized = email.strip()
    return normalized or None


def configure_source_contact_email(email: str | None) -> None:
    """Set the process-local fallback email for source API clients."""
    global _source_contact_email
    _source_contact_email = _normalize_contact_email(email)


def get_configured_source_contact_email() -> str | None:
    """Return the process-local source contact email, if configured."""
    return _source_contact_email


def first_contact_email(*candidates: str | None) -> str | None:
    """Return the first non-empty email from explicit, runtime, or settings candidates."""
    for candidate in candidates:
        normalized = _normalize_contact_email(candidate)
        if normalized:
            return normalized
    return None


__all__ = [
    "configure_source_contact_email",
    "first_contact_email",
    "get_configured_source_contact_email",
]
