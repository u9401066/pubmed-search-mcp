"""Screening log, update-search queueing and PRISMA 2020 flow counts."""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from pubmed_search.application.pipeline.screening import ScreeningService, render_prisma_flow_markdown
from pubmed_search.application.pipeline.store import PipelineStore
from pubmed_search.application.pipeline.validator import parse_and_validate_config
from pubmed_search.domain.entities.pipeline import PipelineRun
from pubmed_search.infrastructure.pipeline_screening import SQLiteScreeningStore
from pubmed_search.presentation.mcp_server.tools.pipeline_screening import register_pipeline_screening_tools
from pubmed_search.presentation.mcp_server.tools.pipeline_tools import PipelineToolRuntime, register_pipeline_tools
from pubmed_search.presentation.mcp_server.tools.unified_pipeline import _execute_pipeline_mode_outcome
from tests.test_pipeline_exhaustive import QUERY, FakeHistorySearcher

if TYPE_CHECKING:
    from pathlib import Path


def _run(run_id: str, pmids: list[str], *, exhaustive: bool = True) -> PipelineRun:
    return PipelineRun(
        run_id=run_id,
        pipeline_name="review",
        started=datetime(2026, 1, 1, tzinfo=timezone.utc),
        pmids=pmids,
        record_version=2,
        record_basis="final_step_full" if exhaustive else "ranked_output",
        retrieval={"mode": "exhaustive" if exhaustive else "bounded", "exhaustive": exhaustive},
        searches=[{"database": "PubMed"}],
    )


def _service(path: Path) -> ScreeningService:
    return ScreeningService(SQLiteScreeningStore(path / "review.sqlite3"))


def _decide(pmid: str, decision: str, stage: str = "title_abstract", **extra: Any) -> dict[str, Any]:
    return {"pmid": pmid, "stage": stage, "decision": decision, **extra}


def test_decisions_are_idempotent_atomic_and_survive_restart(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = service.register_run(_run("run1", ["1", "2", "3"]))
    assert (first["new_count"], first["replayed"]) == (3, False)
    assert service.register_run(_run("run1", ["1", "2", "3"]))["replayed"] is True

    recorded = service.record([_decide("1", "include"), _decide("2", "exclude", reason="wrong population")])
    assert (recorded["recorded"], recorded["replayed"]) == (2, 0)
    retry = _service(tmp_path).record([_decide("1", "include"), _decide("2", "exclude", reason="wrong population")])
    assert (retry["recorded"], retry["replayed"]) == (0, 2)

    with pytest.raises(ValueError, match="different content"):
        service.record(
            [_decide("3", "include", decision_id="fixed-id"), _decide("3", "exclude", decision_id="fixed-id")]
        )
    # All-or-nothing: the valid first decision of the rejected batch was not kept.
    assert _service(tmp_path).log(pmid="3")["total"] == 0
    with pytest.raises(ValueError, match="not identified"):
        service.record([_decide("3", "include"), _decide("999", "include")])
    assert _service(tmp_path).log(pmid="3")["total"] == 0
    with pytest.raises(ValueError, match="needs a title/abstract include"):
        service.record([_decide("2", "include", stage="full_text")])
    with pytest.raises(ValueError, match="require a reason"):
        service.record([_decide("1", "exclude", stage="full_text")])

    reopened = _service(tmp_path)
    flow = reopened.flow()
    assert flow["screening"]["records_screened"] == 3
    assert flow["screening"]["records_excluded"] == 1
    assert flow["screening"]["records_awaiting_screening"] == 1
    assert [item["pmid"] for item in reopened.queue(stage="title_abstract")["items"]] == ["3"]
    assert [item["pmid"] for item in reopened.queue(stage="full_text")["items"]] == ["1"]


def test_returning_to_an_earlier_decision_is_recorded_and_counted(tmp_path: Path) -> None:
    """include → exclude → include is a reversal, not a replay of the first include."""
    service = _service(tmp_path)
    service.register_run(_run("run1", ["111"]))

    outcomes = [service.record([_decide("111", decision)]) for decision in ("include", "exclude", "include")]

    assert [(result["recorded"], result["replayed"]) for result in outcomes] == [(1, 0), (1, 0), (1, 0)]
    assert len({result["decisions"][0]["decision_id"] for result in outcomes}) == 3
    flow = _service(tmp_path).flow()["screening"]
    assert flow["records_excluded"] == 0
    assert flow["reports_sought_for_retrieval"] == 1
    assert [row["decision"] for row in service.log(pmid="111")["decisions"]] == ["include", "exclude", "include"]

    # A retry of the latest decision (same reviewer, same content) is still a replay...
    retry = service.record([_decide("111", "include")])
    assert (retry["recorded"], retry["replayed"]) == (0, 1)
    assert retry["decisions"][0]["decision_id"] == outcomes[2]["decisions"][0]["decision_id"]
    # ...and so is a duplicate inside one batch, while a changed note is a new decision.
    batch = service.record([_decide("111", "exclude"), _decide("111", "exclude")])
    assert (batch["recorded"], batch["replayed"]) == (1, 1)
    noted = service.record([_decide("111", "exclude", note="second look")])
    assert (noted["recorded"], noted["replayed"]) == (1, 0)
    # Another reviewer's identical decision is that reviewer's own first decision.
    other = service.record([_decide("111", "exclude", note="second look", reviewer="reviewer_2")])
    assert (other["recorded"], other["replayed"]) == (1, 0)
    assert service.log(pmid="111")["total"] == 6


def test_client_decision_id_keeps_a_retry_idempotent_after_later_decisions(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.register_run(_run("run1", ["7"]))
    service.record([_decide("7", "include", decision_id="ta-7-a")])
    service.record([_decide("7", "exclude", decision_id="ta-7-b")])

    late_retry = service.record([_decide("7", "include", decision_id="ta-7-a")])

    assert (late_retry["recorded"], late_retry["replayed"]) == (0, 1)
    assert service.flow()["screening"]["records_excluded"] == 1
    # An explicit new key records a new decision even when it repeats the latest one.
    repeat = service.record([_decide("7", "exclude", decision_id="ta-7-c")])
    assert (repeat["recorded"], repeat["replayed"]) == (1, 0)


def test_update_run_queues_only_new_records_and_prisma_counts(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.register_run(_run("run1", ["1", "2", "3", "4", "5"]))
    service.record([_decide(pmid, "exclude", reason="off topic") for pmid in ("4", "5")])
    service.record([_decide(pmid, "include") for pmid in ("1", "2")] + [_decide("3", "maybe")])

    update = service.register_run(_run("run2", ["2", "3", "4", "6", "7"]))
    assert update["new_count"] == 2
    queue = service.queue(stage="title_abstract")
    assert [(item["pmid"], item["first_run_id"]) for item in queue["items"]] == [("6", "run2"), ("7", "run2")]
    assert service.queue(stage="title_abstract", run_id="run1")["total"] == 0

    service.record(
        [
            _decide("1", "include", stage="full_text"),
            _decide("2", "exclude", stage="full_text", reason="wrong comparator"),
            _decide("3", "exclude", stage="full_text", reason="not retrieved"),
            _decide("6", "include"),
        ]
    )
    service.record([_decide("6", "exclude", reviewer="reviewer_2")])

    flow = service.flow()
    assert flow["identification"] == {
        "records_identified": 10,
        "records_identified_by_database": {"PubMed": 10},
        "records_marked_ineligible_by_automation": 0,
        "duplicate_records_removed": 3,
        "records_after_duplicates_removed": 7,
    }
    screening = flow["screening"]
    assert screening["records_screened"] == 7
    assert screening["records_excluded"] == 3  # 4, 5 and 6 (latest decision, reviewer_2)
    assert screening["records_awaiting_screening"] == 1  # 7
    assert screening["reports_sought_for_retrieval"] == 3  # 1, 2, 3 (maybe advances)
    assert screening["reports_not_retrieved"] == 1
    assert screening["reports_assessed_for_eligibility"] == 2
    assert screening["reports_excluded_by_reason"] == {"wrong comparator": 1}
    assert flow["included"]["studies_included"] == 1
    assert flow["conflicts"]["title_abstract"] == 1
    assert [run["new_records_unscreened"] for run in flow["runs"]] == [0, 1]
    assert any("conflict" in warning for warning in flow["warnings"])
    markdown = render_prisma_flow_markdown("review", flow)
    assert "Records identified from databases: 10 (PubMed: 10)" in markdown
    assert "Duplicate records removed (across runs): 3" in markdown
    assert "  - wrong comparator: 1" in markdown


def test_identification_counts_records_removed_by_pipeline_filters(tmp_path: Path) -> None:
    service = _service(tmp_path)
    run = _run("run1", ["1", "2"])
    run.retrieval.update({"identified_count": 5, "removed_by_filters": 3})
    assert service.register_run(run)["identified_count"] == 5
    assert service.register_run(run)["replayed"] is True
    service.register_run(_run("run2", ["2", "3"]))

    flow = service.flow()

    assert flow["identification"] == {
        "records_identified": 7,
        "records_identified_by_database": {"PubMed": 7},
        "records_marked_ineligible_by_automation": 3,
        "duplicate_records_removed": 1,
        "records_after_duplicates_removed": 3,
    }
    assert [run["records_marked_ineligible_by_automation"] for run in flow["runs"]] == [3, 0]
    markdown = render_prisma_flow_markdown("review", flow)
    assert "Records marked ineligible by automation tools (pipeline filter steps): 3" in markdown


def test_version_1_screening_log_is_migrated_in_place(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "review.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE runs (run_id TEXT PRIMARY KEY, sequence INTEGER NOT NULL UNIQUE, database TEXT NOT NULL,
                identified_count INTEGER NOT NULL, new_count INTEGER NOT NULL, exhaustive INTEGER NOT NULL,
                run_started TEXT, registered_at TEXT NOT NULL);
            CREATE TABLE records (pmid TEXT PRIMARY KEY, first_run_id TEXT NOT NULL REFERENCES runs(run_id),
                identified_at TEXT NOT NULL);
            CREATE TABLE decisions (sequence INTEGER PRIMARY KEY AUTOINCREMENT, decision_id TEXT NOT NULL UNIQUE,
                pmid TEXT NOT NULL REFERENCES records(pmid), stage TEXT NOT NULL, decision TEXT NOT NULL,
                reason TEXT, reviewer TEXT NOT NULL, decided_at TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX decisions_by_stage ON decisions(stage, pmid, sequence);
            CREATE INDEX records_by_run ON records(first_run_id);
            INSERT INTO runs VALUES ('run1', 1, 'PubMed', 2, 2, 1, NULL, '2026-01-01T00:00:00Z');
            INSERT INTO records VALUES ('1', 'run1', '2026-01-01T00:00:00Z'), ('2', 'run1', '2026-01-01T00:00:00Z');
            PRAGMA user_version=1;
            """
        )
    service = ScreeningService(SQLiteScreeningStore(path))

    service.record([_decide("1", "exclude")])

    flow = service.flow()
    assert flow["identification"]["records_identified"] == 2
    assert flow["identification"]["records_marked_ineligible_by_automation"] == 0
    assert flow["screening"]["records_excluded"] == 1
    assert service.register_run(_run("run1", ["1", "2"]))["replayed"] is True


def test_bounded_runs_are_not_auto_registered(tmp_path: Path) -> None:
    service = _service(tmp_path)
    assert service.register_if_complete(_run("bounded", ["1"], exhaustive=False)) is None
    explicit = service.register_run(_run("bounded", ["1"], exhaustive=False))
    assert explicit["exhaustive"] is False
    assert service.flow()["warnings"][0].startswith("1 registered run(s) were not exhaustive")


def _decide_from_process(path: str, prefix: str) -> int:
    service = ScreeningService(SQLiteScreeningStore(path))
    total = 0
    for index in range(1, 11):
        result = service.record([_decide(str(index), "include", reviewer=prefix)])
        total += result["recorded"]
    return total


def test_two_processes_record_into_one_log(tmp_path: Path) -> None:
    path = tmp_path / "review.sqlite3"
    ScreeningService(SQLiteScreeningStore(path)).register_run(_run("run1", [str(i) for i in range(1, 11)]))
    with ProcessPoolExecutor(max_workers=2) as pool:
        writers = [pool.submit(_decide_from_process, str(path), prefix) for prefix in ("alice", "bob")]
        assert [writer.result(timeout=40) for writer in writers] == [10, 10]
    service = ScreeningService(SQLiteScreeningStore(path))
    assert service.log(limit=100)["total"] == 20
    assert service.flow()["screening"]["reports_sought_for_retrieval"] == 10
    assert service.flow()["conflicts"]["title_abstract"] == 0


# ---------------------------------------------------------------------------
# Saved-pipeline integration through the MCP tool functions
# ---------------------------------------------------------------------------


def _save_review(store: PipelineStore) -> None:
    result = parse_and_validate_config(
        {
            "steps": [
                {
                    "id": "pubmed",
                    "action": "search",
                    "params": {"query": QUERY, "sources": ["pubmed"], "retrieval": "exhaustive"},
                }
            ],
            "output": {"format": "json", "limit": 10},
        }
    )
    assert result.config is not None
    store.save("review", result.config, scope="workspace")


def _tools(store: PipelineStore) -> dict[str, Any]:
    tools: dict[str, Any] = {}
    mcp = MagicMock()
    mcp.tool = lambda: lambda func: tools.setdefault(func.__name__, func)
    runtime = PipelineToolRuntime(base_store=store)
    register_pipeline_tools(mcp, runtime=runtime)
    register_pipeline_screening_tools(mcp, runtime=runtime)
    return tools


async def test_update_search_feeds_the_screening_queue_automatically(tmp_path: Path) -> None:
    from pubmed_search.presentation.mcp_server.tools.pipeline_screening import (
        _Flow,
        _Queue,
        _RecordDecisions,
    )

    store = PipelineStore(global_data_dir=tmp_path / "global", workspace_dir=tmp_path / "workspace")
    _save_review(store)
    tools = _tools(store)

    await _execute_pipeline_mode_outcome(
        "saved:review", "json", FakeHistorySearcher(["11", "12", "13"]), pipeline_store=store
    )
    queue = json.loads(
        await tools["pipeline_screening"](_Queue(action="queue", pipeline="review", include_abstract=True))
    )
    assert [item["pmid"] for item in queue["items"]] == ["11", "12", "13"]
    assert queue["items"][0]["title"] == "Processed EEG and delirium 11"
    assert queue["items"][0]["abstract"].startswith("Background.")

    decisions = [{"pmid": pmid, "stage": "title_abstract", "decision": "exclude"} for pmid in ("11", "12", "13")]
    recorded = json.loads(
        await tools["pipeline_screening"](
            _RecordDecisions.model_validate({"action": "record", "pipeline": "review", "decisions": decisions})
        )
    )
    assert recorded["recorded"] == 3

    outcome = await _execute_pipeline_mode_outcome(
        "saved:review", "json", FakeHistorySearcher(["11", "12", "13", "14"]), pipeline_store=store
    )
    update_run = json.loads(outcome.response)["run"]["run_id"]
    assert "pipeline_screening" in json.loads(outcome.response)["next"]["screening_queue"]
    queue = json.loads(await tools["pipeline_screening"](_Queue(action="queue", pipeline="review")))
    assert [(item["pmid"], item["first_run_id"]) for item in queue["items"]] == [("14", update_run)]

    flow = await tools["pipeline_screening"](_Flow(action="flow", pipeline="review"))
    assert "Records identified from databases: 7 (PubMed: 7)" in flow
    assert "Duplicate records removed (across runs): 3" in flow

    # Recorded decisions are human work: deletion refuses and removes nothing...
    db_path = store.screening_db_path("review")
    assert db_path.is_file()
    refused = tools["delete_pipeline"](name="review")
    assert "was not deleted" in refused
    assert "3 decisions on 3 PMIDs from 1 reviewer label" in refused
    assert '"action": "log"' in refused
    assert "delete_screening_log=true" in refused
    assert db_path.is_file()
    assert store.exists("review")
    assert len(store.get_history("review", limit=10)) == 2
    assert _service_for(store).decision_summary()["decisions"] == 3

    # ...until the caller explicitly opts in.
    deleted = tools["delete_pipeline"](name="review", delete_screening_log=True)
    assert 'Pipeline "review" deleted' in deleted
    assert "Screening log permanently removed: 3 decisions on 3 PMIDs" in deleted
    assert not db_path.exists()
    assert not store.exists("review")


def _service_for(store: PipelineStore) -> ScreeningService:
    return ScreeningService(SQLiteScreeningStore(store.screening_db_path("review")))


async def test_delete_without_decisions_removes_registered_log_as_before(tmp_path: Path) -> None:
    store = PipelineStore(global_data_dir=tmp_path / "global", workspace_dir=tmp_path / "workspace")
    _save_review(store)
    tools = _tools(store)
    await _execute_pipeline_mode_outcome(
        "saved:review", "json", FakeHistorySearcher(["11", "12"]), pipeline_store=store
    )
    db_path = store.screening_db_path("review")
    assert _service_for(store).decision_summary() == {"decisions": 0, "pmids": 0, "reviewers": 0, "records": 2}

    deleted = tools["delete_pipeline"](name="review")

    assert 'Pipeline "review" deleted' in deleted
    assert "Screening log permanently removed: 0 decisions on 0 PMIDs" in deleted
    assert not db_path.exists()
    assert not store.exists("review")


def test_delete_without_any_log_is_unchanged(tmp_path: Path) -> None:
    store = PipelineStore(global_data_dir=tmp_path / "global", workspace_dir=tmp_path / "workspace")
    _save_review(store)

    deleted = _tools(store)["delete_pipeline"](name="review")

    assert 'Pipeline "review" deleted' in deleted
    assert "Screening log" not in deleted
    assert not store.screening_db_path("review").exists()


def test_store_delete_fails_closed_when_a_log_exists_without_opt_in(tmp_path: Path) -> None:
    from pubmed_search.application.pipeline.store import ScreeningLogPresentError

    store = PipelineStore(global_data_dir=tmp_path / "global", workspace_dir=tmp_path / "workspace")
    _save_review(store)
    _service_for(store).register_run(_run("run1", ["1"]))
    store.save_run("review", _run("20260101_000000_000000_abc", ["1"]))

    with pytest.raises(ScreeningLogPresentError):
        store.delete("review")

    assert store.exists("review")
    assert store.screening_db_path("review").is_file()
    assert store.count_history("review") == 1
    assert store.delete("review", delete_screening_log=True)[1] == 1
    assert not store.screening_db_path("review").exists()


async def test_unknown_pipeline_and_invalid_decisions_are_structured_errors(tmp_path: Path) -> None:
    from pubmed_search.presentation.mcp_server.tools.pipeline_screening import _Flow, _RecordDecisions

    store = PipelineStore(global_data_dir=tmp_path / "global", workspace_dir=tmp_path / "workspace")
    _save_review(store)
    tools = _tools(store)

    missing = json.loads(await tools["pipeline_screening"](_Flow(action="flow", pipeline="nope", format="json")))
    assert "not found" in json.dumps(missing).lower()
    invalid = json.loads(
        await tools["pipeline_screening"](
            _RecordDecisions.model_validate(
                {
                    "action": "record",
                    "pipeline": "review",
                    "decisions": [{"pmid": "1", "stage": "title_abstract", "decision": "include"}],
                }
            )
        )
    )
    assert "not identified" in json.dumps(invalid)
