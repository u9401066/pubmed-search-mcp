"""Regression tests for the pipeline alternate-source DTO boundary."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.pipeline.executor import PipelineExecutor
from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.domain.entities.pipeline import PipelineStep
from pubmed_search.presentation.mcp_server.tools.unified_pipeline import _execute_pipeline_mode


def _openalex_raw_work() -> dict:
    return {
        "id": "https://openalex.org/W314159",
        "doi": "https://doi.org/10.1000/openalex.raw",
        "ids": {
            "doi": "https://doi.org/10.1000/openalex.raw",
            "pmid": "https://pubmed.ncbi.nlm.nih.gov/31415926/",
        },
        "display_name": "OpenAlex raw DTO",
        "authorships": [
            {
                "author": {
                    "display_name": "Ada Lovelace",
                    "orcid": "https://orcid.org/0000-0001-0000-0001",
                }
            }
        ],
        "publication_year": 2025,
        "publication_date": "2025-04-01",
        "type": "article",
        "open_access": {"is_oa": True, "oa_status": "gold"},
        "primary_location": {"source": {"display_name": "Raw Journal"}},
        "cited_by_count": 17,
    }


def _semantic_scholar_raw_paper() -> dict:
    return {
        "paperId": "s2-raw-paper-id",
        "externalIds": {
            "DOI": "10.1000/s2.raw",
            "PubMed": "27182818",
        },
        "title": "Semantic Scholar raw DTO",
        "authors": [{"authorId": "author-1", "name": "Grace Hopper"}],
        "year": 2024,
        "venue": "Raw Proceedings",
        "citationCount": 23,
        "influentialCitationCount": 5,
        "isOpenAccess": True,
    }


async def test_pipeline_maps_openalex_and_s2_raw_page_dtos_once() -> None:
    """The production page seam preserves provider IDs, authors, PMIDs, and DOIs."""

    pages = {
        "openalex": SourceSearchPage(source="openalex", items=[_openalex_raw_work()]),
        "semantic_scholar": SourceSearchPage(
            source="semantic_scholar",
            items=[_semantic_scholar_raw_paper()],
        ),
    }

    async def search_page(**kwargs):
        return pages[kwargs["source"]]

    page_search = AsyncMock(side_effect=search_page)
    executor = PipelineExecutor(alternate_search_page_fn=page_search)
    step = PipelineStep(
        id="search",
        action="search",
        params={
            "query": "provider DTO seam",
            "sources": "openalex,semantic_scholar",
            "limit": 10,
        },
    )

    result = await executor._action_search(step, {})

    assert result.ok
    assert result.metadata["source_api_counts"] == {"openalex": 1, "semantic_scholar": 1}
    by_source = {article.primary_source: article for article in result.articles}

    openalex = by_source["openalex"]
    assert openalex.openalex_id == "W314159"
    assert openalex.pmid == "31415926"
    assert openalex.doi == "10.1000/openalex.raw"
    assert [author.display_name for author in openalex.authors] == ["Ada Lovelace"]

    semantic_scholar = by_source["semantic_scholar"]
    assert semantic_scholar.s2_id == "s2-raw-paper-id"
    assert semantic_scholar.pmid == "27182818"
    assert semantic_scholar.doi == "10.1000/s2.raw"
    assert [author.display_name for author in semantic_scholar.authors] == ["Grace Hopper"]
    assert page_search.await_count == 2


async def test_pipeline_keeps_legacy_normalized_list_injection_compatible() -> None:
    """Third-party list injectors use the explicit legacy normalized contract."""

    records = {
        "openalex": [
            {
                "pmid": "11111111",
                "title": "Legacy OpenAlex",
                "year": "2023",
                "authors": ["Legacy OA Author"],
                "doi": "10.1000/openalex.legacy",
                "_openalex_id": "https://openalex.org/W111",
                "citation_count": 9,
            }
        ],
        "semantic_scholar": [
            {
                "pmid": "22222222",
                "title": "Legacy Semantic Scholar",
                "year": "2022",
                "authors": ["Legacy S2 Author"],
                "doi": "10.1000/s2.legacy",
                "_s2_id": "s2-legacy-id",
                "citation_count": 7,
            }
        ],
    }

    async def legacy_search(**kwargs):
        return records[kwargs["source"]]

    legacy = AsyncMock(side_effect=legacy_search)
    executor = PipelineExecutor(alternate_search_fn=legacy)
    step = PipelineStep(
        id="legacy",
        action="search",
        params={"query": "legacy seam", "sources": "openalex,semantic_scholar"},
    )

    result = await executor._action_search(step, {})

    assert result.ok
    by_source = {article.primary_source: article for article in result.articles}
    openalex = by_source["openalex"]
    assert (openalex.openalex_id, openalex.pmid, openalex.doi) == (
        "W111",
        "11111111",
        "10.1000/openalex.legacy",
    )
    assert [author.display_name for author in openalex.authors] == ["Legacy OA Author"]

    semantic_scholar = by_source["semantic_scholar"]
    assert (semantic_scholar.s2_id, semantic_scholar.pmid, semantic_scholar.doi) == (
        "s2-legacy-id",
        "22222222",
        "10.1000/s2.legacy",
    )
    assert [author.display_name for author in semantic_scholar.authors] == ["Legacy S2 Author"]
    assert legacy.await_count == 2


async def test_pipeline_rejects_list_from_raw_page_contract() -> None:
    """A violated page contract fails loudly instead of inspecting item keys."""

    page_search = AsyncMock(return_value=[_openalex_raw_work()])
    executor = PipelineExecutor(alternate_search_page_fn=page_search)

    with pytest.raises(TypeError, match="must return SourceSearchPage"):
        await executor._search_alternate("openalex", "test", 10, None, None)


async def test_inline_pipeline_wires_production_raw_page_search() -> None:
    """Inline unified_search pipelines inject the page seam, never the legacy list."""

    config = json.dumps(
        {
            "steps": [
                {
                    "id": "search",
                    "action": "search",
                    "params": {"query": "raw page", "sources": "openalex"},
                }
            ],
            "output": {"format": "json"},
        }
    )

    with patch("pubmed_search.application.pipeline.executor.PipelineExecutor") as executor_cls:
        executor_cls.return_value.execute = AsyncMock(return_value=([], {}))
        result = await _execute_pipeline_mode(config, "json", MagicMock())

    assert json.loads(result)["type"] == "pipeline_result"
    kwargs = executor_cls.call_args.kwargs
    assert "alternate_search_fn" not in kwargs
    assert kwargs["alternate_search_page_fn"].__name__ == "search_alternate_source_page"


async def test_pipeline_marks_all_provider_failures_as_a_failed_step() -> None:
    private_query = "PRIVATE_QUERY_SENTINEL"
    secret = "TOPSECRET_SENTINEL"
    page_search = AsyncMock(side_effect=RuntimeError(f"failed {private_query} token={secret}"))
    executor = PipelineExecutor(alternate_search_page_fn=page_search)
    step = PipelineStep(
        id="all-failed",
        action="search",
        params={"query": "safe query", "sources": "openalex,semantic_scholar"},
    )

    result = await executor._action_search(step, {})

    assert result.ok is False
    assert result.error == "All selected search sources failed"
    assert len(result.metadata["source_errors"]) == 2
    serialized = json.dumps(result.metadata)
    assert private_query not in serialized
    assert secret not in serialized


async def test_pipeline_keeps_valid_empty_plus_provider_failure_partial() -> None:
    async def search_page(**kwargs):
        if kwargs["source"] == "openalex":
            return SourceSearchPage(source="openalex", items=[])
        raise TimeoutError("synthetic timeout")

    executor = PipelineExecutor(alternate_search_page_fn=AsyncMock(side_effect=search_page))
    step = PipelineStep(
        id="partial-empty",
        action="search",
        params={"query": "safe query", "sources": "openalex,semantic_scholar"},
    )

    result = await executor._action_search(step, {})

    assert result.ok is True
    assert result.articles == []
    assert result.metadata["source_api_counts"] == {"openalex": 0, "semantic_scholar": 0}
    assert result.metadata["source_errors"][0]["source"] == "semantic_scholar"
