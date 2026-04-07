"""Backward-compatible re-exports for common MCP tool helpers.

Design:
    Older tool modules import shared helpers from this location. It now acts as
    a compatibility barrel over the more focused tool_input, tool_response, and
    tool_session modules.

Maintenance:
    Keep this file limited to re-exports. New shared helper logic should be
    implemented in the specialized modules and surfaced here only when a stable
    compatibility alias is required.
"""

from .tool_input import InputNormalizer, KEY_ALIASES, apply_key_aliases
from .tool_response import ResponseFormatter, format_search_results
from .tool_session import (
    _cache_results,
    _record_search_only,
    check_cache,
    get_last_search_pmids,
    get_session_manager,
    get_strategy_generator,
    set_session_manager,
    set_strategy_generator,
)

__all__ = [
    "InputNormalizer",
    "KEY_ALIASES",
    "ResponseFormatter",
    "_cache_results",
    "_record_search_only",
    "apply_key_aliases",
    "check_cache",
    "format_search_results",
    "get_last_search_pmids",
    "get_session_manager",
    "get_strategy_generator",
    "set_session_manager",
    "set_strategy_generator",
]
