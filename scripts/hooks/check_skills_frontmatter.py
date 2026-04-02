#!/usr/bin/env python3
"""Pre-commit hook: validate YAML frontmatter for repository skills."""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import yaml

# Force UTF-8 output on Windows (cp950 can't encode all messages reliably)
if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = ROOT / ".claude" / "skills"
FRONTMATTER_RE = re.compile(r"\A---\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)


def extract_frontmatter_block(text: str) -> tuple[str | None, str | None]:
    """Extract the frontmatter block from a SKILL.md file."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None, "Missing YAML frontmatter at top of file"
    return match.group("body"), None


def validate_frontmatter_data(data: object, expected_name: str) -> list[str]:
    """Validate parsed YAML frontmatter content."""
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["Frontmatter must parse to a YAML mapping"]

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

    license_value = data.get("license")
    if license_value is not None and (not isinstance(license_value, str) or not license_value.strip()):
        errors.append("Optional field 'license' must be a non-empty string")

    return errors


def validate_skill_file(path: Path) -> list[str]:
    """Validate a single SKILL.md file."""
    text = path.read_text(encoding="utf-8")
    frontmatter, extraction_error = extract_frontmatter_block(text)
    if extraction_error or frontmatter is None:
        return [extraction_error or "Missing YAML frontmatter at top of file"]

    try:
        parsed = yaml.safe_load(frontmatter)
    except yaml.YAMLError as exc:
        return [f"Invalid YAML frontmatter: {exc}"]

    return validate_frontmatter_data(parsed, expected_name=path.parent.name)


def validate_skills_tree(skills_dir: Path) -> list[str]:
    """Validate all repository skills under .claude/skills/."""
    errors: list[str] = []

    if not skills_dir.exists():
        return [f"Skills directory not found: {skills_dir}"]

    for skill_dir in sorted(path for path in skills_dir.iterdir() if path.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            errors.append(f".claude/skills/{skill_dir.name}/SKILL.md: Missing SKILL.md")
            continue

        for error in validate_skill_file(skill_file):
            errors.append(f".claude/skills/{skill_dir.name}/SKILL.md: {error}")

    return errors


def main() -> int:
    errors = validate_skills_tree(SKILLS_DIR)
    if not errors:
        return 0

    print("❌ Repository skill frontmatter validation failed:")
    print()
    for error in errors:
        print(f"  • {error}")
    print()
    print("Each repo skill must start with valid YAML frontmatter like:")
    print("---")
    print("name: your-skill-directory")
    print('description: "Short, YAML-safe description"')
    print("---")
    return 1


if __name__ == "__main__":
    sys.exit(main())