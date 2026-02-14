"""Tests for export MCP tools — prepare_export, helpers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.presentation.mcp_server.tools.export import (
    _format_export_response,
    _get_file_extension,
    _resolve_pmids,
    register_export_tools,
)

# ============================================================
# Pure helpers
# ============================================================


class TestGetFileExtension:
    async def test_ris(self):
        assert _get_file_extension("ris") == "ris"

    async def test_bibtex(self):
        assert _get_file_extension("bibtex") == "bib"

    async def test_csv(self):
        assert _get_file_extension("csv") == "csv"

    async def test_medline(self):
        assert _get_file_extension("medline") == "txt"

    async def test_json(self):
        assert _get_file_extension("json") == "json"

    async def test_csl(self):
        assert _get_file_extension("csl") == "json"

    async def test_unknown(self):
        assert _get_file_extension("xyz") == "txt"


class TestFormatExportResponse:
    async def test_small_export(self):
        result = _format_export_response("TY  - JOUR\n", "ris", 5, source="official")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["article_count"] == 5
        assert "export_text" in parsed

    async def test_large_export_saves_file(self):
        result = _format_export_response("content", "ris", 25, source="local")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert "file_path" in parsed


class TestResolvePmids:
    async def test_comma_separated(self):
        result = _resolve_pmids("111,222,333")
        assert result == ["111", "222", "333"]

    async def test_last_no_session(self):
        with patch(
            "pubmed_search.presentation.mcp_server.tools.export.get_session_manager",
            return_value=None,
        ):
            result = _resolve_pmids("last")
        assert result == []

    async def test_last_with_session(self):
        mock_sm = MagicMock()
        session = MagicMock()
        session.search_history = [{"pmids": ["111", "222"]}]
        mock_sm.get_or_create_session.return_value = session

        with patch(
            "pubmed_search.presentation.mcp_server.tools.export.get_session_manager",
            return_value=mock_sm,
        ):
            result = _resolve_pmids("last")
        assert result == ["111", "222"]


# ============================================================
# prepare_export tool
# ============================================================


def _capture_tools(mcp, searcher):
    tools = {}
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
    register_export_tools(mcp, searcher)
    return tools


class TestPrepareExport:
    @pytest.mark.asyncio
    async def test_no_pmids(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        tools = _capture_tools(mcp, searcher)

        result = await tools["prepare_export"](pmids="", format="ris")
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_official_ris(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        tools = _capture_tools(mcp, searcher)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.content = "TY  - JOUR\nER  -\n"
        mock_result.pmid_count = 1

        with patch(
            "pubmed_search.presentation.mcp_server.tools.export.export_citations_official",
            return_value=mock_result,
        ):
            result = await tools["prepare_export"](pmids="12345678", format="ris", source="official")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["source"] == "official"

    @pytest.mark.asyncio
    async def test_local_bibtex(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        searcher.fetch_details.return_value = [{"pmid": "123", "title": "T", "authors": ["A"]}]
        tools = _capture_tools(mcp, searcher)

        with patch(
            "pubmed_search.presentation.mcp_server.tools.export.export_articles",
            return_value="@article{123,\n  title={T}\n}",
        ):
            result = await tools["prepare_export"](pmids="123", format="bibtex", source="local")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["format"] == "bibtex"

    @pytest.mark.asyncio
    async def test_unsupported_format(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        tools = _capture_tools(mcp, searcher)

        result = await tools["prepare_export"](pmids="123", format="xyz", source="official")
        assert "unsupported" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_official_api_failure_falls_back(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        searcher.fetch_details.return_value = [{"pmid": "123", "title": "T"}]
        tools = _capture_tools(mcp, searcher)

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "API down"

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.export.export_citations_official",
                return_value=mock_result,
            ),
            patch(
                "pubmed_search.presentation.mcp_server.tools.export.export_articles",
                return_value="TY  - JOUR\n",
            ),
        ):
            result = await tools["prepare_export"](pmids="123", format="ris", source="official")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["source"] == "local"

    @pytest.mark.asyncio
    async def test_exception_handling(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        tools = _capture_tools(mcp, searcher)

        with patch(
            "pubmed_search.presentation.mcp_server.tools.export.export_citations_official",
            side_effect=RuntimeError("network error"),
        ):
            result = await tools["prepare_export"](pmids="123", format="ris", source="official")
        assert "error" in result.lower()
