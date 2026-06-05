"""
PubMed Search MCP tool registration.

The package exposes the same registrar functions as before, but loads category
modules only when a registrar is requested. This keeps server/package imports
from pulling the entire tool tree into memory.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from ._common import set_session_manager, set_strategy_generator

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

_TOOL_REGISTRARS: dict[str, tuple[str, str]] = {
    "register_citation_tree_tools": (
        "pubmed_search.presentation.mcp_server.tools.citation_tree",
        "register_citation_tree_tools",
    ),
    "register_discovery_tools": ("pubmed_search.presentation.mcp_server.tools.discovery", "register_discovery_tools"),
    "register_europe_pmc_tools": (
        "pubmed_search.presentation.mcp_server.tools.europe_pmc",
        "register_europe_pmc_tools",
    ),
    "register_export_tools": ("pubmed_search.presentation.mcp_server.tools.export", "register_export_tools"),
    "register_figure_tools": ("pubmed_search.presentation.mcp_server.tools.figure_tools", "register_figure_tools"),
    "register_icd_tools": ("pubmed_search.presentation.mcp_server.tools.icd", "register_icd_tools"),
    "register_image_search_tools": (
        "pubmed_search.presentation.mcp_server.tools.image_search",
        "register_image_search_tools",
    ),
    "register_ncbi_extended_tools": (
        "pubmed_search.presentation.mcp_server.tools.ncbi_extended",
        "register_ncbi_extended_tools",
    ),
    "register_openurl_tools": ("pubmed_search.presentation.mcp_server.tools.openurl", "register_openurl_tools"),
    "register_pico_tools": ("pubmed_search.presentation.mcp_server.tools.pico", "register_pico_tools"),
    "register_pipeline_tools": (
        "pubmed_search.presentation.mcp_server.tools.pipeline_tools",
        "register_pipeline_tools",
    ),
    "register_reference_verification_tools": (
        "pubmed_search.presentation.mcp_server.tools.reference_verification",
        "register_reference_verification_tools",
    ),
    "register_strategy_tools": ("pubmed_search.presentation.mcp_server.tools.strategy", "register_strategy_tools"),
    "register_timeline_tools": ("pubmed_search.presentation.mcp_server.tools.timeline", "register_timeline_tools"),
    "register_unified_search_tools": (
        "pubmed_search.presentation.mcp_server.tools.unified",
        "register_unified_search_tools",
    ),
    "register_vision_tools": ("pubmed_search.presentation.mcp_server.tools.vision_search", "register_vision_tools"),
}


def _load_registrar(name: str) -> Any:
    module_name, attr_name = _TOOL_REGISTRARS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __getattr__(name: str) -> Any:
    if name in _TOOL_REGISTRARS:
        return _load_registrar(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted([*globals(), *_TOOL_REGISTRARS])


def register_all_tools(mcp: FastMCP, searcher: LiteratureSearcher) -> None:
    """Register all primary MCP tools."""
    _load_registrar("register_unified_search_tools")(mcp, searcher)
    _load_registrar("register_pico_tools")(mcp)
    _load_registrar("register_strategy_tools")(mcp, searcher)
    _load_registrar("register_discovery_tools")(mcp, searcher)
    _load_registrar("register_reference_verification_tools")(mcp, searcher)
    _load_registrar("register_export_tools")(mcp, searcher)
    _load_registrar("register_europe_pmc_tools")(mcp)
    _load_registrar("register_figure_tools")(mcp)
    _load_registrar("register_ncbi_extended_tools")(mcp)
    _load_registrar("register_citation_tree_tools")(mcp, searcher)
    _load_registrar("register_timeline_tools")(mcp, searcher)
    _load_registrar("register_vision_tools")(mcp)
    _load_registrar("register_openurl_tools")(mcp)
    _load_registrar("register_icd_tools")(mcp)
    _load_registrar("register_image_search_tools")(mcp)
    _load_registrar("register_pipeline_tools")(mcp)


__all__ = [
    "register_all_tools",
    "set_session_manager",
    "set_strategy_generator",
    "register_citation_tree_tools",
    "register_discovery_tools",
    "register_europe_pmc_tools",
    "register_export_tools",
    "register_figure_tools",
    "register_icd_tools",
    "register_image_search_tools",
    "register_ncbi_extended_tools",
    "register_openurl_tools",
    "register_pico_tools",
    "register_pipeline_tools",
    "register_reference_verification_tools",
    "register_strategy_tools",
    "register_timeline_tools",
    "register_unified_search_tools",
    "register_vision_tools",
]
