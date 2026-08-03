#!/usr/bin/env python3
"""
Pre-commit hook: Ensure presentation-layer storage paths are tenant-scoped.

Auto-fix:  ❌ No — requires routing the path through ``tenant_data_dir()``.
Scope:     src/pubmed_search/presentation/**/*.py

Why it matters:
  - A deployed server handles many agents; each is a separate tenant
  - Any store built straight from ``settings.data_dir`` is shared by every
    caller, so one agent reads and overwrites another agent's artifacts
  - This already happened once for sessions, chronicles, pipelines, and notes
  - ``pubmed_search.shared.tenancy.tenant_data_dir()`` is the single rule:
    the default tenant keeps the shared root, every other tenant is isolated

Escape hatch:
  Append ``# tenant-ok: <reason>`` to the line when the shared root is correct
  (for example when the value is only used as the base for a per-tenant store).

Exit codes:
    0 - All presentation-layer data_dir reads are tenant-scoped
    1 - Unscoped data_dir reads found
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

CHECKED_PREFIX = "src/pubmed_search/presentation/"

#: Attribute reads that resolve to a storage root.
GUARDED_ATTRS = {"data_dir"}

#: Call that applies the tenant rule.
SCOPING_CALL = "tenant_data_dir"

#: Per-line opt-out marker.
ALLOW_MARKER = "# tenant-ok:"


def get_staged_files() -> list[str]:
    """Return staged presentation-layer Python files."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACRM"],
        capture_output=True,
        text=True,
        check=False,
    )
    return [f for f in result.stdout.split("\n") if f.strip().startswith(CHECKED_PREFIX) and f.endswith(".py")]


def _scoped_nodes(tree: ast.AST) -> set[int]:
    """Return ids of nodes that appear inside a ``tenant_data_dir(...)`` call."""
    scoped: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name != SCOPING_CALL:
            continue
        for child in ast.walk(node):
            scoped.add(id(child))
    return scoped


def check_file(filepath: str) -> list[tuple[int, str]]:
    """Return ``(line_number, source_line)`` for unscoped storage-root reads."""
    try:
        content = Path(filepath).read_text(encoding="utf-8")
        tree = ast.parse(content)
    except (OSError, UnicodeDecodeError, SyntaxError):
        return []

    lines = content.splitlines()
    scoped = _scoped_nodes(tree)
    violations: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr not in GUARDED_ATTRS:
            continue
        if id(node) in scoped:
            continue
        line_text = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
        if ALLOW_MARKER in line_text:
            continue
        violations.append((node.lineno, line_text))

    return violations


def main() -> int:
    """Run the check over staged presentation-layer files."""
    all_violations: dict[str, list[tuple[int, str]]] = {}

    for filepath in get_staged_files():
        violations = check_file(filepath)
        if violations:
            all_violations[filepath] = violations

    if not all_violations:
        return 0

    total = sum(len(v) for v in all_violations.values())
    print(f"❌ Found {total} unscoped storage-root read(s) in the presentation layer:")
    print()
    for filepath, violations in all_violations.items():
        for lineno, line_text in violations:
            print(f"  {filepath}:{lineno}  →  {line_text}")
    print()
    print("📐 Tenancy Rule: every store built under the data directory must be")
    print("   resolved per tenant, otherwise agents share each other's artifacts.")
    print()
    print("🔧 Fix:")
    print("   from pubmed_search.shared.tenancy import tenant_data_dir")
    print("   root = tenant_data_dir(settings.data_dir)")
    print()
    print(f"💡 If the shared root is genuinely correct, append `{ALLOW_MARKER} <reason>`.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
