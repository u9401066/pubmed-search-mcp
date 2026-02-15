"""Tests for UnpaywallClient."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pubmed_search.infrastructure.sources.unpaywall import (
    DEFAULT_EMAIL,
    UnpaywallClient,
    find_oa_link,
    find_pdf_link,
    get_oa_status,
    is_open_access,
)


@pytest.fixture
def client():
    c = UnpaywallClient(email="test@example.com")
    c._last_request_time = 0
    c._min_interval = 0
    return c


# ============================================================
# Init
# ============================================================


class TestInit:
    async def test_defaults(self):
        c = UnpaywallClient()
        assert c._email == DEFAULT_EMAIL

    async def test_custom_email(self, client):
        assert client._email == "test@example.com"


# ============================================================
# _make_request
# ============================================================


class TestMakeRequest:
    async def test_success(self, client):
        from unittest.mock import AsyncMock

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"is_oa": True}
        mock_response.raise_for_status = MagicMock()
        client._client = MagicMock()
        client._client.get = AsyncMock(return_value=mock_response)
        result = await client._make_request("https://api.unpaywall.org/v2/test")
        assert result == {"is_oa": True}

    async def test_404(self, client):
        from unittest.mock import AsyncMock

        mock_response = MagicMock()
        mock_response.status_code = 404
        client._client = MagicMock()
        client._client.get = AsyncMock(return_value=mock_response)
        assert await client._make_request("https://test.com") is None

    async def test_422(self, client):
        from unittest.mock import AsyncMock

        mock_response = MagicMock()
        mock_response.status_code = 422
        client._client = MagicMock()
        client._client.get = AsyncMock(return_value=mock_response)
        assert await client._make_request("https://test.com") is None

    async def test_429(self, client):
        from unittest.mock import AsyncMock

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "0"}
        client._client = MagicMock()
        client._client.get = AsyncMock(return_value=mock_response)
        assert await client._make_request("https://test.com") is None

    async def test_500(self, client):
        from unittest.mock import AsyncMock

        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.reason_phrase = "Server Error"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )
        client._client = MagicMock()
        client._client.get = AsyncMock(return_value=mock_response)
        assert await client._make_request("https://test.com") is None

    async def test_url_error(self, client):
        from unittest.mock import AsyncMock

        import httpx

        client._client = MagicMock()
        client._client.get = AsyncMock(side_effect=httpx.RequestError("DNS failed", request=MagicMock()))
        assert await client._make_request("https://test.com") is None

    async def test_generic_error(self, client):
        from unittest.mock import AsyncMock

        client._client = MagicMock()
        client._client.get = AsyncMock(side_effect=Exception("unexpected"))
        assert await client._make_request("https://test.com") is None


# ============================================================
# get_oa_status
# ============================================================


class TestGetOAStatus:
    @patch.object(UnpaywallClient, "_make_request")
    async def test_success(self, mock_req, client):
        mock_req.return_value = {
            "doi": "10.1234/test",
            "is_oa": True,
            "oa_status": "gold",
            "best_oa_location": {
                "url": "https://oa.example.com",
                "host_type": "publisher",
            },
            "oa_locations": [],
            "title": "Test Paper",
            "year": 2023,
            "journal_name": "Nature",
            "journal_issns": "1234-5678",
            "publisher": "Springer",
            "is_paratext": False,
            "updated": "2023-01-01",
        }
        result = await client.get_oa_status("10.1234/test")
        assert result is not None
        assert result["is_oa"] is True
        assert result["oa_status"] == "gold"

    @patch.object(UnpaywallClient, "_make_request")
    async def test_not_found(self, mock_req, client):
        mock_req.return_value = None
        assert await client.get_oa_status("10.xxxx/fake") is None

    async def test_normalize_doi_strips_prefix(self, client):
        assert client._normalize_doi("https://doi.org/10.1234/test") == "10.1234/test"
        assert client._normalize_doi("http://doi.org/10.1234/test") == "10.1234/test"
        assert client._normalize_doi("doi:10.1234/test") == "10.1234/test"
        assert client._normalize_doi("  10.1234/test  ") == "10.1234/test"

    @patch.object(UnpaywallClient, "_make_request", return_value=None)
    async def test_doi_slash_not_encoded_in_url(self, mock_req, client):
        """DOI slashes must stay literal in the URL (not %2F) or Unpaywall returns 422."""
        await client.get_oa_status("10.23736/S0375-9393.21.15517-8")
        url_called = mock_req.call_args[0][0]
        # The DOI slash should appear as '/' not '%2F'
        assert "/10.23736/S0375-9393.21.15517-8?" in url_called
        assert "%2F" not in url_called.split("?")[0]  # no encoded slash in path


# ============================================================
# get_best_oa_link
# ============================================================


class TestGetBestOALink:
    @patch.object(UnpaywallClient, "get_oa_status")
    async def test_found(self, mock_status, client):
        mock_status.return_value = {
            "is_oa": True,
            "best_oa_location": {
                "url": "https://oa.example.com",
                "url_for_pdf": "https://pdf.example.com",
            },
        }
        link = await client.get_best_oa_link("10.1234/test")
        assert link == "https://oa.example.com"

    @patch.object(UnpaywallClient, "get_oa_status")
    async def test_pdf_fallback(self, mock_status, client):
        mock_status.return_value = {
            "is_oa": True,
            "best_oa_location": {"url": None, "url_for_pdf": "https://pdf.example.com"},
        }
        link = await client.get_best_oa_link("10.1234/test")
        assert link == "https://pdf.example.com"

    @patch.object(UnpaywallClient, "get_oa_status")
    async def test_not_oa(self, mock_status, client):
        mock_status.return_value = {"is_oa": False}
        assert await client.get_best_oa_link("10.1234/test") is None

    @patch.object(UnpaywallClient, "get_oa_status")
    async def test_none_response(self, mock_status, client):
        mock_status.return_value = None
        assert await client.get_best_oa_link("10.1234/test") is None


# ============================================================
# get_pdf_link
# ============================================================


class TestGetPdfLink:
    @patch.object(UnpaywallClient, "get_oa_status")
    async def test_best_location_has_pdf(self, mock_status, client):
        mock_status.return_value = {
            "is_oa": True,
            "best_oa_location": {"url_for_pdf": "https://pdf.example.com/best.pdf"},
            "oa_locations": [],
        }
        assert await client.get_pdf_link("10.1234/test") == "https://pdf.example.com/best.pdf"

    @patch.object(UnpaywallClient, "get_oa_status")
    async def test_fallback_location(self, mock_status, client):
        mock_status.return_value = {
            "is_oa": True,
            "best_oa_location": {},
            "oa_locations": [
                {"url_for_pdf": None},
                {"url_for_pdf": "https://pdf.example.com/alt.pdf"},
            ],
        }
        assert await client.get_pdf_link("10.1234/test") == "https://pdf.example.com/alt.pdf"

    @patch.object(UnpaywallClient, "get_oa_status")
    async def test_no_pdf_anywhere(self, mock_status, client):
        mock_status.return_value = {
            "is_oa": True,
            "best_oa_location": {},
            "oa_locations": [{"url_for_pdf": None}],
        }
        assert await client.get_pdf_link("10.1234/test") is None

    @patch.object(UnpaywallClient, "get_oa_status")
    async def test_not_oa(self, mock_status, client):
        mock_status.return_value = {"is_oa": False}
        assert await client.get_pdf_link("10.1234/test") is None

    @patch.object(UnpaywallClient, "get_oa_status")
    async def test_none(self, mock_status, client):
        mock_status.return_value = None
        assert await client.get_pdf_link("10.1234/test") is None


# ============================================================
# batch_get_oa_status
# ============================================================


class TestBatchGetOAStatus:
    @patch.object(UnpaywallClient, "get_oa_status")
    async def test_batch(self, mock_status, client):
        mock_status.side_effect = [
            {"is_oa": True, "doi": "10.1"},
            None,
            {"is_oa": False, "doi": "10.3"},
        ]
        results = await client.batch_get_oa_status(["10.1", "10.2", "10.3"])
        assert len(results) == 3
        assert results["10.1"]["is_oa"] is True
        assert results["10.2"] is None
        assert results["10.3"]["is_oa"] is False


# ============================================================
# enrich_article
# ============================================================


class TestEnrichArticle:
    @patch.object(UnpaywallClient, "get_oa_status")
    async def test_oa_article(self, mock_status, client):
        mock_status.return_value = {
            "is_oa": True,
            "oa_status": "gold",
            "best_oa_location": {
                "url": "https://pub.example.com",
                "url_for_pdf": "https://pub.example.com/pdf",
                "version": "publishedVersion",
                "host_type": "publisher",
                "license": "cc-by",
            },
            "oa_locations": [
                {
                    "url": "https://pub.example.com",
                    "url_for_pdf": "https://pub.example.com/pdf",
                    "version": "publishedVersion",
                    "host_type": "publisher",
                    "license": "cc-by",
                }
            ],
        }
        result = await client.enrich_article("10.1234/test")
        assert result["is_oa"] is True
        assert result["oa_status"] == "gold"
        assert len(result["oa_links"]) == 1

    @patch.object(UnpaywallClient, "get_oa_status")
    async def test_not_found(self, mock_status, client):
        mock_status.return_value = None
        result = await client.enrich_article("10.xxxx/fake")
        assert result["is_oa"] is False
        assert result["oa_links"] == []


# ============================================================
# Static methods
# ============================================================


class TestStaticMethods:
    async def test_get_oa_status_description(self):
        assert "OA journal" in UnpaywallClient.get_oa_status_description("gold")
        assert "repository" in UnpaywallClient.get_oa_status_description("green")
        assert "subscription" in UnpaywallClient.get_oa_status_description("hybrid")
        assert "Free to read" in UnpaywallClient.get_oa_status_description("bronze")
        assert "paywall" in UnpaywallClient.get_oa_status_description("closed")
        assert "not determined" in UnpaywallClient.get_oa_status_description("unknown")
        assert "Unknown" in UnpaywallClient.get_oa_status_description("XXX")


# ============================================================
# Convenience functions
# ============================================================


class TestConvenienceFunctions:
    async def test_find_oa_link(self):
        import pubmed_search.infrastructure.sources.unpaywall as mod

        mod._unpaywall_client = None
        with patch.object(UnpaywallClient, "get_best_oa_link", return_value="https://oa.example.com"):
            result = await find_oa_link("10.1234/test")
            assert result == "https://oa.example.com"
        mod._unpaywall_client = None

    async def test_find_pdf_link(self):
        import pubmed_search.infrastructure.sources.unpaywall as mod

        mod._unpaywall_client = None
        with patch.object(UnpaywallClient, "get_pdf_link", return_value="https://pdf.example.com"):
            result = await find_pdf_link("10.1234/test")
            assert result == "https://pdf.example.com"
        mod._unpaywall_client = None

    async def test_is_open_access(self):
        import pubmed_search.infrastructure.sources.unpaywall as mod

        mod._unpaywall_client = None
        with patch.object(UnpaywallClient, "get_oa_status", return_value={"is_oa": True}):
            assert await is_open_access("10.1234/test") is True
        mod._unpaywall_client = None

    async def test_is_open_access_none(self):
        import pubmed_search.infrastructure.sources.unpaywall as mod

        mod._unpaywall_client = None
        with patch.object(UnpaywallClient, "get_oa_status", return_value=None):
            assert await is_open_access("10.1234/test") is False
        mod._unpaywall_client = None

    async def test_get_oa_status_func(self):
        import pubmed_search.infrastructure.sources.unpaywall as mod

        mod._unpaywall_client = None
        with patch.object(UnpaywallClient, "get_oa_status", return_value={"oa_status": "gold"}):
            assert await get_oa_status("10.1234/test") == "gold"
        mod._unpaywall_client = None

    async def test_get_oa_status_func_none(self):
        import pubmed_search.infrastructure.sources.unpaywall as mod

        mod._unpaywall_client = None
        with patch.object(UnpaywallClient, "get_oa_status", return_value=None):
            assert await get_oa_status("10.1234/test") == "unknown"
        mod._unpaywall_client = None
