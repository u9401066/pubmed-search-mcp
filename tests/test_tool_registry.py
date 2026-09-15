"""Tests for tool_registry.py — pure functions + validation."""

from __future__ import annotations

from types import SimpleNamespace
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


def _fake_tools(names: set[str] | list[str]) -> list[SimpleNamespace]:
    """Build simple tool-like objects exposing a public ``name`` attribute."""
    return [SimpleNamespace(name=name) for name in names]


# ============================================================
# list_registered_tools
# ============================================================


class TestListRegisteredTools:
    async def test_returned_lists_cannot_mutate_canonical_registry(self):
        result = list_registered_tools()
        result["search"].append("not_a_real_tool")

        assert TOOL_CATEGORIES["search"]["tools"] == ["unified_search"]
        assert "not_a_real_tool" not in get_tools_by_category("search")

    async def test_unified_search_is_the_only_generic_literature_search_tool(self):
        """Provider adapters and entity lookups must not expand the search facade."""
        result = list_registered_tools()

        assert result["search"] == ["unified_search"]

    async def test_legacy_merge_tool_is_not_primary_surface(self):
        result = list_registered_tools()
        all_tools = {tool for tools in result.values() for tool in tools}
        assert "merge_search_results" not in all_tools

    async def test_all_categories_present(self):
        result = list_registered_tools()
        expected = {
            "search",
            "query_intelligence",
            "discovery",
            "reference_verification",
            "fulltext",
            "figure",
            "ncbi_extended",
            "citation_network",
            "export",
            "session",
            "institutional",
            "vision",
            "icd",
            "chronicle",
            "image_search",
            "pipeline",
        }
        assert set(result.keys()) == expected


# ============================================================
# get_tool_info
# ============================================================


class TestGetToolInfo:
    async def test_existing_tool(self):
        info = get_tool_info("unified_search")
        assert info is not None
        assert info["name"] == "unified_search"
        assert info["category_id"] == "search"

    async def test_discovery_tool(self):
        info = get_tool_info("fetch_article_details")
        assert info is not None
        assert info["category_id"] == "discovery"

    async def test_nonexistent_tool(self):
        assert get_tool_info("nonexistent_tool_xyz") is None

    async def test_returns_category_description(self):
        info = get_tool_info("validate_pico_plan")
        assert isinstance(info["category_description"], str)
        assert len(info["category_description"]) > 0

    async def test_each_defined_tool_findable(self):
        for cat_info in TOOL_CATEGORIES.values():
            for tool_name in cat_info["tools"]:
                info = get_tool_info(tool_name)
                assert info is not None, f"Tool {tool_name} not found"


# ============================================================
# get_tools_by_category
# ============================================================


class TestGetToolsByCategory:
    async def test_valid_category(self):
        tools = get_tools_by_category("search")
        assert "unified_search" in tools

    async def test_invalid_category(self):
        assert get_tools_by_category("nonexistent") == []

    async def test_ncbi_extended_has_7_tools(self):
        tools = get_tools_by_category("ncbi_extended")
        assert len(tools) == 7

    async def test_chronicle_has_2_tools(self):
        tools = get_tools_by_category("chronicle")
        assert len(tools) == 2


# ============================================================
# generate_tools_index_markdown
# ============================================================


class TestGenerateToolsIndexMarkdown:
    async def test_returns_string(self):
        md = generate_tools_index_markdown()
        assert isinstance(md, str)

    async def test_contains_header(self):
        md = generate_tools_index_markdown()
        assert "# PubMed Search MCP - Tools Index" in md

    async def test_contains_all_categories(self):
        md = generate_tools_index_markdown()
        for cat_info in TOOL_CATEGORIES.values():
            assert cat_info["name"] in md

    async def test_contains_table_format(self):
        md = generate_tools_index_markdown()
        assert "| Tool |" in md
        assert "|------|" in md

    async def test_contains_tool_names(self):
        md = generate_tools_index_markdown()
        assert "`unified_search`" in md
        assert "`validate_pico_plan`" in md


# ============================================================
# validate_tool_registry
# ============================================================


class TestValidateToolRegistry:
    async def test_all_tools_registered(self):
        mcp = MagicMock()
        # Simulate all defined tools being registered
        all_tools = set()
        for cat_info in TOOL_CATEGORIES.values():
            all_tools.update(cat_info["tools"])
        mcp.list_tools.return_value = _fake_tools(all_tools)

        result = validate_tool_registry(mcp)
        assert result["valid"] is True
        assert result["missing"] == []
        assert result["extra"] == []
        assert result["duplicate_definitions"] == []

    async def test_duplicate_category_assignment_is_invalid(self, monkeypatch):
        all_tools = {tool for category in TOOL_CATEGORIES.values() for tool in category["tools"]}
        monkeypatch.setitem(
            TOOL_CATEGORIES,
            "duplicate_test",
            {"name": "Duplicate", "description": "invalid test fixture", "tools": ["unified_search"]},
        )
        mcp = MagicMock()
        mcp.list_tools.return_value = _fake_tools(all_tools)

        result = validate_tool_registry(mcp)

        assert result["valid"] is False
        assert result["duplicate_definitions"] == ["unified_search"]

    async def test_missing_tools(self):
        mcp = MagicMock()
        mcp.list_tools.return_value = _fake_tools(["unified_search"])

        result = validate_tool_registry(mcp)
        assert result["valid"] is False
        assert len(result["missing"]) > 0

    async def test_extra_tools(self):
        mcp = MagicMock()
        all_tools = set()
        for cat_info in TOOL_CATEGORIES.values():
            all_tools.update(cat_info["tools"])
        all_tools.add("extra_undocumented_tool")
        mcp.list_tools.return_value = _fake_tools(all_tools)

        result = validate_tool_registry(mcp)
        assert result["valid"] is False
        assert "extra_undocumented_tool" in result["extra"]

    async def test_awaitable_list_tools(self):
        mcp = MagicMock()

        async def _list_tools():
            return _fake_tools({"unified_search"})

        mcp.list_tools.side_effect = _list_tools
        mcp._tool_manager._tools.keys.return_value = {"unified_search"}

        result = validate_tool_registry(mcp)
        assert "unified_search" in result["registered"]

    async def test_cannot_access_tools(self):
        mcp = MagicMock(spec=[])
        # No public/private tool registry access at all → triggers AttributeError
        result = validate_tool_registry(mcp)
        assert result["valid"] is False
        assert "error" in result

    async def test_private_registry_is_not_used_as_a_production_fallback(self):
        mcp = MagicMock()
        del mcp.list_tools
        mcp._tool_manager._tools.keys.return_value = {"unified_search"}

        result = validate_tool_registry(mcp)
        assert result["valid"] is False
        assert result["registered"] == []
        assert "public API" in result["error"]

    async def test_runtime_registration_matches_tool_registry(self):
        from mcp.server.mcpserver import MCPServer

        from pubmed_search.infrastructure.ncbi import LiteratureSearcher
        from pubmed_search.presentation.mcp_server.session_tools import register_session_tools
        from pubmed_search.presentation.mcp_server.tools import register_all_tools
        from pubmed_search.presentation.mcp_server.tools.pipeline_tools import PipelineToolRuntime

        mcp = MCPServer(name="registry-sync-test")
        searcher = LiteratureSearcher(email="test@example.com")
        session_manager = MagicMock()

        register_all_tools(
            mcp,
            searcher,
            image_search_service=MagicMock(),
            pipeline_runtime=PipelineToolRuntime(base_store=None),
        )
        register_session_tools(mcp, session_manager)
        result = validate_tool_registry(mcp)

        assert result["valid"] is True
        assert "merge_search_results" not in result["registered"]
        assert set(TOOL_CATEGORIES["search"]["tools"]) == {"unified_search"}

    async def test_retired_profiling_env_cannot_expand_public_surface(self, monkeypatch, tmp_path):
        from pubmed_search.presentation.mcp_server.server import create_server

        monkeypatch.setenv("PUBMED_PROFILING", "1")
        mcp = create_server(email="test@example.com", data_dir=str(tmp_path))

        registered = {tool.name for tool in await mcp.list_tools()}
        declared = {name for category in TOOL_CATEGORIES.values() for name in category["tools"]}

        assert registered == declared
        assert len(registered) == 41
        assert "get_performance_metrics" not in registered


# ============================================================
# check_tool_registration
# ============================================================


class TestCheckToolRegistration:
    async def test_valid(self):
        mcp = MagicMock()
        all_tools = set()
        for cat_info in TOOL_CATEGORIES.values():
            all_tools.update(cat_info["tools"])
        mcp.list_tools.return_value = _fake_tools(all_tools)

        assert check_tool_registration(mcp) is True

    async def test_invalid_no_raise(self):
        mcp = MagicMock()
        mcp.list_tools.return_value = []

        assert check_tool_registration(mcp) is False

    async def test_invalid_raise(self):
        mcp = MagicMock()
        mcp.list_tools.return_value = []

        with pytest.raises(RuntimeError):
            check_tool_registration(mcp, raise_on_error=True)


# ============================================================
# register_all_mcp_tools
# ============================================================


class TestRegisterAllMcpTools:
    async def test_calls_all_register_functions(self):
        """Test that register_all_mcp_tools wires everything together."""
        import pubmed_search.presentation.mcp_server.tool_registry as reg_mod

        mcp = MagicMock()
        searcher = MagicMock()
        sm = MagicMock()
        sg = MagicMock()
        session_registry = MagicMock()
        pipeline_runtime = MagicMock()
        image_search_service = MagicMock()
        source_runtime = MagicMock()
        registered_names = {tool for category in TOOL_CATEGORIES.values() for tool in category["tools"]}
        mcp.list_tools.return_value = _fake_tools(registered_names)

        with patch.object(reg_mod, "__name__", reg_mod.__name__):  # Keep module identity
            with (
                patch("pubmed_search.presentation.mcp_server.resources.register_resources") as _mock_res,
                patch("pubmed_search.presentation.mcp_server.session_tools.register_session_resources") as _mock_sres,
                patch("pubmed_search.presentation.mcp_server.session_tools.register_session_tools") as _mock_stools,
                patch("pubmed_search.presentation.mcp_server.tools.register_all_tools") as mock_all,
                patch("pubmed_search.presentation.mcp_server.prompts.register_prompts") as _mock_prompts,
                patch.object(
                    reg_mod,
                    "_build_image_search_service",
                    return_value=image_search_service,
                ) as mock_build_image_search,
                patch.object(
                    reg_mod,
                    "build_pipeline_runtime",
                    return_value=pipeline_runtime,
                ) as mock_build_runtime,
            ):
                stats = register_all_mcp_tools(
                    mcp,
                    searcher,
                    sm,
                    pipeline_runtime=pipeline_runtime,
                    source_runtime=source_runtime,
                    strategy_generator=sg,
                    session_registry=session_registry,
                )

            installed_runtime = mcp.install_tool_session_runtime.call_args.args[0]
            assert installed_runtime.session_manager is sm
            assert installed_runtime.session_registry is session_registry
            assert installed_runtime.strategy_generator is sg
            assert installed_runtime.source_runtime is source_runtime
            mock_build_image_search.assert_called_once_with(source_runtime=source_runtime)
            mock_all.assert_called_once_with(
                mcp,
                searcher,
                image_search_service=image_search_service,
                pipeline_runtime=pipeline_runtime,
            )
            _mock_stools.assert_called_once_with(mcp, sm, session_registry=session_registry)
            _mock_sres.assert_called_once_with(mcp, sm, session_registry=session_registry)
            mock_build_runtime.assert_not_called()
            assert stats == {
                **{category_id: len(category["tools"]) for category_id, category in TOOL_CATEGORIES.items()},
                "total_tools": len(registered_names),
            }

    async def test_no_strategy_generator(self):
        """Test that strategy_generator=None skips set_strategy_generator."""
        mcp = MagicMock()
        searcher = MagicMock()
        sm = MagicMock()
        registered_names = {tool for category in TOOL_CATEGORIES.values() for tool in category["tools"]}
        mcp.list_tools.return_value = _fake_tools(registered_names)

        with (
            patch("pubmed_search.presentation.mcp_server.resources.register_resources"),
            patch("pubmed_search.presentation.mcp_server.session_tools.register_session_resources"),
            patch("pubmed_search.presentation.mcp_server.session_tools.register_session_tools"),
            patch("pubmed_search.presentation.mcp_server.tools.register_all_tools"),
            patch("pubmed_search.presentation.mcp_server.prompts.register_prompts"),
            patch(
                "pubmed_search.presentation.mcp_server.tool_registry.build_pipeline_runtime",
                return_value=MagicMock(),
            ),
        ):
            register_all_mcp_tools(
                mcp,
                searcher,
                sm,
                pipeline_runtime=MagicMock(),
                source_runtime=MagicMock(),
                strategy_generator=None,
            )
            installed_runtime = mcp.install_tool_session_runtime.call_args.args[0]
            assert installed_runtime.session_manager is sm
            assert installed_runtime.strategy_generator is None

    async def test_registration_fails_closed_when_runtime_registry_drifts(self):
        mcp = MagicMock()
        mcp.list_tools.return_value = _fake_tools({"unified_search"})

        with (
            patch("pubmed_search.presentation.mcp_server.resources.register_resources"),
            patch("pubmed_search.presentation.mcp_server.session_tools.register_session_resources"),
            patch("pubmed_search.presentation.mcp_server.session_tools.register_session_tools"),
            patch("pubmed_search.presentation.mcp_server.tools.register_all_tools"),
            patch("pubmed_search.presentation.mcp_server.prompts.register_prompts"),
            patch(
                "pubmed_search.presentation.mcp_server.tool_registry.build_pipeline_runtime",
                return_value=MagicMock(),
            ),
            pytest.raises(RuntimeError, match="Canonical MCP tool registry mismatch"),
        ):
            register_all_mcp_tools(
                mcp,
                MagicMock(),
                MagicMock(),
                pipeline_runtime=MagicMock(),
                source_runtime=MagicMock(),
            )

    def test_registration_requires_explicit_runtime_dependencies(self):
        with pytest.raises(TypeError, match="pipeline_runtime"):
            register_all_mcp_tools(MagicMock(), MagicMock(), MagicMock())  # type: ignore[call-arg]
