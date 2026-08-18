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
    build_chronicle_lineage,
    compare_chronicles,
    derive_chronicle_id,
    diff_chronicles,
    narrate_chronicle,
    project_chronicle_map,
    project_evidence,
    project_graph,
    project_lineage_tree,
    project_timeline,
    render_chronicle_mermaid,
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
    mesh_terms: list[str] | None = None,
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
        metadata={"mesh_terms": list(mesh_terms or []), "keywords": []},
    )


BASE_EVENTS = [
    make_event("1", 2015, MilestoneType.FIRST_REPORT, "First report", mesh_terms=["Molecular Mechanisms"]),
    make_event("2", 2018, MilestoneType.PHASE_3, "Phase 3 trial", mesh_terms=["Clinical Efficacy"]),
    make_event("3", 2020, MilestoneType.FDA_APPROVAL, "FDA approval", mesh_terms=["Clinical Efficacy"]),
]

EXTENDED_EVENTS = [
    *BASE_EVENTS,
    make_event("4", 2023, MilestoneType.SAFETY_ALERT, "Safety alert", mesh_terms=["Drug Safety"]),
    make_event("5", 2024, MilestoneType.META_ANALYSIS, "Meta-analysis", mesh_terms=["Drug Safety"]),
]


class FakeEvidenceProvider:
    """In-memory stand-in for the timeline builder retrieval port."""

    def __init__(self, events: list[TimelineEvent], source_counts: dict[str, int] | None = None) -> None:
        self.events = events
        self.source_counts = source_counts or {"pubmed": len(events)}
        self.topic_calls: list[str] = []
        self.topic_call_kwargs: list[dict[str, Any]] = []
        self.pmid_calls: list[list[str]] = []

    async def build_timeline(self, topic: str, **kwargs: Any) -> ResearchTimeline:
        """Return the canned timeline for a topic search."""
        self.topic_calls.append(topic)
        self.topic_call_kwargs.append(dict(kwargs))
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
        tree=build_chronicle_lineage(timeline),
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

    def test_safety_entries_keep_their_declared_supporting_role(self):
        snapshot = build_snapshot(EXTENDED_EVENTS)
        edge_types = {edge.edge_type for edge in snapshot.graph.edges.values()}
        assert ChronicleEdgeType.SUPPORTS in edge_types
        assert ChronicleEdgeType.CONTRADICTS not in edge_types

    def test_empty_timeline_produces_empty_snapshot(self):
        timeline = ResearchTimeline(topic="nothing", events=[])
        snapshot = assemble_chronicle(topic="nothing", timeline=timeline)

        assert snapshot.entries == []
        assert snapshot.branches == []
        assert snapshot.year_range is None

    def test_semantic_lineage_uses_mesh_signals(self):
        snapshot = build_snapshot(EXTENDED_EVENTS)

        assert snapshot.metadata["lineage_diagnostics"]["basis"] == "topic_signals"
        branch_names = {branch.name for branch in snapshot.branches}
        assert {"Clinical Efficacy", "Drug Safety"} <= branch_names
        assert all("lineage_basis:" in " ".join(branch.tags) for branch in snapshot.branches)

    def test_lineage_falls_back_to_research_stages_when_topic_signals_are_missing(self):
        events = [
            make_event("11", 2010, MilestoneType.FIRST_REPORT, "First"),
            make_event("12", 2015, MilestoneType.PHASE_3, "Trial"),
        ]
        timeline = ResearchTimeline(topic="signal-poor", events=events)
        snapshot = assemble_chronicle(
            topic="signal-poor",
            timeline=timeline,
            tree=build_chronicle_lineage(timeline),
        )
        snapshot.audit = audit_chronicle(snapshot)

        assert snapshot.metadata["lineage_diagnostics"]["basis"] == "research_stage_fallback"
        finding = next(item for item in snapshot.audit.findings if item.check == "lineage_semantics")
        assert finding.status == "warn"
        assert "rather than semantic sub-topics" in finding.message


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

        finding = next(f for f in audit.findings if f.check == "artifact_bundle_preflight")
        assert finding.status == "fail"
        assert "audit.json" in finding.details["missing"]

    def test_missing_source_counts_warn(self):
        timeline = ResearchTimeline(topic="drug X", events=list(BASE_EVENTS))
        snapshot = assemble_chronicle(topic="drug X", timeline=timeline, tree=build_research_tree(timeline))
        audit = audit_chronicle(snapshot)

        finding = next(f for f in audit.findings if f.check == "source_coverage")
        assert finding.status == "warn"

    def test_bounded_source_sample_warns_instead_of_claiming_complete_coverage(self):
        snapshot = build_snapshot(BASE_EVENTS)
        snapshot.input_scope.source_counts = {"pubmed": {"returned": 3, "available": 250}}

        finding = next(f for f in audit_chronicle(snapshot).findings if f.check == "source_coverage")

        assert finding.status == "warn"
        assert finding.details["incomplete_sources"] == ["pubmed"]
        assert "observed, ranked sample" in finding.message

    def test_output_selection_cap_is_a_source_coverage_caveat(self):
        snapshot = build_snapshot(BASE_EVENTS)
        snapshot.metadata["timeline_metadata"] = {
            "total_searched": 90,
            "articles_after_filters": 90,
            "milestone_candidates": 60,
            "events_before_output_cap": 60,
        }

        finding = next(f for f in audit_chronicle(snapshot).findings if f.check == "source_coverage")

        assert finding.status == "warn"
        assert finding.details["selection_limited"] is True
        assert finding.details["selection_counts"]["events_emitted"] == len(BASE_EVENTS)

    def test_explicit_pmid_audit_compares_identifier_sets(self):
        timeline = ResearchTimeline(topic="custom", events=[BASE_EVENTS[0]])
        snapshot = assemble_chronicle(
            topic="custom",
            timeline=timeline,
            scope=ChronicleInputScope(mode="pmids", query="custom", pmids=["999999"]),
        )

        finding = next(f for f in audit_chronicle(snapshot).findings if f.check == "input_coverage")

        assert finding.status == "fail"
        assert finding.details["missing_requested_pmids"] == ["999999"]
        assert finding.details["unexpected_retrieved_pmids"] == [BASE_EVENTS[0].pmid]

    def test_duplicate_and_orphan_branch_references_warn(self):
        snapshot = build_snapshot(BASE_EVENTS)
        snapshot.branches.append(snapshot.branches[0])
        snapshot.branches[0].parent_branch_id = "missing-parent"
        snapshot.entries[0].branch_id = "missing-branch"

        audit = audit_chronicle(snapshot)
        finding = next(f for f in audit.findings if f.check == "branch_coverage")

        assert finding.status == "warn"
        assert finding.details["duplicate_branch_ids"]
        assert finding.details["invalid_entry_assignments"] == [snapshot.entries[0].entry_id]
        assert finding.details["invalid_parent_branches"]

    def test_visually_summarized_mermaid_is_not_audit_pass(self):
        events = [
            make_event(str(index), 1800 + index, MilestoneType.PHASE_1, f"Trial {index}") for index in range(1, 131)
        ]
        snapshot = build_snapshot(events)

        finding = next(item for item in audit_chronicle(snapshot).findings if item.check == "mermaid_renderability")

        assert finding.status == "warn"
        assert finding.details["omitted_counts"]
        assert "complete record" in finding.message

    def test_cyclic_branch_structure_is_repaired_with_audit_warning(self):
        snapshot = build_snapshot(BASE_EVENTS)
        assert len(snapshot.branches) >= 2
        snapshot.branches[0].parent_branch_id = snapshot.branches[1].branch_id
        snapshot.branches[1].parent_branch_id = snapshot.branches[0].branch_id

        finding = next(item for item in audit_chronicle(snapshot).findings if item.check == "mermaid_renderability")

        assert finding.status == "warn"
        assert "branch_cycle_removed" in finding.message


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

    def test_chronicle_map_combines_horizontal_spine_and_branch_order(self):
        snapshot = build_snapshot(EXTENDED_EVENTS)
        projection = project_chronicle_map(snapshot)

        assert projection["layout"] == "horizontal_time_spine_with_lineage_branches"
        assert projection["spine"]["orientation"] == "horizontal"
        assert [anchor["year"] for anchor in projection["spine"]["year_anchors"]] == [
            2015,
            2018,
            2020,
            2023,
            2024,
        ]
        assert projection["lineage_diagnostics"]["basis"] == "topic_signals"
        for branch in projection["branches"]:
            orders = [entry["global_order"] for entry in branch["entries"]]
            assert orders == sorted(orders)
            if branch["entries"]:
                assert branch["branch_point"]["year"] == branch["entries"][0]["year"]
                assert branch["entries"][0]["paper_title"].startswith("Study")

    def test_mermaid_and_mindmap_render(self):
        snapshot = build_snapshot(EXTENDED_EVENTS)

        mermaid = render_timeline_mermaid(snapshot)
        assert mermaid.startswith("timeline")
        assert "2015 : First report" in mermaid

        mindmap = render_lineage_mindmap(snapshot)
        assert mindmap.startswith("mindmap")
        assert "drug X" in mindmap

    def test_chronicle_mermaid_has_horizontal_spine_and_year_anchored_branches(self):
        snapshot = build_snapshot(EXTENDED_EVENTS)

        mermaid = render_chronicle_mermaid(snapshot)

        assert mermaid.startswith("flowchart LR")
        assert mermaid.count("==>") == 5
        assert "-.->" in mermaid
        assert "pmid#58;2" in mermaid
        assert "classDef spine fill:#dbeafe" in mermaid

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

    def test_comparison_entry_digests_use_precision_aware_dates(self):
        first = build_snapshot(BASE_EVENTS, topic="drug X")
        first.entries[0].time_start = "2020-11"
        first.entries[1].time_start = "2020-02"
        first.entries[2].time_start = "2020-07-15"
        second = build_snapshot(BASE_EVENTS, topic="drug Y")

        comparison = compare_chronicles([first, second])
        digest = comparison["chronicles"][0]

        assert digest["first_entry"]["entry_id"] == first.entries[1].entry_id
        assert digest["latest_entry"]["entry_id"] == first.entries[0].entry_id

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
        assert snapshot.audit.status == "warn"
        assert any(finding.check == "lineage_semantics" for finding in snapshot.audit.findings)
        assert provider.topic_calls == ["drug X"]
        assert provider.topic_call_kwargs[0]["include_all"] is True
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

    async def test_build_continues_stored_topic_scope_from_chronicle_id_alone(self, store):
        first = await ChronicleService(FakeEvidenceProvider(BASE_EVENTS), store).build(
            topic="drug X", max_events=40, min_year=2015, max_year=2024
        )

        provider = FakeEvidenceProvider(EXTENDED_EVENTS)
        second = await ChronicleService(provider, store).build(chronicle_id=first.chronicle_id)

        assert second.revision == 2
        assert second.topic == "drug X"
        assert provider.topic_calls == ["drug X"]
        assert provider.topic_call_kwargs[0]["max_events"] == 40
        assert provider.topic_call_kwargs[0]["min_year"] == 2015
        assert provider.topic_call_kwargs[0]["max_year"] == 2024
        assert second.input_scope.filters == first.input_scope.filters
        delta = ChronicleService(provider, store).diff(first.chronicle_id, 1)
        assert "filters" not in delta["scope"]["changes"]

    async def test_build_continues_stored_pmid_scope_from_chronicle_id_alone(self, store):
        first = await ChronicleService(FakeEvidenceProvider(EXTENDED_EVENTS), store).build(
            pmids=["1", "3"], topic="Selected"
        )

        provider = FakeEvidenceProvider(EXTENDED_EVENTS)
        second = await ChronicleService(provider, store).build(chronicle_id=first.chronicle_id)

        assert second.revision == 2
        assert provider.pmid_calls == [["1", "3"]]
        assert provider.topic_calls == []
        assert second.input_scope.mode == "pmids"

    async def test_build_explicit_arguments_override_inherited_scope(self, store):
        first = await ChronicleService(FakeEvidenceProvider(BASE_EVENTS), store).build(topic="drug X", max_events=40)

        provider = FakeEvidenceProvider(EXTENDED_EVENTS)
        await ChronicleService(provider, store).build(chronicle_id=first.chronicle_id, max_events=12)

        assert provider.topic_call_kwargs[0]["max_events"] == 12

    async def test_build_rejects_unknown_chronicle_id_without_scope(self, store):
        service = ChronicleService(FakeEvidenceProvider(BASE_EVENTS), store)

        with pytest.raises(ValueError, match="not found"):
            await service.build(chronicle_id="never-stored-chronicle")

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

        with pytest.raises(ValueError, match=r"not found.*Stored revisions: \[1\]"):
            service.diff(snapshot.chronicle_id, 99)

    async def test_diff_rejects_reversed_range_before_reading_storage(self, store):
        snapshot = await ChronicleService(FakeEvidenceProvider(BASE_EVENTS), store).build(topic="drug X")
        service = ChronicleService(FakeEvidenceProvider(BASE_EVENTS), store)

        with pytest.raises(ValueError, match="forward and strictly increasing"):
            service.diff(snapshot.chronicle_id, 3, 1)

    async def test_artifact_files_cover_required_names(self, store):
        snapshot = await ChronicleService(FakeEvidenceProvider(BASE_EVENTS), store).build(topic="drug X")
        files = ChronicleService.build_artifact_files(snapshot, narrative="# note")

        assert {
            "snapshot.json",
            "chronicle_map.json",
            "chronicle.mmd",
            "mermaid_validation.json",
            "timeline.json",
            "lineage_tree.json",
            "graph.json",
            "evidence.json",
            "audit.json",
        } <= set(files)
        assert files["narrative.md"] == "# note"
        assert files["chronicle.mmd"].startswith("flowchart LR")
        assert "```" not in files["chronicle.mmd"]
        assert files["mermaid_validation.json"]["schema_version"] == "mermaid-validation/v1"
        assert files["mermaid_validation.json"]["structural_valid"] is True
        assert files["mermaid_validation.json"] == snapshot.metadata["mermaid_validation"]

    async def test_service_audits_the_actual_artifact_payload_keys(self, store, monkeypatch):
        original_builder = ChronicleService.build_artifact_files

        def incomplete_builder(snapshot, *, narrative=None):
            files = original_builder(snapshot, narrative=narrative)
            files.pop("graph.json")
            return files

        monkeypatch.setattr(ChronicleService, "build_artifact_files", staticmethod(incomplete_builder))
        snapshot = await ChronicleService(FakeEvidenceProvider(BASE_EVENTS), store).build(topic="drug X")
        finding = next(f for f in snapshot.audit.findings if f.check == "artifact_bundle_preflight")

        assert finding.status == "fail"
        assert finding.details["missing"] == ["graph.json"]

    async def test_render_supports_every_documented_format(self, store):
        snapshot = await ChronicleService(FakeEvidenceProvider(EXTENDED_EVENTS), store).build(topic="drug X")

        for output_format in ("json", "chronicle_map", "timeline", "tree", "graph", "evidence"):
            assert isinstance(ChronicleService.render(snapshot, output_format), dict)
        for output_format in ("mermaid", "timeline_mermaid", "mindmap", "narrative"):
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
    def _register(
        monkeypatch,
        tmp_path,
        events: list[TimelineEvent],
        *,
        persistence_enabled: bool = False,
    ):
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
        monkeypatch.setattr(chronicle_tools, "artifact_persistence_enabled", lambda: persistence_enabled)

        mcp = MCPServer(name="chronicle-test")
        chronicle_tools.register_chronicle_tools(mcp, object())
        return {name: tool.fn for name, tool in mcp._tool_manager._tools.items()}

    async def test_tool_schema_bounds_modes_and_identifiers(self, monkeypatch, tmp_path):
        from mcp.server.mcpserver import MCPServer

        from pubmed_search.presentation.mcp_server.tools import chronicle as chronicle_tools

        monkeypatch.setattr(chronicle_tools, "_chronicle_store", lambda: ChronicleStore(tmp_path / "chronicles"))
        monkeypatch.setattr(
            chronicle_tools, "TimelineBuilder", lambda *args, **kwargs: FakeEvidenceProvider(BASE_EVENTS)
        )
        mcp = MCPServer(name="chronicle-schema-test")
        chronicle_tools.register_chronicle_tools(mcp, object())

        build_schema = mcp._tool_manager._tools["build_research_chronicle"].parameters
        read_schema = mcp._tool_manager._tools["read_research_chronicle"].parameters
        max_events_schema = build_schema["properties"]["max_events"]["anyOf"][0]
        assert max_events_schema["minimum"] == 1
        assert max_events_schema["maximum"] == 200
        assert build_schema["properties"]["max_events"]["default"] is None
        assert "mermaid" in build_schema["properties"]["output"]["enum"]
        assert read_schema["properties"]["mode"]["enum"] == ["brief", "full"]
        chronicle_id_schema = read_schema["properties"]["chronicle_id"]["anyOf"][0]
        assert chronicle_id_schema["pattern"] == r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
        assert build_schema["additionalProperties"] is False
        assert read_schema["additionalProperties"] is False

        for tool_name in ("build_research_chronicle", "read_research_chronicle"):
            argument_model = mcp._tool_manager._tools[tool_name].fn_metadata.arg_model
            with pytest.raises(ValueError, match="Extra inputs are not permitted"):
                argument_model.model_validate({"unexpected_argument": True})

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

    async def test_build_accepts_only_strict_explicit_pmid_tokens(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        result = await tools["build_research_chronicle"](
            pmids="PMID: 1, 2 PMID:3",
            topic="Selected",
        )

        assert "# Research Chronicle: Selected" in result
        assert "Entries: 3" in result

    @pytest.mark.parametrize(
        "pmids",
        [
            "10.1000/123456",
            "1, DOI:10.1000/2, 3",
            "pubmed:123456",
            "PMID123456",
            "123abc",
            "１２３４５６",
        ],
    )
    async def test_build_rejects_non_pmid_and_mixed_identifier_tokens(self, monkeypatch, tmp_path, pmids):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        payload = json.loads(await tools["build_research_chronicle"](pmids=pmids, output="json"))

        assert payload["success"] is False
        assert "ASCII digits" in payload["error"]
        listed = json.loads(await tools["read_research_chronicle"](action="list"))
        assert listed == {"total": 0, "chronicles": []}

    @pytest.mark.parametrize(
        ("kwargs", "field"),
        [
            ({"topic": ["drug X"]}, "topic"),
            ({"pmids": 123456}, "pmids"),
            ({"chronicle_id": {"id": "x"}}, "chronicle_id"),
        ],
    )
    async def test_build_direct_call_non_string_inputs_return_structured_errors(
        self,
        monkeypatch,
        tmp_path,
        kwargs,
        field,
    ):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        payload = json.loads(await tools["build_research_chronicle"](**kwargs, output="json"))

        assert payload["success"] is False
        assert f"{field} must be a string" in payload["error"]

    async def test_build_direct_call_non_string_output_returns_error_instead_of_type_error(
        self,
        monkeypatch,
        tmp_path,
    ):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        result = await tools["build_research_chronicle"](topic="drug X", output=["json"])

        assert "output must be a string" in result

    async def test_build_json_output_is_parseable(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        result = await tools["build_research_chronicle"](topic="drug X", output="json")
        payload = json.loads(result)

        assert payload["schema_version"] == CHRONICLE_SCHEMA_VERSION
        assert len(payload["entries"]) == 3

    async def test_build_structured_errors_remain_json(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        payload = json.loads(await tools["build_research_chronicle"](output="json", max_events=0))

        assert payload["success"] is False
        assert "max_events" in payload["error"]

    async def test_build_rejects_reversed_year_range(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        result = await tools["build_research_chronicle"](topic="drug X", min_year=2025, max_year=2020)

        assert "min_year cannot be later" in result

    async def test_artifact_failure_is_visible_without_losing_saved_revision(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS, persistence_enabled=True)

        result = await tools["build_research_chronicle"](topic="drug X", output="json")
        payload = json.loads(result)

        assert payload["revision"] == 1
        assert payload["artifact"]["status"] == "failed"
        listed = json.loads(await tools["read_research_chronicle"](action="list"))
        assert listed["chronicles"][0]["latest_revision"] == 1

    async def test_build_mermaid_keeps_artifact_note_outside_source(self, monkeypatch, tmp_path):
        from pubmed_search.presentation.mcp_server.tools import chronicle as chronicle_tools

        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)
        persisted: dict[str, Any] = {}

        def capture_artifact(**kwargs: Any) -> dict[str, Any]:
            persisted.update(kwargs)
            return {
                "artifact_id": "artifact-1",
                "artifact_uri": "artifact://artifact-1",
                "audit_status": "pass",
                "read_order": ["audit.json", "chronicle.mmd"],
            }

        monkeypatch.setattr(chronicle_tools, "persist_tool_artifact", capture_artifact)

        result = await tools["build_research_chronicle"](topic="drug X", output="mermaid")
        diagram = result.split("```mermaid\n", maxsplit=1)[1].split("\n```", maxsplit=1)[0]

        assert result.startswith("```mermaid\nflowchart LR")
        assert "## Persistent Artifact" in result
        assert "Persistent Artifact" not in diagram
        assert diagram == persisted["files"]["chronicle.mmd"]
        assert persisted["files"]["response.md"].startswith("```mermaid\nflowchart LR")
        assert persisted["files"]["response.md"].endswith("\n```")

    async def test_read_mermaid_returns_a_renderable_markdown_fence(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)
        summary = await tools["build_research_chronicle"](topic="drug X")
        chronicle_id = summary.split("Chronicle ID: `")[1].split("`")[0]

        result = await tools["read_research_chronicle"](chronicle_id=chronicle_id, output="mermaid")

        assert result.startswith("```mermaid\nflowchart LR")
        assert result.endswith("\n```")

    async def test_json_output_stays_parseable_when_artifact_is_persisted(self, monkeypatch, tmp_path):
        from pubmed_search.presentation.mcp_server.tools import chronicle as chronicle_tools

        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)
        monkeypatch.setattr(
            chronicle_tools,
            "persist_tool_artifact",
            lambda **_kwargs: {
                "artifact_id": "artifact-1",
                "artifact_uri": "artifact://artifact-1",
                "audit_status": "pass",
                "read_order": ["audit.json"],
            },
        )

        result = await tools["build_research_chronicle"](topic="drug X", output="json")

        payload = json.loads(result)
        assert payload["topic"] == "drug X"
        assert payload["artifact"]["artifact_id"] == "artifact-1"
        assert "Persistent Artifact" not in result

    async def test_read_list_then_load_then_diff(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)
        await tools["build_research_chronicle"](topic="drug X")

        listed = json.loads(await tools["read_research_chronicle"](action="list"))
        assert listed["total"] == 1
        chronicle_id = listed["chronicles"][0]["chronicle_id"]

        loaded = await tools["read_research_chronicle"](chronicle_id=chronicle_id, output="timeline")
        assert json.loads(loaded)["projection"] == "timeline"

        extended = self._register(monkeypatch, tmp_path, EXTENDED_EVENTS)
        # Continue existing chronicle by chronicle_id alone without passing topic
        revision_2 = await extended["build_research_chronicle"](chronicle_id=chronicle_id)
        assert "Revision: 2" in revision_2
        assert f"Chronicle ID: `{chronicle_id}`" in revision_2

        delta = json.loads(
            await extended["read_research_chronicle"](action="diff", chronicle_id=chronicle_id, from_revision=1)
        )
        assert len(delta["entries"]["added"]) == 2

    async def test_build_with_unknown_chronicle_id_without_topic_fails(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)
        result = await tools["build_research_chronicle"](chronicle_id="nonexistent-chronicle-id")
        assert "not found" in result.lower()

    async def test_read_diff_reports_stored_revisions_for_unknown_revision(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)
        summary = await tools["build_research_chronicle"](topic="drug X")
        chronicle_id = summary.split("Chronicle ID: `")[1].split("`")[0]

        result = await tools["read_research_chronicle"](action="diff", chronicle_id=chronicle_id, from_revision=99)

        assert "Stored revisions: [1]" in result

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

    @pytest.mark.parametrize(
        ("kwargs", "field"),
        [
            ({"action": "load", "chronicle_id": 123}, "chronicle_id"),
            ({"action": "list", "topic": ["drug X"]}, "topic"),
            ({"action": "compare", "topics": ["a", "b"]}, "topics"),
            ({"action": "compare", "chronicle_ids": {"a", "b"}}, "chronicle_ids"),
            ({"action": "narrate", "mode": ["full"]}, "mode"),
        ],
    )
    async def test_read_direct_call_non_string_inputs_return_structured_errors(
        self,
        monkeypatch,
        tmp_path,
        kwargs,
        field,
    ):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        payload = json.loads(await tools["read_research_chronicle"](**kwargs, output="json"))

        assert payload["success"] is False
        assert f"{field} must be a string" in payload["error"]

    async def test_read_direct_call_non_string_action_and_output_do_not_raise(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        action_payload = json.loads(await tools["read_research_chronicle"](action=["load"], output="json"))
        output_result = await tools["read_research_chronicle"](action="load", output=["json"])

        assert action_payload["success"] is False
        assert "action must be a string" in action_payload["error"]
        assert "output must be a string" in output_result

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

        result = json.loads(await tools["read_research_chronicle"](action="list"))
        assert result == {"total": 0, "chronicles": []}

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

    async def test_compare_rejects_duplicate_target(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)
        await tools["build_research_chronicle"](topic="drug X")

        payload = json.loads(await tools["read_research_chronicle"](action="compare", topics="drug X,drug X"))

        assert payload["success"] is False
        assert "distinct" in payload["error"]

    async def test_compare_uses_exact_stored_topic_for_custom_id(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)
        await tools["build_research_chronicle"](topic="drug X", chronicle_id="custom-x")
        await tools["build_research_chronicle"](topic="drug Y", chronicle_id="custom-y")

        payload = json.loads(await tools["read_research_chronicle"](action="compare", topics="drug x,drug y"))

        assert {row["chronicle_id"] for row in payload["chronicles"]} == {"custom-x", "custom-y"}

    async def test_compare_rejects_too_many_chronicles(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        result = await tools["read_research_chronicle"](action="compare", topics="a,b,c,d,e,f")
        assert "Maximum 5 chronicles" in result

    async def test_compare_reports_unbuilt_topics(self, monkeypatch, tmp_path):
        tools = self._register(monkeypatch, tmp_path, BASE_EVENTS)

        result = await tools["read_research_chronicle"](action="compare", topics="ghost A,ghost B")
        assert "No stored chronicle for" in result
