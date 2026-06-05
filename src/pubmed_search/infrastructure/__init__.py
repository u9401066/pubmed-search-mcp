"""
Infrastructure layer public exports.

Exports are lazy so importing a subpackage such as ``infrastructure.ncbi`` does
not also load optional citation-export HTTP/client dependencies.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "LiteratureSearcher": ("pubmed_search.infrastructure.ncbi", "LiteratureSearcher"),
    "SearchStrategy": ("pubmed_search.infrastructure.ncbi", "SearchStrategy"),
    "NCBICitationExporter": ("pubmed_search.infrastructure.ncbi.citation_exporter", "NCBICitationExporter"),
    "export_citations_official": ("pubmed_search.infrastructure.ncbi.citation_exporter", "export_citations_official"),
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
