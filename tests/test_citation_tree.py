"""Test citation tree functionality."""

import sys

sys.path.insert(0, "src")

from pubmed_search.infrastructure.ncbi import LiteratureSearcher
from pubmed_search.presentation.mcp_server.tools.citation_tree import (
    _make_node,
    _make_edge,
    _to_cytoscape,
    _to_g6,
    _to_d3,
    _to_vis,
    _to_graphml,
)


def test_basic_apis():
    """Test the underlying citation APIs."""
    print("=" * 60)
    print("Test 1: Basic Citation APIs")
    print("=" * 60)

    searcher = LiteratureSearcher()
    pmid = "30676168"  # A music therapy article

    # 1. Fetch article info
    print("\n[1] Fetching article details...")
    articles = searcher.fetch_details([pmid])
    if articles:
        a = articles[0]
        print(f"    Title: {a.get('title', '?')[:60]}...")
        print(f"    Year: {a.get('year', '?')}")
        print(f"    Journal: {a.get('journal', '?')}")

    # 2. Test citing articles (forward)
    print("\n[2] Testing Forward (who cites this)...")
    citing = searcher.get_citing_articles(pmid, limit=3)
    print(f"    Found {len(citing)} citing articles")
    for c in citing[:2]:
        print(f"    - {c.get('title', '?')[:50]}... ({c.get('year', '?')})")

    # 3. Test references (backward)
    print("\n[3] Testing Backward (what this cites)...")
    refs = searcher.get_article_references(pmid, limit=3)
    print(f"    Found {len(refs)} references")
    for r in refs[:2]:
        print(f"    - {r.get('title', '?')[:50]}... ({r.get('year', '?')})")

    return articles[0] if articles else None


def test_format_converters():
    """Test the format conversion functions."""
    print("\n" + "=" * 60)
    print("Test 2: Format Converters")
    print("=" * 60)

    # Sample data
    sample_article = {
        "pmid": "12345678",
        "title": "Test Article Title",
        "year": "2024",
        "journal": "Test Journal",
        "authors": ["Smith J", "Jones K"],
        "doi": "10.1234/test",
    }

    # Create nodes and edges
    nodes = [
        _make_node(sample_article, level=0, direction="root"),
        _make_node(
            {**sample_article, "pmid": "87654321", "title": "Citing Paper"},
            level=1,
            direction="citing",
        ),
        _make_node(
            {**sample_article, "pmid": "11111111", "title": "Reference Paper"},
            level=1,
            direction="reference",
        ),
    ]
    edges = [
        _make_edge("87654321", "12345678", "cites"),
        _make_edge("12345678", "11111111", "cited_by"),
    ]

    print(f"\n    Created {len(nodes)} nodes and {len(edges)} edges")

    # Test each format
    formats = {
        "cytoscape": _to_cytoscape,
        "g6": _to_g6,
        "d3": _to_d3,
        "vis": _to_vis,
    }

    for fmt_name, converter in formats.items():
        result = converter(nodes, edges)
        node_key = "nodes"
        edge_key = "edges" if fmt_name != "d3" else "links"
        print(
            f"\n    [{fmt_name}] nodes: {len(result[node_key])}, edges: {len(result[edge_key])}"
        )
        # Show first node structure
        first_node = result[node_key][0]
        print(f"        Sample node keys: {list(first_node.keys())[:5]}...")

    # Test GraphML
    graphml = _to_graphml(nodes, edges, "Test Article")
    print(f"\n    [graphml] Generated XML ({len(graphml)} chars)")
    print(f"        First 200 chars: {graphml[:200]}...")


def test_full_tree():
    """Test building a complete citation tree."""
    print("\n" + "=" * 60)
    print("Test 3: Full Citation Tree (depth=1)")
    print("=" * 60)

    from pubmed_search.presentation.mcp_server.tools.citation_tree import (
        _make_node,
        _make_edge,
    )

    searcher = LiteratureSearcher()
    pmid = "30676168"

    # Build a simple tree manually
    nodes = []
    edges = []
    seen = set()

    # Root
    root = searcher.fetch_details([pmid])[0]
    nodes.append(_make_node(root, 0, "root"))
    seen.add(pmid)
    print(f"\n    Root: {root.get('title', '?')[:50]}...")

    # Forward (citing)
    citing = searcher.get_citing_articles(pmid, limit=3)
    for c in citing:
        c_pmid = str(c.get("pmid", ""))
        if c_pmid and c_pmid not in seen:
            nodes.append(_make_node(c, 1, "citing"))
            edges.append(_make_edge(c_pmid, pmid, "cites"))
            seen.add(c_pmid)
    print(f"    Added {len(citing)} citing articles")

    # Backward (references)
    refs = searcher.get_article_references(pmid, limit=3)
    for r in refs:
        r_pmid = str(r.get("pmid", ""))
        if r_pmid and r_pmid not in seen:
            nodes.append(_make_node(r, 1, "reference"))
            edges.append(_make_edge(pmid, r_pmid, "cited_by"))
            seen.add(r_pmid)
    print(f"    Added {len(refs)} reference articles")

    print(f"\n    Total: {len(nodes)} nodes, {len(edges)} edges")

    # Convert to different formats
    print("\n    Converting to all formats:")
    cy = _to_cytoscape(nodes, edges)
    print(f"    - Cytoscape: {len(cy['nodes'])} nodes")

    g6 = _to_g6(nodes, edges)
    print(f"    - G6: {len(g6['nodes'])} nodes")

    d3 = _to_d3(nodes, edges)
    print(f"    - D3: {len(d3['nodes'])} nodes, {len(d3['links'])} links")

    vis = _to_vis(nodes, edges)
    print(f"    - vis-network: {len(vis['nodes'])} nodes")

    graphml = _to_graphml(nodes, edges, root.get("title", "Unknown"))
    print(f"    - GraphML: {len(graphml)} chars")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("   CITATION TREE TEST SUITE")
    print("=" * 60)

    test_basic_apis()
    test_format_converters()
    test_full_tree()

    print("\n" + "=" * 60)
    print("   ALL TESTS COMPLETED!")
    print("=" * 60 + "\n")
