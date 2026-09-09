"""Offline budgets, real MCP adapter routing, and measured agent outcomes."""

from __future__ import annotations

import json
import socket
from typing import TYPE_CHECKING

import pytest
from mcp.client import Client
from scripts.benchmark_agent_harness import agent_command, source_fingerprint
from scripts.benchmark_agent_server import _block_network, build_server

from pubmed_search.application.search.agent_benchmark import paired_comparison, score_agent_search
from pubmed_search.infrastructure.evaluation.corpus import FrozenCorpus

try:
    import tomllib
except ImportError:
    import tomli as tomllib

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def frozen_corpus(tmp_path: Path):
    path = tmp_path / "corpus.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"_id": "doc-a", "title": "Sepsis therapy", "text": "Treatment of infection"},
                {"_id": "doc-b", "title": "Diabetes care", "text": "Insulin treatment"},
            ]
        ),
        encoding="utf-8",
    )
    corpus = FrozenCorpus(path, tmp_path / "audit.json", search_budget=2, document_budget=3)
    yield corpus
    corpus.close()


async def test_search_is_query_dependent_and_budget_is_enforced(frozen_corpus: FrozenCorpus):
    first = await frozen_corpus.search("sepsis")
    second = await frozen_corpus.search("diabetes")
    assert first[0]["benchmark_id"] == "doc-a"
    assert second[0]["benchmark_id"] == "doc-b"
    assert first[0]["pmid"] != second[0]["pmid"]
    with pytest.raises(ValueError, match="budget exhausted"):
        await frozen_corpus.search("sepsis")
    audit = json.loads(frozen_corpus.audit_path.read_text())
    assert audit["search_calls"] == 2
    assert audit["document_exposures"] == 2
    assert audit["observed_ids"] == ["doc-a", "doc-b"]


async def test_reads_consume_remaining_document_budget(frozen_corpus: FrozenCorpus):
    results = await frozen_corpus.search("treatment", limit=10)
    ids = [row["pmid"] for row in results]
    assert len(await frozen_corpus.fetch_details(ids)) == 1
    assert await frozen_corpus.fetch_details(ids) == []
    assert frozen_corpus.document_exposures == 3


async def test_punctuation_does_not_become_sql(frozen_corpus: FrozenCorpus):
    assert await frozen_corpus.search('"; DROP TABLE papers; --') == []
    assert (await frozen_corpus.search("sepsis"))[0]["benchmark_id"] == "doc-a"


@pytest.mark.parametrize("arm", ["basic", "repo"])
async def test_native_mcp_search_uses_frozen_corpus(frozen_corpus: FrozenCorpus, tmp_path: Path, arm: str):
    server = await build_server(frozen_corpus, arm, tmp_path / "state")
    async with Client(server) as client:
        listed = {tool.name for tool in (await client.list_tools()).tools}
        assert "budget_status" in listed
        assert "get_fulltext" not in listed
        assert all(tool.annotations.read_only_hint for tool in (await client.list_tools()).tools)
        if arm == "basic":
            result = await client.call_tool("search", {"query": "sepsis"})
        else:
            result = await client.call_tool(
                "unified_search",
                {
                    "query": "sepsis",
                    "sources": "pubmed",
                    "limit": 1,
                    "output_format": "json",
                    "options": "shallow,no_oa,no_relax,no_analysis,no_scores,no_next",
                },
            )
        assert not result.is_error
        text = "\n".join(block.text for block in result.content if hasattr(block, "text"))
        assert "Sepsis therapy" in text
        assert "Diabetes care" not in text
        assert frozen_corpus.search_calls == 1


def test_discovery_and_selection_are_separate():
    scores = score_agent_search(["a"], ["a", "b", "noise"], {"a": 1, "b": 1, "missing": 1})
    assert scores["retrieval_recall"] == pytest.approx(2 / 3)
    assert scores["selection_recall"] == pytest.approx(1 / 3)
    assert scores["selection_precision"] == 1
    assert scores["gold_discard_rate"] == 0.5


def test_unseen_selections_are_rejected():
    with pytest.raises(ValueError, match="retrieved or read"):
        score_agent_search(["hidden"], ["a"], {"hidden": 1})


def test_empty_run_counts_as_zero():
    assert all(score == 0 for score in score_agent_search([], [], {"a": 1}).values())


def test_paired_comparison_requires_same_queries():
    with pytest.raises(ValueError, match="matching query IDs"):
        paired_comparison({"a": 1}, {"b": 1})


def test_paired_interval_uses_query_differences_reproducibly():
    result = paired_comparison({"a": 0.2, "b": 0.5}, {"a": 0.3, "b": 0.6}, samples=100)
    assert result["delta"] == pytest.approx(0.1)
    assert result["paired_bootstrap_95_interval"] == pytest.approx([0.1, 0.1])


def test_duplicate_selections_cannot_inflate_scores():
    with pytest.raises(ValueError, match="unique"):
        score_agent_search(["a", "a"], ["a"], {"a": 1})


def test_offline_server_rejects_external_sockets():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        with pytest.raises(RuntimeError, match="Network access"):
            _block_network("socket.connect", (connection, ("example.com", 443)))
    if hasattr(socket, "AF_UNIX"):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            _block_network("socket.connect", (connection, "/tmp/local.sock"))


def test_offline_server_blocks_network_without_unix_socket_support(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delattr(socket, "AF_UNIX", raising=False)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        with pytest.raises(RuntimeError, match="Network access"):
            _block_network("socket.connect", (connection, ("example.com", 443)))


def test_agent_configuration_limits_tools_and_separates_baseline(tmp_path: Path):
    command = agent_command(tmp_path / 'job " quoted', tmp_path / "data", tmp_path / "old", "repo", "model", "high")
    config = tomllib.loads("\n".join(command[index + 1] for index, arg in enumerate(command) if arg == "-c"))
    assert "--ignore-user-config" in command
    assert config["web_search"] == "disabled"
    assert config["features"]["shell_tool"] is False
    assert config["features"]["plugins"] is False
    assert config["features"]["code_mode_host"] is True
    assert config["mcp_servers"]["literature"]["env"]["PYTHONPATH"] == str(tmp_path / "old/src")
    assert "qrels" not in str(config["mcp_servers"])
    assert config["model_instructions_file"] == str(tmp_path / 'job " quoted/instructions.txt')


def test_revision_fingerprint_detects_source_changes(tmp_path: Path):
    source = tmp_path / "src/pubmed_search"
    source.mkdir(parents=True)
    product = source / "server.py"
    product.write_text("original")
    before = source_fingerprint(tmp_path)
    adapter = source / "infrastructure/evaluation"
    adapter.mkdir(parents=True)
    (adapter / "corpus.py").write_text("shared adapter")
    assert source_fingerprint(tmp_path) == before
    product.write_text("changed")
    assert source_fingerprint(tmp_path) != before
