"""Prevent misplaced files, unsupported paper inputs, and accidental source uploads."""

from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml
from scripts.build_publication import load_evidence, prepare, source_bundle, validate_citations
from scripts.check_repository_layout import inventory

ROOT = Path(__file__).resolve().parents[1]


def test_layout_detects_new_and_ambiguous_files_but_excludes_ignored_output(tmp_path: Path) -> None:
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("build/\n", encoding="utf-8")
    (tmp_path / "build").mkdir()
    (tmp_path / "build/private.log").write_text("local output", encoding="utf-8")
    (tmp_path / "stray.md").touch()
    layout = {"categories": [{"name": "config", "status": "current", "files": [".gitignore"]}]}
    result = inventory(tmp_path, layout)
    assert result["total_files"] == 2
    assert result["errors"] == [{"path": "stray.md", "matching_categories": []}]
    layout["categories"].extend({"name": name, "status": "current", "files": ["stray.md"]} for name in ("a", "b"))
    assert inventory(tmp_path, layout)["errors"] == [{"path": "stray.md", "matching_categories": ["a", "b"]}]


@pytest.mark.parametrize("escape", [False, True])
def test_publication_rejects_tampered_or_out_of_scope_evidence(tmp_path: Path, escape: bool) -> None:
    publication = tmp_path / "docs/publication"
    publication.mkdir(parents=True)
    reports = tmp_path / "docs/reports"
    reports.mkdir()
    record = {"path": "docs/reports/result.json", "sha256": "0" * 64}
    (reports / "result.json").write_text('{"invented_score": 1.0}', encoding="utf-8")
    if escape:
        record["path"] = "../outside.json"
    (publication / "evidence.json").write_text(json.dumps({"records": {"test": record}}), encoding="utf-8")
    with pytest.raises(ValueError, match="outside docs/reports" if escape else "hash mismatch"):
        load_evidence(tmp_path)


def test_publication_rejects_broken_and_duplicate_citations() -> None:
    with pytest.raises(ValueError, match=r"missing=.*absent"):
        validate_citations(r"\citep{absent}", "@article{actual, title={An article}}")
    with pytest.raises(ValueError, match="Duplicate"):
        validate_citations(r"\citep{same}", "@article{same, title={One}}\n@misc{same, title={Two}}")


def test_current_manuscript_build_packages_only_portable_sources(tmp_path: Path) -> None:
    receipt = prepare(ROOT, tmp_path)
    assert receipt["status"] == "prepared; not compiled or submitted"
    # Compilation is explicit, never a side effect of validating evidence.
    assert not (tmp_path / "main.pdf").exists()
    with pytest.raises(ValueError, match=r"main\.bbl"):
        source_bundle(tmp_path)
    (tmp_path / "main.bbl").write_text("resolved bibliography fixture", encoding="utf-8")
    (tmp_path / "main.pdf").write_bytes(b"not an upload source")
    (tmp_path / "private-notes.txt").write_text("must not be uploaded", encoding="utf-8")
    with zipfile.ZipFile(source_bundle(tmp_path)) as archive:
        names = archive.namelist()
        assert "main.bbl" in names and "references.bib" in names
        assert "main.pdf" not in names and "private-notes.txt" not in names
        assert all(Path(name).name == name for name in names)
        assert archive.read("main.tex") == (ROOT / "docs/publication/main.tex").read_bytes()
    # Even an allowlisted name must not pull in a symlink's external contents.
    (tmp_path / "main.bbl").unlink()
    try:
        (tmp_path / "main.bbl").symlink_to(tmp_path / "private-notes.txt")
    except OSError:
        return  # Windows installations may not grant symlink creation.
    with pytest.raises(ValueError, match="unsafe"):
        source_bundle(tmp_path)


def test_author_and_archive_identity_remain_consistent() -> None:
    citation = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    assert citation["authors"] == citation["preferred-citation"]["authors"]
    manuscript = (ROOT / "docs/publication/main.tex").read_text(encoding="utf-8")
    for author in citation["authors"]:
        assert f"{author['given-names']} {author['family-names']}" in manuscript
        assert author["affiliation"] in manuscript
    # Archived drafts have a stable checksum record independent of future Git history.
    manifest = json.loads((ROOT / "docs/archive/publication/originals.json").read_text(encoding="utf-8"))
    from hashlib import sha256

    for name, expected in manifest["sha256"].items():
        assert sha256((ROOT / "docs/archive/publication" / name).read_bytes()).hexdigest() == expected
