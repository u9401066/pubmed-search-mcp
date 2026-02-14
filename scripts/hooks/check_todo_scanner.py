#!/usr/bin/env python3
"""
Pre-commit hook: Scan for TODO/FIXME/HACK/XXX markers and remind the agent.

Auto-fix:  ❌ No — these need to be resolved, not removed.
Scope:     src/**/*.py  and  tests/**/*.py

Why it matters:
  - TODO/FIXME markers indicate unfinished work
  - They should be tracked and resolved before release
  - HACK/XXX markers indicate fragile code requiring attention
  - This hook WARNS but does NOT block the commit (exit 0)

Behavior:
  - Reports all markers found in staged files
  - Groups by urgency: FIXME/HACK/XXX (⚠️ high) vs TODO (📝 low)
  - Always exits 0 (warning only, non-blocking)
  - Set BLOCK_ON_MARKERS=true env var to make it blocking

Exit codes:
    0 - Always (warning mode), or no markers found
    1 - Only when BLOCK_ON_MARKERS=true and markers found
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

SCOPE_DIRS = ("src/", "tests/")

# Markers to scan for (case-insensitive in comments)
HIGH_PRIORITY = {"FIXME", "HACK", "XXX"}
LOW_PRIORITY = {"TODO"}

MARKER_RE = re.compile(
    r"#\s*\b(TODO|FIXME|HACK|XXX)\b[:\s]*(.*)",
    re.IGNORECASE,
)


def get_staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACRM"],
        capture_output=True,
        text=True,
    )
    return [
        f
        for f in result.stdout.strip().split("\n")
        if f.strip() and f.endswith(".py") and any(f.startswith(d) for d in SCOPE_DIRS)
    ]


def scan_file(filepath: str) -> list[tuple[int, str, str]]:
    """Return list of (line_number, marker, description)."""
    try:
        content = Path(filepath).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    markers: list[tuple[int, str, str]] = []

    for i, line in enumerate(content.splitlines(), start=1):
        match = MARKER_RE.search(line)
        if match:
            marker = match.group(1).upper()
            description = match.group(2).strip() or "(no description)"
            markers.append((i, marker, description))

    return markers


def main() -> int:
    staged = get_staged_files()
    if not staged:
        return 0

    block_mode = os.environ.get("BLOCK_ON_MARKERS", "").lower() in ("true", "1", "yes")

    high_items: list[tuple[str, int, str, str]] = []
    low_items: list[tuple[str, int, str, str]] = []

    for filepath in staged:
        markers = scan_file(filepath)
        for lineno, marker, desc in markers:
            if marker in HIGH_PRIORITY:
                high_items.append((filepath, lineno, marker, desc))
            else:
                low_items.append((filepath, lineno, marker, desc))

    if not high_items and not low_items:
        return 0

    total = len(high_items) + len(low_items)
    print(f"📋 Found {total} marker(s) in staged files:")
    print()

    if high_items:
        print(f"  ⚠️  HIGH PRIORITY ({len(high_items)}):")
        for filepath, lineno, marker, desc in high_items:
            print(f"    {filepath}:{lineno}  [{marker}] {desc}")
        print()

    if low_items:
        print(f"  📝 LOW PRIORITY ({len(low_items)}):")
        for filepath, lineno, marker, desc in low_items:
            print(f"    {filepath}:{lineno}  [{marker}] {desc}")
        print()

    print("💡 Agent reminder: Resolve markers before release.")
    if high_items:
        print("   ⚠️  FIXME/HACK/XXX items indicate fragile or broken code.")
        print("   These should be fixed in this PR if possible.")
    print()

    if block_mode and (high_items or low_items):
        print("🚫 BLOCK_ON_MARKERS=true — commit blocked.")
        return 1

    print("ℹ️  This is a warning only. Commit will proceed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
