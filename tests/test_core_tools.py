"""Tests for CORE MCP tools — search_core, get_core_paper, etc."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.presentation.mcp_server.tools.core import register_core_tools


def _capture_tools(mcp):
    tools = {}
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
    register_core_tools(mcp)
    return tools


@pytest.fixture
def tools():
    return _capture_tools(MagicMock())


# ============================================================
# search_core
# ============================================================


class TestSearchCore:
    @pytest.mark.asyncio
    async def test_empty_query(self, tools):
        result = await tools["search_core"](query="")
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_success(self, tools):
        mock_client = AsyncMock()
        mock_client.search.return_value = {
            "results": [{"title": "Paper1", "id": "123"}],
            "total_hits": 42,
        }
        with patch(
            "pubmed_search.infrastructure.sources.core.get_core_client",
            return_value=mock_client,
        ):
            result = await tools["search_core"](query="machine learning")
        parsed = json.loads(result)
        assert parsed["total_hits"] == 42

    @pytest.mark.asyncio
    async def test_no_results(self, tools):
        mock_client = AsyncMock()
        mock_client.search.return_value = {"results": []}
        with patch(
            "pubmed_search.infrastructure.sources.core.get_core_client",
            return_value=mock_client,
        ):
            result = await tools["search_core"](query="xyznonexistent")
        assert "no" in result.lower()

    @pytest.mark.asyncio
    async def test_exception(self, tools):
        with patch(
            "pubmed_search.infrastructure.sources.core.get_core_client",
            side_effect=RuntimeError("API down"),
        ):
            result = await tools["search_core"](query="test")
        assert "error" in result.lower()


# ============================================================
# search_core_fulltext
# ============================================================


class TestSearchCoreFulltext:
    @pytest.mark.asyncio
    async def test_empty_query(self, tools):
        result = await tools["search_core_fulltext"](query="")
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_success(self, tools):
        mock_client = AsyncMock()
        mock_client.search_fulltext.return_value = {
            "results": [{"title": "FT Paper"}],
            "total_hits": 5,
        }
        with patch(
            "pubmed_search.infrastructure.sources.core.get_core_client",
            return_value=mock_client,
        ):
            result = await tools["search_core_fulltext"](query="propofol")
        parsed = json.loads(result)
        assert parsed["total_hits"] == 5

    @pytest.mark.asyncio
    async def test_no_results(self, tools):
        mock_client = AsyncMock()
        mock_client.search_fulltext.return_value = {"results": []}
        with patch(
            "pubmed_search.infrastructure.sources.core.get_core_client",
            return_value=mock_client,
        ):
            result = await tools["search_core_fulltext"](query="nonfound")
        assert "no" in result.lower()


# ============================================================
# get_core_paper
# ============================================================


class TestGetCorePaper:
    @pytest.mark.asyncio
    async def test_missing_id(self, tools):
        result = await tools["get_core_paper"](core_id=None)
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_found(self, tools):
        mock_client = AsyncMock()
        mock_client.get_work.return_value = {"id": "123", "title": "Paper"}
        with patch(
            "pubmed_search.infrastructure.sources.core.get_core_client",
            return_value=mock_client,
        ):
            result = await tools["get_core_paper"](core_id="123")
        parsed = json.loads(result)
        assert parsed["title"] == "Paper"

    @pytest.mark.asyncio
    async def test_not_found(self, tools):
        mock_client = AsyncMock()
        mock_client.get_work.return_value = None
        with patch(
            "pubmed_search.infrastructure.sources.core.get_core_client",
            return_value=mock_client,
        ):
            result = await tools["get_core_paper"](core_id="999")
        assert "not found" in result.lower() or "no" in result.lower()


# ============================================================
# get_core_fulltext
# ============================================================


class TestGetCoreFulltext:
    @pytest.mark.asyncio
    async def test_missing_id(self, tools):
        result = await tools["get_core_fulltext"](core_id=None)
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_found(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext.return_value = "The full text of the paper."
        with patch(
            "pubmed_search.infrastructure.sources.core.get_core_client",
            return_value=mock_client,
        ):
            result = await tools["get_core_fulltext"](core_id="123")
        parsed = json.loads(result)
        assert parsed["truncated"] is False
        assert "full text" in parsed["content"]

    @pytest.mark.asyncio
    async def test_truncated(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext.return_value = "x" * 60000
        with patch(
            "pubmed_search.infrastructure.sources.core.get_core_client",
            return_value=mock_client,
        ):
            result = await tools["get_core_fulltext"](core_id="123")
        parsed = json.loads(result)
        assert parsed["truncated"] is True

    @pytest.mark.asyncio
    async def test_not_available(self, tools):
        mock_client = AsyncMock()
        mock_client.get_fulltext.return_value = None
        with patch(
            "pubmed_search.infrastructure.sources.core.get_core_client",
            return_value=mock_client,
        ):
            result = await tools["get_core_fulltext"](core_id="123")
        assert "not available" in result.lower() or "no" in result.lower()


# ============================================================
# find_in_core
# ============================================================


class TestFindInCore:
    @pytest.mark.asyncio
    async def test_missing_identifier(self, tools):
        result = await tools["find_in_core"](identifier=None)
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_doi_found(self, tools):
        mock_client = AsyncMock()
        mock_client.search_by_doi.return_value = {"title": "DOI Paper"}
        with patch(
            "pubmed_search.infrastructure.sources.core.get_core_client",
            return_value=mock_client,
        ):
            result = await tools["find_in_core"](
                identifier="10.1234/test", identifier_type="doi"
            )
        parsed = json.loads(result)
        assert parsed["title"] == "DOI Paper"

    @pytest.mark.asyncio
    async def test_pmid_found(self, tools):
        mock_client = AsyncMock()
        mock_client.search_by_pmid.return_value = {"title": "PMID Paper"}
        with patch(
            "pubmed_search.infrastructure.sources.core.get_core_client",
            return_value=mock_client,
        ):
            result = await tools["find_in_core"](
                identifier="12345678", identifier_type="pmid"
            )
        parsed = json.loads(result)
        assert parsed["title"] == "PMID Paper"

    @pytest.mark.asyncio
    async def test_unknown_type(self, tools):
        result = await tools["find_in_core"](identifier="xxx", identifier_type="isbn")
        assert "error" in result.lower() or "unknown" in result.lower()

    @pytest.mark.asyncio
    async def test_not_found(self, tools):
        mock_client = AsyncMock()
        mock_client.search_by_doi.return_value = None
        with patch(
            "pubmed_search.infrastructure.sources.core.get_core_client",
            return_value=mock_client,
        ):
            result = await tools["find_in_core"](
                identifier="10.9999/nonexistent", identifier_type="doi"
            )
        assert "not found" in result.lower() or "no" in result.lower()
