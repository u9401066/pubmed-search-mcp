"""Strict biomedical article identifier value objects.

The public tools previously normalized identifiers by deleting arbitrary
characters.  That could turn a DOI, typo, or prose fragment into a different
PMID.  These parsers are deliberately fail-closed: a value is either a valid
identifier in its entirety or it is rejected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import unquote, urlsplit

MAX_IDENTIFIER_CHARS = 512
MAX_PMID_DIGITS = 20
MAX_PMIDS_PER_REQUEST = 1_000
MAX_PMID_BATCH_CHARS = 100_000
_ASCII_CONTROL_LIMIT = 0x20

_PMID_RE = re.compile(rf"[1-9][0-9]{{0,{MAX_PMID_DIGITS - 1}}}")
_PMID_PREFIX_RE = re.compile(r"(?:pmid|pubmed)\s*:\s*", re.IGNORECASE)
_PMCID_RE = re.compile(rf"(?:pmcid\s*:\s*)?(?:pmc)?([1-9][0-9]{{0,{MAX_PMID_DIGITS - 1}}})", re.IGNORECASE)
_DOI_RE = re.compile(r"10\.[0-9]{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
_BATCH_SEPARATOR_RE = re.compile(r"[,;|\s]+")


class IdentifierValidationError(ValueError):
    """Raised when an article identifier is malformed or ambiguous."""


@dataclass(frozen=True, slots=True)
class ArticleIdentifier:
    """A validated, canonical article identifier."""

    kind: Literal["pmid", "pmcid", "doi"]
    value: str


def _bounded_text(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise IdentifierValidationError(f"{label} must be a string")
    text = value.strip()
    if not text:
        raise IdentifierValidationError(f"{label} is empty")
    if len(text) > MAX_IDENTIFIER_CHARS:
        raise IdentifierValidationError(f"{label} exceeds {MAX_IDENTIFIER_CHARS} characters")
    if any(ord(char) < _ASCII_CONTROL_LIMIT or char == "\x7f" for char in text):
        raise IdentifierValidationError(f"{label} contains control characters")
    return text


def normalize_pmid(value: object) -> str:
    """Return one canonical PMID or raise on malformed/ambiguous input."""
    if isinstance(value, bool):
        raise IdentifierValidationError("PMID must not be boolean")
    if isinstance(value, int):
        text = str(value)
    else:
        text = _bounded_text(value, label="PMID")
        text = _PMID_PREFIX_RE.sub("", text, count=1)
    if _PMID_RE.fullmatch(text) is None:
        raise IdentifierValidationError("PMID must be positive ASCII digits with an optional PMID: prefix")
    return text


def try_normalize_pmid(value: object) -> str | None:
    """Return a canonical PMID, or ``None`` for invalid input."""
    try:
        return normalize_pmid(value)
    except IdentifierValidationError:
        return None


def normalize_pmcid(value: object) -> str:
    """Return a canonical ``PMC<digits>`` identifier."""
    if isinstance(value, bool):
        raise IdentifierValidationError("PMCID must not be boolean")
    text = str(value) if isinstance(value, int) else _bounded_text(value, label="PMCID")
    match = _PMCID_RE.fullmatch(text.strip())
    if match is None:
        raise IdentifierValidationError("PMCID must be positive ASCII digits with an optional PMC/PMCID: prefix")
    return f"PMC{match.group(1)}"


def try_normalize_pmcid(value: object) -> str | None:
    """Return a canonical PMCID, or ``None`` for invalid input."""
    try:
        return normalize_pmcid(value)
    except IdentifierValidationError:
        return None


def normalize_doi(value: object) -> str:
    """Return a canonical DOI while rejecting URL parameters and fragments."""
    text = _bounded_text(value, label="DOI")
    lowered = text.lower()
    if lowered.startswith("doi:"):
        text = text[4:].strip()
    elif "://" in text:
        parsed = urlsplit(text)
        if parsed.scheme.lower() not in {"http", "https"}:
            raise IdentifierValidationError("DOI URL must use HTTP or HTTPS")
        if parsed.username or parsed.password or parsed.port is not None:
            raise IdentifierValidationError("DOI URL must not contain credentials or a port")
        if (parsed.hostname or "").lower() not in {"doi.org", "dx.doi.org"}:
            raise IdentifierValidationError("DOI URL host must be doi.org")
        if parsed.query or parsed.fragment:
            raise IdentifierValidationError("DOI URL must not contain a query or fragment")
        text = unquote(parsed.path.lstrip("/"))

    text = text.strip().lower()
    if len(text) > MAX_IDENTIFIER_CHARS or _DOI_RE.fullmatch(text) is None:
        raise IdentifierValidationError("DOI does not match the canonical 10.<registrant>/<suffix> form")
    return text


def try_normalize_doi(value: object) -> str | None:
    """Return a canonical DOI, or ``None`` for invalid input."""
    try:
        return normalize_doi(value)
    except IdentifierValidationError:
        return None


def normalize_pmid_batch(value: object, *, allow_last: bool = True) -> list[str]:
    """Parse a bounded PMID batch without silently dropping malformed tokens."""
    if value is None:
        return []
    if isinstance(value, bool):
        raise IdentifierValidationError("PMID batch must not contain booleans")
    if isinstance(value, int):
        return [normalize_pmid(value)]
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_PMIDS_PER_REQUEST:
            raise IdentifierValidationError(f"PMID batch exceeds {MAX_PMIDS_PER_REQUEST} values")
        combined: list[str] = []
        for item in value:
            combined.extend(normalize_pmid_batch(item, allow_last=allow_last))
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if len(text) > MAX_PMID_BATCH_CHARS:
            raise IdentifierValidationError(f"PMID batch exceeds {MAX_PMID_BATCH_CHARS} characters")
        if text.casefold() == "last":
            if not allow_last:
                raise IdentifierValidationError("last is not a PMID")
            return ["last"]
        without_prefixes = _PMID_PREFIX_RE.sub("", text)
        tokens = [token for token in _BATCH_SEPARATOR_RE.split(without_prefixes) if token]
        if not tokens:
            return []
        combined = [normalize_pmid(token) for token in tokens]
    else:
        raise IdentifierValidationError("PMID batch must be a string, integer, or list")

    if len(combined) > MAX_PMIDS_PER_REQUEST:
        raise IdentifierValidationError(f"PMID batch exceeds {MAX_PMIDS_PER_REQUEST} values")
    if "last" in combined and len(combined) != 1:
        raise IdentifierValidationError("last cannot be combined with explicit PMIDs")
    return list(dict.fromkeys(combined))


def parse_article_identifier(value: object) -> ArticleIdentifier:
    """Parse one PMID, PMCID, or DOI without extracting substrings."""
    if isinstance(value, bool) or value is None:
        raise IdentifierValidationError("article identifier is missing")
    if isinstance(value, int):
        return ArticleIdentifier("pmid", normalize_pmid(value))
    text = _bounded_text(value, label="article identifier")
    lowered = text.casefold()
    if lowered.startswith(("pmc", "pmcid")):
        return ArticleIdentifier("pmcid", normalize_pmcid(text))
    if lowered.startswith(("10.", "doi:")) or "://" in text:
        return ArticleIdentifier("doi", normalize_doi(text))
    return ArticleIdentifier("pmid", normalize_pmid(text))


__all__ = [
    "ArticleIdentifier",
    "IdentifierValidationError",
    "MAX_IDENTIFIER_CHARS",
    "MAX_PMID_BATCH_CHARS",
    "MAX_PMID_DIGITS",
    "MAX_PMIDS_PER_REQUEST",
    "normalize_doi",
    "normalize_pmcid",
    "normalize_pmid",
    "normalize_pmid_batch",
    "parse_article_identifier",
    "try_normalize_doi",
    "try_normalize_pmcid",
    "try_normalize_pmid",
]
