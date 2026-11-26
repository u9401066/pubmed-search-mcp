"""Hybrid search: per-channel query translation and provider-rank fusion.

The end-to-end tests run the real planner, executor, aggregation and
formatter; only the three provider runners are doubles. Each double records
the query and options it received, so a regression that leaks PubMed field
tags to another provider, or that re-ranks by local abstract scoring, fails.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.search.channel_fusion import fuse_channels, hybrid_channel_limit
from pubmed_search.application.search.query_dialect import neutralize_pubmed_query
from pubmed_search.application.search.semantic_enhancer import SemanticEnhancer
from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.application.unified.request import normalize_unified_search_request
from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.presentation.mcp_server.tools.tool_session import ToolSessionRuntime, bind_tool_session_runtime
from pubmed_search.presentation.mcp_server.tools.unified_runner import run_unified_search
from pubmed_search.shared.source_contracts import SourceAdapterError, SourceAdapterResult

MESH_QUERY = (
    '("Delirium"[Mesh] OR delirium[tiab]) AND dexmedetomidine[tiab] '
    'AND "Cardiac Surgical Procedures"[Mesh] AND Randomized Controlled Trial[pt]'
)


def _article(pmid: str, source: str = "pubmed", *, doi: str | None = None) -> UnifiedArticle:
    return UnifiedArticle(
        title=f"Study {pmid}",
        primary_source=source,
        pmid=pmid,
        doi=doi,
        year=2022,
        journal="Journal",
        abstract="dexmedetomidine delirium cardiac surgery",
    )


# ── Query translation ───────────────────────────────────────────────────────


def test_mesh_query_is_translated_without_field_tags() -> None:
    neutral = neutralize_pubmed_query(MESH_QUERY)

    assert neutral.translated is True
    assert neutral.boolean == "(Delirium OR delirium) AND dexmedetomidine AND (Cardiac Surgical Procedures)"
    assert neutral.semantic == "Delirium dexmedetomidine Cardiac Surgical Procedures"
    assert neutral.dropped == ("Randomized Controlled Trial[pt]",)
    assert "[" not in neutral.boolean


def test_restriction_only_clauses_leave_no_dangling_operators() -> None:
    neutral = neutralize_pubmed_query("tranexamic acid[tiab] AND english[la] AND 2015:2020[dp] NOT review[pt]")

    assert neutral.boolean == "(tranexamic acid)"
    assert neutral.dropped == ("english[la]", "2015:2020[dp]", "review[pt]")


def test_quoted_text_phrases_stay_phrases_and_plain_queries_are_unchanged() -> None:
    assert (
        neutralize_pubmed_query('"postoperative pulmonary complications"[tiab] AND sugammadex[nm]').boolean
        == '"postoperative pulmonary complications" AND sugammadex'
    )
    plain = neutralize_pubmed_query("does  dexmedetomidine prevent delirium?")
    assert (plain.boolean, plain.translated) == ("does dexmedetomidine prevent delirium?", False)


# ── Fusion ──────────────────────────────────────────────────────────────────


def test_fusion_orders_by_provider_ranks_and_rewards_agreement() -> None:
    a, b, c, d = (_article(pmid) for pmid in "1234")
    channels = {"pubmed": [a, b, c], "europe_pmc": [c, d], "openalex": [c, a]}

    ranked, report = fuse_channels([d, c, b, a], channels, limit=4, breadth_quota=0)

    # c: three channels; a: PubMed #1 + semantic #2; b: PubMed #2 only; d: full text only.
    assert [article.pmid for article in ranked] == ["3", "1", "2", "4"]
    assert [(hit.channel, hit.rank) for hit in ranked[0].channels] == [
        ("pubmed", 3),
        ("europe_pmc", 1),
        ("openalex", 1),
    ]
    assert ranked[0].ranking_score == 1.0
    assert (report.multi_channel, report.breadth_only) == (2, 1)


def test_breadth_quota_keeps_slots_for_records_pubmed_did_not_return() -> None:
    pubmed = [_article(str(index)) for index in range(1, 9)]
    full_text = [_article("100", "europe_pmc"), _article("101", "europe_pmc"), _article("102", "europe_pmc")]
    merged = [*pubmed, *full_text]
    channels = {"pubmed": pubmed, "europe_pmc": full_text}

    without, _ = fuse_channels(merged, channels, limit=8, breadth_quota=0)
    assert [article.pmid for article in without] == [str(index) for index in range(1, 9)]

    ranked, report = fuse_channels(merged, channels, limit=8, breadth_quota=0.25)
    assert [article.pmid for article in ranked] == ["1", "2", "3", "4", "5", "6", "100", "101"]
    assert (report.breadth_slots, report.breadth_only) == (2, 2)
    assert all(not article.found_by("pubmed") for article in ranked[-2:])


def test_quota_is_unused_when_only_pubmed_answered_and_records_match_across_ids() -> None:
    by_pmid = _article("7", doi="10.1000/X")
    same_by_doi = UnifiedArticle(title="Study 7", primary_source="openalex", doi="https://doi.org/10.1000/x")

    ranked, report = fuse_channels([by_pmid], {"pubmed": [by_pmid], "openalex": [same_by_doi]}, limit=5)

    assert [hit.channel for hit in ranked[0].channels] == ["pubmed", "openalex"]
    assert (report.breadth_slots, report.breadth_only, report.multi_channel) == (0, 0, 1)


def test_channel_depth_exceeds_the_requested_limit() -> None:
    assert (hybrid_channel_limit(5), hybrid_channel_limit(20), hybrid_channel_limit(100)) == (50, 60, 100)


# ── Request contract ────────────────────────────────────────────────────────


@pytest.mark.parametrize("options", ["hybrid,native_semantic", "hybrid,systematic"])
def test_hybrid_rejects_other_retrieval_policies(options: str) -> None:
    with pytest.raises(ValueError, match="hybrid"):
        normalize_unified_search_request(query="x", options=options)


def test_hybrid_keeps_default_pubmed_deepening_and_quota_can_be_disabled() -> None:
    request = normalize_unified_search_request(query="x", options="hybrid")
    assert (request.hybrid, request.deep_search, request.breadth_quota) == (True, True, False)
    assert normalize_unified_search_request(query="x", options="hybrid,breadth_quota").breadth_quota is True


# ── End to end ──────────────────────────────────────────────────────────────


class _NullResolver:
    async def resolve_entity(self, _text: str) -> None:
        return None


def _enhancer() -> SemanticEnhancer:
    return SemanticEnhancer(entity_resolver=_NullResolver())


class _Runner:
    def __init__(self, source: str, pmids: list[str], *, fail: bool = False, fail_modes: tuple[str, ...] = ()) -> None:
        self.source = source
        self.pmids = pmids
        self.fail = fail
        self.fail_modes = fail_modes
        self.calls: list[tuple[str, int, dict[str, Any]]] = []

    async def __call__(
        self, query: str, limit: int, _min_year: int | None, _max_year: int | None, options: dict[str, Any]
    ) -> SourceAdapterResult[UnifiedArticle]:
        self.calls.append((query, limit, dict(options)))
        if self.fail or options.get("_retrieval_mode") in self.fail_modes:
            return SourceAdapterResult.failure(
                source=self.source,
                operation="search",
                error=SourceAdapterError(
                    source=self.source, operation="search", message="Request timed out", kind="timeout", retryable=True
                ),
            )
        items = [_article(pmid, self.source) for pmid in self.pmids][:limit]
        return SourceAdapterResult(
            source=self.source,
            operation="search",
            items=items,
            total_count=len(self.pmids),
            status="ok" if items else "empty",
            metadata={"total_available": len(self.pmids), "query_executed": True},
        )


async def _hybrid(
    runners: dict[str, _Runner],
    *,
    output_format: str = "json",
    limit: int = 4,
    query: str = MESH_QUERY,
    options: str = "hybrid,breadth_quota,no_oa,no_mesh_correction",
) -> str:
    searcher = MagicMock()
    searcher.search_page = AsyncMock(return_value=SourceSearchPage(source="pubmed", items=[], total=0, query="x"))
    with (
        bind_tool_session_runtime(ToolSessionRuntime()),
        patch(
            "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        return await run_unified_search(
            searcher=searcher,
            query=query,
            limit=limit,
            output_format=output_format,  # type: ignore[arg-type]
            options=options,
            enhancer_factory=_enhancer,
            search_functions=runners,
        )


def _runners(*, fail_full_text: bool = False) -> dict[str, _Runner]:
    return {
        "pubmed": _Runner("pubmed", ["1", "2", "3", "4", "5"]),
        "europe_pmc": _Runner("europe_pmc", ["3", "9"], fail=fail_full_text),
        "openalex": _Runner("openalex", ["3", "1"]),
    }


async def test_each_channel_gets_its_own_dialect_and_results_follow_provider_ranks() -> None:
    runners = _runners()

    payload = json.loads(await _hybrid(runners))

    # The exact query goes first; default fill tiers may follow because it left the channel short.
    pubmed_query, pubmed_limit, _ = runners["pubmed"].calls[0]
    ((full_text_query, _, _),) = runners["europe_pmc"].calls
    ((semantic_query, _, semantic_options),) = runners["openalex"].calls
    assert pubmed_query == MESH_QUERY and pubmed_limit == 50
    assert full_text_query == "(Delirium OR delirium) AND dexmedetomidine AND (Cardiac Surgical Procedures)"
    assert semantic_query == "Delirium dexmedetomidine Cardiac Surgical Procedures"
    assert semantic_options["_retrieval_mode"] == "semantic"

    # 3 is in all channels, 1 in two; one of four slots is kept for the full-text-only record 9.
    assert [article["pmid"] for article in payload["articles"]] == ["3", "1", "2", "9"]
    assert payload["articles"][0]["found_by"] == [
        {"channel": "pubmed", "rank": 3},
        {"channel": "europe_pmc", "rank": 1},
        {"channel": "openalex", "rank": 1},
    ]
    assert payload["articles"][3]["found_by"] == [{"channel": "europe_pmc", "rank": 2}]

    hybrid = payload["hybrid"]
    assert hybrid["channels"] == {"pubmed": 5, "europe_pmc": 2, "openalex": 2}
    assert (hybrid["multi_channel_records"], hybrid["breadth_only_records"], hybrid["breadth_slots"]) == (2, 1, 1)
    assert hybrid["dropped_clauses"] == ["Randomized Controlled Trial[pt]"]
    assert hybrid["queries"]["europe_pmc"] == full_text_query
    assert hybrid["failed_channels"] == []


async def test_a_failed_channel_is_disclosed_and_the_rest_still_fuse() -> None:
    payload = json.loads(await _hybrid(_runners(fail_full_text=True)))

    # Without the full-text vote, PubMed #1 (also semantic #2) edges out PubMed #3 (semantic #1).
    assert [article["pmid"] for article in payload["articles"]] == ["1", "3", "2", "4"]
    assert payload["hybrid"]["failed_channels"] == ["europe_pmc"]
    assert "europe_pmc" not in payload["hybrid"]["channels"]
    assert any(error["source"] == "europe_pmc" for error in payload["source_errors"])


async def test_markdown_shows_channels_and_marks_breadth_only_records() -> None:
    text = await _hybrid(_runners(), output_format="markdown")

    assert "Hybrid search" in text
    assert "**Found by**: PubMed #3, full text #1, semantic #1" in text
    assert "**Found by**: 🧭 full text #2" in text
    assert "Applied on PubMed only" in text


async def test_breadth_quota_is_off_unless_requested() -> None:
    payload = json.loads(await _hybrid(_runners(), options="hybrid,no_oa,no_mesh_correction"))

    assert [article["pmid"] for article in payload["articles"]] == ["3", "1", "2", "4"]
    assert payload["hybrid"]["breadth_slots"] == 0


async def test_semantic_channel_falls_back_to_keyword_search_when_unavailable() -> None:
    runners = _runners()
    runners["openalex"] = _Runner("openalex", ["3", "1"], fail_modes=("semantic",))

    payload = json.loads(await _hybrid(runners))

    modes = [options["_retrieval_mode"] for _query, _limit, options in runners["openalex"].calls]
    assert modes == ["semantic", "auto"]
    assert {query for query, _limit, _options in runners["openalex"].calls} == {
        "Delirium dexmedetomidine Cardiac Surgical Procedures"
    }
    assert payload["hybrid"]["channels"]["openalex"] == 2
    assert payload["hybrid"]["failed_channels"] == []
    assert payload["source_metadata"]["openalex"]["provider_mode"] == "keyword_fallback"


async def test_plain_question_keeps_pubmed_fill_tiers_as_the_primary_channel() -> None:
    """A long question ANDs to few PubMed hits; the default fill tiers must still run in hybrid."""
    question = "does dexmedetomidine reduce postoperative delirium after cardiac surgery in elderly patients"

    class _SparseExactPubMed(_Runner):
        async def __call__(
            self, query: str, limit: int, min_year: int | None, max_year: int | None, options: dict[str, Any]
        ) -> SourceAdapterResult[UnifiedArticle]:
            self.pmids = ["1"] if query == question else ["1", "2", "3", "4", "5", "6"]
            return await super().__call__(query, limit, min_year, max_year, options)

    runners = _runners()
    runners["pubmed"] = _SparseExactPubMed("pubmed", [])

    payload = json.loads(await _hybrid(runners, query=question, limit=5, options="hybrid,no_oa"))

    pubmed_queries = [query for query, _limit, _options in runners["pubmed"].calls]
    assert pubmed_queries[0] == question
    assert len(set(pubmed_queries)) > 1, "fill tiers did not run"
    assert payload["hybrid"]["channels"]["pubmed"] > 1
    # Neutral channels ran once each beside the PubMed tiers.
    assert len(runners["europe_pmc"].calls) == 1 and len(runners["openalex"].calls) == 1
    assert payload["articles"][0]["pmid"] in {"1", "3"}
