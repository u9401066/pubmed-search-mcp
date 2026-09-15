"""Offline failures that affect literature retrieval, without external APIs."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pubmed_search.application.pipeline.executor import PipelineExecutor
from pubmed_search.application.search.ranking_algorithms import BM25Corpus, bm25_score, reciprocal_rank_fusion
from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.domain.entities.pipeline import PipelineConfig, PipelineOutput, PipelineStep, StepResult
from pubmed_search.shared.article_identity import canonical_article_key


def article(doc_id: str, title: str, abstract: str = "") -> UnifiedArticle:
    return UnifiedArticle(pmid=doc_id, title=title, abstract=abstract, primary_source="pubmed")


def test_pubmed_syntax_does_not_change_lexical_relevance():
    papers = [article("1", "Mesh repair and title abstract reporting"), article("2", "Glioblastoma therapy")]
    corpus = BM25Corpus.from_articles(papers)
    for paper in papers:
        assert bm25_score(paper, "glioblastoma[MeSH Terms] AND therapy[Title/Abstract]", corpus) == pytest.approx(
            bm25_score(paper, "glioblastoma therapy", corpus)
        )


@pytest.mark.parametrize("term", ["AI", "RA", "MS", "T2", "IL-6", "PD-1"])
def test_short_biomedical_concepts_remain_searchable(term):
    paper = article("1", f"{term} diagnosis")
    assert bm25_score(paper, term, BM25Corpus.from_articles([paper])) > 0


def test_query_repetition_does_not_multiply_term_weight():
    paper = article("1", "Sepsis diagnosis")
    corpus = BM25Corpus.from_articles([paper])
    assert bm25_score(paper, "sepsis OR sepsis", corpus) == bm25_score(paper, "sepsis", corpus)


def test_stopword_padding_does_not_change_document_length_normalization():
    plain = article("1", "Sepsis diagnosis", "Clinical evidence")
    padded = article("2", "Sepsis diagnosis", "Clinical evidence " + "in of to the " * 30)
    corpus = BM25Corpus.from_articles([plain, padded])
    assert bm25_score(plain, "sepsis", corpus) == bm25_score(padded, "sepsis", corpus)


def test_rrf_absence_means_no_vote_and_duplicate_cannot_demote_a_document():
    a, b = article("1", "Sepsis"), article("2", "Diabetes")
    ka, kb = canonical_article_key(a), canonical_article_key(b)
    result = reciprocal_rank_fusion([a, b], {"one": [ka, ka, kb], "two": [kb]})
    assert result.dimension_contributions[ka]["one"] == pytest.approx(0.5 / 61)
    assert result.dimension_contributions[ka]["two"] == 0
    assert result.dimension_contributions[kb]["one"] == pytest.approx(0.5 / 62)
    assert result.ranked_articles == [b, a]


def test_pipeline_rrf_does_not_reward_duplicates_within_one_search():
    repeated = article("1", "Repeated paper")
    shared = article("2", "Paper found by two independent searches")
    executor = PipelineExecutor()
    result = executor._rrf_merge([[repeated] * 5 + [shared], [shared]])
    assert result == [shared, repeated]


async def test_pipeline_uses_query_to_rank_before_truncation():
    searcher = AsyncMock()
    searcher.search_page.return_value = SourceSearchPage(
        source="pubmed",
        query="sepsis",
        total=2,
        items=[
            {"pmid": "1", "title": "Diabetes treatment", "abstract": "Clinical evidence"},
            {"pmid": "2", "title": "Sepsis treatment", "abstract": "Clinical evidence"},
        ],
    )
    config = PipelineConfig(
        steps=[PipelineStep(id="search", action="search", params={"query": "sepsis"})],
        output=PipelineOutput(limit=1),
    )
    papers, _ = await PipelineExecutor(searcher=searcher).execute(config)
    assert [paper.pmid for paper in papers] == ["2"]


def test_ranking_context_uses_only_successful_search_ancestors():
    config = PipelineConfig(
        steps=[
            PipelineStep(id="unrelated", action="search", params={"query": "diabetes"}),
            PipelineStep(id="expanded", action="search"),
            PipelineStep(id="failed", action="search"),
            PipelineStep(id="merge", action="merge", inputs=["expanded", "failed"]),
            PipelineStep(id="later", action="search", params={"query": "asthma"}),
        ]
    )
    results = {
        "unrelated": StepResult(step_id="unrelated", action="search", metadata={"query": "diabetes"}),
        "expanded": StepResult(step_id="expanded", action="search", metadata={"query": "sepsis[MeSH]"}),
        "failed": StepResult(step_id="failed", action="search", error="unavailable", metadata={"query": "cancer"}),
        "later": StepResult(step_id="later", action="search", metadata={"query": "asthma"}),
    }
    assert PipelineExecutor._ranking_query(config, results, "merge") == "sepsis[MeSH]"


def test_ranking_context_includes_each_executed_query_once():
    config = PipelineConfig(
        steps=[
            PipelineStep(id="a", action="search"),
            PipelineStep(id="b", action="search"),
            PipelineStep(id="c", action="search"),
            PipelineStep(id="merge", action="merge", inputs=["a", "b", "c"]),
        ]
    )
    results = {
        step_id: StepResult(step_id=step_id, action="search", metadata={"query": query})
        for step_id, query in [("a", "sepsis"), ("b", "bacteremia"), ("c", "sepsis")]
    }
    assert PipelineExecutor._ranking_query(config, results, "merge") == "sepsis OR bacteremia"


def test_rrf_emits_each_document_once():
    paper = article("1", "Sepsis")
    key = canonical_article_key(paper)
    assert reciprocal_rank_fusion([paper, paper], {"a": [key]}).ranked_articles == [paper]


def test_rrf_rejects_negative_k():
    with pytest.raises(ValueError, match="non-negative"):
        reciprocal_rank_fusion([], {}, k=-1)


@pytest.mark.parametrize("value", [-1, "²", "token=private-value"])
def test_invalid_source_totals_remain_unknown_without_echoing_payload(value):
    from pubmed_search.application.search.source_models import coerce_optional_total

    total, warnings = coerce_optional_total(value)
    assert total is None and warnings
    assert "private-value" not in " ".join(warnings)


def test_icd_expansion_preserves_each_original_occurrence_once():
    from pubmed_search.application.unified.helpers import detect_and_expand_icd_codes
    from pubmed_search.application.unified.planning import _build_provider_neutral_icd_query

    query = "E11 OR E11.9 OR E11"
    expanded, matches = detect_and_expand_icd_codes(query)
    assert len(matches) == 2
    assert expanded.count("[MeSH]") == 3
    neutral = _build_provider_neutral_icd_query(query, matches, semantic=False)
    assert neutral.count("Diabetes Mellitus") == 3
    assert ").9" not in neutral


@pytest.mark.parametrize(
    "query,intent",
    [
        ("corticosteroid treatment", "exploration"),
        ("systematic review of treatment and complications", "systematic"),
    ],
)
def test_query_intent_does_not_match_operator_substrings(query, intent):
    from pubmed_search.application.search.query_analyzer import QueryAnalyzer

    assert QueryAnalyzer().analyze(query).intent.value == intent


def test_analyzer_keeps_identifier_namespaces_and_explicit_relative_years():
    from datetime import datetime, timezone

    from pubmed_search.application.search.query_analyzer import QueryAnalyzer

    analyzer = QueryAnalyzer()
    parsed = analyzer.analyze("PMC12345678")
    assert [(item.type, item.value) for item in parsed.identifiers] == [("pmc", "PMC12345678")]
    assert analyzer.analyze("doi:10.2020/example").year_from is None
    assert analyzer.analyze("last 2 years of sepsis research").year_from == datetime.now(timezone.utc).year - 2


def test_conflicting_identifiers_do_not_merge_evidence():
    from pubmed_search.application.search.result_aggregator import ResultAggregator

    left = article("1", "Study A", "Evidence A")
    left.doi = "10.1000/a"
    right = article("1", "Study B", "Evidence B")
    right.doi = "10.1000/b"
    results, stats = ResultAggregator().aggregate([[left, right]])
    assert len(results) == 2 and stats.duplicates_removed == 0
    assert {paper.abstract for paper in results} == {"Evidence A", "Evidence B"}


def test_aggregate_and_rank_uses_the_override_deduplication_policy():
    from pubmed_search.application.search.result_aggregator import (
        DeduplicationStrategy,
        RankingConfig,
        ResultAggregator,
    )

    papers = [
        UnifiedArticle(title="A long shared study title without identifiers", primary_source="pubmed") for _ in range(2)
    ]
    ranked, stats = ResultAggregator().aggregate_and_rank(
        [papers], RankingConfig(dedup_strategy=DeduplicationStrategy.STRICT)
    )
    assert len(ranked) == 2 and stats.duplicates_removed == 0


def test_zero_weight_dimensions_cannot_break_relevance_ties():
    from pubmed_search.application.search.result_aggregator import RankingConfig, ResultAggregator
    from pubmed_search.domain.entities.article import CitationMetrics

    papers = [article("1", "Sepsis"), article("2", "Sepsis")]
    papers[1].citation_metrics = CitationMetrics(citation_count=1000)
    config = RankingConfig(
        relevance_weight=1,
        quality_weight=0,
        recency_weight=0,
        impact_weight=0,
        source_trust_weight=0,
        entity_match_weight=0,
    )
    ranked = ResultAggregator(config).rank(papers, query="sepsis")
    assert ranked[0].ranking_score == ranked[1].ranking_score


def test_mmr_zero_limit_returns_no_selection():
    from pubmed_search.application.search.ranking_algorithms import mmr_diversify

    assert mmr_diversify([article("1", "Sepsis"), article("2", "Asthma")], "sepsis", top_k=0).articles == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1])
def test_mmr_rejects_invalid_selection_weights(value):
    from pubmed_search.application.search.ranking_algorithms import mmr_diversify

    with pytest.raises(ValueError, match="MMR lambda"):
        mmr_diversify([article("1", "Sepsis"), article("2", "Asthma")], "sepsis", lambda_param=value)


def test_reproducibility_does_not_count_unqueried_sources_or_claim_measured_replay():
    from pubmed_search.application.search.reproducibility import calculate_reproducibility

    report = calculate_reproducibility("sepsis", ["pubmed", "openalex"], ["pubmed", "pubmed", "unqueried"], [])
    assert report.source_coverage == 0.5
    assert report.to_dict()["measurement_type"] == "heuristic"
    assert report.to_dict()["provider_results_may_change"] is True


def test_analyzer_preserves_citation_intent_and_broad_topic_branch():
    from pubmed_search.application.search.query_analyzer import QueryAnalyzer

    analyzer = QueryAnalyzer()
    assert analyzer.analyze("papers citing PMID:12345678").intent.value == "citation_tracking"
    assert analyzer.analyze("cancer").complexity.value == "ambiguous"
    assert analyzer.analyze("RA and IL-6").keywords == ["RA", "IL-6"]


def test_ranking_retains_conflicting_records_with_the_same_canonical_key():
    from pubmed_search.application.search.result_aggregator import ResultAggregator
    from pubmed_search.domain.entities.article import CitationMetrics

    first, second = article("1", "Sepsis evidence"), article("2", "Asthma evidence")
    first.doi = second.doi = "10.1000/conflict"
    second.citation_metrics = CitationMetrics(citation_count=1000, relative_citation_ratio=-2.0)
    ranked, _stats = ResultAggregator().aggregate_and_rank([[first, second]], query="sepsis")
    assert len(ranked) == 2
    assert first.relevance_score > second.relevance_score


def test_mesh_variant_preserves_boolean_constraints_and_entity_boundaries():
    from pubmed_search.application.search.result_aggregator import RankingConfig, ResultAggregator
    from pubmed_search.application.search.semantic_enhancer import ResolvedEntity, SemanticEnhancer

    entities = [ResolvedEntity(word, word.title(), "chemical", word, mesh_id="D1") for word in ("aspirin", "stroke")]
    query = SemanticEnhancer(entity_resolver=None)._build_mesh_query("aspirin AND stroke", entities)
    assert "(aspirin AND stroke)" in query
    score = ResultAggregator()._calculate_entity_match(
        article("1", "Therapy for trauma"), RankingConfig(matched_entities=["RA"])
    )
    assert score == 0.3
