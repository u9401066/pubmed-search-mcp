"""Exhaustive PubMed retrieval for systematic-review pipelines.

Covers the provider boundary (ESearch History Server snapshot + EFetch
``uilist`` paging through fake Entrez callables), the fail-closed config
contract, budget/cap behaviour, run persistence across a fresh store
instance, and the response-size bound for a 10,000-record run.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest

from pubmed_search.application.pipeline.budgets import PipelineExecutionPolicy
from pubmed_search.application.pipeline.executor import PipelineExecutor, final_record_set
from pubmed_search.application.pipeline.exhaustive import (
    ExhaustiveCapExceededError,
    retrieve_pubmed_exhaustive,
)
from pubmed_search.application.pipeline.store import PipelineStore
from pubmed_search.application.pipeline.validator import parse_and_validate_config
from pubmed_search.domain.entities.pipeline import PipelineConfig, PipelineOutput, PipelineStep
from pubmed_search.infrastructure.ncbi import LiteratureSearcher
from pubmed_search.infrastructure.ncbi import batch as ncbi_batch
from pubmed_search.infrastructure.ncbi.base import NCBIInfrastructureError

if TYPE_CHECKING:
    from pathlib import Path

QUERY = '("Delirium"[Mesh] OR delirium[tiab]) AND ("bispectral index"[tiab] OR "Consciousness Monitors"[Mesh])'


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _Handle:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.closed = False

    def read(self) -> Any:
        return self.payload

    def close(self) -> None:
        self.closed = True


class FakeEntrezHistoryServer:
    """Minimal stand-in for ESearch (usehistory) and EFetch (rettype=uilist)."""

    def __init__(self, pmids: list[str]) -> None:
        self.pmids = pmids
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def esearch(self, **kwargs: Any) -> _Handle:
        self.calls.append(("esearch", kwargs))
        return _Handle(("esearch", kwargs))

    def efetch(self, **kwargs: Any) -> _Handle:
        self.calls.append(("efetch", kwargs))
        assert kwargs["rettype"] == "uilist"
        assert kwargs["retmode"] == "text"
        assert kwargs["webenv"] == "MCID_FAKE_WEBENV"
        assert kwargs["query_key"] == "1"
        start, size = kwargs["retstart"], kwargs["retmax"]
        return _Handle("\n".join(self.pmids[start : start + size]) + "\n")

    def read(self, handle: _Handle) -> dict[str, Any]:
        kind, kwargs = handle.payload
        assert kind == "esearch"
        retmax = kwargs["retmax"]
        record: dict[str, Any] = {
            "Count": str(len(self.pmids)),
            "RetMax": str(min(retmax, len(self.pmids))),
            "IdList": list(self.pmids[:retmax]),
            "QueryTranslation": '"delirium"[MeSH Terms] OR "delirium"[Title/Abstract]',
            "TranslationSet": [{"From": "delirium", "To": '"delirium"[MeSH Terms]'}],
            "ErrorList": {"PhraseNotFound": ["zzqx"], "FieldNotFound": []},
            "WarningList": {"QuotedPhraseNotFound": [], "PhraseIgnored": [], "OutputMessage": ["No items found."]},
        }
        if kwargs.get("usehistory") == "y":
            record.update({"WebEnv": "MCID_FAKE_WEBENV", "QueryKey": "1"})
        return record


def _pubmed_row(pmid: str) -> dict[str, Any]:
    return {
        "pmid": pmid,
        "title": f"Processed EEG and delirium {pmid}",
        "authors": ["Doe Jane", "Roe Rick"],
        "authors_full": [{"last_name": "Doe", "fore_name": "Jane"}, {"last_name": "Roe", "fore_name": "Rick"}],
        "abstract": "Background. Methods. Results.",
        "journal": "Journal of Testing",
        "journal_abbrev": "J Test",
        "year": "2024",
        "doi": f"10.1000/{pmid}",
        "pmc_id": "",
        "publication_types": ["Randomized Controlled Trial"],
        "keywords": [],
        "mesh_terms": ["Delirium"],
        "language": "eng",
    }


class FakeHistorySearcher:
    """Application-boundary fake for the three provider operations exhaustive mode uses."""

    def __init__(self, pmids: list[str], *, fail_metadata: bool = False) -> None:
        self.pmids = pmids
        self.fail_metadata = fail_metadata
        self.calls: list[tuple[str, Any]] = []

    async def esearch_snapshot(self, query: str, *, retmax: int, use_history: bool = True, **filters: Any):
        self.calls.append(("esearch", {"query": query, "retmax": retmax, "filters": filters}))
        suffix = f" AND {filters['min_year']}/01/01:2100/12/31[dp]" if "min_year" in filters else ""
        return {
            "count": len(self.pmids),
            "pmids": list(self.pmids[:retmax]),
            "webenv": "W1",
            "query_key": "1",
            "logical_query": query,
            "physical_query": f"({query}){suffix}" if suffix else query,
            "query_translation": f"translated: {query}",
            "translation_set": [],
            "provider_errors": {"phrases_not_found": [], "fields_not_found": []},
            "provider_warnings": {"phrases_ignored": [], "quoted_phrases_not_found": [], "output_messages": []},
        }

    async def fetch_history_pmids(self, webenv: str, query_key: str, *, retstart: int, retmax: int) -> list[str]:
        self.calls.append(("page", {"retstart": retstart, "retmax": retmax}))
        return list(self.pmids[retstart : retstart + retmax])

    async def fetch_details(self, pmids: list[str]) -> list[dict[str, Any]]:
        self.calls.append(("details", len(pmids)))
        if self.fail_metadata:
            raise RuntimeError("upstream exploded")
        return [_pubmed_row(pmid) for pmid in pmids]


def _exhaustive_config(**params: Any) -> PipelineConfig:
    return PipelineConfig(
        name="ma",
        steps=[
            PipelineStep(
                id="pubmed",
                action="search",
                params={"query": QUERY, "sources": ["pubmed"], "retrieval": "exhaustive", **params},
            )
        ],
        output=PipelineOutput(format="json", limit=100),
    )


@pytest.fixture()
def store(tmp_path: Path) -> PipelineStore:
    return PipelineStore(global_data_dir=tmp_path / "global", workspace_dir=tmp_path / "workspace")


# ---------------------------------------------------------------------------
# Provider boundary: History Server snapshot + uilist paging
# ---------------------------------------------------------------------------


async def test_history_snapshot_pages_every_pmid_through_webenv(monkeypatch: pytest.MonkeyPatch) -> None:
    pmids = [str(1000 + index) for index in range(7)]
    server = FakeEntrezHistoryServer(pmids)
    monkeypatch.setattr(ncbi_batch.Entrez, "esearch", server.esearch)
    monkeypatch.setattr(ncbi_batch.Entrez, "efetch", server.efetch)
    monkeypatch.setattr(ncbi_batch.Entrez, "read", server.read)
    searcher = LiteratureSearcher(email="tests@example.org")

    reserved: list[int] = []

    async def reserve() -> None:
        reserved.append(1)

    retrieval = await retrieve_pubmed_exhaustive(
        searcher,
        QUERY,
        filters={"min_year": 2010},
        max_records=10_000,
        reserve_call=reserve,
        fetch_metadata=False,
        page_size=3,
    )

    assert retrieval.pmids == pmids
    assert retrieval.exhaustive is True
    assert retrieval.pages == 3
    assert len(reserved) == 3  # one budget unit per provider operation
    esearch_kwargs = server.calls[0][1]
    assert esearch_kwargs["usehistory"] == "y"
    assert esearch_kwargs["retmax"] == 3
    assert esearch_kwargs["term"].startswith(f"({QUERY}) AND 2010/01/01:")
    pages = [kwargs for kind, kwargs in server.calls if kind == "efetch"]
    assert [(page["retstart"], page["retmax"]) for page in pages] == [(3, 3), (6, 1)]
    snapshot = retrieval.snapshot
    assert "webenv" not in snapshot and "query_key" not in snapshot
    assert snapshot["query_translation"].startswith('"delirium"[MeSH Terms]')
    assert snapshot["provider_errors"]["phrases_not_found"] == ["zzqx"]
    assert snapshot["physical_query"] == esearch_kwargs["term"]


async def test_count_only_snapshot_does_not_store_history(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeEntrezHistoryServer(["11", "12"])
    monkeypatch.setattr(ncbi_batch.Entrez, "esearch", server.esearch)
    monkeypatch.setattr(ncbi_batch.Entrez, "read", server.read)

    snapshot = await LiteratureSearcher(email="tests@example.org").esearch_snapshot(
        "delirium[tiab]", retmax=0, use_history=False
    )

    assert snapshot["count"] == 2
    assert snapshot["pmids"] == []
    assert snapshot["webenv"] is None
    assert server.calls[0][1]["usehistory"] == "n"
    assert server.calls[0][1]["retmax"] == 0


async def test_malformed_uilist_page_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeEntrezHistoryServer(["11", "12"])

    def bad_efetch(**kwargs: Any) -> _Handle:
        return _Handle("11\n<html>error</html>\n")

    monkeypatch.setattr(ncbi_batch.Entrez, "efetch", bad_efetch)
    with pytest.raises(NCBIInfrastructureError) as error:
        await LiteratureSearcher(email="tests@example.org").fetch_history_pmids(
            "MCID_FAKE_WEBENV", "1", retstart=0, retmax=2
        )
    assert error.value.upstream_type == "ProviderSchemaError"
    assert server.calls == []


# ---------------------------------------------------------------------------
# Config contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"retrieval": "exhaustive", "limit": 100}, "limit cannot be combined with retrieval: exhaustive"),
        ({"retrieval": "exhaustive", "sources": ["pubmed", "openalex"]}, "supports only sources: [pubmed]"),
        ({"retrieval": "exhaustive", "max_records": 10_001}, "less than or equal to 10000"),
        ({"max_records": 500}, "require retrieval: exhaustive"),
        ({"limit": 500}, "use retrieval: exhaustive"),
    ],
)
def test_exhaustive_contract_fails_closed(params: dict[str, Any], message: str) -> None:
    raw = {"steps": [{"id": "s", "action": "search", "params": {"query": "delirium", **params}}]}
    result = parse_and_validate_config(raw)
    assert not result.valid
    assert message in "; ".join(result.errors)


def test_exhaustive_config_is_accepted_without_limit() -> None:
    raw = {
        "steps": [
            {
                "id": "pubmed",
                "action": "search",
                "params": {"query": QUERY, "sources": ["pubmed"], "retrieval": "exhaustive", "max_records": 2000},
            }
        ],
        "output": {"format": "json", "limit": 100},
    }
    assert parse_and_validate_config(raw).valid


# ---------------------------------------------------------------------------
# Executor behaviour
# ---------------------------------------------------------------------------


async def test_executor_collects_full_set_and_keeps_output_limit_as_preview() -> None:
    pmids = [str(5000 + index) for index in range(405)]
    searcher = FakeHistorySearcher(pmids)
    executor = PipelineExecutor(searcher=searcher, exhaustive_page_size=200, exhaustive_metadata_batch_size=150)

    articles, results = await executor.execute(_exhaustive_config(min_year=2000))

    step = results["pubmed"]
    assert step.ok
    assert step.pmids == pmids
    assert len(step.records) == 405
    assert len(articles) == 100  # output.limit only shapes the preview
    assert final_record_set(results) == ("pubmed", pmids)
    retrieval = step.metadata["retrieval"]
    assert retrieval["total_count"] == 405
    assert retrieval["retrieved_count"] == 405
    assert retrieval["exhaustive"] is True
    assert retrieval["metadata_count"] == 405
    assert step.metadata["filters"] == {"min_year": 2000}
    assert step.metadata["pubmed_history"]["query_translation"] == f"translated: {QUERY}"
    assert [kind for kind, _ in searcher.calls].count("page") == 2
    assert [kind for kind, _ in searcher.calls].count("details") == 3


async def test_count_above_cap_is_refused_without_paging() -> None:
    searcher = FakeHistorySearcher([str(index) for index in range(1, 52)])
    executor = PipelineExecutor(searcher=searcher)

    _articles, results = await executor.execute(_exhaustive_config(max_records=50))

    step = results["pubmed"]
    assert not step.ok
    assert "above the exhaustive retrieval cap of 50" in (step.error or "")
    assert step.metadata["retrieval"]["total_count"] == 51
    assert step.metadata["retrieval"]["terminal_reason"] == "cap_exceeded"
    assert [kind for kind, _ in searcher.calls] == ["esearch"]


async def test_cap_error_type_reports_count_and_cap() -> None:
    searcher = FakeHistorySearcher([str(index) for index in range(1, 12)])

    async def reserve() -> None:
        return None

    with pytest.raises(ExhaustiveCapExceededError) as error:
        await retrieve_pubmed_exhaustive(searcher, QUERY, filters={}, max_records=10, reserve_call=reserve)
    assert (error.value.total_count, error.value.cap) == (11, 10)


async def test_budget_exhaustion_mid_paging_never_claims_a_complete_set() -> None:
    searcher = FakeHistorySearcher([str(index) for index in range(1, 101)])
    executor = PipelineExecutor(
        searcher=searcher,
        execution_policy=PipelineExecutionPolicy(max_external_calls=2),
        exhaustive_page_size=10,
    )

    articles, results = await executor.execute(_exhaustive_config(fetch_metadata=False))

    step = results["pubmed"]
    assert not step.ok
    assert step.pmids == []
    assert step.metadata["retrieval"]["exhaustive"] is False
    assert step.metadata["retrieval"]["retrieved_count"] == 20
    assert step.metadata["retrieval"]["terminal_reason"] == "external_call_quota_exhausted"
    assert articles == []


async def test_metadata_failure_keeps_identifier_set_complete_and_partial() -> None:
    pmids = [str(index) for index in range(1, 31)]
    executor = PipelineExecutor(searcher=FakeHistorySearcher(pmids, fail_metadata=True))

    _articles, results = await executor.execute(_exhaustive_config())

    step = results["pubmed"]
    assert step.ok
    assert step.pmids == pmids
    assert step.records == {}
    assert step.metadata["retrieval"]["exhaustive"] is True
    assert step.metadata["retrieval"]["metadata_complete"] is False
    assert step.metadata["source_errors"][0]["status"] == "metadata_incomplete"
    assert "upstream exploded" not in json.dumps(step.metadata)


class _StallingMetadataSearcher(FakeHistorySearcher):
    """Metadata batches after the first never finish, as when EFetch hangs at the run deadline."""

    def __init__(self, pmids: list[str], *, fast_batches: int) -> None:
        super().__init__(pmids)
        self.fast_batches = fast_batches
        self.cancelled = 0

    async def fetch_details(self, pmids: list[str]) -> list[dict[str, Any]]:
        if self.fast_batches > 0:
            self.fast_batches -= 1
            return await super().fetch_details(pmids)
        self.calls.append(("details", len(pmids)))
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        raise AssertionError("unreachable")


@pytest.mark.parametrize(("run_timeout", "fast_batches", "expected_metadata"), [(2.6, 1, 200), (1.0, 0, 0)])
async def test_run_deadline_during_metadata_keeps_the_complete_pmid_set(
    run_timeout: float, fast_batches: int, expected_metadata: int
) -> None:
    pmids = [str(5000 + index) for index in range(1000)]
    searcher = _StallingMetadataSearcher(pmids, fast_batches=fast_batches)
    executor = PipelineExecutor(
        searcher=searcher,
        exhaustive_page_size=500,
        exhaustive_metadata_batch_size=200,
        execution_policy=PipelineExecutionPolicy(run_timeout_seconds=run_timeout),
    )

    articles, results = await executor.execute(_exhaustive_config())

    step = results["pubmed"]
    assert step.ok, step.error
    assert step.pmids == pmids
    assert final_record_set(results) == ("pubmed", pmids)
    assert len(articles) == 100
    retrieval = step.metadata["retrieval"]
    assert retrieval["exhaustive"] is True
    assert retrieval["retrieved_count"] == 1000
    assert retrieval["metadata_count"] == expected_metadata
    assert retrieval["metadata_complete"] is False
    assert retrieval["metadata_error"] == {
        "kind": "deadline",
        "terminal_reason": "deadline_exhausted",
        "retryable": True,
    }
    assert step.metadata["source_errors"][0]["status"] == "metadata_incomplete"
    assert step.metadata["source_errors"][0]["kind"] == "deadline"
    assert "PMID set is complete" in retrieval["warnings"][0]
    # An in-flight metadata batch is cancelled rather than left running.
    assert searcher.cancelled == (1 if expected_metadata else 0)


# ---------------------------------------------------------------------------
# Saved-pipeline persistence and response bounds
# ---------------------------------------------------------------------------


def _save_exhaustive_pipeline(store: PipelineStore, name: str = "pacu_ma", output_format: str = "json") -> None:
    result = parse_and_validate_config(
        {
            "steps": [
                {
                    "id": "pubmed",
                    "action": "search",
                    "params": {"query": QUERY, "sources": ["pubmed"], "retrieval": "exhaustive"},
                }
            ],
            "output": {"format": output_format, "limit": 100},
        }
    )
    assert result.valid and result.config is not None
    store.save(name, result.config, scope="workspace")


async def test_saved_exhaustive_run_is_bounded_and_survives_store_restart(tmp_path: Path, store: PipelineStore) -> None:
    from pubmed_search.presentation.mcp_server.tools.unified_pipeline import _execute_pipeline_mode_outcome

    _save_exhaustive_pipeline(store)
    pmids = [str(30_000_000 + index) for index in range(10_000)]
    searcher = FakeHistorySearcher(pmids)

    outcome = await _execute_pipeline_mode_outcome("saved:pacu_ma", "json", searcher, pipeline_store=store)

    assert outcome.status == "completed"
    assert outcome.exhaustive is True
    assert len(outcome.response) < 40_000, len(outcome.response)
    payload = json.loads(outcome.response)
    assert payload["retrieval"]["total_count"] == 10_000
    assert payload["retrieval"]["exhaustive"] is True
    assert payload["run"]["record_count"] == 10_000
    assert len(payload["articles_preview"]) == 20
    assert len(payload["steps"][0]["pmid_preview"]) == 20
    assert "abstract" not in json.dumps(payload["articles_preview"])
    assert "MCID" not in outcome.response and "W1" not in json.dumps(payload["steps"])
    run_id = payload["run"]["run_id"]
    assert run_id in payload["next"]["page_records"]

    # A fresh store instance (process restart) reads the same run and artifact.
    reopened = PipelineStore(global_data_dir=tmp_path / "global", workspace_dir=tmp_path / "workspace")
    run = reopened.get_run("pacu_ma", run_id)
    assert run.pmids == pmids
    assert run.record_basis == "final_step_full"
    assert run.retrieval["exhaustive"] is True
    assert run.artifacts["records"]["count"] == 10_000
    assert "pipeline_artifacts/pacu_ma/" in run.artifacts["records"]["locator"]
    records = reopened.load_run_records("pacu_ma", run_id)
    assert [row["pmid"] for row in records] == pmids
    assert records[0]["doi"] == f"10.1000/{pmids[0]}"


async def test_second_exhaustive_run_diffs_against_previous_complete_set(store: PipelineStore) -> None:
    from pubmed_search.presentation.mcp_server.tools.unified_pipeline import _execute_pipeline_mode_outcome

    _save_exhaustive_pipeline(store, output_format="markdown")
    first = FakeHistorySearcher(["1", "2", "3"])
    second = FakeHistorySearcher(["2", "3", "4", "5"])

    await _execute_pipeline_mode_outcome("saved:pacu_ma", "markdown", first, pipeline_store=store)
    outcome = await _execute_pipeline_mode_outcome("saved:pacu_ma", "markdown", second, pipeline_store=store)

    latest = store.get_run("pacu_ma")
    assert latest.new_pmids == ["4", "5"]
    assert latest.removed_pmids == ["1"]
    assert "Exhaustive PubMed retrieval" in outcome.response
    assert "2 new, 1 removed" in outcome.response


async def test_inline_exhaustive_pipeline_requires_saved_pipeline(store: PipelineStore) -> None:
    from pubmed_search.presentation.mcp_server.tools.unified_pipeline import _execute_pipeline_mode_outcome

    inline = json.dumps(
        {"steps": [{"id": "s", "action": "search", "params": {"query": "delirium", "retrieval": "exhaustive"}}]}
    )
    searcher = FakeHistorySearcher(["1"])

    outcome = await _execute_pipeline_mode_outcome(inline, "json", searcher, pipeline_store=store)

    assert outcome.status == "failed"
    assert "requires a saved pipeline" in outcome.response
    assert searcher.calls == []


def test_history_records_view_pages_the_persisted_set(store: PipelineStore) -> None:
    from unittest.mock import MagicMock

    from pubmed_search.presentation.mcp_server.tools.pipeline_tools import (
        PipelineToolRuntime,
        register_pipeline_tools,
    )

    _save_exhaustive_pipeline(store)
    from datetime import datetime, timezone

    from pubmed_search.domain.entities.pipeline import PipelineRun

    run = PipelineRun(
        run_id="20260101_000000_000000_abc",
        pipeline_name="pacu_ma",
        started=datetime(2026, 1, 1, tzinfo=timezone.utc),
        pmids=[str(index) for index in range(1, 251)],
        article_count=250,
        record_version=2,
        record_basis="final_step_full",
        retrieval={"mode": "exhaustive", "exhaustive": True, "total_count": 250},
    )
    run.artifacts["records"] = store.save_run_records("pacu_ma", run.run_id, [_pubmed_row(p) for p in run.pmids])
    store.save_run("pacu_ma", run)

    tools: dict[str, Any] = {}
    mcp = MagicMock()
    mcp.tool = lambda: lambda func: tools.setdefault(func.__name__, func)
    register_pipeline_tools(mcp, runtime=PipelineToolRuntime(base_store=store))

    table = tools["get_pipeline_history"](name="pacu_ma")
    assert "| exhaustive | 250 |" in table
    assert 'view="records"' in table
    page = json.loads(tools["get_pipeline_history"](name="pacu_ma", view="records", offset=200, limit=100))
    assert page["total"] == 250
    assert [row["pmid"] for row in page["records"]][:2] == ["201", "202"]
    assert len(page["records"]) == 50
    assert page["next_offset"] is None


# ---------------------------------------------------------------------------
# Completeness claims cover every search feeding the final record set
# ---------------------------------------------------------------------------


class _MixedSearcher(FakeHistorySearcher):
    """Exhaustive history paging plus a bounded relevance window (PubMed counts 5000, returns limit)."""

    async def search_page(self, *, query: str, limit: int, **kwargs: Any) -> Any:
        from pubmed_search.application.search.source_models import SourceSearchPage

        rows = [_pubmed_row(str(900_000 + index)) for index in range(limit)]
        return SourceSearchPage(source="pubmed", items=rows, total=5000, query=query)


def _config(steps: list[dict[str, Any]]) -> PipelineConfig:
    result = parse_and_validate_config({"steps": steps, "output": {"format": "json", "limit": 20}})
    assert result.valid and result.config is not None, result.errors
    return result.config


_EXHAUSTIVE_STEP = {"id": "ex", "action": "search", "params": {"query": QUERY, "retrieval": "exhaustive"}}
_BOUNDED_STEP = {"id": "bd", "action": "search", "params": {"query": "other topic", "sources": ["pubmed"], "limit": 10}}


async def test_bounded_search_feeding_the_final_set_is_never_claimed_exhaustive(store: PipelineStore) -> None:
    from pubmed_search.application.pipeline.screening import run_is_complete_identification
    from pubmed_search.presentation.mcp_server.tools.unified_pipeline import _execute_pipeline_mode_outcome

    store.save(
        "mixed",
        _config(
            [
                _EXHAUSTIVE_STEP,
                _BOUNDED_STEP,
                {"id": "m", "action": "merge", "inputs": ["ex", "bd"], "params": {"method": "union"}},
            ]
        ),
        scope="workspace",
    )
    searcher = _MixedSearcher([str(5000 + index) for index in range(30)])

    outcome = await _execute_pipeline_mode_outcome("saved:mixed", "json", searcher, pipeline_store=store)

    payload = json.loads(outcome.response)
    assert outcome.exhaustive is False
    retrieval = payload["retrieval"]
    assert (retrieval["mode"], retrieval["exhaustive"]) == ("mixed", False)
    assert [row["step_id"] for row in retrieval["steps"]] == ["ex"]
    assert [row["step_id"] for row in retrieval["bounded_steps"]] == ["bd"]
    assert retrieval["bounded_steps"][0]["total_count"] == 5000
    assert any("bounded" in warning and "not a complete record set" in warning for warning in payload["warnings"])
    run = store.get_run("mixed")
    assert run.retrieval["exhaustive"] is False
    assert len(run.pmids) == 40
    assert run_is_complete_identification(run) is False
    assert not store.screening_db_path("mixed").exists()  # never auto-registered as complete identification
    markdown = await _execute_pipeline_mode_outcome("saved:mixed", "markdown", searcher, pipeline_store=store)
    assert "mixed" in markdown.response and "not a complete record set" in markdown.response


async def test_bounded_search_outside_the_final_record_flow_keeps_the_exhaustive_claim() -> None:
    from pubmed_search.application.pipeline.run_recorder import retrieval_summary

    executor = PipelineExecutor(searcher=_MixedSearcher([str(5000 + index) for index in range(30)]))
    _articles, results = await executor.execute(
        _config([_BOUNDED_STEP, _EXHAUSTIVE_STEP, {"id": "blocks", "action": "block_analysis", "inputs": ["ex"]}])
    )

    _step, pmids = final_record_set(results)
    summary = retrieval_summary(results, len(pmids))
    assert (summary["mode"], summary["exhaustive"]) == ("exhaustive", True)
    assert summary["identified_count"] == 30
    assert "bounded_steps" not in summary


async def test_filters_keep_metadata_less_records_and_report_them() -> None:
    from pubmed_search.application.pipeline.run_recorder import retrieval_summary

    executor = PipelineExecutor(searcher=FakeHistorySearcher([str(5000 + index) for index in range(30)]))
    steps = [
        {**_EXHAUSTIVE_STEP, "params": {**_EXHAUSTIVE_STEP["params"], "fetch_metadata": False}},
        {"id": "years", "action": "filter", "inputs": ["ex"], "params": {"min_year": 2010, "max_year": 2020}},
        {
            "id": "types",
            "action": "filter",
            "inputs": ["years"],
            "params": {"article_types": ["randomized-controlled-trial"]},
        },
        {"id": "rest", "action": "filter", "inputs": ["types"], "params": {"has_abstract": True, "min_citations": 5}},
    ]

    _articles, results = await executor.execute(_config(steps))

    _final, pmids = final_record_set(results)
    assert len(pmids) == 30
    for step_id in ("years", "types", "rest"):
        metadata = results[step_id].metadata
        assert metadata["removal_reasons"] == {}
        assert metadata["metadata_missing"]["count"] == 30
        assert len(metadata["metadata_missing"]["pmid_preview"]) == 20
        assert "without metadata" in metadata["warning"]
    summary = retrieval_summary(results, len(pmids))
    assert summary["exhaustive"] is True
    assert (summary["identified_count"], summary["removed_by_filters"]) == (30, 0)
    assert any("without metadata" in warning for warning in summary["warnings"])


class _MixedYearSearcher(FakeHistorySearcher):
    async def fetch_details(self, pmids: list[str]) -> list[dict[str, Any]]:
        rows = await super().fetch_details(pmids)
        for row in rows:
            row["year"] = "2010" if int(row["pmid"]) % 2 else "2024"
        return rows


async def test_identification_counts_records_before_pipeline_filters(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from pubmed_search.application.pipeline.run_recorder import PipelineRunRecorder
    from pubmed_search.application.pipeline.screening import ScreeningService
    from pubmed_search.infrastructure.pipeline_screening import SQLiteScreeningStore

    store = PipelineStore(global_data_dir=tmp_path / "global")
    config = _config(
        [_EXHAUSTIVE_STEP, {"id": "recent", "action": "filter", "inputs": ["ex"], "params": {"min_year": 2020}}]
    )
    store.save("filtered", config)
    _articles, results = await PipelineExecutor(
        searcher=_MixedYearSearcher([str(5000 + index) for index in range(30)])
    ).execute(config)

    run = PipelineRunRecorder(store).record(
        pipeline_name="filtered",
        articles=_articles,
        step_results=results,
        report="r",
        started=datetime.now(timezone.utc),
        executed_config=config,
    )

    assert len(run.pmids) == 15
    assert run.retrieval["exhaustive"] is True
    assert (run.retrieval["identified_count"], run.retrieval["removed_by_filters"]) == (30, 15)
    service = ScreeningService(SQLiteScreeningStore(store.screening_db_path("filtered")))
    service.register_run(run)
    identification = service.flow()["identification"]
    assert identification["records_identified"] == 30
    assert identification["records_marked_ineligible_by_automation"] == 15
    assert identification["duplicate_records_removed"] == 0
    assert identification["records_after_duplicates_removed"] == 15


# ---------------------------------------------------------------------------
# Persistence and export disclose what the run record actually is
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("output_format", ["json", "markdown"])
async def test_failed_run_persistence_is_disclosed_not_reported_as_saved(
    store: PipelineStore, monkeypatch: pytest.MonkeyPatch, output_format: str
) -> None:
    from pubmed_search.presentation.mcp_server.tools.unified_pipeline import _execute_pipeline_mode_outcome

    _save_exhaustive_pipeline(store, output_format=output_format)

    def disk_full(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("disk full")

    monkeypatch.setattr(store, "save_run_records", disk_full)

    outcome = await _execute_pipeline_mode_outcome(
        "saved:pacu_ma",
        output_format,
        FakeHistorySearcher([str(5000 + index) for index in range(30)]),
        pipeline_store=store,
    )

    assert outcome.exhaustive is False
    assert store.get_history("pacu_ma", limit=5) == []
    if output_format == "json":
        payload = json.loads(outcome.response)
        assert payload["run"] is None
        assert payload["persistence"] == {"saved": False, "error_type": "OSError"}
        assert payload["summary"]["record_count"] == 30
        assert payload["next"] == {}
        assert any("could not be saved" in warning for warning in payload["warnings"])
    else:
        assert "could not be saved" in outcome.response
        assert "30 records" in outcome.response


async def test_bounded_saved_pipeline_persistence_failure_is_disclosed(
    store: PipelineStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pubmed_search.presentation.mcp_server.tools.unified_pipeline import _execute_pipeline_mode_outcome

    store.save("bounded", _config([_BOUNDED_STEP]), scope="workspace")

    def disk_full(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("disk full")

    monkeypatch.setattr(store, "save_run", disk_full)

    outcome = await _execute_pipeline_mode_outcome("saved:bounded", "json", _MixedSearcher([]), pipeline_store=store)

    payload = json.loads(outcome.response)
    assert any("could not be saved" in warning for warning in payload["warnings"])
    assert payload["persistence"] == {"saved": False, "error_type": "OSError"}


async def test_export_summary_discloses_whether_the_run_is_a_complete_record_set(store: PipelineStore) -> None:
    from pubmed_search.application.pipeline.run_export import export_pipeline_run
    from pubmed_search.presentation.mcp_server.tools.unified_pipeline import _execute_pipeline_mode_outcome

    _save_exhaustive_pipeline(store)
    searcher = _MixedSearcher([str(5000 + index) for index in range(5)])
    await _execute_pipeline_mode_outcome("saved:pacu_ma", "json", searcher, pipeline_store=store)
    store.save(
        "mixed",
        _config(
            [
                _EXHAUSTIVE_STEP,
                _BOUNDED_STEP,
                {"id": "m", "action": "merge", "inputs": ["ex", "bd"], "params": {"method": "union"}},
            ]
        ),
        scope="workspace",
    )
    await _execute_pipeline_mode_outcome("saved:mixed", "json", searcher, pipeline_store=store)
    store.save("bounded", _config([_BOUNDED_STEP]), scope="workspace")
    await _execute_pipeline_mode_outcome("saved:bounded", "json", searcher, pipeline_store=store)

    complete = (await export_pipeline_run(store, "pacu_ma", fmt="ris", include_abstract=False, searcher=None)).summary()
    mixed = (await export_pipeline_run(store, "mixed", fmt="ris", include_abstract=False, searcher=None)).summary()
    bounded = (await export_pipeline_run(store, "bounded", fmt="ris", include_abstract=False, searcher=None)).summary()

    assert (complete["record_basis"], complete["retrieval_mode"], complete["complete_record_set"]) == (
        "final_step_full",
        "exhaustive",
        True,
    )
    assert complete["warnings"] == []
    assert (mixed["record_basis"], mixed["retrieval_mode"], mixed["complete_record_set"]) == (
        "final_step_full",
        "mixed",
        False,
    )
    assert any("bounded" in warning for warning in mixed["warnings"])
    assert (bounded["record_basis"], bounded["retrieval_mode"], bounded["complete_record_set"]) == (
        "ranked_output",
        "bounded",
        False,
    )
    assert any("ranked preview" in warning for warning in bounded["warnings"])


async def test_records_view_pages_merged_sets_beyond_10000(store: PipelineStore) -> None:
    """Two merged exhaustive steps can persist up to 2 x 10,000 records; every page must be reachable."""
    from datetime import datetime, timezone

    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError

    from pubmed_search.application.pipeline.budgets import PIPELINE_RUN_RECORD_LIMIT
    from pubmed_search.domain.entities.pipeline import PipelineRun
    from pubmed_search.presentation.mcp_server.tools.pipeline_tools import (
        PipelineToolRuntime,
        register_pipeline_tools,
    )

    _save_exhaustive_pipeline(store)
    pmids = [str(index) for index in range(1, 10_051)]
    run = PipelineRun(
        run_id="20260101_000000_000000_big",
        pipeline_name="pacu_ma",
        started=datetime(2026, 1, 1, tzinfo=timezone.utc),
        pmids=pmids,
        article_count=len(pmids),
        record_version=2,
        record_basis="final_step_full",
        retrieval={"mode": "exhaustive", "exhaustive": True},
    )
    run.artifacts["records"] = store.save_run_records("pacu_ma", run.run_id, [{"pmid": pmid} for pmid in pmids])
    store.save_run("pacu_ma", run)
    server = MCPServer("records-paging-test")
    register_pipeline_tools(server, runtime=PipelineToolRuntime(base_store=store))

    page = await server.call_tool(
        "get_pipeline_history", {"name": "pacu_ma", "view": "records", "offset": 10_025, "limit": 100}
    )

    assert not page.is_error
    payload = json.loads(page.content[0].text)
    assert [row["pmid"] for row in payload["records"]] == pmids[10_025:]
    assert payload["next_offset"] is None
    assert PIPELINE_RUN_RECORD_LIMIT >= 2 * 10_000
    with pytest.raises(ToolError, match="less than or equal"):
        await server.call_tool(
            "get_pipeline_history",
            {"name": "pacu_ma", "view": "records", "offset": PIPELINE_RUN_RECORD_LIMIT + 1, "limit": 100},
        )
