#!/usr/bin/env python3
"""
Pre-commit hook: Enforce ``from __future__ import annotations`` (PEP 563).

Auto-fix:  ✅ Yes — inserts the import after the module docstring.
Scope:     src/**/*.py  and  tests/**/*.py
Skip:      __init__.py files that are empty or re-export only.

Why it matters:
  - Enables PEP 604 union syntax ``X | Y`` at runtime on Python 3.10
  - Defers annotation evaluation → faster import, avoids circular import issues
  - All new files MUST include it

Exit codes:
    0 - All files have the import (or were auto-fixed)
    1 - Files still missing the import (dry-run / unfixable)
"""

from __future__ import annotations

import ast
import io
import subprocess
import sys
from pathlib import Path

# Force UTF-8 output on Windows (cp950 can't encode emoji)
if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

TARGET = "from __future__ import annotations"

# Files that can skip (empty __init__.py or pure-reexport __init__.py)
SKIP_EMPTY_INIT = True

# Only check staged Python files in these directories
SCOPE_DIRS = ("src/", "tests/")


def get_staged_files() -> list[str]:
    """Get Python files staged for commit."""
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


def is_skippable_init(filepath: str, content: str) -> bool:
    """Skip empty __init__.py or those with only imports/assignments/__all__."""
    if not filepath.endswith("__init__.py"):
        return False
    if not SKIP_EMPTY_INIT:
        return False
    stripped = content.strip()
    if not stripped:
        return True
    # If the file is very short (< 10 non-comment lines), skip
    lines = [line for line in stripped.splitlines() if line.strip() and not line.strip().startswith("#")]
    return len(lines) <= 3


def has_future_annotations(content: str) -> bool:
    """Check if the file already has ``from __future__ import annotations``."""
    return TARGET in content


def find_insert_position(content: str) -> int:
    """Find the byte offset to insert the future import.

    Rules:
      1. After the shebang line (if any)
      2. After the module docstring (if any)
      3. Before any other imports

    Returns the line number (0-based) to insert before.
    """
    lines = content.splitlines(keepends=True)

    insert_line = 0

    # Skip shebang
    if lines and lines[0].startswith("#!"):
        insert_line = 1

    # Skip encoding declaration
    if insert_line < len(lines) and lines[insert_line].strip().startswith("# -*-"):
        insert_line += 1

    # Try to detect module docstring using AST
    try:
        tree = ast.parse(content)
        if (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        ):
            # Docstring found — insert after it
            docstring_end_line = tree.body[0].end_lineno or tree.body[0].lineno
            insert_line = docstring_end_line
    except SyntaxError:
        pass

    # Skip blank lines after docstring
    while insert_line < len(lines) and not lines[insert_line].strip():
        insert_line += 1

    return insert_line


def fix_file(filepath: str, content: str) -> str:
    """Add ``from __future__ import annotations`` at the correct position."""
    insert_line = find_insert_position(content)
    lines = content.splitlines(keepends=True)

    # Insert the import + blank line
    import_line = TARGET + "\n"
    lines.insert(insert_line, "\n")
    lines.insert(insert_line, import_line)

    return "".join(lines)


def main() -> int:
    fix_mode = "--fix" in sys.argv
    staged = get_staged_files()

    if not staged:
        return 0

    missing: list[str] = []
    fixed: list[str] = []

    for filepath in staged:
        try:
            content = Path(filepath).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        if has_future_annotations(content):
            continue

        if is_skippable_init(filepath, content):
            continue

        if fix_mode:
            new_content = fix_file(filepath, content)
            Path(filepath).write_text(new_content, encoding="utf-8")
            fixed.append(filepath)
        else:
            missing.append(filepath)

    if fixed:
        print(f"🔧 Auto-fixed {len(fixed)} file(s) — added 'from __future__ import annotations':")
        for f in fixed:
            print(f"  ✅ {f}")
        print()
        print("💡 Agent reminder: all Python files in src/ and tests/ MUST have")
        print("   'from __future__ import annotations' as the first import.")
        # Return 1 so pre-commit re-stages
        return 1

    if missing:
        print(f"❌ {len(missing)} file(s) missing 'from __future__ import annotations':")
        print()
        for f in missing:
            print(f"  • {f}")
        print()
        print("🔧 Auto-fix: this hook will add the import automatically on commit.")
        print("💡 Agent reminder: ALWAYS include 'from __future__ import annotations'")
        print("   as the first import in every new Python file.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
