"""Regression tests for fail-fast schemas on formerly permissive MCP tools."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver import MCPServer

from pubmed_search.application.search.pico_plan import MAX_PICO_RESULTS
from pubmed_search.presentation.mcp_server.session_tools import register_session_tools
from pubmed_search.presentation.mcp_server.tool_contracts import tool_meta
from pubmed_search.presentation.mcp_server.tools.discovery import (
    MAX_CITATION_COUNT_FILTER,
    MAX_RCR_FILTER,
    register_discovery_tools,
)
from pubmed_search.presentation.mcp_server.tools.export import register_export_tools
from pubmed_search.presentation.mcp_server.tools.icd import register_icd_tools
from pubmed_search.presentation.mcp_server.tools.image_search import register_image_search_tools
from pubmed_search.presentation.mcp_server.tools.ncbi_extended import register_ncbi_extended_tools
from pubmed_search.presentation.mcp_server.tools.pico import register_pico_tools
from pubmed_search.presentation.mcp_server.tools.strategy import register_strategy_tools


def _schemas() -> dict[str, dict]:
    mcp = MCPServer("schema-hardening")
    searcher = MagicMock()
    register_ncbi_extended_tools(mcp)
    register_strategy_tools(mcp, searcher)
    register_discovery_tools(mcp, searcher)
    register_pico_tools(mcp)
    register_icd_tools(mcp)
    register_image_search_tools(mcp, MagicMock())
    register_export_tools(mcp, searcher)
    register_session_tools(mcp, MagicMock())
    return {name: tool.parameters for name, tool in mcp._tool_manager._tools.items()}


def test_query_and_limit_bounds_are_machine_readable() -> None:
    schemas = _schemas()
    assert schemas["search_gene"]["properties"]["query"]["maxLength"] == 500
    assert schemas["search_gene"]["properties"]["limit"]["maximum"] == 50
    gene_id = schemas["get_gene_literature"]["properties"]["gene_id"]
    assert gene_id["type"] == "string"
    assert gene_id["pattern"] == "^[1-9][0-9]{0,19}$"
    assert schemas["generate_search_queries"]["properties"]["topic"]["maxLength"] == 2_000
    assert schemas["search_biomedical_images"]["properties"]["limit"]["maximum"] == 50
    citation_properties = schemas["get_citation_metrics"]["properties"]
    assert citation_properties["min_citations"]["anyOf"][0]["maximum"] == MAX_CITATION_COUNT_FILTER
    assert citation_properties["min_rcr"]["anyOf"][0]["maximum"] == MAX_RCR_FILTER
    session_schema = schemas["read_session"]
    assert session_schema["properties"]["request"]["discriminator"]["propertyName"] == "action"
    assert session_schema["$defs"]["SessionArtifactRequest"]["properties"]["max_chars"]["maximum"] == 200_000
    note_pmids = schemas["save_literature_notes"]["properties"]["pmids"]["anyOf"]
    assert next(branch for branch in note_pmids if branch.get("type") == "array")["maxItems"] == 1_000
    assert next(branch for branch in note_pmids if branch.get("type") == "string")["maxLength"] == 100_000


def test_closed_options_are_json_schema_enums() -> None:
    schemas = _schemas()
    assert schemas["generate_search_queries"]["properties"]["strategy"]["enum"] == [
        "comprehensive",
        "focused",
        "exploratory",
    ]
    assert set(schemas["search_biomedical_images"]["properties"]["image_type"]["anyOf"][0]["enum"]) == {
        "xg",
        "xm",
        "x",
        "u",
        "ph",
        "p",
        "mc",
        "m",
        "g",
        "c",
    }
    assert schemas["save_literature_notes"]["properties"]["note_format"]["enum"] == [
        "wiki",
        "foam",
        "markdown",
        "medpaper",
    ]
    session_request = schemas["read_session"]["properties"]["request"]
    assert "replay_search" in session_request["discriminator"]["mapping"]
    assert len(session_request["oneOf"]) == 9


def test_pico_and_icd_use_unambiguous_structured_contracts() -> None:
    schemas = _schemas()
    pico = schemas["validate_pico_plan"]["properties"]
    assert pico["sources"]["anyOf"][0]["type"] == "array"
    assert pico["sources"]["anyOf"][0]["minItems"] == 1
    assert pico["sources"]["anyOf"][0]["maxItems"] == 5
    assert "pubmed" in pico["sources"]["anyOf"][0]["items"]["enum"]
    assert pico["limit"]["maximum"] == MAX_PICO_RESULTS

    icd = schemas["convert_icd_mesh"]
    assert set(icd["required"]) == {"direction", "value"}
    assert set(icd["properties"]["direction"]["enum"]) == {"icd_to_mesh", "mesh_to_icd"}
    assert "code" not in icd["properties"]
    assert "mesh_term" not in icd["properties"]


def test_unknown_tool_has_no_fallback_contract_category() -> None:
    with pytest.raises(ValueError, match="Unknown canonical MCP tool"):
        tool_meta("retired_tool_name")
