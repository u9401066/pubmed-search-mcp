"""Strategy block contribution analysis: parsing, counting semantics, bounds."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from pubmed_search.application.pipeline.block_analysis import analyze_strategy_blocks
from pubmed_search.application.pipeline.boolean_query import (
    QueryDecompositionError,
    QueryNode,
    decompose_pubmed_query,
    parse_pubmed_query,
)
from pubmed_search.application.pipeline.budgets import PipelineExecutionPolicy
from pubmed_search.application.pipeline.executor import PipelineExecutor, final_record_set
from pubmed_search.application.pipeline.store import PipelineStore
from pubmed_search.application.pipeline.validator import parse_and_validate_config
from pubmed_search.domain.entities.pipeline import PipelineConfig, PipelineOutput, PipelineStep
from tests.test_pipeline_exhaustive import _pubmed_row

if TYPE_CHECKING:
    from pathlib import Path

EVIDENCE_QUERY = (
    '("Anesthesia Recovery Period"[Mesh] OR "Recovery Room"[Mesh] OR PACU[tiab] OR emergence[tiab]) '
    'AND ("Consciousness Monitors"[Mesh] OR "bispectral index"[tiab] OR "processed electroencephalogra*"[tiab]) '
    'AND ("Delirium"[Mesh] OR delirium[tiab] OR "recovery time"[tiab]) '
    'NOT (("Child"[Mesh] OR "Infant"[Mesh]) NOT "Adult"[Mesh])'
)

# A synthetic PubMed: each record lists the verbatim terms that index it.
CORPUS: dict[str, set[str]] = {
    "1": {'"Recovery Room"[Mesh]', '"bispectral index"[tiab]', '"Delirium"[Mesh]', "delirium[tiab]"},
    "2": {"PACU[tiab]", '"bispectral index"[tiab]', "delirium[tiab]"},  # PACU is unique here
    "3": {"emergence[tiab]", "PACU[tiab]", '"Consciousness Monitors"[Mesh]', '"recovery time"[tiab]'},
    "4": {'"Anesthesia Recovery Period"[Mesh]', '"bispectral index"[tiab]', '"Delirium"[Mesh]'},
    "5": {"emergence[tiab]", '"bispectral index"[tiab]', "delirium[tiab]", '"Child"[Mesh]'},  # excluded child
    "6": {
        "emergence[tiab]",
        "PACU[tiab]",
        '"bispectral index"[tiab]',
        "delirium[tiab]",
        '"Child"[Mesh]',
        '"Adult"[Mesh]',
    },
    "7": {'"Recovery Room"[Mesh]', '"processed electroencephalogra*"[tiab]', '"Delirium"[Mesh]'},
    "8": {"PACU[tiab]"},
}


def _evaluate(node: QueryNode) -> set[str]:
    """Left-to-right PubMed Boolean semantics over the synthetic corpus."""
    if node.is_term:
        return {pmid for pmid, terms in CORPUS.items() if node.text in terms}
    result = _evaluate(node.operands[0])
    for operator, operand in zip(node.operators, node.operands[1:], strict=True):
        other = _evaluate(operand)
        result = result | other if operator == "OR" else result & other if operator == "AND" else result - other
    return result


def fake_count(query: str) -> int:
    return len(_evaluate(parse_pubmed_query(query)))


class CorpusSearcher:
    """Answers count-only and History snapshots from the synthetic corpus."""

    def __init__(self) -> None:
        self.count_calls: list[str] = []

    async def esearch_snapshot(self, query: str, *, retmax: int, use_history: bool = True, **filters: Any):
        pmids = sorted(_evaluate(parse_pubmed_query(query)), key=int)
        if retmax == 0:
            self.count_calls.append(query)
        return {
            "count": len(pmids),
            "pmids": pmids[:retmax],
            "webenv": "W" if use_history else None,
            "query_key": "1" if use_history else None,
            "logical_query": query,
            "physical_query": query,
            "query_translation": query,
            "translation_set": [],
            "provider_errors": {},
            "provider_warnings": {},
        }

    async def fetch_history_pmids(self, webenv: str, query_key: str, *, retstart: int, retmax: int) -> list[str]:
        raise AssertionError("single page expected")

    async def fetch_details(self, pmids: list[str]) -> list[dict[str, Any]]:
        return [_pubmed_row(pmid) for pmid in pmids]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_evidence_shaped_strategy_decomposes_into_blocks_and_not() -> None:
    decomposed = decompose_pubmed_query(EVIDENCE_QUERY)
    assert [(block.label, len(block.terms)) for block in decomposed.and_blocks] == [("B1", 4), ("B2", 3), ("B3", 3)]
    assert [block.label for block in decomposed.not_blocks] == ["NOT1"]
    assert decomposed.full() == EVIDENCE_QUERY
    assert decomposed.and_blocks[1].terms[2] == '"processed electroencephalogra*"[tiab]'


def test_quoted_operators_tags_subheadings_and_nesting_stay_verbatim() -> None:
    query = (
        '("recovery (anesthesia) AND x"[tiab] OR Delirium/prevention and control[Mesh] OR "a b"[tiab:~3]) '
        "AND ((c[MeSH Terms] OR d*[tiab]) OR e[majr]) AND f[tiab]"
    )
    decomposed = decompose_pubmed_query(query)
    first, second, third = decomposed.and_blocks
    assert first.terms == (
        '"recovery (anesthesia) AND x"[tiab]',
        "Delirium/prevention and control[Mesh]",
        '"a b"[tiab:~3]',
    )
    assert second.terms == ("(c[MeSH Terms] OR d*[tiab])", "e[majr]")
    assert third.terms == ("f[tiab]",)
    assert first.render_without(1) == '("recovery (anesthesia) AND x"[tiab] OR "a b"[tiab:~3])'


def test_single_or_list_is_one_block() -> None:
    decomposed = decompose_pubmed_query("a[tiab] OR b[tiab] OR c[tiab]")
    assert len(decomposed.and_blocks) == 1
    assert decomposed.and_blocks[0].terms == ("a[tiab]", "b[tiab]", "c[tiab]")


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("a OR b AND c", "left to right"),
        ("(a OR b", "Unbalanced opening parenthesis"),
        ("a OR b)", "Unbalanced closing parenthesis"),
        ('"unterminated OR b', "Unbalanced double quote"),
        ("AND a", "missing its left operand"),
        ("a AND ()", "Empty parentheses"),
        ("a AND", "missing an operand"),
        ("a[tiab AND b", "Unbalanced field tag"),
    ],
)
def test_undecomposable_queries_fail_with_a_reason(query: str, message: str) -> None:
    with pytest.raises(QueryDecompositionError, match=message):
        decompose_pubmed_query(query)


def test_operators_follow_pubmeds_case_rules() -> None:
    # Live ESearch 2026-11-25: "or"/"not" are operators like OR/NOT; "and" and mixed case are not.
    with pytest.raises(QueryDecompositionError, match="left to right"):
        # PubMed reads ((a OR b) AND c) OR d; before, "c[tiab] or d[tiab]" was one AND block.
        decompose_pubmed_query("(a[tiab] OR b[tiab]) AND c[tiab] or d[tiab]")
    decomposed = decompose_pubmed_query("(a[tiab] or b[tiab]) AND c[tiab] not d[tiab]")
    assert [block.terms for block in decomposed.and_blocks] == [("a[tiab]", "b[tiab]"), ("c[tiab]",)]
    assert [block.text for block in decomposed.not_blocks] == ["d[tiab]"]
    assert parse_pubmed_query("a[tiab] or b[tiab]").operators == ["OR"]
    assert decomposed.full() == "(a[tiab] or b[tiab]) AND c[tiab] NOT d[tiab]"
    for word in ("and", "Or", "Not", "oR"):
        assert parse_pubmed_query(f"a[tiab] {word} b[tiab]").is_term, word


def test_nested_and_inside_block_is_kept_whole() -> None:
    decomposed = decompose_pubmed_query("(a[tiab] AND b[tiab]) AND (c[tiab] OR d[tiab])")
    assert decomposed.and_blocks[0].or_list is False
    assert decomposed.and_blocks[0].terms == ("(a[tiab] AND b[tiab])",)


# ---------------------------------------------------------------------------
# Counting semantics
# ---------------------------------------------------------------------------


async def test_counts_cumulative_not_and_unique_contributions_match_semantics() -> None:
    calls: list[str] = []

    async def count(query: str) -> int:
        calls.append(query)
        return fake_count(query)

    analysis = await analyze_strategy_blocks(EVIDENCE_QUERY, count=count, max_count_queries=60)

    assert analysis["decomposable"] is True
    # Records 1-4, 6, 7: record 5 is a child-only study removed by NOT, record 8 misses blocks 2-3.
    assert analysis["full_count"] == 6
    assert [block["count"] for block in analysis["blocks"]] == [8, 7, 7]
    assert [row["count"] for row in analysis["cumulative"]] == [8, 7, 7, 6]
    assert analysis["not_blocks"][0]["records_removed"] == 1
    contributions = {term["term"]: term["unique_contribution"] for term in analysis["terms"]}
    assert contributions["PACU[tiab]"] == 1  # only record 2 has no other block-1 term
    assert contributions['"Recovery Room"[Mesh]'] == 2  # records 1 and 7
    assert contributions["emergence[tiab]"] == 0  # every included emergence record also has PACU
    assert contributions['"bispectral index"[tiab]'] == 4
    assert contributions['"Delirium"[Mesh]'] == 2
    assert contributions['"processed electroencephalogra*"[tiab]'] == 1
    assert {"block": "B1", "term": "emergence[tiab]"} in analysis["zero_contribution_terms"]
    queries = analysis["count_queries"]
    assert queries["executed"] == len(set(calls)) == len(calls)
    assert queries["planned"] == 1 + 3 + 2 + 10
    assert queries["truncated"] is False


async def test_count_query_cap_truncates_and_discloses_unevaluated_terms() -> None:
    calls: list[str] = []

    async def count(query: str) -> int:
        calls.append(query)
        return fake_count(query)

    analysis = await analyze_strategy_blocks(EVIDENCE_QUERY, count=count, max_count_queries=5)

    assert len(calls) == 5
    assert analysis["count_queries"]["truncated"] is True
    assert analysis["count_queries"]["truncation_reason"] == "max_count_queries"
    assert analysis["count_queries"]["terms_not_evaluated"] == 10
    assert all(term["unique_contribution"] is None for term in analysis["terms"])


async def test_not_decomposable_query_makes_no_count_queries() -> None:
    async def count(query: str) -> int:
        raise AssertionError("no provider call expected")

    analysis = await analyze_strategy_blocks("a OR b AND c", count=count, max_count_queries=10)
    assert analysis == {"query": "a OR b AND c", "decomposable": False, "reason": analysis["reason"]}
    assert "left to right" in analysis["reason"]


# ---------------------------------------------------------------------------
# Pipeline action
# ---------------------------------------------------------------------------


def _review_config(**analysis_params: Any) -> PipelineConfig:
    return PipelineConfig(
        name="review",
        steps=[
            PipelineStep(
                id="pubmed",
                action="search",
                params={"query": EVIDENCE_QUERY, "sources": ["pubmed"], "retrieval": "exhaustive"},
            ),
            PipelineStep(id="blocks", action="block_analysis", inputs=["pubmed"], params=analysis_params),
        ],
        output=PipelineOutput(format="json", limit=10),
    )


async def test_block_analysis_step_uses_count_quota_not_record_budget() -> None:
    searcher = CorpusSearcher()
    executor = PipelineExecutor(searcher=searcher, execution_policy=PipelineExecutionPolicy(max_external_calls=2))

    articles, results = await executor.execute(_review_config())

    assert results["blocks"].ok
    analysis = results["blocks"].metadata["block_analysis"]
    assert analysis["full_count"] == 6
    assert analysis["source_step"] == "pubmed"
    assert analysis["count_queries"]["truncated"] is False
    # The analysis is the last step, yet the persisted record set is the search step's.
    assert final_record_set(results) == ("pubmed", ["1", "2", "3", "4", "6", "7"])
    assert len(articles) == 6
    budget = results["blocks"].metadata.get("run_budget") or results["pubmed"].metadata.get("run_budget")
    assert budget["count_queries_used"] == len(searcher.count_calls) == analysis["count_queries"]["executed"]
    assert budget["external_calls_used"] == 2


async def test_block_analysis_count_quota_exhaustion_is_disclosed() -> None:
    executor = PipelineExecutor(
        searcher=CorpusSearcher(),
        execution_policy=PipelineExecutionPolicy(max_count_queries=3),
    )

    _articles, results = await executor.execute(_review_config())

    queries = results["blocks"].metadata["block_analysis"]["count_queries"]
    assert queries["executed"] == 3
    assert queries["truncation_reason"] == "count_query_quota_exhausted"


@pytest.mark.parametrize(
    ("step", "message"),
    [
        ({"id": "b", "action": "block_analysis"}, "provide query or exactly one input"),
        ({"id": "b", "action": "block_analysis", "params": {"query": "a", "max_count_queries": 201}}, "200"),
        ({"id": "b", "action": "block_analysis", "params": {"query": "a", "limit": 5}}, "Extra inputs"),
    ],
)
def test_block_analysis_contract_fails_closed(step: dict[str, Any], message: str) -> None:
    result = parse_and_validate_config({"steps": [step]})
    assert not result.valid
    assert message in "; ".join(result.errors)


async def test_saved_run_persists_block_analysis_and_reports_it(tmp_path: Path) -> None:
    from pubmed_search.presentation.mcp_server.tools.unified_pipeline import _execute_pipeline_mode_outcome

    store = PipelineStore(global_data_dir=tmp_path / "global", workspace_dir=tmp_path / "workspace")
    store.save("review", _review_config(), scope="workspace")

    outcome = await _execute_pipeline_mode_outcome("saved:review", "json", CorpusSearcher(), pipeline_store=store)

    payload = json.loads(outcome.response)
    compact = next(step for step in payload["steps"] if step["id"] == "blocks")["block_analysis"]
    assert compact["full_count"] == 6
    assert compact["zero_contribution_terms"] == [{"block": "B1", "term": "emergence[tiab]"}]
    run = PipelineStore(global_data_dir=tmp_path / "global", workspace_dir=tmp_path / "workspace").get_run("review")
    assert run.pmids == ["1", "2", "3", "4", "6", "7"]
    [persisted] = run.block_analyses
    assert persisted["step_id"] == "blocks"
    assert persisted["cumulative"][-1]["count"] == 6
    report = next((tmp_path / "workspace").rglob(f"{run.run_id}.md")).read_text(encoding="utf-8")
    assert "## Strategy Block Analysis" in report
    assert "| B1 | 4 | 8 | 8 |" in report
