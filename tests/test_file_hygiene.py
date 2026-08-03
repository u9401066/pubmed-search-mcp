"""Tests for root-level file hygiene allowances used by repo AI assets."""

from __future__ import annotations

from scripts.hooks import check_file_hygiene as hygiene
from scripts.hooks.check_file_hygiene import ALLOWED_ROOT_DIRS, ALLOWED_ROOT_FILES, check_file


def test_agents_md_allowed_at_repo_root() -> None:
    assert "AGENTS.md" in ALLOWED_ROOT_FILES
    assert check_file("AGENTS.md") is None


def test_clinerules_directory_allowed_at_repo_root() -> None:
    assert ".clinerules" in ALLOWED_ROOT_DIRS
    assert check_file(".clinerules/00-workspace-baseline.md") is None


def test_non_whitelisted_root_file_still_rejected() -> None:
    assert check_file("random-not-allowed.md") is not None


def test_shipped_agent_harness_directories_are_allowed() -> None:
    """.codex, .cline, and .asset-aware-mcp are version-controlled peers of .claude."""
    for harness in (".codex", ".cline", ".asset-aware-mcp"):
        assert harness in ALLOWED_ROOT_DIRS
        assert check_file(f"{harness}/skills/example/SKILL.md") is None


def test_unknown_hidden_directory_still_rejected() -> None:
    assert check_file(".some-tool-cache/blob.bin") is not None


def test_temp_artifacts_still_rejected() -> None:
    for path in ("test_results.txt", "notes.log", "scripts/fix_thing.txt"):
        assert check_file(path) is not None


def test_scripts_tmp_still_allowed() -> None:
    assert check_file("scripts/_tmp/result.txt") is None


def test_files_already_at_head_are_not_re_judged(monkeypatch) -> None:
    """An accepted file must stay committable, or auto-fixing hooks deadlock it."""
    legacy = ".ngrok.env"
    assert check_file(legacy) is not None, "precondition: this path is not whitelisted"

    monkeypatch.setattr(hygiene, "get_staged_files", lambda: [legacy])
    monkeypatch.setattr(hygiene, "get_committed_files", lambda: {legacy})
    assert hygiene.main() == 0


def test_newly_added_forbidden_file_is_still_blocked(monkeypatch) -> None:
    monkeypatch.setattr(hygiene, "get_staged_files", lambda: ["test_results.txt"])
    monkeypatch.setattr(hygiene, "get_committed_files", set)
    assert hygiene.main() == 1
