"""Tests for the Research Chronicle domain, application services, and MCP tools."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from pubmed_search.application.chronicle import (
    ChronicleService,
    ChronicleStore,
    analyze_milestones,
    assemble_chronicle,
    audit_chronicle,
    compare_chronicles,
    derive_chronicle_id,
    diff_chronicles,
    narrate_chronicle,
    project_evidence,
    project_graph,
    project_lineage_tree,
    project_timeline,
    render_lineage_mindmap,
    render_timeline_mermaid,
)
from pubmed_search.application.timeline import build_research_tree
from pubmed_search.domain.entities.chronicle import (
    CHRONICLE_SCHEMA_VERSION,
    ChronicleEdgeType,
    ChronicleEntryStatus,
    ChronicleEntryType,
    ChronicleGraph,
    ChronicleGraphEdge,
    ChronicleGraphNode,
    ChronicleInputScope,
    ChronicleNodeType,
    ChronicleSnapshot,
    EvidenceArticle,
)
from pubmed_search.domain.entities.timeline import (
    EvidenceLevel,
    MilestoneType,
    ResearchTimeline,
    TimelineEvent,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


def make_event(
    pmid: str,
    year: int,
    milestone_type: MilestoneType,
    label: str,
    title: str = "",
    citations: int = 10,
) -> TimelineEvent:
    """Build a timeline event with sensible defaults for chronicle tests."""
    return TimelineEvent(
        pmid=pmid,
        year=year,
        milestone_type=milestone_type,
        title=title or f"Study {pmid}",
        milestone_label=label,
        citation_count=citations,
        journal="J Chronicle Test",
        doi=f"10.1000/{pmid}",
        confidence_score=0.8,
        evidence_level=EvidenceLevel.LEVEL_2,
    )


BASE_EVENTS = [
    make_event("1", 2015, MilestoneType.FIRST_REPORT, "First report"),
    make_event("2", 2018, MilestoneType.PHASE_3, "Phase 3 trial"),
    make_event("3", 2020, MilestoneType.FDA_APPROVAL, "FDA approval"),
]

EXTENDED_EVENTS = [
    *BASE_EVENTS,
    make_event("4", 2023, MilestoneType.SAFETY_ALERT, "Safety alert"),
    make_event("5", 2024, MilestoneType.META_ANALYSIS, "Meta-analysis"),
]


class FakeEvidenceProvider:
    """In-memory stand-in for the timeline builder retrieval port."""

    def __init__(self, events: list[TimelineEvent], source_counts: dict[str, int] | None = None) -> None:
        self.events = events
        self.source_counts = source_counts or {"pubmed": len(events)}
        self.topic_calls: list[str] = []
        self.pmid_calls: list[list[str]] = []

    async def build_timeline(self, topic: str, **kwargs: Any) -> ResearchTimeline:
        """Return the canned timeline for a topic search."""
        del kwargs
        self.topic_calls.append(topic)
        return ResearchTimeline(
            topic=topic,
            events=list(self.events),
            metadata={"source_counts": self.source_counts},
        )

    async def build_timeline_from_pmids(
        self,
        pmids: list[str],
        topic: str = "Custom Timeline",
        auto_periods: bool = True,
    ) -> ResearchTimeline:
        """Return the canned timeline for an explicit PMID list."""
        del auto_periods
        self.pmid_calls.append(list(pmids))
        selected = [event for event in self.events if event.pmid in set(pmids)]
        return ResearchTimeline(topic=topic, events=selected)


def build_snapshot(events: list[TimelineEvent], topic: str = "drug X") -> ChronicleSnapshot:
    """Assemble and audit a snapshot directly from timeline events."""
    timeline = ResearchTimeline(topic=topic, events=list(events), metadata={"source_counts": {"pubmed": len(events)}})
    snapshot = assemble_chronicle(
        topic=topic,
        timeline=timeline,
        tree=build_research_tree(timeline),
        scope=ChronicleInputScope(mode="topic", query=topic, source_counts={"pubmed": len(events)}),
    )
    snapshot.audit = audit_chronicle(snapshot)
    return snapshot


@pytest.fixture
def store(tmp_path) -> ChronicleStore:
    """Return a chronicle store rooted in a temporary directory."""
    return ChronicleStore(tmp_path / "chronicles")


# ── Domain entities ─────────────────────────────────────────────────────────


class TestChronicleEntities:
    """Serialization and invariant behavior of chronicle entities."""

    def test_snapshot_round_trips_through_json(self):
        snapshot = build_snapshot(EXTENDED_EVENTS)
        restored = ChronicleSnapshot.from_dict(json.loads(json.dumps(snapshot.to_dict())))

        assert restored.to_dict() == snapshot.to_dict()
        assert restored.schema_version == CHRONICLE_SCHEMA_VERSION
        assert len(restored.entries) == len(snapshot.entries)
        assert len(restored.graph.nodes) == len(snapshot.graph.nodes)

    def test_evidence_article_identifier_precedence(self):
        assert EvidenceArticle(title="t", pmid="1", doi="10.1/x").evidence_id == "pmid:1"
        assert EvidenceArticle(title="t", doi="10.1/x").evidence_id == "doi:10.1/x"
        assert EvidenceArticle(title="t", pmcid="PMC9").evidence_id == "pmcid:PMC9"
        assert EvidenceArticle(title="untitled").evidence_id.startswith("title:")
        assert EvidenceArticle(title="t").has_identifier is False

    def test_graph_rejects_invalid_edge_endpoints(self):
        graph = ChronicleGraph()
        graph.add_node(ChronicleGraphNode("entry-a", ChronicleNodeType.ENTRY, "A"))
        graph.add_edge(ChronicleGraphEdge("entry-a", "missing", ChronicleEdgeType.PRECEDES))

        violations = graph.validate()
        assert len(violations) == 1
        assert "unknown target node" in violations[0]

    def test_graph_rejects_invalid_edge_type_pairing(self):
        graph = ChronicleGraph()
        graph.add_node(ChronicleGraphNode("entry-a", ChronicleNodeType.ENTRY, "A"))
        graph.add_node(ChronicleGraphNode("branch-a", ChronicleNodeType.BRANCH, "B"))
        graph.add_edge(ChronicleGraphEdge("entry-a", "branch-a", ChronicleEdgeType.SUPPORTS))

        violations = graph.validate()
        assert len(violations) == 1
        assert "not allowed for 'supports'" in violations[0]

    def test_graph_dedupes_nodes_and_edges(self):
        graph = ChronicleGraph()
        graph.add_node(ChronicleGraphNode("n1", ChronicleNodeType.ENTRY, "first"))
        graph.add_node(ChronicleGraphNode("n1", ChronicleNodeType.ENTRY, "second"))
        graph.add_node(ChronicleGraphNode("n2", ChronicleNodeType.ENTRY, "other"))
        graph.add_edge(ChronicleGraphEdge("n1", "n2", ChronicleEdgeType.PRECEDES))
        graph.add_edge(ChronicleGraphEdge("n1", "n2", ChronicleEdgeType.PRECEDES))

        assert len(graph.nodes) == 2
        assert graph.nodes["n1"].label == "first"
        assert len(graph.edges) == 1

    def test_entry_type_and_status_parse_fall_back(self):
        assert ChronicleEntryType.parse("not-a-type") is ChronicleEntryType.MILESTONE
        assert ChronicleEntryType.parse("safety") is ChronicleEntryType.SAFETY
        assert ChronicleEntryStatus.parse(None) is ChronicleEntryStatus.ACTIVE
        assert ChronicleEntryStatus.parse("contested") is ChronicleEntryStatus.CONTESTED


# ── Assembler ───────────────────────────────────────────────────────────────


class TestChronicleAssembler:
    """Mapping from timeline evidence onto the chronicle model."""

    def test_chronicle_id_is_stable_and_slugged(self):
        first = derive_chronicle_id("Remimazolam Sedation")
        assert first == derive_chronicle_id("remimazolam sedation")
        assert first.startswith("remimazolam-sedation-")
        assert first != derive_chronicle_id("propofol")

    def test_entries_carry_evidence_and_citations(self):
        snapshot = build_snapshot(BASE_EVENTS)

        assert len(snapshot.entries) == 3
        for entry in snapshot.entries:
            assert entry.evidence.supporting_articles
            assert entry.entry_id in entry.entry_id
            assert "PMID:" in entry.summary_claim

    def test_entry_ids_are_stable_across_rebuilds(self):
        first = build_snapshot(BASE_EVENTS)
        second = build_snapshot(BASE_EVENTS)
        assert [e.entry_id for e in first.entries] == [e.entry_id for e in second.entries]

    def test_milestone_types_map_to_entry_types(self):
        snapshot = build_snapshot(EXTENDED_EVENTS)
        by_pmid = {entry.evidence.supporting_articles[0].pmid: entry.entry_type for entry in snapshot.entries}

        assert by_pmid["3"] is ChronicleEntryType.MILESTONE
        assert by_pmid["4"] is ChronicleEntryType.SAFETY
        assert by_pmid["5"] is ChronicleEntryType.EVIDENCE_SHIFT

    def test_entries_are_assigned_to_branches(self):
        snapshot = build_snapshot(EXTENDED_EVENTS)

        assert snapshot.branches
        assert all(entry.branch_id for entry in snapshot.entries)
        assigned = {entry_id for branch in snapshot.branches for entry_id in branch.entry_ids}
        assert assigned == {entry.entry_id for entry in snapshot.entries}

    def test_graph_is_valid_by_construction(self):
        snapshot = build_snapshot(EXTENDED_EVENTS)

        assert snapshot.graph.validate() == []
        assert any(node.node_type is ChronicleNodeType.TOPIC for node in snapshot.graph.nodes.values())
        assert any(edge.edge_type is ChronicleEdgeType.SUPPORTS for edge in snapshot.graph.edges.values())

    def test_safety_entries_use_contradicts_edges(self):
        snapshot = build_snapshot(EXTENDED_EVENTS)
        edge_types = {edge.edge_type for edge in snapshot.graph.edges.values()}
        assert ChronicleEdgeType.CONTRADICTS in edge_types

    def test_empty_timeline_produces_empty_snapshot(self):
        timeline = ResearchTimeline(topic="nothing", events=[])
        snapshot = assemble_chronicle(topic="nothing", timeline=timeline)

        assert snapshot.entries == []
        assert snapshot.branches == []
        assert snapshot.year_range is None


# ── Audit ───────────────────────────────────────────────────────────────────


class TestChronicleAudit:
    """Completeness and integrity checks."""

    def test_complete_chronicle_passes(self):
        snapshot = build_snapshot(EXTENDED_EVENTS)
        audit = audit_chronicle(snapshot)

        assert audit.status == "pass"
        assert audit.warnings == []

    def test_empty_chronicle_fails_input_coverage(self):
        timeline = ResearchTimeline(topic="nothing", events=[])
        snapshot = assemble_chronicle(topic="nothing", timeline=timeline)
        audit = audit_chronicle(snapshot)

        assert audit.status == "fail"
        assert any(f.check == "input_coverage" and f.status == "fail" for f in audit.findings)

    def test_missing_evidence_fails(self):
        snapshot = build_snapshot(BASE_EVENTS)
        snapshot.entries[0].evidence.supporting_articles.clear()
        audit = audit_chronicle(snapshot)

        assert audit.status == "fail"
        assert any(f.check == "evidence_coverage" and f.status == "fail" for f in audit.findings)

    def test_missing_identifiers_are_reported(self):
        snapshot = build_snapshot(BASE_EVENTS)
        for entry in snapshot.entries:
            entry.evidence.supporting_articles[0] = EvidenceArticle(title="anonymous", year=2020)
        audit = audit_chronicle(snapshot)

        finding = next(f for f in audit.findings if f.check == "evidence_identifiers")
        assert finding.status == "fail"

    def test_graph_violation_fails_audit(self):
        snapshot = build_snapshot(BASE_EVENTS)
        snapshot.graph.add_edge(ChronicleGraphEdge("ghost", "phantom", ChronicleEdgeType.PRECEDES))
        audit = audit_chronicle(snapshot)

        assert any(f.check == "graph_integrity" and f.status == "fail" for f in audit.findings)

    def test_missing_artifact_files_fail(self):
        snapshot = build_snapshot(BASE_EVENTS)
        audit = audit_chronicle(snapshot, artifact_files=["snapshot.json"])

        finding = next(f for f in audit.findings if f.check == "artifact_files")
        assert finding.status == "fail"
        assert "audit.json" in finding.details["missing"]

    def test_missing_source_counts_warn(self):
        timeline = ResearchTimeline(topic="drug X", events=list(BASE_EVENTS))
        snapshot = assemble_chronicle(topic="drug X", timeline=timeline, tree=build_research_tree(timeline))
        audit = audit_chronicle(snapshot)

        finding = next(f for f in audit.findings if f.check == "source_coverage")
        assert finding.status == "warn"


# ── Projections ─────────────────────────────────────────────────────────────


class TestChronicleProjections:
    """Read models derived from a snapshot."""

    def test_timeline_projection_is_chronological(self):
        snapshot = build_snapshot(EXTENDED_EVENTS)
        projection = project_timeline(snapshot)

        years = [event["year"] for event in projection["events"]]
        assert years == sorted(years)
        assert projection["total_events"] == len(snapshot.entries)
        assert projection["year_range"] == [2015, 2024]

    def test_lineage_tree_projection_covers_all_entries(self):
        snapshot = build_snapshot(EXTENDED_EVENTS)
        projection = project_lineage_tree(snapshot)

        counted = sum(branch["entry_count"] for branch in projection["branches"])
        assert counted == len(snapshot.entries)
        assert projection["unassigned_entry_ids"] == []

    def test_graph_projection_reports_no_violations(self):
        snapshot = build_snapshot(EXTENDED_EVENTS)
        projection = project_graph(snapshot)

        assert projection["violations"] == []
        assert projection["node_count"] == len(snapshot.graph.nodes)

    def test_evidence_projection_links_back_to_entries(self):
        snapshot = build_snapshot(BASE_EVENTS)
        projection = project_evidence(snapshot)

        assert projection["total_articles"] == 3
        for article in projection["articles"]:
            assert article["backs_entry_ids"]

    def test_mermaid_and_mindmap_render(self):
        snapshot = build_snapshot(EXTENDED_EVENTS)

        mermaid = render_timeline_mermaid(snapshot)
        assert mermaid.startswith("timeline")
        assert "section 2015" in mermaid

        mindmap = render_lineage_mindmap(snapshot)
        assert mindmap.startswith("mindmap")
        assert "drug X" in mindmap

    def test_projections_share_entry_ids(self):
        snapshot = build_snapshot(EXTENDED_EVENTS)
        timeline_ids = {event["entry_id"] for event in project_timeline(snapshot)["events"]}
        tree_ids = {
            entry["entry_id"] for branch in project_lineage_tree(snapshot)["branches"] for entry in branch["entries"]
        }
        assert timeline_ids == tree_ids


# ── Analytics ───────────────────────────────────────────────────────────────


class TestChronicleAnalytics:
    """Milestone analysis and cross-chronicle comparison."""

    def test_milestone_analysis_reports_distributions(self):
        snapshot = build_snapshot(EXTENDED_EVENTS)
        analysis = analyze_milestones(snapshot)

        assert analysis["total_entries"] == 5
        assert analysis["year_range"] == [2015, 2024]
        assert analysis["duration_years"] == 10
        assert analysis["entry_type_distribution"]["safety"] == 1
        assert analysis["activity_by_year"]["2015"] == 1
        assert analysis["evidence_quality"]["with_identifier"] == 5
        assert analysis["audit_status"] == "pass"

    def test_milestone_analysis_ranks_landmarks_by_citations(self):
        events = [
            make_event("1", 2015, MilestoneType.FIRST_REPORT, "First report", citations=5),
            make_event("2", 2018, MilestoneType.PHASE_3, "Phase 3 trial", citations=900),
        ]
        analysis = analyze_milestones(build_snapshot(events))

        assert analysis["landmark_entries"][0]["citations"] == 900

    def test_milestone_analysis_handles_empty_chronicle(self):
        timeline = ResearchTimeline(topic="nothing", events=[])
        analysis = analyze_milestones(assemble_chronicle(topic="nothing", timeline=timeline))

        assert analysis["total_entries"] == 0
        assert analysis["year_range"] is None
        assert analysis["landmark_entries"] == []

    def test_comparison_reports_superlatives_and_shared_evidence(self):
        wide = build_snapshot(EXTENDED_EVENTS, topic="drug X")
        narrow = build_snapshot(BASE_EVENTS, topic="drug Y")

        comparison = compare_chronicles([wide, narrow])

        assert len(comparison["chronicles"]) == 2
        assert comparison["summary"]["most_entries"] == "drug X"
        assert comparison["summary"]["longest_span"] == "drug X"
        assert comparison["summary"]["earliest_research"] == 2015
        assert comparison["summary"]["shared_evidence_count"] == 3
        assert comparison["shared_evidence"][0]["shared_by"] == ["drug X", "drug Y"]

    def test_comparison_requires_two_chronicles(self):
        with pytest.raises(ValueError, match="at least 2"):
            compare_chronicles([build_snapshot(BASE_EVENTS)])


# ── Narrative ───────────────────────────────────────────────────────────────


class TestChronicleNarrative:
    """Evidence-backed prose rendering."""

    def test_every_claim_cites_entry_and_evidence(self):
        snapshot = build_snapshot(EXTENDED_EVENTS)
        narrative = narrate_chronicle(snapshot, mode="full")

        claim_lines = [line for line in narrative.splitlines() if line.startswith("- 2")]
        assert claim_lines
        for line in claim_lines:
            assert "[entry-" in line
            assert "pmid:" in line

    def test_brief_mode_limits_entries_per_branch(self):
        events = [make_event(str(i), 2000 + i, MilestoneType.PHASE_1, f"Trial {i}") for i in range(1, 8)]
        snapshot = build_snapshot(events)

        brief = narrate_chronicle(snapshot, mode="brief")
        full = narrate_chronicle(snapshot, mode="full")

        assert "omitted in brief mode" in brief
        assert full.count("[entry-") > brief.count("[entry-")

    def test_empty_chronicle_makes_no_claims(self):
        timeline = ResearchTimeline(topic="nothing", events=[])
        snapshot = assemble_chronicle(topic="nothing", timeline=timeline)

        narrative = narrate_chronicle(snapshot)
        assert "no claims can be made" in narrative


# ── Differ ──────────────────────────────────────────────────────────────────


class TestChronicleDiff:
    """Revision comparison."""

    def test_added_entries_are_detected(self):
        before = build_snapshot(BASE_EVENTS)
        after = build_snapshot(EXTENDED_EVENTS)
        after.revision = 2

        delta = diff_chronicles(before, after)
        assert len(delta["entries"]["added"]) == 2
        assert delta["entries"]["retired"] == []
        assert delta["evidence"]["total_after"] == 5

    def test_retired_entries_are_detected(self):
        before = build_snapshot(EXTENDED_EVENTS)
        after = build_snapshot(BASE_EVENTS)
        after.revision = 2

        delta = diff_chronicles(before, after)
        assert len(delta["entries"]["retired"]) == 2
        assert delta["entries"]["added"] == []

    def test_status_change_is_reported_as_update(self):
        before = build_snapshot(BASE_EVENTS)
        after = build_snapshot(BASE_EVENTS)
        after.revision = 2
        after.entries[0].status = ChronicleEntryStatus.SUPERSEDED

        delta = diff_chronicles(before, after)
        assert len(delta["entries"]["updated"]) == 1
        assert delta["entries"]["updated"][0]["changes"]["status"]["to"] == "superseded"

    def test_diff_rejects_different_chronicles(self):
        left = build_snapshot(BASE_EVENTS, topic="drug X")
        right = build_snapshot(BASE_EVENTS, topic="drug Y")

        with pytest.raises(ValueError, match="different chronicles"):
            diff_chronicles(left, right)


# ── Store ───────────────────────────────────────────────────────────────────


class TestChronicleStore:
    """Revision persistence."""

    def test_save_and_load_round_trip(self, store):
        snapshot = build_snapshot(BASE_EVENTS)
        store.save(snapshot)

        loaded = store.load(snapshot.chronicle_id)
        assert loaded is not None
        assert loaded.to_dict() == snapshot.to_dict()

    def test_latest_revision_tracks_highest(self, store):
        snapshot = build_snapshot(BASE_EVENTS)
        store.save(snapshot)
        snapshot.revision = 3
        store.save(snapshot)

        assert store.latest_revision(snapshot.chronicle_id) == 3
        assert store.list_revisions(snapshot.chronicle_id) == [1, 3]
        assert store.load(snapshot.chronicle_id).revision == 3

    def test_fixed_revision_cannot_overwrite_history(self, store):
        snapshot = build_snapshot(BASE_EVENTS)
        store.save(snapshot)
        original = store.load(snapshot.chronicle_id, 1)

        snapshot.topic = "mutated"
        with pytest.raises(FileExistsError, match="immutable"):
            store.save(snapshot)

        reloaded = store.load(snapshot.chronicle_id, 1)
        assert reloaded is not None
        assert original is not None
        assert reloaded.to_dict() == original.to_dict()

    def test_missing_chronicle_returns_none(self, store):
        assert store.load("nope-00000000") is None
        assert store.latest_revision("nope-00000000") is None
        assert store.list_revisions("nope-00000000") == []

    def test_list_chronicles_filters_by_topic(self, store):
        store.save(build_snapshot(BASE_EVENTS, topic="drug X"))
        store.save(build_snapshot(BASE_EVENTS, topic="gene Y"))

        assert len(store.list_chronicles()) == 2
        assert len(store.list_chronicles(topic="gene")) == 1

    def test_unsafe_chronicle_id_is_rejected(self, store):
        with pytest.raises(ValueError, match="Unsafe chronicle id"):
            store.load("../escape")


# ── Service ─────────────────────────────────────────────────────────────────


class TestChronicleService:
    """Orchestration across retrieval, assembly, audit, and persistence."""

    async def test_build_persists_first_revision(self, store):
        provider = FakeEvidenceProvider(BASE_EVENTS)
        service = ChronicleService(provider, store)

        snapshot = await service.build(topic="drug X")

        assert snapshot.revision == 1
        assert snapshot.audit.status == "pass"
        assert provider.topic_calls == ["drug X"]
        assert store.load(snapshot.chronicle_id) is not None

    async def test_rebuild_creates_next_revision(self, store):
        first = await ChronicleService(FakeEvidenceProvider(BASE_EVENTS), store).build(topic="drug X")
        second = await ChronicleService(FakeEvidenceProvider(EXTENDED_EVENTS), store).build(topic="drug X")

        assert second.revision == 2
        assert second.chronicle_id == first.chronicle_id
        assert second.created_at == first.created_at
        assert store.list_revisions(first.chronicle_id) == [1, 2]

    def test_concurrent_builds_commit_monotonic_immutable_revisions(self, tmp_path):
        root = tmp_path / "chronicles"

        def _build_one() -> int:
            # Separate service/store instances reproduce MCP worker-thread
            # requests converging on the same process-local storage root.
            service = ChronicleService(FakeEvidenceProvider(BASE_EVENTS), ChronicleStore(root))
            return asyncio.run(service.build(topic="drug X")).revision

        with ThreadPoolExecutor(max_workers=16) as executor:
            revisions = list(executor.map(lambda _: _build_one(), range(16)))

        store = ChronicleStore(root)
        assert sorted(revisions) == list(range(1, 17))
        assert store.list_revisions(derive_chronicle_id("drug X")) == list(range(1, 17))
        for revision in range(1, 17):
            snapshot = store.load(derive_chronicle_id("drug X"), revision)
            assert snapshot is not None
            assert snapshot.revision == revision
            topic_nodes = [node for node in snapshot.graph.nodes.values() if node.node_type is ChronicleNodeType.TOPIC]
            assert dict(topic_nodes[0].attributes)["revision"] == revision

    async def test_build_from_pmids_uses_pmid_mode(self, store):
        provider = FakeEvidenceProvider(EXTENDED_EVENTS)
        service = ChronicleService(provider, store)

        snapshot = await service.build(pmids=["1", "3"], topic="Selected")

        assert provider.pmid_calls == [["1", "3"]]
        assert snapshot.input_scope.mode == "pmids"
        assert snapshot.input_scope.pmids == ["1", "3"]
        assert len(snapshot.entries) == 2

    async def test_build_requires_topic_or_pmids(self, store):
        service = ChronicleService(FakeEvidenceProvider(BASE_EVENTS), store)

        with pytest.raises(ValueError, match=r"topic.*pmids"):
            await service.build()

    async def test_diff_between_stored_revisions(self, store):
        first = await ChronicleService(FakeEvidenceProvider(BASE_EVENTS), store).build(topic="drug X")
        await ChronicleService(FakeEvidenceProvider(EXTENDED_EVENTS), store).build(topic="drug X")

        service = ChronicleService(FakeEvidenceProvider(EXTENDED_EVENTS), store)
        delta = service.diff(first.chronicle_id, 1)

        assert delta["from_revision"] == 1
        assert delta["to_revision"] == 2
        assert len(delta["entries"]["added"]) == 2

    async def test_diff_rejects_unknown_revision(self, store):
        snapshot = await ChronicleService(FakeEvidenceProvider(BASE_EVENTS), store).build(topic="drug X")
        service = ChronicleService(FakeEvidenceProvider(BASE_EVENTS), store)

        with pytest.raises(ValueError, match="not found"):
            service.diff(snapshot.chronicle_id, 99)

    async def test_artifact_files_cover_required_names(self, store):
        snapshot = await ChronicleService(FakeEvidenceProvider(BASE_EVENTS), store).build(topic="drug X")
        files = ChronicleService.build_artifact_files(snapshot, narrative="# note")

        assert {
            "snapshot.json",
            "timeline.json",
            "lineage_tree.json",
            "graph.json",
            "evidence.json",
            "audit.json",
        } <= set(files)
        assert files["narrative.md"] == "# note"

    async def test_render_supports_every_documented_format(self, store):
        snapshot = await ChronicleService(FakeEvidenceProvider(EXTENDED_EVENTS), store).build(topic="drug X")

        for output_format in ("json", "timeline", "tree", "graph", "evidence"):
            assert isinstance(ChronicleService.render(snapshot, output_format), dict)
        for output_format in ("mermaid", "mindmap", "narrative"):
            assert isinstance(ChronicleService.render(snapshot, output_format), str)

    async def test_render_rejects_unknown_format(self, store):
        snapshot = await ChronicleService(FakeEvidenceProvider(BASE_EVENTS), store).build(topic="drug X")

        with pytest.raises(ValueError, match="Unsupported chronicle output format"):
            ChronicleService.render(snapshot, "svg")

    async def test_source_counts_flow_into_scope(self, store):
        provider = FakeEvidenceProvider(BASE_EVENTS, source_counts={"pubmed": 3, "europe_pmc": 2})
        snapshot = await ChronicleService(provider, store).build(topic="drug X")

        assert snapshot.input_scope.source_counts == {"pubmed": 3, "europe_pmc": 2}


# ── MCP tools ───────────────────────────────────────────────────────────────


class TestChronicleTools:
    """Thin MCP wrappers over the chronicle service."""

    @staticmethod
    def _register(monkeypatch, tmp_path, events: list[TimelineEvent]):
        from mcp.server.mcpserver import MCPServer

        from pubmed_search.presentation.mcp_server.tools import chronicle as chronicle_tools

        monkeypatch.setattr(
            chronicle_tools,
            "_chronicle_store",
            lambda: ChronicleStore(tmp_path / "chronicles"),
        )
        monkeypatch.setattr(
            chronicle_tools,
            "TimelineBuilder",
            lambda *args, **kwargs: FakeEvidenceProvider(events),
        )
        monkeypatch.setattr(chronicle_tools, "persist_tool_artifact", lambda **kwargs: None)

        mcp = MCPServer(name="chronicle-test")
        chronicle_tools.register_chronicle_tools(mcp, object())
        return {name: tool.fn for name, tool in mcp._tool_manager._tools.items()}

    async def test_tools_are_registered(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)
        assert "build_research_chronicle" in tools
        assert "read_research_chronicle" in tools

    async def test_build_returns_summary_markdown(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, EXTENDED_EVENTS)

        result = await tools["build_research_chronicle"](topic="drug X")

        assert "# Research Chronicle: drug X" in result
        assert "Revision: 1" in result
        assert "Audit: **pass**" in result

    async def test_build_rejects_unknown_output(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        result = await tools["build_research_chronicle"](topic="drug X", output="svg")
        assert "Unsupported output" in result

    async def test_build_requires_topic_or_pmids(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        result = await tools["build_research_chronicle"]()
        assert "Must provide either 'topic' or 'pmids'" in result

    async def test_build_resolves_last_pmids_from_session(self, monkeypatch, tmp_path):
        from pubmed_search.presentation.mcp_server.tools import chronicle as chronicle_tools

        tools = self._register(monkeypatch, tmp_path, EXTENDED_EVENTS)
        monkeypatch.setattr(chronicle_tools, "get_last_search_pmids", lambda: ["1", "3"])

        result = await tools["build_research_chronicle"](pmids="last", topic="Selected")
        assert "# Research Chronicle: Selected" in result
        assert "Entries: 2" in result

    async def test_build_reports_when_last_search_is_empty(self, monkeypatch, tmp_path):
        from pubmed_search.presentation.mcp_server.tools import chronicle as chronicle_tools

        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)
        monkeypatch.setattr(chronicle_tools, "get_last_search_pmids", list)

        result = await tools["build_research_chronicle"](pmids="last")
        assert "No usable PMIDs resolved" in result

    async def test_build_json_output_is_parseable(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        result = await tools["build_research_chronicle"](topic="drug X", output="json")
        payload = json.loads(result)

        assert payload["schema_version"] == CHRONICLE_SCHEMA_VERSION
        assert len(payload["entries"]) == 3

    async def test_read_list_then_load_then_diff(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)
        await tools["build_research_chronicle"](topic="drug X")

        listed = json.loads(await tools["read_research_chronicle"](action="list"))
        assert listed["total"] == 1
        chronicle_id = listed["chronicles"][0]["chronicle_id"]

        loaded = await tools["read_research_chronicle"](chronicle_id=chronicle_id, output="timeline")
        assert json.loads(loaded)["projection"] == "timeline"

        extended = self._register(monkeypatch, tmp_path, EXTENDED_EVENTS)
        await extended["build_research_chronicle"](topic="drug X")
        delta = json.loads(
            await extended["read_research_chronicle"](action="diff", chronicle_id=chronicle_id, from_revision=1)
        )
        assert len(delta["entries"]["added"]) == 2

    async def test_read_narrate_returns_cited_markdown(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, EXTENDED_EVENTS)
        summary = await tools["build_research_chronicle"](topic="drug X")
        chronicle_id = summary.split("Chronicle ID: `")[1].split("`")[0]

        narrative = await tools["read_research_chronicle"](action="narrate", chronicle_id=chronicle_id, mode="full")
        assert "[entry-" in narrative
        assert "pmid:" in narrative

    async def test_read_rejects_unknown_action(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        result = await tools["read_research_chronicle"](action="explode")
        assert "Unsupported action" in result

    async def test_read_requires_chronicle_id(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        result = await tools["read_research_chronicle"](action="load")
        assert "chronicle_id is required" in result

    async def test_read_missing_revision_reports_available(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)
        summary = await tools["build_research_chronicle"](topic="drug X")
        chronicle_id = summary.split("Chronicle ID: `")[1].split("`")[0]

        result = await tools["read_research_chronicle"](chronicle_id=chronicle_id, revision=42)
        assert "Chronicle revision not found" in result
        assert "[1]" in result

    async def test_diff_requires_from_revision(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        result = await tools["read_research_chronicle"](action="diff", chronicle_id="drug-x-00000000")
        assert "from_revision is required" in result

    async def test_list_with_no_chronicles_reports_no_results(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        result = await tools["read_research_chronicle"](action="list")
        assert "build_research_chronicle" in result

    async def test_milestones_action_returns_analysis(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, EXTENDED_EVENTS)
        summary = await tools["build_research_chronicle"](topic="drug X")
        chronicle_id = summary.split("Chronicle ID: `")[1].split("`")[0]

        payload = json.loads(await tools["read_research_chronicle"](action="milestones", chronicle_id=chronicle_id))
        assert payload["projection"] == "milestones"
        assert payload["total_entries"] == 5

    async def test_compare_action_by_topics(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, EXTENDED_EVENTS)
        await tools["build_research_chronicle"](topic="drug X")
        await tools["build_research_chronicle"](topic="drug Y")

        payload = json.loads(await tools["read_research_chronicle"](action="compare", topics="drug X,drug Y"))
        assert payload["projection"] == "comparison"
        assert len(payload["chronicles"]) == 2
        assert payload["summary"]["shared_evidence_count"] == 5

    async def test_compare_requires_two_chronicles(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        result = await tools["read_research_chronicle"](action="compare", topics="drug X")
        assert "Need at least 2 chronicles" in result

    async def test_compare_rejects_too_many_chronicles(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        result = await tools["read_research_chronicle"](action="compare", topics="a,b,c,d,e,f")
        assert "Maximum 5 chronicles" in result

    async def test_compare_reports_unbuilt_topics(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        result = await tools["read_research_chronicle"](action="compare", topics="ghost A,ghost B")
        assert "No stored chronicle for" in result
