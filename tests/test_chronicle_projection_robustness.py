"""Robustness checks for malformed or unusually deep Chronicle lineages."""

from __future__ import annotations

from dataclasses import replace

from pubmed_search.application.chronicle.projectors import project_chronicle_map, project_evidence, project_lineage_tree
from pubmed_search.domain.entities.chronicle import (
    ChronicleBranch,
    ChronicleEntry,
    ChronicleEntryType,
    ChronicleSnapshot,
    EvidenceArticle,
    EvidenceBundle,
)


def _entry(entry_id: str, year: int, branch_id: str | None) -> ChronicleEntry:
    article = EvidenceArticle(title=f"Paper {entry_id}", pmid=entry_id, year=year)
    return ChronicleEntry(
        entry_id=entry_id,
        entry_type=ChronicleEntryType.MILESTONE,
        title=f"Milestone {entry_id}",
        time_start=str(year),
        summary_claim=f"Claim {entry_id}",
        branch_id=branch_id,
        confidence=0.8,
        evidence=EvidenceBundle(supporting_articles=[article]),
    )


def _snapshot(*, entries: list[ChronicleEntry], branches: list[ChronicleBranch]) -> ChronicleSnapshot:
    return ChronicleSnapshot(
        chronicle_id="projection-robustness",
        topic="Projection robustness",
        entries=entries,
        branches=branches,
    )


def test_evidence_projection_counts_stored_links_once_and_returns_normalized_lookup_sources() -> None:
    earlier = EvidenceArticle(title="Earlier metadata", pmid="456", fulltext_artifact_uri="  ")
    uri = "artifact://example/fulltext"
    linked = replace(earlier, pmcid="https://pmc.ncbi.nlm.nih.gov/articles/PMC123/", fulltext_artifact_uri=uri)
    doi_only = EvidenceArticle(title="DOI only", doi="https://doi.org/10.1000/Example")
    invalid = EvidenceArticle(title="A title mentioning PMC999", pmid="unknown", doi="not a DOI")
    one = _entry("one", 2020, None)
    two = _entry("two", 2021, None)
    one.evidence = EvidenceBundle(supporting_articles=[earlier, doi_only, invalid])
    two.evidence = EvidenceBundle(updating_articles=[linked], contradicting_articles=[doi_only])

    snapshot = _snapshot(entries=[one, two], branches=[])
    before = snapshot.to_dict()
    result = project_evidence(snapshot)

    assert result["fulltext_coverage"] == {
        "total_evidence_ids": 3,
        "with_stored_artifact_uri": 1,
        "scope": "stored_artifact_links_in_this_revision",
    }
    first_row, doi_row, invalid_row = result["articles"]
    assert first_row["title"] == "Earlier metadata"
    assert first_row["backs_entry_ids"] == ["one", "two"]
    assert first_row["fulltext_artifact_uri"] == uri
    assert first_row["fulltext_lookup_source"] == {"kind": "pmcid", "value": "PMC123"}
    assert doi_row["fulltext_lookup_source"] == {"kind": "doi", "value": "10.1000/example"}
    assert invalid_row["fulltext_lookup_source"] is None
    assert snapshot.to_dict() == before


def test_conflicting_pmcids_fall_back_to_consistent_pmid_without_fulltext_coverage() -> None:
    article = EvidenceArticle(title="Shared record", pmid="PMID: 456", pmcid="PMC1", doi="10.1000/example")
    entry = _entry("shared", 2024, None)
    entry.evidence = EvidenceBundle(supporting_articles=[article], updating_articles=[replace(article, pmcid="PMC2")])

    result = project_evidence(_snapshot(entries=[entry], branches=[]))

    assert result["articles"][0]["fulltext_lookup_source"] == {"kind": "pmid", "value": "456"}
    assert result["fulltext_coverage"]["with_stored_artifact_uri"] == 0
    assert result["fulltext_coverage"]["total_evidence_ids"] == 1


def test_duplicate_branch_ids_keep_occurrence_specific_branch_points() -> None:
    entries = [
        _entry("late", 2022, "duplicate"),
        _entry("early", 2010, "duplicate"),
        _entry("child", 2000, "child-branch"),
    ]
    branches = [
        ChronicleBranch(branch_id="duplicate", name="Late duplicate", entry_ids=["late"]),
        ChronicleBranch(branch_id="duplicate", name="Early duplicate", entry_ids=["early"]),
        ChronicleBranch(
            branch_id="child-branch",
            name="Ambiguous child",
            parent_branch_id="duplicate",
            entry_ids=["child"],
        ),
    ]

    projection = project_chronicle_map(_snapshot(entries=entries, branches=branches))
    rows = {row["name"]: row for row in projection["branches"]}

    assert rows["Late duplicate"]["branch_point"]["entry_id"] == "late"
    assert rows["Early duplicate"]["branch_point"]["entry_id"] == "early"
    assert rows["Ambiguous child"]["branch_point"]["entry_id"] == "child"
    assert projection["root_branch_ids"] == ["duplicate", "duplicate", "child-branch"]
    diagnostics = projection["projection_diagnostics"]
    assert diagnostics["duplicate_branch_ids"] == ["duplicate"]
    assert diagnostics["duplicate_branch_id_counts"] == {"duplicate": 2}
    assert diagnostics["ambiguous_parent_references"][0]["branch_id"] == "child-branch"


def test_deep_lineage_is_iterative_bounded_and_diagnosed() -> None:
    branch_count = 1_500
    branches = [
        ChronicleBranch(
            branch_id=f"branch-{index}",
            name=f"Branch {index}",
            parent_branch_id=f"branch-{index - 1}" if index else None,
            entry_ids=["deep-paper"] if index == branch_count - 1 else [],
        )
        for index in range(branch_count)
    ]
    snapshot = _snapshot(entries=[_entry("deep-paper", 2024, f"branch-{branch_count - 1}")], branches=branches)

    tree = project_lineage_tree(snapshot)
    tree_diagnostics = tree["projection_diagnostics"]
    assert tree_diagnostics["max_depth"] == branch_count - 1
    assert tree_diagnostics["depth_limit_exceeded"] is True
    assert tree_diagnostics["truncated"] is True
    assert tree_diagnostics["projected_branch_count"] == tree_diagnostics["depth_limit"] + 1
    assert tree_diagnostics["truncated_branch_count"] > 0

    chronicle_map = project_chronicle_map(snapshot)
    root = next(row for row in chronicle_map["branches"] if row["branch_id"] == "branch-0")
    assert len(chronicle_map["branches"]) == branch_count
    assert root["branch_point"] == {"year": 2024, "entry_id": "deep-paper", "global_order": 1}


def test_cycle_is_broken_deterministically_and_reported() -> None:
    branches = [
        ChronicleBranch(branch_id="a", name="A", parent_branch_id="b"),
        ChronicleBranch(branch_id="b", name="B", parent_branch_id="a"),
    ]
    snapshot = _snapshot(entries=[], branches=branches)

    tree = project_lineage_tree(snapshot)

    assert [branch["branch_id"] for branch in tree["branches"]] == ["a"]
    assert tree["branches"][0]["children"][0]["branch_id"] == "b"
    assert tree["projection_diagnostics"]["cycles_broken"] == [
        {"branch_indices": [0, 1], "branch_ids": ["a", "b"], "detached_branch_index": 0}
    ]


def test_chronicle_map_includes_complete_unassigned_entry_rows() -> None:
    assigned = _entry("assigned", 2021, "main")
    unassigned = _entry("unassigned", 2020, None)
    snapshot = _snapshot(
        entries=[assigned, unassigned],
        branches=[ChronicleBranch(branch_id="main", name="Main", entry_ids=["assigned"])],
    )

    projection = project_chronicle_map(snapshot)

    assert projection["unassigned_entry_ids"] == ["unassigned"]
    assert projection["unassigned_entries"] == [
        {
            "entry_id": "unassigned",
            "year": 2020,
            "time_start": "2020",
            "title": "Milestone unassigned",
            "paper_title": "Paper unassigned",
            "entry_type": "milestone",
            "status": "active",
            "global_order": 1,
            "branch_order": None,
            "evidence_ids": ["pmid:unassigned"],
        }
    ]
