"""Tests for self-evolution policy checks."""

from __future__ import annotations

from scripts.hooks import check_evolution_cycle as cycle


def test_pyproject_addopts_allows_oom_safe_timeout_without_xdist(tmp_path, monkeypatch) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.pytest.ini_options]
addopts = "--timeout=60"
""",
        encoding="utf-8",
    )
    precommit = tmp_path / ".pre-commit-config.yaml"
    precommit.write_text("stages: [pre-push]\n", encoding="utf-8")
    monkeypatch.setattr(cycle, "ROOT", tmp_path)
    monkeypatch.setattr(cycle, "PRECOMMIT_CONFIG", precommit)
    report = cycle.ValidationReport()

    cycle.check_pyproject_addopts(report)

    assert report.errors == []


def test_pyproject_addopts_ignores_comment_only_setting(tmp_path, monkeypatch) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
# addopts = "--timeout=60"
[tool.pytest.ini_options]
testpaths = ["tests"]
""",
        encoding="utf-8",
    )
    precommit = tmp_path / ".pre-commit-config.yaml"
    precommit.write_text("stages: [pre-push]\n", encoding="utf-8")
    monkeypatch.setattr(cycle, "ROOT", tmp_path)
    monkeypatch.setattr(cycle, "PRECOMMIT_CONFIG", precommit)
    report = cycle.ValidationReport()

    cycle.check_pyproject_addopts(report)

    assert any("missing addopts" in issue.message for issue in report.errors)
