"""Tests for tool_registry.py — pure functions + validation."""

import json
from unittest.mock import MagicMock, patch

import pytest

from pubmed_search.presentation.mcp_server.tool_registry import (
    TOOL_CATEGORIES,
    check_tool_registration,
    generate_tools_index_markdown,
    get_tool_info,
    get_tools_by_category,
    list_registered_tools,
    register_all_mcp_tools,
    validate_tool_registry,
)


# ============================================================
# list_registered_tools
# ============================================================

class TestListRegisteredTools:
    def test_returns_dict(self):
        result = list_registered_tools()
        assert isinstance(result, dict)

    def test_has_all_categories(self):
        result = list_registered_tools()
        for cat_id in TOOL_CATEGORIES:
            assert cat_id in result

    def test_tools_are_lists(self):
        result = list_registered_tools()
        for tools in result.values():
            assert isinstance(tools, list)

    def test_unified_search_in_search(self):
        result = list_registered_tools()
        assert "unified_search" in result["search"]

    def test_all_categories_present(self):
        result = list_registered_tools()
        expected = {"search", "query_intelligence", "discovery", "fulltext",
                    "ncbi_extended", "citation_network", "export", "session",
                    "institutional", "vision", "icd", "timeline",
                    "image_search"}
        assert set(result.keys()) == expected


# ============================================================
# get_tool_info
# ============================================================

class TestGetToolInfo:
    def test_existing_tool(self):
        info = get_tool_info("unified_search")
        assert info is not None
        assert info["name"] == "unified_search"
        assert info["category_id"] == "search"

    def test_discovery_tool(self):
        info = get_tool_info("fetch_article_details")
        assert info is not None
        assert info["category_id"] == "discovery"

    def test_nonexistent_tool(self):
        assert get_tool_info("nonexistent_tool_xyz") is None

    def test_returns_category_description(self):
        info = get_tool_info("parse_pico")
        assert isinstance(info["category_description"], str)
        assert len(info["category_description"]) > 0

    def test_each_defined_tool_findable(self):
        for cat_info in TOOL_CATEGORIES.values():
            for tool_name in cat_info["tools"]:
                info = get_tool_info(tool_name)
                assert info is not None, f"Tool {tool_name} not found"


# ============================================================
# get_tools_by_category
# ============================================================

class TestGetToolsByCategory:
    def test_valid_category(self):
        tools = get_tools_by_category("search")
        assert "unified_search" in tools

    def test_invalid_category(self):
        assert get_tools_by_category("nonexistent") == []

    def test_ncbi_extended_has_7_tools(self):
        tools = get_tools_by_category("ncbi_extended")
        assert len(tools) == 7

    def test_timeline_has_6_tools(self):
        tools = get_tools_by_category("timeline")
        assert len(tools) == 6


# ============================================================
# generate_tools_index_markdown
# ============================================================

class TestGenerateToolsIndexMarkdown:
    def test_returns_string(self):
        md = generate_tools_index_markdown()
        assert isinstance(md, str)

    def test_contains_header(self):
        md = generate_tools_index_markdown()
        assert "# PubMed Search MCP - Tools Index" in md

    def test_contains_all_categories(self):
        md = generate_tools_index_markdown()
        for cat_info in TOOL_CATEGORIES.values():
            assert cat_info["name"] in md

    def test_contains_table_format(self):
        md = generate_tools_index_markdown()
        assert "| Tool |" in md
        assert "|------|" in md

    def test_contains_tool_names(self):
        md = generate_tools_index_markdown()
        assert "`unified_search`" in md
        assert "`parse_pico`" in md


# ============================================================
# validate_tool_registry
# ============================================================

class TestValidateToolRegistry:
    def test_all_tools_registered(self):
        mcp = MagicMock()
        # Simulate all defined tools being registered
        all_tools = set()
        for cat_info in TOOL_CATEGORIES.values():
            all_tools.update(cat_info["tools"])
        mcp._tool_manager._tools.keys.return_value = all_tools

        result = validate_tool_registry(mcp)
        assert result["valid"] is True
        assert result["missing"] == []
        assert result["extra"] == []

    def test_missing_tools(self):
        mcp = MagicMock()
        mcp._tool_manager._tools.keys.return_value = {"unified_search"}

        result = validate_tool_registry(mcp)
        assert result["valid"] is False
        assert len(result["missing"]) > 0

    def test_extra_tools(self):
        mcp = MagicMock()
        all_tools = set()
        for cat_info in TOOL_CATEGORIES.values():
            all_tools.update(cat_info["tools"])
        all_tools.add("extra_undocumented_tool")
        mcp._tool_manager._tools.keys.return_value = all_tools

        result = validate_tool_registry(mcp)
        assert result["valid"] is False
        assert "extra_undocumented_tool" in result["extra"]

    def test_cannot_access_tools(self):
        mcp = MagicMock(spec=[])
        # No _tool_manager attribute at all → triggers AttributeError
        result = validate_tool_registry(mcp)
        assert result["valid"] is False
        assert "error" in result


# ============================================================
# check_tool_registration
# ============================================================

class TestCheckToolRegistration:
    def test_valid(self):
        mcp = MagicMock()
        all_tools = set()
        for cat_info in TOOL_CATEGORIES.values():
            all_tools.update(cat_info["tools"])
        mcp._tool_manager._tools.keys.return_value = all_tools

        assert check_tool_registration(mcp) is True

    def test_invalid_no_raise(self):
        mcp = MagicMock()
        mcp._tool_manager._tools.keys.return_value = set()

        assert check_tool_registration(mcp) is False

    def test_invalid_raise(self):
        mcp = MagicMock()
        mcp._tool_manager._tools.keys.return_value = set()

        with pytest.raises(RuntimeError):
            check_tool_registration(mcp, raise_on_error=True)


# ============================================================
# register_all_mcp_tools
# ============================================================

class TestRegisterAllMcpTools:
    def test_calls_all_register_functions(self):
        """Test that register_all_mcp_tools wires everything together."""
        import pubmed_search.presentation.mcp_server.tool_registry as reg_mod

        mcp = MagicMock()
        searcher = MagicMock()
        sm = MagicMock()
        sg = MagicMock()

        with patch.object(reg_mod, '__name__', reg_mod.__name__):  # Keep module identity
            with patch(
                "pubmed_search.presentation.mcp_server.resources.register_resources"
            ) as mock_res, patch(
                "pubmed_search.presentation.mcp_server.session_tools.register_session_resources"
            ) as mock_sres, patch(
                "pubmed_search.presentation.mcp_server.session_tools.register_session_tools"
            ) as mock_stools, patch(
                "pubmed_search.presentation.mcp_server.tools.register_all_tools"
            ) as mock_all, patch(
                "pubmed_search.presentation.mcp_server.tools.set_session_manager"
            ) as mock_set_sm, patch(
                "pubmed_search.presentation.mcp_server.tools.set_strategy_generator"
            ) as mock_set_sg, patch(
                "pubmed_search.presentation.mcp_server.prompts.register_prompts"
            ) as mock_prompts:
                stats = register_all_mcp_tools(mcp, searcher, sm, sg)

            mock_set_sm.assert_called_once_with(sm)
            mock_set_sg.assert_called_once_with(sg)
            mock_all.assert_called_once_with(mcp, searcher)
            assert isinstance(stats, dict)

    def test_no_strategy_generator(self):
        """Test that strategy_generator=None skips set_strategy_generator."""
        mcp = MagicMock()
        searcher = MagicMock()
        sm = MagicMock()

        with patch(
            "pubmed_search.presentation.mcp_server.resources.register_resources"
        ), patch(
            "pubmed_search.presentation.mcp_server.session_tools.register_session_resources"
        ), patch(
            "pubmed_search.presentation.mcp_server.session_tools.register_session_tools"
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.register_all_tools"
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.set_session_manager"
        ), patch(
            "pubmed_search.presentation.mcp_server.tools.set_strategy_generator"
        ) as mock_set_sg, patch(
            "pubmed_search.presentation.mcp_server.prompts.register_prompts"
        ):
            register_all_mcp_tools(mcp, searcher, sm, strategy_generator=None)
            mock_set_sg.assert_not_called()
