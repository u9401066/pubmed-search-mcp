"""Focused regression tests for the staged fulltext helper modules.

Design:
    This file exercises discovery, fetch, and extract helpers directly so the
    refactored phases can be validated independently of the compatibility
    facade in fulltext_download.py.

Maintenance:
    Keep these tests narrow and deterministic. Use mocks to pin phase
    boundaries and reserve end-to-end downloader behavior for the higher-level
    fulltext download test suite.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from pubmed_search.infrastructure.sources import fulltext_discovery as fulltext_discovery_module
from pubmed_search.infrastructure.sources.fulltext_discovery import FulltextDiscoveryPhase
from pubmed_search.infrastructure.sources.fulltext_extract import FulltextExtractPhase
from pubmed_search.infrastructure.sources.fulltext_fetch import FulltextFetchPhase
from pubmed_search.infrastructure.sources.fulltext_models import PDFSource


class _MockStreamResponse:
    def __init__(
        self, *, status_code: int = 200, headers: dict[str, str] | None = None, chunks: list[bytes] | None = None
    ):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_bytes(self, _chunk_size: int):
        for chunk in self._chunks:
            yield chunk


class _MockAsyncClient:
    def __init__(self, responses: dict[str, _MockStreamResponse]):
        self._responses = responses

    def stream(self, _method: str, url: str, headers: dict | None = None):
        del headers
        return self._responses[url]


@pytest.mark.asyncio
async def test_discovery_phase_returns_pmc_and_europe_pmc_links():
    phase = FulltextDiscoveryPhase(AsyncMock())

    links = await phase.get_pmc_links(None, "PMC7096777")

    assert [link.source for link in links] == [PDFSource.EUROPE_PMC, PDFSource.PMC]
    assert links[0].url.endswith("blobtype=pdf")


@pytest.mark.asyncio
async def test_discovery_phase_pmid_lookup_timeout_does_not_block(monkeypatch):
    phase = FulltextDiscoveryPhase(AsyncMock())

    def _slow_lookup(_pmid: str):
        time.sleep(0.05)
        return []

    monkeypatch.setattr(fulltext_discovery_module, "PMC_LINK_LOOKUP_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(fulltext_discovery_module, "_lookup_pmc_links_from_entrez", _slow_lookup)

    links = await asyncio.wait_for(phase.get_pmc_links("12345678", None), timeout=0.1)
    assert links == []


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
    client = _MockAsyncClient(
        {
            landing_url: _MockStreamResponse(headers={"Content-Type": "text/html"}, chunks=[landing_page]),
            pdf_url: _MockStreamResponse(headers={"Content-Type": "application/pdf"}, chunks=[pdf_bytes]),
        }
    )
    phase = FulltextFetchPhase(
        client_getter=AsyncMock(return_value=client),
        execution_policy_factory=MagicMock(),
        transport_kernel=MagicMock(),
        max_pdf_size=1024 * 1024,
        chunk_size=8192,
        retryable_status_codes={429, 500, 502, 503, 504},
        max_concurrent=5,
    )

    result = await phase.download_from_url_impl(landing_url, PDFSource.INSTITUTIONAL_RESOLVER)

    assert result.success is True
    assert result.is_pdf is True
    assert result.url == pdf_url


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
