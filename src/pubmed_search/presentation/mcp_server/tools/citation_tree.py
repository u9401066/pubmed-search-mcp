"""
Citation Tree Tools - Build citation network from a single article.

This module provides tools to build and visualize citation trees,
tracing the research lineage of a scientific paper both forward
(who cites this paper) and backward (what this paper cites).

Tool:
- build_citation_tree: Build and visualize citation network (6 output formats)

Supports multiple output formats:
- cytoscape: Cytoscape.js compatible JSON (academic standard)
- g6: AntV G6 format (modern, high-performance)
- d3: D3.js force graph format (flexible)
- vis: vis-network format (simple)
- graphml: GraphML for Gephi/VOSviewer (desktop tools)
- mermaid: Mermaid diagram (VS Code preview, Markdown)
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field

from pubmed_search.application.citation_network import (
    CitationBuildError,
    CitationNetworkConfig,
    CitationNetworkResult,
    CitationNetworkService,
)
from pubmed_search.application.visualization import (
    MermaidGraphBuilder,
    MermaidRenderResult,
    render_mermaid_graph,
    validate_mermaid_source,
)
from pubmed_search.domain.value_objects import IdentifierValidationError, normalize_pmid
from pubmed_search.shared.markdown import escape_markdown_text

from ._common import ResponseFormatter
from .tool_session import get_tool_session_runtime

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)

# Constants
MAX_DEPTH = 3  # Maximum allowed depth to prevent API overload
DEFAULT_LIMIT_PER_LEVEL = 5
MAX_TOTAL_NODES = 100  # Safety limit
MAX_CONCURRENT_FETCHES = 6
CITATION_TREE_TIMEOUT_SECONDS = 45.0

# Supported output formats
SUPPORTED_FORMATS = ["cytoscape", "g6", "d3", "vis", "graphml", "mermaid"]
CitationDirection = Literal["forward", "backward", "both"]
CitationOutputFormat = Literal["cytoscape", "g6", "d3", "vis", "graphml", "mermaid"]
CitationPMID = Annotated[str, Field(strict=True, min_length=1, max_length=512)]
CitationDepth = Annotated[int, Field(strict=True, ge=1, le=MAX_DEPTH)]
CitationLimit = Annotated[int, Field(strict=True, ge=1, le=20)]
FORMAT_INFO = {
    "cytoscape": {
        "name": "Cytoscape.js",
        "description": "Academic standard, bioinformatics",
        "usage": "cy.add(result.graph)",
    },
    "g6": {
        "name": "AntV G6",
        "description": "Modern, high-performance, TypeScript",
        "usage": "graph.data(result.graph); graph.render();",
    },
    "d3": {
        "name": "D3.js Force Graph",
        "description": "Most flexible, Observable notebooks",
        "usage": "forceSimulation(result.graph.nodes)",
    },
    "vis": {
        "name": "vis-network",
        "description": "Simple, easy prototypes",
        "usage": "new vis.Network(container, result.graph)",
    },
    "graphml": {
        "name": "GraphML (XML)",
        "description": "Gephi, VOSviewer, yEd, Pajek",
        "usage": "Import XML file into desktop tool",
    },
    "mermaid": {
        "name": "Mermaid Diagram",
        "description": "VS Code Markdown preview, documentation",
        "usage": "Paste into ```mermaid code block in Markdown",
    },
}


def _validate_tree_identifiers_and_bounds(
    pmid: object,
    depth: object,
    limit_per_level: object,
) -> tuple[str, int, int]:
    """Enforce the public citation-tree contract for direct callers too."""
    if not isinstance(pmid, str):
        raise IdentifierValidationError("PMID must be a string")
    normalized_pmid = normalize_pmid(pmid)
    if isinstance(depth, bool) or not isinstance(depth, int) or not 1 <= depth <= MAX_DEPTH:
        raise ValueError(f"depth must be an integer between 1 and {MAX_DEPTH}")
    if isinstance(limit_per_level, bool) or not isinstance(limit_per_level, int) or not 1 <= limit_per_level <= 20:
        raise ValueError("limit_per_level must be an integer between 1 and 20")
    return normalized_pmid, depth, limit_per_level


# ============================================================================
# Format Converters
# ============================================================================


def _to_cytoscape(nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    """
    Convert to Cytoscape.js format.
    Academic standard, used in bioinformatics and medical research.

    Format: {elements: {nodes: [{data: {...}}], edges: [{data: {...}}]}}
    """
    cy_nodes = []
    for node in nodes:
        cy_nodes.append(
            {
                "data": {"id": f"pmid_{node['pmid']}", **node},
                "classes": [node["direction"], f"level-{node['level']}"],
            }
        )

    cy_edges = []
    for edge in edges:
        cy_edges.append(
            {
                "data": {
                    "id": f"e_{edge['source']}_{edge['target']}",
                    "source": f"pmid_{edge['source']}",
                    "target": f"pmid_{edge['target']}",
                    "edge_type": edge["edge_type"],
                },
                "classes": [edge["edge_type"]],
            }
        )

    return {"nodes": cy_nodes, "edges": cy_edges}


def _to_g6(nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    """
    Convert to AntV G6 format.
    Modern, high-performance, great for large graphs.
    GitHub: https://github.com/antvis/G6 (11k+ stars)

    Format: {nodes: [{id, label, ...}], edges: [{source, target, ...}]}
    """
    g6_nodes = []
    for node in nodes:
        g6_nodes.append(
            {
                "id": node["pmid"],
                "label": node["label"],
                "data": node,
                # G6 styling hints
                "type": "circle" if node["level"] == 0 else "rect",
                "style": {
                    "fill": "#ff6b6b"
                    if node["direction"] == "root"
                    else "#4ecdc4"
                    if node["direction"] == "citing"
                    else "#95e1d3"
                },
            }
        )

    g6_edges = []
    for edge in edges:
        g6_edges.append(
            {
                "source": edge["source"],
                "target": edge["target"],
                "data": {"type": edge["edge_type"]},
                "style": {"stroke": "#aaa", "endArrow": True},
            }
        )

    return {"nodes": g6_nodes, "edges": g6_edges}


def _to_d3(nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    """
    Convert to D3.js force graph format.
    Most flexible, works with Observable notebooks.

    Format: {nodes: [{id, ...}], links: [{source, target, ...}]}
    """
    d3_nodes = []
    node_ids = set()
    for node in nodes:
        node_ids.add(node["pmid"])
        d3_nodes.append(
            {
                "id": node["pmid"],
                "group": 0 if node["level"] == 0 else (1 if node["direction"] == "citing" else 2),
                **node,
            }
        )

    d3_links = []
    for edge in edges:
        # D3 uses 'links' not 'edges', and nodes must exist
        if edge["source"] in node_ids and edge["target"] in node_ids:
            d3_links.append(
                {
                    "source": edge["source"],
                    "target": edge["target"],
                    "value": 1,
                    "type": edge["edge_type"],
                }
            )

    return {"nodes": d3_nodes, "links": d3_links}


def _vis_identifier(value: str) -> int | str:
    """Keep legacy numeric IDs only when JavaScript can represent them exactly."""
    if value.isascii() and value.isdecimal() and len(value) <= 16:
        number = int(value)
        if number <= 2**53 - 1:
            return number
    return value


def _to_vis(nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    """
    Convert to vis-network format.
    Simple and easy to use, good for quick prototypes.
    GitHub: https://github.com/visjs/vis-network (3.5k stars)

    Format: {nodes: [{id, label, ...}], edges: [{from, to, ...}]}
    """
    vis_nodes = []
    for node in nodes:
        color = "#ff6b6b" if node["level"] == 0 else "#4ecdc4" if node["direction"] == "citing" else "#95e1d3"
        vis_nodes.append(
            {
                "id": _vis_identifier(node["pmid"]),
                "label": node["label"],
                "title": node["title"],  # tooltip
                "color": color,
                "level": node["level"],
                "data": node,
            }
        )

    vis_edges = []
    for edge in edges:
        vis_edges.append(
            {
                "from": _vis_identifier(edge["source"]),
                "to": _vis_identifier(edge["target"]),
                "arrows": "to",
                "title": edge["edge_type"],
            }
        )

    return {"nodes": vis_nodes, "edges": vis_edges}


def _to_graphml(nodes: list[dict], edges: list[dict], root_title: str) -> str:
    """
    Convert to GraphML format (XML string).
    For desktop tools: Gephi, VOSviewer, Pajek, yEd.

    Returns: XML string (not JSON)
    """
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        '  <key id="label" for="node" attr.name="label" attr.type="string"/>',
        '  <key id="title" for="node" attr.name="title" attr.type="string"/>',
        '  <key id="year" for="node" attr.name="year" attr.type="string"/>',
        '  <key id="journal" for="node" attr.name="journal" attr.type="string"/>',
        '  <key id="level" for="node" attr.name="level" attr.type="int"/>',
        '  <key id="direction" for="node" attr.name="direction" attr.type="string"/>',
        '  <key id="edge_type" for="edge" attr.name="edge_type" attr.type="string"/>',
        '  <graph id="citation_tree" edgedefault="directed">',
        f"    <desc>{_escape_xml(root_title[:80])}</desc>",
    ]

    for node in nodes:
        node_id = _escape_xml(str(node["pmid"]))
        lines.append(f'    <node id="{node_id}">')
        lines.append(f'      <data key="label">{_escape_xml(str(node["label"]))}</data>')
        lines.append(f'      <data key="title">{_escape_xml(str(node["title"])[:200])}</data>')
        lines.append(f'      <data key="year">{_escape_xml(str(node["year"]))}</data>')
        lines.append(f'      <data key="journal">{_escape_xml(str(node["journal"]))}</data>')
        lines.append(f'      <data key="level">{node["level"]}</data>')
        lines.append(f'      <data key="direction">{_escape_xml(str(node["direction"]))}</data>')
        lines.append("    </node>")

    for i, edge in enumerate(edges):
        source = _escape_xml(str(edge["source"]))
        target = _escape_xml(str(edge["target"]))
        lines.append(f'    <edge id="e{i}" source="{source}" target="{target}">')
        lines.append(f'      <data key="edge_type">{_escape_xml(str(edge["edge_type"]))}</data>')
        lines.append("    </edge>")

    lines.append("  </graph>")
    lines.append("</graphml>")

    return "\n".join(lines)


def _escape_xml(text: str) -> str:
    """Escape special XML characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _to_mermaid(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    root_title: str,
) -> MermaidRenderResult:
    """Render a citation graph through the shared safe Mermaid kernel."""
    builder = MermaidGraphBuilder()
    node_id_by_pmid: dict[str, str] = {}
    for node in nodes:
        pmid = str(node.get("pmid") or "unknown")
        direction = str(node.get("direction") or "reference")
        role = "shared" if direction == "both" else direction
        if role not in {"root", "citing", "reference", "shared"}:
            role = "reference"
        label = (
            f"{node.get('first_author') or 'Unknown'} ({node.get('year') or '?'}) — "
            f"{node.get('short_title') or node.get('title') or 'Unknown Title'} — PMID {pmid}"
        )
        node_id = builder.add_node("pmid", pmid, label, role, fallback=f"PMID {pmid}")
        if node_id is not None:
            node_id_by_pmid[pmid] = node_id

    for edge in edges:
        source_id = node_id_by_pmid.get(str(edge.get("source") or ""))
        target_id = node_id_by_pmid.get(str(edge.get("target") or ""))
        builder.add_edge(source_id, target_id)

    result = render_mermaid_graph(
        builder.graph,
        direction="TD",
        style_roles=("root", "citing", "reference", "shared", "notice"),
        repairs=builder.repairs,
        omitted=builder.omitted,
        fallback_title=root_title,
        fallback_details="Citation visualization simplified; use the structured graph",
    )
    if not validate_mermaid_source(result.source)[0]:  # construction invariant and final safety gate
        raise ValueError("shared Mermaid renderer returned invalid source")
    return result


def _convert_graph(
    output_format: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    root_title: str,
) -> tuple[dict[str, Any] | str, dict[str, Any] | None]:
    """Serialize one internal graph and return optional Mermaid diagnostics."""
    if output_format == "cytoscape":
        return _to_cytoscape(nodes, edges), None
    if output_format == "g6":
        return _to_g6(nodes, edges), None
    if output_format == "d3":
        return _to_d3(nodes, edges), None
    if output_format == "vis":
        return _to_vis(nodes, edges), None
    if output_format == "graphml":
        return _to_graphml(nodes, edges, root_title), None
    mermaid_result = _to_mermaid(nodes, edges, root_title)
    return mermaid_result.source, mermaid_result.to_dict()


def _format_citation_response(
    network: CitationNetworkResult,
    *,
    pmid: str,
    depth: int,
    direction: str,
    limit_per_level: int,
    output_format: str,
) -> str:
    nodes = network.nodes
    edges = network.edges
    root_article = network.root_article
    root_title = nodes[0]["title"]
    stats = network.statistics()
    coverage = network.coverage()
    graph_data, mermaid_validation = _convert_graph(output_format, nodes, edges, root_title)
    result = {
        "status": coverage["status"],
        "format": output_format,
        "format_info": FORMAT_INFO[output_format],
        "graph": graph_data,
        "metadata": {
            "root_pmid": pmid,
            "root_title": root_title,
            "root_year": root_article.get("year", "?"),
            "depth": depth,
            "direction": direction,
            "limit_per_level": limit_per_level,
            "statistics": stats,
            "coverage": coverage,
            "execution_limits": {
                "max_total_nodes": MAX_TOTAL_NODES,
                "max_concurrency": MAX_CONCURRENT_FETCHES,
                "timeout_seconds": CITATION_TREE_TIMEOUT_SECONDS,
            },
        },
        "available_formats": list(FORMAT_INFO),
    }
    if mermaid_validation is not None:
        result["mermaid_validation"] = mermaid_validation

    summary_status = "Built with partial source coverage" if network.partial else "Built with complete source coverage"
    summary = f"""🌳 **Citation Tree {summary_status}**

📄 **Root Paper**: {escape_markdown_text(root_title[:80])}...
   PMID: {pmid} | Year: {escape_markdown_text(root_article.get("year", "?"))}

📊 **Statistics**:
   - Total Nodes: {stats["total_nodes"]}
   - Total Edges: {stats["total_edges"]}
   - Citing Articles (forward): {stats.get("citing_articles", 0)}
   - Reference Articles (backward): {stats.get("reference_articles", 0)}
   - Shared Articles: {stats.get("shared_articles", 0)}
   - Depth: {depth} levels
   - Completed Expansions: {coverage["completed_expansions"]}/{coverage["requested_expansions"]}
   - Source Failures: {coverage["failed_expansions"]}
   - Timed Out Expansions: {coverage["timed_out_expansions"]}

🎨 **Output Format**: {FORMAT_INFO[output_format]["name"]}
   {FORMAT_INFO[output_format]["description"]}

📌 **Other Available Formats**: {", ".join(value for value in FORMAT_INFO if value != output_format)}

---

"""
    return summary + json.dumps(result, indent=2, ensure_ascii=False)


# ============================================================================
# Tool Registration
# ============================================================================


def register_citation_tree_tools(mcp: MCPServer, searcher: LiteratureSearcher):
    """Register citation tree tools."""

    @mcp.tool()
    async def build_citation_tree(
        pmid: CitationPMID,
        depth: CitationDepth = 2,
        direction: CitationDirection = "both",
        limit_per_level: CitationLimit = 5,
        output_format: CitationOutputFormat = "cytoscape",
    ) -> str:
        """
        Build a citation tree (network) from a single article.

        🌳 Creates a visual citation network showing research lineage:
        - Forward (citing): Who cites this paper? (newer research)
        - Backward (references): What does this paper cite? (foundational work)

        ⚠️ IMPORTANT: Only accepts ONE PMID at a time to control API load.
        For multiple papers, call this tool separately for each.

        📊 Output Formats (output_format parameter):
        - "cytoscape": Cytoscape.js format (default, academic standard)
        - "g6": AntV G6 format (modern, high-performance)
        - "d3": D3.js force graph format (flexible, Observable)
        - "vis": vis-network format (simple, quick prototypes)
        - "graphml": GraphML XML (desktop tools: Gephi, yEd, VOSviewer)
        - "mermaid": Mermaid diagram (VS Code preview, Markdown)

        Args:
            pmid: Single PubMed ID (e.g., "12345678").
                  Only ONE PMID accepted - do NOT pass multiple.
            depth: How many levels to traverse (1-3, default 2).
                   - depth=1: Direct citations/references only
                   - depth=2: Also get citations of citations (recommended)
                   - depth=3: Maximum depth (can be slow, ~100+ API calls)
            direction: Which direction to build the tree:
                   - "forward": Only citing articles (who cites this)
                   - "backward": Only references (what this cites)
                   - "both": Both directions (default, recommended)
            limit_per_level: Max articles to fetch per node per level (default 5)
            output_format: Graph format for visualization (default "cytoscape")
                   - "cytoscape": Cytoscape.js (academic standard, bioinformatics)
                   - "g6": AntV G6 (modern, TypeScript, great for large graphs)
                   - "d3": D3.js force layout (most flexible, Observable notebooks)
                   - "vis": vis-network (simple and easy)
                   - "graphml": GraphML XML (Gephi, VOSviewer, yEd, Pajek)
                   - "mermaid": Mermaid diagram (preview in VS Code Markdown)

        Returns:
            Markdown summary followed by JSON with graph data in the requested format.
            Includes metadata and statistics regardless of format.

        Example usage:
            # Build 2-level tree for a paper (default Cytoscape.js format)
            build_citation_tree(pmid="33475315", depth=2, direction="both")

            # Use AntV G6 format for modern web visualization
            build_citation_tree(pmid="33475315", depth=2, output_format="g6")

            # Export GraphML for Gephi analysis
            build_citation_tree(pmid="33475315", depth=2, output_format="graphml")
        """
        try:
            normalized_pmid, normalized_depth, normalized_limit = _validate_tree_identifiers_and_bounds(
                pmid,
                depth,
                limit_per_level,
            )

            # Validate output format
            valid_formats = SUPPORTED_FORMATS
            if output_format not in valid_formats:
                return ResponseFormatter.error(
                    f"Invalid output format: '{output_format}'",
                    suggestion=f"Use one of: {', '.join(valid_formats)}",
                    example='build_citation_tree(pmid="12345678", output_format="mermaid")',
                    tool_name="build_citation_tree",
                )
            normalized_format = output_format

            # Validate direction
            valid_directions = ["forward", "backward", "both"]
            if direction not in valid_directions:
                return ResponseFormatter.error(
                    f"Invalid direction: '{direction}'",
                    suggestion=f"Use one of: {', '.join(valid_directions)}",
                    example='build_citation_tree(pmid="12345678", direction="both")',
                    tool_name="build_citation_tree",
                )
            normalized_direction = direction

            logger.info(
                "Building citation tree for PMID %s at depth %s, direction %s, format %s",
                normalized_pmid,
                normalized_depth,
                normalized_direction,
                normalized_format,
            )

            config = CitationNetworkConfig(
                depth=normalized_depth,
                direction=normalized_direction,
                limit_per_level=normalized_limit,
                max_total_nodes=MAX_TOTAL_NODES,
                max_concurrency=MAX_CONCURRENT_FETCHES,
                timeout_seconds=CITATION_TREE_TIMEOUT_SECONDS,
            )
            try:
                network = await CitationNetworkService(
                    searcher,
                    task_supervisor=get_tool_session_runtime().citation_tasks,
                ).build(normalized_pmid, config)
            except CitationBuildError as exc:
                reason = {
                    "root_timeout": "The citation source timed out before the root paper was available",
                    "runtime_saturated": "The citation source task capacity is temporarily exhausted",
                    "root_source_unavailable": "The citation source is currently unavailable",
                    "root_not_found": f"Could not fetch article with PMID: {normalized_pmid}",
                }.get(exc.code, "Could not initialize the citation graph")
                return ResponseFormatter.error(
                    reason,
                    suggestion="Verify the PMID and retry later or request a smaller graph",
                    example='fetch_article_details(pmids="33475315")',
                    tool_name="build_citation_tree",
                )
            return _format_citation_response(
                network,
                pmid=normalized_pmid,
                depth=normalized_depth,
                direction=normalized_direction,
                limit_per_level=normalized_limit,
                output_format=normalized_format,
            )

        except (IdentifierValidationError, ValueError) as exc:
            return ResponseFormatter.error(
                exc,
                suggestion="Provide one PMID string, depth 1-3, and limit_per_level 1-20",
                tool_name="build_citation_tree",
            )
        except Exception as exc:
            logger.warning("Build citation tree failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                "Citation tree construction failed",
                suggestion="Check PMID and try again with smaller depth",
                tool_name="build_citation_tree",
            )
