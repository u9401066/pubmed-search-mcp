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
from typing_extensions import Self

from pubmed_search.shared.async_utils import (
    RetryableOperationError,
    create_async_http_client,
    get_transport_kernel,
    parse_retry_after,
)

from .base import build_ncbi_execution_policy

logger = logging.getLogger(__name__)

# API endpoint (redirected from api.ncbi.nlm.nih.gov)
CITATION_API_BASE = "https://pmc.ncbi.nlm.nih.gov/api/ctxp/v1/pubmed/"

# Supported export formats
CitationFormat = Literal["ris", "medline", "csl"]
OFFICIAL_FORMATS: list[CitationFormat] = ["ris", "medline", "csl"]

# Module-level singleton HTTP client shared across all NCBICitationExporter instances.
# This converges on the same transport abstraction instead of each instance owning
# a separate connection pool.
_SHARED_CITATION_CLIENT: httpx.AsyncClient | None = None


def _raise_for_retryable_status(response: httpx.Response) -> None:
    raise RetryableOperationError(
        f"HTTP {response.status_code}",
        retry_after=parse_retry_after(response.headers.get("Retry-After")),
        status_code=response.status_code,
    )


def _get_citation_http_client() -> httpx.AsyncClient:
    """Return the lazily-created module-level citation HTTP client."""
    global _SHARED_CITATION_CLIENT
    if _SHARED_CITATION_CLIENT is None:
        _SHARED_CITATION_CLIENT = create_async_http_client(
            timeout=60.0,
            headers={"User-Agent": "PubMedSearchMCP/1.0 (github.com/u9401066/pubmed-search-mcp)"},
            follow_redirects=True,
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=30.0,
        )
    return _SHARED_CITATION_CLIENT


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

    def __init__(self, timeout: float = 30.0, api_key: str | None = None):
        """
        Initialize citation exporter.

        Args:
            timeout: Request timeout in seconds
            api_key: Optional NCBI API key used to tune shared transport rate limits
        """
        self.timeout = timeout
        self._api_key = api_key
        self._transport_kernel = get_transport_kernel()
        # Instance-level client override (primarily used for testing).
        # When None the module-level shared client is used automatically.
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Return the active HTTP client (instance override or shared singleton)."""
        return self._client if self._client is not None else _get_citation_http_client()

    def _build_execution_policy(self):
        """Build the shared transport policy for official citation export requests."""
        return build_ncbi_execution_policy(
            api_key=self._api_key,
            service_name="ncbi-citation-exporter",
            timeout=self.timeout,
        )

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
        policy = self._build_execution_policy()

        try:
            async def _perform_request() -> str:
                response = await self.client.get(CITATION_API_BASE, params=params)

                if response.status_code in policy.retry.retryable_status_codes:
                    _raise_for_retryable_status(response)

                response.raise_for_status()
                return response.text

            content = await self._transport_kernel.execute(_perform_request, policy=policy)

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

            logger.info(f"Exported {len(pmids)} citations in {format} format via official API")

            return CitationResult(
                success=True,
                format=format,
                content=content,
                pmid_count=len(pmids),
            )

        except httpx.HTTPStatusError as e:
            logger.exception(f"HTTP error from Citation API: {e}")
            return CitationResult(
                success=False,
                format=format,
                content="",
                pmid_count=len(pmids),
                error=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            )
        except httpx.RequestError as e:
            logger.exception(f"Request error: {e}")
            return CitationResult(
                success=False,
                format=format,
                content="",
                pmid_count=len(pmids),
                error=f"Request failed: {e!s}",
            )
        except Exception as e:
            logger.exception(f"Citation exporter request failed: {e}")
            return CitationResult(
                success=False,
                format=format,
                content="",
                pmid_count=len(pmids),
                error=f"Export failed: {e!s}",
            )

    async def close(self) -> None:
        """Close the instance-level HTTP client override if one was set.

        The module-level shared singleton is intentionally kept open across
        requests for connection reuse and is NOT closed here.
        """
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
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
