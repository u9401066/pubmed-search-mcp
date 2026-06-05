"""Regression guards for low-risk internal performance optimizations."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from pubmed_search.application.pipeline.executor import PipelineExecutor
from pubmed_search.application.search.query_analyzer import AnalyzedQuery, QueryIntent
from pubmed_search.application.search.result_aggregator import AggregationStats, RankingConfig, ResultAggregator
from pubmed_search.application.session.manager import ArticleCache
from pubmed_search.domain.entities.article import OpenAccessLink, SourceMetadata, UnifiedArticle
from pubmed_search.presentation.mcp_server.tools.unified_formatting import _format_as_json
from pubmed_search.shared.cache_substrate import JsonFileCacheBackend

if TYPE_CHECKING:
    from pathlib import Path


class CountingJsonFileCacheBackend(JsonFileCacheBackend):
    """JSON backend that exposes how many physical saves were requested."""

    def __init__(self, file_path: str | Path):
        self.save_calls = 0
        super().__init__(file_path)

    def _save(self) -> None:
        self.save_calls += 1
        super()._save()


class CountingList(list):
    """List that lets tests detect quadratic membership probes."""

    def __init__(self, values: list[str]):
        super().__init__(values)
        self.contains_calls = 0

    def __contains__(self, item: object) -> bool:
        self.contains_calls += 1
        return super().__contains__(item)


class CountingArticle(UnifiedArticle):
    """UnifiedArticle variant that counts heavyweight serialization."""

    def to_dict(self) -> dict[str, Any]:
        self.to_dict_calls = getattr(self, "to_dict_calls", 0) + 1
        return super().to_dict()


def _analysis() -> AnalyzedQuery:
    analysis = MagicMock(spec=AnalyzedQuery)
    analysis.original_query = "test"
    analysis.intent = QueryIntent.EXPLORATION
    analysis.to_dict.return_value = {"query": "test"}
    return analysis


def _stats(unique_articles: int = 1) -> AggregationStats:
    stats = MagicMock(spec=AggregationStats)
    stats.to_dict.return_value = {"unique_articles": unique_articles}
    stats.by_source = {"pubmed": unique_articles}
    stats.unique_articles = unique_articles
    return stats


def test_bm25_ranking_skips_heuristic_relevance_when_bm25_replaces_it() -> None:
    class CountingAggregator(ResultAggregator):
        def __init__(self) -> None:
            super().__init__()
            self.relevance_calls = 0

        def _calculate_relevance(self, article: UnifiedArticle, query: str | None) -> float:
            self.relevance_calls += 1
            return super()._calculate_relevance(article, query)

    articles = [
        UnifiedArticle(title="Remimazolam ICU sedation", primary_source="pubmed", pmid="1", abstract="ICU sedation"),
        UnifiedArticle(title="Propofol ICU sedation", primary_source="pubmed", pmid="2", abstract="ICU sedation"),
    ]
    config = RankingConfig(use_bm25=True, use_rrf=False, use_mmr=False)
    aggregator = CountingAggregator()

    aggregator.rank(articles, config=config, query="ICU sedation")

    assert aggregator.relevance_calls == 0


def test_article_cache_put_many_persists_json_backend_once(tmp_path: Path) -> None:
    backend = CountingJsonFileCacheBackend(tmp_path / "article_cache.json")
    cache = ArticleCache(backend=backend)

    warmed = cache.put_many(
        [
            {"pmid": "1", "title": "One", "authors": [], "abstract": "", "journal": "", "year": "2024"},
            {"pmid": "2", "title": "Two", "authors": [], "abstract": "", "journal": "", "year": "2024"},
            {"pmid": "3", "title": "Three", "authors": [], "abstract": "", "journal": "", "year": "2024"},
        ]
    )

    assert warmed == 3
    assert backend.save_calls == 1
    assert cache.get("2").title == "Two"


def test_pipeline_article_type_maps_are_cached_and_read_only() -> None:
    first = PipelineExecutor._article_type_alias_map()
    second = PipelineExecutor._article_type_alias_map()

    assert first is second
    assert first["rct"] == "randomized-controlled-trial"
    with pytest.raises(TypeError):
        first["new-type"] = "review"  # type: ignore[index]


def test_merge_from_deduplicates_keywords_with_set_membership() -> None:
    keywords = CountingList(["alpha", "beta"])
    mesh_terms = CountingList(["mesh-alpha"])
    article = UnifiedArticle(
        title="A",
        primary_source="pubmed",
        keywords=keywords,
        mesh_terms=mesh_terms,
        sources=[SourceMetadata(source="pubmed")],
    )
    other = UnifiedArticle(
        title="A",
        primary_source="crossref",
        keywords=["beta", "gamma", "delta"],
        mesh_terms=["mesh-alpha", "mesh-beta"],
        sources=[SourceMetadata(source="pubmed"), SourceMetadata(source="crossref")],
    )

    article.merge_from(other)

    assert article.keywords == ["alpha", "beta", "gamma", "delta"]
    assert article.mesh_terms == ["mesh-alpha", "mesh-beta"]
    assert [source.source for source in article.sources] == ["pubmed", "crossref"]
    assert keywords.contains_calls == 0
    assert mesh_terms.contains_calls == 0


def test_to_dict_reads_best_oa_link_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    original = UnifiedArticle.best_oa_link

    def counted_best_oa_link(article: UnifiedArticle) -> OpenAccessLink | None:
        nonlocal calls
        calls += 1
        return original.fget(article)

    monkeypatch.setattr(UnifiedArticle, "best_oa_link", property(counted_best_oa_link))
    article = UnifiedArticle(
        title="OA",
        primary_source="pubmed",
        oa_links=[OpenAccessLink(url="https://example.org/fulltext.pdf", is_best=True)],
    )

    payload = article.to_dict()

    assert payload["open_access"]["best_link"] == "https://example.org/fulltext.pdf"
    assert calls == 1


def test_tiny_capped_json_output_does_not_serialize_every_article() -> None:
    articles = [
        CountingArticle(
            title=f"Article {index}",
            primary_source="pubmed",
            pmid=str(1000 + index),
            abstract="Heavy abstract " * 200,
        )
        for index in range(20)
    ]

    result = _format_as_json(
        articles,
        _analysis(),
        _stats(unique_articles=len(articles)),
        max_response_chars=800,
        include_next_tools=False,
    )

    parsed = json.loads(result)
    assert parsed["status"] == "truncated"
    assert sum(getattr(article, "to_dict_calls", 0) for article in articles) == 0
