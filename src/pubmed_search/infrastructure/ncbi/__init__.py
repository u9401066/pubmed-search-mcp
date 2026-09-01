"""
Entrez Module - NCBI Entrez API Integration

This module provides a modular interface to NCBI's Entrez E-utilities.

Module Structure:
    base.py         - Base configuration and shared utilities
    search.py       - Core search functionality (esearch, efetch)
    pdf.py          - PDF download from PMC Open Access
    citation.py     - Citation network (related, citing, references)
    batch.py        - Batch processing with History Server
    utils.py        - Utility functions (spell check, MeSH, export)
    icite.py        - NIH iCite citation metrics integration

Usage:
    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

    searcher = LiteratureSearcher(email="your@email.com")
    page = await searcher.search_page("diabetes treatment", limit=10)
    results = page.items
"""

from __future__ import annotations

from .base import EntrezBase, NCBIInfrastructureError, NCBIProviderSchemaError, SearchStrategy
from .batch import BatchMixin
from .citation import CitationMixin
from .icite import ICiteMixin
from .pdf import PDFMixin
from .search import SearchMixin
from .utils import UtilsMixin


class LiteratureSearcher(SearchMixin, PDFMixin, CitationMixin, BatchMixin, UtilsMixin, ICiteMixin, EntrezBase):
    """
    Complete literature search interface combining all Entrez functionality.

    This class composes the canonical Entrez operations into one infrastructure
    dependency for the application layer.

    Example:
        >>> searcher = LiteratureSearcher(email="researcher@example.com")
        >>> page = await searcher.search_page("machine learning diagnosis", limit=5)
        >>> for paper in page.items:
        ...     print(paper['title'])
    """


__all__ = [
    "BatchMixin",
    "CitationMixin",
    "EntrezBase",
    "LiteratureSearcher",
    "NCBIInfrastructureError",
    "NCBIProviderSchemaError",
    "PDFMixin",
    "SearchMixin",
    "SearchStrategy",
    "UtilsMixin",
]
