"""Installer regressions: upgrades must preserve user-owned skills byte for byte."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

INSTALL = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/install_research_skills.py"))[
    "install_skills"
]


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    source = tmp_path / "bundle"
    for name in ("pubmed-quick-search", "pipeline-persistence", "code-reviewer"):
        skill = source / name
        (skill / "references").mkdir(parents=True)
        (skill / "SKILL.md").write_text("bundled instructions", encoding="utf-8")
        (skill / "references" / "guide.md").write_text("bundled guide", encoding="utf-8")
    return source


def test_reinstall_preserves_customizations_and_does_not_mix_skill_versions(bundle: Path, tmp_path: Path) -> None:
    target = tmp_path / "workspace" / ".claude" / "skills"
    INSTALL(target, source=bundle)
    custom = target / "pubmed-quick-search" / "SKILL.md"
    custom.write_bytes("使用者自行修改\n".encode())
    before = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    (bundle / "pubmed-quick-search" / "SKILL.md").write_text("new version", encoding="utf-8")
    (bundle / "pubmed-quick-search" / "references" / "new.md").write_text("new reference", encoding="utf-8")
    new_skill = bundle / "pubmed-new"
    new_skill.mkdir()
    (new_skill / "SKILL.md").write_text("new skill", encoding="utf-8")

    INSTALL(target, source=bundle)

    assert all((target / relative).read_bytes() == data for relative, data in before.items())
    assert not (target / "pubmed-quick-search" / "references" / "new.md").exists()
    assert (target / "pubmed-new" / "SKILL.md").read_text() == "new skill"
    assert not (target / "code-reviewer").exists()
    assert not (target.parents[1] / "AGENTS.md").exists()


@pytest.mark.parametrize("collision", ["file", "directory", "symlink"])
def test_existing_names_are_preserved_even_for_incomplete_installs(
    bundle: Path, tmp_path: Path, collision: str
) -> None:
    target = tmp_path / "installed"
    target.mkdir()
    existing = target / "pubmed-quick-search"
    if collision == "file":
        existing.write_bytes(b"user file")
    elif collision == "directory":
        existing.mkdir()
    else:
        try:
            existing.symlink_to(tmp_path / "missing", target_is_directory=True)
        except OSError:
            pytest.skip("Creating symlinks requires privileges on this platform")
    INSTALL(target, source=bundle)
    if collision == "file":
        assert existing.read_bytes() == b"user file"
    elif collision == "directory":
        assert list(existing.iterdir()) == []
    else:
        assert existing.is_symlink()
        assert not (tmp_path / "missing").exists()
    assert (target / "pipeline-persistence" / "references" / "guide.md").is_file()


def test_dry_run_creates_nothing_and_source_cannot_be_a_destination(bundle: Path, tmp_path: Path) -> None:
    target = tmp_path / "not-created"
    INSTALL(target, source=bundle, dry_run=True)
    assert not target.exists()
    with pytest.raises(ValueError, match="outside"):
        INSTALL(bundle / "nested", source=bundle)
    assert not (bundle / "nested").exists()


def test_symlinked_parent_cannot_redirect_installation(bundle: Path, tmp_path: Path) -> None:
    link = tmp_path / "link"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires privileges on this platform")
    with pytest.raises(ValueError, match="symlinks"):
        INSTALL(link / "skills", source=bundle)
    assert not (tmp_path / "skills").exists()
