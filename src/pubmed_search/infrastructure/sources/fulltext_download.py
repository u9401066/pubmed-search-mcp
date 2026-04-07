"""Fulltext download facade over explicit discovery, fetch, and extract phases.

Design:
    This facade preserves the historical downloader API while delegating the
    actual work to dedicated discovery, fetch, and extract helpers. It is the
    compatibility boundary between older callers and the refactored staged
    pipeline.

Maintenance:
    Keep legacy wrapper methods stable because tests and downstream code may
    patch them directly. New behavior should usually land in the phase modules,
    with this facade only synchronizing bindings and composing results.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import TYPE_CHECKING, Literal, cast

from pubmed_search.shared.async_utils import RequestExecutionPolicy, create_async_http_client, get_transport_kernel
from pubmed_search.shared.source_contracts import (
    SourceAdapterCall,
    SourceExecutionSettings,
    build_request_execution_policy,
    gather_source_adapter_calls,
)

from .fulltext_discovery import FulltextDiscoveryPhase
from .fulltext_extract import FulltextExtractPhase
from .fulltext_fetch import FulltextFetchPhase
from .fulltext_models import AccessType, DownloadResult, FulltextResult, PDFLink, PDFSource

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)


class FulltextDownloader:
    """Backward-compatible downloader facade that delegates to phase helpers."""

    DEFAULT_TIMEOUT = 30.0
    MAX_PDF_SIZE = 50 * 1024 * 1024
    CHUNK_SIZE = 8192
    MAX_CONCURRENT_REQUESTS = 5
    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 1.0
    RETRY_MAX_DELAY = 30.0
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
    USER_AGENT = "Mozilla/5.0 (compatible; PubMed-Search-MCP/1.0; mailto:research@example.com)"

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        max_concurrent: int = MAX_CONCURRENT_REQUESTS,
    ):
        self._timeout = timeout
        self._max_retries = max_retries
        self._max_concurrent = max_concurrent
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._rate_limit_until: float = 0
        self._transport_kernel = get_transport_kernel()
        self._discovery_phase = FulltextDiscoveryPhase(self._get_client)
        self._fetch_phase = FulltextFetchPhase(
            client_getter=self._get_client,
            execution_policy_factory=self._build_execution_policy,
            transport_kernel=self._transport_kernel,
            max_pdf_size=self.MAX_PDF_SIZE,
            chunk_size=self.CHUNK_SIZE,
            retryable_status_codes=self.RETRYABLE_STATUS_CODES,
            max_concurrent=self._max_concurrent,
        )
        self._extract_phase = FulltextExtractPhase()

    def _build_execution_policy(self) -> RequestExecutionPolicy:
        return build_request_execution_policy(
            SourceExecutionSettings(
                service_name="fulltext-download",
                timeout=self._timeout,
                max_attempts=self._max_retries + 1,
                base_delay=self.RETRY_BASE_DELAY,
                max_delay=self.RETRY_MAX_DELAY,
                min_interval=1.0 / max(float(self._max_concurrent), 1.0),
                rate_limit_name="fulltext-download",
                circuit_breaker_name="fulltext-download",
                failure_threshold=6,
                recovery_timeout=60.0,
                half_open_max_calls=2,
                concurrency_limit=self._max_concurrent,
                concurrency_name="fulltext-download",
            )
        )

    def _sync_phase_bindings(self) -> None:
        self._discovery_phase._get_client = self._get_client
        self._fetch_phase._get_client = self._get_client
        self._fetch_phase._build_execution_policy = self._build_execution_policy

    def _build_link_source_calls(
        self,
        pmid: str | None,
        pmcid: str | None,
        doi: str | None,
    ) -> list[SourceAdapterCall[PDFLink]]:
        calls: list[SourceAdapterCall[PDFLink]] = []

        if pmcid or pmid:
            calls.append(
                SourceAdapterCall(
                    source="pmc",
                    operation="collect_links",
                    execute=partial(self._get_pmc_links, pmid, pmcid),
                )
            )

        if pmid:
            calls.append(
                SourceAdapterCall(
                    source="pubmed-linkout",
                    operation="collect_links",
                    execute=partial(self._get_pubmed_linkout, pmid),
                )
            )

        if pmid or doi:
            calls.append(
                SourceAdapterCall(
                    source="institutional-resolver",
                    operation="collect_links",
                    execute=partial(self._get_openurl_links, pmid, doi),
                )
            )

        if doi:
            calls.append(
                SourceAdapterCall(
                    source="doi-landing-page",
                    operation="collect_links",
                    execute=partial(self._get_doi_redirect_link, doi),
                )
            )
            doi_handlers = [
                ("unpaywall", self._get_unpaywall_links),
                ("crossref", self._get_crossref_links),
                ("core", self._get_core_links),
                ("semantic-scholar", self._get_semantic_scholar_links),
                ("openalex", self._get_openalex_links),
                ("doaj", self._get_doaj_links),
                ("zenodo", self._get_zenodo_links),
            ]
            for source_name, handler in doi_handlers:
                calls.append(
                    SourceAdapterCall(
                        source=source_name,
                        operation="collect_links",
                        execute=partial(handler, doi),
                    )
                )

            if "arxiv" in doi.lower():
                calls.append(
                    SourceAdapterCall(
                        source="arxiv",
                        operation="collect_links",
                        execute=partial(self._get_arxiv_link, doi),
                    )
                )

            if "10.1101/" in doi or "biorxiv" in doi.lower() or "medrxiv" in doi.lower():
                calls.append(
                    SourceAdapterCall(
                        source="preprints",
                        operation="collect_links",
                        execute=partial(self._get_preprint_link, doi),
                    )
                )

        return calls

    @staticmethod
    def _extract_status_code(error: str | None) -> int | None:
        return FulltextFetchPhase.extract_status_code(error)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = create_async_http_client(
                timeout=self._timeout,
                headers={"User-Agent": self.USER_AGENT},
                follow_redirects=True,
                max_connections=10,
                max_keepalive_connections=10,
                keepalive_expiry=30.0,
            )
        if self._client is None:
            msg = "HTTP client initialization failed"
            raise RuntimeError(msg)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def get_pdf_links(
        self,
        pmid: str | None = None,
        pmcid: str | None = None,
        doi: str | None = None,
    ) -> list[PDFLink]:
        self._sync_phase_bindings()
        links: list[PDFLink] = []
        source_results = await gather_source_adapter_calls(self._build_link_source_calls(pmid, pmcid, doi))
        for source_result in source_results:
            links.extend(source_result.items)

        seen_urls: set[str] = set()
        unique_links: list[PDFLink] = []
        for link in sorted(links):
            if link.url in seen_urls:
                continue
            seen_urls.add(link.url)
            unique_links.append(link)
        return unique_links

    async def download_pdf(
        self,
        pmid: str | None = None,
        pmcid: str | None = None,
        doi: str | None = None,
        preferred_source: PDFSource | None = None,
        try_all: bool = True,
    ) -> DownloadResult:
        links = await self.get_pdf_links(pmid, pmcid, doi)
        if not links:
            return DownloadResult(success=False, error="No PDF links found for this article")

        if preferred_source:
            links = sorted(
                links,
                key=lambda link: (0 if link.source == preferred_source else 1, link.source.priority),
            )

        last_error = None
        for link in links:
            result = await self._download_from_url(link.url, link.source)
            if result.success and result.is_pdf:
                return result
            if not try_all:
                return result
            last_error = result.error
            logger.debug("Download failed from %s: %s", link.source.display_name, result.error)

        return DownloadResult(success=False, error=f"All sources failed. Last error: {last_error}")

    async def get_fulltext(
        self,
        pmid: str | None = None,
        pmcid: str | None = None,
        doi: str | None = None,
        strategy: Literal["links_only", "download_best", "extract_text", "try_all"] = "extract_text",
    ) -> FulltextResult:
        result = FulltextResult(pmid=pmid, pmcid=pmcid, doi=doi)

        if strategy == "links_only":
            result.pdf_links = await self.get_pdf_links(pmid, pmcid, doi)
            return result

        if strategy == "try_all" and pmcid:
            xml_result = await self._get_structured_fulltext(pmcid)
            if xml_result:
                result.text_content = xml_result.get("text")
                result.structured_sections = xml_result.get("sections")
                result.content_type = "xml"
                result.source_used = PDFSource.EUROPE_PMC
                result.title = xml_result.get("title")
                result.has_references = bool(xml_result.get("references"))
                if result.text_content:
                    result.word_count = len(result.text_content.split())
                return result

        result.pdf_links = await self.get_pdf_links(pmid, pmcid, doi)
        if not result.pdf_links:
            result.content_type = "none"
            return result

        download = await self.download_pdf(pmid, pmcid, doi)
        if not download.success:
            return result

        result.pdf_bytes = download.content
        result.resolved_pdf_url = download.url
        result.source_used = download.source
        result.content_type = "pdf"
        result.file_size = download.file_size

        if download.source and download.url and all(link.url != download.url for link in result.pdf_links):
            resolved_access_type = cast(
                "AccessType",
                next(
                    (link.access_type for link in result.pdf_links if link.source == download.source),
                    "unknown",
                ),
            )
            result.pdf_links.insert(
                0,
                PDFLink(
                    url=download.url,
                    source=download.source,
                    access_type=resolved_access_type,
                    is_direct_pdf=True,
                    confidence=1.0,
                ),
            )

        if strategy in ("extract_text", "try_all"):
            text = await self._extract_pdf_text(download.content)
            if text:
                result.text_content = text
                result.extraction_method = "pdf_extraction"
                result.word_count = len(text.split())

        return result

    async def _get_pmc_links(self, pmid: str | None, pmcid: str | None) -> list[PDFLink]:
        self._sync_phase_bindings()
        return await self._discovery_phase.get_pmc_links(pmid, pmcid)

    async def _get_unpaywall_links(self, doi: str) -> list[PDFLink]:
        self._sync_phase_bindings()
        return await self._discovery_phase.get_unpaywall_links(doi)

    async def _get_core_links(self, doi: str) -> list[PDFLink]:
        self._sync_phase_bindings()
        return await self._discovery_phase.get_core_links(doi)

    async def _get_semantic_scholar_links(self, doi: str) -> list[PDFLink]:
        self._sync_phase_bindings()
        return await self._discovery_phase.get_semantic_scholar_links(doi)

    async def _get_openalex_links(self, doi: str) -> list[PDFLink]:
        self._sync_phase_bindings()
        return await self._discovery_phase.get_openalex_links(doi)

    async def _get_openurl_links(self, pmid: str | None, doi: str | None) -> list[PDFLink]:
        self._sync_phase_bindings()
        return await self._discovery_phase.get_openurl_links(pmid, doi)

    async def _get_doi_redirect_link(self, doi: str) -> list[PDFLink]:
        self._sync_phase_bindings()
        return await self._discovery_phase.get_doi_redirect_link(doi)

    async def _get_arxiv_link(self, doi: str) -> PDFLink | None:
        self._sync_phase_bindings()
        return await self._discovery_phase.get_arxiv_link(doi)

    async def _get_preprint_link(self, doi: str) -> PDFLink | None:
        self._sync_phase_bindings()
        return await self._discovery_phase.get_preprint_link(doi)

    async def _get_crossref_links(self, doi: str) -> list[PDFLink]:
        self._sync_phase_bindings()
        return await self._discovery_phase.get_crossref_links(doi)

    async def _get_pubmed_linkout(self, pmid: str) -> list[PDFLink]:
        self._sync_phase_bindings()
        return await self._discovery_phase.get_pubmed_linkout(pmid)

    async def _get_doaj_links(self, doi: str) -> list[PDFLink]:
        self._sync_phase_bindings()
        return await self._discovery_phase.get_doaj_links(doi)

    async def _get_zenodo_links(self, doi: str) -> list[PDFLink]:
        self._sync_phase_bindings()
        return await self._discovery_phase.get_zenodo_links(doi)

    async def _wait_for_rate_limit(self):
        self._sync_phase_bindings()
        await self._fetch_phase.wait_for_rate_limit()

    @staticmethod
    def _looks_like_html(content_type: str, content: bytes) -> bool:
        return FulltextFetchPhase.looks_like_html(content_type, content)

    def _extract_pdf_candidates_from_html(self, base_url: str, html_text: str) -> list[str]:
        self._sync_phase_bindings()
        return self._fetch_phase.extract_pdf_candidates_from_html(base_url, html_text)

    async def _download_with_retry(
        self,
        url: str,
        source: PDFSource,
        headers: dict | None = None,
    ) -> DownloadResult:
        self._sync_phase_bindings()
        return await self._fetch_phase.download_with_retry(url, source, headers)

    async def _download_from_url_impl(
        self,
        url: str,
        source: PDFSource,
        headers: dict | None = None,
        depth: int = 0,
        visited: frozenset[str] | None = None,
    ) -> DownloadResult:
        self._sync_phase_bindings()
        return await self._fetch_phase.download_from_url_impl(url, source, headers, depth, visited)

    async def _download_from_url(self, url: str, source: PDFSource) -> DownloadResult:
        return await self._download_with_retry(url, source)

    async def _extract_pdf_text(self, pdf_bytes: bytes | None) -> str | None:
        return await self._extract_phase.extract_pdf_text(pdf_bytes)

    async def _get_structured_fulltext(self, pmcid: str) -> dict | None:
        return await self._extract_phase.get_structured_fulltext(pmcid)


_downloader_instance: FulltextDownloader | None = None


def get_fulltext_downloader() -> FulltextDownloader:
    global _downloader_instance
    if _downloader_instance is None:
        _downloader_instance = FulltextDownloader()
    return _downloader_instance


async def download_fulltext(
    pmid: str | None = None,
    pmcid: str | None = None,
    doi: str | None = None,
    strategy: Literal["links_only", "download_best", "extract_text", "try_all"] = "extract_text",
) -> FulltextResult:
    downloader = get_fulltext_downloader()
    return await downloader.get_fulltext(pmid, pmcid, doi, strategy)


__all__ = [
    "AccessType",
    "DownloadResult",
    "FulltextDownloader",
    "FulltextResult",
    "PDFLink",
    "PDFSource",
    "download_fulltext",
    "get_fulltext_downloader",
]
