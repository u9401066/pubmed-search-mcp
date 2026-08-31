"""Shared validation primitives for untrusted provider payloads."""

from __future__ import annotations

from collections.abc import Mapping

_ERROR_ENVELOPE_KEYS = frozenset({"error", "errors"})


def is_provider_error_envelope(value: object) -> bool:
    """Return whether one mapping directly declares an error envelope."""
    return isinstance(value, Mapping) and any(
        isinstance(key, str) and key.casefold() in _ERROR_ENVELOPE_KEYS for key in value
    )


def has_provider_error_envelope(value: object) -> bool:
    """Return whether a nested provider value contains an explicit error envelope."""
    if isinstance(value, Mapping):
        if is_provider_error_envelope(value):
            return True
        return any(has_provider_error_envelope(nested) for nested in value.values())
    if isinstance(value, (list, tuple)):
        return any(has_provider_error_envelope(item) for item in value)
    return False
