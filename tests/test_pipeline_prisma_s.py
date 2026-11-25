"""PRISMA-S run records, strategy-version history and full-set exports."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from pubmed_search import __version__
from pubmed_search.application.pipeline.prisma_s import PRISMA_S_COLUMNS
from pubmed_search.application.pipeline.store import PipelineStore
from pubmed_search.application.pipeline.validator import parse_and_validate_config
from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.presentation.mcp_server.tools.export import register_export_tools
from pubmed_search.presentation.mcp_server.tools.pipeline_tools import PipelineToolRuntime, register_pipeline_tools
from pubmed_search.presentation.mcp_server.tools.unified_pipeline import _execute_pipeline_mode_outcome
from tests.test_pipeline_exhaustive import QUERY, FakeHistorySearcher, _pubmed_row

QUERY_V2 = QUERY + ' AND ("Anesthesia Recovery Period"[Mesh] OR PACU[tiab])'


def _save(store: PipelineStore, name: str, query: str, **extra: Any) -> str:
    result = parse_and_validate_config(
        {
            "steps": [
                {
                    "id": "pubmed",
                    "action": "search",
                    "params": {"query": query, "sources": ["pubmed"], "retrieval": "exhaustive", **extra},
                }
            ],
            "output": {"format": "json", "limit": 10},
        }
    )
    assert result.valid and result.config is not None
    meta, _ = store.save(name, result.config, scope="workspace")
    return meta.config_hash


def _tools(store: PipelineStore, searcher: Any) -> dict[str, Any]:
    tools: dict[str, Any] = {}
    mcp = MagicMock()
    mcp.tool = lambda: lambda func: tools.setdefault(func.__name__, func)
    runtime = PipelineToolRuntime(base_store=store)
    register_pipeline_tools(mcp, runtime=runtime)
    register_export_tools(mcp, searcher, pipeline_runtime=runtime)
    return tools


@pytest.fixture()
def store(tmp_path: Path) -> PipelineStore:
    return PipelineStore(global_data_dir=tmp_path / "global", workspace_dir=tmp_path / "workspace")


async def test_run_record_carries_prisma_s_provenance_and_immutable_snapshot(store: PipelineStore) -> None:
    config_hash = _save(store, "review", QUERY, min_year=2005)
    pmids = [str(100 + index) for index in range(12)]

    outcome = await _execute_pipeline_mode_outcome(
        "saved:review", "json", FakeHistorySearcher(pmids), pipeline_store=store
    )
    run_id = json.loads(outcome.response)["run"]["run_id"]
    run = store.get_run("review", run_id)

    assert run.record_version == 2
    assert run.server_version == __version__
    assert run.config_hash == config_hash
    assert re.fullmatch(r"[0-9a-f]{64}", run.config_sha256 or "")
    assert run.config_snapshot is not None
    saved_step = run.config_snapshot["saved"]["steps"][0]
    assert saved_step["params"]["query"] == QUERY
    [search] = run.searches
    assert search["database"] == "PubMed"
    assert "E-utilities" in search["platform"]
    assert search["interface"] == f"pubmed-search-mcp {__version__}"
    assert search["logical_query"] == QUERY
    assert search["physical_query"].endswith("[dp]")
    assert search["query_translation"] == f"translated: {QUERY}"
    assert search["total_count"] == 12
    assert search["retrieved_count"] == 12
    assert search["exhaustive"] is True
    assert search["filters"] == {"min_year": 2005}
    assert search["executed_at"].endswith("Z")

    # Editing the saved YAML must not rewrite what an earlier run claims it executed.
    _save(store, "review", QUERY_V2)
    reopened = PipelineStore(global_data_dir=store.global_data_dir, workspace_dir=store._workspace_dir)
    assert reopened.get_run("review", run_id).config_snapshot["saved"]["steps"][0]["params"]["query"] == QUERY


async def test_history_and_prisma_s_distinguish_strategy_versions(store: PipelineStore) -> None:
    first_hash = _save(store, "review", QUERY)
    await _execute_pipeline_mode_outcome("saved:review", "json", FakeHistorySearcher(["1", "2"]), pipeline_store=store)
    second_hash = _save(store, "review", QUERY_V2)
    await _execute_pipeline_mode_outcome(
        "saved:review", "json", FakeHistorySearcher(["1", "2", "3"]), pipeline_store=store
    )
    tools = _tools(store, FakeHistorySearcher([]))

    history = tools["get_pipeline_history"](name="review")
    assert first_hash != second_hash
    assert f"`{first_hash}`" in history and f"`{second_hash}`" in history
    assert "different strategy versions" in history

    prisma = tools["get_pipeline_history"](name="review", view="prisma_s")
    assert "## PRISMA-S search record" in prisma
    csv_text = prisma.split("```csv\n", 1)[1].split("\n```", 1)[0]
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    assert list(rows[0]) == list(PRISMA_S_COLUMNS)
    assert [row["search_strategy"] for row in rows] == [QUERY_V2, QUERY]
    assert [row["records_found"] for row in rows] == ["3", "2"]
    assert {row["database"] for row in rows} == {"PubMed"}
    assert [row["config_hash"] for row in rows] == [second_hash, first_hash]
    assert all(row["exhaustive"] == "yes" for row in rows)

    detail = json.loads(tools["get_pipeline_history"](name="review", view="run"))
    assert detail["type"] == "pipeline_run"
    assert detail["pmid_count"] == 3
    assert detail["searches"][0]["query_translation"] == f"translated: {QUERY_V2}"
    assert detail["config_snapshot"]["saved"]["steps"][0]["params"]["query"] == QUERY_V2


async def test_bounded_search_record_discloses_incompleteness(store: PipelineStore) -> None:
    result = parse_and_validate_config(
        {"steps": [{"id": "s", "action": "search", "params": {"query": "delirium", "limit": 3}}]}
    )
    assert result.config is not None
    store.save("bounded", result.config, scope="workspace")

    class BoundedSearcher:
        async def search_page(self, *, query: str, limit: int, **_: Any) -> SourceSearchPage[dict[str, Any]]:
            return SourceSearchPage(
                source="pubmed",
                items=[_pubmed_row(str(pmid)) for pmid in range(1, limit + 1)],
                total=405,
                query=query,
                metadata={"physical_query": query},
            )

    await _execute_pipeline_mode_outcome("saved:bounded", "json", BoundedSearcher(), pipeline_store=store)

    [search] = store.get_run("bounded").searches
    assert search["retrieval_mode"] == "bounded"
    assert search["exhaustive"] is False
    assert search["total_count"] == 405
    assert search["retrieved_count"] == 3
    assert "not a complete record set" in search["notes"]


@pytest.mark.parametrize("fmt", ["ris", "csv", "csl"])
async def test_run_export_parses_and_preserves_every_identifier(store: PipelineStore, fmt: str) -> None:
    _save(store, "review", QUERY)
    pmids = [str(7000 + index) for index in range(15)]
    await _execute_pipeline_mode_outcome("saved:review", "json", FakeHistorySearcher(pmids), pipeline_store=store)
    tools = _tools(store, FakeHistorySearcher([]))

    response = json.loads(await tools["prepare_export"](pipeline_run="review", format=fmt))

    assert response["status"] == "success"
    assert response["article_count"] == 15
    assert response["pipeline_run"]["metadata_missing_count"] == 0
    text = response["export_text"]
    if fmt == "ris":
        assert text.count("TY  - JOUR") == 15
        assert re.findall(r"^AN  - (\d+)$", text, flags=re.MULTILINE) == pmids
        assert f"DO  - 10.1000/{pmids[0]}" in text
    elif fmt == "csv":
        rows = list(csv.DictReader(io.StringIO(text)))
        assert [row["PMID"] for row in rows] == pmids
        assert rows[0]["DOI"] == f"10.1000/{pmids[0]}"
    else:
        items = json.loads(text)
        assert [item["PMID"] for item in items] == pmids
        assert items[0]["id"] == f"pmid:{pmids[0]}"
        assert items[0]["DOI"] == f"10.1000/{pmids[0]}"


async def test_large_run_export_is_a_file_and_backfills_missing_metadata_once(store: PipelineStore) -> None:
    _save(store, "review", QUERY, fetch_metadata=False)
    pmids = [str(9000 + index) for index in range(450)]
    outcome = await _execute_pipeline_mode_outcome(
        "saved:review", "json", FakeHistorySearcher(pmids), pipeline_store=store
    )
    run_id = json.loads(outcome.response)["run"]["run_id"]
    exporter = FakeHistorySearcher([])
    tools = _tools(store, exporter)

    response = json.loads(await tools["prepare_export"](pipeline_run=f"review@{run_id}", format="ris"))

    assert response["article_count"] == 450
    assert response["pipeline_run"]["metadata_backfilled"] == 450
    assert response["pipeline_run"]["metadata_missing_count"] == 0
    exported = Path(response["file_path"]).read_text(encoding="utf-8")
    assert re.findall(r"^AN  - (\d+)$", exported, flags=re.MULTILINE) == pmids
    assert [kind for kind, _ in exporter.calls] == ["details", "details", "details"]

    exporter.calls.clear()
    again = json.loads(await tools["prepare_export"](pipeline_run=f"review@{run_id}", format="csv"))
    assert again["pipeline_run"]["metadata_backfilled"] == 0
    assert exporter.calls == []  # metadata was cached in the run artifact


async def test_prepare_export_rejects_ambiguous_or_unknown_run(store: PipelineStore) -> None:
    _save(store, "review", QUERY)
    tools = _tools(store, FakeHistorySearcher([]))

    both = json.loads(await tools["prepare_export"](pmids=["1"], pipeline_run="review"))
    assert "either pmids or pipeline_run" in json.dumps(both)
    missing = json.loads(await tools["prepare_export"](pipeline_run="review@20990101_000000_000000_abc"))
    assert "not found" in json.dumps(missing).lower()
    neither = json.loads(await tools["prepare_export"]())
    assert "pmids or pipeline_run is required" in json.dumps(neither)
