"""Contracts that keep the real Mermaid parser/render smoke test active."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_ci_generates_runtime_fixtures_and_uses_pinned_mermaid() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "mermaid@11.16.1 jsdom@26.1.0" in workflow
    assert "--ignore-scripts --no-audit --fund=false" in workflow
    assert 'PYTHONPATH=src python3 -S scripts/export_mermaid_smoke_fixtures.py "$fixture_directory"' in workflow
    assert "node scripts/check_mermaid_rendering.mjs" in workflow
    for checked_path in (
        "docs",
        "ARCHITECTURE.md",
        "CHANGELOG.md",
        "DEPLOYMENT.md",
        "ROADMAP.md",
        "copilot-studio/README.md",
        '"$fixture_directory"',
    ):
        assert checked_path in workflow
    assert 'if [[ -d "$fixture_directory" ]]' not in workflow


def test_render_smoke_rejects_version_drift_oversize_and_error_svg() -> None:
    checker = (REPO_ROOT / "scripts" / "check_mermaid_rendering.mjs").read_text(encoding="utf-8")

    assert 'EXPECTED_MERMAID_VERSION = "11.16.1"' in checker
    assert 'EXPECTED_JSDOM_VERSION = "26.1.0"' in checker
    assert "MAX_MERMAID_CHARACTERS = 49_000" in checker
    assert "DIAGRAM_TIMEOUT_MS = 10_000" in checker
    assert "diagram.source.length > MAX_MERMAID_CHARACTERS" in checker
    assert "/maximum text size|syntax error in text/i.test(result.svg)" in checker
    assert 'layout: "dagre"' in checker
    assert "mermaid.parse(diagram.source" in checker
    assert "mermaid.render(" in checker
    assert "await withTimeout(" in checker


def test_runtime_fixture_export_remains_third_party_free(tmp_path: Path) -> None:
    """The CI fixture exporter must still run under its documented ``-S`` boundary."""
    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            "scripts/export_mermaid_smoke_fixtures.py",
            str(tmp_path),
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert "Exported 6 Mermaid smoke fixtures" in completed.stdout
    assert len(list(tmp_path.glob("*.mmd"))) == 6
