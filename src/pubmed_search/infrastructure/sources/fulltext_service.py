"""Compatibility export for the application-level fulltext service.

Design:
    The real orchestration service now lives under application/fulltext, but
    older imports still resolve through infrastructure/sources. This module
    preserves that path while keeping orchestration logic in the application
    layer.

Maintenance:
    Keep this shim limited to re-exports. If behavior changes are needed,
    implement them in application/fulltext/service.py and let this file remain
    a stable compatibility surface.
"""

from __future__ import annotations

from pubmed_search.application.fulltext.service import (
    FulltextRequest,
    FulltextService,
    FulltextServiceResult,
)

__all__ = ["FulltextRequest", "FulltextService", "FulltextServiceResult"]