"""Shared value objects for the staged fulltext retrieval pipeline.

Design:
    These types are consumed by the discovery, fetch, and extract helpers as
    well as the backward-compatible downloader facade. They provide the common
    language for source ranking, download outcomes, and normalized fulltext
    payloads.

Maintenance:
    Keep this module free of network or parser logic. When the pipeline gains
    new phases or capabilities, extend the models here first so cross-module
    contracts stay explicit and easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

AccessType = Literal[
    "open_access",
    "green_oa",
    "gold",
    "bronze",
    "hybrid",
    "subscription",
    "institutional",
    "unknown",
]


class PDFSource(Enum):
    """PDF/fulltext source ordered by preference."""

    EUROPE_PMC = ("europe_pmc", 1, "Europe PMC")
    UNPAYWALL_PUBLISHER = ("unpaywall_publisher", 2, "Publisher (via Unpaywall)")
    PMC = ("pmc", 3, "PubMed Central")
    UNPAYWALL_REPOSITORY = ("unpaywall_repository", 4, "Repository (via Unpaywall)")
    CORE = ("core", 5, "CORE")
    SEMANTIC_SCHOLAR = ("semantic_scholar", 6, "Semantic Scholar")
    OPENALEX = ("openalex", 7, "OpenAlex")
    INSTITUTIONAL_RESOLVER = ("institutional_resolver", 8, "Institutional Resolver")
    OPENURL = INSTITUTIONAL_RESOLVER
    ARXIV = ("arxiv", 9, "arXiv")
    BIORXIV = ("biorxiv", 10, "bioRxiv")
    MEDRXIV = ("medrxiv", 11, "medRxiv")
    DOI_REDIRECT = ("doi_redirect", 12, "Publisher (DOI)")
    CROSSREF = ("crossref", 13, "CrossRef")
    DOAJ = ("doaj", 14, "DOAJ")
    ZENODO = ("zenodo", 15, "Zenodo")
    INTERNET_ARCHIVE = ("internet_archive", 16, "Internet Archive")
    BROWSER_SESSION = ("browser_session", 17, "Browser Session")

    @property
    def source_id(self) -> str:
        return self.value[0]

    @property
    def priority(self) -> int:
        return self.value[1]

    @property
    def display_name(self) -> str:
        return self.value[2]


@dataclass
class PDFLink:
    """A candidate PDF/fulltext link with source metadata."""

    url: str
    source: PDFSource
    access_type: AccessType = "unknown"
    version: str | None = None
    license: str | None = None
    is_direct_pdf: bool = True
    confidence: float = 1.0

    def __lt__(self, other: PDFLink) -> bool:
        if self.source.priority != other.source.priority:
            return self.source.priority < other.source.priority
        return self.confidence > other.confidence


@dataclass
class DownloadResult:
    """Result of attempting to retrieve a PDF payload."""

    success: bool
    content: bytes | None = None
    content_type: str | None = None
    source: PDFSource | None = None
    url: str | None = None
    error: str | None = None
    file_size: int = 0
    retry_after: float | None = None

    @property
    def is_pdf(self) -> bool:
        content = self.content
        if content is None:
            return False
        return content[:4] == b"%PDF"


@dataclass
class FulltextResult:
    """Normalized fulltext retrieval payload used by the downloader facade."""

    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    title: str | None = None
    text_content: str | None = None
    pdf_bytes: bytes | None = None
    resolved_pdf_url: str | None = None
    retrieved_url: str | None = None
    structured_sections: dict[str, str] | None = None
    pdf_links: list[PDFLink] = field(default_factory=list)
    source_used: PDFSource | None = None
    content_type: Literal["xml", "pdf", "text", "none"] = "none"
    extraction_method: str | None = None
    has_figures: bool = False
    has_tables: bool = False
    has_references: bool = False
    word_count: int = 0
    file_size: int = 0
    error: str | None = None


__all__ = [
    "AccessType",
    "DownloadResult",
    "FulltextResult",
    "PDFLink",
    "PDFSource",
]
