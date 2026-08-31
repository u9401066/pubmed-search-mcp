"""Deterministic and privacy-safe Unified Search enrichment regressions."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from pubmed_search.application.search.query_analyzer import QueryAnalyzer
from pubmed_search.application.search.result_aggregator import (
    AggregationStats,
    RankingConfig,
    ResultAggregator,
)
from pubmed_search.application.session.artifact_envelope import build_unified_search_artifact_envelope
from pubmed_search.application.unified.execution import _rank_articles_deterministically
from pubmed_search.domain.entities.article import (
    OpenAccessLink,
    OpenAccessStatus,
    SourceMetadata,
    UnifiedArticle,
)
from pubmed_search.infrastructure.sources.unified_enrichment import (
    ArticleEnrichmentPatch,
    EnrichmentOutcome,
    EnrichmentReport,
    _apply_enrichment_outcomes,
    _enrich_with_crossref,
    run_unified_enrichments,
)
from pubmed_search.presentation.mcp_server.tools.unified_formatting import _format_as_json


@pytest.mark.asyncio
async def test_crossref_partial_failure_returns_patches_without_in_task_mutation() -> None:
    articles = [
        UnifiedArticle(title="First", primary_source="pubmed", doi="10.1000/first"),
        UnifiedArticle(title="Second", primary_source="pubmed", doi="10.1000/second"),
    ]
    client = AsyncMock()

    async def _get_work(doi: str):
        if doi.endswith("second"):
            raise RuntimeError(
                "token=super-secret https://provider.invalid/work?api_key=super-secret /srv/private/key.json"
            )
        return {
            "DOI": doi,
            "title": ["Crossref title"],
            "is-referenced-by-count": 42,
        }

    client.get_work.side_effect = _get_work
    with patch(
        "pubmed_search.infrastructure.sources.unified_enrichment.get_crossref_client",
        return_value=client,
    ):
        outcome = await _enrich_with_crossref(articles)

    assert all(article.citation_metrics is None for article in articles)
    assert outcome.status == "partial"
    assert (outcome.attempted, outcome.succeeded, outcome.failed) == (2, 1, 1)

    diagnostic = json.dumps(EnrichmentReport((outcome,)).to_diagnostic())
    assert "super-secret" not in diagnostic
    assert "provider.invalid" not in diagnostic
    assert "/srv/private" not in diagnostic
    assert "unexpected" in diagnostic

    _apply_enrichment_outcomes(articles, [outcome])
    assert articles[0].citation_metrics is not None
    assert articles[0].citation_metrics.citation_count == 42
    assert articles[1].citation_metrics is None


@pytest.mark.asyncio
async def test_all_provider_failures_are_reported_without_secret_or_path_leakage(caplog) -> None:
    article = UnifiedArticle(
        title="Article",
        primary_source="openalex",
        doi="10.1000/article",
        sources=[
            SourceMetadata(
                source="openalex",
                raw_data={"_openalex_source_id": "https://openalex.org/S123"},
            )
        ],
    )
    raw_failure = RuntimeError(
        "token=super-secret https://provider.invalid/work?api_key=super-secret /srv/private/key.json"
    )

    with (
        patch(
            "pubmed_search.infrastructure.sources.unified_enrichment.get_crossref_client",
            side_effect=raw_failure,
        ),
        patch(
            "pubmed_search.infrastructure.sources.unified_enrichment.get_openalex_client",
            side_effect=raw_failure,
        ),
        patch(
            "pubmed_search.infrastructure.sources.unified_enrichment.get_unpaywall_client",
            side_effect=raw_failure,
        ),
    ):
        report = await run_unified_enrichments(
            [article],
            include_crossref=True,
            include_journal_metrics=True,
            include_unpaywall=True,
        )

    diagnostic = json.dumps(report.to_diagnostic())
    assert report.status == "failed"
    assert report.failed == 3
    assert [outcome.source for outcome in report.outcomes] == [
        "crossref",
        "journal_metrics",
        "unpaywall",
    ]
    for rendered in (diagnostic, caplog.text):
        assert "super-secret" not in rendered
        assert "provider.invalid" not in rendered
        assert "/srv/private" not in rendered


@pytest.mark.asyncio
async def test_bounded_enrichment_candidates_ignore_tied_input_arrival_order() -> None:
    articles = [
        UnifiedArticle(
            title="Identical relevance",
            primary_source="pubmed",
            doi=f"10.1000/{index:02d}",
            year=2025,
        )
        for index in range(12)
    ]
    aggregator = ResultAggregator()
    config = RankingConfig.default()

    async def _requested_dois(input_articles: list[UnifiedArticle]) -> list[str]:
        ranked = _rank_articles_deterministically(
            input_articles,
            aggregator,
            config,
            "identical relevance",
        )
        client = AsyncMock()
        client.get_work.return_value = None
        with patch(
            "pubmed_search.infrastructure.sources.unified_enrichment.get_crossref_client",
            return_value=client,
        ):
            await _enrich_with_crossref(ranked)
        return [call.args[0] for call in client.get_work.await_args_list]

    forward = await _requested_dois(articles)
    reverse = await _requested_dois(list(reversed(articles)))

    expected = [f"10.1000/{index:02d}" for index in range(10)]
    assert forward == reverse == expected


def test_central_patch_application_has_deterministic_provider_precedence() -> None:
    original = UnifiedArticle(title="Article", primary_source="pubmed", doi="10.1000/article")
    crossref_article = UnifiedArticle(
        title="Crossref article",
        primary_source="crossref",
        doi="10.1000/article",
        oa_links=[
            OpenAccessLink(
                url="https://repository.invalid/article",
                version="unknown",
                license="crossref-license",
            )
        ],
    )
    crossref = EnrichmentOutcome(
        source="crossref",
        attempted=1,
        succeeded=1,
        skipped=0,
        patches=(
            ArticleEnrichmentPatch(
                source="crossref",
                article_index=0,
                crossref_article=crossref_article,
            ),
        ),
    )
    unpaywall = EnrichmentOutcome(
        source="unpaywall",
        attempted=1,
        succeeded=1,
        skipped=0,
        patches=(
            ArticleEnrichmentPatch(
                source="unpaywall",
                article_index=0,
                is_open_access=True,
                oa_status=OpenAccessStatus.GOLD,
                oa_links=(
                    OpenAccessLink(
                        url="https://repository.invalid/article",
                        version="publishedVersion",
                        license="cc-by",
                        is_best=True,
                    ),
                ),
            ),
        ),
    )

    first = [copy.deepcopy(original)]
    second = [copy.deepcopy(original)]
    _apply_enrichment_outcomes(first, [unpaywall, crossref])
    _apply_enrichment_outcomes(second, [crossref, unpaywall])

    assert first[0].to_dict() == second[0].to_dict()
    assert first[0].oa_status is OpenAccessStatus.GOLD
    assert first[0].oa_links[0].license == "cc-by"
    assert first[0].oa_links[0].is_best is True


def test_enrichment_diagnostics_reach_structured_result_and_artifact_metadata() -> None:
    diagnostic = {
        "status": "partial",
        "attempted": 2,
        "succeeded": 1,
        "skipped": 0,
        "failed": 1,
        "providers": [
            {
                "source": "crossref",
                "status": "partial",
                "attempted": 2,
                "succeeded": 1,
                "skipped": 0,
                "failed": 1,
                "failure_categories": {"provider_unavailable": 1},
            }
        ],
    }
    article = UnifiedArticle(
        title="Result",
        primary_source="pubmed",
        pmid="12345",
        doi="10.1000/result",
        year=2025,
    )
    analysis = QueryAnalyzer().analyze("enrichment diagnostics")
    stats = AggregationStats(total_input=1, unique_articles=1, by_source={"pubmed": 1})
    structured = json.loads(
        _format_as_json(
            [article],
            analysis,
            stats,
            source_api_counts={"pubmed": (1, 1)},
            source_statuses={"pubmed": "ok"},
            enrichment_metadata=diagnostic,
            output_format="json",
        )
    )
    assert structured["search_status"]["state"] == "completed"
    assert structured["enrichment"] == diagnostic

    request = SimpleNamespace(
        query="enrichment diagnostics",
        limit=10,
        sources="pubmed,crossref",
        ranking="balanced",
        output_format="json",
        advanced_filters={},
        deep_search=False,
        retrieval_mode="auto",
        include_clinical_trials=False,
    )
    plan = SimpleNamespace(
        request=request,
        query=request.query,
        provider_neutral_query=request.query,
        analysis=analysis,
        icd_matches=[],
        enhanced_query=None,
        matched_entity_names=[],
        user_sources=["pubmed", "crossref"],
        dispatch_sources=["pubmed", "crossref"],
        effective_min_year=None,
        effective_max_year=None,
    )
    execution = SimpleNamespace(
        ranked=[article],
        stats=stats,
        source_api_counts={"pubmed": (1, 1)},
        source_errors=[],
        source_metadata={"pubmed": {}},
        source_statuses={"pubmed": "ok"},
        deep_search_metrics=None,
        relaxation_result=None,
        source_disagreement=None,
        reproducibility_score=None,
        clinical_trials_query=None,
        result_filter_counts={"eligible_unique": 1, "returned": 1},
        enrichment_metadata=diagnostic,
    )
    envelope = build_unified_search_artifact_envelope(
        request=request,
        plan=plan,
        execution=execution,
        structured_payload=json.dumps(structured),
    )

    assert envelope.summary["enrichment"] == diagnostic
    assert envelope.metadata["enrichment"] == diagnostic
    audit = envelope.files["audit.json"]
    assert any(check["check"] == "enrichment_coverage" and check["severity"] == "warn" for check in audit["checks"])
