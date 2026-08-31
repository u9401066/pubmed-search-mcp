"""Regression tests for the pipeline alternate-source adapter boundary."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.pipeline.executor import PipelineExecutor
from pubmed_search.domain.entities.pipeline import PipelineStep
from pubmed_search.presentation.mcp_server.tools.unified_pipeline import _execute_pipeline_mode_outcome
from pubmed_search.shared.source_contracts import SourceAdapterResult


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


async def test_pipeline_maps_openalex_and_s2_adapter_dtos_once() -> None:
    """The adapter seam preserves provider IDs, authors, PMIDs, DOIs, and provenance."""

    pages = {
        "openalex": SourceAdapterResult(
            source="openalex",
            operation="search",
            items=[_openalex_raw_work()],
            total_count=10,
            status="ok",
            cursor="cursor-1",
            cost=0.01,
            provenance={"physical_query": "provider DTO seam"},
        ),
        "semantic_scholar": SourceAdapterResult(
            source="semantic_scholar",
            operation="search",
            items=[_semantic_scholar_raw_paper()],
            total_count=1,
            status="ok",
        ),
    }

    async def search_page(**kwargs):
        return pages[kwargs["source"]]

    adapter_search = AsyncMock(side_effect=search_page)
    executor = PipelineExecutor(alternate_search_adapter=adapter_search)
    step = PipelineStep(
        id="search",
        action="search",
        params={
            "query": "provider DTO seam",
            "sources": ["openalex", "semantic_scholar"],
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
    assert result.metadata["source_results"]["openalex"] == {
        "status": "ok",
        "total_count": 10,
        "next_token": None,
        "cursor": "cursor-1",
        "cost": 0.01,
        "provenance": {"physical_query": "provider DTO seam"},
    }
    assert adapter_search.await_count == 2


async def test_pipeline_rejects_list_from_adapter_contract() -> None:
    """A violated adapter contract fails loudly instead of inspecting item keys."""

    adapter_search = AsyncMock(return_value=[_openalex_raw_work()])
    executor = PipelineExecutor(alternate_search_adapter=adapter_search)

    with pytest.raises(TypeError, match="must return SourceAdapterResult"):
        await executor._search_alternate("openalex", "test", 10, None, None)


async def test_pipeline_non_adapter_result_fails_closed_at_step_boundary() -> None:
    adapter_search = AsyncMock(return_value={"source": "openalex", "items": [_openalex_raw_work()]})
    executor = PipelineExecutor(alternate_search_adapter=adapter_search)
    step = PipelineStep(
        id="invalid-page",
        action="search",
        params={"query": "typed seam", "sources": ["openalex"]},
    )

    result = await executor._action_search(step, {})

    assert result.ok is False
    assert result.articles == []
    assert result.error == "All selected search sources failed"
    assert result.metadata["source_api_counts"] == {"openalex": 0}
    assert result.metadata["source_errors"][0]["kind"] == "unexpected"


async def test_inline_pipeline_wires_production_adapter_search() -> None:
    """Inline unified_search pipelines inject the sole typed adapter seam."""

    config = json.dumps(
        {
            "steps": [
                {
                    "id": "search",
                    "action": "search",
                    "params": {"query": "raw page", "sources": ["openalex"]},
                }
            ],
            "output": {"format": "json"},
        }
    )

    with patch("pubmed_search.application.pipeline.executor.PipelineExecutor") as executor_cls:
        executor_cls.return_value.execute = AsyncMock(return_value=([], {}))
        outcome = await _execute_pipeline_mode_outcome(
            config,
            "json",
            MagicMock(),
            pipeline_store=None,
        )

    assert outcome.status == "completed"
    assert json.loads(outcome.response)["type"] == "pipeline_result"
    kwargs = executor_cls.call_args.kwargs
    assert kwargs["alternate_search_adapter"].__name__ == "search_alternate_source_adapter"


async def test_pipeline_marks_all_provider_failures_as_a_failed_step() -> None:
    private_query = "PRIVATE_QUERY_SENTINEL"
    secret = "TOPSECRET_SENTINEL"
    adapter_search = AsyncMock(side_effect=RuntimeError(f"failed {private_query} token={secret}"))
    executor = PipelineExecutor(alternate_search_adapter=adapter_search)
    step = PipelineStep(
        id="all-failed",
        action="search",
        params={"query": "safe query", "sources": ["openalex", "semantic_scholar"]},
    )

    result = await executor._action_search(step, {})

    assert result.ok is False
    assert result.error == "All selected search sources failed"
    assert len(result.metadata["source_errors"]) == 2
    serialized = json.dumps(result.metadata)
    assert private_query not in serialized
    assert secret not in serialized


async def test_pipeline_keeps_valid_empty_plus_provider_failure_partial() -> None:
    async def search_adapter(**kwargs):
        if kwargs["source"] == "openalex":
            return SourceAdapterResult.empty(source="openalex", operation="search")
        raise TimeoutError("synthetic timeout")

    executor = PipelineExecutor(alternate_search_adapter=AsyncMock(side_effect=search_adapter))
    step = PipelineStep(
        id="partial-empty",
        action="search",
        params={"query": "safe query", "sources": ["openalex", "semantic_scholar"]},
    )

    result = await executor._action_search(step, {})

    assert result.ok is True
    assert result.articles == []
    assert result.metadata["source_api_counts"] == {"openalex": 0, "semantic_scholar": 0}
    assert result.metadata["source_errors"][0]["source"] == "semantic_scholar"
