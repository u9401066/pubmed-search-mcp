"""Compatibility export for the fulltext registry definitions.

Design:
    The authoritative registry implementation lives in the application layer,
    but infrastructure code and tests still import it from this historical
    location. This shim preserves that import surface without duplicating logic.

Maintenance:
    Keep this file thin. New policy rules and source metadata belong in
    application/fulltext/registry.py, and this module should only re-export
    that API for compatibility.
"""

from __future__ import annotations

from pubmed_search.application.fulltext import (
    FulltextPolicyDefinition,
    FulltextPolicyKey,
    FulltextRegistry,
    FulltextSourceDefinition,
    get_fulltext_registry,
)

__all__ = [
    "FulltextPolicyDefinition",
    "FulltextPolicyKey",
    "FulltextRegistry",
    "FulltextSourceDefinition",
    "get_fulltext_registry",
]
