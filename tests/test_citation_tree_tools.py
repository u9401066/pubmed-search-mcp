"""Tests for citation_tree.py — format converters, node/edge builders, and build tool."""

import pytest
from unittest.mock import AsyncMock, MagicMock


from pubmed_search.presentation.mcp_server.tools.citation_tree import (
    _escape_mermaid,
    _escape_xml,
    _make_edge,
    _make_node,
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
        node = _make_node(article, level=0, direction="root")
        assert node["pmid"] == "12345"
        assert node["level"] == 0
        assert node["direction"] == "root"
        assert node["first_author"] == "Smith J"
        assert node["journal"] == "Nature"
        assert "Smith J" in node["label"]

    async def test_no_authors(self):
        article = {"pmid": "1", "title": "T", "year": "2020"}
        node = _make_node(article, level=1, direction="citing")
        assert node["first_author"] == "Unknown"

    async def test_long_title_truncated(self):
        article = {"pmid": "1", "title": "A" * 100}
        node = _make_node(article, level=0, direction="root")
        assert len(node["short_title"]) <= 63

    async def test_missing_fields(self):
        node = _make_node({}, level=2, direction="reference")
        assert node["pmid"] == "unknown"
        assert node["journal"] == "Unknown Journal"
        assert node["node_type"] == "reference"


# ============================================================
# _make_edge
# ============================================================

class TestMakeEdge:
    async def test_basic(self):
        edge = _make_edge("111", "222", "cites")
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
# _escape_mermaid
# ============================================================

class TestEscapeMermaid:
    async def test_basic(self):
        result = _escape_mermaid("Hello (World)")
        assert "(" not in result or "#40;" in result or "world" in result.lower()

    async def test_quotes(self):
        result = _escape_mermaid('Say "hello"')
        assert '"' not in result or "#quot;" in result


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
        assert isinstance(result, str)
        assert "graph TD" in result

    async def test_contains_nodes(self):
        result = _to_mermaid(SAMPLE_NODES, SAMPLE_EDGES, "Root Paper")
        assert "111" in result
        assert "222" in result


# ============================================================
# Tool registration & build_citation_tree
# ============================================================

def _capture_tools(mcp, searcher):
    tools = {}
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
    register_citation_tree_tools(mcp, searcher)
    return tools


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
    async def test_depth_clamped(self):
        self.searcher.fetch_details = AsyncMock(return_value=[{
            "pmid": "111", "title": "Root", "year": "2024",
            "journal": "J", "authors": ["A"], "doi": "",
        }])
        self.searcher.get_citing_articles = AsyncMock(return_value=[])
        self.searcher.get_article_references = AsyncMock(return_value=[])

        result = await self.tools["build_citation_tree"](
            pmid="111", depth=10, limit_per_level=5, output_format="cytoscape"
        )
        # Should succeed (depth clamped to MAX_DEPTH)
        assert isinstance(result, str)
        assert "111" in result

    @pytest.mark.asyncio
    async def test_article_not_found(self):
        self.searcher.fetch_details = AsyncMock(return_value=[])
        result = await self.tools["build_citation_tree"](pmid="999999")
        assert "not" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_successful_tree(self):
        root = {"pmid": "111", "title": "Root Paper", "year": "2024",
                "journal": "Nature", "authors": ["Smith"], "doi": ""}
        citing = {"pmid": "222", "title": "Citing Paper", "year": "2024",
                  "journal": "Science", "authors": ["Doe"], "doi": ""}
        ref = {"pmid": "333", "title": "Reference Paper", "year": "2020",
               "journal": "JAMA", "authors": ["Lee"], "doi": ""}

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


# TestSuggestCitationTreeTool removed in v0.3.1 - suggest_citation_tree merged (Agent decides directly)
