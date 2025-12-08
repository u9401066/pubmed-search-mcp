"""
PubMed Search MCP Tools - Modular Design

Tools organized by domain:
- discovery: Search, related articles, citing articles, article details
- strategy: Query generation and expansion
- pico: PICO clinical question parsing
- merge: Search results merging
- export: Citation export and fulltext access

Usage:
    from .tools import register_all_tools
    register_all_tools(mcp, searcher)
"""

from mcp.server.fastmcp import FastMCP
from ...entrez import LiteratureSearcher
from ...entrez.strategy import SearchStrategyGenerator

from ._common import set_session_manager, set_strategy_generator
from .discovery import register_discovery_tools
from .strategy import register_strategy_tools
from .pico import register_pico_tools
from .merge import register_merge_tools
from .export import register_export_tools


def register_all_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """Register all PubMed search tools."""
    register_discovery_tools(mcp, searcher)
    register_strategy_tools(mcp, searcher)
    register_pico_tools(mcp)
    register_merge_tools(mcp, searcher)
    register_export_tools(mcp, searcher)


__all__ = [
    'register_all_tools',
    'set_session_manager',
    'set_strategy_generator',
]
