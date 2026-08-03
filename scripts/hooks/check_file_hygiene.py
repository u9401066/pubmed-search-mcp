#!/usr/bin/env python3
"""
Pre-commit hook: File hygiene check.

Ensures no forbidden temporary files are committed.
Rules based on .github/copilot-instructions.md file hygiene spec.

Only newly added paths are judged. Files already present at HEAD were accepted
when they landed, so re-checking them would block edits to existing files
without preventing any new clutter.

Exit codes:
    0 - Clean
    1 - Violations found
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import PurePosixPath

# Force UTF-8 output on Windows (cp950 can't encode emoji)
if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ─────────────────────────────────────────────────────────────
# Whitelist: allowed root-level files
# ─────────────────────────────────────────────────────────────

ALLOWED_ROOT_FILES: set[str] = {
    # Config
    "pyproject.toml",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.https.yml",
    ".gitignore",
    ".gitattributes",
    ".pre-commit-config.yaml",
    ".python-version",
    "uv.lock",
    # Docs
    "README.md",
    "README.zh-TW.md",
    "CITATION.cff",
    "CHANGELOG.md",
    "CONSTITUTION.md",
    "ARCHITECTURE.md",
    "ROADMAP.md",
    "CONTRIBUTING.md",
    "DEPLOYMENT.md",
    "TOOLS_INDEX.md",
    "AGENTS.md",
    "LICENSE",
    # Entry points
    "run_copilot.py",
    "run_server.py",
    "start.sh",
    # Tool config
    "vulture_whitelist.py",
    # Hook state
    ".instruction_drift_fingerprint",
}

ALLOWED_ROOT_DIRS: set[str] = {
    "src",
    "tests",
    "scripts",
    "docs",
    "data",
    "nginx",
    "htmlcov",
    "memory-bank",
    "copilot-studio",
    ".git",
    ".github",
    ".claude",
    ".clinerules",
    # Agent harnesses that ship with the repo, peers of .claude/.clinerules
    ".cline",
    ".codex",
    ".asset-aware-mcp",
    ".vscode",
    ".ruff_cache",
    ".mypy_cache",
    "__pycache__",
    ".pytest_cache",
}

TEMP_EXTENSIONS: set[str] = {".txt", ".log", ".tmp", ".bak", ".out"}


def get_staged_files() -> list[str]:
    """Get files staged for commit (Added, Copied, Renamed, Modified)."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACRM"],
        capture_output=True,
        text=True,
    )
    return [f for f in result.stdout.strip().split("\n") if f.strip()]


def get_committed_files() -> set[str]:
    """Return files that already exist at HEAD.

    A file that is already in the repository was accepted at some point, so
    re-judging it on every edit cannot improve hygiene. It only produces a
    deadlock: an auto-fixing hook rewrites the file, this hook refuses to let
    it be staged, and the change can never be committed either way.
    """
    result = subprocess.run(
        ["git", "ls-tree", "-r", "HEAD", "--name-only"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:  # No HEAD yet, e.g. the initial commit.
        return set()
    return {f for f in result.stdout.split("\n") if f.strip()}


def check_file(filepath: str) -> str | None:
    """Check a single staged file for hygiene violations. Returns error or None."""
    path = PurePosixPath(filepath)
    parts = path.parts

    # Root-level file check
    if len(parts) == 1:
        if path.name not in ALLOWED_ROOT_FILES:
            return f"Forbidden root file: {filepath} (not in whitelist)"

    # Root-level directory check
    if len(parts) >= 2:
        root_dir = parts[0]
        if root_dir.startswith("."):
            # Hidden dirs like .github, .claude are OK if in whitelist
            if root_dir not in ALLOWED_ROOT_DIRS:
                return f"Forbidden hidden directory: {root_dir}/"
        # No check for subdirectory names (only root-level matters)

    # scripts/ temp file check (allow scripts/_tmp/)
    if len(parts) >= 2 and parts[0] == "scripts":
        if parts[1] != "_tmp" and path.suffix in TEMP_EXTENSIONS:
            return f"Temp file in scripts/: {filepath} (use scripts/_tmp/ instead)"

    return None


def main() -> int:
    staged = get_staged_files()
    if not staged:
        return 0

    already_committed = get_committed_files()
    violations: list[str] = []
    for f in staged:
        if f in already_committed:
            continue
        error = check_file(f)
        if error:
            violations.append(error)

    if violations:
        print("❌ File hygiene violations found:")
        print()
        for v in violations:
            print(f"  • {v}")
        print()
        print("Fix: remove temp files, or move to scripts/_tmp/ (gitignored)")
        print("     To update the whitelist, edit scripts/hooks/check_file_hygiene.py")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
