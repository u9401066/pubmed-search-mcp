"""Backward-compatible source article mapper exports.

The deterministic mapping helpers live in the domain service layer so domain
and application code do not depend on infrastructure modules. This wrapper
keeps the historical import path stable for adapters and external callers.
"""

from pubmed_search.domain.services.article_mapper import (
    article_from_core,
    article_from_crossref,
    article_from_europe_pmc,
    article_from_openalex,
    article_from_preprint,
    article_from_pubmed,
    article_from_scopus,
    article_from_semantic_scholar,
    article_from_web_of_science,
)

__all__ = [
    "article_from_core",
    "article_from_crossref",
    "article_from_europe_pmc",
    "article_from_openalex",
    "article_from_preprint",
    "article_from_pubmed",
    "article_from_scopus",
    "article_from_semantic_scholar",
    "article_from_web_of_science",
]
