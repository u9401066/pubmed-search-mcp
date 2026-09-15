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

from __future__ import annotations

import logging
import urllib.parse
from typing import TYPE_CHECKING, Any

from pubmed_search.domain.value_objects.article_identifiers import normalize_doi
from pubmed_search.infrastructure.provider_payload import is_provider_error_envelope
from pubmed_search.infrastructure.sources.base_client import (
    _CONTINUE,
    BaseAPIClient,
    raise_provider_schema_error,
)
from pubmed_search.infrastructure.sources.contact import first_contact_email, get_source_contact_email

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

# CrossRef API endpoint
CROSSREF_API_BASE = "https://api.crossref.org"

# Default contact email (required for polite pool)
DEFAULT_EMAIL = "pubmed-search-mcp@example.com"


class CrossRefClient(BaseAPIClient):
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

    _service_name = "CrossRef"

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
        self._email = first_contact_email(email, get_source_contact_email(), DEFAULT_EMAIL) or DEFAULT_EMAIL
        super().__init__(
            timeout=timeout,
            min_interval=0.05,
            headers={
                "User-Agent": f"pubmed-search-mcp/1.0 (mailto:{self._email})",
                "Accept": "application/json",
            },
        )

    async def _execute_request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Add mailto parameter for polite pool access."""
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}mailto={urllib.parse.quote(self._email)}"
        return await super()._execute_request(url, method=method, data=data, params=params, headers=headers)

    def _handle_expected_status(self, response: httpx.Response, url: str) -> Any:
        """Handle 404 (DOI not found)."""
        if response.status_code == 404:
            logger.debug("CrossRef DOI not found")
            return None
        return _CONTINUE

    def _parse_response(self, response: httpx.Response, expect_json: bool) -> dict[str, Any] | str:
        """Extract 'message' key from CrossRef JSON responses."""
        if not expect_json:
            return response.text
        data = response.json()
        if not isinstance(data, dict) or is_provider_error_envelope(data):
            raise_provider_schema_error(self._service_name)
        message = data.get("message", data)
        if not isinstance(message, dict):
            raise_provider_schema_error(self._service_name)
        return message

    async def get_work(self, doi: str) -> dict[str, Any] | None:
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
        result = await self._make_request(url)
        if result is None:
            return None
        if not isinstance(result, dict):
            raise_provider_schema_error(self._service_name)
        return result

    async def search(
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
        data = await self._make_request(url)

        if data is None:
            return {"total_results": 0, "items": []}
        if not isinstance(data, dict):
            raise_provider_schema_error(self._service_name)

        if not isinstance(data.get("items"), list) or any(not isinstance(item, dict) for item in data["items"]):
            raise_provider_schema_error(self._service_name)
        count = data.get("total-results")
        if isinstance(count, bool) or not isinstance(count, int) or count < len(data["items"]):
            raise_provider_schema_error(self._service_name)
        return {
            "total_results": count,
            "items": data.get("items", []),
            "query": query,
        }

    async def search_by_title(
        self,
        title: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Search for candidate works using title relevance.

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
        data = await self._make_request(url)

        if data is None:
            return []
        if not isinstance(data, dict):
            raise_provider_schema_error(self._service_name)

        items = data.get("items")
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise_provider_schema_error(self._service_name)
        return items

    async def get_references(
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
        work = await self.get_work(doi)
        if not work:
            return []

        references = work.get("reference") or []
        if not isinstance(references, list) or any(not isinstance(item, dict) for item in references):
            raise_provider_schema_error(self._service_name)
        return references[:limit]

    async def get_citations(
        self,
        doi: str,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Get the deposited citation count and explicitly report unavailable edges.

        The public Crossref REST API does not implement a references:DOI filter.
        This compatibility method never fabricates an incoming bibliography.

        Args:
            doi: DOI of the cited article
            limit: Maximum citations to return
            offset: Pagination offset

        Returns:
            Dict with optional citation_count, empty items and retrieval_supported=False
        """
        doi = self._normalize_doi(doi)
        work = await self.get_work(doi)
        count = work.get("is-referenced-by-count") if work else None
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            count = None
        return {
            "citation_count": count,
            "items": [],
            "retrieval_supported": False,
            "warning": "Crossref provides a citation count but does not expose incoming citation lookup through a references filter. Use a citation-network provider for incoming edges.",
        }

    async def get_journal(self, issn: str) -> dict[str, Any] | None:
        """
        Get journal metadata by ISSN.

        Args:
            issn: Journal ISSN (print or electronic)

        Returns:
            Journal metadata or None
        """
        url = f"{CROSSREF_API_BASE}/journals/{issn}"
        result = await self._make_request(url)
        if result is None:
            return None
        if not isinstance(result, dict):
            raise_provider_schema_error(self._service_name)
        return result

    async def get_funder(self, funder_id: str) -> dict[str, Any] | None:
        """
        Get funder metadata by Crossref funder identifier.

        Args:
            funder_id: Crossref funder DOI, a raw ``10.13039/...`` identifier,
                or a DOI URL.

        Returns:
            Funder metadata or ``None`` when no record is found.
        """
        normalized_funder_id = self._normalize_funder_id(funder_id)
        url = f"{CROSSREF_API_BASE}/funders/{urllib.parse.quote(normalized_funder_id, safe='')}"
        result = await self._make_request(url)
        if result is None:
            return None
        if not isinstance(result, dict):
            raise_provider_schema_error(self._service_name)
        return result

    async def search_funders(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """
        Search Crossref funders by name.

        Args:
            query: Funder name query string.
            limit: Maximum number of funders to return.

        Returns:
            List of funder metadata dictionaries.
        """
        params = {
            "query": query,
            "rows": str(min(limit, 1000)),
        }
        url = f"{CROSSREF_API_BASE}/funders?{urllib.parse.urlencode(params)}"
        data = await self._make_request(url)
        if data is None:
            return []
        if not isinstance(data, dict):
            raise_provider_schema_error(self._service_name)
        items = data.get("items")
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise_provider_schema_error(self._service_name)
        return items

    async def resolve_doi_batch(
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
            results[doi] = await self.get_work(doi)
        return results

    async def enrich_with_crossref(
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
            work = await self.get_work(doi)
            if work:
                return work

        # Fall back to title search
        if title:
            results = await self.search_by_title(title, limit=3)
            if results:
                # Return best match (first result from title search)
                return results[0]

        return None

    @staticmethod
    def _normalize_doi(doi: str) -> str:
        """Normalize DOI string."""
        return normalize_doi(doi)

    @staticmethod
    def _normalize_funder_id(funder_id: str) -> str:
        """Normalize a Crossref funder identifier to its canonical DOI form."""
        normalized = funder_id.strip()
        for prefix in [
            "https://doi.org/",
            "http://doi.org/",
            "https://dx.doi.org/",
            "http://dx.doi.org/",
            "doi:",
        ]:
            if normalized.lower().startswith(prefix.lower()):
                normalized = normalized[len(prefix) :]
        return normalized

    @staticmethod
    def extract_publication_date(
        work: dict[str, Any],
    ) -> tuple[int | None, int | None, int | None]:
        """
        Extract publication date from CrossRef work.

        CrossRef has multiple date fields with different granularity.
        Priority: published-print > published-online > published > issued

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
            "issued",
        ]

        for field in date_fields:
            value = work.get(field)
            if not isinstance(value, dict):
                continue
            date_parts = value.get("date-parts")
            if (
                not isinstance(date_parts, list)
                or not date_parts
                or not isinstance(date_parts[0], list)
                or not date_parts[0]
            ):
                continue
            parts = date_parts[0]
            year = parts[0]
            if isinstance(year, bool) or not isinstance(year, int) or not 1000 <= year <= 9999:
                continue
            month = parts[1] if len(parts) > 1 else None
            day = parts[2] if len(parts) > 2 else None
            if isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12:
                month = None
            if month is None or isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 31:
                day = None
            return (year, month, day)
        return (None, None, None)
