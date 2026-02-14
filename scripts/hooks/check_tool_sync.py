#!/usr/bin/env python3
"""
Pre-commit hook: MCP tool documentation sync.

Checks that MCP tool documentation is in sync with the actual registered tools.
If out of sync, auto-runs `count_mcp_tools.py --update-docs` and stages the
updated files.

When auto-fix applies, pre-commit will detect the file changes and fail the
commit — the developer simply re-stages and commits again.

Exit codes:
    0 - Docs are in sync (or were auto-fixed and staged)
    1 - Sync script failed
"""

from __future__ import annotations

import io
import subprocess
import sys

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


def get_modified_doc_files() -> list[str]:
    """Check if any doc files were modified by the sync script (unstaged changes)."""
    result = run(["git", "diff", "--name-only"])
    if result.returncode != 0:
        return []
    return [f for f in result.stdout.strip().split("\n") if f.strip() and any(kw in f for kw in DOCS_KEYWORDS)]


def main() -> int:
    # Step 1: Run the sync script
    print("🔍 Checking MCP tool documentation sync...")
    result = run(["uv", "run", "python", "scripts/count_mcp_tools.py", "--update-docs"])

    if result.returncode != 0:
        print("❌ MCP tool count sync script failed:")
        print(result.stderr or result.stdout)
        return 1

    # Step 2: Check if docs were modified (indicating they were out of sync)
    modified = get_modified_doc_files()
    if not modified:
        print("✅ MCP tool docs are in sync")
        return 0

    # Step 3: Auto-stage the updated files
    stage_result = run(["git", "add", *modified])
    if stage_result.returncode != 0:
        print("❌ Failed to stage auto-updated files:")
        print(stage_result.stderr)
        return 1

    print("🔄 MCP tool docs were out of sync — auto-updated and staged:")
    for f in modified:
        print(f"  ✅ {f}")
    print()
    print("The commit will proceed with the updated docs included.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
