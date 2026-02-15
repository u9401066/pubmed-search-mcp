#!/usr/bin/env python3
"""
Pre-commit hook: Guard per-source API count display in search results.

Auto-fix:  ❌ No — requires correct implementation of count tracking.
Scope:     src/pubmed_search/presentation/mcp_server/tools/unified_formatting.py

Why it matters:
  Per-source API return counts (e.g., "pubmed (8/500), openalex (5)")
  are CRITICAL for agent decision-making. Without counts, the agent
  cannot assess search coverage or decide whether additional sources
  are needed. This hook ensures:

  1. The format function accepts source_api_counts parameter
  2. The **Sources** display includes parenthesized counts
  3. Tests exist that guard this behavior

Exit codes:
    0 - Per-source count display is properly implemented
    1 - Source count display is missing or broken
"""

from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

# After refactoring, _format_unified_results() lives in unified_formatting.py
# while **Sources** display logic may span both files.
FORMATTING_PY = Path("src/pubmed_search/presentation/mcp_server/tools/unified_formatting.py")
UNIFIED_PY = Path("src/pubmed_search/presentation/mcp_server/tools/unified.py")

# Patterns that MUST exist in the formatting module or unified.py
REQUIRED_PATTERNS = [
    # The format function must accept source_api_counts
    "source_api_counts",
    # Must have **Sources** display with parenthesized counts
    "**Sources**",
]

# Test files that must contain per-source count guard tests
GUARD_TEST_PATTERNS = {
    Path("tests/test_unified_tools.py"): "source_api_counts",
    Path("tests/test_pipeline.py"): "source_api_counts",
}


def check_format_function_signature(tree: ast.Module) -> list[str]:
    """Verify _format_unified_results accepts source_api_counts parameter."""
    errors: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "_format_unified_results":
                arg_names = [a.arg for a in node.args.args + node.args.kwonlyargs]
                if "source_api_counts" not in arg_names:
                    errors.append(
                        f"  Line {node.lineno}: _format_unified_results() missing 'source_api_counts' parameter"
                    )
                return errors
    errors.append("  _format_unified_results() function not found in unified_formatting.py")
    return errors


def check_source_display_logic(content: str) -> list[str]:
    """Verify per-source counts are displayed with numeric values."""
    errors: list[str] = []

    # Must have Sources display
    if "**Sources**" not in content:
        errors.append("  Missing '**Sources**' display in formatting module")

    # Must NOT have the old pattern of showing only source names without counts
    # Old broken pattern: stats.by_source.keys()  (loses count values)
    if "by_source.keys()" in content:
        errors.append(
            "  Found 'by_source.keys()' — this loses per-source counts! Use 'by_source.items()' to preserve counts."
        )

    return errors


def check_guard_tests() -> list[str]:
    """Verify test files contain per-source count guard assertions."""
    errors: list[str] = []
    for test_file, pattern in GUARD_TEST_PATTERNS.items():
        if not test_file.exists():
            errors.append(f"  Guard test file missing: {test_file}")
            continue
        content = test_file.read_text(encoding="utf-8")
        if pattern not in content:
            errors.append(
                f"  {test_file}: missing '{pattern}' guard test — per-source counts must have test protection"
            )
    return errors


def main() -> int:
    # After refactoring, function definitions are in unified_formatting.py
    target_file = FORMATTING_PY if FORMATTING_PY.exists() else UNIFIED_PY
    if not target_file.exists():
        print("source-counts-guard: formatting module not found, skipping")
        return 0

    content = target_file.read_text(encoding="utf-8")
    tree = ast.parse(content)
    all_errors: list[str] = []

    all_errors.extend(check_format_function_signature(tree))
    all_errors.extend(check_source_display_logic(content))
    all_errors.extend(check_guard_tests())

    if all_errors:
        print("❌ source-counts-guard: Per-source API count display violations found:\n")
        for err in all_errors:
            print(err)
        print(
            "\n💡 Per-source API return counts are a CRITICAL feature for agent decision-making."
            "\n   The agent needs to know how many results each source returned."
            "\n   See: _format_unified_results() source_api_counts parameter"
        )
        print("\n🤖 [Agent Reminder] Fix the source count display before committing.")
        return 1

    print("✅ source-counts-guard: Per-source API count display verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
