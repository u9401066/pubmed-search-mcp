"""Tests for the repository skill frontmatter pre-commit hook."""

from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "hooks" / "check_skills_frontmatter.py"
SPEC = importlib.util.spec_from_file_location("check_skills_frontmatter", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write_skill(tmp_path: Path, directory: str, content: str) -> Path:
    skill_dir = tmp_path / ".claude" / "skills" / directory
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content, encoding="utf-8")
    return skill_file


class TestCheckSkillsFrontmatter:
    def test_validate_skill_file_accepts_valid_frontmatter(self, tmp_path: Path) -> None:
        skill_file = _write_skill(
            tmp_path,
            "demo-skill",
            "---\nname: demo-skill\ndescription: \"Valid description\"\n---\n\n# Demo\n",
        )

        assert MODULE.validate_skill_file(skill_file) == []

    def test_validate_skill_file_rejects_name_mismatch(self, tmp_path: Path) -> None:
        skill_file = _write_skill(
            tmp_path,
            "demo-skill",
            "---\nname: other-skill\ndescription: \"Valid description\"\n---\n",
        )

        errors = MODULE.validate_skill_file(skill_file)
        assert any("does not match directory" in error for error in errors)

    def test_validate_skill_file_rejects_invalid_yaml(self, tmp_path: Path) -> None:
        skill_file = _write_skill(
            tmp_path,
            "demo-skill",
            "---\nname: demo-skill\ndescription: invalid: yaml\n---\n",
        )

        errors = MODULE.validate_skill_file(skill_file)
        assert any("Invalid YAML frontmatter" in error for error in errors)

    def test_validate_skills_tree_reports_missing_skill_file(self, tmp_path: Path) -> None:
        empty_skill_dir = tmp_path / ".claude" / "skills" / "missing-skill"
        empty_skill_dir.mkdir(parents=True)

        errors = MODULE.validate_skills_tree(tmp_path / ".claude" / "skills")
        assert any("Missing SKILL.md" in error for error in errors)