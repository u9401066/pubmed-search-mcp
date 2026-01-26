"""
Infrastructure Layer - External Systems Integration

Contains:
- ncbi: NCBI Entrez, iCite, and Citation Exporter APIs
- sources: External sources (Europe PMC, CORE, CrossRef, etc.)
- http: HTTP client utilities
"""

from .ncbi import LiteratureSearcher, SearchStrategy
from .ncbi.citation_exporter import NCBICitationExporter, export_citations_official

__all__ = [
    "LiteratureSearcher",
    "SearchStrategy",
    "export_citations_official",
    "NCBICitationExporter",
]
