"""Durable research history, independent open actions, retries and isolation."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING, Any

import pytest

from pubmed_search.application.research_workspace import ResearchWorkspaceService
from pubmed_search.infrastructure.research_workspace import SQLiteResearchWorkspaceStore

if TYPE_CHECKING:
    from pathlib import Path


def workspace(root: Path) -> ResearchWorkspaceService:
    return ResearchWorkspaceService(SQLiteResearchWorkspaceStore(root))


def test_handoff_after_restart_retains_old_open_work_and_bounded_history(tmp_path: Path) -> None:
    service = workspace(tmp_path)
    assert not service.create("implant", "Which devices were compared?")["replayed"]
    assert service.create("implant", "Which devices were compared?")["replayed"]
    with pytest.raises(ValueError, match="different question"):
        service.create("implant", "Different topic")
    service.record(
        "implant",
        "seed",
        "explore",
        "Two devices appear in this abstract.",
        source_refs=["pmid:3878092"],
        evidence_scope="abstract",
        next_action="Read the results table.",
    )
    service.record(
        "implant",
        "strategy",
        "expand",
        "Saved the comparison search.",
        source_refs=["pipeline:device-comparison"],
        parent_ids=["seed"],
        next_action="Check coverage.",
    )
    service.record("implant", "synthesis", "explain", "Describe the remaining disagreement.", parent_ids=["seed"])

    resumed = workspace(tmp_path).read("implant", limit=1)
    assert resumed["record_count"] == 3
    assert resumed["activity_counts"] == {"explore": 1, "expand": 1, "examine": 0, "explain": 1}
    assert [record["record_id"] for record in resumed["records"]] == ["synthesis"]
    assert resumed["next_after"] is None
    assert resumed["open_action_count"] == 2
    action = resumed["open_actions"][0]
    assert action["record_id"] == "seed"
    assert action["source_handoffs"][0]["source_ref"] == "pmid:3878092"
    assert resumed["next_open_offset"] == 1
    page = service.read("implant", after=0, limit=1, open_offset=1)
    assert page["records"][0]["record_id"] == "seed"
    assert page["next_after"] == 1
    assert page["open_actions"][0]["record_id"] == "strategy"
    assert page["next_open_offset"] is None

    detail: dict[str, Any] = {
        "source_refs": ["pmid:3878092"],
        "evidence_scope": "fulltext",
        "locator": "Results, table 1",
        "parent_ids": ["seed", "strategy"],
        "resolves": ["seed"],
        "actor": "human",
    }
    recorded = service.record("implant", "table", "examine", "Logged a reading.", **detail)
    assert recorded["record"]["verification_status"] == "unverified"
    assert recorded["record"]["sequence"] == 4
    assert "source_handoffs" not in recorded["record"]
    duplicate = workspace(tmp_path).record("implant", "table", "examine", "Logged a reading.", **detail)
    assert duplicate == {**recorded, "replayed": True}
    assert [item["record_id"] for item in service.read("implant")["open_actions"]] == ["strategy"]
    with pytest.raises(ValueError, match="different content"):
        service.record("implant", "table", "examine", "A different reading.", **detail)
    with pytest.raises(ValueError, match="no open action"):
        service.record("implant", "duplicate", "examine", "Already answered", resolves=["seed"])


def test_invalid_references_roll_back_whole_record_and_resolutions(tmp_path: Path) -> None:
    service = workspace(tmp_path)
    service.create("one", "First")
    service.create("two", "Second")
    service.record("one", "topic", "explore", "Scope", next_action="Find sources")
    service.record("two", "other", "expand", "Scope", next_action="Review")
    with pytest.raises(ValueError, match="Unknown parent"):
        service.record("one", "next", "expand", "Try a cross-workspace edge", parent_ids=["other"])
    with pytest.raises(ValueError, match="no open action"):
        service.record("one", "next", "expand", "Partial resolution", resolves=["topic", "other"])
    actual = service.read("one")
    assert actual["record_count"] == 1
    assert actual["open_actions"][0]["record_id"] == "topic"
    assert service.list_workspaces(limit=1)["next_offset"] == 1
    assert service.list_workspaces(offset=1)["workspaces"][0]["workspace_id"] == "two"
    separate = workspace(tmp_path / "another-tenant")
    assert separate.list_workspaces()["workspaces"] == []
    with pytest.raises(ValueError, match="Unknown workspace"):
        separate.read("one")


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"evidence_scope": "fulltext", "source_refs": ["pmid:123"]}, "locator"),
        ({"evidence_scope": "abstract"}, "reference"),
        ({"evidence_scope": "unknown"}, "evidence_scope"),
        ({"locator": "Table 1"}, "scope"),
        ({"source_refs": ["123"]}, "namespace"),
        ({"source_refs": ["url:https://example.org?api_key=private-value"]}, "credential"),
        ({"parent_ids": ["../other"]}, "identifier"),
        ({"actor": "expert-bot"}, "actor"),
    ],
)
def test_invalid_evidence_never_appended(tmp_path: Path, options: dict[str, Any], message: str) -> None:
    service = workspace(tmp_path)
    service.create("one", "First")
    with pytest.raises(ValueError, match=message):
        service.record("one", "entry", "examine", "Reading", **options)
    assert not service.read("one")["records"]


def _append_from_process(root: Path, prefix: str) -> list[int]:
    service = workspace(root)
    service.create("shared", "A joint question")
    return [
        service.record("shared", f"{prefix}{index}", "explore", "Independent observation")["record"]["sequence"]
        for index in range(8)
    ]


def test_independent_processes_append_without_lost_or_interleaved_sequences(tmp_path: Path) -> None:
    with ProcessPoolExecutor(max_workers=2) as pool:
        writers = [pool.submit(_append_from_process, tmp_path, prefix) for prefix in ("left", "right")]
        sequences = [sequence for writer in writers for sequence in writer.result(timeout=40)]
    assert sorted(sequences) == list(range(1, 17))
    assert workspace(tmp_path).read("shared")["record_count"] == 16
