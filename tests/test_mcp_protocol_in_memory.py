"""In-memory MCP protocol tests against the real MCPServer instance."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp.client import Client

from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.infrastructure.sources import unified_broker
from pubmed_search.presentation.mcp_server import create_server
from pubmed_search.presentation.mcp_server.server import build_asgi_app
from pubmed_search.presentation.mcp_server.tenancy import build_tenancy_middleware
from pubmed_search.presentation.mcp_server.tool_contracts import MAX_MCP_TEXT_RESPONSE_CHARS, PubMedMCPServer
from pubmed_search.presentation.mcp_server.tool_registry import TOOL_CATEGORIES
from pubmed_search.presentation.mcp_server.tools import chronicle as chronicle_tools
from pubmed_search.presentation.mcp_server.tools import unified as unified_tools
from pubmed_search.shared.source_contracts import SourceAdapterResult
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
    async def _fake_search_pubmed_adapter(*args, **kwargs):
        del args, kwargs
        return SourceAdapterResult(
            source="pubmed",
            operation="search",
            items=[UnifiedArticle(title="Mock Article", primary_source="pubmed", pmid="12345")],
            total_count=1,
            metadata={
                "total_available": 1,
                "physical_query": "diabetes",
                "query_executed": True,
            },
        )

    monkeypatch.setattr(unified_broker, "_search_pubmed_adapter", _fake_search_pubmed_adapter)

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
    assert [tool.name for tool in tools if tool.annotations is None] == []
    assert [tool.name for tool in tools if not tool.meta] == []
    assert [tool.name for tool in tools if tool.output_schema is not None] == []

    by_name = {tool.name: tool for tool in tools}
    assert by_name["unified_search"].annotations.read_only_hint is False
    assert by_name["unified_search"].annotations.open_world_hint is True
    assert by_name["get_fulltext"].annotations.read_only_hint is False
    assert by_name["analyze_search_query"].annotations.open_world_hint is False
    assert by_name["validate_pico_plan"].annotations.open_world_hint is False
    assert by_name["list_resolver_presets"].annotations.open_world_hint is False
    assert by_name["schedule_pipeline"].annotations.open_world_hint is True
    assert by_name["read_session"].annotations.open_world_hint is False
    assert by_name["delete_pipeline"].annotations.destructive_hint is True
    assert by_name["delete_pipeline"].annotations.read_only_hint is False
    assert by_name["build_research_chronicle"].annotations.idempotent_hint is False
    assert by_name["save_pipeline"].annotations.idempotent_hint is False
    assert by_name["unified_search"].meta["pubmed-search"]["contractVersion"] == 3
    assert [tool.name for tool in tools if tool.input_schema.get("additionalProperties") is not False] == []


@pytest.mark.asyncio
async def test_unknown_tool_arguments_fail_closed():
    async with Client(create_server()) as client:
        result = await client.call_tool("analyze_search_query", {"query": "abc", "TYPO": "ignored-before"})

    assert result.is_error is True


@pytest.mark.asyncio
async def test_pipeline_identity_and_tags_are_strict_machine_readable_contracts():
    async with Client(create_server()) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        invalid_name = await client.call_tool(
            "save_pipeline",
            {"name": "My Pipeline", "config": "template: comprehensive", "tags": ["review"]},
        )
        csv_tags = await client.call_tool(
            "save_pipeline",
            {"name": "my_pipeline", "config": "template: comprehensive", "tags": "review,weekly"},
        )

    properties = tools["save_pipeline"].input_schema["properties"]
    assert properties["name"]["pattern"] == r"^[a-z0-9](?:[a-z0-9_-]{0,63})$"
    tag_array = next(branch for branch in properties["tags"]["anyOf"] if branch.get("type") == "array")
    assert tag_array["maxItems"] == 20
    assert tag_array["items"]["pattern"] == r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,63})$"
    assert invalid_name.is_error is True
    assert csv_tags.is_error is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments", "secret_marker"),
    [
        (
            "analyze_search_query",
            {"query": "abc", "TYPO": "schema-extra-secret-marker"},
            "schema-extra-secret-marker",
        ),
        (
            "analyze_search_query",
            {"query": ["wrong-scalar-secret-marker"]},
            "wrong-scalar-secret-marker",
        ),
        (
            "get_fulltext",
            {"source": {"kind": "pmid", "value": {"nested": "wrong-nested-secret-marker"}}},
            "wrong-nested-secret-marker",
        ),
    ],
)
async def test_argument_validation_does_not_expose_rejected_values(tool_name, arguments, secret_marker, caplog):
    async with Client(create_server()) as client:
        result = await client.call_tool(tool_name, arguments)

    rendered = " ".join(block.text for block in result.content if hasattr(block, "text"))
    assert result.is_error is True
    assert rendered.startswith("Invalid tool arguments.")
    assert "input_value" not in rendered
    assert secret_marker not in rendered
    assert secret_marker not in caplog.text


@pytest.mark.asyncio
async def test_formatted_service_failures_use_native_mcp_error_channel(monkeypatch):
    class BrokenAnalyzer:
        def analyze(self, _query):
            raise RuntimeError("private-upstream-sentinel")

    monkeypatch.setattr(unified_tools, "QueryAnalyzer", BrokenAnalyzer)
    async with Client(create_server()) as client:
        result = await client.call_tool("analyze_search_query", {"query": "abc"})

    rendered = " ".join(block.text for block in result.content if hasattr(block, "text"))
    assert result.is_error is True
    assert "private-upstream-sentinel" not in rendered


@pytest.mark.asyncio
async def test_global_execution_boundary_redacts_unhandled_exception_details(caplog):
    server = PubMedMCPServer("redaction-test")

    @server.tool(name="analyze_search_query")
    def unexpected_failure() -> str:
        raise RuntimeError("token=secret https://user:pass@example.test/private/path")

    async with Client(server) as client:
        result = await client.call_tool("analyze_search_query", {})

    rendered = " ".join(block.text for block in result.content if hasattr(block, "text"))
    assert result.is_error is True
    assert rendered == "Tool execution failed. Retry later or use a narrower request."
    assert "secret" not in rendered
    assert "example.test" not in rendered
    assert "/private/path" not in rendered
    assert "secret" not in caplog.text
    assert "example.test" not in caplog.text
    assert "/private/path" not in caplog.text


@pytest.mark.asyncio
async def test_global_transport_budget_rejects_oversized_tool_text():
    server = PubMedMCPServer("bounded-test")

    @server.tool(name="analyze_search_query")
    def oversized_result() -> str:
        return "x" * (MAX_MCP_TEXT_RESPONSE_CHARS + 1)

    async with Client(server) as client:
        result = await client.call_tool("analyze_search_query", {})

    rendered = " ".join(block.text for block in result.content if hasattr(block, "text"))
    assert result.is_error is True
    assert "transport budget" in rendered
    assert len(rendered) < 500


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("unified_search", {"query": "abc", "limit": "10"}),
        ("read_session", {"request": {"action": "summary", "include_history": "true"}}),
        ("build_research_chronicle", {"topic": "abc", "max_events": "10"}),
    ],
)
async def test_tool_arguments_do_not_coerce_schema_invalid_scalar_types(tool_name, arguments):
    async with Client(create_server()) as client:
        result = await client.call_tool(tool_name, arguments)

    assert result.is_error is True


@pytest.mark.asyncio
async def test_read_session_exposes_one_strict_discriminated_request():
    async with Client(create_server()) as client:
        tool = next(tool for tool in (await client.list_tools()).tools if tool.name == "read_session")
        unrelated_field = await client.call_tool(
            "read_session",
            {"request": {"action": "summary", "pmid": "12345"}},
        )
        missing_required_field = await client.call_tool(
            "read_session",
            {"request": {"action": "article"}},
        )
        flat_legacy_shape = await client.call_tool(
            "read_session",
            {"action": "summary"},
        )

    assert tool.input_schema.get("required") == ["request"]
    assert set(tool.input_schema.get("properties", {})) == {"request"}
    assert unrelated_field.is_error is True
    assert missing_required_field.is_error is True
    assert flat_legacy_shape.is_error is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("validate_pico_plan", {"description": "ICU sedation", "sources": '["pubmed"]'}),
        (
            "prepare_figure_search",
            {"source": '{"kind":"base64","data":"YWJj"}'},
        ),
    ],
)
async def test_tool_arguments_do_not_decode_stringified_arrays_or_objects(tool_name, arguments):
    async with Client(create_server()) as client:
        result = await client.call_tool(tool_name, arguments)

    assert result.is_error is True


@pytest.mark.asyncio
async def test_institutional_tools_require_exact_discriminated_sources():
    async with Client(create_server()) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        legacy_link = await client.call_tool("get_institutional_link", {"pmid": "12345"})
        wrong_link_kind = await client.call_tool(
            "get_institutional_link",
            {"source": {"kind": "pmcid", "value": "PMC12345"}},
        )
        legacy_diagnosis = await client.call_tool(
            "diagnose_institutional_access",
            {"doi": "10.1000/example"},
        )

    link_schema = tools["get_institutional_link"].input_schema
    diagnosis_schema = tools["diagnose_institutional_access"].input_schema
    assert link_schema["required"] == ["source"]
    assert diagnosis_schema["required"] == ["source"]
    assert set(link_schema["properties"]) == {"source"}
    assert set(diagnosis_schema["properties"]) == {"source", "try_direct", "try_ezproxy"}
    assert set(link_schema["properties"]["source"]["discriminator"]["mapping"]) == {
        "doi",
        "metadata",
        "pmid",
    }
    assert set(diagnosis_schema["properties"]["source"]["discriminator"]["mapping"]) == {
        "doi",
        "pmid",
    }
    assert legacy_link.is_error is True
    assert wrong_link_kind.is_error is True
    assert legacy_diagnosis.is_error is True


@pytest.mark.asyncio
async def test_unified_search_accepts_pipeline_without_query():
    async with Client(create_server()) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        result = await client.call_tool(
            "unified_search",
            {
                "pipeline": "template: comprehensive\ntemplate_params:\n  query: CRISPR gene therapy\n",
                "dry_run": True,
            },
        )

    assert "query" not in tools["unified_search"].input_schema.get("required", [])
    assert result.is_error is False


@pytest.mark.asyncio
async def test_consolidated_timeline_tools_stay_removed():
    """The chronicle tools replaced these; re-adding them would split the surface again."""
    async with Client(create_server()) as client:
        live = {tool.name for tool in (await client.list_tools()).tools}

    assert live.isdisjoint({"build_research_timeline", "compare_timelines", "analyze_timeline_milestones"})


@pytest.mark.asyncio
async def test_chronicle_read_is_reachable_over_the_protocol():
    async with Client(create_server()) as client:
        result = await client.call_tool(
            "read_research_chronicle",
            {"request": {"action": "list"}},
        )

    assert result.is_error is False


@pytest.mark.asyncio
async def test_chronicle_read_rejects_legacy_and_cross_action_arguments_over_protocol():
    async with Client(create_server()) as client:
        tool = next(tool for tool in (await client.list_tools()).tools if tool.name == "read_research_chronicle")
        flat_legacy = await client.call_tool(
            "read_research_chronicle",
            {"action": "list"},
        )
        unrelated_field = await client.call_tool(
            "read_research_chronicle",
            {"request": {"action": "list", "chronicle_id": "not-valid-for-list"}},
        )
        missing_diff_revision = await client.call_tool(
            "read_research_chronicle",
            {"request": {"action": "diff", "chronicle_id": "chronicle-1"}},
        )
        scalar_compare_values = await client.call_tool(
            "read_research_chronicle",
            {
                "request": {
                    "action": "compare",
                    "selection": {"kind": "topics", "values": "topic-a,topic-b"},
                }
            },
        )

    assert tool.input_schema["required"] == ["request"]
    assert set(tool.input_schema["properties"]) == {"request"}
    assert flat_legacy.is_error is True
    assert unrelated_field.is_error is True
    assert missing_diff_revision.is_error is True
    assert scalar_compare_values.is_error is True


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
                result = await client.call_tool(
                    "read_research_chronicle",
                    {"request": {"action": "list"}},
                )
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
    assert "PUBMED\\_AUTH\\_TOKENS" in refusal


@pytest.mark.parametrize("transport", ["streamable-http", "sse"])
def test_asgi_app_builds_for_each_http_transport(transport):
    app = build_asgi_app(create_server(), transport, host="127.0.0.1")
    assert app.routes


def test_asgi_app_rejects_an_unknown_transport():
    with pytest.raises(ValueError, match="transport"):
        build_asgi_app(create_server(), "carrier-pigeon")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        '{"status":"error","message":"Provider unavailable"}',
        "tool: x\nstatus: failed\nmessage: unavailable",
        "tool: x\nsuccess: false",
        "type: pipeline_result\nstatus: failed",
        '{"tool":"unified_search","search_status":{"state":"failed"}}',
    ],
)
async def test_encoded_json_error_is_native_mcp_error(payload):
    server = PubMedMCPServer("json-error-test")

    @server.tool(name="analyze_search_query")
    def failed_analysis() -> str:
        return payload

    async with Client(server) as client:
        result = await client.call_tool("analyze_search_query", {})
    assert result.is_error is True


@pytest.mark.asyncio
async def test_prompt_query_example_preserves_quotes_and_newlines(tmp_path):
    import ast
    import re

    topic = '"heart failure" AND therapy\nfollow-up'
    async with Client(create_server(data_dir=str(tmp_path))) as client:
        prompt = await client.get_prompt("quick_search", {"topic": topic})
    text = "\n".join(message.content.text for message in prompt.messages if hasattr(message.content, "text"))
    command = re.search(r"Call `(.*?)`", text, re.DOTALL).group(1)
    call = ast.parse(command, mode="eval").body
    assert ast.literal_eval(call.keywords[0].value) == topic
