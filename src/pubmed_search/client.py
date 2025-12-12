"""
PubMed Client - High-level wrapper for PubMed API interactions.

This module provides a clean, user-friendly interface for PubMed searches.
"""

from typing import Any, Self  # Python 3.11+
from dataclasses import dataclass
from enum import Enum

from .entrez import LiteratureSearcher


class SearchStrategy(Enum):
    """Search strategy options for literature search."""
    RECENT = "recent"
    MOST_CITED = "most_cited"
    RELEVANCE = "relevance"
    IMPACT = "impact"
    AGENT_DECIDED = "agent_decided"


@dataclass
class SearchResult:
    """Result from a PubMed search."""
    pmid: str
    title: str
    authors: list[str]
    authors_full: list[dict[str, str]]
    abstract: str
    journal: str
    journal_abbrev: str
    year: str
    month: str = ""
    day: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    pmc_id: str = ""
    keywords: list[str] | None = None
    mesh_terms: list[str] | None = None
    
    def __post_init__(self):
        if self.keywords is None:
            self.keywords = []
        if self.mesh_terms is None:
            self.mesh_terms = []
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create from dictionary."""
        return cls(
            pmid=data.get("pmid", ""),
            title=data.get("title", ""),
            authors=data.get("authors", []),
            authors_full=data.get("authors_full", []),
            abstract=data.get("abstract", ""),
            journal=data.get("journal", ""),
            journal_abbrev=data.get("journal_abbrev", ""),
            year=data.get("year", ""),
            month=data.get("month", ""),
            day=data.get("day", ""),
            volume=data.get("volume", ""),
            issue=data.get("issue", ""),
            pages=data.get("pages", ""),
            doi=data.get("doi", ""),
            pmc_id=data.get("pmc_id", ""),
            keywords=data.get("keywords", []),
            mesh_terms=data.get("mesh_terms", []),
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "pmid": self.pmid,
            "title": self.title,
            "authors": self.authors,
            "authors_full": self.authors_full,
            "abstract": self.abstract,
            "journal": self.journal,
            "journal_abbrev": self.journal_abbrev,
            "year": self.year,
            "month": self.month,
            "day": self.day,
            "volume": self.volume,
            "issue": self.issue,
            "pages": self.pages,
            "doi": self.doi,
            "pmc_id": self.pmc_id,
            "keywords": self.keywords,
            "mesh_terms": self.mesh_terms,
        }


class PubMedClient:
    """
    PubMed API client for literature search.
    
    Wraps the Entrez functionality and provides a clean interface.
    
    Example:
        >>> client = PubMedClient(email="researcher@example.com")
        >>> results = client.search("diabetes treatment", limit=5)
        >>> for article in results:
        ...     print(f"{article.pmid}: {article.title}")
    """
    
    def __init__(self, email: str = "your.email@example.com", api_key: str | None = None):
        """
        Initialize PubMed client.
        
        Args:
            email: Email address required by NCBI Entrez API.
            api_key: Optional NCBI API key for higher rate limits.
        """
        self._searcher = LiteratureSearcher(email=email, api_key=api_key)
    
    @property
    def searcher(self) -> LiteratureSearcher:
        """Get the underlying LiteratureSearcher for advanced operations."""
        return self._searcher
    
    def search(
        self,
        query: str,
        limit: int = 5,
        min_year: int | None = None,
        max_year: int | None = None,
        article_type: str | None = None,
        strategy: SearchStrategy = SearchStrategy.RELEVANCE,
        date_from: str | None = None,
        date_to: str | None = None,
        date_type: str = "edat",
    ) -> list[SearchResult]:
        """
        Search PubMed for articles.
        
        Args:
            query: Search query string.
            limit: Maximum number of results.
            min_year: Minimum publication year (legacy).
            max_year: Maximum publication year (legacy).
            article_type: Article type filter.
            strategy: Search strategy.
            date_from: Precise start date in YYYY/MM/DD format.
            date_to: Precise end date in YYYY/MM/DD format.
            date_type: Date field to search (edat, pdat, mdat).
            
        Returns:
            List of SearchResult objects.
        """
        results = self._searcher.search(
            query=query,
            limit=limit,
            min_year=min_year,
            max_year=max_year,
            article_type=article_type,
            strategy=strategy.value,
            date_from=date_from,
            date_to=date_to,
            date_type=date_type,
        )
        
        return [SearchResult.from_dict(r) for r in results if "error" not in r]
    
    def search_raw(
        self,
        query: str,
        limit: int = 5,
        min_year: int | None = None,
        max_year: int | None = None,
        article_type: str | None = None,
        strategy: str = "relevance",
        date_from: str | None = None,
        date_to: str | None = None,
        date_type: str = "edat",
    ) -> list[dict[str, Any]]:
        """
        Search PubMed and return raw dictionaries.
        
        Same as search() but returns dicts instead of SearchResult objects.
        Useful for JSON serialization.
        """
        return self._searcher.search(
            query=query,
            limit=limit,
            min_year=min_year,
            max_year=max_year,
            article_type=article_type,
            strategy=strategy,
            date_from=date_from,
            date_to=date_to,
            date_type=date_type,
        )
    
    def fetch_by_pmid(self, pmid: str) -> SearchResult | None:
        """
        Fetch article details by PMID.
        
        Args:
            pmid: PubMed ID.
            
        Returns:
            SearchResult or None if not found.
        """
        results = self._searcher.fetch_details([pmid])
        if results and "error" not in results[0]:
            return SearchResult.from_dict(results[0])
        return None
    
    def fetch_by_pmids(self, pmids: list[str]) -> list[SearchResult]:
        """
        Fetch details for multiple PMIDs.
        
        Args:
            pmids: List of PubMed IDs.
            
        Returns:
            List of SearchResult objects.
        """
        results = self._searcher.fetch_details(pmids)
        return [SearchResult.from_dict(r) for r in results if "error" not in r]
    
    def fetch_by_pmids_raw(self, pmids: list[str]) -> list[dict[str, Any]]:
        """
        Fetch details for multiple PMIDs and return raw dictionaries.
        """
        return self._searcher.fetch_details(pmids)
    
    def fetch_details(self, pmids: list[str]) -> list[dict[str, Any]]:
        """
        Fetch details for multiple PMIDs (returns dicts).
        
        Alias for fetch_by_pmids_raw(). This is the recommended method
        for integrations that need dict format (e.g., zotero-keeper).
        
        Args:
            pmids: List of PubMed IDs.
            
        Returns:
            List of article dictionaries.
        """
        return self._searcher.fetch_details(pmids)
    
    def find_related(self, pmid: str, limit: int = 5) -> list[SearchResult]:
        """
        Find related articles.
        
        Args:
            pmid: Source PMID.
            limit: Maximum number of results.
            
        Returns:
            List of related articles.
        """
        results = self._searcher.find_related_articles(pmid, limit=limit)
        return [SearchResult.from_dict(r) for r in results if "error" not in r]
    
    def find_citing(self, pmid: str, limit: int = 10) -> list[SearchResult]:
        """
        Find articles that cite this one.
        
        Args:
            pmid: Source PMID.
            limit: Maximum number of results.
            
        Returns:
            List of citing articles.
        """
        results = self._searcher.find_citing_articles(pmid, limit=limit)
        return [SearchResult.from_dict(r) for r in results if "error" not in r]
    
    def download_pdf(self, pmid: str, output_path: str | None = None) -> bytes | None:
        """
        Download PDF if available from PMC.
        
        Args:
            pmid: PubMed ID.
            output_path: Optional path to save the PDF.
            
        Returns:
            PDF content as bytes or None.
        """
        return self._searcher.download_pdf(pmid, output_path)
    
    def get_pmc_url(self, pmid: str) -> str | None:
        """
        Get PMC full text URL if available.
        
        Args:
            pmid: PubMed ID.
            
        Returns:
            URL to PMC full text, or None.
        """
        return self._searcher.get_pmc_fulltext_url(pmid)
