"""
PubMed Search MCP - Complete PubMed/NCBI Search Library

A comprehensive library for searching PubMed, NCBI databases, and other academic sources.
Provides MCP server integration and standalone Python API.

Quick Start:
    from pubmed_search import LiteratureSearcher

    searcher = LiteratureSearcher(email="your@email.com")
    results = searcher.search("diabetes treatment", limit=10)

    for article in results:
        print(f"{article['pmid']}: {article['title']}")

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

Architecture (DDD):
    domain/          - Core business logic (entities, value objects)
    application/     - Use cases (search, export, session)
    infrastructure/  - External systems (NCBI, Europe PMC, etc.)
    presentation/    - User interfaces (MCP server, REST API)
    shared/          - Cross-cutting concerns (exceptions, utils)
"""

# ═══════════════════════════════════════════════════════════════════
# Core Entrez API
# ═══════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════
# Export functionality
# ═══════════════════════════════════════════════════════════════════
from .application.export import (
    SUPPORTED_FORMATS,
    export_articles,
    export_bibtex,
    export_csv,
    export_json,
    export_medline,
    export_ris,
    get_fulltext_links,
)

# ═══════════════════════════════════════════════════════════════════
# Strategy & Query Analysis
# ═══════════════════════════════════════════════════════════════════
from .application.search import (
    AnalyzedQuery,
    QueryAnalyzer,
    QueryComplexity,
    QueryIntent,
    RankingConfig,
    ResultAggregator,
)

# ═══════════════════════════════════════════════════════════════════
# Domain Entities
# ═══════════════════════════════════════════════════════════════════
from .domain.entities.article import UnifiedArticle
from .infrastructure.ncbi import (
    BatchMixin,
    CitationMixin,
    EntrezBase,
    LiteratureSearcher,
    PDFMixin,
    SearchMixin,
    SearchStrategy,
    UtilsMixin,
)

# HTTP Client and PubMed Client
from .infrastructure.http import PubMedClient
from .infrastructure.http.pubmed_client import SearchResult

# iCite metrics
from .infrastructure.ncbi.icite import ICiteMixin

# Strategy generator
from .infrastructure.ncbi.strategy import SearchStrategyGenerator

# ═══════════════════════════════════════════════════════════════════
# Multi-source clients (lazy-loaded)
# ═══════════════════════════════════════════════════════════════════
from .infrastructure.sources import (
    SearchSource,
    get_crossref_client,
    get_europe_pmc_client,
    get_ncbi_extended_client,
    get_openalex_client,
    get_semantic_scholar_client,
    get_unpaywall_client,
)

# ═══════════════════════════════════════════════════════════════════
# Europe PMC (fulltext, text mining)
# ═══════════════════════════════════════════════════════════════════
from .infrastructure.sources.europe_pmc import EuropePMCClient

# ═══════════════════════════════════════════════════════════════════
# NCBI Extended (Gene, PubChem, ClinVar)
# ═══════════════════════════════════════════════════════════════════
from .infrastructure.sources.ncbi_extended import NCBIExtendedClient

# ═══════════════════════════════════════════════════════════════════
# OpenURL / Institutional access
# ═══════════════════════════════════════════════════════════════════
from .infrastructure.sources.openurl import (
    configure_openurl,
    get_openurl_config,
    get_openurl_link,
)
from .infrastructure.sources.openurl import (
    list_presets as list_openurl_presets,
)

# ═══════════════════════════════════════════════════════════════════
# Presentation - MCP Server
# ═══════════════════════════════════════════════════════════════════
from .presentation.mcp_server import (
    create_server as create_mcp_server,
)
from .presentation.mcp_server import (
    main as mcp_main,
)

__version__ = "0.3.4"

__all__ = [
    # ═══════════════════════════════════════════════════════════════════
    # Core Entrez API
    # ═══════════════════════════════════════════════════════════════════
    "LiteratureSearcher",
    "EntrezBase",
    "SearchStrategy",
    "SearchMixin",
    "PDFMixin",
    "CitationMixin",
    "BatchMixin",
    "UtilsMixin",
    "ICiteMixin",
    # HTTP Client
    "PubMedClient",
    "SearchResult",
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
    # ═══════════════════════════════════════════════════════════════════
    # Domain Entities
    # ═══════════════════════════════════════════════════════════════════
    "UnifiedArticle",
    # ═══════════════════════════════════════════════════════════════════
    # MCP Server
    # ═══════════════════════════════════════════════════════════════════
    "create_mcp_server",
    "mcp_main",
]
