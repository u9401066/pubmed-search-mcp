"""Tests for OpenAlexClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from pubmed_search.infrastructure.sources.openalex import (
    DEFAULT_EMAIL,
    OpenAlexClient,
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
    async def test_defaults(self):
        c = OpenAlexClient()
        assert c._email == DEFAULT_EMAIL
        assert c._api_key is None
        assert c._auth_params == {"mailto": DEFAULT_EMAIL}

    async def test_api_key_overrides_mailto_auth(self):
        c = OpenAlexClient(email="test@example.com", api_key="oa-key")
        assert c._api_key == "oa-key"
        assert c._auth_params == {"api_key": "oa-key"}

    async def test_context_manager(self):
        async with OpenAlexClient() as c:
            assert c is not None


# ============================================================
# _make_request
# ============================================================


class TestMakeRequest:
    async def test_success(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)
        result = await client._make_request("https://api.openalex.org/test")
        assert result == {"results": []}

    async def test_http_error(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.reason_phrase = "Server Error"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)
        assert await client._make_request("https://test.com") is None

    async def test_url_error(self, client):
        client._client = AsyncMock()
        client._client.get = AsyncMock(side_effect=httpx.ConnectError("DNS failed", request=MagicMock()))
        assert await client._make_request("https://test.com") is None


# ============================================================
# search
# ============================================================


class TestSearch:
    @patch.object(OpenAlexClient, "_make_request")
    async def test_basic(self, mock_req, client):
        mock_req.return_value = {
            "results": [
                {
                    "id": "W123",
                    "display_name": "Test Paper",
                    "publication_date": "2023-06-15",
                    "publication_year": 2023,
                    "authorships": [{"author": {"display_name": "John Doe"}}],
                    "ids": {
                        "doi": "https://doi.org/10.1234/test",
                        "pmid": "https://pubmed.ncbi.nlm.nih.gov/12345/",
                    },
                    "cited_by_count": 50,
                    "open_access": {"is_oa": True, "oa_status": "gold"},
                    "best_oa_location": {"pdf_url": "https://pdf.example.com"},
                    "primary_location": {"source": {"display_name": "Nature", "is_in_doaj": False}},
                }
            ]
        }
        results = await client.search("deep learning")
        assert len(results) == 1
        assert results[0]["title"] == "Test Paper"
        assert results[0]["doi"] == "10.1234/test"
        assert results[0]["pmid"] == "12345"
        assert results[0]["year"] == "2023"
        assert results[0]["month"] == "06"
        assert results[0]["day"] == "15"
        assert results[0]["_source"] == "openalex"

    @patch.object(OpenAlexClient, "_make_request")
    async def test_with_filters(self, mock_req, client):
        mock_req.return_value = {"results": []}
        await client.search("test", min_year=2020, max_year=2024, open_access_only=True, is_doaj=True)
        url = mock_req.call_args[0][0]
        assert "is_oa%3Atrue" in url or "is_oa:true" in url
        assert "2020" in url

    @patch.object(OpenAlexClient, "_make_request")
    async def test_with_sort(self, mock_req, client):
        mock_req.return_value = {"results": []}
        await client.search("test", sort="cited_by_count:desc")
        url = mock_req.call_args[0][0]
        assert "sort=" in url

    @patch.object(OpenAlexClient, "_make_request")
    async def test_uses_api_key_when_configured(self, mock_req):
        mock_req.return_value = {"results": []}
        client = OpenAlexClient(email="test@example.com", api_key="oa-key")
        await client.search("test")
        url = mock_req.call_args[0][0]
        assert "api_key=oa-key" in url
        assert "mailto=" not in url

    @patch.object(OpenAlexClient, "_make_request")
    async def test_limit_capped(self, mock_req, client):
        mock_req.return_value = {"results": []}
        await client.search("test", limit=500)
        url = mock_req.call_args[0][0]
        assert "per_page=200" in url

    @patch.object(OpenAlexClient, "_make_request")
    async def test_returns_empty_on_none(self, mock_req, client):
        mock_req.return_value = None
        assert await client.search("test") == []

    @patch.object(OpenAlexClient, "_make_request")
    async def test_exception(self, mock_req, client):
        mock_req.side_effect = Exception("fail")
        assert await client.search("test") == []


# ============================================================
# get_work
# ============================================================


class TestGetWork:
    @patch.object(OpenAlexClient, "_make_request")
    async def test_by_doi(self, mock_req, client):
        mock_req.return_value = {
            "id": "W123",
            "display_name": "Test",
            "ids": {"doi": "https://doi.org/10.1234/test"},
        }
        result = await client.get_work("10.1234/test")
        assert result is not None
        assert result["title"] == "Test"

    @patch.object(OpenAlexClient, "_make_request")
    async def test_by_pmid(self, mock_req, client):
        mock_req.return_value = {
            "id": "W456",
            "display_name": "PMID Test",
            "ids": {},
        }
        result = await client.get_work("12345")
        assert result is not None

    @patch.object(OpenAlexClient, "_make_request")
    async def test_not_found(self, mock_req, client):
        mock_req.return_value = None
        assert await client.get_work("W999") is None

    @patch.object(OpenAlexClient, "_make_request")
    async def test_exception(self, mock_req, client):
        mock_req.side_effect = Exception("fail")
        assert await client.get_work("W1") is None

    @patch.object(OpenAlexClient, "_make_request")
    async def test_by_doi_uses_api_key_when_configured(self, mock_req):
        mock_req.return_value = {"id": "W123", "display_name": "Test", "ids": {}}
        client = OpenAlexClient(email="test@example.com", api_key="oa-key")
        await client.get_work("10.1234/test")
        url = mock_req.call_args[0][0]
        assert "api_key=oa-key" in url
        assert "mailto=" not in url


# ============================================================
# get_citations
# ============================================================


class TestGetCitations:
    @patch.object(OpenAlexClient, "_make_request")
    async def test_success(self, mock_req, client):
        mock_req.return_value = {
            "results": [
                {"id": "W1", "display_name": "Citing Paper", "ids": {}},
            ]
        }
        results = await client.get_citations("W123")
        assert len(results) == 1

    @patch.object(OpenAlexClient, "_make_request")
    async def test_empty(self, mock_req, client):
        mock_req.return_value = None
        assert await client.get_citations("W123") == []

    @patch.object(OpenAlexClient, "_make_request")
    async def test_exception(self, mock_req, client):
        mock_req.side_effect = Exception("fail")
        assert await client.get_citations("W123") == []


# ============================================================
# get_source / get_sources_batch
# ============================================================


class TestSourceMetadata:
    @patch.object(OpenAlexClient, "_make_request")
    async def test_get_source_success(self, mock_req, client):
        mock_req.return_value = {
            "id": "https://openalex.org/S123",
            "display_name": "Nature Medicine",
            "issn": ["1078-8956"],
            "issn_l": "1078-8956",
            "summary_stats": {
                "h_index": 200,
                "2yr_mean_citedness": 12.5,
                "i10_index": 100,
            },
            "works_count": 1000,
            "cited_by_count": 50000,
            "is_in_doaj": False,
            "type": "journal",
            "x_concepts": [
                {"display_name": "Medicine", "level": 0},
                {"display_name": "Oncology", "level": 1},
            ],
        }

        result = await client.get_source("https://openalex.org/S123")

        assert result is not None
        assert result["openalex_source_id"] == "S123"
        assert result["display_name"] == "Nature Medicine"
        assert result["subject_areas"] == ["Medicine", "Oncology"]

    @patch.object(OpenAlexClient, "_make_request")
    async def test_get_sources_batch_success(self, mock_req, client):
        mock_req.return_value = {
            "results": [
                {
                    "id": "https://openalex.org/S1",
                    "display_name": "Journal One",
                    "summary_stats": {},
                    "x_concepts": [],
                },
                {
                    "id": "https://openalex.org/S2",
                    "display_name": "Journal Two",
                    "summary_stats": {},
                    "x_concepts": [],
                },
            ]
        }

        results = await client.get_sources_batch(["https://openalex.org/S1", "S2"])

        assert set(results) == {"S1", "S2"}
        assert results["S1"]["display_name"] == "Journal One"

    async def test_get_sources_batch_empty_input(self, client):
        assert await client.get_sources_batch([]) == {}


# ============================================================
# get_author / search_authors
# ============================================================


class TestAuthorMetadata:
    @patch.object(OpenAlexClient, "_make_request")
    async def test_get_author_success(self, mock_req, client):
        mock_req.return_value = {
            "id": "https://openalex.org/A123",
            "display_name": "Jane Doe",
            "ids": {"orcid": "https://orcid.org/0000-0001-2345-6789"},
            "summary_stats": {
                "h_index": 40,
                "2yr_mean_citedness": 3.2,
                "i10_index": 80,
            },
            "works_count": 120,
            "cited_by_count": 4500,
            "last_known_institutions": [{"display_name": "MIT"}],
            "x_concepts": [{"display_name": "Machine learning"}],
        }

        result = await client.get_author("A123")

        assert result is not None
        assert result["openalex_author_id"] == "A123"
        assert result["orcid"] == "0000-0001-2345-6789"
        assert result["last_known_institutions"] == ["MIT"]
        assert result["concepts"] == ["Machine learning"]

    @patch.object(OpenAlexClient, "_make_request")
    async def test_get_author_normalizes_orcid_identifier(self, mock_req, client):
        mock_req.return_value = {"id": "https://openalex.org/A123", "display_name": "Jane Doe"}

        await client.get_author("0000-0001-2345-6789")

        url = mock_req.call_args[0][0]
        assert "https%3A%2F%2Forcid.org%2F0000-0001-2345-6789" in url

    @patch.object(OpenAlexClient, "_make_request")
    async def test_search_authors_success(self, mock_req, client):
        mock_req.return_value = {
            "results": [
                {
                    "id": "https://openalex.org/A1",
                    "display_name": "John Smith",
                    "summary_stats": {},
                }
            ]
        }

        results = await client.search_authors("John Smith")

        assert len(results) == 1
        assert results[0]["display_name"] == "John Smith"

    @patch.object(OpenAlexClient, "_make_request")
    async def test_search_authors_returns_empty_on_none(self, mock_req, client):
        mock_req.return_value = None
        assert await client.search_authors("Nobody") == []


# ============================================================
# _normalize_work
# ============================================================


class TestNormalizeWork:
    async def test_full_work(self, client):
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

    async def test_minimal_work(self, client):
        work = {"id": "W1"}
        result = client._normalize_work(work)
        assert result["title"] == ""
        assert result["doi"] == ""
        assert result["_source"] == "openalex"

    async def test_single_name_author(self, client):
        work = {"authorships": [{"author": {"display_name": "Madonna"}}]}
        result = client._normalize_work(work)
        assert result["authors_full"][0]["last_name"] == "Madonna"

    async def test_none_ids(self, client):
        work = {"ids": None}
        result = client._normalize_work(work)
        assert result["doi"] == ""

    async def test_none_authorships(self, client):
        work = {"authorships": None}
        result = client._normalize_work(work)
        assert result["authors"] == []

    async def test_none_primary_location(self, client):
        work = {"primary_location": None}
        result = client._normalize_work(work)
        assert result["journal"] == ""

    async def test_title_fallback(self, client):
        work = {"title": "Fallback Title"}
        result = client._normalize_work(work)
        assert result["title"] == "Fallback Title"


# ============================================================
# _get_abstract
# ============================================================


class TestGetAbstract:
    async def test_inverted_index(self, client):
        work = {
            "abstract_inverted_index": {
                "This": [0],
                "is": [1],
                "a": [2],
                "test": [3],
            }
        }
        abstract = client._get_abstract(work)
        assert abstract == "This is a test"

    async def test_no_abstract(self, client):
        assert client._get_abstract({}) == ""

    async def test_none_abstract(self, client):
        assert client._get_abstract({"abstract_inverted_index": None}) == ""

    async def test_multi_position_words(self, client):
        work = {
            "abstract_inverted_index": {
                "the": [0, 3],
                "cat": [1],
                "sat": [2],
                "mat": [4],
            }
        }
        abstract = client._get_abstract(work)
        assert abstract == "the cat sat the mat"
