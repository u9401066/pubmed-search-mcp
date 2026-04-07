"""
Figure Tools - Extract figures and visual data from PMC articles.

Tools:
- get_article_figures: Extract figure metadata (label, caption, image URL, PDF links)
  from PMC Open Access articles.

Architecture:
  MCP Tool → FigureClient (infrastructure) → Europe PMC / PMC efetch / BioC
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal, Union

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
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from pubmed_search.domain.entities.figure import ArticleFiguresResult

logger = logging.getLogger(__name__)


def register_figure_tools(mcp: FastMCP):
    """Register figure extraction MCP tools."""

    @mcp.tool()
    async def get_article_figures(
        identifier: str | None = None,
        pmcid: Union[str, int] | None = None,
        pmid: Union[str, int] | None = None,
        include_subfigures: bool = False,
        include_tables: bool = False,
        output_format: Literal["markdown", "json", "toon"] = "markdown",
    ) -> str:
        """Get structured figure metadata (label, caption, image URL) and PDF links from a PMC Open Access article.

        Returns all figures with their captions and direct image URLs, plus
        PDF download links for the complete article.

        Accepts flexible input - provide ANY ONE of:
        - identifier: Auto-detects PMID or PMC ID
        - pmcid: Direct PMC ID
        - pmid: PubMed ID (requires PMC ID lookup)

        Args:
            identifier: Auto-detect format - PMID or PMC ID.
                       Examples: "PMC12086443", "40384072"
            pmcid: PubMed Central ID (e.g., "PMC12086443" or "12086443").
            pmid: PubMed ID (e.g., "40384072"). The article must be in PMC.
            include_subfigures: Parse sub-figures (e.g., Figure 3A, 3B) as separate entries.
            include_tables: Also extract tables rendered as images.

        Returns:
            Structured figure data with image URLs, captions, and PDF links.

        Example:
            get_article_figures(identifier="PMC12086443")
            get_article_figures(pmid="40384072")
        """
        # Smart identifier detection
        normalized_output_format = normalize_output_format(output_format)
        detected_pmcid = pmcid
        detected_pmid = pmid

        if identifier:
            identifier = str(identifier).strip()
            if identifier.upper().startswith("PMC"):
                detected_pmcid = identifier
            elif identifier.isdigit() and len(identifier) > 8:
                detected_pmcid = f"PMC{identifier}"
            elif identifier.isdigit():
                detected_pmid = identifier
            else:
                detected_pmid = identifier

        # Normalize inputs
        if detected_pmcid:
            detected_pmcid = InputNormalizer.normalize_pmcid(str(detected_pmcid))
        if detected_pmid:
            detected_pmid = InputNormalizer.normalize_pmid_single(detected_pmid)

        # Need at least PMCID to proceed
        if not detected_pmcid and not detected_pmid:
            return ResponseFormatter.error(
                error="No valid identifier provided",
                suggestion="Provide a PMC ID or PubMed ID",
                example='get_article_figures(pmcid="PMC12086443")',
                tool_name="get_article_figures",
                output_format=normalized_output_format,
            )

        # If only PMID, try to resolve to PMCID
        if not detected_pmcid and detected_pmid:
            detected_pmcid = await _resolve_pmid_to_pmcid(detected_pmid)
            if not detected_pmcid:
                return ResponseFormatter.error(
                    error="Article not available in PMC",
                    suggestion=(
                        f"PMID {detected_pmid} does not have a corresponding PMC ID. "
                        "Only PMC Open Access articles have extractable figures. "
                        "Try get_fulltext() with extended_sources=True for PDF links."
                    ),
                    tool_name="get_article_figures",
                    output_format=normalized_output_format,
                )

        logger.info("Extracting figures: pmcid=%s, pmid=%s", detected_pmcid, detected_pmid)

        try:
            from pubmed_search.infrastructure.sources.figure_client import (
                get_figure_client,
            )

            client = get_figure_client()
            result = await client.get_article_figures(
                pmcid=str(detected_pmcid),
                pmid=str(detected_pmid) if detected_pmid else None,
                include_subfigures=include_subfigures,
                include_tables=include_tables,
            )

            if result.error:
                return ResponseFormatter.error(
                    error=result.error,
                    suggestion=(result.error_detail or "Try a different article or check if it's in PMC"),
                    tool_name="get_article_figures",
                    output_format=normalized_output_format,
                )

            if is_structured_output_format(normalized_output_format):
                return _format_figures_structured(
                    result,
                    identifier=identifier,
                    pmcid=str(detected_pmcid) if detected_pmcid else None,
                    pmid=str(detected_pmid) if detected_pmid else None,
                    include_subfigures=include_subfigures,
                    include_tables=include_tables,
                    output_format=normalized_output_format,
                )

            return _format_figures_output(result)

        except Exception as e:
            logger.exception("Figure extraction failed: %s", e)
            return ResponseFormatter.error(
                error=e,
                suggestion="Check if the article is Open Access in PMC",
                tool_name="get_article_figures",
                output_format=normalized_output_format,
            )


async def _resolve_pmid_to_pmcid(pmid: str) -> str | None:
    """Resolve PMID to PMCID using NCBI ID converter."""
    try:
        from pubmed_search.infrastructure.sources import get_europe_pmc_client

        client = get_europe_pmc_client()
        result = await client.search(
            query=f"EXT_ID:{pmid} AND SRC:MED",
            limit=1,
            result_type="lite",
        )
        articles = result.get("results", [])
        if articles and articles[0].get("pmc_id"):
            return articles[0]["pmc_id"]
    except Exception as e:
        logger.warning("PMID→PMCID resolution failed for %s: %s", pmid, e)
    return None


def _format_figures_structured(
    result: ArticleFiguresResult,
    *,
    identifier: str | None,
    pmcid: str | None,
    pmid: str | None,
    include_subfigures: bool,
    include_tables: bool,
    output_format: OutputFormat = "json",
) -> str:
    """Format figure extraction output as a structured agent-facing payload."""
    structured_output_format = preferred_structured_output_format(output_format)
    figures = [figure.to_dict() for figure in result.figures]
    next_tool_candidates: list[dict[str, str]] = []

    if pmid:
        next_tool_candidates.append(
            make_next_tool(
                "fetch_article_details",
                "Hydrate the article metadata before export or citation exploration.",
                f'fetch_article_details(pmids="{pmid}", output_format="{structured_output_format}")',
            )
        )
        next_tool_candidates.append(
            make_next_tool(
                "get_fulltext",
                "Pull the article text with figures enabled so captions and narrative stay aligned.",
                (
                    f'get_fulltext(pmid="{pmid}", include_figures=True, extended_sources=True, '
                    f'output_format="{structured_output_format}")'
                ),
            )
        )
    if pmcid:
        next_tool_candidates.append(
            make_next_tool(
                "get_text_mined_terms",
                "Pair figure evidence with Europe PMC text-mined entities from the same PMC article.",
                f'get_text_mined_terms(pmcid="{pmcid}", output_format="{structured_output_format}")',
            )
        )

    next_tools, next_commands = finalize_next_tools(next_tool_candidates)
    visible_fields = sorted(
        {key for figure in figures for key, value in figure.items() if value not in (None, "", [], {}, ())}
    )
    payload: dict[str, Any] = {
        "tool": "get_article_figures",
        "identifiers": {"identifier": identifier, "pmcid": pmcid, "pmid": pmid},
        "title": result.article_title or None,
        "figure_count": len(figures),
        "total_figures": result.total_figures,
        "include_subfigures": include_subfigures,
        "include_tables": include_tables,
        "figures": figures,
        "pdf_links": result.pdf_links,
        "source_counts": [
            make_source_count_row(
                "pmc-figure-client",
                len(figures),
                result.total_figures or len(figures),
            )
        ],
        "next_tools": next_tools,
        "next_commands": next_commands,
        "section_provenance": {
            "figures": make_section_provenance(
                surfacing_source="PMC Open Access / FigureClient",
                canonical_host="PubMed Central",
                provenance="mixed",
                note="Figure metadata is collected through the PMC-focused figure client and may combine multiple PMC-backed extraction paths.",
                fields=visible_fields,
            ),
            "pdf_links": make_section_provenance(
                surfacing_source="PubMed Central",
                canonical_host="PubMed Central",
                provenance="indirect",
                note="PDF links point back to the PMC article landing or PDF assets associated with the extracted figures.",
            ),
            "source_counts": make_section_provenance(
                surfacing_source="pubmed-search-mcp",
                canonical_host=None,
                provenance="derived",
                note="Counts summarize how many figure rows were retained after extraction formatting.",
                upstream_sources=["pmc-figure-client"],
            ),
            "next_tools": make_section_provenance(
                surfacing_source="pubmed-search-mcp",
                canonical_host="pubmed-search-mcp",
                provenance="derived",
                note="Next-tool suggestions are inferred locally from the resolved PMC and PubMed identifiers.",
            ),
        },
    }
    return serialize_structured_payload(payload, output_format)


def _format_figures_output(result: ArticleFiguresResult) -> str:
    """Format ArticleFiguresResult as markdown for MCP response."""
    output = f"🖼️ **Article Figures: {result.article_title or result.pmcid}**\n"
    output += f"📑 PMC ID: {result.pmcid}"
    if result.pmid:
        output += f" | PMID: {result.pmid}"
    output += f" | Source: {result.source}\n"
    output += f"📊 Total figures: **{result.total_figures}**\n\n"

    # === PDF Links section ===
    if result.pdf_links:
        output += "## 📥 PDF / Article Links\n\n"
        for link in result.pdf_links:
            icon = "📄" if link.get("type") == "pdf" else "🔗"
            output += f"- {icon} **{link.get('source', 'Unknown')}**: {link.get('url', '')}\n"
        output += "\n"

    # === Figures section ===
    if result.figures:
        output += "## 🖼️ Figures\n\n"
        for fig in result.figures:
            output += f"### {fig.label or fig.figure_id}\n"
            if fig.caption_title:
                output += f"**{fig.caption_title}**\n\n"
            if fig.caption_text:
                output += f"{fig.caption_text}\n\n"
            if fig.image_url:
                output += f"🔗 **Image URL**: {fig.image_url}\n"
            if fig.graphic_href:
                output += f"📎 Graphic ref: `{fig.graphic_href}`\n"
            if fig.mentioned_in_sections:
                output += f"📍 Referenced in: {', '.join(fig.mentioned_in_sections)}\n"

            # Subfigures
            if fig.subfigures:
                output += "\n**Sub-figures:**\n"
                for sf in fig.subfigures:
                    output += (
                        f"  - **{sf.label}**: {sf.caption_text[:100]}{'...' if len(sf.caption_text) > 100 else ''}"
                    )
                    if sf.image_url:
                        output += f"\n    🔗 {sf.image_url}"
                    output += "\n"

            output += "\n"
    elif result.total_figures == 0 and not result.error:
        output += "_No figures found in this article._\n\n"

    # Tip
    if result.figures:
        output += "---\n"
        output += "💡 **Tips**:\n"
        output += "- Image URLs can be opened directly in a browser\n"
        output += "- Use `get_fulltext(include_figures=True)` to get figures inline with text\n"
        if result.pdf_links:
            output += "- PDF links contain the complete article with all formatting\n"

    return output
