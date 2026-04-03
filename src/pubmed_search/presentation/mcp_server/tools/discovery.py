"""
Discovery Tools - Search and explore PubMed literature.

Tools:
- search_literature: Basic PubMed search (supports alternate sources internally)
- find_related_articles: Find related papers (similar articles)
- find_citing_articles: Find papers that cite this article (forward in time)
- get_article_references: Get this article's bibliography (backward in time)
- fetch_article_details: Get full article details
- get_citation_metrics: Get NIH iCite citation metrics (RCR, percentile)

Internal Features:
- Multi-source search: PubMed (default), Semantic Scholar, OpenAlex
- Cross-search fallback when PubMed results are insufficient

Phase 2.1 Updates:
- InputNormalizer for flexible input handling
- ResponseFormatter for consistent error messages
- KEY_ALIASES for parameter name tolerance
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal, Union

from pubmed_search.infrastructure.sources import cross_search, search_alternate_source

from ._common import (
    # Phase 2.1 imports
    InputNormalizer,
    ResponseFormatter,
    _cache_results,
    _record_search_only,
    check_cache,
    format_search_results,
)
from .agent_output import (
    OutputFormat,
    finalize_next_tools,
    is_structured_output_format,
    make_next_tool,
    make_section_provenance,
    make_source_count_row,
    normalize_output_format,
    preferred_structured_output_format,
    serialize_structured_payload,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)

# Known journal names that might be confused with topics
# Format: {lowercase_name: (journal_title, ISSN, hint)}
AMBIGUOUS_JOURNAL_NAMES = {
    "anesthesiology": ("Anesthesiology", "1528-1175", "journal[ta]"),
    "anesthesia": ("Anesthesia & Analgesia", None, "anesthesia[ta]"),
    "lancet": ("The Lancet", "1474-547X", "lancet[ta]"),
    "nature": ("Nature", "1476-4687", "nature[ta]"),
    "science": ("Science", "1095-9203", "science[ta]"),
    "cell": ("Cell", "1097-4172", "cell[ta]"),
    "circulation": ("Circulation", "1524-4539", "circulation[ta]"),
    "neurology": ("Neurology", "1526-632X", "neurology[ta]"),
    "pediatrics": ("Pediatrics", "1098-4275", "pediatrics[ta]"),
    "radiology": ("Radiology", "1527-1315", "radiology[ta]"),
    "surgery": ("Surgery", "1532-7361", "surgery[ta]"),
    "medicine": ("Medicine", "1536-5964", "medicine[ta]"),
    "chest": ("Chest", "1931-3543", "chest[ta]"),
    "gut": ("Gut", "1468-3288", "gut[ta]"),
    "brain": ("Brain", "1460-2156", "brain[ta]"),
    "blood": ("Blood", "1528-0020", "blood[ta]"),
    "pain": ("Pain", "1872-6623", "pain[ta]"),
    "sleep": ("Sleep", "1550-9109", "sleep[ta]"),
    "critical care": ("Critical Care", "1466-609X", "critical care[ta]"),
    "intensive care": ("Intensive Care Medicine", "1432-1238", "intensive care[ta]"),
}


def _detect_ambiguous_terms(query: str) -> list:
    """Detect if query contains terms that could be journal names."""
    query_lower = query.lower()
    ambiguous = []

    for term, (journal, _issn, hint) in AMBIGUOUS_JOURNAL_NAMES.items():
        # Check if the term appears as a standalone word
        if term in query_lower:
            # Simple check: is it likely being used as a topic rather than journal?
            # If query has other substantive terms, it's probably a topic search
            other_terms = query_lower.replace(term, "").strip()
            if len(other_terms.split()) <= 2:  # Few other terms = might mean journal
                ambiguous.append({"term": term, "journal": journal, "hint": hint})

    return ambiguous


def _format_ambiguity_hint(ambiguous_terms: list, query: str) -> str:
    """Format a concise hint about ambiguous terms."""
    if not ambiguous_terms:
        return ""

    hints = []
    for item in ambiguous_terms[:2]:  # Limit to 2 hints
        term = item["term"]
        journal = item["journal"]
        hint = item["hint"]
        hints.append(f'"{term}" = journal "{journal}"? Use: {hint}')

    return "\n\n⚠️ **Tip**: " + " | ".join(hints)


def _format_fetch_article_details_json(
    requested_pmids: list[str],
    articles: list[dict[str, Any]],
    output_format: OutputFormat = "json",
) -> str:
    """Format fetch_article_details as an agent-oriented JSON envelope."""
    structured_output_format = preferred_structured_output_format(output_format)
    lead_pmid = next((str(article.get("pmid")) for article in articles if article.get("pmid")), None)
    pmid_csv = ",".join(str(article.get("pmid")) for article in articles if article.get("pmid"))

    next_tool_candidates: list[dict[str, str]] = []
    if lead_pmid:
        next_tool_candidates.append(
            make_next_tool(
                "find_related_articles",
                "Use the lead PMID as a seed before widening the exploration graph.",
                f'find_related_articles(pmid="{lead_pmid}", limit=10)',
            )
        )
        next_tool_candidates.append(
            make_next_tool(
                "get_fulltext",
                "Pivot from metadata into fulltext or OA link discovery for the lead article.",
                (
                    f'get_fulltext(pmid="{lead_pmid}", extended_sources=True, '
                    f'output_format="{structured_output_format}")'
                ),
            )
        )
    if pmid_csv:
        next_tool_candidates.append(
            make_next_tool(
                "get_citation_metrics",
                "Rank these detailed records by impact before exporting or narrowing further.",
                f'get_citation_metrics(pmids="{pmid_csv}")',
            )
        )
        if len(articles) > 1:
            next_tool_candidates.append(
                make_next_tool(
                    "prepare_export",
                    "You already have multiple resolved records; export them once you are ready to shortlist offline.",
                    f'prepare_export(pmids="{pmid_csv}", format="ris")',
                )
            )

    next_tools, next_commands = finalize_next_tools(next_tool_candidates)
    visible_fields = sorted(
        {key for article in articles for key, value in article.items() if value not in (None, "", [], {}, ())}
    )

    payload = {
        "tool": "fetch_article_details",
        "pmids_requested": requested_pmids,
        "article_count": len(articles),
        "articles": articles,
        "source_counts": [make_source_count_row("pubmed", len(articles))],
        "next_tools": next_tools,
        "next_commands": next_commands,
        "section_provenance": {
            "articles": make_section_provenance(
                surfacing_source="PubMed / NCBI Entrez",
                canonical_host="PubMed",
                provenance="direct",
                note="Detailed article metadata is fetched directly from PubMed/NCBI records.",
                fields=visible_fields,
            ),
            "source_counts": make_section_provenance(
                surfacing_source="pubmed-search-mcp",
                canonical_host=None,
                provenance="derived",
                note="Counts reflect how many PubMed records were successfully materialized for this request.",
                upstream_sources=["pubmed"],
            ),
            "next_tools": make_section_provenance(
                surfacing_source="pubmed-search-mcp",
                canonical_host="pubmed-search-mcp",
                provenance="derived",
                note="Next-tool suggestions are inferred locally from resolved PMIDs and article metadata.",
            ),
        },
    }
    return serialize_structured_payload(payload, output_format)


def _format_citation_metrics_structured(
    requested_pmids: list[str],
    resolved_pmids: list[str],
    articles: list[dict[str, Any]],
    *,
    sort_by: str,
    min_citations: int | None,
    min_rcr: float | None,
    min_percentile: float | None,
    total_metrics: int,
    output_format: OutputFormat = "json",
) -> str:
    """Format get_citation_metrics as a structured agent-facing payload."""
    structured_output_format = preferred_structured_output_format(output_format)
    normalized_articles: list[dict[str, Any]] = []
    for article in articles:
        icite = article.get("icite", {})
        normalized_articles.append(
            {
                "pmid": str(icite.get("pmid") or article.get("pmid") or ""),
                "title": icite.get("title"),
                "journal": icite.get("journal"),
                "year": icite.get("year"),
                "citation_count": icite.get("citation_count"),
                "relative_citation_ratio": icite.get("relative_citation_ratio"),
                "nih_percentile": icite.get("nih_percentile"),
                "citations_per_year": icite.get("citations_per_year"),
                "apt": icite.get("apt"),
            }
        )

    lead_pmid = next((article["pmid"] for article in normalized_articles if article.get("pmid")), None)
    pmid_csv = ",".join(article["pmid"] for article in normalized_articles if article.get("pmid"))

    next_tool_candidates: list[dict[str, str]] = []
    if pmid_csv:
        next_tool_candidates.append(
            make_next_tool(
                "fetch_article_details",
                "Hydrate the ranked PMIDs with richer PubMed metadata before deeper review or export.",
                f'fetch_article_details(pmids="{pmid_csv}", output_format="{structured_output_format}")',
            )
        )
    if lead_pmid:
        next_tool_candidates.append(
            make_next_tool(
                "get_fulltext",
                "Move from citation impact into fulltext access for the strongest PMID first.",
                (
                    f'get_fulltext(pmid="{lead_pmid}", extended_sources=True, '
                    f'output_format="{structured_output_format}")'
                ),
            )
        )
        next_tool_candidates.append(
            make_next_tool(
                "find_related_articles",
                "Use the highest-impact PMID as a seed for neighborhood exploration.",
                f'find_related_articles(pmid="{lead_pmid}", limit=10)',
            )
        )
    if len(normalized_articles) > 1 and pmid_csv:
        next_tool_candidates.append(
            make_next_tool(
                "prepare_export",
                "Export the ranked citation set once you are ready to compare it offline.",
                f'prepare_export(pmids="{pmid_csv}", format="ris")',
            )
        )

    next_tools, next_commands = finalize_next_tools(next_tool_candidates)
    visible_fields = sorted(
        {
            key
            for article in normalized_articles
            for key, value in article.items()
            if value not in (None, "", [], {}, ())
        }
    )
    filters = {
        key: value
        for key, value in {
            "min_citations": min_citations,
            "min_rcr": min_rcr,
            "min_percentile": min_percentile,
        }.items()
        if value is not None
    }

    payload = {
        "tool": "get_citation_metrics",
        "pmids_requested": requested_pmids,
        "pmids_resolved": resolved_pmids,
        "article_count": len(normalized_articles),
        "sort_by": sort_by,
        "filters": filters,
        "articles": normalized_articles,
        "source_counts": [make_source_count_row("nih-icite", len(normalized_articles), total_metrics)],
        "next_tools": next_tools,
        "next_commands": next_commands,
        "section_provenance": {
            "articles": make_section_provenance(
                surfacing_source="NIH iCite",
                canonical_host="NIH iCite",
                provenance="direct",
                note="Citation metrics are fetched directly from the NIH iCite service for the resolved PMIDs.",
                fields=visible_fields,
            ),
            "source_counts": make_section_provenance(
                surfacing_source="pubmed-search-mcp",
                canonical_host=None,
                provenance="derived",
                note="Counts reflect how many iCite metric rows survived sorting and filter constraints.",
                upstream_sources=["nih-icite"],
            ),
            "next_tools": make_section_provenance(
                surfacing_source="pubmed-search-mcp",
                canonical_host="pubmed-search-mcp",
                provenance="derived",
                note="Next-tool suggestions are inferred locally from the ranked PMID set and chosen metric sort.",
            ),
        },
    }
    return serialize_structured_payload(payload, output_format)


def register_discovery_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """Register discovery tools for exploring PubMed."""

    # Supported alternate sources
    alternate_sources = ("semantic_scholar", "openalex")

    # ❌ REMOVED v0.1.20: Replaced by unified_search which auto-handles multi-source
    # @mcp.tool()
    async def search_literature(
        query: str,
        limit: int = 5,
        min_year: int | None = None,
        max_year: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        date_type: str = "edat",
        article_type: str | None = None,
        strategy: str = "relevance",
        force_refresh: bool = False,
        source: Literal["pubmed", "semantic_scholar", "openalex"] = "pubmed",
        open_access_only: bool = False,
        cross_search_fallback: bool = False,
        cross_search_threshold: int = 3,
    ) -> str:
        """
        Search for medical literature based on a query using PubMed.

        Results are automatically cached to avoid redundant API calls.
        Repeated searches with the same query will return cached results.

        Args:
            query: The search query (e.g., "diabetes treatment guidelines").
            limit: The maximum number of results to return.
            min_year: Optional minimum publication year (e.g., 2020).
            max_year: Optional maximum publication year.
            date_from: Precise start date in YYYY/MM/DD format (e.g., "2025/10/01").
            date_to: Precise end date in YYYY/MM/DD format (e.g., "2025/11/28").
            date_type: Which date field to search. Options:
                       - "edat" (default): Entrez date - when added to PubMed (best for NEW articles)
                       - "pdat": Publication date
                       - "mdat": Modification date
            article_type: Optional article type (e.g., "Review", "Clinical Trial", "Meta-Analysis").
            strategy: Search strategy ("recent", "most_cited", "relevance", "impact").
                     Default is "relevance".
            force_refresh: If True, bypass cache and fetch fresh results from API.
        """
        # === Internal parameters (not shown in docstring) ===
        # source: Search source ("pubmed", "semantic_scholar", "openalex")
        # open_access_only: Only return open access papers (for alternate sources)
        # cross_search_fallback: Auto-search alternate sources if PubMed < threshold
        # cross_search_threshold: Minimum results before triggering cross-search

        logger.info(f"Searching literature: query='{query}', limit={limit}, source='{source}', strategy='{strategy}'")
        try:
            if not query:
                return "Error: Query is required."

            # === Handle alternate sources (internal feature) ===
            if source in alternate_sources:
                # Cast to narrow type (we've already checked source is in alternate_sources)
                alt_source: Literal["semantic_scholar", "openalex"] = source  # type: ignore[assignment]
                return await _search_alternate_source_internal(
                    query=query,
                    source=alt_source,
                    limit=limit,
                    min_year=min_year,
                    max_year=max_year,
                    open_access_only=open_access_only,
                )

            # === PubMed search (default) ===
            # Detect ambiguous terms (journal vs topic)
            ambiguous = _detect_ambiguous_terms(query)

            # Check cache first (unless force_refresh or filters applied)
            has_filters = any([min_year, max_year, date_from, date_to, article_type])
            if not force_refresh and not has_filters:
                cached = check_cache(query, limit)
                if cached:
                    logger.info(f"Returning {len(cached)} cached results for '{query}'")
                    result = format_search_results(cached[:limit]) + "\n\n_(cached results)_"
                    result += _format_ambiguity_hint(ambiguous, query)
                    return result

            # No cache hit - call API
            results = await searcher.search(
                query,
                limit,
                min_year,
                max_year,
                article_type,
                strategy,
                date_from=date_from,
                date_to=date_to,
                date_type=date_type,
            )

            # Extract total count from metadata (if present)
            total_count = None
            if results and "_search_metadata" in results[0]:
                total_count = results[0]["_search_metadata"].get("total_count")
                # Remove metadata from results before caching/formatting
                del results[0]["_search_metadata"]
                # If this was a metadata-only result (no actual article data), remove it
                if len(results[0]) == 0 or (len(results[0]) == 1 and "error" not in results[0]):
                    results = results[1:] if len(results) > 1 else []

            # Cache results (only for queries without filters)
            if not has_filters:
                _cache_results(results, query)
            else:
                # Always record search history for "last" export feature
                _record_search_only(results, query)

            # Format results with total count info
            returned_count = len(results[:limit])

            # Always show total_count if available, even when returned_count == 0
            if total_count is not None:
                if returned_count == 0:
                    result = f"📊 PubMed 共有 **{total_count}** 篇符合條件，但無法取得詳細資料\n\n"
                elif total_count > returned_count:
                    result = f"📊 Found **{returned_count}** results (of **{total_count}** total in PubMed)\n\n"
                else:
                    result = f"📊 Found **{returned_count}** results\n\n"
            else:
                result = f"📊 Found **{returned_count}** results\n\n"
            result += format_search_results(results[:limit])

            # Add hint about potential journal name confusion
            # Always show for single-word queries or when results suggest broad topic
            if ambiguous:
                result += _format_ambiguity_hint(ambiguous, query)

            # Add session persistence hint for large result sets
            if returned_count >= 5:
                pmids_list = [r.get("pmid") for r in results[:limit] if r.get("pmid")]
                result += f"\n---\n💾 **Session 已暫存 {len(pmids_list)} 篇 PMIDs**"
                result += "\n🔖 後續可用: `get_session_pmids()` 或 `pmids='last'`"

            # === Cross-search fallback (when PubMed results insufficient) ===
            if cross_search_fallback and returned_count < cross_search_threshold:
                result += await _perform_cross_search_fallback(
                    query=query,
                    existing_results=results[:limit],
                    limit=limit - returned_count,
                    min_year=min_year,
                    max_year=max_year,
                    open_access_only=open_access_only,
                )

            return result
        except Exception as e:
            logger.exception(f"Search failed: {e}")
            return f"Error: {e}"

    async def _search_alternate_source_internal(
        query: str,
        source: Literal["semantic_scholar", "openalex"],
        limit: int,
        min_year: int | None,
        max_year: int | None,
        open_access_only: bool,
    ) -> str:
        """Internal: Search alternate sources (Semantic Scholar, OpenAlex)."""
        try:
            results = await search_alternate_source(
                query=query,
                source=source,
                limit=limit,
                min_year=min_year,
                max_year=max_year,
                open_access_only=open_access_only,
            )

            source_name = {
                "semantic_scholar": "Semantic Scholar",
                "openalex": "OpenAlex",
            }.get(source, source)

            if not results:
                return f"📊 No results found from {source_name} for '{query}'."

            # Format header
            returned_count = len(results)
            oa_note = " (Open Access only)" if open_access_only else ""
            result = f"📊 Found **{returned_count}** results from **{source_name}**{oa_note}\n\n"

            # Format results
            result += format_search_results(results)

            # Note about source
            result += f"\n---\n📚 Source: {source_name}"
            if source == "openalex":
                result += " | Has citation counts & open access info"
            elif source == "semantic_scholar":
                result += " | Has influential citations & TLDR"

            return result

        except Exception as e:
            logger.exception(f"Alternate source search failed: {e}")
            return f"Error searching {source}: {e}"

    async def _perform_cross_search_fallback(
        query: str,
        existing_results: list,
        limit: int,
        min_year: int | None,
        max_year: int | None,
        open_access_only: bool,
    ) -> str:
        """Internal: Perform cross-search when PubMed results insufficient."""
        if limit <= 0:
            return ""

        try:
            cross_results = await cross_search(
                query=query,
                sources=["openalex"],  # OpenAlex is more reliable for fallback
                limit_per_source=limit,
                min_year=min_year,
                max_year=max_year,
                open_access_only=open_access_only,
                deduplicate=True,
            )

            if not cross_results.get("results"):
                return ""

            # Filter out papers already in PubMed results (by PMID or title)
            existing_pmids = {r.get("pmid") for r in existing_results if r.get("pmid")}
            existing_titles = {r.get("title", "").lower()[:50] for r in existing_results}

            new_results = []
            for paper in cross_results["results"]:
                if paper.get("pmid") in existing_pmids:
                    continue
                if paper.get("title", "").lower()[:50] in existing_titles:
                    continue
                new_results.append(paper)

            if not new_results:
                return ""

            # Format supplemental results
            output = f"\n\n---\n🔄 **Cross-search results from OpenAlex** ({len(new_results)} additional)\n\n"
            output += format_search_results(new_results[:limit])

            return output

        except Exception as e:
            logger.warning(f"Cross-search fallback failed: {e}")
            return ""

    @mcp.tool()
    async def find_related_articles(pmid: Union[str, int], limit: int = 5) -> str:
        """
        Find articles related to a given PubMed article.
        Uses PubMed's "Related Articles" feature to find similar papers.

        ═══════════════════════════════════════════════════════════════
        🔗 CITATION NETWORK EXPLORATION WORKFLOW
        ═══════════════════════════════════════════════════════════════

        This is ONE of THREE tools for exploring citation networks:

        1️⃣ find_related_articles() ← YOU ARE HERE
           │  📌 Algorithm-based similarity (like PubMed "Similar Articles")
           │  📌 Finds papers with similar topics, MeSH terms, authors
           │  📌 Good for: Discovering related research you might have missed
           └─► Returns: Similar papers (not based on citations)

        2️⃣ find_citing_articles()
           │  📌 Forward citation search (who cited THIS paper?)
           │  📌 Finds papers published AFTER the source article
           │  📌 Good for: Tracking impact, finding follow-up studies
           └─► Returns: Papers that cite this article

        3️⃣ get_article_references()
           │  📌 Backward citation search (what did THIS paper cite?)
           │  📌 Finds papers published BEFORE the source article
           │  📌 Good for: Finding foundational papers, methodology sources
           └─► Returns: This article's bibliography

        ═══════════════════════════════════════════════════════════════
        EXAMPLE WORKFLOW:
        ═══════════════════════════════════════════════════════════════

        Step 1: Start with a key paper
            find_related_articles(pmid="23132851")
            → Find similar research directions

        Step 2: Explore backward (foundations)
            get_article_references(pmid="23132851")
            → Find the foundational papers it builds on

        Step 3: Explore forward (impact)
            find_citing_articles(pmid="23132851")
            → Find how the field developed after this paper

        Args:
            pmid: PubMed ID of the source article (accepts: "12345678", "PMID:12345678", 12345678).
            limit: Maximum number of related articles to return (1-50, default: 5).

        Returns:
            List of related articles with details.
        """
        # Phase 2.1: Input normalization
        normalized_pmid = InputNormalizer.normalize_pmid_single(pmid)
        if not normalized_pmid:
            return ResponseFormatter.error(
                error="Invalid PMID format",
                suggestion="Provide a valid PMID number",
                example='find_related_articles(pmid="12345678")',
                tool_name="find_related_articles",
            )

        normalized_limit = InputNormalizer.normalize_limit(limit, default=5, min_val=1, max_val=50)

        logger.info(f"Finding related articles for PMID: {normalized_pmid}")
        try:
            results = await searcher.get_related_articles(normalized_pmid, normalized_limit)

            if not results:
                return ResponseFormatter.no_results(
                    query=f"PMID {normalized_pmid}",
                    suggestions=[
                        "Check if the PMID is correct",
                        "Try find_citing_articles to see papers citing this article",
                        "Try get_article_references to see this article's bibliography",
                    ],
                )

            if "error" in results[0]:
                return ResponseFormatter.error(
                    error=results[0]["error"],
                    suggestion="Check if the PMID exists in PubMed",
                    tool_name="find_related_articles",
                )

            output = f"📚 **Related Articles for PMID {normalized_pmid}** ({len(results)} found)\n\n"
            output += format_search_results(results)
            return output
        except Exception as e:
            logger.exception(f"Find related articles failed: {e}")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check PMID format and try again",
                tool_name="find_related_articles",
            )

    @mcp.tool()
    async def find_citing_articles(pmid: Union[str, int], limit: int = 10) -> str:
        """
        Find articles that cite a given PubMed article.
        Uses PubMed Central's citation data to find papers that reference this article.

        ═══════════════════════════════════════════════════════════════
        📈 FORWARD CITATION SEARCH (Impact Tracking)
        ═══════════════════════════════════════════════════════════════

        Direction: Source Paper → Papers that cite it (FORWARD in time)

        USE CASES:
        ──────────
        - 🔬 Track research impact: Who built on this work?
        - 📊 Find follow-up studies: What happened after this discovery?
        - 🔄 Identify controversies: Papers that challenge or refute findings
        - 📚 Literature review: Ensure you have the latest developments

        COMPLEMENTARY TOOLS:
        ────────────────────
        - get_article_references(): BACKWARD search (what this paper cited)
        - find_related_articles(): Similar papers (topic-based, not citation-based)

        ═══════════════════════════════════════════════════════════════
        EXAMPLE:
        ═══════════════════════════════════════════════════════════════

        # Find papers that cite a landmark CRISPR paper
        find_citing_articles(pmid="23287718", limit=20)
        → Returns papers published AFTER 2012 that reference this work

        # Then analyze citation metrics
        get_citation_metrics(pmids="last")
        → See which citing papers are most influential

        Args:
            pmid: PubMed ID of the source article (accepts: "12345678", "PMID:12345678", 12345678).
            limit: Maximum number of citing articles to return (1-100, default: 10).

        Returns:
            List of citing articles with details.
        """
        # Phase 2.1: Input normalization
        normalized_pmid = InputNormalizer.normalize_pmid_single(pmid)
        if not normalized_pmid:
            return ResponseFormatter.error(
                error="Invalid PMID format",
                suggestion="Provide a valid PMID number",
                example='find_citing_articles(pmid="12345678")',
                tool_name="find_citing_articles",
            )

        normalized_limit = InputNormalizer.normalize_limit(limit, default=10, min_val=1, max_val=100)

        logger.info(f"Finding citing articles for PMID: {normalized_pmid}")
        try:
            results = await searcher.get_citing_articles(normalized_pmid, normalized_limit)

            if not results:
                return ResponseFormatter.no_results(
                    query=f"PMID {normalized_pmid}",
                    suggestions=[
                        "Article may not be indexed in PMC",
                        "Article may have no citations yet",
                        "Try find_related_articles for similar papers",
                        "Try get_article_references to see its bibliography",
                    ],
                )

            if "error" in results[0]:
                return ResponseFormatter.error(
                    error=results[0]["error"],
                    suggestion="Check if the PMID exists and is indexed in PMC",
                    tool_name="find_citing_articles",
                )

            output = f"📖 **Articles Citing PMID {normalized_pmid}** ({len(results)} found)\n\n"
            output += format_search_results(results)
            return output
        except Exception as e:
            logger.exception(f"Find citing articles failed: {e}")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check PMID format and try again",
                tool_name="find_citing_articles",
            )

    @mcp.tool()
    async def get_article_references(pmid: Union[str, int], limit: int = 20) -> str:
        """
        Get the references (bibliography) of a PubMed article.

        Returns the list of articles that this paper cites in its bibliography.
        This is the OPPOSITE of find_citing_articles:
        - get_article_references: Papers THIS article cites (backward in time)
        - find_citing_articles: Papers that cite THIS article (forward in time)

        ═══════════════════════════════════════════════════════════════
        📚 BACKWARD CITATION SEARCH (Foundation Discovery)
        ═══════════════════════════════════════════════════════════════

        Direction: Source Paper → Papers it cited (BACKWARD in time)

        USE CASES:
        ──────────
        - 🏛️ Find foundational papers: Core works the field builds on
        - ⚗️ Methodology sources: Papers describing techniques used
        - 📖 Background reading: Build understanding of a topic
        - 🔍 Verify claims: Check sources for specific assertions

        ═══════════════════════════════════════════════════════════════
        EXAMPLE WORKFLOW:
        ═══════════════════════════════════════════════════════════════

        # Start with a recent review article
        get_article_references(pmid="38123456", limit=50)
        → Get the bibliography of this review

        # Find most-cited foundational papers
        get_citation_metrics(pmids="last", sort_by="citation_count")
        → Identify which references are the most influential

        # Read a foundational paper
        fetch_article_details(pmids="12345678")
        → Get full details of an important reference

        Args:
            pmid: PubMed ID of the source article (accepts: "12345678", "PMID:12345678", 12345678).
            limit: Maximum number of references to return (1-100, default: 20).

        Returns:
            List of referenced articles with details.
        """
        # Phase 2.1: Input normalization
        normalized_pmid = InputNormalizer.normalize_pmid_single(pmid)
        if not normalized_pmid:
            return ResponseFormatter.error(
                error="Invalid PMID format",
                suggestion="Provide a valid PMID number",
                example='get_article_references(pmid="12345678")',
                tool_name="get_article_references",
            )

        normalized_limit = InputNormalizer.normalize_limit(limit, default=20, min_val=1, max_val=100)

        logger.info(f"Getting references for PMID: {normalized_pmid}")
        try:
            results = await searcher.get_article_references(normalized_pmid, normalized_limit)

            if not results:
                return ResponseFormatter.no_results(
                    query=f"PMID {normalized_pmid}",
                    suggestions=[
                        "Article may not be indexed in PMC",
                        "References may not be available for this article",
                        "Try find_citing_articles to see papers citing this article",
                    ],
                )

            if "error" in results[0]:
                return ResponseFormatter.error(
                    error=results[0]["error"],
                    suggestion="Check if the PMID exists and is indexed in PMC",
                    tool_name="get_article_references",
                )

            output = f"📚 **References of PMID {normalized_pmid}** ({len(results)} found)\n\n"
            output += "These are the papers cited BY this article (its bibliography):\n\n"
            output += format_search_results(results)
            return output
        except Exception as e:
            logger.exception(f"Get article references failed: {e}")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check PMID format and try again",
                tool_name="get_article_references",
            )

    @mcp.tool()
    async def fetch_article_details(
        pmids: Union[str, list, int],
        output_format: Literal["markdown", "json"] = "markdown",
    ) -> str:
        """
        Fetch detailed information for one or more PubMed articles.

        Args:
            pmids: PubMed IDs - accepts multiple formats:
                   - "12345678" (single)
                   - "12345678,87654321" (comma-separated)
                   - "PMID:12345678" (with prefix)
                   - ["12345678", "87654321"] (list)
                   - 12345678 (integer)

        Returns:
            Detailed information for each article.
        """
        # Phase 2.1: Input normalization
        normalized_output_format = normalize_output_format(output_format)
        normalized_pmids = InputNormalizer.normalize_pmids(pmids)

        if not normalized_pmids:
            return ResponseFormatter.error(
                error="No valid PMIDs provided",
                suggestion="Provide one or more valid PMID numbers",
                example='fetch_article_details(pmids="12345678,87654321")',
                tool_name="fetch_article_details",
                output_format=normalized_output_format,
            )

        logger.info(f"Fetching details for PMIDs: {normalized_pmids}")
        try:
            results = await searcher.fetch_details(normalized_pmids)

            if not results:
                if is_structured_output_format(normalized_output_format):
                    structured_output_format = preferred_structured_output_format(normalized_output_format)
                    return serialize_structured_payload(
                        {
                            "tool": "fetch_article_details",
                            "pmids_requested": normalized_pmids,
                            "article_count": 0,
                            "articles": [],
                            "source_counts": [make_source_count_row("pubmed", 0)],
                            "next_tools": [
                                make_next_tool(
                                    "unified_search",
                                    "Resolve valid PubMed records first when the requested PMIDs cannot be materialized.",
                                    f'unified_search(query="<topic>", output_format="{structured_output_format}")',
                                )
                            ],
                            "next_commands": [
                                f'unified_search(query="<topic>", output_format="{structured_output_format}")'
                            ],
                            "section_provenance": {
                                "articles": make_section_provenance(
                                    surfacing_source="PubMed / NCBI Entrez",
                                    canonical_host="PubMed",
                                    provenance="direct",
                                    note="No PubMed records were returned for the requested PMIDs.",
                                ),
                                "source_counts": make_section_provenance(
                                    surfacing_source="pubmed-search-mcp",
                                    canonical_host=None,
                                    provenance="derived",
                                    note="Counts reflect the absence of resolved records from PubMed.",
                                    upstream_sources=["pubmed"],
                                ),
                                "next_tools": make_section_provenance(
                                    surfacing_source="pubmed-search-mcp",
                                    canonical_host="pubmed-search-mcp",
                                    provenance="derived",
                                    note="Fallback navigation is generated locally when no records are returned.",
                                ),
                            },
                        },
                        normalized_output_format,
                    )
                return ResponseFormatter.no_results(
                    query=f"PMIDs: {', '.join(normalized_pmids)}",
                    suggestions=[
                        "Check if the PMIDs are correct",
                        "Use unified_search to find valid PMIDs",
                    ],
                )

            if "error" in results[0]:
                return ResponseFormatter.error(
                    error=results[0]["error"],
                    suggestion="Check if the PMIDs exist in PubMed",
                    tool_name="fetch_article_details",
                    output_format=normalized_output_format,
                )

            if is_structured_output_format(normalized_output_format):
                return _format_fetch_article_details_json(normalized_pmids, results, normalized_output_format)

            return format_search_results(results, include_doi=True)
        except Exception as e:
            logger.exception(f"Fetch details failed: {e}")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check PMID format and try again",
                tool_name="fetch_article_details",
                output_format=normalized_output_format,
            )

    @mcp.tool()
    async def get_citation_metrics(
        pmids: Union[str, list, int],
        sort_by: str = "citation_count",
        min_citations: int | None = None,
        min_rcr: float | None = None,
        min_percentile: float | None = None,
        output_format: Literal["markdown", "json", "toon"] = "markdown",
    ) -> str:
        """
        Get citation metrics from NIH iCite for articles.

        Returns field-normalized citation data including:
        - citation_count: Total number of citations
        - relative_citation_ratio (RCR): Field-normalized metric (1.0 = average)
        - nih_percentile: Percentile ranking (0-100)
        - citations_per_year: Citation velocity
        - apt: Approximate Potential to Translate (clinical relevance 0-1)

        Can sort and filter results by citation metrics.

        Args:
            pmids: PubMed IDs - accepts multiple formats:
                   - "12345678,87654321" (comma-separated)
                   - ["12345678", "87654321"] (list)
                   - "PMID:12345678" (with prefix)
                   - "last" to use PMIDs from the last search
            sort_by: Metric to sort by:
                - "citation_count": Raw citation count (default)
                - "relative_citation_ratio": Field-normalized (recommended)
                - "nih_percentile": Percentile ranking
                - "citations_per_year": Citation velocity
            min_citations: Filter out articles with fewer citations
            min_rcr: Filter out articles with RCR below threshold (e.g., 1.0 = average)
            min_percentile: Filter out articles below percentile (e.g., 50 = top half)

        Returns:
            Articles with citation metrics, sorted and filtered as requested.
        """
        normalized_output_format = normalize_output_format(output_format)

        # Phase 2.1: Input normalization
        normalized_pmids = InputNormalizer.normalize_pmids(pmids)

        logger.info(f"Getting citation metrics for: {normalized_pmids}")

        try:
            # Handle "last" keyword
            if normalized_pmids == ["last"]:
                from ._common import get_last_search_pmids

                pmid_list = get_last_search_pmids()
                if not pmid_list:
                    return ResponseFormatter.error(
                        error="No previous search results found",
                        suggestion="Search first or provide PMIDs directly",
                        example='get_citation_metrics(pmids="12345678,87654321")',
                        tool_name="get_citation_metrics",
                        output_format=normalized_output_format,
                    )
            else:
                pmid_list = normalized_pmids

            if not pmid_list:
                return ResponseFormatter.error(
                    error="No valid PMIDs provided",
                    suggestion="Provide PMIDs or use 'last' for recent search results",
                    example='get_citation_metrics(pmids="12345678")',
                    tool_name="get_citation_metrics",
                    output_format=normalized_output_format,
                )

            # Get metrics from iCite
            metrics = await searcher.get_citation_metrics(pmid_list)

            if not metrics:
                return ResponseFormatter.no_results(
                    query=f"PMIDs: {', '.join(pmid_list[:5])}{'...' if len(pmid_list) > 5 else ''}",
                    suggestions=[
                        "Articles may be too recent (iCite needs time to index)",
                        "Check if PMIDs are correct",
                        "Try fetch_article_details to verify the articles exist",
                    ],
                    output_format=normalized_output_format,
                    tool_name="get_citation_metrics",
                )

            # Convert to list for sorting/filtering
            articles: list[dict[str, Any]] = [{"pmid": pmid, "icite": data} for pmid, data in metrics.items()]

            # Apply filters
            if min_citations is not None:
                articles = [a for a in articles if (a["icite"].get("citation_count") or 0) >= min_citations]

            if min_rcr is not None:
                articles = [a for a in articles if (a["icite"].get("relative_citation_ratio") or 0) >= min_rcr]

            if min_percentile is not None:
                articles = [a for a in articles if (a["icite"].get("nih_percentile") or 0) >= min_percentile]

            if not articles:
                return ResponseFormatter.no_results(
                    query=f"Filtered PMIDs: {', '.join(pmid_list[:5])}{'...' if len(pmid_list) > 5 else ''}",
                    suggestions=[
                        "Relax one or more citation filters",
                        "Try sorting without filters first to inspect the raw iCite rows",
                    ],
                    output_format=normalized_output_format,
                    tool_name="get_citation_metrics",
                )

            # Sort
            def get_sort_value(a):
                val = a["icite"].get(sort_by)
                return val if val is not None else -1

            articles = sorted(articles, key=get_sort_value, reverse=True)

            if is_structured_output_format(normalized_output_format):
                return _format_citation_metrics_structured(
                    normalized_pmids,
                    pmid_list,
                    articles,
                    sort_by=sort_by,
                    min_citations=min_citations,
                    min_rcr=min_rcr,
                    min_percentile=min_percentile,
                    total_metrics=len(metrics),
                    output_format=normalized_output_format,
                )

            # Format output
            output = f"📊 **Citation Metrics** ({len(articles)} articles)\n"
            output += f"Sorted by: {sort_by}\n"

            if min_citations or min_rcr or min_percentile:
                filters = []
                if min_citations:
                    filters.append(f"citations≥{min_citations}")
                if min_rcr:
                    filters.append(f"RCR≥{min_rcr}")
                if min_percentile:
                    filters.append(f"percentile≥{min_percentile}")
                output += f"Filters: {', '.join(filters)}\n"

            output += "\n"

            for i, article in enumerate(articles, 1):
                icite = article["icite"]
                pmid = icite.get("pmid", article["pmid"])
                title = icite.get("title", "Unknown")[:80]
                year = icite.get("year", "?")
                journal = icite.get("journal", "Unknown")

                citations = icite.get("citation_count", 0) or 0
                rcr = icite.get("relative_citation_ratio")
                percentile = icite.get("nih_percentile")
                cpy = icite.get("citations_per_year")
                apt = icite.get("apt")

                output += f"**{i}. [{pmid}]** {title}...\n"
                output += f"   📅 {year} | 📰 {journal}\n"
                output += f"   📈 Citations: **{citations}**"

                if rcr is not None:
                    output += f" | RCR: **{rcr:.2f}**"
                if percentile is not None:
                    output += f" | Percentile: **{percentile:.1f}%**"
                if cpy is not None:
                    output += f" | {cpy:.1f}/yr"
                if apt is not None and apt > 0.5:
                    output += f" | 🏥 APT: {apt:.2f}"

                output += "\n\n"

            # Add legend
            output += "---\n"
            output += "**Legend**: RCR=Relative Citation Ratio (1.0=field average), "
            output += "APT=Approximate Potential to Translate (clinical relevance)\n"

            return output

        except Exception as e:
            logger.exception(f"Get citation metrics failed: {e}")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check PMID format and try again",
                tool_name="get_citation_metrics",
                output_format=normalized_output_format,
            )
