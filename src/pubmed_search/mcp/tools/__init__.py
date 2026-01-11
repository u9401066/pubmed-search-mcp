"""
PubMed Search MCP Tools - Simplified Architecture (v0.1.20)

🎯 真正精簡到 20 個核心工具：

✅ 已融合的功能：
- unified_search 內建：europe_pmc, core, openalex, crossref, semantic_scholar
- get_fulltext 內建：europe_pmc, core 全文來源
- 自動擴展、合併、去重

❌ 已移除的工具：
- search_literature（被 unified_search 取代）
- search_europe_pmc（融合進 unified_search）
- search_core（融合進 unified_search）
- search_core_fulltext（融合進 unified_search）
- search_openalex（融合進 unified_search）
- search_crossref（融合進 unified_search）
- search_semantic_scholar（融合進 unified_search）
- get_fulltext_xml（融合進 get_fulltext，用 format 參數）
- get_core_fulltext（融合進 get_fulltext）
- expand_search_queries（自動執行）
- merge_search_results（自動執行）

Usage:
    from .tools import register_all_tools
    register_all_tools(mcp, searcher)
"""

from mcp.server.fastmcp import FastMCP
from ...entrez import LiteratureSearcher

from ._common import set_session_manager, set_strategy_generator
from .discovery import register_discovery_tools
from .strategy import register_strategy_tools
from .pico import register_pico_tools
from .export import register_export_tools
from .ncbi_extended import register_ncbi_extended_tools
from .unified import register_unified_search_tools
from .citation_tree import register_citation_tree_tools

# Note: europe_pmc, core, merge 不再註冊 - 功能已融合進其他工具


def register_all_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """
    真正精簡到 20 個核心工具 (v0.1.20)。
    
    已移除重複工具，功能已融合：
    - 多源搜索 → unified_search 自動處理
    - 全文來源 → get_fulltext 自動選擇最佳來源
    - 擴展/合併 → 自動執行
    """
    # 1. Core entry point (1 tool)
    register_unified_search_tools(mcp, searcher)  # unified_search
    
    # 2. Advanced PICO (1 tool)
    register_pico_tools(mcp)  # parse_pico
    
    # 3. Query materials (2 tools)
    register_strategy_tools(mcp, searcher)  # generate_search_queries, analyze_search_query
    
    # 4. Article exploration (5 tools)
    register_discovery_tools(mcp, searcher)  # fetch, find_related/citing/references, metrics
    
    # 5. Fulltext & export (2+1 tools)
    register_export_tools(mcp, searcher)  # get_fulltext, prepare_export, text_mined_terms
    
    # 6. NCBI Extended (6 tools)
    register_ncbi_extended_tools(mcp)  # gene, compound, clinvar
    
    # 7. Citation network (2 tools - optional)
    register_citation_tree_tools(mcp, searcher)  # build_citation_tree, suggest_citation_tree


__all__ = [
    'register_all_tools',
    'set_session_manager',
    'set_strategy_generator',
]
