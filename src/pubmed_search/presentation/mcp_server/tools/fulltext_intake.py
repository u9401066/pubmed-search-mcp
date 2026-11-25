"""MCP tool for fulltext obtained by the host agent or the user.

Tools:
- register_fulltext: store article text that the server could not obtain
  itself (host WebFetch of a public page, the user's browser session, a PDF
  the user owns, a Zotero attachment) with mandatory provenance, so later
  ``get_fulltext`` reads, notes and Chronicle evidence reuse it as
  ``agent_supplied`` / ``user_supplied`` text, never as provider-verified
  fulltext.

The tool only adapts MCP input and output; validation, path policy, bounds and
storage live in ``application.fulltext.intake`` and ``.supplied``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from pubmed_search.shared.markdown import escape_markdown_block, escape_markdown_text
from pubmed_search.shared.settings import load_settings
from pubmed_search.shared.tenancy import current_tenant

from ._common import ResponseFormatter, get_session_manager
from .agent_output import (
    finalize_next_tools,
    is_structured_output_format,
    make_next_tool,
    normalize_output_format,
    serialize_structured_payload,
)
from .article_source import ArticleSource, normalize_article_source
from .artifact_memory import artifact_markdown_note, artifact_persistence_enabled, persist_tool_artifact
from .fulltext_runtime import supplied_fulltext_store

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from pubmed_search.application.fulltext.intake import FulltextIntakeResult, IntakePathPolicy
    from pubmed_search.application.fulltext.supplied import SuppliedFulltextRecord

logger = logging.getLogger(__name__)

IntakeContent = Annotated[str, Field(min_length=1, max_length=1_000_000)]
IntakePath = Annotated[str, Field(min_length=1, max_length=4_096)]
IntakeTitle = Annotated[str, Field(min_length=1, max_length=500)]
_ShortText = Annotated[str, Field(min_length=1, max_length=500)]

_SUGGESTIONS = {
    "invalid_provenance": (
        "Provide provenance.retrieval_method, provenance.retrieved_at (ISO-8601) and provenance.source_url "
        "(or a file_path / provenance.source_file)."
    ),
    "content_required": "Send exactly one of content or file_path.",
    "content_too_large": "Register the relevant sections only, or save the text to a file inside the workspace.",
    "file_not_allowed": (
        "Save the file inside the workspace (PUBMED_WORKSPACE_DIR), the notes directory or a directory listed in "
        "PUBMED_FULLTEXT_INTAKE_ROOTS, without '..' components; remote callers must send content instead."
    ),
    "file_not_found": "Check the path; relative paths resolve against the workspace directory.",
    "unsupported_file_type": "Use .pdf, .txt, .md, .html/.htm or .xml/.nxml (JATS).",
    "file_too_large": "Split the document or register only the needed sections as content.",
    "extraction_failed": (
        "Install a PDF text backend (PyMuPDF or pdfplumber), use asset-aware-mcp to ingest/OCR the PDF, "
        "or send the extracted text as content."
    ),
    "empty_content": "Send the verbatim article text, not an empty page or a summary.",
    "invalid_content": "Check that content_format matches the content (text, markdown, jats or html).",
    "invalid_identifier": "Use one strict PMID, PMC-prefixed PMCID or DOI source object.",
    "storage_unavailable": "Retry once; if it persists, check the server data directory permissions.",
}


class SuppliedProvenanceInput(BaseModel):
    """Where the supplied text came from (required)."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    retrieval_method: Literal[
        "host_fetch",
        "host_browser",
        "user_upload",
        "zotero_attachment",
        "asset_aware_ingest",
        "manual_entry",
        "other",
    ] = Field(description="How the text was obtained, e.g. host_fetch for the agent's WebFetch.")
    retrieved_at: Annotated[str, Field(min_length=4, max_length=64)] = Field(
        description="ISO-8601 date or date-time when the text was fetched or exported."
    )
    source_url: Annotated[str, Field(min_length=8, max_length=2_048)] | None = Field(
        default=None, description="http(s) URL the text was read from."
    )
    source_file: _ShortText | None = Field(default=None, description="Display name of the source file, if any.")
    license: _ShortText | None = Field(default=None, description="License or terms shown with the copy, verbatim.")
    note: _ShortText | None = Field(default=None, description="Short free-text note, e.g. which version.")


def _intake_path_policy(store_root: Path) -> IntakePathPolicy:
    """Roots a caller may read: workspace, notes, tenant data and explicit intake roots."""
    from pubmed_search.application.fulltext.intake import IntakePathPolicy

    settings = load_settings()
    identity = current_tenant()
    roots: list[Path] = []
    for value in (settings.workspace_dir, settings.notes_dir, *settings.fulltext_intake_roots):
        if value:
            roots.append(Path(value))
    # The tenant data directory (two levels above the store root) is always allowed.
    roots.append(store_root.parent.parent)
    return IntakePathPolicy(roots=tuple(roots), allow_files=not identity.is_authenticated)


def _local_aliases(kind: str, value: str) -> tuple[tuple[str, str], ...]:
    """Add identifiers already known locally for a PMID (no network)."""
    if kind != "pmid":
        return ()
    manager = get_session_manager()
    getter = getattr(manager, "get_cached_article", None)
    if not callable(getter):
        return ()
    try:
        article = getter(value)
    except Exception:
        return ()
    if not isinstance(article, dict):
        return ()
    aliases: list[tuple[str, str]] = []
    if article.get("pmc_id"):
        aliases.append(("pmcid", str(article["pmc_id"])))
    if article.get("doi"):
        aliases.append(("doi", str(article["doi"])))
    return tuple(aliases)


def _render_record_markdown(record: SuppliedFulltextRecord) -> str:
    lines = [f"# {escape_markdown_text(record.title or 'Supplied fulltext')}", ""]
    if record.abstract:
        lines.extend(["## Abstract", "", escape_markdown_block(record.abstract), ""])
    for section in record.sections:
        lines.extend(
            [f"## {escape_markdown_text(section['title'])}", "", escape_markdown_block(section["content"]), ""]
        )
    return "\n".join(lines)


def _source_literal(source: dict[str, str]) -> str:
    return f'{{"kind":"{source["kind"]}","value":"{source["value"]}"}}'


def _response_payload(
    outcome: FulltextIntakeResult,
    *,
    requested: dict[str, str],
    artifact: dict[str, Any] | None,
) -> dict[str, Any]:
    record = outcome.record
    suggestions = [
        make_next_tool(
            "get_fulltext",
            "Read the registered text back (sections filter supported); it is labelled as supplied.",
            f'get_fulltext(source={_source_literal(requested)}, output_format="json")',
        )
    ]
    if "pmid" in record.identifiers:
        suggestions.append(
            make_next_tool(
                "save_literature_notes",
                "Write a literature note; its front matter records the registered fulltext state.",
                f'save_literature_notes(pmids="{record.identifiers["pmid"]}")',
            )
        )
    next_tools, next_commands = finalize_next_tools(suggestions)
    payload: dict[str, Any] = {
        "tool": "register_fulltext",
        "status": "registered",
        "record": {
            "record_id": record.record_id,
            "origin": record.origin,
            "provider_verified": False,
            "identifiers": dict(record.identifiers),
            "title": record.title or None,
            "content_format": record.content_format,
            "section_titles": [section["title"] for section in record.sections],
            "section_count": len(record.sections),
            "char_count": record.char_count,
            "abstract_chars": len(record.abstract),
            "content_sha256": record.content_sha256,
            "truncated": record.truncated,
            "registered_at": record.registered_at,
        },
        "provenance": record.provenance.to_dict(),
        "source_bytes": outcome.source_bytes,
        "storage": {
            "scope": "tenant",
            "reused_by": ["get_fulltext", "save_literature_notes", "read_research_chronicle evidence lookups"],
            "note": (
                "Later get_fulltext reads for these identifiers serve this text first, labelled as "
                f"{record.origin}; pass use_registered_fulltext=false to re-query providers."
            ),
        },
        "citation_ready": {
            "status": "not_citation_ready",
            "reason": "Supplied text has no page or line locators.",
            "hint": (
                "For PDFs, ingest the same file with asset-aware-mcp (ingest_documents / parse_pdf_structure) "
                "for citation-ready evidence spans."
            ),
        },
        "hints": list(record.hints),
        "next_tools": next_tools,
        "next_commands": next_commands,
    }
    if artifact:
        payload["artifact"] = artifact
    return payload


def _payload_markdown(payload: dict[str, Any]) -> str:
    record = payload["record"]
    provenance = payload["provenance"]
    lines = [
        f"✅ **Registered {escape_markdown_text(record['origin'])} fulltext** (`{record['record_id']}`)",
        "",
        f"- Identifiers: {escape_markdown_text(', '.join(f'{k}={v}' for k, v in record['identifiers'].items()))}",
        f"- Title: {escape_markdown_text(record['title'] or '—')}",
        f"- Format: {escape_markdown_text(record['content_format'])}; sections: {record['section_count']}; "
        f"characters: {record['char_count']}{' (truncated)' if record['truncated'] else ''}",
        f"- Retrieved: {escape_markdown_text(provenance.get('retrieved_at', ''))} via "
        f"{escape_markdown_text(provenance.get('retrieval_method', ''))} from "
        f"{escape_markdown_text(provenance.get('source_url') or provenance.get('source_file') or '')}",
    ]
    if provenance.get("license"):
        lines.append(f"- Declared license: {escape_markdown_text(provenance['license'])}")
    lines.extend(
        [
            "- Provider verified: no (the server did not check this text against a provider copy)",
            "",
            f"_{escape_markdown_text(payload['storage']['note'])}_",
            "",
            f"_Citation readiness: {escape_markdown_text(payload['citation_ready']['hint'])}_",
        ]
    )
    for hint in payload["hints"]:
        lines.append(f"\n> {escape_markdown_text(hint)}")
    if payload["next_commands"]:
        lines.extend(["", "Next:", *(f"- `{command}`" for command in payload["next_commands"])])
    return "\n".join(lines) + "\n"


def register_fulltext_intake_tools(mcp: MCPServer) -> None:
    """Register the supplied-fulltext intake tool."""

    @mcp.tool()
    async def register_fulltext(
        source: ArticleSource,
        provenance: SuppliedProvenanceInput,
        content: IntakeContent | None = None,
        content_format: Literal["text", "markdown", "jats", "html"] = "markdown",
        file_path: IntakePath | None = None,
        supplied_by: Literal["agent", "user"] = "agent",
        title: IntakeTitle | None = None,
        output_format: Literal["markdown", "json", "toon"] = "markdown",
    ) -> str:
        """
        Register article fulltext obtained by the host agent or the user.

        Use this after get_fulltext returned no usable body and you followed a
        fulltext_plan step yourself: WebFetch of a public article page, the
        user's own browser session, an open-access PDF, a Zotero attachment,
        or a file the user provided. The text is stored in this tenant's
        fulltext store as agent_supplied or user_supplied (never as
        provider-verified fulltext), and later get_fulltext reads, literature
        notes and Chronicle evidence lookups reuse it.

        Register only verbatim article text (not a summary) that the user may
        lawfully use; individual reading only, never bulk or systematic
        downloads. PDFs are text-extracted without page locators; for
        citation-ready spans also ingest the PDF with asset-aware-mcp.

        Args:
            source: Article identifier, e.g. {"kind":"pmid","value":"30721296"}.
            provenance: Required. {"retrieval_method": "host_fetch" | "host_browser" |
                "user_upload" | "zotero_attachment" | "asset_aware_ingest" | "manual_entry" |
                "other", "retrieved_at": ISO-8601, "source_url": "https://...",
                "license": optional verbatim license text, "note": optional}.
                A source_url or a file is required.
            content: Article text (up to 1,000,000 characters). Exactly one of
                content or file_path.
            content_format: Format of content: markdown (default, e.g. WebFetch
                output), text, jats (XML) or html.
            file_path: Local .pdf, .txt, .md, .html or .xml file inside the
                workspace, notes directory, tenant data directory or
                PUBMED_FULLTEXT_INTAKE_ROOTS. Relative paths resolve against the
                workspace. Not available to remote authenticated callers.
            supplied_by: "agent" (default) or "user" (the user provided the copy).
            title: Optional article title when the content has none.
            output_format: "markdown" (default), "json" or "toon".

        Returns:
            The stored record summary, its provenance and how it will be reused.

        Example:
            register_fulltext(
                source={"kind":"pmcid","value":"PMC6439616"},
                content="# Results\\n...verbatim text...",
                provenance={"retrieval_method":"host_fetch",
                            "source_url":"https://pmc.ncbi.nlm.nih.gov/articles/PMC6439616/",
                            "retrieved_at":"2026-11-25T08:00:00Z"})
        """
        from pubmed_search.application.fulltext.intake import FulltextIntakeRequest, FulltextIntakeService
        from pubmed_search.application.fulltext.supplied import SuppliedFulltextError
        from pubmed_search.infrastructure.sources.fulltext_intake import IntakeContentParsers
        from pubmed_search.presentation.mcp_server.tenancy import durable_storage_denied

        normalized_output_format = normalize_output_format(output_format)
        denied = durable_storage_denied("register_fulltext", output_format=normalized_output_format)
        if denied:
            return denied
        store = supplied_fulltext_store()
        if store is None:
            return ResponseFormatter.error(
                error="Persistent tenant storage is not configured, so supplied fulltext cannot be kept",
                suggestion="Ask the server operator to configure a persistent PUBMED_DATA_DIR.",
                tool_name="register_fulltext",
                output_format=normalized_output_format,
            )

        identifier = normalize_article_source(source)
        requested = {"kind": identifier.kind, "value": identifier.value}
        artifact_holder: dict[str, Any] = {}

        async def write_artifact(record: SuppliedFulltextRecord) -> str | None:
            if not artifact_persistence_enabled():
                return None
            artifact = await persist_tool_artifact(
                tool="register_fulltext",
                kind="fulltext",
                files={
                    "fulltext.md": _render_record_markdown(record),
                    "provenance.json": record.retrieval_summary(),
                    "record.json": record.to_dict(),
                },
                primary_file="fulltext.md",
                summary={
                    "title": record.title or None,
                    **record.identifiers,
                    "origin": record.origin,
                    "fulltext_available": True,
                    "provider_verified": False,
                },
                metadata={"origin": record.origin, "content_format": record.content_format},
            )
            if artifact:
                artifact_holder["artifact"] = artifact
                uri = artifact.get("artifact_uri")
                return str(uri) if uri else None
            return None

        service = FulltextIntakeService(
            store=store,
            parser=IntakeContentParsers(),
            path_policy=_intake_path_policy(store.root),
        )
        try:
            outcome = await service.register(
                FulltextIntakeRequest(
                    identifier_kind=identifier.kind,
                    identifier_value=identifier.value,
                    provenance=provenance.model_dump(exclude_none=True),
                    supplied_by=supplied_by,
                    content=content,
                    content_format=content_format,
                    file_path=file_path,
                    title=title,
                    aliases=_local_aliases(identifier.kind, identifier.value),
                ),
                artifact_writer=write_artifact,
            )
        except SuppliedFulltextError as exc:
            return ResponseFormatter.error(
                error=f"{exc.code}: {exc}",
                suggestion=_SUGGESTIONS.get(exc.code),
                tool_name="register_fulltext",
                output_format=normalized_output_format,
            )

        payload = _response_payload(outcome, requested=requested, artifact=artifact_holder.get("artifact"))
        if is_structured_output_format(normalized_output_format):
            return serialize_structured_payload(payload, normalized_output_format)
        return _payload_markdown(payload) + artifact_markdown_note(artifact_holder.get("artifact"))


__all__ = ["SuppliedProvenanceInput", "register_fulltext_intake_tools"]
