"""Cross-projection and audit integrity regressions for Research Chronicle."""

from __future__ import annotations

from collections import Counter

import pytest

from pubmed_search.application.chronicle import (
    audit_chronicle,
    chronology_key,
    narrate_chronicle,
    project_chronicle_map,
    project_lineage_tree,
    project_timeline,
    render_chronicle_mermaid,
)
from pubmed_search.application.chronicle.graph import build_chronicle_graph
from pubmed_search.application.chronicle.ordering import chronicle_time_status, definitely_precedes
from pubmed_search.domain.entities.chronicle import (
    CHRONICLE_SCHEMA_VERSION,
    ChronicleBranch,
    ChronicleEdgeType,
    ChronicleEntry,
    ChronicleEntryStatus,
    ChronicleEntryType,
    ChronicleGraph,
    ChronicleInputScope,
    ChronicleSnapshot,
    EvidenceArticle,
    EvidenceBundle,
)


def _entry(
    entry_id: str,
    time_start: str,
    *,
    branch_id: str | None = "main",
    status: ChronicleEntryStatus = ChronicleEntryStatus.ACTIVE,
    contradicting: bool = False,
) -> ChronicleEntry:
    year_text = time_start[:4]
    year = int(year_text) if year_text.isdigit() else None
    supporting = EvidenceArticle(title=f"Supporting paper {entry_id}", pmid=f"s-{entry_id}", year=year)
    contradicting_articles = (
        [EvidenceArticle(title=f"Contradicting paper {entry_id}", pmid=f"c-{entry_id}", year=year)]
        if contradicting
        else []
    )
    return ChronicleEntry(
        entry_id=entry_id,
        entry_type=ChronicleEntryType.SAFETY if contradicting else ChronicleEntryType.MILESTONE,
        title=f"Title {entry_id}",
        time_start=time_start,
        summary_claim=f"Claim {entry_id}.",
        branch_id=branch_id,
        confidence=0.8,
        status=status,
        evidence=EvidenceBundle(
            supporting_articles=[supporting],
            contradicting_articles=contradicting_articles,
        ),
    )


def _snapshot(entries: list[ChronicleEntry], branches: list[ChronicleBranch]) -> ChronicleSnapshot:
    snapshot = ChronicleSnapshot(
        chronicle_id="cross-projection-integrity",
        topic="Cross-projection integrity",
        entries=entries,
        branches=branches,
        input_scope=ChronicleInputScope(source_counts={"pubmed": len(entries)}),
        metadata={
            "lineage_diagnostics": {
                "basis": "topic_signals",
                "semantic_coverage_ratio": 1.0,
                "selected_signals": [{"label": "A"}, {"label": "B"}],
            }
        },
    )
    snapshot.graph = build_chronicle_graph(snapshot)
    return snapshot


def _finding(snapshot: ChronicleSnapshot, check: str):  # type: ignore[no-untyped-def]
    return next(finding for finding in audit_chronicle(snapshot).findings if finding.check == check)


def _flatten_tree_entries(branches: list[dict[str, object]]) -> list[str]:
    result: list[str] = []
    pending = list(reversed(branches))
    while pending:
        branch = pending.pop()
        raw_entries = branch.get("entries")
        if isinstance(raw_entries, list):
            result.extend(str(entry["entry_id"]) for entry in raw_entries if isinstance(entry, dict))
        children = branch.get("children")
        if isinstance(children, list):
            pending.extend(reversed([child for child in children if isinstance(child, dict)]))
    return result


def test_precision_aware_order_is_shared_and_undated_is_last() -> None:
    entries = [
        _entry("march-first", "2020-03-01"),
        _entry("january", "2020-01-15"),
        _entry("march-second", "2020-03-01"),
        _entry("february", "2020-02"),
        _entry("undated", "Undated"),
    ]
    branch = ChronicleBranch(branch_id="main", name="Main", entry_ids=[entry.entry_id for entry in entries])
    snapshot = _snapshot(entries, [branch])
    expected = ["january", "february", "march-first", "march-second", "undated"]

    assert [entry.entry_id for entry in sorted(snapshot.entries, key=chronology_key)] == expected
    assert [row["entry_id"] for row in project_timeline(snapshot)["events"]] == expected
    assert project_chronicle_map(snapshot)["spine"]["ordered_entry_ids"] == expected
    assert _flatten_tree_entries(project_lineage_tree(snapshot)["branches"]) == expected

    narrative = narrate_chronicle(snapshot, mode="full")
    assert [
        line.split("Claim ", 1)[1].split(".", 1)[0] for line in narrative.splitlines() if line.startswith("- Claim ")
    ] == expected


def test_equal_precision_never_invents_precedes_or_supersedes() -> None:
    first = _entry("first", "2020-03-01", status=ChronicleEntryStatus.SUPERSEDED)
    second = _entry("second", "2020-03-01")
    snapshot = _snapshot(
        [first, second],
        [ChronicleBranch(branch_id="main", name="Main", entry_ids=["first", "second"])],
    )

    temporal_edges = [
        edge
        for edge in snapshot.graph.edges.values()
        if edge.edge_type in {ChronicleEdgeType.PRECEDES, ChronicleEdgeType.SUPERSEDES}
    ]
    assert temporal_edges == []
    assert definitely_precedes(first, second) is False
    assert _finding(snapshot, "graph_integrity").status == "pass"


def test_supporting_and_contradicting_roles_are_not_inferred_from_entry_type() -> None:
    entry = _entry("safety", "2021", contradicting=True)
    snapshot = _snapshot(
        [entry],
        [ChronicleBranch(branch_id="main", name="Main", entry_ids=[entry.entry_id])],
    )
    role_by_source = {
        edge.source: edge.edge_type
        for edge in snapshot.graph.edges.values()
        if edge.target == entry.entry_id
        and edge.edge_type in {ChronicleEdgeType.SUPPORTS, ChronicleEdgeType.CONTRADICTS}
    }

    assert role_by_source["pmid:s-safety"] is ChronicleEdgeType.SUPPORTS
    assert role_by_source["pmid:c-safety"] is ChronicleEdgeType.CONTRADICTS


def test_membership_mismatch_is_visible_in_every_projection_and_audit() -> None:
    missing = _entry("missing", "2020", branch_id="main")
    listed = _entry("listed", "2021", branch_id="main")
    snapshot = _snapshot(
        [missing, listed],
        [ChronicleBranch(branch_id="main", name="Main", entry_ids=["listed", "ghost"])],
    )

    timeline = project_timeline(snapshot)
    tree = project_lineage_tree(snapshot)
    chronicle_map = project_chronicle_map(snapshot)
    narrative = narrate_chronicle(snapshot, mode="full")

    assert [event["entry_id"] for event in timeline["events"]] == ["missing", "listed"]
    assert timeline["events"][0]["branch_id"] is None
    assert "missing_from_declared_branch" in timeline["events"][0]["membership_repair_reasons"]
    assert tree["unassigned_entry_ids"] == ["missing"]
    assert chronicle_map["unassigned_entry_ids"] == ["missing"]
    repair_branch = next(branch for branch in chronicle_map["branches"] if branch.get("synthetic"))
    assert [row["entry_id"] for row in repair_branch["entries"]] == ["missing"]
    assert "## Unassigned Entries" in narrative and "Claim missing." in narrative
    assert "Title missing" in render_chronicle_mermaid(snapshot)

    branch_finding = _finding(snapshot, "branch_coverage")
    assert branch_finding.status == "warn"
    assert branch_finding.details["dangling_branch_memberships"][0]["entry_id"] == "ghost"
    assert _finding(snapshot, "graph_integrity").status == "pass"


def test_duplicate_entry_ids_and_stale_graph_are_audit_failures() -> None:
    entries = [_entry("duplicate", "2020"), _entry("duplicate", "2021")]
    snapshot = ChronicleSnapshot(
        chronicle_id="duplicates",
        topic="Duplicates",
        entries=entries,
        branches=[ChronicleBranch(branch_id="main", name="Main", entry_ids=["duplicate"])],
        graph=ChronicleGraph(),
        input_scope=ChronicleInputScope(source_counts={"pubmed": 2}),
    )

    identity = _finding(snapshot, "snapshot_identity")
    graph = _finding(snapshot, "graph_integrity")
    assert identity.status == "fail"
    assert identity.details["duplicate_entry_ids"] == ["duplicate"]
    assert graph.status == "fail"
    assert graph.details["missing_expected_nodes"]


def test_graph_audit_detects_missing_expected_evidence_edge() -> None:
    entry = _entry("entry", "2020")
    snapshot = _snapshot(
        [entry],
        [ChronicleBranch(branch_id="main", name="Main", entry_ids=[entry.entry_id])],
    )
    support_edge_id = next(
        edge_id for edge_id, edge in snapshot.graph.edges.items() if edge.edge_type is ChronicleEdgeType.SUPPORTS
    )
    snapshot.graph.edges.pop(support_edge_id)

    finding = _finding(snapshot, "graph_integrity")
    assert finding.status == "fail"
    assert finding.details["missing_expected_edges"]


@pytest.mark.parametrize("invalid_time", ["2020-13", "2021-02-29", "0000", "20xx"])
def test_impossible_dates_fail_chronology_audit(invalid_time: str) -> None:
    entry = _entry("invalid", invalid_time)
    snapshot = _snapshot(
        [entry],
        [ChronicleBranch(branch_id="main", name="Main", entry_ids=[entry.entry_id])],
    )

    finding = _finding(snapshot, "chronology")
    assert chronicle_time_status(invalid_time) == "invalid"
    assert finding.status == "fail"
    assert finding.details["invalid_dates"][0]["value"] == invalid_time


def test_reversed_date_range_and_invalid_precedes_edge_fail_audit() -> None:
    newer = _entry("newer", "2021")
    newer.time_end = "2020"
    older = _entry("older", "2019")
    snapshot = _snapshot(
        [newer, older],
        [ChronicleBranch(branch_id="main", name="Main", entry_ids=["newer", "older"])],
    )
    # Replace the valid edge with a validly typed but chronologically reversed one.
    snapshot.graph.edges = {
        edge_id: edge
        for edge_id, edge in snapshot.graph.edges.items()
        if edge.edge_type is not ChronicleEdgeType.PRECEDES
    }
    from pubmed_search.domain.entities.chronicle import ChronicleGraphEdge

    snapshot.graph.add_edge(ChronicleGraphEdge("newer", "older", ChronicleEdgeType.PRECEDES))

    assert _finding(snapshot, "chronology").status == "fail"
    graph_finding = _finding(snapshot, "graph_integrity")
    assert graph_finding.status == "fail"
    assert graph_finding.details["chronology_violations"]


def test_child_only_container_branch_is_not_reported_empty() -> None:
    entry = _entry("child-entry", "2020", branch_id="child")
    snapshot = _snapshot(
        [entry],
        [
            ChronicleBranch(branch_id="container", name="Container"),
            ChronicleBranch(
                branch_id="child",
                name="Child",
                parent_branch_id="container",
                entry_ids=[entry.entry_id],
            ),
        ],
    )

    finding = _finding(snapshot, "branch_coverage")
    assert finding.status == "pass"
    assert finding.details["empty_branches"] == []


def test_narrative_audit_covers_every_occurrence_and_evidence_identifier() -> None:
    entries = [_entry("first", "2020"), _entry("second", "2021")]
    snapshot = _snapshot(
        entries,
        [ChronicleBranch(branch_id="main", name="Main", entry_ids=[entry.entry_id for entry in entries])],
    )

    finding = _finding(snapshot, "narrative_citations")
    narrative = narrate_chronicle(snapshot, mode="full")
    assert finding.status == "pass"
    assert finding.details["expected_claim_occurrences"] == 2
    assert Counter(identifier in narrative for identifier in ("pmid:s-first", "pmid:s-second"))[True] == 2


def test_branch_confidence_zero_round_trips_without_becoming_one() -> None:
    branch = ChronicleBranch(branch_id="zero", name="Zero", confidence=0.0)
    assert ChronicleBranch.from_dict(branch.to_dict()).confidence == 0.0


def test_snapshot_rejects_unknown_schema_but_accepts_missing_legacy_field() -> None:
    current = ChronicleSnapshot(chronicle_id="schema", topic="Schema").to_dict()
    assert ChronicleSnapshot.from_dict(current).schema_version == CHRONICLE_SCHEMA_VERSION

    legacy = dict(current)
    legacy.pop("schema_version")
    assert ChronicleSnapshot.from_dict(legacy).schema_version == CHRONICLE_SCHEMA_VERSION

    future = {**current, "schema_version": "research-chronicle/v999"}
    with pytest.raises(ValueError, match="Unsupported Chronicle schema version"):
        ChronicleSnapshot.from_dict(future)


def test_artifact_audit_is_explicitly_only_a_preflight() -> None:
    snapshot = _snapshot([], [])
    audit = audit_chronicle(snapshot, artifact_files=["snapshot.json"])
    finding = next(item for item in audit.findings if item.check == "artifact_bundle_preflight")

    assert finding.status == "fail"
    assert "Prepared artifact bundle" in finding.message
    assert "persist" not in finding.message.casefold()
