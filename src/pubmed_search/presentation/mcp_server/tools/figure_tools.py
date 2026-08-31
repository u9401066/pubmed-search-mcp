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
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field

from pubmed_search.domain.value_objects.article_identifiers import (
    IdentifierValidationError,
    normalize_pmcid,
)
from pubmed_search.shared.markdown import escape_markdown_code, escape_markdown_text, safe_markdown_url

from ._common import ResponseFormatter
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
from .article_source import PubmedSource, normalize_article_source

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from pubmed_search.domain.entities.figure import ArticleFiguresResult

logger = logging.getLogger(__name__)

StrictBool = Annotated[bool, Field(strict=True)]


def register_figure_tools(mcp: MCPServer):
    """Register figure extraction MCP tools."""

    @mcp.tool()
    async def get_article_figures(
        source: PubmedSource,
        include_subfigures: StrictBool = False,
        include_tables: StrictBool = False,
        output_format: Literal["markdown", "json", "toon"] = "markdown",
    ) -> str:
        """Get structured figure metadata (label, caption, image URL) and PDF links from a PMC Open Access article.

        Returns all figures with their captions and direct image URLs, plus
        PDF download links for the complete article.

        ``source`` is a discriminated identifier object, so the schema itself
        requires exactly one explicit PMID or PMCID.

        Args:
            source: {"kind":"pmcid","value":"PMC12086443"} or
                    {"kind":"pmid","value":"40384072"}.
            include_subfigures: Parse sub-figures (e.g., Figure 3A, 3B) as separate entries.
            include_tables: Also extract tables rendered as images.

        Returns:
            Structured figure data with image URLs, captions, and PDF links.

        Example:
            get_article_figures(source={"kind":"pmcid","value":"PMC12086443"})
        """
        normalized_output_format = normalize_output_format(output_format)
        try:
            normalized_source = normalize_article_source(source)
            detected_pmcid = normalized_source.value if normalized_source.kind == "pmcid" else None
            detected_pmid = normalized_source.value if normalized_source.kind == "pmid" else None
        except IdentifierValidationError as exc:
            return ResponseFormatter.error(
                error=exc,
                suggestion="Provide exactly one strict PMID or PMC-prefixed PMCID.",
                example='get_article_figures(source={"kind":"pmcid","value":"PMC12086443"})',
                tool_name="get_article_figures",
                output_format=normalized_output_format,
            )

        # If only PMID, try to resolve to PMCID
        if not detected_pmcid and detected_pmid:
            try:
                detected_pmcid = await _resolve_pmid_to_pmcid(detected_pmid)
            except Exception as exc:
                logger.warning("PMID to PMCID resolution failed (%s)", type(exc).__name__)
                return ResponseFormatter.error(
                    error="PMC identifier resolution source unavailable.",
                    suggestion="Retry later or provide a known PMC-prefixed PMCID.",
                    tool_name="get_article_figures",
                    output_format=normalized_output_format,
                )
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

        logger.info("Extracting figures for one normalized article identifier")

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
                    error="Figure extraction sources were unavailable.",
                    suggestion="Figure extraction sources were unavailable; retry later.",
                    tool_name="get_article_figures",
                    output_format=normalized_output_format,
                )

            if is_structured_output_format(normalized_output_format):
                return _format_figures_structured(
                    result,
                    requested_source={"kind": normalized_source.kind, "value": normalized_source.value},
                    pmcid=str(detected_pmcid) if detected_pmcid else None,
                    pmid=str(detected_pmid) if detected_pmid else None,
                    include_subfigures=include_subfigures,
                    include_tables=include_tables,
                    output_format=normalized_output_format,
                )

            return _format_figures_output(result)

        except Exception as e:
            logger.warning("Figure extraction failed (%s)", type(e).__name__)
            return ResponseFormatter.error(
                error="Figure extraction source unavailable.",
                suggestion="Retry later after confirming that the article is Open Access in PMC.",
                tool_name="get_article_figures",
                output_format=normalized_output_format,
            )


async def _resolve_pmid_to_pmcid(pmid: str) -> str | None:
    """Resolve PMID to PMCID using NCBI ID converter."""
    from pubmed_search.infrastructure.sources import get_europe_pmc_client

    client = get_europe_pmc_client()
    result = await client.search(
        query=f"EXT_ID:{pmid} AND SRC:MED",
        limit=1,
        result_type="lite",
    )
    articles = result.get("results", [])
    if articles and articles[0].get("pmc_id"):
        try:
            return normalize_pmcid(str(articles[0]["pmc_id"]))
        except IdentifierValidationError as exc:
            raise RuntimeError("Europe PMC returned a malformed PMCID") from exc
    return None


def _format_figures_structured(
    result: ArticleFiguresResult,
    *,
    requested_source: dict[str, str],
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
                    f'get_fulltext(source={{"kind":"pmid","value":"{pmid}"}}, '
                    f"include_figures=True, extended_sources=True, "
                    f'output_format="{structured_output_format}")'
                ),
            )
        )
    if pmcid:
        next_tool_candidates.append(
            make_next_tool(
                "get_text_mined_terms",
                "Pair figure evidence with Europe PMC text-mined entities from the same PMC article.",
                (
                    f'get_text_mined_terms(source={{"kind":"pmcid","value":"{pmcid}"}}, '
                    f'output_format="{structured_output_format}")'
                ),
            )
        )

    next_tools, next_commands = finalize_next_tools(next_tool_candidates)
    visible_fields = sorted(
        {key for figure in figures for key, value in figure.items() if value not in (None, "", [], {}, ())}
    )
    payload: dict[str, Any] = {
        "tool": "get_article_figures",
        "identifiers": {"requested": requested_source, "pmcid": pmcid, "pmid": pmid},
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
    output = f"🖼️ **Article Figures: {escape_markdown_text(result.article_title or result.pmcid)}**\n"
    output += f"📑 PMC ID: {escape_markdown_text(result.pmcid)}"
    if result.pmid:
        output += f" | PMID: {escape_markdown_text(result.pmid)}"
    output += f" | Source: {escape_markdown_text(result.source)}\n"
    output += f"📊 Total figures: **{result.total_figures}**\n\n"

    # === PDF Links section ===
    if result.pdf_links:
        output += "## 📥 PDF / Article Links\n\n"
        for link in result.pdf_links:
            icon = "📄" if link.get("type") == "pdf" else "🔗"
            safe_url = safe_markdown_url(link.get("url"))
            source = escape_markdown_text(link.get("source", "Unknown"))
            if safe_url:
                output += f"- {icon} **{source}**: {safe_url}\n"
            else:
                output += f"- {icon} **{source}**: unsafe URL omitted\n"
        output += "\n"

    # === Figures section ===
    if result.figures:
        output += "## 🖼️ Figures\n\n"
        for fig in result.figures:
            output += f"### {escape_markdown_text(fig.label or fig.figure_id)}\n"
            if fig.caption_title:
                output += f"**{escape_markdown_text(fig.caption_title)}**\n\n"
            if fig.caption_text:
                output += f"{escape_markdown_text(fig.caption_text)}\n\n"
            if fig.image_url:
                safe_url = safe_markdown_url(fig.image_url)
                output += f"🔗 **Image URL**: {safe_url or 'unsafe URL omitted'}\n"
            if fig.graphic_href:
                output += f"📎 Graphic ref: `{escape_markdown_code(fig.graphic_href)}`\n"
            if fig.mentioned_in_sections:
                sections = ", ".join(escape_markdown_text(section) for section in fig.mentioned_in_sections)
                output += f"📍 Referenced in: {sections}\n"

            # Subfigures
            if fig.subfigures:
                output += "\n**Sub-figures:**\n"
                for sf in fig.subfigures:
                    excerpt = sf.caption_text[:100]
                    output += (
                        f"  - **{escape_markdown_text(sf.label)}**: {escape_markdown_text(excerpt)}"
                        f"{'...' if len(sf.caption_text) > 100 else ''}"
                    )
                    if sf.image_url:
                        safe_url = safe_markdown_url(sf.image_url)
                        output += f"\n    🔗 {safe_url or 'unsafe URL omitted'}"
                    output += "\n"

            output += "\n"
    elif result.total_figures == 0 and not result.error:
        output += "_No figures found in this article._\n\n"

    # Tip
    if result.figures:
        output += "---\n"
        output += "💡 **Tips**:\n"
        output += "- Image URLs can be opened directly in a browser\n"
        output += '- Use `get_fulltext(source={"kind":"pmcid","value":"PMC..."}, include_figures=True)` '
        output += "to get figures inline with text\n"
        if result.pdf_links:
            output += "- PDF links contain the complete article with all formatting\n"

    return output
