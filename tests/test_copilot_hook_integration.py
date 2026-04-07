"""Integration tests for Copilot hook entry scripts across bash and PowerShell."""

from __future__ import annotations

import json
import shutil
import subprocess
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
        if bash is None or shutil.which("jq") is None:
            pytest.skip("bash and jq are required for bash hook integration tests")
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
    return subprocess.run(
        _shell_command(shell_name, script_relative_path),
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=runtime_root,
        check=False,
    )


def _write_policy(runtime_root: Path, policy: dict[str, object]) -> None:
    (runtime_root / ".github" / "hooks" / "copilot-tool-policy.json").write_text(
        json.dumps(policy, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _tracker_payload(policy: dict[str, object]) -> dict[str, object]:
    workflow_steps = policy["workflowSteps"]
    assert isinstance(workflow_steps, dict)
    step_names = list(workflow_steps)
    return {
        "topic": "test topic",
        "intent": "quick_search",
        "template": "comprehensive",
        "created_at": "2026-04-06T00:00:00Z",
        "steps": dict.fromkeys(step_names, "not-started"),
    }


@pytest.mark.parametrize(
    ("shell_name", "script_relative_path"),
    [
        ("bash", "scripts/hooks/copilot/analyze-prompt.sh"),
        ("powershell", "scripts/hooks/copilot/analyze-prompt.ps1"),
    ],
)
def test_analyze_prompt_uses_shared_policy_workflow_metadata(
    tmp_path: Path,
    shell_name: str,
    script_relative_path: str,
) -> None:
    runtime_root = _copy_hook_runtime(tmp_path)
    policy_path = runtime_root / ".github" / "hooks" / "copilot-tool-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["workflowSteps"]["query_analysis"]["label"] = "Stage Alpha"
    policy["workflowSteps"]["query_analysis"]["nextInstruction"] = "custom_sequence"
    _write_policy(runtime_root, policy)

    result = _run_hook(
        runtime_root,
        shell_name,
        script_relative_path,
        {"prompt": "find literature about remimazolam sedation"},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), result.stderr

    response = json.loads(result.stdout)
    instructions = response["instructions"]
    assert "Stage Alpha" in instructions
    assert "custom_sequence" in instructions

    tracker_path = runtime_root / ".github" / "hooks" / "_state" / "workflow_tracker.json"
    tracker = json.loads(tracker_path.read_text(encoding="utf-8"))
    assert set(tracker["steps"]) == set(policy["workflowSteps"])


@pytest.mark.parametrize(
    ("shell_name", "script_relative_path"),
    [
        ("bash", "scripts/hooks/copilot/enforce-pipeline.sh"),
        ("powershell", "scripts/hooks/copilot/enforce-pipeline.ps1"),
    ],
)
def test_enforce_pipeline_uses_policy_rules_for_guardrails(
    tmp_path: Path,
    shell_name: str,
    script_relative_path: str,
) -> None:
    runtime_root = _copy_hook_runtime(tmp_path)
    policy_path = runtime_root / ".github" / "hooks" / "copilot-tool-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["rules"]["requiresEvidenceOrIdentifiers"] = ["search_gene"]
    _write_policy(runtime_root, policy)

    state_dir = runtime_root / ".github" / "hooks" / "_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "workflow_tracker.json").write_text(
        json.dumps(_tracker_payload(policy), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = _run_hook(
        runtime_root,
        shell_name,
        script_relative_path,
        {"toolName": "search_gene", "toolArgs": {}},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), result.stderr

    response = json.loads(result.stdout)
    assert response["permissionDecision"] == "deny"
    assert "search_gene" in response["permissionDecisionReason"]


@pytest.mark.parametrize(
    ("shell_name", "script_relative_path"),
    [
        ("bash", "scripts/hooks/copilot/evaluate-results.sh"),
        ("powershell", "scripts/hooks/copilot/evaluate-results.ps1"),
    ],
)
def test_evaluate_results_uses_policy_workflow_mapping_and_writes_eval_state(
    tmp_path: Path,
    shell_name: str,
    script_relative_path: str,
) -> None:
    runtime_root = _copy_hook_runtime(tmp_path)
    policy_path = runtime_root / ".github" / "hooks" / "copilot-tool-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["workflowSteps"]["initial_search"]["tools"] = [
        tool for tool in policy["workflowSteps"]["initial_search"]["tools"] if tool != "search_gene"
    ]
    policy["workflowSteps"]["result_evaluation"]["tools"] = ["search_gene"]
    _write_policy(runtime_root, policy)

    state_dir = runtime_root / ".github" / "hooks" / "_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    tracker_path = state_dir / "workflow_tracker.json"
    tracker_path.write_text(
        json.dumps(_tracker_payload(policy), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = _run_hook(
        runtime_root,
        shell_name,
        script_relative_path,
        {
            "toolName": "search_gene",
            "toolArgs": {"query": "EGFR"},
            "toolResult": {
                "resultType": "success",
                "textResultForLlm": "1. PMID: 12345\n2. PMID: 23456",
            },
        },
    )

    assert result.returncode == 0, result.stderr

    tracker = json.loads(tracker_path.read_text(encoding="utf-8"))
    assert tracker["steps"]["result_evaluation"] == "completed"

    eval_path = state_dir / "last_research_eval.json"
    evaluation = json.loads(eval_path.read_text(encoding="utf-8"))
    assert evaluation["tool_name"] == "search_gene"
    assert evaluation["quality"] == "poor"
