#!/usr/bin/env python3
"""
Pre-commit hook: Ban bare ``# type: ignore`` without error codes.

Auto-fix:  ❌ No — requires knowing the correct mypy error code.
Scope:     src/**/*.py  and  tests/**/*.py

Why it matters:
  - Bare ``# type: ignore`` suppresses ALL mypy errors on that line
  - This hides real bugs and defeats the purpose of type checking
  - Always specify: ``# type: ignore[assignment]``, ``# type: ignore[arg-type]``, etc.

Exit codes:
    0 - No bare type: ignore found
    1 - Bare type: ignore comments detected
"""

from __future__ import annotations

import io
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

# Match "# type: ignore" NOT followed by "[" (i.e., bare ignore)
BARE_IGNORE_RE = re.compile(r"#\s*type:\s*ignore(?!\[)")


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


def check_file(filepath: str) -> list[tuple[int, str]]:
    """Return list of (line_number, line_text) for bare type: ignore."""
    try:
        content = Path(filepath).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    violations: list[tuple[int, str]] = []

    for i, line in enumerate(content.splitlines(), start=1):
        if BARE_IGNORE_RE.search(line):
            violations.append((i, line.strip()))

    return violations


def main() -> int:
    staged = get_staged_files()
    if not staged:
        return 0

    all_violations: dict[str, list[tuple[int, str]]] = {}

    for filepath in staged:
        violations = check_file(filepath)
        if violations:
            all_violations[filepath] = violations

    if all_violations:
        total = sum(len(v) for v in all_violations.values())
        print(f"❌ Found {total} bare '# type: ignore' comment(s):")
        print()
        for filepath, violations in all_violations.items():
            for lineno, line_text in violations:
                print(f"  {filepath}:{lineno}  →  {line_text}")
        print()
        print("🔧 Fix: Add the specific mypy error code in brackets:")
        print("   ❌ # type: ignore")
        print("   ✅ # type: ignore[assignment]")
        print("   ✅ # type: ignore[arg-type]")
        print("   ✅ # type: ignore[return-value]")
        print()
        print("   Run 'uv run mypy <file>' to see the exact error code.")
        print()
        print("💡 Agent reminder: NEVER use bare '# type: ignore'.")
        print("   Always specify the error code so real type errors aren't hidden.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
