"""Agent Plugins package and MCP Registry metadata stay publishable."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIND_DRIFT = runpy.run_path(str(ROOT / "scripts/build_agent_plugin.py"))["find_drift"]


def test_plugin_and_registry_metadata_match_skills_and_release_version() -> None:
    assert FIND_DRIFT() == []


def test_pypi_readme_carries_registry_ownership_marker() -> None:
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))

    assert f"mcp-name: {server['name']}" in (ROOT / "README.md").read_text(encoding="utf-8")
