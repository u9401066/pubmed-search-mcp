"""In-memory MCP protocol tests against the real FastMCP server."""

from __future__ import annotations

import anyio
import pytest
from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session

from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.presentation.mcp_server import create_server
from pubmed_search.presentation.mcp_server.tools import unified as unified_module


@pytest.mark.asyncio
async def test_in_memory_protocol_lists_tools_resources_and_prompts():
    async with create_connected_server_and_client_session(create_server()) as session:
        tool_result = await session.list_tools()
        unified_tool = next(tool for tool in tool_result.tools if tool.name == "unified_search")

        assert unified_tool.execution is not None
        assert unified_tool.execution.taskSupport == "optional"
        assert unified_tool.meta["pubmedSearch"]["experimentalTaskSupport"] == "optional"

        analyze_result = await session.call_tool(
            "analyze_search_query",
            arguments={"query": "remimazolam ICU sedation"},
        )
        assert analyze_result.isError is False
        assert any("Query Analysis" in block.text for block in analyze_result.content if hasattr(block, "text"))

        resources_result = await session.list_resources()
        age_group_resource = next(
            resource for resource in resources_result.resources if str(resource.uri) == "pubmed://filters/age_group"
        )
        session_resource = next(
            resource for resource in resources_result.resources if str(resource.uri) == "session://last-search"
        )

        assert age_group_resource.title == "Age Group Filters"
        assert age_group_resource.mimeType == "application/json"
        assert age_group_resource.meta["pubmedSearch"]["category"] == "filters"
        assert session_resource.meta["pubmedSearch"]["dynamic"] is True

        read_result = await session.read_resource("pubmed://filters/age_group")
        assert read_result.contents[0].mimeType == "application/json"
        assert "newborn" in read_result.contents[0].text

        prompt_result = await session.list_prompts()
        assert any(prompt.name == "quick_search" for prompt in prompt_result.prompts)

        quick_search_prompt = await session.get_prompt("quick_search", {"topic": "remimazolam"})
        assert any(
            "unified_search" in message.content.text
            for message in quick_search_prompt.messages
            if hasattr(message.content, "text")
        )


@pytest.mark.asyncio
async def test_unified_search_supports_task_augmented_execution(monkeypatch):
    async def _fake_search_pubmed(*args, **kwargs):
        del args, kwargs
        return ([UnifiedArticle(title="Mock Article", primary_source="pubmed", pmid="12345")], 1)

    monkeypatch.setattr(unified_module, "_search_pubmed", _fake_search_pubmed)

    async with create_connected_server_and_client_session(create_server()) as session:
        create_task_result = await session.send_request(
            types.ClientRequest(
                types.CallToolRequest(
                    params=types.CallToolRequestParams(
                        name="unified_search",
                        arguments={"query": "diabetes", "limit": 1},
                        task=types.TaskMetadata(ttl=60000),
                    )
                )
            ),
            types.CreateTaskResult,
        )

        assert create_task_result.task.taskId
        assert create_task_result.meta is not None
        assert any("model-immediate-response" in key for key in create_task_result.meta)

        task_state = None
        for _ in range(50):
            task_state = await session.send_request(
                types.ClientRequest(
                    types.GetTaskRequest(
                        params=types.GetTaskRequestParams(taskId=create_task_result.task.taskId)
                    )
                ),
                types.GetTaskResult,
            )
            if task_state.status == "completed":
                break
            await anyio.sleep(0.02)

        assert task_state is not None
        assert task_state.status == "completed"

        task_payload = await session.send_request(
            types.ClientRequest(
                types.GetTaskPayloadRequest(
                    params=types.GetTaskPayloadRequestParams(taskId=create_task_result.task.taskId)
                )
            ),
            types.CallToolResult,
        )
        assert task_payload.isError is False
        assert any("Mock Article" in block.text for block in task_payload.content if hasattr(block, "text"))

        session_resource = await session.read_resource("session://last-search")
        assert "diabetes" in session_resource.contents[0].text
