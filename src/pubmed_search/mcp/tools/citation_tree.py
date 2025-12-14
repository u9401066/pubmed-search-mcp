"""
Citation Tree Tools - Build citation network from a single article.

This module provides tools to build and visualize citation trees,
tracing the research lineage of a scientific paper both forward
(who cites this paper) and backward (what this paper cites).

Supports multiple output formats:
- cytoscape: Cytoscape.js compatible JSON (academic standard)
- g6: AntV G6 format (modern, high-performance)
- d3: D3.js force graph format (flexible)
- vis: vis-network format (simple)
- graphml: GraphML for Gephi/VOSviewer (desktop tools)
- mermaid: Mermaid diagram (VS Code preview, Markdown)
"""

import logging
import json
from typing import Dict, Any, List, Set
from mcp.server.fastmcp import FastMCP
from ...entrez import LiteratureSearcher

logger = logging.getLogger(__name__)

# Constants
MAX_DEPTH = 3  # Maximum allowed depth to prevent API overload
DEFAULT_LIMIT_PER_LEVEL = 5
MAX_TOTAL_NODES = 100  # Safety limit

# Supported output formats
SUPPORTED_FORMATS = ["cytoscape", "g6", "d3", "vis", "graphml", "mermaid"]


def _make_node(article: Dict[str, Any], level: int, direction: str) -> Dict[str, Any]:
    """
    Create internal node representation from article data.
    
    Args:
        article: Article dict with pmid, title, authors, year, journal
        level: Depth level (0=root, 1=first level, etc.)
        direction: 'citing' (forward), 'reference' (backward), or 'root'
    
    Returns:
        Internal node format (converted to specific format later)
    """
    pmid = str(article.get("pmid", "unknown"))
    title = article.get("title", "Unknown Title")
    year = article.get("year", "?")
    journal = article.get("journal", "Unknown Journal")
    authors = article.get("authors", [])
    first_author = authors[0] if authors else "Unknown"
    doi = article.get("doi", "")
    
    # Truncate title for label
    short_title = title[:60] + "..." if len(title) > 60 else title
    
    return {
        "pmid": pmid,
        "label": f"{first_author} ({year})",
        "title": title,
        "short_title": short_title,
        "year": year,
        "journal": journal,
        "authors": authors[:3],
        "first_author": first_author,
        "doi": doi,
        "level": level,
        "direction": direction,
        "node_type": "root" if level == 0 else direction
    }


def _make_edge(source_pmid: str, target_pmid: str, edge_type: str) -> Dict[str, Any]:
    """Create internal edge representation."""
    return {
        "source": source_pmid,
        "target": target_pmid,
        "edge_type": edge_type
    }


# ============================================================================
# Format Converters
# ============================================================================

def _to_cytoscape(nodes: List[Dict], edges: List[Dict]) -> Dict[str, Any]:
    """
    Convert to Cytoscape.js format.
    Academic standard, used in bioinformatics and medical research.
    
    Format: {elements: {nodes: [{data: {...}}], edges: [{data: {...}}]}}
    """
    cy_nodes = []
    for node in nodes:
        cy_nodes.append({
            "data": {
                "id": f"pmid_{node['pmid']}",
                **node
            },
            "classes": [node["direction"], f"level-{node['level']}"]
        })
    
    cy_edges = []
    for edge in edges:
        cy_edges.append({
            "data": {
                "id": f"e_{edge['source']}_{edge['target']}",
                "source": f"pmid_{edge['source']}",
                "target": f"pmid_{edge['target']}",
                "edge_type": edge["edge_type"]
            },
            "classes": [edge["edge_type"]]
        })
    
    return {"nodes": cy_nodes, "edges": cy_edges}


def _to_g6(nodes: List[Dict], edges: List[Dict]) -> Dict[str, Any]:
    """
    Convert to AntV G6 format.
    Modern, high-performance, great for large graphs.
    GitHub: https://github.com/antvis/G6 (11k+ stars)
    
    Format: {nodes: [{id, label, ...}], edges: [{source, target, ...}]}
    """
    g6_nodes = []
    for node in nodes:
        g6_nodes.append({
            "id": node["pmid"],
            "label": node["label"],
            "data": node,
            # G6 styling hints
            "type": "circle" if node["level"] == 0 else "rect",
            "style": {
                "fill": "#ff6b6b" if node["direction"] == "root" else 
                        "#4ecdc4" if node["direction"] == "citing" else "#95e1d3"
            }
        })
    
    g6_edges = []
    for edge in edges:
        g6_edges.append({
            "source": edge["source"],
            "target": edge["target"],
            "data": {"type": edge["edge_type"]},
            "style": {
                "stroke": "#aaa",
                "endArrow": True
            }
        })
    
    return {"nodes": g6_nodes, "edges": g6_edges}


def _to_d3(nodes: List[Dict], edges: List[Dict]) -> Dict[str, Any]:
    """
    Convert to D3.js force graph format.
    Most flexible, works with Observable notebooks.
    
    Format: {nodes: [{id, ...}], links: [{source, target, ...}]}
    """
    d3_nodes = []
    node_ids = set()
    for node in nodes:
        node_ids.add(node["pmid"])
        d3_nodes.append({
            "id": node["pmid"],
            "group": 0 if node["level"] == 0 else (1 if node["direction"] == "citing" else 2),
            **node
        })
    
    d3_links = []
    for edge in edges:
        # D3 uses 'links' not 'edges', and nodes must exist
        if edge["source"] in node_ids and edge["target"] in node_ids:
            d3_links.append({
                "source": edge["source"],
                "target": edge["target"],
                "value": 1,
                "type": edge["edge_type"]
            })
    
    return {"nodes": d3_nodes, "links": d3_links}


def _to_vis(nodes: List[Dict], edges: List[Dict]) -> Dict[str, Any]:
    """
    Convert to vis-network format.
    Simple and easy to use, good for quick prototypes.
    GitHub: https://github.com/visjs/vis-network (3.5k stars)
    
    Format: {nodes: [{id, label, ...}], edges: [{from, to, ...}]}
    """
    vis_nodes = []
    for node in nodes:
        color = "#ff6b6b" if node["level"] == 0 else \
                "#4ecdc4" if node["direction"] == "citing" else "#95e1d3"
        vis_nodes.append({
            "id": int(node["pmid"]) if node["pmid"].isdigit() else node["pmid"],
            "label": node["label"],
            "title": node["title"],  # tooltip
            "color": color,
            "level": node["level"],
            "data": node
        })
    
    vis_edges = []
    for edge in edges:
        vis_edges.append({
            "from": int(edge["source"]) if edge["source"].isdigit() else edge["source"],
            "to": int(edge["target"]) if edge["target"].isdigit() else edge["target"],
            "arrows": "to",
            "title": edge["edge_type"]
        })
    
    return {"nodes": vis_nodes, "edges": vis_edges}


def _to_graphml(nodes: List[Dict], edges: List[Dict], root_title: str) -> str:
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
        f'    <!-- Citation tree for: {_escape_xml(root_title[:80])} -->'
    ]
    
    for node in nodes:
        lines.append(f'    <node id="{node["pmid"]}">')
        lines.append(f'      <data key="label">{_escape_xml(node["label"])}</data>')
        lines.append(f'      <data key="title">{_escape_xml(node["title"][:200])}</data>')
        lines.append(f'      <data key="year">{node["year"]}</data>')
        lines.append(f'      <data key="journal">{_escape_xml(node["journal"])}</data>')
        lines.append(f'      <data key="level">{node["level"]}</data>')
        lines.append(f'      <data key="direction">{node["direction"]}</data>')
        lines.append('    </node>')
    
    for i, edge in enumerate(edges):
        lines.append(f'    <edge id="e{i}" source="{edge["source"]}" target="{edge["target"]}">')
        lines.append(f'      <data key="edge_type">{edge["edge_type"]}</data>')
        lines.append('    </edge>')
    
    lines.append('  </graph>')
    lines.append('</graphml>')
    
    return '\n'.join(lines)


def _escape_xml(text: str) -> str:
    """Escape special XML characters."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


def _to_mermaid(nodes: List[Dict], edges: List[Dict], root_title: str) -> str:
    """
    Convert to Mermaid diagram format.
    Can be directly previewed in VS Code Markdown or rendered by Mermaid.js.
    
    Returns: Mermaid diagram code string (ready for ```mermaid block)
    """
    lines = [
        "graph TD",
        f"    %% Citation Tree: {_escape_mermaid(root_title[:50])}...",
        ""
    ]
    
    # Define nodes with styling
    for node in nodes:
        pmid = node["pmid"]
        # Create readable label: "Author (Year)<br/>Short Title"
        label = f"{_escape_mermaid(node['first_author'])} ({node['year']})"
        short_title = _escape_mermaid(node['short_title'][:40])
        
        # Use different shapes based on direction
        if node["direction"] == "root":
            # Root: stadium shape (rounded rectangle)
            lines.append(f'    pmid_{pmid}(["<b>{label}</b><br/>{short_title}..."])')
        elif node["direction"] == "citing":
            # Citing: rectangle
            lines.append(f'    pmid_{pmid}["{label}<br/>{short_title}..."]')
        else:  # reference
            # Reference: rounded rectangle
            lines.append(f'    pmid_{pmid}("{label}<br/>{short_title}...")')
    
    lines.append("")
    
    # Define edges
    for edge in edges:
        source = f"pmid_{edge['source']}"
        target = f"pmid_{edge['target']}"
        if edge["edge_type"] == "cites":
            # Citing article points to root (arrow direction: newer -> older)
            lines.append(f"    {source} --> {target}")
        else:  # cited_by / references
            # Root points to reference
            lines.append(f"    {source} --> {target}")
    
    lines.append("")
    
    # Add styling
    lines.append("    %% Styling")
    for node in nodes:
        pmid = node["pmid"]
        if node["direction"] == "root":
            lines.append(f"    style pmid_{pmid} fill:#ff6b6b,stroke:#c0392b,stroke-width:3px,color:#fff")
        elif node["direction"] == "citing":
            lines.append(f"    style pmid_{pmid} fill:#4ecdc4,stroke:#16a085,color:#fff")
        else:  # reference
            lines.append(f"    style pmid_{pmid} fill:#95e1d3,stroke:#27ae60")
    
    return "\n".join(lines)


def _escape_mermaid(text: str) -> str:
    """Escape special Mermaid characters."""
    return (text
            .replace('"', "'")
            .replace("[", "(")
            .replace("]", ")")
            .replace("{", "(")
            .replace("}", ")")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("#", "")
            .replace("&", "and"))


# ============================================================================
# Tool Registration
# ============================================================================


def register_citation_tree_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """Register citation tree tools."""
    
    @mcp.tool()
    def build_citation_tree(
        pmid: str,
        depth: int = 2,
        direction: str = "both",
        limit_per_level: int = 5,
        include_details: bool = True,
        output_format: str = "cytoscape"
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
        - "mermaid": Mermaid diagram (VS Code preview, Markdown) ⭐NEW
        
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
            include_details: Include full article details (default True)
            output_format: Graph format for visualization (default "cytoscape")
                   - "cytoscape": Cytoscape.js (academic standard, bioinformatics)
                   - "g6": AntV G6 (modern, TypeScript, great for large graphs)
                   - "d3": D3.js force layout (most flexible, Observable notebooks)
                   - "vis": vis-network (simple and easy)
                   - "graphml": GraphML XML (Gephi, VOSviewer, yEd, Pajek)
                   - "mermaid": Mermaid diagram (preview in VS Code Markdown)
            
        Returns:
            JSON string with graph data in the requested format.
            Includes metadata and statistics regardless of format.
            
        Example usage:
            # Build 2-level tree for a paper (default Cytoscape.js format)
            build_citation_tree(pmid="33475315", depth=2, direction="both")
            
            # Use AntV G6 format for modern web visualization
            build_citation_tree(pmid="33475315", depth=2, output_format="g6")
            
            # Export GraphML for Gephi analysis
            build_citation_tree(pmid="33475315", depth=2, output_format="graphml")
        """
        logger.info(f"Building citation tree for PMID: {pmid}, depth={depth}, direction={direction}, format={output_format}")
        
        try:
            # Validate inputs
            pmid = pmid.strip()
            if "," in pmid:
                return json.dumps({
                    "error": "Only ONE PMID accepted at a time. Please call separately for each paper.",
                    "hint": "This prevents API overload and ensures complete trees."
                }, indent=2)
            
            if not pmid.isdigit():
                return json.dumps({
                    "error": f"Invalid PMID format: '{pmid}'. PMID should be numeric.",
                    "example": "12345678"
                }, indent=2)
            
            # Validate output format
            valid_formats = ["cytoscape", "g6", "d3", "vis", "graphml", "mermaid"]
            output_format = output_format.lower().strip()
            if output_format not in valid_formats:
                return json.dumps({
                    "error": f"Invalid output format: '{output_format}'",
                    "valid_formats": valid_formats,
                    "recommendations": {
                        "cytoscape": "Academic standard, Cytoscape.js",
                        "g6": "Modern, AntV G6, best for large graphs",
                        "d3": "Most flexible, D3.js, Observable notebooks",
                        "vis": "Simple, vis-network, quick prototypes",
                        "graphml": "Desktop tools: Gephi, VOSviewer, yEd",
                        "mermaid": "VS Code Markdown preview, documentation"
                    }
                }, indent=2)
            
            # Enforce depth limit
            if depth < 1:
                depth = 1
            if depth > MAX_DEPTH:
                return json.dumps({
                    "error": f"Maximum depth is {MAX_DEPTH}. Requested: {depth}",
                    "reason": f"Depth {depth} would require too many API calls (~{5**depth}+)",
                    "suggestion": f"Use depth={MAX_DEPTH} or less"
                }, indent=2)
            
            # Validate direction
            valid_directions = ["forward", "backward", "both"]
            if direction not in valid_directions:
                return json.dumps({
                    "error": f"Invalid direction: '{direction}'",
                    "valid_options": valid_directions
                }, indent=2)
            
            # Initialize data structures
            nodes: List[Dict[str, Any]] = []
            edges: List[Dict[str, Any]] = []
            seen_pmids: Set[str] = set()
            stats = {
                "total_nodes": 0,
                "total_edges": 0,
                "citing_articles": 0,
                "reference_articles": 0,
                "levels": {}
            }
            
            # Fetch root article
            root_articles = searcher.fetch_details([pmid])
            if not root_articles or "error" in root_articles[0]:
                return json.dumps({
                    "error": f"Could not fetch article with PMID: {pmid}",
                    "detail": root_articles[0].get("error") if root_articles else "No results"
                }, indent=2)
            
            root_article = root_articles[0]
            root_node = _make_node(root_article, level=0, direction="root")
            nodes.append(root_node)
            seen_pmids.add(pmid)
            stats["total_nodes"] = 1
            stats["levels"]["0"] = 1
            
            # BFS traversal for each direction
            def traverse(start_pmids: List[str], current_depth: int, 
                        fetch_func, edge_type: str, direction_name: str):
                """
                BFS traversal helper.
                
                Args:
                    start_pmids: PMIDs to expand
                    current_depth: Current depth level
                    fetch_func: Function to get related articles (citing or refs)
                    edge_type: 'cites' or 'cited_by'
                    direction_name: 'citing' or 'reference' for stats
                """
                if current_depth > depth:
                    return
                
                next_level_pmids = []
                level_key = str(current_depth)
                
                for parent_pmid in start_pmids:
                    if stats["total_nodes"] >= MAX_TOTAL_NODES:
                        logger.warning(f"Reached max nodes limit ({MAX_TOTAL_NODES})")
                        break
                    
                    # Fetch related articles
                    try:
                        related = fetch_func(parent_pmid, limit_per_level)
                    except Exception as e:
                        logger.warning(f"Error fetching for {parent_pmid}: {e}")
                        continue
                    
                    if not related or (related and "error" in related[0]):
                        continue
                    
                    for article in related:
                        article_pmid = str(article.get("pmid", ""))
                        if not article_pmid or article_pmid in seen_pmids:
                            continue
                        
                        if stats["total_nodes"] >= MAX_TOTAL_NODES:
                            break
                        
                        # Add node
                        node = _make_node(article, level=current_depth, direction=direction_name)
                        nodes.append(node)
                        seen_pmids.add(article_pmid)
                        stats["total_nodes"] += 1
                        stats[f"{direction_name}_articles"] = stats.get(f"{direction_name}_articles", 0) + 1
                        stats["levels"][level_key] = stats["levels"].get(level_key, 0) + 1
                        
                        # Add edge
                        if edge_type == "cites":
                            # citing article -> root (citing article cites root)
                            edge = _make_edge(article_pmid, parent_pmid, edge_type)
                        else:  # cited_by / references
                            # root -> reference (root cites reference)
                            edge = _make_edge(parent_pmid, article_pmid, edge_type)
                        
                        edges.append(edge)
                        stats["total_edges"] += 1
                        
                        # Queue for next level
                        next_level_pmids.append(article_pmid)
                
                # Continue to next level
                if next_level_pmids and current_depth < depth:
                    traverse(next_level_pmids, current_depth + 1, 
                            fetch_func, edge_type, direction_name)
            
            # Build forward tree (citing articles)
            if direction in ["forward", "both"]:
                traverse([pmid], 1, searcher.get_citing_articles, "cites", "citing")
            
            # Build backward tree (references)
            if direction in ["backward", "both"]:
                traverse([pmid], 1, searcher.get_article_references, "cited_by", "reference")
            
            # Convert to requested output format
            root_title = root_article.get("title", "Unknown")
            
            format_info = {
                "cytoscape": {
                    "name": "Cytoscape.js",
                    "description": "Academic standard, bioinformatics",
                    "usage": "cy.add(result.graph)"
                },
                "g6": {
                    "name": "AntV G6",
                    "description": "Modern, high-performance, TypeScript",
                    "usage": "graph.data(result.graph); graph.render();"
                },
                "d3": {
                    "name": "D3.js Force Graph",
                    "description": "Most flexible, Observable notebooks",
                    "usage": "forceSimulation(result.graph.nodes)"
                },
                "vis": {
                    "name": "vis-network",
                    "description": "Simple, easy prototypes",
                    "usage": "new vis.Network(container, result.graph)"
                },
                "graphml": {
                    "name": "GraphML (XML)",
                    "description": "Gephi, VOSviewer, yEd, Pajek",
                    "usage": "Import XML file into desktop tool"
                },
                "mermaid": {
                    "name": "Mermaid Diagram",
                    "description": "VS Code Markdown preview, documentation",
                    "usage": "Paste into ```mermaid code block in Markdown"
                }
            }
            
            # Convert internal format to requested output format
            if output_format == "cytoscape":
                graph_data = _to_cytoscape(nodes, edges)
            elif output_format == "g6":
                graph_data = _to_g6(nodes, edges)
            elif output_format == "d3":
                graph_data = _to_d3(nodes, edges)
            elif output_format == "vis":
                graph_data = _to_vis(nodes, edges)
            elif output_format == "graphml":
                graph_data = _to_graphml(nodes, edges, root_title)
            elif output_format == "mermaid":
                graph_data = _to_mermaid(nodes, edges, root_title)
            
            # Build result
            result = {
                "format": output_format,
                "format_info": format_info[output_format],
                "graph": graph_data,
                "metadata": {
                    "root_pmid": pmid,
                    "root_title": root_title,
                    "root_year": root_article.get("year", "?"),
                    "depth": depth,
                    "direction": direction,
                    "limit_per_level": limit_per_level,
                    "statistics": stats
                },
                "available_formats": list(format_info.keys())
            }
            
            # Add summary as human-readable output first
            summary = f"""🌳 **Citation Tree Built Successfully**

📄 **Root Paper**: {root_title[:80]}...
   PMID: {pmid} | Year: {root_article.get('year', '?')}

📊 **Statistics**:
   - Total Nodes: {stats['total_nodes']}
   - Total Edges: {stats['total_edges']}
   - Citing Articles (forward): {stats.get('citing_articles', 0)}
   - Reference Articles (backward): {stats.get('reference_articles', 0)}
   - Depth: {depth} levels

🎨 **Output Format**: {format_info[output_format]['name']}
   {format_info[output_format]['description']}

📌 **Other Available Formats**: {', '.join(f for f in format_info.keys() if f != output_format)}

---

"""
            return summary + json.dumps(result, indent=2, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"Build citation tree failed: {e}")
            return json.dumps({
                "error": str(e),
                "pmid": pmid
            }, indent=2)


    @mcp.tool()
    def suggest_citation_tree(pmid: str) -> str:
        """
        After fetching article details, suggest whether to build a citation tree.
        
        This is a lightweight check that can be called after fetch_article_details
        to help decide if building a citation tree would be useful.
        
        Args:
            pmid: PubMed ID of the article
            
        Returns:
            Suggestion with article info and tree-building options.
        """
        logger.info(f"Checking citation tree potential for PMID: {pmid}")
        
        try:
            # Get basic article info
            articles = searcher.fetch_details([pmid.strip()])
            if not articles or "error" in articles[0]:
                return f"Could not fetch article {pmid}"
            
            article = articles[0]
            title = article.get("title", "Unknown")
            year = article.get("year", "?")
            journal = article.get("journal", "Unknown")
            
            # Quick check for citation potential
            # (In a full implementation, we'd check actual citation counts)
            
            output = f"""📄 **Article**: {title[:80]}...
📅 Year: {year} | 📰 {journal}
🔗 PMID: {pmid}

---

🌳 **Citation Tree Options**:

Would you like to explore this paper's citation network?

1️⃣ **Quick Overview** (recommended first):
   ```
   build_citation_tree(pmid="{pmid}", depth=1, direction="both")
   ```
   - Shows direct citations and references only
   - Fast (~10 API calls)

2️⃣ **Standard Tree** (most useful):
   ```
   build_citation_tree(pmid="{pmid}", depth=2, direction="both")
   ```
   - 2 levels: citations of citations, references of references
   - Good balance of depth and speed (~50 API calls)

3️⃣ **Deep Exploration** (comprehensive):
   ```
   build_citation_tree(pmid="{pmid}", depth=3, direction="both", limit_per_level=3)
   ```
   - 3 levels deep - full research landscape
   - Slower but thorough (~100+ API calls)

---

📊 **Output Format Options** (output_format parameter):

| Format | Library | Best For |
|--------|---------|----------|
| `cytoscape` | Cytoscape.js | Academic research, bioinformatics |
| `g6` | AntV G6 | Modern web apps, large graphs |
| `d3` | D3.js | Flexible viz, Observable notebooks |
| `vis` | vis-network | Quick prototypes, simple use |
| `graphml` | GraphML XML | Gephi, VOSviewer, yEd, Pajek |
| `mermaid` | Mermaid.js | ⭐ VS Code preview, Markdown docs |

Example with format:
```
build_citation_tree(pmid="{pmid}", depth=2, output_format="mermaid")
```

---

💡 **Tip**: Start with depth=1 to get a quick sense of the network size,
then increase depth if needed.
"""
            return output
            
        except Exception as e:
            logger.error(f"Suggest citation tree failed: {e}")
            return f"Error: {e}"
