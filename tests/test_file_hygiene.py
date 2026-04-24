"""Tests for root-level file hygiene allowances used by repo AI assets."""

from __future__ import annotations

from scripts.hooks.check_file_hygiene import ALLOWED_ROOT_DIRS, ALLOWED_ROOT_FILES, check_file


def test_agents_md_allowed_at_repo_root() -> None:
    assert "AGENTS.md" in ALLOWED_ROOT_FILES
    assert check_file("AGENTS.md") is None


def test_clinerules_directory_allowed_at_repo_root() -> None:
    assert ".clinerules" in ALLOWED_ROOT_DIRS
    assert check_file(".clinerules/00-workspace-baseline.md") is None


def test_non_whitelisted_root_file_still_rejected() -> None:
    assert check_file("random-not-allowed.md") is not None