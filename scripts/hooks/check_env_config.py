#!/usr/bin/env python3
"""
Pre-commit hook: Ban ``os.environ`` / ``os.getenv`` in inner DDD layers.

Auto-fix:  ❌ No — requires using DI container or settings object.
Scope:     src/pubmed_search/{domain,application,shared}/**/*.py

Why it matters:
  - DDD inner layers (domain, application, shared) must be pure business logic
  - Environment variables are an infrastructure concern
  - Config should be injected via the DI container or settings objects
  - Only presentation/ and container.py may read os.environ

Exit codes:
    0 - No env access in inner layers
    1 - Environment access found in inner layers
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

PACKAGE_ROOT = "pubmed_search"

# Only check inner DDD layers
INNER_LAYERS = {"domain", "application", "shared"}

# Allowed files (they act as infrastructure glue)
ALLOWED_FILES: set[str] = set()


def get_staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACRM"],
        capture_output=True,
        text=True,
    )
    files = []
    for f in result.stdout.strip().split("\n"):
        if not f.strip() or not f.endswith(".py"):
            continue
        if not f.startswith(f"src/{PACKAGE_ROOT}/"):
            continue
        # Check if file is in an inner layer
        parts = Path(f).parts
        try:
            pkg_idx = list(parts).index(PACKAGE_ROOT)
            if pkg_idx + 1 < len(parts) and parts[pkg_idx + 1] in INNER_LAYERS:
                files.append(f)
        except ValueError:
            continue
    return files


def check_file(filepath: str) -> list[tuple[int, str]]:
    """Return list of (line_number, description) for os.environ/os.getenv usage."""
    if Path(filepath).name in ALLOWED_FILES:
        return []

    try:
        content = Path(filepath).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    violations: list[tuple[int, str]] = []
    lines = content.splitlines()

    for node in ast.walk(tree):
        # os.environ['KEY'] or os.environ.get('KEY')
        if isinstance(node, ast.Attribute):
            if (
                isinstance(node.value, ast.Name)
                and node.value.id == "os"
                and node.attr in ("environ", "getenv")
            ):
                line_text = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
                violations.append((node.lineno, line_text))

        # os.getenv('KEY')
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
                and node.func.attr == "getenv"
            ):
                # Avoid double-counting with the attribute check above
                pass

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
        print(f"❌ Found {total} os.environ/os.getenv usage(s) in inner DDD layers:")
        print()
        for filepath, violations in all_violations.items():
            for lineno, line_text in violations:
                print(f"  {filepath}:{lineno}  →  {line_text}")
        print()
        print("📐 DDD Rule: Inner layers (domain/, application/, shared/) must NOT")
        print("   read environment variables directly.")
        print()
        print("🔧 Fix: Inject configuration via the DI container or settings object.")
        print("   Only presentation/ and container.py may access os.environ.")
        print()
        print("💡 Agent reminder: Use dependency injection for configuration.")
        print("   Import settings from the container, NOT from os.environ.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
