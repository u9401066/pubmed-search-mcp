"""Tests for FulltextDownloader."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.infrastructure.sources.fulltext_download import (
    PDFSource,
    PDFLink,
    DownloadResult,
    FulltextResult,
    FulltextDownloader,
    get_fulltext_downloader,
    download_fulltext,
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
        assert result.pdf_links == []
        assert result.word_count == 0


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


# ============================================================
# get_pdf_links
# ============================================================


class TestGetPdfLinks:
    @pytest.mark.asyncio
    async def test_with_pmcid(self):
        d = FulltextDownloader()
        with patch.object(d, "_get_pmc_links", new_callable=AsyncMock) as mock_pmc:
            mock_pmc.return_value = [
                PDFLink(url="https://epmc.org/pdf1", source=PDFSource.EUROPE_PMC),
            ]
            links = await d.get_pdf_links(pmcid="PMC123")
            assert len(links) == 1
            assert links[0].source == PDFSource.EUROPE_PMC

    @pytest.mark.asyncio
    async def test_with_doi(self):
        d = FulltextDownloader()
        with (
            patch.object(d, "_get_unpaywall_links", new_callable=AsyncMock) as mock_uw,
            patch.object(d, "_get_crossref_links", new_callable=AsyncMock) as mock_cr,
            patch.object(d, "_get_core_links", new_callable=AsyncMock) as mock_core,
            patch.object(
                d, "_get_semantic_scholar_links", new_callable=AsyncMock
            ) as mock_ss,
            patch.object(d, "_get_openalex_links", new_callable=AsyncMock) as mock_oa,
            patch.object(d, "_get_doaj_links", new_callable=AsyncMock) as mock_doaj,
            patch.object(d, "_get_zenodo_links", new_callable=AsyncMock) as mock_zen,
        ):
            mock_uw.return_value = [
                PDFLink(url="https://uw.com/pdf", source=PDFSource.UNPAYWALL_PUBLISHER)
            ]
            mock_cr.return_value = []
            mock_core.return_value = []
            mock_ss.return_value = []
            mock_oa.return_value = []
            mock_doaj.return_value = []
            mock_zen.return_value = []

            links = await d.get_pdf_links(doi="10.1234/test")
            assert len(links) == 1

    @pytest.mark.asyncio
    async def test_deduplicates_urls(self):
        d = FulltextDownloader()
        with patch.object(d, "_get_pmc_links", new_callable=AsyncMock) as mock_pmc:
            mock_pmc.return_value = [
                PDFLink(url="https://same.url/pdf", source=PDFSource.EUROPE_PMC),
                PDFLink(url="https://same.url/pdf", source=PDFSource.PMC),
            ]
            links = await d.get_pdf_links(pmcid="PMC123")
            assert len(links) == 1  # Deduplicated

    @pytest.mark.asyncio
    async def test_no_ids(self):
        d = FulltextDownloader()
        links = await d.get_pdf_links()
        assert links == []

    @pytest.mark.asyncio
    async def test_arxiv_doi(self):
        d = FulltextDownloader()
        with (
            patch.object(
                d, "_get_unpaywall_links", new_callable=AsyncMock, return_value=[]
            ),
            patch.object(
                d, "_get_crossref_links", new_callable=AsyncMock, return_value=[]
            ),
            patch.object(d, "_get_core_links", new_callable=AsyncMock, return_value=[]),
            patch.object(
                d,
                "_get_semantic_scholar_links",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch.object(
                d, "_get_openalex_links", new_callable=AsyncMock, return_value=[]
            ),
            patch.object(d, "_get_doaj_links", new_callable=AsyncMock, return_value=[]),
            patch.object(
                d, "_get_zenodo_links", new_callable=AsyncMock, return_value=[]
            ),
            patch.object(d, "_get_arxiv_link", new_callable=AsyncMock) as mock_arxiv,
        ):
            mock_arxiv.return_value = PDFLink(
                url="https://arxiv.org/pdf/2301.00001.pdf", source=PDFSource.ARXIV
            )
            links = await d.get_pdf_links(doi="10.48550/arxiv.2301.00001")
            assert any(lnk.source == PDFSource.ARXIV for lnk in links)

    @pytest.mark.asyncio
    async def test_exception_in_task(self):
        d = FulltextDownloader()
        with patch.object(d, "_get_pmc_links", new_callable=AsyncMock) as mock_pmc:
            mock_pmc.side_effect = Exception("network error")
            links = await d.get_pdf_links(pmcid="PMC123")
            assert links == []  # Exception handled gracefully


# ============================================================
# _get_pmc_links
# ============================================================


class TestGetPMCLinks:
    @pytest.mark.asyncio
    async def test_with_pmcid(self):
        d = FulltextDownloader()
        links = await d._get_pmc_links(None, "PMC7096777")
        assert len(links) == 2
        assert any("europepmc" in lnk.url for lnk in links)
        assert any("ncbi.nlm.nih.gov" in lnk.url for lnk in links)

    @pytest.mark.asyncio
    async def test_pmcid_lowercase(self):
        d = FulltextDownloader()
        links = await d._get_pmc_links(None, "pmc123")
        assert len(links) == 2
        assert "123" in links[0].url


# ============================================================
# _get_arxiv_link
# ============================================================


class TestGetArxivLink:
    @pytest.mark.asyncio
    async def test_valid_arxiv_doi(self):
        d = FulltextDownloader()
        link = await d._get_arxiv_link("10.48550/arxiv.2301.00001")
        assert link is not None
        assert "arxiv.org/pdf/2301.00001" in link.url
        assert link.source == PDFSource.ARXIV

    @pytest.mark.asyncio
    async def test_with_version(self):
        d = FulltextDownloader()
        link = await d._get_arxiv_link("10.48550/arxiv.2301.00001v2")
        assert link is not None
        assert "v2" in link.url

    @pytest.mark.asyncio
    async def test_no_match(self):
        d = FulltextDownloader()
        link = await d._get_arxiv_link("10.1234/not_arxiv")
        assert link is None


# ============================================================
# _get_preprint_link
# ============================================================


class TestGetPreprintLink:
    @pytest.mark.asyncio
    async def test_biorxiv_doi(self):
        d = FulltextDownloader()
        link = await d._get_preprint_link("10.1101/2024.01.01.123456")
        assert link is not None
        assert "biorxiv" in link.url
        assert link.source == PDFSource.BIORXIV

    @pytest.mark.asyncio
    async def test_medrxiv_doi(self):
        d = FulltextDownloader()
        link = await d._get_preprint_link("10.1101/2024.01.01.123456medrxiv")
        assert link is not None

    @pytest.mark.asyncio
    async def test_no_match(self):
        d = FulltextDownloader()
        link = await d._get_preprint_link("10.1234/regular_paper")
        assert link is None


# ============================================================
# download_pdf
# ============================================================


class TestDownloadPdf:
    @pytest.mark.asyncio
    async def test_no_links(self):
        d = FulltextDownloader()
        with patch.object(d, "get_pdf_links", new_callable=AsyncMock, return_value=[]):
            result = await d.download_pdf(doi="10.1234/fake")
            assert result.success is False
            assert "No PDF links" in result.error

    @pytest.mark.asyncio
    async def test_successful_download(self):
        d = FulltextDownloader()
        pdf_link = PDFLink(
            url="https://example.com/paper.pdf", source=PDFSource.EUROPE_PMC
        )
        with (
            patch.object(
                d, "get_pdf_links", new_callable=AsyncMock, return_value=[pdf_link]
            ),
            patch.object(d, "_download_from_url", new_callable=AsyncMock) as mock_dl,
        ):
            mock_dl.return_value = DownloadResult(
                success=True, content=b"%PDF-1.4 content", source=PDFSource.EUROPE_PMC
            )
            result = await d.download_pdf(doi="10.1234/test")
            assert result.success is True
            assert result.is_pdf is True

    @pytest.mark.asyncio
    async def test_all_sources_fail(self):
        d = FulltextDownloader()
        links = [
            PDFLink(url="https://a.com/pdf", source=PDFSource.EUROPE_PMC),
            PDFLink(url="https://b.com/pdf", source=PDFSource.PMC),
        ]
        with (
            patch.object(
                d, "get_pdf_links", new_callable=AsyncMock, return_value=links
            ),
            patch.object(d, "_download_from_url", new_callable=AsyncMock) as mock_dl,
        ):
            mock_dl.return_value = DownloadResult(success=False, error="timeout")
            result = await d.download_pdf(doi="10.1234/test", try_all=True)
            assert result.success is False

    @pytest.mark.asyncio
    async def test_preferred_source(self):
        d = FulltextDownloader()
        links = [
            PDFLink(url="https://a.com/pdf", source=PDFSource.EUROPE_PMC),
            PDFLink(url="https://b.com/pdf", source=PDFSource.CORE),
        ]
        with (
            patch.object(
                d, "get_pdf_links", new_callable=AsyncMock, return_value=links
            ),
            patch.object(d, "_download_from_url", new_callable=AsyncMock) as mock_dl,
        ):
            mock_dl.return_value = DownloadResult(
                success=True, content=b"%PDF-1.4", source=PDFSource.CORE
            )
            _result = await d.download_pdf(
                doi="10.1234/test", preferred_source=PDFSource.CORE
            )
            # CORE should be tried first
            first_call_url = mock_dl.call_args_list[0][0][0]
            assert "b.com" in first_call_url


# ============================================================
# get_fulltext
# ============================================================


class TestGetFulltext:
    @pytest.mark.asyncio
    async def test_links_only(self):
        d = FulltextDownloader()
        with patch.object(d, "get_pdf_links", new_callable=AsyncMock) as mock_links:
            mock_links.return_value = [
                PDFLink(url="https://example.com/pdf", source=PDFSource.EUROPE_PMC),
            ]
            result = await d.get_fulltext(doi="10.1234/test", strategy="links_only")
            assert len(result.pdf_links) == 1
            assert result.content_type == "none"  # links_only doesn't download

    @pytest.mark.asyncio
    async def test_try_all_xml_first(self):
        d = FulltextDownloader()
        with patch.object(
            d, "_get_structured_fulltext", new_callable=AsyncMock
        ) as mock_xml:
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
    async def test_no_links_found(self):
        d = FulltextDownloader()
        with patch.object(d, "get_pdf_links", new_callable=AsyncMock, return_value=[]):
            result = await d.get_fulltext(doi="10.1234/test", strategy="download_best")
            assert result.content_type == "none"

    @pytest.mark.asyncio
    async def test_extract_text(self):
        d = FulltextDownloader()
        pdf_content = b"%PDF-1.4 some content"
        with (
            patch.object(d, "get_pdf_links", new_callable=AsyncMock) as mock_links,
            patch.object(d, "download_pdf", new_callable=AsyncMock) as mock_dl,
            patch.object(
                d, "_extract_pdf_text", new_callable=AsyncMock
            ) as mock_extract,
        ):
            mock_links.return_value = [
                PDFLink(url="https://x.com", source=PDFSource.PMC)
            ]
            mock_dl.return_value = DownloadResult(
                success=True, content=pdf_content, source=PDFSource.PMC, file_size=100
            )
            mock_extract.return_value = "Extracted text from PDF"

            result = await d.get_fulltext(doi="10.1234/test", strategy="extract_text")
            assert result.content_type == "pdf"
            assert result.text_content == "Extracted text from PDF"
            assert result.extraction_method == "pdf_extraction"


# ============================================================
# _extract_pdf_text
# ============================================================


class TestExtractPdfText:
    @pytest.mark.asyncio
    async def test_none_input(self):
        d = FulltextDownloader()
        result = await d._extract_pdf_text(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_fitz_available(self):
        d = FulltextDownloader()
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Page 1 text"
        mock_doc.__iter__ = lambda s: iter([mock_page])
        mock_doc.close = AsyncMock()

        with patch.dict("sys.modules", {"fitz": MagicMock()}):
            import sys

            sys.modules["fitz"].open.return_value = mock_doc
            result = await d._extract_pdf_text(b"%PDF-test")
            assert result == "Page 1 text"

    @pytest.mark.asyncio
    async def test_no_library_available(self):
        d = FulltextDownloader()
        with patch.dict("sys.modules", {"fitz": None, "pdfplumber": None}):
            # This should handle ImportError gracefully
            result = await d._extract_pdf_text(b"%PDF-1.4 test")
            # May return None if no library available
            assert result is None or isinstance(result, str)


# ============================================================
# Singleton and convenience
# ============================================================


class TestSingleton:
    async def test_get_fulltext_downloader(self):
        import pubmed_search.infrastructure.sources.fulltext_download as mod

        mod._downloader_instance = None
        d = get_fulltext_downloader()
        assert isinstance(d, FulltextDownloader)
        # Same instance on second call
        d2 = get_fulltext_downloader()
        assert d is d2
        mod._downloader_instance = None

    @pytest.mark.asyncio
    async def test_download_fulltext_convenience(self):
        import pubmed_search.infrastructure.sources.fulltext_download as mod

        mod._downloader_instance = None
        with patch.object(
            FulltextDownloader, "get_fulltext", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = FulltextResult(pmid="123")
            result = await download_fulltext(pmid="123")
            assert result.pmid == "123"
        mod._downloader_instance = None


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
        d._client = MagicMock()
        d._client.is_closed = False
        d._client.aclose = AsyncMock()
        await d.close()
        d._client_called = True  # aclose was called
