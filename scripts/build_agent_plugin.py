"""Sync the Agent Plugins package and MCP Registry metadata with the release.

Mirrors research skills from .claude/skills into plugins/pubmed-search/skills and
stamps the pyproject version into plugin.json, mcp.json, and server.json.
Run after editing a research skill or bumping the version; --check only reports drift.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "pubmed-search"
SKILLS_SOURCE = ROOT / ".claude" / "skills"
SERVER_JSON = ROOT / "server.json"
PACKAGE = "pubmed-search-mcp"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(data: Any) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def expected_files() -> dict[Path, bytes]:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    plugin = _load(PLUGIN_ROOT / "plugin.json")
    plugin["version"] = version
    mcp = _load(PLUGIN_ROOT / "mcp.json")
    mcp["mcpServers"]["pubmed-search"]["args"] = [f"{PACKAGE}@{version}"]
    server = _load(SERVER_JSON)
    server["version"] = version
    for package in server["packages"]:
        package["version"] = version

    expected = {
        PLUGIN_ROOT / "plugin.json": _dump(plugin),
        PLUGIN_ROOT / "mcp.json": _dump(mcp),
        SERVER_JSON: _dump(server),
    }
    skills = sorted(
        path
        for path in SKILLS_SOURCE.iterdir()
        if path.name.startswith("pubmed-") or path.name == "pipeline-persistence"
    )
    for skill in skills:
        for source in skill.rglob("*"):
            if source.is_file():
                expected[PLUGIN_ROOT / "skills" / skill.name / source.relative_to(skill)] = source.read_bytes()
    return expected


def find_drift() -> list[str]:
    expected = expected_files()
    stale = {path for path, content in expected.items() if not path.is_file() or path.read_bytes() != content}
    stale |= {path for path in PLUGIN_ROOT.rglob("*") if path.is_file() and path not in expected}
    return sorted(path.relative_to(ROOT).as_posix() for path in stale)


def sync() -> None:
    expected = expected_files()
    shutil.rmtree(PLUGIN_ROOT / "skills", ignore_errors=True)
    for path, content in expected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Report drift without writing")
    args = parser.parse_args()
    if not args.check:
        sync()
    drift = find_drift()
    for path in drift:
        print(f"Out of sync: {path}")
    if drift:
        print("Run: uv run python scripts/build_agent_plugin.py")
    return int(bool(drift))


if __name__ == "__main__":
    raise SystemExit(main())
