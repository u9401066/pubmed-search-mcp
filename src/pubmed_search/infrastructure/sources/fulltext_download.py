"""Staged infrastructure orchestration for fulltext retrieval.

Design:
    ``FulltextDownloader`` coordinates the discovery, fetch, and extract
    phases behind the current infrastructure contract. Source-specific link
    discovery and transport/parsing details remain owned by their phase
    objects instead of being re-exported as duplicate downloader methods.

Maintenance:
    Add phase behavior to the relevant phase module. Keep this class focused
    on ordering candidates, enforcing the end-to-end deadline, composing phase
    results, and managing its HTTP client lifecycle.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING, Any, Literal

from pubmed_search.shared.async_utils import RequestExecutionPolicy, create_async_http_client, get_transport_kernel
from pubmed_search.shared.source_contracts import (
    SourceAdapterCall,
    SourceAdapterError,
    SourceAdapterResult,
    SourceExecutionSettings,
    build_request_execution_policy,
    gather_source_adapter_calls,
)

from .fulltext_discovery import FulltextDiscoveryPhase
from .fulltext_extract import FulltextExtractPhase
from .fulltext_fetch import FulltextFetchPhase
from .fulltext_models import (
    AccessType,
    DownloadResult,
    FulltextResult,
    LinkDiscoverySourceError,
    PDFLink,
    PDFLinkDiscoveryResult,
    PDFSource,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import httpx

logger = logging.getLogger(__name__)


class FulltextDownloader:
    """Coordinate fulltext discovery, download, and extraction phases."""

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
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("Fulltext timeout must be finite and positive")
        if type(max_retries) is not int or max_retries < 0 or type(max_concurrent) is not int or max_concurrent < 1:
            raise ValueError("Fulltext retry and concurrency budgets must be valid integers")
        self._timeout = timeout
        self._max_retries = max_retries
        self._max_concurrent = max_concurrent
        self._client: httpx.AsyncClient | None = None
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
            request_timeout=self._timeout,
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

    def _derive_end_to_end_timeout(self) -> float:
        """Bound total downloader work so link retries cannot chain indefinitely."""
        return max(self._timeout, min(self._timeout * 2, self._timeout + 30.0))

    @staticmethod
    def _build_deadline(total_timeout: float | None) -> float | None:
        if total_timeout is None:
            return None
        if isinstance(total_timeout, bool) or not math.isfinite(total_timeout) or total_timeout <= 0:
            raise ValueError("Fulltext total_timeout must be finite and positive")
        return time.monotonic() + total_timeout

    @staticmethod
    def _remaining_budget(deadline: float | None) -> float | None:
        if deadline is None:
            return None
        return deadline - time.monotonic()

    def _budget_message(self, phase: str, total_timeout: float | None) -> str:
        if total_timeout is None:
            return f"Fulltext retrieval timed out during {phase}"
        return f"Fulltext retrieval exceeded total timeout of {total_timeout:.2f}s during {phase}"

    def _raise_if_budget_exhausted(
        self,
        *,
        deadline: float | None,
        total_timeout: float | None,
        phase: str,
    ) -> None:
        remaining = self._remaining_budget(deadline)
        if remaining is None or remaining > 0:
            return
        raise asyncio.TimeoutError(self._budget_message(phase, total_timeout))

    async def _await_with_deadline(
        self,
        operation: Callable[[], Awaitable[Any]],
        *,
        deadline: float | None,
        total_timeout: float | None,
        phase: str,
    ) -> Any:
        self._raise_if_budget_exhausted(deadline=deadline, total_timeout=total_timeout, phase=phase)

        remaining = self._remaining_budget(deadline)
        if remaining is None:
            return await operation()

        try:
            return await asyncio.wait_for(operation(), timeout=remaining)
        except asyncio.TimeoutError as exc:
            raise asyncio.TimeoutError(self._budget_message(phase, total_timeout)) from exc

    def _build_link_source_calls(
        self,
        pmid: str | None,
        pmcid: str | None,
        doi: str | None,
    ) -> list[SourceAdapterCall[PDFLink]]:
        calls: list[SourceAdapterCall[PDFLink]] = []

        if pmcid or pmid:
            calls.append(
                self._build_link_collection_call(
                    "pmc",
                    partial(self._discovery_phase.get_pmc_links, pmid, pmcid),
                )
            )

        if pmid:
            calls.append(
                self._build_link_collection_call(
                    "pubmed_linkout",
                    partial(self._discovery_phase.get_pubmed_linkout, pmid),
                )
            )

        if pmid or doi:
            calls.append(
                self._build_link_collection_call(
                    "institutional_resolver",
                    partial(self._discovery_phase.get_openurl_links, pmid, doi),
                )
            )

        if doi:
            calls.append(
                self._build_link_collection_call(
                    "doi_landing_page",
                    partial(self._discovery_phase.get_doi_redirect_link, doi),
                )
            )
            doi_handlers = [
                ("unpaywall", self._discovery_phase.get_unpaywall_links),
                ("crossref", self._discovery_phase.get_crossref_links),
                ("core", self._discovery_phase.get_core_links),
                ("semantic_scholar", self._discovery_phase.get_semantic_scholar_links),
                ("openalex", self._discovery_phase.get_openalex_links),
                ("doaj", self._discovery_phase.get_doaj_links),
                ("zenodo", self._discovery_phase.get_zenodo_links),
            ]
            for source_name, handler in doi_handlers:
                calls.append(
                    self._build_link_collection_call(
                        source_name,
                        partial(handler, doi),
                    )
                )

            if "arxiv" in doi.lower():
                calls.append(
                    self._build_optional_link_call(
                        "arxiv",
                        partial(self._discovery_phase.get_arxiv_link, doi),
                    )
                )

            if "10.1101/" in doi or "biorxiv" in doi.lower() or "medrxiv" in doi.lower():
                calls.append(
                    self._build_optional_link_call(
                        "preprints",
                        partial(self._discovery_phase.get_preprint_link, doi),
                    )
                )

        return calls

    @staticmethod
    def _build_link_collection_call(
        source: str,
        collect: Callable[[], Awaitable[list[PDFLink]]],
    ) -> SourceAdapterCall[PDFLink]:
        """Bind a list-returning discovery adapter to the strict result contract."""

        async def _execute() -> SourceAdapterResult[PDFLink]:
            links = await collect()
            return SourceAdapterResult(
                source=source,
                operation="collect_links",
                items=links,
                total_count=len(links),
                status="ok" if links else "empty",
            )

        return SourceAdapterCall(source=source, operation="collect_links", execute=_execute)

    @staticmethod
    def _build_optional_link_call(
        source: str,
        collect: Callable[[], Awaitable[PDFLink | None]],
    ) -> SourceAdapterCall[PDFLink]:
        """Bind a single optional discovery result to the strict result contract."""

        async def _execute() -> SourceAdapterResult[PDFLink]:
            link = await collect()
            links = [link] if link is not None else []
            return SourceAdapterResult(
                source=source,
                operation="collect_links",
                items=links,
                total_count=len(links),
                status="ok" if links else "empty",
            )

        return SourceAdapterCall(source=source, operation="collect_links", execute=_execute)

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
        *,
        total_timeout: float | None = None,
        deadline: float | None = None,
    ) -> PDFLinkDiscoveryResult:
        """Discover candidate links without hiding partial source failures."""
        effective_total_timeout = total_timeout if total_timeout is not None else self._derive_end_to_end_timeout()
        effective_deadline = deadline if deadline is not None else self._build_deadline(effective_total_timeout)
        per_call_timeout = max(5.0, min(self._timeout, 15.0))
        remaining = self._remaining_budget(effective_deadline)
        if remaining is not None:
            self._raise_if_budget_exhausted(
                deadline=effective_deadline,
                total_timeout=effective_total_timeout,
                phase="link discovery",
            )
            per_call_timeout = max(0.05, min(per_call_timeout, remaining))

        source_results = await self._await_with_deadline(
            lambda: gather_source_adapter_calls(
                self._build_link_source_calls(pmid, pmcid, doi),
                per_call_timeout=per_call_timeout,
            ),
            deadline=effective_deadline,
            total_timeout=effective_total_timeout,
            phase="link discovery",
        )
        return self._compose_link_discovery_result(source_results)

    def _compose_link_discovery_result(
        self,
        source_results: list[SourceAdapterResult[PDFLink]],
    ) -> PDFLinkDiscoveryResult:
        """Build one immutable, sanitized discovery envelope."""
        links = [link for source_result in source_results for link in source_result.items]
        seen_urls: set[str] = set()
        unique_links: list[PDFLink] = []
        for link in self._order_links_for_download(links):
            if link.url in seen_urls:
                continue
            seen_urls.add(link.url)
            unique_links.append(link)

        attempted_sources = tuple(dict.fromkeys(result.source for result in source_results))
        completed_sources = tuple(
            dict.fromkeys(result.source for result in source_results if result.status in {"ok", "empty", "partial"})
        )
        source_errors = tuple(
            self._sanitize_link_source_error(error)
            for source_result in source_results
            for error in source_result.errors
        )
        return PDFLinkDiscoveryResult(
            links=tuple(unique_links),
            attempted_sources=attempted_sources,
            completed_sources=completed_sources,
            source_errors=source_errors,
        )

    @staticmethod
    def _sanitize_link_source_error(error: SourceAdapterError) -> LinkDiscoverySourceError:
        """Remove raw provider messages while preserving actionable error type."""
        return LinkDiscoverySourceError(
            source=error.source,
            kind=error.kind,
            retryable=error.retryable,
            status_code=error.status_code,
        )

    async def download_pdf(
        self,
        pmid: str | None = None,
        pmcid: str | None = None,
        doi: str | None = None,
        preferred_source: PDFSource | None = None,
        try_all: bool = True,
        allow_browser_session: bool | None = None,
        discovery_result: PDFLinkDiscoveryResult | None = None,
        *,
        total_timeout: float | None = None,
        deadline: float | None = None,
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
        effective_total_timeout = total_timeout if total_timeout is not None else self._derive_end_to_end_timeout()
        effective_deadline = deadline if deadline is not None else self._build_deadline(effective_total_timeout)

        try:
            discovery = (
                discovery_result
                if discovery_result is not None
                else await self.get_pdf_links(
                    pmid,
                    pmcid,
                    doi,
                    total_timeout=effective_total_timeout,
                    deadline=effective_deadline,
                )
            )
        except asyncio.TimeoutError:
            return DownloadResult(
                success=False,
                error=self._budget_message("PDF link discovery", effective_total_timeout),
                link_discovery=discovery_result,
            )

        links = list(discovery.links)
        if not links:
            return DownloadResult(
                success=False,
                error="No PDF links were discovered for this article",
                link_discovery=discovery,
            )

        ordered_links = self._order_links_for_download(links, preferred_source=preferred_source)
        article_metadata = self._build_article_metadata(pmid=pmid, pmcid=pmcid, doi=doi)
        failed_sources: list[str] = []

        for link in ordered_links:
            try:
                self._raise_if_budget_exhausted(
                    deadline=effective_deadline,
                    total_timeout=effective_total_timeout,
                    phase="pdf candidate download",
                )
                result = await self._download_candidate(
                    link,
                    article_metadata=article_metadata,
                    allow_browser_session=allow_browser_session,
                    deadline=effective_deadline,
                    total_timeout=effective_total_timeout,
                )
            except asyncio.TimeoutError:
                return DownloadResult(
                    success=False,
                    error=self._budget_message("PDF candidate download", effective_total_timeout),
                    link_discovery=discovery,
                )

            if result.success and result.is_pdf:
                return replace(result, link_discovery=discovery)
            if not try_all:
                return self._sanitize_failed_download_result(result, discovery)

            failed_sources.append(link.source.source_id)
            logger.debug("PDF candidate retrieval failed source=%s", link.source.source_id)

        if failed_sources:
            source_keys = ", ".join(dict.fromkeys(failed_sources))
            return DownloadResult(
                success=False,
                error=f"All PDF candidates failed (sources: {source_keys})",
                link_discovery=discovery,
            )
        return DownloadResult(
            success=False,
            error="All PDF candidates failed",
            link_discovery=discovery,
        )

    @staticmethod
    def _sanitize_failed_download_result(
        result: DownloadResult,
        discovery: PDFLinkDiscoveryResult,
    ) -> DownloadResult:
        """Return a public failure without carrying transport error details."""
        return DownloadResult(
            success=False,
            source=result.source,
            error="PDF candidate retrieval failed",
            retry_after=result.retry_after,
            link_discovery=discovery,
        )

    async def get_fulltext(
        self,
        pmid: str | None = None,
        pmcid: str | None = None,
        doi: str | None = None,
        strategy: Literal["links_only", "download_best", "extract_text", "try_all"] = "extract_text",
        allow_browser_session: bool | None = None,
        *,
        total_timeout: float | None = None,
    ) -> FulltextResult:
        if strategy not in {"links_only", "download_best", "extract_text", "try_all"}:
            raise ValueError("Unsupported fulltext strategy")
        result = FulltextResult(pmid=pmid, pmcid=pmcid, doi=doi)
        effective_total_timeout = total_timeout if total_timeout is not None else self._derive_end_to_end_timeout()
        deadline = self._build_deadline(effective_total_timeout)

        try:
            if strategy == "links_only":
                result.link_discovery = await self.get_pdf_links(
                    pmid,
                    pmcid,
                    doi,
                    total_timeout=effective_total_timeout,
                    deadline=deadline,
                )
                return result

            if strategy == "try_all" and pmcid:
                xml_result = await self._await_with_deadline(
                    lambda: self._extract_phase.get_structured_fulltext(pmcid),
                    deadline=deadline,
                    total_timeout=effective_total_timeout,
                    phase="structured fulltext retrieval",
                )
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

            result.link_discovery = await self.get_pdf_links(
                pmid,
                pmcid,
                doi,
                total_timeout=effective_total_timeout,
                deadline=deadline,
            )
            if not result.link_discovery.links:
                result.content_type = "none"
                result.error = "No PDF links found for this article"
                return result

            if strategy == "download_best":
                download = await self.download_pdf(
                    pmid,
                    pmcid,
                    doi,
                    allow_browser_session=allow_browser_session,
                    discovery_result=result.link_discovery,
                    total_timeout=effective_total_timeout,
                    deadline=deadline,
                )
                if not download.success:
                    result.error = "PDF retrieval failed"
                    return result

                self._apply_download_result(result, download)
                return result

            article_metadata = self._build_article_metadata(pmid=pmid, pmcid=pmcid, doi=doi)
            best_pdf_download: DownloadResult | None = None
            failed_sources: list[str] = []

            for link in self._order_links_for_download(list(result.link_discovery.links)):
                self._raise_if_budget_exhausted(
                    deadline=deadline,
                    total_timeout=effective_total_timeout,
                    phase="pdf candidate download",
                )
                download = await self._download_candidate(
                    link,
                    article_metadata=article_metadata,
                    allow_browser_session=allow_browser_session,
                    deadline=deadline,
                    total_timeout=effective_total_timeout,
                )
                if not download.success or not download.is_pdf:
                    failed_sources.append(link.source.source_id)
                    logger.debug("Fulltext candidate retrieval failed source=%s", link.source.source_id)
                    continue

                if best_pdf_download is None:
                    best_pdf_download = download

                text = await self._await_with_deadline(
                    partial(self._extract_phase.extract_pdf_text, download.content),
                    deadline=deadline,
                    total_timeout=effective_total_timeout,
                    phase="pdf text extraction",
                )
                if text:
                    self._apply_download_result(result, download)
                    result.text_content = text
                    result.extraction_method = "pdf_extraction"
                    result.word_count = len(text.split())
                    return result

                failed_sources.append(link.source.source_id)
                logger.debug("PDF text extraction failed source=%s", link.source.source_id)

            if best_pdf_download is not None:
                self._apply_download_result(result, best_pdf_download)
                result.error = "PDF downloaded successfully, but text extraction failed across all candidate sources"
                return result

            if failed_sources:
                source_keys = ", ".join(dict.fromkeys(failed_sources))
                result.error = f"All fulltext candidates failed (sources: {source_keys})"
            else:
                result.error = "All fulltext candidates failed"
            return result
        except asyncio.TimeoutError:
            result.error = self._budget_message("fulltext retrieval", effective_total_timeout)
            return result

    async def _download_candidate(
        self,
        link: PDFLink,
        *,
        article_metadata: dict[str, Any],
        allow_browser_session: bool | None,
        deadline: float | None,
        total_timeout: float | None,
    ) -> DownloadResult:
        """Download a candidate link, with optional browser-session fallback."""
        browser_enabled = self._browser_session_allowed(allow_browser_session)
        request_headers = self._build_candidate_headers(link, article_metadata)

        if link.is_direct_pdf and link.access_type != "institutional":
            result = await self._await_with_deadline(
                lambda: self._fetch_phase.download_with_retry(link.url, link.source, headers=request_headers),
                deadline=deadline,
                total_timeout=total_timeout,
                phase=f"direct PDF download from {link.source.display_name}",
            )
            if result.success and result.is_pdf:
                return result

            if not browser_enabled or not self._should_try_browser_fallback(link, result):
                return result
        elif not link.is_direct_pdf:
            result = await self._await_with_deadline(
                lambda: self._fetch_phase.download_with_retry(link.url, link.source, headers=request_headers),
                deadline=deadline,
                total_timeout=total_timeout,
                phase=f"landing-page PDF resolution from {link.source.display_name}",
            )
            if result.success and result.is_pdf:
                return result
            if not browser_enabled:
                return result
        elif not browser_enabled:
            return DownloadResult(
                success=False,
                error="Institutional PDF fetch requires browser-session assist",
                url=link.url,
                source=link.source,
            )

        browser_result = await self._await_with_deadline(
            lambda: self._download_with_browser_session(link, article_metadata),
            deadline=deadline,
            total_timeout=total_timeout,
            phase=f"browser-session fallback for {link.source.display_name}",
        )
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

        discovery = result.link_discovery or PDFLinkDiscoveryResult()
        links = list(discovery.links)
        access_type: AccessType = "unknown"
        for index, link in enumerate(links):
            if link.url == download.url:
                links[index] = replace(link, is_direct_pdf=True)
                result.link_discovery = replace(discovery, links=tuple(links))
                return
            if link.source == download.source and access_type == "unknown":
                access_type = link.access_type

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

        if links and links[0].source == download.source and not links[0].is_direct_pdf:
            links[0] = direct_link
            result.link_discovery = replace(discovery, links=tuple(links))
            return

        links.insert(0, direct_link)
        result.link_discovery = replace(discovery, links=tuple(links))

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
                error="Browser-session PDF retrieval failed",
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


__all__ = [
    "AccessType",
    "DownloadResult",
    "FulltextDownloader",
    "FulltextResult",
    "LinkDiscoverySourceError",
    "PDFLink",
    "PDFLinkDiscoveryResult",
    "PDFSource",
]
