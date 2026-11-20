"""Sync the Agent Plugins package and MCP Registry metadata with the release.

Mirrors research skills from .claude/skills into plugins/pubmed-search/skills and
stamps the pyproject version into plugin.json, mcp.json, and server.json.
Run after editing a research skill or bumping the version; --check only reports drift.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
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
            if source.is_file() and "__pycache__" not in source.parts and source.suffix != ".pyc":
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


def build_development_plugin(destination: Path) -> Path:
    """Build a directory-installable plugin that starts the server from this checkout."""
    if destination.is_symlink():
        raise ValueError("Choose a development output directory that is not a symlink")
    destination = destination.resolve()
    if destination.is_relative_to(PLUGIN_ROOT) or destination.is_relative_to(SKILLS_SOURCE):
        raise ValueError("Choose an output directory outside the maintained plugin and source skills")
    files = {path.relative_to(PLUGIN_ROOT): data for path, data in expected_files().items() if path != SERVER_JSON}
    mcp = json.loads(files[Path("mcp.json")])
    server = mcp["mcpServers"]["pubmed-search"]
    server.update(command="uv", args=["run", "--project", str(ROOT), "--frozen", PACKAGE])
    files[Path("mcp.json")] = _dump(mcp)
    if destination.exists():
        # A client may have added or customized skills after installation.
        if (destination / "mcp.json").is_file():
            existing = {p.relative_to(destination) for p in destination.rglob("*") if p.is_file() or p.is_symlink()}
            if existing == files.keys() and all(
                not (destination / p).is_symlink() and (destination / p).read_bytes() == data
                for p, data in files.items()
            ):
                return destination
        raise ValueError("Output already exists with different contents. Choose a new directory.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        staged = Path(temporary) / "plugin"
        for relative, content in files.items():
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        staged.rename(destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Report drift without writing")
    mode.add_argument("--dev-output", type=Path, help="Generate a plugin that runs this checkout in a new directory")
    args = parser.parse_args()
    if args.dev_output:
        try:
            destination = build_development_plugin(args.dev_output)
        except (OSError, ValueError) as exc:
            parser.exit(1, f"{exc}\n")
        print(f"Development plugin: {destination}")
        return 0
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
