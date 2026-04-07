"""HTTP client exports for infrastructure integrations.

Design:
    This package-level export keeps the public HTTP client surface small and
    stable for callers that only need the primary PubMed client.

Maintenance:
    Add new shared HTTP utilities here only when they are intended to be part
    of the package surface. Internal helpers should stay in their own modules.
"""

from __future__ import annotations

from .pubmed_client import PubMedClient

__all__ = [
    "PubMedClient",
]
