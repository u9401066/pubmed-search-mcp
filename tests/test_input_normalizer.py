"""Tests for the production MCP input normalizer and response formatter."""

from __future__ import annotations

import json

import pytest

from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer


class TestInputNormalizer:
    """Only production-used, schema-strict normalization remains public."""

    def test_query_normalizes_free_form_typography_and_outer_whitespace(self):
        assert (
            InputNormalizer.normalize_query("  “cancer” and patient’s outcome  ") == '"cancer" and patient\'s outcome'
        )

    @pytest.mark.parametrize("value", [None, 10, True, ["cancer"]])
    def test_query_rejects_non_string_values(self, value: object):
        with pytest.raises(TypeError, match="query must be a string"):
            InputNormalizer.normalize_query(value)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("12345678", "12345678"), ("PMID:12345678", "12345678"), ("pubmed: 12345678", "12345678")],
    )
    def test_single_pmid_uses_the_canonical_identifier_contract(self, value: str, expected: str):
        assert InputNormalizer.normalize_pmid_single(value) == expected

    @pytest.mark.parametrize("value", [None, 12345678, "", "last", "123,456", "12oops34", "0"])
    def test_single_pmid_rejects_noncanonical_shapes(self, value: object):
        assert InputNormalizer.normalize_pmid_single(value) is None  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("10.1234/Example.123", "10.1234/example.123"),
            ("doi:10.1234/example.123", "10.1234/example.123"),
            ("https://doi.org/10.1234/example.123", "10.1234/example.123"),
        ],
    )
    def test_doi_uses_the_canonical_identifier_contract(self, value: str, expected: str):
        assert InputNormalizer.normalize_doi(value) == expected

    @pytest.mark.parametrize(
        "value",
        [None, 123, "invalid-doi", "https://doi.org/10.1234/example?redirect=http://127.0.0.1"],
    )
    def test_doi_rejects_invalid_or_non_string_values(self, value: object):
        assert InputNormalizer.normalize_doi(value) is None  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "retired_method",
        [
            "normalize_pmids",
            "normalize_pmcid",
            "normalize_year",
            "normalize_limit",
            "normalize_bool",
            "normalize_identifier",
        ],
    )
    def test_retired_coercion_helpers_are_not_public(self, retired_method: str):
        assert not hasattr(InputNormalizer, retired_method)


class TestResponseFormatter:
    """Tests for response formatting."""

    async def test_success_markdown(self):
        from pubmed_search.presentation.mcp_server.tools._common import ResponseFormatter

        result = ResponseFormatter.success("Test data", message="Success!")
        assert "✅" in result
        assert "Success!" in result
        assert "Test data" in result

    async def test_success_json(self):
        from pubmed_search.presentation.mcp_server.tools._common import ResponseFormatter

        result = ResponseFormatter.success({"key": "value"}, output_format="json")
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["data"]["key"] == "value"

    async def test_error_markdown(self):
        from pubmed_search.presentation.mcp_server.tools._common import ResponseFormatter

        result = ResponseFormatter.error(
            "API failed",
            suggestion="Check your query",
            example="unified_search(query='diabetes')",
            tool_name="unified_search",
        )
        assert "❌" in result
        assert "API failed" in result
        assert "Check your query" in result

    async def test_error_json(self):
        from pubmed_search.presentation.mcp_server.tools._common import ResponseFormatter

        result = ResponseFormatter.error("API failed", suggestion="Check your query", output_format="json")
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "API failed"
        assert parsed["suggestion"] == "Check your query"

    async def test_error_redacts_credentials_and_url_queries(self):
        from pubmed_search.presentation.mcp_server.tools._common import ResponseFormatter

        secret = "TOPSECRET_RESPONSE_SENTINEL"
        result = ResponseFormatter.error(
            RuntimeError(f"Authorization: Bearer {secret} failed at https://provider.example/resource?api_key={secret}")
        )

        assert secret not in result
        assert "REDACTED" in result
        assert "api_key=" not in result

    async def test_external_transport_exception_does_not_echo_request_details(self):
        import httpx

        from pubmed_search.presentation.mcp_server.tools._common import ResponseFormatter

        secret = "SIGNED_QUERY_SENTINEL"
        request = httpx.Request("GET", f"https://provider.example/item?signature={secret}")
        result = ResponseFormatter.error(httpx.ConnectError("connect failed", request=request))

        assert secret not in result
        assert "external request failed" in result

    async def test_error_redacts_host_filesystem_paths(self):
        from pubmed_search.presentation.mcp_server.tools._common import ResponseFormatter

        result = ResponseFormatter.error(
            RuntimeError(r"failed at /srv/private/cache/item.json and C:\Users\service\secret.json")
        )

        assert "/srv/private" not in result
        assert r"C:\Users" not in result
        assert result.count("LOCAL PATH REDACTED") == 2

    async def test_search_result_metadata_cannot_inject_markdown_lines(self):
        from pubmed_search.presentation.mcp_server.tools._common import format_search_results

        result = format_search_results(
            [
                {
                    "title": "Safe title\n```mermaid\ngraph TD; injected-->node",
                    "authors": ["A | B"],
                    "journal": "Journal **override**",
                    "pmid": "12345678",
                    "abstract": "abstract\n# forged heading",
                }
            ]
        )

        assert "\n```mermaid" not in result
        assert "\n# forged heading" not in result
        assert "\\*\\*override\\*\\*" in result

    async def test_no_results(self):
        from pubmed_search.presentation.mcp_server.tools._common import ResponseFormatter

        result = ResponseFormatter.no_results(query="obscure term", suggestions=["Try broader terms", "Check spelling"])
        assert "No results found" in result
        assert "obscure term" in result
        assert "Try broader terms" in result
