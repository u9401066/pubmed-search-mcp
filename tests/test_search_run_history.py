"""Crash recovery and round-trip tests for durable unified-search runs."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from pubmed_search.application.session.manager import SessionManager
from pubmed_search.application.session.registry import SessionManagerRegistry
from pubmed_search.shared.tenancy import TenantIdentity, bind_tenant


def _complete_run(manager: SessionManager, index: int) -> str:
    run = manager.start_search_run(
        f"query {index}",
        request={"query": f"query {index}", "limit": 20, "sources": "pubmed,openalex"},
    )
    run_id = str(run["run_id"])
    manager.plan_search_run(
        run_id,
        plan={"logical_query": f"query {index}", "ranking": "balanced"},
        sources=["pubmed", "openalex"],
    )
    manager.record_search_source_attempt(
        run_id,
        "pubmed",
        "completed",
        logical_query=f"query {index}",
        physical_query=f"query {index}[Title/Abstract]",
        returned=1,
        available=1,
    )
    manager.complete_search_run(
        run_id,
        pmids=[str(index)],
        result_refs=[{"source": "pubmed", "pmid": str(index)}],
    )
    return run_id


def test_search_run_round_trips_plan_attempt_results_artifact_and_replay(tmp_path: Path):
    manager = SessionManager(data_dir=str(tmp_path))
    run = manager.start_search_run(
        "remimazolam sedation",
        request={
            "query": "remimazolam sedation",
            "limit": 25,
            "sources": "pubmed,openalex",
            "ranking": "quality",
            "output_format": "json",
            "api_key": "must-not-persist",
            "pipeline": "template: comprehensive\napi_key: must-not-persist",
        },
    )
    run_id = str(run["run_id"])
    manager.plan_search_run(
        run_id,
        plan={"provider_neutral_query": "remimazolam sedation", "retrieval_mode": "systematic"},
        sources=["pubmed", "openalex"],
    )
    manager.record_search_source_attempt(
        run_id,
        "openalex",
        "partial",
        logical_query="remimazolam sedation",
        physical_query="search:remimazolam sedation",
        returned=2,
        available=5,
        metadata={"next_cursor": "cursor", "authorization": "Bearer secret"},
        error="https://api.example.test/works?api_key=secret returned 429",
    )
    completed = manager.complete_search_run(
        run_id,
        pmids=["123"],
        result_count=2,
        result_refs=[
            {"source": "pubmed", "pmid": "123"},
            {"source": "openalex", "id": "W1", "doi": "10.1/example"},
        ],
        warnings=["OpenAlex returned a partial page"],
        status="partial",
    )
    assert completed["status"] == "partial"

    manifest = manager.save_artifact(
        tool="unified_search",
        kind="search_results",
        files={"results.json": {"articles": [{"pmid": "123"}]}, "audit.json": {"status": "warn"}},
        primary_file="results.json",
        summary={"query": "remimazolam sedation", "returned": 2},
    )

    reloaded = SessionManager(data_dir=str(tmp_path))
    restored = reloaded.get_search_run(run_id)
    replay = reloaded.get_search_run_replay(run_id)

    assert restored is not None
    assert restored["status"] == "partial"
    assert restored["plan"]["sources"] == ["pubmed", "openalex"]
    assert restored["source_attempts"][0]["physical_query"] == "search:remimazolam sedation"
    assert restored["source_attempts"][0]["failure"]["message"].endswith("api_key=[REDACTED] returned 429")
    assert restored["source_attempts"][0]["metadata"]["authorization"] == "[REDACTED]"
    assert restored["result"]["count"] == 2
    assert restored["artifact"]["artifact_id"] == manifest["artifact_id"]
    assert restored["artifact"]["artifact_uri"] == manifest["artifact_uri"]
    assert replay == {
        "tool": "unified_search",
        "arguments": {
            "query": "remimazolam sedation",
            "limit": 25,
            "sources": "pubmed,openalex",
            "ranking": "quality",
            "output_format": "json",
            "pipeline": "template: comprehensive\napi_key: [REDACTED]",
        },
        "replay_of": run_id,
        "previous_status": "partial",
    }
    assert "must-not-persist" not in (tmp_path / f"session_{manifest['session_id']}.json").read_text(encoding="utf-8")


def test_restart_marks_in_flight_run_interrupted_and_preserves_exact_replay(tmp_path: Path):
    manager = SessionManager(data_dir=str(tmp_path))
    run = manager.start_search_run(
        "asthma biologics",
        request={"query": "asthma biologics", "limit": 40, "options": "systematic"},
    )
    run_id = str(run["run_id"])
    manager.plan_search_run(run_id, plan={"ranking": "balanced"}, sources=["pubmed"])
    manager.record_search_source_attempt(
        run_id,
        "pubmed",
        "running",
        logical_query="asthma biologics",
        physical_query="asthma biologics[Title/Abstract]",
    )

    reloaded = SessionManager(data_dir=str(tmp_path))
    restored = reloaded.get_search_run(run_id)

    assert restored is not None
    assert restored["status"] == "interrupted"
    assert restored["recoverable"] is True
    assert restored["failure"]["stage"] == "recovery"
    assert restored["source_attempts"][0]["status"] == "running"
    assert reloaded.get_search_run_replay(run_id)["arguments"] == {
        "query": "asthma biologics",
        "limit": 40,
        "options": "systematic",
    }

    # Recovery itself is durable and idempotent across another restart.
    second_reload = SessionManager(data_dir=str(tmp_path))
    assert second_reload.get_search_run(run_id)["status"] == "interrupted"
    events = second_reload.get_session_event_log(kind="search_run_interrupted")
    assert len(events) == 1


def test_search_attempt_and_artifact_boundaries_redact_credentials(tmp_path: Path):
    sentinel = "TOPSECRET_SENTINEL"
    manager = SessionManager(data_dir=str(tmp_path))
    run = manager.start_search_run(
        f"cancer api_key={sentinel}",
        request={"query": f"cancer api_key={sentinel}"},
    )
    run_id = str(run["run_id"])
    manager.record_search_source_attempt(
        run_id,
        "openalex",
        "completed",
        logical_query=f"cancer api_key={sentinel}",
        physical_query=f"https://api.openalex.org/works?api_key={sentinel}&search=cancer",
        returned=0,
    )
    manifest = manager.save_artifact(
        tool="unified_search",
        kind="search_results",
        files={
            "results.json": json.dumps({"query": f"cancer api_key={sentinel}", "api_key": sentinel}),
            "query.md": f"# Query\n\ncancer api_key={sentinel}\n",
        },
        primary_file="results.json",
        summary={"query": f"cancer api_key={sentinel}", "token": sentinel},
        metadata={"authorization": f"Bearer {sentinel}"},
    )

    restored = manager.get_search_run(run_id)
    assert restored is not None
    assert sentinel not in json.dumps(restored, ensure_ascii=False)
    assert restored["source_attempts"][0]["logical_query"].endswith("api_key=[REDACTED]")
    assert restored["source_attempts"][0]["physical_query"].endswith("api_key=[REDACTED]&search=cancer")
    assert sentinel not in json.dumps(manifest, ensure_ascii=False)
    persisted_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in tmp_path.rglob("*") if path.is_file()
    )
    assert sentinel not in persisted_text
    assert "[REDACTED]" in persisted_text


def test_published_artifact_is_recovered_when_session_index_write_failed(tmp_path: Path):
    manager = SessionManager(data_dir=str(tmp_path))
    run = manager.start_search_run("crash recovery", request={"query": "crash recovery", "limit": 10})
    run_id = str(run["run_id"])
    manager.complete_search_run(run_id, pmids=["42"])

    with (
        patch(
            "pubmed_search.application.session.manager.atomic_write_json",
            side_effect=OSError("disk unavailable"),
        ),
        pytest.raises(OSError, match="disk unavailable"),
    ):
        manager.save_artifact(
            tool="unified_search",
            kind="search_results",
            files={"results.json": {"pmids": ["42"]}},
            primary_file="results.json",
            summary={"query": "crash recovery", "returned": 1},
        )

    reloaded = SessionManager(data_dir=str(tmp_path))
    artifacts = reloaded.list_artifacts(tool="unified_search")
    restored = reloaded.get_search_run(run_id)

    assert len(artifacts) == 1
    assert restored is not None
    assert restored["artifact"]["artifact_id"] == artifacts[0]["artifact_id"]
    assert reloaded.get_session_event_log(kind="artifacts_recovered")


def test_corrupt_sessions_index_is_rebuilt_from_atomic_session_files(tmp_path: Path):
    manager = SessionManager(data_dir=str(tmp_path))
    run_id = _complete_run(manager, 7)
    (tmp_path / "sessions.json").write_text("{broken", encoding="utf-8")

    reloaded = SessionManager(data_dir=str(tmp_path))

    assert reloaded.get_search_run(run_id) is not None
    repaired_index = json.loads((tmp_path / "sessions.json").read_text(encoding="utf-8"))
    assert repaired_index["current_session_id"]
    assert len(repaired_index["sessions"]) == 1


def test_concurrent_search_run_transitions_are_unique_complete_and_parseable(tmp_path: Path):
    manager = SessionManager(data_dir=str(tmp_path))

    with ThreadPoolExecutor(max_workers=12) as executor:
        run_ids = list(executor.map(lambda index: _complete_run(manager, index), range(40)))

    assert len(set(run_ids)) == 40
    runs = manager.list_search_runs(limit=100)
    assert len(runs) == 40
    assert {run["status"] for run in runs} == {"completed"}
    session = manager.get_current_session()
    assert session is not None
    payload = json.loads((tmp_path / f"session_{session.session_id}.json").read_text(encoding="utf-8"))
    assert len(payload["search_runs"]) == 40
    assert not list(tmp_path.glob(".*.tmp"))


def test_failed_run_mutation_rolls_back_in_memory_state(tmp_path: Path):
    manager = SessionManager(data_dir=str(tmp_path))
    manager.get_or_create_session("rollback")

    with (
        patch(
            "pubmed_search.application.session.manager.atomic_write_json",
            side_effect=OSError("disk unavailable"),
        ),
        pytest.raises(OSError, match="disk unavailable"),
    ):
        manager.start_search_run("must not appear", request={"query": "must not appear"})

    assert manager.list_search_runs(limit=10) == []


def test_search_runs_remain_tenant_isolated_across_restart(tmp_path: Path):
    registry = SessionManagerRegistry(str(tmp_path))
    tenant_a = TenantIdentity.for_principal("team-a", source="auth")
    tenant_b = TenantIdentity.for_principal("team-b", source="auth")

    with bind_tenant(tenant_a):
        manager_a = registry.for_tenant()
        run_a = manager_a.start_search_run("private A", request={"query": "private A"})
        manager_a.fail_search_run(str(run_a["run_id"]), "temporary failure", retryable=True)
    with bind_tenant(tenant_b):
        manager_b = registry.for_tenant()
        run_b = manager_b.start_search_run("private B", request={"query": "private B"})
        manager_b.complete_search_run(str(run_b["run_id"]), pmids=[])

    restarted = SessionManagerRegistry(str(tmp_path))
    with bind_tenant(tenant_a):
        runs_a = restarted.for_tenant().list_search_runs(limit=10)
    with bind_tenant(tenant_b):
        runs_b = restarted.for_tenant().list_search_runs(limit=10)

    assert [run["query"] for run in runs_a] == ["private A"]
    assert [run["query"] for run in runs_b] == ["private B"]
    assert (
        Path(restarted.tenant_data_dir(tenant_a.tenant_id)).resolve()
        != Path(restarted.tenant_data_dir(tenant_b.tenant_id)).resolve()
    )


def test_legacy_search_history_gets_stable_read_only_run_projection(tmp_path: Path):
    session_id = "legacy-session"
    payload = {
        "session_id": session_id,
        "topic": "legacy",
        "created_at": "2024-01-01T00:00:00+00:00",
        "updated_at": "2024-01-01T00:00:00+00:00",
        "cached_pmids": [],
        "search_history": [
            {
                "query": "legacy query",
                "timestamp": "2024-01-01T00:00:00+00:00",
                "result_count": 1,
                "pmids": ["123"],
                "filters": {"year": "2020-2024"},
            }
        ],
        "event_log": [],
        "reading_list": {},
        "excluded_pmids": [],
        "notes": {},
        "artifacts": [],
    }
    (tmp_path / f"session_{session_id}.json").write_text(json.dumps(payload), encoding="utf-8")

    first = SessionManager(data_dir=str(tmp_path))
    first_run = first.list_search_runs(limit=10)[0]
    second = SessionManager(data_dir=str(tmp_path))
    second_run = second.list_search_runs(limit=10)[0]

    assert first_run["run_id"].startswith("legacy-")
    assert second_run["run_id"] == first_run["run_id"]
    assert second_run["request"] == {"query": "legacy query", "filters": {"year": "2020-2024"}}
    assert second.get_search_run_replay(second_run["run_id"])["arguments"] == {
        "query": "legacy query",
        "filters": {"year": "2020-2024"},
    }
