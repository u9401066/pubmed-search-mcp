"""Agent-facing offline smoke tests for unified search and artifact recovery."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.presentation.mcp_server import create_server
from pubmed_search.presentation.mcp_server.tools import unified as unified_module
from pubmed_search.shared.source_contracts import SourceAdapterError, SourceAdapterResult

ROOT = Path(__file__).resolve().parents[1]
OFFLINE_SERVER = ROOT / "tests" / "fixtures" / "offline_unified_mcp_server.py"
SEARCH_ARGUMENTS = {
    "query": "offline smoke",
    "sources": "pubmed,semantic_scholar",
    "limit": 3,
    "output_format": "json",
    "options": "shallow,no_oa,no_relax,no_analysis,no_scores,no_next",
}
PIPELINE_SMOKE = """\
name: offline-recovery-plan
steps:
  - id: search
    action: search
    params:
      query: offline pipeline
      sources: pubmed
      limit: 2
output:
  format: json
  limit: 2
"""
EXPECTED_REPLAY_ARGUMENTS = {
    **SEARCH_ARGUMENTS,
    "ranking": "balanced",
    "dry_run": False,
    "stop_at": "",
}
SECRET_SENTINEL = "OFFLINE_SMOKE_TOPSECRET"


def _result_text(result: Any) -> str:
    return "\n".join(block.text for block in result.content if hasattr(block, "text"))


def _assert_credential_free(value: Any) -> None:
    serialized = json.dumps(value, ensure_ascii=False).lower()
    for forbidden in ("api_key", "apikey", "authorization", "bearer ", "client_secret", "password"):
        assert forbidden not in serialized
    assert "offline-smoke@example.com" not in serialized


async def _successful_pubmed(*args: object, **kwargs: object) -> SourceAdapterResult[UnifiedArticle]:
    del args, kwargs
    return SourceAdapterResult(
        source="pubmed",
        operation="search",
        items=[
            UnifiedArticle(
                title="Deterministic Offline Evidence",
                primary_source="pubmed",
                pmid="42424242",
                doi="10.1000/offline-smoke",
                year=2026,
            )
        ],
        total_count=1,
        metadata={"total_available": 1, "physical_query": "offline smoke", "query_executed": True},
    )


async def _failed_semantic_scholar(*args: object, **kwargs: object) -> SourceAdapterResult[UnifiedArticle]:
    del args, kwargs
    return SourceAdapterResult.failure(
        source="semantic_scholar",
        operation="search",
        error=SourceAdapterError(
            source="semantic_scholar",
            operation="search",
            message="deterministic offline rate limit",
            kind="http",
            retryable=True,
            status_code=429,
        ),
        metadata={"physical_query": "offline smoke", "query_executed": True},
    )


async def _assert_search_and_recovery(client: Client[Any]) -> None:
    listed = await client.list_tools()
    tool_names = {tool.name for tool in listed.tools}
    assert "unified_search" in tool_names
    assert tool_names.isdisjoint({"search_pubmed", "search_literature", "search_openalex"})

    result = await client.call_tool("unified_search", SEARCH_ARGUMENTS)
    assert result.is_error is False
    payload = json.loads(_result_text(result))
    assert [article["identifiers"]["pmid"] for article in payload["articles"]] == ["42424242"]
    assert len(payload["source_errors"]) == 1
    source_error = payload["source_errors"][0]
    assert source_error["source"] == "semantic_scholar"
    assert source_error["status"] == "rate_limited"
    assert source_error["status_code"] == 429
    assert source_error["retryable"] is True
    source_rows = {row["source"]: row for row in payload["source_counts"]}
    assert source_rows["pubmed"]["returned"] == 1
    assert source_rows["semantic_scholar"]["returned"] == 0

    summary = payload["artifact_summary"]
    assert summary["artifact_uri"].startswith("artifact://")
    assert summary["audit_status"] == "warn"
    assert summary["recommended_read_order"][:2] == ["audit.json", "query_strategy.json"]

    search_run = payload["search_run"]
    run_id = search_run["run_id"]
    assert run_id
    assert search_run == {
        "run_id": run_id,
        "status": "partial",
        "recoverable": True,
        "history_available": True,
        "inspect": {
            "tool": "read_session",
            "arguments": {"action": "search_run", "run_id": run_id},
        },
        "replay": {
            "tool": "read_session",
            "arguments": {"action": "replay_search", "run_id": run_id},
        },
        "artifact_uri": summary["artifact_uri"],
    }

    run_result = await client.call_tool(
        "read_session",
        {"action": "search_run", "run_id": run_id},
    )
    run_page = json.loads(_result_text(run_result))
    assert run_page["success"] is True
    assert run_page["replay_available"] is True
    recovered_run = run_page["run"]
    assert recovered_run["run_id"] == run_id
    assert recovered_run["status"] == "partial"
    assert recovered_run["recoverable"] is True
    assert recovered_run["artifact"]["artifact_uri"] == summary["artifact_uri"]
    assert len(recovered_run["artifact"]["sha256"]) == 64
    assert recovered_run["artifact"]["files"]["results.json"]["sha256"]
    assert recovered_run["artifact"]["files"]["audit.json"]["sha256"]
    attempts = {attempt["source"]: attempt for attempt in recovered_run["source_attempts"]}
    assert attempts["pubmed"]["status"] == "ok"
    assert attempts["pubmed"]["returned"] == 1
    assert attempts["semantic_scholar"]["status"] == "rate_limited"
    assert attempts["semantic_scholar"]["returned"] == 0
    assert attempts["semantic_scholar"]["failure"]["retryable"] is True

    replay_result = await client.call_tool(
        "read_session",
        {"action": "replay_search", "run_id": run_id},
    )
    replay_page = json.loads(_result_text(replay_result))
    assert replay_page["success"] is True
    assert replay_page["run_id"] == run_id
    assert replay_page["automatic_execution"] is False
    assert replay_page["replay"] == {
        "tool": "unified_search",
        "arguments": EXPECTED_REPLAY_ARGUMENTS,
        "replay_of": run_id,
        "previous_status": "partial",
    }
    _assert_credential_free(replay_page)

    audit_result = await client.call_tool(
        "read_session",
        {
            "action": "artifact",
            "artifact_uri": summary["artifact_uri"],
            "artifact_file": "audit.json",
        },
    )
    audit_page = json.loads(_result_text(audit_result))
    assert audit_page["success"] is True
    assert json.loads(audit_page["content"])["status"] == "warn"

    strategy_result = await client.call_tool(
        "read_session",
        {
            "action": "artifact",
            "artifact_uri": summary["artifact_uri"],
            "artifact_file": "query_strategy.json",
        },
    )
    strategy_page = json.loads(_result_text(strategy_result))
    strategy = json.loads(strategy_page["content"])
    assert strategy["original_query"] == "offline smoke"
    assert strategy["source_queries"]["pubmed"]["logical_query"] == "offline smoke"
    assert strategy["source_queries"]["semantic_scholar"]["executed"] is True
    assert strategy["source_counts"]["semantic_scholar"]["returned"] == 0


async def _assert_planning_failure_is_recoverable(client: Client[Any]) -> None:
    result = await client.call_tool(
        "unified_search",
        {
            "query": "offline invalid source",
            "sources": "provider_that_does_not_exist",
            "output_format": "json",
            "options": "shallow,no_oa,no_relax",
        },
    )
    assert result.is_error is False
    error_payload = json.loads(_result_text(result))
    assert error_payload["success"] is False
    assert "read_session" in error_payload["suggestion"]

    runs_result = await client.call_tool(
        "read_session",
        {"action": "search_runs", "run_status": "failed"},
    )
    runs_page = json.loads(_result_text(runs_result))
    assert runs_page["success"] is True
    assert runs_page["returned_runs"] >= 1
    failed_run = runs_page["runs"][-1]
    assert failed_run["status"] == "failed"
    assert failed_run["recoverable"] is False


async def _assert_pipeline_dry_run_is_journaled(client: Client[Any]) -> None:
    result = await client.call_tool(
        "unified_search",
        {
            "query": "offline pipeline",
            "pipeline": PIPELINE_SMOKE,
            "dry_run": True,
            "output_format": "json",
        },
    )
    assert result.is_error is False
    payload = json.loads(_result_text(result))
    assert payload["type"] == "pipeline_result"
    assert payload["pipeline"]["dry_run"] is True
    assert payload["search_status"] == {
        "state": "completed",
        "bounded": True,
        "exhaustive": False,
        "mode": "pipeline",
    }
    run_id = payload["search_run"]["run_id"]

    replay_result = await client.call_tool(
        "read_session",
        {"action": "replay_search", "run_id": run_id},
    )
    replay_page = json.loads(_result_text(replay_result))
    assert replay_page["success"] is True
    assert replay_page["replay"]["arguments"]["pipeline"] == PIPELINE_SMOKE
    assert replay_page["replay"]["arguments"]["dry_run"] is True
    assert replay_page["replay"]["arguments"]["query"] == "offline pipeline"


async def _assert_credential_bearing_query_is_rejected(client: Client[Any]) -> None:
    result = await client.call_tool(
        "unified_search",
        {
            "query": f"cancer api_key={SECRET_SENTINEL}",
            "output_format": "json",
        },
    )
    assert result.is_error is False
    response_text = _result_text(result)
    assert SECRET_SENTINEL not in response_text
    payload = json.loads(response_text)
    assert payload["success"] is False
    assert "credential material" in payload["error"]


@pytest.mark.asyncio
async def test_in_memory_unified_search_partial_failure_and_artifact_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(unified_module, "_search_pubmed_adapter", _successful_pubmed)
    monkeypatch.setattr(unified_module, "_search_semantic_scholar_adapter", _failed_semantic_scholar)
    data_dir = tmp_path / "in-memory-data"
    async with Client(create_server(data_dir=data_dir, mode="local")) as client:
        await _assert_search_and_recovery(client)
        await _assert_pipeline_dry_run_is_journaled(client)
        await _assert_planning_failure_is_recoverable(client)
        await _assert_credential_bearing_query_is_rejected(client)
    assert SECRET_SENTINEL not in "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in data_dir.rglob("*") if path.is_file()
    )


@pytest.mark.asyncio
async def test_real_stdio_subprocess_unified_search_and_artifact_recovery(tmp_path: Path) -> None:
    env = os.environ.copy()
    data_dir = tmp_path / "stdio-data"
    env.update(
        {
            "NCBI_EMAIL": "offline-smoke@example.com",
            "PUBMED_DATA_DIR": str(data_dir),
            "PUBMED_SCHEDULER_ENABLED": "false",
            "PYTHONUNBUFFERED": "1",
        }
    )
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(OFFLINE_SERVER)],
        cwd=ROOT,
        env=env,
    )

    async with Client(stdio_client(parameters), read_timeout_seconds=20) as client:
        await _assert_search_and_recovery(client)
        await _assert_pipeline_dry_run_is_journaled(client)
        await _assert_credential_bearing_query_is_rejected(client)
    assert SECRET_SENTINEL not in "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in data_dir.rglob("*") if path.is_file()
    )
