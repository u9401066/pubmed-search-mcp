"""
Europe PMC Tools - Access Europe PMC for fulltext and search.

Tools:
- get_fulltext: 🔥 Enhanced multi-source fulltext retrieval
  - Supports PMID, PMC ID, or DOI input
  - Auto-tries: Europe PMC → Unpaywall → CORE
  - Extended sources: CrossRef, DOAJ, Zenodo, PubMed LinkOut (15 total)
  - Returns fulltext content + PDF links
- get_text_mined_terms: Get text-mined annotations (genes, diseases, chemicals)

Internal (not registered):
- search_europe_pmc: Use unified_search instead
- get_fulltext_xml: Use get_fulltext instead
- get_europe_pmc_citations: Use find_citing_articles instead

Phase 2.2 Updates (v0.1.21):
- Multi-source fulltext: Europe PMC, Unpaywall, CORE
- Flexible input: PMID, PMC ID, or DOI
- PDF link aggregation from all sources

Phase 3 Updates (v0.2.8):
- Extended sources via FulltextDownloader (15 total sources)
- CrossRef, DOAJ, Zenodo, PubMed LinkOut integration
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal, Union

from mcp.server.fastmcp import Context  # noqa: TC002 - FastMCP needs runtime access for tool context injection

from pubmed_search.application.fulltext import FulltextRequest, FulltextService
from pubmed_search.infrastructure.sources import get_europe_pmc_client
from pubmed_search.infrastructure.sources.core import get_core_client
from pubmed_search.infrastructure.sources.unpaywall import get_unpaywall_client

from ._common import InputNormalizer, ResponseFormatter
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
    sort_source_count_rows,
)
from .tool_runtime import safe_log, safe_report_progress

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def _build_fulltext_next_tools(
    *,
    pmcid: str | None,
    pmid: str | None,
    include_figures: bool,
    output_format: OutputFormat = "json",
) -> tuple[list[dict[str, str]], list[str]]:
    """Build pragmatic next-tool suggestions for get_fulltext."""
    structured_output_format = preferred_structured_output_format(output_format)
    suggestions: list[dict[str, str]] = []

    if pmid:
        suggestions.append(
            make_next_tool(
                "fetch_article_details",
                "Resolve the PubMed metadata record alongside the fulltext view before branching further.",
                f'fetch_article_details(pmids="{pmid}", output_format="{structured_output_format}")',
            )
        )
        suggestions.append(
            make_next_tool(
                "get_text_mined_terms",
                "Use Europe PMC annotations to extract entities from this article after confirming access.",
                f'get_text_mined_terms(pmid="{pmid}")',
            )
        )

    if pmcid and not include_figures:
        suggestions.append(
            make_next_tool(
                "get_article_figures",
                "A PMCID is available, so you can pivot into structured figure extraction next.",
                f'get_article_figures(identifier="{pmcid}")',
            )
        )
    elif pmcid:
        suggestions.append(
            make_next_tool(
                "get_text_mined_terms",
                "You already have PMC-backed access; annotate the same article for entities and concepts.",
                f'get_text_mined_terms(pmcid="{pmcid}")',
            )
        )

    return finalize_next_tools(suggestions)


def _build_fulltext_source_counts(
    *,
    sources_tried: list[str],
    fulltext_source: str | None,
    pdf_links: list[dict[str, Any]],
    figures_count: int,
) -> list[dict[str, Any]]:
    """Summarize how many response artifacts each source contributed."""
    artifact_counts: dict[str, int] = dict.fromkeys(sources_tried, 0)

    if fulltext_source:
        artifact_counts[fulltext_source] = artifact_counts.get(fulltext_source, 0) + 1

    for link in pdf_links:
        source_name = str(link.get("source") or "unknown")
        artifact_counts[source_name] = artifact_counts.get(source_name, 0) + 1

    if figures_count > 0:
        artifact_counts["PMC Open Access / FigureClient"] = (
            artifact_counts.get(
                "PMC Open Access / FigureClient",
                0,
            )
            + figures_count
        )

    return [
        dict(row)
        for row in sort_source_count_rows(
            [make_source_count_row(source, count) for source, count in artifact_counts.items()]
        )
    ]


def _format_get_fulltext_json(
    *,
    identifier: str | None,
    pmcid: str | None,
    pmid: str | None,
    doi: str | None,
    title: str | None,
    fulltext_content: str | None,
    content_sections: list[dict[str, Any]],
    pdf_links: list[dict[str, Any]],
    sources_tried: list[str],
    source_counts: list[dict[str, Any]],
    next_tools: list[dict[str, str]],
    next_commands: list[str],
    fulltext_source: str | None,
    fulltext_canonical_host: str | None,
    fulltext_provenance: Literal["direct", "indirect", "derived", "mixed"] | None,
    include_figures: bool,
    figures: list[dict[str, Any]],
    output_format: OutputFormat = "json",
) -> str:
    """Format get_fulltext as an agent-oriented JSON or TOON envelope."""
    section_provenance: dict[str, dict[str, Any]] = {
        "source_counts": make_section_provenance(
            surfacing_source="pubmed-search-mcp",
            canonical_host=None,
            provenance="derived",
            note="Counts describe response artifacts yielded per source in this fulltext workflow (content blocks, links, figures).",
            upstream_sources=sources_tried,
        ),
        "next_tools": make_section_provenance(
            surfacing_source="pubmed-search-mcp",
            canonical_host="pubmed-search-mcp",
            provenance="derived",
            note="Next-tool suggestions are inferred locally from resolved identifiers and access path shape.",
        ),
    }

    if fulltext_source and fulltext_provenance:
        section_provenance["content"] = make_section_provenance(
            surfacing_source=fulltext_source,
            canonical_host=fulltext_canonical_host,
            provenance=fulltext_provenance,
            note="Structured or extracted article text came from the reported surfacing source.",
            fields=[section.get("title", "") for section in content_sections] if content_sections else None,
        )

    if pdf_links:
        section_provenance["pdf_links"] = make_section_provenance(
            surfacing_source="fulltext-link-aggregation",
            canonical_host=None,
            provenance="mixed",
            note="Each link preserves the surfacing source; the final OA or publisher host may differ by URL.",
            upstream_sources=[str(link.get("source") or "unknown") for link in pdf_links],
        )

    if figures:
        section_provenance["figures"] = make_section_provenance(
            surfacing_source="PMC Open Access / FigureClient",
            canonical_host="PubMed Central",
            provenance="mixed",
            note="Figure metadata is extracted through the PMC-focused figure client and remains article-license scoped.",
        )

    payload = {
        "tool": "get_fulltext",
        "identifiers": {
            "identifier": identifier,
            "pmcid": pmcid,
            "pmid": pmid,
            "doi": doi,
        },
        "title": title,
        "fulltext_available": bool(fulltext_content),
        "content": fulltext_content,
        "content_sections": content_sections,
        "pdf_links": pdf_links,
        "sources_tried": sources_tried,
        "source_counts": source_counts,
        "next_tools": next_tools,
        "next_commands": next_commands,
        "include_figures": include_figures,
        "figures": figures,
        "section_provenance": section_provenance,
    }
    return serialize_structured_payload(payload, output_format)


def _format_text_mined_terms_structured(
    *,
    pmid: str | None,
    pmcid: str | None,
    semantic_type: str | None,
    terms: list[dict[str, Any]],
    output_format: OutputFormat = "json",
) -> str:
    """Format Europe PMC text-mined terms as a structured agent-facing payload."""
    structured_output_format = preferred_structured_output_format(output_format)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for term in terms:
        term_type = str(term.get("semantic_type") or "OTHER")
        by_type.setdefault(term_type, []).append(term)

    grouped_terms: list[dict[str, Any]] = []
    for term_type in sorted(by_type):
        type_terms = by_type[term_type]
        counts: dict[str, int] = {}
        for term in type_terms:
            name = str(term.get("term") or term.get("name") or "Unknown")
            counts[name] = counts.get(name, 0) + 1

        grouped_terms.append(
            {
                "semantic_type": term_type,
                "annotation_count": len(type_terms),
                "unique_term_count": len(counts),
                "terms": [
                    {"term": name, "count": count}
                    for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
                ],
            }
        )

    next_tool_candidates: list[dict[str, str]] = []
    if pmid:
        next_tool_candidates.append(
            make_next_tool(
                "fetch_article_details",
                "Hydrate PubMed metadata for the annotated article before moving into citation or export workflows.",
                f'fetch_article_details(pmids="{pmid}", output_format="{structured_output_format}")',
            )
        )
        next_tool_candidates.append(
            make_next_tool(
                "get_fulltext",
                "Inspect the article text alongside its extracted entities and concepts.",
                (f'get_fulltext(pmid="{pmid}", extended_sources=True, output_format="{structured_output_format}")'),
            )
        )
    if pmcid:
        next_tool_candidates.append(
            make_next_tool(
                "get_article_figures",
                "PMC-backed annotations can be paired with figure evidence from the same open-access article.",
                f'get_article_figures(identifier="{pmcid}", output_format="{structured_output_format}")',
            )
        )

    next_tools, next_commands = finalize_next_tools(next_tool_candidates)
    visible_fields = sorted(
        {key for term in terms for key, value in term.items() if value not in (None, "", [], {}, ())}
    )
    payload = {
        "tool": "get_text_mined_terms",
        "identifiers": {"pmid": pmid, "pmcid": pmcid},
        "semantic_type_filter": semantic_type,
        "annotation_count": len(terms),
        "unique_term_count": sum(group["unique_term_count"] for group in grouped_terms),
        "annotations": terms,
        "term_groups": grouped_terms,
        "source_counts": [make_source_count_row("europe-pmc-text-mining", len(terms))],
        "next_tools": next_tools,
        "next_commands": next_commands,
        "section_provenance": {
            "annotations": make_section_provenance(
                surfacing_source="Europe PMC",
                canonical_host="Europe PMC",
                provenance="direct",
                note="Text-mined annotations are retrieved directly from Europe PMC's annotation service.",
                fields=visible_fields,
            ),
            "term_groups": make_section_provenance(
                surfacing_source="pubmed-search-mcp",
                canonical_host=None,
                provenance="derived",
                note="Grouped term counts are derived locally from the raw Europe PMC annotations.",
                upstream_sources=["europe-pmc-text-mining"],
            ),
            "source_counts": make_section_provenance(
                surfacing_source="pubmed-search-mcp",
                canonical_host=None,
                provenance="derived",
                note="Counts reflect the number of annotation rows returned by Europe PMC.",
                upstream_sources=["europe-pmc-text-mining"],
            ),
            "next_tools": make_section_provenance(
                surfacing_source="pubmed-search-mcp",
                canonical_host="pubmed-search-mcp",
                provenance="derived",
                note="Next-tool suggestions are inferred locally from the resolved identifiers and annotation payload.",
            ),
        },
    }
    return serialize_structured_payload(payload, output_format)


def register_europe_pmc_tools(mcp: FastMCP):
    """
    Register Europe PMC tools for fulltext access and text mining.

    Note: search_europe_pmc is NOT registered - use unified_search instead.
    Only registers:
    - get_fulltext: Get parsed fulltext content
    - get_text_mined_terms: Get text-mined annotations
    """

    # NOTE: search_europe_pmc is NOT registered as a tool.
    # Use unified_search(sources=["europe_pmc"]) instead.
    # Keeping the function for internal use by unified_search.
    # @mcp.tool()  # REMOVED - integrated into unified_search
    async def search_europe_pmc(
        query: str,
        limit: int = 10,
        min_year: int | None = None,
        max_year: int | None = None,
        open_access_only: bool = False,
        has_fulltext: bool = False,
        sort: str = "relevance",
    ) -> str:
        """
        Search Europe PMC for scientific literature.

        Europe PMC indexes 33M+ publications with 6.5M open access fulltext.
        Best for: finding open access papers, getting fulltext, European research.

        Args:
            query: Search query (supports standard boolean operators AND, OR, NOT).
            limit: Maximum number of results (1-100, default: 10).
            min_year: Filter by minimum publication year (e.g., 2020).
            max_year: Filter by maximum publication year (e.g., 2024).
            open_access_only: Only return open access papers.
            has_fulltext: Only return papers with fulltext available in Europe PMC.
            sort: Sort order - "relevance" (default), "date" (newest first), or "cited" (most cited).

        Returns:
            Search results with titles, abstracts, and fulltext availability.
        """
        # Phase 2.1: Input normalization
        normalized_query = InputNormalizer.normalize_query(query)
        if not normalized_query:
            return ResponseFormatter.error(
                error="Query is required",
                suggestion="Provide a search query",
                example='search_europe_pmc(query="COVID-19 treatment")',
                tool_name="search_europe_pmc",
            )

        normalized_limit = InputNormalizer.normalize_limit(limit, default=10, min_val=1, max_val=100)
        normalized_min_year = InputNormalizer.normalize_year(min_year)
        normalized_max_year = InputNormalizer.normalize_year(max_year)
        normalized_oa_only = InputNormalizer.normalize_bool(open_access_only, default=False)
        normalized_fulltext = InputNormalizer.normalize_bool(has_fulltext, default=False)

        logger.info(f"Searching Europe PMC: query='{normalized_query}', limit={normalized_limit}")

        try:
            client = get_europe_pmc_client()

            # Map sort_by to Europe PMC sort syntax
            sort_map = {
                "relevance": None,  # Default sorting
                "date": "P_PDATE_D desc",
                "cited": "CITED desc",
            }
            sort_param = sort_map.get(sort)

            result = await client.search(
                query=normalized_query,
                limit=normalized_limit,
                min_year=normalized_min_year,
                max_year=normalized_max_year,
                open_access_only=normalized_oa_only,
                has_fulltext=normalized_fulltext,
                sort=sort_param,
            )

            if not result.get("results"):
                return ResponseFormatter.no_results(
                    query=normalized_query,
                    suggestions=[
                        "Try broader search terms",
                        "Remove year filters",
                        "Disable open_access_only filter",
                        "Try unified_search for PubMed or multi-source discovery instead",
                    ],
                )

            total = result.get("hit_count", len(result["results"]))
            articles = result["results"]

            # Format header
            output = "📚 **Europe PMC Search Results**\n"
            output += f"Found **{len(articles)}** results"
            if total > len(articles):
                output += f" (of {total:,} total)"

            filters = []
            if normalized_oa_only:
                filters.append("Open Access")
            if normalized_fulltext:
                filters.append("Fulltext available")
            if normalized_min_year or normalized_max_year:
                year_range = f"{normalized_min_year or '...'}-{normalized_max_year or '...'}"
                filters.append(year_range)
            if filters:
                output += f" | Filters: {', '.join(filters)}"
            output += "\n\n"

            # Format results
            for i, article in enumerate(articles, 1):
                pmid = article.get("pmid", "N/A")
                pmc_id = article.get("pmc_id", "")
                title = article.get("title", "No title")
                authors = article.get("authors", [])
                year = article.get("year", "")
                journal = article.get("journal", "")

                # Format author string
                if authors:
                    author_str = f"{authors[0]} et al." if len(authors) > 3 else ", ".join(authors)
                else:
                    author_str = article.get("author_string", "Unknown authors")

                # Status indicators
                indicators = []
                if article.get("is_open_access"):
                    indicators.append("🔓 OA")
                if article.get("has_fulltext"):
                    indicators.append("📄 Fulltext")
                if article.get("citation_count"):
                    indicators.append(f"📊 {article['citation_count']} cites")

                output += f"**{i}. [{pmid}]** {title}\n"
                output += f"   👤 {author_str} | 📅 {year} | 📰 {journal}\n"
                if pmc_id:
                    output += f"   🆔 PMC: {pmc_id}"
                if indicators:
                    output += f" | {' | '.join(indicators)}"
                output += "\n"

                # Abstract preview
                abstract = article.get("abstract", "")
                if abstract:
                    preview = abstract[:200] + "..." if len(abstract) > 200 else abstract
                    output += f"   📝 {preview}\n"

                output += "\n"

            # Add fulltext hint
            fulltext_available = [a for a in articles if a.get("has_fulltext") or a.get("pmc_id")]
            if fulltext_available:
                pmc_ids = [a.get("pmc_id") for a in fulltext_available[:3] if a.get("pmc_id")]
                if pmc_ids:
                    output += "---\n"
                    output += f"💡 **Tip**: Use `get_fulltext(pmcid='{pmc_ids[0]}')` to read the full paper\n"

            return output

        except Exception as e:
            logger.exception(f"Europe PMC search failed: {e}")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check query syntax and try again",
                tool_name="search_europe_pmc",
            )

    @mcp.tool()
    async def get_fulltext(
        identifier: str | None = None,
        pmcid: Union[str, int] | None = None,
        pmid: Union[str, int] | None = None,
        doi: str | None = None,
        sections: str | None = None,
        include_pdf_links: bool = True,
        include_figures: bool = False,
        extended_sources: bool = False,
        output_format: Literal["markdown", "json", "toon"] = "markdown",
        allow_browser_session: bool | None = None,
        ctx: Context | None = None,
    ) -> str:
        """
        🔥 Enhanced multi-source fulltext retrieval.

        Automatically tries multiple sources to find the best fulltext:
        1. Europe PMC (if PMC ID available)
        2. Unpaywall (finds OA versions via DOI)
        3. CORE (200M+ open access papers)

        With extended_sources=True, also searches:
        4. CrossRef (publisher links)
        5. DOAJ (Gold OA journals)
        6. Zenodo (research repository)
        7. PubMed LinkOut (external providers)
        8. Semantic Scholar, OpenAlex, arXiv, bioRxiv, medRxiv

        Accepts flexible input - provide ANY ONE of:
        - identifier: Auto-detects PMID, PMC ID, or DOI
        - pmcid: Direct PMC ID
        - pmid: PubMed ID (will lookup PMC ID)
        - doi: DOI (will search Unpaywall/CORE)

        Args:
            identifier: Auto-detect format - PMID, PMC ID, or DOI
                       Examples: "PMC7096777", "12345678", "10.1001/jama.2024.1234"
            pmcid: PubMed Central ID (e.g., "PMC7096777", "7096777")
            pmid: PubMed ID (e.g., "12345678")
            doi: DOI (e.g., "10.1001/jama.2024.1234")
            sections: Filter sections (e.g., "introduction,methods,results")
            include_pdf_links: Include PDF download links (default: True)
            include_figures: Include figure metadata with image URLs (default: False)
            extended_sources: Search 15 sources instead of 3 (default: False)
            output_format: Response format - "markdown" (default), "json", or "toon"
            allow_browser_session: Control browser-session fallback.
                - True: force broker fallback when configured
                - False: disable broker fallback
                - None: use auto mode from broker configuration

        Returns:
            Fulltext content with PDF links from all available sources.

        Example:
            get_fulltext(identifier="PMC7096777")
            get_fulltext(doi="10.1038/s41586-021-03819-2")
            get_fulltext(pmid="12345678", extended_sources=True)
        """

        async def _progress(progress: float, total: float, message: str) -> None:
            await safe_report_progress(ctx, progress, total, message)

        async def _log(level: Literal["debug", "info", "warning", "error"], message: str) -> None:
            await safe_log(ctx, level, message, logger_name=__name__)

        await _progress(1, 6, "Resolving article identifiers...")
        normalized_output_format = normalize_output_format(output_format)

        # Phase 2.2: Smart identifier detection
        detected_pmcid = pmcid
        detected_doi = doi
        detected_pmid = pmid

        if identifier:
            identifier = str(identifier).strip()
            # Detect format
            if identifier.upper().startswith("PMC") or (identifier.isdigit() and len(identifier) > 6):
                if identifier.upper().startswith("PMC"):
                    detected_pmcid = identifier
                # Could be PMID or PMC number - assume PMID if < 8 digits
                elif len(identifier) <= 8:
                    detected_pmid = identifier
                else:
                    detected_pmcid = f"PMC{identifier}"
            elif identifier.startswith("10.") or "doi.org" in identifier:
                # DOI format
                detected_doi = identifier.replace("https://doi.org/", "").replace("http://doi.org/", "")
            elif identifier.isdigit():
                detected_pmid = identifier
            else:
                # Try as PMID
                detected_pmid = identifier

        # Normalize inputs
        if detected_pmcid:
            detected_pmcid = InputNormalizer.normalize_pmcid(str(detected_pmcid))
        if detected_pmid:
            detected_pmid = InputNormalizer.normalize_pmid_single(detected_pmid)

        if not any([detected_pmcid, detected_pmid, detected_doi]):
            return ResponseFormatter.error(
                error="No valid identifier provided",
                suggestion="Provide pmcid, pmid, doi, or auto-detect identifier",
                example='get_fulltext(identifier="PMC7096777") or get_fulltext(doi="10.1038/...")',
                tool_name="get_fulltext",
                output_format=normalized_output_format,
            )

        logger.info(f"Getting fulltext: pmcid={detected_pmcid}, pmid={detected_pmid}, doi={detected_doi}")
        await _log(
            "info",
            f"get_fulltext start pmcid={detected_pmcid} pmid={detected_pmid} doi={'yes' if detected_doi else 'no'}",
        )

        browser_session_note = None

        from pubmed_search.infrastructure.sources.figure_client import get_figure_client
        from pubmed_search.infrastructure.sources.fulltext_download import FulltextDownloader

        service = FulltextService(
            europe_pmc_client_factory=get_europe_pmc_client,
            unpaywall_client_factory=get_unpaywall_client,
            core_client_factory=get_core_client,
            downloader_factory=FulltextDownloader,
            figure_client_factory=get_figure_client if include_figures else None,
        )
        retrieval = await service.retrieve(
            FulltextRequest(
                identifier=identifier,
                pmcid=str(detected_pmcid) if detected_pmcid else None,
                pmid=str(detected_pmid) if detected_pmid else None,
                doi=str(detected_doi) if detected_doi else None,
                sections=sections,
                include_figures=include_figures,
                extended_sources=extended_sources,
                allow_browser_session=allow_browser_session,
            ),
            progress=_progress,
            log=_log,
        )

        # Keep the main service as the primary path, then fall back to
        # multi-source PDF retrieval only when the service has not already
        # attempted the extended downloader path.
        if (
            not retrieval.fulltext_content
            and any([detected_pmid, detected_pmcid, detected_doi])
            and not retrieval.extended_sources_attempted
        ):
            await _progress(5.5, 6, "Trying multi-source PDF retrieval fallback...")
            retrieval.sources_tried.append("PDF Retrieval Fallback")
            try:
                from pubmed_search.infrastructure.sources.fulltext_download import (
                    FulltextDownloader,
                    PDFSource,
                )

                downloader = FulltextDownloader()
                try:
                    assisted = await downloader.get_fulltext(
                        pmid=str(detected_pmid) if detected_pmid else None,
                        pmcid=str(detected_pmcid) if detected_pmcid else None,
                        doi=str(detected_doi) if detected_doi else None,
                        strategy="extract_text",
                        allow_browser_session=allow_browser_session,
                    )
                finally:
                    await downloader.close()

                seen_urls = {str(link.get("url") or "") for link in retrieval.pdf_links}
                for ext_link in assisted.pdf_links:
                    if not ext_link.url or ext_link.url in seen_urls:
                        continue
                    seen_urls.add(ext_link.url)
                    retrieval.pdf_links.append(
                        {
                            "source": ext_link.source.display_name,
                            "url": ext_link.url,
                            "type": "pdf" if ext_link.is_direct_pdf else "landing_page",
                            "access": ext_link.access_type,
                            "version": ext_link.version,
                            "license": ext_link.license,
                        }
                    )

                if assisted.text_content:
                    retrieval.fulltext_content = assisted.text_content
                    retrieval.content_sections = [
                        {
                            "title": "Extracted PDF Text",
                            "content": assisted.text_content,
                        }
                    ]
                    if assisted.source_used:
                        retrieval.fulltext_source_name = assisted.source_used.display_name
                        retrieval.fulltext_canonical_host = assisted.source_used.display_name
                        retrieval.fulltext_provenance = "derived"

                if not retrieval.title and assisted.title:
                    retrieval.title = assisted.title

                note_parts: list[str] = []
                if assisted.source_used == PDFSource.BROWSER_SESSION:
                    if assisted.text_content:
                        note_parts.append(
                            f"🔐 Browser-session broker fetched PDF and extracted text from {assisted.retrieved_url or 'institutional access'}"
                        )
                    else:
                        note_parts.append(
                            f"🔐 Browser-session broker fetched PDF from {assisted.retrieved_url or 'institutional access'}"
                        )
                elif assisted.source_used:
                    if assisted.text_content:
                        note_parts.append(
                            f"📄 PDF retrieval fallback extracted text via {assisted.source_used.display_name}"
                        )
                    else:
                        note_parts.append(
                            f"📄 PDF retrieval fallback retrieved PDF via {assisted.source_used.display_name}"
                        )
                if assisted.error:
                    note_parts.append(f"⚠️ PDF retrieval fallback did not succeed: {assisted.error}")

                if note_parts:
                    browser_session_note = "\n".join(note_parts)
            except Exception as e:
                logger.warning(f"PDF retrieval fallback failed: {e}")
                await _log("warning", f"PDF retrieval fallback failed: {e!s}")

        next_tools, next_commands = _build_fulltext_next_tools(
            pmcid=str(detected_pmcid) if detected_pmcid else None,
            pmid=str(detected_pmid) if detected_pmid else None,
            include_figures=include_figures,
            output_format=normalized_output_format,
        )
        exposed_pdf_links = retrieval.pdf_links if include_pdf_links else []
        source_counts = _build_fulltext_source_counts(
            sources_tried=retrieval.sources_tried,
            fulltext_source=retrieval.fulltext_source_name,
            pdf_links=exposed_pdf_links,
            figures_count=len(retrieval.figures),
        )

        # === BUILD OUTPUT ===
        if is_structured_output_format(normalized_output_format):
            return _format_get_fulltext_json(
                identifier=identifier,
                pmcid=str(detected_pmcid) if detected_pmcid else None,
                pmid=str(detected_pmid) if detected_pmid else None,
                doi=str(detected_doi) if detected_doi else None,
                title=retrieval.title,
                fulltext_content=retrieval.fulltext_content,
                content_sections=retrieval.content_sections,
                pdf_links=exposed_pdf_links,
                sources_tried=retrieval.sources_tried,
                source_counts=source_counts,
                next_tools=next_tools,
                next_commands=next_commands,
                fulltext_source=retrieval.fulltext_source_name,
                fulltext_canonical_host=retrieval.fulltext_canonical_host,
                fulltext_provenance=retrieval.fulltext_provenance,
                include_figures=include_figures,
                figures=retrieval.figures,
                output_format=normalized_output_format,
            )

        if not retrieval.fulltext_content and not retrieval.pdf_links:
            return ResponseFormatter.no_results(
                query=f"pmcid={detected_pmcid}, pmid={detected_pmid}, doi={detected_doi}",
                suggestions=[
                    "Article may not be open access",
                    "Try searching with DOI for Unpaywall lookup",
                    "Check if article is available in PubMed Central",
                    f"Sources tried: {', '.join(retrieval.sources_tried)}",
                ],
                output_format=normalized_output_format,
                tool_name="get_fulltext",
            )

        # Format output
        await _progress(6, 6, "Formatting fulltext response...")
        output = f"📖 **{retrieval.title or 'Fulltext Retrieved'}**\n"
        output += f"🔍 Sources checked: {', '.join(retrieval.sources_tried)}\n\n"

        if browser_session_note:
            output += browser_session_note + "\n\n"

        # PDF Links section
        if retrieval.pdf_links and include_pdf_links:
            output += "## 📥 PDF/Fulltext Links\n\n"
            for link in retrieval.pdf_links:
                icon = "📄" if link["type"] == "pdf" else "🔗"
                access_badge = {
                    "gold": "🥇 Gold OA",
                    "green": "🟢 Green OA",
                    "hybrid": "🔶 Hybrid",
                    "bronze": "🟤 Bronze",
                    "open_access": "🔓 Open Access",
                    "alternative": "📋 Alternative",
                    "subscription": "🏛️ Institutional",
                }.get(link.get("access", ""), "")

                output += f"- {icon} **{link['source']}** {access_badge}\n"
                output += f"  {link['url']}\n"
                if link.get("version"):
                    output += f"  _Version: {link['version']}_\n"
                if link.get("license"):
                    output += f"  _License: {link['license']}_\n"
            output += "\n"

        # Fulltext content
        if retrieval.fulltext_content:
            output += "## 📝 Content\n\n"
            output += retrieval.fulltext_content
        elif retrieval.pdf_links:
            output += "_Structured fulltext not available. Use the PDF links above to access the article._\n"
            if any(link.get("access") == "subscription" for link in retrieval.pdf_links):
                output += "_Institutional links usually require campus IP recognition or library VPN/proxy access._\n"

        if retrieval.figures:
            output += "\n---\n"
            output += f"## 🖼️ Figures ({len(retrieval.figures)})\n\n"
            for fig in retrieval.figures:
                output += f"#### {fig.get('label') or fig.get('figure_id', 'Figure')}\n"
                if fig.get("caption_title"):
                    output += f"**{fig['caption_title']}**\n\n"
                if fig.get("caption_text"):
                    output += f"{fig['caption_text']}\n\n"
                if fig.get("image_url"):
                    output += f"**Image URL:** {fig['image_url']}\n\n"

        return output

    # NOTE: get_fulltext_xml is NOT registered as a tool.
    # Use get_fulltext instead - it provides better parsed output.
    # @mcp.tool()  # REMOVED - use get_fulltext instead
    async def get_fulltext_xml(pmcid: Union[str, int]) -> str:
        """
        Get raw JATS XML fulltext from Europe PMC.

        Returns the complete XML document in JATS format. Use this if you need
        the raw XML structure for custom parsing or analysis.

        Args:
            pmcid: PubMed Central ID (accepts: "PMC7096777", "7096777", 7096777).

        Returns:
            JATS XML document as string, or error message.
        """
        # Phase 2.1: Input normalization
        pmcid_normalized = InputNormalizer.normalize_pmcid(str(pmcid) if pmcid else None)
        if not pmcid_normalized:
            return ResponseFormatter.error(
                error="Invalid PMC ID format",
                suggestion="Provide a valid PMC ID number",
                example='get_fulltext_xml(pmcid="PMC7096777")',
                tool_name="get_fulltext_xml",
            )

        logger.info(f"Getting fulltext XML for: {pmcid_normalized}")

        try:
            client = get_europe_pmc_client()

            xml = await client.get_fulltext_xml(pmcid_normalized)
            if not xml:
                return ResponseFormatter.no_results(
                    query=pmcid_normalized,
                    suggestions=[
                        "Article may not be in PMC",
                        "Article may not be open access",
                    ],
                )

            # Return with size info
            output = f"<!-- JATS XML for {pmcid_normalized} ({len(xml):,} bytes) -->\n\n"

            # Truncate if very large
            if len(xml) > 50000:
                output += xml[:50000]
                output += f"\n\n<!-- ... {len(xml) - 50000:,} bytes truncated -->"
            else:
                output += xml

            return output

        except Exception as e:
            logger.exception(f"Get fulltext XML failed: {e}")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check if the PMC ID is correct",
                tool_name="get_fulltext_xml",
            )

    @mcp.tool()
    async def get_text_mined_terms(
        pmid: Union[str, int] | None = None,
        pmcid: Union[str, int] | None = None,
        semantic_type: str | None = None,
        output_format: Literal["markdown", "json", "toon"] = "markdown",
        ctx: Context | None = None,
    ) -> str:
        """
        Get text-mined annotations from Europe PMC.

        Returns entities extracted from the article text including genes, diseases,
        chemicals, organisms, and more. Useful for identifying key concepts.

        Args:
            pmid: PubMed ID of the article (accepts: "12345678", 12345678).
            pmcid: PMC ID (alternative to PMID, accepts: "PMC7096777", "7096777").
            semantic_type: Filter by entity type. Options:
                - "GENE_PROTEIN": Genes and proteins
                - "DISEASE": Diseases and conditions
                - "CHEMICAL": Drugs and chemicals
                - "ORGANISM": Species and organisms
                - "GO_TERM": Gene Ontology terms
                - None: Return all types (default)

        Returns:
            List of text-mined entities with counts and sections.
        """

        async def _progress(progress: float, total: float, message: str) -> None:
            await safe_report_progress(ctx, progress, total, message)

        # Phase 2.1: Input normalization
        normalized_pmid = InputNormalizer.normalize_pmid_single(pmid) if pmid else None
        normalized_pmcid = InputNormalizer.normalize_pmcid(str(pmcid)) if pmcid else None
        normalized_output_format = normalize_output_format(output_format)

        logger.info(f"Getting text-mined terms for PMID={normalized_pmid}, PMCID={normalized_pmcid}")

        try:
            await _progress(1, 3, "Resolving article identifier...")
            if not normalized_pmid and not normalized_pmcid:
                return ResponseFormatter.error(
                    error="Either pmid or pmcid is required",
                    suggestion="Provide a PMID or PMC ID",
                    example='get_text_mined_terms(pmid="12345678")',
                    tool_name="get_text_mined_terms",
                    output_format=normalized_output_format,
                )

            client = get_europe_pmc_client()

            # Determine source and ID
            if normalized_pmid:
                source = "MED"
                article_id = normalized_pmid
            else:
                source = "PMC"
                # Extract digits from normalized PMCID (PMC7096777 -> 7096777)
                if normalized_pmcid and normalized_pmcid.startswith("PMC"):
                    article_id = normalized_pmcid[3:]
                else:
                    article_id = normalized_pmcid or ""

            await _progress(2, 3, "Fetching Europe PMC text-mined annotations...")
            terms = await client.get_text_mined_terms(source, str(article_id), semantic_type)

            if not terms:
                id_str = f"PMID:{normalized_pmid}" if normalized_pmid else f"PMC:{normalized_pmcid}"
                return ResponseFormatter.no_results(
                    query=id_str,
                    suggestions=[
                        "Article may not have text-mining data",
                        "Try a different article",
                    ],
                    output_format=normalized_output_format,
                    tool_name="get_text_mined_terms",
                )

            if is_structured_output_format(normalized_output_format):
                await _progress(3, 3, "Formatting structured annotation response...")
                return _format_text_mined_terms_structured(
                    pmid=str(normalized_pmid) if normalized_pmid else None,
                    pmcid=str(normalized_pmcid) if normalized_pmcid else None,
                    semantic_type=semantic_type,
                    terms=terms,
                    output_format=normalized_output_format,
                )

            # Group by semantic type
            by_type: dict[str, list[dict[str, Any]]] = {}
            for term in terms:
                term_type = term.get("semantic_type", "OTHER")
                if term_type not in by_type:
                    by_type[term_type] = []
                by_type[term_type].append(term)

            # Format output
            id_str = f"PMID:{pmid}" if pmid else f"PMC:{pmcid}"
            output = f"🔬 **Text-Mined Terms for {id_str}**\n\n"
            output += f"Total: {len(terms)} annotations\n\n"

            # Type emoji mapping
            type_emoji = {
                "GENE_PROTEIN": "🧬",
                "DISEASE": "🏥",
                "CHEMICAL": "💊",
                "ORGANISM": "🦠",
                "GO_TERM": "📋",
                "EFO": "🔬",
            }

            for term_type, type_terms in sorted(by_type.items()):
                emoji = type_emoji.get(term_type, "📌")
                output += f"### {emoji} {term_type} ({len(type_terms)})\n\n"

                # Deduplicate and count
                term_counts: dict[str, int] = {}
                for t in type_terms:
                    name = t.get("term", t.get("name", "Unknown"))
                    term_counts[name] = term_counts.get(name, 0) + 1

                # Sort by frequency
                sorted_terms = sorted(term_counts.items(), key=lambda x: x[1], reverse=True)

                # Show top 10 per type
                for name, count in sorted_terms[:10]:
                    output += f"- **{name}**"
                    if count > 1:
                        output += f" (×{count})"
                    output += "\n"

                if len(sorted_terms) > 10:
                    output += f"- _...and {len(sorted_terms) - 10} more_\n"

                output += "\n"

            await _progress(3, 3, "Text-mined terms ready")
            return output

        except Exception as e:
            logger.exception(f"Get text-mined terms failed: {e}")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check the ID and try again",
                tool_name="get_text_mined_terms",
                output_format=normalized_output_format,
            )

    # NOTE: get_europe_pmc_citations is NOT registered as a tool.
    # Use find_citing_articles or get_article_references instead.
    # @mcp.tool()  # REMOVED - use find_citing_articles instead
    async def get_europe_pmc_citations(
        pmid: Union[str, int] | None = None,
        pmcid: Union[str, int] | None = None,
        direction: str = "citing",
        limit: int = 20,
    ) -> str:
        """
        Get citation network from Europe PMC.

        Can retrieve either articles that cite this paper (forward) or
        references this paper cites (backward).

        Args:
            pmid: PubMed ID of the source article (accepts: "12345678", 12345678).
            pmcid: PMC ID (alternative to PMID, accepts: "PMC7096777", "7096777").
            direction: Citation direction:
                - "citing": Papers that cite this article (forward in time, default)
                - "references": Papers this article cites (backward, its bibliography)
            limit: Maximum number of results (1-100, default: 20).

        Returns:
            List of citing or referenced articles.
        """
        # Phase 2.1: Input normalization
        normalized_pmid = InputNormalizer.normalize_pmid_single(pmid) if pmid else None
        normalized_pmcid = InputNormalizer.normalize_pmcid(str(pmcid)) if pmcid else None
        normalized_limit = InputNormalizer.normalize_limit(limit, default=20, min_val=1, max_val=100)

        logger.info(f"Getting {direction} for PMID={normalized_pmid}, PMCID={normalized_pmcid}")

        try:
            if not normalized_pmid and not normalized_pmcid:
                return ResponseFormatter.error(
                    error="Either pmid or pmcid is required",
                    suggestion="Provide a PMID or PMC ID",
                    example='get_europe_pmc_citations(pmid="12345678")',
                    tool_name="get_europe_pmc_citations",
                )

            client = get_europe_pmc_client()

            # Determine source and ID
            if normalized_pmid:
                source = "MED"
                article_id = normalized_pmid
            else:
                source = "PMC"
                if normalized_pmcid and normalized_pmcid.startswith("PMC"):
                    article_id = normalized_pmcid[3:]
                else:
                    article_id = normalized_pmcid or ""

            # Get citations or references
            if direction == "references":
                results = await client.get_references(source, str(article_id), limit=normalized_limit)
                direction_label = "References (Bibliography)"
                direction_desc = "papers cited BY this article"
            else:
                results = await client.get_citations(source, str(article_id), limit=normalized_limit)
                direction_label = "Citing Articles"
                direction_desc = "papers that cite this article"

            if not results:
                id_str = f"PMID:{normalized_pmid}" if normalized_pmid else f"PMC:{normalized_pmcid}"
                return ResponseFormatter.no_results(
                    query=id_str,
                    suggestions=[
                        f"Article may have no {direction}",
                        "Try find_citing_articles or get_article_references for PubMed data",
                    ],
                )

            # Format output
            id_str = f"PMID:{pmid}" if pmid else f"PMC:{pmcid}"
            output = f"📖 **{direction_label} for {id_str}**\n"
            output += f"Found **{len(results)}** {direction_desc}\n\n"

            # Format results
            for i, article in enumerate(results, 1):
                title = article.get("title", "No title")
                authors = article.get("authors", [])
                year = article.get("year", article.get("pub_year", ""))
                journal = article.get("journal", "")
                ref_pmid = article.get("pmid", "")
                doi = article.get("doi", "")

                # Author string
                if authors:
                    author_str = f"{authors[0]} et al." if len(authors) > 2 else ", ".join(authors)
                else:
                    author_str = article.get("author_string", "Unknown")

                output += f"**{i}.** {title}\n"
                output += f"   👤 {author_str} | 📅 {year}"
                if journal:
                    output += f" | 📰 {journal}"
                output += "\n"

                ids = []
                if ref_pmid:
                    ids.append(f"PMID:{ref_pmid}")
                if doi:
                    ids.append(f"DOI:{doi}")
                if ids:
                    output += f"   🔗 {' | '.join(ids)}\n"

                output += "\n"

            return output

        except Exception as e:
            logger.exception(f"Get Europe PMC citations failed: {e}")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check the ID and direction parameter",
                tool_name="get_europe_pmc_citations",
            )
