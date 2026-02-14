"""
Tests for Phase 2.1 Input Normalizer and Response Formatter

These utilities make MCP tools more Agent-friendly by:
- Accepting multiple input formats
- Providing helpful error messages
- Auto-correcting common mistakes
"""

from __future__ import annotations

import json


class TestInputNormalizerPMIDs:
    """Tests for PMID normalization."""

    async def test_single_pmid_string(self):
        """Single PMID string should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_pmids("12345678")
        assert result == ["12345678"]

    async def test_multiple_pmids_comma(self):
        """Comma-separated PMIDs should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_pmids("12345678,87654321")
        assert result == ["12345678", "87654321"]

    async def test_multiple_pmids_comma_spaces(self):
        """Comma with spaces should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_pmids("12345678, 87654321, 11111111")
        assert result == ["12345678", "87654321", "11111111"]

    async def test_multiple_pmids_space_separated(self):
        """Space-separated PMIDs should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_pmids("12345678 87654321")
        assert result == ["12345678", "87654321"]

    async def test_pmid_with_prefix(self):
        """PMID: prefix should be stripped."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_pmids("PMID:12345678")
        assert result == ["12345678"]

    async def test_pmid_with_prefix_and_space(self):
        """PMID: prefix with space should be stripped."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_pmids("PMID: 12345678")
        assert result == ["12345678"]

    async def test_mixed_format_pmids(self):
        """Mixed formats should all work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_pmids("PMID:12345678, 87654321, pmid: 11111111")
        assert result == ["12345678", "87654321", "11111111"]

    async def test_list_input(self):
        """List input should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_pmids(["12345678", "87654321"])
        assert result == ["12345678", "87654321"]

    async def test_int_input(self):
        """Integer input should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_pmids(12345678)
        assert result == ["12345678"]

    async def test_int_list_input(self):
        """Integer list should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_pmids([12345678, 87654321])
        assert result == ["12345678", "87654321"]

    async def test_last_keyword(self):
        """'last' keyword should be preserved."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_pmids("last")
        assert result == ["last"]

    async def test_none_input(self):
        """None should return empty list."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_pmids(None)
        assert result == []

    async def test_empty_string(self):
        """Empty string should return empty list."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_pmids("")
        assert result == []


class TestInputNormalizerPMCID:
    """Tests for PMC ID normalization."""

    async def test_pmc_with_prefix(self):
        """PMCxxxxxxx format should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_pmcid("PMC7096777")
        assert result == "PMC7096777"

    async def test_pmc_without_prefix(self):
        """Digits only should add PMC prefix."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_pmcid("7096777")
        assert result == "PMC7096777"

    async def test_pmc_lowercase(self):
        """Lowercase pmc should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_pmcid("pmc7096777")
        assert result == "PMC7096777"

    async def test_pmc_with_pmcid_prefix(self):
        """PMCID: prefix should be handled."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_pmcid("PMCID: PMC7096777")
        assert result == "PMC7096777"


class TestInputNormalizerYear:
    """Tests for year normalization."""

    async def test_year_int(self):
        """Integer year should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_year(2024)
        assert result == 2024

    async def test_year_string(self):
        """String year should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_year("2024")
        assert result == 2024

    async def test_year_with_text(self):
        """Year with text should extract year."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_year("2024年")
        assert result == 2024

    async def test_year_since(self):
        """'since 2020' should extract 2020."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_year("since 2020")
        assert result == 2020

    async def test_year_invalid(self):
        """Invalid year should return None."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_year("invalid")
        assert result is None

    async def test_year_out_of_range(self):
        """Year out of range should return None."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_year(1800)
        assert result is None


class TestInputNormalizerLimit:
    """Tests for limit normalization."""

    async def test_limit_int(self):
        """Integer limit should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_limit(20)
        assert result == 20

    async def test_limit_string(self):
        """String limit should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_limit("20")
        assert result == 20

    async def test_limit_none_uses_default(self):
        """None should use default."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_limit(None, default=15)
        assert result == 15

    async def test_limit_clamped_max(self):
        """Limit above max should be clamped."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_limit(200, max_val=100)
        assert result == 100

    async def test_limit_clamped_min(self):
        """Limit below min should be clamped."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_limit(0, min_val=1)
        assert result == 1


class TestInputNormalizerBool:
    """Tests for boolean normalization."""

    async def test_bool_true(self):
        """True should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        assert InputNormalizer.normalize_bool(True) is True

    async def test_bool_false(self):
        """False should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        assert InputNormalizer.normalize_bool(False) is False

    async def test_bool_string_true(self):
        """'true' string should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        assert InputNormalizer.normalize_bool("true") is True
        assert InputNormalizer.normalize_bool("True") is True
        assert InputNormalizer.normalize_bool("TRUE") is True

    async def test_bool_string_false(self):
        """'false' string should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        assert InputNormalizer.normalize_bool("false") is False
        assert InputNormalizer.normalize_bool("False") is False

    async def test_bool_yes_no(self):
        """yes/no should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        assert InputNormalizer.normalize_bool("yes") is True
        assert InputNormalizer.normalize_bool("no") is False

    async def test_bool_int(self):
        """1/0 should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        assert InputNormalizer.normalize_bool(1) is True
        assert InputNormalizer.normalize_bool(0) is False

    async def test_bool_none_default(self):
        """None should use default."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        assert InputNormalizer.normalize_bool(None, default=True) is True
        assert InputNormalizer.normalize_bool(None, default=False) is False


class TestInputNormalizerQuery:
    """Tests for query normalization."""

    async def test_query_strip(self):
        """Query should be stripped."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_query("  diabetes  ")
        assert result == "diabetes"

    async def test_query_unicode_quotes(self):
        """Unicode quotes should be normalized."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_query('"diabetes treatment"')
        assert result == '"diabetes treatment"'

    async def test_query_empty(self):
        """Empty query should return empty string."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        assert InputNormalizer.normalize_query("") == ""
        assert InputNormalizer.normalize_query(None) == ""


class TestInputNormalizerDOI:
    """Tests for DOI normalization (v0.1.21)."""

    async def test_doi_simple(self):
        """Simple DOI should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_doi("10.1234/example.123")
        assert result == "10.1234/example.123"

    async def test_doi_with_prefix(self):
        """DOI with doi: prefix should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_doi("doi:10.1234/example.123")
        assert result == "10.1234/example.123"

    async def test_doi_with_prefix_space(self):
        """DOI with 'DOI: ' prefix should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_doi("DOI: 10.1234/example.123")
        assert result == "10.1234/example.123"

    async def test_doi_url_https(self):
        """DOI URL with https://doi.org should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_doi("https://doi.org/10.1234/example.123")
        assert result == "10.1234/example.123"

    async def test_doi_url_dx(self):
        """DOI URL with dx.doi.org should work."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_doi("http://dx.doi.org/10.1234/example.123")
        assert result == "10.1234/example.123"

    async def test_doi_invalid(self):
        """Invalid DOI should return None."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        assert InputNormalizer.normalize_doi("invalid-doi") is None
        assert InputNormalizer.normalize_doi("12345678") is None
        assert InputNormalizer.normalize_doi(None) is None


class TestInputNormalizerIdentifier:
    """Tests for auto-detect identifier normalization (v0.1.21)."""

    async def test_identifier_pmid_digits(self):
        """Pure digits should be detected as PMID."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_identifier("12345678")
        assert result["type"] == "pmid"
        assert result["value"] == "12345678"

    async def test_identifier_pmid_prefix(self):
        """PMID: prefix should be detected as PMID."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_identifier("PMID:12345678")
        assert result["type"] == "pmid"
        assert result["value"] == "12345678"

    async def test_identifier_pmid_int(self):
        """Integer should be detected as PMID."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_identifier(12345678)
        assert result["type"] == "pmid"
        assert result["value"] == "12345678"

    async def test_identifier_pmcid(self):
        """PMC ID should be detected."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_identifier("PMC7096777")
        assert result["type"] == "pmcid"
        assert result["value"] == "PMC7096777"

    async def test_identifier_pmcid_lowercase(self):
        """Lowercase PMC ID should be detected."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_identifier("pmc7096777")
        assert result["type"] == "pmcid"
        assert result["value"] == "PMC7096777"

    async def test_identifier_doi(self):
        """DOI should be detected."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_identifier("10.1038/nature12373")
        assert result["type"] == "doi"
        assert result["value"] == "10.1038/nature12373"

    async def test_identifier_doi_url(self):
        """DOI URL should be detected."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_identifier("https://doi.org/10.1038/s41586")
        assert result["type"] == "doi"
        assert result["value"] == "10.1038/s41586"

    async def test_identifier_none(self):
        """None should return type=None."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_identifier(None)
        assert result["type"] is None
        assert result["value"] is None

    async def test_identifier_preserves_original(self):
        """Original value should be preserved."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_identifier("PMID:12345678")
        assert result["original"] == "PMID:12345678"


class TestResponseFormatter:
    """Tests for response formatting."""

    async def test_success_markdown(self):
        """Success response in markdown."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            ResponseFormatter,
        )

        result = ResponseFormatter.success("Test data", message="Success!")
        assert "✅" in result
        assert "Success!" in result
        assert "Test data" in result

    async def test_success_json(self):
        """Success response in JSON."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            ResponseFormatter,
        )

        result = ResponseFormatter.success({"key": "value"}, output_format="json")
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["data"]["key"] == "value"

    async def test_error_markdown(self):
        """Error response in markdown."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            ResponseFormatter,
        )

        result = ResponseFormatter.error(
            "API failed",
            suggestion="Check your query",
            example="search_literature(query='diabetes')",
            tool_name="search_literature",
        )
        assert "❌" in result
        assert "API failed" in result
        assert "Check your query" in result

    async def test_error_json(self):
        """Error response in JSON."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            ResponseFormatter,
        )

        result = ResponseFormatter.error("API failed", suggestion="Check your query", output_format="json")
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "API failed"
        assert parsed["suggestion"] == "Check your query"

    async def test_no_results(self):
        """No results response."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            ResponseFormatter,
        )

        result = ResponseFormatter.no_results(query="obscure term", suggestions=["Try broader terms", "Check spelling"])
        assert "No results found" in result
        assert "obscure term" in result
        assert "Try broader terms" in result


class TestKeyAliases:
    """Tests for key alias mapping."""

    async def test_year_aliases(self):
        """Year aliases should be mapped."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            apply_key_aliases,
        )

        result = apply_key_aliases({"year_from": 2020, "year_to": 2024})
        assert result == {"min_year": 2020, "max_year": 2024}

    async def test_limit_aliases(self):
        """Limit aliases should be mapped."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            apply_key_aliases,
        )

        result = apply_key_aliases({"max_results": 20})
        assert result == {"limit": 20}

    async def test_standard_key_preserved(self):
        """Standard key should not be overwritten by alias."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            apply_key_aliases,
        )

        # If both standard and alias present, standard wins
        result = apply_key_aliases({"min_year": 2020, "year_from": 2019})
        assert result["min_year"] == 2020

    async def test_unknown_keys_preserved(self):
        """Unknown keys should pass through."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            apply_key_aliases,
        )

        result = apply_key_aliases({"query": "test", "custom_param": 123})
        assert result == {"query": "test", "custom_param": 123}
