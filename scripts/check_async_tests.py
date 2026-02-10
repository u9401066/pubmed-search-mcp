#!/usr/bin/env python3
"""
Detect async/sync mismatches in test files.

Finds tests that call async methods without await, or use sync Mock
where AsyncMock is needed.

Usage:
    uv run python scripts/check_async_tests.py          # Check all tests
    uv run python scripts/check_async_tests.py --fix    # Auto-fix simple cases
    uv run python scripts/check_async_tests.py --verbose  # Show details

Exit codes:
    0 - No issues found
    1 - Issues detected (or --fix applied changes)
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────
# Configuration: known async methods that must be awaited
# ─────────────────────────────────────────────────────────────────────

# method_name → class_or_module (for reporting)
KNOWN_ASYNC_METHODS: dict[str, str] = {
    # PubMedClient
    "search": "PubMedClient/LiteratureSearcher",
    "search_raw": "PubMedClient",
    "fetch_by_pmid": "PubMedClient",
    "fetch_by_pmids": "PubMedClient",
    "fetch_by_pmids_raw": "PubMedClient",
    "fetch_details": "PubMedClient/LiteratureSearcher",
    "find_related": "PubMedClient",
    "find_citing": "PubMedClient",
    "download_pdf": "PubMedClient",
    "get_pmc_url": "PubMedClient",
    # LiteratureSearcher
    "find_related_articles": "LiteratureSearcher",
    "find_citing_articles": "LiteratureSearcher",
    "get_citation_metrics": "LiteratureSearcher",
    # ClinicalTrialsClient
    "get_study": "ClinicalTrialsClient",
    # BaseAPIClient / source clients
    "_make_request": "BaseAPIClient",
    # MCP tool functions (async)
    "_format_unified_results": "unified.py",
}

# Patterns that are definitely NOT async calls (avoid false positives)
SAFE_PATTERNS = {
    "mock_searcher.search",
    "Mock().search",
    "MagicMock().search",
    "mock.search",
}


@dataclass
class Issue:
    """A detected async/sync mismatch."""

    file: str
    line: int
    test_name: str
    issue_type: str  # "missing_await", "sync_mock_for_async", "sync_test_async_call"
    detail: str
    fixable: bool = False


@dataclass
class FileReport:
    """Report for one test file."""

    path: str
    issues: list[Issue] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────
# AST-based detection
# ─────────────────────────────────────────────────────────────────────


class AsyncMismatchDetector(ast.NodeVisitor):
    """AST visitor that detects async/sync mismatches in test functions."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.issues: list[Issue] = []
        self._current_func: str | None = None
        self._current_func_is_async: bool = False
        self._current_class: str | None = None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        old_class = self._current_class
        self._current_class = node.name
        self.generic_visit(node)
        self._current_class = old_class

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name.startswith("test_"):
            self._check_sync_test_for_async_calls(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node.name.startswith("test_"):
            old_func = self._current_func
            old_is_async = self._current_func_is_async
            self._current_func = node.name
            self._current_func_is_async = True
            self._check_async_test_for_missing_await(node)
            self._current_func = old_func
            self._current_func_is_async = old_is_async

    def _get_test_name(self, func_name: str) -> str:
        if self._current_class:
            return f"{self._current_class}::{func_name}"
        return func_name

    def _check_sync_test_for_async_calls(self, node: ast.FunctionDef) -> None:
        """Check if a sync test function calls known async methods."""
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                method_name = self._get_call_method_name(child)
                if method_name and method_name in KNOWN_ASYNC_METHODS:
                    self.issues.append(
                        Issue(
                            file=self.filepath,
                            line=child.lineno,
                            test_name=self._get_test_name(node.name),
                            issue_type="sync_test_async_call",
                            detail=f"Sync test calls async method `{method_name}()` without await "
                            f"(from {KNOWN_ASYNC_METHODS[method_name]})",
                            fixable=False,
                        )
                    )

    def _check_async_test_for_missing_await(self, node: ast.AsyncFunctionDef) -> None:
        """Check if an async test function calls known async methods without await."""
        # Collect all awaited call nodes
        awaited_calls: set[int] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Await) and isinstance(child.value, ast.Call):
                awaited_calls.add(id(child.value))

        # Check all calls
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and id(child) not in awaited_calls:
                method_name = self._get_call_method_name(child)
                if method_name and method_name in KNOWN_ASYNC_METHODS:
                    # Check if it's inside a benchmark() call (special case)
                    if not self._is_inside_benchmark(node, child):
                        self.issues.append(
                            Issue(
                                file=self.filepath,
                                line=child.lineno,
                                test_name=self._get_test_name(node.name),
                                issue_type="missing_await",
                                detail=f"Async method `{method_name}()` called without `await` "
                                f"(from {KNOWN_ASYNC_METHODS[method_name]})",
                                fixable=True,
                            )
                        )

    def _get_call_method_name(self, node: ast.Call) -> str | None:
        """Extract method name from a Call node, only for attribute calls (obj.method)."""
        if isinstance(node.func, ast.Attribute):
            method = node.func.attr
            # For generic method names like 'search', require a client-like receiver
            if method in ("search",):
                receiver = self._get_receiver_name(node.func.value)
                if receiver and not self._is_client_like(receiver):
                    return None
            return method
        if isinstance(node.func, ast.Name):
            # Only match standalone function names that are clearly async tools
            if node.func.id in (
                "_format_unified_results",
                "enhance_query",
            ):
                return node.func.id
        return None

    def _get_receiver_name(self, node: ast.expr) -> str | None:
        """Get the name of the receiver object (e.g., 'client' from 'client.search()')."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def _is_client_like(self, name: str) -> bool:
        """Check if an identifier looks like a client/searcher object."""
        lower = name.lower()
        # Exclude known non-client objects
        exclude_patterns = ("pattern", "_re", "regex", "mock_response", "soup")
        if any(p in lower for p in exclude_patterns):
            return False
        client_patterns = ("client", "searcher", "_searcher", "_client")
        return any(p in lower for p in client_patterns) or lower == "c"

    def _is_inside_benchmark(
        self, func_node: ast.AsyncFunctionDef, call_node: ast.Call
    ) -> bool:
        """Check if a call is inside a benchmark() invocation (which doesn't support async)."""
        for child in ast.walk(func_node):
            if isinstance(child, ast.Call):
                func = child.func
                if isinstance(func, ast.Name) and func.id == "benchmark":
                    # Check if our call is one of the args
                    for arg in child.args:
                        if isinstance(
                            arg, ast.Attribute
                        ) and arg.attr == self._get_call_method_name(call_node):
                            return True
                if isinstance(func, ast.Attribute) and func.attr == "pedantic":
                    return True
        return False


# ─────────────────────────────────────────────────────────────────────
# Regex-based detection (supplements AST)
# ─────────────────────────────────────────────────────────────────────


def check_mock_types(filepath: str, source: str) -> list[Issue]:
    """
    Check for sync Mock/MagicMock used where AsyncMock is needed.

    Pattern: mock_searcher = Mock() followed by mock_searcher.search.return_value = ...
    where .search() is async → should be AsyncMock.
    """
    issues: list[Issue] = []

    # Find Mock() assignments that are used for async methods
    # This is a heuristic check
    lines = source.split("\n")
    for i, line in enumerate(lines, 1):
        # Check: mock_searcher = Mock() or MagicMock()
        m = re.match(r"\s+(mock_\w+)\s*=\s*(Mock|MagicMock)\(\)", line)
        if m:
            var_name = m.group(1)
            mock_type = m.group(2)
            # Look ahead for async method usage
            for j in range(i, min(i + 30, len(lines))):
                ahead = lines[j]
                for method in KNOWN_ASYNC_METHODS:
                    if f"{var_name}.{method}" in ahead and "AsyncMock" not in ahead:
                        # Check if the method's return_value is set (it's being mocked)
                        if (
                            "return_value" in ahead
                            or f"await {var_name}.{method}" in ahead
                        ):
                            issues.append(
                                Issue(
                                    file=filepath,
                                    line=i,
                                    test_name="(class-level or function-level)",
                                    issue_type="sync_mock_for_async",
                                    detail=f"`{var_name} = {mock_type}()` but `{var_name}.{method}()` is async → "
                                    f"use `AsyncMock()` or `{var_name}.{method} = AsyncMock(return_value=...)`",
                                    fixable=False,
                                )
                            )
                            break
                    if f"{var_name}.{method}" in ahead:
                        break

    return issues


# ─────────────────────────────────────────────────────────────────────
# Auto-fix
# ─────────────────────────────────────────────────────────────────────


def auto_fix_missing_await(filepath: str, issues: list[Issue]) -> int:
    """
    Auto-fix simple missing-await issues.

    Only fixes cases where a known async method call is on its own line
    or in a simple assignment like `result = client.method(...)`.

    Returns number of fixes applied.
    """
    if not issues:
        return 0

    fixable = [i for i in issues if i.fixable and i.issue_type == "missing_await"]
    if not fixable:
        return 0

    lines = Path(filepath).read_text(encoding="utf-8").split("\n")
    fix_count = 0

    for issue in fixable:
        idx = issue.line - 1
        if idx >= len(lines):
            continue

        line = lines[idx]
        # Extract method name from detail
        m = re.search(r"`(\w+)\(\)`", issue.detail)
        if not m:
            continue
        method = m.group(1)

        # Pattern: result = obj.method(...) → result = await obj.method(...)
        pattern = rf"(\s*\w+\s*=\s*\w+\.{method}\()"
        if re.search(pattern, line) and "await " not in line:
            lines[idx] = re.sub(
                rf"(\s*)(\w+\s*=\s*)(\w+\.{method}\()",
                r"\1\2await \3",
                line,
            )
            fix_count += 1
            continue

        # Pattern: standalone call: obj.method(...) → await obj.method(...)
        pattern2 = rf"(\s+)(\w+\.{method}\()"
        if (
            re.search(pattern2, line)
            and "await " not in line
            and "=" not in line.split(f".{method}(")[0]
        ):
            lines[idx] = re.sub(
                rf"(\s+)(\w+\.{method}\()",
                r"\1await \2",
                line,
            )
            fix_count += 1
            continue

        # Pattern: bare function call: method(...) → await method(...)
        pattern3 = rf"(\s+)({method}\()"
        if (
            re.search(pattern3, line)
            and "await " not in line
            and "=" not in line.split(f"{method}(")[0]
        ):
            lines[idx] = re.sub(
                rf"(\s+)({method}\()",
                r"\1await \2",
                line,
            )
            fix_count += 1
            continue

    if fix_count > 0:
        Path(filepath).write_text("\n".join(lines), encoding="utf-8")

    return fix_count


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────


def scan_file(filepath: str) -> FileReport:
    """Scan a single test file for async/sync mismatches."""
    report = FileReport(path=filepath)
    source = Path(filepath).read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        return report

    # AST-based detection
    detector = AsyncMismatchDetector(filepath)
    detector.visit(tree)
    report.issues.extend(detector.issues)

    # Regex-based mock type detection
    report.issues.extend(check_mock_types(filepath, source))

    return report


def scan_directory(test_dir: str) -> list[FileReport]:
    """Scan all test files in a directory."""
    reports = []
    for path in sorted(Path(test_dir).rglob("test_*.py")):
        report = scan_file(str(path))
        if report.issues:
            reports.append(report)
    return reports


def print_report(reports: list[FileReport], verbose: bool = False) -> int:
    """Print report and return total issue count."""
    total = 0
    for report in reports:
        total += len(report.issues)

    if total == 0:
        print("✅ No async/sync mismatches detected!")
        return 0

    print(f"\n⚠️  Found {total} async/sync mismatch(es) in {len(reports)} file(s):\n")

    for report in reports:
        try:
            rel_path = str(Path(report.path).relative_to(Path.cwd()))
        except ValueError:
            rel_path = report.path
        print(f"📄 {rel_path} ({len(report.issues)} issue(s))")

        for issue in report.issues:
            icon = {
                "missing_await": "🔴",
                "sync_test_async_call": "🟡",
                "sync_mock_for_async": "🟠",
            }.get(issue.issue_type, "⚪")

            fix_tag = " [auto-fixable]" if issue.fixable else ""
            print(f"  {icon} L{issue.line}: {issue.test_name}")
            if verbose:
                print(f"     ↳ {issue.detail}{fix_tag}")
        print()

    # Summary by type
    by_type: dict[str, int] = {}
    for report in reports:
        for issue in report.issues:
            by_type[issue.issue_type] = by_type.get(issue.issue_type, 0) + 1

    print("Summary:")
    type_labels = {
        "missing_await": "Missing `await` on async call",
        "sync_test_async_call": "Sync test calling async method",
        "sync_mock_for_async": "Sync Mock used for async method",
    }
    for t, count in sorted(by_type.items()):
        print(f"  {type_labels.get(t, t)}: {count}")

    fixable = sum(1 for r in reports for i in r.issues if i.fixable)
    if fixable:
        print(f"\n💡 {fixable} issue(s) can be auto-fixed with --fix")

    return total


def main():
    # Ensure UTF-8 output on Windows
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Check for async/sync mismatches in tests"
    )
    parser.add_argument(
        "--fix", action="store_true", help="Auto-fix simple missing-await issues"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed issue descriptions"
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="tests",
        help="Test directory or file (default: tests)",
    )
    args = parser.parse_args()

    target = Path(args.path)
    if not target.exists():
        print(f"Error: {target} not found")
        sys.exit(2)

    if target.is_file():
        reports = [scan_file(str(target))]
        reports = [r for r in reports if r.issues]
    else:
        reports = scan_directory(str(target))

    total = print_report(reports, verbose=args.verbose)

    if args.fix and total > 0:
        print("\n🔧 Applying auto-fixes...")
        total_fixed = 0
        for report in reports:
            fixed = auto_fix_missing_await(report.path, report.issues)
            if fixed:
                try:
                    rel = str(Path(report.path).relative_to(Path.cwd()))
                except ValueError:
                    rel = report.path
                print(f"  ✅ {rel}: {fixed} fix(es) applied")
                total_fixed += fixed
        print(f"\n  Total: {total_fixed} fix(es) applied")
        if total_fixed < total:
            print(
                f"  ⚠️  {total - total_fixed} issue(s) need manual fix (Mock→AsyncMock, benchmark refactor, etc.)"
            )
        sys.exit(1 if total_fixed > 0 else 0)

    sys.exit(1 if total > 0 else 0)


if __name__ == "__main__":
    main()
