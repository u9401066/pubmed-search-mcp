"""Run the shared local pre-push gate or the smaller cloud smoke gate.

No success cache: every invocation checks the current working tree. Live API
probes are deliberately excluded; they have a separate, explicit opt-in.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK_PATHS = ("src/", "tests/", "scripts/", "run_server.py", "run_copilot.py")
SMOKE_TESTS = (
    "tests/test_documentation_integrity.py",
    "tests/test_docs_site_sync.py",
    "tests/test_github_wiki_build.py",
    "tests/test_public_api_facade.py",
    "tests/test_source_contracts.py",
    "tests/test_provider_failure_contracts.py",
    "tests/test_ncbi_provider_schema_contracts.py",
    "tests/test_search_query_provenance.py",
    "tests/test_search_run_journal.py",
    "tests/test_tool_schema_hardening.py",
    "tests/test_install_research_skills.py",
    "tests/test_check_repo.py",
    "tests/test_release_transport_smoke.py",
    "tests/test_all_tools_mcp_acceptance.py",
)


def commands(profile: str) -> list[tuple[str, ...]]:
    """Keep local and CI commands in one place, with a single pytest process."""
    checks = [
        ("ruff", "check", *CHECK_PATHS),
        ("ruff", "format", "--check", *CHECK_PATHS),
        ("python", "scripts/check_async_tests.py"),
    ]
    if profile == "full":
        checks.append(("python", "scripts/perf/symbol_inventory.py"))
        checks.append(("mypy", "src/", "tests/"))
    checks.append(("pytest", "-q", *(SMOKE_TESTS if profile == "smoke" else ("tests/",)), "-m", "not integration"))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=("full", "smoke"), nargs="?", default="full")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing them")
    args = parser.parse_args()
    for command in commands(args.profile):
        invocation = (sys.executable, *command[1:]) if command[0] == "python" else (sys.executable, "-m", *command)
        print(f"Checking: {shlex.join(command)}", flush=True)
        if not args.dry_run:
            result = subprocess.run(invocation, cwd=ROOT, check=False)
            if result.returncode:
                return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
