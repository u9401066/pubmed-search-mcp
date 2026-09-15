"""Inventory every Git-visible Python definition without importing project code.

The generated inventory is local/ignored; only review decisions are committed.
Parsing a definition is never counted as reviewing its behavior. File changes
invalidate recorded reviews, and an optional completion gate fails closed.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CODE_EXTENSIONS = {".py", ".pyi", ".js", ".mjs", ".ts", ".tsx", ".sh", ".ps1"}


def visible_files(root: Path) -> list[Path]:
    """Include current tracked/untracked files, excluding worktree deletions."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    deleted = subprocess.run(["git", "ls-files", "--deleted", "-z"], cwd=root, check=True, capture_output=True)
    paths = set(result.stdout.decode("utf-8").split("\0")) - set(deleted.stdout.decode("utf-8").split("\0"))
    return [root / path for path in sorted(paths) if path]


class DefinitionVisitor(ast.NodeVisitor):
    """Keep lexical owners; methods, nested functions, and duplicate names differ."""

    def __init__(self, path: str, digest: str) -> None:
        self.path = path
        self.digest = digest
        self.owners: list[tuple[str, str]] = []
        self.occurrences: Counter[str] = Counter()
        self.symbols: list[dict[str, Any]] = []

    def _definition(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        if kind == "function" and self.owners:
            kind = "method" if self.owners[-1][1] == "class" else "nested_function"
        qualname = ".".join([*(name for name, _ in self.owners), node.name])
        self.occurrences[qualname] += 1
        symbol_id = f"{self.path}::{qualname}#{self.occurrences[qualname]}"
        self.symbols.append(
            {
                "id": symbol_id,
                "path": self.path,
                "qualname": qualname,
                "kind": kind,
                "async": isinstance(node, ast.AsyncFunctionDef),
                "line": min([node.lineno, *(d.lineno for d in node.decorator_list)]),
                "end_line": node.end_lineno,
                "file_sha256": self.digest,
                "review_status": "pending",
            }
        )
        self.owners.append((node.name, kind))
        self.generic_visit(node)
        self.owners.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._definition(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._definition(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._definition(node)


def build_inventory(root: Path, reviews: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a reproducible manifest, definition inventory, and review coverage."""
    reviews = reviews or {}
    files: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    totals: dict[str, Counter[str]] = defaultdict(Counter)
    for path in visible_files(root):
        if path.suffix not in CODE_EXTENSIONS:
            continue
        relative = path.relative_to(root).as_posix()
        scope = path.relative_to(root).parts[0] if len(path.relative_to(root).parts) > 1 else "root"
        record: dict[str, Any] = {"path": relative, "scope": scope, "status": "not_python"}
        files.append(record)
        if path.is_symlink() or not path.is_file():
            record["status"] = "unreadable"
            continue
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        record["sha256"] = digest
        if path.suffix not in {".py", ".pyi"}:
            continue
        totals[scope]["python_files"] += 1
        try:
            tree = ast.parse(raw, filename=relative)
        except (SyntaxError, ValueError) as exc:
            record.update(status="parse_error", error=str(exc))
            continue
        visitor = DefinitionVisitor(relative, digest)
        visitor.visit(tree)
        record.update(status="parsed", definitions=len(visitor.symbols))
        for symbol in visitor.symbols:
            totals[scope]["classes" if symbol["kind"] == "class" else "functions"] += 1
            if symbol["kind"] != "class":
                category = {"function": "module_functions", "method": "methods", "nested_function": "nested_functions"}[
                    symbol["kind"]
                ]
                totals[scope][category] += 1
            totals[scope]["async_functions"] += int(symbol["async"])
            review = reviews.get(symbol["id"])
            if review:
                valid = (
                    review.get("file_sha256") == digest
                    and review.get("reviewed_by")
                    and review.get("notes")
                    and review.get("evidence")
                )
                symbol["review_status"] = (
                    "reviewed"
                    if valid and review.get("decision") in {"retain", "changed"}
                    else "follow_up"
                    if valid
                    else "stale_review"
                )
            symbols.append(symbol)
    status_counts = Counter(symbol["review_status"] for symbol in symbols)
    manifest = [(file["path"], file.get("sha256"), file["status"]) for file in files]
    known_ids = {symbol["id"] for symbol in symbols}
    return {
        "schema_version": 1,
        "scope": "Git-visible code files; Python def/async def/class only; lambdas and generated methods excluded",
        "snapshot_sha256": hashlib.sha256(json.dumps(manifest, separators=(",", ":")).encode()).hexdigest(),
        "counts": {scope: dict(counts) for scope, counts in sorted(totals.items())},
        "file_status_counts": dict(Counter(file["status"] for file in files)),
        "review_status_counts": dict(status_counts),
        "orphan_reviews": sorted(set(reviews) - known_ids),
        "files": files,
        "symbols": symbols,
    }


def review_complete(inventory: dict[str, Any], prefix: str) -> bool:
    """Require a nonempty Python scope with no parse gaps or pending reviews."""
    files = [file for file in inventory["files"] if file["path"].startswith(prefix)]
    symbols = [symbol for symbol in inventory["symbols"] if symbol["path"].startswith(prefix)]
    return (
        bool(files and symbols)
        and all(file["status"] == "parsed" for file in files)
        and all(symbol["review_status"] == "reviewed" for symbol in symbols)
        and not any(symbol.startswith(prefix) for symbol in inventory["orphan_reviews"])
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "scripts/_tmp/review/symbols.json")
    parser.add_argument("--ledger", type=Path, default=ROOT / "docs/reports/code_review_ledger.json")
    parser.add_argument("--require-reviewed", metavar="PATH_PREFIX", help="Fail unless the selected scope is reviewed")
    args = parser.parse_args()
    ledger = json.loads(args.ledger.read_text(encoding="utf-8")) if args.ledger.exists() else {"reviews": {}}
    inventory = build_inventory(ROOT, ledger["reviews"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in inventory.items() if key not in {"files", "symbols"}}, indent=2))
    print(f"Inventory: {args.output}")
    parse_gaps = any(file["status"] in {"parse_error", "unreadable"} for file in inventory["files"])
    return int(
        parse_gaps or (args.require_reviewed is not None and not review_complete(inventory, args.require_reviewed))
    )


if __name__ == "__main__":
    raise SystemExit(main())
