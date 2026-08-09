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

import json
import logging
from typing import TYPE_CHECKING, Any, Literal

from mcp.server.mcpserver import Context  # noqa: TC002 - MCPServer needs runtime access for tool context injection

from pubmed_search.application.chronicle import (
    CHRONICLE_READ_ORDER,
    ChronicleService,
    ChronicleStore,
    derive_chronicle_id,
    narrate_chronicle,
)
from pubmed_search.application.timeline import LandmarkScorer, MilestoneDetector, TimelineBuilder
from pubmed_search.presentation.mcp_server.tenancy import durable_storage_denied
from pubmed_search.shared.settings import DEFAULT_DATA_DIR

from ._common import InputNormalizer, ResponseFormatter, get_last_search_pmids, get_session_manager
from .artifact_memory import artifact_markdown_note, persist_tool_artifact
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
    "timeline",
    "tree",
    "graph",
    "evidence",
    "milestones",
    "mermaid",
    "mindmap",
    "narrative",
)

#: Read actions accepted by ``read_research_chronicle``.
READ_ACTIONS = ("load", "list", "diff", "narrate", "milestones", "compare")

#: How many spine entries the default summary shows.
_SPINE_LIMIT = 12

#: Maximum topics/chronicles accepted by ``action="compare"``.
_MAX_COMPARE = 5


def _chronicle_store() -> ChronicleStore:
    """Return the chronicle revision store for the tenant of the current request.

    Callers that cannot own durable storage are turned away by
    ``durable_storage_denied`` before reaching here, so the root is never None.
    """
    manager = get_session_manager()
    root = getattr(manager, "data_dir", None) or DEFAULT_DATA_DIR
    return ChronicleStore(f"{root}/chronicles")


def _resolve_pmids(pmids: str | None) -> list[str]:
    """Normalize a PMID argument, resolving the ``last`` sentinel via session."""
    normalized = InputNormalizer.normalize_pmids(pmids)
    if normalized == ["last"]:
        return get_last_search_pmids()
    return normalized


def _split_csv(value: str | None) -> list[str]:
    """Split a comma-separated argument into trimmed, non-empty parts."""
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _format_summary(snapshot: ChronicleSnapshot) -> str:
    """Render the compact Markdown index card for a chronicle revision."""
    year_range = snapshot.year_range
    span = f"{year_range[0]}\u2013{year_range[1]}" if year_range else "n/a"
    lines = [
        f"# Research Chronicle: {snapshot.topic}",
        "",
        f"- Chronicle ID: `{snapshot.chronicle_id}`",
        f"- Revision: {snapshot.revision} (mode: {snapshot.input_scope.mode})",
        f"- Entries: {len(snapshot.entries)} across {len(snapshot.branches)} branches",
        f"- Evidence articles: {len(snapshot.evidence_articles)}",
        f"- Year span: {span}",
        f"- Graph: {len(snapshot.graph.nodes)} nodes, {len(snapshot.graph.edges)} edges",
        f"- Audit: **{snapshot.audit.status}**",
        "",
    ]

    spine = sorted(snapshot.entries, key=lambda entry: (entry.year or 0, entry.entry_id))
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

    highlights = sorted(snapshot.entries, key=lambda entry: -entry.confidence)[:5]
    if highlights:
        lines.append("## Highest-confidence Claims")
        lines.append("")
        for entry in highlights:
            citations = ", ".join(a.evidence_id for a in entry.evidence.all_articles) or "no evidence"
            lines.append(f"- {entry.summary_claim} `[{entry.entry_id}; {citations}]`")
        lines.append("")

    if snapshot.audit.warnings:
        lines.append("## Completeness Caveats")
        lines.append("")
        lines.extend(f"- {warning}" for warning in snapshot.audit.warnings)
        lines.append("")

    lines.append(
        f'Next: `read_research_chronicle(action="narrate", chronicle_id="{snapshot.chronicle_id}")` '
        f'or `read_research_chronicle(action="diff", chronicle_id="{snapshot.chronicle_id}", from_revision=1)`'
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


def _persist_chronicle_artifact(snapshot: ChronicleSnapshot, *, response_markdown: str) -> dict[str, Any] | None:
    """Persist the full chronicle revision as a session artifact."""
    files = ChronicleService.build_artifact_files(snapshot, narrative=narrate_chronicle(snapshot, mode="full"))
    files["response.md"] = response_markdown
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
        topic: str | None = None,
        pmids: str | None = None,
        max_events: int = 30,
        min_year: int | None = None,
        max_year: int | None = None,
        chronicle_id: str | None = None,
        output: str = "summary",
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
                    spine), "json", "timeline", "tree", "graph", "evidence",
                    "milestones", "mermaid", "mindmap", or "narrative".

        Returns:
            The requested rendering plus a persistent artifact locator. The full
            snapshot, projections, evidence table, milestone analysis, and audit
            are always written to the artifact regardless of `output`.

        Examples:
            build_research_chronicle(topic="remimazolam")
            build_research_chronicle(pmids="last", topic="My Reading List")
            build_research_chronicle(topic="CAR-T therapy", output="narrative")
        """
        if output not in BUILD_OUTPUTS:
            return ResponseFormatter.error(
                error=f"Unsupported output: {output!r}",
                suggestion=f"Choose one of: {', '.join(BUILD_OUTPUTS)}",
                tool_name="build_research_chronicle",
            )

        denied = durable_storage_denied("build_research_chronicle")
        if denied:
            return denied

        pmid_list = _resolve_pmids(pmids)
        if pmids and not pmid_list:
            return ResponseFormatter.error(
                error="No usable PMIDs resolved",
                suggestion='Run a search first, or pass explicit PMIDs like pmids="12345678,23456789"',
                tool_name="build_research_chronicle",
            )
        if not topic and not pmid_list:
            return ResponseFormatter.error(
                error="Must provide either 'topic' or 'pmids'",
                suggestion='Examples: topic="remimazolam" OR pmids="last"',
                tool_name="build_research_chronicle",
            )

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
            artifact = _persist_chronicle_artifact(snapshot, response_markdown=body)
            return body + artifact_markdown_note(artifact)

        except ValueError as exc:
            return ResponseFormatter.error(
                error=str(exc),
                suggestion="Check the topic, PMIDs, and output format",
                tool_name="build_research_chronicle",
            )
        except Exception as exc:
            logger.exception("Chronicle build failed")
            return ResponseFormatter.error(
                error=str(exc),
                suggestion="Try a narrower topic or check network connectivity",
                tool_name="build_research_chronicle",
            )

    @mcp.tool()
    async def read_research_chronicle(
        action: Literal["load", "list", "diff", "narrate", "milestones", "compare"] = "load",
        chronicle_id: str | None = None,
        revision: int | None = None,
        from_revision: int | None = None,
        to_revision: int | None = None,
        topic: str | None = None,
        topics: str | None = None,
        chronicle_ids: str | None = None,
        output: str = "summary",
        mode: str = "brief",
        limit: int = 20,
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
        - "diff": compare two revisions — added, retired, and updated entries,
          evidence churn, branch churn, and the audit status transition
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
            output: For "load": "summary", "json", "timeline", "tree", "graph",
                    "evidence", "milestones", "mermaid", "mindmap", or "narrative".
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
        if action not in READ_ACTIONS:
            return ResponseFormatter.error(
                error=f"Unsupported action: {action!r}",
                suggestion=f"Choose one of: {', '.join(READ_ACTIONS)}",
                tool_name="read_research_chronicle",
            )

        denied = durable_storage_denied("read_research_chronicle")
        if denied:
            return denied

        try:
            if action == "list":
                records = service().list_chronicles(topic=topic, limit=limit)
                if not records:
                    return ResponseFormatter.no_results(
                        query=topic or "all chronicles",
                        suggestions=['Build one first: build_research_chronicle(topic="...")'],
                    )
                return json.dumps({"total": len(records), "chronicles": records}, indent=2, ensure_ascii=False)

            if action == "compare":
                requested = _split_csv(chronicle_ids) or [derive_chronicle_id(value) for value in _split_csv(topics)]
                if len(requested) < 2:
                    return ResponseFormatter.error(
                        error="Need at least 2 chronicles to compare",
                        suggestion='Pass topics="a,b" or chronicle_ids="id1,id2"',
                        tool_name="read_research_chronicle",
                    )
                if len(requested) > _MAX_COMPARE:
                    return ResponseFormatter.error(
                        error=f"Maximum {_MAX_COMPARE} chronicles for comparison",
                        suggestion="Compare fewer topics at a time",
                        tool_name="read_research_chronicle",
                    )
                return json.dumps(service().compare(requested), indent=2, ensure_ascii=False)

            if not chronicle_id:
                return ResponseFormatter.error(
                    error="chronicle_id is required for this action",
                    suggestion='List stored chronicles first: read_research_chronicle(action="list")',
                    tool_name="read_research_chronicle",
                )

            if action == "diff":
                if from_revision is None:
                    return ResponseFormatter.error(
                        error="from_revision is required for action='diff'",
                        suggestion="Pass the earlier revision number, e.g. from_revision=1",
                        tool_name="read_research_chronicle",
                    )
                delta = service().diff(chronicle_id, from_revision, to_revision)
                return json.dumps(delta, indent=2, ensure_ascii=False)

            snapshot = service().load(chronicle_id, revision)
            if snapshot is None:
                revisions = service().list_revisions(chronicle_id)
                return ResponseFormatter.error(
                    error=f"Chronicle revision not found: {chronicle_id} rev {revision or 'latest'}",
                    suggestion=f"Stored revisions: {revisions}" if revisions else "Build the chronicle first",
                    tool_name="read_research_chronicle",
                )

            await safe_log(
                ctx,
                "info",
                f"Loaded chronicle {chronicle_id} revision {snapshot.revision}",
                logger_name=__name__,
            )
            if action == "narrate":
                return service().narrate(snapshot, mode=mode)
            if action == "milestones":
                return _render_output(snapshot, "milestones")
            if output not in BUILD_OUTPUTS:
                return ResponseFormatter.error(
                    error=f"Unsupported output: {output!r}",
                    suggestion=f"Choose one of: {', '.join(BUILD_OUTPUTS)}",
                    tool_name="read_research_chronicle",
                )
            return _render_output(snapshot, output)

        except ValueError as exc:
            return ResponseFormatter.error(
                error=str(exc),
                suggestion="Check the chronicle ID and revision numbers",
                tool_name="read_research_chronicle",
            )
        except Exception as exc:
            logger.exception("Chronicle read failed")
            return ResponseFormatter.error(
                error=str(exc),
                suggestion="Verify the chronicle store is writable",
                tool_name="read_research_chronicle",
            )

    logger.info("Registered 2 research chronicle tools")


__all__ = ["BUILD_OUTPUTS", "READ_ACTIONS", "register_chronicle_tools"]
