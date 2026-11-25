"""Precision-first deep_strategy regressions at the provider boundary.

Fake source runners stand in for PubMed so these tests exercise the real
planner, SemanticEnhancer strategy generation, tiered broker, aggregation,
ranking, formatting, and artifact envelope -- only provider I/O is replaced.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from pubmed_search.application.search.query_analyzer import AnalyzedQuery, QueryComplexity, QueryIntent
from pubmed_search.application.search.semantic_enhancer import (
    EnhancedQuery,
    ExpandedTerm,
    ResolvedEntity,
    SearchPlan,
    SemanticEnhancer,
)
from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.application.session.artifact_envelope import build_unified_search_artifact_envelope
from pubmed_search.application.unified.planning import _build_deep_strategies
from pubmed_search.application.unified.tiering import (
    DeepFillTracker,
    build_broadening_disclosure,
    order_by_retrieval_tier,
    provenance_for,
)
from pubmed_search.domain.entities.article import ArticleType, CitationMetrics, RetrievalProvenance, UnifiedArticle
from pubmed_search.infrastructure.sources.registry import get_source_registry
from pubmed_search.infrastructure.sources.unified_broker import _execute_deep_search
from pubmed_search.presentation.mcp_server.tools.unified_formatting import _format_as_json
from pubmed_search.presentation.mcp_server.tools.unified_runner import run_unified_search
from pubmed_search.shared.source_contracts import SourceAdapterError, SourceAdapterResult

EXPERT_QUERY = (
    '("Recovery Room"[Mesh] OR PACU[tiab] OR "postanesthesia care unit"[tiab]) AND '
    '("Consciousness Monitors"[Mesh] OR "bispectral index"[tiab] OR "processed EEG"[tiab]) AND '
    '("Emergence Delirium"[Mesh] OR delirium[tiab]) AND adult*'
)
NATURAL_QUERY = "processed EEG emergence delirium PACU adults"
BROAD_MARKER = "[Title/Abstract]"


class _NullResolver:
    async def resolve_entity(self, _text: str) -> None:
        return None


class _ModerateAnalyzer:
    def analyze(self, query: str) -> AnalyzedQuery:
        return AnalyzedQuery(
            original_query=query,
            normalized_query=query,
            complexity=QueryComplexity.MODERATE,
            intent=QueryIntent.COMPARISON,
        )


def _real_enhancer() -> SemanticEnhancer:
    """Real strategy generation; entity resolution resolves nothing offline."""
    return SemanticEnhancer(entity_resolver=_NullResolver())


def _article(pmid: str, title: str, *, high_quality: bool = False) -> UnifiedArticle:
    return UnifiedArticle(
        title=title,
        primary_source="pubmed",
        pmid=pmid,
        year=2024,
        journal="Journal",
        abstract="processed EEG emergence delirium bispectral index recovery room",
        article_type=ArticleType.META_ANALYSIS if high_quality else ArticleType.UNKNOWN,
        citation_metrics=CitationMetrics(citation_count=5_000 if high_quality else 1),
    )


class _FakePubMed:
    """Provider-boundary double: exact query and broad query have separate corpora."""

    def __init__(
        self,
        *,
        exact_total: int,
        broad_total: int = 12_598,
        broad_overlap: tuple[str, ...] = (),
        exact_status: str = "ok",
        broad_status: str = "ok",
    ) -> None:
        self.exact_total = exact_total
        self.broad_total = broad_total
        self.broad_overlap = broad_overlap
        self.exact_status = exact_status
        self.broad_status = broad_status
        self.calls: list[tuple[str, int]] = []

    async def __call__(
        self,
        query: str,
        limit: int,
        _min_year: int | None,
        _max_year: int | None,
        _options: dict[str, Any],
    ) -> SourceAdapterResult[UnifiedArticle]:
        self.calls.append((query, limit))
        if BROAD_MARKER in query:
            if self.broad_status == "hang":
                await asyncio.Event().wait()
            if self.broad_status == "error":
                return SourceAdapterResult.failure(
                    source="pubmed",
                    operation="search",
                    error=SourceAdapterError(
                        source="pubmed",
                        operation="search",
                        message="Provider returned HTTP 503",
                        kind="http",
                        retryable=True,
                        status_code=503,
                    ),
                    metadata={"logical_query": query, "physical_query": query, "query_executed": True},
                )
            overlap = [_article(pmid, f"Exact hit {pmid}") for pmid in self.broad_overlap]
            # Broad noise is deliberately "high quality" so ranking alone would
            # place it above the exact hits.
            noise = [
                _article(str(9000 + index), f"Broad noise {index}", high_quality=True)
                for index in range(self.broad_total)
            ]
            items = (overlap + noise)[:limit]
            total = self.broad_total
        else:
            if self.exact_status == "error":
                return SourceAdapterResult.failure(
                    source="pubmed",
                    operation="search",
                    error=SourceAdapterError(
                        source="pubmed",
                        operation="search",
                        message="Request timed out",
                        kind="timeout",
                        retryable=True,
                    ),
                    metadata={"logical_query": query, "physical_query": query, "query_executed": True},
                )
            items = [_article(str(1000 + index), f"Exact hit {1000 + index}") for index in range(self.exact_total)][
                :limit
            ]
            total = self.exact_total
        return SourceAdapterResult(
            source="pubmed",
            operation="search",
            items=items,
            total_count=total,
            status="ok" if items else "empty",
            metadata={"total_available": total, "physical_query": query, "query_executed": True},
        )

    @property
    def broad_calls(self) -> list[tuple[str, int]]:
        return [call for call in self.calls if BROAD_MARKER in call[0]]


async def _search(
    fake: _FakePubMed,
    *,
    query: str = EXPERT_QUERY,
    limit: int = 15,
    output_format: str = "json",
    options: str = "no_oa",
    searcher: Any | None = None,
) -> str:
    with patch(
        "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
        new_callable=AsyncMock,
        return_value=[],
    ):
        return await run_unified_search(
            searcher=searcher or AsyncMock(),
            query=query,
            limit=limit,
            ranking="quality",
            sources="pubmed",
            output_format=output_format,  # type: ignore[arg-type]
            options=options,
            analyzer_factory=_ModerateAnalyzer,
            enhancer_factory=_real_enhancer,
            search_functions={"pubmed": fake},
        )


# ---------------------------------------------------------------------------
# Expert query with enough hits: authoritative, never diluted
# ---------------------------------------------------------------------------


async def test_expert_query_with_enough_hits_runs_only_the_original_strategy() -> None:
    fake = _FakePubMed(exact_total=45)

    payload = json.loads(await _search(fake))

    assert fake.calls == [(EXPERT_QUERY, 15)]
    broadening = payload["broadening"]
    assert broadening["schema_version"] == "search-broadening/v1"
    assert broadening["needed"] is False
    assert broadening["applied"] is False
    assert broadening["mechanisms"] == []
    assert broadening["summary"] == (
        "no broadening needed (original total 45 ≥ limit 15); skipped lower-precision strategies: broad_tiab"
    )
    attempts = {row["strategy"]: row for row in broadening["attempts"]}
    assert attempts["original"]["executed"] is True
    assert attempts["original"]["total_available"] == 45
    assert attempts["original"]["contributed"] == 15
    assert attempts["broad_tiab"]["executed"] is False
    assert attempts["broad_tiab"]["skip_reason"] == "limit_filled"
    assert len(payload["articles"]) == 15
    assert {article["retrieval"]["tier"] for article in payload["articles"]} == {"exact"}
    assert payload["source_counts"][0]["total_available"] == 45


async def test_markdown_states_that_no_broadening_was_needed() -> None:
    markdown = await _search(_FakePubMed(exact_total=45), output_format="markdown")

    assert "**Broadening**: ✅ no broadening needed" in markdown
    assert "original total 45 ≥ limit 15" in markdown
    assert "🔻" not in markdown


# ---------------------------------------------------------------------------
# Sparse query: broadening fills only the gap, labeled and ranked last
# ---------------------------------------------------------------------------


async def test_sparse_query_broadens_only_the_gap_and_ranks_broadened_records_last() -> None:
    fake = _FakePubMed(exact_total=6, broad_overlap=("1000", "1001"))

    payload = json.loads(await _search(fake))

    assert fake.calls[0] == (EXPERT_QUERY, 15)
    assert len(fake.broad_calls) == 1
    # The broad request asks for the full per-source budget so overlap with the
    # exact hits cannot starve the fill; contribution is clipped to 9 slots.
    assert fake.broad_calls[0][1] == 15
    articles = payload["articles"]
    assert len(articles) == 15
    tiers = [article["retrieval"]["tier"] for article in articles]
    assert tiers == ["exact"] * 6 + ["broad"] * 9
    assert all(article["retrieval"]["broadened"] for article in articles[6:])
    assert not any(article["retrieval"]["broadened"] for article in articles[:6])
    assert {article["identifiers"]["pmid"] for article in articles[:6]} == {str(1000 + index) for index in range(6)}

    broadening = payload["broadening"]
    assert broadening["applied"] is True
    assert broadening["mechanisms"] == ["deep_strategy_tiers"]
    assert broadening["broadened_records"] == 9
    assert broadening["filled"] is True
    assert broadening["summary"] == (
        "original returned 6 of requested 15 (PubMed total 6) → broadened with broad_tiab, "
        "adding 9 lower-precision record(s)"
    )
    broad_row = next(row for row in broadening["attempts"] if row["strategy"] == "broad_tiab")
    assert broad_row["phase"] == "broaden"
    assert broad_row["total_available"] == 12_598
    assert broad_row["returned"] == 15
    assert broad_row["duplicates"] == 2
    assert broad_row["contributed"] == 9
    assert broad_row["surplus_discarded"] == 4
    # Totals of different queries are not additive, and the broad total must
    # never be presented as the PubMed total of the user's query.
    assert payload["source_counts"][0]["total_available"] is None


async def test_markdown_marks_broadened_records_after_exact_records() -> None:
    markdown = await _search(_FakePubMed(exact_total=6), output_format="markdown")

    assert "**Broadening**: ⚠️ original returned 6 of requested 15" in markdown
    assert "| broad | PubMed | broad\\_tiab | broaden | ok | 12598 | 15 | 9 |" in markdown
    divider = markdown.index("#### 🔻 Broadened results")
    assert markdown.index("### 6. Exact hit") < divider < markdown.index("### 7. Broad noise")
    assert markdown.count("**Retrieval**: 🔻 broadened") == 9


# ---------------------------------------------------------------------------
# Under-fill regression (v0.10.0 returned 8 of 15 from a budget split)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exact_total", "expected_calls"),
    [
        pytest.param(200, 1, id="original-alone-fills"),
        pytest.param(1, 2, id="broadening-fills-remaining-14"),
    ],
)
async def test_natural_language_query_fills_the_requested_limit(exact_total: int, expected_calls: int) -> None:
    fake = _FakePubMed(exact_total=exact_total)

    payload = json.loads(await _search(fake, query=NATURAL_QUERY))

    assert fake.calls[0] == (NATURAL_QUERY, 15)
    assert len(fake.calls) == expected_calls
    assert len(payload["articles"]) == 15
    assert payload["result_filter_counts"]["returned"] == 15
    assert payload["broadening"]["filled"] is True


# ---------------------------------------------------------------------------
# Opt-out and failure semantics
# ---------------------------------------------------------------------------


async def test_no_relax_disables_deep_broadening_and_says_so() -> None:
    fake = _FakePubMed(exact_total=6)

    payload = json.loads(await _search(fake, options="no_oa,no_relax"))

    assert fake.calls == [(EXPERT_QUERY, 15)]
    assert len(payload["articles"]) == 6
    broadening = payload["broadening"]
    assert broadening["needed"] is True
    assert broadening["applied"] is False
    assert broadening["enabled"] is False
    assert broadening["blocked_reason"] == "broadening_disabled"
    assert broadening["summary"] == (
        'original returned 6 of requested 15 (PubMed total 6); broadening disabled by options="no_relax"; '
        "still under-filled (6 of 15)"
    )


async def test_failed_exact_query_is_not_replaced_by_broadened_records() -> None:
    fake = _FakePubMed(exact_total=6, exact_status="error")

    payload = json.loads(await _search(fake))

    assert fake.broad_calls == []
    assert payload["articles"] == []
    assert payload["search_status"]["state"] == "failed"
    broad_row = next(row for row in payload["broadening"]["attempts"] if row["strategy"] == "broad_tiab")
    assert broad_row["skip_reason"] == "exact_tier_failed"
    assert "exact-tier query failed" in payload["broadening"]["summary"]


async def test_failed_broadening_attempt_is_disclosed_as_a_failure_not_an_empty_result() -> None:
    fake = _FakePubMed(exact_total=6, broad_status="error")

    payload = json.loads(await _search(fake))

    assert len(fake.broad_calls) == 1
    broadening = payload["broadening"]
    # Nothing was broadened: the only broadening request failed.
    assert broadening["applied"] is False
    assert broadening["mechanisms"] == []
    assert broadening["failed_attempts"] == 1
    assert broadening["summary"] == (
        "original returned 6 of requested 15 (PubMed total 6) → broadening with broad_tiab failed "
        "(PubMed request failed), so lower-precision coverage is incomplete; still under-filled (6 of 15)"
    )
    broad_row = next(row for row in broadening["attempts"] if row["strategy"] == "broad_tiab")
    assert (broad_row["status"], broad_row["executed"], broad_row["contributed"]) == ("error", True, 0)

    markdown = await _search(_FakePubMed(exact_total=6, broad_status="error"), output_format="markdown")
    assert "**Broadening**: ⚠️ original returned 6 of requested 15" in markdown
    assert "| broad | PubMed | broad\\_tiab | broaden | error |" in markdown

    original = SearchPlan(name="original", query=EXPERT_QUERY, source="pubmed")
    request, plan, execution = _artifact_inputs([_tagged("1", original)], broadening)
    envelope = build_unified_search_artifact_envelope(
        request=request, plan=plan, execution=execution, structured_payload="{}"
    )
    checks = {check["check"]: check for check in envelope.files["audit.json"]["checks"]}
    assert checks["search_broadening"]["severity"] == "warn"
    assert "failed or timed out" in checks["search_broadening"]["message"]


async def test_timed_out_broadening_attempt_is_disclosed_as_timed_out() -> None:
    fake = _FakePubMed(exact_total=6, broad_status="hang")
    original = SearchPlan(name="original", query=EXPERT_QUERY, source="pubmed")
    broad = SearchPlan(name="broad_tiab", query=f'"PACU"{BROAD_MARKER}', source="pubmed", priority=0, tier="broad")

    _results, metrics, _total, _counts, errors = await asyncio.wait_for(
        _execute_deep_search(
            AsyncMock(),
            EnhancedQuery(original_query=EXPERT_QUERY, strategies=[original, broad]),
            limit=15,
            min_year=None,
            max_year=None,
            advanced_filters={},
            strategies=[original, broad],
            search_functions={"pubmed": fake},
            strategy_timeout=0.05,
        ),
        timeout=5,
    )
    disclosure = build_broadening_disclosure(
        requested_limit=15, deep_metrics=metrics, relaxation=None, broadening_enabled=True
    )

    assert disclosure is not None
    assert (disclosure["applied"], disclosure["mechanisms"], disclosure["failed_attempts"]) == (False, [], 1)
    assert "→ broadening with broad_tiab timed out" in disclosure["summary"]
    assert "no new eligible records" not in disclosure["summary"]
    assert [error.kind for error in errors] == ["timeout"]


async def test_relaxation_whose_every_request_failed_is_not_reported_as_applied() -> None:
    query = "diabetes AND therapy"
    calls = 0

    async def page(*_args: Any, **_kwargs: Any) -> SourceSearchPage[dict[str, Any]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return SourceSearchPage(source="pubmed", items=[], total=0, query=query)
        raise RuntimeError("PubMed unavailable")

    searcher = AsyncMock()
    searcher.search_page.side_effect = page
    with patch(
        "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
        new_callable=AsyncMock,
        return_value=[],
    ):
        raw = await run_unified_search(
            searcher=searcher,
            query=query,
            sources="pubmed",
            output_format="json",
            options="shallow,no_scores",
            analyzer_factory=_ModerateAnalyzer,
        )

    broadening = json.loads(raw)["broadening"]
    relax_rows = [row for row in broadening["attempts"] if row["phase"] == "relax"]
    assert relax_rows and {row["status"] for row in relax_rows} == {"error"}
    assert (broadening["applied"], broadening["mechanisms"]) == (False, [])
    assert broadening["failed_attempts"] == len(relax_rows)
    assert "could not complete every broader PubMed query" in broadening["summary"]


async def test_exact_query_is_deepened_before_any_broadening() -> None:
    """Ineligible exact hits (e.g. exclude_seen) are replaced from the same query first."""
    fake = _FakePubMed(exact_total=45)
    original = SearchPlan(name="original", query=EXPERT_QUERY, source="pubmed")
    broad = SearchPlan(name="broad_tiab", query=f'"PACU"{BROAD_MARKER}', source="pubmed", priority=0, tier="broad")
    seen = {str(1000 + index) for index in range(10)}

    _results, metrics, pubmed_total, counts, errors = await _execute_deep_search(
        AsyncMock(),
        EnhancedQuery(original_query=EXPERT_QUERY, strategies=[original, broad]),
        limit=15,
        min_year=None,
        max_year=None,
        advanced_filters={},
        strategies=[original, broad],
        search_functions={"pubmed": fake},
        eligibility=lambda article: article.pmid not in seen,
    )

    assert fake.calls == [(EXPERT_QUERY, 15), (EXPERT_QUERY, 30)]
    outcome = metrics.tier_outcome
    assert outcome is not None
    assert outcome.exact_eligible_unique == 5
    assert outcome.deepened_records == 10
    assert outcome.broadening_needed is False
    assert outcome.eligible_unique == 15
    assert [(row.strategy_name, row.phase) for row in metrics.strategy_results] == [
        ("original", "exact"),
        ("original", "deepen"),
        ("broad_tiab", "skipped"),
    ]
    assert pubmed_total == 45
    assert counts == {"pubmed": (25, 45)}
    assert errors == []


async def test_exact_row_contributed_counts_only_eligible_new_records() -> None:
    """Records later removed by exclude_seen / preprint policy did not contribute to the result."""
    fake = _FakePubMed(exact_total=15)
    original = SearchPlan(name="original", query=EXPERT_QUERY, source="pubmed")
    seen = {str(1000 + index) for index in range(10)}

    _results, metrics, *_ = await _execute_deep_search(
        AsyncMock(),
        EnhancedQuery(original_query=EXPERT_QUERY, strategies=[original]),
        limit=15,
        min_year=None,
        max_year=None,
        advanced_filters={},
        strategies=[original],
        search_functions={"pubmed": fake},
        eligibility=lambda article: article.pmid not in seen,
    )

    exact_row = metrics.strategy_results[0]
    assert (exact_row.phase, exact_row.articles_count) == ("exact", 15)
    assert (exact_row.new_unique, exact_row.ineligible, exact_row.contributed) == (15, 10, 5)
    disclosure = build_broadening_disclosure(
        requested_limit=15, deep_metrics=metrics, relaxation=None, broadening_enabled=True
    )
    assert disclosure is not None
    assert disclosure["attempts"][0]["contributed"] == disclosure["exact_eligible_unique"] == 5


# ---------------------------------------------------------------------------
# auto_relax shares the same disclosure and provenance contract
# ---------------------------------------------------------------------------


def _searcher_with_pages(*pages: SourceSearchPage[dict[str, Any]]) -> AsyncMock:
    searcher = AsyncMock()
    searcher.search_page.side_effect = list(pages)
    return searcher


async def test_shallow_auto_relax_uses_the_broadening_disclosure_contract() -> None:
    query = "diabetes AND therapy"
    searcher = _searcher_with_pages(
        SourceSearchPage(source="pubmed", items=[], total=0, query=query),
        SourceSearchPage(
            source="pubmed",
            items=[{"pmid": "12345", "title": "Relaxed Article", "authors": ["A B"]}],
            total=1,
            query="diabetes OR therapy",
        ),
    )
    with patch(
        "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
        new_callable=AsyncMock,
        return_value=[],
    ):
        raw = await run_unified_search(
            searcher=searcher,
            query=query,
            sources="pubmed",
            output_format="json",
            options="shallow,no_scores",
            analyzer_factory=_ModerateAnalyzer,
        )

    payload = json.loads(raw)
    broadening = payload["broadening"]
    assert broadening["schema_version"] == "search-broadening/v1"
    assert broadening["mechanisms"] == ["auto_relax"]
    assert broadening["applied"] is True
    assert broadening["needed"] is True
    assert broadening["broadened_records"] == 1
    assert broadening["summary"].startswith(
        "original returned 0 of requested 10 (PubMed total 0) → auto-relaxed the PubMed query (level 1: and_to_or)"
    )
    assert [(row["strategy"], row["tier"]) for row in broadening["attempts"]] == [
        ("original", "exact"),
        ("auto_relax:and_to_or", "relaxed"),
    ]
    retrieval = payload["articles"][0]["retrieval"]
    assert retrieval == {
        "tier": "relaxed",
        "tier_rank": 3,
        "broadened": True,
        "source": "pubmed",
        "strategy": "auto_relax:and_to_or",
        "matched_by": [{"source": "pubmed", "strategy": "auto_relax:and_to_or", "tier": "relaxed", "tier_rank": 3}],
    }


async def test_deep_tiers_and_auto_relax_compose_into_one_disclosure() -> None:
    query = "(diabetes[tiab] AND therapy[tiab])"
    fake = _FakePubMed(exact_total=0, broad_total=0)
    searcher = _searcher_with_pages(
        SourceSearchPage(
            source="pubmed",
            items=[{"pmid": "777", "title": "Relaxed via field-tag removal", "authors": ["A B"]}],
            total=3,
            query="diabetes AND therapy",
        ),
    )

    payload = json.loads(await _search(fake, query=query, limit=10, searcher=searcher))

    broadening = payload["broadening"]
    assert broadening["mechanisms"] == ["deep_strategy_tiers", "auto_relax"]
    assert broadening["summary"].startswith(
        "original returned 0 of requested 10 (PubMed total 0) → broadened with broad_tiab, "
        "but no new eligible records were found → auto-relaxed the PubMed query"
    )
    assert payload["articles"][0]["retrieval"]["tier"] == "relaxed"
    assert payload["relaxation"]["was_relaxed"] is True


async def test_markdown_shows_the_same_disclosure_for_auto_relax() -> None:
    query = "diabetes AND therapy"
    searcher = _searcher_with_pages(
        SourceSearchPage(source="pubmed", items=[], total=0, query=query),
        SourceSearchPage(
            source="pubmed",
            items=[{"pmid": "12345", "title": "Relaxed Article", "authors": ["A B"]}],
            total=1,
            query="diabetes OR therapy",
        ),
    )
    with patch(
        "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
        new_callable=AsyncMock,
        return_value=[],
    ):
        markdown = await run_unified_search(
            searcher=searcher,
            query=query,
            sources="pubmed",
            options="shallow,no_scores",
            analyzer_factory=_ModerateAnalyzer,
        )

    assert "**Broadening**: ⚠️ original returned 0 of requested 10" in markdown
    assert "**Retrieval**: 🔻 broadened — found only by PubMed auto\\_relax:and\\_to\\_or (relaxed tier)" in markdown


# ---------------------------------------------------------------------------
# Structured formats, artifact, and audit
# ---------------------------------------------------------------------------


async def test_toon_output_carries_the_broadening_disclosure() -> None:
    toon = await _search(_FakePubMed(exact_total=6), output_format="toon")

    assert "search-broadening/v1" in toon
    assert "deep_strategy_tiers" in toon


def test_size_capped_json_keeps_a_compact_broadening_summary() -> None:
    articles = [_article(str(index), f"Article {index}") for index in range(5)]
    broadening = {
        "schema_version": "search-broadening/v1",
        "needed": True,
        "applied": True,
        "mechanisms": ["deep_strategy_tiers"],
        "broadened_records": 3,
        "filled": True,
        "summary": "original returned 2 of requested 5 (PubMed total 2) → broadened with broad_tiab, adding 3",
        "attempts": [{"strategy": "original"}, {"strategy": "broad_tiab"}],
    }
    stats = SimpleNamespace(unique_articles=5, to_dict=dict, by_source={})
    analysis = _ModerateAnalyzer().analyze("q")

    payload = json.loads(
        _format_as_json(articles, analysis, stats, broadening=broadening, max_response_chars=2_500)  # type: ignore[arg-type]
    )

    assert payload["status"] == "truncated"
    assert payload["broadening"]["summary"] == broadening["summary"]
    assert "attempts" not in payload["broadening"]


def _artifact_inputs(ranked: list[UnifiedArticle], broadening: dict[str, Any]) -> tuple[Any, Any, Any]:
    request = SimpleNamespace(
        query=EXPERT_QUERY,
        limit=15,
        sources="pubmed",
        ranking="quality",
        output_format="json",
        advanced_filters={},
        deep_search=True,
        include_clinical_trials=False,
    )
    original = SearchPlan(name="original", query=EXPERT_QUERY, source="pubmed")
    broad = SearchPlan(name="broad_tiab", query="broad", source="pubmed", priority=0, tier="broad")
    plan = SimpleNamespace(
        request=request,
        query=EXPERT_QUERY,
        provider_neutral_query=EXPERT_QUERY,
        analysis=_ModerateAnalyzer().analyze(EXPERT_QUERY),
        enhanced_query=None,
        deep_strategies=[original, broad],
        dispatch_sources=["pubmed"],
    )
    execution = SimpleNamespace(
        ranked=ranked,
        stats=SimpleNamespace(unique_articles=len(ranked), total_input=len(ranked), duplicates_removed=0),
        source_api_counts={"pubmed": (len(ranked), None)},
        source_errors=[],
        deep_search_metrics=None,
        relaxation_result=None,
        broadening=broadening,
        result_filter_counts={"eligible_unique": len(ranked), "returned": len(ranked)},
    )
    return request, plan, execution


def _tagged(pmid: str, strategy: SearchPlan) -> UnifiedArticle:
    article = _article(pmid, f"Article {pmid}")
    article.retrieval.append(provenance_for(strategy))
    return article


async def test_artifact_persists_broadening_and_audits_tier_order() -> None:
    original = SearchPlan(name="original", query=EXPERT_QUERY, source="pubmed")
    broad = SearchPlan(name="broad_tiab", query="broad", source="pubmed", tier="broad")
    ranked = [_tagged("1", original), _tagged("2", original), _tagged("3", broad)]
    broadening = {
        "schema_version": "search-broadening/v1",
        "needed": True,
        "applied": True,
        "mechanisms": ["deep_strategy_tiers"],
        "broadened_records": 1,
        "filled": True,
        "summary": "original returned 2 of requested 3 (PubMed total 2) → broadened with broad_tiab, adding 1",
        "attempts": [],
    }

    request, plan, execution = _artifact_inputs(ranked, broadening)
    envelope = build_unified_search_artifact_envelope(
        request=request,
        plan=plan,
        execution=execution,
        structured_payload="{}",
    )

    strategy = envelope.files["query_strategy.json"]
    assert strategy["broadening"]["summary"] == broadening["summary"]
    assert [row["tier"] for row in strategy["deep_search"]["generated_strategies"]] == ["exact", "broad"]
    assert envelope.summary["broadening"]["applied"] is True
    checks = {check["check"]: check for check in envelope.files["audit.json"]["checks"]}
    assert checks["search_broadening"]["severity"] == "info"
    assert checks["retrieval_tier_order"]["severity"] == "pass"

    request, plan, execution = _artifact_inputs([ranked[2], ranked[0], ranked[1]], broadening)
    bad = build_unified_search_artifact_envelope(
        request=request,
        plan=plan,
        execution=execution,
        structured_payload="{}",
    )
    bad_checks = {check["check"]: check for check in bad.files["audit.json"]["checks"]}
    assert bad_checks["retrieval_tier_order"]["severity"] == "fail"
    assert bad.files["audit.json"]["status"] == "fail"


# ---------------------------------------------------------------------------
# Planning, strategy generation, and pure policy units
# ---------------------------------------------------------------------------


def test_strategy_generation_declares_tiers_without_changing_the_lead_strategy() -> None:
    enhancer = _real_enhancer()
    entity = ResolvedEntity(
        original_text="propofol",
        resolved_name="Propofol",
        entity_type="chemical",
        entity_id="@CHEMICAL_Propofol",
        mesh_id="D015742",
    )
    terms = [
        ExpandedTerm(term="propofol", source="original"),
        ExpandedTerm(term="sedation", source="original"),
        ExpandedTerm(term="Propofol", source="pubtator", mesh_id="D015742"),
    ]

    strategies = enhancer._generate_strategies("propofol sedation", [entity], terms)

    assert {strategy.name: strategy.tier for strategy in strategies} == {
        "original": "exact",
        "mesh_expanded": "narrow",
        "entity_semantic": "semantic",
        "fulltext_epmc": "exact",
        "broad_tiab": "broad",
    }
    # The pipeline ``expand`` action reads strategies[0]; keep it unchanged.
    assert strategies[0].name == "entity_semantic"


def test_planner_drops_narrowing_and_duplicate_fill_strategies() -> None:
    query = "propofol sedation"
    enhanced = EnhancedQuery(
        original_query=query,
        strategies=[
            SearchPlan(name="original", query=query, source="pubmed"),
            SearchPlan(name="mesh_expanded", query=f"(MeSH) AND ({query})", source="pubmed", tier="narrow"),
            SearchPlan(name="entity_semantic", query=query, source="pubmed", tier="semantic"),
            SearchPlan(name="broad_tiab", query='"propofol"[Title/Abstract]', source="pubmed", tier="broad"),
        ],
    )

    strategies = _build_deep_strategies(
        query=query,
        enhanced_query=enhanced,
        dispatch_sources=["pubmed"],
        registry=get_source_registry(),
    )

    assert [(strategy.name, strategy.tier) for strategy in strategies] == [
        ("original", "exact"),
        ("broad_tiab", "broad"),
    ]


def test_fill_tracker_counts_eligible_unique_records_and_clips_surplus() -> None:
    exact = SearchPlan(name="original", query="q", source="pubmed")
    broad = SearchPlan(name="broad_tiab", query="b", source="pubmed", tier="broad")
    tracker = DeepFillTracker(4, eligibility=lambda article: article.pmid != "2")

    exact_admission = tracker.admit_exact([_article("1", "A"), _article("2", "B")], provenance_for(exact))
    fill = tracker.admit_fill(
        [_article("1", "A"), _article("3", "C"), _article("4", "D"), _article("5", "E"), _article("6", "F")],
        provenance_for(broad),
    )

    assert len(exact_admission.accepted) == 2
    assert exact_admission.ineligible == 1
    assert [article.pmid for article in fill.accepted] == ["3", "4", "5"]
    assert fill.duplicates == 1
    assert fill.surplus_discarded == 1
    assert tracker.filled
    assert all(article.retrieval[0].tier == "broad" for article in fill.accepted)


def test_merged_records_keep_their_most_precise_tier_and_tier_order_is_stable() -> None:
    exact = RetrievalProvenance(source="europe_pmc", strategy="fulltext_epmc", tier="exact", tier_rank=0)
    broad = RetrievalProvenance(source="pubmed", strategy="broad_tiab", tier="broad", tier_rank=2)
    broad_only = _article("10", "Broad only")
    broad_only.retrieval.append(broad)
    merged = _article("11", "Found by both")
    merged.retrieval.append(broad)
    duplicate = _article("11", "Found by both")
    duplicate.retrieval.append(exact)
    untiered = _article("12", "Shallow record")

    merged.merge_from(duplicate)

    assert merged.retrieval_tier_rank == 0
    assert merged.retrieval_payload()["tier"] == "exact"  # type: ignore[index]
    assert untiered.retrieval_payload() is None
    assert [article.pmid for article in order_by_retrieval_tier([broad_only, merged, untiered])] == ["11", "12", "10"]
