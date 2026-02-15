"""
Unpaywall API Integration

Provides access to Unpaywall's API for finding open access versions of articles.
Unpaywall indexes OA copies from repositories, preprint servers, and publisher sites.

API Documentation: https://unpaywall.org/products/api

Features:
- Find OA versions by DOI
- Get best available OA link
- Determine OA status (gold, green, hybrid, bronze)
- License information

Rate Limits:
- 100,000 requests/day with email
- No API key required, just email

Best Practices:
- Always include email parameter
- Cache responses (OA status changes slowly)
- Use for enriching existing article data
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import TYPE_CHECKING, Any, Literal

from pubmed_search.infrastructure.sources.base_client import _CONTINUE, BaseAPIClient

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

# Unpaywall API endpoint
UNPAYWALL_API_BASE = "https://api.unpaywall.org/v2"

# Default contact email (required)
DEFAULT_EMAIL = "pubmed-search-mcp@example.com"


class UnpaywallClient(BaseAPIClient):
    """
    Unpaywall API client for finding open access versions of articles.

    Usage:
        client = UnpaywallClient(email="your@email.com")

        # Check if article has OA version
        oa_info = client.get_oa_status("10.1001/jama.2024.12345")

        if oa_info and oa_info["is_oa"]:
            print(f"OA link: {oa_info['best_oa_location']['url']}")

    Note:
        Email is required. Unpaywall uses it to track usage and
        contact you if there are issues.
    """

    _service_name = "Unpaywall"

    def __init__(
        self,
        email: str | None = None,
        timeout: float = 30.0,
    ):
        """
        Initialize Unpaywall client.

        Args:
            email: Contact email (required by Unpaywall ToS)
            timeout: Request timeout in seconds
        """
        self._email = email or DEFAULT_EMAIL
        super().__init__(
            timeout=timeout,
            min_interval=0.1,
            headers={
                "User-Agent": f"pubmed-search-mcp/1.0 (mailto:{self._email})",
                "Accept": "application/json",
            },
        )

    def _handle_expected_status(self, response: httpx.Response, url: str) -> dict[str, Any] | str | None:
        """Handle 404 (DOI not found) and 422 (invalid DOI format)."""
        if response.status_code == 404:
            logger.debug("Unpaywall: DOI not found")
            return None
        if response.status_code == 422:
            logger.warning("Unpaywall: Invalid DOI format")
            return None
        return _CONTINUE  # type: ignore[return-value]

    async def get_oa_status(self, doi: str) -> dict[str, Any] | None:
        """
        Get open access status and links for a DOI.

        Args:
            doi: DOI string (with or without https://doi.org/ prefix)

        Returns:
            OA information dict or None if DOI not found

        Example:
            >>> client.get_oa_status("10.1001/jama.2024.12345")
            {
                "doi": "10.1001/jama.2024.12345",
                "is_oa": True,
                "oa_status": "green",
                "best_oa_location": {
                    "url": "https://...",
                    "host_type": "repository",
                    "version": "publishedVersion",
                    "license": "cc-by"
                },
                "oa_locations": [...],
                ...
            }
        """
        doi = self._normalize_doi(doi)
        url = f"{UNPAYWALL_API_BASE}/{urllib.parse.quote(doi, safe='/')}?email={urllib.parse.quote(self._email, safe='@')}"

        data = await self._make_request(url)
        if not data:
            return None

        # Normalize response
        if isinstance(data, str):
            return None
        return self._normalize_response(data)

    async def get_best_oa_link(self, doi: str) -> str | None:
        """
        Get the best available OA link for a DOI.

        Args:
            doi: DOI string

        Returns:
            Best OA URL or None if not available
        """
        oa_info = await self.get_oa_status(doi)
        if oa_info and oa_info.get("is_oa"):
            best = oa_info.get("best_oa_location")
            if best:
                return best.get("url") or best.get("url_for_pdf")
        return None

    async def get_pdf_link(self, doi: str) -> str | None:
        """
        Get direct PDF link if available.

        Args:
            doi: DOI string

        Returns:
            PDF URL or None
        """
        oa_info = await self.get_oa_status(doi)
        if not oa_info or not oa_info.get("is_oa"):
            return None

        # Check best location first
        best = oa_info.get("best_oa_location", {})
        if best.get("url_for_pdf"):
            return best["url_for_pdf"]

        # Check all locations for PDF
        for loc in oa_info.get("oa_locations", []):
            if loc.get("url_for_pdf"):
                return loc["url_for_pdf"]

        return None

    async def batch_get_oa_status(
        self,
        dois: list[str],
    ) -> dict[str, dict[str, Any] | None]:
        """
        Get OA status for multiple DOIs.

        Note: Makes sequential requests with rate limiting.
        For large batches, consider using Unpaywall's data dump instead.

        Args:
            dois: List of DOIs

        Returns:
            Dict mapping DOI -> OA info (None if not found)
        """
        results = {}
        for doi in dois:
            results[doi] = await self.get_oa_status(doi)
        return results

    async def enrich_article(
        self,
        doi: str,
    ) -> dict[str, Any]:
        """
        Get OA enrichment data for an article.

        Returns structured data suitable for merging with UnifiedArticle.

        Args:
            doi: DOI string

        Returns:
            Dict with OA fields for article enrichment
        """
        oa_info = await self.get_oa_status(doi)

        result: dict[str, Any] = {
            "is_oa": False,
            "oa_status": "unknown",
            "oa_links": [],
        }

        if not oa_info:
            return result

        result["is_oa"] = oa_info.get("is_oa", False)
        result["oa_status"] = oa_info.get("oa_status", "unknown")

        # Build OA links list
        for loc in oa_info.get("oa_locations", []):
            link = {
                "url": loc.get("url") or loc.get("url_for_landing_page"),
                "url_for_pdf": loc.get("url_for_pdf"),
                "version": loc.get("version", "unknown"),
                "host_type": loc.get("host_type"),
                "license": loc.get("license"),
                "is_best": loc == oa_info.get("best_oa_location"),
            }
            if link["url"]:
                result["oa_links"].append(link)

        return result

    def _normalize_response(self, data: dict[str, Any]) -> dict[str, Any]:
        """Normalize Unpaywall API response."""
        return {
            "doi": data.get("doi"),
            "is_oa": data.get("is_oa", False),
            "oa_status": data.get("oa_status", "unknown"),
            "best_oa_location": data.get("best_oa_location"),
            "oa_locations": data.get("oa_locations", []),
            "title": data.get("title"),
            "year": data.get("year"),
            "journal_name": data.get("journal_name"),
            "journal_issn": data.get("journal_issns"),
            "publisher": data.get("publisher"),
            "is_paratext": data.get("is_paratext", False),
            "updated": data.get("updated"),
        }

    @staticmethod
    def _normalize_doi(doi: str) -> str:
        """Normalize DOI string."""
        doi = doi.strip()
        for prefix in ["https://doi.org/", "http://doi.org/", "doi:"]:
            if doi.lower().startswith(prefix.lower()):
                doi = doi[len(prefix) :]
        return doi

    @staticmethod
    def get_oa_status_description(status: str) -> str:
        """
        Get human-readable description of OA status.

        Args:
            status: OA status code (gold, green, hybrid, bronze, closed)

        Returns:
            Description string
        """
        descriptions = {
            "gold": "Published in an OA journal (free to read and reuse)",
            "green": "Archived in a repository (author's version)",
            "hybrid": "OA in a subscription journal (often author-paid APC)",
            "bronze": "Free to read on publisher site (no clear license)",
            "closed": "Behind paywall (no free version found)",
            "unknown": "OA status not determined",
        }
        return descriptions.get(status, f"Unknown status: {status}")


# OA Status type for type hints
OAStatus = Literal["gold", "green", "hybrid", "bronze", "closed", "unknown"]


# Singleton instance
_unpaywall_client: UnpaywallClient | None = None


def get_unpaywall_client(email: str | None = None) -> UnpaywallClient:
    """Get or create Unpaywall client singleton."""
    global _unpaywall_client
    if _unpaywall_client is None:
        import os

        _unpaywall_client = UnpaywallClient(email=email or os.environ.get("UNPAYWALL_EMAIL"))
    return _unpaywall_client


# Convenience functions
async def find_oa_link(doi: str) -> str | None:
    """Find best OA link for a DOI."""
    client = get_unpaywall_client()
    return await client.get_best_oa_link(doi)


async def find_pdf_link(doi: str) -> str | None:
    """Find PDF link for a DOI."""
    client = get_unpaywall_client()
    return await client.get_pdf_link(doi)


async def is_open_access(doi: str) -> bool:
    """Check if DOI has an OA version."""
    client = get_unpaywall_client()
    oa_info = await client.get_oa_status(doi)
    return oa_info.get("is_oa", False) if oa_info else False


async def get_oa_status(doi: str) -> OAStatus:
    """Get OA status for a DOI."""
    client = get_unpaywall_client()
    oa_info = await client.get_oa_status(doi)
    if oa_info:
        return oa_info.get("oa_status", "unknown")
    return "unknown"
