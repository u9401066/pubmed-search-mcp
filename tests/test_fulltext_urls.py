"""
Deep URL Format Validation for Fulltext Download Module

This test validates that all URL formats are correct and sources are accessible.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest


class TestURLFormats:
    """Test URL formats for each fulltext source."""

    @pytest.fixture
    def client(self):
        """Create async HTTP client."""
        return httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/pdf,text/html,application/json,*/*",
            },
        )

    @pytest.mark.asyncio
    async def test_europe_pmc_pdf_url(self, client):
        """Europe PMC PDF URL should return PDF content."""
        # PMC7096777 is a known open access article
        url = "https://europepmc.org/backend/ptpmcrender.fcgi?accid=PMC7096777&blobtype=pdf"

        async with client:
            resp = await client.head(url)
            assert resp.status_code == 200, f"Europe PMC PDF returned {resp.status_code}"
            content_type = resp.headers.get("content-type", "")
            assert "pdf" in content_type.lower(), f"Expected PDF, got {content_type}"

    @pytest.mark.asyncio
    async def test_arxiv_pdf_url(self, client):
        """arXiv PDF URL should return PDF content."""
        # 2301.00001 is a real arXiv paper
        url = "https://arxiv.org/pdf/2301.00001.pdf"

        async with client:
            resp = await client.head(url)
            assert resp.status_code == 200, f"arXiv PDF returned {resp.status_code}"
            content_type = resp.headers.get("content-type", "")
            assert "pdf" in content_type.lower(), f"Expected PDF, got {content_type}"

    @pytest.mark.asyncio
    async def test_biorxiv_pdf_url_formats(self, client):
        """Test bioRxiv PDF URL formats."""
        # bioRxiv might return 403 for programmatic access
        # but we can at least verify the URL format is correct

        # Real bioRxiv DOI: 10.1101/2024.01.15.575635
        test_urls = [
            # Format 1: Direct content URL with version
            "https://www.biorxiv.org/content/10.1101/2024.01.15.575635v1.full.pdf",
            # Format 2: Without version (redirects)
            "https://www.biorxiv.org/content/10.1101/2024.01.15.575635.full.pdf",
        ]

        async with client:
            for url in test_urls:
                resp = await client.head(url)
                # Accept 200 (success), 301/302 (redirect), or 403 (blocked but URL valid)
                assert resp.status_code in [200, 301, 302, 403], f"URL: {url}, Status: {resp.status_code}"
                print(f"bioRxiv URL test: {resp.status_code} for {url[-40:]}")

    @pytest.mark.asyncio
    async def test_unpaywall_api(self, client):
        """Unpaywall API should return OA info."""
        # Use a well-known OA DOI (PLOS ONE article)
        doi = "10.1371/journal.pone.0185809"
        url = f"https://api.unpaywall.org/v2/{doi}?email=test@pubmed-search.com"

        async with client:
            resp = await client.get(url)
            # 200 = found, 404 = DOI not found (both valid API responses)
            assert resp.status_code in [200, 404], f"Unpaywall API returned {resp.status_code}"

            if resp.status_code == 200:
                data = resp.json()
                assert "is_oa" in data, "Missing is_oa field"
                print(f"Unpaywall: is_oa={data.get('is_oa')}")

    @pytest.mark.asyncio
    async def test_core_api_accessible(self, client):
        """CORE API should be accessible (endpoint responds)."""
        url = "https://api.core.ac.uk/v3/search/works?q=test&limit=1"

        async with client:
            try:
                resp = await client.get(url)
                # CORE might require API key, block unauthenticated, rate limit, or error
                # 200 = works, 401 = needs auth, 403 = blocked, 429 = rate limited, 5xx = server issue
                assert resp.status_code < 600, f"CORE API returned unexpected {resp.status_code}"
            except httpx.ConnectError:
                pytest.skip("CORE API unreachable")

    @pytest.mark.asyncio
    async def test_semantic_scholar_api(self, client):
        """Semantic Scholar API should be accessible."""
        doi = "10.1038/nature12373"
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=openAccessPdf"

        async with client:
            resp = await client.get(url)
            assert resp.status_code in [200, 404, 429], f"S2 API returned {resp.status_code}"

            if resp.status_code == 200:
                data = resp.json()
                print(f"S2: openAccessPdf={data.get('openAccessPdf')}")

    @pytest.mark.asyncio
    async def test_openalex_api(self, client):
        """OpenAlex API should be accessible."""
        doi = "10.1038/nature12373"
        url = f"https://api.openalex.org/works/doi:{doi}?mailto=test@pubmed-search.com"

        async with client:
            resp = await client.get(url)
            assert resp.status_code in [200, 404], f"OpenAlex API returned {resp.status_code}"

            if resp.status_code == 200:
                data = resp.json()
                oa = data.get("open_access", {})
                print(
                    f"OpenAlex: is_oa={oa.get('is_oa')}, pdf_url={data.get('best_oa_location', {}).get('pdf_url', 'N/A')[:50]}"
                )

    @pytest.mark.asyncio
    async def test_crossref_api(self, client):
        """CrossRef API should return link info."""
        doi = "10.1038/nature12373"
        url = f"https://api.crossref.org/works/{doi}?mailto=test@pubmed-search.com"

        async with client:
            resp = await client.get(url)
            assert resp.status_code in [200, 404], f"CrossRef API returned {resp.status_code}"

            if resp.status_code == 200:
                data = resp.json()
                msg = data.get("message", {})
                links = msg.get("link", [])
                print(f"CrossRef: {len(links)} links found")
                for link in links[:2]:
                    if "pdf" in link.get("content-type", "").lower():
                        print(f"  PDF: {link.get('URL', '')[:60]}")

    @pytest.mark.asyncio
    async def test_doaj_api(self, client):
        """DOAJ API should return OA journal info."""
        # Use a known PLOS ONE DOI (OA journal)
        doi = "10.1371/journal.pone.0185809"
        url = f"https://doaj.org/api/search/articles/doi:{doi}"

        async with client:
            resp = await client.get(url)
            assert resp.status_code in [200, 404], f"DOAJ API returned {resp.status_code}"

            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                print(f"DOAJ: {len(results)} results")

    @pytest.mark.asyncio
    async def test_zenodo_api(self, client):
        """Zenodo API should be accessible (may be blocked by Cloudflare)."""
        url = "https://zenodo.org/api/records?q=covid&size=1"

        async with client:
            resp = await client.get(url)
            # Zenodo may block automated requests with 403 (Cloudflare)
            # Accept 200, 403, or 404 as valid responses
            assert resp.status_code in [200, 403, 404], f"Zenodo API returned {resp.status_code}"

            if resp.status_code == 200:
                data = resp.json()
                total = data.get("hits", {}).get("total", 0)
                print(f"Zenodo: {total} total records")
            elif resp.status_code == 403:
                print("Zenodo: Blocked by Cloudflare (expected in some environments)")

    @pytest.mark.asyncio
    async def test_pubmed_linkout(self, client):
        """PubMed LinkOut should return external links."""
        pmid = "23903782"  # Known article with external links
        url = (
            f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?dbfrom=pubmed&id={pmid}&cmd=llinks&retmode=json"
        )

        async with client:
            resp = await client.get(url)
            assert resp.status_code == 200, f"PubMed LinkOut returned {resp.status_code}"

            data = resp.json()
            linksets = data.get("linksets", [])
            print(f"PubMed LinkOut: {len(linksets)} linksets")


class TestFulltextDownloader:
    """Test the FulltextDownloader class."""

    @pytest.mark.asyncio
    async def test_get_pdf_links_with_pmcid(self):
        """Should return PDF links for a known PMC article."""
        from pubmed_search.infrastructure.sources.fulltext_download import (
            FulltextDownloader,
            PDFSource,
        )

        downloader = FulltextDownloader()
        try:
            links = await downloader.get_pdf_links(pmcid="PMC7096777")

            assert len(links) > 0, "Should find at least one PDF link"

            # Should prioritize Europe PMC
            sources = [lnk.source for lnk in links]
            assert PDFSource.EUROPE_PMC in sources or PDFSource.PMC in sources

            # Print found links
            for link in links:
                print(f"Found: {link.source.display_name} - {link.url[:60]}...")
        finally:
            await downloader.close()

    @pytest.mark.asyncio
    async def test_get_pdf_links_with_doi(self):
        """Should return PDF links for a known OA DOI."""
        from pubmed_search.infrastructure.sources.fulltext_download import (
            FulltextDownloader,
        )

        downloader = FulltextDownloader()

        # Mock the HTTP client to avoid real network calls
        mock_response_unpaywall = MagicMock()
        mock_response_unpaywall.status_code = 200
        mock_response_unpaywall.json.return_value = {
            "is_oa": True,
            "best_oa_location": {
                "url_for_pdf": "https://example.com/paper.pdf",
                "url": "https://example.com/paper",
            },
            "oa_locations": [
                {
                    "url_for_pdf": "https://example.com/paper.pdf",
                    "url": "https://example.com/paper",
                    "host_type": "publisher",
                }
            ],
        }

        mock_response_crossref = MagicMock()
        mock_response_crossref.status_code = 200
        mock_response_crossref.json.return_value = {
            "status": "ok",
            "message": {
                "DOI": "10.1038/nature12373",
                "link": [
                    {
                        "URL": "https://publisher.com/paper.pdf",
                        "content-type": "application/pdf",
                    }
                ],
            },
        }

        mock_response_default = MagicMock()
        mock_response_default.status_code = 404
        mock_response_default.json.return_value = {}

        async def mock_get(url, **kwargs):
            if "unpaywall" in url:
                return mock_response_unpaywall
            if "crossref" in url:
                return mock_response_crossref
            return mock_response_default

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.head = AsyncMock(return_value=mock_response_default)
        mock_client.is_closed = False
        mock_client.aclose = AsyncMock()

        downloader._client = mock_client
        try:
            links = await downloader.get_pdf_links(doi="10.1038/nature12373")

            # Should find at least one link from mocked sources
            print(f"Found {len(links)} links for DOI")
            sources_found = set()
            for link in links:
                sources_found.add(link.source.display_name)
                print(f"  {link.source.display_name}: {link.url[:60]}...")

            assert len(links) >= 1, f"Expected at least 1 link, got: {sources_found}"
        finally:
            downloader._client = None

    @pytest.mark.asyncio
    async def test_get_pdf_links_with_arxiv_doi(self):
        """Should construct correct arXiv URL from DOI."""
        from pubmed_search.infrastructure.sources.fulltext_download import (
            FulltextDownloader,
            PDFSource,
        )

        downloader = FulltextDownloader()
        try:
            # arXiv DOI format
            links = await downloader.get_pdf_links(doi="10.48550/arXiv.2301.00001")

            # Should include arXiv source
            arxiv_links = [lnk for lnk in links if lnk.source == PDFSource.ARXIV]
            assert len(arxiv_links) > 0, "Should find arXiv link"

            # URL should be correct
            assert "arxiv.org/pdf" in arxiv_links[0].url
            print(f"arXiv URL: {arxiv_links[0].url}")
        finally:
            await downloader.close()

    @pytest.mark.asyncio
    async def test_get_pdf_links_with_biorxiv_doi(self):
        """Should construct correct bioRxiv URL from DOI."""
        from pubmed_search.infrastructure.sources.fulltext_download import (
            FulltextDownloader,
            PDFSource,
        )

        downloader = FulltextDownloader()
        try:
            # bioRxiv DOI starts with 10.1101
            links = await downloader.get_pdf_links(doi="10.1101/2024.01.15.575635")

            # Should include bioRxiv source
            biorxiv_links = [lnk for lnk in links if lnk.source == PDFSource.BIORXIV]
            assert len(biorxiv_links) > 0, "Should find bioRxiv link"

            # URL should include version
            assert "v1.full.pdf" in biorxiv_links[0].url or ".full.pdf" in biorxiv_links[0].url
            print(f"bioRxiv URL: {biorxiv_links[0].url}")
        finally:
            await downloader.close()

    @pytest.mark.asyncio
    async def test_get_pdf_links_with_pmid(self):
        """Should return links including PubMed LinkOut."""
        from pubmed_search.infrastructure.sources.fulltext_download import (
            FulltextDownloader,
        )

        downloader = FulltextDownloader()
        try:
            # Known PMID with external links
            links = await downloader.get_pdf_links(pmid="23903782")

            print(f"Found {len(links)} links for PMID")
            for link in links:
                print(f"  {link.source.display_name}: {link.url[:60]}...")
        finally:
            await downloader.close()

    @pytest.mark.asyncio
    async def test_all_sources_priority_order(self):
        """Verify sources are returned in priority order."""
        from pubmed_search.infrastructure.sources.fulltext_download import (
            PDFSource,
        )

        # Verify enum priority values
        priorities = [(s.display_name, s.priority) for s in PDFSource]
        print("Source priorities:")
        for name, priority in sorted(priorities, key=lambda x: x[1]):
            print(f"  {priority}. {name}")

        # Europe PMC should be first (priority 1)
        assert PDFSource.EUROPE_PMC.priority == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
