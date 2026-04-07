"""Fulltext fetch phase for HTTP retrieval and landing-page resolution.

Design:
    This module accepts discovered candidate URLs and is responsible for the
    network-facing part of retrieval: rate limiting, retry policy, stream
    handling, landing-page parsing, and PDF detection.

Maintenance:
    Keep transport and retry behavior centralized here so discovery modules do
    not grow HTTP concerns. HTML heuristics should remain conservative because
    they are shared by direct downloads and resolver landing pages.
"""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import httpx

from pubmed_search.shared.async_utils import (
    RequestExecutionPolicy,
    RetryableOperationError,
    get_rate_limiter,
    parse_retry_after,
)

from .fulltext_models import DownloadResult, PDFSource

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


def _normalize_candidate_url(base_url: str, candidate_url: str) -> str | None:
    raw_url = candidate_url.strip()
    if not raw_url or raw_url.startswith(("#", "javascript:", "mailto:")):
        return None
    return urljoin(base_url, raw_url)


def _has_explicit_pdf_signal(candidate_url: str) -> bool:
    normalized = candidate_url.lower()
    return any(signal in normalized for signal in (".pdf", "/pdf", "pdf=", "articlepdf", "full.pdf"))


def _looks_like_pdf_candidate(candidate_url: str, context: str = "") -> bool:
    normalized_context = context.lower()
    if _has_explicit_pdf_signal(candidate_url):
        return True
    return any(keyword in normalized_context for keyword in ("pdf", "download", "full text", "fulltext"))


class _LandingPageCandidateParser(HTMLParser):
    _META_PRIORITIES = {
        "citation_pdf_url": 0,
        "wkhealth_pdf_url": 0,
        "pdf_url": 1,
        "eprints.document_url": 1,
    }

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self._base_url = base_url
        self._candidates: list[tuple[int, str]] = []

    def _add_candidate(self, candidate_url: str, priority: int) -> None:
        normalized = _normalize_candidate_url(self._base_url, candidate_url)
        if normalized:
            self._candidates.append((priority, normalized))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {str(key).lower(): str(value) for key, value in attrs if key and value}

        if tag == "meta":
            name = (attributes.get("name") or attributes.get("property") or "").lower()
            content = attributes.get("content", "").strip()
            priority = self._META_PRIORITIES.get(name)
            if content and priority is not None:
                self._add_candidate(content, priority)
            return

        if tag not in {"a", "link"}:
            return

        href = attributes.get("href", "").strip()
        if not href:
            return

        context = " ".join(
            value
            for value in (
                attributes.get("title", ""),
                attributes.get("aria-label", ""),
                attributes.get("type", ""),
                attributes.get("rel", ""),
                attributes.get("class", ""),
            )
            if value
        )
        if _looks_like_pdf_candidate(href, context):
            priority = 1 if _has_explicit_pdf_signal(href) else 2
            self._add_candidate(href, priority)

    def get_candidates(self) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for _, candidate in sorted(self._candidates, key=lambda item: (item[0], item[1])):
            if candidate in seen:
                continue
            seen.add(candidate)
            ordered.append(candidate)
        return ordered


class FulltextFetchPhase:
    """Fetch phase for downloading PDF content or resolving landing pages."""

    def __init__(
        self,
        *,
        client_getter: Callable[[], Awaitable[httpx.AsyncClient]],
        execution_policy_factory: Callable[[], RequestExecutionPolicy],
        transport_kernel: Any,
        max_pdf_size: int,
        chunk_size: int,
        retryable_status_codes: set[int],
        max_concurrent: int,
    ) -> None:
        self._get_client = client_getter
        self._build_execution_policy = execution_policy_factory
        self._transport_kernel = transport_kernel
        self._max_pdf_size = max_pdf_size
        self._chunk_size = chunk_size
        self._retryable_status_codes = retryable_status_codes
        self._max_concurrent = max_concurrent

    @staticmethod
    def extract_status_code(error: str | None) -> int | None:
        if not error:
            return None
        match = re.search(r"\b(\d{3})\b", error)
        if not match:
            return None
        return int(match.group(1))

    async def wait_for_rate_limit(self) -> None:
        limiter = get_rate_limiter("fulltext-download", rate=max(float(self._max_concurrent), 1.0), per=1.0)
        await limiter.acquire()

    @staticmethod
    def looks_like_html(content_type: str, content: bytes) -> bool:
        preview = content[:2000].lower()
        return "html" in content_type.lower() or b"<html" in preview or b"<!doctype html" in preview

    def extract_pdf_candidates_from_html(self, base_url: str, html_text: str) -> list[str]:
        parser = _LandingPageCandidateParser(base_url)
        try:
            parser.feed(html_text)
        except Exception as exc:
            logger.debug("Landing page parse failed for %s: %s", base_url, exc)

        candidates = parser.get_candidates()
        regex_candidates = re.findall(r'["\']([^"\'#]+\.pdf(?:\?[^"\']*)?)["\']', html_text, flags=re.IGNORECASE)
        for candidate in regex_candidates:
            normalized = _normalize_candidate_url(base_url, candidate)
            if normalized and normalized not in candidates:
                candidates.append(normalized)
        return candidates[:5]

    async def download_with_retry(self, url: str, source: PDFSource, headers: dict | None = None) -> DownloadResult:
        policy = self._build_execution_policy()

        async def perform_download() -> DownloadResult:
            result = await self.download_from_url_impl(url, source, headers)
            if result.success:
                return result

            status_code = self.extract_status_code(result.error)
            if status_code in self._retryable_status_codes:
                raise RetryableOperationError(
                    result.error or f"HTTP {status_code}",
                    retry_after=result.retry_after,
                    status_code=status_code,
                )
            return result

        try:
            return await self._transport_kernel.execute(perform_download, policy=policy)
        except httpx.TimeoutException:
            return DownloadResult(success=False, error="Max retries exceeded: Download timeout", url=url, source=source)
        except Exception as exc:
            return DownloadResult(success=False, error=f"Max retries exceeded: {exc}", url=url, source=source)

    async def download_from_url_impl(
        self,
        url: str,
        source: PDFSource,
        headers: dict | None = None,
        depth: int = 0,
        visited: frozenset[str] | None = None,
    ) -> DownloadResult:
        try:
            visited_urls = set(visited or ())
            if url in visited_urls:
                return DownloadResult(success=False, error="Landing-page resolution loop detected", url=url, source=source)

            visited_urls.add(url)
            client = await self._get_client()
            req_headers = dict(headers or {})
            if "ncbi.nlm.nih.gov" in url:
                req_headers["Accept"] = "application/pdf"

            async with client.stream("GET", url, headers=req_headers) as response:
                if response.status_code != 200:
                    return DownloadResult(
                        success=False,
                        error=f"HTTP {response.status_code}",
                        url=url,
                        source=source,
                        retry_after=parse_retry_after(response.headers.get("Retry-After")),
                    )

                content_type = response.headers.get("Content-Type", "")
                content_length = response.headers.get("Content-Length")
                if content_length:
                    size = int(content_length)
                    if size > self._max_pdf_size:
                        return DownloadResult(
                            success=False,
                            error=f"PDF too large ({size / 1024 / 1024:.1f}MB)",
                            url=url,
                            source=source,
                        )

                chunks: list[bytes] = []
                total_size = 0
                async for chunk in response.aiter_bytes(self._chunk_size):
                    total_size += len(chunk)
                    if total_size > self._max_pdf_size:
                        return DownloadResult(
                            success=False,
                            error=f"PDF too large (>{self._max_pdf_size / 1024 / 1024:.0f}MB)",
                            url=url,
                            source=source,
                        )
                    chunks.append(chunk)

                content = b"".join(chunks)
                if content[:4] == b"%PDF":
                    return DownloadResult(
                        success=True,
                        content=content,
                        content_type=content_type,
                        source=source,
                        url=url,
                        file_size=len(content),
                    )

                if self.looks_like_html(content_type, content):
                    if depth >= 2:
                        return DownloadResult(
                            success=False,
                            error="Received HTML instead of PDF after resolver fallback",
                            url=url,
                            source=source,
                            content_type="text/html",
                        )

                    html_text = content[:500000].decode("utf-8", errors="ignore")
                    candidate_urls = self.extract_pdf_candidates_from_html(url, html_text)
                    for candidate_url in candidate_urls:
                        if candidate_url in visited_urls:
                            continue
                        candidate_result = await self.download_from_url_impl(
                            candidate_url,
                            source,
                            headers=headers,
                            depth=depth + 1,
                            visited=frozenset(visited_urls),
                        )
                        if candidate_result.success and candidate_result.is_pdf:
                            return candidate_result

                    return DownloadResult(
                        success=False,
                        error="Received HTML instead of PDF (landing page with no direct PDF link)",
                        url=url,
                        source=source,
                        content_type="text/html",
                    )

                return DownloadResult(
                    success=False,
                    error=f"Received non-PDF content ({content_type or 'unknown'})",
                    url=url,
                    source=source,
                    content_type=content_type or None,
                )
        except httpx.TimeoutException:
            return DownloadResult(success=False, error="Download timeout", url=url, source=source)
        except Exception as exc:
            return DownloadResult(success=False, error=str(exc), url=url, source=source)


__all__ = ["FulltextFetchPhase"]
