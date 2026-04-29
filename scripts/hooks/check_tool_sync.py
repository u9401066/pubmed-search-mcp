#!/usr/bin/env python3
"""
Pre-commit hook: MCP tool documentation sync.

Checks that MCP tool documentation is in sync with the actual registered tools.
If out of sync, auto-runs `count_mcp_tools.py --update-docs` and reports the
updated files. It never stages files, which keeps dirty worktrees safe.

When auto-fix applies, the hook fails so the developer can review and stage the
generated changes intentionally.

Exit codes:
    0 - Docs are in sync (or were auto-fixed and staged)
    1 - Sync script failed
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

# Force UTF-8 output on Windows (cp950 can't encode emoji)
if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

DOCS_KEYWORDS = [
    "README.md",
    "README.zh-TW.md",
    "copilot-instructions.md",
    "TOOLS_INDEX.md",
    "instructions.py",
    "SKILL.md",
]


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    """Run a command and return the result."""
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _is_doc_file(path: str) -> bool:
    return any(keyword in path for keyword in DOCS_KEYWORDS)


def _tracked_doc_files() -> list[str]:
    result = run(["git", "ls-files"])
    if result.returncode != 0:
        return []
    return [path for path in result.stdout.splitlines() if _is_doc_file(path)]


def snapshot_doc_files() -> dict[str, bytes | None]:
    """Read tracked generated-doc candidates before the sync script runs."""
    snapshots: dict[str, bytes | None] = {}
    for relative_path in _tracked_doc_files():
        path = Path(relative_path)
        snapshots[relative_path] = path.read_bytes() if path.is_file() else None
    return snapshots


def changed_doc_files(before: dict[str, bytes | None]) -> list[str]:
    """Return tracked doc files whose bytes changed during this hook run."""
    changed: list[str] = []
    for relative_path in _tracked_doc_files():
        path = Path(relative_path)
        after = path.read_bytes() if path.is_file() else None
        if before.get(relative_path) != after:
            changed.append(relative_path)
    return changed


def main() -> int:
    # Step 1: Run the sync script
    print("🔍 Checking MCP tool documentation sync...")
    before = snapshot_doc_files()
    result = run(["uv", "run", "python", "scripts/count_mcp_tools.py", "--update-docs"])

    if result.returncode != 0:
        print("❌ MCP tool count sync script failed:")
        print(result.stderr or result.stdout)
        return 1

    # Step 2: Check if docs were modified by this hook run.
    modified = changed_doc_files(before)
    if not modified:
        print("✅ MCP tool docs are in sync")
        return 0

    print("🔄 MCP tool docs were out of sync — auto-updated locally:")
    for f in modified:
        print(f"  - {f}")
    print()
    print("Review and stage these generated changes, then retry the commit.")

    return 1


if __name__ == "__main__":
    sys.exit(main())
