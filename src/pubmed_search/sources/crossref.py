"""
CrossRef API Integration

Provides access to CrossRef's metadata API for DOI resolution and article lookup.
CrossRef is the official DOI registration agency for scholarly publications.

API Documentation: https://api.crossref.org/swagger-ui/index.html

Features:
- DOI metadata resolution
- Work search by title/author
- Citation counts (is-referenced-by-count)
- Reference lists
- Funder information

Rate Limits:
- Polite pool (with email): ~50 req/sec
- Anonymous: ~1 req/sec (strongly discouraged)

Best Practices:
- Always include email in User-Agent (polite pool)
- Use mailto: parameter for higher rate limits
- Cache responses when possible
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# CrossRef API endpoint
CROSSREF_API_BASE = "https://api.crossref.org"

# Default contact email (required for polite pool)
DEFAULT_EMAIL = "pubmed-search-mcp@example.com"


class CrossRefClient:
    """
    CrossRef API client for DOI metadata and article search.
    
    Usage:
        client = CrossRefClient(email="your@email.com")
        
        # Get article by DOI
        article = client.get_work("10.1001/jama.2024.12345")
        
        # Search for articles
        results = client.search("machine learning healthcare", limit=10)
        
        # Get references cited by an article
        refs = client.get_references("10.1001/jama.2024.12345")
    
    Note:
        Always provide your email for access to the "polite pool" with
        higher rate limits. Without email, requests are severely throttled.
    """
    
    def __init__(
        self,
        email: str | None = None,
        timeout: float = 30.0,
    ):
        """
        Initialize CrossRef client.
        
        Args:
            email: Contact email for polite pool access (strongly recommended)
            timeout: Request timeout in seconds
        """
        self._email = email or DEFAULT_EMAIL
        self._timeout = timeout
        self._last_request_time = 0.0
        # Rate limit: be polite, ~20 req/sec max
        self._min_interval = 0.05
    
    def _rate_limit(self) -> None:
        """Simple rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()
    
    def _make_request(self, url: str) -> dict[str, Any] | None:
        """Make HTTP request to CrossRef API."""
        self._rate_limit()
        
        # Add mailto parameter for polite pool
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}mailto={urllib.parse.quote(self._email)}"
        
        headers = {
            "User-Agent": f"pubmed-search-mcp/1.0 (mailto:{self._email})",
            "Accept": "application/json",
        }
        
        request = urllib.request.Request(url, headers=headers)
        
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
                return data.get("message", data)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                logger.debug(f"CrossRef: DOI not found - {url}")
            elif e.code == 429:
                logger.warning("CrossRef: Rate limit exceeded, please slow down")
            else:
                logger.error(f"CrossRef HTTP error {e.code}: {e.reason}")
            return None
        except urllib.error.URLError as e:
            logger.error(f"CrossRef URL error: {e.reason}")
            return None
        except Exception as e:
            logger.error(f"CrossRef request failed: {e}")
            return None
    
    def get_work(self, doi: str) -> dict[str, Any] | None:
        """
        Get metadata for a single work by DOI.
        
        Args:
            doi: DOI string (with or without https://doi.org/ prefix)
            
        Returns:
            Work metadata dict or None if not found
            
        Example:
            >>> client.get_work("10.1001/jama.2024.12345")
            {
                "DOI": "10.1001/jama.2024.12345",
                "title": ["Article Title"],
                "author": [...],
                "container-title": ["JAMA"],
                ...
            }
        """
        # Normalize DOI
        doi = self._normalize_doi(doi)
        
        url = f"{CROSSREF_API_BASE}/works/{urllib.parse.quote(doi, safe='')}"
        return self._make_request(url)
    
    def search(
        self,
        query: str,
        limit: int = 10,
        offset: int = 0,
        sort: str = "relevance",
        order: str = "desc",
        filter_params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Search for works in CrossRef.
        
        Args:
            query: Search query (searches title, author, etc.)
            limit: Maximum results (max 1000)
            offset: Results offset for pagination
            sort: Sort field - "relevance", "published", "indexed", "is-referenced-by-count"
            order: Sort order - "asc" or "desc"
            filter_params: Additional filters (e.g., {"from-pub-date": "2020"})
            
        Returns:
            Dict with items and metadata
            
        Example:
            >>> client.search("CRISPR gene therapy", limit=5, sort="is-referenced-by-count")
        """
        params = {
            "query": query,
            "rows": str(min(limit, 1000)),
            "offset": str(offset),
            "sort": sort,
            "order": order,
        }
        
        # Add filters
        if filter_params:
            filter_parts = []
            for key, value in filter_params.items():
                filter_parts.append(f"{key}:{value}")
            params["filter"] = ",".join(filter_parts)
        
        url = f"{CROSSREF_API_BASE}/works?{urllib.parse.urlencode(params)}"
        data = self._make_request(url)
        
        if not data:
            return {"total_results": 0, "items": []}
        
        return {
            "total_results": data.get("total-results", 0),
            "items": data.get("items", []),
            "query": query,
        }
    
    def search_by_title(
        self,
        title: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Search for works by exact title match.
        
        More precise than general search - useful for finding specific articles.
        
        Args:
            title: Article title
            limit: Maximum results
            
        Returns:
            List of matching works
        """
        params = {
            "query.title": title,
            "rows": str(min(limit, 20)),
        }
        
        url = f"{CROSSREF_API_BASE}/works?{urllib.parse.urlencode(params)}"
        data = self._make_request(url)
        
        if not data:
            return []
        
        return data.get("items", [])
    
    def get_references(
        self,
        doi: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get references cited by an article.
        
        Note: Not all publishers deposit reference lists with CrossRef.
        
        Args:
            doi: DOI of the citing article
            limit: Maximum references to return
            
        Returns:
            List of reference objects (may include DOIs for linked refs)
        """
        work = self.get_work(doi)
        if not work:
            return []
        
        references = work.get("reference", [])
        return references[:limit]
    
    def get_citations(
        self,
        doi: str,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Get articles that cite this DOI (forward citations).
        
        Uses CrossRef's citation index, which may not be complete
        for all publishers.
        
        Args:
            doi: DOI of the cited article
            limit: Maximum citations to return
            offset: Pagination offset
            
        Returns:
            Dict with citing articles and count
        """
        doi = self._normalize_doi(doi)
        
        # Get citation count from work metadata
        work = self.get_work(doi)
        citation_count = work.get("is-referenced-by-count", 0) if work else 0
        
        # Search for citing works
        params = {
            "filter": f"references:{doi}",
            "rows": str(min(limit, 100)),
            "offset": str(offset),
            "sort": "published",
            "order": "desc",
        }
        
        url = f"{CROSSREF_API_BASE}/works?{urllib.parse.urlencode(params)}"
        data = self._make_request(url)
        
        if not data:
            return {"citation_count": citation_count, "items": []}
        
        return {
            "citation_count": citation_count,
            "items": data.get("items", []),
        }
    
    def get_journal(self, issn: str) -> dict[str, Any] | None:
        """
        Get journal metadata by ISSN.
        
        Args:
            issn: Journal ISSN (print or electronic)
            
        Returns:
            Journal metadata or None
        """
        url = f"{CROSSREF_API_BASE}/journals/{issn}"
        return self._make_request(url)
    
    def resolve_doi_batch(
        self,
        dois: list[str],
    ) -> dict[str, dict[str, Any] | None]:
        """
        Resolve multiple DOIs in batch.
        
        Note: CrossRef doesn't have a true batch API, so this makes
        sequential requests with rate limiting.
        
        Args:
            dois: List of DOIs to resolve
            
        Returns:
            Dict mapping DOI -> work metadata (None if not found)
        """
        results = {}
        for doi in dois:
            results[doi] = self.get_work(doi)
        return results
    
    def enrich_with_crossref(
        self,
        pmid: str | None = None,
        doi: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Enrich article data by finding CrossRef metadata.
        
        Tries to find CrossRef record using available identifiers.
        
        Args:
            pmid: PubMed ID (will search by title if DOI not found)
            doi: DOI (preferred)
            title: Article title (fallback search)
            
        Returns:
            CrossRef work metadata or None
        """
        # Try DOI first (most reliable)
        if doi:
            work = self.get_work(doi)
            if work:
                return work
        
        # Fall back to title search
        if title:
            results = self.search_by_title(title, limit=3)
            if results:
                # Return best match (first result from title search)
                return results[0]
        
        return None
    
    @staticmethod
    def _normalize_doi(doi: str) -> str:
        """Normalize DOI string."""
        doi = doi.strip()
        # Remove URL prefixes
        for prefix in ["https://doi.org/", "http://doi.org/", "doi:"]:
            if doi.lower().startswith(prefix.lower()):
                doi = doi[len(prefix):]
        return doi
    
    @staticmethod
    def extract_publication_date(work: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
        """
        Extract publication date from CrossRef work.
        
        CrossRef has multiple date fields with different granularity.
        Priority: published-print > published-online > published > created
        
        Args:
            work: CrossRef work metadata
            
        Returns:
            Tuple of (year, month, day) - components may be None
        """
        # Try different date fields in order of preference
        date_fields = [
            "published-print",
            "published-online", 
            "published",
            "created",
        ]
        
        for field in date_fields:
            if field in work:
                date_parts = work[field].get("date-parts", [[]])
                if date_parts and date_parts[0]:
                    parts = date_parts[0]
                    year = parts[0] if len(parts) >= 1 else None
                    month = parts[1] if len(parts) >= 2 else None
                    day = parts[2] if len(parts) >= 3 else None
                    return (year, month, day)
        
        return (None, None, None)


# Singleton instance
_crossref_client: CrossRefClient | None = None


def get_crossref_client(email: str | None = None) -> CrossRefClient:
    """Get or create CrossRef client singleton."""
    global _crossref_client
    if _crossref_client is None:
        import os
        _crossref_client = CrossRefClient(
            email=email or os.environ.get("CROSSREF_EMAIL")
        )
    return _crossref_client


# Convenience functions
def get_doi_metadata(doi: str) -> dict[str, Any] | None:
    """Get metadata for a DOI."""
    client = get_crossref_client()
    return client.get_work(doi)


def search_crossref(
    query: str,
    limit: int = 10,
    sort: str = "relevance",
) -> list[dict[str, Any]]:
    """Search CrossRef for works."""
    client = get_crossref_client()
    result = client.search(query=query, limit=limit, sort=sort)
    return result.get("items", [])


def get_citation_count(doi: str) -> int:
    """Get citation count for a DOI."""
    client = get_crossref_client()
    work = client.get_work(doi)
    if work:
        return work.get("is-referenced-by-count", 0)
    return 0
