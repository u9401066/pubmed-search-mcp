"""The ``core`` tool profile publishes a small research surface and keeps it consistent."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from mcp.client import Client

from pubmed_search.presentation.mcp_server import create_server
from pubmed_search.presentation.mcp_server.instructions import CORE_SERVER_INSTRUCTIONS
from pubmed_search.presentation.mcp_server.tool_registry import TOOL_CATEGORIES, TOOL_PROFILES
from pubmed_search.presentation.mcp_server.tools.agent_output import finalize_next_tools, set_published_tools

if TYPE_CHECKING:
    from collections.abc import Iterator

CORE_TOOLS = TOOL_PROFILES["core"]
assert CORE_TOOLS is not None


@pytest.fixture
def core_profile(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PUBMED_TOOL_PROFILE", "core")
    yield
    set_published_tools(None)


def test_core_profile_names_only_canonical_tools() -> None:
    canonical = {tool for category in TOOL_CATEGORIES.values() for tool in category["tools"]}
    assert set(CORE_TOOLS) <= canonical
    assert len(CORE_TOOLS) == len(set(CORE_TOOLS))


async def test_core_profile_lists_only_core_tools_with_short_instructions(core_profile: None) -> None:
    async with Client(create_server()) as client:
        tools = await client.list_tools()
        assert sorted(tool.name for tool in tools.tools) == sorted(CORE_TOOLS)
        instructions = client.instructions
    assert instructions == CORE_SERVER_INSTRUCTIONS
    assert len(CORE_SERVER_INSTRUCTIONS) < 2_000
    for tool in CORE_TOOLS:
        assert tool in CORE_SERVER_INSTRUCTIONS


async def test_core_profile_rejects_hidden_tools(core_profile: None) -> None:
    async with Client(create_server()) as client:
        result = await client.call_tool("prepare_export", arguments={"pmids": "12345678"})
    assert result.is_error is True


def test_next_tools_never_point_outside_the_published_profile() -> None:
    suggestions = [
        {"tool": "prepare_export", "reason": "export", "command": 'prepare_export(pmids="1")'},
        {"tool": "find_related_articles", "reason": "expand", "command": 'find_related_articles(pmid="1")'},
    ]
    try:
        set_published_tools(frozenset(CORE_TOOLS))
        tools, commands = finalize_next_tools(suggestions)
    finally:
        set_published_tools(None)
    assert [tool["tool"] for tool in tools] == ["find_related_articles"]
    assert commands == ['find_related_articles(pmid="1")']

    full_tools, _ = finalize_next_tools(suggestions)
    assert [tool["tool"] for tool in full_tools] == ["prepare_export", "find_related_articles"]


async def test_full_profile_is_still_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PUBMED_TOOL_PROFILE", raising=False)
    async with Client(create_server()) as client:
        tools = await client.list_tools()
    canonical = {tool for category in TOOL_CATEGORIES.values() for tool in category["tools"]}
    assert {tool.name for tool in tools.tools} == canonical
