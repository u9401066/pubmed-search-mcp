"""Agent Plugins package and MCP Registry metadata stay publishable."""

from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from scripts.build_agent_plugin import build_development_plugin

from tests.fixtures.release_support import smoke_env
from tests.test_all_tools_mcp_acceptance import PIPELINE_CONFIG
from tests.test_release_transport_smoke import result_text

ROOT = Path(__file__).resolve().parents[1]
FIND_DRIFT = runpy.run_path(str(ROOT / "scripts/build_agent_plugin.py"))["find_drift"]


def test_plugin_and_registry_metadata_match_skills_and_release_version() -> None:
    assert FIND_DRIFT() == []


def test_pypi_readme_carries_registry_ownership_marker() -> None:
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))

    assert f"mcp-name: {server['name']}" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_development_plugin_runs_checkout_and_preserves_customized_skills(tmp_path: Path) -> None:
    target = tmp_path / "compatible client" / "pubmed plugin"
    assert build_development_plugin(target) == target
    launcher = json.loads((target / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["pubmed-search"]
    assert launcher["command"] == "uv"
    assert launcher["args"] == ["run", "--project", str(ROOT), "--frozen", "pubmed-search-mcp"]
    assert not (target / "server.json").exists()
    assert build_development_plugin(target) == target
    skill = target / "skills/pubmed-research-workspace/SKILL.md"
    assert skill.is_file()
    skill.write_text("My lab's own workflow", encoding="utf-8")
    with pytest.raises(ValueError, match="different contents"):
        build_development_plugin(target)
    assert skill.read_text(encoding="utf-8") == "My lab's own workflow"


@pytest.mark.asyncio
async def test_development_plugin_resumes_a_branch_and_reopens_its_saved_strategy(tmp_path: Path) -> None:
    plugin = build_development_plugin(tmp_path / "plugin")
    launcher = json.loads((plugin / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["pubmed-search"]
    server = StdioServerParameters(
        command=launcher["command"], args=launcher["args"], cwd=tmp_path, env=smoke_env(tmp_path)
    )

    async def workspace(client: Client, action: str, **fields: Any) -> dict[str, Any]:
        response = await client.call_tool(
            "research_workspace", {"request": {"action": action, "workspace_id": "implant-history", **fields}}
        )
        assert not response.is_error
        return json.loads(result_text(response))

    async with Client(stdio_client(server), read_timeout_seconds=30) as client:
        await workspace(client, "create", question="Which historical comparisons should we examine?")
        saved = await client.call_tool(
            "save_pipeline", {"name": "implant", "config": PIPELINE_CONFIG, "scope": "global"}
        )
        assert not saved.is_error
        await workspace(
            client,
            "record",
            activity="explore",
            record_id="search",
            note="Saved the retrieval strategy.",
            source_refs=["pipeline:implant"],
        )
        await workspace(
            client,
            "record",
            activity="expand",
            record_id="branch",
            parent_ids=["search"],
            note="Follow the comparison in this indexed paper.",
            source_refs=["pmid:3878092"],
            next_action="Inspect the abstract.",
        )

    async with Client(stdio_client(server), read_timeout_seconds=30) as client:
        resumed = await workspace(client, "read")
        assert [r["record_id"] for r in resumed["open_actions"]] == ["branch"]
        schemas = {t.name: t.input_schema for t in (await client.list_tools()).tools}
        for record in resumed["records"]:
            for suggestion in record["source_handoffs"]:
                Draft202012Validator(schemas[suggestion["tool"]]).validate(suggestion["arguments"])
        strategy = resumed["records"][0]["source_handoffs"][0]
        loaded = await client.call_tool(strategy["tool"], strategy["arguments"])
        assert not loaded.is_error and "offline pipeline" in str(loaded.content)
        await workspace(
            client,
            "record",
            activity="examine",
            record_id="abstract",
            parent_ids=["branch"],
            resolves=["branch"],
            source_refs=["pmid:3878092"],
            evidence_scope="abstract",
            note="This test fixture records the evidence scope.",
            next_action="Find the original passage.",
        )
        await workspace(
            client,
            "record",
            activity="explain",
            record_id="summary",
            parent_ids=["abstract"],
            note="Passage-level verification is still open.",
        )
        result = await workspace(client, "read")
        assert result["activity_counts"] == dict.fromkeys(("explore", "expand", "examine", "explain"), 1)
        assert [r["record_id"] for r in result["open_actions"]] == ["abstract"]
        assert all(r["verification_status"] == "unverified" for r in result["records"])
