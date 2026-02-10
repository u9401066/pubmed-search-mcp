"""
NCBI Citation Exporter API Client.

Official NCBI API for exporting citations in standard formats.
This provides high-quality, officially formatted citations.

API Endpoint: https://pmc.ncbi.nlm.nih.gov/api/ctxp/v1/pubmed/

Supported formats:
- ris: Reference manager format (EndNote, Zotero, Mendeley)
- medline: NBIB/MEDLINE format
- csl: Citation Style Language JSON (for programmatic use)

Advantages over local formatting:
- Official formatting, always up-to-date
- Complete metadata (abstracts, MeSH terms, affiliations)
- Batch support (multiple PMIDs in single request)
- No maintenance required

Rate limits:
- Same as E-utilities (3/sec without key, 10/sec with key)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import httpx

logger = logging.getLogger(__name__)

# API endpoint (redirected from api.ncbi.nlm.nih.gov)
CITATION_API_BASE = "https://pmc.ncbi.nlm.nih.gov/api/ctxp/v1/pubmed/"

# Supported export formats
CitationFormat = Literal["ris", "medline", "csl"]
OFFICIAL_FORMATS: list[CitationFormat] = ["ris", "medline", "csl"]


@dataclass
class CitationResult:
    """Result from citation export."""

    success: bool
    format: str
    content: str
    pmid_count: int
    error: str | None = None


class NCBICitationExporter:
    """
    Client for NCBI Citation Exporter API.

    Provides official citation formatting from NCBI.
    Use this as the default for best quality outputs.

    Example:
        exporter = NCBICitationExporter()
        result = exporter.export_citations(["12345678", "87654321"], format="ris")
        if result.success:
            print(result.content)
    """

    def __init__(self, timeout: float = 30.0):
        """
        Initialize citation exporter.

        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy-initialized async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": "PubMedSearchMCP/1.0 (github.com/u9401066/pubmed-search-mcp)"
                },
            )
        return self._client

    async def export_citations(
        self,
        pmids: list[str],
        format: CitationFormat = "ris",
    ) -> CitationResult:
        """
        Export citations using official NCBI API.

        This is the RECOMMENDED method for citation export.
        Uses official NCBI formatting for best quality.

        Args:
            pmids: List of PubMed IDs to export
            format: Export format
                - "ris": Reference managers (EndNote, Zotero, Mendeley)
                - "medline": MEDLINE/NBIB format
                - "csl": Citation Style Language JSON

        Returns:
            CitationResult with formatted content

        Example:
            result = exporter.export_citations(["37654670"], format="ris")
            # Returns complete RIS with abstract, MeSH, affiliations
        """
        if not pmids:
            return CitationResult(
                success=False,
                format=format,
                content="",
                pmid_count=0,
                error="No PMIDs provided",
            )

        if format not in OFFICIAL_FORMATS:
            return CitationResult(
                success=False,
                format=format,
                content="",
                pmid_count=0,
                error=f"Unsupported format: {format}. Use: {', '.join(OFFICIAL_FORMATS)}",
            )

        # Build request
        pmid_str = ",".join(str(p) for p in pmids)
        params = {
            "format": format,
            "id": pmid_str,
        }

        try:
            response = await self.client.get(CITATION_API_BASE, params=params)
            response.raise_for_status()

            content = response.text

            # Check for API error response (JSON with error)
            if content.startswith("{") and '"format"' in content:
                import json

                try:
                    error_data = json.loads(content)
                    if "format" in error_data:
                        return CitationResult(
                            success=False,
                            format=format,
                            content="",
                            pmid_count=0,
                            error=f"Invalid format: {error_data['format']}",
                        )
                except json.JSONDecodeError:
                    pass  # Not an error response, continue

            logger.info(
                f"Exported {len(pmids)} citations in {format} format via official API"
            )

            return CitationResult(
                success=True,
                format=format,
                content=content,
                pmid_count=len(pmids),
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error from Citation API: {e}")
            return CitationResult(
                success=False,
                format=format,
                content="",
                pmid_count=len(pmids),
                error=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            )
        except httpx.RequestError as e:
            logger.error(f"Request error: {e}")
            return CitationResult(
                success=False,
                format=format,
                content="",
                pmid_count=len(pmids),
                error=f"Request failed: {str(e)}",
            )

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "NCBICitationExporter":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()


# Module-level singleton for convenience
_default_exporter: NCBICitationExporter | None = None


def get_exporter() -> NCBICitationExporter:
    """Get default citation exporter instance."""
    global _default_exporter
    if _default_exporter is None:
        _default_exporter = NCBICitationExporter()
    return _default_exporter


async def export_citations_official(
    pmids: list[str],
    format: CitationFormat = "ris",
) -> CitationResult:
    """
    Convenience function to export citations via official API.

    This is the recommended way to export citations.
    Falls back gracefully on failure.

    Args:
        pmids: List of PubMed IDs
        format: Export format (ris, medline, csl)

    Returns:
        CitationResult with formatted content

    Example:
        result = await export_citations_official(["37654670", "37654671"])
        if result.success:
            save_to_file(result.content, "references.ris")
    """
    return await get_exporter().export_citations(pmids, format)
