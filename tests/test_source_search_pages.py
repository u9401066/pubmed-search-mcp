"""Contract and seam tests for provider-DTO search pages."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.search.source_models import SourceSearchPage, coerce_optional_total
from pubmed_search.infrastructure.sources.base_client import APIRequestError
from pubmed_search.infrastructure.sources.openalex import OpenAlexClient
from pubmed_search.infrastructure.sources.semantic_scholar import (
    SemanticScholarClient,
    compile_semantic_scholar_bulk_query,
)
from pubmed_search.presentation.mcp_server.tools.unified_source_search import (
    _search_openalex,
    _search_semantic_scholar,
)


def _openalex_work() -> dict:
    return {
        "id": "https://openalex.org/W123",
        "title": "Raw OpenAlex Work",
        "abstract_inverted_index": {"Raw": [0], "abstract": [1]},
        "publication_year": 2024,
        "publication_date": "2024-02-03",
        "authorships": [
            {
                "author": {
                    "display_name": "Ada Lovelace",
                    "orcid": "https://orcid.org/0000-0001-0000-0001",
                }
            }
        ],
        "ids": {
            "doi": "https://doi.org/10.1000/raw",
            "pmid": "https://pubmed.ncbi.nlm.nih.gov/12345/",
            "pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC77/",
        },
        "open_access": {"is_oa": True, "oa_status": "gold"},
        "best_oa_location": {"pdf_url": "https://example.test/raw.pdf", "license": "cc-by"},
        "primary_location": {"source": {"display_name": "Test Journal"}},
        "cited_by_count": 17,
        "type": "article",
    }


def _s2_paper() -> dict:
    return {
        "paperId": "s2-paper-id",
        "title": "Raw Semantic Scholar Paper",
        "abstract": "Raw S2 abstract",
        "year": 2023,
        "authors": [{"authorId": "a1", "name": "Grace Hopper"}],
        "venue": "S2 Journal",
        "publicationVenue": {"name": "S2 Journal", "type": "journal"},
        "citationCount": 9,
        "influentialCitationCount": 2,
        "isOpenAccess": True,
        "openAccessPdf": {"url": "https://example.test/s2.pdf", "license": "CC-BY-NC"},
        "externalIds": {
            "DOI": "10.1000/s2",
            "PubMed": "54321",
            "PubMedCentral": "PMC88",
        },
    }


def test_source_search_page_total_coercion_is_explicit() -> None:
    assert coerce_optional_total("12,345") == (12345, [])
    total, warnings = coerce_optional_total({"unexpected": True})
    assert total is None
    assert warnings


def test_s2_bulk_query_compiler_preserves_phrases_and_boolean_semantics() -> None:
    compiled = compile_semantic_scholar_bulk_query('(melanoma OR "targeted AND therapy") AND NOT review')

    assert compiled == '(melanoma | "targeted AND therapy") + -review'


@pytest.mark.asyncio
async def test_openalex_page_preserves_raw_dto_and_envelope() -> None:
    client = OpenAlexClient(email="test@example.com")
    client._min_interval = 0
    client._make_request = AsyncMock(
        return_value={
            "meta": {
                "count": 321,
                "next_cursor": "next-cursor",
                "x_query": "canonical OQL",
                "cost_usd": 0.001,
            },
            "results": [_openalex_work()],
        }
    )
    try:
        page = await client.search_page("raw query", limit=500, cursor="*")
    finally:
        await client.close()

    assert page.items[0]["authorships"][0]["author"]["display_name"] == "Ada Lovelace"
    assert "authors" not in page.items[0]
    assert page.total == 321
    assert page.cursor == "next-cursor"
    assert page.query == "canonical OQL"
    assert page.cost == 0.001
    request_url = client._make_request.await_args.args[0]
    assert "per_page=100" in request_url
    assert "select=" in request_url
    assert "abstract_inverted_index" in request_url


@pytest.mark.asyncio
async def test_openalex_schema_failure_is_not_reported_as_empty() -> None:
    client = OpenAlexClient(email="test@example.com")
    client._min_interval = 0
    client._make_request = AsyncMock(return_value={"meta": {"count": 0}, "results": {"bad": "shape"}})
    try:
        with pytest.raises(APIRequestError, match="OpenAlex"):
            await client.search_page("schema drift")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_openalex_current_x_query_object_preserves_oql_without_url() -> None:
    client = OpenAlexClient(email="test@example.com", api_key="secret-key")
    client._min_interval = 0
    client._last_rate_limit_headers.set(
        {
            "x-ratelimit-limit": "10000",
            "x-ratelimit-remaining": "7",
            "x-ratelimit-remaining-usd": "0.007",
            "x-ratelimit-reset": "2026-08-15T00:00:00Z",
        }
    )
    client._make_request = AsyncMock(
        return_value={
            "meta": {
                "count": 1,
                "x_query": {
                    "oql": "title.search:malaria",
                    "oqo": "malaria",
                    "url": "https://api.openalex.org/works?api_key=must-not-persist",
                },
            },
            "results": [_openalex_work()],
        }
    )
    try:
        page = await client.search_page("malaria")
    finally:
        await client.close()

    assert page.query == "title.search:malaria"
    assert page.metadata["x_query"] == {"oql": "title.search:malaria", "oqo": "malaria"}
    assert "url" not in page.metadata["x_query"]
    assert "secret-key" not in str(page.metadata)
    assert page.metadata["rate_limit"]["x-ratelimit-remaining"] == "7"
    assert any("credit budget is low" in warning for warning in page.warnings)


@pytest.mark.asyncio
async def test_openalex_client_runner_mapper_seam_maps_once() -> None:
    client = OpenAlexClient(email="test@example.com")
    client._min_interval = 0
    client._make_request = AsyncMock(return_value={"meta": {"count": 1}, "results": [_openalex_work()]})
    try:
        with patch(
            "pubmed_search.infrastructure.sources.get_openalex_client",
            return_value=client,
        ):
            articles, total = await _search_openalex("raw query", 10, None, None)
    finally:
        await client.close()

    assert total == 1
    assert len(articles) == 1
    article = articles[0]
    assert article.openalex_id == "W123"
    assert article.doi == "10.1000/raw"
    assert article.pmid == "12345"
    assert article.pmc == "PMC77"
    assert article.authors[0].full_name == "Ada Lovelace"
    assert article.abstract == "Raw abstract"
    assert article.citation_metrics is not None
    assert article.citation_metrics.citation_count == 17
    assert article.oa_links[0].license == "cc-by"


@pytest.mark.asyncio
async def test_openalex_semantic_constraints_and_native_parameter() -> None:
    client = OpenAlexClient(email="test@example.com")
    client._min_interval = 0
    client._make_request = AsyncMock(return_value={"meta": {"count": 0}, "results": []})
    limiter = MagicMock()
    limiter.acquire = AsyncMock()
    try:
        with patch(
            "pubmed_search.infrastructure.sources.openalex.get_rate_limiter",
            return_value=limiter,
        ):
            page = await client.search_semantic_page("meaning based query", limit=999)
            with pytest.raises(ValueError, match=r"2,000|2000"):
                await client.search_semantic_page("x" * 2_001)
    finally:
        await client.close()

    assert page.mode == "semantic"
    request_url = client._make_request.await_args.args[0]
    assert "search.semantic=" in request_url
    assert "per_page=50" in request_url
    assert "cursor=" not in request_url
    limiter.acquire.assert_awaited_once()


@pytest.mark.asyncio
async def test_openalex_all_list_operations_cap_per_page_at_100() -> None:
    client = OpenAlexClient(email="test@example.com")
    client._min_interval = 0
    client._make_request = AsyncMock(return_value={"results": []})
    try:
        await client.get_citations("W1", limit=999)
        await client.search_authors("Ada", limit=999)
    finally:
        await client.close()

    urls = [call.args[0] for call in client._make_request.await_args_list]
    assert all("per_page=100" in url for url in urls)


@pytest.mark.asyncio
async def test_openalex_cursor_is_bounded_and_detects_repetition() -> None:
    client = OpenAlexClient(email="test@example.com")
    client.search_page = AsyncMock(
        side_effect=[
            SourceSearchPage(
                source="openalex",
                items=[{"id": "W1"}],
                total=3,
                cursor="repeat",
                cost=0.001,
            ),
            SourceSearchPage(
                source="openalex",
                items=[{"id": "W2"}],
                total=3,
                cursor="repeat",
                cost=0.001,
            ),
        ]
    )
    try:
        page = await client.search_cursor("query", max_results=10, max_pages=5)
    finally:
        await client.close()

    assert [item["id"] for item in page.items] == ["W1", "W2"]
    assert page.cost == 0.002
    assert page.metadata["pages_fetched"] == 2
    assert any("repeated cursor" in warning for warning in page.warnings)
    assert client.search_page.await_args_list[0].kwargs["cursor"] == "*"


@pytest.mark.asyncio
async def test_s2_relevance_page_preserves_raw_dto_total_and_next() -> None:
    client = SemanticScholarClient()
    client._min_interval = 0
    client._make_request = AsyncMock(
        return_value={
            "total": "42",
            "offset": 0,
            "next": 10,
            "data": [_s2_paper()],
        }
    )
    try:
        page = await client.search_page("plain text query", offset=0)
    finally:
        await client.close()

    assert page.total == 42
    assert page.next_token == 10
    assert page.items[0]["externalIds"]["DOI"] == "10.1000/s2"
    assert "doi" not in page.items[0]
    request_url = client._make_request.await_args.args[0]
    assert "offset=0" in request_url


@pytest.mark.asyncio
async def test_s2_schema_failure_is_not_reported_as_empty() -> None:
    client = SemanticScholarClient()
    client._min_interval = 0
    client._official_client.search_papers = AsyncMock(side_effect=ValueError("synthetic schema drift"))
    try:
        with pytest.raises(APIRequestError, match="Semantic Scholar"):
            await client.search_page("schema drift")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_s2_relevance_continuation_offset_is_consumable_and_bounded() -> None:
    client = SemanticScholarClient()
    client._min_interval = 0
    client._make_request = AsyncMock(return_value={"total": 1_000, "offset": 100, "next": 200, "data": []})
    try:
        page = await client.search_page("plain text query", limit=100, offset=100)
        with pytest.raises(ValueError, match="1,000"):
            await client.search_page("plain text query", limit=100, offset=950)
    finally:
        await client.close()

    assert page.next_token == 200
    assert "offset=100" in client._make_request.await_args.args[0]


@pytest.mark.asyncio
async def test_s2_client_runner_mapper_seam_maps_once() -> None:
    client = SemanticScholarClient()
    client._min_interval = 0
    client._make_request = AsyncMock(return_value={"total": 1, "data": [_s2_paper()]})
    try:
        with patch(
            "pubmed_search.infrastructure.sources.get_semantic_scholar_client",
            return_value=client,
        ):
            articles, total = await _search_semantic_scholar("plain text query", 10, None, None)
    finally:
        await client.close()

    assert total == 1
    assert len(articles) == 1
    article = articles[0]
    assert article.s2_id == "s2-paper-id"
    assert article.doi == "10.1000/s2"
    assert article.pmid == "54321"
    assert article.pmc == "PMC88"
    assert article.authors[0].full_name == "Grace Hopper"
    assert article.oa_links[0].license == "CC-BY-NC"


@pytest.mark.asyncio
async def test_s2_bulk_page_and_bounded_token_loop() -> None:
    client = SemanticScholarClient()
    client._min_interval = 0
    client._make_request = AsyncMock(
        return_value={
            "total": "5000",
            "token": "token-2",
            "data": [_s2_paper()],
        }
    )
    try:
        one_page = await client.bulk_search_page("fish | ladder", sort="paperId")
        client.bulk_search_page = AsyncMock(
            side_effect=[
                SourceSearchPage(
                    source="semantic_scholar",
                    items=[{"paperId": "1"}],
                    total=5_000,
                    next_token="repeat",
                    mode="bulk",
                ),
                SourceSearchPage(
                    source="semantic_scholar",
                    items=[{"paperId": "2"}],
                    total=5_000,
                    next_token="repeat",
                    mode="bulk",
                ),
            ]
        )
        bounded = await client.bulk_search("fish | ladder", max_results=10, max_pages=5)
    finally:
        await client.close()

    assert one_page.total == 5_000
    assert one_page.next_token == "token-2"
    request_url = client._make_request.await_args.args[0]
    assert "/paper/search/bulk" in request_url
    assert "sort=paperId" in request_url
    assert [item["paperId"] for item in bounded.items] == ["1", "2"]
    assert any("repeated bulk token" in warning for warning in bounded.warnings)


@pytest.mark.asyncio
async def test_s2_batch_enforces_500_id_contract() -> None:
    client = SemanticScholarClient()
    client._min_interval = 0
    client._make_request = AsyncMock(return_value=[_s2_paper(), None])
    try:
        result = await client.get_papers_batch(["id-1", "id-2"])
        with pytest.raises(ValueError, match="500"):
            await client.get_papers_batch([f"id-{index}" for index in range(501)])
    finally:
        await client.close()

    assert result[0] is not None
    assert result[1] is None
    assert client._make_request.await_args.kwargs["method"] == "POST"
    assert client._make_request.await_args.kwargs["data"] == {"ids": ["id-1", "id-2"]}
