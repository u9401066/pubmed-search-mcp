"""The local gate must propagate failures and never pretend a dry run passed checks."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest
import yaml

GATE = Path(__file__).resolve().parents[1] / "scripts/check_repo.py"


def test_push_gate_is_installed_and_cloud_does_not_duplicate_the_full_matrix() -> None:
    root = GATE.parents[1]
    hooks = yaml.safe_load((root / ".pre-commit-config.yaml").read_text())
    assert "pre-push" in hooks["default_install_hook_types"]
    push = [hook for repo in hooks["repos"] for hook in repo["hooks"] if "pre-push" in hook.get("stages", [])]
    assert len(push) == 1
    assert push[0]["entry"] == "uv run --frozen python scripts/check_repo.py full"
    assert push[0]["always_run"] is True
    plans = runpy.run_path(str(GATE))["commands"]
    assert ("python", "scripts/perf/symbol_inventory.py") in plans("full")
    full_tests = [command for command in plans("full") if command[0] == "pytest"]
    smoke_tests = [command for command in plans("smoke") if command[0] == "pytest"]
    assert len(full_tests) == len(smoke_tests) == 1
    assert "tests/" in full_tests[0]
    # Selecting the module includes its fresh-wheel test; exclude live APIs,
    # but never exclude "slow" and silently lose wheel acceptance.
    assert "tests/test_all_tools_mcp_acceptance.py" in smoke_tests[0]
    assert "tests/test_release_transport_smoke.py" in smoke_tests[0]
    assert "tests/test_e2e_workflows.py" in smoke_tests[0]
    assert plans("pretest") == plans("full")
    assert not any(command[0] in {"ruff", "mypy"} for command in plans("smoke"))
    assert "slow" not in full_tests[0][-1] and "slow" not in smoke_tests[0][-1]
    assert "not integration" in full_tests[0][-1] and "not integration" in smoke_tests[0][-1]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
    # Ordinary CI checks the actual merge result and OS-dependent artifacts;
    # manual extended full matrices remain available without repeating each push.
    assert sum("if" not in job for job in workflow["jobs"].values()) == 1
    platforms = workflow["jobs"]["quality-and-package"]["strategy"]["matrix"]["os"]
    assert "ubuntu-latest" in platforms and "windows-latest" in platforms
    windows_steps = workflow["jobs"]["quality-and-package"]["steps"]
    assert any(
        step.get("if") == "runner.os == 'Windows'"
        and "test_copilot_hook_integration.py -k powershell" in step.get("run", "")
        for step in windows_steps
    )
    publish = yaml.safe_load((root / ".github/workflows/publish.yml").read_text())
    release_commands = "\n".join(step.get("run", "") for step in publish["jobs"]["verify"]["steps"])
    assert "check_repo.py smoke --release-dist dist" in release_commands
    assert "check_repo.py container --container-image" in release_commands
    assert "--help" not in release_commands
    for name in ("mermaid-rendering", "test-matrix", "container-smoke"):
        condition = workflow["jobs"][name]["if"]
        assert "github.event_name == 'workflow_dispatch'" in condition
        assert "inputs.run_extended_checks" in condition


@pytest.mark.parametrize("dry_run", [False, True])
def test_gate_stops_at_first_failed_child_or_only_previews_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dry_run: bool
) -> None:
    fail = tmp_path / "fail.py"
    later = tmp_path / "later.py"
    fail.write_text("from pathlib import Path\nPath('started').touch()\nraise SystemExit(17)\n", encoding="utf-8")
    later.write_text("from pathlib import Path\nPath('should-not-run').touch()\n", encoding="utf-8")
    main = runpy.run_path(str(GATE))["main"]
    monkeypatch.setitem(main.__globals__, "ROOT", tmp_path)
    monkeypatch.setitem(main.__globals__, "commands", lambda _: [("python", str(fail)), ("python", str(later))])
    monkeypatch.setattr(sys, "argv", [str(GATE), "full", *(["--dry-run"] if dry_run else [])])

    assert main() == (0 if dry_run else 17)
    assert (tmp_path / "started").exists() is not dry_run
    assert not (tmp_path / "should-not-run").exists()

    report = tmp_path / "build/validation/full.json"
    assert report.exists() is not dry_run
    if not dry_run:
        evidence = json.loads(report.read_text())
        assert evidence["status"] == "failed"
        assert len(evidence["steps"]) == 1
        assert evidence["steps"][0]["returncode"] == 17


def test_gate_reruns_after_success_and_replaces_stale_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    child = tmp_path / "check.py"
    child.write_text("raise SystemExit(0)\n")
    main = runpy.run_path(str(GATE))["main"]
    monkeypatch.setitem(main.__globals__, "ROOT", tmp_path)
    monkeypatch.setitem(main.__globals__, "commands", lambda _: [("python", str(child))])
    monkeypatch.setattr(sys, "argv", [str(GATE), "pretest"])
    assert main() == 0
    report = tmp_path / "build/validation/pretest.json"
    assert json.loads(report.read_text())["status"] == "passed"
    child.write_text("raise SystemExit(23)\n")
    assert main() == 23
    assert json.loads(report.read_text())["status"] == "failed"
    # A preview neither runs the failing child nor changes existing evidence.
    previous = report.read_bytes()
    monkeypatch.setattr(sys, "argv", [str(GATE), "pretest", "--dry-run"])
    assert main() == 0
    assert report.read_bytes() == previous


def test_container_gate_requires_explicit_image(monkeypatch: pytest.MonkeyPatch) -> None:
    main = runpy.run_path(str(GATE))["main"]
    monkeypatch.setattr(sys, "argv", [str(GATE), "container"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
