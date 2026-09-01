"""Contact identity helpers for external source clients."""

from __future__ import annotations


def _normalize_contact_email(email: str | None) -> str | None:
    if email is None:
        return None
    normalized = email.strip()
    return normalized or None


def get_source_contact_email() -> str | None:
    """Return the contact identity bound to the current source runtime."""
    from .runtime import get_source_runtime

    return get_source_runtime().contact_email


def first_contact_email(*candidates: str | None) -> str | None:
    """Return the first non-empty email from explicit, runtime, or settings candidates."""
    for candidate in candidates:
        normalized = _normalize_contact_email(candidate)
        if normalized:
            return normalized
    return None


__all__ = [
    "first_contact_email",
    "get_source_contact_email",
]
