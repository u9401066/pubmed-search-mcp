"""Regression tests for Chronicle revision identity, persistence, and diffs."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

import pytest

from pubmed_search.application.chronicle.assembler import assemble_chronicle, derive_chronicle_id
from pubmed_search.application.chronicle.differ import diff_chronicles
from pubmed_search.application.chronicle.service import ChronicleService
from pubmed_search.application.chronicle.store import ChronicleStore
from pubmed_search.domain.entities.chronicle import (
    ChronicleBranch,
    ChronicleEntry,
    ChronicleEntryStatus,
    ChronicleEntryType,
    ChronicleInputScope,
    ChronicleSnapshot,
    EvidenceArticle,
    EvidenceBundle,
)
from pubmed_search.domain.entities.timeline import MilestoneType, ResearchTimeline, TimelineEvent

if TYPE_CHECKING:
    from pathlib import Path


def _snapshot(
    chronicle_id: str,
    revision: int,
    *,
    topic: str = "Topic Alpha",
    scope: ChronicleInputScope | None = None,
    entries: list[ChronicleEntry] | None = None,
    branches: list[ChronicleBranch] | None = None,
) -> ChronicleSnapshot:
    """Build a compact, deterministic snapshot for persistence tests."""
    return ChronicleSnapshot(
        chronicle_id=chronicle_id,
        topic=topic,
        revision=revision,
        input_scope=scope or ChronicleInputScope(mode="topic", query=topic),
        entries=list(entries or []),
        branches=list(branches or []),
        created_at="2020-01-01T00:00:00+00:00",
        updated_at=f"2020-01-{revision:02d}T00:00:00+00:00",
    )


def _append_in_process(arguments: tuple[str, str]) -> int:
    """Append one revision in a spawned process and return its allocation."""
    root_dir, chronicle_id = arguments
    store = ChronicleStore(root_dir)
    snapshot = store.append(
        chronicle_id,
        lambda revision, _previous: _snapshot(chronicle_id, revision),
    )
    return snapshot.revision


class EmptyEvidenceProvider:
    """Deterministic evidence provider recording normalized PMID calls."""

    def __init__(self) -> None:
        self.pmid_calls: list[list[str]] = []

    async def build_timeline(self, topic: str, **_kwargs: Any) -> ResearchTimeline:
        """Return one stable topic event so persistence invariants can be tested."""
        return ResearchTimeline(
            topic=topic,
            events=[_event("1")],
            metadata={"source_counts": {"pubmed": 1}},
        )

    async def build_timeline_from_pmids(
        self,
        pmids: list[str],
        topic: str = "Custom Timeline",
        auto_periods: bool = True,
    ) -> ResearchTimeline:
        """Return explicit-scope events and record their normalized order."""
        del auto_periods
        self.pmid_calls.append(list(pmids))
        return ResearchTimeline(
            topic=topic,
            events=[_event(pmid) for pmid in pmids],
            metadata={"source_counts": {"pubmed": len(pmids)}},
        )


def _event(pmid: str, *, year: int = 2020, milestone_type: MilestoneType = MilestoneType.OTHER) -> TimelineEvent:
    """Build one minimal evidence event for service-level persistence tests."""
    return TimelineEvent(
        pmid=pmid,
        year=year,
        milestone_type=milestone_type,
        title=f"Paper {pmid}",
        milestone_label="Background publication",
    )


def test_save_never_overwrites_an_immutable_revision(tmp_path: Path) -> None:
    store = ChronicleStore(tmp_path / "chronicles")
    chronicle_id = "topic-alpha-00000001"
    store.save(_snapshot(chronicle_id, 1, topic="Original topic"))

    with pytest.raises(FileExistsError, match="immutable"):
        store.save(_snapshot(chronicle_id, 1, topic="Replacement topic"))

    restored = store.load(chronicle_id, 1)
    assert restored is not None
    assert restored.topic == "Original topic"


def test_commit_next_compatibility_callback_keeps_original_created_at(tmp_path: Path) -> None:
    store = ChronicleStore(tmp_path / "chronicles")
    chronicle_id = "topic-alpha-commit-next"
    received_created_at: list[str | None] = []

    def build_snapshot(revision: int, created_at: str | None) -> ChronicleSnapshot:
        received_created_at.append(created_at)
        snapshot = _snapshot(chronicle_id, revision)
        if created_at is not None:
            snapshot.created_at = created_at
        return snapshot

    first = store.commit_next(chronicle_id, build_snapshot)
    second = store.commit_next(chronicle_id, build_snapshot)

    assert first.revision == 1
    assert second.revision == 2
    assert received_created_at == [None, first.created_at]
    assert second.created_at == first.created_at
    assert store.list_revisions(chronicle_id) == [1, 2]


def test_nonfinite_snapshot_values_are_rejected_before_revision_publication(tmp_path: Path) -> None:
    store = ChronicleStore(tmp_path / "chronicles")
    chronicle_id = "topic-alpha-nonfinite"
    snapshot = _snapshot(
        chronicle_id,
        1,
        entries=[
            ChronicleEntry(
                entry_id="entry-nan",
                entry_type=ChronicleEntryType.BACKGROUND,
                title="Invalid confidence",
                time_start="2020",
                summary_claim="Invalid numeric value.",
                confidence=float("nan"),
            )
        ],
    )

    with pytest.raises(ValueError, match="Out of range float"):
        store.save(snapshot)

    assert store.list_revisions(chronicle_id) == []


def test_out_of_order_import_cannot_regress_latest_index(tmp_path: Path) -> None:
    store = ChronicleStore(tmp_path / "chronicles")
    chronicle_id = "topic-alpha-00000002"
    store.save(_snapshot(chronicle_id, 1))
    store.save(_snapshot(chronicle_id, 3))
    store.save(_snapshot(chronicle_id, 2))

    index = json.loads((store.root_dir / chronicle_id / "index.json").read_text(encoding="utf-8"))
    assert index["latest_revision"] == 3
    assert store.latest_revision(chronicle_id) == 3
    assert store.load(chronicle_id).revision == 3
    assert store.list_revisions(chronicle_id) == [1, 2, 3]


def test_index_failure_after_durable_revision_does_not_report_append_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChronicleStore(tmp_path / "chronicles")
    chronicle_id = "topic-alpha-crash-consistency"
    store.save(_snapshot(chronicle_id, 1))
    index_path = store.root_dir / chronicle_id / "index.json"
    original_write_index = store._write_index_atomic

    def fail_index_refresh(_chronicle_dir: Path, _snapshot_value: ChronicleSnapshot) -> None:
        raise OSError("simulated index device failure")

    monkeypatch.setattr(store, "_write_index_atomic", fail_index_refresh)
    appended = store.append(
        chronicle_id,
        lambda revision, _previous: _snapshot(chronicle_id, revision),
    )

    assert appended.revision == 2
    assert store.load(chronicle_id, 2) == appended
    assert json.loads(index_path.read_text(encoding="utf-8"))["latest_revision"] == 1
    assert store.list_chronicles()[0]["latest_revision"] == 2
    assert store.find_chronicle_ids_by_topic("Topic Alpha") == [chronicle_id]

    monkeypatch.setattr(store, "_write_index_atomic", original_write_index)
    assert store.list_chronicles()[0]["latest_revision"] == 2
    assert json.loads(index_path.read_text(encoding="utf-8"))["latest_revision"] == 2


@pytest.mark.parametrize("index_state", ["missing", "corrupt", "stale"])
def test_list_and_find_rebuild_index_cache_from_revision_source_of_truth(
    tmp_path: Path,
    index_state: str,
) -> None:
    store = ChronicleStore(tmp_path / "chronicles")
    chronicle_id = f"topic-alpha-{index_state}-index"
    store.save(_snapshot(chronicle_id, 1))
    store.save(_snapshot(chronicle_id, 2))
    index_path = store.root_dir / chronicle_id / "index.json"

    def damage_index() -> None:
        if index_state == "missing":
            index_path.unlink(missing_ok=True)
        elif index_state == "corrupt":
            index_path.write_text("{not-json", encoding="utf-8")
        else:
            index_path.write_text(
                json.dumps(
                    {
                        "chronicle_id": chronicle_id,
                        "topic": "Stale Topic",
                        "latest_revision": 1,
                    }
                ),
                encoding="utf-8",
            )

    damage_index()
    assert store.find_chronicle_ids_by_topic("Topic Alpha") == [chronicle_id]
    repaired = json.loads(index_path.read_text(encoding="utf-8"))
    assert repaired["topic"] == "Topic Alpha"
    assert repaired["latest_revision"] == 2

    damage_index()
    assert store.list_chronicles(topic="Topic Alpha") == [
        {
            "chronicle_id": chronicle_id,
            "topic": "Topic Alpha",
            "latest_revision": 2,
            "created_at": "2020-01-01T00:00:00+00:00",
            "updated_at": "2020-01-02T00:00:00+00:00",
            "entry_count": 0,
            "evidence_count": 0,
            "audit_status": "pass",
            "mode": "topic",
        }
    ]
    assert json.loads(index_path.read_text(encoding="utf-8"))["latest_revision"] == 2


def test_threaded_append_allocates_unique_complete_revisions(tmp_path: Path) -> None:
    store = ChronicleStore(tmp_path / "chronicles")
    chronicle_id = "topic-alpha-00000003"

    def append_once(_index: int) -> int:
        return store.append(
            chronicle_id,
            lambda revision, _previous: _snapshot(chronicle_id, revision),
        ).revision

    with ThreadPoolExecutor(max_workers=8) as executor:
        allocated = list(executor.map(append_once, range(8)))

    assert sorted(allocated) == list(range(1, 9))
    assert store.list_revisions(chronicle_id) == list(range(1, 9))
    chronicle_dir = store.root_dir / chronicle_id
    for revision in range(1, 9):
        data = json.loads((chronicle_dir / f"revision-{revision}.json").read_text(encoding="utf-8"))
        assert data["revision"] == revision
    assert not list(chronicle_dir.glob("*.tmp"))


def test_spawned_processes_allocate_unique_revisions(tmp_path: Path) -> None:
    root_dir = str(tmp_path / "chronicles")
    chronicle_id = "topic-alpha-00000004"
    context = multiprocessing.get_context("spawn")

    with ProcessPoolExecutor(max_workers=4, mp_context=context) as executor:
        allocated = list(executor.map(_append_in_process, [(root_dir, chronicle_id)] * 4))

    store = ChronicleStore(root_dir)
    assert sorted(allocated) == [1, 2, 3, 4]
    assert store.list_revisions(chronicle_id) == [1, 2, 3, 4]


def test_exact_topic_lookup_normalizes_unicode_case_and_whitespace(tmp_path: Path) -> None:
    store = ChronicleStore(tmp_path / "chronicles")
    store.save(_snapshot("topic-a-00000001", 1, topic="Cafe\u0301   Research"))
    store.save(_snapshot("topic-a-00000002", 1, topic="CAFÉ Research"))
    store.save(_snapshot("topic-b-00000001", 1, topic="Café Research Methods"))

    assert store.find_chronicle_ids_by_topic("  café\t research ") == [
        "topic-a-00000001",
        "topic-a-00000002",
    ]
    service = ChronicleService(EmptyEvidenceProvider(), store)
    assert service.find_chronicle_ids_by_topic("CAFÉ RESEARCH") == [
        "topic-a-00000001",
        "topic-a-00000002",
    ]
    assert derive_chronicle_id("Café   Research") == derive_chronicle_id("Cafe\u0301 Research")
    assert derive_chronicle_id("Café Research") == derive_chronicle_id("CAFÉ RESEARCH")


@pytest.mark.asyncio
async def test_pmid_only_scope_identity_is_sorted_unique_and_set_specific(tmp_path: Path) -> None:
    store = ChronicleStore(tmp_path / "chronicles")
    provider = EmptyEvidenceProvider()
    service = ChronicleService(provider, store)

    first = await service.build(pmids=["20", "10", "20", " 00010 "])
    same_scope = await service.build(pmids=["10", "20"])
    different_scope = await service.build(pmids=["10", "30"])

    assert provider.pmid_calls == [["10", "20"], ["10", "20"], ["10", "30"]]
    assert first.input_scope.pmids == ["10", "20"]
    assert same_scope.chronicle_id == first.chronicle_id
    assert same_scope.revision == 2
    assert different_scope.chronicle_id != first.chronicle_id
    assert different_scope.revision == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_pmid", ["doi:10.1000/182", "123abc456", "0", "１２３", 123])
async def test_service_rejects_noncanonical_pmid_tokens(tmp_path: Path, invalid_pmid: object) -> None:
    service = ChronicleService(EmptyEvidenceProvider(), ChronicleStore(tmp_path / "chronicles"))

    with pytest.raises(ValueError, match="positive ASCII-digit PubMed IDs"):
        await service.build(pmids=[invalid_pmid])  # type: ignore[list-item]


@pytest.mark.asyncio
async def test_service_rejects_topic_discontinuity_without_writing_revision(tmp_path: Path) -> None:
    store = ChronicleStore(tmp_path / "chronicles")
    service = ChronicleService(EmptyEvidenceProvider(), store)
    first = await service.build(topic="Topic Alpha")

    with pytest.raises(ValueError, match="belongs to topic"):
        await service.build(topic="Topic Beta", chronicle_id=first.chronicle_id)

    assert store.list_revisions(first.chronicle_id) == [1]


@pytest.mark.asyncio
async def test_explicit_id_without_topic_continues_its_stored_topic(tmp_path: Path) -> None:
    store = ChronicleStore(tmp_path / "chronicles")
    service = ChronicleService(EmptyEvidenceProvider(), store)
    first = await service.build(topic="Topic Alpha")

    second = await service.build(pmids=["1"], chronicle_id=first.chronicle_id)

    assert second.topic == "Topic Alpha"
    assert second.revision == 2
    assert second.input_scope.query == "Topic Alpha"


@pytest.mark.asyncio
async def test_service_does_not_publish_an_empty_evidence_revision(tmp_path: Path) -> None:
    class NoEvidenceProvider(EmptyEvidenceProvider):
        async def build_timeline(self, topic: str, **_kwargs: Any) -> ResearchTimeline:
            return ResearchTimeline(topic=topic, events=[], metadata={"source_counts": {"pubmed": 0}})

    store = ChronicleStore(tmp_path / "chronicles")
    service = ChronicleService(NoEvidenceProvider(), store)

    with pytest.raises(ValueError, match="no Chronicle revision was saved"):
        await service.build(topic="No matches")

    assert store.list_chronicles() == []


@pytest.mark.asyncio
async def test_blocking_store_append_runs_off_the_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ChronicleStore(tmp_path / "chronicles")
    original_append = store.append

    def delayed_append(*args: Any, **kwargs: Any) -> ChronicleSnapshot:
        time.sleep(0.12)
        return original_append(*args, **kwargs)

    monkeypatch.setattr(store, "append", delayed_append)
    service = ChronicleService(EmptyEvidenceProvider(), store)
    build_task = asyncio.create_task(service.build(topic="Nonblocking persistence"))
    started = time.monotonic()
    await asyncio.sleep(0.02)
    heartbeat_elapsed = time.monotonic() - started
    await build_task

    assert heartbeat_elapsed < 0.08


def test_entry_identity_survives_year_and_classifier_correction() -> None:
    chronicle_id = "stable-entry-identity"
    before = assemble_chronicle(
        topic="Therapy",
        timeline=ResearchTimeline("Therapy", [_event("123", year=2020, milestone_type=MilestoneType.OTHER)]),
        chronicle_id=chronicle_id,
        revision=1,
    )
    after = assemble_chronicle(
        topic="Therapy",
        timeline=ResearchTimeline(
            "Therapy",
            [_event("123", year=2021, milestone_type=MilestoneType.RANDOMIZED_TRIAL)],
        ),
        chronicle_id=chronicle_id,
        revision=2,
    )

    assert before.entries[0].entry_id == after.entries[0].entry_id
    delta = diff_chronicles(before, after)
    assert delta["entries"]["added"] == []
    assert delta["entries"]["retired"] == []
    assert delta["entries"]["updated"][0]["entry_id"] == before.entries[0].entry_id


def test_missing_entry_is_never_declared_conclusively_retired() -> None:
    entry = ChronicleEntry(
        entry_id="entry-observed",
        entry_type=ChronicleEntryType.BACKGROUND,
        title="Observed paper",
        time_start="2020",
        summary_claim="Observed in the earlier ranked sample.",
    )
    before = _snapshot("topic-alpha-absence", 1, entries=[entry])
    after = _snapshot("topic-alpha-absence", 2)

    delta = diff_chronicles(before, after)

    assert delta["interpretation"]["retired_entries_are_conclusive"] is False
    assert delta["interpretation"]["absence_semantics"] == "not_observed_in_revision"
    assert delta["entries"]["removed_from_view"] == delta["entries"]["retired"]
    assert delta["entries"]["not_observed_in_revision"] == delta["entries"]["retired"]


def test_diff_reports_scope_entry_evidence_role_and_branch_changes() -> None:
    chronicle_id = "topic-alpha-00000005"
    before_article = EvidenceArticle(title="Original paper", pmid="123", journal="Old Journal", year=2020)
    after_article = EvidenceArticle(title="Corrected paper", pmid="123", journal="New Journal", year=2021)
    before_entry = ChronicleEntry(
        entry_id="entry-stable",
        entry_type=ChronicleEntryType.MILESTONE,
        title="Original milestone",
        time_start="2020",
        summary_claim="Original claim",
        branch_id="branch-stable",
        confidence=0.4,
        evidence=EvidenceBundle(
            supporting_articles=[before_article],
            verification_summary={"status": "pending"},
            source_coverage={"pubmed": 1},
        ),
        tags=["original"],
        provenance={"source": "search"},
    )
    after_entry = ChronicleEntry(
        entry_id="entry-stable",
        entry_type=ChronicleEntryType.METHOD,
        title="Revised milestone",
        time_start="2021-02",
        time_end="2022",
        summary_claim="Revised claim",
        branch_id="branch-stable",
        confidence=0.9,
        status=ChronicleEntryStatus.CONTESTED,
        evidence=EvidenceBundle(
            contradicting_articles=[after_article],
            verification_summary={"status": "verified"},
            source_coverage={"pubmed": 1, "crossref": 1},
        ),
        tags=["revised"],
        provenance={"source": "pipeline"},
    )
    before = _snapshot(
        chronicle_id,
        1,
        scope=ChronicleInputScope(mode="pmids", query="Topic Alpha", pmids=["123"]),
        entries=[before_entry],
        branches=[ChronicleBranch("branch-stable", "Original branch", entry_ids=["entry-stable"])],
    )
    after = _snapshot(
        chronicle_id,
        2,
        scope=ChronicleInputScope(mode="pmids", query="Topic Alpha", pmids=["123", "456"]),
        entries=[after_entry],
        branches=[
            ChronicleBranch(
                "branch-stable",
                "Revised branch",
                description="New description",
                parent_branch_id="parent-branch",
                entry_ids=["entry-stable", "entry-new"],
                confidence=0.5,
                tags=["new"],
            )
        ],
    )

    delta = diff_chronicles(before, after)

    assert delta["scope_changed"] is True
    assert delta["scope"]["changes"]["pmids"]["to"] == ["123", "456"]
    entry_changes = delta["entries"]["updated"][0]["changes"]
    assert {
        "title",
        "time_start",
        "time_end",
        "summary_claim",
        "entry_type",
        "status",
        "confidence",
        "tags",
        "provenance",
        "evidence",
    } <= entry_changes.keys()
    assert entry_changes["evidence"]["role_changes"] == [
        {"evidence_id": "pmid:123", "from": ["supporting"], "to": ["contradicting"]}
    ]
    assert entry_changes["evidence"]["updated"][0]["changes"]["journal"] == {
        "from": "Old Journal",
        "to": "New Journal",
    }
    assert delta["branches"]["updated"][0]["changes"]["parent_branch_id"]["to"] == "parent-branch"
    assert delta["evidence"]["updated"][0]["changes"]["title"]["to"] == "Corrected paper"


@pytest.mark.parametrize("before_revision,after_revision", [(2, 1), (2, 2)])
def test_diff_requires_strictly_forward_revisions(before_revision: int, after_revision: int) -> None:
    chronicle_id = "topic-alpha-00000006"

    with pytest.raises(ValueError, match="forward and strictly increasing"):
        diff_chronicles(
            _snapshot(chronicle_id, before_revision),
            _snapshot(chronicle_id, after_revision),
        )


def test_diff_rejects_topic_discontinuity_even_with_same_id() -> None:
    chronicle_id = "topic-alpha-00000007"

    with pytest.raises(ValueError, match="topic discontinuity"):
        diff_chronicles(
            _snapshot(chronicle_id, 1, topic="Topic Alpha"),
            _snapshot(chronicle_id, 2, topic="Topic Beta"),
        )
