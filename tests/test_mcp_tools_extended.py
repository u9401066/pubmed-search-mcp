"""
Tests for MCP Tools - merge, pico, strategy, and export tools.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestMergeTools:
    """Tests for merge_search_results tool."""

    async def test_merge_simple_format(self):
        """Test merging results in simple list format."""
        from pubmed_search.presentation.mcp_server.tools.merge import (
            register_merge_tools,
        )

        mcp = MagicMock()
        searcher = AsyncMock()

        # Capture the registered function
        registered_fn = None

        def capture_tool():
            def decorator(fn):
                nonlocal registered_fn
                registered_fn = fn
                return fn

            return decorator

        mcp.tool = capture_tool
        register_merge_tools(mcp, searcher)

        # Test the function
        input_json = json.dumps([["12345", "67890"], ["67890", "11111"]])

        result = registered_fn(input_json)
        parsed = json.loads(result)

        assert parsed["total_unique"] == 3
        assert parsed["duplicates_removed"] == 1
        assert "67890" in parsed["high_relevance"]["pmids"]

    async def test_merge_query_id_format(self):
        """Test merging results with query IDs."""
        from pubmed_search.presentation.mcp_server.tools.merge import (
            register_merge_tools,
        )

        mcp = MagicMock()
        searcher = AsyncMock()

        registered_fn = None

        def capture_tool():
            def decorator(fn):
                nonlocal registered_fn
                registered_fn = fn
                return fn

            return decorator

        mcp.tool = capture_tool
        register_merge_tools(mcp, searcher)

        input_json = json.dumps(
            [
                {"query_id": "q1_title", "pmids": ["123", "456"]},
                {"query_id": "q2_tiab", "pmids": ["456", "789"]},
            ]
        )

        result = registered_fn(input_json)
        parsed = json.loads(result)

        assert parsed["total_unique"] == 3
        assert "q1_title" in parsed["by_source"]
        assert "q2_tiab" in parsed["by_source"]

    async def test_merge_invalid_json(self):
        """Test merging with invalid JSON."""
        from pubmed_search.presentation.mcp_server.tools.merge import (
            register_merge_tools,
        )

        mcp = MagicMock()
        searcher = AsyncMock()

        registered_fn = None

        def capture_tool():
            def decorator(fn):
                nonlocal registered_fn
                registered_fn = fn
                return fn

            return decorator

        mcp.tool = capture_tool
        register_merge_tools(mcp, searcher)

        result = registered_fn("not valid json")
        assert "Error" in result

    async def test_merge_empty(self):
        """Test merging empty results."""
        from pubmed_search.presentation.mcp_server.tools.merge import (
            register_merge_tools,
        )

        mcp = MagicMock()
        searcher = AsyncMock()

        registered_fn = None

        def capture_tool():
            def decorator(fn):
                nonlocal registered_fn
                registered_fn = fn
                return fn

            return decorator

        mcp.tool = capture_tool
        register_merge_tools(mcp, searcher)

        result = registered_fn(json.dumps([]))
        parsed = json.loads(result)

        assert parsed["total_unique"] == 0


class TestPicoTools:
    """Tests for PICO parsing tools."""

    async def test_parse_pico_structured(self):
        """Test parsing with pre-structured PICO."""
        from pubmed_search.presentation.mcp_server.tools.pico import register_pico_tools

        mcp = MagicMock()

        registered_fn = None

        def capture_tool():
            def decorator(fn):
                nonlocal registered_fn
                registered_fn = fn
                return fn

            return decorator

        mcp.tool = capture_tool
        register_pico_tools(mcp)

        result = registered_fn(
            description="Test question",
            p="ICU patients",
            i="Drug A",
            c="Drug B",
            o="mortality",
        )
        parsed = json.loads(result)

        assert parsed["source"] == "user_provided"
        assert parsed["pico"]["P"] == "ICU patients"
        assert parsed["pico"]["I"] == "Drug A"
        assert parsed["pico"]["C"] == "Drug B"
        assert parsed["pico"]["O"] == "mortality"

    async def test_parse_pico_needs_parsing(self):
        """Test parsing with natural language description."""
        from pubmed_search.presentation.mcp_server.tools.pico import register_pico_tools

        mcp = MagicMock()

        registered_fn = None

        def capture_tool():
            def decorator(fn):
                nonlocal registered_fn
                registered_fn = fn
                return fn

            return decorator

        mcp.tool = capture_tool
        register_pico_tools(mcp)

        result = registered_fn(description="Is remimazolam better than propofol for ICU sedation?")
        parsed = json.loads(result)

        assert parsed["source"] == "needs_parsing"
        assert "[Agent:" in parsed["pico"]["P"]

    async def test_parse_pico_question_type_therapy(self):
        """Test inferring therapy question type."""
        from pubmed_search.presentation.mcp_server.tools.pico import register_pico_tools

        mcp = MagicMock()

        registered_fn = None

        def capture_tool():
            def decorator(fn):
                nonlocal registered_fn
                registered_fn = fn
                return fn

            return decorator

        mcp.tool = capture_tool
        register_pico_tools(mcp)

        result = registered_fn(description="What is the treatment effect of drug X versus placebo?")
        parsed = json.loads(result)

        assert parsed["question_type"] == "therapy"

    async def test_parse_pico_question_type_diagnosis(self):
        """Test inferring diagnosis question type."""
        from pubmed_search.presentation.mcp_server.tools.pico import register_pico_tools

        mcp = MagicMock()

        registered_fn = None

        def capture_tool():
            def decorator(fn):
                nonlocal registered_fn
                registered_fn = fn
                return fn

            return decorator

        mcp.tool = capture_tool
        register_pico_tools(mcp)

        result = registered_fn(description="What is the sensitivity and specificity of test X for diagnosis?")
        parsed = json.loads(result)

        assert parsed["question_type"] == "diagnosis"

    async def test_parse_pico_question_type_prognosis(self):
        """Test inferring prognosis question type."""
        from pubmed_search.presentation.mcp_server.tools.pico import register_pico_tools

        mcp = MagicMock()

        registered_fn = None

        def capture_tool():
            def decorator(fn):
                nonlocal registered_fn
                registered_fn = fn
                return fn

            return decorator

        mcp.tool = capture_tool
        register_pico_tools(mcp)

        result = registered_fn(description="What is the survival rate and mortality for patients with condition Y?")
        parsed = json.loads(result)

        assert parsed["question_type"] == "prognosis"


class TestStrategyTools:
    """Tests for search strategy tools."""

    async def test_generate_search_queries_fallback(self):
        """Test generate_search_queries with fallback (no strategy generator)."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            set_strategy_generator,
        )
        from pubmed_search.presentation.mcp_server.tools.strategy import (
            register_strategy_tools,
        )

        # Ensure no strategy generator is set
        set_strategy_generator(None)

        mcp = MagicMock()
        searcher = AsyncMock()

        registered_fn = None

        def capture_tool():
            def decorator(fn):
                nonlocal registered_fn
                if fn.__name__ == "generate_search_queries":
                    registered_fn = fn
                return fn

            return decorator

        mcp.tool = capture_tool
        register_strategy_tools(mcp, searcher)

        result = await registered_fn(topic="diabetes treatment")
        parsed = json.loads(result)

        # Fallback should create basic queries
        assert "suggested_queries" in parsed
        assert len(parsed["suggested_queries"]) >= 1

    async def test_generate_search_queries_with_generator(self):
        """Test generate_search_queries with strategy generator."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            set_strategy_generator,
        )
        from pubmed_search.presentation.mcp_server.tools.strategy import (
            register_strategy_tools,
        )

        # Set up mock strategy generator
        mock_generator = AsyncMock()
        mock_generator.generate_strategies.return_value = {
            "corrected_topic": "diabetes",
            "mesh_terms": [{"preferred_term": "Diabetes Mellitus"}],
            "suggested_queries": [{"query": "diabetes[MeSH]"}],
        }
        set_strategy_generator(mock_generator)

        mcp = MagicMock()
        searcher = AsyncMock()

        registered_fn = None

        def capture_tool():
            def decorator(fn):
                nonlocal registered_fn
                if fn.__name__ == "generate_search_queries":
                    registered_fn = fn
                return fn

            return decorator

        mcp.tool = capture_tool
        register_strategy_tools(mcp, searcher)

        result = await registered_fn(topic="diabetes")
        parsed = json.loads(result)

        assert "corrected_topic" in parsed
        assert parsed["corrected_topic"] == "diabetes"

        # Clean up
        set_strategy_generator(None)


class TestExportTools:
    """Tests for export MCP tools."""

    async def test_prepare_export_ris(self):
        """Test prepare_export with RIS format."""
        from pubmed_search.presentation.mcp_server.tools.export import (
            register_export_tools,
        )

        mcp = MagicMock()
        searcher = AsyncMock()
        searcher.fetch_details.return_value = [
            {
                "pmid": "123",
                "title": "Test",
                "authors": ["Smith J"],
                "year": "2024",
                "journal": "J Med",
            }
        ]

        # Capture the prepare_export function
        registered_fns = {}

        def capture_tool():
            def decorator(fn):
                registered_fns[fn.__name__] = fn
                return fn

            return decorator

        mcp.tool = capture_tool
        register_export_tools(mcp, searcher)

        result = await registered_fns["prepare_export"](pmids="123", format="ris")
        parsed = json.loads(result)

        assert parsed["status"] == "success"
        assert parsed["format"] == "ris"

    async def test_prepare_export_invalid_format(self):
        """Test prepare_export with invalid format."""
        from pubmed_search.presentation.mcp_server.tools.export import (
            register_export_tools,
        )

        mcp = MagicMock()
        searcher = AsyncMock()

        registered_fns = {}

        def capture_tool():
            def decorator(fn):
                registered_fns[fn.__name__] = fn
                return fn

            return decorator

        mcp.tool = capture_tool
        register_export_tools(mcp, searcher)

        result = await registered_fns["prepare_export"](pmids="123", format="invalid")

        # Result could be JSON or plain text error message
        try:
            parsed = json.loads(result)
            assert parsed.get("status") == "error" or "unsupported" in str(parsed).lower()
        except json.JSONDecodeError:
            # Plain text error message
            assert "unsupported" in result.lower() or "error" in result.lower()

    # v0.1.21: get_article_fulltext_links has been integrated into get_fulltext
    @pytest.mark.skip(reason="v0.1.21: get_article_fulltext_links integrated into get_fulltext")
    async def test_get_article_fulltext_links(self):
        """Test get_article_fulltext_links tool."""
        # This tool has been integrated into get_fulltext

    # v0.1.21: analyze_fulltext_access has been integrated into get_fulltext
    @pytest.mark.skip(reason="v0.1.21: analyze_fulltext_access integrated into get_fulltext")
    async def test_analyze_fulltext_access(self):
        """Test analyze_fulltext_access tool."""
        # This tool has been integrated into get_fulltext


class TestCommonToolsExtended:
    """Extended tests for common tool utilities."""

    async def test_get_last_search_pmids_empty(self):
        """Test get_last_search_pmids with no session."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            get_last_search_pmids,
            set_session_manager,
        )

        set_session_manager(None)
        result = get_last_search_pmids()
        assert result == []

    async def test_get_last_search_pmids_with_session(self):
        """Test get_last_search_pmids with session."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            get_last_search_pmids,
            set_session_manager,
        )

        mock_session = MagicMock()
        mock_session.search_history = [
            MagicMock(pmids=["123", "456"])  # Use a mock with pmids attribute
        ]

        mock_manager = MagicMock()
        mock_manager.get_or_create_session.return_value = mock_session

        set_session_manager(mock_manager)

        result = get_last_search_pmids()
        assert "123" in result or len(result) > 0 or result == ["123", "456"]

        # Clean up
        set_session_manager(None)

    async def test_check_cache_no_session(self):
        """Test check_cache with no session manager."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            check_cache,
            set_session_manager,
        )

        set_session_manager(None)
        result = check_cache("test query", 10)
        assert result is None

    async def test_format_search_results_include_doi(self, mock_article_data):
        """Test format_search_results with DOI included."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            format_search_results,
        )

        result = format_search_results([mock_article_data], include_doi=True)

        assert "10.1000" in result or "doi" in result.lower()
