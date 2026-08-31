"""Tests for citation_tree.py — format converters, node/edge builders, and build tool."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from pubmed_search.application.citation_network import make_citation_edge, make_citation_node
from pubmed_search.application.visualization import validate_mermaid_source
from pubmed_search.presentation.mcp_server.tools.citation_tree import (
    _escape_xml,
    _to_cytoscape,
    _to_d3,
    _to_g6,
    _to_graphml,
    _to_mermaid,
    _to_vis,
    register_citation_tree_tools,
)

# ============================================================
# _make_node
# ============================================================


class TestMakeNode:
    async def test_basic(self):
        article = {
            "pmid": "12345",
            "title": "My Research Paper",
            "year": "2024",
            "journal": "Nature",
            "authors": ["Smith J", "Doe A"],
            "doi": "10.1234/test",
        }
        node = make_citation_node(article, level=0, direction="root")
        assert node["pmid"] == "12345"
        assert node["level"] == 0
        assert node["direction"] == "root"
        assert node["first_author"] == "Smith J"
        assert node["journal"] == "Nature"
        assert "Smith J" in node["label"]

    async def test_no_authors(self):
        article = {"pmid": "1", "title": "T", "year": "2020"}
        node = make_citation_node(article, level=1, direction="citing")
        assert node["first_author"] == "Unknown"

    async def test_long_title_truncated(self):
        article = {"pmid": "1", "title": "A" * 100}
        node = make_citation_node(article, level=0, direction="root")
        assert len(node["short_title"]) <= 63

    async def test_missing_fields(self):
        node = make_citation_node({}, level=2, direction="reference")
        assert node["pmid"] == "unknown"
        assert node["journal"] == "Unknown Journal"
        assert node["node_type"] == "reference"


# ============================================================
# _make_edge
# ============================================================


class TestMakeEdge:
    async def test_basic(self):
        edge = make_citation_edge("111", "222")
        assert edge["source"] == "111"
        assert edge["target"] == "222"
        assert edge["edge_type"] == "cites"


# ============================================================
# _escape_xml
# ============================================================


class TestEscapeXml:
    async def test_ampersand(self):
        assert "&amp;" in _escape_xml("A & B")

    async def test_lt_gt(self):
        assert "&lt;" in _escape_xml("<tag>")
        assert "&gt;" in _escape_xml("<tag>")

    async def test_quotes(self):
        assert "&quot;" in _escape_xml('"hello"')
        assert "&apos;" in _escape_xml("it's")

    async def test_no_escaping_needed(self):
        assert _escape_xml("hello world") == "hello world"


# ============================================================
# Format converters
# ============================================================

SAMPLE_NODES = [
    {
        "pmid": "111",
        "label": "Smith (2024)",
        "title": "Paper A",
        "short_title": "Paper A",
        "year": "2024",
        "journal": "Nature",
        "authors": ["Smith"],
        "first_author": "Smith",
        "doi": "10.1/a",
        "level": 0,
        "direction": "root",
        "node_type": "root",
    },
    {
        "pmid": "222",
        "label": "Doe (2023)",
        "title": "Paper B",
        "short_title": "Paper B",
        "year": "2023",
        "journal": "Science",
        "authors": ["Doe"],
        "first_author": "Doe",
        "doi": "10.1/b",
        "level": 1,
        "direction": "citing",
        "node_type": "citing",
    },
]

SAMPLE_EDGES = [
    {"source": "222", "target": "111", "edge_type": "cites"},
]


class TestToCytoscape:
    async def test_structure(self):
        result = _to_cytoscape(SAMPLE_NODES, SAMPLE_EDGES)
        assert "nodes" in result
        assert "edges" in result
        assert len(result["nodes"]) == 2
        assert len(result["edges"]) == 1

    async def test_node_data(self):
        result = _to_cytoscape(SAMPLE_NODES, SAMPLE_EDGES)
        node = result["nodes"][0]
        assert "data" in node
        assert node["data"]["pmid"] == "111"

    async def test_empty(self):
        result = _to_cytoscape([], [])
        assert result["nodes"] == []
        assert result["edges"] == []


class TestToG6:
    async def test_structure(self):
        result = _to_g6(SAMPLE_NODES, SAMPLE_EDGES)
        assert "nodes" in result
        assert "edges" in result
        assert len(result["nodes"]) == 2

    async def test_node_has_id(self):
        result = _to_g6(SAMPLE_NODES, SAMPLE_EDGES)
        assert result["nodes"][0]["id"] == "111"


class TestToD3:
    async def test_structure(self):
        result = _to_d3(SAMPLE_NODES, SAMPLE_EDGES)
        assert "nodes" in result
        assert "links" in result  # D3 uses "links" not "edges"
        assert len(result["nodes"]) == 2

    async def test_link_has_source_target(self):
        result = _to_d3(SAMPLE_NODES, SAMPLE_EDGES)
        assert result["links"][0]["source"] == "222"
        assert result["links"][0]["target"] == "111"


class TestToVis:
    async def test_structure(self):
        result = _to_vis(SAMPLE_NODES, SAMPLE_EDGES)
        assert "nodes" in result
        assert "edges" in result

    async def test_edge_has_arrows(self):
        result = _to_vis(SAMPLE_NODES, SAMPLE_EDGES)
        assert result["edges"][0]["arrows"] == "to"


class TestToGraphml:
    async def test_returns_xml_string(self):
        result = _to_graphml(SAMPLE_NODES, SAMPLE_EDGES, "Test Tree")
        assert isinstance(result, str)
        assert "<?xml" in result
        assert "<graphml" in result
        assert "</graphml>" in result

    async def test_contains_nodes(self):
        result = _to_graphml(SAMPLE_NODES, SAMPLE_EDGES, "Test Tree")
        assert 'node id="111"' in result
        assert 'node id="222"' in result

    async def test_contains_edges(self):
        result = _to_graphml(SAMPLE_NODES, SAMPLE_EDGES, "Test Tree")
        assert 'source="222"' in result
        assert 'target="111"' in result

    async def test_escapes_special_chars(self):
        nodes = [{**SAMPLE_NODES[0], "title": "A & B <test>"}]
        result = _to_graphml(nodes, [], "Test")
        assert "&amp;" in result
        assert "&lt;" in result


class TestToMermaid:
    async def test_returns_string(self):
        result = _to_mermaid(SAMPLE_NODES, SAMPLE_EDGES, "Test")
        assert isinstance(result.source, str)
        assert result.source.startswith("flowchart TD")
        assert result.structural_valid is True

    async def test_contains_nodes(self):
        result = _to_mermaid(SAMPLE_NODES, SAMPLE_EDGES, "Root Paper")
        assert "111" in result.source
        assert "222" in result.source

    async def test_hostile_labels_are_single_line_and_directive_safe(self):
        hostile = [
            {
                **SAMPLE_NODES[0],
                "title": 'Break\r\n    injected["node"]\n%%{init: {}}%%```\u202e',
                "short_title": 'Break\r\n    injected["node"]\n%%{init: {}}%%```\u202e',
                "first_author": 'A"]\n    attack --> root',
            }
        ]
        result = _to_mermaid(hostile, [], "Hostile\r\n%%{init: {}}%%")
        valid, issues = validate_mermaid_source(result.source)
        assert valid, issues
        assert "%%{" not in result.source
        assert "```" not in result.source
        assert "\r" not in result.source
        assert "injected[" not in result.source


# ============================================================
# Tool registration & build_citation_tree
# ============================================================


def _capture_tools(mcp, searcher):
    tools = {}
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
    register_citation_tree_tools(mcp, searcher)
    return tools


def _result_payload(response: str) -> dict:
    return json.loads(response.split("\n---\n\n", 1)[1])


class TestBuildCitationTreeTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.searcher = MagicMock()
        self.tools = _capture_tools(self.mcp, self.searcher)

    @pytest.mark.asyncio
    async def test_invalid_pmid(self):
        result = await self.tools["build_citation_tree"](pmid="")
        assert "error" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_out_of_range_depth_is_rejected(self):
        self.searcher.fetch_details = AsyncMock(
            return_value=[
                {
                    "pmid": "111",
                    "title": "Root",
                    "year": "2024",
                    "journal": "J",
                    "authors": ["A"],
                    "doi": "",
                }
            ]
        )
        self.searcher.get_citing_articles = AsyncMock(return_value=[])
        self.searcher.get_article_references = AsyncMock(return_value=[])

        result = await self.tools["build_citation_tree"](
            pmid="111", depth=10, limit_per_level=5, output_format="cytoscape"
        )
        assert "depth must be an integer between 1 and 3" in result
        self.searcher.fetch_details.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_article_not_found(self):
        self.searcher.fetch_details = AsyncMock(return_value=[])
        result = await self.tools["build_citation_tree"](pmid="999999")
        assert "not" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_successful_tree(self):
        root = {
            "pmid": "111",
            "title": "Root Paper",
            "year": "2024",
            "journal": "Nature",
            "authors": ["Smith"],
            "doi": "",
        }
        citing = {
            "pmid": "222",
            "title": "Citing Paper",
            "year": "2024",
            "journal": "Science",
            "authors": ["Doe"],
            "doi": "",
        }
        ref = {
            "pmid": "333",
            "title": "Reference Paper",
            "year": "2020",
            "journal": "JAMA",
            "authors": ["Lee"],
            "doi": "",
        }

        self.searcher.fetch_details = AsyncMock(return_value=[root])
        self.searcher.get_citing_articles = AsyncMock(return_value=[citing])
        self.searcher.get_article_references = AsyncMock(return_value=[ref])

        result = await self.tools["build_citation_tree"](
            pmid="111", depth=1, limit_per_level=5, output_format="cytoscape"
        )
        assert "111" in result
        assert isinstance(result, str)
        # Should contain some tree/graph related content
        assert len(result) > 50

    @pytest.mark.asyncio
    async def test_tool_preserves_convergent_edges(self):
        self.searcher.fetch_details = AsyncMock(return_value=[{**SAMPLE_NODES[0], "pmid": "1", "authors": ["Root"]}])

        async def citing(pmid: str, _limit: int):
            return {
                "1": [
                    {**SAMPLE_NODES[1], "pmid": "2", "authors": ["A"]},
                    {**SAMPLE_NODES[1], "pmid": "3", "authors": ["B"]},
                ],
                "2": [{**SAMPLE_NODES[1], "pmid": "4", "authors": ["C"]}],
                "3": [{**SAMPLE_NODES[1], "pmid": "4", "authors": ["C"]}],
            }.get(pmid, [])

        self.searcher.get_citing_articles = AsyncMock(side_effect=citing)
        self.searcher.get_article_references = AsyncMock(return_value=[])

        response = await self.tools["build_citation_tree"](
            pmid="1",
            depth=2,
            direction="forward",
            output_format="cytoscape",
        )
        payload = _result_payload(response)
        retained_edges = {(row["data"]["source"], row["data"]["target"]) for row in payload["graph"]["edges"]}
        assert ("pmid_4", "pmid_2") in retained_edges
        assert ("pmid_4", "pmid_3") in retained_edges

    @pytest.mark.asyncio
    async def test_tool_discloses_partial_source_failure(self):
        self.searcher.fetch_details = AsyncMock(return_value=[{**SAMPLE_NODES[0], "pmid": "1", "authors": ["Root"]}])
        self.searcher.get_citing_articles = AsyncMock(side_effect=RuntimeError("private upstream detail"))
        self.searcher.get_article_references = AsyncMock(return_value=[])

        response = await self.tools["build_citation_tree"](pmid="1", depth=1, direction="both")
        payload = _result_payload(response)
        coverage = payload["metadata"]["coverage"]
        assert payload["status"] == "partial"
        assert coverage["failed_expansions"] == 1
        assert coverage["source_errors"][0]["kind"] == "source_exception"
        assert "private upstream detail" not in response

    @pytest.mark.asyncio
    async def test_tool_mermaid_includes_validation_contract(self):
        hostile = {
            **SAMPLE_NODES[0],
            "pmid": "1",
            "authors": ['A"]\r\n    injected --> node'],
            "title": "Title\r\n%%{init: {}}%% ``` \u202e",
            "short_title": "Title\r\n%%{init: {}}%% ``` \u202e",
        }
        self.searcher.fetch_details = AsyncMock(return_value=[hostile])
        self.searcher.get_citing_articles = AsyncMock(return_value=[])
        self.searcher.get_article_references = AsyncMock(return_value=[])

        response = await self.tools["build_citation_tree"](
            pmid="1",
            depth=1,
            output_format="mermaid",
        )
        payload = _result_payload(response)
        source = payload["graph"]
        assert payload["mermaid_validation"]["structural_valid"] is True
        assert source.startswith("flowchart TD\n")
        assert "%%{" not in source
        assert "```" not in source
        assert "\r" not in source


# TestSuggestCitationTreeTool removed in v0.3.1 - suggest_citation_tree merged (Agent decides directly)
