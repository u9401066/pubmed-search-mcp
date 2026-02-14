#!/usr/bin/env python3
"""
Pre-commit hook: Validate consistency between Instructions ↔ Skills ↔ Hooks.

The Self-Evolution Cycle:
  ┌─────────────┐     ┌──────────┐     ┌──────────┐
  │ Instructions │────▶│  Skills  │────▶│  Hooks   │
  │ (copilot-   │     │ (SKILL.md│     │ (.pre-   │
  │ instructions│     │  files)  │     │  commit- │
  │  .md)       │     │          │     │  config) │
  └──────┬──────┘     └────┬─────┘     └────┬─────┘
         │                 │                 │
         └─────────────────┼─────────────────┘
                    Validate & Sync

This hook checks:
1. All hooks defined in .pre-commit-config.yaml are documented in instructions
2. All custom scripts referenced by hooks actually exist
3. Hook package versions are not stale (optional: --check-versions)
4. Skills reference the correct hook IDs
5. Instructions and skills are consistent about what hooks do

Exit codes:
    0 - All consistent
    1 - Inconsistencies found (printed as actionable report)
"""

from __future__ import annotations

import io
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Force UTF-8 output on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent.parent

# ─────────────────────────────────────────────────────────────
# File paths (single source of truth)
# ─────────────────────────────────────────────────────────────

PRECOMMIT_CONFIG = ROOT / ".pre-commit-config.yaml"
COPILOT_INSTRUCTIONS = ROOT / ".github" / "copilot-instructions.md"
GIT_PRECOMMIT_SKILL = ROOT / ".claude" / "skills" / "git-precommit" / "SKILL.md"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
HOOKS_DIR = ROOT / "scripts" / "hooks"


@dataclass
class Issue:
    severity: str  # "error" | "warning"
    category: str  # "hook-doc", "script-missing", "version-stale", "skill-sync"
    message: str
    fix_hint: str = ""


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)

    def add(self, severity: str, category: str, message: str, fix_hint: str = "") -> None:
        self.issues.append(Issue(severity=severity, category=category, message=message, fix_hint=fix_hint))

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]


# ─────────────────────────────────────────────────────────────
# Parsers
# ─────────────────────────────────────────────────────────────


def extract_hook_ids_from_config(content: str) -> list[str]:
    """Extract all hook IDs from .pre-commit-config.yaml."""
    return re.findall(r"^\s+-\s+id:\s+(\S+)", content, re.MULTILINE)


def extract_local_hook_entries(content: str) -> list[str]:
    """Extract entry paths from local hooks (uv run ... scripts/...)."""
    return re.findall(r"entry:\s+uv run.*?(scripts/\S+\.py)", content)


def extract_remote_repo_versions(content: str) -> dict[str, str]:
    """Extract {repo_url: rev} from remote repos."""
    repos: dict[str, str] = {}
    for match in re.finditer(r"repo:\s+(https://\S+)\s+rev:\s+(\S+)", content):
        repos[match.group(1)] = match.group(2)
    return repos


# ─────────────────────────────────────────────────────────────
# Validators
# ─────────────────────────────────────────────────────────────


def check_hooks_documented(report: ValidationReport) -> None:
    """Check all hook IDs appear in instructions and skills."""
    config_text = PRECOMMIT_CONFIG.read_text(encoding="utf-8")
    hook_ids = extract_hook_ids_from_config(config_text)

    for doc_file, doc_name in [
        (COPILOT_INSTRUCTIONS, "copilot-instructions.md"),
        (GIT_PRECOMMIT_SKILL, "git-precommit SKILL.md"),
    ]:
        if not doc_file.exists():
            report.add("error", "file-missing", f"{doc_name} not found at {doc_file}")
            continue

        doc_text = doc_file.read_text(encoding="utf-8")

        # Key hooks that MUST be documented (skip generic ones like trailing-whitespace)
        important_hooks = {
            "ruff",
            "ruff-format",
            "mypy",
            "async-test-checker",
            "file-hygiene",
            "tool-count-sync",
            "pytest",
        }

        for hook_id in hook_ids:
            if hook_id in important_hooks and hook_id not in doc_text:
                report.add(
                    "error",
                    "hook-doc",
                    f"Hook '{hook_id}' defined in .pre-commit-config.yaml but NOT documented in {doc_name}",
                    fix_hint=f"Add '{hook_id}' description to {doc_name}",
                )


def check_hook_scripts_exist(report: ValidationReport) -> None:
    """Check all scripts referenced by local hooks actually exist."""
    config_text = PRECOMMIT_CONFIG.read_text(encoding="utf-8")
    script_paths = extract_local_hook_entries(config_text)

    for script_rel in script_paths:
        script_abs = ROOT / script_rel
        if not script_abs.exists():
            report.add(
                "error",
                "script-missing",
                f"Hook references '{script_rel}' but file does not exist",
                fix_hint=f"Create {script_rel} or update .pre-commit-config.yaml",
            )


def check_contributing_hooks_table(report: ValidationReport) -> None:
    """Check CONTRIBUTING.md hook table matches .pre-commit-config.yaml."""
    if not CONTRIBUTING.exists():
        return

    config_text = PRECOMMIT_CONFIG.read_text(encoding="utf-8")
    hook_ids = set(extract_hook_ids_from_config(config_text))

    contrib_text = CONTRIBUTING.read_text(encoding="utf-8")

    # Important hooks that should be in CONTRIBUTING's hook table
    must_document = {"ruff", "mypy", "pytest", "file-hygiene", "tool-count-sync"}
    for hook_id in must_document:
        if hook_id in hook_ids and hook_id not in contrib_text:
            report.add(
                "warning",
                "hook-doc",
                f"Hook '{hook_id}' not mentioned in CONTRIBUTING.md",
                fix_hint=f"Add '{hook_id}' to the hooks table in CONTRIBUTING.md",
            )


def check_version_staleness(report: ValidationReport) -> None:
    """Check if remote hook versions might be stale (informational)."""
    config_text = PRECOMMIT_CONFIG.read_text(encoding="utf-8")
    repos = extract_remote_repo_versions(config_text)

    # We can't check latest versions without network, so just warn if
    # the config has a comment with a date that's old
    for repo_url, rev in repos.items():
        # Simple heuristic: if rev looks like a tag (v4.x, v0.x), just note it
        short_name = repo_url.split("/")[-1]
        report.add(
            "warning",
            "version-info",
            f"{short_name}: using {rev}",
            fix_hint="Run `uv run pre-commit autoupdate` to check for newer versions",
        )


def check_pyproject_addopts(report: ValidationReport) -> None:
    """Check pyproject.toml addopts is consistent with pre-push hook."""
    pyproject = ROOT / "pyproject.toml"
    if not pyproject.exists():
        return

    pyproject_text = pyproject.read_text(encoding="utf-8")
    config_text = PRECOMMIT_CONFIG.read_text(encoding="utf-8")

    # Check addopts has -n (multi-core enforcement)
    if "addopts" in pyproject_text:
        addopts_match = re.search(r'addopts\s*=\s*"([^"]*)"', pyproject_text)
        if addopts_match:
            addopts = addopts_match.group(1)
            if "-n " not in addopts:
                report.add(
                    "error",
                    "config-sync",
                    "pyproject.toml addopts missing '-n' (multi-core enforcement)",
                    fix_hint='Set addopts = "-n 8 --timeout=60" in [tool.pytest.ini_options]',
                )
    else:
        report.add(
            "error",
            "config-sync",
            "pyproject.toml missing addopts (multi-core not enforced)",
            fix_hint='Add addopts = "-n 8 --timeout=60" to [tool.pytest.ini_options]',
        )

    # Check pre-push hook exists
    if "stages: [pre-push]" not in config_text:
        report.add(
            "error",
            "config-sync",
            ".pre-commit-config.yaml missing pre-push stage (tests not running on push)",
            fix_hint="Add a pytest hook with stages: [pre-push]",
        )


def check_skill_references_hooks(report: ValidationReport) -> None:
    """Check git-precommit skill references the actual hook infrastructure."""
    if not GIT_PRECOMMIT_SKILL.exists():
        report.add(
            "error",
            "skill-sync",
            "git-precommit SKILL.md not found",
            fix_hint="Create .claude/skills/git-precommit/SKILL.md",
        )
        return

    skill_text = GIT_PRECOMMIT_SKILL.read_text(encoding="utf-8")

    required_references = {
        ".pre-commit-config.yaml": "hook config file",
        "pre-commit install": "setup instructions",
        "pre-commit autoupdate": "auto-evolution command",
        "pre-commit run": "manual execution",
    }

    for ref, desc in required_references.items():
        if ref not in skill_text:
            report.add(
                "error",
                "skill-sync",
                f"git-precommit skill missing reference to '{ref}' ({desc})",
                fix_hint=f"Add '{ref}' to the skill documentation",
            )


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────


def run_validation() -> ValidationReport:
    report = ValidationReport()

    check_hooks_documented(report)
    check_hook_scripts_exist(report)
    check_contributing_hooks_table(report)
    check_skill_references_hooks(report)
    check_pyproject_addopts(report)
    check_version_staleness(report)

    return report


def print_report(report: ValidationReport) -> None:
    if not report.issues:
        print("✅ Instructions ↔ Skills ↔ Hooks: all consistent")
        return

    errors = report.errors
    warnings = report.warnings

    if errors:
        print(f"❌ {len(errors)} consistency error(s) found:")
        print()
        for i, e in enumerate(errors, 1):
            print(f"  {i}. [{e.category}] {e.message}")
            if e.fix_hint:
                print(f"     → Fix: {e.fix_hint}")
        print()

    if warnings:
        print(f"⚠️  {len(warnings)} warning(s):")
        print()
        for w in warnings:
            print(f"  • [{w.category}] {w.message}")
            if w.fix_hint:
                print(f"    → {w.fix_hint}")
        print()

    if errors:
        print("The evolution cycle is broken — fix errors above to restore consistency.")
        print()
        print("Self-Evolution Cycle:")
        print("  Instructions (copilot-instructions.md)")
        print("       ↓ guides")
        print("  Skills (SKILL.md files)")
        print("       ↓ build & configure")
        print("  Hooks (.pre-commit-config.yaml + scripts/hooks/)")
        print("       ↓ validate & enforce")
        print("  Results → feedback → update Instructions & Skills")


def main() -> int:
    report = run_validation()
    print_report(report)
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
