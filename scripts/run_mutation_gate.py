from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class MutationCase:
    name: str
    file_path: Path
    original: str
    mutated: str
    test_command: tuple[str, ...]


def _pytest_command(*test_paths: str) -> tuple[str, ...]:
    return ("uv", "run", "pytest", *test_paths, "-q", "-n", "0", "--no-cov", "--tb=no", "--maxfail=1")


SOURCE_CONTRACTS_TEST_COMMAND = _pytest_command("tests/test_source_contracts.py")
CACHE_SUBSTRATE_TEST_COMMAND = _pytest_command("tests/test_cache_substrate.py")


MUTATION_CASES: tuple[MutationCase, ...] = (
    MutationCase(
        name="source_contracts status classification",
        file_path=REPO_ROOT / "src/pubmed_search/shared/source_contracts.py",
        original='    status: SourceAdapterStatus = "ok" if items else "empty"\n',
        mutated='    status: SourceAdapterStatus = "empty" if items else "ok"\n',
        test_command=SOURCE_CONTRACTS_TEST_COMMAND,
    ),
    MutationCase(
        name="source_contracts tuple metadata branch",
        file_path=REPO_ROOT / "src/pubmed_search/shared/source_contracts.py",
        original=(
            '            if isinstance(second, dict):\n'
            '                metadata = dict(second)\n'
            '            else:\n'
            '                total_count = int(second)\n'
        ),
        mutated=(
            '            if not isinstance(second, dict):\n'
            '                metadata = dict(second)\n'
            '            else:\n'
            '                total_count = int(second)\n'
        ),
        test_command=SOURCE_CONTRACTS_TEST_COMMAND,
    ),
    MutationCase(
        name="source_contracts resolved total fallback",
        file_path=REPO_ROOT / "src/pubmed_search/shared/source_contracts.py",
        original='    resolved_total = total_count if total_count is not None else len(items)\n',
        mutated='    resolved_total = len(items)\n',
        test_command=SOURCE_CONTRACTS_TEST_COMMAND,
    ),
    MutationCase(
        name="source_contracts retryable operation retry flag",
        file_path=REPO_ROOT / "src/pubmed_search/shared/source_contracts.py",
        original=(
            '    if isinstance(error, RetryableOperationError):\n'
            '        return SourceAdapterError(\n'
            '            source=source,\n'
            '            operation=operation,\n'
            '            message=str(error),\n'
            '            kind="retryable",\n'
            '            retryable=True,\n'
            '            status_code=error.status_code,\n'
            '        )\n'
        ),
        mutated=(
            '    if isinstance(error, RetryableOperationError):\n'
            '        return SourceAdapterError(\n'
            '            source=source,\n'
            '            operation=operation,\n'
            '            message=str(error),\n'
            '            kind="retryable",\n'
            '            retryable=False,\n'
            '            status_code=error.status_code,\n'
            '        )\n'
        ),
        test_command=SOURCE_CONTRACTS_TEST_COMMAND,
    ),
    MutationCase(
        name="source_contracts http retry classification",
        file_path=REPO_ROOT / "src/pubmed_search/shared/source_contracts.py",
        original='            retryable=status_code in {408, 425, 429, 500, 502, 503, 504},\n',
        mutated='            retryable=False,\n',
        test_command=SOURCE_CONTRACTS_TEST_COMMAND,
    ),
    MutationCase(
        name="source_contracts timeout kind",
        file_path=REPO_ROOT / "src/pubmed_search/shared/source_contracts.py",
        original=(
            '    if isinstance(error, httpx.TimeoutException):\n'
            '        return SourceAdapterError(\n'
            '            source=source,\n'
            '            operation=operation,\n'
            '            message=str(error) or "Request timed out",\n'
            '            kind="timeout",\n'
            '            retryable=True,\n'
            '        )\n'
        ),
        mutated=(
            '    if isinstance(error, httpx.TimeoutException):\n'
            '        return SourceAdapterError(\n'
            '            source=source,\n'
            '            operation=operation,\n'
            '            message=str(error) or "Request timed out",\n'
            '            kind="transport",\n'
            '            retryable=True,\n'
            '        )\n'
        ),
        test_command=SOURCE_CONTRACTS_TEST_COMMAND,
    ),
    MutationCase(
        name="source_contracts request error kind",
        file_path=REPO_ROOT / "src/pubmed_search/shared/source_contracts.py",
        original=(
            '    if isinstance(error, httpx.RequestError):\n'
            '        return SourceAdapterError(\n'
            '            source=source,\n'
            '            operation=operation,\n'
            '            message=str(error),\n'
            '            kind="transport",\n'
            '            retryable=True,\n'
            '        )\n'
        ),
        mutated=(
            '    if isinstance(error, httpx.RequestError):\n'
            '        return SourceAdapterError(\n'
            '            source=source,\n'
            '            operation=operation,\n'
            '            message=str(error),\n'
            '            kind="unexpected",\n'
            '            retryable=True,\n'
            '        )\n'
        ),
        test_command=SOURCE_CONTRACTS_TEST_COMMAND,
    ),
    MutationCase(
        name="cache_substrate hit statistics",
        file_path=REPO_ROOT / "src/pubmed_search/shared/cache_substrate.py",
        original='        self._stats.hits += 1\n',
        mutated='        self._stats.hits += 0\n',
        test_command=CACHE_SUBSTRATE_TEST_COMMAND,
    ),
    MutationCase(
        name="cache_substrate persistence payload",
        file_path=REPO_ROOT / "src/pubmed_search/shared/cache_substrate.py",
        original='        payload = {key: entry.to_dict() for key, entry in self._entries.items()}\n',
        mutated='        payload = {}\n',
        test_command=CACHE_SUBSTRATE_TEST_COMMAND,
    ),
    MutationCase(
        name="cache_substrate warmup statistics",
        file_path=REPO_ROOT / "src/pubmed_search/shared/cache_substrate.py",
        original='            self._stats.warmups += warmed\n',
        mutated='            self._stats.warmups += 0\n',
        test_command=CACHE_SUBSTRATE_TEST_COMMAND,
    ),
    MutationCase(
        name="cache_substrate invalidation statistics",
        file_path=REPO_ROOT / "src/pubmed_search/shared/cache_substrate.py",
        original='            self._stats.invalidations += 1\n',
        mutated='            self._stats.invalidations += 0\n',
        test_command=CACHE_SUBSTRATE_TEST_COMMAND,
    ),
)


def _read_text(path: Path) -> str:
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def _write_text(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def _render_for_file(snippet: str, content: str) -> str:
    newline = "\r\n" if "\r\n" in content else "\n"
    return snippet.replace("\n", newline)


def _run_command(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _print_output(prefix: str, result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout:
        print(f"{prefix} stdout:\n{result.stdout.rstrip()}\n")
    if result.stderr:
        print(f"{prefix} stderr:\n{result.stderr.rstrip()}\n")


def _run_baselines() -> int:
    seen_commands: set[tuple[str, ...]] = set()

    for case in MUTATION_CASES:
        if case.test_command in seen_commands:
            continue
        seen_commands.add(case.test_command)

        print(f"[baseline] {' '.join(case.test_command)}")
        result = _run_command(case.test_command)
        if result.returncode != 0:
            _print_output("baseline", result)
            print("[error] Baseline tests failed. Fix the target test suite before running the mutation gate.")
            return 1

    return 0


def _apply_case(case: MutationCase) -> tuple[str, str | None]:
    original_content = _read_text(case.file_path)
    original = _render_for_file(case.original, original_content)
    mutated = _render_for_file(case.mutated, original_content)
    match_count = original_content.count(original)

    if match_count != 1:
        return "stale", f"expected 1 exact match, found {match_count}"

    mutated_content = original_content.replace(original, mutated, 1)

    try:
        _write_text(case.file_path, mutated_content)
        result = _run_command(case.test_command)
    finally:
        _write_text(case.file_path, original_content)

    if result.returncode == 0:
        _print_output("survived", result)
        return "survived", None

    return "killed", None


def main() -> int:
    print("Running deterministic mutation hard gate for core shared modules.")
    print()

    baseline_exit_code = _run_baselines()
    if baseline_exit_code != 0:
        return baseline_exit_code

    killed = 0
    survived: list[str] = []
    stale: list[str] = []

    for case in MUTATION_CASES:
        print(f"[mutate] {case.name}")
        status, detail = _apply_case(case)
        if status == "killed":
            killed += 1
            print(f"[killed] {case.name}")
        elif status == "survived":
            survived.append(case.name)
            print(f"[survived] {case.name}")
        else:
            stale.append(f"{case.name}: {detail}")
            print(f"[stale] {case.name}: {detail}")
        print()

    print("Mutation gate summary")
    print(f"  Cases: {len(MUTATION_CASES)}")
    print(f"  Killed: {killed}")
    print(f"  Survived: {len(survived)}")
    print(f"  Stale: {len(stale)}")

    if survived:
        print()
        print("Surviving mutations:")
        for name in survived:
            print(f"  - {name}")

    if stale:
        print()
        print("Stale mutation definitions:")
        for detail in stale:
            print(f"  - {detail}")

    return 1 if survived or stale else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FileNotFoundError as error:
        print(f"[error] Missing executable or file: {error}", file=sys.stderr)
        raise SystemExit(1) from error
