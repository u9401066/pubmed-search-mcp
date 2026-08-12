"""Safety and size contracts for legacy Chronicle Mermaid projections."""

from __future__ import annotations

import re

from pubmed_search.application.chronicle import render_lineage_mindmap, render_timeline_mermaid
from pubmed_search.domain.entities.chronicle import (
    ChronicleBranch,
    ChronicleEntry,
    ChronicleEntryType,
    ChronicleSnapshot,
)

_MAX_MERMAID_BYTES = 49_000


def _entry(
    index: int,
    *,
    branch_id: str | None,
    title: str = "Research event",
    time_start: str = "2020",
) -> ChronicleEntry:
    return ChronicleEntry(
        entry_id=f"entry-{index}",
        entry_type=ChronicleEntryType.MILESTONE,
        title=title,
        time_start=time_start,
        summary_claim="Test claim",
        branch_id=branch_id,
    )


def _snapshot(
    *,
    entries: list[ChronicleEntry],
    branches: list[ChronicleBranch] | None = None,
    topic: str = "Research topic",
) -> ChronicleSnapshot:
    return ChronicleSnapshot(
        chronicle_id="legacy-mermaid-test",
        topic=topic,
        entries=entries,
        branches=list(branches or []),
    )


def test_timeline_mermaid_bounds_and_escapes_hostile_events() -> None:
    hostile = 'Bad"]\n%%{init: {"securityLevel": "loose"}}%%\n<script>|{(測試)}'
    entries = [
        _entry(
            index,
            branch_id="branch",
            title=f"{hostile} {index} " + "研究" * 100,
            time_start=str(1950 + (index % 75)),
        )
        for index in range(600)
    ]
    entries.append(_entry(601, branch_id="branch", title=hostile, time_start="Undated"))
    snapshot = _snapshot(entries=entries, topic=hostile + "主題" * 100)

    source = render_timeline_mermaid(snapshot)

    assert source.startswith("timeline\n")
    assert len(source.encode("utf-8")) < _MAX_MERMAID_BYTES
    assert "omitted" in source.casefold()
    assert "%%{" not in source
    assert "<script" not in source.casefold()
    assert source == render_timeline_mermaid(snapshot)
    for line in source.splitlines()[2:]:
        assert re.fullmatch(r"    (?:\d{1,4}|\s{4}|Summary) : .+", line)


def test_mindmap_mermaid_repairs_deep_duplicate_cycle_and_orphan_branches() -> None:
    hostile = 'Bad"]\n%%{init: true}%%\n<script>|{(分支)}'
    branches = [
        ChronicleBranch("orphan", f"Orphan {hostile}", parent_branch_id="missing", entry_ids=["entry-0"]),
        ChronicleBranch("cycle-a", "Cycle A", parent_branch_id="cycle-b", entry_ids=["entry-1"]),
        ChronicleBranch("cycle-b", "Cycle B", parent_branch_id="cycle-a", entry_ids=["entry-2"]),
        ChronicleBranch("branch-0", "Root", entry_ids=["entry-3"]),
        ChronicleBranch("branch-0", "Duplicate root", entry_ids=["entry-4"]),
    ]
    for index in range(1, 180):
        branches.append(
            ChronicleBranch(
                f"branch-{index}",
                f"{hostile} {index} " + "研究" * 100,
                parent_branch_id=f"branch-{index - 1}",
                entry_ids=[f"entry-{index + 4}"],
            )
        )
    entries = [
        _entry(
            index,
            branch_id=branches[min(index, len(branches) - 1)].branch_id,
            title=f"{hostile} paper {index} " + "論文" * 100,
            time_start=str(1900 + (index % 125)),
        )
        for index in range(240)
    ]
    snapshot = _snapshot(entries=entries, branches=branches, topic=hostile + "主題" * 100)

    source = render_lineage_mindmap(snapshot)

    assert source.startswith("mindmap\n")
    assert len(source.encode("utf-8")) < _MAX_MERMAID_BYTES
    assert "omitted" in source.casefold() or "simplified" in source.casefold()
    assert "%%{" not in source
    assert "<script" not in source.casefold()
    assert source == render_lineage_mindmap(snapshot)
    node_lines = source.splitlines()[1:]
    assert len(node_lines) <= 180
    assert all(
        re.fullmatch(r" {2,30}(?:root|branch_\d+|entry_\d+|summary_\d+)\[\"[^\"\r\n]*\"\]", line) for line in node_lines
    )


def test_legacy_mermaid_keeps_small_complete_views_without_notice() -> None:
    entries = [
        _entry(1, branch_id="branch", title="First report", time_start="2018"),
        _entry(2, branch_id="branch", title="Follow-up", time_start="2020"),
    ]
    branch = ChronicleBranch("branch", "Clinical evidence", entry_ids=[entry.entry_id for entry in entries])
    snapshot = _snapshot(entries=entries, branches=[branch], topic="Treatment X")

    timeline = render_timeline_mermaid(snapshot)
    mindmap = render_lineage_mindmap(snapshot)

    assert "2018 : First report" in timeline
    assert "2020 : Follow-up" in timeline
    assert "Clinical evidence" in mindmap
    assert "omitted" not in timeline.casefold()
    assert "omitted" not in mindmap.casefold()
