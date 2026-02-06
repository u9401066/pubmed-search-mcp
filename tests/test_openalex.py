"""Tests for OpenAlexClient."""

import json
from unittest.mock import MagicMock, patch

import pytest

from pubmed_search.infrastructure.sources.openalex import (
    OpenAlexClient,
    DEFAULT_EMAIL,
)


@pytest.fixture
def client():
    c = OpenAlexClient(email="test@example.com")
    c._last_request_time = 0
    c._min_interval = 0
    return c


# ============================================================
# Init
# ============================================================

class TestInit:
    def test_defaults(self):
        c = OpenAlexClient()
        assert c._email == DEFAULT_EMAIL

    def test_context_manager(self):
        with OpenAlexClient() as c:
            assert c is not None
        c.close()


# ============================================================
# _make_request
# ============================================================

class TestMakeRequest:
    @patch("urllib.request.urlopen")
    def test_success(self, mock_urlopen, client):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"results": []}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        result = client._make_request("https://api.openalex.org/test")
        assert result == {"results": []}

    @patch("urllib.request.urlopen")
    def test_http_error(self, mock_urlopen, client):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError("url", 500, "Error", {}, None)
        assert client._make_request("https://test.com") is None

    @patch("urllib.request.urlopen")
    def test_url_error(self, mock_urlopen, client):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("DNS failed")
        assert client._make_request("https://test.com") is None


# ============================================================
# search
# ============================================================

class TestSearch:
    @patch.object(OpenAlexClient, "_make_request")
    def test_basic(self, mock_req, client):
        mock_req.return_value = {"results": [{
            "id": "W123",
            "display_name": "Test Paper",
            "publication_date": "2023-06-15",
            "publication_year": 2023,
            "authorships": [{"author": {"display_name": "John Doe"}}],
            "ids": {"doi": "https://doi.org/10.1234/test", "pmid": "https://pubmed.ncbi.nlm.nih.gov/12345/"},
            "cited_by_count": 50,
            "open_access": {"is_oa": True, "oa_status": "gold"},
            "best_oa_location": {"pdf_url": "https://pdf.example.com"},
            "primary_location": {"source": {"display_name": "Nature", "is_in_doaj": False}},
        }]}
        results = client.search("deep learning")
        assert len(results) == 1
        assert results[0]["title"] == "Test Paper"
        assert results[0]["doi"] == "10.1234/test"
        assert results[0]["pmid"] == "12345"
        assert results[0]["year"] == "2023"
        assert results[0]["month"] == "06"
        assert results[0]["day"] == "15"
        assert results[0]["_source"] == "openalex"

    @patch.object(OpenAlexClient, "_make_request")
    def test_with_filters(self, mock_req, client):
        mock_req.return_value = {"results": []}
        client.search("test", min_year=2020, max_year=2024, open_access_only=True, is_doaj=True)
        url = mock_req.call_args[0][0]
        assert "is_oa%3Atrue" in url or "is_oa:true" in url
        assert "2020" in url

    @patch.object(OpenAlexClient, "_make_request")
    def test_with_sort(self, mock_req, client):
        mock_req.return_value = {"results": []}
        client.search("test", sort="cited_by_count:desc")
        url = mock_req.call_args[0][0]
        assert "sort=" in url

    @patch.object(OpenAlexClient, "_make_request")
    def test_limit_capped(self, mock_req, client):
        mock_req.return_value = {"results": []}
        client.search("test", limit=500)
        url = mock_req.call_args[0][0]
        assert "per_page=200" in url

    @patch.object(OpenAlexClient, "_make_request")
    def test_returns_empty_on_none(self, mock_req, client):
        mock_req.return_value = None
        assert client.search("test") == []

    @patch.object(OpenAlexClient, "_make_request")
    def test_exception(self, mock_req, client):
        mock_req.side_effect = Exception("fail")
        assert client.search("test") == []


# ============================================================
# get_work
# ============================================================

class TestGetWork:
    @patch.object(OpenAlexClient, "_make_request")
    def test_by_doi(self, mock_req, client):
        mock_req.return_value = {
            "id": "W123",
            "display_name": "Test",
            "ids": {"doi": "https://doi.org/10.1234/test"},
        }
        result = client.get_work("10.1234/test")
        assert result is not None
        assert result["title"] == "Test"

    @patch.object(OpenAlexClient, "_make_request")
    def test_by_pmid(self, mock_req, client):
        mock_req.return_value = {
            "id": "W456",
            "display_name": "PMID Test",
            "ids": {},
        }
        result = client.get_work("12345")
        assert result is not None

    @patch.object(OpenAlexClient, "_make_request")
    def test_not_found(self, mock_req, client):
        mock_req.return_value = None
        assert client.get_work("W999") is None

    @patch.object(OpenAlexClient, "_make_request")
    def test_exception(self, mock_req, client):
        mock_req.side_effect = Exception("fail")
        assert client.get_work("W1") is None


# ============================================================
# get_citations
# ============================================================

class TestGetCitations:
    @patch.object(OpenAlexClient, "_make_request")
    def test_success(self, mock_req, client):
        mock_req.return_value = {"results": [
            {"id": "W1", "display_name": "Citing Paper", "ids": {}},
        ]}
        results = client.get_citations("W123")
        assert len(results) == 1

    @patch.object(OpenAlexClient, "_make_request")
    def test_empty(self, mock_req, client):
        mock_req.return_value = None
        assert client.get_citations("W123") == []

    @patch.object(OpenAlexClient, "_make_request")
    def test_exception(self, mock_req, client):
        mock_req.side_effect = Exception("fail")
        assert client.get_citations("W123") == []


# ============================================================
# _normalize_work
# ============================================================

class TestNormalizeWork:
    def test_full_work(self, client):
        work = {
            "id": "https://openalex.org/W123",
            "display_name": "Test Paper",
            "abstract_inverted_index": {"Hello": [0], "world": [1]},
            "publication_date": "2023-06-15",
            "publication_year": 2023,
            "authorships": [
                {"author": {"display_name": "John Smith"}},
                {"author": {"display_name": "Jane"}},
            ],
            "ids": {
                "doi": "https://doi.org/10.1234/test",
                "pmid": "https://pubmed.ncbi.nlm.nih.gov/12345/",
                "pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC999/",
            },
            "cited_by_count": 50,
            "open_access": {"is_oa": True, "oa_status": "gold"},
            "best_oa_location": {"pdf_url": "https://pdf.example.com"},
            "primary_location": {"source": {"display_name": "Nature", "is_in_doaj": True}},
        }
        result = client._normalize_work(work)
        assert result["doi"] == "10.1234/test"
        assert result["pmid"] == "12345"
        assert "PMC" in result["pmc_id"]
        assert result["title"] == "Test Paper"
        assert result["citation_count"] == 50
        assert result["is_open_access"] is True
        assert result["is_doaj"] is True
        assert len(result["authors"]) == 2
        assert result["authors_full"][0]["last_name"] == "Smith"

    def test_minimal_work(self, client):
        work = {"id": "W1"}
        result = client._normalize_work(work)
        assert result["title"] == ""
        assert result["doi"] == ""
        assert result["_source"] == "openalex"

    def test_single_name_author(self, client):
        work = {"authorships": [{"author": {"display_name": "Madonna"}}]}
        result = client._normalize_work(work)
        assert result["authors_full"][0]["last_name"] == "Madonna"

    def test_none_ids(self, client):
        work = {"ids": None}
        result = client._normalize_work(work)
        assert result["doi"] == ""

    def test_none_authorships(self, client):
        work = {"authorships": None}
        result = client._normalize_work(work)
        assert result["authors"] == []

    def test_none_primary_location(self, client):
        work = {"primary_location": None}
        result = client._normalize_work(work)
        assert result["journal"] == ""

    def test_title_fallback(self, client):
        work = {"title": "Fallback Title"}
        result = client._normalize_work(work)
        assert result["title"] == "Fallback Title"


# ============================================================
# _get_abstract
# ============================================================

class TestGetAbstract:
    def test_inverted_index(self, client):
        work = {"abstract_inverted_index": {
            "This": [0],
            "is": [1],
            "a": [2],
            "test": [3],
        }}
        abstract = client._get_abstract(work)
        assert abstract == "This is a test"

    def test_no_abstract(self, client):
        assert client._get_abstract({}) == ""

    def test_none_abstract(self, client):
        assert client._get_abstract({"abstract_inverted_index": None}) == ""

    def test_multi_position_words(self, client):
        work = {"abstract_inverted_index": {
            "the": [0, 3],
            "cat": [1],
            "sat": [2],
            "mat": [4],
        }}
        abstract = client._get_abstract(work)
        assert abstract == "the cat sat the mat"
