"""
PubMed Search MCP server entrypoints.

Exports are lazy to keep ``import pubmed_search.presentation.mcp_server`` cheap
unless the caller actually creates a server or registers tools.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "create_server": ("pubmed_search.presentation.mcp_server.server", "create_server"),
    "main": ("pubmed_search.presentation.mcp_server.server", "main"),
    "register_all_tools": ("pubmed_search.presentation.mcp_server.tools", "register_all_tools"),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *_LAZY_EXPORTS])
