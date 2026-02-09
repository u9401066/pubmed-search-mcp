"""
Tool Registry - 集中管理所有 MCP Tool 註冊

此模組提供統一的 tool 註冊介面，方便管理和查詢所有可用工具。

Usage:
    from .tool_registry import register_all_mcp_tools, list_registered_tools

    # 註冊所有工具
    register_all_mcp_tools(mcp, searcher, session_manager, strategy_generator)

    # 查詢已註冊工具
    tools = list_registered_tools()
"""

import logging
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from pubmed_search.application.session.manager import SessionManager
from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)


# ============================================================================
# Tool Categories - 工具分類定義
# ============================================================================

TOOL_CATEGORIES = {
    "search": {
        "name": "搜尋工具",
        "description": "文獻搜索入口",
        "tools": [
            "unified_search",
            # Note: search_literature, search_europe_pmc, search_core 已整合到 unified_search
        ],
    },
    "query_intelligence": {
        "name": "查詢智能",
        "description": "MeSH 擴展、PICO 解析",
        "tools": ["parse_pico", "generate_search_queries", "analyze_search_query"],
    },
    "discovery": {
        "name": "文章探索",
        "description": "相關文章、引用網路",
        "tools": [
            "fetch_article_details",
            "find_related_articles",
            "find_citing_articles",
            "get_article_references",
            "get_citation_metrics",
        ],
    },
    "fulltext": {
        "name": "全文工具",
        "description": "全文取得與文本挖掘",
        "tools": ["get_fulltext", "get_text_mined_terms"],
    },
    "ncbi_extended": {
        "name": "NCBI 延伸",
        "description": "Gene, PubChem, ClinVar",
        "tools": [
            "search_gene",
            "get_gene_details",
            "get_gene_literature",
            "search_compound",
            "get_compound_details",
            "get_compound_literature",
            "search_clinvar",
        ],
    },
    "citation_network": {
        "name": "引用網絡",
        "description": "引用樹建構與探索",
        "tools": ["build_citation_tree"],
    },
    "export": {
        "name": "匯出工具",
        "description": "引用格式匯出",
        "tools": ["prepare_export"],
    },
    "session": {
        "name": "Session 管理",
        "description": "PMID 暫存與歷史",
        "tools": [
            "get_session_pmids",
            "get_cached_article",
            "get_session_summary",
        ],
    },
    "institutional": {
        "name": "機構訂閱",
        "description": "OpenURL Link Resolver",
        "tools": [
            "configure_institutional_access",
            "get_institutional_link",
            "list_resolver_presets",
            "test_institutional_access",
        ],
    },
    "vision": {
        "name": "視覺搜索",
        "description": "圖片分析與搜索 (實驗性)",
        "tools": ["analyze_figure_for_search"],
    },
    "icd": {
        "name": "ICD 轉換",
        "description": "ICD-10 與 MeSH 轉換",
        "tools": ["convert_icd_mesh", "search_by_icd"],
    },
    "timeline": {
        "name": "研究時間軸",
        "description": "研究演化追蹤與里程碑偵測",
        "tools": [
            "build_research_timeline",
            "analyze_timeline_milestones",
            "compare_timelines",
        ],
    },
    "image_search": {
        "name": "圖片搜尋",
        "description": "生物醫學圖片搜尋",
        "tools": ["search_biomedical_images"],
    },
}


# ============================================================================
# Registration Functions - 工具註冊函數
# ============================================================================


def register_all_mcp_tools(
    mcp: FastMCP,
    searcher: LiteratureSearcher,
    session_manager: SessionManager,
    strategy_generator: Optional[Any] = None,
) -> Dict[str, int]:
    """
    註冊所有 MCP 工具。

    Args:
        mcp: FastMCP server instance
        searcher: LiteratureSearcher instance
        session_manager: SessionManager instance
        strategy_generator: Optional strategy generator

    Returns:
        Dict with category names and tool counts
    """
    from .resources import register_resources
    from .session_tools import register_session_resources, register_session_tools
    from .tools import register_all_tools, set_session_manager, set_strategy_generator

    # Set global references
    set_session_manager(session_manager)
    if strategy_generator:
        set_strategy_generator(strategy_generator)

    stats = {}

    # 1. Core search tools (from tools/__init__.py)
    logger.info("Registering search tools...")
    register_all_tools(mcp, searcher)
    stats["search_and_discovery"] = 25  # Approximate

    # 2. Session tools
    logger.info("Registering session tools...")
    register_session_tools(mcp, session_manager)
    register_session_resources(mcp, session_manager)
    stats["session"] = 3  # get_session_pmids, get_cached_article, get_session_summary

    # 3. Resources (filter docs, etc.)
    logger.info("Registering resources...")
    register_resources(mcp)
    # Note: ICD tools are now registered via register_all_tools -> tools/icd.py

    # 4. Prompts
    logger.info("Registering research prompts...")
    from .prompts import register_prompts

    register_prompts(mcp)
    stats["prompts"] = 9  # Approximate

    total = sum(stats.values())
    logger.info(f"Total registered: {total} tools/prompts/resources")

    return stats


def list_registered_tools() -> Dict[str, List[str]]:
    """
    列出所有已定義的工具，按類別分組。

    Returns:
        Dict with category names as keys and tool lists as values
    """
    return {cat_id: cat_info["tools"] for cat_id, cat_info in TOOL_CATEGORIES.items()}


def get_tool_info(tool_name: str) -> Optional[Dict[str, str]]:
    """
    取得特定工具的資訊。

    Args:
        tool_name: 工具名稱

    Returns:
        Dict with category, description, or None if not found
    """
    for cat_id, cat_info in TOOL_CATEGORIES.items():
        if tool_name in cat_info["tools"]:
            return {
                "name": tool_name,
                "category": cat_info["name"],
                "category_id": cat_id,
                "category_description": cat_info["description"],
            }
    return None


def get_tools_by_category(category_id: str) -> List[str]:
    """
    取得特定類別的所有工具。

    Args:
        category_id: 類別 ID (e.g., "search", "discovery")

    Returns:
        List of tool names, or empty list if category not found
    """
    if category_id in TOOL_CATEGORIES:
        return TOOL_CATEGORIES[category_id]["tools"]
    return []


def generate_tools_index_markdown() -> str:
    """
    產生工具索引的 Markdown 文檔。

    Returns:
        Markdown formatted string
    """
    lines = [
        "# PubMed Search MCP - Tools Index",
        "",
        "Quick reference for all available MCP tools.",
        "",
        "---",
        "",
    ]

    for cat_id, cat_info in TOOL_CATEGORIES.items():
        lines.append(f"## {cat_info['name']}")
        lines.append(f"*{cat_info['description']}*")
        lines.append("")
        lines.append("| Tool | Description |")
        lines.append("|------|-------------|")
        for tool in cat_info["tools"]:
            # 簡短描述 (可以後續從 docstring 提取)
            lines.append(f"| `{tool}` | - |")
        lines.append("")

    return "\n".join(lines)


# ============================================================================
# Validation Functions - 驗證工具註冊
# ============================================================================


def validate_tool_registry(mcp: FastMCP) -> Dict[str, List[str]]:
    """
    驗證 TOOL_CATEGORIES 與實際註冊的工具是否同步。

    Args:
        mcp: FastMCP server instance (after tools are registered)

    Returns:
        Dict with:
        - defined: Tools in TOOL_CATEGORIES
        - registered: Actually registered tools
        - missing: Defined but not registered
        - extra: Registered but not defined
        - valid: True if fully synchronized
    """
    # Get defined tools from TOOL_CATEGORIES
    defined_tools = set()
    for cat_info in TOOL_CATEGORIES.values():
        defined_tools.update(cat_info["tools"])

    # Get actually registered tools from mcp._tool_manager._tools
    try:
        registered_tools = set(mcp._tool_manager._tools.keys())
    except AttributeError:
        logger.warning("Cannot access registered tools from FastMCP instance")
        return {
            "defined": list(defined_tools),
            "registered": [],
            "missing": [],
            "extra": [],
            "valid": False,
            "error": "Cannot access FastMCP tools registry",
        }

    # Calculate differences
    missing = defined_tools - registered_tools
    extra = registered_tools - defined_tools

    result = {
        "defined": sorted(defined_tools),
        "registered": sorted(registered_tools),
        "missing": sorted(missing),
        "extra": sorted(extra),
        "valid": len(missing) == 0 and len(extra) == 0,
    }

    if missing:
        logger.warning(f"Tools defined but not registered: {missing}")
    if extra:
        logger.info(f"Tools registered but not in TOOL_CATEGORIES: {extra}")

    return result


def check_tool_registration(mcp: FastMCP, raise_on_error: bool = False) -> bool:
    """
    生產環境檢查：驗證所有工具都已正確註冊。

    Args:
        mcp: FastMCP server instance
        raise_on_error: If True, raise exception on validation failure

    Returns:
        True if all tools are properly registered
    """
    result = validate_tool_registry(mcp)

    if not result["valid"]:
        msg = f"Tool registry validation failed. Missing: {result['missing']}, Extra: {result['extra']}"
        if raise_on_error:
            raise RuntimeError(msg)
        logger.error(msg)
        return False

    logger.info(
        f"Tool registry validated: {len(result['registered'])} tools registered"
    )
    return True


__all__ = [
    "TOOL_CATEGORIES",
    "register_all_mcp_tools",
    "list_registered_tools",
    "get_tool_info",
    "get_tools_by_category",
    "generate_tools_index_markdown",
    "validate_tool_registry",
    "check_tool_registration",
]
