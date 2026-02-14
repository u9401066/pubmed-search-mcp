"""Tests for SemanticScholarClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from pubmed_search.infrastructure.sources.semantic_scholar import (
    SemanticScholarClient,
)


@pytest.fixture
def client():
    c = SemanticScholarClient(timeout=5.0)
    c._last_request_time = 0  # skip rate limiting in tests
    c._min_interval = 0
    return c


@pytest.fixture
def client_with_key():
    c = SemanticScholarClient(api_key="test_key", timeout=5.0)
    c._min_interval = 0
    return c


# ============================================================
# Init
# ============================================================


class TestInit:
    async def test_defaults(self):
        c = SemanticScholarClient()
        assert c._api_key is None
        assert c._timeout == 30.0

    async def test_with_key(self, client_with_key):
        assert client_with_key._api_key == "test_key"

    async def test_context_manager(self):
        async with SemanticScholarClient() as c:
            assert c is not None


# ============================================================
# _make_request
# ============================================================


class TestMakeRequest:
    async def test_success(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"total": 1}
        mock_response.raise_for_status = MagicMock()
        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)
        result = await client._make_request("https://api.semanticscholar.org/test")
        assert result == {"total": 1}

    async def test_with_api_key_header(self, client_with_key):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status = MagicMock()
        client_with_key._client = AsyncMock()
        client_with_key._client.get = AsyncMock(return_value=mock_response)

        await client_with_key._make_request("https://api.semanticscholar.org/test")
        call_kwargs = client_with_key._client.get.call_args[1]
        assert call_kwargs["headers"]["x-api-key"] == "test_key"

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
    @patch.object(SemanticScholarClient, "_make_request")
    async def test_basic_search(self, mock_req, client):
        mock_req.return_value = {
            "data": [
                {
                    "paperId": "abc123",
                    "title": "Deep Learning",
                    "abstract": "A review",
                    "year": 2023,
                    "authors": [{"name": "Jane Doe"}],
                    "venue": "Nature",
                    "publicationVenue": None,
                    "citationCount": 100,
                    "influentialCitationCount": 10,
                    "isOpenAccess": True,
                    "openAccessPdf": {"url": "https://pdf.example.com/paper.pdf"},
                    "externalIds": {"DOI": "10.1234/test", "PubMed": "12345"},
                }
            ]
        }

        results = await client.search("deep learning")
        assert len(results) == 1
        assert results[0]["title"] == "Deep Learning"
        assert results[0]["doi"] == "10.1234/test"
        assert results[0]["pmid"] == "12345"
        assert results[0]["_source"] == "semantic_scholar"
        assert results[0]["pdf_url"] == "https://pdf.example.com/paper.pdf"

    @patch.object(SemanticScholarClient, "_make_request")
    async def test_search_with_year_range(self, mock_req, client):
        mock_req.return_value = {"data": []}
        await client.search("test", min_year=2020, max_year=2024)
        url = mock_req.call_args[0][0]
        assert "2020-2024" in url

    @patch.object(SemanticScholarClient, "_make_request")
    async def test_search_min_year_only(self, mock_req, client):
        mock_req.return_value = {"data": []}
        await client.search("test", min_year=2020)
        url = mock_req.call_args[0][0]
        assert "2020-" in url

    @patch.object(SemanticScholarClient, "_make_request")
    async def test_search_max_year_only(self, mock_req, client):
        mock_req.return_value = {"data": []}
        await client.search("test", max_year=2024)
        url = mock_req.call_args[0][0]
        assert "-2024" in url

    @patch.object(SemanticScholarClient, "_make_request")
    async def test_search_open_access(self, mock_req, client):
        mock_req.return_value = {"data": []}
        await client.search("test", open_access_only=True)
        url = mock_req.call_args[0][0]
        assert "openAccessPdf" in url

    @patch.object(SemanticScholarClient, "_make_request")
    async def test_search_limit_capped(self, mock_req, client):
        mock_req.return_value = {"data": []}
        await client.search("test", limit=500)
        url = mock_req.call_args[0][0]
        assert "limit=100" in url

    @patch.object(SemanticScholarClient, "_make_request")
    async def test_search_returns_empty_on_none(self, mock_req, client):
        mock_req.return_value = None
        assert await client.search("test") == []

    @patch.object(SemanticScholarClient, "_make_request")
    async def test_search_exception(self, mock_req, client):
        mock_req.side_effect = Exception("fail")
        assert await client.search("test") == []


# ============================================================
# get_paper
# ============================================================


class TestGetPaper:
    @patch.object(SemanticScholarClient, "_make_request")
    async def test_get_by_doi(self, mock_req, client):
        mock_req.return_value = {
            "paperId": "abc",
            "title": "Test Paper",
            "year": 2023,
            "authors": [],
            "externalIds": {},
        }
        result = await client.get_paper("DOI:10.1234/test")
        assert result is not None
        assert result["title"] == "Test Paper"

    @patch.object(SemanticScholarClient, "_make_request")
    async def test_get_not_found(self, mock_req, client):
        mock_req.return_value = None
        assert await client.get_paper("DOI:10.1234/fake") is None

    @patch.object(SemanticScholarClient, "_make_request")
    async def test_get_exception(self, mock_req, client):
        mock_req.side_effect = Exception("fail")
        assert await client.get_paper("abc") is None


# ============================================================
# get_citations & get_references
# ============================================================


class TestCitationsRefs:
    @patch.object(SemanticScholarClient, "_make_request")
    async def test_get_citations(self, mock_req, client):
        mock_req.return_value = {
            "data": [
                {
                    "citingPaper": {
                        "paperId": "p1",
                        "title": "Citing 1",
                        "year": 2023,
                        "authors": [],
                        "externalIds": {},
                    }
                },
                {
                    "citingPaper": {
                        "paperId": "p2",
                        "title": "Citing 2",
                        "year": 2022,
                        "authors": [],
                        "externalIds": {},
                    }
                },
            ]
        }
        results = await client.get_citations("abc123")
        assert len(results) == 2
        assert results[0]["title"] == "Citing 1"

    @patch.object(SemanticScholarClient, "_make_request")
    async def test_get_citations_empty(self, mock_req, client):
        mock_req.return_value = None
        assert await client.get_citations("abc") == []

    @patch.object(SemanticScholarClient, "_make_request")
    async def test_get_citations_exception(self, mock_req, client):
        mock_req.side_effect = Exception("fail")
        assert await client.get_citations("abc") == []

    @patch.object(SemanticScholarClient, "_make_request")
    async def test_get_references(self, mock_req, client):
        mock_req.return_value = {
            "data": [
                {
                    "citedPaper": {
                        "paperId": "r1",
                        "title": "Ref 1",
                        "year": 2020,
                        "authors": [],
                        "externalIds": {},
                    }
                },
            ]
        }
        results = await client.get_references("abc123")
        assert len(results) == 1

    @patch.object(SemanticScholarClient, "_make_request")
    async def test_get_references_empty(self, mock_req, client):
        mock_req.return_value = None
        assert await client.get_references("abc") == []

    @patch.object(SemanticScholarClient, "_make_request")
    async def test_get_references_exception(self, mock_req, client):
        mock_req.side_effect = Exception("fail")
        assert await client.get_references("abc") == []


# ============================================================
# get_recommendations
# ============================================================


class TestRecommendations:
    @patch.object(SemanticScholarClient, "_make_request")
    async def test_success(self, mock_req, client):
        mock_req.return_value = {
            "recommendedPapers": [
                {
                    "paperId": "r1",
                    "title": "Rec 1",
                    "year": 2023,
                    "authors": [],
                    "externalIds": {},
                },
                {
                    "paperId": "r2",
                    "title": "Rec 2",
                    "year": 2022,
                    "authors": [],
                    "externalIds": {},
                },
            ]
        }
        results = await client.get_recommendations("abc123", limit=10)
        assert len(results) == 2
        assert results[0]["similarity_score"] == 1.0
        assert results[1]["similarity_score"] == 0.5
        assert results[0]["similarity_source"] == "semantic_scholar"

    @patch.object(SemanticScholarClient, "_make_request")
    async def test_empty(self, mock_req, client):
        mock_req.return_value = None
        assert await client.get_recommendations("abc") == []

    @patch.object(SemanticScholarClient, "_make_request")
    async def test_exception(self, mock_req, client):
        mock_req.side_effect = Exception("fail")
        assert await client.get_recommendations("abc") == []

    @patch.object(SemanticScholarClient, "_make_request")
    async def test_limit_capped(self, mock_req, client):
        mock_req.return_value = {"recommendedPapers": []}
        await client.get_recommendations("abc", limit=1000)
        url = mock_req.call_args[0][0]
        assert "limit=500" in url


# ============================================================
# get_paper_embedding_similarity
# ============================================================


class TestEmbeddingSimilarity:
    @patch.object(SemanticScholarClient, "get_recommendations")
    async def test_found_by_pmid(self, mock_recs, client):
        mock_recs.return_value = [
            {"_s2_id": "", "pmid": "12345", "doi": "", "similarity_score": 0.8},
        ]
        score = await client.get_paper_embedding_similarity("abc", "PMID:12345")
        assert score == 0.8

    @patch.object(SemanticScholarClient, "get_recommendations")
    async def test_found_by_doi(self, mock_recs, client):
        mock_recs.return_value = [
            {"_s2_id": "", "pmid": "", "doi": "10.1234/test", "similarity_score": 0.9},
        ]
        score = await client.get_paper_embedding_similarity("abc", "DOI:10.1234/test")
        assert score == 0.9

    @patch.object(SemanticScholarClient, "get_recommendations")
    async def test_found_by_s2_id(self, mock_recs, client):
        mock_recs.return_value = [
            {"_s2_id": "target123", "pmid": "", "doi": "", "similarity_score": 0.7},
        ]
        score = await client.get_paper_embedding_similarity("abc", "target123")
        assert score == 0.7

    @patch.object(SemanticScholarClient, "get_recommendations")
    async def test_not_found(self, mock_recs, client):
        mock_recs.return_value = [
            {
                "_s2_id": "other",
                "pmid": "999",
                "doi": "10.xxx",
                "similarity_score": 0.5,
            },
        ]
        score = await client.get_paper_embedding_similarity("abc", "xyz")
        assert score == 0.1

    @patch.object(SemanticScholarClient, "get_recommendations")
    async def test_exception(self, mock_recs, client):
        mock_recs.side_effect = Exception("fail")
        assert await client.get_paper_embedding_similarity("abc", "xyz") is None


# ============================================================
# _normalize_paper
# ============================================================


class TestNormalizePaper:
    async def test_full_paper(self, client):
        paper = {
            "paperId": "abc123",
            "title": "Test Paper",
            "abstract": "Abstract text",
            "year": 2023,
            "authors": [
                {"name": "John Smith"},
                {"name": "Jane"},
            ],
            "venue": "Nature",
            "publicationVenue": {
                "name": "Nature Medicine",
                "alternate_names": ["Nat Med"],
            },
            "citationCount": 50,
            "influentialCitationCount": 5,
            "isOpenAccess": True,
            "openAccessPdf": {"url": "https://pdf.example.com"},
            "externalIds": {
                "DOI": "10.1234/test",
                "PubMed": "12345",
                "PubMedCentral": "PMC999",
                "ArXiv": "2301.00001",
            },
        }
        result = client._normalize_paper(paper)
        assert result["title"] == "Test Paper"
        assert result["doi"] == "10.1234/test"
        assert result["pmid"] == "12345"
        assert result["pmc_id"] == "PMC999"
        assert result["arxiv_id"] == "2301.00001"
        assert result["citation_count"] == 50
        assert result["is_open_access"] is True
        assert result["pdf_url"] == "https://pdf.example.com"
        assert result["journal"] == "Nature Medicine"
        assert len(result["authors"]) == 2
        assert result["authors_full"][0]["last_name"] == "Smith"

    async def test_minimal_paper(self, client):
        paper = {"paperId": "x", "title": "Min"}
        result = client._normalize_paper(paper)
        assert result["title"] == "Min"
        assert result["pmid"] == ""
        assert result["doi"] == ""
        assert result["_source"] == "semantic_scholar"

    async def test_single_name_author(self, client):
        paper = {"paperId": "x", "authors": [{"name": "Madonna"}]}
        result = client._normalize_paper(paper)
        assert result["authors_full"][0]["last_name"] == "Madonna"
        assert result["authors_full"][0]["fore_name"] == ""

    async def test_venue_as_string(self, client):
        paper = {"paperId": "x", "venue": "JAMA", "publicationVenue": None}
        result = client._normalize_paper(paper)
        assert result["journal"] == "JAMA"

    async def test_none_external_ids(self, client):
        paper = {"paperId": "x", "externalIds": None}
        result = client._normalize_paper(paper)
        assert result["doi"] == ""

    async def test_none_authors(self, client):
        paper = {"paperId": "x", "authors": None}
        result = client._normalize_paper(paper)
        assert result["authors"] == []

    async def test_no_open_access_pdf(self, client):
        paper = {"paperId": "x", "openAccessPdf": None}
        result = client._normalize_paper(paper)
        assert result["pdf_url"] is None
