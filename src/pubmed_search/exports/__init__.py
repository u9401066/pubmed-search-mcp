"""
Exports Module - Citation export and file download functionality.

Provides:
- Citation export in multiple formats (RIS, BibTeX, CSV, MEDLINE, JSON)
- Fulltext link retrieval (PMC, DOI, Publisher)
- Batch export and download preparation

Note: PDF download functionality is in entrez.pdf (PDFMixin).
This module focuses on citation formats and link aggregation.
"""

from .formats import (
    export_ris,
    export_bibtex,
    export_csv,
    export_medline,
    export_json,
    export_articles,
    SUPPORTED_FORMATS,
)
from .links import (
    get_fulltext_links,
    get_fulltext_links_with_lookup,
    get_batch_fulltext_links,
    summarize_access,
)

__all__ = [
    # Format exporters
    "export_ris",
    "export_bibtex", 
    "export_csv",
    "export_medline",
    "export_json",
    "export_articles",  # Unified export function
    "SUPPORTED_FORMATS",
    # Link utilities
    "get_fulltext_links",
    "get_fulltext_links_with_lookup",
    "get_batch_fulltext_links",
    "summarize_access",
]
