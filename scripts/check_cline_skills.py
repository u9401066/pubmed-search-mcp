#!/usr/bin/env python3
"""Validate repository skills used by Cline and other bundled agent harnesses."""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import yaml

if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOTS = (ROOT / ".cline" / "skills", ROOT / ".codex" / "skills")
FRONTMATTER_RE = re.compile(r"\A---\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)


def _validate_skill_file(path: Path, root: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return ["Missing YAML frontmatter at top of file"]

    try:
        data = yaml.safe_load(match.group("body"))
    except yaml.YAMLError as exc:
        return [f"Invalid YAML frontmatter: {exc}"]

    if not isinstance(data, dict):
        return ["Frontmatter must parse to a YAML mapping"]

    errors: list[str] = []
    expected_name = path.parent.name
    name = data.get("name")
    description = data.get("description")
    if not isinstance(name, str) or not name.strip():
        errors.append("Missing required string field 'name'")
    elif name.strip() != expected_name:
        errors.append(f"Frontmatter name '{name.strip()}' does not match directory '{expected_name}'")
    if not isinstance(description, str) or not description.strip():
        errors.append("Missing required non-empty string field 'description'")

    allowed_tools = data.get("allowed-tools")
    if allowed_tools is not None and (
        not isinstance(allowed_tools, list)
        or any(not isinstance(tool, str) or not tool.strip() for tool in allowed_tools)
    ):
        errors.append("Optional field 'allowed-tools' must be a list of non-empty strings")

    return [f"{path.relative_to(root.parent.parent)}: {error}" for error in errors]


def _validate_skill_root(root: Path) -> list[str]:
    if not root.exists():
        return []

    errors: list[str] = []
    for skill_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            errors.append(f"{skill_dir.relative_to(ROOT)}/SKILL.md: Missing SKILL.md")
            continue
        errors.extend(_validate_skill_file(skill_file, ROOT))
    return errors


def main() -> int:
    errors: list[str] = []
    for root in SKILL_ROOTS:
        errors.extend(_validate_skill_root(root))

    if not errors:
        print("Cline/Codex skill validation passed.")
        return 0

    print("Cline/Codex skill validation failed:")
    print()
    for error in errors:
        print(f"  - {error}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
