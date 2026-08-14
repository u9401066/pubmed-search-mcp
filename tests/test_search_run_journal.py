"""Unified-search lifecycle integration with the durable session journal."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from pubmed_search.application.session.manager import SessionManager
from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.presentation.mcp_server.tools import search_run_journal as journal_module
from pubmed_search.presentation.mcp_server.tools.search_run_journal import (
    SearchRunJournal,
    compact_search_run_handoff,
    search_run_markdown_note,
)


@pytest.mark.asyncio
async def test_journal_persists_plan_attempts_partial_result_and_exact_replay(tmp_path) -> None:
    manager = SessionManager(data_dir=tmp_path)
    request = {
        "query": "melanoma AND immunotherapy",
        "limit": 25,
        "sources": "pubmed,semantic_scholar",
        "ranking": "quality",
        "output_format": "json",
        "filters": "year:2020-2026",
        "options": "systematic,no_relax",
    }
    journal = await SearchRunJournal.start(query=request["query"], request=request, manager=manager)
    run_id = journal.run_id
    assert run_id

    plan = SimpleNamespace(
        query=request["query"],
        provider_neutral_query=request["query"],
        request=SimpleNamespace(retrieval_mode="systematic"),
        effective_min_year=2020,
        effective_max_year=2026,
        analysis=SimpleNamespace(to_dict=lambda: {"intent": "systematic"}),
        deep_strategies=[],
        dispatch_sources=["pubmed", "semantic_scholar"],
    )
    await journal.plan(plan)

    article = UnifiedArticle(
        title="Checkpointed evidence",
        primary_source="pubmed",
        pmid="12345",
        doi="10.1000/example",
    )
    execution = SimpleNamespace(
        ranked=[article],
        source_api_counts={"pubmed": (1, 42), "semantic_scholar": (0, None)},
        source_statuses={"pubmed": "ok", "semantic_scholar": "error"},
        source_metadata={
            "pubmed": {"logical_query": request["query"], "physical_query": "compiled-pubmed"},
            "semantic_scholar": {"logical_query": request["query"], "physical_query": "compiled-s2"},
        },
        source_errors=[
            {
                "source": "semantic_scholar",
                "status": "rate_limited",
                "message": "HTTP 429",
                "retryable": True,
            }
        ],
    )
    await journal.record_execution(execution, plan)
    artifact = {
        "artifact_id": "artifact-1",
        "artifact_uri": "artifact://session/artifact-1",
        "tool": "unified_search",
        "kind": "search_results",
        "primary_file": "results.json",
        "sha256": "abc",
        "files": {},
    }
    completed = await journal.complete(execution, artifact=artifact)

    assert completed is not None
    assert completed["status"] == "partial"
    assert [attempt["status"] for attempt in completed["source_attempts"]] == ["ok", "rate_limited"]
    assert completed["result"]["references"][0]["doi"] == "10.1000/example"
    assert completed["artifact"]["artifact_uri"] == artifact["artifact_uri"]
    replay = manager.get_search_run_replay(run_id)
    assert replay is not None
    assert replay["arguments"] == request

    handoff = compact_search_run_handoff(completed)
    assert handoff is not None
    assert handoff["run_id"] == run_id
    assert handoff["replay"]["arguments"] == {"action": "replay_search", "run_id": run_id}
    note = search_run_markdown_note(completed)
    assert run_id in note
    assert 'action="replay_search"' in note


@pytest.mark.asyncio
async def test_journal_records_cancelled_terminal_state(tmp_path) -> None:
    manager = SessionManager(data_dir=tmp_path)
    journal = await SearchRunJournal.start(query="cancel me", request={"query": "cancel me"}, manager=manager)

    await journal.cancel()

    run = manager.get_search_run(journal.run_id or "")
    assert run is not None
    assert run["status"] == "cancelled"
    assert run["recoverable"] is True


@pytest.mark.asyncio
async def test_cancellation_during_atomic_start_does_not_leave_a_started_run(tmp_path) -> None:
    started = threading.Event()
    release = threading.Event()

    class SlowStartManager(SessionManager):
        def start_search_run(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            started.set()
            release.wait(timeout=5)
            return super().start_search_run(*args, **kwargs)

    manager = SlowStartManager(data_dir=tmp_path)
    task = asyncio.create_task(
        SearchRunJournal.start(
            query="cancel during start",
            request={"query": "cancel during start"},
            manager=manager,
        )
    )
    assert await asyncio.to_thread(started.wait, 5)

    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    runs = manager.list_search_runs(limit=10)
    assert len(runs) == 1
    assert runs[0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_journal_marks_an_all_source_failure_as_failed(tmp_path) -> None:
    manager = SessionManager(data_dir=tmp_path)
    journal = await SearchRunJournal.start(
        query="unavailable evidence",
        request={"query": "unavailable evidence", "sources": "pubmed,openalex"},
        manager=manager,
    )
    execution = SimpleNamespace(
        ranked=[],
        source_errors=[
            {"source": "pubmed", "status": "timeout", "message": "timed out", "retryable": True},
            {"source": "openalex", "status": "error", "message": "invalid response", "retryable": False},
        ],
    )

    completed = await journal.complete(execution, artifact=None)

    assert completed is not None
    assert completed["status"] == "failed"
    assert completed["recoverable"] is True
    assert completed["failure"] == {
        "stage": "sources",
        "type": "AllSourcesFailed",
        "message": "All selected search sources failed: openalex, pubmed",
        "retryable": True,
    }
    assert completed["result"]["count"] == 0


@pytest.mark.asyncio
async def test_journal_marks_valid_empty_plus_failed_source_as_partial(tmp_path) -> None:
    manager = SessionManager(data_dir=tmp_path)
    journal = await SearchRunJournal.start(
        query="rare bounded topic",
        request={"query": "rare bounded topic", "sources": "pubmed,openalex"},
        manager=manager,
    )
    execution = SimpleNamespace(
        ranked=[],
        source_statuses={"pubmed": "empty", "openalex": "error"},
        source_errors=[{"source": "openalex", "status": "rate_limited", "message": "HTTP 429", "retryable": True}],
    )

    completed = await journal.complete(execution, artifact=None)

    assert completed is not None
    assert completed["status"] == "partial"
    assert completed["failure"] is None


@pytest.mark.asyncio
async def test_journal_is_a_noop_when_persistence_is_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(journal_module, "get_session_manager", lambda: None)
    journal = await SearchRunJournal.start(query="ephemeral", request={"query": "ephemeral"}, manager=None)

    assert journal.run_id is None
    assert compact_search_run_handoff(None) is None


@pytest.mark.asyncio
async def test_terminal_write_failure_falls_back_to_a_durable_failed_run(tmp_path) -> None:
    class FailCompletionManager(SessionManager):
        def complete_search_run(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise OSError("synthetic completion failure")

    manager = FailCompletionManager(data_dir=tmp_path)
    journal = await SearchRunJournal.start(query="fallback", request={"query": "fallback"}, manager=manager)
    execution = SimpleNamespace(ranked=[], source_errors=[], source_statuses={"pubmed": "empty"})

    completed = await journal.complete(execution, artifact=None)

    assert completed is not None
    assert completed["status"] == "failed"
    assert completed["failure"]["stage"] == "persistence"
    persisted = manager.get_search_run(journal.run_id or "")
    assert persisted is not None
    assert persisted["status"] == "failed"


@pytest.mark.asyncio
async def test_unrecoverable_terminal_write_returns_truthful_transient_handoff(tmp_path) -> None:
    class UnavailableManager(SessionManager):
        def complete_search_run(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise OSError("synthetic completion failure")

        def fail_search_run(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise OSError("synthetic fallback failure")

    manager = UnavailableManager(data_dir=tmp_path)
    journal = await SearchRunJournal.start(query="unavailable", request={"query": "unavailable"}, manager=manager)
    execution = SimpleNamespace(ranked=[], source_errors=[], source_statuses={"pubmed": "empty"})

    completed = await journal.complete(execution, artifact=None)
    handoff = compact_search_run_handoff(completed)

    assert handoff is not None
    assert handoff["status"] == "history_unavailable"
    assert handoff["intended_status"] == "completed"
    assert handoff["history_available"] is False
    assert "inspect" not in handoff
    assert "replay" not in handoff
    assert "recovery is not guaranteed" in search_run_markdown_note(completed)


@pytest.mark.asyncio
async def test_start_write_failure_is_visible_in_final_handoff(tmp_path) -> None:
    class FailStartManager(SessionManager):
        def start_search_run(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise OSError("synthetic start failure")

    manager = FailStartManager(data_dir=tmp_path)
    journal = await SearchRunJournal.start(query="no start", request={"query": "no start"}, manager=manager)
    execution = SimpleNamespace(ranked=[], source_errors=[], source_statuses={"pubmed": "empty"})

    completed = await journal.complete(execution, artifact=None)
    handoff = compact_search_run_handoff(completed)

    assert journal.run_id
    assert handoff is not None
    assert handoff["status"] == "history_unavailable"
    assert handoff["history_available"] is False
