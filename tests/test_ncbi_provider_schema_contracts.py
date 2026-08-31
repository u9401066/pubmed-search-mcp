"""Strict schema and absence contracts for NCBI provider responses."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.timeline.timeline_builder import TimelineBuilder, TimelineRetrievalError
from pubmed_search.infrastructure.ncbi.base import NCBIInfrastructureError, NCBIProviderSchemaError
from pubmed_search.infrastructure.ncbi.citation import CitationMixin
from pubmed_search.infrastructure.ncbi.search import SearchMixin
from pubmed_search.infrastructure.sources.base_client import ProviderSchemaError
from pubmed_search.infrastructure.sources.ncbi_extended import NCBIExtendedClient
from pubmed_search.presentation.mcp_server.tools.discovery import register_discovery_tools
from pubmed_search.presentation.mcp_server.tools.export import register_export_tools
from pubmed_search.presentation.mcp_server.tools.ncbi_extended import register_ncbi_extended_tools

PRIVATE_PROVIDER_DETAIL = "token=provider-secret https://private.example/query /srv/private/provider.json"


@pytest.fixture
def extended_client() -> NCBIExtendedClient:
    return NCBIExtendedClient(email="test@example.com")


ExtendedCall = Callable[[NCBIExtendedClient], Awaitable[Any]]

EXTENDED_CALLS: tuple[tuple[str, ExtendedCall], ...] = (
    ("search_gene", lambda client: client.search_gene("BRCA1")),
    ("get_gene", lambda client: client.get_gene("672")),
    ("get_gene_pubmed_links", lambda client: client.get_gene_pubmed_links("672")),
    ("search_compound", lambda client: client.search_compound("aspirin")),
    ("get_compound", lambda client: client.get_compound("2244")),
    ("get_compound_pubmed_links", lambda client: client.get_compound_pubmed_links("2244")),
    ("search_clinvar", lambda client: client.search_clinvar("BRCA1")),
)


@pytest.mark.parametrize(("_name", "call"), EXTENDED_CALLS)
@pytest.mark.asyncio
async def test_all_extended_paths_reject_error_envelopes_without_leaking_detail(
    _name: str,
    call: ExtendedCall,
    extended_client: NCBIExtendedClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    with patch.object(
        extended_client,
        "_make_request",
        new=AsyncMock(return_value={"ERROR": PRIVATE_PROVIDER_DETAIL}),
    ):
        with pytest.raises(ProviderSchemaError) as exc_info:
            await call(extended_client)

    assert str(exc_info.value) == "NCBI request failed"
    assert PRIVATE_PROVIDER_DETAIL not in str(exc_info.value)
    assert PRIVATE_PROVIDER_DETAIL not in caplog.text


@pytest.mark.parametrize(("_name", "call"), EXTENDED_CALLS)
@pytest.mark.asyncio
async def test_all_extended_paths_require_their_top_level_envelope(
    _name: str,
    call: ExtendedCall,
    extended_client: NCBIExtendedClient,
) -> None:
    with patch.object(extended_client, "_make_request", new=AsyncMock(return_value={})):
        with pytest.raises(ProviderSchemaError):
            await call(extended_client)


@pytest.mark.parametrize(
    ("call", "responses"),
    (
        (
            lambda client: client.search_gene("BRCA1"),
            ({"esearchresult": {"idlist": ["672"]}}, {"result": {"uids": ["672"]}}),
        ),
        (
            lambda client: client.get_gene("672"),
            ({"result": {"uids": ["672"]}},),
        ),
        (
            lambda client: client.search_compound("aspirin"),
            ({"esearchresult": {"idlist": ["2244"]}}, {"result": {"uids": ["2244"]}}),
        ),
        (
            lambda client: client.get_compound("2244"),
            ({"result": {"uids": ["2244"]}},),
        ),
        (
            lambda client: client.search_clinvar("BRCA1"),
            ({"esearchresult": {"idlist": ["12345"]}}, {"result": {"uids": ["12345"]}}),
        ),
    ),
)
@pytest.mark.asyncio
async def test_esummary_declared_ids_require_materialized_rows(
    call: ExtendedCall,
    responses: tuple[dict[str, Any], ...],
    extended_client: NCBIExtendedClient,
) -> None:
    with patch.object(extended_client, "_make_request", new=AsyncMock(side_effect=responses)):
        with pytest.raises(ProviderSchemaError):
            await call(extended_client)


@pytest.mark.parametrize(
    ("call", "payload", "expected"),
    (
        (lambda client: client.search_gene("missing"), {"esearchresult": {"idlist": []}}, []),
        (lambda client: client.get_gene("672"), {"result": {"uids": []}}, None),
        (lambda client: client.get_gene_pubmed_links("672"), {"linksets": []}, []),
        (
            lambda client: client.get_gene_pubmed_links("672"),
            {"linksets": [{"dbfrom": "gene", "ids": ["672"]}]},
            [],
        ),
        (lambda client: client.search_compound("missing"), {"esearchresult": {"idlist": []}}, []),
        (lambda client: client.get_compound("2244"), {"result": {"uids": []}}, None),
        (lambda client: client.get_compound_pubmed_links("2244"), {"linksets": []}, []),
        (
            lambda client: client.get_compound_pubmed_links("2244"),
            {"linksets": [{"dbfrom": "pccompound", "ids": ["2244"]}]},
            [],
        ),
        (lambda client: client.search_clinvar("missing"), {"esearchresult": {"idlist": []}}, []),
    ),
)
@pytest.mark.asyncio
async def test_extended_explicit_empty_and_not_found_remain_successful(
    call: ExtendedCall,
    payload: dict[str, Any],
    expected: object,
    extended_client: NCBIExtendedClient,
) -> None:
    with patch.object(extended_client, "_make_request", new=AsyncMock(return_value=payload)):
        assert await call(extended_client) == expected


@pytest.mark.parametrize(
    ("call", "payload"),
    (
        (
            lambda client: client.get_gene("999999999999999999"),
            {
                "result": {
                    "uids": ["999999999999999999"],
                    "999999999999999999": {
                        "uid": "999999999999999999",
                        "error": "cannot get document summary",
                    },
                }
            },
        ),
        (
            lambda client: client.get_compound("999999999999999999"),
            {
                "result": {
                    "uids": ["999999999999999999"],
                    "999999999999999999": {
                        "uid": "999999999999999999",
                        "error": "cannot get document summary",
                    },
                }
            },
        ),
    ),
)
@pytest.mark.asyncio
async def test_extended_explicit_esummary_not_found_remains_none(
    call: ExtendedCall,
    payload: dict[str, Any],
    extended_client: NCBIExtendedClient,
) -> None:
    with patch.object(extended_client, "_make_request", new=AsyncMock(return_value=payload)):
        assert await call(extended_client) is None


def _article(pmid: str) -> dict[str, Any]:
    return {
        "MedlineCitation": {
            "PMID": pmid,
            "Article": {
                "ArticleTitle": "Strict provider response",
                "AuthorList": [],
                "Journal": {"Title": "Journal", "JournalIssue": {"PubDate": {"Year": "2024"}}},
            },
        },
        "PubmedData": {"ArticleIdList": []},
    }


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"ERROR": PRIVATE_PROVIDER_DETAIL},
        {"PubmedArticle": {}},
        {"PubmedArticle": [None]},
        {"PubmedArticle": [{"MedlineCitation": {"PMID": "123", "Article": []}}]},
        {"PubmedArticle": [_article("999")]},
    ),
)
@pytest.mark.asyncio
async def test_fetch_details_rejects_malformed_efetch_payloads(
    payload: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _Searcher(SearchMixin):
        pass

    searcher = _Searcher()
    searcher._fetch_articles = AsyncMock(return_value=payload)  # type: ignore[method-assign]
    caplog.set_level(logging.DEBUG)

    with pytest.raises(NCBIProviderSchemaError) as exc_info:
        await searcher.fetch_details(["123"])

    assert str(exc_info.value) == "NCBI fetch_details failed"
    assert exc_info.value.retryable is False
    assert PRIVATE_PROVIDER_DETAIL not in str(exc_info.value)
    assert PRIVATE_PROVIDER_DETAIL not in caplog.text


@pytest.mark.asyncio
async def test_fetch_details_preserves_explicit_empty_and_partial_not_found() -> None:
    class _Searcher(SearchMixin):
        pass

    searcher = _Searcher()
    searcher._fetch_articles = AsyncMock(return_value={"PubmedArticle": []})  # type: ignore[method-assign]
    assert await searcher.fetch_details(["123"]) == []

    searcher._fetch_articles = AsyncMock(  # type: ignore[method-assign]
        return_value={"PubmedArticle": [_article("123")]}
    )
    rows = await searcher.fetch_details(["123", "456"])
    assert [row["pmid"] for row in rows] == ["123"]


@pytest.mark.asyncio
async def test_timeline_does_not_convert_efetch_schema_failure_to_no_results() -> None:
    searcher = MagicMock()
    searcher.fetch_details = AsyncMock(side_effect=NCBIProviderSchemaError("fetch_details"))

    with pytest.raises(TimelineRetrievalError, match="PubMed detail retrieval failed"):
        await TimelineBuilder(searcher).build_timeline_from_pmids(["123"])


@pytest.mark.asyncio
async def test_citation_lookup_does_not_convert_efetch_schema_failure_to_no_results() -> None:
    class _CitationSearcher(CitationMixin):
        pass

    searcher = _CitationSearcher()
    handle = MagicMock()
    searcher._rate_limited_call = AsyncMock(return_value=handle)
    searcher.fetch_details = AsyncMock(side_effect=NCBIProviderSchemaError("fetch_details"))
    record = [{"LinkSetDb": [{"LinkName": "pubmed_pubmed", "Link": [{"Id": "456"}]}]}]

    with patch(
        "pubmed_search.infrastructure.ncbi.citation._read_entrez_handle",
        new=AsyncMock(return_value=record),
    ):
        with pytest.raises(NCBIInfrastructureError) as exc_info:
            await searcher.get_related_articles("123")

    assert exc_info.value.operation == "related_articles"
    assert exc_info.value.upstream_type == "ProviderSchemaError"


@pytest.mark.asyncio
async def test_local_export_does_not_convert_efetch_schema_failure_to_no_results() -> None:
    mcp = MagicMock()
    tools: dict[str, Callable[..., Awaitable[str]]] = {}
    mcp.tool = lambda: lambda function: (tools.__setitem__(function.__name__, function), function)[1]
    searcher = MagicMock()
    searcher.fetch_details = AsyncMock(side_effect=NCBIProviderSchemaError("fetch_details"))
    register_export_tools(mcp, searcher)

    result = await tools["prepare_export"](pmids="123", format="json", source="local")
    payload = json.loads(result)

    assert payload["error"] == "Citation export could not be completed"
    assert "No results" not in result


@pytest.mark.asyncio
async def test_fetch_article_details_tool_reports_efetch_schema_failure() -> None:
    mcp = MagicMock()
    tools: dict[str, Callable[..., Awaitable[str]]] = {}
    mcp.tool = lambda: lambda function: (tools.__setitem__(function.__name__, function), function)[1]
    searcher = MagicMock()
    searcher.fetch_details = AsyncMock(side_effect=NCBIProviderSchemaError("fetch_details"))
    register_discovery_tools(mcp, searcher)

    result = await tools["fetch_article_details"](pmids="123", output_format="json")

    assert "PubMed article-detail lookup failed" in result
    assert "No results" not in result
    assert PRIVATE_PROVIDER_DETAIL not in result


@pytest.mark.parametrize(
    ("tool_name", "client_method", "arguments", "expected_message"),
    (
        ("search_gene", "search_gene", {"query": "BRCA1"}, "NCBI Gene search could not be completed"),
        ("get_gene_details", "get_gene", {"gene_id": "672"}, "NCBI Gene details could not be retrieved"),
        (
            "get_gene_literature",
            "get_gene_pubmed_links",
            {"gene_id": "672"},
            "NCBI Gene literature could not be retrieved",
        ),
        ("search_compound", "search_compound", {"query": "aspirin"}, "PubChem search could not be completed"),
        (
            "get_compound_details",
            "get_compound",
            {"cid": "2244"},
            "PubChem compound details could not be retrieved",
        ),
        (
            "get_compound_literature",
            "get_compound_pubmed_links",
            {"cid": "2244"},
            "PubChem literature could not be retrieved",
        ),
        ("search_clinvar", "search_clinvar", {"query": "BRCA1"}, "ClinVar search could not be completed"),
    ),
)
@pytest.mark.asyncio
async def test_all_extended_tools_report_provider_failure_instead_of_no_results(
    tool_name: str,
    client_method: str,
    arguments: dict[str, Any],
    expected_message: str,
) -> None:
    mcp = MagicMock()
    tools: dict[str, Callable[..., Awaitable[str]]] = {}
    mcp.tool = lambda: lambda function: (tools.__setitem__(function.__name__, function), function)[1]
    register_ncbi_extended_tools(mcp)
    client = MagicMock()
    setattr(client, client_method, AsyncMock(side_effect=RuntimeError(PRIVATE_PROVIDER_DETAIL)))

    with patch(
        "pubmed_search.infrastructure.sources.get_ncbi_extended_client",
        return_value=client,
    ):
        result = await tools[tool_name](**arguments)

    assert expected_message in result
    assert "No results" not in result
    assert PRIVATE_PROVIDER_DETAIL not in result
