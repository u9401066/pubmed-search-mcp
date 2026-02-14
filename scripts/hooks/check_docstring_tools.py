#!/usr/bin/env python3
"""
Pre-commit hook: Require docstrings on MCP tool functions.

Auto-fix:  ❌ No — docstrings need meaningful content.
Scope:     src/pubmed_search/presentation/mcp_server/tools/**/*.py

Why it matters:
  - MCP tool docstrings become the tool description shown to AI agents
  - Missing docstrings make tools invisible/unusable to agents
  - FastMCP uses the function docstring as the tool's help text

Exit codes:
    0 - All tool functions have docstrings
    1 - Tool functions missing docstrings
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

TOOLS_DIR = "src/pubmed_search/presentation/mcp_server/tools"

# Decorator names that mark MCP tools (checked on the decorator itself)
TOOL_DECORATORS = {"tool", "mcp.tool"}

# Functions that are NOT tools (helpers, internal)
SKIP_FUNCTIONS = {"register_", "_"}  # prefixes


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
        and f.startswith(TOOLS_DIR)
    ]


def _is_tool_decorator(node: ast.expr) -> bool:
    """Check if a decorator looks like @mcp.tool() or similar."""
    # @tool or @tool()
    if isinstance(node, ast.Name) and node.id == "tool":
        return True
    if isinstance(node, ast.Call):
        return _is_tool_decorator(node.func)
    # @mcp.tool()
    return isinstance(node, ast.Attribute) and node.attr == "tool"


def _should_skip_function(name: str) -> bool:
    """Check if function should be skipped (helpers, private, register_*)."""
    return any(name.startswith(prefix) for prefix in SKIP_FUNCTIONS)


def check_file(filepath: str) -> list[tuple[int, str]]:
    """Return list of (line_number, function_name) for tool functions without docstrings."""
    try:
        content = Path(filepath).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    violations: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        if _should_skip_function(node.name):
            continue

        # Check if it has a tool-like decorator
        has_tool_dec = any(_is_tool_decorator(d) for d in node.decorator_list)
        if not has_tool_dec:
            continue

        # Check for docstring
        docstring = ast.get_docstring(node)
        if not docstring or len(docstring.strip()) < 10:
            violations.append((node.lineno, node.name))

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
        print(f"❌ Found {total} MCP tool function(s) missing docstrings:")
        print()
        for filepath, violations in all_violations.items():
            for lineno, func_name in violations:
                print(f"  {filepath}:{lineno}  →  {func_name}()")
        print()
        print("🔧 Fix: Add a descriptive docstring to each @tool function.")
        print("   The docstring becomes the tool description shown to AI agents.")
        print()
        print("   @mcp.tool()")
        print("   async def search_literature(query: str) -> str:")
        print('       """Search PubMed for articles matching the query."""')
        print()
        print("💡 Agent reminder: Every @tool function MUST have a docstring ≥10 chars.")
        print("   This is the tool description visible to users and other agents.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
