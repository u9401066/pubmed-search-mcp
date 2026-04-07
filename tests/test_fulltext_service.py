"""Application-service regression tests for policy-driven fulltext retrieval.

Design:
    These tests verify how the application service selects sources, shapes
    results, and integrates figure or extended-source behavior without relying
    on live network calls.

Maintenance:
    Keep orchestration assertions here and leave downloader transport details
    to lower-level suites. When policy resolution changes, update these tests
    alongside the registry expectations.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from pubmed_search.infrastructure.sources.fulltext_download import FulltextResult, PDFLink, PDFSource
from pubmed_search.infrastructure.sources.fulltext_service import FulltextRequest, FulltextService


class _FigureStub:
    def __init__(self, payload: dict[str, str]):
        self._payload = payload

    def to_dict(self) -> dict[str, str]:
        return dict(self._payload)


class TestFulltextService:
    @pytest.mark.asyncio
    async def test_prefers_structured_europe_pmc_content(self):
        mock_europe_pmc = AsyncMock()
        mock_europe_pmc.get_fulltext_xml.return_value = "<xml/>"
        mock_europe_pmc.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "Structured Article",
                "sections": [{"title": "Introduction", "content": "Hello fulltext"}],
                "references": [{"title": "Ref1"}],
            }
        )

        service = FulltextService(
            europe_pmc_client_factory=lambda: mock_europe_pmc,
            unpaywall_client_factory=lambda: AsyncMock(),
            core_client_factory=lambda: AsyncMock(),
            downloader_factory=lambda: MagicMock(),
            figure_client_factory=None,
        )

        result = await service.retrieve(FulltextRequest(pmcid="PMC7096777"))

        assert result.policy_key == "structured_first"
        assert result.fulltext_source_name == "Europe PMC"
        assert "Hello fulltext" in (result.fulltext_content or "")
        assert result.pdf_links[0]["source"] == "PubMed Central"

    @pytest.mark.asyncio
    async def test_uses_extended_sources_for_pdf_text_and_links(self):
        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = {"is_oa": False}

        mock_core = AsyncMock()
        mock_core.search.return_value = {"results": []}

        mock_downloader = MagicMock()
        mock_downloader.get_fulltext = AsyncMock(
            return_value=FulltextResult(
                text_content="Institutional PDF text",
                pdf_links=[
                    PDFLink(
                        url="https://resolver.example.edu/openurl?id=1",
                        source=PDFSource.INSTITUTIONAL_RESOLVER,
                        access_type="subscription",
                        is_direct_pdf=False,
                    ),
                    PDFLink(
                        url="https://publisher.example.edu/paper.pdf",
                        source=PDFSource.INSTITUTIONAL_RESOLVER,
                        access_type="subscription",
                        is_direct_pdf=True,
                    ),
                ],
                source_used=PDFSource.INSTITUTIONAL_RESOLVER,
                content_type="pdf",
            )
        )
        mock_downloader.close = AsyncMock()

        service = FulltextService(
            europe_pmc_client_factory=lambda: AsyncMock(),
            unpaywall_client_factory=lambda: mock_unpaywall,
            core_client_factory=lambda: mock_core,
            downloader_factory=lambda: mock_downloader,
            figure_client_factory=None,
        )

        result = await service.retrieve(
            FulltextRequest(doi="10.1234/test", extended_sources=True),
        )

        mock_downloader.get_fulltext.assert_awaited_once_with(
            pmid=None,
            pmcid=None,
            doi="10.1234/test",
            strategy="extract_text",
        )
        assert result.fulltext_provenance == "derived"
        assert result.content_sections[0]["title"] == "Extracted PDF Text"
        assert any(link["url"] == "https://publisher.example.edu/paper.pdf" for link in result.pdf_links)

    @pytest.mark.asyncio
    async def test_loads_figures_when_requested(self):
        mock_europe_pmc = AsyncMock()
        mock_europe_pmc.get_fulltext_xml.return_value = "<xml/>"
        mock_europe_pmc.parse_fulltext_xml = MagicMock(
            return_value={
                "title": "PMC Article",
                "sections": [{"title": "Results", "content": "Result text"}],
            }
        )

        mock_figure_client = MagicMock()
        mock_figure_client.get_article_figures = AsyncMock(
            return_value=SimpleNamespace(
                figures=[
                    _FigureStub(
                        {
                            "label": "Figure 1",
                            "caption_title": "Test figure",
                            "image_url": "https://pmc.example/figure1.png",
                        }
                    )
                ]
            )
        )

        service = FulltextService(
            europe_pmc_client_factory=lambda: mock_europe_pmc,
            unpaywall_client_factory=lambda: AsyncMock(),
            core_client_factory=lambda: AsyncMock(),
            downloader_factory=lambda: MagicMock(),
            figure_client_factory=lambda: mock_figure_client,
        )

        result = await service.retrieve(
            FulltextRequest(pmcid="PMC7096777", include_figures=True),
        )

        assert result.figures[0]["label"] == "Figure 1"
        assert result.figures[0]["image_url"] == "https://pmc.example/figure1.png"