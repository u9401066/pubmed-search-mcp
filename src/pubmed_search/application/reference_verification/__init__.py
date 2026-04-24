"""Reference verification use cases.

This package contains the first-stage reference-list verification workflow:
parse reference entries, resolve them against PubMed evidence, and return a
structured verification report for MCP tools or higher-level orchestrators.
"""

from __future__ import annotations

from .service import ReferenceVerificationService

__all__ = ["ReferenceVerificationService"]
