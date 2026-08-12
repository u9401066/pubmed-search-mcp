"""In-memory MCP protocol tests against the real MCPServer instance."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp.client import Client

from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.presentation.mcp_server import create_server
from pubmed_search.presentation.mcp_server.server import build_asgi_app
from pubmed_search.presentation.mcp_server.tenancy import build_tenancy_middleware
from pubmed_search.presentation.mcp_server.tool_registry import TOOL_CATEGORIES
from pubmed_search.presentation.mcp_server.tools import chronicle as chronicle_tools
from pubmed_search.presentation.mcp_server.tools import unified as unified_module
from pubmed_search.shared.tenancy import TenantIdentity, bind_tenant, current_tenant


@pytest.mark.asyncio
async def test_in_memory_protocol_lists_tools_resources_and_prompts():
    async with Client(create_server()) as client:
        tool_result = await client.list_tools()
        unified_tool = next(tool for tool in tool_result.tools if tool.name == "unified_search")
        assert unified_tool.description
        assert "experimentalTaskSupport" not in str(unified_tool.meta or {})

        analyze_result = await client.call_tool(
            "analyze_search_query",
            arguments={"query": "remimazolam ICU sedation"},
        )
        assert analyze_result.is_error is False
        assert any("Query Analysis" in block.text for block in analyze_result.content if hasattr(block, "text"))

        resources_result = await client.list_resources()
        age_group_resource = next(
            resource for resource in resources_result.resources if str(resource.uri) == "pubmed://filters/age_group"
        )
        session_resource = next(
            resource for resource in resources_result.resources if str(resource.uri) == "session://last-search"
        )

        assert age_group_resource.title == "Age Group Filters"
        assert age_group_resource.mime_type == "application/json"
        assert age_group_resource.meta["pubmedSearch"]["category"] == "filters"
        assert session_resource.meta["pubmedSearch"]["dynamic"] is True

        read_result = await client.read_resource("pubmed://filters/age_group")
        assert read_result.contents[0].mime_type == "application/json"
        assert "newborn" in read_result.contents[0].text

        prompt_result = await client.list_prompts()
        assert any(prompt.name == "quick_search" for prompt in prompt_result.prompts)

        quick_search_prompt = await client.get_prompt("quick_search", {"topic": "remimazolam"})
        assert any(
            "unified_search" in message.content.text
            for message in quick_search_prompt.messages
            if hasattr(message.content, "text")
        )


@pytest.mark.asyncio
async def test_unified_search_reports_progress_and_persists_session(monkeypatch):
    async def _fake_search_pubmed(*args, **kwargs):
        del args, kwargs
        return ([UnifiedArticle(title="Mock Article", primary_source="pubmed", pmid="12345")], 1)

    monkeypatch.setattr(unified_module, "_search_pubmed", _fake_search_pubmed)

    progress_updates: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        progress_updates.append((progress, total, message))

    async with Client(create_server()) as client:
        result = await client.call_tool(
            "unified_search",
            {"query": "diabetes", "limit": 1},
            progress_callback=on_progress,
        )

        assert result.is_error is False
        assert any("Mock Article" in block.text for block in result.content if hasattr(block, "text"))
        assert progress_updates, "unified_search should emit MCP progress updates"

        session_resource = await client.read_resource("session://last-search")
        assert "diabetes" in session_resource.contents[0].text


@pytest.mark.asyncio
async def test_registered_tools_match_the_declared_registry():
    """Catch a whole category silently failing to register, in either direction."""
    declared = {name for category in TOOL_CATEGORIES.values() for name in category["tools"]}

    async with Client(create_server()) as client:
        live = {tool.name for tool in (await client.list_tools()).tools}

    assert live - declared == set(), "tool registered but missing from TOOL_CATEGORIES"
    assert declared - live == set(), "tool declared in TOOL_CATEGORIES but never registered"


@pytest.mark.asyncio
async def test_every_tool_exposes_a_usable_contract():
    async with Client(create_server()) as client:
        tools = (await client.list_tools()).tools

    assert [tool.name for tool in tools if not tool.description] == []
    assert [tool.name for tool in tools if not tool.input_schema] == []


@pytest.mark.asyncio
async def test_consolidated_timeline_tools_stay_removed():
    """The chronicle tools replaced these; re-adding them would split the surface again."""
    async with Client(create_server()) as client:
        live = {tool.name for tool in (await client.list_tools()).tools}

    assert live.isdisjoint({"build_research_timeline", "compare_timelines", "analyze_timeline_milestones"})


@pytest.mark.asyncio
async def test_chronicle_read_is_reachable_over_the_protocol():
    async with Client(create_server()) as client:
        result = await client.call_tool("read_research_chronicle", {"action": "list"})

    assert result.is_error is False


@pytest.mark.asyncio
async def test_in_memory_caller_is_the_default_tenant_and_may_persist():
    """stdio and in-memory callers are one local user, so nothing should be withheld."""
    seen: list[str] = []
    original = chronicle_tools.durable_storage_denied

    def record(tool_name: str, *, output_format: str = "markdown") -> str | None:
        seen.append(current_tenant().source)
        return original(tool_name, output_format=output_format)

    chronicle_tools.durable_storage_denied = record
    try:
        async with Client(create_server()) as client:
            with bind_tenant(TenantIdentity.for_principal("sess-1", source="transport")):
                result = await client.call_tool("read_research_chronicle", {"action": "list"})
    finally:
        chronicle_tools.durable_storage_denied = original

    assert seen == ["stdio"], "middleware must rebind each request, not inherit the caller's context"
    assert result.is_error is False


@pytest.mark.asyncio
async def test_transport_session_caller_is_refused_through_the_middleware():
    """The header -> tenant -> guard chain must actually withhold durable writes."""
    middleware = build_tenancy_middleware(isolation_enabled=True, max_concurrency=0)
    request = SimpleNamespace(headers={"mcp-session-id": "sess-1"})
    ctx = SimpleNamespace(method="tools/call", request=request, request_context=SimpleNamespace(request=request))

    async def call_next(_ctx: object) -> str | None:
        return chronicle_tools.durable_storage_denied("build_research_chronicle")

    refusal = await middleware(ctx, call_next)

    assert refusal is not None
    assert "PUBMED_AUTH_TOKENS" in refusal


@pytest.mark.parametrize("transport", ["streamable-http", "sse"])
def test_asgi_app_builds_for_each_http_transport(transport):
    app = build_asgi_app(create_server(), transport, host="127.0.0.1")
    assert app.routes


def test_asgi_app_rejects_an_unknown_transport():
    with pytest.raises(ValueError, match="transport"):
        build_asgi_app(create_server(), "carrier-pigeon")
