"""Tests for UnpaywallClient."""

import json
from unittest.mock import MagicMock, patch

import pytest

from pubmed_search.infrastructure.sources.unpaywall import (
    UnpaywallClient,
    find_oa_link,
    find_pdf_link,
    is_open_access,
    get_oa_status,
    DEFAULT_EMAIL,
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
    def test_defaults(self):
        c = UnpaywallClient()
        assert c._email == DEFAULT_EMAIL

    def test_custom_email(self, client):
        assert client._email == "test@example.com"


# ============================================================
# _make_request
# ============================================================

class TestMakeRequest:
    @patch("urllib.request.urlopen")
    def test_success(self, mock_urlopen, client):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"is_oa": True}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        result = client._make_request("https://api.unpaywall.org/v2/test")
        assert result == {"is_oa": True}

    @patch("urllib.request.urlopen")
    def test_404(self, mock_urlopen, client):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError("url", 404, "Not Found", {}, None)
        assert client._make_request("https://test.com") is None

    @patch("urllib.request.urlopen")
    def test_422(self, mock_urlopen, client):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError("url", 422, "Invalid DOI", {}, None)
        assert client._make_request("https://test.com") is None

    @patch("urllib.request.urlopen")
    def test_429(self, mock_urlopen, client):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError("url", 429, "Rate limit", {}, None)
        assert client._make_request("https://test.com") is None

    @patch("urllib.request.urlopen")
    def test_500(self, mock_urlopen, client):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError("url", 500, "Server Error", {}, None)
        assert client._make_request("https://test.com") is None

    @patch("urllib.request.urlopen")
    def test_url_error(self, mock_urlopen, client):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("DNS failed")
        assert client._make_request("https://test.com") is None

    @patch("urllib.request.urlopen")
    def test_generic_error(self, mock_urlopen, client):
        mock_urlopen.side_effect = Exception("unexpected")
        assert client._make_request("https://test.com") is None


# ============================================================
# get_oa_status
# ============================================================

class TestGetOAStatus:
    @patch.object(UnpaywallClient, "_make_request")
    def test_success(self, mock_req, client):
        mock_req.return_value = {
            "doi": "10.1234/test",
            "is_oa": True,
            "oa_status": "gold",
            "best_oa_location": {"url": "https://oa.example.com", "host_type": "publisher"},
            "oa_locations": [],
            "title": "Test Paper",
            "year": 2023,
            "journal_name": "Nature",
            "journal_issns": "1234-5678",
            "publisher": "Springer",
            "is_paratext": False,
            "updated": "2023-01-01",
        }
        result = client.get_oa_status("10.1234/test")
        assert result is not None
        assert result["is_oa"] is True
        assert result["oa_status"] == "gold"

    @patch.object(UnpaywallClient, "_make_request")
    def test_not_found(self, mock_req, client):
        mock_req.return_value = None
        assert client.get_oa_status("10.xxxx/fake") is None

    def test_normalize_doi_strips_prefix(self, client):
        assert client._normalize_doi("https://doi.org/10.1234/test") == "10.1234/test"
        assert client._normalize_doi("http://doi.org/10.1234/test") == "10.1234/test"
        assert client._normalize_doi("doi:10.1234/test") == "10.1234/test"
        assert client._normalize_doi("  10.1234/test  ") == "10.1234/test"


# ============================================================
# get_best_oa_link
# ============================================================

class TestGetBestOALink:
    @patch.object(UnpaywallClient, "get_oa_status")
    def test_found(self, mock_status, client):
        mock_status.return_value = {
            "is_oa": True,
            "best_oa_location": {"url": "https://oa.example.com", "url_for_pdf": "https://pdf.example.com"},
        }
        link = client.get_best_oa_link("10.1234/test")
        assert link == "https://oa.example.com"

    @patch.object(UnpaywallClient, "get_oa_status")
    def test_pdf_fallback(self, mock_status, client):
        mock_status.return_value = {
            "is_oa": True,
            "best_oa_location": {"url": None, "url_for_pdf": "https://pdf.example.com"},
        }
        link = client.get_best_oa_link("10.1234/test")
        assert link == "https://pdf.example.com"

    @patch.object(UnpaywallClient, "get_oa_status")
    def test_not_oa(self, mock_status, client):
        mock_status.return_value = {"is_oa": False}
        assert client.get_best_oa_link("10.1234/test") is None

    @patch.object(UnpaywallClient, "get_oa_status")
    def test_none_response(self, mock_status, client):
        mock_status.return_value = None
        assert client.get_best_oa_link("10.1234/test") is None


# ============================================================
# get_pdf_link
# ============================================================

class TestGetPdfLink:
    @patch.object(UnpaywallClient, "get_oa_status")
    def test_best_location_has_pdf(self, mock_status, client):
        mock_status.return_value = {
            "is_oa": True,
            "best_oa_location": {"url_for_pdf": "https://pdf.example.com/best.pdf"},
            "oa_locations": [],
        }
        assert client.get_pdf_link("10.1234/test") == "https://pdf.example.com/best.pdf"

    @patch.object(UnpaywallClient, "get_oa_status")
    def test_fallback_location(self, mock_status, client):
        mock_status.return_value = {
            "is_oa": True,
            "best_oa_location": {},
            "oa_locations": [
                {"url_for_pdf": None},
                {"url_for_pdf": "https://pdf.example.com/alt.pdf"},
            ],
        }
        assert client.get_pdf_link("10.1234/test") == "https://pdf.example.com/alt.pdf"

    @patch.object(UnpaywallClient, "get_oa_status")
    def test_no_pdf_anywhere(self, mock_status, client):
        mock_status.return_value = {
            "is_oa": True,
            "best_oa_location": {},
            "oa_locations": [{"url_for_pdf": None}],
        }
        assert client.get_pdf_link("10.1234/test") is None

    @patch.object(UnpaywallClient, "get_oa_status")
    def test_not_oa(self, mock_status, client):
        mock_status.return_value = {"is_oa": False}
        assert client.get_pdf_link("10.1234/test") is None

    @patch.object(UnpaywallClient, "get_oa_status")
    def test_none(self, mock_status, client):
        mock_status.return_value = None
        assert client.get_pdf_link("10.1234/test") is None


# ============================================================
# batch_get_oa_status
# ============================================================

class TestBatchGetOAStatus:
    @patch.object(UnpaywallClient, "get_oa_status")
    def test_batch(self, mock_status, client):
        mock_status.side_effect = [
            {"is_oa": True, "doi": "10.1"},
            None,
            {"is_oa": False, "doi": "10.3"},
        ]
        results = client.batch_get_oa_status(["10.1", "10.2", "10.3"])
        assert len(results) == 3
        assert results["10.1"]["is_oa"] is True
        assert results["10.2"] is None
        assert results["10.3"]["is_oa"] is False


# ============================================================
# enrich_article
# ============================================================

class TestEnrichArticle:
    @patch.object(UnpaywallClient, "get_oa_status")
    def test_oa_article(self, mock_status, client):
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
            "oa_locations": [{
                "url": "https://pub.example.com",
                "url_for_pdf": "https://pub.example.com/pdf",
                "version": "publishedVersion",
                "host_type": "publisher",
                "license": "cc-by",
            }],
        }
        result = client.enrich_article("10.1234/test")
        assert result["is_oa"] is True
        assert result["oa_status"] == "gold"
        assert len(result["oa_links"]) == 1

    @patch.object(UnpaywallClient, "get_oa_status")
    def test_not_found(self, mock_status, client):
        mock_status.return_value = None
        result = client.enrich_article("10.xxxx/fake")
        assert result["is_oa"] is False
        assert result["oa_links"] == []


# ============================================================
# Static methods
# ============================================================

class TestStaticMethods:
    def test_get_oa_status_description(self):
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
    def test_find_oa_link(self):
        import pubmed_search.infrastructure.sources.unpaywall as mod
        mod._unpaywall_client = None
        with patch.object(UnpaywallClient, "get_best_oa_link", return_value="https://oa.example.com"):
            result = find_oa_link("10.1234/test")
            assert result == "https://oa.example.com"
        mod._unpaywall_client = None

    def test_find_pdf_link(self):
        import pubmed_search.infrastructure.sources.unpaywall as mod
        mod._unpaywall_client = None
        with patch.object(UnpaywallClient, "get_pdf_link", return_value="https://pdf.example.com"):
            result = find_pdf_link("10.1234/test")
            assert result == "https://pdf.example.com"
        mod._unpaywall_client = None

    def test_is_open_access(self):
        import pubmed_search.infrastructure.sources.unpaywall as mod
        mod._unpaywall_client = None
        with patch.object(UnpaywallClient, "get_oa_status", return_value={"is_oa": True}):
            assert is_open_access("10.1234/test") is True
        mod._unpaywall_client = None

    def test_is_open_access_none(self):
        import pubmed_search.infrastructure.sources.unpaywall as mod
        mod._unpaywall_client = None
        with patch.object(UnpaywallClient, "get_oa_status", return_value=None):
            assert is_open_access("10.1234/test") is False
        mod._unpaywall_client = None

    def test_get_oa_status_func(self):
        import pubmed_search.infrastructure.sources.unpaywall as mod
        mod._unpaywall_client = None
        with patch.object(UnpaywallClient, "get_oa_status", return_value={"oa_status": "gold"}):
            assert get_oa_status("10.1234/test") == "gold"
        mod._unpaywall_client = None

    def test_get_oa_status_func_none(self):
        import pubmed_search.infrastructure.sources.unpaywall as mod
        mod._unpaywall_client = None
        with patch.object(UnpaywallClient, "get_oa_status", return_value=None):
            assert get_oa_status("10.1234/test") == "unknown"
        mod._unpaywall_client = None
