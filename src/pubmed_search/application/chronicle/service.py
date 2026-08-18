"""Chronicle application service.

This is the single orchestration point for building, updating, reading, and
comparing research chronicles. MCP tools stay thin wrappers over these methods.

The service depends on a narrow :class:`ChronicleEvidenceProvider` port rather
than the concrete timeline builder, so evidence retrieval can be swapped or
faked in tests without touching chronicle logic.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol

from pubmed_search.domain.entities.chronicle import ChronicleInputScope, ChronicleSnapshot

from .analytics import analyze_milestones, compare_chronicles
from .assembler import assemble_chronicle, canonical_topic_key, derive_chronicle_id
from .audit import audit_chronicle
from .differ import diff_chronicles
from .lineage import build_chronicle_lineage
from .narrator import narrate_chronicle
from .projectors import (
    project_chronicle_map,
    project_evidence,
    project_graph,
    project_lineage_tree,
    project_timeline,
    render_chronicle_mermaid_result,
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
    "chronicle_map.json",
    "chronicle.mmd",
    "mermaid_validation.json",
    "timeline.json",
    "lineage_tree.json",
    "graph.json",
    "evidence.json",
    "milestones.json",
    "audit.json",
)

#: Recommended order for an agent reading a chronicle artifact.
CHRONICLE_READ_ORDER = (
    "audit.json",
    "snapshot.json",
    "chronicle_map.json",
    "chronicle.mmd",
    "mermaid_validation.json",
    "timeline.json",
    "lineage_tree.json",
    "evidence.json",
)

_MAX_TOPIC_CHARS = 500
_MAX_CHRONICLE_PMIDS = 500
_MAX_CHRONICLE_EVENTS = 200
_MAX_PMID_DIGITS = 20

#: Timeline events considered when the caller does not specify a bound.
DEFAULT_CHRONICLE_EVENTS = 30


def _inherit_filter(requested: int | None, stored: Any, low: int, high: int) -> int | None:
    """Resolve one retrieval filter, keeping a stored value only if still in range.

    Stored filters are read back from disk, so an out-of-range value is dropped
    rather than raising: the caller asked to continue, not to supply that bound.
    """
    if requested is not None:
        return requested
    if isinstance(stored, int) and not isinstance(stored, bool) and low <= stored <= high:
        return stored
    return None


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
        max_events: int | None = None,
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

        Passing only *chronicle_id* re-runs the stored revision's own scope, so
        a later diff reflects research movement rather than a silently reset
        retrieval window.

        Args:
            topic: Research topic. Required unless *pmids* or a stored
                *chronicle_id* is supplied.
            pmids: Explicit PMIDs to chronicle instead of running a search.
            max_events: Maximum timeline events to consider (topic mode).
                ``None`` inherits the continued revision's value, else
                :data:`DEFAULT_CHRONICLE_EVENTS`.
            min_year: Earliest publication year to include (topic mode).
            max_year: Latest publication year to include (topic mode).
            chronicle_id: Continue an existing chronicle instead of deriving one.
            source_artifact_uris: Upstream artifacts feeding this revision.
            pipeline_run_ids: Pipeline runs feeding this revision.

        Returns:
            The persisted :class:`ChronicleSnapshot`, audit included.

        Raises:
            ValueError: If no topic, PMIDs, or stored chronicle can be resolved.
        """
        if topic is not None and not isinstance(topic, str):
            raise ValueError("topic must be a string")
        if chronicle_id is not None and not isinstance(chronicle_id, str):
            raise ValueError("chronicle_id must be a string")
        provided_topic = topic.strip() if topic and topic.strip() else None
        if provided_topic is not None and len(provided_topic) > _MAX_TOPIC_CHARS:
            raise ValueError(f"topic must contain at most {_MAX_TOPIC_CHARS} characters")
        if max_events is not None and (
            isinstance(max_events, bool)
            or not isinstance(max_events, int)
            or not 1 <= max_events <= _MAX_CHRONICLE_EVENTS
        ):
            raise ValueError(f"max_events must be an integer between 1 and {_MAX_CHRONICLE_EVENTS}")
        latest_year = datetime.now(timezone.utc).year + 1
        for label, year in (("min_year", min_year), ("max_year", max_year)):
            if year is not None and (
                isinstance(year, bool) or not isinstance(year, int) or not 1000 <= year <= latest_year
            ):
                raise ValueError(f"{label} must be an integer between 1000 and {latest_year}")

        if pmids is not None and not isinstance(pmids, list):
            raise ValueError("pmids must be a list of PubMed ID strings")
        raw_pmids = list(pmids or [])
        invalid_pmids = [
            pmid
            for pmid in raw_pmids
            if not isinstance(pmid, str)
            or not pmid.strip().isascii()
            or not pmid.strip().isdigit()
            or len(pmid.strip()) > _MAX_PMID_DIGITS
            or not pmid.strip().lstrip("0")
        ]
        if invalid_pmids:
            preview = ", ".join(repr(value) for value in invalid_pmids[:5])
            raise ValueError(f"pmids must contain positive ASCII-digit PubMed IDs; invalid values: {preview}")
        normalized_pmids = sorted({pmid.strip().lstrip("0") for pmid in raw_pmids})
        if len(normalized_pmids) > _MAX_CHRONICLE_PMIDS:
            raise ValueError(f"At most {_MAX_CHRONICLE_PMIDS} unique PMIDs can be chronicled at once")

        existing_hint = await asyncio.to_thread(self._store.load, chronicle_id) if chronicle_id else None
        inherited: dict[str, Any] = {}
        if provided_topic is None and not normalized_pmids:
            if existing_hint is None:
                if chronicle_id:
                    msg = f"Chronicle '{chronicle_id}' not found. Provide 'topic' or 'pmids' to create a new chronicle."
                else:
                    msg = "Provide either 'topic', 'pmids', or an existing 'chronicle_id' to build a chronicle."
                raise ValueError(msg)
            if existing_hint.input_scope.mode == "pmids" and existing_hint.input_scope.pmids:
                normalized_pmids = sorted(set(existing_hint.input_scope.pmids))
                resolved_topic = existing_hint.topic
            else:
                resolved_topic = existing_hint.input_scope.query or existing_hint.topic
                provided_topic = resolved_topic
            inherited = existing_hint.input_scope.filters
        else:
            resolved_topic = provided_topic or (existing_hint.topic if existing_hint else "Custom Chronicle")

        max_events = _inherit_filter(max_events, inherited.get("max_events"), 1, _MAX_CHRONICLE_EVENTS)
        min_year = _inherit_filter(min_year, inherited.get("min_year"), 1000, latest_year)
        max_year = _inherit_filter(max_year, inherited.get("max_year"), 1000, latest_year)
        if max_events is None:
            max_events = DEFAULT_CHRONICLE_EVENTS
        if min_year is not None and max_year is not None and min_year > max_year:
            raise ValueError("min_year cannot be later than max_year")

        if normalized_pmids:
            timeline = await self._evidence.build_timeline_from_pmids(
                pmids=normalized_pmids,
                topic=resolved_topic,
            )
            mode = "pmids"
        else:
            timeline = await self._evidence.build_timeline(
                topic=resolved_topic,
                max_events=max_events,
                include_all=True,
                min_year=min_year,
                max_year=max_year,
            )
            mode = "topic"

        if not timeline.events:
            scope_label = f"the {len(normalized_pmids)} requested PMIDs" if normalized_pmids else repr(resolved_topic)
            msg = (
                f"No PubMed article evidence was retrieved for {scope_label}; "
                "no Chronicle revision was saved. Check the identifiers, broaden the topic, or adjust the year range."
            )
            raise ValueError(msg)

        scope = ChronicleInputScope(
            mode=mode,
            query=resolved_topic,
            pmids=normalized_pmids,
            source_artifact_uris=list(source_artifact_uris or []),
            pipeline_run_ids=list(pipeline_run_ids or []),
            filters={"max_events": max_events, "min_year": min_year, "max_year": max_year},
            source_counts=self._extract_source_counts(timeline),
        )

        if chronicle_id:
            resolved_id = chronicle_id
        elif provided_topic is None:
            pmid_scope_key = f"pmids:{','.join(normalized_pmids)}"
            resolved_id = derive_chronicle_id(resolved_topic, scope_key=pmid_scope_key)
        else:
            existing_ids = await asyncio.to_thread(self._store.find_chronicle_ids_by_topic, resolved_topic)
            if len(existing_ids) > 1:
                msg = (
                    f"Multiple stored chronicles match topic {resolved_topic!r}: {', '.join(existing_ids)}. "
                    "Pass chronicle_id explicitly to choose which history to continue."
                )
                raise ValueError(msg)
            resolved_id = existing_ids[0] if existing_ids else derive_chronicle_id(resolved_topic)

        def _assemble_revision(revision: int, previous: ChronicleSnapshot | None) -> ChronicleSnapshot:
            if previous is not None and not self._topics_match(previous.topic, resolved_topic):
                msg = (
                    f"Chronicle {resolved_id} belongs to topic {previous.topic!r}; "
                    f"it cannot be continued as {resolved_topic!r}."
                )
                raise ValueError(msg)

            stable_topic = previous.topic if previous is not None else resolved_topic
            historical_entry_ids: dict[str, str] = {}
            ambiguous_evidence_ids: set[str] = set()
            if previous is not None:
                for previous_entry in previous.entries:
                    for article in previous_entry.evidence.all_articles:
                        evidence_id = article.evidence_id
                        prior_id = historical_entry_ids.get(evidence_id)
                        if prior_id is not None and prior_id != previous_entry.entry_id:
                            ambiguous_evidence_ids.add(evidence_id)
                        else:
                            historical_entry_ids[evidence_id] = previous_entry.entry_id
                for evidence_id in ambiguous_evidence_ids:
                    historical_entry_ids.pop(evidence_id, None)
            snapshot = assemble_chronicle(
                topic=stable_topic,
                timeline=timeline,
                tree=build_chronicle_lineage(timeline) if timeline.events else None,
                scope=scope,
                chronicle_id=resolved_id,
                revision=revision,
                created_at=previous.created_at if previous else None,
                entry_id_overrides=historical_entry_ids,
            )
            snapshot.metadata["mermaid_validation"] = render_chronicle_mermaid_result(snapshot).to_dict()
            # Audit the actual payload builder, not a self-declared constant.
            # The manifest is created by the session artifact store; every
            # other required name must be present in this concrete projection.
            snapshot.audit = audit_chronicle(snapshot)
            prepared_files = self.build_artifact_files(snapshot)
            snapshot.audit = audit_chronicle(
                snapshot,
                artifact_files=["manifest.json", *prepared_files],
            )
            return snapshot

        # ChronicleStore uses an inter-process file lock and blocking filesystem
        # durability calls. Keep that work off the MCP server's async event loop.
        return await asyncio.to_thread(self._store.append, resolved_id, _assemble_revision)

    def load(self, chronicle_id: str, revision: int | None = None) -> ChronicleSnapshot | None:
        """Load one chronicle revision, defaulting to the latest."""
        return self._store.load(chronicle_id, revision)

    def list_chronicles(self, *, topic: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """List stored chronicles, most recently updated first."""
        return self._store.list_chronicles(topic=topic, limit=limit)

    def find_chronicle_ids_by_topic(self, topic: str) -> list[str]:
        """Return every stored chronicle ID matching one normalized exact topic."""
        return self._store.find_chronicle_ids_by_topic(topic)

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
            ValueError: If the range is not forward or either revision is absent.
        """
        if to_revision is not None and from_revision >= to_revision:
            msg = f"Chronicle diffs must be forward and strictly increasing: revision {from_revision} -> {to_revision}"
            raise ValueError(msg)

        before = self._store.load(chronicle_id, from_revision)
        after = self._store.load(chronicle_id, to_revision)
        missing = [
            str(requested)
            for requested, snapshot in ((from_revision, before), (to_revision or "latest", after))
            if snapshot is None
        ]
        if missing or before is None or after is None:
            stored = self._store.list_revisions(chronicle_id)
            available = f"Stored revisions: {stored}" if stored else "No revisions are stored yet"
            msg = f"Revision {' and '.join(missing)} not found for chronicle {chronicle_id}. {available}."
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
        mermaid_result = render_chronicle_mermaid_result(snapshot)
        files: dict[str, Any] = {
            "snapshot.json": snapshot.to_dict(),
            "chronicle_map.json": project_chronicle_map(snapshot),
            "chronicle.mmd": mermaid_result.source,
            "mermaid_validation.json": mermaid_result.to_dict(),
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
            output_format: One of ``json``, ``chronicle_map``, ``timeline``,
                ``tree``, ``graph``, ``evidence``, ``mermaid``,
                ``timeline_mermaid``, ``mindmap``, or ``narrative``.

        Returns:
            A dict for JSON projections, or a string for text renderings.

        Raises:
            ValueError: If *output_format* is not supported.
        """
        renderers: dict[str, Callable[[], dict[str, Any] | str]] = {
            "json": snapshot.to_dict,
            "chronicle_map": lambda: project_chronicle_map(snapshot),
            "timeline": lambda: project_timeline(snapshot),
            "tree": lambda: project_lineage_tree(snapshot),
            "graph": lambda: project_graph(snapshot),
            "evidence": lambda: project_evidence(snapshot),
            "milestones": lambda: analyze_milestones(snapshot),
            "mermaid": lambda: render_chronicle_mermaid_result(snapshot).source,
            "timeline_mermaid": lambda: render_timeline_mermaid(snapshot),
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

    @staticmethod
    def _topics_match(left: str, right: str) -> bool:
        """Return whether two topic labels differ only by safe normalization."""
        return canonical_topic_key(left) == canonical_topic_key(right)


__all__ = [
    "CHRONICLE_ARTIFACT_FILES",
    "CHRONICLE_READ_ORDER",
    "ChronicleEvidenceProvider",
    "ChronicleService",
]
