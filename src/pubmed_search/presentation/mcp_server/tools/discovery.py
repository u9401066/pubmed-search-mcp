"""
Discovery Tools - Search and explore PubMed literature.

Tools:
- find_related_articles: Find related papers (similar articles)
- find_citing_articles: Find papers that cite this article (forward in time)
- get_article_references: Get this article's bibliography (backward in time)
- fetch_article_details: Get full article details
- get_citation_metrics: Get NIH iCite citation metrics (RCR, percentile)

Phase 2.1 Updates:
- InputNormalizer for flexible input handling
- ResponseFormatter for consistent error messages
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field

from pubmed_search.domain.value_objects import (
    MAX_IDENTIFIER_CHARS,
    MAX_PMID_BATCH_CHARS,
    MAX_PMIDS_PER_REQUEST,
    IdentifierValidationError,
    normalize_pmid_batch,
)
from pubmed_search.shared.exceptions import APIError, ErrorContext, PubMedSearchError, ServiceUnavailableError

from ._common import ResponseFormatter, format_search_results
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
    from mcp.server.mcpserver import MCPServer

    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)

CitationSortField = Literal[
    "citation_count",
    "relative_citation_ratio",
    "nih_percentile",
    "citations_per_year",
]
PMIDText = Annotated[str, Field(strict=True, min_length=1, max_length=MAX_IDENTIFIER_CHARS)]
PMIDBatchText = Annotated[str, Field(strict=True, min_length=1, max_length=MAX_PMID_BATCH_CHARS)]
PMIDList = Annotated[list[PMIDText], Field(min_length=1, max_length=MAX_PMIDS_PER_REQUEST)]
PMIDBatchInput = PMIDBatchText | PMIDList
MAX_CITATION_COUNT_FILTER = 2_000_000_000
MAX_RCR_FILTER = 1_000_000.0
NonNegativeCitationCount = Annotated[int, Field(strict=True, ge=0, le=MAX_CITATION_COUNT_FILTER)]
NonNegativeMetric = Annotated[float, Field(strict=True, ge=0, le=MAX_RCR_FILTER, allow_inf_nan=False)]
PercentileThreshold = Annotated[float, Field(strict=True, ge=0, le=100, allow_inf_nan=False)]
RelatedLimit = Annotated[int, Field(strict=True, ge=1, le=50)]
CitationLinkLimit = Annotated[int, Field(strict=True, ge=1, le=100)]
_CITATION_SORT_FIELDS = {
    "citation_count",
    "relative_citation_ratio",
    "nih_percentile",
    "citations_per_year",
}


def _public_source_failure(message: str, error: PubMedSearchError, *, operation: str) -> APIError:
    """Preserve typed retry metadata without exposing an upstream message."""
    retry_after = error.context.retry_after
    return APIError(
        message,
        context=ErrorContext(operation=operation, retry_after=retry_after),
        retryable=error.retryable,
    )


def _normalize_public_pmid_batch(value: object, *, allow_last: bool = True) -> list[str]:
    """Validate the public string-only PMID contract before domain parsing."""
    if isinstance(value, str):
        return normalize_pmid_batch(value, allow_last=allow_last)
    if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        return normalize_pmid_batch(value, allow_last=allow_last)
    raise IdentifierValidationError("PMIDs must be a non-empty string or a non-empty list of strings")


def _normalize_public_pmid(value: object) -> str:
    """Parse exactly one PMID from the public string-only contract."""
    pmids = _normalize_public_pmid_batch(value, allow_last=False)
    if len(pmids) != 1:
        raise IdentifierValidationError("Exactly one PMID is required")
    return pmids[0]


def _validate_limit(value: object, *, maximum: int) -> int:
    """Apply bounds to direct Python calls as well as MCP protocol calls."""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"limit must be an integer between 1 and {maximum}")
    return value


def _validate_citation_metric_inputs(
    *,
    sort_by: str,
    min_citations: int | None,
    min_rcr: float | None,
    min_percentile: float | None,
) -> None:
    """Apply the MCP schema boundaries to direct Python callers as well."""
    if sort_by not in _CITATION_SORT_FIELDS:
        raise ValueError("sort_by must be a supported iCite metric")
    if min_citations is not None and (
        isinstance(min_citations, bool)
        or not isinstance(min_citations, int)
        or not 0 <= min_citations <= MAX_CITATION_COUNT_FILTER
    ):
        raise ValueError(f"min_citations must be an integer between 0 and {MAX_CITATION_COUNT_FILTER}")
    if min_rcr is not None and (
        isinstance(min_rcr, bool)
        or not isinstance(min_rcr, (int, float))
        or not math.isfinite(min_rcr)
        or not 0 <= min_rcr <= MAX_RCR_FILTER
    ):
        raise ValueError(f"min_rcr must be a finite number between 0 and {MAX_RCR_FILTER:g}")
    if min_percentile is not None and (
        isinstance(min_percentile, bool)
        or not isinstance(min_percentile, (int, float))
        or not math.isfinite(min_percentile)
        or not 0 <= min_percentile <= 100
    ):
        raise ValueError("min_percentile must be between 0 and 100")


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
                    f'get_fulltext(source={{"kind":"pmid","value":"{lead_pmid}"}}, extended_sources=True, '
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
                    f'get_fulltext(source={{"kind":"pmid","value":"{lead_pmid}"}}, extended_sources=True, '
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


def register_discovery_tools(mcp: MCPServer, searcher: LiteratureSearcher):
    """Register discovery tools for exploring PubMed."""

    @mcp.tool()
    async def find_related_articles(pmid: PMIDText, limit: RelatedLimit = 5) -> str:
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
            pmid: PubMed ID of the source article ("12345678" or "PMID:12345678").
            limit: Maximum number of related articles to return (1-50, default: 5).

        Returns:
            List of related articles with details.
        """
        try:
            normalized_pmid = _normalize_public_pmid(pmid)
            normalized_limit = _validate_limit(limit, maximum=50)
        except (IdentifierValidationError, ValueError) as exc:
            return ResponseFormatter.error(
                error=exc,
                suggestion="Provide one PMID string and a limit between 1 and 50",
                example='find_related_articles(pmid="12345678")',
                tool_name="find_related_articles",
            )

        logger.info("Finding related articles for one PMID")
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

            output = f"📚 **Related Articles for PMID {normalized_pmid}** ({len(results)} found)\n\n"
            output += format_search_results(results)
            return output
        except PubMedSearchError as exc:
            logger.warning("Related-article lookup failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                error=_public_source_failure(
                    "PubMed related-article lookup failed",
                    exc,
                    operation="find_related_articles",
                ),
                suggestion="Check PMID format and try again",
                tool_name="find_related_articles",
            )
        except Exception as exc:
            logger.warning("Related-article lookup failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                error="PubMed related-article lookup failed",
                suggestion="Check PMID format and try again",
                tool_name="find_related_articles",
            )

    @mcp.tool()
    async def find_citing_articles(pmid: PMIDText, limit: CitationLinkLimit = 10) -> str:
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
            pmid: PubMed ID of the source article ("12345678" or "PMID:12345678").
            limit: Maximum number of citing articles to return (1-100, default: 10).

        Returns:
            List of citing articles with details.
        """
        try:
            normalized_pmid = _normalize_public_pmid(pmid)
            normalized_limit = _validate_limit(limit, maximum=100)
        except (IdentifierValidationError, ValueError) as exc:
            return ResponseFormatter.error(
                error=exc,
                suggestion="Provide one PMID string and a limit between 1 and 100",
                example='find_citing_articles(pmid="12345678")',
                tool_name="find_citing_articles",
            )

        logger.info("Finding citing articles for one PMID")
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

            output = f"📖 **Articles Citing PMID {normalized_pmid}** ({len(results)} found)\n\n"
            output += format_search_results(results)
            return output
        except PubMedSearchError as exc:
            logger.warning("Citing-article lookup failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                error=_public_source_failure(
                    "PubMed citing-article lookup failed",
                    exc,
                    operation="find_citing_articles",
                ),
                suggestion="Check PMID format and try again",
                tool_name="find_citing_articles",
            )
        except Exception as exc:
            logger.warning("Citing-article lookup failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                error="PubMed citing-article lookup failed",
                suggestion="Check PMID format and try again",
                tool_name="find_citing_articles",
            )

    @mcp.tool()
    async def get_article_references(pmid: PMIDText, limit: CitationLinkLimit = 20) -> str:
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
            pmid: PubMed ID of the source article ("12345678" or "PMID:12345678").
            limit: Maximum number of references to return (1-100, default: 20).

        Returns:
            List of referenced articles with details.
        """
        try:
            normalized_pmid = _normalize_public_pmid(pmid)
            normalized_limit = _validate_limit(limit, maximum=100)
        except (IdentifierValidationError, ValueError) as exc:
            return ResponseFormatter.error(
                error=exc,
                suggestion="Provide one PMID string and a limit between 1 and 100",
                example='get_article_references(pmid="12345678")',
                tool_name="get_article_references",
            )

        logger.info("Getting references for one PMID")
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

            output = f"📚 **References of PMID {normalized_pmid}** ({len(results)} found)\n\n"
            output += "These are the papers cited BY this article (its bibliography):\n\n"
            output += format_search_results(results)
            return output
        except PubMedSearchError as exc:
            logger.warning("Article-reference lookup failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                error=_public_source_failure(
                    "PubMed article-reference lookup failed",
                    exc,
                    operation="get_article_references",
                ),
                suggestion="Check PMID format and try again",
                tool_name="get_article_references",
            )
        except Exception as exc:
            logger.warning("Article-reference lookup failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                error="PubMed article-reference lookup failed",
                suggestion="Check PMID format and try again",
                tool_name="get_article_references",
            )

    @mcp.tool()
    async def fetch_article_details(
        pmids: PMIDBatchInput,
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
                   Inputs are string-only and fail as a complete batch when any PMID is invalid.

        Returns:
            Detailed information for each article.
        """
        normalized_output_format = normalize_output_format(output_format)
        try:
            normalized_pmids = _normalize_public_pmid_batch(pmids, allow_last=False)
        except IdentifierValidationError as exc:
            return ResponseFormatter.error(
                error=exc,
                suggestion="Provide one or more valid PMID numbers",
                example='fetch_article_details(pmids="12345678,87654321")',
                tool_name="fetch_article_details",
                output_format=normalized_output_format,
            )
        if not normalized_pmids:
            return ResponseFormatter.error(
                error="No PMIDs provided",
                suggestion="Provide one or more valid PMID numbers",
                example='fetch_article_details(pmids="12345678,87654321")',
                tool_name="fetch_article_details",
                output_format=normalized_output_format,
            )

        logger.info("Fetching details for %s PMID values", len(normalized_pmids))
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

            if is_structured_output_format(normalized_output_format):
                return _format_fetch_article_details_json(normalized_pmids, results, normalized_output_format)

            return format_search_results(results, include_doi=True)
        except PubMedSearchError as exc:
            logger.warning("Article-detail lookup failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                error=_public_source_failure(
                    "PubMed article-detail lookup failed",
                    exc,
                    operation="fetch_article_details",
                ),
                suggestion="Check PMID format and try again",
                tool_name="fetch_article_details",
                output_format=normalized_output_format,
            )
        except Exception as exc:
            logger.warning("Article-detail lookup failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                error="PubMed article-detail lookup failed",
                suggestion="Check PMID format and try again",
                tool_name="fetch_article_details",
                output_format=normalized_output_format,
            )

    @mcp.tool()
    async def get_citation_metrics(
        pmids: PMIDBatchInput,
        sort_by: CitationSortField = "citation_count",
        min_citations: NonNegativeCitationCount | None = None,
        min_rcr: NonNegativeMetric | None = None,
        min_percentile: PercentileThreshold | None = None,
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
                   Batches are fail-closed and limited to 1,000 unique PMIDs.
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
            iCite transport or response failures return an explicit retryable
            error and are never rendered as an empty/unindexed result.
        """
        normalized_output_format = normalize_output_format(output_format)

        try:
            normalized_pmids = _normalize_public_pmid_batch(pmids)
            _validate_citation_metric_inputs(
                sort_by=sort_by,
                min_citations=min_citations,
                min_rcr=min_rcr,
                min_percentile=min_percentile,
            )
        except (IdentifierValidationError, ValueError) as exc:
            return ResponseFormatter.error(
                error=exc,
                suggestion="Provide valid PMIDs and citation metric controls",
                example='get_citation_metrics(pmids="12345678", sort_by="citation_count")',
                tool_name="get_citation_metrics",
                output_format=normalized_output_format,
            )

        try:
            logger.info("Getting citation metrics for %d PMID values", len(normalized_pmids))

            # Handle "last" keyword
            if normalized_pmids == ["last"]:
                from ._common import get_last_search_pmids

                last_pmids = get_last_search_pmids()
                if not last_pmids:
                    return ResponseFormatter.error(
                        error="No previous search results found",
                        suggestion="Search first or provide PMIDs directly",
                        example='get_citation_metrics(pmids="12345678,87654321")',
                        tool_name="get_citation_metrics",
                        output_format=normalized_output_format,
                    )
                pmid_list = normalize_pmid_batch(last_pmids, allow_last=False)
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

        except ServiceUnavailableError as exc:
            logger.warning("Citation-metrics lookup failed (%s)", type(exc).__name__)
            safe_error = ServiceUnavailableError(
                "citation-metrics lookup failed",
                service="NIH iCite",
                context=ErrorContext(
                    operation="get_citation_metrics",
                    retry_after=exc.context.retry_after,
                ),
            )
            return ResponseFormatter.error(
                error=safe_error,
                suggestion="NIH iCite is temporarily unavailable; retry later and do not treat this as missing citation data",
                tool_name="get_citation_metrics",
                output_format=normalized_output_format,
            )
        except Exception as exc:
            logger.warning("Citation-metrics lookup failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                error="NIH iCite citation-metrics lookup failed",
                suggestion="Check PMID format and try again",
                tool_name="get_citation_metrics",
                output_format=normalized_output_format,
            )
