"""Domain value object exports.

Design:
        This package gathers immutable domain concepts that carry validation and
        formatting rules but no persistence or transport behavior.

Maintenance:
        Re-export stable value objects here for ergonomic imports. Keep I/O helpers
        and infrastructure concerns outside the domain package.
"""

from __future__ import annotations

from .article_identifiers import (
    MAX_IDENTIFIER_CHARS,
    MAX_PMID_BATCH_CHARS,
    MAX_PMID_DIGITS,
    MAX_PMIDS_PER_REQUEST,
    ArticleIdentifier,
    IdentifierValidationError,
    normalize_doi,
    normalize_pmcid,
    normalize_pmid,
    normalize_pmid_batch,
    parse_article_identifier,
    try_normalize_doi,
    try_normalize_pmcid,
    try_normalize_pmid,
)
from .icd_codes import IcdCode, IcdCodeValidationError, IcdVersion, normalize_icd_code
from .ncbi_identifiers import (
    MAX_NCBI_IDENTIFIER_DIGITS,
    NcbiIdentifierValidationError,
    normalize_ncbi_identifier,
)

__all__ = [
    "ArticleIdentifier",
    "IdentifierValidationError",
    "IcdCode",
    "IcdCodeValidationError",
    "IcdVersion",
    "MAX_IDENTIFIER_CHARS",
    "MAX_NCBI_IDENTIFIER_DIGITS",
    "MAX_PMID_BATCH_CHARS",
    "MAX_PMID_DIGITS",
    "MAX_PMIDS_PER_REQUEST",
    "NcbiIdentifierValidationError",
    "normalize_doi",
    "normalize_icd_code",
    "normalize_pmcid",
    "normalize_pmid",
    "normalize_pmid_batch",
    "normalize_ncbi_identifier",
    "parse_article_identifier",
    "try_normalize_doi",
    "try_normalize_pmcid",
    "try_normalize_pmid",
]
