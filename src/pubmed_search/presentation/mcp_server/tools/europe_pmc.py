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
from typing import TYPE_CHECKING, Annotated, Any, Literal

from mcp.server.mcpserver import Context  # noqa: TC002 - MCPServer needs runtime access for tool context injection
from pydantic import Field

from pubmed_search.application.fulltext import FulltextRequest, FulltextService
from pubmed_search.domain.value_objects.article_identifiers import IdentifierValidationError
from pubmed_search.infrastructure.sources import get_core_client, get_europe_pmc_client, get_unpaywall_client
from pubmed_search.shared.markdown import escape_markdown_block, escape_markdown_text, markdown_link
from pubmed_search.shared.settings import load_settings

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
    sort_source_count_rows,
)
from .article_source import ArticleSource, PubmedSource, normalize_article_source
from .artifact_memory import artifact_markdown_note, artifact_persistence_enabled, persist_tool_artifact
from .tool_runtime import safe_log, safe_report_progress

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

logger = logging.getLogger(__name__)

SectionFilter = Annotated[str, Field(strict=True, min_length=1, max_length=500)]
StrictBool = Annotated[bool, Field(strict=True)]
SemanticType = Literal["GENE_PROTEIN", "DISEASE", "CHEMICAL", "ORGANISM", "GO_TERM", "EFO"]
_SEMANTIC_TYPES: frozenset[str] = frozenset({"GENE_PROTEIN", "DISEASE", "CHEMICAL", "ORGANISM", "GO_TERM", "EFO"})


def _validate_semantic_type(semantic_type: str | None) -> None:
    if semantic_type is not None and semantic_type not in _SEMANTIC_TYPES:
        raise IdentifierValidationError("semantic_type is not a supported Europe PMC entity type")


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
                f'get_text_mined_terms(source={{"kind":"pmid","value":"{pmid}"}})',
            )
        )

    if pmcid and not include_figures:
        suggestions.append(
            make_next_tool(
                "get_article_figures",
                "A PMCID is available, so you can pivot into structured figure extraction next.",
                f'get_article_figures(source={{"kind":"pmcid","value":"{pmcid}"}})',
            )
        )
    elif pmcid:
        suggestions.append(
            make_next_tool(
                "get_text_mined_terms",
                "You already have PMC-backed access; annotate the same article for entities and concepts.",
                f'get_text_mined_terms(source={{"kind":"pmcid","value":"{pmcid}"}})',
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
        artifact_counts["pmc_figures"] = (
            artifact_counts.get(
                "pmc_figures",
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
    requested_source: dict[str, str],
    pmcid: str | None,
    pmid: str | None,
    doi: str | None,
    title: str | None,
    fulltext_content: str | None,
    content_sections: list[dict[str, Any]],
    pdf_links: list[dict[str, Any]],
    sources_tried: list[str],
    sources_completed: list[str],
    source_errors: list[dict[str, str]],
    coverage_status: Literal["complete", "partial", "unavailable"],
    source_counts: list[dict[str, Any]],
    next_tools: list[dict[str, str]],
    next_commands: list[str],
    fulltext_source: str | None,
    fulltext_canonical_host: str | None,
    fulltext_provenance: Literal["direct", "indirect", "derived", "mixed"] | None,
    include_figures: bool,
    figures: list[dict[str, Any]],
    output_format: OutputFormat = "json",
    artifact_manifest: dict[str, Any] | None = None,
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
        "coverage": make_section_provenance(
            surfacing_source="pubmed-search-mcp",
            canonical_host=None,
            provenance="derived",
            note="Coverage distinguishes completed upstream checks from sanitized source failures.",
            upstream_sources=sources_tried,
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
            surfacing_source="pmc_figures",
            canonical_host="PubMed Central",
            provenance="mixed",
            note="Figure metadata is extracted through the PMC-focused figure client and remains article-license scoped.",
        )

    payload = {
        "tool": "get_fulltext",
        "identifiers": {
            "requested": requested_source,
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
        "sources_completed": sources_completed,
        "source_errors": source_errors,
        "coverage_status": coverage_status,
        "source_counts": source_counts,
        "next_tools": next_tools,
        "next_commands": next_commands,
        "include_figures": include_figures,
        "figures": figures,
        "section_provenance": section_provenance,
    }
    if artifact_manifest:
        payload["artifact"] = artifact_manifest
    return serialize_structured_payload(payload, output_format)


def _artifact_read_hint(artifact: dict[str, Any] | None) -> str:
    if not artifact:
        return 'read_session(request={"action":"artifact","locator":{"kind":"artifact_id","value":"artifact-123"}})'
    return str(
        artifact.get("read_via")
        or (
            'read_session(request={"action":"artifact","locator":'
            f'{{"kind":"artifact_id","value":"{artifact.get("artifact_id", "")}"}}}})'
        )
    )


def _truncate_inline_fulltext(text: str, max_chars: int, artifact: dict[str, Any] | None) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    artifact_id = str((artifact or {}).get("artifact_id") or "")
    if artifact_id:
        recovery = f"Artifact: `{artifact_id}`. Use `{_artifact_read_hint(artifact)}` for the saved full content."
    else:
        recovery = "The full response was not persisted; request narrower sections to retrieve omitted text."
    return text[:max_chars] + f"\n\n_... {omitted} characters omitted from inline response. {recovery}_"


def _format_source_coverage_markdown(
    *,
    coverage_status: Literal["complete", "partial", "unavailable"],
    sources_completed: list[str],
    source_errors: list[dict[str, str]],
) -> str:
    """Render sanitized upstream coverage without exposing exception details."""
    if coverage_status == "complete":
        return ""
    lines = [f"## ⚠️ Source coverage: {escape_markdown_text(coverage_status)}"]
    if sources_completed:
        completed = ", ".join(escape_markdown_text(source) for source in sources_completed)
        lines.append(f"Completed checks: {completed}")
    if source_errors:
        lines.append("Unavailable checks:")
        lines.extend(
            f"- {escape_markdown_text(issue.get('source', 'unknown'))}: "
            f"{escape_markdown_text(issue.get('message', 'source unavailable'))}"
            for issue in source_errors
        )
    lines.append("_Absence of fulltext cannot be concluded from unavailable sources._")
    return "\n\n".join(lines) + "\n\n"


def _render_fulltext_content_for_artifact(
    content_sections: list[dict[str, Any]],
    fallback: str | None,
) -> str | None:
    """Render full section text for saved artifacts without inline preview truncation."""
    rendered_sections: list[str] = []
    for section in content_sections:
        content = str(section.get("content") or "")
        if not content:
            continue
        title = escape_markdown_text(section.get("title") or "Untitled Section")
        rendered_sections.append(f"### {title}\n\n{escape_markdown_block(content)}")
    if rendered_sections:
        return "\n\n".join(rendered_sections)
    return escape_markdown_block(fallback) if fallback else fallback


def _limit_fulltext_payload_for_response(
    payload_kwargs: dict[str, Any],
    *,
    artifact: dict[str, Any] | None,
    max_chars: int,
) -> dict[str, Any]:
    if max_chars <= 0:
        return payload_kwargs

    content = str(payload_kwargs.get("fulltext_content") or "")
    section_chars = sum(len(str(section.get("content", ""))) for section in payload_kwargs.get("content_sections", []))
    if len(content) + section_chars <= max_chars:
        return payload_kwargs

    preview_source = content
    if not preview_source:
        preview_source = "\n\n".join(
            str(section.get("content", "")) for section in payload_kwargs.get("content_sections", [])
        )
    preview = _truncate_inline_fulltext(preview_source, max_chars, artifact)
    limited = dict(payload_kwargs)
    limited["fulltext_content"] = preview
    limited["content_sections"] = [{"title": "Inline Preview", "content": preview}] if preview else []
    return limited


def _limit_fulltext_markdown_for_response(
    output: str,
    *,
    artifact: dict[str, Any] | None,
    max_chars: int,
) -> str:
    if max_chars <= 0 or len(output) <= max_chars:
        return output
    return _truncate_inline_fulltext(output, max_chars, artifact) + "\n"


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
                (
                    f'get_fulltext(source={{"kind":"pmid","value":"{pmid}"}}, '
                    f'extended_sources=True, output_format="{structured_output_format}")'
                ),
            )
        )
    if pmcid:
        next_tool_candidates.append(
            make_next_tool(
                "get_article_figures",
                "PMC-backed annotations can be paired with figure evidence from the same open-access article.",
                (
                    f'get_article_figures(source={{"kind":"pmcid","value":"{pmcid}"}}, '
                    f'output_format="{structured_output_format}")'
                ),
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


def register_europe_pmc_tools(mcp: MCPServer):
    """
    Register Europe PMC tools for fulltext access and text mining.

    Note: search_europe_pmc is NOT registered - use unified_search instead.
    Only registers:
    - get_fulltext: Get parsed fulltext content
    - get_text_mined_terms: Get text-mined annotations
    """

    @mcp.tool()
    async def get_fulltext(
        source: ArticleSource,
        sections: SectionFilter | None = None,
        include_pdf_links: StrictBool = True,
        include_figures: StrictBool = False,
        extended_sources: StrictBool = False,
        output_format: Literal["markdown", "json", "toon"] = "markdown",
        allow_browser_session: StrictBool | None = None,
        ctx: Context | None = None,
    ) -> str:
        """
        🔥 Enhanced multi-source fulltext retrieval.

        Automatically tries multiple sources to find the best fulltext:
        1. Europe PMC (if PMC ID available)
        2. Unpaywall (finds OA versions via DOI)
        3. Institutional direct/EZproxy fetch (when DOI-backed and enabled)
        4. CORE (200M+ open access papers)

        With extended_sources=True, also searches:
        5. CrossRef (publisher links)
        6. DOAJ (Gold OA journals)
        7. Zenodo (research repository)
        8. PubMed LinkOut (external providers)
        9. Semantic Scholar, OpenAlex, arXiv, bioRxiv, medRxiv

        ``source`` is a discriminated identifier object, so the schema itself
        requires exactly one explicit PMID, PMCID, or DOI kind.

        Args:
            source: One object such as {"kind":"pmid","value":"12345678"},
                    {"kind":"pmcid","value":"PMC7096777"}, or
                    {"kind":"doi","value":"10.1001/jama.2024.1234"}.
            sections: Filter sections (e.g., "introduction,methods,results")
            include_pdf_links: Include PDF download links (default: True)
            include_figures: Include figure metadata with image URLs (default: False)
            extended_sources: Search the extended downloader chain after the standard policy (default: False)
            output_format: Response format - "markdown" (default), "json", or "toon"
            allow_browser_session: Control browser-session fallback.
                - True: force broker fallback when configured
                - False: disable broker fallback
                - None: use auto mode from broker configuration

        Returns:
            Fulltext content with PDF links from all available sources.

        Example:
            get_fulltext(source={"kind":"pmcid","value":"PMC7096777"})
            get_fulltext(source={"kind":"doi","value":"10.1038/s41586-021-03819-2"})
        """

        async def _progress(progress: float, total: float, message: str) -> None:
            await safe_report_progress(ctx, progress, total, message)

        async def _log(level: Literal["debug", "info", "warning", "error"], message: str) -> None:
            await safe_log(ctx, level, message, logger_name=__name__)

        await _progress(1, 6, "Resolving article identifiers...")
        normalized_output_format = normalize_output_format(output_format)
        settings = load_settings()

        normalized_source = normalize_article_source(source)
        requested_source = {"kind": normalized_source.kind, "value": normalized_source.value}
        if normalized_source.kind == "pmid":
            request = FulltextRequest(
                pmid=normalized_source.value,
                sections=sections,
                include_figures=include_figures,
                extended_sources=extended_sources,
                allow_browser_session=allow_browser_session,
            )
        elif normalized_source.kind == "pmcid":
            request = FulltextRequest(
                pmcid=normalized_source.value,
                sections=sections,
                include_figures=include_figures,
                extended_sources=extended_sources,
                allow_browser_session=allow_browser_session,
            )
        else:
            request = FulltextRequest(
                doi=normalized_source.value,
                sections=sections,
                include_figures=include_figures,
                extended_sources=extended_sources,
                allow_browser_session=allow_browser_session,
            )

        browser_session_note = None

        from pubmed_search.infrastructure.sources.figure_client import get_figure_client
        from pubmed_search.infrastructure.sources.fulltext_download import FulltextDownloader
        from pubmed_search.infrastructure.sources.institutional_fulltext import (
            InstitutionalFulltextClient,
        )

        _institutional_factory = InstitutionalFulltextClient if settings.institutional_direct_fetch else None

        service = FulltextService(
            europe_pmc_client_factory=get_europe_pmc_client,
            unpaywall_client_factory=get_unpaywall_client,
            core_client_factory=get_core_client,
            downloader_factory=FulltextDownloader,
            figure_client_factory=get_figure_client if include_figures else None,
            institutional_client_factory=_institutional_factory,
        )
        try:
            retrieval = await service.retrieve(request, progress=_progress, log=_log)
        except IdentifierValidationError as exc:
            return ResponseFormatter.error(
                error=exc,
                suggestion="Provide exactly one strict PMID, PMC-prefixed PMCID, or DOI.",
                example='get_fulltext(source={"kind":"pmcid","value":"PMC7096777"})',
                tool_name="get_fulltext",
                output_format=normalized_output_format,
            )
        except Exception as exc:
            logger.warning("Fulltext orchestration failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                error="Fulltext retrieval could not be completed because an upstream service was unavailable.",
                suggestion="Retry later or use unified_search to confirm the article identifiers.",
                tool_name="get_fulltext",
                output_format=normalized_output_format,
            )

        resolved_pmcid = retrieval.pmcid
        resolved_pmid = retrieval.pmid
        resolved_doi = retrieval.doi
        await _log(
            "info",
            (
                "get_fulltext identifiers resolved "
                f"pmcid={'yes' if resolved_pmcid else 'no'} "
                f"pmid={'yes' if resolved_pmid else 'no'} "
                f"doi={'yes' if resolved_doi else 'no'}"
            ),
        )

        # Keep the main service as the primary path, then fall back to
        # multi-source PDF retrieval only when the service has not already
        # attempted the extended downloader path.
        if (
            not retrieval.fulltext_content
            and any([resolved_pmid, resolved_pmcid, resolved_doi])
            and not retrieval.extended_sources_attempted
        ):
            await _progress(5.5, 6, "Trying multi-source PDF retrieval fallback...")
            retrieval.record_source_attempted("pdf_retrieval_fallback")
            try:
                from pubmed_search.infrastructure.sources.fulltext_download import (
                    FulltextDownloader,
                    PDFSource,
                )

                downloader = FulltextDownloader()
                try:
                    assisted = await downloader.get_fulltext(
                        pmid=resolved_pmid,
                        pmcid=resolved_pmcid,
                        doi=resolved_doi,
                        strategy="extract_text",
                        allow_browser_session=allow_browser_session,
                    )
                finally:
                    await downloader.close()

                link_discovery = assisted.require_link_discovery()
                for attempted_source in link_discovery.attempted_sources:
                    retrieval.record_source_attempted(attempted_source)
                for completed_source in link_discovery.completed_sources:
                    retrieval.record_source_completed(completed_source)
                for source_error in link_discovery.source_errors:
                    retrieval.record_source_error(source_error.source)

                seen_urls = {str(link.get("url") or "") for link in retrieval.pdf_links}
                for ext_link in link_discovery.links:
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
                    retrieval.raw_fulltext_content = assisted.text_content
                    extracted_text = FulltextService.truncate_extracted_text(assisted.text_content)
                    retrieval.fulltext_content = extracted_text
                    retrieval.content_sections = [
                        {
                            "title": "Extracted PDF Text",
                            "content": extracted_text,
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
                            "🔐 Browser-session broker fetched PDF and extracted text from "
                            f"{escape_markdown_text(assisted.retrieved_url or 'institutional access')}"
                        )
                    else:
                        note_parts.append(
                            "🔐 Browser-session broker fetched PDF from "
                            f"{escape_markdown_text(assisted.retrieved_url or 'institutional access')}"
                        )
                elif assisted.source_used:
                    if assisted.text_content:
                        note_parts.append(
                            "📄 PDF retrieval fallback extracted text via "
                            f"{escape_markdown_text(assisted.source_used.display_name)}"
                        )
                    else:
                        note_parts.append(
                            "📄 PDF retrieval fallback retrieved PDF via "
                            f"{escape_markdown_text(assisted.source_used.display_name)}"
                        )
                if assisted.error:
                    note_parts.append("⚠️ PDF retrieval fallback completed without usable fulltext.")

                if note_parts:
                    browser_session_note = "\n".join(note_parts)
                if link_discovery.coverage_status != "unavailable" or assisted.text_content:
                    retrieval.record_source_completed("pdf_retrieval_fallback")
            except Exception as e:
                logger.warning("PDF retrieval fallback failed (%s)", type(e).__name__)
                retrieval.record_source_error("pdf_retrieval_fallback")
                await _log("warning", "PDF retrieval fallback source unavailable")

        next_tools, next_commands = _build_fulltext_next_tools(
            pmcid=resolved_pmcid,
            pmid=resolved_pmid,
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
        fulltext_payload_kwargs: dict[str, Any] = {
            "requested_source": requested_source,
            "pmcid": resolved_pmcid,
            "pmid": resolved_pmid,
            "doi": resolved_doi,
            "title": retrieval.title,
            "fulltext_content": retrieval.fulltext_content,
            "content_sections": retrieval.content_sections,
            "pdf_links": exposed_pdf_links,
            "sources_tried": retrieval.sources_tried,
            "sources_completed": retrieval.sources_completed,
            "source_errors": [issue.to_dict() for issue in retrieval.source_errors],
            "coverage_status": retrieval.coverage_status,
            "source_counts": source_counts,
            "next_tools": next_tools,
            "next_commands": next_commands,
            "fulltext_source": retrieval.fulltext_source_name,
            "fulltext_canonical_host": retrieval.fulltext_canonical_host,
            "fulltext_provenance": retrieval.fulltext_provenance,
            "include_figures": include_figures,
            "figures": retrieval.figures,
        }
        raw_fulltext_content = getattr(retrieval, "raw_fulltext_content", None)
        artifact_sections = retrieval.content_sections
        if raw_fulltext_content and raw_fulltext_content != retrieval.fulltext_content:
            artifact_sections = [{"title": "Full Text", "content": raw_fulltext_content}]
        artifact_fulltext_content = _render_fulltext_content_for_artifact(
            artifact_sections,
            raw_fulltext_content or retrieval.fulltext_content,
        )
        artifact_content_sections = retrieval.content_sections
        if raw_fulltext_content and raw_fulltext_content != retrieval.fulltext_content:
            artifact_content_sections = [{"title": "Full Text", "content": raw_fulltext_content}]
        artifact_payload_kwargs = {
            **fulltext_payload_kwargs,
            "fulltext_content": artifact_fulltext_content,
            "content_sections": artifact_content_sections,
        }
        raw_content_files = (
            {"raw_content.txt": raw_fulltext_content}
            if raw_fulltext_content and raw_fulltext_content != retrieval.fulltext_content
            else {}
        )

        # === BUILD OUTPUT ===
        if is_structured_output_format(normalized_output_format):
            artifact = None
            if artifact_persistence_enabled():
                try:
                    primary_file = f"fulltext.{normalized_output_format}"
                    fulltext_payload = _format_get_fulltext_json(
                        **artifact_payload_kwargs,
                        output_format=normalized_output_format,
                    )
                    artifact = await persist_tool_artifact(
                        tool="get_fulltext",
                        kind="fulltext",
                        files={
                            primary_file: fulltext_payload,
                            "links.json": exposed_pdf_links,
                            "provenance.json": {
                                "identifiers": {
                                    "requested": requested_source,
                                    "pmcid": resolved_pmcid,
                                    "pmid": resolved_pmid,
                                    "doi": resolved_doi,
                                },
                                "sources_tried": retrieval.sources_tried,
                                "sources_completed": retrieval.sources_completed,
                                "source_errors": [issue.to_dict() for issue in retrieval.source_errors],
                                "coverage_status": retrieval.coverage_status,
                                "source_counts": source_counts,
                                "fulltext_source": retrieval.fulltext_source_name,
                                "fulltext_canonical_host": retrieval.fulltext_canonical_host,
                                "fulltext_provenance": retrieval.fulltext_provenance,
                            },
                            **raw_content_files,
                        },
                        primary_file=primary_file,
                        summary={
                            "title": retrieval.title,
                            "pmcid": resolved_pmcid,
                            "pmid": resolved_pmid,
                            "doi": resolved_doi,
                            "fulltext_available": bool(retrieval.fulltext_content),
                            "pdf_links": len(exposed_pdf_links),
                        },
                        metadata={
                            "output_format": normalized_output_format,
                            "include_pdf_links": include_pdf_links,
                            "include_figures": include_figures,
                            "extended_sources": extended_sources,
                            "fulltext_source": retrieval.fulltext_source_name,
                            "fulltext_canonical_host": retrieval.fulltext_canonical_host,
                            "fulltext_provenance": retrieval.fulltext_provenance,
                        },
                    )
                except Exception as exc:
                    logger.warning("Failed to prepare get_fulltext artifact payload (%s)", type(exc).__name__)
            response_payload_kwargs = _limit_fulltext_payload_for_response(
                fulltext_payload_kwargs,
                artifact=artifact,
                max_chars=settings.fulltext_inline_max_chars,
            )
            return _format_get_fulltext_json(
                **response_payload_kwargs,
                output_format=normalized_output_format,
                artifact_manifest=artifact,
            )

        if not retrieval.fulltext_content and not retrieval.pdf_links:
            if retrieval.source_errors:
                no_results_response = "⚠️ **Fulltext retrieval incomplete**\n\n"
                no_results_response += _format_source_coverage_markdown(
                    coverage_status=retrieval.coverage_status,
                    sources_completed=retrieval.sources_completed,
                    source_errors=[issue.to_dict() for issue in retrieval.source_errors],
                )
                no_results_response += "Retry later before treating this article as unavailable."
            else:
                no_results_response = ResponseFormatter.no_results(
                    query=f"pmcid={resolved_pmcid}, pmid={resolved_pmid}, doi={resolved_doi}",
                    suggestions=[
                        "Article may not be open access",
                        "Try searching with DOI for Unpaywall lookup",
                        "Check if article is available in PubMed Central",
                        f"Sources tried: {', '.join(retrieval.sources_tried)}",
                    ],
                    output_format=normalized_output_format,
                    tool_name="get_fulltext",
                )
            artifact = None
            if artifact_persistence_enabled():
                artifact = await persist_tool_artifact(
                    tool="get_fulltext",
                    kind="fulltext",
                    files={
                        "response.md": no_results_response,
                        "provenance.json": {
                            "identifiers": {
                                "requested": requested_source,
                                "pmcid": resolved_pmcid,
                                "pmid": resolved_pmid,
                                "doi": resolved_doi,
                            },
                            "sources_tried": retrieval.sources_tried,
                            "sources_completed": retrieval.sources_completed,
                            "source_errors": [issue.to_dict() for issue in retrieval.source_errors],
                            "coverage_status": retrieval.coverage_status,
                            "source_counts": source_counts,
                        },
                    },
                    primary_file="response.md",
                    summary={
                        "pmcid": resolved_pmcid,
                        "pmid": resolved_pmid,
                        "doi": resolved_doi,
                        "fulltext_available": False,
                        "pdf_links": 0,
                    },
                    metadata={"output_format": normalized_output_format},
                )
            return no_results_response + artifact_markdown_note(artifact)

        # Format output
        await _progress(6, 6, "Formatting fulltext response...")
        output = f"📖 **{escape_markdown_text(retrieval.title or 'Fulltext Retrieved')}**\n"
        checked_sources = ", ".join(escape_markdown_text(source) for source in retrieval.sources_tried)
        output += f"🔍 Sources checked: {checked_sources}\n\n"
        output += _format_source_coverage_markdown(
            coverage_status=retrieval.coverage_status,
            sources_completed=retrieval.sources_completed,
            source_errors=[issue.to_dict() for issue in retrieval.source_errors],
        )

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

                output += f"- {icon} **{markdown_link(link.get('source', 'Open fulltext'), link.get('url'))}** "
                output += f"{access_badge}\n"
                if link.get("version"):
                    output += f"  _Version: {escape_markdown_text(link['version'])}_\n"
                if link.get("license"):
                    output += f"  _License: {escape_markdown_text(link['license'])}_\n"
            output += "\n"

        # Fulltext content
        if retrieval.fulltext_content:
            output += "## 📝 Content\n\n"
            output += (
                _render_fulltext_content_for_artifact(
                    [],
                    retrieval.fulltext_content,
                )
                or ""
            )
        elif retrieval.pdf_links:
            output += "_Structured fulltext not available. Use the PDF links above to access the article._\n"
            if any(link.get("access") == "subscription" for link in retrieval.pdf_links):
                output += "_Institutional links usually require campus IP recognition or library VPN/proxy access._\n"

        if retrieval.figures:
            output += "\n---\n"
            output += f"## 🖼️ Figures ({len(retrieval.figures)})\n\n"
            for fig in retrieval.figures:
                label = escape_markdown_text(fig.get("label") or fig.get("figure_id", "Figure"))
                output += f"#### {label}\n"
                if fig.get("caption_title"):
                    output += f"**{escape_markdown_text(fig['caption_title'])}**\n\n"
                if fig.get("caption_text"):
                    output += f"{escape_markdown_block(fig['caption_text'])}\n\n"
                if fig.get("image_url"):
                    output += f"**Image URL:** {markdown_link('Open image', fig['image_url'])}\n\n"

        artifact = None
        if artifact_persistence_enabled():
            try:
                structured_payload = _format_get_fulltext_json(
                    **artifact_payload_kwargs,
                    output_format="json",
                )
                artifact = await persist_tool_artifact(
                    tool="get_fulltext",
                    kind="fulltext",
                    files={
                        "fulltext.md": output,
                        "payload.json": structured_payload,
                        "links.json": exposed_pdf_links,
                        "provenance.json": {
                            "identifiers": {
                                "requested": requested_source,
                                "pmcid": resolved_pmcid,
                                "pmid": resolved_pmid,
                                "doi": resolved_doi,
                            },
                            "sources_tried": retrieval.sources_tried,
                            "sources_completed": retrieval.sources_completed,
                            "source_errors": [issue.to_dict() for issue in retrieval.source_errors],
                            "coverage_status": retrieval.coverage_status,
                            "source_counts": source_counts,
                            "fulltext_source": retrieval.fulltext_source_name,
                            "fulltext_canonical_host": retrieval.fulltext_canonical_host,
                            "fulltext_provenance": retrieval.fulltext_provenance,
                        },
                        **raw_content_files,
                    },
                    primary_file="payload.json",
                    summary={
                        "title": retrieval.title,
                        "pmcid": resolved_pmcid,
                        "pmid": resolved_pmid,
                        "doi": resolved_doi,
                        "fulltext_available": bool(retrieval.fulltext_content),
                        "pdf_links": len(exposed_pdf_links),
                    },
                    metadata={
                        "output_format": normalized_output_format,
                        "include_pdf_links": include_pdf_links,
                        "include_figures": include_figures,
                        "extended_sources": extended_sources,
                        "fulltext_source": retrieval.fulltext_source_name,
                        "fulltext_canonical_host": retrieval.fulltext_canonical_host,
                        "fulltext_provenance": retrieval.fulltext_provenance,
                    },
                )
            except Exception as exc:
                logger.warning("Failed to prepare get_fulltext artifact payload (%s)", type(exc).__name__)
        response_output = _limit_fulltext_markdown_for_response(
            output,
            artifact=artifact,
            max_chars=settings.fulltext_inline_max_chars,
        )
        return response_output + artifact_markdown_note(artifact)

    @mcp.tool()
    async def get_text_mined_terms(
        source: PubmedSource,
        semantic_type: SemanticType | None = None,
        output_format: Literal["markdown", "json", "toon"] = "markdown",
        ctx: Context | None = None,
    ) -> str:
        """
        Get text-mined annotations from Europe PMC.

        Returns entities extracted from the article text including genes, diseases,
        chemicals, organisms, and more. ``source`` is exactly one PMID or PMCID.

        Args:
            source: {"kind":"pmid","value":"12345678"} or
                    {"kind":"pmcid","value":"PMC7096777"}.
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

        normalized_output_format = normalize_output_format(output_format)

        try:
            await _progress(1, 3, "Resolving article identifier...")
            normalized_source = normalize_article_source(source)
            if normalized_source.kind == "pmid":
                request = FulltextRequest(pmid=normalized_source.value).normalized()
            else:
                request = FulltextRequest(pmcid=normalized_source.value).normalized()
            normalized_pmid = request.pmid
            normalized_pmcid = request.pmcid
            _validate_semantic_type(semantic_type)

            logger.info(
                "Getting text-mined terms for PMID=%s, PMCID=%s",
                normalized_pmid,
                normalized_pmcid,
            )

            client = get_europe_pmc_client()

            # Determine source and ID
            if normalized_pmid:
                source_db = "MED"
                article_id = normalized_pmid
            else:
                source_db = "PMC"
                # Extract digits from normalized PMCID (PMC7096777 -> 7096777)
                if normalized_pmcid and normalized_pmcid.startswith("PMC"):
                    article_id = normalized_pmcid[3:]
                else:
                    article_id = normalized_pmcid or ""

            await _progress(2, 3, "Fetching Europe PMC text-mined annotations...")
            terms = await client.get_text_mined_terms(source_db, str(article_id), semantic_type)

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
            id_str = f"PMID:{normalized_pmid}" if normalized_pmid else f"PMC:{normalized_pmcid}"
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

        except IdentifierValidationError as exc:
            return ResponseFormatter.error(
                error=exc,
                suggestion="Provide one schema-valid PMID or PMCID source object.",
                example='get_text_mined_terms(source={"kind":"pmid","value":"12345678"})',
                tool_name="get_text_mined_terms",
                output_format=normalized_output_format,
            )
        except Exception as e:
            logger.warning("Text-mined term lookup failed (%s)", type(e).__name__)
            return ResponseFormatter.error(
                error="Europe PMC text-mining source unavailable.",
                suggestion="Retry later after confirming the article identifier.",
                tool_name="get_text_mined_terms",
                output_format=normalized_output_format,
            )
