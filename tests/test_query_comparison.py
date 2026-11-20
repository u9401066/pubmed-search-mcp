"""Boolean difference counts, provider failure and recoverable agent evidence."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest
from mcp.client import Client

from pubmed_search.application.search.query_comparison import QueryComparison, compare_queries
from pubmed_search.infrastructure.ncbi.strategy import SearchStrategyGenerator
from pubmed_search.presentation.mcp_server.server import create_server
from pubmed_search.shared.tenancy import ANONYMOUS_HTTP_TENANT

if TYPE_CHECKING:
    from pathlib import Path


def observation(count: int, *pmids: str, warnings: list[str] | None = None) -> dict[str, Any]:
    return {"count": count, "pmids": list(pmids), "translation": "PubMed translation", "warnings": warnings or []}


async def test_seed_priority_uses_exact_membership_outside_sample_and_preserves_groups():
    probe = AsyncMock(
        side_effect=[
            observation(0),
            observation(4, "1", "2", "3"),
            observation(90, "4", "5", "6"),
            observation(1, "42"),
            observation(1, "7"),
            observation(0),
        ]
    )
    spec = QueryComparison(blocks={"C": "gamma", "B": "beta OR alias", "D": "delta"}, seed_pmids=["7", "42"])
    summary, files = await compare_queries("alpha AND 1980:1990[dp]", spec, probe)
    assert summary["changes"] == [
        {"drop": "B", "add": 4, "seed_hits": ["7"]},
        {"drop": "D", "add": 1, "seed_hits": ["42"]},
    ]
    assert summary["more"] == 1 and "either_total" not in summary
    assert summary["baseline"] == 0 and summary["status"] == "ok"
    assert len(probe.await_args_list) == 6
    assert (
        files["drop-C.json"]["difference"]["query"]
        == "((alpha AND 1980:1990[dp]) AND (beta OR alias) AND (delta)) NOT (gamma)"
    )
    assert probe.await_args_list[-2].args == (
        "(((alpha AND 1980:1990[dp]) AND (gamma) AND (delta)) NOT (beta OR alias)) AND (42[uid] OR 7[uid])",
        2,
    )


async def test_partial_results_do_not_convert_warning_or_deadline_to_zero():
    spec = QueryComparison(blocks={"C": "gamma", "B": "beta"})
    probe = AsyncMock(side_effect=[observation(3), observation(0, warnings=["term ignored"]), observation(0)])
    summary, files = await compare_queries("alpha", spec, probe)
    assert summary == {
        "status": "partial",
        "baseline": 3,
        "changes": [],
        "relevance": "unassessed",
        "incomplete": ["B"],
        "warning_examples": ["term ignored"],
    }
    assert files["drop-B.json"]["difference"]["warnings"] == ["term ignored"]
    expired, _ = await compare_queries("alpha", spec, probe, timeout=0)
    assert expired["baseline"] is None and expired["incomplete"] == ["baseline", "B", "C"]
    assert probe.await_count == 3


@pytest.mark.parametrize(
    "blocks", [{"B": "beta", "C": "Beta "}, {"B": "beta", "b": "gamma"}, {"B": "(beta", "C": "gamma"}]
)
async def test_invalid_blocks_fail_before_network(blocks):
    probe = AsyncMock()
    with pytest.raises(ValueError):
        await compare_queries("alpha", QueryComparison(blocks=blocks), probe)
    probe.assert_not_awaited()


async def test_reordering_blocks_keeps_queries_and_zero_counts():
    probe = AsyncMock(return_value=observation(0))
    for blocks in ({"B": "beta", "C": "gamma"}, {"C": "gamma", "B": "beta"}):
        summary, _ = await compare_queries("alpha", QueryComparison(blocks=blocks), probe)
        assert summary["status"] == "ok" and summary["either_total"] == 0 and summary["changes"] == []
    assert probe.await_args_list[:3] == probe.await_args_list[3:]


async def test_anonymous_preview_returns_inline_samples_without_writing(tmp_path, monkeypatch):
    from pubmed_search.presentation.mcp_server.tools import unified

    probe = AsyncMock(side_effect=[observation(0), observation(1, "7"), observation(0)])
    persist = AsyncMock()
    monkeypatch.setattr(SearchStrategyGenerator, "probe_query", probe)
    monkeypatch.setattr(unified, "current_tenant", lambda: ANONYMOUS_HTTP_TENANT)
    monkeypatch.setattr(unified, "persist_tool_artifact", persist)
    async with Client(create_server(data_dir=str(tmp_path))) as client:
        response = await client.call_tool(
            "analyze_search_query",
            {
                "query": "alpha",
                "comparison": {"blocks": {"B": "beta", "C": "gamma"}},
            },
        )
        payload = json.loads(response.content[0].text)
        assert payload["storage"] == "inline" and "artifact_uri" not in payload
        assert payload["changes"] == [{"drop": "B", "add": 1, "sample_pmids": ["7"]}]
        persist.assert_not_awaited()


def test_provider_probe_rejects_malformed_counts_and_distinguishes_real_empty():
    raw = {
        "Count": "0",
        "IdList": [],
        "QueryTranslation": "beta",
        "WarningList": {"OutputMessage": ["No items found."]},
    }
    assert SearchStrategyGenerator._parse_probe(raw, 3) == observation(0) | {"translation": "beta"}
    with pytest.raises(ValueError):
        SearchStrategyGenerator._parse_probe({**raw, "Count": "1"}, 3)
    with pytest.raises(KeyError):
        SearchStrategyGenerator._parse_probe({"IdList": []}, 3)


async def test_public_preview_and_artifact_resume_after_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    probe = AsyncMock(
        side_effect=[observation(12, "1", "2", "3"), observation(10, "4", "5", "6"), observation(190, "7", "8", "9")]
    )
    monkeypatch.setattr(SearchStrategyGenerator, "probe_query", probe)
    args = {
        "query": "Cochlear Implants[mh]",
        "comparison": {"blocks": {"C": "Speech Intelligibility[mh]", "B": "Speech Perception[mh]"}},
    }
    async with Client(create_server(data_dir=str(tmp_path))) as client:
        local = await client.call_tool(
            "analyze_search_query", {"query": "Cochlear Implants[mh] AND Speech Perception[mh]"}
        )
        assert "comparison.blocks" in local.content[0].text
        probe.assert_not_awaited()
        response = await client.call_tool("analyze_search_query", args)
        assert not response.is_error
        payload = json.loads(response.content[0].text)
        assert payload["either_total"] == 212 and payload["baseline"] == 12
        assert payload["changes"] == [{"drop": "C", "add": 190}, {"drop": "B", "add": 10}]
        assert len(response.content[0].text.encode()) < 350
        assert probe.await_count == 3
    async with Client(create_server(data_dir=str(tmp_path))) as resumed:
        read = await resumed.call_tool(
            "read_session",
            {
                "request": {
                    "action": "artifact",
                    "locator": {"kind": "artifact_uri", "value": payload["artifact_uri"]},
                    "artifact_file": "drop-B.json",
                }
            },
        )
        assert not read.is_error
        evidence = json.loads(json.loads(read.content[0].text)["content"])
        assert evidence["difference"]["pmids"] == ["4", "5", "6"]
        assert evidence["relaxed_query"] == "(Cochlear Implants[mh]) AND (Speech Intelligibility[mh])"
