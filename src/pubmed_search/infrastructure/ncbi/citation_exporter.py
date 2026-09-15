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
- Local validation remains necessary when upstream behavior changes

Rate limits:
- Same as E-utilities (3/sec without key, 10/sec with key)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

import httpx
from typing_extensions import Self

from pubmed_search.domain.value_objects.article_identifiers import normalize_pmid
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


def _raise_for_retryable_status(response: httpx.Response) -> None:
    raise RetryableOperationError(
        f"HTTP {response.status_code}",
        retry_after=parse_retry_after(response.headers.get("Retry-After")),
        status_code=response.status_code,
    )


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
        # Each exporter owns one lazy pool. The surrounding SourceRuntime owns
        # and closes the exporter, so clients never cross server/event-loop
        # boundaries. Tests may still inject a client directly.
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Return this exporter's lazily-created HTTP client."""
        if self._client is None:
            self._client = create_async_http_client(
                timeout=60.0,
                headers={"User-Agent": "PubMedSearchMCP/1.0 (github.com/u9401066/pubmed-search-mcp)"},
                follow_redirects=True,
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30.0,
            )
        return self._client

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

        try:
            pmids = list(dict.fromkeys(normalize_pmid(pmid) for pmid in pmids))
        except ValueError:
            return CitationResult(False, format, "", 0, "Invalid PMID")
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
                try:
                    error_data = json.loads(content)
                    if "format" in error_data:
                        return CitationResult(
                            success=False,
                            format=format,
                            content="",
                            pmid_count=0,
                            error="Citation API rejected the requested format",
                        )
                except json.JSONDecodeError:
                    pass  # Not an error response, continue

            if format == "ris":
                starts = len(re.findall(r"^TY  - ", content, re.MULTILINE))
                count = len(re.findall(r"^ER  -[ \t]*$", content, re.MULTILINE))
                valid = count > 0 and count == starts
            elif format == "medline":
                count = len(re.findall(r"^PMID- [1-9][0-9]*[ \t]*$", content, re.MULTILINE))
                valid = count > 0
            else:
                try:
                    records = json.loads(content)
                except json.JSONDecodeError:
                    records = None
                valid = (
                    isinstance(records, list)
                    and bool(records)
                    and all(isinstance(row, dict) and row.get("type") for row in records)
                )
                count = len(records) if isinstance(records, list) else 0
            if not valid or count > len(pmids):
                return CitationResult(False, format, "", 0, "Citation API returned invalid citation records")
            logger.info("Exported %s citation records in %s format", count, format)

            return CitationResult(
                success=True,
                format=format,
                content=content,
                pmid_count=count,
            )

        except httpx.HTTPStatusError as exc:
            logger.warning("Citation API returned HTTP %s", exc.response.status_code)
            return CitationResult(
                success=False,
                format=format,
                content="",
                pmid_count=len(pmids),
                error=f"Citation API request failed with HTTP {exc.response.status_code}",
            )
        except httpx.RequestError as exc:
            logger.warning("Citation API request failed (%s)", type(exc).__name__)
            return CitationResult(
                success=False,
                format=format,
                content="",
                pmid_count=len(pmids),
                error="Citation API request failed",
            )
        except Exception as exc:
            logger.warning("Citation export failed (%s)", type(exc).__name__)
            return CitationResult(
                success=False,
                format=format,
                content="",
                pmid_count=len(pmids),
                error="Citation export failed",
            )

    async def close(self) -> None:
        """Close and forget this exporter's HTTP client."""
        client = self._client
        self._client = None
        if client is not None and not client.is_closed:
            await client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


def get_exporter() -> NCBICitationExporter:
    """Return the citation exporter owned by the active source runtime."""
    from pubmed_search.infrastructure.sources.runtime import get_source_runtime

    return get_source_runtime().get_or_create_client(
        ("ncbi_citation_exporter",),
        NCBICitationExporter,
    )
