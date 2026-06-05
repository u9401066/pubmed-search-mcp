#!/usr/bin/env python3
"""Audit internal module reachability and heavy top-level imports."""

from __future__ import annotations

import argparse
import ast
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "pubmed_search"
PACKAGE = "pubmed_search"

HEAVY_IMPORTS = {
    "Bio",
    "fastapi",
    "httpx",
    "mcp",
    "playwright",
    "pydantic",
    "pydantic_settings",
    "requests",
    "starlette",
    "toons",
    "trafilatura",
    "yaml",
    "apscheduler",
}

SKIP_DIR_NAMES = {
    ".git",
    ".tox",
    ".uv-cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "data",
    "dist",
    "__pycache__",
    "htmlcov",
}
SKIP_RELATIVE_PREFIXES = {
    "scripts/_tmp",
}
SCAN_ROOTS = ("src", "tests", "scripts")

ROOT_MODULES = {
    "pubmed_search",
    "pubmed_search.__main__",
    "pubmed_search.presentation.mcp_server",
    "pubmed_search.presentation.mcp_server.__main__",
    "pubmed_search.presentation.browser_fetch_broker",
}


@dataclass(frozen=True)
class ImportRecord:
    importer: str
    target: str
    path: str
    lineno: int
    scope: str


@dataclass(frozen=True)
class ModuleAudit:
    module: str
    path: str
    src_importers: list[str]
    test_importers: list[str]
    script_importers: list[str]
    other_importers: list[str]
    status: str


@dataclass(frozen=True)
class HeavyImportAudit:
    module: str
    path: str
    imported: str
    lineno: int


def _is_skipped(path: Path) -> bool:
    rel = path.relative_to(REPO_ROOT).as_posix()
    return any(part in SKIP_DIR_NAMES for part in path.relative_to(REPO_ROOT).parts) or any(
        rel == prefix or rel.startswith(f"{prefix}/") for prefix in SKIP_RELATIVE_PREFIXES
    )


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root_name in SCAN_ROOTS:
        root = REPO_ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if _is_skipped(path):
                continue
            files.append(path)
    return sorted(files)


def _module_from_src_path(path: Path) -> str:
    rel = path.relative_to(REPO_ROOT / "src").with_suffix("")
    parts = rel.parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _module_from_any_path(path: Path) -> str:
    if path.is_relative_to(SRC_ROOT):
        return _module_from_src_path(path)
    rel = path.relative_to(REPO_ROOT).with_suffix("")
    return ".".join(rel.parts)


def _source_modules() -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in sorted(SRC_ROOT.rglob("*.py")):
        modules[_module_from_src_path(path)] = path
    return modules


def _resolve_imported_module(name: str, modules: dict[str, Path]) -> str | None:
    parts = name.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in modules:
            return candidate
        parts.pop()
    return None


def _resolve_from_import(
    node: ast.ImportFrom,
    importer: str,
    modules: dict[str, Path],
    *,
    importer_is_package: bool,
) -> list[str]:
    if node.module is None:
        base_parts = importer.split(".")
        if not importer_is_package:
            base_parts = base_parts[:-1]
        if node.level:
            base_parts = base_parts[: max(len(base_parts) - node.level + 1, 0)]
        base = ".".join(base_parts)
    elif node.level:
        package_parts = importer.split(".")
        if not importer_is_package:
            package_parts = package_parts[:-1]
        package_parts = package_parts[: max(len(package_parts) - node.level + 1, 0)]
        base = ".".join([*package_parts, node.module])
    else:
        base = node.module

    targets: list[str] = []
    if base:
        resolved_base = _resolve_imported_module(base, modules)
        if resolved_base:
            targets.append(resolved_base)

    for alias in node.names:
        if alias.name == "*":
            continue
        candidate = f"{base}.{alias.name}" if base else alias.name
        resolved = _resolve_imported_module(candidate, modules)
        if resolved:
            targets.append(resolved)
    return sorted(set(targets))


def _scope_for_node(parent_stack: list[ast.AST]) -> str:
    for parent in reversed(parent_stack):
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return "function"
        if isinstance(parent, ast.ClassDef):
            return "class"
    if any(isinstance(parent, ast.If) for parent in parent_stack):
        return "conditional"
    return "module"


def _collect_imports(path: Path, modules: dict[str, Path]) -> list[ImportRecord]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []

    importer = _module_from_any_path(path)
    importer_is_package = path.name == "__init__.py"
    records: list[ImportRecord] = []
    stack: list[ast.AST] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Import):
            scope = _scope_for_node(stack)
            for alias in node.names:
                resolved = _resolve_imported_module(alias.name, modules)
                if resolved:
                    records.append(
                        ImportRecord(
                            importer=importer,
                            target=resolved,
                            path=path.relative_to(REPO_ROOT).as_posix(),
                            lineno=node.lineno,
                            scope=scope,
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            scope = _scope_for_node(stack)
            for resolved in _resolve_from_import(
                node,
                importer,
                modules,
                importer_is_package=importer_is_package,
            ):
                records.append(
                    ImportRecord(
                        importer=importer,
                        target=resolved,
                        path=path.relative_to(REPO_ROOT).as_posix(),
                        lineno=node.lineno,
                        scope=scope,
                    )
                )

        stack.append(node)
        for child in ast.iter_child_nodes(node):
            visit(child)
        stack.pop()

    visit(tree)

    for node in tree.body:
        if isinstance(node, ast.Assign):
            target_names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_names = [node.target.id]
            value = node.value
        else:
            continue
        if value is None:
            continue
        if not any("LAZY" in name or "REGISTRAR" in name for name in target_names):
            continue
        for child in ast.walk(value):
            if not isinstance(child, ast.Constant) or not isinstance(child.value, str):
                continue
            if not child.value.startswith(f"{PACKAGE}."):
                continue
            resolved = _resolve_imported_module(child.value, modules)
            if resolved:
                records.append(
                    ImportRecord(
                        importer=importer,
                        target=resolved,
                        path=path.relative_to(REPO_ROOT).as_posix(),
                        lineno=child.lineno,
                        scope="lazy",
                    )
                )

    return records


def _collect_top_level_heavy_imports(path: Path) -> list[tuple[str, int]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []

    findings: list[tuple[str, int]] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in HEAVY_IMPORTS:
                    findings.append((root, node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".", 1)[0]
            if root in HEAVY_IMPORTS:
                findings.append((root, node.lineno))
    return findings


def _classify_importer(importer_path: str) -> str:
    if importer_path.startswith("src/"):
        return "src"
    if importer_path.startswith("tests/"):
        return "tests"
    if importer_path.startswith("scripts/") or importer_path.endswith(".py"):
        return "scripts"
    return "other"


def build_audit() -> dict[str, Any]:
    modules = _source_modules()
    records: list[ImportRecord] = []
    for path in _iter_python_files():
        records.extend(_collect_imports(path, modules))

    incoming: dict[str, dict[str, set[str]]] = {
        module: {"src": set(), "tests": set(), "scripts": set(), "other": set()} for module in modules
    }
    for record in records:
        if record.importer == record.target:
            continue
        category = _classify_importer(record.path)
        incoming[record.target][category].add(record.importer)

    module_audits: list[ModuleAudit] = []
    for module, path in modules.items():
        groups = incoming[module]
        src_importers = sorted(groups["src"])
        test_importers = sorted(groups["tests"])
        script_importers = sorted(groups["scripts"])
        other_importers = sorted(groups["other"])
        if module in ROOT_MODULES or path.name == "__init__.py":
            status = "root_or_package"
        elif not src_importers and not test_importers and not script_importers and not other_importers:
            status = "no_static_importers"
        elif not src_importers and test_importers and not script_importers and not other_importers:
            status = "tests_only"
        elif not src_importers and script_importers and not test_importers and not other_importers:
            status = "scripts_only"
        elif not src_importers:
            status = "non_runtime_importers_only"
        else:
            status = "runtime_referenced"
        module_audits.append(
            ModuleAudit(
                module=module,
                path=path.relative_to(REPO_ROOT).as_posix(),
                src_importers=src_importers[:10],
                test_importers=test_importers[:10],
                script_importers=script_importers[:10],
                other_importers=other_importers[:10],
                status=status,
            )
        )

    heavy: list[HeavyImportAudit] = []
    for module, path in modules.items():
        for imported, lineno in _collect_top_level_heavy_imports(path):
            heavy.append(
                HeavyImportAudit(
                    module=module,
                    path=path.relative_to(REPO_ROOT).as_posix(),
                    imported=imported,
                    lineno=lineno,
                )
            )

    status_counts: dict[str, int] = defaultdict(int)
    for audit in module_audits:
        status_counts[audit.status] += 1

    return {
        "module_count": len(modules),
        "status_counts": dict(sorted(status_counts.items())),
        "modules": [asdict(audit) for audit in sorted(module_audits, key=lambda item: (item.status, item.module))],
        "heavy_top_level_imports": [
            asdict(item) for item in sorted(heavy, key=lambda item: (item.imported, item.path))
        ],
        "import_records": [asdict(item) for item in records],
    }


def _print_text(audit: dict[str, Any]) -> None:
    print(f"Source modules: {audit['module_count']}")
    print("Status counts:")
    for status, count in audit["status_counts"].items():
        print(f"  {status}: {count}")

    print("\nPotential orphan/test-only modules:")
    for module in audit["modules"]:
        if module["status"] in {"no_static_importers", "tests_only", "scripts_only", "non_runtime_importers_only"}:
            print(f"  [{module['status']}] {module['path']} ({module['module']})")
            for key in ("src_importers", "test_importers", "script_importers", "other_importers"):
                if module[key]:
                    print(f"    {key}: {', '.join(module[key])}")

    print("\nHeavy top-level imports:")
    for item in audit["heavy_top_level_imports"]:
        print(f"  {item['path']}:{item['lineno']} imports {item['imported']} ({item['module']})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit full JSON")
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    args = parser.parse_args()

    audit = build_audit()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.json:
        print(json.dumps(audit, indent=2, ensure_ascii=False))
    else:
        _print_text(audit)


if __name__ == "__main__":
    main()
