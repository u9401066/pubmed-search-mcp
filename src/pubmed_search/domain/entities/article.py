"""
UnifiedArticle - Standardized Article Model for Multi-Source Search

This module defines the canonical data structure for academic articles,
designed to normalize data from different sources into a single format.

Architecture Decision:
    We use dataclasses instead of Pydantic for:
    1. Lightweight - no external dependency
    2. Performance - faster instantiation
    3. Simplicity - easy to understand and maintain

Supported Sources:
    - PubMed (NCBI E-utilities)
    - CrossRef (DOI metadata)
    - OpenAlex (Open scholarly data)
    - Semantic Scholar (AI-powered)
    - Europe PMC (Full text access)
    - CORE (Open access aggregator)
    - Unpaywall (OA link resolver)

Example:
    >>> article = UnifiedArticle(
    ...     title="Machine Learning in Healthcare",
    ...     pmid="12345678",
    ...     doi="10.1000/example",
    ...     primary_source="pubmed"
    ... )
    >>> article.has_open_access
    False
    >>> article.best_identifier
    'PMID:12345678'
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Literal

MONTHS_PER_YEAR = 12

# ── Impact classification thresholds ────────────────────────────────────────
# JournalInfo.impact_tier: 2-year mean citedness (≈ Impact Factor)
_IMPACT_TIER_TOP = 10.0
_IMPACT_TIER_HIGH = 5.0
_IMPACT_TIER_MEDIUM = 2.0
_IMPACT_TIER_LOW = 1.0

# CitationMetrics.impact_level: NIH percentile thresholds
_PERCENTILE_HIGH = 90
_PERCENTILE_MEDIUM = 50

# CitationMetrics.impact_level: Relative Citation Ratio thresholds
_RCR_HIGH = 2.0
_RCR_MEDIUM = 0.5

# CitationMetrics.impact_level: Raw citation count thresholds
_CITATION_HIGH = 100
_CITATION_MEDIUM = 10

# Author display limits
_AUTHOR_DISPLAY_MAX = 3
_APA_AUTHOR_MAX = 7
_CROSSREF_AUTHOR_BATCH = 2  # Min date-parts for full date

# APA citation formatting
_APA_AUTHOR_TRUNCATE = 6  # Show first 6 authors before "..."
_APA_DUAL_AUTHOR = 2  # When exactly 2 authors, join with "&"

# CrossRef date parsing: minimum date parts for full date
_DATE_PARTS_FULL = 3

_PUBMED_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _parse_pubmed_month(token: str) -> int | None:
    normalized = token.strip().lower()
    if not normalized:
        return None

    if normalized in _PUBMED_MONTHS:
        return _PUBMED_MONTHS[normalized]

    if normalized.isdigit():
        month = int(normalized)
        if 1 <= month <= MONTHS_PER_YEAR:
            return month

    return None


def _parse_pubmed_date(value: Any) -> tuple[int | None, date | None]:
    if not isinstance(value, str):
        return None, None

    normalized = value.strip()
    if not normalized:
        return None, None

    year_match = re.search(r"\b(\d{4})\b", normalized)
    if not year_match:
        return None, None

    year = int(year_match.group(1))
    pub_date = None

    tokens = [token for token in re.split(r"[\s/,-]+", normalized) if token]
    if not tokens:
        return year, None

    try:
        start_index = tokens.index(year_match.group(1)) + 1
    except ValueError:
        start_index = 1

    month = None
    day = None

    for index in range(start_index, len(tokens)):
        month = _parse_pubmed_month(tokens[index])
        if month is None:
            continue

        for day_token in tokens[index + 1 :]:
            if day_token.isdigit():
                day = int(day_token)
                break
        break

    if month is not None and day is not None:
        with contextlib.suppress(ValueError):
            pub_date = date(year, month, day)

    return year, pub_date


class ArticleType(Enum):
    """Standard article types across sources."""

    JOURNAL_ARTICLE = "journal-article"
    REVIEW = "review"
    META_ANALYSIS = "meta-analysis"
    SYSTEMATIC_REVIEW = "systematic-review"
    CLINICAL_TRIAL = "clinical-trial"
    RANDOMIZED_CONTROLLED_TRIAL = "randomized-controlled-trial"
    CASE_REPORT = "case-report"
    LETTER = "letter"
    EDITORIAL = "editorial"
    COMMENT = "comment"
    PREPRINT = "preprint"
    BOOK_CHAPTER = "book-chapter"
    CONFERENCE_PAPER = "conference-paper"
    THESIS = "thesis"
    DATASET = "dataset"
    OTHER = "other"
    UNKNOWN = "unknown"


class OpenAccessStatus(Enum):
    """Open access status categories (Unpaywall taxonomy)."""

    GOLD = "gold"  # Published in OA journal
    GREEN = "green"  # Archived in repository
    HYBRID = "hybrid"  # OA in subscription journal
    BRONZE = "bronze"  # Free to read, but no license
    CLOSED = "closed"  # Paywalled
    UNKNOWN = "unknown"


@dataclass
class Author:
    """
    Author information.

    Handles name formats from different sources:
    - PubMed: "Smith J" or "John Smith"
    - CrossRef: {"given": "John", "family": "Smith"}
    - OpenAlex: {"display_name": "John Smith"}
    """

    family_name: str | None = None
    given_name: str | None = None
    full_name: str | None = None
    orcid: str | None = None
    affiliation: str | None = None
    is_corresponding: bool = False

    @property
    def display_name(self) -> str:
        """Return best available name representation."""
        if self.full_name:
            return self.full_name
        parts = []
        if self.given_name:
            parts.append(self.given_name)
        if self.family_name:
            parts.append(self.family_name)
        return " ".join(parts) if parts else "Unknown"

    @property
    def citation_name(self) -> str:
        """Return name in citation format: 'Smith J' or 'Smith JA'."""
        if self.family_name and self.given_name:
            # Extract initials
            initials = "".join(word[0].upper() for word in self.given_name.split() if word)
            return f"{self.family_name} {initials}"
        return self.display_name

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Author:
        """Create Author from various source formats."""
        # CrossRef format
        if "family" in data:
            return cls(
                family_name=data.get("family"),
                given_name=data.get("given"),
                orcid=data.get("ORCID"),
                affiliation="; ".join(aff.get("name", "") for aff in data.get("affiliation", [])) or None,
            )
        # OpenAlex format
        if "display_name" in data:
            return cls(
                full_name=data.get("display_name"),
                orcid=data.get("orcid"),
            )
        # Simple string
        if isinstance(data, str):
            return cls(full_name=data)
        # Generic dict
        return cls(
            family_name=data.get("family_name"),
            given_name=data.get("given_name"),
            full_name=data.get("full_name") or data.get("name"),
            orcid=data.get("orcid"),
            affiliation=data.get("affiliation"),
        )


@dataclass
class OpenAccessLink:
    """
    Open access link information.

    Tracks multiple potential access points for an article.
    """

    url: str
    version: Literal["publishedVersion", "acceptedVersion", "submittedVersion", "unknown"] = "unknown"
    host_type: Literal["publisher", "repository", "preprint"] | None = None
    license: str | None = None  # e.g., "cc-by", "cc-by-nc"
    is_best: bool = False  # Best available OA option

    @property
    def is_pdf(self) -> bool:
        """Check if URL likely points to PDF."""
        return self.url.lower().endswith(".pdf") or "/pdf/" in self.url.lower()


@dataclass
class JournalMetrics:
    """
    Journal-level metrics from OpenAlex Sources API.

    Provides journal impact and ranking information:
    - 2yr_mean_citedness: mathematically equivalent to 2-year Impact Factor
    - h_index: journal h-index
    - i10_index: number of papers with 10+ citations
    - works_count: total articles published
    - cited_by_count: total citations to journal's articles

    Source: OpenAlex /sources endpoint (free, open data)
    """

    issn: str | None = None
    issn_l: str | None = None  # Linking ISSN (canonical identifier)
    openalex_source_id: str | None = None
    h_index: int | None = None
    two_year_mean_citedness: float | None = None  # ≈ 2-year Impact Factor
    i10_index: int | None = None
    works_count: int | None = None
    cited_by_count: int | None = None
    is_in_doaj: bool | None = None
    source_type: str | None = None  # journal, repository, conference, etc.
    subject_areas: list[str] = field(default_factory=list)

    @property
    def impact_tier(self) -> str:
        """Categorize journal by 2yr_mean_citedness (≈ IF)."""
        if self.two_year_mean_citedness is None:
            return "unknown"
        if self.two_year_mean_citedness >= _IMPACT_TIER_TOP:
            return "top"  # Top-tier journals (Nature, NEJM, Lancet...)
        if self.two_year_mean_citedness >= _IMPACT_TIER_HIGH:
            return "high"
        if self.two_year_mean_citedness >= _IMPACT_TIER_MEDIUM:
            return "medium"
        if self.two_year_mean_citedness >= _IMPACT_TIER_LOW:
            return "low"
        return "minimal"


@dataclass
class CitationMetrics:
    """
    Citation and impact metrics from various sources.

    Combines data from:
    - NIH iCite (RCR, APT)
    - Semantic Scholar (influential citations)
    - OpenAlex (citation counts)
    - CrossRef (reference counts)
    """

    citation_count: int | None = None
    # NIH iCite metrics
    relative_citation_ratio: float | None = None  # RCR (1.0 = field average)
    nih_percentile: float | None = None  # 0-100
    apt: float | None = None  # Approximate Potential to Translate (clinical relevance)
    # Semantic Scholar
    influential_citation_count: int | None = None
    # Calculated
    citations_per_year: float | None = None

    @property
    def impact_level(self) -> Literal["high", "medium", "low", "unknown"]:
        """Categorize impact level based on available metrics."""
        if self.nih_percentile is not None:
            if self.nih_percentile >= _PERCENTILE_HIGH:
                return "high"
            if self.nih_percentile >= _PERCENTILE_MEDIUM:
                return "medium"
            return "low"
        if self.relative_citation_ratio is not None:
            if self.relative_citation_ratio >= _RCR_HIGH:
                return "high"
            if self.relative_citation_ratio >= _RCR_MEDIUM:
                return "medium"
            return "low"
        if self.citation_count is not None:
            if self.citation_count >= _CITATION_HIGH:
                return "high"
            if self.citation_count >= _CITATION_MEDIUM:
                return "medium"
            return "low"
        return "unknown"


@dataclass
class SourceMetadata:
    """
    Metadata about where article data came from.

    Useful for:
    - Deduplication (prefer certain sources)
    - Quality assessment
    - Debugging
    """

    source: str  # e.g., "pubmed", "crossref", "openalex"
    fetched_at: str | None = None  # ISO timestamp
    raw_data: dict[str, Any] | None = field(default=None, repr=False)


@dataclass
class UnifiedArticle:
    """
    Unified article representation across all academic sources.

    Design Principles:
    1. Nullable fields - not all sources provide all data
    2. Multiple identifiers - same article may have DOI, PMID, etc.
    3. Source tracking - know where data came from
    4. Extensible - easy to add new fields

    Key Identifiers:
    - pmid: PubMed ID (primary for biomedical)
    - doi: Digital Object Identifier (universal)
    - pmc: PubMed Central ID (for OA biomedical)
    - openalex_id: OpenAlex Work ID
    - s2_id: Semantic Scholar Paper ID
    - core_id: CORE Work ID

    Usage:
        # From PubMed search result
        article = UnifiedArticle.from_pubmed(pubmed_data)

        # From CrossRef
        article = UnifiedArticle.from_crossref(crossref_data)

        # Merge data from multiple sources
        article.merge_from(crossref_article)
    """

    # === Core Identity ===
    title: str
    primary_source: str  # Source that provided this record

    # === Identifiers ===
    pmid: str | None = None
    doi: str | None = None
    pmc: str | None = None  # PMC ID (e.g., "PMC7096777")
    openalex_id: str | None = None
    s2_id: str | None = None  # Semantic Scholar 40-char hex ID
    core_id: str | None = None
    arxiv_id: str | None = None

    # === Bibliographic ===
    authors: list[Author] = field(default_factory=list)
    abstract: str | None = None
    journal: str | None = None
    journal_abbrev: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    publication_date: date | None = None
    year: int | None = None
    publisher: str | None = None
    article_type: ArticleType = ArticleType.UNKNOWN
    language: str | None = None
    keywords: list[str] = field(default_factory=list)
    mesh_terms: list[str] = field(default_factory=list)

    # === Open Access ===
    oa_status: OpenAccessStatus = OpenAccessStatus.UNKNOWN
    oa_links: list[OpenAccessLink] = field(default_factory=list)
    is_open_access: bool | None = None

    # === Metrics ===
    citation_metrics: CitationMetrics | None = None
    journal_metrics: JournalMetrics | None = None

    # === Similarity Scores (from external APIs) ===
    similarity_score: float | None = None  # 0.0-1.0, higher = more similar
    similarity_source: str | None = None  # e.g., "semantic_scholar", "europe_pmc"
    similarity_details: dict[str, float] | None = field(default=None, repr=False)  # Multiple sources

    # === Source Tracking ===
    sources: list[SourceMetadata] = field(default_factory=list)

    # === Internal (ranking scores, set by ResultAggregator) ===
    relevance_score: float | None = field(default=None, repr=False)
    quality_score: float | None = field(default=None, repr=False)
    ranking_score: float | None = field(default=None, repr=False)

    # ===================================================================
    # Properties
    # ===================================================================

    @property
    def best_identifier(self) -> str:
        """Return the best available identifier for display."""
        if self.pmid:
            return f"PMID:{self.pmid}"
        if self.doi:
            return f"DOI:{self.doi}"
        if self.pmc:
            return f"PMC:{self.pmc}"
        if self.openalex_id:
            return f"OpenAlex:{self.openalex_id}"
        if self.s2_id:
            return f"S2:{self.s2_id[:8]}..."
        return f"Title:{self.title[:30]}..."

    @property
    def has_open_access(self) -> bool:
        """Check if article has any open access option."""
        if self.is_open_access is True:
            return True
        if self.oa_status in (
            OpenAccessStatus.GOLD,
            OpenAccessStatus.GREEN,
            OpenAccessStatus.HYBRID,
            OpenAccessStatus.BRONZE,
        ):
            return True
        return bool(self.oa_links)

    @property
    def best_oa_link(self) -> OpenAccessLink | None:
        """Get the best open access link if available."""
        if not self.oa_links:
            return None
        # Prefer marked as best
        for link in self.oa_links:
            if link.is_best:
                return link
        # Prefer published version
        for link in self.oa_links:
            if link.version == "publishedVersion":
                return link
        # Return first available
        return self.oa_links[0]

    @property
    def author_string(self) -> str:
        """Return formatted author string for display."""
        if not self.authors:
            return "Unknown"
        names = [a.citation_name for a in self.authors[:_AUTHOR_DISPLAY_MAX]]
        result = ", ".join(names)
        if len(self.authors) > _AUTHOR_DISPLAY_MAX:
            result += " et al."
        return result

    @property
    def citation_string(self) -> str:
        """Return formatted citation string (Vancouver/NLM style - medical default)."""
        return self.cite_vancouver()

    def cite_vancouver(self) -> str:
        """
        Vancouver/NLM citation style (醫學文獻標準格式).

        Format: Authors. Title. Journal. Year;Volume(Issue):Pages. doi:DOI
        Example: Smith J, Doe A. Machine Learning in Healthcare. JAMA. 2024;331(2):123-130. doi:10.1000/example
        """
        parts = []
        # Authors
        parts.append(self.author_string)
        # Title
        parts.append(self.title)
        # Journal
        if self.journal:
            journal_part = self.journal_abbrev or self.journal
            if self.year:
                journal_part += f". {self.year}"
            if self.volume:
                journal_part += f";{self.volume}"
                if self.issue:
                    journal_part += f"({self.issue})"
            if self.pages:
                journal_part += f":{self.pages}"
            parts.append(journal_part)
        elif self.year:
            parts.append(str(self.year))
        # DOI
        if self.doi:
            parts.append(f"doi:{self.doi}")

        return ". ".join(parts) + "."

    def cite_apa(self) -> str:
        """
        APA 7th edition citation style.

        Format: Authors (Year). Title. Journal, Volume(Issue), Pages. https://doi.org/DOI
        Example: Smith, J., & Doe, A. (2024). Machine Learning in Healthcare. JAMA, 331(2), 123-130. https://doi.org/10.1000/example
        """
        parts = []
        # Authors in APA format: "Last, F. M., & Last, F. M."
        if self.authors:
            apa_names = []
            for _i, author in enumerate(self.authors[:_APA_AUTHOR_MAX]):
                if author.family_name and author.given_name:
                    initials = ". ".join(w[0].upper() for w in author.given_name.split() if w) + "."
                    apa_names.append(f"{author.family_name}, {initials}")
                else:
                    apa_names.append(author.display_name)
            if len(self.authors) > _APA_AUTHOR_MAX:
                author_str = ", ".join(apa_names[:_APA_AUTHOR_TRUNCATE]) + ", ... " + apa_names[-1]
            elif len(apa_names) == _APA_DUAL_AUTHOR:
                author_str = " & ".join(apa_names)
            elif len(apa_names) > _APA_DUAL_AUTHOR:
                author_str = ", ".join(apa_names[:-1]) + ", & " + apa_names[-1]
            else:
                author_str = apa_names[0] if apa_names else "Unknown"
            parts.append(author_str)
        else:
            parts.append("Unknown")

        # Year
        year_str = f"({self.year})" if self.year else "(n.d.)"
        parts.append(year_str)

        # Title (sentence case, italicized in real APA)
        parts.append(self.title)

        # Journal, Volume(Issue), Pages
        if self.journal:
            journal_part = self.journal  # Full name for APA
            if self.volume:
                journal_part += f", {self.volume}"
                if self.issue:
                    journal_part += f"({self.issue})"
            if self.pages:
                journal_part += f", {self.pages}"
            parts.append(journal_part)

        citation = ". ".join(parts) + "."

        # DOI as URL
        if self.doi:
            citation += f" https://doi.org/{self.doi}"

        return citation

    @property
    def pubmed_url(self) -> str | None:
        """Get PubMed URL if PMID available."""
        if self.pmid:
            return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"
        return None

    @property
    def doi_url(self) -> str | None:
        """Get DOI resolver URL if DOI available."""
        if self.doi:
            return f"https://doi.org/{self.doi}"
        return None

    @property
    def pmc_url(self) -> str | None:
        """Get PMC URL if PMC ID available."""
        if self.pmc:
            pmc_id = self.pmc.replace("PMC", "")
            return f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id}/"
        return None

    # ===================================================================
    # Class Methods - Factory Methods
    # ===================================================================

    @classmethod
    def from_pubmed(cls, data: dict[str, Any]) -> UnifiedArticle:
        """
        Create UnifiedArticle from PubMed search result.

        Expected format: Result from unified_search(), fetch_article_details(), or raw PubMed extraction
        """
        from pubmed_search.infrastructure.sources.article_mapper import article_from_pubmed

        return article_from_pubmed(data)

    @classmethod
    def from_crossref(cls, data: dict[str, Any]) -> UnifiedArticle:
        """
        Create UnifiedArticle from CrossRef API response.

        Expected format: Single work from CrossRef /works/{doi} endpoint
        """
        from pubmed_search.infrastructure.sources.article_mapper import article_from_crossref

        return article_from_crossref(data)

    @classmethod
    def from_openalex(cls, data: dict[str, Any]) -> UnifiedArticle:
        """
        Create UnifiedArticle from OpenAlex API response.

        Expected format: Single work from OpenAlex /works endpoint
        """
        from pubmed_search.infrastructure.sources.article_mapper import article_from_openalex

        return article_from_openalex(data)

    @classmethod
    def from_semantic_scholar(cls, data: dict[str, Any]) -> UnifiedArticle:
        """Create UnifiedArticle from Semantic Scholar API response."""
        from pubmed_search.infrastructure.sources.article_mapper import article_from_semantic_scholar

        return article_from_semantic_scholar(data)

    @classmethod
    def from_core(cls, data: dict[str, Any]) -> UnifiedArticle:
        """Create UnifiedArticle from CORE API normalized response."""
        from pubmed_search.infrastructure.sources.article_mapper import article_from_core

        return article_from_core(data)

    @classmethod
    def from_scopus(cls, data: dict[str, Any]) -> UnifiedArticle:
        """Create UnifiedArticle from Scopus normalized response."""
        from pubmed_search.infrastructure.sources.article_mapper import article_from_scopus

        return article_from_scopus(data)

    @classmethod
    def from_web_of_science(cls, data: dict[str, Any]) -> UnifiedArticle:
        """Create UnifiedArticle from Web of Science normalized response."""
        from pubmed_search.infrastructure.sources.article_mapper import article_from_web_of_science

        return article_from_web_of_science(data)

    # ===================================================================
    # Instance Methods
    # ===================================================================

    def merge_from(self, other: UnifiedArticle, *, merge_identifiers: bool = True) -> None:
        """
        Merge data from another UnifiedArticle into this one.

        Strategy:
        - Fill in missing fields
        - Combine lists (authors, oa_links)
        - Keep track of all sources

        Args:
            other: Another UnifiedArticle to merge from
            merge_identifiers: Whether strong identifiers such as DOI/PMID/PMC
                may be copied from ``other``. Set this to ``False`` when two
                records were grouped only by weak evidence (for example,
                title-only deduplication) to avoid propagating a wrong DOI.
        """
        # Merge identifiers only when the caller has corroborated that these
        # records refer to the same article through a strong identifier match.
        if merge_identifiers:
            if not self.pmid and other.pmid:
                self.pmid = other.pmid
            if not self.doi and other.doi:
                self.doi = other.doi
            if not self.pmc and other.pmc:
                self.pmc = other.pmc
            if not self.openalex_id and other.openalex_id:
                self.openalex_id = other.openalex_id
            if not self.s2_id and other.s2_id:
                self.s2_id = other.s2_id
            if not self.core_id and other.core_id:
                self.core_id = other.core_id
            if not self.arxiv_id and other.arxiv_id:
                self.arxiv_id = other.arxiv_id

        # Merge bibliographic (fill missing)
        if not self.abstract and other.abstract:
            self.abstract = other.abstract
        if not self.journal and other.journal:
            self.journal = other.journal
        if not self.journal_abbrev and other.journal_abbrev:
            self.journal_abbrev = other.journal_abbrev
        if not self.volume and other.volume:
            self.volume = other.volume
        if not self.issue and other.issue:
            self.issue = other.issue
        if not self.pages and other.pages:
            self.pages = other.pages
        if not self.year and other.year:
            self.year = other.year
        if not self.publication_date and other.publication_date:
            self.publication_date = other.publication_date
        if not self.publisher and other.publisher:
            self.publisher = other.publisher
        if self.article_type == ArticleType.UNKNOWN and other.article_type != ArticleType.UNKNOWN:
            self.article_type = other.article_type

        # Merge authors (if empty)
        if not self.authors and other.authors:
            self.authors = other.authors.copy()

        # Merge keywords/MeSH
        if other.keywords:
            for kw in other.keywords:
                if kw not in self.keywords:
                    self.keywords.append(kw)
        if other.mesh_terms:
            for term in other.mesh_terms:
                if term not in self.mesh_terms:
                    self.mesh_terms.append(term)

        # Merge OA info
        if self.oa_status == OpenAccessStatus.UNKNOWN:
            self.oa_status = other.oa_status
        if self.is_open_access is None:
            self.is_open_access = other.is_open_access

        # Merge OA links (dedupe by URL)
        existing_urls = {link.url for link in self.oa_links}
        for link in other.oa_links:
            if link.url not in existing_urls:
                self.oa_links.append(link)
                existing_urls.add(link.url)

        # Merge citation metrics
        if other.citation_metrics:
            if not self.citation_metrics:
                self.citation_metrics = other.citation_metrics
            else:
                # Prefer higher citation count (more recent data)
                if (other.citation_metrics.citation_count or 0) > (self.citation_metrics.citation_count or 0):
                    self.citation_metrics.citation_count = other.citation_metrics.citation_count
                # Fill missing metrics
                if not self.citation_metrics.relative_citation_ratio and other.citation_metrics.relative_citation_ratio:
                    self.citation_metrics.relative_citation_ratio = other.citation_metrics.relative_citation_ratio
                if not self.citation_metrics.nih_percentile and other.citation_metrics.nih_percentile:
                    self.citation_metrics.nih_percentile = other.citation_metrics.nih_percentile
                if not self.citation_metrics.apt and other.citation_metrics.apt:
                    self.citation_metrics.apt = other.citation_metrics.apt
                if (
                    not self.citation_metrics.influential_citation_count
                    and other.citation_metrics.influential_citation_count
                ):
                    self.citation_metrics.influential_citation_count = other.citation_metrics.influential_citation_count

        # Merge journal metrics
        if other.journal_metrics:
            if not self.journal_metrics:
                self.journal_metrics = other.journal_metrics
            else:
                # Fill missing fields
                if not self.journal_metrics.issn and other.journal_metrics.issn:
                    self.journal_metrics.issn = other.journal_metrics.issn
                if not self.journal_metrics.issn_l and other.journal_metrics.issn_l:
                    self.journal_metrics.issn_l = other.journal_metrics.issn_l
                if self.journal_metrics.h_index is None and other.journal_metrics.h_index is not None:
                    self.journal_metrics.h_index = other.journal_metrics.h_index
                if (
                    self.journal_metrics.two_year_mean_citedness is None
                    and other.journal_metrics.two_year_mean_citedness is not None
                ):
                    self.journal_metrics.two_year_mean_citedness = other.journal_metrics.two_year_mean_citedness
                if self.journal_metrics.i10_index is None and other.journal_metrics.i10_index is not None:
                    self.journal_metrics.i10_index = other.journal_metrics.i10_index

        # Track sources
        for source in other.sources:
            if source.source not in [s.source for s in self.sources]:
                self.sources.append(source)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary for JSON serialization.

        This is the format returned by MCP tools.
        """
        result: dict[str, Any] = {
            "title": self.title,
            "primary_source": self.primary_source,
            "identifiers": {
                "pmid": self.pmid,
                "doi": self.doi,
                "pmc": self.pmc,
                "openalex_id": self.openalex_id,
                "s2_id": self.s2_id,
                "core_id": self.core_id,
                "arxiv_id": self.arxiv_id,
            },
            "authors": [{"name": a.display_name, "orcid": a.orcid} for a in self.authors],
            "author_string": self.author_string,
            "abstract": self.abstract,
            "journal": self.journal,
            "journal_abbrev": self.journal_abbrev,
            "volume": self.volume,
            "issue": self.issue,
            "pages": self.pages,
            "year": self.year,
            "publication_date": self.publication_date.isoformat() if self.publication_date else None,
            "publisher": self.publisher,
            "article_type": self.article_type.value,
            "keywords": self.keywords,
            "mesh_terms": self.mesh_terms,
            "open_access": {
                "is_oa": self.has_open_access,
                "status": self.oa_status.value,
                "best_link": self.best_oa_link.url if self.best_oa_link else None,
                "links": [
                    {
                        "url": link.url,
                        "version": link.version,
                        "host_type": link.host_type,
                    }
                    for link in self.oa_links
                ],
            },
            "urls": {
                "pubmed": self.pubmed_url,
                "doi": self.doi_url,
                "pmc": self.pmc_url,
            },
            "sources": [s.source for s in self.sources],
        }

        # Add citation metrics if available
        if self.citation_metrics:
            result["citation_metrics"] = {
                "citation_count": self.citation_metrics.citation_count,
                "rcr": self.citation_metrics.relative_citation_ratio,
                "percentile": self.citation_metrics.nih_percentile,
                "apt": self.citation_metrics.apt,
                "influential_citations": self.citation_metrics.influential_citation_count,
                "impact_level": self.citation_metrics.impact_level,
            }

        # Add journal metrics if available
        if self.journal_metrics:
            jm = self.journal_metrics
            journal_data: dict[str, Any] = {}
            if jm.two_year_mean_citedness is not None:
                journal_data["impact_factor_approx"] = round(jm.two_year_mean_citedness, 3)
                journal_data["impact_tier"] = jm.impact_tier
            if jm.h_index is not None:
                journal_data["h_index"] = jm.h_index
            if jm.i10_index is not None:
                journal_data["i10_index"] = jm.i10_index
            if jm.works_count is not None:
                journal_data["works_count"] = jm.works_count
            if jm.cited_by_count is not None:
                journal_data["cited_by_count"] = jm.cited_by_count
            if jm.issn:
                journal_data["issn"] = jm.issn
            if jm.subject_areas:
                journal_data["subject_areas"] = jm.subject_areas
            if jm.is_in_doaj is not None:
                journal_data["is_in_doaj"] = jm.is_in_doaj
            if journal_data:
                result["journal_metrics"] = journal_data

        # Add ranking scores if calculated
        if self.ranking_score is not None:
            result["_ranking_score"] = round(self.ranking_score, 4)

        # Add similarity scores if available
        if self.similarity_score is not None:
            result["similarity"] = {
                "score": self.similarity_score,
                "source": self.similarity_source,
            }
            if self.similarity_details:
                result["similarity"]["details"] = self.similarity_details

        return result

    def matches_identifier(self, other: UnifiedArticle) -> bool:
        """
        Check if this article likely matches another based on identifiers.

        Used for deduplication.
        """
        # DOI match (most reliable)
        if self.doi and other.doi:
            return self._normalize_doi(self.doi) == self._normalize_doi(other.doi)

        # PMID match
        if self.pmid and other.pmid:
            return self.pmid == other.pmid

        # PMC match
        if self.pmc and other.pmc:
            return self._normalize_pmc(self.pmc) == self._normalize_pmc(other.pmc)

        # OpenAlex ID match
        if self.openalex_id and other.openalex_id:
            return self.openalex_id == other.openalex_id

        # S2 ID match
        if self.s2_id and other.s2_id:
            return self.s2_id.lower() == other.s2_id.lower()

        return False

    @staticmethod
    def _normalize_doi(doi: str) -> str:
        """Normalize DOI for comparison."""
        doi = doi.lower().strip()
        doi = doi.replace("https://doi.org/", "")
        doi = doi.replace("http://doi.org/", "")
        return doi.replace("doi:", "")

    @staticmethod
    def _normalize_pmc(pmc: str) -> str:
        """Normalize PMC ID for comparison."""
        pmc = pmc.upper().strip()
        if not pmc.startswith("PMC"):
            pmc = f"PMC{pmc}"
        return pmc
