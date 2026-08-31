"""Strict value objects for numeric NCBI database identifiers."""

from __future__ import annotations

import re

MAX_NCBI_IDENTIFIER_DIGITS = 20
_NCBI_IDENTIFIER_RE = re.compile(rf"[1-9][0-9]{{0,{MAX_NCBI_IDENTIFIER_DIGITS - 1}}}")


class NcbiIdentifierValidationError(ValueError):
    """Raised when a Gene ID, PubChem CID, or similar ID is malformed."""


def normalize_ncbi_identifier(value: object, *, label: str = "NCBI identifier") -> str:
    """Return a canonical positive numeric NCBI identifier.

    NCBI identifiers are opaque decimal identifiers.  Rejecting signs,
    decimals, Unicode lookalike digits, surrounding prose, and zero prevents a
    malformed request from being silently redirected to a different record.
    """

    if not isinstance(value, str):
        raise NcbiIdentifierValidationError(f"{label} must be a digit string")
    if _NCBI_IDENTIFIER_RE.fullmatch(value) is None:
        raise NcbiIdentifierValidationError(
            f"{label} must contain exactly 1-{MAX_NCBI_IDENTIFIER_DIGITS} positive ASCII digits"
        )
    return value


__all__ = [
    "MAX_NCBI_IDENTIFIER_DIGITS",
    "NcbiIdentifierValidationError",
    "normalize_ncbi_identifier",
]
