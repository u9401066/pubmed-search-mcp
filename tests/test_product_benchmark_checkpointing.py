"""Full-scale preparation and interruption recovery without calling any model."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from typing import TYPE_CHECKING, Any

import pytest
from scripts import benchmark_product_harness as runner

from pubmed_search.application.search.agent_benchmark import summarize_product_comparison
from pubmed_search.infrastructure.evaluation.checkpoints import ExperimentStore, write_json

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Benchmark execution uses POSIX process groups and locks")


def question(text: str) -> dict[str, Any]:
    return {"question": text, "golden_answers": ["insulin"], "pmid": "123"}


def settings(repo: Path, *, prepare_only: bool = False, batch_size: int | None = None) -> argparse.Namespace:
    return argparse.Namespace(
        repo_root=repo,
        model="test-model",
        effort="high",
        timeout=60,
        repeats=1,
        prepare_only=prepare_only,
        batch_size=batch_size,
    )


def protocol(rows: list[dict[str, Any]], *, repeats: int = 1) -> dict[str, Any]:
    return {
        "query_ids": [hashlib.sha256(row["question"].encode()).hexdigest() for row in rows],
        "repeats": repeats,
        "development_query_ids": [],
    }


def fake_executor(monkeypatch: pytest.MonkeyPatch, statuses: list[str] | None = None) -> list[str]:
    calls = []
    outcomes = list(statuses or [])

    def run(
        job: Path,
        row: dict[str, Any],
        _repo: Path,
        arm: str,
        _model: str,
        _effort: str,
        _timeout: int,
        *,
        experiment_fingerprint: str,
        repeat: int,
    ) -> dict[str, Any]:
        calls.append(arm)
        status = outcomes.pop(0) if outcomes else "completed"
        job.mkdir(parents=True)
        trace = job / "events.jsonl"
        trace.write_text('{"type":"test_execution"}\n')
        result = {
            "arm": arm,
            "query_id": hashlib.sha256(row["question"].encode()).hexdigest(),
            "repeat": repeat,
            "experiment_fingerprint": experiment_fingerprint,
            "status": status,
            "metrics": {"answer_exact_match": 1.0, "source_pmid_hit": 1.0},
            "usage": {"input_tokens": 10},
            "usage_known": True,
            "elapsed_seconds": 1,
            "events_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
        }
        write_json(job / "result.json", result)
        return result

    monkeypatch.setattr(runner, "run_product_case", run)
    return calls


def test_prepare_all_5000_queries_never_calls_an_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    rows = [question(f"Question {index}") for index in range(5000)]
    manifest = protocol(rows)
    calls = fake_executor(monkeypatch)
    store = ExperimentStore(tmp_path / "run", manifest)
    try:
        summary = runner.execute_experiment(store, manifest, rows, settings(tmp_path, prepare_only=True))
    finally:
        store.close()
    assert calls == []
    assert summary["state"] == "prepared"
    assert summary["planned_queries"] == 5000
    assert summary["planned_agent_runs"] == 10000
    assert summary["attempts"] == 0
    assert summary["comparison"] == {}


def test_batch_resume_reuses_completed_pairs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    rows = [question("one"), question("two")]
    manifest = protocol(rows)
    calls = fake_executor(monkeypatch)
    args = settings(tmp_path, batch_size=1)
    store = ExperimentStore(tmp_path / "run", manifest)
    try:
        first = runner.execute_experiment(store, manifest, rows, args)
    finally:
        store.close()
    assert first["state"] == "paused_batch"
    assert first["complete_query_count"] == 1
    assert calls == ["native", "package"]
    store = ExperimentStore(tmp_path / "run", manifest, resume=True)
    try:
        second = runner.execute_experiment(store, manifest, rows, args)
    finally:
        store.close()
    assert second["state"] == "completed"
    assert second["complete_query_count"] == 2
    assert calls == ["native", "package", "package", "native"]
    assert second["resources"]["native"]["total_usage"]["input_tokens"] == 20


def test_quota_failure_pauses_without_zeroing_missing_arm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    rows = [question("one")]
    manifest = protocol(rows)
    calls = fake_executor(monkeypatch, ["completed", "provider_limited"])
    store = ExperimentStore(tmp_path / "run", manifest)
    try:
        first = runner.execute_experiment(store, manifest, rows, settings(tmp_path))
    finally:
        store.close()
    assert first["state"] == "paused_provider_limited"
    assert first["scored_agent_runs"] == 1
    assert first["comparison"] == {}
    store = ExperimentStore(tmp_path / "run", manifest, resume=True)
    try:
        second = runner.execute_experiment(store, manifest, rows, settings(tmp_path))
    finally:
        store.close()
    assert calls == ["native", "package", "package"]
    assert second["attempts"] == 3
    assert second["complete_query_count"] == 1
    assert second["resources"]["package"]["total_usage"]["input_tokens"] == 20
    assert second["comparison"]["answer_exact_match"]["delta"] == 0


def test_store_rejects_changed_protocol_and_concurrent_writer(tmp_path: Path):
    store = ExperimentStore(tmp_path, {"model": "original"})
    try:
        with pytest.raises(BlockingIOError):
            ExperimentStore(tmp_path, {"model": "original"}, resume=True)
    finally:
        store.close()
    with pytest.raises(ValueError, match="protocol mismatch"):
        ExperimentStore(tmp_path, {"model": "changed"}, resume=True)


def test_resume_distinguishes_boolean_and_integer_protocol_values(tmp_path: Path):
    store = ExperimentStore(tmp_path, {"repeats": True})
    store.close()
    with pytest.raises(ValueError, match="protocol mismatch"):
        ExperimentStore(tmp_path, {"repeats": 1}, resume=True)


@pytest.mark.parametrize("corruption", ["status", "trace", "arm", "repeat"])
def test_accounting_validates_every_persisted_attempt(tmp_path: Path, monkeypatch, corruption):
    rows = [question("one")]
    manifest = protocol(rows)
    fake_executor(monkeypatch)
    store = ExperimentStore(tmp_path, manifest)
    try:
        runner.execute_experiment(store, manifest, rows, settings(tmp_path))
        result_path = next((tmp_path / "cases").glob("*/*/attempt-*/result.json"))
        result = json.loads(result_path.read_text())
        if corruption == "trace":
            (result_path.parent / "events.jsonl").write_text("Changed")
        else:
            result[corruption] = {"status": "unknown_success", "arm": "invalid", "repeat": False}[corruption]
            write_json(result_path, result)
        with pytest.raises(ValueError):
            store.attempts()
        if corruption == "status":
            with pytest.raises(ValueError, match="status"):
                store.outcome(result["query_id"], result["repeat"], result["arm"])
    finally:
        store.close()


def test_store_preserves_interrupted_attempt_and_detects_changed_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    rows = [question("one")]
    manifest = protocol(rows)
    fake_executor(monkeypatch)
    qid = manifest["query_ids"][0]
    store = ExperimentStore(tmp_path, manifest)
    try:
        interrupted = store.next_attempt(qid, 0, "native")
        interrupted.mkdir()
        (interrupted / "events.jsonl").write_text("Partial trace")
        summary = runner.execute_experiment(store, manifest, rows, settings(tmp_path))
        assert summary["unfinished_attempts"] == 1
        assert summary["unknown_usage_attempts"] == 1
        assert store.next_attempt(qid, 0, "native").name == "attempt-0003"
        completed = interrupted.parent / "attempt-0002/events.jsonl"
        completed.write_text("Changed")
        with pytest.raises(ValueError, match="trace fingerprint"):
            store.outcome(qid, 0, "native")
    finally:
        store.close()


def test_comparison_averages_repeats_and_excludes_pilot_and_incomplete_pairs():
    def score(value: float) -> dict[str, Any]:
        return {"metrics": {"answer_exact_match": value, "source_pmid_hit": value}}

    data = {
        "pilot": [{"native": score(0), "package": score(1)}] * 2,
        "heldout": [{"native": score(0), "package": score(1)}, {"native": score(1), "package": score(1)}],
        "incomplete": [{"native": score(1)}, {}],
    }
    summary = summarize_product_comparison(data, repeats=2, development_query_ids=["pilot"])
    assert summary["complete_query_count"] == 2
    assert summary["primary_query_count"] == 1
    assert summary["comparison"]["answer_exact_match"]["delta"] == 0.5
    assert summary["comparison"]["answer_exact_match"]["query_count"] == 1


@pytest.mark.parametrize(
    "events,returncode,expected",
    [
        ([{"type": "turn.failed", "error": {"message": "You've hit your usage limit"}}], 1, "provider_limited"),
        ([{"type": "turn.completed", "usage": {"input_tokens": 20}}], 0, "completed"),
        ([], 0, "invalid_trace"),
    ],
)
def test_process_outcomes_are_classified_without_live_model_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    events: list[dict[str, Any]],
    returncode: int,
    expected: str,
):
    job = tmp_path / "job"

    class Process:
        def __init__(self, _command, **kwargs):
            self.returncode = returncode
            for event in events:
                kwargs["stdout"].write(json.dumps(event) + "\n")
            (job / "answer.json").write_text(
                json.dumps({"answer": "insulin", "cited_pmids": ["123"], "source_urls": []})
            )

        def communicate(self, _prompt, timeout):
            return None

    monkeypatch.setattr(runner.subprocess, "Popen", Process)
    result = runner.run_product_case(job, question("one"), tmp_path, "native", "model", "high", 60)
    assert result["status"] == expected
    assert result["metrics"]["answer_exact_match"] == (1.0 if expected == "completed" else 0.0)
    assert (job / "workspace").is_dir()
    assert not (job / "workspace/result.json").exists()


def test_dataset_validation_rejects_duplicates_before_execution(tmp_path: Path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps([question("same"), question("same")]))
    with pytest.raises(ValueError, match="Duplicate questions"):
        runner.load_questions(path)


def test_manifest_fingerprints_skills_and_keeps_gold_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "repo"
    (root / "src/pubmed_search").mkdir(parents=True)
    (root / "src/pubmed_search/server.py").write_text("original")
    skill = root / ".claude/skills/pubmed-search/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("original instructions")
    data = tmp_path / "data.json"
    rows = [question("one"), question("two")]
    data.write_text(json.dumps(rows))
    args = settings(root)
    args.dataset, args.revision_label, args.development_query_count = data, "original", 1
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *_args, **_kwargs: "codex-test")
    before = runner.build_manifest(args, rows)
    assert len(before["query_ids"]) == 2
    assert len(before["development_query_ids"]) == 1
    assert "insulin" not in json.dumps(before)
    assert "123" not in before.values()
    skill.write_text("changed instructions")
    after = runner.build_manifest(args, rows)
    assert before["package_skills_sha256"] != after["package_skills_sha256"]


@pytest.mark.parametrize("interrupted", [False, True])
def test_timeout_and_interrupt_keep_a_recoverable_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupted: bool
):
    stopped = []

    class Process:
        pid = 987654
        returncode = -9

        def __init__(self, *_args, **_kwargs):
            self.calls = 0

        def communicate(self, _prompt=None, timeout=None):
            self.calls += 1
            if self.calls == 1:
                if interrupted:
                    raise KeyboardInterrupt
                raise subprocess.TimeoutExpired("fake-codex", timeout)

    monkeypatch.setattr(runner.subprocess, "Popen", Process)
    monkeypatch.setattr(runner.os, "killpg", lambda pid, _signal: stopped.append(pid))
    result = runner.run_product_case(tmp_path / "job", question("one"), tmp_path, "native", "model", "high", 60)
    assert result["status"] == ("interrupted" if interrupted else "timeout")
    assert result["usage_known"] is False
    assert result["metrics"]["answer_exact_match"] == 0
    assert stopped == [987654]
    assert (tmp_path / "job/result.json").exists()
