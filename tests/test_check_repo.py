"""The local gate must propagate failures and never pretend a dry run passed checks."""

from __future__ import annotations

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
    assert full_tests[0][-2:] == smoke_tests[0][-2:] == ("-m", "not integration")
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
    assert sum("if" not in job for job in workflow["jobs"].values()) == 1
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
