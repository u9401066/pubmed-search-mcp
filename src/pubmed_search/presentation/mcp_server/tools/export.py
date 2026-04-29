"""
Export Tools - MCP tools for citation export and fulltext access.

Provides:
- prepare_export: Export search results to various formats
- get_fulltext_links: Get fulltext URLs for an article
- summarize_fulltext_access: Analyze fulltext availability

Phase 2.1 Updates:
- InputNormalizer for flexible PMID input
- ResponseFormatter for consistent error messages

v0.1.30 Updates:
- Official NCBI Citation API as default source
- Fallback to local formatting when API unavailable
"""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Union

from pubmed_search.application.export import (
    SUPPORTED_FORMATS,
    export_articles,
    get_fulltext_links_with_lookup,
    resolve_note_export_dir,
    summarize_access,
    write_literature_notes,
)
from pubmed_search.infrastructure.ncbi.citation_exporter import (
    OFFICIAL_FORMATS,
    CitationResult,
    export_citations_official,
)
from pubmed_search.shared.settings import load_settings

from ._common import InputNormalizer, ResponseFormatter, get_session_manager

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)

# Export directory for prepared files
EXPORT_DIR = Path(tempfile.gettempdir()) / "pubmed_exports"


def register_export_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """Register export-related tools."""

    @mcp.tool()
    async def prepare_export(
        pmids: Union[str, list, int],
        format: str = "ris",
        include_abstract: bool = True,
        source: str = "official",
    ) -> str:
        """
        Export citations to reference manager formats.

        ╔═══════════════════════════════════════════════════════════════════╗
        ║  RECOMMENDED: Use source="official" (default) for best quality   ║
        ╚═══════════════════════════════════════════════════════════════════╝

        ## When to Use
        - Exporting references to EndNote, Zotero, Mendeley
        - Creating BibTeX for LaTeX documents
        - Generating citation lists for manuscripts

        ## Source Options
        | Source     | Formats            | Quality    | Speed  |
        |------------|--------------------|------------|--------|
        | official   | ris, medline, csl  | ★★★★★     | Fast   |
        | local      | ris, bibtex, csv, medline, json | ★★★★ | Fast |

        ## Format Selection Guide
        - ris: EndNote, Zotero, Mendeley (official recommended)
        - medline: NBIB format for PubMed tools
        - csl: JSON for programmatic citation styling
        - bibtex: LaTeX documents (local only)
        - csv: Data analysis, Excel (local only)

        Args:
            pmids: Articles to export. Accepts:
                   - "last" → results from previous search
                   - "12345678,87654321" → comma-separated PMIDs
                   - ["12345678", "87654321"] → list of PMIDs
                   - "PMID:12345678" → with prefix
            format: Export format (default: "ris")
                   - official API: ris, medline, csl
                   - local only: bibtex, csv, json
            include_abstract: Include abstracts in output (default: True)
            source: Citation source (default: "official")
                   - "official": NCBI Citation API (recommended, best quality)
                   - "local": Local formatting (more formats, offline capable)

        Returns:
            JSON with status and export_text containing formatted citations.

        Examples:
            # Export last search results (recommended)
            prepare_export(pmids="last", format="ris")

            # Export specific PMIDs to BibTeX
            prepare_export(pmids="12345678,87654321", format="bibtex", source="local")

            # Get CSL-JSON for programmatic use
            prepare_export(pmids="last", format="csl", source="official")
        """
        # Phase 2.1: Input normalization
        normalized_pmids = InputNormalizer.normalize_pmids(pmids)
        normalized_abstract = InputNormalizer.normalize_bool(include_abstract, default=True)

        # Handle "last" keyword
        pmid_list = _resolve_pmids("last") if normalized_pmids == ["last"] else normalized_pmids

        if not pmid_list:
            return ResponseFormatter.error(
                error="No valid PMIDs provided",
                suggestion="Use 'last' for last search results or provide PMIDs",
                example='prepare_export(pmids="12345678,87654321", format="ris")',
                tool_name="prepare_export",
            )

        format_lower = format.lower()
        source_lower = source.lower()

        # Determine which source to use
        use_official = source_lower == "official" and format_lower in OFFICIAL_FORMATS

        # If user requested official but format not supported, suggest alternative
        if source_lower == "official" and format_lower not in OFFICIAL_FORMATS:
            if format_lower in SUPPORTED_FORMATS:
                # Use local fallback for unsupported official formats
                use_official = False
                logger.info(f"Format '{format_lower}' not available via official API, using local")
            else:
                return ResponseFormatter.error(
                    error=f"Unsupported format: {format}",
                    suggestion=f"Official API formats: {', '.join(OFFICIAL_FORMATS)}. "
                    f"Local formats: {', '.join(SUPPORTED_FORMATS)}",
                    example='prepare_export(pmids="last", format="ris")',
                    tool_name="prepare_export",
                )

        # Validate format for local source
        if not use_official and format_lower not in SUPPORTED_FORMATS:
            return ResponseFormatter.error(
                error=f"Unsupported format: {format}",
                suggestion=f"Use one of: {', '.join(SUPPORTED_FORMATS)}",
                example='prepare_export(pmids="last", format="ris")',
                tool_name="prepare_export",
            )

        try:
            if use_official:
                # Use official NCBI Citation API
                result: CitationResult = await export_citations_official(
                    pmid_list,
                    format=format_lower,  # type: ignore[arg-type]
                )

                if result.success:
                    return _format_export_response(
                        result.content,
                        format_lower,
                        result.pmid_count,
                        source="official",
                    )
                # Fallback to local on API failure
                logger.warning(f"Official API failed ({result.error}), falling back to local")
                return await _export_local(pmid_list, format_lower, normalized_abstract, searcher)
            # Use local formatting
            return await _export_local(pmid_list, format_lower, normalized_abstract, searcher)

        except Exception as e:
            logger.exception("Error preparing export")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check PMIDs and format, then try again",
                tool_name="prepare_export",
            )

    @mcp.tool()
    async def save_literature_notes(
        pmids: Union[str, list, int] = "last",
        output_dir: str | None = None,
        note_format: str = "wiki",
        include_abstract: bool = True,
        overwrite: bool = False,
        create_index: bool = True,
        collection_name: str | None = None,
        template_file: str | None = None,
        include_csl_json: bool = True,
    ) -> str:
        """
        Save searched articles as guided local wiki/Foam/Markdown notes.

        ## When to Use
        - After unified_search, persist the selected literature into a local note library.
        - Give agents a structured alternative to generic write_file calls.
        - Create wiki notes with Foam-compatible wikilinks, MedPaper-like reference notes, and frontmatter.

        ## Local Directory Resolution
        1. output_dir argument, if provided
        2. PUBMED_NOTES_DIR environment variable
        3. PUBMED_WORKSPACE_DIR/references
        4. PUBMED_DATA_DIR/references

        Args:
            pmids: Articles to save. Accepts "last", comma-separated PMIDs, list, or int.
            output_dir: Optional target folder for notes.
            note_format: "wiki" (default, Foam-compatible), "foam", "markdown", or "medpaper".
            include_abstract: Include abstracts in article notes.
            overwrite: Overwrite existing per-article notes when filenames collide.
            create_index: Create a collection index note linking saved articles.
            collection_name: Optional title/file stem for the index note.
            template_file: Optional Markdown template with placeholders like {title}, {pmid}, {citation_key}.
            include_csl_json: Write references.csl.json beside notes for citation-manager handoff.

        Returns:
            JSON with output_dir, written files, skipped files, and index path.

        Examples:
            save_literature_notes(pmids="last")
            save_literature_notes(pmids="last", note_format="medpaper", output_dir="./references")
            save_literature_notes(pmids="12345678,87654321", template_file="./ref-template.md")
        """
        normalized_pmids = InputNormalizer.normalize_pmids(pmids)
        normalized_abstract = InputNormalizer.normalize_bool(include_abstract, default=True)
        normalized_overwrite = InputNormalizer.normalize_bool(overwrite, default=False)
        normalized_create_index = InputNormalizer.normalize_bool(create_index, default=True)
        normalized_csl = InputNormalizer.normalize_bool(include_csl_json, default=True)

        pmid_list = _resolve_pmids("last") if normalized_pmids == ["last"] else normalized_pmids
        if not pmid_list:
            return ResponseFormatter.error(
                error="No valid PMIDs provided",
                suggestion="Run unified_search first and use pmids='last', or provide PMID values",
                example='save_literature_notes(pmids="last", output_dir="./references")',
                tool_name="save_literature_notes",
            )

        try:
            settings = load_settings()
            target_dir = resolve_note_export_dir(
                output_dir,
                notes_dir=settings.notes_dir,
                workspace_dir=settings.workspace_dir,
                data_dir=settings.data_dir,
            )
            articles = await _get_articles_for_note_export(pmid_list, searcher)
            if not articles:
                return ResponseFormatter.no_results(
                    query=f"PMIDs: {', '.join(pmid_list[:5])}",
                    suggestions=[
                        "Check if the PMIDs are correct",
                        "Use unified_search first, then save_literature_notes(pmids='last')",
                    ],
                )

            result = write_literature_notes(
                articles,
                target_dir,
                note_format=note_format,
                include_abstract=normalized_abstract,
                overwrite=normalized_overwrite,
                create_index=normalized_create_index,
                collection_name=collection_name,
                search_context=_get_last_search_context() if normalized_pmids == ["last"] else None,
                template_file=Path(template_file).expanduser() if template_file else None,
                include_csl_json=normalized_csl,
            )
            result["instructions"] = (
                "Notes were written locally using a guided template; agents can now edit those files directly."
            )
            return json.dumps(result, ensure_ascii=False, indent=2)

        except ValueError as e:
            return ResponseFormatter.error(
                error=str(e),
                suggestion="Use note_format='wiki', 'foam', 'markdown', or 'medpaper'; verify template_file path/placeholders",
                example='save_literature_notes(pmids="last", note_format="wiki")',
                tool_name="save_literature_notes",
            )
        except Exception as e:
            logger.exception("Error saving literature notes")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check PMIDs and output directory permissions, then try again",
                tool_name="save_literature_notes",
            )

    # ❌ REMOVED v0.1.20: Merged into unified get_fulltext tool
    # @mcp.tool()
    async def get_article_fulltext_links(pmid: Union[str, int]) -> str:
        """
        Get fulltext links for a single article.

        Returns URLs to access the full text:
        - PubMed page
        - PMC (if available - free full text)
        - PMC PDF direct link
        - DOI (publisher page)

        Args:
            pmid: PubMed ID (accepts: "12345678", "PMID:12345678", 12345678)

        Returns:
            JSON with available links and access type.
        """
        # Phase 2.1: Input normalization
        normalized_pmid = InputNormalizer.normalize_pmid_single(pmid)

        if not normalized_pmid:
            return ResponseFormatter.error(
                error="Invalid PMID format",
                suggestion="Provide a valid PMID number",
                example='get_article_fulltext_links(pmid="12345678")',
                tool_name="get_article_fulltext_links",
            )

        try:
            # Use API lookup to get PMC status
            links = await get_fulltext_links_with_lookup(normalized_pmid, searcher)

            # Add article title if available
            articles = await searcher.fetch_details([normalized_pmid])
            if articles:
                links["title"] = articles[0].get("title", "")[:100]
                links["doi_url"] = f"https://doi.org/{articles[0].get('doi')}" if articles[0].get("doi") else None

            return json.dumps({"status": "success", "links": links})

        except Exception as e:
            logger.exception(f"Error getting fulltext links for {normalized_pmid}")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check if the PMID is correct",
                tool_name="get_article_fulltext_links",
            )

    # ❌ REMOVED v0.1.20: Auto-handled by unified get_fulltext
    # @mcp.tool()
    async def analyze_fulltext_access(pmids: Union[str, list, int]) -> str:
        """
        Analyze fulltext availability for multiple articles.

        Useful for planning literature review - shows which articles
        have free full text available via PMC.

        Args:
            pmids: PubMed IDs - accepts multiple formats:
                   - "12345678,87654321" (comma-separated)
                   - ["12345678", "87654321"] (list)
                   - "PMID:12345678" (with prefix)
                   - "last" to use results from last search

        Returns:
            Summary statistics with lists of:
            - Open access articles (PMC available)
            - Subscription-required articles
            - Abstract-only articles
        """
        # Phase 2.1: Input normalization
        normalized_pmids = InputNormalizer.normalize_pmids(pmids)

        # Handle "last" keyword
        pmid_list = _resolve_pmids("last") if normalized_pmids == ["last"] else normalized_pmids

        if not pmid_list:
            return ResponseFormatter.error(
                error="No valid PMIDs provided",
                suggestion="Use 'last' for last search results or provide PMIDs",
                example='analyze_fulltext_access(pmids="12345678,87654321")',
                tool_name="analyze_fulltext_access",
            )

        try:
            # Fetch article details to get PMC info
            articles = await searcher.fetch_details(pmid_list)

            if not articles:
                return ResponseFormatter.no_results(
                    query=f"PMIDs: {', '.join(pmid_list[:5])}",
                    suggestions=[
                        "Check if the PMIDs are correct",
                        "Use unified_search to find valid PMIDs",
                    ],
                )

            # Analyze access
            summary = summarize_access(articles)

            return json.dumps({"status": "success", "summary": summary})

        except Exception as e:
            logger.exception("Error analyzing fulltext access")
            return ResponseFormatter.error(
                error=e,
                suggestion="Check PMIDs and try again",
                tool_name="analyze_fulltext_access",
            )


def _resolve_pmids(pmids: str) -> list:
    """Resolve PMID string to list. Supports 'last' for last search results."""
    if pmids.lower() == "last":
        # Get from session manager
        session_manager = get_session_manager()
        if session_manager:
            session = session_manager.get_or_create_session()
            if session.search_history:
                last_search = session.search_history[-1]
                # search_history is List[Dict], each dict has 'pmids' key
                if isinstance(last_search, dict):
                    return last_search.get("pmids", [])[:100]  # Limit to 100
                # Fallback for SearchRecord dataclass
                if hasattr(last_search, "pmids"):
                    return last_search.pmids[:100]
        return []

    # Parse comma-separated list
    return [p.strip() for p in pmids.split(",") if p.strip()]


def _save_export_file(content: str, format: str, count: int) -> str:
    """Save export content to a temporary file."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    extension = _get_file_extension(format)
    filename = f"pubmed_export_{count}_{timestamp}.{extension}"
    file_path = EXPORT_DIR / filename

    with file_path.open("w", encoding="utf-8") as f:
        f.write(content)

    return str(file_path)


def _get_file_extension(format: str) -> str:
    """Get file extension for format."""
    extensions = {
        "ris": "ris",
        "bibtex": "bib",
        "csv": "csv",
        "medline": "txt",
        "json": "json",
        "csl": "json",
    }
    return extensions.get(format, "txt")


async def _export_local(
    pmid_list: list,
    format_lower: str,
    include_abstract: bool,
    searcher: LiteratureSearcher,
) -> str:
    """
    Export citations using local formatting.

    Used as fallback when official API is unavailable,
    or for formats not supported by official API (bibtex, csv, json).
    """
    articles = await searcher.fetch_details(pmid_list)

    if not articles:
        return ResponseFormatter.no_results(
            query=f"PMIDs: {', '.join(pmid_list[:5])}",
            suggestions=[
                "Check if the PMIDs are correct",
                "Use unified_search to find valid PMIDs",
            ],
        )

    exported_text = export_articles(articles, fmt=format_lower, include_abstract=include_abstract)

    return _format_export_response(
        exported_text,
        format_lower,
        len(articles),
        source="local",
    )


async def _get_articles_for_note_export(
    pmid_list: list[str],
    searcher: LiteratureSearcher,
) -> list[dict]:
    """Return article payloads for notes, preferring session cache when available."""
    session_manager = get_session_manager()
    cached_map: dict[str, dict] = {}
    missing = list(pmid_list)

    if session_manager:
        cached_map, missing = session_manager.get_cached_article_map(pmid_list)

    fetched_map: dict[str, dict] = {}
    if missing:
        fetched_articles = await searcher.fetch_details(missing)
        fetched_map = {str(article.get("pmid", "")): article for article in fetched_articles if article.get("pmid")}
        if session_manager and fetched_articles:
            session_manager.add_to_cache(fetched_articles)

    merged = {**cached_map, **fetched_map}
    return [merged[pmid] for pmid in pmid_list if pmid in merged]


def _get_last_search_context() -> dict | None:
    """Return metadata for the latest session search, when available."""
    session_manager = get_session_manager()
    if not session_manager:
        return None

    session = session_manager.get_current_session()
    if not session or not session.search_history:
        return None

    latest = session.search_history[-1]
    return {
        "query": latest.get("query", ""),
        "timestamp": latest.get("timestamp", ""),
        "result_count": latest.get("result_count", len(latest.get("pmids", []))),
    }


def _format_export_response(
    content: str,
    format_str: str,
    count: int,
    source: str = "official",
) -> str:
    """
    Format export response consistently.

    For large exports (>20 articles), saves to file.
    For small exports, returns content directly.
    """
    # For large exports, save to file
    if count > 20:
        file_path = _save_export_file(content, format_str, count)
        return json.dumps(
            {
                "status": "success",
                "article_count": count,
                "format": format_str,
                "source": source,
                "message": "Large export saved to file",
                "file_path": file_path,
                "instructions": "Use 'cat' or open the file to view contents",
            }
        )

    # For small exports, return content directly
    return json.dumps(
        {
            "status": "success",
            "article_count": count,
            "format": format_str,
            "source": source,
            "export_text": content,
            "instructions": f"Copy the export_text content and save as .{_get_file_extension(format_str)}",
        }
    )
