"""Reference verification use cases.

This package contains the first-stage reference-list verification workflow:
parse reference entries, resolve them against PubMed evidence, and return a
structured verification report for MCP tools or higher-level orchestrators.
"""

from __future__ import annotations

from .service import (
    MAX_REFERENCE_BYTES,
    MAX_REFERENCE_CHARS,
    MAX_REFERENCE_TEXT_BYTES,
    MAX_REFERENCE_TEXT_CHARS,
    MAX_REFERENCES,
    MAX_SOURCE_NAME_BYTES,
    MAX_SOURCE_NAME_CHARS,
    ReferenceStatus,
    ReferenceVerificationInputError,
    ReferenceVerificationService,
)

__all__ = [
    "MAX_REFERENCES",
    "MAX_REFERENCE_BYTES",
    "MAX_REFERENCE_CHARS",
    "MAX_REFERENCE_TEXT_BYTES",
    "MAX_REFERENCE_TEXT_CHARS",
    "MAX_SOURCE_NAME_BYTES",
    "MAX_SOURCE_NAME_CHARS",
    "ReferenceStatus",
    "ReferenceVerificationInputError",
    "ReferenceVerificationService",
]
