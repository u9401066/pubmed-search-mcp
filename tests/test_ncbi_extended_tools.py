"""Tests for ncbi_extended MCP tools — search_gene, get_gene_details, etc."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.presentation.mcp_server.tools.ncbi_extended import (
    register_ncbi_extended_tools,
)


def _capture_tools(mcp):
    """Capture registered tool functions from register call."""
    tools = {}
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
    register_ncbi_extended_tools(mcp)
    return tools


@pytest.fixture
def tools():
    mcp = MagicMock()
    return _capture_tools(mcp)


# ============================================================
# search_gene
# ============================================================


class TestSearchGeneTool:
    @pytest.mark.asyncio
    async def test_empty_query(self, tools):
        result = await tools["search_gene"](query="")
        assert "error" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_success(self, tools):
        mock_client = AsyncMock()
        mock_client.search_gene.return_value = [{"gene_id": "672", "symbol": "BRCA1", "name": "BRCA1 DNA repair"}]
        with patch(
            "pubmed_search.infrastructure.sources.get_ncbi_extended_client",
            return_value=mock_client,
        ):
            result = await tools["search_gene"](query="BRCA1", organism="human")
        parsed = json.loads(result)
        assert parsed["count"] == 1
        assert parsed["genes"][0]["symbol"] == "BRCA1"

    @pytest.mark.asyncio
    async def test_no_results(self, tools):
        mock_client = AsyncMock()
        mock_client.search_gene.return_value = []
        with patch(
            "pubmed_search.infrastructure.sources.get_ncbi_extended_client",
            return_value=mock_client,
        ):
            result = await tools["search_gene"](query="zzzznonexistent")
        assert "no" in result.lower() or "suggest" in result.lower()

    @pytest.mark.asyncio
    async def test_upstream_failure_is_not_reported_as_no_results(self, tools):
        mock_client = AsyncMock()
        mock_client.search_gene.side_effect = RuntimeError("token=secret /srv/private/gene-cache")
        with patch(
            "pubmed_search.infrastructure.sources.get_ncbi_extended_client",
            return_value=mock_client,
        ):
            result = await tools["search_gene"](query="BRCA1")
        assert "NCBI Gene search could not be completed" in result
        assert "secret" not in result
        assert "/srv/private" not in result
        assert "No results" not in result


# ============================================================
# get_gene_details
# ============================================================


class TestGetGeneDetailsTool:
    @pytest.mark.asyncio
    async def test_missing_gene_id(self, tools):
        result = await tools["get_gene_details"](gene_id=None)
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_success(self, tools):
        mock_client = AsyncMock()
        mock_client.get_gene.return_value = {"gene_id": "672", "symbol": "BRCA1"}
        with patch(
            "pubmed_search.infrastructure.sources.get_ncbi_extended_client",
            return_value=mock_client,
        ):
            result = await tools["get_gene_details"](gene_id="672")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["gene"]["symbol"] == "BRCA1"

    @pytest.mark.parametrize("invalid_id", [672, 0, -1, "12.3", "１２３", "672 ", "672 trailing"])
    @pytest.mark.asyncio
    async def test_invalid_gene_id_fails_closed(self, tools, invalid_id):
        result = await tools["get_gene_details"](gene_id=invalid_id)
        assert "digit string" in result.lower() or "positive ascii digits" in result.lower()

    @pytest.mark.asyncio
    async def test_not_found(self, tools):
        mock_client = AsyncMock()
        mock_client.get_gene.return_value = None
        with patch(
            "pubmed_search.infrastructure.sources.get_ncbi_extended_client",
            return_value=mock_client,
        ):
            result = await tools["get_gene_details"](gene_id="99999999")
        assert "not found" in result.lower() or "no" in result.lower()


# ============================================================
# get_gene_literature
# ============================================================


class TestGetGeneLiteratureTool:
    @pytest.mark.asyncio
    async def test_missing_gene_id(self, tools):
        result = await tools["get_gene_literature"](gene_id=None)
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_success(self, tools):
        mock_client = AsyncMock()
        mock_client.get_gene_pubmed_links.return_value = ["12345", "67890"]
        with patch(
            "pubmed_search.infrastructure.sources.get_ncbi_extended_client",
            return_value=mock_client,
        ):
            result = await tools["get_gene_literature"](gene_id="672", limit=10)
        parsed = json.loads(result)
        assert parsed["pubmed_count"] == 2
        assert "12345" in parsed["pmids"]


# ============================================================
# search_compound
# ============================================================


class TestSearchCompoundTool:
    @pytest.mark.asyncio
    async def test_empty_query(self, tools):
        result = await tools["search_compound"](query="")
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_success(self, tools):
        mock_client = AsyncMock()
        mock_client.search_compound.return_value = [{"cid": "2244", "name": "Aspirin"}]
        with patch(
            "pubmed_search.infrastructure.sources.get_ncbi_extended_client",
            return_value=mock_client,
        ):
            result = await tools["search_compound"](query="aspirin")
        parsed = json.loads(result)
        assert parsed["count"] == 1


# ============================================================
# get_compound_details
# ============================================================


class TestGetCompoundDetailsTool:
    @pytest.mark.asyncio
    async def test_missing_cid(self, tools):
        result = await tools["get_compound_details"](cid=None)
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_success(self, tools):
        mock_client = AsyncMock()
        mock_client.get_compound.return_value = {"cid": "2244", "name": "Aspirin"}
        with patch(
            "pubmed_search.infrastructure.sources.get_ncbi_extended_client",
            return_value=mock_client,
        ):
            result = await tools["get_compound_details"](cid="2244")
        parsed = json.loads(result)
        assert parsed["status"] == "success"
        assert parsed["compound"]["name"] == "Aspirin"

    @pytest.mark.asyncio
    async def test_integer_cid_is_rejected_without_coercion(self, tools):
        result = await tools["get_compound_details"](cid=2244)
        assert "digit string" in result.lower()

    @pytest.mark.asyncio
    async def test_not_found(self, tools):
        mock_client = AsyncMock()
        mock_client.get_compound.return_value = None
        with patch(
            "pubmed_search.infrastructure.sources.get_ncbi_extended_client",
            return_value=mock_client,
        ):
            result = await tools["get_compound_details"](cid="99999999")
        assert "not found" in result.lower() or "no" in result.lower()


# ============================================================
# get_compound_literature
# ============================================================


class TestGetCompoundLiteratureTool:
    @pytest.mark.asyncio
    async def test_missing_cid(self, tools):
        result = await tools["get_compound_literature"](cid=None)
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_success(self, tools):
        mock_client = AsyncMock()
        mock_client.get_compound_pubmed_links.return_value = ["111", "222"]
        with patch(
            "pubmed_search.infrastructure.sources.get_ncbi_extended_client",
            return_value=mock_client,
        ):
            result = await tools["get_compound_literature"](cid="2244")
        parsed = json.loads(result)
        assert parsed["pubmed_count"] == 2


# ============================================================
# search_clinvar
# ============================================================


class TestSearchClinvarTool:
    @pytest.mark.asyncio
    async def test_empty_query(self, tools):
        result = await tools["search_clinvar"](query="")
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_success(self, tools):
        mock_client = AsyncMock()
        mock_client.search_clinvar.return_value = [{"variant_id": "1", "gene": "BRCA1", "significance": "Pathogenic"}]
        with patch(
            "pubmed_search.infrastructure.sources.get_ncbi_extended_client",
            return_value=mock_client,
        ):
            result = await tools["search_clinvar"](query="BRCA1")
        parsed = json.loads(result)
        assert parsed["count"] == 1

    @pytest.mark.asyncio
    async def test_overlong_query_is_rejected_before_client_creation(self, tools):
        with patch("pubmed_search.infrastructure.sources.get_ncbi_extended_client") as client_factory:
            result = await tools["search_clinvar"](query="x" * 501)
        assert "exceeds 500" in result
        client_factory.assert_not_called()
