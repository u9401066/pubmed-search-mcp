"""
CORE API Integration

Provides access to CORE's API for open access research outputs.
CORE aggregates open access research from repositories worldwide.

API Documentation: https://api.core.ac.uk/docs/v3

Features:
- 200M+ metadata records, 42M+ full text
- Full text search capability
- Access to 14,000+ data providers
- Free API key required for better rate limits
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# CORE API endpoints
CORE_API_BASE = "https://api.core.ac.uk/v3"

# Default values
DEFAULT_EMAIL = "pubmed-search-mcp@example.com"


class COREClient:
    """
    CORE API client for open access research.
    
    Usage:
        # Without API key (limited to 100 requests/day)
        client = COREClient()
        
        # With API key (5000+ requests/day)
        client = COREClient(api_key="your-api-key")
        
        results = client.search("machine learning", limit=10)
        work = client.get_work(152480964)
    """
    
    def __init__(
        self, 
        api_key: str | None = None, 
        email: str | None = None,
        timeout: float = 30.0
    ):
        """
        Initialize CORE client.
        
        Args:
            api_key: CORE API key (get from https://core.ac.uk/services/api)
            email: Contact email
            timeout: Request timeout in seconds
        """
        self._api_key = api_key
        self._email = email or DEFAULT_EMAIL
        self._timeout = timeout
        self._last_request_time = 0
        # Rate limit: 10/min without key, 25/min with key
        self._min_interval = 6.0 if not api_key else 2.5
    
    def _rate_limit(self):
        """Simple rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()
    
    def _make_request(
        self, 
        url: str, 
        method: str = "GET",
        data: dict | None = None
    ) -> dict | None:
        """Make HTTP request to CORE API."""
        self._rate_limit()
        
        headers = {
            "User-Agent": f"pubmed-search-mcp/1.0 (mailto:{self._email})",
            "Accept": "application/json",
        }
        
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        
        if method == "POST" and data:
            headers["Content-Type"] = "application/json"
            request_data = json.dumps(data).encode("utf-8")
            request = urllib.request.Request(url, data=request_data, headers=headers, method="POST")
        else:
            request = urllib.request.Request(url, headers=headers)
        
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                logger.error("CORE API: Unauthorized - check your API key")
            elif e.code == 429:
                logger.warning("CORE API: Rate limit exceeded")
            else:
                logger.error(f"CORE API HTTP error {e.code}: {e.reason}")
            return None
        except urllib.error.URLError as e:
            logger.error(f"CORE API URL error: {e.reason}")
            return None
        except Exception as e:
            logger.error(f"CORE API request failed: {e}")
            return None
    
    def search(
        self,
        query: str,
        limit: int = 10,
        offset: int = 0,
        entity_type: str = "works",
        year_from: int | None = None,
        year_to: int | None = None,
        has_fulltext: bool = False,
        sort: str | None = None,
    ) -> dict[str, Any]:
        """
        Search CORE for research outputs.
        
        Args:
            query: Search query (supports CORE query language)
            limit: Maximum results (max 100 per request)
            offset: Results offset for pagination
            entity_type: "works" (deduplicated) or "outputs" (raw)
            year_from: Minimum publication year
            year_to: Maximum publication year
            has_fulltext: Only return items with full text
            sort: Sort order (e.g., "relevance", "recency")
            
        Returns:
            Dict with results and metadata
        """
        try:
            # Build query with filters
            query_parts = [query]
            
            if year_from:
                query_parts.append(f'yearPublished>="{year_from}"')
            if year_to:
                query_parts.append(f'yearPublished<="{year_to}"')
            if has_fulltext:
                query_parts.append("_exists_:fullText")
            
            full_query = " AND ".join(query_parts) if len(query_parts) > 1 else query
            
            params = {
                "q": full_query,
                "limit": str(min(limit, 100)),
                "offset": str(offset),
            }
            
            if sort:
                params["sort"] = sort
            
            url = f"{CORE_API_BASE}/search/{entity_type}?{urllib.parse.urlencode(params)}"
            data = self._make_request(url)
            
            if not data:
                return {"total_hits": 0, "results": []}
            
            # Normalize results
            results = []
            for item in data.get("results", []):
                results.append(self._normalize_work(item))
            
            return {
                "total_hits": data.get("totalHits", len(results)),
                "results": results,
                "offset": offset,
                "limit": limit,
            }
            
        except Exception as e:
            logger.error(f"CORE search failed: {e}")
            return {"total_hits": 0, "results": []}
    
    def search_fulltext(
        self,
        query: str,
        limit: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> dict[str, Any]:
        """
        Search within full text content.
        
        Args:
            query: Text to search in full text
            limit: Maximum results
            year_from: Minimum publication year
            year_to: Maximum publication year
            
        Returns:
            Dict with results containing full text matches
        """
        # Search in fullText field specifically
        fulltext_query = f'fullText:"{query}"'
        return self.search(
            query=fulltext_query,
            limit=limit,
            entity_type="outputs",  # Outputs have full text
            year_from=year_from,
            year_to=year_to,
            has_fulltext=True,
        )
    
    def get_work(self, work_id: int | str) -> dict | None:
        """
        Get a specific work by ID.
        
        Args:
            work_id: CORE work ID
            
        Returns:
            Work details or None
        """
        try:
            url = f"{CORE_API_BASE}/works/{work_id}"
            data = self._make_request(url)
            
            if not data:
                return None
            
            return self._normalize_work(data)
            
        except Exception as e:
            logger.error(f"Get CORE work failed: {e}")
            return None
    
    def get_output(self, output_id: int | str) -> dict | None:
        """
        Get a specific output by ID.
        
        Outputs are raw records from data providers, may include full text.
        
        Args:
            output_id: CORE output ID
            
        Returns:
            Output details or None
        """
        try:
            url = f"{CORE_API_BASE}/outputs/{output_id}"
            data = self._make_request(url)
            
            if not data:
                return None
            
            return self._normalize_output(data)
            
        except Exception as e:
            logger.error(f"Get CORE output failed: {e}")
            return None
    
    def get_fulltext(self, output_id: int | str) -> str | None:
        """
        Get full text content for an output.
        
        Args:
            output_id: CORE output ID
            
        Returns:
            Full text string or None
        """
        output = self.get_output(output_id)
        if output:
            return output.get("full_text")
        return None
    
    def search_by_doi(self, doi: str) -> dict | None:
        """
        Find a work by DOI.
        
        Args:
            doi: DOI string
            
        Returns:
            Work details or None
        """
        result = self.search(f'doi:"{doi}"', limit=1)
        if result.get("results"):
            return result["results"][0]
        return None
    
    def search_by_pmid(self, pmid: str) -> dict | None:
        """
        Find a work by PubMed ID.
        
        Args:
            pmid: PubMed ID
            
        Returns:
            Work details or None
        """
        result = self.search(f'pubmedId:{pmid}', limit=1)
        if result.get("results"):
            return result["results"][0]
        return None
    
    def _normalize_work(self, work: dict) -> dict:
        """Normalize CORE work to common format."""
        # Extract authors
        authors = []
        for author in work.get("authors", []):
            if isinstance(author, dict):
                authors.append(author.get("name", ""))
            elif isinstance(author, str):
                authors.append(author)
        
        # Extract identifiers
        identifiers = work.get("identifiers", [])
        doi = None
        pmid = None
        arxiv_id = None
        
        for ident in identifiers:
            if isinstance(ident, dict):
                ident_type = ident.get("type", "").upper()
                ident_value = ident.get("identifier", "")
                if ident_type == "DOI":
                    doi = ident_value
                elif ident_type == "PMID":
                    pmid = ident_value
                elif ident_type == "ARXIV":
                    arxiv_id = ident_value
        
        # Also check direct fields
        if not doi:
            doi = work.get("doi")
        if not pmid:
            pmid = work.get("pubmedId")
        if not arxiv_id:
            arxiv_id = work.get("arxivId")
        
        # Get journal info
        journals = work.get("journals", [])
        journal = ""
        if journals and isinstance(journals[0], dict):
            journal = journals[0].get("title", "")
        
        # Get download URL
        download_url = work.get("downloadUrl")
        
        # Get links
        links = work.get("links", [])
        pdf_url = None
        reader_url = None
        for link in links:
            if isinstance(link, dict):
                link_type = link.get("type", "")
                if link_type == "download":
                    pdf_url = link.get("url")
                elif link_type == "reader":
                    reader_url = link.get("url")
        
        return {
            "core_id": work.get("id"),
            "title": work.get("title", ""),
            "authors": authors,
            "author_string": ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else ""),
            "abstract": work.get("abstract", ""),
            "year": work.get("yearPublished"),
            "journal": journal,
            "publisher": work.get("publisher", ""),
            "doi": doi,
            "pmid": pmid,
            "arxiv_id": arxiv_id,
            "language": work.get("language", {}).get("name") if isinstance(work.get("language"), dict) else None,
            "document_type": work.get("documentType", []),
            "has_fulltext": bool(work.get("fullText")),
            "fulltext_available": "_exists_:fullText" in str(work) or work.get("downloadUrl") is not None,
            "download_url": download_url,
            "pdf_url": pdf_url,
            "reader_url": reader_url,
            "citation_count": work.get("citationCount"),
            "data_providers": [dp.get("name") for dp in work.get("dataProviders", []) if isinstance(dp, dict)],
            "_source": "core",
        }
    
    def _normalize_output(self, output: dict) -> dict:
        """Normalize CORE output to common format."""
        # Start with work normalization
        normalized = self._normalize_work(output)
        
        # Add output-specific fields
        normalized["output_id"] = output.get("id")
        normalized["full_text"] = output.get("fullText")
        normalized["fulltext_status"] = output.get("fulltextStatus")
        
        # Repository info
        repos = output.get("repositories", [])
        if repos and isinstance(repos, dict):
            normalized["repository"] = repos.get("name")
            normalized["repository_url"] = repos.get("urlHomepage")
        elif repos and isinstance(repos, list) and repos:
            first_repo = repos[0] if isinstance(repos[0], dict) else {}
            normalized["repository"] = first_repo.get("name")
            normalized["repository_url"] = first_repo.get("urlHomepage")
        
        return normalized


# Singleton instance
_core_client: COREClient | None = None


def get_core_client(api_key: str | None = None) -> COREClient:
    """Get or create CORE client singleton."""
    global _core_client
    if _core_client is None:
        import os
        key = api_key or os.environ.get("CORE_API_KEY")
        _core_client = COREClient(api_key=key)
    return _core_client


# Convenience functions
def search_core(
    query: str,
    limit: int = 10,
    year_from: int | None = None,
    year_to: int | None = None,
    has_fulltext: bool = False,
) -> list[dict]:
    """Search CORE for research outputs."""
    client = get_core_client()
    result = client.search(
        query=query,
        limit=limit,
        year_from=year_from,
        year_to=year_to,
        has_fulltext=has_fulltext,
    )
    return result.get("results", [])


def search_core_fulltext(
    query: str,
    limit: int = 10,
) -> list[dict]:
    """Search within full text content in CORE."""
    client = get_core_client()
    result = client.search_fulltext(query=query, limit=limit)
    return result.get("results", [])
