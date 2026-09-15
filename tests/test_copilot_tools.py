"""Tests for shared MCP response and direct-helper utilities."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from pubmed_search.presentation.mcp_server.tools._common import ResponseFormatter


class TestResponseFormatterSuccess:
    async def test_success_markdown(self):
        result = ResponseFormatter.success("Test data", message="Done")
        assert "✅" in result
        assert "Done" in result
        assert "Test data" in result

    async def test_success_json_with_metadata(self):
        result = ResponseFormatter.success(
            {"key": "value"},
            message="Done",
            metadata={"count": 10},
            output_format="json",
        )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["data"]["key"] == "value"
        assert parsed["message"] == "Done"
        assert parsed["metadata"]["count"] == 10


class TestResponseFormatterError:
    async def test_error_markdown(self):
        result = ResponseFormatter.error("Something went wrong", suggestion="Try again", tool_name="test_tool")
        assert "❌" in result
        assert "test\\_tool" in result
        assert "Something went wrong" in result
        assert "Try again" in result

    async def test_error_with_example(self):
        result = ResponseFormatter.error("Invalid input", example="tool(param='value')")
        assert "📝" in result
        assert "tool(param='value')" in result

    async def test_error_json(self):
        result = ResponseFormatter.error("Error message", suggestion="Fix it", output_format="json")
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "Error message"
        assert parsed["suggestion"] == "Fix it"


class TestResponseFormatterNoResults:
    async def test_no_results_with_context(self):
        result = ResponseFormatter.no_results(
            query="test query",
            suggestions=["Try broader terms"],
            alternative_tools=["unified_search"],
        )
        assert "No results found" in result
        assert "test query" in result
        assert "Try broader terms" in result
        assert "unified_search" in result


class TestResponseFormatterPartialSuccess:
    async def test_partial_success_basic(self):
        result = ResponseFormatter.partial_success(successful=[1, 2, 3], failed=[{"id": "x", "error": "failed"}])
        assert "3 succeeded" in result
        assert "1 failed" in result

    async def test_partial_success_truncates_failure_list(self):
        failed = [{"id": str(index), "error": f"error {index}"} for index in range(10)]
        result = ResponseFormatter.partial_success(successful=[], failed=failed, message="Custom message")
        assert "Custom message" in result
        assert "and 5 more" in result


class TestCommonFunctions:
    async def test_set_get_session_manager(self):
        from pubmed_search.presentation.mcp_server.tools._common import get_session_manager, set_session_manager

        mock_manager = MagicMock()
        set_session_manager(mock_manager)
        assert get_session_manager() is mock_manager
        set_session_manager(None)

    async def test_set_get_strategy_generator(self):
        from pubmed_search.presentation.mcp_server.tools._common import get_strategy_generator, set_strategy_generator

        mock_gen = MagicMock()
        set_strategy_generator(mock_gen)
        assert get_strategy_generator() is mock_gen
        set_strategy_generator(None)

    async def test_format_search_results_empty(self):
        from pubmed_search.presentation.mcp_server.tools._common import format_search_results

        assert "No results found" in format_search_results([])

    async def test_format_search_results_does_not_surface_unknown_mapping_values(self):
        from pubmed_search.presentation.mcp_server.tools._common import format_search_results

        assert "API failed" not in format_search_results([{"unexpected_payload": "API failed"}])

    async def test_format_search_results_normal(self):
        from pubmed_search.presentation.mcp_server.tools._common import format_search_results

        result = format_search_results(
            [
                {
                    "title": "Test Article",
                    "authors": ["Smith J", "Doe J"],
                    "journal": "Nature",
                    "year": "2024",
                    "pmid": "12345678",
                    "doi": "10.1234/test",
                    "abstract": "This is a test abstract " * 20,
                }
            ]
        )
        assert "Test Article" in result
        assert "Smith J" in result
        assert "Nature" in result
        assert "12345678" in result

    async def test_session_helpers_without_manager(self):
        from pubmed_search.presentation.mcp_server.tools._common import (
            check_cache,
            get_last_search_pmids,
            set_session_manager,
        )

        set_session_manager(None)
        assert get_last_search_pmids() == []
        assert check_cache("test query") is None


def test_response_retains_immediate_retry_and_zero_suggestion_budget():
    from pubmed_search.presentation.mcp_server.tools.agent_output import finalize_next_tools
    from pubmed_search.shared.exceptions import RateLimitError

    payload = json.loads(ResponseFormatter.error(RateLimitError(retry_after=0), output_format="json"))
    assert payload["retry_after"] == 0
    assert finalize_next_tools(
        [{"tool": "unified_search", "command": "unified_search(query='test')"}], max_items=0
    ) == ([], [])
