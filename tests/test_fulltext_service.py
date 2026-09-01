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
from typing import Literal
from unittest.mock import AsyncMock, MagicMock

import pytest

from pubmed_search.application.fulltext import (
    FulltextRequest,
    FulltextService,
    FulltextServiceResult,
    FulltextSourceError,
)
from pubmed_search.domain.value_objects.article_identifiers import IdentifierValidationError
from pubmed_search.infrastructure.sources.fulltext_download import (
    FulltextResult,
    LinkDiscoverySourceError,
    PDFLink,
    PDFLinkDiscoveryResult,
    PDFSource,
)


class _FigureStub:
    def __init__(self, payload: dict[str, str]):
        self._payload = payload

    def to_dict(self) -> dict[str, str]:
        return dict(self._payload)


class TestFulltextService:
    def test_coverage_fields_reject_display_labels(self):
        result = FulltextServiceResult()

        with pytest.raises(ValueError, match="underscore keys"):
            result.record_source_attempted("Europe PMC")
        with pytest.raises(ValueError, match="underscore keys"):
            result.record_source_completed("Extended (15 sources)")
        with pytest.raises(ValueError, match="underscore keys"):
            FulltextSourceError(source="PMC Open Access / FigureClient")
        with pytest.raises(ValueError, match="underscore keys"):
            FulltextServiceResult(sources_tried=["Europe PMC"])
        with pytest.raises(ValueError, match="attempted before"):
            result.record_source_error("core")

    @pytest.mark.asyncio
    async def test_rejects_ambiguous_or_non_string_identifiers(self):
        service = FulltextService(
            europe_pmc_client_factory=lambda: AsyncMock(),
            unpaywall_client_factory=lambda: AsyncMock(),
            core_client_factory=lambda: AsyncMock(),
            downloader_factory=lambda: MagicMock(),
        )

        with pytest.raises(IdentifierValidationError, match="exactly one"):
            await service.retrieve(FulltextRequest(pmid="123", doi="10.1000/test"))
        with pytest.raises(IdentifierValidationError, match="strings"):
            await service.retrieve(FulltextRequest(pmid=123))  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_numeric_auto_identifier_is_always_pmid(self):
        mock_europe_pmc = AsyncMock()
        mock_europe_pmc.get_article.return_value = None
        service = FulltextService(
            europe_pmc_client_factory=lambda: mock_europe_pmc,
            unpaywall_client_factory=lambda: AsyncMock(),
            core_client_factory=lambda: AsyncMock(),
            downloader_factory=lambda: MagicMock(),
        )

        result = await service.retrieve(FulltextRequest(identifier="123456789012"))

        assert result.pmid == "123456789012"
        assert result.pmcid is None
        mock_europe_pmc.get_article.assert_awaited_once_with("MED", "123456789012", result_type="core")

    @pytest.mark.asyncio
    async def test_source_exception_is_reported_as_unavailable_without_details(self):
        mock_europe_pmc = AsyncMock()
        mock_europe_pmc.get_fulltext_xml.side_effect = RuntimeError("token=super-secret")
        messages: list[str] = []

        async def capture_log(_level: Literal["debug", "info", "warning", "error"], message: str) -> None:
            messages.append(message)

        service = FulltextService(
            europe_pmc_client_factory=lambda: mock_europe_pmc,
            unpaywall_client_factory=lambda: AsyncMock(),
            core_client_factory=lambda: AsyncMock(),
            downloader_factory=lambda: MagicMock(),
        )

        result = await service.retrieve(FulltextRequest(pmcid="PMC7096777"), log=capture_log)

        assert result.coverage_status == "unavailable"
        assert result.sources_tried == ["europe_pmc"]
        assert result.sources_completed == []
        assert [issue.to_dict() for issue in result.source_errors] == [
            {
                "source": "europe_pmc",
                "code": "source_unavailable",
                "message": "The upstream source was unavailable during this request.",
            }
        ]
        assert "super-secret" not in " ".join(messages)

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
        assert result.sources_tried == ["europe_pmc"]
        assert result.sources_completed == ["europe_pmc"]
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
                link_discovery=PDFLinkDiscoveryResult(
                    links=(
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
                    ),
                    attempted_sources=("institutional_resolver",),
                    completed_sources=("institutional_resolver",),
                ),
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
            allow_browser_session=None,
        )
        assert result.fulltext_provenance == "derived"
        assert result.content_sections[0]["title"] == "Extracted PDF Text"
        assert any(link["url"] == "https://publisher.example.edu/paper.pdf" for link in result.pdf_links)

    @pytest.mark.asyncio
    async def test_extended_source_failure_keeps_successful_link_as_partial_coverage(self):
        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = {"is_oa": False}
        mock_core = AsyncMock()
        mock_core.search.return_value = {"results": []}
        successful_link = PDFLink(
            url="https://repository.example/paper.pdf",
            source=PDFSource.PMC,
            access_type="open_access",
        )
        mock_downloader = MagicMock()
        mock_downloader.get_fulltext = AsyncMock(
            return_value=FulltextResult(
                link_discovery=PDFLinkDiscoveryResult(
                    links=(successful_link,),
                    attempted_sources=("pmc", "semantic_scholar"),
                    completed_sources=("pmc",),
                    source_errors=(
                        LinkDiscoverySourceError(
                            source="semantic_scholar",
                            kind="transport",
                            retryable=True,
                        ),
                    ),
                )
            )
        )
        mock_downloader.close = AsyncMock()
        service = FulltextService(
            europe_pmc_client_factory=lambda: AsyncMock(),
            unpaywall_client_factory=lambda: mock_unpaywall,
            core_client_factory=lambda: mock_core,
            downloader_factory=lambda: mock_downloader,
        )

        result = await service.retrieve(FulltextRequest(doi="10.1234/test", extended_sources=True))

        assert result.coverage_status == "partial"
        assert result.sources_tried == ["unpaywall", "core", "extended", "pmc", "semantic_scholar"]
        assert result.sources_completed == ["unpaywall", "core", "pmc", "extended"]
        assert any(link["url"] == successful_link.url for link in result.pdf_links)
        assert "pmc" in result.sources_completed
        assert [issue.source for issue in result.source_errors] == ["semantic_scholar"]

    @pytest.mark.asyncio
    async def test_preserves_raw_extended_text_for_artifacts(self):
        raw_text = "A" * 12050
        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = {"is_oa": False}
        mock_core = AsyncMock()
        mock_core.search.return_value = {"results": []}
        mock_downloader = MagicMock()
        mock_downloader.get_fulltext = AsyncMock(
            return_value=FulltextResult(
                text_content=raw_text,
                link_discovery=PDFLinkDiscoveryResult(
                    attempted_sources=("institutional_resolver",),
                    completed_sources=("institutional_resolver",),
                ),
                source_used=PDFSource.INSTITUTIONAL_RESOLVER,
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

        result = await service.retrieve(FulltextRequest(doi="10.1234/test", extended_sources=True))

        assert result.raw_fulltext_content == raw_text
        assert len(result.fulltext_content or "") < len(raw_text)
        assert "characters truncated" in (result.fulltext_content or "")

    @pytest.mark.asyncio
    async def test_resolves_pmid_to_doi_before_unpaywall_lookup(self):
        mock_europe_pmc = AsyncMock()
        mock_europe_pmc.get_article.return_value = {
            "pmid": "41817525",
            "doi": "10.1001/jamanetworkopen.2026.1515",
        }

        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = {
            "is_oa": True,
            "title": "JAMA OA Paper",
            "oa_status": "gold",
            "best_oa_location": {
                "url_for_pdf": "https://jamanetwork.com/articlepdf/example.pdf",
                "host_type": "publisher",
                "version": "publishedVersion",
            },
            "oa_locations": [],
        }
        mock_core = AsyncMock()
        mock_core.search.return_value = {"results": []}

        service = FulltextService(
            europe_pmc_client_factory=lambda: mock_europe_pmc,
            unpaywall_client_factory=lambda: mock_unpaywall,
            core_client_factory=lambda: mock_core,
            downloader_factory=lambda: MagicMock(),
            figure_client_factory=None,
        )

        result = await service.retrieve(FulltextRequest(pmid="41817525"))

        mock_europe_pmc.get_article.assert_awaited_once_with("MED", "41817525", result_type="core")
        mock_unpaywall.get_oa_status.assert_awaited_once_with("10.1001/jamanetworkopen.2026.1515")
        assert result.doi == "10.1001/jamanetworkopen.2026.1515"
        assert result.sources_tried == ["europe_pmc_metadata", "unpaywall", "core"]
        assert result.sources_completed == ["europe_pmc_metadata", "unpaywall", "core"]
        assert any(link["url"] == "https://jamanetwork.com/articlepdf/example.pdf" for link in result.pdf_links)

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
        assert result.sources_tried == ["europe_pmc", "pmc_figures"]
        assert result.sources_completed == ["europe_pmc", "pmc_figures"]

    @pytest.mark.asyncio
    async def test_institutional_collect_populates_fulltext(self):
        """When Unpaywall finds no OA, institutional client supplies fulltext."""
        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = {"is_oa": False}

        mock_core = AsyncMock()
        mock_core.search.return_value = {"results": []}

        mock_institutional = AsyncMock()
        mock_institutional.get_fulltext_by_doi.return_value = SimpleNamespace(
            success=True,
            text="Full publisher article body fetched via institutional access.",
            title="Institutional Paper",
            final_url="https://publisher.example/article/1",
            source_used="direct",
            content_class="fulltext_html",
            error=None,
        )

        service = FulltextService(
            europe_pmc_client_factory=lambda: AsyncMock(),
            unpaywall_client_factory=lambda: mock_unpaywall,
            core_client_factory=lambda: mock_core,
            downloader_factory=lambda: MagicMock(),
            figure_client_factory=None,
            institutional_client_factory=lambda: mock_institutional,
        )

        result = await service.retrieve(FulltextRequest(doi="10.1000/x"))

        assert "publisher article body" in (result.fulltext_content or "")
        assert result.fulltext_source_name == "Institutional (direct)"
        assert result.fulltext_provenance == "direct"
        assert any(link["url"] == "https://publisher.example/article/1" for link in result.pdf_links)
        # CORE should be skipped once institutional succeeds
        mock_core.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_institutional_skipped_when_factory_none(self):
        mock_unpaywall = AsyncMock()
        mock_unpaywall.get_oa_status.return_value = {"is_oa": False}
        mock_core = AsyncMock()
        mock_core.search.return_value = {"results": []}

        service = FulltextService(
            europe_pmc_client_factory=lambda: AsyncMock(),
            unpaywall_client_factory=lambda: mock_unpaywall,
            core_client_factory=lambda: mock_core,
            downloader_factory=lambda: MagicMock(),
            figure_client_factory=None,
            institutional_client_factory=None,
        )
        result = await service.retrieve(FulltextRequest(doi="10.1000/x"))
        # No exception and falls back to CORE attempt
        assert result.fulltext_content is None
        mock_core.search.assert_called_once()
