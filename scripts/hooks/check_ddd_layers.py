#!/usr/bin/env python3
"""
Pre-commit hook: Enforce DDD layer dependency rules.

Auto-fix:  ❌ No — architecture violations require refactoring.
Scope:     src/pubmed_search/**/*.py

DDD Layer Rules (inner cannot import outer):
  - domain/      → may NOT import application/, infrastructure/, presentation/
  - application/  → may NOT import infrastructure/, presentation/
  - shared/       → may NOT import domain/, application/, infrastructure/, presentation/

Allowed:
  - Any layer may import from shared/
  - presentation/ may import from anything
  - infrastructure/ may import from domain/ and application/

Exit codes:
    0 - No DDD violations
    1 - Layer dependency violations found
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
# DDD Layer Rules
# ─────────────────────────────────────────────────────────────

PACKAGE_ROOT = "pubmed_search"

# Map layer name → set of layers it CANNOT import from
FORBIDDEN_IMPORTS: dict[str, set[str]] = {
    "domain": {"application", "infrastructure", "presentation"},
    "application": {"infrastructure", "presentation"},
    "shared": {"domain", "application", "infrastructure", "presentation"},
    # infrastructure and presentation have no restrictions
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
        if f.strip()
        and f.endswith(".py")
        and f.startswith(f"src/{PACKAGE_ROOT}/")
    ]


def get_layer(filepath: str) -> str | None:
    """Extract the DDD layer from a file path.

    Example: src/pubmed_search/domain/entities/article.py → 'domain'
    """
    parts = Path(filepath).parts
    try:
        pkg_idx = list(parts).index(PACKAGE_ROOT)
        if pkg_idx + 1 < len(parts):
            return parts[pkg_idx + 1]
    except ValueError:
        pass
    return None


def check_file(filepath: str) -> list[tuple[int, str, str]]:
    """Return list of (line_number, import_module, violated_layer)."""
    layer = get_layer(filepath)
    if layer is None or layer not in FORBIDDEN_IMPORTS:
        return []

    forbidden = FORBIDDEN_IMPORTS[layer]

    try:
        content = Path(filepath).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    violations: list[tuple[int, str, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                violated = _check_import_name(alias.name, forbidden)
                if violated:
                    violations.append((node.lineno, alias.name, violated))
        elif isinstance(node, ast.ImportFrom) and node.module:
            violated = _check_import_name(node.module, forbidden)
            if violated:
                violations.append((node.lineno, node.module, violated))

    return violations


def _check_import_name(module_name: str, forbidden: set[str]) -> str | None:
    """Check if an import name references a forbidden layer."""
    # Match patterns like:
    #   pubmed_search.infrastructure.xxx
    #   pubmed_search.presentation.xxx
    for layer in forbidden:
        if (
            module_name == f"{PACKAGE_ROOT}.{layer}"
            or module_name.startswith(f"{PACKAGE_ROOT}.{layer}.")
        ):
            return layer
    return None


def main() -> int:
    staged = get_staged_files()
    if not staged:
        return 0

    all_violations: dict[str, list[tuple[int, str, str]]] = {}

    for filepath in staged:
        violations = check_file(filepath)
        if violations:
            all_violations[filepath] = violations

    if all_violations:
        total = sum(len(v) for v in all_violations.values())
        print(f"❌ Found {total} DDD layer violation(s):")
        print()
        for filepath, violations in all_violations.items():
            layer = get_layer(filepath)
            for lineno, module, violated_layer in violations:
                print(f"  {filepath}:{lineno}")
                print(f"    {layer}/ imports {violated_layer}/ → {module}")
        print()
        print("📐 DDD Layer Rules:")
        print("    domain/      → may NOT import application/, infrastructure/, presentation/")
        print("    application/  → may NOT import infrastructure/, presentation/")
        print("    shared/       → may NOT import any other layer")
        print()
        print("🔧 Fix: Use dependency injection or define interfaces in the inner layer.")
        print()
        print("💡 Agent reminder: Follow DDD dependency direction — inner layers MUST NOT")
        print("   import from outer layers. Use the DI container for cross-layer wiring.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
