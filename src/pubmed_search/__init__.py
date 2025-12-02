"""
PubMed Search - Independent PubMed/Entrez Search Library

A standalone library for searching PubMed and interacting with NCBI Entrez APIs.
Designed to be used as a submodule in other projects.

Usage:
    from pubmed_search import PubMedClient, SearchResult
    
    client = PubMedClient(email="your@email.com")
    results = client.search("diabetes treatment", limit=10)
    
    for article in results:
        print(f"{article.pmid}: {article.title}")

Features:
    - PubMed search with various strategies (recent, relevance, etc.)
    - Related articles discovery
    - Citation network exploration
    - PDF download from PMC Open Access
    - Batch processing for large result sets
    - MeSH term validation
    - Citation matching
"""

from .client import PubMedClient, SearchResult, SearchStrategy
from .entrez import (
    LiteratureSearcher,
    EntrezBase,
    SearchMixin,
    PDFMixin,
    CitationMixin,
    BatchMixin,
    UtilsMixin,
)

__version__ = "0.1.0"

__all__ = [
    # High-level API
    "PubMedClient",
    "SearchResult", 
    "SearchStrategy",
    # Low-level Entrez API
    "LiteratureSearcher",
    "EntrezBase",
    "SearchMixin",
    "PDFMixin",
    "CitationMixin",
    "BatchMixin",
    "UtilsMixin",
]
