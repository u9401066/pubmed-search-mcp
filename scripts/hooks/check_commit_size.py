#!/usr/bin/env python3
"""
Pre-commit hook: Commit size guard.

Prevents oversized commits by limiting the number of staged files.
This enforces granular git history with clear context per commit.

Exit codes:
    0 - Commit size within limits
    1 - Too many staged files
"""

from __future__ import annotations

import io
import subprocess
import sys

# Force UTF-8 output on Windows (cp950 can't encode emoji)
if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

MAX_STAGED_FILES = 30

# File patterns that don't count toward the limit
# (auto-generated or always bulk-updated together)
EXEMPT_PATTERNS: set[str] = {
    "uv.lock",
    "htmlcov/",
    "memory-bank/",
}


def get_staged_files() -> list[str]:
    """Get list of staged files (excluding deleted)."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=d"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [f for f in result.stdout.strip().split("\n") if f.strip()]


def is_exempt(filepath: str) -> bool:
    """Check if a file is exempt from the limit."""
    return any(filepath.startswith(pat) or filepath == pat for pat in EXEMPT_PATTERNS)


def main() -> int:
    staged = get_staged_files()
    counted = [f for f in staged if not is_exempt(f)]
    total = len(counted)
    exempt_count = len(staged) - total

    if total <= MAX_STAGED_FILES:
        if exempt_count > 0:
            print(f"✅ Commit size: {total} files (+{exempt_count} exempt) ≤ {MAX_STAGED_FILES} limit")
        else:
            print(f"✅ Commit size: {total} files ≤ {MAX_STAGED_FILES} limit")
        return 0

    print(f"❌ Commit too large: {total} files staged (limit: {MAX_STAGED_FILES})")
    print()
    print("Split your commit into smaller, focused changes:")
    print("  git reset HEAD -- <files>   # unstage files")
    print("  git add -p                  # stage partial changes")
    print()
    print(f"Staged files ({total}):")
    for f in sorted(counted):
        print(f"  {f}")

    if exempt_count > 0:
        print(f"\n(+{exempt_count} exempt files not counted)")

    print()
    print("To bypass this check (emergency only):")
    print("  git commit --no-verify")

    return 1


if __name__ == "__main__":
    sys.exit(main())
