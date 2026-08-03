"""Chronicle application service.

This is the single orchestration point for building, updating, reading, and
comparing research chronicles. MCP tools stay thin wrappers over these methods.

The service depends on a narrow :class:`ChronicleEvidenceProvider` port rather
than the concrete timeline builder, so evidence retrieval can be swapped or
faked in tests without touching chronicle logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from pubmed_search.application.timeline import build_research_tree
from pubmed_search.domain.entities.chronicle import ChronicleInputScope, ChronicleSnapshot

from .analytics import analyze_milestones, compare_chronicles
from .assembler import assemble_chronicle, derive_chronicle_id
from .audit import audit_chronicle
from .differ import diff_chronicles
from .narrator import narrate_chronicle
from .projectors import (
    project_evidence,
    project_graph,
    project_lineage_tree,
    project_timeline,
    render_lineage_mindmap,
    render_timeline_mermaid,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from pubmed_search.domain.entities.timeline import ResearchTimeline

    from .store import ChronicleStore

#: File names written for every persisted chronicle revision.
CHRONICLE_ARTIFACT_FILES = (
    "snapshot.json",
    "timeline.json",
    "lineage_tree.json",
    "graph.json",
    "evidence.json",
    "milestones.json",
    "audit.json",
)

#: Recommended order for an agent reading a chronicle artifact.
CHRONICLE_READ_ORDER = ("audit.json", "snapshot.json", "timeline.json", "lineage_tree.json", "evidence.json")


class ChronicleEvidenceProvider(Protocol):
    """Retrieval port supplying timeline evidence for chronicle assembly."""

    async def build_timeline(
        self,
        topic: str,
        max_events: int = 50,
        include_all: bool = False,
        min_year: int | None = None,
        max_year: int | None = None,
        sort_by_citations: bool = True,
        auto_periods: bool = True,
        highlight_landmarks: bool = True,
        source_counts: dict[str, int] | None = None,
    ) -> ResearchTimeline:
        """Build a timeline by searching for *topic*."""
        ...

    async def build_timeline_from_pmids(
        self,
        pmids: list[str],
        topic: str = "Custom Timeline",
        auto_periods: bool = True,
    ) -> ResearchTimeline:
        """Build a timeline from an explicit PMID list."""
        ...


class ChronicleService:
    """Build, persist, and read versioned research chronicles."""

    def __init__(self, evidence_provider: ChronicleEvidenceProvider, store: ChronicleStore) -> None:
        """Wire the service to its retrieval port and revision store.

        Args:
            evidence_provider: Supplies timelines for topics or PMID lists.
            store: Persists and reads chronicle revisions.
        """
        self._evidence = evidence_provider
        self._store = store

    async def build(
        self,
        *,
        topic: str | None = None,
        pmids: list[str] | None = None,
        max_events: int = 30,
        min_year: int | None = None,
        max_year: int | None = None,
        chronicle_id: str | None = None,
        source_artifact_uris: list[str] | None = None,
        pipeline_run_ids: list[str] | None = None,
    ) -> ChronicleSnapshot:
        """Build a new chronicle revision and persist it.

        When a chronicle already exists for the topic (or *chronicle_id* is
        given), the new snapshot becomes ``latest_revision + 1`` and inherits the
        original creation timestamp.

        Args:
            topic: Research topic. Required unless *pmids* is supplied.
            pmids: Explicit PMIDs to chronicle instead of running a search.
            max_events: Maximum timeline events to consider (topic mode).
            min_year: Earliest publication year to include (topic mode).
            max_year: Latest publication year to include (topic mode).
            chronicle_id: Continue an existing chronicle instead of deriving one.
            source_artifact_uris: Upstream artifacts feeding this revision.
            pipeline_run_ids: Pipeline runs feeding this revision.

        Returns:
            The persisted :class:`ChronicleSnapshot`, audit included.

        Raises:
            ValueError: If neither *topic* nor *pmids* is provided.
        """
        if not topic and not pmids:
            msg = "Provide either 'topic' or 'pmids' to build a chronicle."
            raise ValueError(msg)

        resolved_topic = topic or "Custom Chronicle"
        if pmids:
            timeline = await self._evidence.build_timeline_from_pmids(pmids=pmids, topic=resolved_topic)
            mode = "pmids"
        else:
            timeline = await self._evidence.build_timeline(
                topic=resolved_topic,
                max_events=max_events,
                min_year=min_year,
                max_year=max_year,
            )
            mode = "topic"

        scope = ChronicleInputScope(
            mode=mode,
            query=resolved_topic,
            pmids=list(pmids or []),
            source_artifact_uris=list(source_artifact_uris or []),
            pipeline_run_ids=list(pipeline_run_ids or []),
            filters={"max_events": max_events, "min_year": min_year, "max_year": max_year},
            source_counts=self._extract_source_counts(timeline),
        )

        resolved_id = chronicle_id or derive_chronicle_id(resolved_topic)
        previous = self._store.load(resolved_id)
        revision = (previous.revision + 1) if previous else 1

        snapshot = assemble_chronicle(
            topic=resolved_topic,
            timeline=timeline,
            tree=build_research_tree(timeline) if timeline.events else None,
            scope=scope,
            chronicle_id=resolved_id,
            revision=revision,
            created_at=previous.created_at if previous else None,
        )
        snapshot.audit = audit_chronicle(snapshot, artifact_files=self.artifact_file_names())
        self._store.save(snapshot)
        return snapshot

    def load(self, chronicle_id: str, revision: int | None = None) -> ChronicleSnapshot | None:
        """Load one chronicle revision, defaulting to the latest."""
        return self._store.load(chronicle_id, revision)

    def list_chronicles(self, *, topic: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """List stored chronicles, most recently updated first."""
        return self._store.list_chronicles(topic=topic, limit=limit)

    def list_revisions(self, chronicle_id: str) -> list[int]:
        """List every stored revision number for *chronicle_id*."""
        return self._store.list_revisions(chronicle_id)

    def diff(self, chronicle_id: str, from_revision: int, to_revision: int | None = None) -> dict[str, Any]:
        """Compare two revisions of one chronicle.

        Args:
            chronicle_id: Chronicle to compare.
            from_revision: Earlier revision number.
            to_revision: Later revision number, or ``None`` for the latest.

        Returns:
            The delta report from :func:`diff_chronicles`.

        Raises:
            ValueError: If either revision cannot be loaded.
        """
        before = self._store.load(chronicle_id, from_revision)
        after = self._store.load(chronicle_id, to_revision)
        if before is None:
            msg = f"Revision {from_revision} not found for chronicle {chronicle_id}"
            raise ValueError(msg)
        if after is None:
            msg = f"Revision {to_revision or 'latest'} not found for chronicle {chronicle_id}"
            raise ValueError(msg)
        return diff_chronicles(before, after)

    def narrate(self, snapshot: ChronicleSnapshot, *, mode: str = "brief") -> str:
        """Render *snapshot* as evidence-backed Markdown."""
        return narrate_chronicle(snapshot, mode=mode)

    def compare(self, chronicle_ids: Sequence[str]) -> dict[str, Any]:
        """Compare the latest revision of several stored chronicles.

        Args:
            chronicle_ids: Two or more chronicle identifiers.

        Returns:
            The comparison report from :func:`compare_chronicles`.

        Raises:
            ValueError: If fewer than two IDs are given or any is not stored.
        """
        snapshots: list[ChronicleSnapshot] = []
        missing: list[str] = []
        for chronicle_id in chronicle_ids:
            snapshot = self._store.load(chronicle_id)
            if snapshot is None:
                missing.append(chronicle_id)
            else:
                snapshots.append(snapshot)

        if missing:
            msg = f"No stored chronicle for: {', '.join(missing)}. Build each topic first."
            raise ValueError(msg)
        return compare_chronicles(snapshots)

    @staticmethod
    def artifact_file_names() -> list[str]:
        """Return the file names a persisted chronicle artifact must contain."""
        return ["manifest.json", *CHRONICLE_ARTIFACT_FILES]

    @staticmethod
    def build_artifact_files(snapshot: ChronicleSnapshot, *, narrative: str | None = None) -> dict[str, Any]:
        """Build the artifact payload for one chronicle revision.

        Args:
            snapshot: The revision to serialize.
            narrative: Optional narrative Markdown to include as ``narrative.md``.

        Returns:
            A mapping of file name to content, ready for the artifact store.
        """
        files: dict[str, Any] = {
            "snapshot.json": snapshot.to_dict(),
            "timeline.json": project_timeline(snapshot),
            "lineage_tree.json": project_lineage_tree(snapshot),
            "graph.json": project_graph(snapshot),
            "evidence.json": project_evidence(snapshot),
            "milestones.json": analyze_milestones(snapshot),
            "audit.json": snapshot.audit.to_dict(),
        }
        if narrative:
            files["narrative.md"] = narrative
        return files

    @staticmethod
    def render(snapshot: ChronicleSnapshot, output_format: str) -> dict[str, Any] | str:
        """Render a chronicle projection in the requested format.

        Args:
            snapshot: The revision to render.
            output_format: One of ``json``, ``timeline``, ``tree``, ``graph``,
                ``evidence``, ``mermaid``, ``mindmap``, or ``narrative``.

        Returns:
            A dict for JSON projections, or a string for text renderings.

        Raises:
            ValueError: If *output_format* is not supported.
        """
        renderers: dict[str, Callable[[], dict[str, Any] | str]] = {
            "json": snapshot.to_dict,
            "timeline": lambda: project_timeline(snapshot),
            "tree": lambda: project_lineage_tree(snapshot),
            "graph": lambda: project_graph(snapshot),
            "evidence": lambda: project_evidence(snapshot),
            "milestones": lambda: analyze_milestones(snapshot),
            "mermaid": lambda: render_timeline_mermaid(snapshot),
            "mindmap": lambda: render_lineage_mindmap(snapshot),
            "narrative": lambda: narrate_chronicle(snapshot, mode="full"),
        }
        renderer = renderers.get(output_format)
        if renderer is None:
            msg = f"Unsupported chronicle output format: {output_format!r}. Choose one of {sorted(renderers)}."
            raise ValueError(msg)
        return renderer()

    @staticmethod
    def _extract_source_counts(timeline: ResearchTimeline) -> dict[str, Any]:
        """Pull per-source retrieval counts out of timeline metadata."""
        metadata = timeline.metadata if isinstance(timeline.metadata, dict) else {}
        counts = metadata.get("source_counts")
        return dict(counts) if isinstance(counts, dict) else {}


__all__ = [
    "CHRONICLE_ARTIFACT_FILES",
    "CHRONICLE_READ_ORDER",
    "ChronicleEvidenceProvider",
    "ChronicleService",
]
