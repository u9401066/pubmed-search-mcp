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

import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Literal


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
    GOLD = "gold"           # Published in OA journal
    GREEN = "green"         # Archived in repository
    HYBRID = "hybrid"       # OA in subscription journal
    BRONZE = "bronze"       # Free to read, but no license
    CLOSED = "closed"       # Paywalled
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
            initials = "".join(
                word[0].upper() 
                for word in self.given_name.split() 
                if word
            )
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
                affiliation="; ".join(
                    aff.get("name", "") 
                    for aff in data.get("affiliation", [])
                ) or None,
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
            if self.nih_percentile >= 90:
                return "high"
            if self.nih_percentile >= 50:
                return "medium"
            return "low"
        if self.relative_citation_ratio is not None:
            if self.relative_citation_ratio >= 2.0:
                return "high"
            if self.relative_citation_ratio >= 0.5:
                return "medium"
            return "low"
        if self.citation_count is not None:
            if self.citation_count >= 100:
                return "high"
            if self.citation_count >= 10:
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
    
    # === Source Tracking ===
    sources: list[SourceMetadata] = field(default_factory=list)
    
    # === Internal ===
    _relevance_score: float | None = field(default=None, repr=False)
    _quality_score: float | None = field(default=None, repr=False)
    _ranking_score: float | None = field(default=None, repr=False)
    
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
        if self.oa_status in (OpenAccessStatus.GOLD, OpenAccessStatus.GREEN, 
                              OpenAccessStatus.HYBRID, OpenAccessStatus.BRONZE):
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
        names = [a.citation_name for a in self.authors[:3]]
        result = ", ".join(names)
        if len(self.authors) > 3:
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
            for i, author in enumerate(self.authors[:7]):  # APA shows up to 7
                if author.family_name and author.given_name:
                    initials = ". ".join(w[0].upper() for w in author.given_name.split() if w) + "."
                    apa_names.append(f"{author.family_name}, {initials}")
                else:
                    apa_names.append(author.display_name)
            if len(self.authors) > 7:
                author_str = ", ".join(apa_names[:6]) + ", ... " + apa_names[-1]
            elif len(apa_names) == 2:
                author_str = " & ".join(apa_names)
            elif len(apa_names) > 2:
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
        
        Expected format: Result from search_literature() or fetch_article_details()
        """
        # Parse authors
        authors = []
        if "authors" in data:
            for author_str in data["authors"]:
                if isinstance(author_str, str):
                    authors.append(Author(full_name=author_str))
                elif isinstance(author_str, dict):
                    authors.append(Author.from_dict(author_str))
        
        # Parse date
        pub_date = None
        year = None
        if data.get("pub_date"):
            try:
                # Try various formats
                date_str = data["pub_date"]
                if isinstance(date_str, str):
                    # "2024", "2024 Jan", "2024 Jan 15"
                    year_match = re.match(r"(\d{4})", date_str)
                    if year_match:
                        year = int(year_match.group(1))
            except (ValueError, TypeError):
                pass
        if not year and data.get("year"):
            year = int(data["year"])
        
        # Parse article type
        article_type = ArticleType.UNKNOWN
        if data.get("article_type"):
            type_map = {
                "Journal Article": ArticleType.JOURNAL_ARTICLE,
                "Review": ArticleType.REVIEW,
                "Meta-Analysis": ArticleType.META_ANALYSIS,
                "Systematic Review": ArticleType.SYSTEMATIC_REVIEW,
                "Clinical Trial": ArticleType.CLINICAL_TRIAL,
                "Randomized Controlled Trial": ArticleType.RANDOMIZED_CONTROLLED_TRIAL,
                "Case Reports": ArticleType.CASE_REPORT,
                "Letter": ArticleType.LETTER,
                "Editorial": ArticleType.EDITORIAL,
                "Comment": ArticleType.COMMENT,
            }
            for pub_type in data.get("article_type", []):
                if pub_type in type_map:
                    article_type = type_map[pub_type]
                    break
        
        # Determine OA status
        oa_status = OpenAccessStatus.UNKNOWN
        oa_links = []
        is_oa = False
        if data.get("pmc"):
            is_oa = True
            oa_status = OpenAccessStatus.GREEN
            pmc_id = data["pmc"].replace("PMC", "")
            oa_links.append(OpenAccessLink(
                url=f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id}/",
                version="publishedVersion",
                host_type="repository",
                is_best=True,
            ))
        
        return cls(
            title=data.get("title", "Unknown Title"),
            primary_source="pubmed",
            pmid=data.get("pmid") or data.get("uid"),
            doi=data.get("doi"),
            pmc=data.get("pmc"),
            authors=authors,
            abstract=data.get("abstract"),
            journal=data.get("journal") or data.get("fulljournalname"),
            journal_abbrev=data.get("source"),
            volume=data.get("volume"),
            issue=data.get("issue"),
            pages=data.get("pages"),
            year=year,
            publication_date=pub_date,
            article_type=article_type,
            language=data.get("language"),
            keywords=data.get("keywords", []),
            mesh_terms=data.get("mesh_terms", []),
            oa_status=oa_status,
            oa_links=oa_links,
            is_open_access=is_oa,
            sources=[SourceMetadata(source="pubmed", raw_data=data)],
        )
    
    @classmethod
    def from_crossref(cls, data: dict[str, Any]) -> UnifiedArticle:
        """
        Create UnifiedArticle from CrossRef API response.
        
        Expected format: Single work from CrossRef /works/{doi} endpoint
        """
        # Parse authors
        authors = []
        for author_data in data.get("author", []):
            authors.append(Author.from_dict(author_data))
        
        # Parse date
        year = None
        pub_date = None
        date_parts = data.get("published", {}).get("date-parts", [[]])
        if date_parts and date_parts[0]:
            parts = date_parts[0]
            if len(parts) >= 1:
                year = parts[0]
            if len(parts) >= 3:
                try:
                    pub_date = date(parts[0], parts[1], parts[2])
                except (ValueError, TypeError):
                    pass
        
        # Parse article type
        article_type = ArticleType.UNKNOWN
        cr_type = data.get("type", "").lower()
        type_map = {
            "journal-article": ArticleType.JOURNAL_ARTICLE,
            "posted-content": ArticleType.PREPRINT,
            "book-chapter": ArticleType.BOOK_CHAPTER,
            "proceedings-article": ArticleType.CONFERENCE_PAPER,
            "dissertation": ArticleType.THESIS,
            "dataset": ArticleType.DATASET,
        }
        article_type = type_map.get(cr_type, ArticleType.UNKNOWN)
        
        # Parse container (journal)
        journal = None
        journal_abbrev = None
        container = data.get("container-title", [])
        if container:
            journal = container[0]
        short_container = data.get("short-container-title", [])
        if short_container:
            journal_abbrev = short_container[0]
        
        # Parse pages
        pages = data.get("page")
        
        # Extract PMC if in alternative-id
        pmc = None
        for alt_id in data.get("alternative-id", []):
            if str(alt_id).startswith("PMC"):
                pmc = alt_id
                break
        
        # Parse OA links
        oa_links = []
        for link in data.get("link", []):
            if link.get("content-type") == "application/pdf":
                oa_links.append(OpenAccessLink(
                    url=link["URL"],
                    version="publishedVersion" if "publisher" in link.get("intended-application", "") else "unknown",
                    host_type="publisher",
                ))
        
        return cls(
            title=data.get("title", ["Unknown Title"])[0] if isinstance(data.get("title"), list) else data.get("title", "Unknown Title"),
            primary_source="crossref",
            doi=data.get("DOI"),
            pmc=pmc,
            authors=authors,
            abstract=data.get("abstract"),
            journal=journal,
            journal_abbrev=journal_abbrev,
            volume=data.get("volume"),
            issue=data.get("issue"),
            pages=pages,
            year=year,
            publication_date=pub_date,
            publisher=data.get("publisher"),
            article_type=article_type,
            oa_links=oa_links,
            citation_metrics=CitationMetrics(
                citation_count=data.get("is-referenced-by-count"),
            ) if data.get("is-referenced-by-count") else None,
            sources=[SourceMetadata(source="crossref", raw_data=data)],
        )
    
    @classmethod
    def from_openalex(cls, data: dict[str, Any]) -> UnifiedArticle:
        """
        Create UnifiedArticle from OpenAlex API response.
        
        Expected format: Single work from OpenAlex /works endpoint
        """
        # Parse authors
        authors = []
        for authorship in data.get("authorships", []):
            author_info = authorship.get("author", {})
            authors.append(Author(
                full_name=author_info.get("display_name"),
                orcid=author_info.get("orcid"),
            ))
        
        # Parse date
        year = data.get("publication_year")
        pub_date = None
        if data.get("publication_date"):
            try:
                pub_date = date.fromisoformat(data["publication_date"])
            except ValueError:
                pass
        
        # Extract IDs
        doi = None
        pmid = None
        pmc = None
        if data.get("doi"):
            doi = data["doi"].replace("https://doi.org/", "")
        ids = data.get("ids", {})
        if ids.get("pmid"):
            pmid = ids["pmid"].replace("https://pubmed.ncbi.nlm.nih.gov/", "").rstrip("/")
        if ids.get("pmcid"):
            pmc = ids["pmcid"].replace("https://www.ncbi.nlm.nih.gov/pmc/articles/", "").rstrip("/")
        
        # OA info
        is_oa = data.get("open_access", {}).get("is_oa", False)
        oa_url = data.get("open_access", {}).get("oa_url")
        oa_status_str = data.get("open_access", {}).get("oa_status", "unknown")
        oa_status_map = {
            "gold": OpenAccessStatus.GOLD,
            "green": OpenAccessStatus.GREEN,
            "hybrid": OpenAccessStatus.HYBRID,
            "bronze": OpenAccessStatus.BRONZE,
            "closed": OpenAccessStatus.CLOSED,
        }
        oa_status = oa_status_map.get(oa_status_str, OpenAccessStatus.UNKNOWN)
        
        oa_links = []
        if oa_url:
            oa_links.append(OpenAccessLink(
                url=oa_url,
                is_best=True,
            ))
        
        # Journal
        journal = None
        location = data.get("primary_location", {})
        source = location.get("source", {})
        if source:
            journal = source.get("display_name")
        
        return cls(
            title=data.get("title") or data.get("display_name", "Unknown Title"),
            primary_source="openalex",
            openalex_id=data.get("id", "").replace("https://openalex.org/", ""),
            doi=doi,
            pmid=pmid,
            pmc=pmc,
            authors=authors,
            abstract=data.get("abstract"),
            journal=journal,
            year=year,
            publication_date=pub_date,
            article_type=ArticleType.UNKNOWN,  # OpenAlex type mapping needed
            is_open_access=is_oa,
            oa_status=oa_status,
            oa_links=oa_links,
            citation_metrics=CitationMetrics(
                citation_count=data.get("cited_by_count"),
            ) if data.get("cited_by_count") else None,
            sources=[SourceMetadata(source="openalex", raw_data=data)],
        )
    
    @classmethod
    def from_semantic_scholar(cls, data: dict[str, Any]) -> UnifiedArticle:
        """Create UnifiedArticle from Semantic Scholar API response."""
        # Parse authors
        authors = []
        for author in data.get("authors", []):
            authors.append(Author(
                full_name=author.get("name"),
            ))
        
        # Extract IDs
        doi = data.get("externalIds", {}).get("DOI")
        pmid = data.get("externalIds", {}).get("PubMed")
        pmc = data.get("externalIds", {}).get("PubMedCentral")
        arxiv = data.get("externalIds", {}).get("ArXiv")
        
        # OA info
        is_oa = data.get("isOpenAccess", False)
        oa_links = []
        if data.get("openAccessPdf", {}).get("url"):
            oa_links.append(OpenAccessLink(
                url=data["openAccessPdf"]["url"],
                is_best=True,
            ))
        
        return cls(
            title=data.get("title", "Unknown Title"),
            primary_source="semantic_scholar",
            s2_id=data.get("paperId"),
            doi=doi,
            pmid=pmid,
            pmc=f"PMC{pmc}" if pmc else None,
            arxiv_id=arxiv,
            authors=authors,
            abstract=data.get("abstract"),
            journal=data.get("venue"),
            year=data.get("year"),
            is_open_access=is_oa,
            oa_links=oa_links,
            citation_metrics=CitationMetrics(
                citation_count=data.get("citationCount"),
                influential_citation_count=data.get("influentialCitationCount"),
            ) if data.get("citationCount") else None,
            sources=[SourceMetadata(source="semantic_scholar", raw_data=data)],
        )
    
    # ===================================================================
    # Instance Methods
    # ===================================================================
    
    def merge_from(self, other: UnifiedArticle) -> None:
        """
        Merge data from another UnifiedArticle into this one.
        
        Strategy:
        - Fill in missing fields
        - Combine lists (authors, oa_links)
        - Keep track of all sources
        
        Args:
            other: Another UnifiedArticle to merge from
        """
        # Merge identifiers (fill missing)
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
                if not self.citation_metrics.influential_citation_count and other.citation_metrics.influential_citation_count:
                    self.citation_metrics.influential_citation_count = other.citation_metrics.influential_citation_count
        
        # Track sources
        for source in other.sources:
            if source.source not in [s.source for s in self.sources]:
                self.sources.append(source)
    
    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary for JSON serialization.
        
        This is the format returned by MCP tools.
        """
        result = {
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
            "authors": [
                {"name": a.display_name, "orcid": a.orcid}
                for a in self.authors
            ],
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
                    {"url": link.url, "version": link.version, "host_type": link.host_type}
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
        
        # Add ranking scores if calculated
        if self._ranking_score is not None:
            result["_ranking_score"] = round(self._ranking_score, 4)
        
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
        doi = doi.replace("doi:", "")
        return doi
    
    @staticmethod
    def _normalize_pmc(pmc: str) -> str:
        """Normalize PMC ID for comparison."""
        pmc = pmc.upper().strip()
        if not pmc.startswith("PMC"):
            pmc = f"PMC{pmc}"
        return pmc
