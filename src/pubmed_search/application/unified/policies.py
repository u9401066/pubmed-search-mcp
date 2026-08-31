"""Pure post-retrieval policies shared by unified-search adapters."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pubmed_search.domain.entities.article import UnifiedArticle

logger = logging.getLogger(__name__)


def is_preprint(article: UnifiedArticle, article_type_class: type) -> bool:  # type: ignore[type-arg]
    """Return whether stable metadata heuristically identifies a preprint."""
    if article.article_type == article_type_class.PREPRINT:  # type: ignore[attr-defined]
        return True
    if getattr(article, "arxiv_id", None) and not article.pmid:
        return True

    preprint_sources = {
        "arxiv",
        "medrxiv",
        "biorxiv",
        "chemrxiv",
        "ssrn",
        "preprints.org",
        "research square",
    }
    if article.primary_source and article.primary_source.lower() in preprint_sources:
        return True

    doi = (article.doi or "").lower()
    if doi.startswith(("10.1101/", "10.48550/", "10.26434/", "10.2139/", "10.20944/", "10.21203/")):
        return True

    journal = (article.journal or "").lower()
    return bool(
        journal
        and any(
            name in journal
            for name in ("arxiv", "medrxiv", "biorxiv", "chemrxiv", "ssrn", "preprints", "research square")
        )
    )


def enrich_with_rank_percentiles(articles: list[UnifiedArticle]) -> None:
    """Attach an order-derived percentile without claiming semantic similarity."""
    try:
        if not articles:
            return
        total = len(articles)
        for index, article in enumerate(articles):
            article.rank_percentile = round((total - index) / total, 3)
            article.rank_percentile_source = "final_result_order"
            article.rank_percentile_details = {
                "rank_position": float(index + 1),
                "result_count": float(total),
            }
        logger.debug("Enriched %s articles with rank percentiles", len(articles))
    except Exception as exc:
        logger.warning("Rank-percentile enrichment failed (%s)", type(exc).__name__)


__all__ = ["enrich_with_rank_percentiles", "is_preprint"]
