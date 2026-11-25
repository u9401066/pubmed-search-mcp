"""Pipelines never rewrite a saved strategy; they record MeSH correction suggestions.

The PubMed searcher double answers like ``LiteratureSearcher``: a query with
``"Post-Anesthesia Care Units"[Mesh]`` reports PubMed's live-shaped
``QuotedPhraseNotFound`` diagnostics (``search_page`` metadata and
``esearch_snapshot`` provider warnings). MeSH evidence comes from the
production gateway over ``tests.fixtures.mesh_entrez``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from pubmed_search.application.pipeline.budgets import PipelineExecutionPolicy
from pubmed_search.application.pipeline.executor import PipelineExecutor
from pubmed_search.application.pipeline.mesh_suggestions import count_scope_for, suggestion_note
from pubmed_search.application.pipeline.report_generator import generate_pipeline_report
from pubmed_search.application.pipeline.store import PipelineStore
from pubmed_search.application.pipeline.validator import parse_and_validate_config
from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.domain.value_objects.query_diagnostics import PubMedQueryDiagnostics
from pubmed_search.presentation.mcp_server.tools.pipeline_tools import PipelineToolRuntime, register_pipeline_tools
from pubmed_search.presentation.mcp_server.tools.tool_session import ToolSessionRuntime, bind_tool_session_runtime
from pubmed_search.presentation.mcp_server.tools.unified_pipeline import _execute_pipeline_mode_outcome
from tests.fixtures.mesh_entrez import PACU, PACU_QUERY, FakeEntrez, make_service
from tests.test_pipeline_exhaustive import _pubmed_row

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

BLOCK_QUERY = f"({PACU} OR PACU[tiab]) AND delirium[tiab]"


def _diagnostics(query: str) -> PubMedQueryDiagnostics:
    if PACU in query:
        return PubMedQueryDiagnostics(query_translation=query, quoted_phrases_not_found=(PACU,))
    return PubMedQueryDiagnostics(query_translation=query)


class FlaggingSearcher:
    """PubMed double whose unresolved MeSH clause matches nothing, with PubMed's warning."""

    def __init__(self) -> None:
        self.search_queries: list[str] = []
        self.count_queries: list[str] = []

    async def search_page(self, *, query: str, limit: int, **filters: Any) -> SourceSearchPage[dict[str, Any]]:
        self.search_queries.append(query)
        physical = f"({query}) AND 2020/01/01:2100/12/31[dp]" if filters.get("min_year") else query
        diagnostics = _diagnostics(physical)
        items = [] if PACU in query else [_pubmed_row(str(pmid)) for pmid in range(1, limit + 1)]
        return SourceSearchPage(
            source="pubmed",
            items=items,
            total=len(items),
            query=physical,
            warnings=diagnostics.issue_messages(),
            metadata={"physical_query": physical, "query_diagnostics": diagnostics.to_dict()},
        )

    async def esearch_snapshot(self, query: str, *, retmax: int, use_history: bool = True, **_: Any) -> dict:
        self.count_queries.append(query)
        has_pacu_text, has_delirium = "PACU[tiab]" in query, "delirium[tiab]" in query
        if has_pacu_text:
            count = 40 if has_delirium else 300
        else:
            # A quoted phrase PubMed cannot find contributes no records; ANDed with it, nothing matches.
            count = 0 if PACU in query or not has_delirium else 5_000
        diagnostics = _diagnostics(query).to_dict()
        return {
            "count": count,
            "pmids": [],
            "logical_query": query,
            "physical_query": query,
            "query_translation": query,
            "translation_set": [],
            "provider_errors": diagnostics["error_list"],
            "provider_warnings": diagnostics["warning_list"],
        }


@pytest.fixture
def fake_entrez() -> Iterator[FakeEntrez]:
    entrez = FakeEntrez()
    with entrez.installed():
        yield entrez


@pytest.fixture
def store(tmp_path: Path) -> PipelineStore:
    return PipelineStore(global_data_dir=tmp_path / "global", workspace_dir=tmp_path / "workspace")


def _config(steps: list[dict[str, Any]]) -> Any:
    result = parse_and_validate_config({"steps": steps, "output": {"format": "json", "limit": 5}})
    assert result.valid and result.config is not None
    return result.config


async def test_saved_strategy_is_not_rewritten_and_prisma_s_records_the_suggestion(
    fake_entrez: FakeEntrez, store: PipelineStore
) -> None:
    store.save(
        "pacu",
        _config([{"id": "pubmed", "action": "search", "params": {"query": PACU_QUERY, "limit": 3, "min_year": 2020}}]),
        scope="workspace",
    )
    searcher = FlaggingSearcher()

    with bind_tool_session_runtime(ToolSessionRuntime(mesh_correction=make_service())):
        outcome = await _execute_pipeline_mode_outcome("saved:pacu", "json", searcher, pipeline_store=store)

    # Suggest-only: PubMed ran the saved query exactly once, and the saved config is unchanged.
    assert searcher.search_queries == [PACU_QUERY]
    saved, _meta = store.load("pacu")
    assert saved.steps[0].params["query"] == PACU_QUERY

    response = json.loads(outcome.response)
    suggestion = response["steps"][0]["metadata"]["mesh_correction"]
    assert (suggestion["mode"], suggestion["applied"], suggestion["status"]) == ("suggestion", False, "corrected")
    assert suggestion["unresolved_clauses"] == [PACU]
    assert '"Anesthesia Recovery Period"[Mesh]' in suggestion["corrected_query"]
    assert suggestion["corrections"][0]["tier"] == "co_occurrence"
    assert "save a new pipeline version" in suggestion["adopt"]
    # The after-count was measured with the step's date filter.
    assert any(
        "Anesthesia Recovery Period" in term and "[dp]" in term
        for kind, db, term in fake_entrez.calls
        if (kind, db) == ("esearch", "pubmed")
    )
    assert any("suggested MeSH correction (not applied)" in warning for warning in response["warnings"])

    [run] = store.get_history("pacu")
    [search] = run.searches
    assert search["mesh_correction"]["corrected_query"] == suggestion["corrected_query"]
    assert search["provider_notes"]["quoted_phrases_not_found"] == [PACU]
    assert search["query_translation"].endswith("[dp]")
    assert "save a new pipeline version to adopt it" in search["notes"]

    tools: dict[str, Any] = {}
    mcp = MagicMock()
    mcp.tool = lambda: lambda func: tools.setdefault(func.__name__, func)
    register_pipeline_tools(mcp, runtime=PipelineToolRuntime(base_store=store))
    prisma = tools["get_pipeline_history"](name="pacu", view="prisma_s")
    assert "PubMed could not resolve" in prisma and "not applied" in prisma


async def test_markdown_report_explains_how_to_adopt(fake_entrez: FakeEntrez) -> None:
    config = _config([{"id": "pubmed", "action": "search", "params": {"query": PACU_QUERY, "limit": 3}}])
    executor = PipelineExecutor(searcher=FlaggingSearcher(), mesh_correction=make_service())

    articles, results = await executor.execute(config)
    report = generate_pipeline_report(articles, results, config)

    assert "PubMed MeSH clauses that matched nothing" in report
    assert "Saved strategies are never rewritten automatically" in report


async def test_suggestion_respects_the_run_quota_and_never_fails_the_run(fake_entrez: FakeEntrez) -> None:
    config = _config([{"id": "pubmed", "action": "search", "params": {"query": PACU_QUERY, "limit": 3}}])
    executor = PipelineExecutor(
        searcher=FlaggingSearcher(),
        mesh_correction=make_service(),
        execution_policy=PipelineExecutionPolicy(max_external_calls=5),
    )

    _articles, results = await executor.execute(config)

    suggestion = results["pubmed"].metadata["mesh_correction"]
    assert suggestion["status"] == "skipped" and suggestion["corrected_query"] == PACU_QUERY
    assert "quota" in suggestion["warnings"][0]
    assert results["pubmed"].error is None
    assert fake_entrez.calls == []


async def test_without_a_service_the_unresolved_clause_is_still_recorded() -> None:
    config = _config([{"id": "pubmed", "action": "search", "params": {"query": PACU_QUERY, "limit": 3}}])

    _articles, results = await PipelineExecutor(searcher=FlaggingSearcher()).execute(config)

    suggestion = results["pubmed"].metadata["mesh_correction"]
    assert (suggestion["status"], suggestion["unresolved_clauses"]) == ("unavailable", [PACU])
    assert "PubMed could not resolve" in (suggestion_note(suggestion) or "")


async def test_valid_pipeline_query_gets_no_suggestion() -> None:
    config = _config([{"id": "pubmed", "action": "search", "params": {"query": '"Delirium"[Mesh]', "limit": 3}}])

    _articles, results = await PipelineExecutor(searcher=FlaggingSearcher(), mesh_correction=MagicMock()).execute(
        config
    )

    assert "mesh_correction" not in results["pubmed"].metadata


async def test_block_analysis_marks_terms_pubmed_did_not_find(fake_entrez: FakeEntrez) -> None:
    config = _config([{"id": "blocks", "action": "block_analysis", "params": {"query": BLOCK_QUERY}}])
    searcher = FlaggingSearcher()
    executor = PipelineExecutor(searcher=searcher, mesh_correction=make_service())

    articles, results = await executor.execute(config)

    analysis = results["blocks"].metadata["block_analysis"]
    terms = {term["term"]: term for term in analysis["terms"]}
    broken = terms[PACU]
    assert broken["unique_contribution"] == 0
    assert broken["pubmed_not_found"] == [PACU] and broken["contribution_meaningful"] is False
    assert analysis["unresolved_terms"] == [{"block": "B1", "term": PACU, "not_found": [PACU]}]
    # A broken term is not presented as a redundant one.
    assert {"block": "B1", "term": PACU} not in analysis["zero_contribution_terms"]
    assert terms["PACU[tiab]"]["unique_contribution"] == 40
    assert "contribution_meaningful" not in terms["PACU[tiab]"]
    suggestion = analysis["mesh_correction"]
    assert suggestion["mode"] == "suggestion" and '"Anesthesia Recovery Period"[Mesh]' in suggestion["corrected_query"]

    report = generate_pipeline_report(articles, results, config)
    assert "PubMed did not find these terms" in report


def test_count_scope_reuses_the_compiled_filter_suffix() -> None:
    scope = count_scope_for("a[tiab]", "(a[tiab]) AND 2020/01/01:2100/12/31[dp]")
    assert scope is not None and scope("b[tiab]") == "(b[tiab]) AND 2020/01/01:2100/12/31[dp]"
    assert count_scope_for("a[tiab]", "a[tiab]") is None
    assert count_scope_for("a[tiab]", "unrelated") is None
