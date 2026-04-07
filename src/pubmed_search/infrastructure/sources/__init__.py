"""
Multi-Source Academic Search

Internal module for searching across multiple academic databases.
Aggregates results from PubMed, Semantic Scholar, OpenAlex, Europe PMC, CORE,
and extended NCBI databases (Gene, PubChem, ClinVar).

This module is NOT exposed as separate MCP tools - it's used internally
by unified_search and related orchestration layers.

Architecture:
    ┌─────────────────────────────────────────────────────────┐
    │        MCP Tools (unified_search, get_fulltext, etc.)    │
    │                    (public orchestration layer)           │
    └───────────────────────────┬─────────────────────────────┘
                                │
    ┌───────────────────────────▼─────────────────────────────┐
    │              MultiSourceSearcher                         │
    │  ┌──────────┬──────────┬──────────┬──────────┬───────┐  │
    │  │  PubMed  │ Sem.S2   │ OpenAlex │ EuropePMC│  CORE │  │
    │  │ (default)│  (alt)   │  (alt)   │(fulltext)│(200M+)│  │
    │  └──────────┴──────────┴──────────┴──────────┴───────┘  │
    │  ┌─────────────────────────────────────────────────────┐│
    │  │        NCBI Extended: Gene | PubChem | ClinVar     ││
    │  └─────────────────────────────────────────────────────┘│
    └─────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, Literal, cast

from pubmed_search.shared.settings import load_settings
from pubmed_search.shared.source_contracts import (
    SourceAdapterCall,
    SourceAdapterResult,
    format_source_adapter_error,
    gather_source_adapter_calls,
)

from .registry import (
    SourceDefinition,
    SourceRegistry,
    SourceSelection,
    SourceSelectionError,
    get_source_registry,
)

logger = logging.getLogger(__name__)

# Lazy imports to avoid startup overhead
_semantic_scholar_client = None
_openalex_client = None
_europe_pmc_client = None
_core_client = None
_scopus_client = None
_web_of_science_client = None
_ncbi_extended_client = None
_crossref_client = None
_unpaywall_client = None
_openurl_builder = None
_clinical_trials_client = None
_openi_client = None


class SearchSource(Enum):
    """Available search sources."""

    PUBMED = "pubmed"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    OPENALEX = "openalex"
    EUROPE_PMC = "europe_pmc"
    CORE = "core"
    SCOPUS = "scopus"
    WEB_OF_SCIENCE = "web_of_science"
    ALL = "all"


AlternateSearchSource = Literal[
    "semantic_scholar",
    "openalex",
    "europe_pmc",
    "core",
    "scopus",
    "web_of_science",
]
AlternateSourceRunner = Callable[
    [str, int, int | None, int | None, bool, bool, str | None],
    Awaitable[list[dict[str, Any]]],
]


def get_semantic_scholar_client(api_key: str | None = None):
    """Get or create Semantic Scholar client (lazy initialization)."""
    global _semantic_scholar_client
    if _semantic_scholar_client is None:
        from .semantic_scholar import SemanticScholarClient

        _semantic_scholar_client = SemanticScholarClient(api_key=api_key)
    return _semantic_scholar_client


def get_openalex_client(email: str | None = None):
    """Get or create OpenAlex client (lazy initialization)."""
    global _openalex_client
    if _openalex_client is None:
        from .openalex import OpenAlexClient

        _openalex_client = OpenAlexClient(email=email)
    return _openalex_client


def get_europe_pmc_client(email: str | None = None):
    """Get or create Europe PMC client (lazy initialization)."""
    global _europe_pmc_client
    if _europe_pmc_client is None:
        from .europe_pmc import EuropePMCClient

        _europe_pmc_client = EuropePMCClient(email=email)
    return _europe_pmc_client


def get_core_client(api_key: str | None = None):
    """Get or create CORE client (lazy initialization)."""
    global _core_client
    if _core_client is None:
        from .core import COREClient

        settings = load_settings()
        _core_client = COREClient(api_key=api_key or settings.core_api_key)
    return _core_client


def get_scopus_client(api_key: str | None = None, insttoken: str | None = None):
    """Get or create Scopus client (lazy initialization, default-off unless licensed)."""
    global _scopus_client
    if _scopus_client is None:
        from .scopus import ScopusClient

        settings = load_settings()
        resolved_api_key = api_key or settings.scopus_api_key
        resolved_insttoken = insttoken or settings.scopus_insttoken
        _scopus_client = ScopusClient(api_key=resolved_api_key, insttoken=resolved_insttoken)
    return _scopus_client


def get_web_of_science_client(api_key: str | None = None):
    """Get or create Web of Science client (lazy initialization, default-off unless licensed)."""
    global _web_of_science_client
    if _web_of_science_client is None:
        from .web_of_science import WebOfScienceClient

        settings = load_settings()
        resolved_api_key = api_key or settings.web_of_science_api_key
        _web_of_science_client = WebOfScienceClient(api_key=resolved_api_key)
    return _web_of_science_client


def get_ncbi_extended_client(email: str | None = None, api_key: str | None = None):
    """Get or create NCBI Extended client (lazy initialization)."""
    global _ncbi_extended_client
    if _ncbi_extended_client is None:
        from .ncbi_extended import NCBIExtendedClient

        settings = load_settings()

        _ncbi_extended_client = NCBIExtendedClient(
            email=email or settings.ncbi_email,
            api_key=api_key or settings.ncbi_api_key,
        )
    return _ncbi_extended_client


def get_crossref_client(email: str | None = None):
    """Get or create CrossRef client (lazy initialization)."""
    global _crossref_client
    if _crossref_client is None:
        from .crossref import CrossRefClient

        settings = load_settings()

        _crossref_client = CrossRefClient(
            email=email or settings.crossref_email,
        )
    return _crossref_client


def get_unpaywall_client(email: str | None = None):
    """Get or create Unpaywall client (lazy initialization)."""
    global _unpaywall_client
    if _unpaywall_client is None:
        from .unpaywall import UnpaywallClient

        settings = load_settings()

        _unpaywall_client = UnpaywallClient(
            email=email or settings.unpaywall_email or settings.ncbi_email,
        )
    return _unpaywall_client


def get_openurl_builder(resolver_base: str | None = None, preset: str | None = None):
    """Get or create OpenURL builder (lazy initialization)."""
    global _openurl_builder
    if _openurl_builder is None:
        from .openurl import OpenURLBuilder, get_openurl_config

        settings = load_settings()

        # Try preset first, then resolver_base, then env var
        if preset:
            _openurl_builder = OpenURLBuilder.from_preset(preset, resolver_base)
        elif resolver_base or settings.openurl_resolver:
            _openurl_builder = OpenURLBuilder(resolver_base=resolver_base or settings.openurl_resolver)
        else:
            # Return a builder that will check config at runtime
            config = get_openurl_config()
            _openurl_builder = config.get_builder()
    return _openurl_builder


def get_openi_client():
    """Get or create Open-i client (lazy initialization)."""
    global _openi_client
    if _openi_client is None:
        from .openi import OpenIClient

        _openi_client = OpenIClient()
    return _openi_client


async def search_alternate_source(
    query: str,
    source: AlternateSearchSource,
    limit: int = 10,
    min_year: int | None = None,
    max_year: int | None = None,
    open_access_only: bool = False,
    has_fulltext: bool = False,
    email: str | None = None,
) -> list[dict[str, Any]]:
    """
    Search an alternate academic source.

    This function is used internally when:
    1. User explicitly requests a different source
    2. PubMed returns few results and cross-search is enabled
    3. User wants open access papers (OpenAlex/DOAJ filter)
    4. User needs full text access (Europe PMC, CORE)

    Args:
        query: Search query
        source: Target source (semantic_scholar, openalex, europe_pmc, core, scopus, or web_of_science)
        limit: Maximum results
        min_year: Minimum publication year
        max_year: Maximum publication year
        open_access_only: Only return open access papers
        has_fulltext: Only return papers with full text (Europe PMC, CORE)
        email: Email for APIs

    Returns:
        List of normalized paper dictionaries
    """
    try:
        return await _search_alternate_source_unchecked(
            query=query,
            source=source,
            limit=limit,
            min_year=min_year,
            max_year=max_year,
            open_access_only=open_access_only,
            has_fulltext=has_fulltext,
            email=email,
        )

    except Exception as e:
        logger.exception(f"Search failed for {source}: {e}")
        return []


async def _search_alternate_source_unchecked(
    query: str,
    source: AlternateSearchSource,
    limit: int = 10,
    min_year: int | None = None,
    max_year: int | None = None,
    open_access_only: bool = False,
    has_fulltext: bool = False,
    email: str | None = None,
) -> list[dict[str, Any]]:
    """Search one alternate source without swallowing source-level exceptions."""
    registry = get_source_registry()
    resolved_source = registry.resolve_key(source) or source
    if not _is_alternate_source(resolved_source):
        logger.warning(f"Unknown alternate source requested: {source}")
        return []

    runner = _ALTERNATE_SOURCE_RUNNERS.get(resolved_source)
    if runner is None:
        logger.warning(f"No alternate source runner registered for: {resolved_source}")
        return []

    return await runner(
        query,
        limit,
        min_year,
        max_year,
        open_access_only,
        has_fulltext,
        email,
    )


async def _run_semantic_scholar_search(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    open_access_only: bool,
    has_fulltext: bool,
    email: str | None,
) -> list[dict[str, Any]]:
    del has_fulltext, email
    client = get_semantic_scholar_client()
    return await client.search(
        query=query,
        limit=limit,
        min_year=min_year,
        max_year=max_year,
        open_access_only=open_access_only,
    )


async def _run_openalex_search(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    open_access_only: bool,
    has_fulltext: bool,
    email: str | None,
) -> list[dict[str, Any]]:
    del has_fulltext
    client = get_openalex_client(email)
    return await client.search(
        query=query,
        limit=limit,
        min_year=min_year,
        max_year=max_year,
        open_access_only=open_access_only,
    )


async def _run_europe_pmc_search(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    open_access_only: bool,
    has_fulltext: bool,
    email: str | None,
) -> list[dict[str, Any]]:
    client = get_europe_pmc_client(email)
    result = await client.search(
        query=query,
        limit=limit,
        min_year=min_year,
        max_year=max_year,
        open_access_only=open_access_only,
        has_fulltext=has_fulltext,
    )
    return result.get("results", [])


async def _run_core_search(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    open_access_only: bool,
    has_fulltext: bool,
    email: str | None,
) -> list[dict[str, Any]]:
    del open_access_only, email

    client = get_core_client()
    result = await client.search(
        query=query,
        limit=limit,
        year_from=min_year,
        year_to=max_year,
        has_fulltext=has_fulltext,
    )
    return result.get("results", [])


async def _run_scopus_search(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    open_access_only: bool,
    has_fulltext: bool,
    email: str | None,
) -> list[dict[str, Any]]:
    del has_fulltext, email
    client = get_scopus_client()
    return await client.search(
        query=query,
        limit=limit,
        min_year=min_year,
        max_year=max_year,
        open_access_only=open_access_only,
    )


async def _run_web_of_science_search(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    open_access_only: bool,
    has_fulltext: bool,
    email: str | None,
) -> list[dict[str, Any]]:
    del has_fulltext, email
    client = get_web_of_science_client()
    return await client.search(
        query=query,
        limit=limit,
        min_year=min_year,
        max_year=max_year,
        open_access_only=open_access_only,
    )


_ALTERNATE_SOURCE_RUNNERS: dict[str, AlternateSourceRunner] = {
    "semantic_scholar": _run_semantic_scholar_search,
    "openalex": _run_openalex_search,
    "europe_pmc": _run_europe_pmc_search,
    "core": _run_core_search,
    "scopus": _run_scopus_search,
    "web_of_science": _run_web_of_science_search,
}


def _is_alternate_source(source: str) -> bool:
    registry = get_source_registry()
    definition = registry.get(source)
    return bool(
        definition
        and definition.selectable_in_unified
        and definition.supports_primary_search
        and definition.key not in {"pubmed"}
        and definition.alternate_search_runner in _ALTERNATE_SOURCE_RUNNERS
        and registry.is_enabled(definition.key)
    )


def _normalize_alternate_sources(sources: list[str]) -> list[AlternateSearchSource]:
    registry = get_source_registry()
    normalized: list[AlternateSearchSource] = []
    for source in sources:
        key = registry.resolve_key(source)
        if key is not None and _is_alternate_source(key):
            normalized.append(cast("AlternateSearchSource", key))
    return normalized


async def cross_search(
    query: str,
    sources: list[str] | None = None,
    limit_per_source: int = 5,
    min_year: int | None = None,
    max_year: int | None = None,
    open_access_only: bool = False,
    has_fulltext: bool = False,
    email: str | None = None,
    deduplicate: bool = True,
) -> dict[str, Any]:
    """
    Search across multiple sources and merge results.

    This is used internally when PubMed results are insufficient
    or when user wants comprehensive coverage.

    Args:
        query: Search query
        sources: List of sources (default: ["semantic_scholar", "openalex", "europe_pmc", "core"])
        limit_per_source: Max results per source
        min_year: Minimum publication year
        max_year: Maximum publication year
        open_access_only: Only return open access papers
        has_fulltext: Only return papers with full text (Europe PMC, CORE)
        email: Email for APIs
        deduplicate: Remove duplicate papers (by DOI/PMID)

    Returns:
        Dict with:
        - results: Merged list of papers
        - by_source: Results grouped by source
        - stats: Search statistics
    """
    if sources is None:
        sources = ["semantic_scholar", "openalex", "europe_pmc", "core"]

    all_results = []
    by_source = {}

    # Filter out pubmed (handled by main LiteratureSearcher)
    valid_sources = _normalize_alternate_sources(sources)

    async def _search_one(source: AlternateSearchSource) -> list[dict[str, Any]]:
        """Search a single source through the public alternate-source seam."""
        return await search_alternate_source(
            query=query,
            source=source,
            limit=limit_per_source,
            min_year=min_year,
            max_year=max_year,
            open_access_only=open_access_only,
            has_fulltext=has_fulltext if source in ("europe_pmc", "core") else False,
            email=email,
        )

    def _build_cross_search_call(source: AlternateSearchSource) -> SourceAdapterCall[dict[str, Any]]:
        async def _execute() -> list[dict[str, Any]]:
            return await _search_one(source)

        return SourceAdapterCall(
            source=source,
            operation="cross_search",
            execute=_execute,
        )

    search_results: list[SourceAdapterResult[dict[str, Any]]] = await gather_source_adapter_calls(
        [_build_cross_search_call(source) for source in valid_sources]
    )

    for source_result in search_results:
        by_source[source_result.source] = source_result.items
        all_results.extend(source_result.items)
        for error in source_result.errors:
            logger.exception("Cross-search failed for %s", format_source_adapter_error(error))

    # Deduplicate by DOI or title
    if deduplicate:
        all_results = _deduplicate_results(all_results)

    return {
        "results": all_results,
        "by_source": by_source,
        "stats": {
            "total": len(all_results),
            "sources_searched": list(by_source.keys()),
            "per_source": {s: len(r) for s, r in by_source.items()},
        },
    }


def _deduplicate_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Remove duplicate papers based on DOI or title similarity.

    Priority: Keep PubMed > Semantic Scholar > OpenAlex
    (because PubMed has more structured metadata)
    """
    seen_dois = set()
    seen_pmids = set()
    seen_titles = set()
    unique = []

    # Sort by source priority
    source_priority = {
        "pubmed": 0,
        "semantic_scholar": 1,
        "openalex": 2,
        "scopus": 3,
        "web_of_science": 4,
        "core": 5,
    }
    sorted_results = sorted(results, key=lambda x: source_priority.get(x.get("_source", ""), 99))

    for paper in sorted_results:
        doi = (paper.get("doi") or "").lower().strip()
        pmid = (paper.get("pmid") or "").strip()
        title = _normalize_title(paper.get("title") or "")

        # Check for duplicates
        is_duplicate = False

        if (doi and doi in seen_dois) or (pmid and pmid in seen_pmids) or (title and title in seen_titles):
            is_duplicate = True

        if not is_duplicate:
            unique.append(paper)
            if doi:
                seen_dois.add(doi)
            if pmid:
                seen_pmids.add(pmid)
            if title:
                seen_titles.add(title)

    return unique


def _normalize_title(title: str) -> str:
    """Normalize title for comparison."""
    # Remove punctuation, lowercase, remove extra spaces
    title = re.sub(r"[^\w\s]", "", title.lower())
    return " ".join(title.split())


async def get_paper_from_any_source(
    identifier: str,
    email: str | None = None,
) -> dict[str, Any] | None:
    """
    Get paper details from any source based on identifier type.

    Args:
        identifier: DOI, PMID, S2 ID, or OpenAlex ID
        email: Email for APIs

    Returns:
        Paper dictionary or None
    """
    identifier = identifier.strip()

    # DOI
    if identifier.startswith(("10.", "doi:")):
        doi = identifier.replace("doi:", "")

        # Try Semantic Scholar first (faster)
        client = get_semantic_scholar_client()
        result = await client.get_paper(f"DOI:{doi}")
        if result:
            return result

        # Fallback to OpenAlex
        client = get_openalex_client(email)
        return await client.get_work(f"doi:{doi}")

    # PMID
    if identifier.isdigit() or identifier.upper().startswith("PMID:"):
        pmid = identifier.upper().replace("PMID:", "")

        # Try Semantic Scholar
        client = get_semantic_scholar_client()
        result = await client.get_paper(f"PMID:{pmid}")
        if result:
            return result

        # Fallback to OpenAlex
        client = get_openalex_client(email)
        return await client.get_work(f"pmid:{pmid}")

    # S2 ID (40 char hex)
    if len(identifier) == 40 and all(c in "0123456789abcdef" for c in identifier.lower()):
        client = get_semantic_scholar_client()
        return await client.get_paper(identifier)

    # OpenAlex ID
    if identifier.startswith(("W", "https://openalex.org/")):
        client = get_openalex_client(email)
        return await client.get_work(identifier)

    logger.warning(f"Unknown identifier format: {identifier}")
    return None


async def get_fulltext_xml(pmcid: str, email: str | None = None) -> str | None:
    """
    Get full text XML from Europe PMC.

    This is the UNIQUE feature of Europe PMC - direct full text access!

    Args:
        pmcid: PMC ID (e.g., "PMC7096777" or just "7096777")
        email: Contact email

    Returns:
        Full text XML string or None
    """
    client = get_europe_pmc_client(email)
    return await client.get_fulltext_xml(pmcid)


async def get_fulltext_parsed(pmcid: str, email: str | None = None) -> dict[str, Any]:
    """
    Get parsed full text from Europe PMC.

    Args:
        pmcid: PMC ID
        email: Contact email

    Returns:
        Dict with structured content (title, abstract, sections, references)
    """
    client = get_europe_pmc_client(email)
    xml = await client.get_fulltext_xml(pmcid)
    if xml:
        return client.parse_fulltext_xml(xml)
    return {"error": "Full text not available"}


# ============================================================================
# PDF/Fulltext Download (NEW: Multi-source PDF link discovery)
# ============================================================================
_fulltext_downloader = None


def get_fulltext_downloader():
    """Get or create FulltextDownloader instance (lazy initialization)."""
    global _fulltext_downloader
    if _fulltext_downloader is None:
        from .fulltext_download import FulltextDownloader

        _fulltext_downloader = FulltextDownloader()
    return _fulltext_downloader


# Export for convenience
__all__ = [
    "SearchSource",
    "SourceDefinition",
    "SourceRegistry",
    "SourceSelection",
    "SourceSelectionError",
    "cross_search",
    "get_core_client",
    "get_crossref_client",
    "get_europe_pmc_client",
    "get_fulltext_downloader",
    "get_fulltext_parsed",
    "get_fulltext_xml",
    "get_ncbi_extended_client",
    "get_openalex_client",
    "get_openi_client",
    "get_openurl_builder",
    "get_paper_from_any_source",
    "get_scopus_client",
    "get_web_of_science_client",
    "get_source_registry",
    "get_semantic_scholar_client",
    "get_unpaywall_client",
    "search_alternate_source",
]
