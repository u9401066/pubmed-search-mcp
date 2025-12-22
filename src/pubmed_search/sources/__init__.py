"""
Multi-Source Academic Search

Internal module for searching across multiple academic databases.
Aggregates results from PubMed, Semantic Scholar, OpenAlex, Europe PMC, CORE,
and extended NCBI databases (Gene, PubChem, ClinVar).

This module is NOT exposed as separate MCP tools - it's used internally
by existing tools via the `source` parameter.

Architecture:
    ┌─────────────────────────────────────────────────────────┐
    │           MCP Tools (search_literature, etc.)           │
    │                      (unchanged API)                     │
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

import logging
import re
from enum import Enum
from typing import Any, Literal

logger = logging.getLogger(__name__)

# Lazy imports to avoid startup overhead
_semantic_scholar_client = None
_openalex_client = None
_europe_pmc_client = None
_core_client = None
_ncbi_extended_client = None


class SearchSource(Enum):
    """Available search sources."""
    PUBMED = "pubmed"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    OPENALEX = "openalex"
    EUROPE_PMC = "europe_pmc"
    CORE = "core"
    ALL = "all"


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
        import os
        _core_client = COREClient(api_key=api_key or os.environ.get("CORE_API_KEY"))
    return _core_client


def get_ncbi_extended_client(email: str | None = None, api_key: str | None = None):
    """Get or create NCBI Extended client (lazy initialization)."""
    global _ncbi_extended_client
    if _ncbi_extended_client is None:
        from .ncbi_extended import NCBIExtendedClient
        import os
        _ncbi_extended_client = NCBIExtendedClient(
            email=email or os.environ.get("NCBI_EMAIL"),
            api_key=api_key or os.environ.get("NCBI_API_KEY"),
        )
    return _ncbi_extended_client


def search_alternate_source(
    query: str,
    source: Literal["semantic_scholar", "openalex", "europe_pmc", "core"],
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
        source: Target source (semantic_scholar, openalex, europe_pmc, or core)
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
        if source == "semantic_scholar":
            client = get_semantic_scholar_client()
            return client.search(
                query=query,
                limit=limit,
                min_year=min_year,
                max_year=max_year,
                open_access_only=open_access_only,
            )
        
        elif source == "openalex":
            client = get_openalex_client(email)
            return client.search(
                query=query,
                limit=limit,
                min_year=min_year,
                max_year=max_year,
                open_access_only=open_access_only,
            )
        
        elif source == "europe_pmc":
            client = get_europe_pmc_client(email)
            result = client.search(
                query=query,
                limit=limit,
                min_year=min_year,
                max_year=max_year,
                open_access_only=open_access_only,
                has_fulltext=has_fulltext,
            )
            return result.get("results", [])
        
        elif source == "core":
            client = get_core_client()
            result = client.search(
                query=query,
                limit=limit,
                year_from=min_year,
                year_to=max_year,
                has_fulltext=has_fulltext,
            )
            return result.get("results", [])
        
        else:
            logger.warning(f"Unknown source: {source}")
            return []
            
    except Exception as e:
        logger.error(f"Search failed for {source}: {e}")
        return []


def cross_search(
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
    
    for source in sources:
        try:
            if source == "pubmed":
                # PubMed is handled by the main LiteratureSearcher
                # This function is for alternate sources only
                continue
                
            results = search_alternate_source(
                query=query,
                source=source,
                limit=limit_per_source,
                min_year=min_year,
                max_year=max_year,
                open_access_only=open_access_only,
                has_fulltext=has_fulltext if source in ("europe_pmc", "core") else False,
                email=email,
            )
            
            by_source[source] = results
            all_results.extend(results)
            
        except Exception as e:
            logger.error(f"Cross-search failed for {source}: {e}")
            by_source[source] = []
    
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
    source_priority = {"pubmed": 0, "semantic_scholar": 1, "openalex": 2}
    sorted_results = sorted(
        results,
        key=lambda x: source_priority.get(x.get("_source", ""), 99)
    )
    
    for paper in sorted_results:
        doi = (paper.get("doi") or "").lower().strip()
        pmid = (paper.get("pmid") or "").strip()
        title = _normalize_title(paper.get("title") or "")
        
        # Check for duplicates
        is_duplicate = False
        
        if doi and doi in seen_dois:
            is_duplicate = True
        elif pmid and pmid in seen_pmids:
            is_duplicate = True
        elif title and title in seen_titles:
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
    title = re.sub(r'[^\w\s]', '', title.lower())
    title = ' '.join(title.split())
    return title


def get_paper_from_any_source(
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
    if identifier.startswith("10.") or identifier.startswith("doi:"):
        doi = identifier.replace("doi:", "")
        
        # Try Semantic Scholar first (faster)
        client = get_semantic_scholar_client()
        result = client.get_paper(f"DOI:{doi}")
        if result:
            return result
        
        # Fallback to OpenAlex
        client = get_openalex_client(email)
        return client.get_work(f"doi:{doi}")
    
    # PMID
    if identifier.isdigit() or identifier.upper().startswith("PMID:"):
        pmid = identifier.upper().replace("PMID:", "")
        
        # Try Semantic Scholar
        client = get_semantic_scholar_client()
        result = client.get_paper(f"PMID:{pmid}")
        if result:
            return result
        
        # Fallback to OpenAlex
        client = get_openalex_client(email)
        return client.get_work(f"pmid:{pmid}")
    
    # S2 ID (40 char hex)
    if len(identifier) == 40 and all(c in '0123456789abcdef' for c in identifier.lower()):
        client = get_semantic_scholar_client()
        return client.get_paper(identifier)
    
    # OpenAlex ID
    if identifier.startswith("W") or identifier.startswith("https://openalex.org/"):
        client = get_openalex_client(email)
        return client.get_work(identifier)
    
    logger.warning(f"Unknown identifier format: {identifier}")
    return None


def get_fulltext_xml(pmcid: str, email: str | None = None) -> str | None:
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
    return client.get_fulltext_xml(pmcid)


def get_fulltext_parsed(pmcid: str, email: str | None = None) -> dict[str, Any]:
    """
    Get parsed full text from Europe PMC.
    
    Args:
        pmcid: PMC ID
        email: Contact email
        
    Returns:
        Dict with structured content (title, abstract, sections, references)
    """
    client = get_europe_pmc_client(email)
    xml = client.get_fulltext_xml(pmcid)
    if xml:
        return client.parse_fulltext_xml(xml)
    return {"error": "Full text not available"}


# Export for convenience
__all__ = [
    "SearchSource",
    "search_alternate_source",
    "cross_search",
    "get_paper_from_any_source",
    "get_semantic_scholar_client",
    "get_openalex_client",
    "get_europe_pmc_client",
    "get_core_client",
    "get_ncbi_extended_client",
    "get_fulltext_xml",
    "get_fulltext_parsed",
]
