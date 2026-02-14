#!/usr/bin/env python3
"""
Pre-commit hook: Ban ``print()`` calls in production source code.

Auto-fix:  ❌ No — requires human/agent judgment (use ``logger.info()`` instead).
Scope:     src/**/*.py
Skip:      ``__main__.py``, CLI entry points.

Why it matters:
  - Production code should use structured logging via ``logging`` module
  - ``print()`` bypasses log levels, formatters, and handlers
  - Makes debugging in production impossible

Exit codes:
    0 - No print() calls found
    1 - print() calls detected
"""

from __future__ import annotations

import ast
import io
import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

SCOPE_DIR = "src/"

# Files allowed to use print() (CLI entry points, etc.)
ALLOWED_FILES = {
    "__main__.py",
    "run_server.py",
    "run_copilot.py",
}


def get_staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACRM"],
        capture_output=True,
        text=True,
    )
    return [
        f
        for f in result.stdout.strip().split("\n")
        if f.strip() and f.endswith(".py") and f.startswith(SCOPE_DIR)
    ]


def check_file(filepath: str) -> list[tuple[int, str]]:
    """Return list of (line_number, line_text) for print() calls."""
    if Path(filepath).name in ALLOWED_FILES:
        return []

    try:
        content = Path(filepath).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    violations: list[tuple[int, str]] = []

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    lines = content.splitlines()

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            lineno = node.lineno
            line_text = lines[lineno - 1].strip() if lineno <= len(lines) else ""
            violations.append((lineno, line_text))

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
        print(f"❌ Found {total} print() call(s) in production code:")
        print()
        for filepath, violations in all_violations.items():
            for lineno, line_text in violations:
                print(f"  {filepath}:{lineno}  →  {line_text}")
        print()
        print("🔧 Fix: Replace print() with logger.info() or logger.debug()")
        print("   Example:")
        print("     import logging")
        print("     logger = logging.getLogger(__name__)")
        print("     logger.info('message here')")
        print()
        print("💡 Agent reminder: NEVER use print() in src/. Use the logging module.")
        print("   Allowed exceptions: __main__.py, run_server.py, run_copilot.py")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
