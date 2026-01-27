"""
PubMed Search MCP Tools - Simplified Architecture (v0.1.26)

🎯 28 個核心工具：

✅ 核心搜索入口 (1)：
- unified_search: 主入口，自動多源搜索

✅ 查詢智能 (3)：
- parse_pico, generate_search_queries, analyze_search_query

✅ 文章探索 (5)：
- fetch_article_details, find_related_articles, find_citing_articles
- get_article_references, get_citation_metrics

✅ 全文工具 (2)：
- get_fulltext: 獲取 Europe PMC 全文
- get_text_mined_terms: 文本挖掘標註

✅ NCBI 延伸 (7)：
- search_gene, get_gene_details, get_gene_literature
- search_compound, get_compound_details, get_compound_literature
- search_clinvar

✅ 引用網絡 (2)：
- build_citation_tree, suggest_citation_tree

✅ Session 管理 (4) [在 session_tools.py 註冊]：
- get_session_pmids, list_search_history, get_cached_article, get_session_summary

✅ 匯出 (1)：
- prepare_export

✅ 視覺搜索 (2) [實驗性]：
- analyze_figure_for_search: 分析圖片並提取搜索關鍵字
- reverse_image_search_pubmed: 反向圖片搜索文獻

✅ 機構訂閱 (3)：
- configure_institutional_access: 設定機構 Link Resolver
- get_institutional_link: 產生機構訂閱連結 (OpenURL)
- list_resolver_presets: 列出可用的預設機構

✅ ICD 轉換 (3)：
- convert_icd_to_mesh: ICD-9/10 轉 MeSH 詞彙
- convert_mesh_to_icd: MeSH 轉 ICD 代碼
- search_by_icd: 用 ICD 代碼搜尋 PubMed

❌ 已移除的重複工具（功能已整合進 unified_search）：
- search_literature, search_europe_pmc, search_core, search_openalex...
- merge_search_results, expand_search_queries...

Usage:
    from .tools import register_all_tools
    register_all_tools(mcp, searcher)
"""

from mcp.server.fastmcp import FastMCP

from pubmed_search.infrastructure.ncbi import LiteratureSearcher

from ._common import set_session_manager, set_strategy_generator
from .citation_tree import register_citation_tree_tools
from .discovery import register_discovery_tools
from .europe_pmc import (
    register_europe_pmc_tools,
)  # For get_fulltext, get_text_mined_terms
from .export import register_export_tools
from .icd import register_icd_tools  # ICD-9/ICD-10 to MeSH conversion
from .ncbi_extended import register_ncbi_extended_tools
from .openurl import register_openurl_tools  # Institutional access (OpenURL)
from .pico import register_pico_tools
from .strategy import register_strategy_tools
from .unified import register_unified_search_tools
from .vision_search import register_vision_tools  # Experimental: image-to-literature


def register_all_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """
    精簡到 25 個核心工具 (v0.1.25)。

    保留的核心功能：
    - unified_search: 主搜索入口（自動多源）
    - get_fulltext: 獲取全文內容
    - get_text_mined_terms: 文本挖掘
    - Session 管理工具
    - OpenURL 機構訂閱連結

    已移除重複工具（功能已整合）：
    - 多源搜索工具 → unified_search
    - 擴展/合併工具 → 自動執行
    """
    # 1. Core entry point (1 tool)
    register_unified_search_tools(mcp, searcher)  # unified_search

    # 2. Advanced PICO (1 tool)
    register_pico_tools(mcp)  # parse_pico

    # 3. Query materials (2 tools)
    register_strategy_tools(
        mcp, searcher
    )  # generate_search_queries, analyze_search_query

    # 4. Article exploration (5 tools)
    register_discovery_tools(
        mcp, searcher
    )  # fetch, find_related/citing/references, metrics

    # 5. Export & session (1 tool: prepare_export)
    register_export_tools(mcp, searcher)

    # 6. Fulltext & text mining (2 tools: get_fulltext, get_text_mined_terms)
    # Note: search_europe_pmc is NOT registered (use unified_search instead)
    register_europe_pmc_tools(mcp)

    # 7. NCBI Extended (6 tools)
    register_ncbi_extended_tools(mcp)  # gene, compound, clinvar

    # 8. Citation network (2 tools)
    register_citation_tree_tools(
        mcp, searcher
    )  # build_citation_tree, suggest_citation_tree

    # 9. Vision-based search (2 tools) - Experimental
    register_vision_tools(mcp)  # analyze_figure_for_search, reverse_image_search_pubmed

    # 10. Institutional access (3 tools) - OpenURL/Link Resolver
    register_openurl_tools(
        mcp
    )  # configure_institutional_access, get_institutional_link, list_resolver_presets

    # 11. ICD conversion (3 tools)
    register_icd_tools(mcp)  # convert_icd_to_mesh, convert_mesh_to_icd, search_by_icd


__all__ = [
    "register_all_tools",
    "set_session_manager",
    "set_strategy_generator",
    # For testing/direct use
    "register_discovery_tools",
    "register_strategy_tools",
    "register_pico_tools",
    "register_export_tools",
    "register_unified_search_tools",
    "register_europe_pmc_tools",
    "register_ncbi_extended_tools",
    "register_citation_tree_tools",
    "register_vision_tools",
    "register_openurl_tools",
    "register_icd_tools",
]
