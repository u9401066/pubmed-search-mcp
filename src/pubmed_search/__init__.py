"""
PubMed Search MCP - Complete PubMed/NCBI Search Library

A comprehensive library for searching PubMed, NCBI databases, and other academic sources.
Provides MCP server integration and standalone Python API.

Quick Start:
    from pubmed_search import PubMedClient, SearchResult

    client = PubMedClient(email="your@email.com")
    results = client.search("diabetes treatment", limit=10)

    for article in results:
        print(f"{article.pmid}: {article.title}")

Extended Usage:
    # NCBI Extended (Gene, PubChem, ClinVar)
    from pubmed_search import NCBIExtendedClient
    ncbi = NCBIExtendedClient(email="your@email.com")
    genes = ncbi.search_gene("BRCA1", organism="human")

    # Europe PMC (fulltext, text mining)
    from pubmed_search import EuropePMCClient
    pmc = EuropePMCClient()
    fulltext = pmc.get_fulltext_xml("PMC1234567")

    # Export citations
    from pubmed_search import export_articles
    ris_content = export_articles(articles, format="ris")

    # OpenURL / Institutional access
    from pubmed_search import get_openurl_link, list_openurl_presets
    link = get_openurl_link(article, preset="ntu")

Features:
    - PubMed search with various strategies (recent, relevance, etc.)
    - NCBI Extended: Gene, PubChem, ClinVar databases
    - Europe PMC: Fulltext XML, text-mined annotations
    - Multi-source: OpenAlex, Semantic Scholar, CrossRef
    - Citation network exploration (citing, references, related)
    - NIH iCite metrics (RCR, percentile)
    - Export: RIS, BibTeX, CSV, MEDLINE, JSON
    - OpenURL institutional link resolver
    - MCP server for AI agent integration
"""

from .client import PubMedClient, SearchResult, SearchStrategy

# Core Entrez API
from .entrez import (
    LiteratureSearcher,
    EntrezBase,
    SearchMixin,
    PDFMixin,
    CitationMixin,
    BatchMixin,
    UtilsMixin,
)

# NCBI Extended (Gene, PubChem, ClinVar)
from .sources.ncbi_extended import NCBIExtendedClient

# Europe PMC (fulltext, text mining)
from .sources.europe_pmc import EuropePMCClient

# Multi-source clients
from .sources import (
    get_semantic_scholar_client,
    get_openalex_client,
    get_europe_pmc_client,
    get_ncbi_extended_client,
    get_crossref_client,
    get_unpaywall_client,
    SearchSource,
)

# Export functionality
from .exports import (
    export_ris,
    export_bibtex,
    export_csv,
    export_medline,
    export_json,
    export_articles,
    SUPPORTED_FORMATS,
    get_fulltext_links,
)

# OpenURL / Institutional access
from .sources.openurl import (
    get_openurl_link,
    list_presets as list_openurl_presets,
    configure_openurl,
    get_openurl_config,
)

# iCite metrics
from .entrez.icite import ICiteMixin

# Strategy generator
from .entrez.strategy import SearchStrategyGenerator

# Unified search components
from .unified import (
    QueryAnalyzer,
    QueryComplexity,
    QueryIntent,
    AnalyzedQuery,
    ResultAggregator,
    RankingConfig,
)

__version__ = "0.1.29"

__all__ = [
    # ═══════════════════════════════════════════════════════════════════
    # High-level API
    # ═══════════════════════════════════════════════════════════════════
    "PubMedClient",
    "SearchResult",
    "SearchStrategy",
    
    # ═══════════════════════════════════════════════════════════════════
    # Core Entrez API
    # ═══════════════════════════════════════════════════════════════════
    "LiteratureSearcher",
    "EntrezBase",
    "SearchMixin",
    "PDFMixin",
    "CitationMixin",
    "BatchMixin",
    "UtilsMixin",
    "ICiteMixin",
    
    # ═══════════════════════════════════════════════════════════════════
    # NCBI Extended (Gene, PubChem, ClinVar)
    # ═══════════════════════════════════════════════════════════════════
    "NCBIExtendedClient",
    
    # ═══════════════════════════════════════════════════════════════════
    # Europe PMC (fulltext, text mining)
    # ═══════════════════════════════════════════════════════════════════
    "EuropePMCClient",
    
    # ═══════════════════════════════════════════════════════════════════
    # Multi-source clients (lazy-loaded)
    # ═══════════════════════════════════════════════════════════════════
    "get_semantic_scholar_client",
    "get_openalex_client",
    "get_europe_pmc_client",
    "get_ncbi_extended_client",
    "get_crossref_client",
    "get_unpaywall_client",
    "SearchSource",
    
    # ═══════════════════════════════════════════════════════════════════
    # Export functionality
    # ═══════════════════════════════════════════════════════════════════
    "export_ris",
    "export_bibtex",
    "export_csv",
    "export_medline",
    "export_json",
    "export_articles",
    "SUPPORTED_FORMATS",
    "get_fulltext_links",
    
    # ═══════════════════════════════════════════════════════════════════
    # OpenURL / Institutional access
    # ═══════════════════════════════════════════════════════════════════
    "get_openurl_link",
    "list_openurl_presets",
    "configure_openurl",
    "get_openurl_config",
    
    # ═══════════════════════════════════════════════════════════════════
    # Strategy & Query Analysis
    # ═══════════════════════════════════════════════════════════════════
    "SearchStrategyGenerator",
    "QueryAnalyzer",
    "QueryComplexity",
    "QueryIntent",
    "AnalyzedQuery",
    "ResultAggregator",
    "RankingConfig",
]
