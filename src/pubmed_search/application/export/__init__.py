"""
Exports Module - Citation export and file download functionality.

Provides:
- Citation export in multiple formats (RIS, BibTeX, CSV, MEDLINE, JSON)
- Guided local note export for wiki/Foam/Markdown libraries
- Fulltext link retrieval (PMC, DOI, Publisher)
- Batch export and download preparation

Note: PDF download functionality is in entrez.pdf (PDFMixin).
This module focuses on citation formats and link aggregation.
"""

from __future__ import annotations

from .formats import (
    SUPPORTED_FORMATS,
    export_articles,
    export_bibtex,
    export_csv,
    export_json,
    export_medline,
    export_ris,
)
from .links import (
    get_batch_fulltext_links,
    get_fulltext_links,
    get_fulltext_links_with_lookup,
    summarize_access,
)
from .notes import SUPPORTED_NOTE_FORMATS, resolve_note_export_dir, write_literature_notes

__all__ = [
    # Format exporters
    "export_ris",
    "export_bibtex",
    "export_csv",
    "export_medline",
    "export_json",
    "export_articles",  # Unified export function
    "SUPPORTED_FORMATS",
    "SUPPORTED_NOTE_FORMATS",
    "resolve_note_export_dir",
    "write_literature_notes",
    # Link utilities
    "get_fulltext_links",
    "get_fulltext_links_with_lookup",
    "get_batch_fulltext_links",
    "summarize_access",
]
