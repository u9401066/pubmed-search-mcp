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
