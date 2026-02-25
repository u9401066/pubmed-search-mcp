"""
PubMed Search MCP Tools (v0.4.4)

🎯 40 個 MCP 工具 / 15 categories：

✅ 搜尋工具 (1)：
- unified_search: 統一搜索入口，自動多源搜索 (PubMed, Europe PMC, OpenAlex, Semantic Scholar, CrossRef, CORE)

✅ 查詢智能 (3)：
- parse_pico, generate_search_queries, analyze_search_query

✅ 文章探索 (5)：
- fetch_article_details, find_related_articles, find_citing_articles
- get_article_references, get_citation_metrics

✅ 全文工具 (2)：
- get_fulltext: 多源全文取得
- get_text_mined_terms: 文本挖掘標註

✅ 圖表擷取 (1)：
- get_article_figures: 文章圖表與視覺資料擷取

✅ NCBI 延伸 (7)：
- search_gene, get_gene_details, get_gene_literature
- search_compound, get_compound_details, get_compound_literature
- search_clinvar

✅ 引用網絡 (1)：
- build_citation_tree

✅ 研究時間軸 (3)：
- build_research_timeline, analyze_timeline_milestones, compare_timelines

✅ Session 管理 (3) [在 session_tools.py 註冊]：
- get_session_pmids, get_cached_article, get_session_summary

✅ 匯出 (1)：
- prepare_export

✅ 視覺搜索 (1) [實驗性]：
- analyze_figure_for_search

✅ 機構訂閱 (4)：
- configure_institutional_access, get_institutional_link
- list_resolver_presets, test_institutional_access

✅ ICD 轉換 (1)：
- convert_icd_mesh

✅ 圖片搜尋 (1)：
- search_biomedical_images

✅ Pipeline 管理 (6)：
- save_pipeline, list_pipelines, load_pipeline
- delete_pipeline, get_pipeline_history, schedule_pipeline

Usage:
    from .tools import register_all_tools
    register_all_tools(mcp, searcher)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._common import set_session_manager, set_strategy_generator
from .citation_tree import register_citation_tree_tools
from .discovery import register_discovery_tools
from .europe_pmc import (
    register_europe_pmc_tools,
)  # For get_fulltext, get_text_mined_terms
from .export import register_export_tools
from .figure_tools import register_figure_tools  # Article figure extraction
from .icd import register_icd_tools  # ICD-9/ICD-10 to MeSH conversion
from .image_search import register_image_search_tools  # Biomedical image search
from .ncbi_extended import register_ncbi_extended_tools
from .openurl import register_openurl_tools  # Institutional access (OpenURL)
from .pico import register_pico_tools
from .pipeline_tools import register_pipeline_tools  # Pipeline persistence & management
from .strategy import register_strategy_tools
from .timeline import register_timeline_tools
from .unified import register_unified_search_tools
from .vision_search import register_vision_tools  # Experimental: image-to-literature

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from pubmed_search.infrastructure.ncbi import LiteratureSearcher


def register_all_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """註冊全部 39 個 MCP 工具 (14 categories)。"""
    # 1. 搜尋工具 (1)
    register_unified_search_tools(mcp, searcher)

    # 2. 查詢智能 - PICO (1)
    register_pico_tools(mcp)

    # 3. 查詢智能 - 策略 (2)
    register_strategy_tools(mcp, searcher)

    # 4. 文章探索 (5)
    register_discovery_tools(mcp, searcher)

    # 5. 匯出工具 (1)
    register_export_tools(mcp, searcher)

    # 6. 全文工具 (2)
    register_europe_pmc_tools(mcp)

    # 6.5 圖表擷取 (1)
    register_figure_tools(mcp)

    # 7. NCBI 延伸 (7)
    register_ncbi_extended_tools(mcp)

    # 8. 引用網絡 (1)
    register_citation_tree_tools(mcp, searcher)

    # 9. 研究時間軸 (3)
    register_timeline_tools(mcp, searcher)

    # 10. 視覺搜索 (1)
    register_vision_tools(mcp)

    # 11. 機構訂閱 (4)
    register_openurl_tools(mcp)

    # 12. ICD 轉換 (2)
    register_icd_tools(mcp)

    # 13. 圖片搜尋 (1)
    register_image_search_tools(mcp)

    # 14. Pipeline 管理 (6)
    register_pipeline_tools(mcp)


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
    "register_timeline_tools",
    "register_vision_tools",
    "register_openurl_tools",
    "register_icd_tools",
    "register_image_search_tools",
    "register_pipeline_tools",
    "register_figure_tools",
]
