"""Tests for the official spec-backed generated source adapters."""

from __future__ import annotations

from unittest.mock import AsyncMock

from pubmed_search.infrastructure.sources.official_generated_clients import (
    SCOPUS_SEARCH_OPERATION,
    SEMANTIC_SCHOLAR_CITATIONS_OPERATION,
    SEMANTIC_SCHOLAR_PAPER_OPERATION,
    SEMANTIC_SCHOLAR_RECOMMENDATIONS_OPERATION,
    SEMANTIC_SCHOLAR_REFERENCES_OPERATION,
    SEMANTIC_SCHOLAR_SEARCH_OPERATION,
    WEB_OF_SCIENCE_SEARCH_OPERATION,
    OfficialScopusGeneratedClient,
    OfficialSemanticScholarGeneratedClient,
    OfficialWebOfScienceGeneratedClient,
    ScopusSearchRequest,
    SemanticScholarSearchRequest,
    WebOfScienceSearchRequest,
)


class _FakeOwner:
    """Minimal owner exposing the BaseAPIClient request surface used by adapters."""

    def __init__(self, payload):
        self._make_request = AsyncMock(return_value=payload)


class TestScopusGeneratedClient:
    def test_operation_metadata_points_to_official_spec(self):
        assert SCOPUS_SEARCH_OPERATION.service == "Scopus"
        assert SCOPUS_SEARCH_OPERATION.operation_id == "ScopusSearch"
        assert SCOPUS_SEARCH_OPERATION.spec_url == "https://dev.elsevier.com/elsdoc/scopus"
        assert SCOPUS_SEARCH_OPERATION.listing_url == "https://dev.elsevier.com/elsdoc/listings/Scopus_Search"
        assert SCOPUS_SEARCH_OPERATION.path == "/content/search/scopus"

    async def test_generated_client_uses_official_path_and_parses_entries(self):
        owner = _FakeOwner(
            {
                "search-results": {
                    "entry": [
                        {
                            "dc:title": "Scopus Article",
                            "prism:doi": "10.1000/scopus",
                        }
                    ]
                }
            }
        )
        client = OfficialScopusGeneratedClient(owner)

        response = await client.search_documents(
            ScopusSearchRequest(
                query="TITLE-ABS-KEY(test)",
                apiKey="licensed-key",
                count=5,
            )
        )

        assert response is not None
        assert response.entries()[0].title == "Scopus Article"
        owner._make_request.assert_awaited_once()
        assert owner._make_request.await_args.args[0] == "/content/search/scopus"


class TestWebOfScienceGeneratedClient:
    def test_operation_metadata_points_to_official_spec(self):
        assert WEB_OF_SCIENCE_SEARCH_OPERATION.service == "Web of Science"
        assert WEB_OF_SCIENCE_SEARCH_OPERATION.spec_url == "https://developer.clarivate.com/apis/wos-starter/swagger"
        assert WEB_OF_SCIENCE_SEARCH_OPERATION.path == "/documents"

    async def test_generated_client_uses_documents_endpoint(self):
        owner = _FakeOwner(
            {
                "metadata": {"total": 1, "page": 1, "limit": 10},
                "hits": [{"uid": "WOS:1", "title": "WOS Article"}],
            }
        )
        client = OfficialWebOfScienceGeneratedClient(owner)

        response = await client.search_documents(WebOfScienceSearchRequest(q="TS=(test)", limit=5, page=1))

        assert response is not None
        assert response.hits[0].uid == "WOS:1"
        owner._make_request.assert_awaited_once()
        assert owner._make_request.await_args.args[0] == "/documents"


class TestSemanticScholarGeneratedClient:
    def test_operation_metadata_points_to_official_specs(self):
        assert SEMANTIC_SCHOLAR_SEARCH_OPERATION.spec_url == "https://api.semanticscholar.org/graph/v1/swagger.json"
        assert SEMANTIC_SCHOLAR_PAPER_OPERATION.operation_id == "get_graph_get_paper"
        assert SEMANTIC_SCHOLAR_CITATIONS_OPERATION.operation_id == "get_graph_get_paper_citations"
        assert SEMANTIC_SCHOLAR_REFERENCES_OPERATION.operation_id == "get_graph_get_paper_references"
        assert (
            SEMANTIC_SCHOLAR_RECOMMENDATIONS_OPERATION.spec_url
            == "https://api.semanticscholar.org/recommendations/v1/swagger.json"
        )

    async def test_search_builds_graph_url_from_official_operation(self):
        owner = _FakeOwner({"data": [{"paperId": "abc123", "title": "Semantic Paper"}]})
        client = OfficialSemanticScholarGeneratedClient(owner)

        response = await client.search_papers(
            SemanticScholarSearchRequest(
                query="covid",
                limit=10,
                fields="title,year",
                year="2020-2024",
                openAccessPdf="",
            )
        )

        assert response is not None
        assert response.data[0].paperId == "abc123"
        owner._make_request.assert_awaited_once()
        url = owner._make_request.await_args.args[0]
        assert url.startswith("https://api.semanticscholar.org/graph/v1/paper/search?")
        assert "query=covid" in url
        assert "year=2020-2024" in url

    async def test_recommendations_builds_official_recommendations_url(self):
        owner = _FakeOwner({"recommendedPapers": [{"paperId": "p1", "title": "Rec 1"}]})
        client = OfficialSemanticScholarGeneratedClient(owner)

        response = await client.get_recommendations("PMID:12345", limit=20, fields="title")

        assert response is not None
        assert response.recommendedPapers[0].paperId == "p1"
        owner._make_request.assert_awaited_once()
        url = owner._make_request.await_args.args[0]
        assert url.startswith("https://api.semanticscholar.org/recommendations/v1/papers/forpaper/")
        assert "PMID%3A12345" in url
        assert "limit=20" in url
