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
    from pubmed_search.entrez import LiteratureSearcher
    
    searcher = LiteratureSearcher(email="your@email.com")
    results = searcher.search("diabetes treatment", limit=10)
"""

from .base import EntrezBase, SearchStrategy
from .search import SearchMixin
from .pdf import PDFMixin
from .citation import CitationMixin
from .batch import BatchMixin
from .utils import UtilsMixin
from .icite import ICiteMixin


class LiteratureSearcher(
    SearchMixin,
    PDFMixin,
    CitationMixin,
    BatchMixin,
    UtilsMixin,
    ICiteMixin,
    EntrezBase
):
    """
    Complete literature search interface combining all Entrez functionality.
    
    This class uses mixins to provide a clean, modular API while maintaining
    backward compatibility with the original LiteratureSearcher interface.
    
    Example:
        >>> searcher = LiteratureSearcher(email="researcher@example.com")
        >>> results = searcher.search("machine learning diagnosis", limit=5)
        >>> for paper in results:
        ...     print(paper['title'])
    """
    pass


__all__ = [
    'LiteratureSearcher',
    'EntrezBase',
    'SearchStrategy',
    'SearchMixin',
    'PDFMixin',
    'CitationMixin',
    'BatchMixin',
    'UtilsMixin',
]
