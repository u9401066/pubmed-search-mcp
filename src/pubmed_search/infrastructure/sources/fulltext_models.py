"""Shared value objects for the staged fulltext retrieval pipeline.

Design:
    These types are consumed by the discovery, fetch, and extract helpers and
    their current downloader coordinator. They provide the common language for
    source ranking, download outcomes, and normalized fulltext payloads.

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
LinkDiscoveryCoverage = Literal["complete", "partial", "unavailable"]
LinkDiscoveryErrorKind = Literal["http", "timeout", "transport", "retryable", "validation", "unexpected"]


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


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
class LinkDiscoverySourceError:
    """Sanitized failure reported by one fulltext link source.

    Raw provider exception text is deliberately absent from this contract: it
    can contain request URLs, credentials, response bodies, or local paths.
    """

    source: str
    kind: LinkDiscoveryErrorKind
    retryable: bool = False
    status_code: int | None = None
    code: Literal["source_unavailable"] = field(default="source_unavailable", init=False)
    message: str = field(
        default="The upstream link source was unavailable during this request.",
        init=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            msg = "Link discovery error source must be non-empty"
            raise TypeError(msg)
        if self.kind not in {"http", "timeout", "transport", "retryable", "validation", "unexpected"}:
            msg = "Link discovery error kind is invalid"
            raise ValueError(msg)
        if not isinstance(self.retryable, bool):
            msg = "Link discovery retryable must be a boolean"
            raise TypeError(msg)
        if self.status_code is not None and (
            isinstance(self.status_code, bool) or not isinstance(self.status_code, int)
        ):
            msg = "Link discovery status code must be an integer or None"
            raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class PDFLinkDiscoveryResult:
    """Immutable link-discovery outcome with explicit source coverage."""

    links: tuple[PDFLink, ...] = ()
    attempted_sources: tuple[str, ...] = ()
    completed_sources: tuple[str, ...] = ()
    source_errors: tuple[LinkDiscoverySourceError, ...] = ()

    def __post_init__(self) -> None:
        tuple_fields = {
            "links": self.links,
            "attempted_sources": self.attempted_sources,
            "completed_sources": self.completed_sources,
            "source_errors": self.source_errors,
        }
        for name, value in tuple_fields.items():
            if not isinstance(value, tuple):
                msg = f"PDFLinkDiscoveryResult.{name} must be a tuple"
                raise TypeError(msg)
        if any(not isinstance(link, PDFLink) for link in self.links):
            msg = "PDFLinkDiscoveryResult.links must contain only PDFLink values"
            raise TypeError(msg)
        if any(not isinstance(error, LinkDiscoverySourceError) for error in self.source_errors):
            msg = "PDFLinkDiscoveryResult.source_errors must contain only LinkDiscoverySourceError values"
            raise TypeError(msg)
        for name, sources in (
            ("attempted_sources", self.attempted_sources),
            ("completed_sources", self.completed_sources),
        ):
            if any(not isinstance(source, str) or not source.strip() for source in sources):
                msg = f"PDFLinkDiscoveryResult.{name} must contain non-empty source keys"
                raise TypeError(msg)
            if len(sources) != len(set(sources)):
                msg = f"PDFLinkDiscoveryResult.{name} must not contain duplicate source keys"
                raise ValueError(msg)
        attempted = set(self.attempted_sources)
        if not set(self.completed_sources).issubset(attempted):
            msg = "Completed link sources must be a subset of attempted sources"
            raise ValueError(msg)
        if any(error.source not in attempted for error in self.source_errors):
            msg = "Link source errors must belong to attempted sources"
            raise ValueError(msg)
        if self.links and not attempted:
            msg = "Discovered links require at least one attempted source"
            raise ValueError(msg)

    @property
    def coverage_status(self) -> LinkDiscoveryCoverage:
        """Describe whether every attempted link source completed."""
        if not self.source_errors:
            return "complete"
        if self.completed_sources or self.links:
            return "partial"
        return "unavailable"


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
    link_discovery: PDFLinkDiscoveryResult | None = None

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
    link_discovery: PDFLinkDiscoveryResult | None = None
    source_used: PDFSource | None = None
    content_type: Literal["xml", "pdf", "text", "none"] = "none"
    extraction_method: str | None = None
    has_figures: bool = False
    has_tables: bool = False
    has_references: bool = False
    word_count: int = 0
    file_size: int = 0
    error: str | None = None

    def require_link_discovery(self) -> PDFLinkDiscoveryResult:
        """Return the discovery envelope or reject a malformed retrieval result."""
        if self.link_discovery is None:
            msg = "Fulltext result has no link-discovery outcome"
            raise TypeError(msg)
        return self.link_discovery


__all__ = [
    "AccessType",
    "DownloadResult",
    "FulltextResult",
    "LinkDiscoveryCoverage",
    "LinkDiscoveryErrorKind",
    "LinkDiscoverySourceError",
    "PDFLink",
    "PDFLinkDiscoveryResult",
    "PDFSource",
]
