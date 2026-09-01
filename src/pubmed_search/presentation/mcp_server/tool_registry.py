"""
Tool Registry - 集中管理所有 MCP Tool 註冊

此模組提供統一的 tool 註冊介面，方便管理和查詢所有可用工具。

Usage:
    from .tool_registry import register_all_mcp_tools, list_registered_tools

    # 註冊所有工具
    register_all_mcp_tools(
        mcp,
        searcher,
        session_manager,
        pipeline_runtime=pipeline_runtime,
        source_runtime=source_runtime,
        strategy_generator=strategy_generator,
    )

    # 查詢已註冊工具
    tools = list_registered_tools()
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from pubmed_search.shared.settings import load_settings

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from mcp.server import MCPServer

    from pubmed_search.application.image_search import ImageSearchService
    from pubmed_search.application.session.manager import SessionManager
    from pubmed_search.application.session.registry import SessionManagerRegistry
    from pubmed_search.infrastructure.ncbi import LiteratureSearcher
    from pubmed_search.infrastructure.sources.runtime import SourceRuntime
    from pubmed_search.shared.settings import AppSettings

    from .tools.pipeline_tools import PipelineToolRuntime

logger = logging.getLogger(__name__)


async def _await_registered_tools(awaitable: Awaitable[Any]) -> Any:
    """Normalize generic awaitables into a coroutine that asyncio.run can execute."""
    return await awaitable


def _run_awaitable_in_thread(awaitable: Any) -> Any:
    """Run an awaitable to completion from a sync context, even if an event loop is already running."""
    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def _worker() -> None:
        try:
            result["value"] = asyncio.run(_await_registered_tools(awaitable))
        except BaseException as exc:  # pragma: no cover - defensive transport glue
            error["value"] = exc

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join()

    if "value" in error:
        raise error["value"]

    return result.get("value")


def _resolve_awaitable(awaitable: Awaitable[Any]) -> Any:
    """Resolve an awaitable from sync code without leaking un-awaited coroutines."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_await_registered_tools(awaitable))

    return _run_awaitable_in_thread(awaitable)


def _extract_registered_tool_names(mcp: MCPServer) -> set[str]:
    """Get registered tool names through the public MCP v2 API."""
    list_tools = getattr(mcp, "list_tools", None)
    if not callable(list_tools):
        msg = "MCPServer.list_tools() public API is unavailable"
        raise TypeError(msg)

    raw_tools = list_tools()
    if inspect.isawaitable(raw_tools):
        raw_tools = _resolve_awaitable(raw_tools)

    names: set[str] = set()
    for tool in raw_tools:
        if isinstance(tool, str):
            names.add(tool)
            continue

        tool_name = getattr(tool, "name", None)
        if isinstance(tool_name, str):
            names.add(tool_name)
    return names


# ============================================================================
# Tool Categories - 工具分類定義
# ============================================================================

TOOL_CATEGORIES: dict[str, dict[str, Any]] = {
    "search": {
        "name": "搜尋工具",
        "description": "Unified multi-source literature search gateway",
        "tools": ["unified_search"],
    },
    "query_intelligence": {
        "name": "查詢智能",
        "description": "MeSH expansion, agent-provided PICO handoff, and query analysis",
        "tools": ["validate_pico_plan", "generate_search_queries", "analyze_search_query"],
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
    "reference_verification": {
        "name": "引用驗證",
        "description": "Reference list verification with PubMed evidence",
        "tools": ["verify_reference_list"],
    },
    "fulltext": {
        "name": "全文工具",
        "description": "全文取得與文本挖掘",
        "tools": ["get_fulltext", "get_text_mined_terms"],
    },
    "figure": {
        "name": "圖表擷取",
        "description": "文章圖表與視覺資料擷取",
        "tools": ["get_article_figures"],
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
        "description": "引用格式匯出與本機文獻筆記保存",
        "tools": ["prepare_export", "save_literature_notes"],
    },
    "session": {
        "name": "Session 管理",
        "description": "PMID 暫存與歷史",
        "tools": ["read_session"],
    },
    "institutional": {
        "name": "機構訂閱",
        "description": "OpenURL Link Resolver",
        "tools": [
            "configure_institutional_access",
            "get_institutional_link",
            "list_resolver_presets",
            "test_institutional_access",
            "diagnose_institutional_access",
        ],
    },
    "vision": {
        "name": "視覺搜索",
        "description": "圖片分析與搜索 (實驗性)",
        "tools": ["prepare_figure_search"],
    },
    "icd": {
        "name": "ICD 轉換",
        "description": "ICD-10 與 MeSH 轉換",
        "tools": ["convert_icd_mesh"],
    },
    "chronicle": {
        "name": "研究編年史",
        "description": "研究演化脈絡：持久化、可版本比對、證據支撐的時序主軸與分支投影",
        "tools": [
            "build_research_chronicle",
            "read_research_chronicle",
        ],
    },
    "image_search": {
        "name": "圖片搜尋",
        "description": "生物醫學圖片搜尋",
        "tools": ["search_biomedical_images"],
    },
    "pipeline": {
        "name": "Pipeline 管理",
        "description": "Pipeline 持久化、載入、排程",
        "tools": [
            "save_pipeline",
            "list_pipelines",
            "load_pipeline",
            "delete_pipeline",
            "get_pipeline_history",
            "schedule_pipeline",
            "unschedule_pipeline",
        ],
    },
}


# ============================================================================
# Registration Functions - 工具註冊函數
# ============================================================================


def build_pipeline_runtime(
    *,
    searcher: LiteratureSearcher,
    session_manager: SessionManager,
    source_runtime: SourceRuntime,
    workspace_dir: str | None = None,
    settings: AppSettings | None = None,
) -> PipelineToolRuntime:
    """Build one isolated pipeline runtime for one MCP server instance."""
    from pathlib import Path

    from pubmed_search.application.pipeline.budgets import PipelineExecutionPolicy
    from pubmed_search.application.pipeline.runner import StoredPipelineRunner
    from pubmed_search.application.pipeline.store import PipelineStore
    from pubmed_search.infrastructure.pubtator.semantic_adapter import get_semantic_enhancer
    from pubmed_search.infrastructure.scheduling import APSPipelineScheduler
    from pubmed_search.infrastructure.sources import search_alternate_source_adapter
    from pubmed_search.infrastructure.sources.runtime import bind_source_runtime
    from pubmed_search.shared.async_utils import bind_shared_async_client_runtime

    from .tools.pipeline_tools import PipelineToolRuntime

    data_dir = str(session_manager.data_dir) if session_manager.data_dir else str(Path.home() / ".pubmed-search-mcp")
    resolved_settings = settings or load_settings()
    configured_workspace_dir = getattr(resolved_settings, "workspace_dir", None)
    effective_workspace_dir = workspace_dir or (
        str(configured_workspace_dir).strip() if configured_workspace_dir else None
    )

    pipeline_store = PipelineStore(
        global_data_dir=data_dir,
        workspace_dir=effective_workspace_dir,
    )

    async def _runtime_bound_source_search(*args: Any, **kwargs: Any) -> Any:
        with (
            bind_source_runtime(source_runtime),
            bind_shared_async_client_runtime(source_runtime.shared_http),
        ):
            return await search_alternate_source_adapter(*args, **kwargs)

    @contextmanager
    def _bind_pipeline_execution_runtime():
        with (
            bind_source_runtime(source_runtime),
            bind_shared_async_client_runtime(source_runtime.shared_http),
        ):
            yield

    pipeline_runner = StoredPipelineRunner(
        store=pipeline_store,
        searcher=searcher,
        alternate_search_adapter=_runtime_bound_source_search,
        semantic_enhancer_factory=get_semantic_enhancer,
        execution_policy=PipelineExecutionPolicy(
            run_timeout_seconds=resolved_settings.pipeline_run_timeout_seconds,
            max_external_calls=resolved_settings.pipeline_max_external_calls,
        ),
        execution_context=_bind_pipeline_execution_runtime,
    )
    pipeline_scheduler = APSPipelineScheduler(
        store=pipeline_store,
        runner=pipeline_runner,
        settings=resolved_settings,
    )
    return PipelineToolRuntime(base_store=pipeline_store, scheduler=pipeline_scheduler)


def _build_image_search_service(*, source_runtime: SourceRuntime) -> ImageSearchService:
    """Compose image search with one server-owned Open-i client factory."""
    from pubmed_search.application.image_search import ImageSearchService
    from pubmed_search.application.image_search.source_adapters import build_image_source_registry
    from pubmed_search.infrastructure.sources.openi import OpenIClient

    def _openi_client_factory() -> OpenIClient:
        return source_runtime.get_or_create_client(("openi",), OpenIClient)

    return ImageSearchService(
        adapters=build_image_source_registry(
            openi_client_factory=_openi_client_factory,
        )
    )


def register_all_mcp_tools(
    mcp: MCPServer,
    searcher: LiteratureSearcher,
    session_manager: SessionManager,
    *,
    pipeline_runtime: PipelineToolRuntime,
    source_runtime: SourceRuntime,
    strategy_generator: Any | None = None,
    session_registry: SessionManagerRegistry | None = None,
) -> dict[str, int]:
    """
    註冊所有 MCP 工具。

    Args:
        mcp: MCPServer instance
        searcher: LiteratureSearcher instance
        session_manager: SessionManager instance
        pipeline_runtime: Explicit server-scoped pipeline dependencies.
        source_runtime: Explicit server-scoped provider dependencies.
        strategy_generator: Optional strategy generator
        session_registry: Optional request-time tenant router for session tools and resources.

    Returns:
        Dict with category names and tool counts
    """
    from .resources import register_resources
    from .session_tools import register_session_resources, register_session_tools
    from .tools import register_all_tools
    from .tools.tool_session import ToolSessionRuntime

    install_runtime = getattr(mcp, "install_tool_session_runtime", None)
    if not callable(install_runtime):
        msg = "register_all_mcp_tools requires PubMedMCPServer runtime isolation"
        raise TypeError(msg)
    install_runtime(
        ToolSessionRuntime(
            session_manager=session_manager,
            session_registry=session_registry,
            strategy_generator=strategy_generator,
            source_runtime=source_runtime,
        )
    )

    # 1. Core search tools (from tools/__init__.py)
    logger.info("Registering search tools...")
    register_all_tools(
        mcp,
        searcher,
        image_search_service=_build_image_search_service(source_runtime=source_runtime),
        pipeline_runtime=pipeline_runtime,
    )

    # 2. Session tools
    logger.info("Registering session tools...")
    register_session_tools(mcp, session_manager, session_registry=session_registry)
    register_session_resources(mcp, session_manager, session_registry=session_registry)

    # 3. Resources (filter docs, etc.)
    logger.info("Registering resources...")
    register_resources(mcp)
    # Note: ICD tools are now registered via register_all_tools -> tools/icd.py

    # 4. Prompts
    logger.info("Registering research prompts...")
    from .prompts import register_prompts

    register_prompts(mcp)

    registered_names = _extract_registered_tool_names(mcp)
    registry_validation = validate_tool_registry(mcp)
    if not registry_validation["valid"]:
        msg = (
            "Canonical MCP tool registry mismatch: "
            f"missing={registry_validation['missing']}, "
            f"extra={registry_validation['extra']}, "
            f"duplicate_definitions={registry_validation['duplicate_definitions']}"
        )
        raise RuntimeError(msg)
    stats = {
        category_id: len(registered_names.intersection(category["tools"]))
        for category_id, category in TOOL_CATEGORIES.items()
    }
    stats["total_tools"] = len(registered_names)
    logger.info("Registered %d tools across %d categories", len(registered_names), len(TOOL_CATEGORIES))

    return stats


def list_registered_tools() -> dict[str, list[str]]:
    """
    列出所有已定義的工具，按類別分組。

    Returns:
        Dict with category names as keys and tool lists as values
    """
    return {cat_id: list(cat_info["tools"]) for cat_id, cat_info in TOOL_CATEGORIES.items()}


def get_tool_info(tool_name: str) -> dict[str, str] | None:
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


def get_tools_by_category(category_id: str) -> list[str]:
    """
    取得特定類別的所有工具。

    Args:
        category_id: 類別 ID (e.g., "search", "discovery")

    Returns:
        List of tool names, or empty list if category not found
    """
    if category_id in TOOL_CATEGORIES:
        return list(TOOL_CATEGORIES[category_id]["tools"])
    return []


def _render_markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """Render a compact markdown table for generated docs."""
    rendered = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("-" * max(len(header) + 2, 6) for header in headers) + "|",
    ]
    for row in rows:
        rendered.append("| " + " | ".join(row) + " |")
    return rendered


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

    for cat_info in TOOL_CATEGORIES.values():
        lines.extend([f"## {cat_info['name']}", "", cat_info["description"], ""])
        rows: list[list[str]] = []
        for tool in cat_info["tools"]:
            # 簡短描述 (可以後續從 docstring 提取)
            rows.append([f"`{tool}`", "-"])
        lines.extend(_render_markdown_table(["Tool", "Description"], rows))
        lines.append("")

    return "\n".join(lines)


# ============================================================================
# Validation Functions - 驗證工具註冊
# ============================================================================


def validate_tool_registry(mcp: MCPServer) -> dict[str, Any]:
    """
    驗證 TOOL_CATEGORIES 與實際註冊的工具是否同步。

    Args:
        mcp: MCPServer instance (after tools are registered)

    Returns:
        Dict with:
        - defined: Tools in TOOL_CATEGORIES
        - registered: Actually registered tools
        - missing: Defined but not registered
        - extra: Registered but not defined
        - valid: True if fully synchronized
    """
    # Get defined tools from TOOL_CATEGORIES
    defined_tools: set[str] = set()
    duplicate_definitions: set[str] = set()
    for cat_info in TOOL_CATEGORIES.values():
        for tool_name in cat_info["tools"]:
            if tool_name in defined_tools:
                duplicate_definitions.add(tool_name)
            defined_tools.add(tool_name)

    try:
        registered_tools = _extract_registered_tool_names(mcp)
    except (AttributeError, TypeError) as exc:
        logger.warning(
            "Cannot access registered tools through MCPServer.list_tools() (%s)",
            type(exc).__name__,
        )
        return {
            "defined": list(defined_tools),
            "registered": [],
            "missing": [],
            "extra": [],
            "duplicate_definitions": sorted(duplicate_definitions),
            "valid": False,
            "error": "MCPServer.list_tools() public API could not be inspected",
        }

    # Calculate differences
    missing = defined_tools - registered_tools
    extra = registered_tools - defined_tools

    result = {
        "defined": sorted(defined_tools),
        "registered": sorted(registered_tools),
        "missing": sorted(missing),
        "extra": sorted(extra),
        "duplicate_definitions": sorted(duplicate_definitions),
        "valid": not missing and not extra and not duplicate_definitions,
    }

    if missing:
        logger.warning(f"Tools defined but not registered: {missing}")
    if extra:
        logger.info(f"Tools registered but not in TOOL_CATEGORIES: {extra}")
    if duplicate_definitions:
        logger.warning("Tools assigned to more than one category: %s", duplicate_definitions)

    return result


def check_tool_registration(mcp: MCPServer, raise_on_error: bool = False) -> bool:
    """
    生產環境檢查：驗證所有工具都已正確註冊。

    Args:
        mcp: MCPServer instance
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

    logger.info(f"Tool registry validated: {len(result['registered'])} tools registered")
    return True


__all__ = [
    "TOOL_CATEGORIES",
    "check_tool_registration",
    "generate_tools_index_markdown",
    "get_tool_info",
    "get_tools_by_category",
    "list_registered_tools",
    "register_all_mcp_tools",
    "validate_tool_registry",
]
