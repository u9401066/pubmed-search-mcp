"""
Unified Search — Enrichment Module.

Contains functions that enrich articles with additional metadata from external
APIs: CrossRef, OpenAlex journal metrics, Unpaywall OA links, similarity scores,
and preprint detection.

Extracted from unified.py to keep each module under 400 lines.
"""

from __future__ import annotations

import asyncio
import logging

from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.infrastructure.sources import (
    get_crossref_client,
    get_openalex_client,
    get_unpaywall_client,
)

logger = logging.getLogger(__name__)


# ============================================================================
# CrossRef Enrichment
# ============================================================================


async def _enrich_with_crossref(articles: list[UnifiedArticle]) -> None:
    """Enrich articles with CrossRef metadata (in-place, parallel)."""
    try:
        client = get_crossref_client()

        # Filter articles that need enrichment
        articles_to_enrich = [
            (i, article) for i, article in enumerate(articles) if article.doi and not article.citation_metrics
        ]

        if not articles_to_enrich:
            return

        # Limit to avoid too many parallel requests
        max_parallel = 10
        articles_to_enrich = articles_to_enrich[:max_parallel]

        async def fetch_crossref(idx: int, article: UnifiedArticle) -> tuple[int, dict | None]:
            try:
                doi = article.doi
                if not doi:
                    return (idx, None)
                work = await client.get_work(doi)
                return (idx, work)
            except Exception:
                return (idx, None)

        # Parallel fetch with asyncio.gather
        results = await asyncio.gather(
            *[fetch_crossref(idx, article) for idx, article in articles_to_enrich],
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                logger.debug(f"CrossRef enrichment skipped: {result}")
                continue
            # Type narrowing: result is now tuple, not Exception
            idx, work = result  # type: ignore[misc]
            if work:
                try:
                    crossref_article = UnifiedArticle.from_crossref(work)
                    articles[idx].merge_from(crossref_article)
                except Exception as e:
                    logger.debug(f"CrossRef enrichment skipped: {e}")

    except Exception as e:
        logger.warning(f"CrossRef enrichment failed: {e}")


# ============================================================================
# Journal Metrics Enrichment (OpenAlex Sources API)
# ============================================================================


async def _enrich_with_journal_metrics(articles: list[UnifiedArticle]) -> None:
    """Enrich articles with journal-level metrics from OpenAlex Sources API (in-place).

    Fetches journal h-index, 2yr_mean_citedness (≈ Impact Factor), ISSN, DOAJ status,
    subject areas, etc. Uses batch API for efficiency.

    Strategy:
    1. Collect OpenAlex source IDs from articles that came from OpenAlex
    2. Batch-fetch source metadata
    3. For articles without source IDs, skip (no reliable lookup available)
    4. Create JournalMetrics objects and assign to articles
    """
    from pubmed_search.domain.entities.article import JournalMetrics

    try:
        client = get_openalex_client()

        # Collect unique source IDs from OpenAlex-sourced articles
        # Source ID is stored in raw_data._openalex_source_id
        source_id_to_articles: dict[str, list[int]] = {}  # source_id → [article_idx]

        for i, article in enumerate(articles):
            if article.journal_metrics:
                continue  # Already enriched

            source_id = _extract_openalex_source_id(article)
            if source_id:
                clean_id = source_id.replace("https://openalex.org/", "")
                if clean_id not in source_id_to_articles:
                    source_id_to_articles[clean_id] = []
                source_id_to_articles[clean_id].append(i)

        if not source_id_to_articles:
            return

        # Batch fetch all unique sources
        source_data = await client.get_sources_batch(list(source_id_to_articles.keys()))

        # Map source data to articles
        for source_id, article_indices in source_id_to_articles.items():
            data = source_data.get(source_id)
            if not data:
                continue

            journal_metrics = JournalMetrics(
                issn=data.get("issn"),
                issn_l=data.get("issn_l"),
                openalex_source_id=data.get("openalex_source_id"),
                h_index=data.get("h_index"),
                two_year_mean_citedness=data.get("two_year_mean_citedness"),
                i10_index=data.get("i10_index"),
                works_count=data.get("works_count"),
                cited_by_count=data.get("cited_by_count"),
                is_in_doaj=data.get("is_in_doaj"),
                source_type=data.get("source_type"),
                subject_areas=data.get("subject_areas", []),
            )

            for idx in article_indices:
                articles[idx].journal_metrics = journal_metrics

        enriched = sum(1 for a in articles if a.journal_metrics is not None)
        if enriched > 0:
            logger.info(
                f"Journal metrics: enriched {enriched}/{len(articles)} articles from {len(source_data)} unique journals"
            )

    except Exception as e:
        logger.warning(f"Journal metrics enrichment failed: {e}")


def _extract_openalex_source_id(article: UnifiedArticle) -> str | None:
    """Extract OpenAlex source ID from an article's metadata.

    Checks:
    1. raw_data._openalex_source_id (set by OpenAlex _normalize_work)
    2. raw_data.primary_location.source.id (direct OpenAlex response)
    """
    for source_meta in article.sources:
        if source_meta.source == "openalex" and source_meta.raw_data:
            raw = source_meta.raw_data
            # Check _openalex_source_id (set in _normalize_work)
            if raw.get("_openalex_source_id"):
                return raw["_openalex_source_id"]
            # Fallback: check nested structure
            location = raw.get("primary_location", {})
            if isinstance(location, dict):
                source = location.get("source", {})
                if isinstance(source, dict) and source.get("id"):
                    return source["id"]
    return None


# ============================================================================
# Unpaywall OA Link Enrichment
# ============================================================================


async def _enrich_with_unpaywall(articles: list[UnifiedArticle]) -> None:
    """Enrich articles with Unpaywall OA links (in-place, parallel)."""
    try:
        client = get_unpaywall_client()

        # Filter articles that need enrichment
        articles_to_enrich = [
            (i, article) for i, article in enumerate(articles) if article.doi and not article.has_open_access
        ]

        if not articles_to_enrich:
            return

        # Limit to avoid too many parallel requests
        max_parallel = 10
        articles_to_enrich = articles_to_enrich[:max_parallel]

        async def fetch_unpaywall(idx: int, article: UnifiedArticle) -> tuple[int, dict | None]:
            try:
                doi = article.doi
                if not doi:
                    return (idx, None)
                oa_info = await client.enrich_article(doi)
                return (idx, oa_info if oa_info.get("is_oa") else None)
            except Exception:
                return (idx, None)

        # Parallel fetch with asyncio.gather
        results = await asyncio.gather(
            *[fetch_unpaywall(idx, article) for idx, article in articles_to_enrich],
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                logger.debug(f"Unpaywall enrichment skipped: {result}")
                continue
            # Type narrowing: result is now tuple, not Exception
            idx, oa_info = result  # type: ignore[misc]
            if oa_info:
                try:
                    from pubmed_search.domain.entities.article import (
                        OpenAccessLink,
                        OpenAccessStatus,
                    )

                    articles[idx].is_open_access = True

                    # Map OA status
                    status_map = {
                        "gold": OpenAccessStatus.GOLD,
                        "green": OpenAccessStatus.GREEN,
                        "hybrid": OpenAccessStatus.HYBRID,
                        "bronze": OpenAccessStatus.BRONZE,
                    }
                    articles[idx].oa_status = status_map.get(
                        oa_info.get("oa_status", "unknown"),
                        OpenAccessStatus.UNKNOWN,
                    )

                    # Add OA links
                    for link_data in oa_info.get("oa_links", []):
                        if link_data.get("url"):
                            articles[idx].oa_links.append(
                                OpenAccessLink(
                                    url=link_data["url"],
                                    version=link_data.get("version", "unknown"),
                                    host_type=link_data.get("host_type"),
                                    license=link_data.get("license"),
                                    is_best=link_data.get("is_best", False),
                                )
                            )
                except Exception as e:
                    logger.debug(f"Unpaywall enrichment skipped: {e}")

    except Exception as e:
        logger.warning(f"Unpaywall enrichment failed: {e}")


# ============================================================================
# Preprint Detection
# ============================================================================


def _is_preprint(article: UnifiedArticle, _article_type_class: type) -> bool:  # type: ignore[type-arg]
    """
    Determine if an article is a non-peer-reviewed preprint.

    Detection heuristics (ordered by confidence):
    1. article_type is PREPRINT (detected from OpenAlex/CrossRef/S2)
    2. Has arXiv ID but no PubMed ID (arXiv-only paper)
    3. Primary source is a known preprint server
    4. DOI prefix matches known preprint servers
    5. Journal name matches known preprint servers

    Returns:
        True if the article is likely a preprint (not peer-reviewed).
    """
    # Check article type
    if article.article_type == _article_type_class.PREPRINT:  # type: ignore[attr-defined]
        return True

    # Has arXiv ID but no PubMed ID → likely preprint
    if getattr(article, "arxiv_id", None) and not article.pmid:
        return True

    # Primary source is a preprint server
    preprint_sources = {"arxiv", "medrxiv", "biorxiv", "chemrxiv", "ssrn", "preprints.org", "research square"}
    if article.primary_source and article.primary_source.lower() in preprint_sources:
        return True

    # DOI prefix matches known preprint servers
    doi = article.doi or ""
    if doi:
        doi_lower = doi.lower()
        # 10.1101/ → bioRxiv/medRxiv
        # 10.48550/ → arXiv
        # 10.26434/ → chemRxiv
        # 10.2139/ → SSRN
        # 10.20944/ → Preprints.org
        # 10.21203/ → Research Square
        preprint_doi_prefixes = (
            "10.1101/",
            "10.48550/",
            "10.26434/",
            "10.2139/",
            "10.20944/",
            "10.21203/",
        )
        if any(doi_lower.startswith(prefix) for prefix in preprint_doi_prefixes):
            return True

    # Journal name matches known preprint servers
    journal = (article.journal or "").lower()
    if journal:
        preprint_journal_names = (
            "arxiv",
            "medrxiv",
            "biorxiv",
            "chemrxiv",
            "ssrn",
            "preprints",
            "research square",
        )
        if any(name in journal for name in preprint_journal_names):
            return True

    return False


# ============================================================================
# Similarity Score Enrichment
# ============================================================================


def _enrich_with_similarity_scores(
    articles: list[UnifiedArticle],
    query: str,
) -> None:
    """
    Enrich articles with similarity scores using external APIs (in-place).

    Uses a ranking-based approach:
    - First article from each source gets highest similarity (1.0)
    - Subsequent articles get linearly decreasing scores

    For cross-source similarity, we use the article's ranking position.

    Args:
        articles: Articles to enrich
        query: Original search query (for context)
    """
    try:
        if not articles:
            return

        # Calculate similarity scores based on ranking position
        # This is a simple but effective approach:
        # - Search engines already rank by relevance
        # - We convert ranking position to 0-1 score

        total = len(articles)
        for i, article in enumerate(articles):
            # Base similarity from ranking position
            # First result = 1.0, last = 0.1 (never 0)
            base_score = max(0.1, 1.0 - (i * 0.9 / max(total - 1, 1)))

            # Adjust based on source trust (PubMed results generally more relevant)
            source_boost = {
                "pubmed": 0.1,
                "semantic_scholar": 0.05,
                "openalex": 0.03,
                "crossref": 0.0,
            }
            boost = source_boost.get(article.primary_source, 0.0)

            # Calculate final score (cap at 1.0)
            final_score = min(1.0, base_score + boost)

            # Set similarity fields
            article.similarity_score = round(final_score, 3)
            article.similarity_source = "ranking"
            article.similarity_details = {
                "ranking_score": round(base_score, 3),
                "source_boost": boost,
                "position": i + 1,
            }

        logger.debug(f"Enriched {len(articles)} articles with similarity scores")

    except Exception as e:
        logger.warning(f"Similarity enrichment failed: {e}")


async def _enrich_with_api_similarity(
    articles: list[UnifiedArticle],
    seed_pmid: str | None = None,
) -> None:
    """
    Enrich articles with similarity scores from external APIs.

    Uses Semantic Scholar recommendations and Europe PMC similar articles
    to get pre-computed similarity scores when available.

    Args:
        articles: Articles to enrich
        seed_pmid: Optional seed PMID for API-based similarity lookup
    """
    if not articles or not seed_pmid:
        return

    try:
        from pubmed_search.infrastructure.sources.semantic_scholar import (
            SemanticScholarClient,
        )

        s2_client = SemanticScholarClient()

        # Get recommendations based on seed article
        recommendations = await s2_client.get_recommendations(f"PMID:{seed_pmid}", limit=50)

        if not recommendations:
            return

        # Build lookup table: PMID/DOI -> similarity_score
        sim_lookup: dict[str, float] = {}
        for rec in recommendations:
            pmid = rec.get("pmid", "")
            doi = rec.get("doi", "")
            score = rec.get("similarity_score", 0.5)

            if pmid:
                sim_lookup[pmid] = score
            if doi:
                sim_lookup[doi.lower()] = score

        # Enrich articles with API-based similarity
        for article in articles:
            if article.pmid and article.pmid in sim_lookup:
                article.similarity_score = sim_lookup[article.pmid]
                article.similarity_source = "semantic_scholar"
            elif article.doi and article.doi.lower() in sim_lookup:
                article.similarity_score = sim_lookup[article.doi.lower()]
                article.similarity_source = "semantic_scholar"

        logger.debug("Enriched articles with API similarity scores")

    except Exception as e:
        logger.debug(f"API similarity enrichment skipped: {e}")
