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

import hashlib
import json
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


def normalize_article_identifier(kind: str, value: str | int | None) -> str:
    """Normalize a provider identifier for cross-source identity matching."""
    # Adapter payloads use strings (and occasionally integer CORE ids). Reject
    # arbitrary truthy objects so mocks or malformed provider values cannot
    # become accidental canonical identities.
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return ""

    normalized = str(value).strip()
    if not normalized:
        return ""

    kind = kind.strip().lower()
    lowered = normalized.lower()
    if kind == "pmc":
        lowered = lowered.removeprefix("https://www.ncbi.nlm.nih.gov/pmc/articles/").strip("/")
        return lowered.upper() if lowered.upper().startswith("PMC") else f"PMC{lowered.upper()}"
    if kind == "openalex":
        return lowered.removeprefix("https://openalex.org/").upper()
    if kind == "arxiv":
        lowered = lowered.removeprefix("https://arxiv.org/abs/").removeprefix("arxiv:")
        return re.sub(r"v\d+$", "", lowered)
    return lowered


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

    for attr, kind in (
        ("pmc", "pmc"),
        ("openalex_id", "openalex"),
        ("s2_id", "s2"),
        ("core_id", "core"),
        ("arxiv_id", "arxiv"),
    ):
        identifier = normalize_article_identifier(kind, getattr(article, attr, None))
        if identifier:
            return f"{kind}:{identifier}"

    title = normalize_article_title(getattr(article, "title", None))
    if title:
        return f"title:{title}"

    authors = []
    for author in getattr(article, "authors", None) or []:
        authors.append(str(getattr(author, "full_name", None) or getattr(author, "name", None) or author))
    source_records = []
    for source in getattr(article, "sources", None) or []:
        source_records.append(
            {
                "source": getattr(source, "source", None),
                "raw_data": getattr(source, "raw_data", None),
            }
        )
    fallback_payload = {
        "primary_source": getattr(article, "primary_source", None),
        "journal": getattr(article, "journal", None),
        "year": getattr(article, "year", None),
        "publication_date": getattr(article, "publication_date", None),
        "volume": getattr(article, "volume", None),
        "issue": getattr(article, "issue", None),
        "pages": getattr(article, "pages", None),
        "publisher": getattr(article, "publisher", None),
        "abstract": getattr(article, "abstract", None),
        "authors": authors,
        "sources": source_records,
    }
    serialized = json.dumps(fallback_payload, sort_keys=True, default=str, ensure_ascii=False)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:24]
    return f"fallback:{digest}"
