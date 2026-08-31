"""Downloader-level regression tests for staged fulltext orchestration.

Design:
    These tests exercise ``FulltextDownloader`` orchestration while phase-level
    discovery, fetch, and extraction contracts are tested through their owning
    phase objects.

Maintenance:
    Keep facade behavior covered here and reserve direct phase assertions for
    test_fulltext_phases.py. Do not add downloader pass-through methods solely
    to create patch points; patch the owning phase instead.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, NoReturn
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from pubmed_search.infrastructure.sources.fulltext_download import (
    DownloadResult,
    FulltextDownloader,
    FulltextResult,
    LinkDiscoverySourceError,
    PDFLink,
    PDFLinkDiscoveryResult,
    PDFSource,
)
from pubmed_search.shared.source_contracts import SourceAdapterError, SourceAdapterResult

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from contextlib import AbstractContextManager


@pytest.fixture
def fail_closed_network_probe() -> Callable[[], AbstractContextManager[list[str]]]:
    """Build a guard that rejects and records DNS/socket use after the event loop starts."""

    @contextmanager
    def guard() -> Iterator[list[str]]:
        attempts: list[str] = []

        def reject_dns(host: object, *args: object, **kwargs: object) -> NoReturn:
            del args, kwargs
            attempts.append(f"dns:{host}")
            raise AssertionError(f"Unit test attempted DNS resolution for {host!r}")

        def reject_socket(_sock: socket.socket, address: object) -> NoReturn:
            attempts.append(f"socket:{address}")
            raise AssertionError(f"Unit test attempted a socket connection to {address!r}")

        with (
            patch.object(socket, "getaddrinfo", new=reject_dns),
            patch.object(socket.socket, "connect", new=reject_socket),
            patch.object(socket.socket, "connect_ex", new=reject_socket),
        ):
            yield attempts

    return guard


async def _public_resolver(_host: str, _port: int) -> tuple[str, ...]:
    return ("93.184.216.34",)


def _discovery(*links: PDFLink) -> PDFLinkDiscoveryResult:
    """Build a successful typed discovery outcome for downloader tests."""
    return PDFLinkDiscoveryResult(
        links=links,
        attempted_sources=("test-source",),
        completed_sources=("test-source",),
    )


# ============================================================
# Data Classes
# ============================================================


class TestPDFSource:
    async def test_properties(self):
        assert PDFSource.EUROPE_PMC.source_id == "europe_pmc"
        assert PDFSource.EUROPE_PMC.priority == 1
        assert PDFSource.EUROPE_PMC.display_name == "Europe PMC"

    async def test_priority_ordering(self):
        assert PDFSource.EUROPE_PMC.priority < PDFSource.PMC.priority
        assert PDFSource.PMC.priority < PDFSource.CORE.priority
        assert PDFSource.CORE.priority < PDFSource.ARXIV.priority


class TestPDFLink:
    async def test_sorting(self):
        link1 = PDFLink(url="a", source=PDFSource.EUROPE_PMC)
        link2 = PDFLink(url="b", source=PDFSource.CORE)
        assert link1 < link2

    async def test_sorting_same_source(self):
        link1 = PDFLink(url="a", source=PDFSource.CORE, confidence=0.9)
        link2 = PDFLink(url="b", source=PDFSource.CORE, confidence=0.5)
        assert link1 < link2  # higher confidence first

    async def test_defaults(self):
        link = PDFLink(url="https://example.com/paper.pdf", source=PDFSource.PMC)
        assert link.access_type == "unknown"
        assert link.is_direct_pdf is True
        assert link.confidence == 1.0


class TestDownloadResult:
    async def test_is_pdf_true(self):
        result = DownloadResult(success=True, content=b"%PDF-1.4 test content")
        assert result.is_pdf is True

    async def test_is_pdf_false_html(self):
        result = DownloadResult(success=True, content=b"<html>Not a PDF</html>")
        assert result.is_pdf is False

    async def test_is_pdf_no_content(self):
        result = DownloadResult(success=False, content=None)
        assert result.is_pdf is False


class TestFulltextResult:
    async def test_defaults(self):
        result = FulltextResult()
        assert result.pmid is None
        assert result.content_type == "none"
        assert result.link_discovery is None
        assert result.word_count == 0

    def test_link_discovery_rejects_mutable_list_contract(self):
        link = PDFLink(url="https://example.com/paper.pdf", source=PDFSource.PMC)

        with pytest.raises(TypeError, match="links must be a tuple"):
            PDFLinkDiscoveryResult(  # type: ignore[arg-type]
                links=[link],
                attempted_sources=("pmc",),
                completed_sources=("pmc",),
            )


# ============================================================
# FulltextDownloader Init
# ============================================================


class TestFulltextDownloaderInit:
    async def test_defaults(self):
        d = FulltextDownloader()
        assert d._timeout == 30.0
        assert d._max_retries == 3
        assert d._client is None

    async def test_custom_params(self):
        d = FulltextDownloader(timeout=60.0, max_retries=5, max_concurrent=10)
        assert d._timeout == 60.0
        assert d._max_retries == 5

    async def test_retired_pass_through_surface_is_absent(self):
        import pubmed_search.infrastructure.sources.fulltext_download as module

        retired_methods = {
            "_download_from_url",
            "_download_from_url_impl",
            "_extract_pdf_text",
            "_get_crossref_links",
            "_get_pmc_links",
            "_get_structured_fulltext",
            "_get_unpaywall_links",
        }
        assert retired_methods.isdisjoint(vars(FulltextDownloader))
        assert not hasattr(module, "download_fulltext")
        assert not hasattr(module, "get_fulltext_downloader")


# ============================================================
# get_pdf_links
# ============================================================


class TestGetPdfLinks:
    @pytest.mark.asyncio
    async def test_with_pmcid(self):
        d = FulltextDownloader()
        with patch.object(d._discovery_phase, "get_pmc_links", new_callable=AsyncMock) as mock_pmc:
            mock_pmc.return_value = [
                PDFLink(url="https://epmc.org/pdf1", source=PDFSource.EUROPE_PMC),
            ]
            discovery = await d.get_pdf_links(pmcid="PMC123")
            assert len(discovery.links) == 1
            assert discovery.links[0].source == PDFSource.EUROPE_PMC
            assert discovery.coverage_status == "complete"

    @pytest.mark.asyncio
    async def test_with_doi(self):
        d = FulltextDownloader()
        phase = d._discovery_phase
        with (
            patch.object(phase, "get_openurl_links", new_callable=AsyncMock, return_value=[]),
            patch.object(phase, "get_unpaywall_links", new_callable=AsyncMock) as mock_uw,
            patch.object(phase, "get_crossref_links", new_callable=AsyncMock) as mock_cr,
            patch.object(phase, "get_core_links", new_callable=AsyncMock) as mock_core,
            patch.object(phase, "get_semantic_scholar_links", new_callable=AsyncMock) as mock_ss,
            patch.object(phase, "get_openalex_links", new_callable=AsyncMock) as mock_oa,
            patch.object(phase, "get_doaj_links", new_callable=AsyncMock) as mock_doaj,
            patch.object(phase, "get_zenodo_links", new_callable=AsyncMock) as mock_zen,
        ):
            mock_uw.return_value = [PDFLink(url="https://uw.com/pdf", source=PDFSource.UNPAYWALL_PUBLISHER)]
            mock_cr.return_value = []
            mock_core.return_value = []
            mock_ss.return_value = []
            mock_oa.return_value = []
            mock_doaj.return_value = []
            mock_zen.return_value = []

            discovery = await d.get_pdf_links(doi="10.1234/test")
            assert len(discovery.links) == 2
            assert any(link.source == PDFSource.DOI_REDIRECT for link in discovery.links)

    @pytest.mark.asyncio
    async def test_adds_doi_landing_page_fallback(self):
        d = FulltextDownloader()
        phase = d._discovery_phase
        with (
            patch.object(phase, "get_openurl_links", new_callable=AsyncMock, return_value=[]),
            patch.object(phase, "get_unpaywall_links", new_callable=AsyncMock, return_value=[]),
            patch.object(phase, "get_crossref_links", new_callable=AsyncMock, return_value=[]),
            patch.object(phase, "get_core_links", new_callable=AsyncMock, return_value=[]),
            patch.object(phase, "get_semantic_scholar_links", new_callable=AsyncMock, return_value=[]),
            patch.object(phase, "get_openalex_links", new_callable=AsyncMock, return_value=[]),
            patch.object(phase, "get_doaj_links", new_callable=AsyncMock, return_value=[]),
            patch.object(phase, "get_zenodo_links", new_callable=AsyncMock, return_value=[]),
        ):
            discovery = await d.get_pdf_links(doi="10.1234/test")

        assert any(
            link.source == PDFSource.DOI_REDIRECT
            and link.url == "https://doi.org/10.1234/test"
            and link.is_direct_pdf is False
            for link in discovery.links
        )

    @pytest.mark.asyncio
    async def test_deduplicates_urls(self):
        d = FulltextDownloader()
        with patch.object(d._discovery_phase, "get_pmc_links", new_callable=AsyncMock) as mock_pmc:
            mock_pmc.return_value = [
                PDFLink(url="https://same.url/pdf", source=PDFSource.EUROPE_PMC),
                PDFLink(url="https://same.url/pdf", source=PDFSource.PMC),
            ]
            discovery = await d.get_pdf_links(pmcid="PMC123")
            assert len(discovery.links) == 1  # Deduplicated

    @pytest.mark.asyncio
    async def test_no_ids(self):
        d = FulltextDownloader()
        discovery = await d.get_pdf_links()
        assert discovery.links == ()
        assert discovery.attempted_sources == ()
        assert discovery.coverage_status == "complete"

    @pytest.mark.asyncio
    async def test_arxiv_doi(self):
        d = FulltextDownloader()
        phase = d._discovery_phase
        with (
            patch.object(phase, "get_unpaywall_links", new_callable=AsyncMock, return_value=[]),
            patch.object(phase, "get_crossref_links", new_callable=AsyncMock, return_value=[]),
            patch.object(phase, "get_core_links", new_callable=AsyncMock, return_value=[]),
            patch.object(
                phase,
                "get_semantic_scholar_links",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch.object(phase, "get_openalex_links", new_callable=AsyncMock, return_value=[]),
            patch.object(phase, "get_doaj_links", new_callable=AsyncMock, return_value=[]),
            patch.object(phase, "get_zenodo_links", new_callable=AsyncMock, return_value=[]),
            patch.object(phase, "get_arxiv_link", new_callable=AsyncMock) as mock_arxiv,
        ):
            mock_arxiv.return_value = PDFLink(url="https://arxiv.org/pdf/2301.00001.pdf", source=PDFSource.ARXIV)
            discovery = await d.get_pdf_links(doi="10.48550/arxiv.2301.00001")
            assert any(link.source == PDFSource.ARXIV for link in discovery.links)

    @pytest.mark.asyncio
    async def test_exception_in_task(self):
        d = FulltextDownloader()
        with patch.object(d._discovery_phase, "get_pmc_links", new_callable=AsyncMock) as mock_pmc:
            mock_pmc.side_effect = Exception("network error")
            discovery = await d.get_pdf_links(pmcid="PMC123")

        assert discovery.links == ()
        assert discovery.coverage_status == "unavailable"
        assert discovery.completed_sources == ()
        assert discovery.source_errors == (LinkDiscoverySourceError(source="pmc", kind="unexpected"),)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("target_source", "target_method", "identifier_kind", "expected_kind", "expected_status"),
        [
            ("pmc", "get_pmc_links", "pmid", "timeout", None),
            ("pubmed_linkout", "get_pubmed_linkout", "pmid", "http", 503),
            ("institutional_resolver", "get_openurl_links", "pmid", "transport", None),
            ("unpaywall", "get_unpaywall_links", "doi", "transport", None),
            ("crossref", "get_crossref_links", "doi", "http", 503),
            ("doaj", "get_doaj_links", "doi", "http", 503),
            ("zenodo", "get_zenodo_links", "doi", "http", 503),
        ],
    )
    async def test_real_discovery_provider_outage_is_sanitized_partial_coverage(
        self,
        monkeypatch,
        caplog,
        target_source,
        target_method,
        identifier_kind,
        expected_kind,
        expected_status,
    ):
        d = FulltextDownloader()
        phase = d._discovery_phase
        discovery_methods = {
            "get_pmc_links",
            "get_pubmed_linkout",
            "get_openurl_links",
            "get_unpaywall_links",
            "get_crossref_links",
            "get_core_links",
            "get_semantic_scholar_links",
            "get_openalex_links",
            "get_doaj_links",
            "get_zenodo_links",
        }
        for method_name in discovery_methods - {target_method}:
            monkeypatch.setattr(phase, method_name, AsyncMock(return_value=[]))

        request = httpx.Request("GET", "https://provider.example/private?token=super-secret")
        if target_source == "pmc":

            def fail_pmc_lookup(_pmid):
                raise TimeoutError("token=super-secret /srv/private/pmc.xml")

            monkeypatch.setattr(
                "pubmed_search.infrastructure.sources.fulltext_discovery._lookup_pmc_links_from_entrez",
                fail_pmc_lookup,
            )
        elif target_source == "unpaywall":
            client = AsyncMock()
            client.get_oa_status.side_effect = httpx.ConnectError("token=super-secret", request=request)
            monkeypatch.setattr("pubmed_search.infrastructure.sources.get_unpaywall_client", lambda: client)
        elif target_source == "institutional_resolver":

            def fail_openurl(_article):
                raise httpx.ConnectError("token=super-secret", request=request)

            monkeypatch.setattr(
                "pubmed_search.infrastructure.sources.openurl.get_openurl_link",
                fail_openurl,
            )
        else:
            response = httpx.Response(503, request=request)
            client = AsyncMock()
            client.get.return_value = response
            monkeypatch.setattr(phase, "_get_client", AsyncMock(return_value=client))

        caplog.set_level(logging.WARNING)
        identifiers = {identifier_kind: "12345678" if identifier_kind == "pmid" else "10.1000/test"}
        discovery = await d.get_pdf_links(**identifiers)

        assert target_source in discovery.attempted_sources
        assert target_source not in discovery.completed_sources
        assert discovery.coverage_status == "partial"
        assert discovery.source_errors == (
            LinkDiscoverySourceError(
                source=target_source,
                kind=expected_kind,
                retryable=expected_kind in {"timeout", "transport", "http"},
                status_code=expected_status,
            ),
        )
        assert "super-secret" not in repr(discovery)
        assert "/srv/private" not in repr(discovery)
        assert "super-secret" not in caplog.text
        assert "/srv/private" not in caplog.text

    def test_partial_result_preserves_links_and_sanitizes_source_errors(self):
        d = FulltextDownloader()
        link = PDFLink(url="https://public.example/paper.pdf", source=PDFSource.PMC)
        discovery = d._compose_link_discovery_result(
            [
                SourceAdapterResult(
                    source="pmc",
                    operation="collect_links",
                    items=[link],
                    total_count=1,
                    status="ok",
                ),
                SourceAdapterResult.failure(
                    source="core",
                    operation="collect_links",
                    error=SourceAdapterError(
                        source="core",
                        operation="collect_links",
                        message=(
                            "token=super-secret https://private.example/paper?key=hidden /srv/private/provider.json"
                        ),
                        kind="transport",
                        retryable=True,
                    ),
                ),
            ]
        )

        assert discovery.links == (link,)
        assert discovery.coverage_status == "partial"
        assert discovery.completed_sources == ("pmc",)
        assert discovery.source_errors == (LinkDiscoverySourceError(source="core", kind="transport", retryable=True),)
        assert "super-secret" not in repr(discovery)
        assert "/srv/private" not in repr(discovery)


class TestFulltextBudget:
    @pytest.mark.asyncio
    async def test_get_fulltext_honors_end_to_end_timeout(self):
        d = FulltextDownloader(timeout=30.0)
        candidate = PDFLink(url="https://example.org/paper.pdf", source=PDFSource.CORE)

        async def _slow_download(*args, **kwargs):
            await asyncio.Event().wait()

        with (
            patch.object(d, "get_pdf_links", new_callable=AsyncMock, return_value=_discovery(candidate)),
            patch.object(d._fetch_phase, "download_with_retry", new_callable=AsyncMock, side_effect=_slow_download),
        ):
            started = time.monotonic()
            result = await d.get_fulltext(doi="10.1234/test", total_timeout=0.05)

        assert time.monotonic() - started < 0.2
        assert result.error is not None
        assert "total timeout" in result.error.lower()


class TestCrossrefLinks:
    @pytest.mark.asyncio
    async def test_unspecified_content_type_pdf_url_is_kept(self):
        d = FulltextDownloader()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {
                "link": [
                    {
                        "URL": "https://jamanetwork.com/journals/jama/articlepdf/2845042/example.pdf",
                        "content-type": "unspecified",
                    }
                ]
            }
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with patch.object(d._discovery_phase, "_get_client", new_callable=AsyncMock, return_value=mock_client):
            links = await d._discovery_phase.get_crossref_links("10.1001/jama.2025.27019")

        assert len(links) == 1
        assert links[0].is_direct_pdf is True
        assert links[0].source == PDFSource.CROSSREF

    @pytest.mark.asyncio
    async def test_doi_url_is_normalized_and_quoted_for_crossref_lookup(self):
        d = FulltextDownloader()
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"message": {}}
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with patch.object(d._discovery_phase, "_get_client", new_callable=AsyncMock, return_value=mock_client):
            await d._discovery_phase.get_crossref_links("https://doi.org/10.1001/jama.2025.27019")

        requested_url = mock_client.get.await_args.args[0]
        assert requested_url.startswith("https://api.crossref.org/works/10.1001%2Fjama.2025.27019?")
        assert "https://doi.org" not in requested_url

    @pytest.mark.asyncio
    async def test_crossref_lookup_uses_configured_source_contact_email(self):
        from pubmed_search.infrastructure.sources.runtime import SourceRuntime, bind_source_runtime

        with bind_source_runtime(SourceRuntime(contact_email="runtime@example.com")):
            d = FulltextDownloader()
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.json.return_value = {"message": {}}
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response

            with patch.object(d._discovery_phase, "_get_client", new_callable=AsyncMock, return_value=mock_client):
                await d._discovery_phase.get_crossref_links("10.1001/jama.2025.27019")

            requested_url = mock_client.get.await_args.args[0]
            assert "mailto=runtime%40example.com" in requested_url


# ============================================================
# _get_pmc_links
# ============================================================


class TestGetPMCLinks:
    @pytest.mark.asyncio
    async def test_with_pmcid(self):
        d = FulltextDownloader()
        links = await d._discovery_phase.get_pmc_links(None, "PMC7096777")
        assert len(links) == 2
        assert any("europepmc" in lnk.url for lnk in links)
        assert any("ncbi.nlm.nih.gov" in lnk.url for lnk in links)

    @pytest.mark.asyncio
    async def test_pmcid_lowercase(self):
        d = FulltextDownloader()
        links = await d._discovery_phase.get_pmc_links(None, "pmc123")
        assert len(links) == 2
        assert "123" in links[0].url


class TestInstitutionalResolverLinks:
    @pytest.mark.asyncio
    async def test_get_openurl_links(self):
        d = FulltextDownloader()
        with patch(
            "pubmed_search.infrastructure.sources.openurl.get_openurl_link",
            return_value="https://resolver.example.edu/openurl?id=123",
        ):
            links = await d._discovery_phase.get_openurl_links("12345", "10.1234/test")

        assert len(links) == 1
        assert links[0].source == PDFSource.INSTITUTIONAL_RESOLVER
        assert links[0].access_type == "subscription"
        assert links[0].is_direct_pdf is False


# ============================================================
# _get_arxiv_link
# ============================================================


class TestGetArxivLink:
    @pytest.mark.asyncio
    async def test_valid_arxiv_doi(self):
        d = FulltextDownloader()
        link = await d._discovery_phase.get_arxiv_link("10.48550/arxiv.2301.00001")
        assert link is not None
        assert "arxiv.org/pdf/2301.00001" in link.url
        assert link.source == PDFSource.ARXIV

    @pytest.mark.asyncio
    async def test_with_version(self):
        d = FulltextDownloader()
        link = await d._discovery_phase.get_arxiv_link("10.48550/arxiv.2301.00001v2")
        assert link is not None
        assert "v2" in link.url

    @pytest.mark.asyncio
    async def test_no_match(self):
        d = FulltextDownloader()
        link = await d._discovery_phase.get_arxiv_link("10.1234/not_arxiv")
        assert link is None


# ============================================================
# _get_preprint_link
# ============================================================


class TestGetPreprintLink:
    @pytest.mark.asyncio
    async def test_biorxiv_doi(self):
        d = FulltextDownloader()
        link = await d._discovery_phase.get_preprint_link("10.1101/2024.01.01.123456")
        assert link is not None
        assert "biorxiv" in link.url
        assert link.source == PDFSource.BIORXIV

    @pytest.mark.asyncio
    async def test_medrxiv_doi(self):
        d = FulltextDownloader()
        link = await d._discovery_phase.get_preprint_link("10.1101/2024.01.01.123456medrxiv")
        assert link is not None

    @pytest.mark.asyncio
    async def test_no_match(self):
        d = FulltextDownloader()
        link = await d._discovery_phase.get_preprint_link("10.1234/regular_paper")
        assert link is None


# ============================================================
# download_pdf
# ============================================================


class TestDownloadPdf:
    @pytest.mark.asyncio
    async def test_no_links(self):
        d = FulltextDownloader()
        with patch.object(d, "get_pdf_links", new_callable=AsyncMock, return_value=_discovery()):
            result = await d.download_pdf(doi="10.1234/fake")
            assert result.success is False
            assert result.error is not None
            assert "No PDF links" in result.error

    @pytest.mark.asyncio
    async def test_successful_download(self):
        d = FulltextDownloader()
        pdf_link = PDFLink(url="https://example.com/paper.pdf", source=PDFSource.EUROPE_PMC)
        with (
            patch.object(d, "get_pdf_links", new_callable=AsyncMock, return_value=_discovery(pdf_link)),
            patch.object(d._fetch_phase, "download_with_retry", new_callable=AsyncMock) as mock_dl,
        ):
            mock_dl.return_value = DownloadResult(
                success=True, content=b"%PDF-1.4 content", source=PDFSource.EUROPE_PMC
            )
            result = await d.download_pdf(doi="10.1234/test")
            assert result.success is True
            assert result.is_pdf is True

    @pytest.mark.asyncio
    async def test_non_direct_landing_page_uses_http_resolver_when_browser_disabled(self):
        d = FulltextDownloader()
        link = PDFLink(
            url="https://publisher.example/article",
            source=PDFSource.CROSSREF,
            is_direct_pdf=False,
        )

        with patch.object(d._fetch_phase, "download_with_retry", new_callable=AsyncMock) as mock_download:
            mock_download.return_value = DownloadResult(
                success=True,
                content=b"%PDF-1.4 content",
                source=PDFSource.CROSSREF,
                url="https://publisher.example/article.pdf",
            )

            result = await d._download_candidate(
                link,
                article_metadata={},
                allow_browser_session=False,
                deadline=None,
                total_timeout=None,
            )

        assert result.success is True
        assert result.is_pdf is True
        mock_download.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_all_sources_fail_without_exposing_transport_error(self, caplog):
        d = FulltextDownloader()
        caplog.set_level(logging.DEBUG)
        links = [
            PDFLink(url="https://a.com/pdf", source=PDFSource.EUROPE_PMC),
            PDFLink(url="https://b.com/pdf", source=PDFSource.PMC),
        ]
        with (
            patch.object(d, "get_pdf_links", new_callable=AsyncMock, return_value=_discovery(*links)),
            patch.object(d._fetch_phase, "download_with_retry", new_callable=AsyncMock) as mock_dl,
        ):
            mock_dl.return_value = DownloadResult(
                success=False,
                error="token=super-secret https://private.example/paper?key=hidden /srv/private/file.pdf",
            )
            result = await d.download_pdf(doi="10.1234/test", try_all=True)
            assert result.success is False

        assert result.error == "All PDF candidates failed (sources: europe_pmc, pmc)"
        assert "super-secret" not in caplog.text
        assert "/srv/private" not in caplog.text

    @pytest.mark.asyncio
    async def test_preferred_source(self):
        d = FulltextDownloader()
        links = [
            PDFLink(url="https://a.com/pdf", source=PDFSource.EUROPE_PMC),
            PDFLink(url="https://b.com/pdf", source=PDFSource.CORE),
        ]
        with (
            patch.object(d, "get_pdf_links", new_callable=AsyncMock, return_value=_discovery(*links)),
            patch.object(d._fetch_phase, "download_with_retry", new_callable=AsyncMock) as mock_dl,
        ):
            mock_dl.return_value = DownloadResult(success=True, content=b"%PDF-1.4", source=PDFSource.CORE)
            _result = await d.download_pdf(doi="10.1234/test", preferred_source=PDFSource.CORE)
            # CORE should be tried first
            first_call_url = mock_dl.call_args_list[0][0][0]
            assert "b.com" in first_call_url

    @pytest.mark.asyncio
    async def test_prefers_direct_pdf_before_landing_page(self):
        d = FulltextDownloader()
        links = [
            PDFLink(url="https://doi.example/article", source=PDFSource.DOI_REDIRECT, is_direct_pdf=False),
            PDFLink(url="https://publisher.example/paper.pdf", source=PDFSource.CROSSREF, is_direct_pdf=True),
        ]
        with (
            patch.object(d, "get_pdf_links", new_callable=AsyncMock, return_value=_discovery(*links)),
            patch.object(d._fetch_phase, "download_with_retry", new_callable=AsyncMock) as mock_dl,
        ):
            mock_dl.return_value = DownloadResult(
                success=True,
                content=b"%PDF-1.4 test",
                source=PDFSource.CROSSREF,
                url="https://publisher.example/paper.pdf",
                file_size=16,
            )
            result = await d.download_pdf(doi="10.1234/test")

        assert result.success is True
        first_call_url = mock_dl.call_args_list[0][0][0]
        assert first_call_url == "https://publisher.example/paper.pdf"

    @pytest.mark.asyncio
    async def test_browser_session_fallback_for_institutional_link(
        self,
        fail_closed_network_probe: Callable[[], AbstractContextManager[list[str]]],
    ):
        d = FulltextDownloader()
        openurl_link = PDFLink(
            url="https://resolver.library.edu/openurl?doi=10.1234/test",
            source=PDFSource.OPENURL,
            access_type="institutional",
            is_direct_pdf=False,
        )
        mock_fetcher = MagicMock()
        mock_fetcher.is_enabled.return_value = True
        mock_fetcher.fetch_pdf = AsyncMock(
            return_value=MagicMock(
                success=True,
                content=b"%PDF-1.4 institutional",
                content_type="application/pdf",
                final_url="https://publisher.example/download.pdf",
            )
        )

        with (
            fail_closed_network_probe() as network_attempts,
            patch.object(d, "get_pdf_links", new_callable=AsyncMock, return_value=_discovery(openurl_link)),
            patch.object(
                d._fetch_phase,
                "download_with_retry",
                new_callable=AsyncMock,
                return_value=DownloadResult(
                    success=False,
                    error="Institutional landing page requires browser authentication",
                    source=PDFSource.OPENURL,
                    url=openurl_link.url,
                ),
            ) as mock_http_download,
            patch(
                "pubmed_search.infrastructure.sources.browser_session.get_browser_session_fetcher",
                return_value=mock_fetcher,
            ),
        ):
            result = await d.download_pdf(doi="10.1234/test", allow_browser_session=True)

        assert result.success is True
        assert result.source == PDFSource.BROWSER_SESSION
        assert result.url == "https://publisher.example/download.pdf"
        mock_http_download.assert_awaited_once()
        mock_fetcher.fetch_pdf.assert_awaited_once()
        assert network_attempts == []

    @pytest.mark.asyncio
    async def test_browser_session_auto_mode_for_institutional_link(
        self,
        fail_closed_network_probe: Callable[[], AbstractContextManager[list[str]]],
    ):
        d = FulltextDownloader()
        openurl_link = PDFLink(
            url="https://resolver.library.edu/openurl?doi=10.1234/test",
            source=PDFSource.OPENURL,
            access_type="institutional",
            is_direct_pdf=False,
        )
        mock_fetcher = MagicMock()
        mock_fetcher.is_auto_enabled.return_value = True
        mock_fetcher.fetch_pdf = AsyncMock(
            return_value=MagicMock(
                success=True,
                content=b"%PDF-1.4 institutional",
                content_type="application/pdf",
                final_url="https://publisher.example/download.pdf",
            )
        )

        with (
            fail_closed_network_probe() as network_attempts,
            patch.object(d, "get_pdf_links", new_callable=AsyncMock, return_value=_discovery(openurl_link)),
            patch.object(
                d._fetch_phase,
                "download_with_retry",
                new_callable=AsyncMock,
                return_value=DownloadResult(
                    success=False,
                    error="Institutional landing page requires browser authentication",
                    source=PDFSource.OPENURL,
                    url=openurl_link.url,
                ),
            ) as mock_http_download,
            patch(
                "pubmed_search.infrastructure.sources.browser_session.get_browser_session_fetcher",
                return_value=mock_fetcher,
            ),
        ):
            result = await d.download_pdf(doi="10.1234/test")

        assert result.success is True
        assert result.source == PDFSource.BROWSER_SESSION
        assert result.url == "https://publisher.example/download.pdf"
        mock_http_download.assert_awaited_once()
        mock_fetcher.fetch_pdf.assert_awaited_once()
        assert network_attempts == []

    @pytest.mark.asyncio
    async def test_get_pdf_links_includes_openurl_when_configured(
        self,
        fail_closed_network_probe: Callable[[], AbstractContextManager[list[str]]],
    ):
        d = FulltextDownloader()
        phase = d._discovery_phase
        with (
            fail_closed_network_probe() as network_attempts,
            patch(
                "pubmed_search.infrastructure.sources.openurl.get_openurl_link",
                return_value="https://resolver.library.edu/openurl?doi=10.1234/test",
            ),
            patch.object(phase, "get_unpaywall_links", new_callable=AsyncMock, return_value=[]),
            patch.object(phase, "get_crossref_links", new_callable=AsyncMock, return_value=[]),
            patch.object(phase, "get_core_links", new_callable=AsyncMock, return_value=[]),
            patch.object(phase, "get_semantic_scholar_links", new_callable=AsyncMock, return_value=[]),
            patch.object(phase, "get_openalex_links", new_callable=AsyncMock, return_value=[]),
            patch.object(phase, "get_doaj_links", new_callable=AsyncMock, return_value=[]),
            patch.object(phase, "get_zenodo_links", new_callable=AsyncMock, return_value=[]),
        ):
            discovery = await d.get_pdf_links(doi="10.1234/test")

        assert any(link.source == PDFSource.OPENURL for link in discovery.links)
        assert network_attempts == []

    @pytest.mark.asyncio
    async def test_builds_jama_referer_for_articlepdf_links(self):
        d = FulltextDownloader()
        link = PDFLink(
            url="https://jamanetwork.com/journals/jamasurgery/articlepdf/2846796/example.pdf",
            source=PDFSource.OPENALEX,
        )

        headers = d._build_candidate_headers(link, {"doi": "10.1001/jamasurg.2026.0307"})

        assert headers["Referer"] == "https://jamanetwork.com/journals/jamasurgery/fullarticle/2846796"


class TestLandingPageResolution:
    @pytest.mark.asyncio
    async def test_extract_pdf_candidates_from_html(self):
        d = FulltextDownloader()
        html = """
                <html>
                    <head>
                        <meta name="citation_pdf_url" content="/downloads/paper.pdf" />
                    </head>
                    <body>
                        <a href="/downloads/paper.pdf">Download PDF</a>
                    </body>
                </html>
                """

        candidates = d._fetch_phase.extract_pdf_candidates_from_html("https://publisher.example.edu/article", html)

        assert candidates == ["https://publisher.example.edu/downloads/paper.pdf"]

    @pytest.mark.asyncio
    async def test_download_from_url_impl_follows_landing_page_pdf(self):
        d = FulltextDownloader()
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
            d._fetch_phase._address_resolver = _public_resolver
            with patch.object(d._fetch_phase, "_get_client", new_callable=AsyncMock, return_value=client):
                result = await d._fetch_phase.download_from_url_impl(
                    landing_url,
                    PDFSource.INSTITUTIONAL_RESOLVER,
                )

        assert result.success is True
        assert result.is_pdf is True
        assert result.url == pdf_url


# ============================================================
# get_fulltext
# ============================================================


class TestGetFulltext:
    @pytest.mark.asyncio
    async def test_links_only(self):
        d = FulltextDownloader()
        with patch.object(d, "get_pdf_links", new_callable=AsyncMock) as mock_links:
            mock_links.return_value = _discovery(PDFLink(url="https://example.com/pdf", source=PDFSource.EUROPE_PMC))
            result = await d.get_fulltext(doi="10.1234/test", strategy="links_only")
            assert len(result.require_link_discovery().links) == 1
            assert result.content_type == "none"  # links_only doesn't download

    @pytest.mark.asyncio
    async def test_try_all_xml_first(self):
        d = FulltextDownloader()
        with patch.object(d._extract_phase, "get_structured_fulltext", new_callable=AsyncMock) as mock_xml:
            mock_xml.return_value = {
                "text": "Full text content here",
                "sections": {"introduction": "Intro text"},
                "title": "Test Paper",
                "references": ["ref1"],
            }
            result = await d.get_fulltext(pmcid="PMC123", strategy="try_all")
            assert result.content_type == "xml"
            assert result.text_content == "Full text content here"
            assert result.source_used == PDFSource.EUROPE_PMC

    @pytest.mark.asyncio
    async def test_get_structured_fulltext_awaits_xml_fetch(self):
        d = FulltextDownloader()
        mock_client = MagicMock()
        mock_client.get_fulltext_xml = AsyncMock(return_value="<article><abstract>Test</abstract></article>")
        mock_client.parse_fulltext_xml.return_value = {
            "title": "Test Paper",
            "abstract": "Abstract text",
            "sections": [{"title": "Introduction", "content": "Intro text"}],
            "references": ["ref1"],
        }

        with patch(
            "pubmed_search.infrastructure.sources.get_europe_pmc_client",
            return_value=mock_client,
        ):
            result = await d._extract_phase.get_structured_fulltext("PMC123")

        mock_client.get_fulltext_xml.assert_awaited_once_with("PMC123")
        mock_client.parse_fulltext_xml.assert_called_once()
        assert result is not None
        assert result["title"] == "Test Paper"
        assert "ABSTRACT\nAbstract text" in result["text"]

    @pytest.mark.asyncio
    async def test_no_links_found(self):
        d = FulltextDownloader()
        with patch.object(d, "get_pdf_links", new_callable=AsyncMock, return_value=_discovery()):
            result = await d.get_fulltext(doi="10.1234/test", strategy="download_best")
            assert result.content_type == "none"

    @pytest.mark.asyncio
    async def test_extract_text(self):
        d = FulltextDownloader()
        pdf_content = b"%PDF-1.4 some content"
        with (
            patch.object(d, "get_pdf_links", new_callable=AsyncMock) as mock_links,
            patch.object(d, "_download_candidate", new_callable=AsyncMock) as mock_download,
            patch.object(d._extract_phase, "extract_pdf_text", new_callable=AsyncMock) as mock_extract,
        ):
            mock_links.return_value = _discovery(PDFLink(url="https://x.com", source=PDFSource.PMC))
            mock_download.return_value = DownloadResult(
                success=True, content=pdf_content, source=PDFSource.PMC, file_size=100
            )
            mock_extract.return_value = "Extracted text from PDF"

            result = await d.get_fulltext(doi="10.1234/test", strategy="extract_text")
            assert result.content_type == "pdf"
            assert result.text_content == "Extracted text from PDF"
            assert result.extraction_method == "pdf_extraction"

    @pytest.mark.asyncio
    async def test_extract_text_adds_resolved_pdf_link(self):
        d = FulltextDownloader()
        resolved_pdf_url = "https://publisher.example.edu/paper.pdf"
        with (
            patch.object(
                d,
                "get_pdf_links",
                new_callable=AsyncMock,
                return_value=_discovery(
                    PDFLink(
                        url="https://resolver.example.edu/openurl?id=1",
                        source=PDFSource.INSTITUTIONAL_RESOLVER,
                        access_type="subscription",
                        is_direct_pdf=False,
                    )
                ),
            ),
            patch.object(d, "_download_candidate", new_callable=AsyncMock) as mock_download,
            patch.object(
                d._extract_phase,
                "extract_pdf_text",
                new_callable=AsyncMock,
                return_value="Institutional fulltext",
            ),
        ):
            mock_download.return_value = DownloadResult(
                success=True,
                content=b"%PDF-1.4 test content",
                source=PDFSource.INSTITUTIONAL_RESOLVER,
                url=resolved_pdf_url,
                file_size=128,
            )
            result = await d.get_fulltext(doi="10.1234/test", strategy="extract_text")

        assert result.resolved_pdf_url == resolved_pdf_url
        assert result.require_link_discovery().links[0].url == resolved_pdf_url
        assert result.require_link_discovery().links[0].access_type == "subscription"

    async def test_extract_text_reuses_links_without_second_discovery(self):
        d = FulltextDownloader()
        link = PDFLink(url="https://publisher.example/paper.pdf", source=PDFSource.CROSSREF)
        with (
            patch.object(d, "get_pdf_links", new_callable=AsyncMock, return_value=_discovery(link)) as mock_links,
            patch.object(d, "_download_candidate", new_callable=AsyncMock) as mock_download,
            patch.object(
                d._extract_phase,
                "extract_pdf_text",
                new_callable=AsyncMock,
                return_value="Extracted text",
            ) as mock_extract,
        ):
            mock_download.return_value = DownloadResult(
                success=True,
                content=b"%PDF-1.4 some content",
                source=PDFSource.CROSSREF,
                url=link.url,
                file_size=100,
            )

            result = await d.get_fulltext(doi="10.1234/test", strategy="extract_text")

        assert result.text_content == "Extracted text"
        assert mock_links.await_count == 1
        mock_extract.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_extract_text_falls_back_to_second_pdf_when_first_extraction_fails(self):
        d = FulltextDownloader()
        first = PDFLink(url="https://publisher.example/first.pdf", source=PDFSource.CROSSREF)
        second = PDFLink(url="https://publisher.example/second.pdf", source=PDFSource.UNPAYWALL_PUBLISHER)
        with (
            patch.object(d, "get_pdf_links", new_callable=AsyncMock, return_value=_discovery(first, second)),
            patch.object(d, "_download_candidate", new_callable=AsyncMock) as mock_download,
            patch.object(d._extract_phase, "extract_pdf_text", new_callable=AsyncMock) as mock_extract,
        ):
            mock_download.side_effect = [
                DownloadResult(
                    success=True,
                    content=b"%PDF-1.4 first",
                    source=PDFSource.CROSSREF,
                    url=first.url,
                    file_size=50,
                ),
                DownloadResult(
                    success=True,
                    content=b"%PDF-1.4 second",
                    source=PDFSource.UNPAYWALL_PUBLISHER,
                    url=second.url,
                    file_size=80,
                ),
            ]
            mock_extract.side_effect = [None, "Recovered text from second PDF"]

            result = await d.get_fulltext(doi="10.1234/test", strategy="extract_text")

        assert result.text_content == "Recovered text from second PDF"
        assert result.source_used == PDFSource.UNPAYWALL_PUBLISHER
        assert mock_download.await_count == 2

    @pytest.mark.asyncio
    async def test_download_failure_is_sanitized(self):
        d = FulltextDownloader()
        with (
            patch.object(d, "get_pdf_links", new_callable=AsyncMock) as mock_links,
            patch.object(d, "download_pdf", new_callable=AsyncMock) as mock_dl,
        ):
            mock_links.return_value = _discovery(PDFLink(url="https://resolver.edu", source=PDFSource.OPENURL))
            mock_dl.return_value = DownloadResult(
                success=False,
                error="token=super-secret https://private.example/path?key=secret /srv/private/file",
            )

            result = await d.get_fulltext(
                doi="10.1234/test",
                strategy="download_best",
                allow_browser_session=True,
            )

        assert result.error == "PDF retrieval failed"
        assert "super-secret" not in result.error


# ============================================================
# _extract_pdf_text
# ============================================================


class TestExtractPdfText:
    @pytest.mark.asyncio
    async def test_none_input(self):
        d = FulltextDownloader()
        result = await d._extract_phase.extract_pdf_text(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_fitz_available(self):
        d = FulltextDownloader()
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Page 1 text"
        mock_doc.__iter__ = lambda s: iter([mock_page])
        mock_doc.close = MagicMock()

        with patch.dict("sys.modules", {"fitz": MagicMock()}):
            import sys

            sys.modules["fitz"].open.return_value = mock_doc
            result = await d._extract_phase.extract_pdf_text(b"%PDF-test")
            assert result == "Page 1 text"

    @pytest.mark.asyncio
    async def test_no_library_available(self):
        d = FulltextDownloader()
        with patch.dict("sys.modules", {"fitz": None, "pdfplumber": None}):
            # This should handle ImportError gracefully
            result = await d._extract_phase.extract_pdf_text(b"%PDF-1.4 test")
            # May return None if no library available
            assert result is None or isinstance(result, str)


# ============================================================
# close
# ============================================================


class TestClose:
    @pytest.mark.asyncio
    async def test_close_no_client(self):
        d = FulltextDownloader()
        await d.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_close_with_client(self):
        d = FulltextDownloader()
        mock_client = MagicMock()
        mock_client.is_closed = False
        mock_client.aclose = AsyncMock()
        d._client = mock_client
        await d.close()
        mock_client.aclose.assert_awaited_once()
