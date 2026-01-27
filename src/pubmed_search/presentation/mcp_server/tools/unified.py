"""
Unified Search Tool - Single Entry Point for Multi-Source Academic Search

This is the MVP of the Unified Search Gateway (Phase 2.0).

Design Philosophy:
    單一入口 + 後端自動分流（像 Google 一樣）

    Old way (Agent must choose):
        search_literature() / search_europe_pmc() / search_core() / ...

    New way (Single entry point):
        unified_search(query) → Auto-dispatch to best sources

Architecture:
    User Query
         │
         ▼
    ┌──────────────────┐
    │  QueryAnalyzer   │  ← Determines complexity, detects PICO
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐
    │ DispatchStrategy │  ← Selects sources based on query type
    └────────┬─────────┘
             │
    ┌────────┴────────┬──────────┐
    ▼                 ▼          ▼
  PubMed          CrossRef    OpenAlex  (parallel or sequential)
    │                 │          │
    └────────┬────────┴──────────┘
             │
             ▼
    ┌──────────────────┐
    │ ResultAggregator │  ← Dedup + Multi-dimensional ranking
    └────────┬─────────┘
             │
             ▼
      UnifiedArticle[]

Features:
    - Automatic query analysis (complexity, intent, PICO)
    - Smart source selection based on query characteristics
    - Multi-source parallel search with deduplication
    - Configurable ranking (impact/recency/quality focused)
    - Transparent operation with analysis metadata
"""

import json
import logging
import re
from typing import Literal, Union

from mcp.server.fastmcp import FastMCP

from pubmed_search.application.search.query_analyzer import (
    AnalyzedQuery,
    QueryAnalyzer,
    QueryComplexity,
    QueryIntent,
)
from pubmed_search.application.search.result_aggregator import (
    AggregationStats,
    RankingConfig,
    ResultAggregator,
)
from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.infrastructure.ncbi import LiteratureSearcher
from pubmed_search.infrastructure.sources import (
    get_crossref_client,
    get_unpaywall_client,
    search_alternate_source,
)
from pubmed_search.infrastructure.sources.openurl import (
    get_openurl_config,
    get_openurl_link,
)
from pubmed_search.infrastructure.sources.preprints import PreprintSearcher

from .icd import lookup_icd_to_mesh
from ._common import InputNormalizer, ResponseFormatter

logger = logging.getLogger(__name__)


# ============================================================================
# ICD Code Detection and Conversion
# ============================================================================


# ICD-10 pattern: Letter + 2-3 digits + optional dot + more digits
ICD10_PATTERN = re.compile(r"\b([A-Z]\d{2}(?:\.\d{1,4})?)\b", re.IGNORECASE)
# ICD-9 pattern: 3-5 digits with optional dot
ICD9_PATTERN = re.compile(r"\b(\d{3}(?:\.\d{1,2})?)\b")


def detect_and_expand_icd_codes(query: str) -> tuple[str, list[dict]]:
    """
    Detect ICD codes in query and expand to MeSH terms.

    Args:
        query: Search query that may contain ICD codes

    Returns:
        Tuple of (expanded_query, icd_matches)
        - expanded_query: Query with ICD codes replaced/augmented by MeSH terms
        - icd_matches: List of detected ICD codes and their mappings
    """
    icd_matches: list[dict] = []

    # Detect ICD-10 codes
    for match in ICD10_PATTERN.finditer(query):
        code = match.group(1).upper()
        result = lookup_icd_to_mesh(code)
        if result:
            icd_matches.append(
                {
                    "code": code,
                    "type": "ICD-10",
                    "mesh": result["mesh"],
                    "description": result.get("description", ""),
                }
            )

    # Detect ICD-9 codes (3-digit numeric)
    for match in ICD9_PATTERN.finditer(query):
        code = match.group(1)
        # Only consider valid ICD-9 ranges (001-999)
        try:
            base = int(code.split(".")[0])
            if 1 <= base <= 999:
                result = lookup_icd_to_mesh(code)
                if result:
                    icd_matches.append(
                        {
                            "code": code,
                            "type": "ICD-9",
                            "mesh": result["mesh"],
                            "description": result.get("description", ""),
                        }
                    )
        except ValueError:
            pass

    if not icd_matches:
        return query, []

    # Build expanded query
    # Replace ICD codes with MeSH terms in the query
    expanded_query = query
    for icd in icd_matches:
        mesh_term = icd["mesh"]
        # Replace or augment the ICD code with MeSH
        expanded_query = re.sub(
            rf"\b{re.escape(icd['code'])}\b",
            f'("{mesh_term}"[MeSH] OR {icd["code"]})',
            expanded_query,
            flags=re.IGNORECASE,
        )

    logger.info(f"ICD codes detected: {[i['code'] for i in icd_matches]}")
    logger.info(f"Expanded query: {expanded_query}")

    return expanded_query, icd_matches


# ============================================================================
# Dispatch Strategy Matrix
# ============================================================================


class DispatchStrategy:
    """
    Determines which sources to query based on query analysis.

    Strategy Matrix:
    ┌─────────────────┬─────────────┬────────────────────────────────────┐
    │ Complexity      │ Intent      │ Sources                            │
    ├─────────────────┼─────────────┼────────────────────────────────────┤
    │ SIMPLE          │ LOOKUP      │ PubMed only (fast)                 │
    │ SIMPLE          │ EXPLORATION │ PubMed                             │
    │ MODERATE        │ *           │ PubMed + CrossRef enrichment       │
    │ COMPLEX         │ COMPARISON  │ PubMed + OpenAlex + S2             │
    │ COMPLEX         │ SYSTEMATIC  │ All sources (max coverage)         │
    │ AMBIGUOUS       │ *           │ PubMed + OpenAlex (broad)          │
    └─────────────────┴─────────────┴────────────────────────────────────┘
    """

    @staticmethod
    def get_sources(analysis: AnalyzedQuery) -> list[str]:
        """Get ordered list of sources to query."""
        complexity = analysis.complexity
        intent = analysis.intent

        # LOOKUP: Direct identifier search
        if intent == QueryIntent.LOOKUP:
            if analysis.identifiers:
                # Has identifiers - just PubMed
                return ["pubmed"]
            return ["pubmed", "crossref"]

        # SIMPLE: PubMed only for speed
        if complexity == QueryComplexity.SIMPLE:
            return ["pubmed"]

        # MODERATE: PubMed + CrossRef for DOI enrichment
        if complexity == QueryComplexity.MODERATE:
            return ["pubmed", "crossref"]

        # COMPLEX - depends on intent
        if complexity == QueryComplexity.COMPLEX:
            if intent == QueryIntent.COMPARISON:
                # Comparison needs diverse results
                return ["pubmed", "openalex", "semantic_scholar"]
            if intent == QueryIntent.SYSTEMATIC:
                # Systematic review needs maximum coverage
                return ["pubmed", "openalex", "semantic_scholar", "europe_pmc"]
            # Default complex
            return ["pubmed", "openalex", "crossref"]

        # AMBIGUOUS: Broad search
        if complexity == QueryComplexity.AMBIGUOUS:
            return ["pubmed", "openalex"]

        # Default fallback
        return ["pubmed"]

    @staticmethod
    def get_ranking_config(analysis: AnalyzedQuery) -> RankingConfig:
        """Get ranking configuration based on query analysis."""
        intent = analysis.intent

        # SYSTEMATIC: Quality focused (favor RCTs, meta-analyses)
        if intent == QueryIntent.SYSTEMATIC:
            return RankingConfig.quality_focused()

        # COMPARISON: Impact focused (favor high-cited comparative studies)
        if intent == QueryIntent.COMPARISON:
            return RankingConfig.impact_focused()

        # EXPLORATION with recent constraint: Recency focused
        if intent == QueryIntent.EXPLORATION and analysis.year_from:
            return RankingConfig.recency_focused()

        # Default: Balanced
        return RankingConfig.default()

    @staticmethod
    def should_enrich_with_unpaywall(analysis: AnalyzedQuery) -> bool:
        """Determine if results should be enriched with Unpaywall OA links."""
        # Always enrich for systematic reviews (need full text)
        if analysis.intent == QueryIntent.SYSTEMATIC:
            return True
        # Enrich for complex queries
        if analysis.complexity == QueryComplexity.COMPLEX:
            return True
        return False


# ============================================================================
# Source Search Functions
# ============================================================================


def _search_pubmed(
    searcher: LiteratureSearcher,
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    **advanced_filters,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search PubMed and convert to UnifiedArticle.

    Returns:
        Tuple of (articles, total_count) where total_count is the total
        number of matching articles in PubMed (not just returned count).

    Advanced Filters (passed via **advanced_filters):
        age_group: newborn, infant, child, adolescent, adult, aged, etc.
        sex: male, female
        species: humans, animals
        language: english, chinese, japanese, etc.
        clinical_query: therapy, diagnosis, prognosis, etiology
    """
    try:
        results = searcher.search(
            query=query,
            limit=limit,
            min_year=min_year,
            max_year=max_year,
            **advanced_filters,  # Pass all advanced filters
        )

        # Extract total_count from metadata (if present)
        total_count = None
        if results and "_search_metadata" in results[0]:
            total_count = results[0]["_search_metadata"].get("total_count")
            del results[0]["_search_metadata"]
            # Remove empty dict if only metadata was present
            if not results[0] or results[0] == {}:
                results = results[1:] if len(results) > 1 else []

        articles = []
        for r in results:
            if r and "error" not in r:  # Skip error entries
                articles.append(UnifiedArticle.from_pubmed(r))

        return articles, total_count
    except Exception as e:
        logger.error(f"PubMed search failed: {e}")
        return [], None


def _search_openalex(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search OpenAlex and convert to UnifiedArticle.

    Returns:
        Tuple of (articles, total_count).
    """
    try:
        results = search_alternate_source(
            query=query,
            source="openalex",
            limit=limit,
            min_year=min_year,
            max_year=max_year,
        )

        articles = []
        for r in results:
            articles.append(UnifiedArticle.from_openalex(r))

        # OpenAlex doesn't return total count in our current implementation
        return articles, None
    except Exception as e:
        logger.error(f"OpenAlex search failed: {e}")
        return [], None


def _search_semantic_scholar(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search Semantic Scholar and convert to UnifiedArticle.

    Returns:
        Tuple of (articles, total_count).
    """
    try:
        results = search_alternate_source(
            query=query,
            source="semantic_scholar",
            limit=limit,
            min_year=min_year,
            max_year=max_year,
        )

        articles = []
        for r in results:
            articles.append(UnifiedArticle.from_semantic_scholar(r))

        # Semantic Scholar doesn't return total count in our current implementation
        return articles, None
    except Exception as e:
        logger.error(f"Semantic Scholar search failed: {e}")
        return [], None


def _enrich_with_crossref(articles: list[UnifiedArticle]) -> None:
    """Enrich articles with CrossRef metadata (in-place, parallel)."""
    try:
        client = get_crossref_client()

        # Filter articles that need enrichment
        articles_to_enrich = [
            (i, article)
            for i, article in enumerate(articles)
            if article.doi and not article.citation_metrics
        ]

        if not articles_to_enrich:
            return

        # Limit to avoid too many parallel requests
        MAX_PARALLEL = 10
        articles_to_enrich = articles_to_enrich[:MAX_PARALLEL]

        from concurrent.futures import ThreadPoolExecutor, as_completed

        def fetch_crossref(
            idx_article: tuple[int, UnifiedArticle],
        ) -> tuple[int, dict | None]:
            idx, article = idx_article
            try:
                doi = article.doi
                if not doi:
                    return (idx, None)
                work = client.get_work(doi)
                return (idx, work)
            except Exception:
                return (idx, None)

        # Parallel fetch
        with ThreadPoolExecutor(
            max_workers=min(5, len(articles_to_enrich))
        ) as executor:
            futures = {
                executor.submit(fetch_crossref, item): item
                for item in articles_to_enrich
            }

            for future in as_completed(futures):
                try:
                    idx, work = future.result()
                    if work:
                        crossref_article = UnifiedArticle.from_crossref(work)
                        articles[idx].merge_from(crossref_article)
                except Exception as e:
                    logger.debug(f"CrossRef enrichment skipped: {e}")

    except Exception as e:
        logger.warning(f"CrossRef enrichment failed: {e}")


def _enrich_with_unpaywall(articles: list[UnifiedArticle]) -> None:
    """Enrich articles with Unpaywall OA links (in-place, parallel)."""
    try:
        client = get_unpaywall_client()

        # Filter articles that need enrichment
        articles_to_enrich = [
            (i, article)
            for i, article in enumerate(articles)
            if article.doi and not article.has_open_access
        ]

        if not articles_to_enrich:
            return

        # Limit to avoid too many parallel requests
        MAX_PARALLEL = 10
        articles_to_enrich = articles_to_enrich[:MAX_PARALLEL]

        from concurrent.futures import ThreadPoolExecutor, as_completed

        def fetch_unpaywall(
            idx_article: tuple[int, UnifiedArticle],
        ) -> tuple[int, dict | None]:
            idx, article = idx_article
            try:
                doi = article.doi
                if not doi:
                    return (idx, None)
                oa_info = client.enrich_article(doi)
                return (idx, oa_info if oa_info.get("is_oa") else None)
            except Exception:
                return (idx, None)

        # Parallel fetch
        with ThreadPoolExecutor(
            max_workers=min(5, len(articles_to_enrich))
        ) as executor:
            futures = {
                executor.submit(fetch_unpaywall, item): item
                for item in articles_to_enrich
            }

            for future in as_completed(futures):
                try:
                    idx, oa_info = future.result()
                    if oa_info:
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


def _enrich_with_api_similarity(
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
        recommendations = s2_client.get_recommendations(f"PMID:{seed_pmid}", limit=50)

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


# ============================================================================
# Result Formatting
# ============================================================================


def _format_unified_results(
    articles: list[UnifiedArticle],
    analysis: AnalyzedQuery,
    stats: AggregationStats,
    include_analysis: bool = True,
    pubmed_total_count: int | None = None,
    icd_matches: list | None = None,
    preprint_results: dict | None = None,
    include_trials: bool = True,
    original_query: str = "",
) -> str:
    """Format unified search results for MCP response."""
    output_parts: list[str] = []

    # Header with analysis summary
    if include_analysis:
        output_parts.append("## 🔍 Unified Search Results\n")
        output_parts.append(f"**Query**: {analysis.original_query}")
        output_parts.append(
            f"**Analysis**: {analysis.complexity.value} complexity, {analysis.intent.value} intent"
        )
        if analysis.pico:
            pico_str = ", ".join(
                f"{k}={v}" for k, v in analysis.pico.to_dict().items() if v
            )
            output_parts.append(f"**PICO**: {pico_str}")

        # ICD code expansion info
        if icd_matches:
            icd_info = ", ".join([f"{m['code']}→{m['mesh']}" for m in icd_matches])
            output_parts.append(f"**ICD Expansion**: {icd_info}")

        output_parts.append(f"**Sources**: {', '.join(stats.by_source.keys())}")

        # Show total count info with PubMed total
        results_str = f"{stats.unique_articles} unique ({stats.duplicates_removed} duplicates removed)"
        if (
            pubmed_total_count is not None
            and pubmed_total_count > stats.unique_articles
        ):
            results_str = f"📊 返回 **{stats.unique_articles}** 篇 (PubMed 總共 **{pubmed_total_count}** 篇符合) | {stats.duplicates_removed} 去重"
        output_parts.append(f"**Results**: {results_str}")
        output_parts.append("")

    # Articles
    if not articles:
        output_parts.append("No results found.")
        return "\n".join(output_parts)

    output_parts.append("---\n")

    for i, article in enumerate(articles, 1):
        # Article header
        score_str = (
            f" (score: {article._ranking_score:.2f})" if article._ranking_score else ""
        )
        output_parts.append(f"### {i}. {article.title}{score_str}")

        # Identifiers
        ids = []
        if article.pmid:
            ids.append(f"PMID: {article.pmid}")
        if article.doi:
            ids.append(f"DOI: {article.doi}")
        if article.pmc:
            ids.append(f"PMC: {article.pmc}")
        if ids:
            output_parts.append(" | ".join(ids))

        # Study type badge (from PubMed publication_types, not hard-coded inference)
        from pubmed_search.domain.entities.article import ArticleType

        if article.article_type and article.article_type != ArticleType.UNKNOWN:
            # Evidence level badge based on study type
            type_badges = {
                ArticleType.META_ANALYSIS: "🟢 Meta-Analysis (1a)",
                ArticleType.SYSTEMATIC_REVIEW: "🟢 Systematic Review (1a)",
                ArticleType.RANDOMIZED_CONTROLLED_TRIAL: "🟢 RCT (1b)",
                ArticleType.CLINICAL_TRIAL: "🟡 Clinical Trial (1b-2b)",
                ArticleType.REVIEW: "⚪ Review",
                ArticleType.CASE_REPORT: "🟠 Case Report (4)",
            }
            badge = type_badges.get(
                article.article_type, f"📄 {article.article_type.value}"
            )
            output_parts.append(f"**Type**: {badge}")

        # Authors and journal
        output_parts.append(f"**Authors**: {article.author_string}")
        if article.journal:
            journal_str = article.journal
            if article.year:
                journal_str += f" ({article.year})"
            if article.volume:
                journal_str += f"; {article.volume}"
                if article.issue:
                    journal_str += f"({article.issue})"
            if article.pages:
                journal_str += f": {article.pages}"
            output_parts.append(f"**Journal**: {journal_str}")

        # Open Access status
        if article.has_open_access:
            oa_link = article.best_oa_link
            if oa_link:
                output_parts.append(
                    f"**OA**: ✅ [{article.oa_status.value}]({oa_link.url})"
                )
            else:
                output_parts.append(f"**OA**: ✅ {article.oa_status.value}")

        # Institutional access link (OpenURL)
        openurl_config = get_openurl_config()
        if openurl_config.enabled and (
            openurl_config.resolver_base or openurl_config.preset
        ):
            openurl = get_openurl_link(
                {
                    "pmid": article.pmid,
                    "doi": article.doi,
                    "title": article.title,
                    "journal": article.journal,
                    "year": article.year,
                    "volume": article.volume,
                    "issue": article.issue,
                    "pages": article.pages,
                }
            )
            if openurl:
                output_parts.append(f"**Library**: 🏛️ [Find via Library]({openurl})")

        # Citation metrics
        if article.citation_metrics:
            metrics = article.citation_metrics
            metric_parts = []
            if metrics.citation_count is not None:
                metric_parts.append(f"Citations: {metrics.citation_count}")
            if metrics.nih_percentile is not None:
                metric_parts.append(f"Percentile: {metrics.nih_percentile:.0f}%")
            if metrics.relative_citation_ratio is not None:
                metric_parts.append(f"RCR: {metrics.relative_citation_ratio:.2f}")
            if metric_parts:
                output_parts.append(f"**Impact**: {', '.join(metric_parts)}")

        # Similarity score
        if article.similarity_score is not None:
            sim_str = f"**Relevance**: {article.similarity_score:.0%}"
            if article.similarity_source:
                sim_str += f" ({article.similarity_source})"
            output_parts.append(sim_str)

        # Abstract (truncated)
        if article.abstract:
            abstract = article.abstract
            if len(abstract) > 300:
                abstract = abstract[:300] + "..."
            output_parts.append(f"\n{abstract}")

        # Sources
        sources = [s.source for s in article.sources]
        output_parts.append(f"\n*Sources: {', '.join(sources)}*")
        output_parts.append("")

    # === Preprint Results Section ===
    if preprint_results and preprint_results.get("total", 0) > 0:
        output_parts.append("\n---")
        output_parts.append("\n## 📄 Preprints (Not Peer-Reviewed)\n")
        for src, papers in preprint_results.get("by_source", {}).items():
            if papers:
                output_parts.append(f"### {src.upper()} ({len(papers)} results)")
                for j, paper in enumerate(papers[:5], 1):  # Show max 5 per source
                    output_parts.append(f"\n**{j}. {paper.get('title', 'N/A')}**")
                    if paper.get("authors"):
                        authors_str = ", ".join(paper["authors"][:3])
                        if len(paper["authors"]) > 3:
                            authors_str += " et al."
                        output_parts.append(
                            f"*{authors_str}* ({paper.get('published', 'N/A')})"
                        )
                    if paper.get("pdf_url"):
                        output_parts.append(f"PDF: {paper['pdf_url']}")
                    if paper.get("source_url"):
                        output_parts.append(f"Link: {paper['source_url']}")
                output_parts.append("")

    # === Related Clinical Trials (optional) ===
    if include_trials and original_query:
        try:
            from pubmed_search.infrastructure.sources.clinical_trials import (
                format_trials_section,
                search_related_trials,
            )

            # Get first few words of query for trial search
            trial_query = " ".join(original_query.split()[:5])
            trials = search_related_trials(trial_query, limit=3)
            if trials:
                output_parts.append(format_trials_section(trials, max_display=3))
        except Exception as e:
            logger.debug(f"Clinical trials search skipped: {e}")

    return "\n".join(output_parts)


def _format_as_json(
    articles: list[UnifiedArticle],
    analysis: AnalyzedQuery,
    stats: AggregationStats,
) -> str:
    """Format results as JSON for programmatic access."""
    return json.dumps(
        {
            "analysis": analysis.to_dict(),
            "statistics": stats.to_dict(),
            "articles": [a.to_dict() for a in articles],
        },
        ensure_ascii=False,
        indent=2,
    )


# ============================================================================
# MCP Tool Registration
# ============================================================================


def register_unified_search_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """Register unified search MCP tools."""

    @mcp.tool()
    def unified_search(
        query: str,
        limit: Union[int, str] = 10,
        min_year: Union[int, str, None] = None,
        max_year: Union[int, str, None] = None,
        ranking: Literal["balanced", "impact", "recency", "quality"] = "balanced",
        output_format: Literal["markdown", "json"] = "markdown",
        include_oa_links: Union[bool, str] = True,
        show_analysis: Union[bool, str] = True,
        # Similarity scores (Phase 5.10)
        include_similarity_scores: Union[bool, str] = True,
        # Advanced filters (Phase 2.1)
        age_group: Union[str, None] = None,
        sex: Union[str, None] = None,
        species: Union[str, None] = None,
        language: Union[str, None] = None,
        clinical_query: Union[str, None] = None,
        # Preprint search (Phase 2.2)
        include_preprints: Union[bool, str] = False,
    ) -> str:
        """
        🔍 Unified Search - Single entry point for multi-source academic search.

        Automatically analyzes your query and searches the best sources.
        No need to choose between PubMed, OpenAlex, CrossRef, etc.

        ═══════════════════════════════════════════════════════════════════
        WHAT IT DOES:
        ═══════════════════════════════════════════════════════════════════
        1. Analyzes your query (complexity, intent, PICO elements)
        2. Automatically selects best sources based on query type
        3. Searches multiple sources in parallel
        4. Deduplicates and merges results
        5. Ranks by configurable criteria
        6. Enriches with OA links (Unpaywall)
        7. Auto-detects ICD-9/10 codes and expands to MeSH terms
        8. Optionally searches preprints (arXiv, medRxiv, bioRxiv)

        ═══════════════════════════════════════════════════════════════════
        EXAMPLES:
        ═══════════════════════════════════════════════════════════════════

        Simple lookup:
            unified_search("PMID:12345678")
            → PubMed only, fast

        Topic exploration:
            unified_search("machine learning in anesthesia", limit=20)
            → PubMed + CrossRef enrichment

        Clinical comparison:
            unified_search("remimazolam vs propofol for ICU sedation")
            → Multi-source, PICO detected, impact-ranked

        Systematic review prep:
            unified_search("CRISPR gene therapy cancer", ranking="quality")
            → All sources, quality-ranked, OA links

        Advanced clinical filters:
            unified_search("diabetes treatment", age_group="aged", clinical_query="therapy")
            → Only elderly population studies with therapy filter

            unified_search("breast cancer screening", sex="female", species="humans")
            → Female human studies only

        ICD Code Auto-Detection:
            unified_search("E11 complications")
            → Auto-expands E11 to "Diabetes Mellitus, Type 2"[MeSH]

            unified_search("I21 treatment outcomes")
            → Auto-expands I21 to "Myocardial Infarction"[MeSH]

        Preprint Search:
            unified_search("COVID-19 vaccine efficacy", include_preprints=True)
            → Also searches arXiv, medRxiv, bioRxiv

        Args:
            query: Your search query (natural language, ICD codes, or structured)
            limit: Maximum results per source (default 10)
            min_year: Filter by minimum publication year
            max_year: Filter by maximum publication year
            ranking: Ranking strategy:
                - "balanced": Default, considers all factors
                - "impact": Prioritize high-citation papers
                - "recency": Prioritize recent publications
                - "quality": Prioritize high-evidence studies (RCTs, meta-analyses)
            output_format: "markdown" (human-readable) or "json" (programmatic)
            include_oa_links: Enrich results with open access links (default True)
            show_analysis: Include query analysis in output (default True)
            include_similarity_scores: Add relevance/similarity scores to each result
                                       based on ranking position and source trust.
                                       (default True). Scores range from 0-100%.
            age_group: Age group filter (PubMed only). Options:
                       "newborn" (0-1mo), "infant" (1-23mo), "preschool" (2-5y),
                       "child" (6-12y), "adolescent" (13-18y), "young_adult" (19-24y),
                       "adult" (19+), "middle_aged" (45-64y), "aged" (65+), "aged_80" (80+)
            sex: Sex filter (PubMed only). Options: "male", "female"
            species: Species filter (PubMed only). Options: "humans", "animals"
            language: Language filter (PubMed only). Options: "english", "chinese", etc.
            clinical_query: Clinical query filter (PubMed only). Options:
                           "therapy" (broad), "therapy_narrow" (high specificity),
                           "diagnosis", "diagnosis_narrow",
                           "prognosis", "prognosis_narrow",
                           "etiology", "etiology_narrow",
                           "clinical_prediction", "clinical_prediction_narrow"
                           These are validated PubMed clinical query strategies for EBM.
            include_preprints: Also search preprint servers (arXiv, medRxiv, bioRxiv)
                              Default: False. Set True for cutting-edge research.

        Returns:
            Formatted search results with:
            - Query analysis (complexity, intent, PICO)
            - ICD code expansions (if detected)
            - Search statistics (sources, dedup count)
            - Ranked articles with metadata
            - Open access links where available
            - Preprints (if include_preprints=True)
        """
        logger.info(
            f"Unified search: query='{query}', limit={limit}, ranking='{ranking}'"
        )

        try:
            # === Step 0: Normalize Inputs ===
            query = InputNormalizer.normalize_query(query)
            if not query:
                return ResponseFormatter.error(
                    "Empty query",
                    suggestion="Provide a search query",
                    example='unified_search(query="machine learning in anesthesia")',
                    tool_name="unified_search",
                )

            limit = InputNormalizer.normalize_limit(limit, default=10, max_val=100)
            min_year = InputNormalizer.normalize_year(min_year)
            max_year = InputNormalizer.normalize_year(max_year)
            include_oa_links = InputNormalizer.normalize_bool(
                include_oa_links, default=True
            )
            show_analysis = InputNormalizer.normalize_bool(show_analysis, default=True)
            include_similarity_scores = InputNormalizer.normalize_bool(
                include_similarity_scores, default=True
            )
            include_preprints = InputNormalizer.normalize_bool(
                include_preprints, default=False
            )

            # === Step 0.5: ICD Code Detection and Expansion ===
            icd_matches: list[dict] = []
            expanded_query, icd_matches = detect_and_expand_icd_codes(query)
            if icd_matches:
                query = expanded_query
                logger.info(f"ICD codes detected: {[i['code'] for i in icd_matches]}")

            # === Step 1: Analyze Query ===
            analyzer = QueryAnalyzer()
            analysis = analyzer.analyze(query)

            logger.info(
                f"Query analysis: complexity={analysis.complexity.value}, intent={analysis.intent.value}"
            )

            # === Step 2: Determine Sources ===
            sources = DispatchStrategy.get_sources(analysis)
            logger.info(f"Selected sources: {sources}")

            # === Step 3: Get Ranking Config ===
            if ranking == "impact":
                config = RankingConfig.impact_focused()
            elif ranking == "recency":
                config = RankingConfig.recency_focused()
            elif ranking == "quality":
                config = RankingConfig.quality_focused()
            else:
                config = DispatchStrategy.get_ranking_config(analysis)

            # === Step 4: Search Each Source (Parallel) ===
            all_results: list[list[UnifiedArticle]] = []
            pubmed_total_count: int | None = None
            preprint_results: dict = {}

            # Build advanced filters dict for cleaner passing
            advanced_filters = {
                k: v
                for k, v in {
                    "age_group": age_group,
                    "sex": sex,
                    "species": species,
                    "language": language,
                    "clinical_query": clinical_query,
                }.items()
                if v is not None
            }

            # Use ThreadPoolExecutor for parallel search
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def search_source(
                source: str,
            ) -> tuple[str, list[UnifiedArticle], int | None]:
                """Search a single source and return (source_name, articles, total_count)."""
                effective_min_year = min_year or analysis.year_from
                effective_max_year = max_year or analysis.year_to

                if source == "pubmed":
                    articles, total_count = _search_pubmed(
                        searcher,
                        query,
                        limit,
                        effective_min_year,
                        effective_max_year,
                        **advanced_filters,  # Cleaner: pass all advanced filters
                    )
                    return ("pubmed", articles, total_count)

                elif source == "openalex":
                    articles, total_count = _search_openalex(
                        query,
                        limit,
                        effective_min_year,
                        effective_max_year,
                    )
                    return ("openalex", articles, total_count)

                elif source == "semantic_scholar":
                    articles, total_count = _search_semantic_scholar(
                        query,
                        limit,
                        effective_min_year,
                        effective_max_year,
                    )
                    return ("semantic_scholar", articles, total_count)

                elif source == "crossref":
                    # CrossRef is used for enrichment, not primary search
                    return ("crossref", [], None)

                return (source, [], None)

            # Filter out crossref from parallel search (it's enrichment only)
            search_sources = [s for s in sources if s != "crossref"]

            # Execute searches in parallel
            with ThreadPoolExecutor(max_workers=len(search_sources)) as executor:
                futures = {executor.submit(search_source, s): s for s in search_sources}

                for future in as_completed(futures):
                    source_name = futures[future]
                    try:
                        name, articles, total_count = future.result()
                        if articles:
                            all_results.append(articles)
                        if name == "pubmed" and total_count is not None:
                            pubmed_total_count = total_count
                        logger.info(
                            f"{name}: {len(articles)} results"
                            + (f" (total: {total_count})" if total_count else "")
                        )
                    except Exception as e:
                        logger.error(f"Search failed for {source_name}: {e}")

            # === Step 4.5: Search Preprints (if enabled) ===
            if include_preprints:
                try:
                    preprint_searcher = PreprintSearcher()
                    # Use original query for preprints (without MeSH expansion)
                    preprint_query = (
                        query.split("[MeSH]")[0].replace('"', "").strip()
                        if "[MeSH]" in query
                        else query
                    )
                    preprint_results = preprint_searcher.search_medical_preprints(
                        query=preprint_query,
                        limit=min(limit, 10),  # Cap preprint results
                    )
                    logger.info(
                        f"Preprints: {preprint_results.get('total', 0)} results"
                    )
                except Exception as e:
                    logger.warning(f"Preprint search failed: {e}")
                    preprint_results = {}

            # === Step 5: Aggregate and Deduplicate ===
            aggregator = ResultAggregator(config)
            articles, stats = aggregator.aggregate(all_results)

            logger.info(
                f"Aggregation: {stats.unique_articles} unique from {stats.total_input} total"
            )

            # === Step 6: Enrich with CrossRef (if in sources) ===
            if "crossref" in sources:
                _enrich_with_crossref(articles)

            # === Step 7: Enrich with Unpaywall OA Links ===
            if include_oa_links and DispatchStrategy.should_enrich_with_unpaywall(
                analysis
            ):
                _enrich_with_unpaywall(articles)

            # === Step 8: Rank Results ===
            ranked = aggregator.rank(articles, config, query)

            # Apply limit
            if limit and len(ranked) > limit:
                ranked = ranked[:limit]

            # === Step 8.5: Enrich with Similarity Scores ===
            if include_similarity_scores:
                _enrich_with_similarity_scores(ranked, query)

            # === Step 9: Format Output ===
            if output_format == "json":
                return _format_as_json(ranked, analysis, stats)
            else:
                return _format_unified_results(
                    ranked,
                    analysis,
                    stats,
                    show_analysis,
                    pubmed_total_count,
                    icd_matches,
                    preprint_results if include_preprints else None,
                    include_trials=True,
                    original_query=analysis.original_query,
                )

        except Exception as e:
            logger.error(f"Unified search failed: {e}", exc_info=True)
            return f"Error: Unified search failed - {str(e)}"

    @mcp.tool()
    def analyze_search_query(query: str) -> str:
        """
        Analyze a search query without executing the search.

        Useful for understanding how unified_search will process your query
        before actually running it.

        Args:
            query: The search query to analyze

        Returns:
            Analysis including:
            - Complexity level (SIMPLE/MODERATE/COMPLEX/AMBIGUOUS)
            - Intent (LOOKUP/EXPLORATION/COMPARISON/SYSTEMATIC)
            - PICO elements (if detected)
            - Recommended sources
            - Recommended strategies
        """
        # Normalize input
        query = InputNormalizer.normalize_query(query)
        if not query:
            return ResponseFormatter.error(
                "Empty query",
                suggestion="Provide a search query to analyze",
                example='analyze_search_query(query="remimazolam vs propofol")',
                tool_name="analyze_search_query",
            )

        try:
            analyzer = QueryAnalyzer()
            analysis = analyzer.analyze(query)

            # Get dispatch strategy
            sources = DispatchStrategy.get_sources(analysis)
            config = DispatchStrategy.get_ranking_config(analysis)
            enrich_oa = DispatchStrategy.should_enrich_with_unpaywall(analysis)

            output = [
                "## 🔬 Query Analysis\n",
                f"**Original Query**: {analysis.original_query}",
                f"**Normalized**: {analysis.normalized_query}",
                "",
                "### Classification",
                f"- **Complexity**: {analysis.complexity.value}",
                f"- **Intent**: {analysis.intent.value}",
                f"- **Confidence**: {analysis.confidence:.0%}",
            ]

            if analysis.clinical_category:
                output.append(f"- **Clinical Category**: {analysis.clinical_category}")

            if analysis.pico:
                output.append("\n### PICO Elements")
                for key, value in analysis.pico.to_dict().items():
                    if value:
                        output.append(f"- **{key}**: {value}")

            if analysis.identifiers:
                output.append("\n### Extracted Identifiers")
                for ident in analysis.identifiers:
                    output.append(f"- {ident.type.upper()}: {ident.value}")

            if analysis.keywords:
                output.append(f"\n### Keywords: {', '.join(analysis.keywords)}")

            if analysis.year_from or analysis.year_to:
                year_str = []
                if analysis.year_from:
                    year_str.append(f"from {analysis.year_from}")
                if analysis.year_to:
                    year_str.append(f"to {analysis.year_to}")
                output.append(f"\n### Year Constraint: {' '.join(year_str)}")

            output.extend(
                [
                    "\n### Dispatch Strategy",
                    f"- **Sources**: {' → '.join(sources)}",
                    f"- **Ranking**: {config.normalized_weights()}",
                    f"- **OA Enrichment**: {'Yes' if enrich_oa else 'No'}",
                ]
            )

            return "\n".join(output)

        except Exception as e:
            logger.error(f"Query analysis failed: {e}")
            return f"Error: Query analysis failed - {str(e)}"
