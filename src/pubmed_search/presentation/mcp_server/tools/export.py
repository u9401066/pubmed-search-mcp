"""
Export Tools - MCP tools for citation export and fulltext access.

Provides citation exports and local literature-note persistence.

v0.1.30 Updates:
- Official NCBI Citation API as default source
- Explicit local formatting for caller-selected offline formats
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, cast

from pydantic import Field

from pubmed_search.application.export import (
    SUPPORTED_FORMATS,
    export_articles,
    resolve_note_export_dir,
    tenant_export_root,
    write_export_artifact,
    write_literature_notes,
)
from pubmed_search.domain.value_objects import (
    MAX_IDENTIFIER_CHARS,
    MAX_PMID_BATCH_CHARS,
    MAX_PMIDS_PER_REQUEST,
    IdentifierValidationError,
    normalize_pmid_batch,
)
from pubmed_search.shared.tenancy import current_tenant

from ._common import ResponseFormatter, get_session_manager, get_session_registry

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)

# Export directory for prepared files
EXPORT_DIR = Path(tempfile.gettempdir()) / "pubmed_exports"
OFFICIAL_FORMATS = ("ris", "medline", "csl")
OfficialCitationFormat = Literal["ris", "medline", "csl"]
NoteFormat = Literal["wiki", "foam", "markdown", "medpaper"]
NotePath = Annotated[str, Field(min_length=1, max_length=4_096)]
CollectionName = Annotated[str, Field(min_length=1, max_length=200)]
NotePmidText = Annotated[str, Field(min_length=1, max_length=MAX_PMID_BATCH_CHARS)]
NotePmidToken = Annotated[str, Field(min_length=1, max_length=MAX_IDENTIFIER_CHARS)]
NotePmidList = Annotated[
    list[NotePmidToken],
    Field(min_length=1, max_length=MAX_PMIDS_PER_REQUEST),
]
NotePmidInput = NotePmidText | NotePmidList


def _tenant_reference_locator(path_value: object, root: Path) -> dict[str, str]:
    """Convert one server-local note path into a tenant-safe logical locator."""
    if not isinstance(path_value, str) or not path_value:
        raise ValueError("Literature-note result contained an invalid filesystem path")
    canonical_root = root.expanduser().resolve()
    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        candidate = canonical_root / candidate
    try:
        relative = candidate.resolve().relative_to(canonical_root)
    except ValueError:
        raise ValueError("Literature-note result escaped the tenant references directory") from None
    return {
        "kind": "tenant_reference",
        "value": f"references/{relative.as_posix()}",
    }


def _redact_tenant_note_paths(result: dict[str, Any], root: Path) -> dict[str, Any]:
    """Remove host filesystem paths from an authenticated note-export result."""

    def sanitize(value: object) -> Any:
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        if not isinstance(value, dict):
            return value

        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if key == "output_dir":
                continue
            if key == "path" or key.endswith("_path"):
                locator_key = "locator" if key == "path" else f"{key[:-5]}_locator"
                cleaned[locator_key] = None if item is None else _tenant_reference_locator(item, root)
                continue
            cleaned[key] = sanitize(item)
        return cleaned

    redacted = sanitize(result)
    if not isinstance(redacted, dict):  # pragma: no cover - guarded by the public signature
        raise TypeError("Literature-note result must be an object")
    redacted["storage_locator"] = {"kind": "tenant_references", "value": "references"}
    redacted["path_visibility"] = "redacted"
    if str(root.expanduser().resolve()) in json.dumps(redacted, ensure_ascii=False):
        raise ValueError("Literature-note response still contains a server filesystem path")
    return redacted


def register_export_tools(mcp: MCPServer, searcher: LiteratureSearcher):
    """Register export-related tools."""

    @mcp.tool()
    async def prepare_export(
        pmids: NotePmidInput,
        format: Literal["ris", "medline", "csl", "bibtex", "csv", "json"] = "ris",
        include_abstract: bool = True,
        source: Literal["official", "local"] = "official",
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
            include_abstract: Include abstracts in output (default: True).
                False requires source="local"; official payloads are returned unmodified.
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
        try:
            normalized_pmids = normalize_pmid_batch(pmids)
            pmid_list = _resolve_pmids("last") if normalized_pmids == ["last"] else normalized_pmids
        except IdentifierValidationError as exc:
            return ResponseFormatter.error(
                error=exc,
                suggestion="Provide 'last', a PMID string, or a bounded JSON array of PMID strings",
                example='prepare_export(pmids=["12345678", "87654321"], format="ris")',
                tool_name="prepare_export",
                output_format="json",
            )
        if not isinstance(include_abstract, bool):
            return ResponseFormatter.error(
                error="include_abstract must be a boolean",
                tool_name="prepare_export",
                output_format="json",
            )
        normalized_abstract = include_abstract

        if not pmid_list:
            return ResponseFormatter.error(
                error="No valid PMIDs provided",
                suggestion="Use 'last' for last search results or provide PMIDs",
                example='prepare_export(pmids="12345678,87654321", format="ris")',
                tool_name="prepare_export",
                output_format="json",
            )

        format_lower = format
        source_lower = source
        if source_lower == "official" and not include_abstract:
            return ResponseFormatter.error(
                error="Official citation export cannot suppress abstracts",
                suggestion="Set source='local' with a supported local format and include_abstract=False",
                tool_name="prepare_export",
                output_format="json",
            )

        if source_lower == "official" and format_lower not in OFFICIAL_FORMATS:
            return ResponseFormatter.error(
                error=f"Format '{format_lower}' is not supported by the official NCBI exporter",
                suggestion=(
                    f"Use one of {', '.join(OFFICIAL_FORMATS)}, or explicitly set source='local' "
                    f"for {', '.join(SUPPORTED_FORMATS)}"
                ),
                example='prepare_export(pmids="last", format="bibtex", source="local")',
                tool_name="prepare_export",
                output_format="json",
            )

        # Validate format for local source
        if source_lower == "local" and format_lower not in SUPPORTED_FORMATS:
            return ResponseFormatter.error(
                error=f"Unsupported format: {format}",
                suggestion=f"Use one of: {', '.join(SUPPORTED_FORMATS)}",
                example='prepare_export(pmids="last", format="ris")',
                tool_name="prepare_export",
                output_format="json",
            )

        try:
            if source_lower == "official":
                # Resolve the exporter from the active server-scoped SourceRuntime.
                from pubmed_search.infrastructure.ncbi.citation_exporter import get_exporter

                result = await get_exporter().export_citations(
                    pmid_list,
                    format=cast("OfficialCitationFormat", format_lower),
                )

                if result.success:
                    return await asyncio.to_thread(
                        _format_export_response,
                        result.content,
                        format_lower,
                        result.pmid_count,
                        source="official",
                    )
                return ResponseFormatter.error(
                    error="Official NCBI citation export failed",
                    suggestion=(
                        "Retry the official export, or explicitly choose source='local' "
                        "if locally generated citation metadata is acceptable"
                    ),
                    tool_name="prepare_export",
                    output_format="json",
                )
            # Use local formatting
            return await _export_local(pmid_list, format_lower, normalized_abstract, searcher)

        except Exception as exc:
            logger.warning("Citation export failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                error="Citation export could not be completed",
                suggestion="Check PMIDs and format, then try again",
                tool_name="prepare_export",
                output_format="json",
            )

    @mcp.tool()
    async def save_literature_notes(
        pmids: NotePmidInput = "last",
        output_dir: NotePath | None = None,
        note_format: NoteFormat = "wiki",
        include_abstract: bool = True,
        overwrite: bool = False,
        create_index: bool = True,
        collection_name: CollectionName | None = None,
        template_file: NotePath | None = None,
        include_csl_json: bool = True,
    ) -> str:
        """
        Save searched articles as guided local wiki/Foam/Markdown notes.

        ## When to Use
        - After unified_search, persist the selected literature into a local note library.
        - Give agents a structured alternative to generic write_file calls.
        - Create wiki notes with Foam-compatible wikilinks, MedPaper-like reference notes, and frontmatter.
        - Use stable wiki/Foam link targets and return wiki_validation for unresolved-link checks.

        ## Local Directory Resolution
        1. output_dir argument, if provided
        2. PUBMED_NOTES_DIR environment variable
        3. PUBMED_WORKSPACE_DIR/references
        4. PUBMED_DATA_DIR/references

        ## Authenticated Service Boundary
        Remote authenticated callers cannot choose output_dir or template_file.
        Their notes always go to references/ under the current tenant's installed
        SessionManager data root; process-wide notes/workspace environment paths
        are intentionally ignored.

        Args:
            pmids: Articles to save. Accepts "last", a PMID string, or a JSON array of PMID strings.
            output_dir: Optional target folder for notes.
            note_format: "wiki" (default, Foam-compatible), "foam", "markdown", or "medpaper".
            include_abstract: Include abstracts in article notes.
            overwrite: Overwrite existing per-article notes when filenames collide.
            create_index: Create a collection index note linking saved articles.
            collection_name: Optional title/file stem for the index note.
            template_file: Optional Markdown template with placeholders like {title}, {pmid}, {citation_key}.
            include_csl_json: Write references.csl.json beside notes for citation-manager handoff.

        Returns:
            JSON with written/skipped files, index information, and wiki_validation.
            Local callers receive filesystem paths. Authenticated callers receive
            tenant-relative logical locators and never receive server host paths.

        Examples:
            save_literature_notes(pmids="last")
            save_literature_notes(pmids="last", note_format="medpaper", output_dir="./references")
            save_literature_notes(pmids="12345678,87654321", template_file="./ref-template.md")
        """
        try:
            normalized_pmids = normalize_pmid_batch(pmids)
            pmid_list = _resolve_pmids("last") if normalized_pmids == ["last"] else normalized_pmids
        except IdentifierValidationError as exc:
            return ResponseFormatter.error(
                error=exc,
                suggestion="Use 'last' or provide only complete positive PMID values",
                tool_name="save_literature_notes",
            )
        for name, flag_value in (
            ("include_abstract", include_abstract),
            ("overwrite", overwrite),
            ("create_index", create_index),
            ("include_csl_json", include_csl_json),
        ):
            if not isinstance(flag_value, bool):
                return ResponseFormatter.error(
                    error=f"{name} must be a boolean",
                    tool_name="save_literature_notes",
                )

        if note_format not in {"wiki", "foam", "markdown", "medpaper"}:
            return ResponseFormatter.error(
                error=f"Unsupported note format: {note_format}",
                suggestion="Use wiki, foam, markdown, or medpaper",
                tool_name="save_literature_notes",
            )
        for name, value, max_chars in (
            ("output_dir", output_dir, 4_096),
            ("template_file", template_file, 4_096),
            ("collection_name", collection_name, 200),
        ):
            if value is not None and (not value.strip() or len(value) > max_chars):
                return ResponseFormatter.error(
                    error=f"{name} must contain 1-{max_chars} characters",
                    tool_name="save_literature_notes",
                )

        if not pmid_list:
            return ResponseFormatter.error(
                error="No valid PMIDs provided",
                suggestion="Run unified_search first and use pmids='last', or provide PMID values",
                example='save_literature_notes(pmids="last", output_dir="./references")',
                tool_name="save_literature_notes",
            )

        try:
            from pubmed_search.presentation.mcp_server.tenancy import durable_storage_denied

            denied = durable_storage_denied("save_literature_notes")
            if denied:
                return denied

            identity = current_tenant()
            resolved_template_file: Path | None
            if identity.is_authenticated:
                if output_dir is not None:
                    return ResponseFormatter.error(
                        error="Authenticated service callers cannot choose output_dir",
                        suggestion=(
                            "Omit output_dir; notes are saved under the current tenant's isolated references directory"
                        ),
                        tool_name="save_literature_notes",
                    )
                if template_file is not None:
                    return ResponseFormatter.error(
                        error="Authenticated service callers cannot read template_file from the server filesystem",
                        suggestion="Omit template_file and use a built-in note_format",
                        tool_name="save_literature_notes",
                    )

                session_manager = get_session_manager()
                installed_data_dir = getattr(session_manager, "data_dir", None)
                if not isinstance(installed_data_dir, (str, Path)):
                    return ResponseFormatter.error(
                        error="No persistent tenant note directory is installed for this caller",
                        suggestion="Ask the server operator to configure a persistent PUBMED_DATA_DIR",
                        tool_name="save_literature_notes",
                    )

                tenant_root = Path(installed_data_dir).expanduser().resolve()
                target_dir = (tenant_root / "references").resolve()
                try:
                    target_dir.relative_to(tenant_root)
                except ValueError:
                    return ResponseFormatter.error(
                        error="Tenant references directory resolves outside the installed tenant data root",
                        suggestion="Ask the server operator to repair the tenant references directory",
                        tool_name="save_literature_notes",
                    )
                resolved_template_file = None
            else:
                from pubmed_search.shared.settings import load_settings
                from pubmed_search.shared.tenancy import tenant_data_dir

                settings = load_settings()
                target_dir = resolve_note_export_dir(
                    output_dir,
                    notes_dir=settings.notes_dir,
                    workspace_dir=settings.workspace_dir,
                    data_dir=tenant_data_dir(settings.data_dir),
                )
                resolved_template_file = Path(template_file).expanduser() if template_file else None

            articles = await _get_articles_for_note_export(pmid_list, searcher)
            if not articles:
                return ResponseFormatter.no_results(
                    query=f"PMIDs: {', '.join(pmid_list[:5])}",
                    suggestions=[
                        "Check if the PMIDs are correct",
                        "Use unified_search first, then save_literature_notes(pmids='last')",
                    ],
                )

            result = await asyncio.to_thread(
                write_literature_notes,
                articles,
                target_dir,
                note_format=note_format,
                include_abstract=include_abstract,
                overwrite=overwrite,
                create_index=create_index,
                collection_name=collection_name,
                search_context=_get_last_search_context() if normalized_pmids == ["last"] else None,
                template_file=resolved_template_file,
                include_csl_json=include_csl_json,
            )
            result["instructions"] = (
                "Notes were written locally using a guided template; agents can now edit those files directly."
            )
            if identity.is_authenticated:
                result = _redact_tenant_note_paths(result, target_dir)
                result["instructions"] = (
                    "Notes were written to isolated tenant storage. Use the returned logical locators; "
                    "server filesystem paths are intentionally hidden."
                )
            return json.dumps(result, ensure_ascii=False, indent=2)

        except ValueError as e:
            return ResponseFormatter.error(
                error=str(e),
                suggestion="Use note_format='wiki', 'foam', 'markdown', or 'medpaper'; verify template_file path/placeholders",
                example='save_literature_notes(pmids="last", note_format="wiki")',
                tool_name="save_literature_notes",
            )
        except Exception as exc:
            logger.warning("Literature-note export failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                error="Literature notes could not be saved",
                suggestion="Check PMIDs and output directory permissions, then try again",
                tool_name="save_literature_notes",
            )


def _resolve_pmids(pmids: str) -> list[str]:
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
                    return normalize_pmid_batch(last_search.get("pmids", []), allow_last=False)
                # Fallback for SearchRecord dataclass
                if hasattr(last_search, "pmids"):
                    return normalize_pmid_batch(last_search.pmids, allow_last=False)
        return []

    # Parse comma-separated list
    return normalize_pmid_batch(pmids, allow_last=False)


def _save_export_file(content: str, format: str) -> str:
    """Save a local stdio export to the temporary export directory."""
    _export_id, file_path = write_export_artifact(
        content,
        extension=_get_file_extension(format),
        root=EXPORT_DIR,
    )
    return str(file_path)


def _configured_export_data_dir() -> str | None:
    """Return the data root installed with the active server.

    Programmatic callers may pass ``data_dir`` directly to ``create_server``;
    that injected registry is authoritative over process-wide environment
    settings. An explicitly in-memory registry must also stay in-memory.
    """
    registry = get_session_registry()
    if registry is not None:
        return registry.data_dir  # tenant-ok: base only; tenant_export_root scopes before writing

    # Keep the export tool's import surface lightweight. Settings pulls in
    # pydantic-settings and is only needed for this no-registry fallback.
    from pubmed_search.shared.settings import load_settings

    return load_settings().data_dir  # tenant-ok: base only; tenant_export_root scopes before writing


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

    Used only when the caller explicitly selects local formatting.
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

    return await asyncio.to_thread(
        _format_export_response,
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
        identity = current_tenant()
        if not identity.owns_durable_storage:
            return json.dumps(
                {
                    "status": "success",
                    "article_count": count,
                    "format": format_str,
                    "source": source,
                    "export_text": content,
                    "message": "Ephemeral HTTP callers receive large exports inline; no server file was created",
                }
            )

        if identity.source != "stdio":
            export_root = tenant_export_root(_configured_export_data_dir(), identity)
            if export_root is None:  # pragma: no cover - guarded by durable identity
                return ResponseFormatter.error(
                    error="No tenant export directory is available",
                    suggestion="Ask the server operator to configure PUBMED_DATA_DIR",
                    tool_name="prepare_export",
                )
            export_id, _file_path = write_export_artifact(
                content,
                extension=_get_file_extension(format_str),
                root=export_root,
            )
            return json.dumps(
                {
                    "status": "success",
                    "article_count": count,
                    "format": format_str,
                    "source": source,
                    "message": "Large export saved to tenant-scoped storage",
                    "export_id": export_id,
                    "download_url": f"/download/{export_id}",
                }
            )

        file_path = _save_export_file(content, format_str)
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
