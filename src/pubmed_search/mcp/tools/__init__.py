"""
PubMed Search MCP Tools - Simplified Architecture (v0.1.20)

Streamlined to 20 core tools for better Agent experience:
- Core: unified_search (main entry), parse_pico (advanced)
- Query: generate_search_queries, analyze_search_query (optional)
- Articles: fetch_article_details, find_related/citing/references, get_citation_metrics
- Fulltext: get_fulltext (unified), get_text_mined_terms
- NCBI: search_gene/compound, get_gene/compound_details, search_clinvar
- Session: get_session_pmids, list_search_history, prepare_export

Backend tools (auto-used by unified_search):
- europe_pmc, core, openalex, crossref, semantic_scholar
- merge_search_results, expand_search_queries

Usage:
    from .tools import register_all_tools
    register_all_tools(mcp, searcher)
"""

from mcp.server.fastmcp import FastMCP
from ...entrez import LiteratureSearcher
from ...entrez.strategy import SearchStrategyGenerator  # noqa: F401 (re-exported)

from ._common import set_session_manager, set_strategy_generator
from .discovery import register_discovery_tools
from .strategy import register_strategy_tools
from .pico import register_pico_tools
from .export import register_export_tools
from .ncbi_extended import register_ncbi_extended_tools
from .unified import register_unified_search_tools

# Backend tools - not directly exposed but used internally
from .merge import register_merge_tools
from .citation_tree import register_citation_tree_tools
from .europe_pmc import register_europe_pmc_tools
from .core import register_core_tools


def register_all_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """
    Register streamlined core tools (v0.1.20).
    
    20 core tools exposed:
    - unified_search (main entry with auto-analysis, multi-source, ranking)
    - parse_pico (advanced PICO parsing)
    - generate_search_queries, analyze_search_query (query materials)
    - 5 article tools (details, related, citing, references, metrics)
    - 2 fulltext tools (get_fulltext unified, text_mined_terms)
    - 6 NCBI tools (gene, compound, clinvar)
    - 3 session tools (pmids, history, export)
    
    Backend tools automatically used by unified_search:
    - Multi-source search (europe_pmc, core, openalex, crossref, semantic_scholar)
    - Result merging and expansion
    """
    # Core entry points
    register_unified_search_tools(mcp, searcher)  # unified_search (main)
    register_pico_tools(mcp)  # parse_pico (advanced)
    
    # Query materials (optional, for advanced users)
    register_strategy_tools(mcp, searcher)  # generate_search_queries, analyze_search_query
    
    # Article exploration
    register_discovery_tools(mcp, searcher)  # fetch, find_related/citing/references, metrics
    
    # Fulltext & export
    register_export_tools(mcp, searcher)  # get_fulltext (unified), prepare_export, session tools
    
    # NCBI Extended
    register_ncbi_extended_tools(mcp)  # gene, compound, clinvar (6 tools)
    
    # Backend tools (not directly exposed but registered for internal use)
    register_merge_tools(mcp, searcher)  # Used by unified_search
    register_citation_tree_tools(mcp, searcher)  # Optional citation network
    register_europe_pmc_tools(mcp)  # Backend for fulltext
    register_core_tools(mcp)  # Backend for fulltext


__all__ = [
    'register_all_tools',
    'set_session_manager',
    'set_strategy_generator',
]
