"""Subprocess integration tests for the shared Copilot hook runtime."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_SOURCE_DIR = REPO_ROOT / "scripts" / "hooks" / "copilot"
POLICY_SOURCE_PATH = REPO_ROOT / ".github" / "hooks" / "copilot-tool-policy.json"


def _copy_hook_runtime(tmp_path: Path) -> Path:
    runtime_root = tmp_path / "hook-runtime"
    shutil.copytree(HOOKS_SOURCE_DIR, runtime_root / "scripts" / "hooks" / "copilot")
    hooks_dir = runtime_root / ".github" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(POLICY_SOURCE_PATH, hooks_dir / "copilot-tool-policy.json")
    return runtime_root


def _shell_command(shell_name: str, script_relative_path: str) -> list[str]:
    if shell_name == "bash":
        bash = shutil.which("bash")
        if bash is None:
            pytest.skip("bash is required for bash hook integration tests")
        probe = subprocess.run(
            [bash, "-lc", "true"],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode != 0:
            pytest.skip("the discovered bash executable is not usable")
        return [bash, script_relative_path]

    powershell = shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is required for PowerShell hook integration tests")

    executable_name = Path(powershell).name.lower()
    if executable_name.startswith("pwsh"):
        return [powershell, "-NoProfile", "-File", script_relative_path]
    return [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_relative_path]


def _run_hook(
    runtime_root: Path,
    shell_name: str,
    script_relative_path: str,
    payload: dict[str, object],
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PUBMED_HOOK_PYTHON"] = sys.executable
    return subprocess.run(
        _shell_command(shell_name, script_relative_path),
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=runtime_root,
        env=env,
        check=False,
    )


def _write_policy(runtime_root: Path, policy: dict[str, object]) -> None:
    (runtime_root / ".github" / "hooks" / "copilot-tool-policy.json").write_text(
        json.dumps(policy, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _state_text(runtime_root: Path) -> str:
    state_dir = runtime_root / ".github" / "hooks" / "_state"
    return "\n".join(path.read_text(encoding="utf-8") for path in state_dir.glob("*") if path.is_file())


def _start_workflow(runtime_root: Path, shell_name: str, prompt: str) -> None:
    result = _run_hook(
        runtime_root,
        shell_name,
        "scripts/hooks/copilot/analyze-prompt.sh"
        if shell_name == "bash"
        else "scripts/hooks/copilot/analyze-prompt.ps1",
        {"prompt": prompt},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), result.stderr


SHELL_PHASES = [
    ("bash", ".sh"),
    ("powershell", ".ps1"),
]


@pytest.mark.parametrize(("shell_name", "suffix"), SHELL_PHASES)
def test_analyze_prompt_uses_policy_without_persisting_prompt(
    tmp_path: Path,
    shell_name: str,
    suffix: str,
) -> None:
    runtime_root = _copy_hook_runtime(tmp_path)
    policy_path = runtime_root / ".github" / "hooks" / "copilot-tool-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["workflowSteps"]["query_analysis"]["label"] = "Stage Alpha"
    policy["workflowSteps"]["query_analysis"]["nextInstruction"] = "custom_sequence"
    _write_policy(runtime_root, policy)
    sentinel = "PRIVATE_PROMPT_SENTINEL"

    result = _run_hook(
        runtime_root,
        shell_name,
        f"scripts/hooks/copilot/analyze-prompt{suffix}",
        {"prompt": f"find literature about {sentinel} remimazolam sedation"},
    )

    assert result.returncode == 0, result.stderr
    instructions = json.loads(result.stdout)["instructions"]
    assert "Stage Alpha" in instructions
    assert "custom_sequence" in instructions

    tracker_path = runtime_root / ".github" / "hooks" / "_state" / "workflow_tracker.json"
    tracker = json.loads(tracker_path.read_text(encoding="utf-8"))
    assert tracker["schema_version"] == 2
    assert tracker["prompt_fingerprint"].startswith("h1:")
    assert all(isinstance(state, dict) for state in tracker["steps"].values())
    assert sentinel not in _state_text(runtime_root)


@pytest.mark.parametrize(("shell_name", "suffix"), SHELL_PHASES)
def test_heuristic_complexity_is_advisory_and_query_is_fingerprinted(
    tmp_path: Path,
    shell_name: str,
    suffix: str,
) -> None:
    runtime_root = _copy_hook_runtime(tmp_path)
    query = "PRIVATE_QUERY_SENTINEL remimazolam vs propofol ICU patient efficacy safety"

    result = _run_hook(
        runtime_root,
        shell_name,
        f"scripts/hooks/copilot/enforce-pipeline{suffix}",
        {"toolName": "unified_search", "toolArgs": {"query": query}},
    )

    assert result.returncode == 0, result.stderr
    decision = json.loads(result.stdout)
    assert decision["permissionDecision"] == "allow"
    assert "Complexity hint" in decision["permissionDecisionReason"]
    pending_path = runtime_root / ".github" / "hooks" / "_state" / "pending_complexity.json"
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    assert pending["query_fingerprint"].startswith("h1:")
    assert query not in _state_text(runtime_root)


@pytest.mark.parametrize(("shell_name", "suffix"), SHELL_PHASES)
def test_missing_evidence_guard_is_advisory_not_a_false_block(
    tmp_path: Path,
    shell_name: str,
    suffix: str,
) -> None:
    runtime_root = _copy_hook_runtime(tmp_path)
    _start_workflow(runtime_root, shell_name, "find literature about remimazolam")
    policy_path = runtime_root / ".github" / "hooks" / "copilot-tool-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["rules"]["requiresEvidenceOrIdentifiers"] = ["search_gene"]
    _write_policy(runtime_root, policy)

    result = _run_hook(
        runtime_root,
        shell_name,
        f"scripts/hooks/copilot/enforce-pipeline{suffix}",
        {"toolName": "search_gene", "toolArgs": {}},
    )

    assert result.returncode == 0, result.stderr
    decision = json.loads(result.stdout)
    assert decision["permissionDecision"] == "allow"
    assert "Context hint" in decision["permissionDecisionReason"]


def _partial_search_result(query: str) -> dict[str, object]:
    return {
        "toolName": "unified_search",
        "toolArgs": {"query": query, "output_format": "json"},
        "toolResult": {
            "resultType": "success",
            "structuredContent": {
                "tool": "unified_search",
                "statistics": {"unique_articles": 2},
                "articles": [{"pmid": "12345"}, {"doi": "10.1000/example"}],
                "source_counts": [
                    {"source": "pubmed", "returned": 2, "total": 2},
                    {"source": "semantic_scholar", "returned": 0, "total": None},
                ],
                "source_errors": [
                    {
                        "source": "semantic_scholar",
                        "status": "rate_limited",
                        "status_code": 429,
                        "retryable": True,
                        "suggestion": "PRIVATE_RENDERED_SENTINEL must not persist",
                    }
                ],
                "artifact_summary": {
                    "artifact_id": "run-123",
                    "artifact_uri": "artifact://session/run-123",
                    "audit_status": "warn",
                    "available_files": ["audit.json", "query_strategy.json", "results.json"],
                },
                "search_run": {
                    "run_id": "run-opaque-123",
                    "status": "partial",
                    "recoverable": True,
                    "artifact_uri": "artifact://session/run-123",
                },
            },
        },
    }


@pytest.mark.parametrize(("shell_name", "suffix"), SHELL_PHASES)
def test_structured_partial_result_persists_recoverable_safe_state(
    tmp_path: Path,
    shell_name: str,
    suffix: str,
) -> None:
    runtime_root = _copy_hook_runtime(tmp_path)
    _start_workflow(runtime_root, shell_name, "find literature about remimazolam")
    query = "PRIVATE_QUERY_SENTINEL remimazolam"

    result = _run_hook(
        runtime_root,
        shell_name,
        f"scripts/hooks/copilot/evaluate-results{suffix}",
        _partial_search_result(query),
    )

    assert result.returncode == 0, result.stderr
    state_dir = runtime_root / ".github" / "hooks" / "_state"
    evaluation = json.loads((state_dir / "last_research_eval.json").read_text(encoding="utf-8"))
    assert evaluation["outcome"] == "partial"
    assert evaluation["result_count"] == 2
    assert evaluation["failed_sources"] == ["semantic_scholar"]
    source_counts = {row["source"]: row for row in evaluation["source_counts"]}
    assert source_counts["pubmed"]["returned"] == 2
    assert source_counts["semantic_scholar"]["status"] == "rate_limited"
    assert evaluation["artifact"]["artifact_uri"] == "artifact://session/run-123"
    assert evaluation["search_run"]["run_id"] == "run-opaque-123"
    handoff = evaluation["recovery"]["artifact_handoff"]
    assert handoff == {
        "tool": "read_session",
        "arguments": {
            "action": "artifact",
            "artifact_uri": "artifact://session/run-123",
            "artifact_file": "audit.json",
        },
    }
    assert evaluation["recovery"]["search_run"]["replay"]["arguments"] == {
        "action": "replay_search",
        "run_id": "run-opaque-123",
    }
    tracker = json.loads((state_dir / "workflow_tracker.json").read_text(encoding="utf-8"))
    assert tracker["steps"]["initial_search"]["status"] == "completed_with_warnings"
    assert query not in _state_text(runtime_root)
    assert "PRIVATE_RENDERED_SENTINEL" not in _state_text(runtime_root)


@pytest.mark.parametrize(("shell_name", "suffix"), SHELL_PHASES)
def test_partial_result_nudge_points_to_artifact_without_blocking(
    tmp_path: Path,
    shell_name: str,
    suffix: str,
) -> None:
    runtime_root = _copy_hook_runtime(tmp_path)
    _start_workflow(runtime_root, shell_name, "find literature about remimazolam")
    _run_hook(
        runtime_root,
        shell_name,
        f"scripts/hooks/copilot/evaluate-results{suffix}",
        _partial_search_result("remimazolam"),
    )

    result = _run_hook(
        runtime_root,
        shell_name,
        f"scripts/hooks/copilot/enforce-pipeline{suffix}",
        {"toolName": "configure_institutional_access", "toolArgs": {}},
    )

    decision = json.loads(result.stdout)
    assert decision["permissionDecision"] == "allow"
    assert "artifact://session/run-123" in decision["permissionDecisionReason"]
    assert 'read_session(action="artifact"' in decision["permissionDecisionReason"]
    assert 'read_session(action="replay_search", run_id="run-opaque-123")' in decision["permissionDecisionReason"]


@pytest.mark.parametrize(("shell_name", "suffix"), SHELL_PHASES)
def test_empty_structured_search_is_not_misclassified_as_failure(
    tmp_path: Path,
    shell_name: str,
    suffix: str,
) -> None:
    runtime_root = _copy_hook_runtime(tmp_path)

    result = _run_hook(
        runtime_root,
        shell_name,
        f"scripts/hooks/copilot/evaluate-results{suffix}",
        {
            "toolName": "unified_search",
            "toolArgs": {"query": "no-match query"},
            "toolResult": {
                "resultType": "success",
                "textResultForLlm": json.dumps(
                    {
                        "tool": "unified_search",
                        "statistics": {"unique_articles": 0},
                        "articles": [],
                        "source_counts": [{"source": "pubmed", "returned": 0, "total": 0}],
                    }
                ),
            },
        },
    )

    assert result.returncode == 0, result.stderr
    evaluation = json.loads(
        (runtime_root / ".github" / "hooks" / "_state" / "last_research_eval.json").read_text(encoding="utf-8")
    )
    assert evaluation["outcome"] == "empty"
    assert evaluation["quality"] == "acceptable"
    assert evaluation["count_known"] is True


@pytest.mark.parametrize(("shell_name", "suffix"), SHELL_PHASES)
def test_all_provider_errors_are_failed_not_empty_or_partial(
    tmp_path: Path,
    shell_name: str,
    suffix: str,
) -> None:
    runtime_root = _copy_hook_runtime(tmp_path)
    result = _run_hook(
        runtime_root,
        shell_name,
        f"scripts/hooks/copilot/evaluate-results{suffix}",
        {
            "toolName": "unified_search",
            "toolArgs": {"query": "offline"},
            "toolResult": {
                "resultType": "success",
                "structuredContent": {
                    "tool": "unified_search",
                    "articles": [],
                    "source_counts": [{"source": "semantic_scholar", "returned": 0}],
                    "source_errors": [
                        {
                            "source": "semantic_scholar",
                            "status": "rate_limited",
                            "retryable": True,
                        }
                    ],
                },
            },
        },
    )

    assert result.returncode == 0, result.stderr
    evaluation = json.loads(
        (runtime_root / ".github" / "hooks" / "_state" / "last_research_eval.json").read_text(encoding="utf-8")
    )
    assert evaluation["outcome"] == "failed"
    assert evaluation["quality"] == "poor"


@pytest.mark.parametrize(("shell_name", "suffix"), SHELL_PHASES)
def test_session_end_and_restart_preserve_recovery_tracker(
    tmp_path: Path,
    shell_name: str,
    suffix: str,
) -> None:
    runtime_root = _copy_hook_runtime(tmp_path)
    _start_workflow(runtime_root, shell_name, "find literature about remimazolam")
    tracker_path = runtime_root / ".github" / "hooks" / "_state" / "workflow_tracker.json"
    workflow_id = json.loads(tracker_path.read_text(encoding="utf-8"))["workflow_id"]

    cleanup = _run_hook(
        runtime_root,
        shell_name,
        f"scripts/hooks/copilot/session-cleanup{suffix}",
        {"reason": "user_exit"},
    )
    assert cleanup.returncode == 0, cleanup.stderr
    assert tracker_path.exists()

    restart = _run_hook(
        runtime_root,
        shell_name,
        f"scripts/hooks/copilot/session-init{suffix}",
        {"source": "resume"},
    )
    assert restart.returncode == 0, restart.stderr
    instructions = json.loads(restart.stdout)["instructions"]
    assert workflow_id in instructions
    assert "Recovered research workflow" in instructions
    assert json.loads(tracker_path.read_text(encoding="utf-8"))["workflow_id"] == workflow_id


@pytest.mark.parametrize(("shell_name", "suffix"), SHELL_PHASES)
def test_corrupt_current_tracker_recovers_from_atomic_previous_copy(
    tmp_path: Path,
    shell_name: str,
    suffix: str,
) -> None:
    runtime_root = _copy_hook_runtime(tmp_path)
    _start_workflow(runtime_root, shell_name, "find literature about remimazolam")
    tracker_path = runtime_root / ".github" / "hooks" / "_state" / "workflow_tracker.json"
    original_id = json.loads(tracker_path.read_text(encoding="utf-8"))["workflow_id"]
    _run_hook(
        runtime_root,
        shell_name,
        f"scripts/hooks/copilot/session-cleanup{suffix}",
        {"reason": "checkpoint"},
    )
    assert tracker_path.with_suffix(".previous.json").exists()
    tracker_path.write_text("{corrupt", encoding="utf-8")

    restart = _run_hook(
        runtime_root,
        shell_name,
        f"scripts/hooks/copilot/session-init{suffix}",
        {"source": "resume"},
    )

    assert restart.returncode == 0, restart.stderr
    restored = json.loads(tracker_path.read_text(encoding="utf-8"))
    assert restored["workflow_id"] == original_id


@pytest.mark.parametrize(("shell_name", "suffix"), SHELL_PHASES)
def test_session_init_scrubs_legacy_raw_prompt_and_query_state(
    tmp_path: Path,
    shell_name: str,
    suffix: str,
) -> None:
    runtime_root = _copy_hook_runtime(tmp_path)
    state_dir = runtime_root / ".github" / "hooks" / "_state"
    state_dir.mkdir(parents=True)
    sentinel = "LEGACY_PRIVATE_SENTINEL"
    policy = json.loads((runtime_root / ".github" / "hooks" / "copilot-tool-policy.json").read_text(encoding="utf-8"))
    state_dir.joinpath("workflow_tracker.json").write_text(
        json.dumps(
            {
                "topic": f"raw prompt {sentinel}",
                "intent": "quick_search",
                "template": "comprehensive",
                "steps": dict.fromkeys(policy["workflowSteps"], "not-started"),
            }
        ),
        encoding="utf-8",
    )
    state_dir.joinpath("last_research_eval.json").write_text(
        json.dumps({"query": f"raw query {sentinel}", "outcome": "partial"}),
        encoding="utf-8",
    )
    state_dir.joinpath("last_search_eval.json").write_text(sentinel, encoding="utf-8")
    state_dir.joinpath("search_audit.jsonl").write_text(
        json.dumps({"event": "legacy", "query": f"raw query {sentinel}"}) + "\n",
        encoding="utf-8",
    )

    result = _run_hook(
        runtime_root,
        shell_name,
        f"scripts/hooks/copilot/session-init{suffix}",
        {"source": "resume"},
    )

    assert result.returncode == 0, result.stderr
    assert sentinel not in _state_text(runtime_root)
    tracker = json.loads(state_dir.joinpath("workflow_tracker.json").read_text(encoding="utf-8"))
    assert tracker["schema_version"] == 2
    assert tracker["prompt_fingerprint"].startswith("h1:")
    evaluation = json.loads(state_dir.joinpath("last_research_eval.json").read_text(encoding="utf-8"))
    assert evaluation["query_fingerprint"].startswith("h1:")
    assert not state_dir.joinpath("last_search_eval.json").exists()
