"""Tests for Strategy MCP tools — generate_search_queries, expand_search_queries."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.presentation.mcp_server.tools.strategy import (
    register_strategy_tools,
)


def _capture_tools(mcp, searcher):
    tools = {}
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
    register_strategy_tools(mcp, searcher)
    return tools


@pytest.fixture
def setup():
    mcp = MagicMock()
    searcher = MagicMock()
    tools = _capture_tools(mcp, searcher)
    return tools, searcher


class TestGenerateSearchQueries:
    @pytest.mark.asyncio
    async def test_empty_topic(self, setup):
        tools, _ = setup
        result = await tools["generate_search_queries"](topic="")
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_with_strategy_generator(self, setup):
        tools, _ = setup
        mock_gen = AsyncMock()
        mock_gen.generate_strategies.return_value = {
            "topic": "remimazolam",
            "mesh_terms": [{"preferred": "remimazolam"}],
            "suggested_queries": [{"id": "q1", "query": "remimazolam[MeSH]"}],
        }
        with patch(
            "pubmed_search.presentation.mcp_server.tools.strategy.get_strategy_generator",
            return_value=mock_gen,
        ):
            result = await tools["generate_search_queries"](topic="remimazolam")
        parsed = json.loads(result)
        assert "_hint" in parsed
        assert "mesh_terms" in parsed

    @pytest.mark.asyncio
    async def test_fallback_no_generator(self, setup):
        tools, _ = setup
        with patch(
            "pubmed_search.presentation.mcp_server.tools.strategy.get_strategy_generator",
            return_value=None,
        ):
            result = await tools["generate_search_queries"](topic="propofol sedation")
        parsed = json.loads(result)
        assert parsed["topic"] == "propofol sedation"
        assert "fallback" in parsed.get("note", "").lower()
        assert len(parsed["suggested_queries"]) >= 3

    @pytest.mark.asyncio
    async def test_invalid_strategy_defaults(self, setup):
        tools, _ = setup
        with patch(
            "pubmed_search.presentation.mcp_server.tools.strategy.get_strategy_generator",
            return_value=None,
        ):
            result = await tools["generate_search_queries"](
                topic="test", strategy="invalid_strategy"
            )
        parsed = json.loads(result)
        assert parsed["strategy"] == "comprehensive"

    @pytest.mark.asyncio
    async def test_generator_exception_falls_back(self, setup):
        tools, _ = setup
        mock_gen = AsyncMock()
        mock_gen.generate_strategies.side_effect = RuntimeError("API failure")
        with patch(
            "pubmed_search.presentation.mcp_server.tools.strategy.get_strategy_generator",
            return_value=mock_gen,
        ):
            result = await tools["generate_search_queries"](topic="test")
        parsed = json.loads(result)
        # Should fall back to basic
        assert "suggested_queries" in parsed
        assert "fallback" in parsed.get("note", "").lower()

    @pytest.mark.asyncio
    async def test_single_word_topic(self, setup):
        tools, _ = setup
        with patch(
            "pubmed_search.presentation.mcp_server.tools.strategy.get_strategy_generator",
            return_value=None,
        ):
            result = await tools["generate_search_queries"](topic="diabetes")
        parsed = json.loads(result)
        # Single word: should have title, tiab, mesh but no AND query
        queries = parsed["suggested_queries"]
        ids = [q["id"] for q in queries]
        assert "q1_title" in ids
        assert "q4_mesh" in ids
