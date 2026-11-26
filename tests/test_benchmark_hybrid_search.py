"""Scoring and reporting of the hybrid-search benchmark, without provider calls."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from scripts.benchmark_hybrid_search import (
    DEFAULT_TOPICS,
    primary_study_pmids,
    ranking_ids,
    run_topic,
    score,
    summarize,
    to_markdown,
)

from pubmed_search.application.search.query_dialect import neutralize_pubmed_query
from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.domain.entities.article import ChannelHit, UnifiedArticle


def test_gold_keeps_primary_studies_published_before_the_review() -> None:
    references = [
        {"pmid": "1", "publication_types": ["Randomized Controlled Trial"], "year": "2019"},
        {"pmid": "2", "publication_types": ["Journal Article", "Review"], "year": "2018"},
        {"pmid": "3", "publication_types": ["Meta-Analysis"], "year": "2017"},
        {"pmid": "4", "publication_types": ["Journal Article"], "year": "2025"},
        {"pmid": "5", "publication_types": [], "year": ""},
        {"pmid": "1", "publication_types": ["Journal Article"], "year": "2019"},
    ]

    assert primary_study_pmids(references, max_year=2020) == ["1", "5"]


def test_ranking_ids_drop_the_review_and_duplicates() -> None:
    records = [{"pmid": "9"}, {"pmid": "1"}, {"pmid": "", "doi": "10.1/x"}, {"pmid": "1"}, {}]

    assert ranking_ids(records, exclude="9") == ["1", "doi:10.1/x", "unidentified:4"]


def test_score_counts_recall_against_all_gold() -> None:
    metrics = score(["1", "x", "2"], ["1", "2", "3", "4"])

    assert metrics["recall@10"] == 0.5
    assert metrics["gold_found"] == 2.0


def test_shipped_topics_are_well_formed_and_translate_for_neutral_channels() -> None:
    topics = json.loads(DEFAULT_TOPICS.read_text(encoding="utf-8"))["topics"]

    assert len({topic["id"] for topic in topics}) == len(topics) >= 6
    for topic in topics:
        assert topic["review_pmid"].isdigit()
        neutral = neutralize_pubmed_query(topic["pubmed_query"])
        assert neutral.boolean and "[" not in neutral.boolean
        assert neutral.boolean.count("(") == neutral.boolean.count(")")


class _Searcher:
    async def get_article_references(self, _pmid: str, limit: int = 20) -> list[dict[str, Any]]:
        return [{"pmid": str(n), "publication_types": ["Clinical Trial"], "year": "2019"} for n in range(1, 7)]


class _Client:
    """Client double: PubMed finds gold 1-2; hybrid adds gold 3 from a breadth-only channel."""

    searcher = _Searcher()

    async def search_pubmed_page(self, query: str, **_kwargs: Any) -> SourceSearchPage[dict[str, Any]]:
        return SourceSearchPage(
            source="pubmed", items=[{"pmid": "1"}, {"pmid": "2"}, {"pmid": "99"}], total=3, query=query
        )

    async def unified_search(self, _query: str, *, options: str, **_kwargs: Any) -> Any:
        articles = [UnifiedArticle(title="a", primary_source="pubmed", pmid=pmid) for pmid in ("1", "2")]
        hybrid = None
        if "hybrid" in options:
            for rank, article in enumerate(articles, 1):
                article.channels = [ChannelHit("pubmed", rank)]
            extra = UnifiedArticle(title="b", primary_source="europe_pmc", pmid="3")
            extra.channels = [ChannelHit("europe_pmc", 1)]
            articles.append(extra)
            hybrid = {"channels": {"pubmed": 2, "europe_pmc": 1}}
        return SimpleNamespace(articles=tuple(articles), source_counts=(), source_errors=(), hybrid=hybrid)


async def test_topic_run_scores_every_arm_and_credits_breadth_only_gold(monkeypatch: Any) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("scripts.benchmark_hybrid_search.asyncio.sleep", no_sleep)
    topic = {"id": "t", "review_pmid": "99", "max_year": 2020, "question": "q", "pubmed_query": "q[tiab]"}

    row = await run_topic(_Client(), topic)  # type: ignore[arg-type]

    assert row["gold"] == ["1", "2", "3", "4", "5", "6"]
    assert row["arms"]["mesh:pubmed"]["ranked"] == ["1", "2"]  # the review (99) is removed
    assert row["arms"]["mesh:hybrid"]["metrics"]["gold_found"] == 3.0
    assert row["arms"]["mesh:hybrid"]["metrics"]["gold_found_breadth_only"] == 1.0

    summary = summarize([row])
    assert summary["mesh:hybrid"]["recall@10"] == 0.5
    assert summary["mesh:pubmed"]["recall@10"] == round(2 / 6, 4)
    report = {"topics_total": 1, "topics_scored": 1, "summary": summary, "topics": [row]}
    assert "| mesh | hybrid | 0.500 |" in to_markdown(report)


def test_incomplete_topics_are_left_out_of_the_mean() -> None:
    assert summarize([{"id": "t", "gold": ["1"], "arms": {}, "skipped": "only 1"}]) == {}
