"""Research Chronicle MCP tools.

Two thin wrappers over :class:`ChronicleService`:

- ``build_research_chronicle`` creates a new, persisted, evidence-backed
  revision from a topic or an explicit PMID list.
- ``read_research_chronicle`` is the read facade: load, list, diff, narrate,
  milestones, and compare.

The chronicle's primary axis is chronological; branches are a secondary
organizing dimension. Both are projections of the same stored snapshot, so
``output="timeline"`` and ``output="tree"`` never disagree.

Business logic lives in ``pubmed_search.application.chronicle``; these functions
only validate inputs, call the service, persist an artifact, and format text.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Annotated, Any, Literal

from mcp.server.mcpserver import Context  # noqa: TC002 - MCPServer needs runtime access for tool context injection
from pydantic import BaseModel, Field

from pubmed_search.application.chronicle import (
    CHRONICLE_READ_ORDER,
    ChronicleService,
    ChronicleStore,
    chronology_key,
    entry_max_citations,
    landmark_importance_score,
    landmark_rank_key,
    narrate_chronicle,
)
from pubmed_search.application.timeline import LandmarkScorer, MilestoneDetector, TimelineBuilder
from pubmed_search.presentation.mcp_server.tenancy import durable_storage_denied
from pubmed_search.shared.settings import DEFAULT_DATA_DIR

from ._common import ResponseFormatter, get_last_search_pmids, get_session_manager
from .artifact_memory import artifact_markdown_note, artifact_persistence_enabled, persist_tool_artifact
from .tool_runtime import safe_log, safe_report_progress

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from pubmed_search.domain.entities.chronicle import ChronicleSnapshot
    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)

#: Output modes accepted by ``build_research_chronicle``.
BUILD_OUTPUTS = (
    "summary",
    "json",
    "chronicle_map",
    "timeline",
    "tree",
    "graph",
    "evidence",
    "milestones",
    "mermaid",
    "timeline_mermaid",
    "mindmap",
    "narrative",
)

#: Read actions accepted by ``read_research_chronicle``.
READ_ACTIONS = ("load", "list", "diff", "narrate", "milestones", "compare")

ChronicleOutput = Literal[
    "summary",
    "json",
    "chronicle_map",
    "timeline",
    "tree",
    "graph",
    "evidence",
    "milestones",
    "mermaid",
    "timeline_mermaid",
    "mindmap",
    "narrative",
]
ChronicleReadAction = Literal["load", "list", "diff", "narrate", "milestones", "compare"]
NarrativeMode = Literal["brief", "full"]

MaxEvents = Annotated[int, Field(ge=1, le=200, description="Maximum Chronicle events")]
PublicationYear = Annotated[int, Field(ge=1000, le=2100, description="Four-digit publication year")]
PositiveRevision = Annotated[int, Field(ge=1, description="Positive Chronicle revision")]
ListLimit = Annotated[int, Field(ge=1, le=100, description="Maximum Chronicle records")]
TopicText = Annotated[str, Field(min_length=1, max_length=500)]
ChronicleIdText = Annotated[
    str,
    Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"),
]

#: How many spine entries the default summary shows.
_SPINE_LIMIT = 12

#: Maximum topics/chronicles accepted by ``action="compare"``.
_MAX_COMPARE = 5

#: Maximum explicit evidence set accepted in one request.
_MAX_PMIDS = 500
_MAX_PMID_DIGITS = 20

#: Machine-readable Chronicle projections. Errors for these modes remain JSON.
_STRUCTURED_OUTPUTS = frozenset({"json", "chronicle_map", "timeline", "tree", "graph", "evidence", "milestones"})

#: Permit ahead-of-print records dated one year beyond the server clock.
_MAX_PUBLICATION_YEAR = datetime.now(timezone.utc).year + 1

_SAFE_CHRONICLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_PMID_ITEM_PATTERN = r"(?:(?i:PMID)\s*:\s*)?([0-9]+)"
_PMID_LIST_RE = re.compile(rf"^\s*{_PMID_ITEM_PATTERN}(?:\s*(?:[,;|]|\s+)\s*{_PMID_ITEM_PATTERN})*\s*$")
_PMID_ITEM_RE = re.compile(_PMID_ITEM_PATTERN)


def _chronicle_store() -> ChronicleStore:
    """Return the chronicle revision store for the tenant of the current request.

    Callers that cannot own durable storage are turned away by
    ``durable_storage_denied`` before reaching here, so the root is never None.
    """
    manager = get_session_manager()
    root = getattr(manager, "data_dir", None) or DEFAULT_DATA_DIR
    return ChronicleStore(f"{root}/chronicles")


def _resolve_pmids(pmids: str | None) -> list[str]:
    """Parse strict PMID tokens, resolving the ``last`` sentinel via session.

    Chronicle evidence scope must be reproducible.  In particular, DOI text or
    arbitrary mixed identifiers must never be converted to a PMID by deleting
    their non-digit characters.
    """
    if pmids is None:
        return []

    raw = pmids.strip()
    if raw.casefold() == "last":
        resolved = get_last_search_pmids()
        invalid = [
            value
            for value in resolved
            if not isinstance(value, str) or not value.strip().isascii() or not value.strip().isdigit()
        ]
        if invalid:
            raise ValueError("The previous search contains a non-PMID identifier; run a new PubMed search first")
        tokens = [value.strip() for value in resolved]
        if any(len(value) > _MAX_PMID_DIGITS or not value.lstrip("0") for value in tokens):
            raise ValueError(f"PMIDs must be positive integers of at most {_MAX_PMID_DIGITS} digits")
        return [value.lstrip("0") for value in tokens]
    if not raw:
        return []
    if _PMID_LIST_RE.fullmatch(raw) is None:
        raise ValueError(
            "pmids must contain only ASCII digits or an explicit 'PMID:' prefix, "
            "separated by commas, semicolons, pipes, or whitespace"
        )
    tokens = [match.group(1) for match in _PMID_ITEM_RE.finditer(raw)]
    if any(len(value) > _MAX_PMID_DIGITS or not value.lstrip("0") for value in tokens):
        raise ValueError(f"PMIDs must be positive integers of at most {_MAX_PMID_DIGITS} digits")
    return [value.lstrip("0") for value in tokens]


def _split_csv(value: str | None) -> list[str]:
    """Split a comma-separated argument into trimmed, non-empty parts."""
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _build_response_format(output: str) -> str:
    """Return the formatter mode appropriate for a Chronicle build output."""
    return "json" if output in _STRUCTURED_OUTPUTS else "markdown"


def _read_response_format(action: str, output: str) -> str:
    """Keep errors machine-readable for read actions whose success is JSON."""
    if action in {"list", "diff", "milestones", "compare"}:
        return "json"
    if action == "load" and output in _STRUCTURED_OUTPUTS:
        return "json"
    return "markdown"


def _validate_year_range(min_year: int | None, max_year: int | None) -> str | None:
    """Validate publication bounds without silently changing the requested scope."""
    for label, year in (("min_year", min_year), ("max_year", max_year)):
        if year is None:
            continue
        if isinstance(year, bool) or not isinstance(year, int):
            return f"{label} must be an integer year"
        if not 1000 <= year <= _MAX_PUBLICATION_YEAR:
            return f"{label} must be between 1000 and {_MAX_PUBLICATION_YEAR}"
    if min_year is not None and max_year is not None and min_year > max_year:
        return "min_year cannot be later than max_year"
    return None


def _validate_chronicle_id(chronicle_id: str | None) -> str | None:
    """Validate an optional Chronicle identifier before retrieval begins."""
    if chronicle_id is None:
        return None
    if not isinstance(chronicle_id, str):
        return "chronicle_id must be a string"
    if len(chronicle_id) > 200 or not _SAFE_CHRONICLE_ID_RE.fullmatch(chronicle_id):
        return "chronicle_id must be 1-200 characters using only letters, numbers, '.', '_' or '-'"
    return None


def _optional_string_error(name: str, value: Any, *, max_length: int | None = None) -> str | None:
    """Return a user-facing error for an optional direct-call string input."""
    if value is None:
        return None
    if not isinstance(value, str):
        return f"{name} must be a string"
    if max_length is not None and len(value) > max_length:
        return f"{name} must contain at most {max_length} characters"
    return None


def _forbid_extra_tool_arguments(mcp: MCPServer, *tool_names: str) -> None:
    """Make the two Chronicle argument models reject unknown MCP properties.

    MCPServer currently has no decorator-level model-config hook.  Keep this
    post-registration adjustment local to Chronicle rather than changing the
    argument behavior of every server tool.
    """
    manager = getattr(mcp, "_tool_manager", None)
    get_tool = getattr(manager, "get_tool", None)
    if not callable(get_tool):  # pragma: no cover - compatibility with a future MCPServer implementation
        logger.warning("Could not enable strict extra-property rejection for Chronicle tools")
        return
    for tool_name in tool_names:
        tool = get_tool(tool_name)
        if tool is None:  # pragma: no cover - registration invariant
            logger.warning("Could not find registered Chronicle tool %s for schema hardening", tool_name)
            continue
        argument_model = tool.fn_metadata.arg_model
        if not isinstance(argument_model, type) or not issubclass(argument_model, BaseModel):
            # Lightweight MCP doubles used by embedders may expose a callable
            # ``get_tool`` without constructing MCP SDK 2's Pydantic metadata.
            # Registration must remain compatible with those hosts; the real
            # MCP SDK 2 path below is still hardened and covered by protocol tests.
            logger.debug("Skipping Chronicle schema hardening for non-Pydantic tool %s", tool_name)
            continue
        argument_model.model_config["extra"] = "forbid"
        argument_model.model_rebuild(force=True)
        tool.parameters = argument_model.model_json_schema(by_alias=True)


def _artifact_failure() -> dict[str, str]:
    """Return the structured marker used when optional artifact persistence fails."""
    return {
        "status": "failed",
        "warning": "The Chronicle revision was saved, but its session artifact could not be persisted.",
    }


def _format_summary(snapshot: ChronicleSnapshot) -> str:
    """Render the compact Markdown index card for a chronicle revision."""
    year_range = snapshot.year_range
    span = f"{year_range[0]}\u2013{year_range[1]}" if year_range else "n/a"
    lineage = snapshot.metadata.get("lineage_diagnostics", {})
    lineage_basis = lineage.get("basis", "unknown") if isinstance(lineage, dict) else "unknown"
    semantic_coverage = lineage.get("semantic_coverage_ratio", 0.0) if isinstance(lineage, dict) else 0.0
    lineage_label = (
        f"semantic topic signals ({float(semantic_coverage):.0%} entry coverage)"
        if lineage_basis == "topic_signals"
        else "research-stage fallback (not semantic topic clustering)"
        if lineage_basis == "research_stage_fallback"
        else str(lineage_basis)
    )
    lines = [
        f"# Research Chronicle: {snapshot.topic}",
        "",
        f"- Chronicle ID: `{snapshot.chronicle_id}`",
        f"- Revision: {snapshot.revision} (mode: {snapshot.input_scope.mode})",
        f"- Entries: {len(snapshot.entries)} across {len(snapshot.branches)} branches",
        f"- Evidence articles: {len(snapshot.evidence_articles)}",
        f"- Year span: {span}",
        f"- Graph: {len(snapshot.graph.nodes)} nodes, {len(snapshot.graph.edges)} edges",
        f"- Lineage basis: {lineage_label}",
        f"- Audit: **{snapshot.audit.status}**",
        "",
    ]

    spine = sorted(snapshot.entries, key=chronology_key)
    if spine:
        lines.append("## Chronological Spine")
        lines.append("")
        for entry in spine[:_SPINE_LIMIT]:
            branch_note = f" ({entry.branch_id})" if entry.branch_id else ""
            lines.append(f"- **{entry.time_start}** {entry.title}{branch_note} `[{entry.entry_id}]`")
        if len(spine) > _SPINE_LIMIT:
            lines.append(f'- _{len(spine) - _SPINE_LIMIT} further entries; use `output="timeline"` for all._')
        lines.append("")

    if snapshot.branches:
        lines.append("## Research Lines")
        lines.append("")
        for branch in snapshot.branches:
            if branch.entry_ids:
                lines.append(f"- **{branch.name}** \u2014 {len(branch.entry_ids)} entries")
        lines.append("")

    highlights = sorted(snapshot.entries, key=landmark_rank_key)[:5]
    if highlights:
        lines.append("## Evidence-informed Highlights")
        lines.append("")
        for entry in highlights:
            citations = ", ".join(a.evidence_id for a in entry.evidence.all_articles) or "no evidence"
            importance = landmark_importance_score(entry)
            ranking_note = (
                f"landmark importance {importance:.2f}"
                if importance is not None
                else f"citation-count fallback {entry_max_citations(entry)}"
            )
            lines.append(f"- {entry.summary_claim} `[{entry.entry_id}; {citations}; {ranking_note}]`")
        lines.append("")

    if snapshot.audit.warnings:
        lines.append("## Completeness Caveats")
        lines.append("")
        lines.extend(f"- {warning}" for warning in snapshot.audit.warnings)
        lines.append("")

    lines.append(
        f'Next: `read_research_chronicle(chronicle_id="{snapshot.chronicle_id}", output="mermaid")` '
        "for the horizontal time-spine/lineage map, or "
        f'`read_research_chronicle(action="diff", chronicle_id="{snapshot.chronicle_id}", from_revision=1)`'
    )
    return "\n".join(lines)


def _render_output(snapshot: ChronicleSnapshot, output: str) -> str:
    """Render a snapshot in the requested output mode as tool text."""
    if output == "summary":
        return _format_summary(snapshot)
    rendered = ChronicleService.render(snapshot, output)
    if isinstance(rendered, str):
        return rendered
    return json.dumps(rendered, indent=2, ensure_ascii=False)


def _with_artifact_note(
    body: str,
    artifact: dict[str, Any] | None,
    *,
    output: str,
    persistence_failed: bool = False,
) -> str:
    """Keep outputs parseable while exposing artifact success or failure."""
    note = artifact_markdown_note(artifact)
    if output in {"mermaid", "timeline_mermaid", "mindmap"}:
        rendered = _markdown_response_body(body, output=output) + note
        if persistence_failed:
            rendered += "\n\n> ⚠️ The Chronicle revision was saved, but its session artifact could not be persisted."
        return rendered
    if not note:
        if not persistence_failed:
            return body
        if output in _STRUCTURED_OUTPUTS:
            payload = json.loads(body)
            if isinstance(payload, dict):
                payload["artifact"] = _artifact_failure()
                return json.dumps(payload, indent=2, ensure_ascii=False)
        return body + "\n\n> ⚠️ The Chronicle revision was saved, but its session artifact could not be persisted."
    if output in {"json", "chronicle_map", "timeline", "tree", "graph", "evidence", "milestones"}:
        payload = json.loads(body)
        if isinstance(payload, dict):
            payload["artifact"] = artifact
            return json.dumps(payload, indent=2, ensure_ascii=False)
    return body + note


def _markdown_response_body(body: str, *, output: str) -> str:
    """Wrap Mermaid renderings for Markdown artifacts without altering source files."""
    return f"```mermaid\n{body}\n```" if output in {"mermaid", "timeline_mermaid", "mindmap"} else body


def _persist_chronicle_artifact(snapshot: ChronicleSnapshot, *, response_markdown: str) -> dict[str, Any] | None:
    """Persist the full chronicle revision as a session artifact."""
    files = ChronicleService.build_artifact_files(snapshot, narrative=narrate_chronicle(snapshot, mode="full"))
    files["response.md"] = response_markdown
    raw_lineage = snapshot.metadata.get("lineage_diagnostics")
    lineage_basis = raw_lineage.get("basis") if isinstance(raw_lineage, dict) else None
    return persist_tool_artifact(
        tool="build_research_chronicle",
        kind="research_chronicle",
        files=files,
        primary_file="snapshot.json",
        summary={
            "schema_version": snapshot.schema_version,
            "chronicle_id": snapshot.chronicle_id,
            "revision": snapshot.revision,
            "topic": snapshot.topic,
            "entry_count": len(snapshot.entries),
            "evidence_count": len(snapshot.evidence_articles),
            "audit_status": snapshot.audit.status,
            "audit": snapshot.audit.to_dict(),
            "lineage_basis": lineage_basis,
            "read_order": list(CHRONICLE_READ_ORDER),
        },
        metadata={
            "schema_version": "research-chronicle-artifact/v1",
            "chronicle_id": snapshot.chronicle_id,
            "revision": snapshot.revision,
        },
    )


def register_chronicle_tools(mcp: MCPServer, searcher: LiteratureSearcher) -> None:
    """Register the research chronicle tools (2 tools)."""
    builder = TimelineBuilder(searcher, MilestoneDetector(), LandmarkScorer())

    def service() -> ChronicleService:
        # Resolved per call: the store is tenant-scoped, so it cannot be captured.
        return ChronicleService(builder, _chronicle_store())

    @mcp.tool()
    async def build_research_chronicle(
        topic: TopicText | None = None,
        pmids: Annotated[str, Field(max_length=10000)] | None = None,
        max_events: MaxEvents = 30,
        min_year: PublicationYear | None = None,
        max_year: PublicationYear | None = None,
        chronicle_id: ChronicleIdText | None = None,
        output: ChronicleOutput = "summary",
        ctx: Context | None = None,
    ) -> str:
        """
        Build a persisted, versioned, evidence-backed Research Chronicle.

        A chronicle is the durable record of how a research topic evolved, and
        the single entry point for research-evolution work (it replaces the older
        one-shot timeline tools). It is stored with a monotonic revision number,
        so re-running it later produces revision N+1 and you can diff revisions
        to see exactly what changed.

        The primary axis is chronological; research branches are a secondary
        organizing dimension. Both come from the same stored snapshot, so
        `output="timeline"` and `output="tree"` can never disagree.

        Every entry carries:
        - a one-sentence claim with inline citations
        - supporting / contradicting / updating evidence articles
        - a research branch (lineage) assignment
        - provenance and a confidence score

        The typed provenance graph links Topic → Branch → Entry → EvidenceArticle
        and is validated against edge invariants. The audit reports evidence
        coverage, identifier coverage, branch coverage, graph integrity, and
        chronology gaps, so you always know how complete the picture is.

        Args:
            topic: Research topic (drug, gene, disease, intervention).
                   Required unless `pmids` is supplied.
            pmids: Comma-separated PMIDs, or "last" to chronicle the previous
                   search results instead of running a new search.
            max_events: Maximum timeline events to consider (topic mode).
            min_year: Earliest publication year to include (topic mode).
            max_year: Latest publication year to include (topic mode).
            chronicle_id: Continue an existing chronicle (creates revision N+1)
                          instead of deriving the ID from the topic.
            output: "summary" (default compact Markdown with the chronological
                    spine), "json", "chronicle_map", "timeline", "tree",
                    "graph", "evidence", "milestones", "mermaid" (horizontal
                    time spine with lineage branches), "timeline_mermaid"
                    (legacy flat timeline), "mindmap", or "narrative".

        Returns:
            The requested rendering plus an artifact locator when durable
            artifact persistence is enabled and succeeds. The artifact contains
            the full snapshot, projections, evidence table, milestone analysis,
            and audit regardless of `output`. Artifact failure is reported but
            does not roll back the already saved Chronicle revision.

        Examples:
            build_research_chronicle(topic="remimazolam")
            build_research_chronicle(pmids="last", topic="My Reading List")
            build_research_chronicle(topic="CAR-T therapy", output="mermaid")
        """
        if not isinstance(output, str):
            return ResponseFormatter.error(
                error="output must be a string",
                suggestion=f"Choose one of: {', '.join(BUILD_OUTPUTS)}",
                tool_name="build_research_chronicle",
            )
        if output not in BUILD_OUTPUTS:
            return ResponseFormatter.error(
                error=f"Unsupported output: {output!r}",
                suggestion=f"Choose one of: {', '.join(BUILD_OUTPUTS)}",
                tool_name="build_research_chronicle",
            )

        response_format = _build_response_format(output)
        for name, value, max_length in (
            ("topic", topic, 500),
            ("pmids", pmids, 10_000),
            ("chronicle_id", chronicle_id, 200),
        ):
            string_error = _optional_string_error(name, value, max_length=max_length)
            if string_error:
                return ResponseFormatter.error(
                    error=string_error,
                    suggestion="Pass text values exactly as documented by the tool schema",
                    tool_name="build_research_chronicle",
                    output_format=response_format,
                )
        topic = topic.strip() if topic else None
        if topic is not None and len(topic) > 500:
            return ResponseFormatter.error(
                error="topic must contain at most 500 characters",
                suggestion="Use a focused biomedical topic or a saved PMID set",
                tool_name="build_research_chronicle",
                output_format=response_format,
            )
        if isinstance(max_events, bool) or not isinstance(max_events, int) or not 1 <= max_events <= 200:
            return ResponseFormatter.error(
                error="max_events must be an integer between 1 and 200",
                suggestion="Use 30 for a compact Chronicle or up to 200 for broader coverage",
                tool_name="build_research_chronicle",
                output_format=response_format,
            )
        year_error = _validate_year_range(min_year, max_year)
        if year_error:
            return ResponseFormatter.error(
                error=year_error,
                suggestion="Use a valid chronological range without reversing its bounds",
                tool_name="build_research_chronicle",
                output_format=response_format,
            )
        id_error = _validate_chronicle_id(chronicle_id)
        if id_error:
            return ResponseFormatter.error(
                error=id_error,
                suggestion="Use the ID returned by build/list, or omit it to derive one safely",
                tool_name="build_research_chronicle",
                output_format=response_format,
            )

        try:
            pmid_list = list(dict.fromkeys(_resolve_pmids(pmids)))
        except ValueError as exc:
            return ResponseFormatter.error(
                error=str(exc),
                suggestion='Pass explicit PubMed IDs such as pmids="12345678,PMID:23456789"',
                tool_name="build_research_chronicle",
                output_format=response_format,
            )
        if pmids and not pmid_list:
            return ResponseFormatter.error(
                error="No usable PMIDs resolved",
                suggestion='Run a search first, or pass explicit PMIDs like pmids="12345678,23456789"',
                tool_name="build_research_chronicle",
                output_format=response_format,
            )
        if len(pmid_list) > _MAX_PMIDS:
            return ResponseFormatter.error(
                error=f"At most {_MAX_PMIDS} unique PMIDs can be chronicled at once",
                suggestion="Split the evidence set into narrower topics or smaller saved searches",
                tool_name="build_research_chronicle",
                output_format=response_format,
            )
        if not topic and not pmid_list:
            return ResponseFormatter.error(
                error="Must provide either 'topic' or 'pmids'",
                suggestion='Examples: topic="remimazolam" OR pmids="last"',
                tool_name="build_research_chronicle",
                output_format=response_format,
            )

        denied = durable_storage_denied("build_research_chronicle", output_format=response_format)
        if denied:
            return denied

        try:
            await safe_report_progress(ctx, 1, 3, "Retrieving chronicle evidence...")
            snapshot = await service().build(
                topic=topic,
                pmids=pmid_list or None,
                max_events=max_events,
                min_year=min_year,
                max_year=max_year,
                chronicle_id=chronicle_id,
            )
            await safe_log(
                ctx,
                "info",
                f"Chronicle {snapshot.chronicle_id} revision {snapshot.revision}: "
                f"{len(snapshot.entries)} entries, audit={snapshot.audit.status}",
                logger_name=__name__,
            )

            await safe_report_progress(ctx, 2, 3, "Rendering chronicle projection...")
            body = _render_output(snapshot, output)

            await safe_report_progress(ctx, 3, 3, "Persisting chronicle artifact...")
            persistence_expected = artifact_persistence_enabled()
            persistence_failed = False
            try:
                artifact = _persist_chronicle_artifact(
                    snapshot,
                    response_markdown=_markdown_response_body(body, output=output),
                )
                persistence_failed = persistence_expected and artifact is None
            except Exception:
                logger.exception("Chronicle revision saved, but artifact preparation or persistence failed")
                artifact = None
                persistence_failed = True
            return _with_artifact_note(
                body,
                artifact,
                output=output,
                persistence_failed=persistence_failed,
            )

        except ValueError as exc:
            return ResponseFormatter.error(
                error=str(exc),
                suggestion="Check the topic, PMIDs, and output format",
                tool_name="build_research_chronicle",
                output_format=response_format,
            )
        except Exception as exc:
            logger.exception("Chronicle build failed")
            return ResponseFormatter.error(
                error=str(exc),
                suggestion="Try a narrower topic or check network connectivity",
                tool_name="build_research_chronicle",
                output_format=response_format,
            )

    @mcp.tool()
    async def read_research_chronicle(
        action: ChronicleReadAction = "load",
        chronicle_id: ChronicleIdText | None = None,
        revision: PositiveRevision | None = None,
        from_revision: PositiveRevision | None = None,
        to_revision: PositiveRevision | None = None,
        topic: TopicText | None = None,
        topics: Annotated[str, Field(max_length=2500)] | None = None,
        chronicle_ids: Annotated[str, Field(max_length=1100)] | None = None,
        output: ChronicleOutput = "summary",
        mode: NarrativeMode = "brief",
        limit: ListLimit = 20,
        ctx: Context | None = None,
    ) -> str:
        """
        Read stored Research Chronicles: load, list, diff, narrate, analyze, compare.

        This is the read facade over chronicles created by
        `build_research_chronicle`. Chronicles persist across sessions, so you
        can revisit a topic weeks later and see precisely what moved. Because the
        evidence is already stored, analysis and comparison are instant and do
        not re-run any search.

        Actions:
        - "load": read one revision (defaults to latest) in any output format
        - "list": list stored chronicles, most recently updated first
        - "diff": compare two revisions — added, not observed/removed from the
          later view, and updated entries, plus evidence churn, branch churn,
          and the audit status transition. Absence does not prove retirement.
        - "narrate": render evidence-backed Markdown where every claim carries
          its entry ID and article identifiers
        - "milestones": entry-type and status distribution, per-year activity,
          evidence quality, and landmark entries for one chronicle
        - "compare": compare 2-5 chronicles side by side, including the evidence
          articles they share

        Args:
            action: "load", "list", "diff", "narrate", "milestones", or "compare".
            chronicle_id: Chronicle to read. Required for load/diff/narrate/milestones.
            revision: Revision to load/narrate/analyze. Defaults to the latest.
            from_revision: Earlier revision for "diff".
            to_revision: Later revision for "diff". Defaults to the latest.
            topic: Case-insensitive topic filter for "list".
            topics: Comma-separated topics for "compare" (resolved to chronicle
                    IDs; each topic must already have a chronicle).
            chronicle_ids: Comma-separated chronicle IDs for "compare".
            output: For "load": "summary", "json", "chronicle_map", "timeline",
                    "tree", "graph", "evidence", "milestones", "mermaid",
                    "timeline_mermaid", "mindmap", or "narrative".
            mode: For "narrate": "brief" (top claims per branch) or "full".
            limit: Maximum records returned by "list".

        Returns:
            Markdown or JSON text depending on the action and output format.

        Examples:
            read_research_chronicle(action="list")
            read_research_chronicle(chronicle_id="remimazolam-9f2b1c4d", output="tree")
            read_research_chronicle(action="diff", chronicle_id="remimazolam-9f2b1c4d", from_revision=1)
            read_research_chronicle(action="narrate", chronicle_id="remimazolam-9f2b1c4d", mode="full")
            read_research_chronicle(action="milestones", chronicle_id="remimazolam-9f2b1c4d")
            read_research_chronicle(action="compare", topics="remimazolam,propofol")
        """
        fallback_response_format = "json" if isinstance(output, str) and output == "json" else "markdown"
        if not isinstance(action, str):
            return ResponseFormatter.error(
                error="action must be a string",
                suggestion=f"Choose one of: {', '.join(READ_ACTIONS)}",
                tool_name="read_research_chronicle",
                output_format=fallback_response_format,
            )
        if not isinstance(output, str):
            return ResponseFormatter.error(
                error="output must be a string",
                suggestion=f"Choose one of: {', '.join(BUILD_OUTPUTS)}",
                tool_name="read_research_chronicle",
            )
        if action not in READ_ACTIONS:
            return ResponseFormatter.error(
                error=f"Unsupported action: {action!r}",
                suggestion=f"Choose one of: {', '.join(READ_ACTIONS)}",
                tool_name="read_research_chronicle",
                output_format=fallback_response_format,
            )

        response_format = _read_response_format(action, output)
        input_error_format = "json" if output == "json" else response_format
        for name, string_value, max_length in (
            ("chronicle_id", chronicle_id, 200),
            ("topic", topic, 500),
            ("topics", topics, 2_500),
            ("chronicle_ids", chronicle_ids, 1_100),
        ):
            string_error = _optional_string_error(name, string_value, max_length=max_length)
            if string_error:
                return ResponseFormatter.error(
                    error=string_error,
                    suggestion="Pass text values exactly as documented by the tool schema",
                    tool_name="read_research_chronicle",
                    output_format=input_error_format,
                )
        if not isinstance(mode, str):
            return ResponseFormatter.error(
                error="mode must be a string",
                suggestion="Choose 'brief' or 'full'",
                tool_name="read_research_chronicle",
                output_format=input_error_format,
            )
        if action == "load" and output not in BUILD_OUTPUTS:
            return ResponseFormatter.error(
                error=f"Unsupported output: {output!r}",
                suggestion=f"Choose one of: {', '.join(BUILD_OUTPUTS)}",
                tool_name="read_research_chronicle",
            )
        if action == "narrate" and mode not in {"brief", "full"}:
            return ResponseFormatter.error(
                error=f"Unsupported narrative mode: {mode!r}",
                suggestion="Choose 'brief' or 'full'",
                tool_name="read_research_chronicle",
            )
        if action == "list" and (isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100):
            return ResponseFormatter.error(
                error="limit must be an integer between 1 and 100",
                suggestion="Use limit=20 for the default Chronicle index page",
                tool_name="read_research_chronicle",
                output_format=response_format,
            )
        for label, revision_value in (
            ("revision", revision),
            ("from_revision", from_revision),
            ("to_revision", to_revision),
        ):
            if revision_value is not None and (
                isinstance(revision_value, bool) or not isinstance(revision_value, int) or revision_value < 1
            ):
                return ResponseFormatter.error(
                    error=f"{label} must be a positive integer",
                    suggestion="List the Chronicle first to inspect its available revisions",
                    tool_name="read_research_chronicle",
                    output_format=response_format,
                )
        id_error = _validate_chronicle_id(chronicle_id)
        if id_error:
            return ResponseFormatter.error(
                error=id_error,
                suggestion="Use a Chronicle ID returned by action='list'",
                tool_name="read_research_chronicle",
                output_format=response_format,
            )

        denied = durable_storage_denied("read_research_chronicle", output_format=response_format)
        if denied:
            return denied

        chronicle_service = service()
        try:
            if action == "list":
                records = await asyncio.to_thread(
                    chronicle_service.list_chronicles,
                    topic=topic.strip() if topic else None,
                    limit=limit,
                )
                if not records:
                    return json.dumps({"total": 0, "chronicles": []}, indent=2, ensure_ascii=False)
                return json.dumps({"total": len(records), "chronicles": records}, indent=2, ensure_ascii=False)

            if action == "compare":
                requested_ids = _split_csv(chronicle_ids)
                requested_topics = _split_csv(topics)
                if requested_ids and requested_topics:
                    return ResponseFormatter.error(
                        error="Pass either 'topics' or 'chronicle_ids', not both",
                        suggestion="Use topics for exact stored-topic lookup, or IDs from action='list'",
                        tool_name="read_research_chronicle",
                        output_format=response_format,
                    )
                raw_requested = requested_topics or requested_ids
                if len(raw_requested) < 2:
                    return ResponseFormatter.error(
                        error="Need at least 2 chronicles to compare, and they must be distinct",
                        suggestion='Pass topics="a,b" or chronicle_ids="id1,id2"',
                        tool_name="read_research_chronicle",
                        output_format=response_format,
                    )
                if len(raw_requested) > _MAX_COMPARE:
                    return ResponseFormatter.error(
                        error=f"Maximum {_MAX_COMPARE} chronicles for comparison",
                        suggestion="Compare fewer topics at a time",
                        tool_name="read_research_chronicle",
                        output_format=response_format,
                    )
                requested: list[str] = []
                if requested_topics:
                    match_sets = await asyncio.gather(
                        *(
                            asyncio.to_thread(chronicle_service.find_chronicle_ids_by_topic, requested_topic)
                            for requested_topic in requested_topics
                        )
                    )
                    for requested_topic, matches in zip(requested_topics, match_sets, strict=True):
                        if not matches:
                            return ResponseFormatter.error(
                                error=f"No stored chronicle for exact topic: {requested_topic}",
                                suggestion="Use action='list' to inspect stored topic names, or build it first",
                                tool_name="read_research_chronicle",
                                output_format=response_format,
                            )
                        if len(matches) > 1:
                            return ResponseFormatter.error(
                                error=f"Topic is ambiguous: {requested_topic}",
                                suggestion=f"Pass one of these chronicle IDs explicitly: {', '.join(matches)}",
                                tool_name="read_research_chronicle",
                                output_format=response_format,
                            )
                        requested.append(matches[0])
                else:
                    requested = requested_ids
                    for requested_id in requested:
                        compare_id_error = _validate_chronicle_id(requested_id)
                        if compare_id_error:
                            return ResponseFormatter.error(
                                error=f"Invalid comparison ID {requested_id!r}: {compare_id_error}",
                                suggestion="Use Chronicle IDs returned by action='list'",
                                tool_name="read_research_chronicle",
                                output_format=response_format,
                            )
                requested = list(dict.fromkeys(requested))
                if len(requested) < 2:
                    return ResponseFormatter.error(
                        error="Need at least 2 chronicles to compare, and they must be distinct",
                        suggestion='Pass topics="a,b" or chronicle_ids="id1,id2"',
                        tool_name="read_research_chronicle",
                        output_format=response_format,
                    )
                comparison = await asyncio.to_thread(chronicle_service.compare, requested)
                return json.dumps(comparison, indent=2, ensure_ascii=False)

            if not chronicle_id:
                return ResponseFormatter.error(
                    error="chronicle_id is required for this action",
                    suggestion='List stored chronicles first: read_research_chronicle(action="list")',
                    tool_name="read_research_chronicle",
                    output_format=response_format,
                )

            if action == "diff":
                if from_revision is None:
                    return ResponseFormatter.error(
                        error="from_revision is required for action='diff'",
                        suggestion="Pass the earlier revision number, e.g. from_revision=1",
                        tool_name="read_research_chronicle",
                        output_format=response_format,
                    )
                delta = await asyncio.to_thread(chronicle_service.diff, chronicle_id, from_revision, to_revision)
                return json.dumps(delta, indent=2, ensure_ascii=False)

            snapshot = await asyncio.to_thread(chronicle_service.load, chronicle_id, revision)
            if snapshot is None:
                revisions = await asyncio.to_thread(chronicle_service.list_revisions, chronicle_id)
                return ResponseFormatter.error(
                    error=f"Chronicle revision not found: {chronicle_id} rev {revision or 'latest'}",
                    suggestion=f"Stored revisions: {revisions}" if revisions else "Build the chronicle first",
                    tool_name="read_research_chronicle",
                    output_format=response_format,
                )

            await safe_log(
                ctx,
                "info",
                f"Loaded chronicle {chronicle_id} revision {snapshot.revision}",
                logger_name=__name__,
            )
            if action == "narrate":
                return chronicle_service.narrate(snapshot, mode=mode)
            if action == "milestones":
                return _render_output(snapshot, "milestones")
            return _markdown_response_body(_render_output(snapshot, output), output=output)

        except ValueError as exc:
            return ResponseFormatter.error(
                error=str(exc),
                suggestion="Check the chronicle ID and revision numbers",
                tool_name="read_research_chronicle",
                output_format=response_format,
            )
        except Exception as exc:
            logger.exception("Chronicle read failed")
            return ResponseFormatter.error(
                error=str(exc),
                suggestion="Verify the chronicle store is writable",
                tool_name="read_research_chronicle",
                output_format=response_format,
            )

    _forbid_extra_tool_arguments(
        mcp,
        "build_research_chronicle",
        "read_research_chronicle",
    )
    logger.info("Registered 2 research chronicle tools")


__all__ = ["BUILD_OUTPUTS", "READ_ACTIONS", "register_chronicle_tools"]
