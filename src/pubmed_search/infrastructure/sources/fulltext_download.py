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
import re
from functools import partial
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.parse import urlparse

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
    BROWSERISH_USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
    )

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
        for link in self._order_links_for_download(links):
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
        allow_browser_session: bool | None = None,
        candidate_links: list[PDFLink] | None = None,
    ) -> DownloadResult:
        """
        Download PDF from best available source.

        Args:
            pmid: PubMed ID
            pmcid: PubMed Central ID
            doi: Digital Object Identifier
            preferred_source: Try this source first
            try_all: If preferred fails, try other sources

        Returns:
            DownloadResult with PDF bytes or error
        """
        # Get all available links
        links = list(candidate_links) if candidate_links is not None else await self.get_pdf_links(pmid, pmcid, doi)

        if not links:
            return DownloadResult(success=False, error="No PDF links found for this article")

        ordered_links = self._order_links_for_download(links, preferred_source=preferred_source)
        article_metadata = self._build_article_metadata(pmid=pmid, pmcid=pmcid, doi=doi)
        attempt_errors: list[str] = []

        for link in ordered_links:
            result = await self._download_candidate(
                link,
                article_metadata=article_metadata,
                allow_browser_session=allow_browser_session,
            )
            if result.success and result.is_pdf:
                return result
            if not try_all:
                return result

            if result.error:
                attempt_errors.append(f"{link.source.display_name}: {result.error}")
            logger.debug(f"Download failed from {link.source.display_name}: {result.error}")

        if attempt_errors:
            return DownloadResult(success=False, error=f"All sources failed. Attempts: {' | '.join(attempt_errors[:3])}")
        return DownloadResult(success=False, error="All sources failed without a recoverable error")

    async def get_fulltext(
        self,
        pmid: str | None = None,
        pmcid: str | None = None,
        doi: str | None = None,
        strategy: Literal["links_only", "download_best", "extract_text", "try_all"] = "extract_text",
        allow_browser_session: bool | None = None,
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
            result.error = "No PDF links found for this article"
            return result

        if strategy == "download_best":
            download = await self.download_pdf(
                pmid,
                pmcid,
                doi,
                allow_browser_session=allow_browser_session,
                candidate_links=result.pdf_links,
            )
            if not download.success:
                result.error = download.error
                return result

            self._apply_download_result(result, download)
            return result

        article_metadata = self._build_article_metadata(pmid=pmid, pmcid=pmcid, doi=doi)
        best_pdf_download: DownloadResult | None = None
        extraction_errors: list[str] = []

        for link in self._order_links_for_download(result.pdf_links):
            download = await self._download_candidate(
                link,
                article_metadata=article_metadata,
                allow_browser_session=allow_browser_session,
            )
            if not download.success or not download.is_pdf:
                if download.error:
                    extraction_errors.append(f"{link.source.display_name}: {download.error}")
                continue

            if best_pdf_download is None:
                best_pdf_download = download

            text = await self._extract_pdf_text(download.content)
            if text:
                self._apply_download_result(result, download)
                result.text_content = text
                result.extraction_method = "pdf_extraction"
                result.word_count = len(text.split())
                return result

            extraction_errors.append(f"{link.source.display_name}: PDF downloaded but text extraction failed")

        if best_pdf_download is not None:
            self._apply_download_result(result, best_pdf_download)
            result.error = "PDF downloaded successfully, but text extraction failed across all candidate sources"
            return result

        if extraction_errors:
            result.error = f"All fulltext candidates failed. Attempts: {' | '.join(extraction_errors[:3])}"
        else:
            result.error = "All fulltext candidates failed"
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

    async def _download_from_url(
        self,
        url: str,
        source: PDFSource,
        headers: dict[str, str] | None = None,
    ) -> DownloadResult:
        return await self._download_with_retry(url, source, headers=headers)
    async def _download_candidate(
        self,
        link: PDFLink,
        *,
        article_metadata: dict[str, Any],
        allow_browser_session: bool | None,
    ) -> DownloadResult:
        """Download a candidate link, with optional browser-session fallback."""
        browser_enabled = self._browser_session_allowed(allow_browser_session)
        request_headers = self._build_candidate_headers(link, article_metadata)

        if link.is_direct_pdf and link.access_type != "institutional":
            result = await self._download_from_url(link.url, link.source, headers=request_headers)
            if result.success and result.is_pdf:
                return result

            if not browser_enabled or not self._should_try_browser_fallback(link, result):
                return result
        elif not browser_enabled:
            return DownloadResult(
                success=False,
                error="Institutional/landing-page fetch requires browser-session assist",
                url=link.url,
                source=link.source,
            )

        browser_result = await self._download_with_browser_session(link, article_metadata)
        if browser_result.success and browser_result.is_pdf:
            return browser_result
        return browser_result

    def _build_article_metadata(
        self,
        *,
        pmid: str | None,
        pmcid: str | None,
        doi: str | None,
    ) -> dict[str, Any]:
        """Build the metadata payload passed to browser-assisted download flows."""
        return {
            "pmid": pmid,
            "pmcid": pmcid,
            "doi": doi,
        }

    def _build_candidate_headers(self, link: PDFLink, article_metadata: dict[str, Any]) -> dict[str, str]:
        """Build request headers tailored to a PDF candidate and publisher host."""
        headers: dict[str, str] = {}
        referer = self._infer_referer(link.url, article_metadata)
        if referer:
            headers["Referer"] = referer
        return headers

    def _build_download_headers(
        self,
        url: str,
        source: PDFSource,
        headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Merge caller headers with browser-like defaults for publisher PDF downloads."""
        req_headers = dict(headers or {})
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()

        req_headers.setdefault("User-Agent", self.USER_AGENT)

        if self._is_browserish_pdf_host(hostname, source, url):
            req_headers["User-Agent"] = self.BROWSERISH_USER_AGENT
            req_headers.setdefault("Accept", "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8")
            req_headers.setdefault("Accept-Language", "en-US,en;q=0.9")
            req_headers.setdefault("Sec-Fetch-Site", "same-origin")
            req_headers.setdefault("Sec-Fetch-Mode", "navigate")
            req_headers.setdefault("Sec-Fetch-Dest", "document")

        return req_headers

    def _is_browserish_pdf_host(self, hostname: str, source: PDFSource, url: str) -> bool:
        """Return True when a host is known to prefer browser-like PDF requests."""
        return any(
            [
                "jamanetwork.com" in hostname,
                source in {PDFSource.OPENALEX, PDFSource.CROSSREF, PDFSource.DOI_REDIRECT},
                self._looks_like_pdf_url(url),
            ]
        )

    def _looks_like_pdf_url(self, url: str) -> bool:
        """Return True when a URL strongly suggests a direct PDF endpoint."""
        lowered = url.lower()
        return lowered.endswith(".pdf") or "articlepdf" in lowered or "/pdf/" in lowered or "content/pdf/" in lowered

    def _infer_referer(self, url: str, article_metadata: dict[str, Any]) -> str | None:
        """Infer a plausible publisher landing page to use as Referer."""
        lowered = url.lower()
        if "jamanetwork.com" in lowered:
            match = re.search(r"/journals/([^/]+)/articlepdf/(\d+)/", lowered)
            if match:
                journal, article_id = match.groups()
                return f"https://jamanetwork.com/journals/{journal}/fullarticle/{article_id}"

        doi = str(article_metadata.get("doi") or "").strip()
        if doi:
            return f"https://doi.org/{doi}"

        return None

    def _order_links_for_download(
        self,
        links: list[PDFLink],
        preferred_source: PDFSource | None = None,
    ) -> list[PDFLink]:
        """Order links so direct, likely-open PDF candidates are tried before landing pages."""
        return sorted(
            links,
            key=lambda link: (
                0 if preferred_source and link.source == preferred_source else 1,
                0 if link.is_direct_pdf else 1,
                self._access_priority(link.access_type),
                link.source.priority,
                -link.confidence,
            ),
        )

    def _access_priority(self, access_type: str) -> int:
        """Rank access types for download ordering.

        Open-access links are tried before unknown links, which are tried before
        subscription/institutional landing pages.
        """
        if access_type in {"open_access", "gold", "green_oa", "bronze", "hybrid"}:
            return 0
        if access_type == "unknown":
            return 1
        if access_type == "subscription":
            return 2
        if access_type == "institutional":
            return 3
        return 4

    def _apply_download_result(self, result: FulltextResult, download: DownloadResult) -> None:
        """Copy downloaded PDF metadata into a fulltext result object."""
        result.pdf_bytes = download.content
        result.source_used = download.source
        result.content_type = "pdf"
        result.file_size = download.file_size
        result.resolved_pdf_url = download.url
        result.retrieved_url = download.url
        self._record_resolved_pdf_link(result, download)

    def _record_resolved_pdf_link(self, result: FulltextResult, download: DownloadResult) -> None:
        """Expose the final direct PDF URL in the result link list when available."""
        if not download.url or download.source is None:
            return

        access_type = "unknown"
        for link in result.pdf_links:
            if link.url == download.url:
                link.is_direct_pdf = True
                return
            if link.source == download.source:
                access_type = link.access_type
                break

        if access_type == "unknown" and download.source in {
            PDFSource.INSTITUTIONAL_RESOLVER,
            PDFSource.OPENURL,
            PDFSource.BROWSER_SESSION,
        }:
            access_type = "subscription"

        direct_link = PDFLink(
            url=download.url,
            source=download.source,
            access_type=access_type,
            is_direct_pdf=True,
        )

        if result.pdf_links and result.pdf_links[0].source == download.source and not result.pdf_links[0].is_direct_pdf:
            result.pdf_links[0] = direct_link
            return

        result.pdf_links.insert(0, direct_link)

    def _browser_session_allowed(self, allow_browser_session: bool | None) -> bool:
        """Return True when the caller and config both allow browser-session fallback."""
        from pubmed_search.infrastructure.sources.browser_session import get_browser_session_fetcher

        if allow_browser_session is False:
            return False

        fetcher = get_browser_session_fetcher()
        if allow_browser_session is True:
            return fetcher.is_enabled()
        return fetcher.is_auto_enabled()

    def _should_try_browser_fallback(self, link: PDFLink, result: DownloadResult) -> bool:
        """Decide whether a failed direct download should fall back to the browser broker."""
        if link.source == PDFSource.INSTITUTIONAL_RESOLVER or link.access_type == "institutional":
            return True

        error = (result.error or "").lower()
        return any(
            marker in error
            for marker in (
                "landing page",
                "http 401",
                "http 403",
                "http 302",
                "http 307",
                "timeout",
            )
        )

    async def _download_with_browser_session(
        self,
        link: PDFLink,
        article_metadata: dict[str, Any],
    ) -> DownloadResult:
        """Use the local broker to fetch a PDF inside a browser-authenticated session."""
        from pubmed_search.infrastructure.sources.browser_session import get_browser_session_fetcher

        fetcher = get_browser_session_fetcher()
        result = await fetcher.fetch_pdf(
            link.url,
            article=article_metadata,
            source_hint=link.source.display_name,
        )
        if not result.success:
            return DownloadResult(
                success=False,
                error=result.error,
                url=result.final_url or link.url,
                source=link.source,
            )

        return DownloadResult(
            success=True,
            content=result.content,
            content_type=result.content_type,
            source=PDFSource.BROWSER_SESSION,
            url=result.final_url or link.url,
            file_size=len(result.content or b""),
        )

    def _get_openurl_link(
        self,
        *,
        pmid: str | None,
        pmcid: str | None,
        doi: str | None,
    ) -> PDFLink | None:
        """Build an institutional resolver landing-page link when configured."""
        try:
            from pubmed_search.infrastructure.sources.openurl import get_openurl_link

            article = {
                "pmid": pmid,
                "pmc_id": pmcid,
                "doi": doi,
            }
            openurl = get_openurl_link(article)
            if not openurl:
                return None

            return PDFLink(
                url=openurl,
                source=PDFSource.INSTITUTIONAL_RESOLVER,
                access_type="institutional",
                is_direct_pdf=False,
                confidence=0.75,
            )
        except Exception as exc:
            logger.debug(f"OpenURL link generation failed: {exc}")
            return None

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
    allow_browser_session: bool | None = None,
) -> FulltextResult:
    downloader = get_fulltext_downloader()
    return await downloader.get_fulltext(
        pmid,
        pmcid,
        doi,
        strategy,
        allow_browser_session=allow_browser_session,
    )


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
