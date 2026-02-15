#!/usr/bin/env python3
"""
Pre-commit hook: Detect potential instruction drift.

When MCP tool docstrings or parameters change, the hand-written sections
of instructions.py may become stale. This hook computes a fingerprint
of tool signatures and compares it against a stored baseline. If the
fingerprint changes, it emits a **warning** reminding the developer to
review instructions.py.

Workflow:
1. Scan all @mcp.tool() functions in tools/*.py for signature + docstring.
2. Hash the collected signatures into a single fingerprint.
3. Compare against .instruction_drift_fingerprint (auto-created).
4. If different → warn (non-blocking).
5. Auto-update the fingerprint file and stage it.

Exit codes:
    0 - Always (warning-only hook, never blocks).
"""

from __future__ import annotations

import ast
import hashlib
import io
import re
import subprocess
import sys
from pathlib import Path

# Force UTF-8 output on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS_DIR = ROOT / "src" / "pubmed_search" / "presentation" / "mcp_server" / "tools"
INSTRUCTIONS_FILE = ROOT / "src" / "pubmed_search" / "presentation" / "mcp_server" / "instructions.py"
FINGERPRINT_FILE = ROOT / ".instruction_drift_fingerprint"


def extract_tool_signatures(tools_dir: Path) -> list[str]:
    """Extract function name + parameters + first 200 chars of docstring from @tool functions."""
    signatures: list[str] = []

    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                continue

            # Check if decorated with @mcp.tool or similar
            is_tool = False
            for decorator in node.decorator_list:
                dec_src = ast.dump(decorator)
                if "tool" in dec_src.lower():
                    is_tool = True
                    break

            if not is_tool:
                continue

            # Build signature: function_name(param1, param2, ...)
            args = node.args
            param_names = [a.arg for a in args.args if a.arg != "self"]
            sig = f"{py_file.name}::{node.name}({', '.join(param_names)})"

            # Extract docstring (first 200 chars)
            docstring = ast.get_docstring(node) or ""
            # Normalize whitespace for stable hashing
            docstring_normalized = re.sub(r"\s+", " ", docstring[:200]).strip()

            signatures.append(f"{sig}|{docstring_normalized}")

    return signatures


def compute_fingerprint(signatures: list[str]) -> str:
    """Compute SHA-256 fingerprint of all tool signatures."""
    combined = "\n".join(sorted(signatures))
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]


def read_stored_fingerprint() -> str | None:
    """Read the stored fingerprint, if it exists."""
    if not FINGERPRINT_FILE.exists():
        return None
    return FINGERPRINT_FILE.read_text(encoding="utf-8").strip()


def write_fingerprint(fingerprint: str) -> None:
    """Write the fingerprint and stage it."""
    FINGERPRINT_FILE.write_text(fingerprint + "\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", str(FINGERPRINT_FILE)],
        capture_output=True,
        text=True,
    )


def main() -> int:
    if not TOOLS_DIR.exists():
        return 0

    signatures = extract_tool_signatures(TOOLS_DIR)
    if not signatures:
        return 0

    current_fp = compute_fingerprint(signatures)
    stored_fp = read_stored_fingerprint()

    if stored_fp is None:
        # First run — create baseline
        print(f"📝 instruction-drift: Creating initial fingerprint ({current_fp})")
        write_fingerprint(current_fp)
        return 0

    if current_fp == stored_fp:
        # No change
        return 0

    # Fingerprint changed — tool signatures/docstrings were modified
    print("⚠️  instruction-drift: MCP tool signatures or docstrings have changed!")
    print(f"   Previous fingerprint: {stored_fp}")
    print(f"   Current  fingerprint: {current_fp}")
    print()
    print("   👉 Please review and update the hand-written sections of:")
    print(f"      {INSTRUCTIONS_FILE.relative_to(ROOT)}")
    print()
    print("   The auto-synced tool list is handled by tool-count-sync,")
    print("   but strategy guides, usage examples, and feature descriptions")
    print("   in instructions.py must be updated manually.")
    print()
    print("   Also consider updating .github/copilot-instructions.md")
    print()

    # Auto-update fingerprint (so warning appears only once per change)
    write_fingerprint(current_fp)
    print(f"   ✅ Fingerprint auto-updated to {current_fp}")

    # Always return 0 — this is a warning-only hook
    return 0


if __name__ == "__main__":
    sys.exit(main())
