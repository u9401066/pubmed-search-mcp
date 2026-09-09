"""The product experiment adds the package without weakening native Codex."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from scripts.benchmark_product_harness import install_package_skills, product_command, validate_answer

from pubmed_search.application.search.agent_benchmark import score_factoid_answer

try:
    import tomllib
except ImportError:
    import tomli as tomllib

if TYPE_CHECKING:
    from pathlib import Path


def test_native_and_package_keep_the_same_web_and_api_capabilities(tmp_path: Path):
    configs = {}
    for arm in ("native", "package"):
        command = product_command(tmp_path / arm, tmp_path / "old-repo", arm, "model", "xhigh")
        assert "--ignore-user-config" in command
        assert "model_instructions_file" not in str(command)
        config = tomllib.loads("\n".join(command[i + 1] for i, arg in enumerate(command) if arg == "-c"))
        assert config["web_search"] == "live"
        assert config["features"]["shell_tool"] is True
        assert config["features"]["unified_exec"] is True
        assert config["sandbox_workspace_write"]["network_access"] is True
        configs[arm] = config
    server = configs["package"].pop("mcp_servers")["pubmed_search"]
    assert configs["native"] == configs["package"]
    assert server["env"]["PYTHONPATH"] == str(tmp_path / "old-repo/src")
    assert "disabled_tools" not in server
    assert "enabled_tools" not in server
    assert server["args"] == ["-m", "pubmed_search.presentation.mcp_server.server"]


def test_package_skills_and_references_are_copied_without_rewriting(tmp_path: Path):
    root = tmp_path / "revision"
    skill = root / ".claude/skills/pubmed-quick-search"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text("Original workflow")
    (skill / "references/details.md").write_text("Original reference")
    hashes = install_package_skills(root, tmp_path / "job")
    assert len(hashes) == 2
    for relative in hashes:
        assert (tmp_path / "job" / relative).read_bytes() == (
            root / relative.replace(".agents/", ".claude/", 1)
        ).read_bytes()


def test_factoid_exact_match_uses_aliases_but_not_substring_matching():
    assert score_factoid_answer("The DMD protein.", ["dystrophin", "DMD protein"], ["123"], "123") == {
        "answer_exact_match": 1.0,
        "source_pmid_hit": 1.0,
    }
    assert score_factoid_answer("DMD protein or insulin", ["DMD protein"], [], "123")["answer_exact_match"] == 0


def test_answer_and_source_success_are_independent():
    assert score_factoid_answer("insulin", ["insulin"], ["456"], "123") == {
        "answer_exact_match": 1.0,
        "source_pmid_hit": 0.0,
    }
    assert score_factoid_answer("", [""], [], "123")["answer_exact_match"] == 0


@pytest.mark.parametrize("pmids", [["123", "123"], ["not-a-pmid"], [123], ["1", "2", "3", "4", "5", "6"]])
def test_invalid_citations_are_rejected(pmids: list):
    with pytest.raises(ValueError):
        validate_answer({"answer": "insulin", "cited_pmids": pmids, "source_urls": []})


def test_valid_json_submission():
    validate_answer(
        json.loads('{"answer":"insulin","cited_pmids":["123"],"source_urls":["https://pubmed.ncbi.nlm.nih.gov/123/"]}')
    )
