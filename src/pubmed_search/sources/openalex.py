"""
OpenAlex Integration

Provides open access academic search via OpenAlex API.
This is an internal module - not exposed as separate MCP tools.

API Documentation: https://docs.openalex.org/

Features:
- Completely free and open (no API key required)
- Open access filter (DOAJ integration built-in)
- Comprehensive coverage (200M+ works)
- Institution and concept relationships
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# OpenAlex API endpoints
OA_API_BASE = "https://api.openalex.org"
OA_WORKS_URL = f"{OA_API_BASE}/works"
OA_AUTHORS_URL = f"{OA_API_BASE}/authors"

# Polite pool email (required for higher rate limits)
# Users should set their email in NCBI_EMAIL env var
DEFAULT_EMAIL = "pubmed-search-mcp@example.com"


class OpenAlexClient:
    """
    OpenAlex API client.
    
    Usage:
        client = OpenAlexClient(email="your@email.com")
        results = client.search("CRISPR gene editing", limit=10, open_access_only=True)
    """
    
    def __init__(self, email: str | None = None, timeout: float = 30.0):
        """
        Initialize client.
        
        Args:
            email: Email for polite pool (higher rate limits)
            timeout: Request timeout in seconds
        """
        self._email = email or DEFAULT_EMAIL
        self._timeout = timeout
        self._last_request_time = 0
        self._min_interval = 0.1  # OpenAlex is more generous with rate limits
    
    def _rate_limit(self):
        """Simple rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()
    
    def _make_request(self, url: str) -> dict | None:
        """Make HTTP GET request with proper headers."""
        self._rate_limit()
        
        request = urllib.request.Request(url)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", f"pubmed-search-mcp/1.0 (mailto:{self._email})")
        
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            logger.error(f"HTTP error {e.code}: {e.reason}")
            return None
        except urllib.error.URLError as e:
            logger.error(f"URL error: {e.reason}")
            return None
    
    def search(
        self,
        query: str,
        limit: int = 10,
        min_year: int | None = None,
        max_year: int | None = None,
        open_access_only: bool = False,
        is_doaj: bool = False,
        sort: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search OpenAlex works.
        
        Args:
            query: Search query (searches title, abstract, fulltext)
            limit: Maximum results (max 200 per page)
            min_year: Filter by minimum publication year
            max_year: Filter by maximum publication year
            open_access_only: Only return open access works
            is_doaj: Only return works from DOAJ journals
            sort: Sort order. Options:
                  - None (default): Use OpenAlex default (relevance when searching)
                  - "cited_by_count:desc": Most cited first
                  - "publication_date:desc": Most recent first
                  Note: "relevance_score" only works when search is active
            
        Returns:
            List of work dictionaries in normalized format
        """
        try:
            # Build filter string
            filters = []
            
            if min_year:
                filters.append(f"from_publication_date:{min_year}-01-01")
            if max_year:
                filters.append(f"to_publication_date:{max_year}-12-31")
            if open_access_only:
                filters.append("is_oa:true")
            if is_doaj:
                filters.append("locations.source.is_in_doaj:true")
            
            params = {
                "search": query,
                "per_page": str(min(limit, 200)),
                "mailto": self._email,
            }
            
            # Only add sort if explicitly provided
            # Note: relevance_score is the default when search is active
            if sort:
                params["sort"] = sort
            
            if filters:
                params["filter"] = ",".join(filters)
            
            url = f"{OA_WORKS_URL}?{urllib.parse.urlencode(params)}"
            data = self._make_request(url)
            
            if not data:
                return []
            
            works = data.get("results", [])
            
            # Normalize to common format
            return [self._normalize_work(w) for w in works]
            
        except Exception as e:
            logger.error(f"OpenAlex search failed: {e}")
            return []
    
    def get_work(self, work_id: str) -> dict[str, Any] | None:
        """
        Get work by ID (OpenAlex ID, DOI, or PMID).
        
        Args:
            work_id: Work identifier (e.g., "doi:10.1234/example", "pmid:12345678")
            
        Returns:
            Work dictionary or None
        """
        try:
            # Normalize ID format
            if work_id.startswith("10."):  # DOI
                work_id = f"doi:{work_id}"
            elif work_id.isdigit():  # PMID
                work_id = f"pmid:{work_id}"
            
            # URL encode the work_id
            encoded_id = urllib.parse.quote(work_id, safe="")
            params = {"mailto": self._email}
            url = f"{OA_WORKS_URL}/{encoded_id}?{urllib.parse.urlencode(params)}"
            
            data = self._make_request(url)
            if not data:
                return None
            
            return self._normalize_work(data)
            
        except Exception as e:
            logger.error(f"Failed to get work {work_id}: {e}")
            return None
    
    def get_citations(self, work_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """
        Get works that cite this work.
        
        Args:
            work_id: Work identifier
            limit: Maximum results
            
        Returns:
            List of citing works
        """
        try:
            # Use filter to find citing works
            params = {
                "filter": f"cites:{work_id}",
                "per_page": str(min(limit, 200)),
                "sort": "cited_by_count:desc",
                "mailto": self._email,
            }
            
            url = f"{OA_WORKS_URL}?{urllib.parse.urlencode(params)}"
            data = self._make_request(url)
            
            if not data:
                return []
            
            return [self._normalize_work(w) for w in data.get("results", [])]
            
        except Exception as e:
            logger.error(f"Failed to get citations for {work_id}: {e}")
            return []
    
    def _normalize_work(self, work: dict[str, Any]) -> dict[str, Any]:
        """
        Normalize OpenAlex work to common format compatible with PubMed results.
        
        Note: OpenAlex returns very large objects. We extract only essential fields
        to avoid token explosion when sending to LLM.
        """
        # Extract IDs
        ids = work.get("ids", {}) or {}
        doi = ids.get("doi", "")
        if doi and doi.startswith("https://doi.org/"):
            doi = doi.replace("https://doi.org/", "")
        
        pmid = ids.get("pmid", "")
        if pmid and pmid.startswith("https://pubmed.ncbi.nlm.nih.gov/"):
            pmid = pmid.replace("https://pubmed.ncbi.nlm.nih.gov/", "").rstrip("/")
        
        pmc_id = ids.get("pmcid", "")
        if pmc_id and "PMC" in pmc_id:
            # Extract just the PMC ID
            pmc_id = pmc_id.split("PMC")[-1] if "PMC" in pmc_id else pmc_id
            pmc_id = f"PMC{pmc_id}" if pmc_id and not pmc_id.startswith("PMC") else pmc_id
        
        # Extract authors (limit to avoid token explosion)
        authorships = work.get("authorships", []) or []
        author_names = []
        authors_full = []
        for authorship in authorships[:10]:  # Limit to 10 authors
            author = authorship.get("author", {}) or {}
            name = author.get("display_name", "")
            if name:
                author_names.append(name)
                parts = name.rsplit(" ", 1)
                if len(parts) == 2:
                    authors_full.append({"fore_name": parts[0], "last_name": parts[1]})
                else:
                    authors_full.append({"last_name": name, "fore_name": ""})
        
        # Extract journal/source
        primary_location = work.get("primary_location", {}) or {}
        source = primary_location.get("source", {}) or {}
        journal = source.get("display_name", "")
        
        # Extract year/date
        pub_date = work.get("publication_date", "") or ""
        year = pub_date[:4] if pub_date else str(work.get("publication_year", ""))
        month = pub_date[5:7] if len(pub_date) >= 7 else ""
        day = pub_date[8:10] if len(pub_date) >= 10 else ""
        
        # Extract open access info
        oa = work.get("open_access", {}) or {}
        best_oa = work.get("best_oa_location", {}) or {}
        
        return {
            # Core fields - matching PubMed format
            "pmid": pmid,
            "title": work.get("display_name", "") or work.get("title", ""),
            "abstract": self._get_abstract(work),
            "year": year,
            "month": month,
            "day": day,
            "authors": author_names,
            "authors_full": authors_full,
            "journal": journal,
            "journal_abbrev": "",  # OpenAlex doesn't provide abbreviations
            "volume": "",
            "issue": "",
            "pages": "",
            "doi": doi,
            "pmc_id": pmc_id,
            "keywords": [],
            "mesh_terms": [],
            
            # Metrics
            "citation_count": work.get("cited_by_count", 0),
            
            # Access
            "is_open_access": oa.get("is_oa", False),
            "oa_status": oa.get("oa_status", ""),  # gold, green, bronze, etc.
            "pdf_url": best_oa.get("pdf_url"),
            "is_doaj": source.get("is_in_doaj", False),
            
            # Source marker
            "_source": "openalex",
            "_openalex_id": work.get("id", ""),
        }
    
    def _get_abstract(self, work: dict[str, Any]) -> str:
        """
        Extract abstract from OpenAlex inverted index format.
        
        OpenAlex stores abstracts as inverted indices to save space.
        We need to reconstruct the original text.
        """
        abstract_index = work.get("abstract_inverted_index")
        if not abstract_index:
            return ""
        
        try:
            # Reconstruct from inverted index
            # Format: {"word": [positions], ...}
            word_positions = []
            for word, positions in abstract_index.items():
                for pos in positions:
                    word_positions.append((pos, word))
            
            # Sort by position and join
            word_positions.sort(key=lambda x: x[0])
            return " ".join(word for _, word in word_positions)
            
        except Exception as e:
            logger.warning(f"Failed to reconstruct abstract: {e}")
            return ""
    
    def close(self):
        """Close resources (no-op for urllib, but keeps interface consistent)."""
        pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()
