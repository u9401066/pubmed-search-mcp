"""
PubMed Search MCP package surface.

The package root is a convenience API for Python callers. Exports are resolved
lazily so a lightweight ``import pubmed_search`` does not also import the MCP
server, every MCP tool module, HTTP clients, YAML support, or optional citation
formatters.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__version__ = "0.5.15"

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # Core Entrez API
    "LiteratureSearcher": ("pubmed_search.infrastructure.ncbi", "LiteratureSearcher"),
    "EntrezBase": ("pubmed_search.infrastructure.ncbi", "EntrezBase"),
    "SearchStrategy": ("pubmed_search.infrastructure.ncbi", "SearchStrategy"),
    "SearchMixin": ("pubmed_search.infrastructure.ncbi", "SearchMixin"),
    "PDFMixin": ("pubmed_search.infrastructure.ncbi", "PDFMixin"),
    "CitationMixin": ("pubmed_search.infrastructure.ncbi", "CitationMixin"),
    "BatchMixin": ("pubmed_search.infrastructure.ncbi", "BatchMixin"),
    "UtilsMixin": ("pubmed_search.infrastructure.ncbi", "UtilsMixin"),
    "ICiteMixin": ("pubmed_search.infrastructure.ncbi.icite", "ICiteMixin"),
    # NCBI Extended / Europe PMC
    "NCBIExtendedClient": ("pubmed_search.infrastructure.sources.ncbi_extended", "NCBIExtendedClient"),
    "EuropePMCClient": ("pubmed_search.infrastructure.sources.europe_pmc", "EuropePMCClient"),
    # Multi-source clients
    "get_semantic_scholar_client": ("pubmed_search.infrastructure.sources", "get_semantic_scholar_client"),
    "get_openalex_client": ("pubmed_search.infrastructure.sources", "get_openalex_client"),
    "get_europe_pmc_client": ("pubmed_search.infrastructure.sources", "get_europe_pmc_client"),
    "get_ncbi_extended_client": ("pubmed_search.infrastructure.sources", "get_ncbi_extended_client"),
    "get_crossref_client": ("pubmed_search.infrastructure.sources", "get_crossref_client"),
    "get_unpaywall_client": ("pubmed_search.infrastructure.sources", "get_unpaywall_client"),
    "SearchSource": ("pubmed_search.infrastructure.sources", "SearchSource"),
    # Export functionality
    "export_ris": ("pubmed_search.application.export.formats", "export_ris"),
    "export_bibtex": ("pubmed_search.application.export.formats", "export_bibtex"),
    "export_csv": ("pubmed_search.application.export.formats", "export_csv"),
    "export_medline": ("pubmed_search.application.export.formats", "export_medline"),
    "export_json": ("pubmed_search.application.export.formats", "export_json"),
    "export_articles": ("pubmed_search.application.export.formats", "export_articles"),
    "SUPPORTED_FORMATS": ("pubmed_search.application.export.formats", "SUPPORTED_FORMATS"),
    "get_fulltext_links": ("pubmed_search.application.export.links", "get_fulltext_links"),
    # OpenURL / institutional access
    "get_openurl_link": ("pubmed_search.infrastructure.sources.openurl", "get_openurl_link"),
    "list_openurl_presets": ("pubmed_search.infrastructure.sources.openurl", "list_presets"),
    "configure_openurl": ("pubmed_search.infrastructure.sources.openurl", "configure_openurl"),
    "get_openurl_config": ("pubmed_search.infrastructure.sources.openurl", "get_openurl_config"),
    # Strategy and query analysis
    "SearchStrategyGenerator": ("pubmed_search.infrastructure.ncbi.strategy", "SearchStrategyGenerator"),
    "QueryAnalyzer": ("pubmed_search.application.search.query_analyzer", "QueryAnalyzer"),
    "QueryComplexity": ("pubmed_search.application.search.query_analyzer", "QueryComplexity"),
    "QueryIntent": ("pubmed_search.application.search.query_analyzer", "QueryIntent"),
    "AnalyzedQuery": ("pubmed_search.application.search.query_analyzer", "AnalyzedQuery"),
    "ResultAggregator": ("pubmed_search.application.search.result_aggregator", "ResultAggregator"),
    "RankingConfig": ("pubmed_search.application.search.result_aggregator", "RankingConfig"),
    # Domain entities
    "UnifiedArticle": ("pubmed_search.domain.entities.article", "UnifiedArticle"),
    # MCP primary surface
    "create_mcp_server": ("pubmed_search.presentation.mcp_server.server", "create_server"),
    "mcp_main": ("pubmed_search.presentation.mcp_server.server", "main"),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve public root exports on first use."""
    try:
        module_name, attr_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *_LAZY_EXPORTS])
