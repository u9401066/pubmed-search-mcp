"""Input normalization helpers for MCP tool entry points.

Design:
    Tool implementations receive heterogeneous agent and user inputs. Article
    identifiers are parsed by strict domain value objects; malformed values are
    rejected as a whole and are never repaired by deleting characters.

Maintenance:
    Keep these helpers narrow and predictable. Validation with user-facing
    errors belongs in the tool layer; this module should focus on safe parsing
    of values already declared by each canonical tool schema.
"""

from __future__ import annotations

from pubmed_search.domain.value_objects import (
    try_normalize_doi,
    try_normalize_pmid,
)


class InputNormalizer:
    """Agent-friendly input normalizer for MCP tools."""

    @staticmethod
    def normalize_pmid_single(value: str | None) -> str | None:
        """Return one canonical PMID without accepting alternate input types."""
        if not isinstance(value, str):
            return None
        return try_normalize_pmid(value)

    @staticmethod
    def normalize_query(query: str) -> str:
        """Normalize typography and surrounding whitespace in free-form text."""
        if not isinstance(query, str):
            raise TypeError("query must be a string")

        query = query.strip()
        return query.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")

    @staticmethod
    def normalize_doi(value: str | None) -> str | None:
        """Return a canonical DOI, including canonical DOI URL/prefix parsing."""
        if not isinstance(value, str):
            return None
        return try_normalize_doi(value)


__all__ = ["InputNormalizer"]
