"""Run complete local pretests, portable runtime smoke, or opt-in container smoke.

Every invocation checks current files. Reports are evidence, never a cache or
permission to skip validation. Literature-provider network calls stay opt-in.
"""

from __future__ import annotations

import argparse
import json
import platform
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CHECK_PATHS = ("src/", "tests/", "scripts/", "run_server.py", "run_copilot.py")
SMOKE_TESTS = (
    "tests/test_release_transport_smoke.py",
    "tests/test_all_tools_mcp_acceptance.py",
    "tests/test_e2e_workflows.py",
)


def commands(profile: str) -> list[tuple[str, ...]]:
    """Own the local/CI split in one place; each profile uses one pytest process."""
    if profile == "container":
        return [("pytest", "-q", "tests/test_container_smoke.py")]
    if profile == "smoke":
        return [("pytest", "-q", *SMOKE_TESTS, "-m", "not integration")]
    if profile not in {"full", "pretest"}:
        raise ValueError(f"Unknown validation profile: {profile}")
    return [
        ("ruff", "check", *CHECK_PATHS),
        ("ruff", "format", "--check", *CHECK_PATHS),
        ("python", "scripts/check_async_tests.py"),
        ("python", "scripts/check_repository_layout.py"),
        ("python", "scripts/build_publication.py", "--prepare-only", "--output", "build/publication-preflight"),
        ("python", "scripts/perf/symbol_inventory.py"),
        ("mypy", "src/", "tests/"),
        ("pytest", "-q", "tests/", "-m", "not integration and not container"),
    ]


def _git_output(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=("full", "pretest", "smoke", "container"), nargs="?", default="full")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing or writing a report")
    parser.add_argument(
        "--release-dist", type=Path, help="Test the supplied wheel/sdist pair instead of building again"
    )
    parser.add_argument("--container-image", help="Locally built image required by the container profile")
    parser.add_argument("--report", type=Path, help="JSON evidence path; defaults to build/validation/<profile>.json")
    args = parser.parse_args()
    if args.profile == "container" and not args.container_image:
        parser.error("container profile requires --container-image; it must not succeed by skipping")
    if args.profile != "container" and args.container_image:
        parser.error("--container-image requires the container profile")
    if args.profile == "container" and args.release_dist:
        parser.error("--release-dist does not apply to the container profile")
    checks = commands(args.profile)
    pytest_args = ("--release-dist", str(args.release_dist.resolve())) if args.release_dist else ()
    if args.container_image:
        pytest_args += ("--container-image", args.container_image)
    report_path = args.report or ROOT / "build" / "validation" / f"{args.profile}.json"
    report: dict[str, Any] = {
        "schema_version": 1,
        "profile": args.profile,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "commit": _git_output("rev-parse", "HEAD"),
        "dirty": bool(_git_output("status", "--porcelain")),
        "steps": [],
    }

    def save_report() -> None:
        if not args.dry_run:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    save_report()  # Invalidate an earlier success before starting any checks.
    for planned in checks:
        command = (*planned, *pytest_args) if planned[0] == "pytest" else planned
        invocation = (sys.executable, *command[1:]) if command[0] == "python" else (sys.executable, "-m", *command)
        print(f"Checking: {shlex.join(command)}", flush=True)
        if args.dry_run:
            continue
        started = time.monotonic()
        try:
            result = subprocess.run(invocation, cwd=ROOT, check=False)
            returncode = result.returncode
        except (OSError, KeyboardInterrupt) as exc:
            returncode = 130 if isinstance(exc, KeyboardInterrupt) else 1
        report["steps"].append(
            {"command": list(command), "returncode": returncode, "seconds": round(time.monotonic() - started, 3)}
        )
        if returncode:
            report["status"] = "failed"
            save_report()
            print(f"Validation failed; evidence: {report_path}", flush=True)
            return returncode
        save_report()
    if not args.dry_run:
        report["status"] = "passed"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        save_report()
        print(f"Validation passed; evidence: {report_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
