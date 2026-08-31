"""Focused regression tests for the staged fulltext helper modules.

Design:
    This file exercises discovery, fetch, and extract helpers directly so the
    phases can be validated independently of the downloader orchestrator in
    fulltext_download.py.

Maintenance:
    Keep these tests narrow and deterministic. Use mocks to pin phase
    boundaries and reserve end-to-end downloader behavior for the higher-level
    fulltext download test suite.
"""

from __future__ import annotations

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from pubmed_search.infrastructure.sources import fulltext_discovery as fulltext_discovery_module
from pubmed_search.infrastructure.sources.fulltext_discovery import FulltextDiscoveryPhase
from pubmed_search.infrastructure.sources.fulltext_extract import FulltextExtractPhase
from pubmed_search.infrastructure.sources.fulltext_fetch import FulltextFetchPhase
from pubmed_search.infrastructure.sources.fulltext_models import PDFSource


async def _public_resolver(_host: str, _port: int) -> tuple[str, ...]:
    return ("93.184.216.34",)


def _fetch_phase(client: httpx.AsyncClient) -> FulltextFetchPhase:
    return FulltextFetchPhase(
        client_getter=AsyncMock(return_value=client),
        execution_policy_factory=MagicMock(),
        transport_kernel=MagicMock(),
        max_pdf_size=1024 * 1024,
        chunk_size=8192,
        retryable_status_codes={429, 500, 502, 503, 504},
        max_concurrent=5,
        request_timeout=30.0,
        address_resolver=_public_resolver,
    )


@pytest.mark.asyncio
async def test_discovery_phase_returns_pmc_and_europe_pmc_links():
    phase = FulltextDiscoveryPhase(AsyncMock())

    links = await phase.get_pmc_links(None, "PMC7096777")

    assert [link.source for link in links] == [PDFSource.EUROPE_PMC, PDFSource.PMC]
    assert links[0].url.endswith("blobtype=pdf")


@pytest.mark.asyncio
async def test_discovery_phase_pmid_lookup_timeout_propagates_without_blocking(monkeypatch):
    phase = FulltextDiscoveryPhase(AsyncMock())

    def _slow_lookup(_pmid: str):
        time.sleep(0.05)
        return []

    monkeypatch.setattr(fulltext_discovery_module, "PMC_LINK_LOOKUP_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(fulltext_discovery_module, "_lookup_pmc_links_from_entrez", _slow_lookup)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(phase.get_pmc_links("12345678", None), timeout=0.1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "arguments"),
    [
        ("get_crossref_links", ("10.1000/test",)),
        ("get_pubmed_linkout", ("12345678",)),
        ("get_doaj_links", ("10.1000/test",)),
        ("get_zenodo_links", ("10.1000/test",)),
    ],
)
async def test_http_discovery_phase_accepts_only_explicit_absence(method_name, arguments):
    request = httpx.Request("GET", "https://provider.example/record")
    response = httpx.Response(404, request=request)
    client = AsyncMock()
    client.get.return_value = response
    phase = FulltextDiscoveryPhase(AsyncMock(return_value=client))

    links = await getattr(phase, method_name)(*arguments)

    assert links == []


@pytest.mark.asyncio
async def test_core_discovery_resolves_runtime_client_once(monkeypatch):
    client = AsyncMock()
    client.search.return_value = {"results": []}
    client_getter = MagicMock(return_value=client)
    monkeypatch.setattr("pubmed_search.infrastructure.sources.get_core_client", client_getter)
    phase = FulltextDiscoveryPhase(AsyncMock())

    links = await phase.get_core_links("10.1000/test")

    assert links == []
    client_getter.assert_called_once_with()
    client.search.assert_awaited_once_with('doi:"10.1000/test"', limit=1)


@pytest.mark.asyncio
async def test_discovery_propagates_sanitized_provider_failure(monkeypatch):
    from pubmed_search.infrastructure.sources.base_client import APIRequestError

    phase = FulltextDiscoveryPhase(AsyncMock())

    class _FailingSemanticScholarClient:
        async def get_paper(self, _identifier: str):
            raise APIRequestError("Semantic Scholar")

    monkeypatch.setattr(
        "pubmed_search.infrastructure.sources.get_semantic_scholar_client",
        _FailingSemanticScholarClient,
    )

    with pytest.raises(APIRequestError, match="Semantic Scholar request failed"):
        await phase.get_semantic_scholar_links("10.1000/test")


@pytest.mark.asyncio
async def test_fetch_phase_resolves_landing_page_pdf_link():
    landing_url = "https://resolver.example.edu/openurl?id=1"
    pdf_url = "https://resolver.example.edu/downloads/paper.pdf"
    landing_page = b"""
    <html>
        <head>
            <meta name=\"citation_pdf_url\" content=\"/downloads/paper.pdf\" />
        </head>
    </html>
    """
    pdf_bytes = b"%PDF-1.4 test content"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/downloads/paper.pdf":
            return httpx.Response(200, headers={"Content-Type": "application/pdf"}, content=pdf_bytes)
        return httpx.Response(200, headers={"Content-Type": "text/html"}, content=landing_page)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        result = await _fetch_phase(client).download_from_url_impl(landing_url, PDFSource.INSTITUTIONAL_RESOLVER)

    assert result.success is True
    assert result.is_pdf is True
    assert result.url == pdf_url


@pytest.mark.asyncio
async def test_fetch_phase_preserves_retryable_error_from_landing_page_pdf_candidate():
    landing_url = "https://resolver.example.edu/openurl?id=1"
    landing_page = b"""
    <html>
        <head>
            <meta name=\"citation_pdf_url\" content=\"/downloads/paper.pdf\" />
        </head>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/downloads/paper.pdf":
            return httpx.Response(
                503,
                headers={"Content-Type": "text/html", "Retry-After": "7"},
                content=b"temporarily unavailable",
            )
        return httpx.Response(200, headers={"Content-Type": "text/html"}, content=landing_page)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        result = await _fetch_phase(client).download_from_url_impl(landing_url, PDFSource.INSTITUTIONAL_RESOLVER)

    assert result.success is False
    assert result.error == "HTTP 503"
    assert result.retry_after == 7


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "private_url",
    [
        "http://127.0.0.1/internal.pdf",
        "http://169.254.169.254/latest/meta-data.pdf",
    ],
)
async def test_fetch_phase_rejects_initial_private_url_before_transport(private_url: str):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"%PDF-1.4 should never be read")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        result = await _fetch_phase(client).download_from_url_impl(private_url, PDFSource.OPENURL)

    assert result.success is False
    assert result.error and result.error.startswith("Unsafe outbound URL")
    assert requests == []


@pytest.mark.asyncio
async def test_fetch_phase_rejects_redirect_to_private_url_before_second_hop():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/internal.pdf"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        result = await _fetch_phase(client).download_from_url_impl("https://papers.example/start", PDFSource.OPENURL)

    assert result.success is False
    assert result.error and result.error.startswith("Unsafe outbound URL")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_fetch_phase_rejects_private_html_candidate_before_recursive_transport():
    requests: list[httpx.Request] = []
    landing_page = b"""
    <html><head>
      <meta name="citation_pdf_url" content="http://169.254.169.254/private.pdf" />
    </head></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, headers={"Content-Type": "text/html"}, content=landing_page)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        result = await _fetch_phase(client).download_from_url_impl("https://papers.example/article", PDFSource.OPENURL)

    assert result.success is False
    assert result.error and result.error.startswith("Unsafe outbound URL")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_extract_phase_structured_fulltext_uses_client_factory():
    mock_client = MagicMock()
    mock_client.get_fulltext_xml = AsyncMock(return_value="<article />")
    mock_client.parse_fulltext_xml.return_value = {
        "title": "Test Paper",
        "abstract": "Abstract body",
        "sections": [{"title": "Introduction", "content": "Intro body"}],
        "references": ["ref1"],
    }
    phase = FulltextExtractPhase(europe_pmc_client_factory=lambda: mock_client)

    result = await phase.get_structured_fulltext("PMC123")

    assert result is not None
    assert result["title"] == "Test Paper"
    assert result["sections"]["introduction"] == "Intro body"
    assert "ABSTRACT" in result["text"]


@pytest.mark.asyncio
async def test_extract_failure_log_does_not_expose_exception_details(caplog):
    mock_client = MagicMock()
    mock_client.get_fulltext_xml = AsyncMock(side_effect=RuntimeError("token=super-secret /srv/private/article.xml"))
    caplog.set_level(logging.DEBUG)

    result = await FulltextExtractPhase(lambda: mock_client).get_structured_fulltext("PMC123")

    assert result is None
    assert "RuntimeError" in caplog.text
    assert "super-secret" not in caplog.text
    assert "/srv/private" not in caplog.text
