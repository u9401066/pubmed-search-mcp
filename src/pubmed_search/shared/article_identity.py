"""Deterministic article identity helpers shared across transports and ranking.

This module provides a single canonical article key strategy used by search
ranking, diagnostics, and pipeline execution. The key must be:

- deterministic across process runs
- stable across modules
- tolerant of DOI/title formatting differences

Priority order:
1. DOI (normalized)
2. PMID
3. Title (normalized)
4. Minimal metadata fallback
"""

from __future__ import annotations

import re
from typing import Any

_DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi:",
)


def normalize_article_doi(doi: str | None) -> str:
    """Normalize a DOI for identity comparisons.

    Args:
        doi: Raw DOI string, optionally with URL-style prefixes.

    Returns:
        Normalized lowercase DOI without transport prefixes.
    """
    if not doi:
        return ""

    normalized = doi.strip().lower()
    for prefix in _DOI_PREFIXES:
        normalized = normalized.removeprefix(prefix)
    return normalized


def normalize_article_title(title: str | None) -> str:
    """Normalize a title for deterministic identity fallback.

    Args:
        title: Raw article title.

    Returns:
        Lowercased title with punctuation removed and whitespace collapsed.
    """
    if not title:
        return ""

    normalized = title.lower()
    normalized = re.sub(r"[^\w\s]", "", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def canonical_article_key(article: Any) -> str:
    """Build a deterministic canonical key for an article-like object.

    Args:
        article: Object exposing article attributes such as ``pmid``, ``doi``,
            ``title``, ``primary_source``, ``journal``, and ``year``.

    Returns:
        Canonical identity key for set operations, ranking, and diagnostics.
    """
    doi = normalize_article_doi(getattr(article, "doi", None))
    if doi:
        return f"doi:{doi}"

    pmid = str(getattr(article, "pmid", "") or "").strip()
    if pmid:
        return f"pmid:{pmid}"

    title = normalize_article_title(getattr(article, "title", None))
    if title:
        return f"title:{title}"

    source = normalize_article_title(str(getattr(article, "primary_source", "") or ""))
    journal = normalize_article_title(str(getattr(article, "journal", "") or ""))
    year = str(getattr(article, "year", "") or "").strip()
    fallback_parts = [part for part in (source, journal, year) if part]
    if fallback_parts:
        return f"fallback:{':'.join(fallback_parts)}"

    return "fallback:unknown"
