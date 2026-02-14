"""
Tests for Copilot Studio compatible tools.

Target: copilot_tools.py and _common.py coverage from 0% to 90%+
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from pubmed_search.presentation.mcp_server.tools._common import (
    InputNormalizer,
    ResponseFormatter,
    apply_key_aliases,
)

# =============================================================================
# InputNormalizer Tests
# =============================================================================


class TestInputNormalizerPmids:
    """Tests for PMID normalization."""

    async def test_normalize_pmids_none(self):
        """Test None input."""
        assert InputNormalizer.normalize_pmids(None) == []

    async def test_normalize_pmids_single_str(self):
        """Test single string PMID."""
        assert InputNormalizer.normalize_pmids("12345678") == ["12345678"]

    async def test_normalize_pmids_comma_separated(self):
        """Test comma-separated PMIDs."""
        result = InputNormalizer.normalize_pmids("12345678,87654321")
        assert result == ["12345678", "87654321"]

    async def test_normalize_pmids_with_spaces(self):
        """Test comma-separated with spaces."""
        result = InputNormalizer.normalize_pmids("12345678, 87654321, 11111111")
        assert result == ["12345678", "87654321", "11111111"]

    async def test_normalize_pmids_space_separated(self):
        """Test space-separated PMIDs."""
        result = InputNormalizer.normalize_pmids("12345678 87654321")
        assert result == ["12345678", "87654321"]

    async def test_normalize_pmids_with_prefix(self):
        """Test with PMID: prefix."""
        result = InputNormalizer.normalize_pmids("PMID:12345678")
        assert result == ["12345678"]

    async def test_normalize_pmids_mixed_prefixes(self):
        """Test mixed formats with prefixes."""
        result = InputNormalizer.normalize_pmids("PMID: 12345678, pubmed:87654321")
        assert result == ["12345678", "87654321"]

    async def test_normalize_pmids_list_input(self):
        """Test list input."""
        result = InputNormalizer.normalize_pmids(["12345678", "87654321"])
        assert result == ["12345678", "87654321"]

    async def test_normalize_pmids_int_list(self):
        """Test list of integers."""
        result = InputNormalizer.normalize_pmids([12345678, 87654321])
        assert result == ["12345678", "87654321"]

    async def test_normalize_pmids_single_int(self):
        """Test single integer."""
        result = InputNormalizer.normalize_pmids(12345678)
        assert result == ["12345678"]

    async def test_normalize_pmids_last_keyword(self):
        """Test 'last' keyword."""
        result = InputNormalizer.normalize_pmids("last")
        assert result == ["last"]

    async def test_normalize_pmids_last_case_insensitive(self):
        """Test 'LAST' keyword."""
        result = InputNormalizer.normalize_pmids("LAST")
        assert result == ["last"]

    async def test_normalize_pmids_semicolon_separated(self):
        """Test semicolon-separated PMIDs."""
        result = InputNormalizer.normalize_pmids("12345678;87654321")
        assert result == ["12345678", "87654321"]

    async def test_normalize_pmids_pipe_separated(self):
        """Test pipe-separated PMIDs."""
        result = InputNormalizer.normalize_pmids("12345678|87654321")
        assert result == ["12345678", "87654321"]


class TestInputNormalizerPmidSingle:
    """Tests for single PMID normalization."""

    async def test_normalize_pmid_single_valid(self):
        """Test valid single PMID."""
        result = InputNormalizer.normalize_pmid_single("12345678")
        assert result == "12345678"

    async def test_normalize_pmid_single_with_prefix(self):
        """Test with prefix."""
        result = InputNormalizer.normalize_pmid_single("PMID:12345678")
        assert result == "12345678"

    async def test_normalize_pmid_single_int(self):
        """Test integer input."""
        result = InputNormalizer.normalize_pmid_single(12345678)
        assert result == "12345678"

    async def test_normalize_pmid_single_none(self):
        """Test None input."""
        result = InputNormalizer.normalize_pmid_single(None)
        assert result is None

    async def test_normalize_pmid_single_empty(self):
        """Test empty string."""
        result = InputNormalizer.normalize_pmid_single("")
        assert result is None


class TestInputNormalizerPmcid:
    """Tests for PMC ID normalization."""

    async def test_normalize_pmcid_with_prefix(self):
        """Test with PMC prefix."""
        result = InputNormalizer.normalize_pmcid("PMC7096777")
        assert result == "PMC7096777"

    async def test_normalize_pmcid_without_prefix(self):
        """Test without prefix."""
        result = InputNormalizer.normalize_pmcid("7096777")
        assert result == "PMC7096777"

    async def test_normalize_pmcid_lowercase(self):
        """Test lowercase prefix."""
        result = InputNormalizer.normalize_pmcid("pmc7096777")
        assert result == "PMC7096777"

    async def test_normalize_pmcid_with_colon(self):
        """Test PMCID: prefix."""
        result = InputNormalizer.normalize_pmcid("PMCID: PMC7096777")
        assert result == "PMC7096777"

    async def test_normalize_pmcid_none(self):
        """Test None input."""
        result = InputNormalizer.normalize_pmcid(None)
        assert result is None

    async def test_normalize_pmcid_invalid(self):
        """Test invalid input."""
        result = InputNormalizer.normalize_pmcid("invalid")
        assert result is None


class TestInputNormalizerYear:
    """Tests for year normalization."""

    async def test_normalize_year_int(self):
        """Test integer year."""
        result = InputNormalizer.normalize_year(2024)
        assert result == 2024

    async def test_normalize_year_str(self):
        """Test string year."""
        result = InputNormalizer.normalize_year("2024")
        assert result == 2024

    async def test_normalize_year_with_suffix(self):
        """Test year with suffix."""
        result = InputNormalizer.normalize_year("2024年")
        assert result == 2024

    async def test_normalize_year_with_prefix(self):
        """Test 'since' prefix."""
        result = InputNormalizer.normalize_year("since 2020")
        assert result == 2020

    async def test_normalize_year_before(self):
        """Test 'before' prefix."""
        result = InputNormalizer.normalize_year("before 2024")
        assert result == 2024

    async def test_normalize_year_none(self):
        """Test None input."""
        result = InputNormalizer.normalize_year(None)
        assert result is None

    async def test_normalize_year_invalid_range(self):
        """Test year outside valid range."""
        result = InputNormalizer.normalize_year(1800)
        assert result is None

    async def test_normalize_year_future(self):
        """Test future year beyond range."""
        result = InputNormalizer.normalize_year(2200)
        assert result is None


class TestInputNormalizerLimit:
    """Tests for limit normalization."""

    async def test_normalize_limit_default(self):
        """Test default value."""
        result = InputNormalizer.normalize_limit(None, default=10)
        assert result == 10

    async def test_normalize_limit_valid(self):
        """Test valid limit."""
        result = InputNormalizer.normalize_limit(50)
        assert result == 50

    async def test_normalize_limit_string(self):
        """Test string limit."""
        result = InputNormalizer.normalize_limit("25")
        assert result == 25

    async def test_normalize_limit_min_clamp(self):
        """Test minimum clamping."""
        result = InputNormalizer.normalize_limit(0, min_val=1)
        assert result == 1

    async def test_normalize_limit_max_clamp(self):
        """Test maximum clamping."""
        result = InputNormalizer.normalize_limit(200, max_val=100)
        assert result == 100

    async def test_normalize_limit_invalid_string(self):
        """Test invalid string."""
        result = InputNormalizer.normalize_limit("abc", default=10)
        assert result == 10


class TestInputNormalizerBool:
    """Tests for boolean normalization."""

    async def test_normalize_bool_true(self):
        """Test True."""
        assert InputNormalizer.normalize_bool(True) is True

    async def test_normalize_bool_false(self):
        """Test False."""
        assert InputNormalizer.normalize_bool(False) is False

    async def test_normalize_bool_str_true(self):
        """Test 'true' string."""
        assert InputNormalizer.normalize_bool("true") is True

    async def test_normalize_bool_str_yes(self):
        """Test 'yes' string."""
        assert InputNormalizer.normalize_bool("yes") is True

    async def test_normalize_bool_str_1(self):
        """Test '1' string."""
        assert InputNormalizer.normalize_bool("1") is True

    async def test_normalize_bool_str_false(self):
        """Test 'false' string."""
        assert InputNormalizer.normalize_bool("false") is False

    async def test_normalize_bool_str_no(self):
        """Test 'no' string."""
        assert InputNormalizer.normalize_bool("no") is False

    async def test_normalize_bool_int_1(self):
        """Test integer 1."""
        assert InputNormalizer.normalize_bool(1) is True

    async def test_normalize_bool_int_0(self):
        """Test integer 0."""
        assert InputNormalizer.normalize_bool(0) is False

    async def test_normalize_bool_none_default(self):
        """Test None with default."""
        assert InputNormalizer.normalize_bool(None, default=True) is True

    async def test_normalize_bool_on_off(self):
        """Test 'on' and 'off' strings."""
        assert InputNormalizer.normalize_bool("on") is True
        assert InputNormalizer.normalize_bool("off") is False


class TestInputNormalizerQuery:
    """Tests for query normalization."""

    async def test_normalize_query_basic(self):
        """Test basic query."""
        result = InputNormalizer.normalize_query("cancer treatment")
        assert result == "cancer treatment"

    async def test_normalize_query_strip(self):
        """Test whitespace stripping."""
        result = InputNormalizer.normalize_query("  cancer treatment  ")
        assert result == "cancer treatment"

    async def test_normalize_query_unicode_quotes(self):
        """Test Unicode quote normalization."""
        result = InputNormalizer.normalize_query('"cancer"')
        assert '"' in result

    async def test_normalize_query_empty(self):
        """Test empty query."""
        result = InputNormalizer.normalize_query("")
        assert result == ""

    async def test_normalize_query_none(self):
        """Test None query."""
        result = InputNormalizer.normalize_query(None)
        assert result == ""


class TestInputNormalizerDoi:
    """Tests for DOI normalization."""

    async def test_normalize_doi_plain(self):
        """Test plain DOI."""
        result = InputNormalizer.normalize_doi("10.1234/example.123")
        assert result == "10.1234/example.123"

    async def test_normalize_doi_with_prefix(self):
        """Test with doi: prefix."""
        result = InputNormalizer.normalize_doi("doi:10.1234/example.123")
        assert result == "10.1234/example.123"

    async def test_normalize_doi_url(self):
        """Test DOI URL."""
        result = InputNormalizer.normalize_doi("https://doi.org/10.1234/example.123")
        assert result == "10.1234/example.123"

    async def test_normalize_doi_dx_url(self):
        """Test dx.doi.org URL."""
        result = InputNormalizer.normalize_doi("http://dx.doi.org/10.1234/example.123")
        assert result == "10.1234/example.123"

    async def test_normalize_doi_invalid(self):
        """Test invalid DOI."""
        result = InputNormalizer.normalize_doi("not-a-doi")
        assert result is None

    async def test_normalize_doi_none(self):
        """Test None DOI."""
        result = InputNormalizer.normalize_doi(None)
        assert result is None


class TestInputNormalizerIdentifier:
    """Tests for identifier auto-detection."""

    async def test_normalize_identifier_pmid(self):
        """Test PMID detection."""
        result = InputNormalizer.normalize_identifier("12345678")
        assert result["type"] == "pmid"
        assert result["value"] == "12345678"

    async def test_normalize_identifier_pmid_prefix(self):
        """Test PMID with prefix."""
        result = InputNormalizer.normalize_identifier("PMID:12345678")
        assert result["type"] == "pmid"
        assert result["value"] == "12345678"

    async def test_normalize_identifier_pmcid(self):
        """Test PMC ID detection."""
        result = InputNormalizer.normalize_identifier("PMC7096777")
        assert result["type"] == "pmcid"
        assert result["value"] == "PMC7096777"

    async def test_normalize_identifier_doi(self):
        """Test DOI detection."""
        result = InputNormalizer.normalize_identifier("10.1234/example")
        assert result["type"] == "doi"
        assert result["value"] == "10.1234/example"

    async def test_normalize_identifier_doi_url(self):
        """Test DOI URL detection."""
        result = InputNormalizer.normalize_identifier("https://doi.org/10.1234/example")
        assert result["type"] == "doi"
        assert result["value"] == "10.1234/example"

    async def test_normalize_identifier_int(self):
        """Test integer input."""
        result = InputNormalizer.normalize_identifier(12345678)
        assert result["type"] == "pmid"
        assert result["value"] == "12345678"

    async def test_normalize_identifier_none(self):
        """Test None input."""
        result = InputNormalizer.normalize_identifier(None)
        assert result["type"] is None
        assert result["value"] is None


# =============================================================================
# ResponseFormatter Tests
# =============================================================================


class TestResponseFormatterSuccess:
    """Tests for success response formatting."""

    async def test_success_markdown(self):
        """Test markdown format."""
        result = ResponseFormatter.success("Test data", message="Done")
        assert "✅" in result
        assert "Done" in result
        assert "Test data" in result

    async def test_success_json(self):
        """Test JSON format."""
        result = ResponseFormatter.success({"key": "value"}, message="Done", output_format="json")
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["data"]["key"] == "value"
        assert parsed["message"] == "Done"

    async def test_success_with_metadata(self):
        """Test with metadata."""
        result = ResponseFormatter.success("data", metadata={"count": 10}, output_format="json")
        parsed = json.loads(result)
        assert parsed["metadata"]["count"] == 10

    async def test_success_list_data(self):
        """Test with list data."""
        result = ResponseFormatter.success([1, 2, 3])
        assert "1" in result


class TestResponseFormatterError:
    """Tests for error response formatting."""

    async def test_error_markdown(self):
        """Test markdown error format."""
        result = ResponseFormatter.error("Something went wrong", suggestion="Try again", tool_name="test_tool")
        assert "❌" in result
        assert "test_tool" in result
        assert "Something went wrong" in result
        assert "💡" in result
        assert "Try again" in result

    async def test_error_with_example(self):
        """Test error with example."""
        result = ResponseFormatter.error("Invalid input", example="tool(param='value')")
        assert "📝" in result
        assert "tool(param='value')" in result

    async def test_error_json(self):
        """Test JSON error format."""
        result = ResponseFormatter.error("Error message", suggestion="Fix it", output_format="json")
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "Error message"
        assert parsed["suggestion"] == "Fix it"

    async def test_error_from_exception(self):
        """Test error from exception object."""
        try:
            raise ValueError("Test exception")
        except ValueError as e:
            result = ResponseFormatter.error(e)
            assert "Test exception" in result


class TestResponseFormatterNoResults:
    """Tests for no-results formatting."""

    async def test_no_results_basic(self):
        """Test basic no results."""
        result = ResponseFormatter.no_results()
        assert "No results found" in result

    async def test_no_results_with_query(self):
        """Test no results with query."""
        result = ResponseFormatter.no_results(query="test query")
        assert "test query" in result

    async def test_no_results_with_suggestions(self):
        """Test no results with suggestions."""
        result = ResponseFormatter.no_results(suggestions=["Try broader terms"])
        assert "Try broader terms" in result

    async def test_no_results_with_alternatives(self):
        """Test no results with alternative tools."""
        result = ResponseFormatter.no_results(alternative_tools=["search_core"])
        assert "search_core" in result


class TestResponseFormatterPartialSuccess:
    """Tests for partial success formatting."""

    async def test_partial_success_basic(self):
        """Test basic partial success."""
        result = ResponseFormatter.partial_success(successful=[1, 2, 3], failed=[{"id": "x", "error": "failed"}])
        assert "3 succeeded" in result
        assert "1 failed" in result

    async def test_partial_success_with_message(self):
        """Test with custom message."""
        result = ResponseFormatter.partial_success(successful=[], failed=[], message="Custom message")
        assert "Custom message" in result

    async def test_partial_success_many_failures(self):
        """Test with many failures (>5)."""
        failed = [{"id": str(i), "error": f"error {i}"} for i in range(10)]
        result = ResponseFormatter.partial_success(successful=[], failed=failed)
        assert "and 5 more" in result


# =============================================================================
# Key Alias Tests
# =============================================================================


class TestKeyAliases:
    """Tests for key alias mapping."""

    async def test_apply_year_aliases(self):
        """Test year parameter aliases."""
        result = apply_key_aliases({"year_from": 2020, "year_to": 2024})
        assert result["min_year"] == 2020
        assert result["max_year"] == 2024

    async def test_apply_limit_aliases(self):
        """Test limit parameter aliases."""
        result = apply_key_aliases({"max_results": 50})
        assert result["limit"] == 50

    async def test_apply_format_aliases(self):
        """Test format parameter aliases."""
        result = apply_key_aliases({"format": "json"})
        assert result["output_format"] == "json"

    async def test_standard_key_takes_precedence(self):
        """Test that standard key takes precedence over alias."""
        result = apply_key_aliases({"limit": 10, "max_results": 50})
        assert result["limit"] == 10

    async def test_no_aliases_needed(self):
        """Test with standard keys only."""
        result = apply_key_aliases({"limit": 10, "min_year": 2020})
        assert result["limit"] == 10
        assert result["min_year"] == 2020


# =============================================================================
# Module Functions Tests
# =============================================================================


class TestCommonFunctions:
    """Tests for common module functions."""

    async def test_set_get_session_manager(self):
        """Test session manager getter/setter."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            get_session_manager,
            set_session_manager,
        )

        mock_manager = MagicMock()
        set_session_manager(mock_manager)
        assert get_session_manager() is mock_manager
        # Cleanup
        set_session_manager(None)

    async def test_set_get_strategy_generator(self):
        """Test strategy generator getter/setter."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            get_strategy_generator,
            set_strategy_generator,
        )

        mock_gen = MagicMock()
        set_strategy_generator(mock_gen)
        assert get_strategy_generator() is mock_gen
        # Cleanup
        set_strategy_generator(None)

    async def test_format_search_results_empty(self):
        """Test format with empty results."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            format_search_results,
        )

        result = format_search_results([])
        assert "No results found" in result

    async def test_format_search_results_error(self):
        """Test format with error in results."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            format_search_results,
        )

        result = format_search_results([{"error": "API failed"}])
        assert "Error" in result

    async def test_format_search_results_normal(self):
        """Test format with normal results."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            format_search_results,
        )

        results = [
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
        result = format_search_results(results)
        assert "Test Article" in result
        assert "Smith J" in result
        assert "Nature" in result
        assert "12345678" in result

    async def test_get_last_search_pmids_no_manager(self):
        """Test get_last_search_pmids without manager."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            get_last_search_pmids,
            set_session_manager,
        )

        set_session_manager(None)
        result = get_last_search_pmids()
        assert result == []

    async def test_check_cache_no_manager(self):
        """Test check_cache without manager."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            check_cache,
            set_session_manager,
        )

        set_session_manager(None)
        result = check_cache("test query")
        assert result is None


# =============================================================================
# Copilot Tools Integration Tests (with mocks)
# =============================================================================


class TestCopilotToolsIntegration:
    """Integration tests for copilot tools with mocked searcher."""

    @pytest.fixture
    def mock_searcher(self):
        """Create a mock LiteratureSearcher."""
        searcher = AsyncMock()
        searcher.search.return_value = [
            {
                "pmid": "12345678",
                "title": "Test Article",
                "authors": ["Smith J"],
                "journal": "Nature",
                "year": "2024",
            }
        ]
        searcher.fetch_details.return_value = [
            {
                "pmid": "12345678",
                "title": "Test Article",
                "authors": ["Smith J", "Doe J"],
                "journal": "Nature",
                "year": "2024",
                "abstract": "Test abstract text.",
                "doi": "10.1234/test",
            }
        ]
        searcher.find_related_articles.return_value = [
            {
                "pmid": "87654321",
                "title": "Related Article",
                "authors": ["Brown A"],
                "journal": "Science",
                "year": "2023",
            }
        ]
        searcher.find_citing_articles.return_value = []
        searcher.get_article_references.return_value = []
        return searcher

    @pytest.fixture
    def mock_mcp(self):
        """Create a mock FastMCP."""
        mcp = MagicMock()
        tools = {}

        def tool_decorator():
            def wrapper(func):
                tools[func.__name__] = func
                return func

            return wrapper

        mcp.tool = tool_decorator
        mcp._tools = tools
        return mcp

    async def test_register_tools(self, mock_mcp, mock_searcher):
        """Test that tools register correctly."""
        from pubmed_search.presentation.mcp_server.copilot_tools import (
            register_copilot_compatible_tools,
        )

        register_copilot_compatible_tools(mock_mcp, mock_searcher)

        # Check that tools were registered
        assert len(mock_mcp._tools) > 0

    async def test_search_pubmed_tool(self, mock_mcp, mock_searcher):
        """Test search_pubmed tool functionality."""
        from pubmed_search.presentation.mcp_server.copilot_tools import (
            register_copilot_compatible_tools,
        )

        register_copilot_compatible_tools(mock_mcp, mock_searcher)

        # Get the registered tool
        search_tool = mock_mcp._tools.get("search_pubmed")
        if search_tool:
            result = await search_tool("cancer treatment", limit=10)
            assert "Test Article" in result

    async def test_get_article_tool(self, mock_mcp, mock_searcher):
        """Test get_article tool functionality."""
        from pubmed_search.presentation.mcp_server.copilot_tools import (
            register_copilot_compatible_tools,
        )

        register_copilot_compatible_tools(mock_mcp, mock_searcher)

        get_article_tool = mock_mcp._tools.get("get_article")
        if get_article_tool:
            result = await get_article_tool("12345678")
            assert "Test Article" in result

    async def test_get_article_invalid_pmid(self, mock_mcp, mock_searcher):
        """Test get_article with invalid PMID."""
        from pubmed_search.presentation.mcp_server.copilot_tools import (
            register_copilot_compatible_tools,
        )

        register_copilot_compatible_tools(mock_mcp, mock_searcher)

        get_article_tool = mock_mcp._tools.get("get_article")
        if get_article_tool:
            result = await get_article_tool("")
            assert "Invalid" in result or "Error" in result

    async def test_find_related_tool(self, mock_mcp, mock_searcher):
        """Test find_related tool functionality."""
        from pubmed_search.presentation.mcp_server.copilot_tools import (
            register_copilot_compatible_tools,
        )

        register_copilot_compatible_tools(mock_mcp, mock_searcher)

        find_related_tool = mock_mcp._tools.get("find_related")
        if find_related_tool:
            result = await find_related_tool("12345678", limit=10)
            assert "Related Article" in result


class TestCopilotToolCount:
    """Test tool count constant."""

    async def test_copilot_tool_count(self):
        """Verify COPILOT_TOOL_COUNT constant."""
        from pubmed_search.presentation.mcp_server.copilot_tools import (
            COPILOT_TOOL_COUNT,
        )

        assert COPILOT_TOOL_COUNT == 12
