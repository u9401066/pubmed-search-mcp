"""
Tests for ranking_algorithms.py — BM25, RRF, MMR, Source Disagreement.

Covers:
- BM25 corpus construction, scoring, normalization, field boosting
- RRF fusion across multiple dimensions
- MMR diversification
- Source Disagreement Analysis
- Edge cases (empty inputs, single articles, etc.)
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest

from pubmed_search.application.search.ranking_algorithms import (
    BM25Corpus,
    MMRResult,
    RRFResult,
    SourceDisagreement,
    _article_key,
    _average_pairwise_distance,
    _extract_article_terms,
    _jaccard_similarity,
    analyze_source_disagreement,
    bm25_score,
    bm25_score_normalized,
    mmr_diversify,
    reciprocal_rank_fusion,
)


# =============================================================================
# Fixtures
# =============================================================================


def _make_article(
    title: str = "Test Article",
    pmid: str | None = None,
    doi: str | None = None,
    abstract: str | None = None,
    keywords: list[str] | None = None,
    mesh_terms: list[str] | None = None,
    primary_source: str = "pubmed",
    sources: list | None = None,
    ranking_score: float | None = None,
):
    """Create a mock UnifiedArticle for testing."""
    article = MagicMock()
    article.title = title
    article.pmid = pmid
    article.doi = doi
    article.abstract = abstract
    article.keywords = keywords or []
    article.mesh_terms = mesh_terms or []
    article.primary_source = primary_source
    article.ranking_score = ranking_score

    # Simulate source metadata
    if sources:
        source_metas = []
        for s in sources:
            sm = MagicMock()
            sm.source = s
            source_metas.append(sm)
        article.sources = source_metas
    else:
        sm = MagicMock()
        sm.source = primary_source
        article.sources = [sm]

    return article


@pytest.fixture
def sample_articles():
    """3 articles with different topics for testing."""
    return [
        _make_article(
            title="Machine Learning in Radiology",
            pmid="111",
            abstract="Deep learning models improve diagnostic accuracy in radiology imaging analysis",
            keywords=["machine learning", "radiology", "deep learning"],
            mesh_terms=["Machine Learning", "Radiology"],
        ),
        _make_article(
            title="Natural Language Processing for Clinical Notes",
            pmid="222",
            abstract="NLP techniques extract structured information from unstructured clinical notes",
            keywords=["NLP", "clinical notes", "text mining"],
            mesh_terms=["Natural Language Processing", "Electronic Health Records"],
        ),
        _make_article(
            title="Machine Learning for Drug Discovery",
            pmid="333",
            abstract="Machine learning approaches accelerate drug discovery and molecular design",
            keywords=["machine learning", "drug discovery"],
            mesh_terms=["Machine Learning", "Drug Discovery"],
        ),
    ]


# =============================================================================
# BM25 Tests
# =============================================================================


class TestBM25Corpus:
    """Tests for BM25 corpus construction."""

    def test_from_articles_basic(self, sample_articles):
        corpus = BM25Corpus.from_articles(sample_articles)
        assert corpus.total_docs == 3
        assert corpus.avg_doc_length > 0

    def test_from_articles_doc_freq(self, sample_articles):
        corpus = BM25Corpus.from_articles(sample_articles)
        # "machine" appears in 2 of 3 articles (articles 1 and 3)
        assert corpus.doc_freq.get("machine", 0) == 2
        # "learning" appears in 2 of 3 articles
        assert corpus.doc_freq.get("learning", 0) == 2

    def test_from_articles_empty(self):
        corpus = BM25Corpus.from_articles([])
        assert corpus.total_docs == 0
        assert corpus.avg_doc_length == 0.0
        assert corpus.doc_freq == {}

    def test_from_articles_single(self):
        article = _make_article(title="Test", abstract="Simple test article")
        corpus = BM25Corpus.from_articles([article])
        assert corpus.total_docs == 1
        assert corpus.avg_doc_length > 0


class TestExtractArticleTerms:
    """Tests for term extraction."""

    def test_extracts_title(self):
        article = _make_article(title="Machine Learning Review")
        terms = _extract_article_terms(article)
        assert "machine" in terms
        assert "learning" in terms
        assert "review" in terms

    def test_extracts_abstract(self):
        article = _make_article(title="X", abstract="Deep neural network architecture")
        terms = _extract_article_terms(article)
        assert "deep" in terms
        assert "neural" in terms
        assert "network" in terms

    def test_extracts_keywords(self):
        article = _make_article(title="X", keywords=["artificial intelligence"])
        terms = _extract_article_terms(article)
        assert "artificial" in terms
        assert "intelligence" in terms

    def test_extracts_mesh(self):
        article = _make_article(title="X", mesh_terms=["Machine Learning"])
        terms = _extract_article_terms(article)
        assert "machine" in terms
        assert "learning" in terms

    def test_filters_short_terms(self):
        article = _make_article(title="A B CD EFG HIJK")
        terms = _extract_article_terms(article)
        # Only terms >= 3 chars should be included
        assert "efg" in terms
        assert "hijk" in terms
        assert "a" not in terms
        assert "b" not in terms
        assert "cd" not in terms

    def test_empty_article(self):
        article = _make_article(title=None, abstract=None)
        article.title = None
        terms = _extract_article_terms(article)
        assert terms == []


class TestBM25Score:
    """Tests for BM25 scoring."""

    def test_relevant_article_higher_score(self, sample_articles):
        corpus = BM25Corpus.from_articles(sample_articles)
        # "machine learning" query should score higher for ML articles
        ml_score = bm25_score(sample_articles[0], "machine learning", corpus)
        nlp_score = bm25_score(sample_articles[1], "machine learning", corpus)
        assert ml_score > nlp_score

    def test_zero_on_empty_query(self, sample_articles):
        corpus = BM25Corpus.from_articles(sample_articles)
        score = bm25_score(sample_articles[0], "", corpus)
        assert score == 0.0

    def test_zero_on_empty_corpus(self, sample_articles):
        empty_corpus = BM25Corpus()
        score = bm25_score(sample_articles[0], "machine learning", empty_corpus)
        assert score == 0.0

    def test_title_boost(self):
        # Article with query term in title should score higher
        titled = _make_article(title="Machine Learning Study", abstract="This is a study")
        not_titled = _make_article(title="A Study", abstract="Machine learning is discussed here")
        corpus = BM25Corpus.from_articles([titled, not_titled])

        score_titled = bm25_score(titled, "machine", corpus)
        score_not = bm25_score(not_titled, "machine", corpus)
        assert score_titled > score_not

    def test_mesh_boost(self):
        # Article with query term in MeSH should score higher than abstract only
        meshed = _make_article(title="Study", abstract="General study", mesh_terms=["Radiology"])
        unmes = _make_article(title="Study", abstract="Radiology imaging discussed")
        corpus = BM25Corpus.from_articles([meshed, unmes])

        score_m = bm25_score(meshed, "radiology", corpus)
        score_u = bm25_score(unmes, "radiology", corpus)
        assert score_m > score_u

    def test_non_negative_score(self, sample_articles):
        corpus = BM25Corpus.from_articles(sample_articles)
        for article in sample_articles:
            score = bm25_score(article, "machine learning radiology", corpus)
            assert score >= 0.0

    def test_score_increases_with_tf(self):
        # More occurrences → higher score (with saturation)
        few = _make_article(title="Test", abstract="cancer treatment")
        many = _make_article(title="Test", abstract="cancer cancer cancer treatment treatment")
        corpus = BM25Corpus.from_articles([few, many])

        score_few = bm25_score(few, "cancer", corpus)
        score_many = bm25_score(many, "cancer", corpus)
        assert score_many > score_few


class TestBM25Normalized:
    """Tests for BM25 normalized scoring."""

    def test_normalized_range(self, sample_articles):
        corpus = BM25Corpus.from_articles(sample_articles)
        # compute max first
        scores = [bm25_score(a, "machine learning", corpus) for a in sample_articles]
        max_score = max(scores)
        for article in sample_articles:
            norm = bm25_score_normalized(article, "machine learning", corpus, max_score)
            assert 0.0 <= norm <= 1.0

    def test_max_article_gets_1(self, sample_articles):
        corpus = BM25Corpus.from_articles(sample_articles)
        scores = [bm25_score(a, "machine learning", corpus) for a in sample_articles]
        max_score = max(scores)
        max_idx = scores.index(max_score)
        norm = bm25_score_normalized(sample_articles[max_idx], "machine learning", corpus, max_score)
        assert norm == pytest.approx(1.0)

    def test_zero_max_returns_neutral(self, sample_articles):
        corpus = BM25Corpus.from_articles(sample_articles)
        norm = bm25_score_normalized(sample_articles[0], "xyz", corpus, 0.0)
        assert norm == 0.5  # Neutral fallback


# =============================================================================
# RRF Tests
# =============================================================================


class TestReciprocalRankFusion:
    """Tests for Reciprocal Rank Fusion."""

    def test_basic_fusion(self, sample_articles):
        # Consistent ranking across dimensions → highest RRF
        dim_rankings = {
            "relevance": ["pmid:111", "pmid:222", "pmid:333"],
            "citations": ["pmid:111", "pmid:333", "pmid:222"],
        }
        result = reciprocal_rank_fusion(sample_articles, dim_rankings)
        assert isinstance(result, RRFResult)
        assert len(result.ranked_articles) == 3
        # Article 111 is top in both → should be first
        assert result.ranked_articles[0].pmid == "111"

    def test_rrf_scores_positive(self, sample_articles):
        dim_rankings = {
            "dim1": ["pmid:111", "pmid:222", "pmid:333"],
        }
        result = reciprocal_rank_fusion(sample_articles, dim_rankings)
        for key, score in result.rrf_scores.items():
            assert score > 0

    def test_rrf_dimension_contributions(self, sample_articles):
        dim_rankings = {
            "dim1": ["pmid:111", "pmid:222", "pmid:333"],
            "dim2": ["pmid:333", "pmid:111", "pmid:222"],
        }
        result = reciprocal_rank_fusion(sample_articles, dim_rankings)
        # Each article should have contributions from both dimensions
        for key, contribs in result.dimension_contributions.items():
            assert "dim1" in contribs
            assert "dim2" in contribs

    def test_single_dimension(self, sample_articles):
        dim_rankings = {
            "relevance": ["pmid:111", "pmid:222", "pmid:333"],
        }
        result = reciprocal_rank_fusion(sample_articles, dim_rankings)
        assert result.ranked_articles[0].pmid == "111"

    def test_empty_articles(self):
        result = reciprocal_rank_fusion([], {})
        assert result.ranked_articles == []
        assert result.rrf_scores == {}

    def test_missing_rank_gets_worst(self, sample_articles):
        # Article 333 not in dim1 ranking → gets worst rank
        dim_rankings = {
            "dim1": ["pmid:111", "pmid:222"],  # 333 missing
        }
        result = reciprocal_rank_fusion(sample_articles, dim_rankings)
        # 333 should be last
        assert result.ranked_articles[-1].pmid == "333"

    def test_custom_k(self, sample_articles):
        dim_rankings = {
            "dim1": ["pmid:111", "pmid:222", "pmid:333"],
        }
        result_default = reciprocal_rank_fusion(sample_articles, dim_rankings, k=60)
        result_small_k = reciprocal_rank_fusion(sample_articles, dim_rankings, k=1)
        # Smaller k amplifies rank differences
        default_diff = abs(
            result_default.rrf_scores["pmid:111"] - result_default.rrf_scores["pmid:333"]
        )
        small_k_diff = abs(
            result_small_k.rrf_scores["pmid:111"] - result_small_k.rrf_scores["pmid:333"]
        )
        assert small_k_diff > default_diff


# =============================================================================
# MMR Tests
# =============================================================================


class TestMMRDiversify:
    """Tests for Maximal Marginal Relevance."""

    def test_basic_diversification(self, sample_articles):
        result = mmr_diversify(sample_articles, "machine learning")
        assert isinstance(result, MMRResult)
        assert len(result.articles) == 3

    def test_diversity_scores_populated(self, sample_articles):
        result = mmr_diversify(sample_articles, "machine learning")
        assert len(result.diversity_scores) == 3

    def test_pairwise_distance_positive(self, sample_articles):
        result = mmr_diversify(sample_articles, "machine learning")
        assert result.avg_pairwise_distance >= 0.0
        assert result.avg_pairwise_distance <= 1.0

    def test_top_k_limits_results(self, sample_articles):
        result = mmr_diversify(sample_articles, "machine learning", top_k=2)
        assert len(result.articles) == 2

    def test_lambda_1_is_pure_relevance(self, sample_articles):
        """λ=1.0 should be pure relevance (no diversity consideration)."""
        result = mmr_diversify(sample_articles, "machine learning", lambda_param=1.0)
        # First should be the most relevant to "machine learning"
        assert len(result.articles) == 3

    def test_lambda_0_is_pure_diversity(self, sample_articles):
        """λ=0.0 should maximize diversity between selected articles."""
        result = mmr_diversify(sample_articles, "irrelevant query xyz", lambda_param=0.0)
        assert len(result.articles) == 3

    def test_single_article(self):
        article = _make_article(title="Only Article", pmid="1")
        result = mmr_diversify([article], "anything")
        assert len(result.articles) == 1

    def test_empty_articles(self):
        result = mmr_diversify([], "anything")
        assert result.articles == []
        assert result.avg_pairwise_distance == 1.0

    def test_similar_articles_get_reordered(self):
        """Two very similar articles should not be adjacent after MMR with low λ."""
        a1 = _make_article(
            title="Machine Learning in Radiology Imaging",
            pmid="1",
            keywords=["machine learning", "radiology"],
            mesh_terms=["Machine Learning", "Radiology"],
            ranking_score=1.0,
        )
        a2 = _make_article(
            title="Machine Learning in Radiology Diagnosis",
            pmid="2",
            keywords=["machine learning", "radiology"],
            mesh_terms=["Machine Learning", "Radiology"],
            ranking_score=0.9,
        )
        a3 = _make_article(
            title="Natural Language Processing Text Mining",
            pmid="3",
            keywords=["NLP", "text mining"],
            mesh_terms=["Natural Language Processing"],
            ranking_score=0.8,
        )
        articles = [a1, a2, a3]
        result = mmr_diversify(articles, "machine learning radiology", lambda_param=0.3)
        # With low λ, the NLP article (diverse) should come before second ML article
        pmid_order = [a.pmid for a in result.articles]
        # a1 first (most relevant), then a3 should come before a2 (diversity)
        assert pmid_order[0] == "1"
        # a3 should be selected before a2 due to diversity
        assert pmid_order.index("3") < pmid_order.index("2")


# =============================================================================
# Source Disagreement Tests
# =============================================================================


class TestSourceDisagreement:
    """Tests for Source Disagreement Analysis."""

    def test_single_source_perfect_agreement(self):
        articles = [
            _make_article(pmid="1", sources=["pubmed"]),
            _make_article(pmid="2", sources=["pubmed"]),
        ]
        result = analyze_source_disagreement(articles)
        assert isinstance(result, SourceDisagreement)
        assert result.source_agreement_score == 1.0  # Trivially 1 for single source
        assert result.cross_source_articles == 0
        assert result.single_source_articles == 2

    def test_multi_source_agreement(self):
        articles = [
            _make_article(pmid="1", sources=["pubmed", "openalex"]),
            _make_article(pmid="2", sources=["pubmed", "openalex"]),
        ]
        result = analyze_source_disagreement(articles)
        assert result.cross_source_articles == 2
        assert result.single_source_articles == 0
        assert result.source_agreement_score > 0.5

    def test_zero_overlap_disagreement(self):
        articles = [
            _make_article(pmid="1", sources=["pubmed"], primary_source="pubmed"),
            _make_article(pmid="2", sources=["openalex"], primary_source="openalex"),
        ]
        result = analyze_source_disagreement(articles)
        # No articles shared → max complementarity
        assert result.source_complementarity == 1.0
        assert result.source_agreement_score == 0.0
        assert result.cross_source_articles == 0
        assert result.single_source_articles == 2

    def test_per_source_unique_count(self):
        articles = [
            _make_article(pmid="1", sources=["pubmed"], primary_source="pubmed"),
            _make_article(pmid="2", sources=["pubmed", "openalex"], primary_source="pubmed"),
            _make_article(pmid="3", sources=["openalex"], primary_source="openalex"),
        ]
        result = analyze_source_disagreement(articles)
        assert result.per_source_unique["pubmed"] == 1
        assert result.per_source_unique["openalex"] == 1

    def test_rank_correlation_pairs(self):
        articles = [
            _make_article(pmid="1", sources=["pubmed", "openalex"]),
            _make_article(pmid="2", sources=["pubmed"]),
            _make_article(pmid="3", sources=["openalex"]),
        ]
        result = analyze_source_disagreement(articles)
        assert "openalex↔pubmed" in result.rank_correlation or "pubmed↔openalex" in result.rank_correlation

    def test_empty_articles(self):
        result = analyze_source_disagreement([])
        assert result.source_agreement_score == 1.0
        assert result.cross_source_articles == 0

    def test_to_dict(self):
        articles = [
            _make_article(pmid="1", sources=["pubmed", "openalex"]),
            _make_article(pmid="2", sources=["pubmed"]),
        ]
        result = analyze_source_disagreement(articles)
        d = result.to_dict()
        assert "source_agreement_score" in d
        assert "source_complementarity" in d
        assert "per_source_unique" in d
        assert "rank_correlation" in d
        assert isinstance(d["source_agreement_score"], float)

    def test_three_sources(self):
        articles = [
            _make_article(pmid="1", sources=["pubmed", "openalex", "core"]),
            _make_article(pmid="2", sources=["pubmed"]),
            _make_article(pmid="3", sources=["openalex", "core"]),
            _make_article(pmid="4", sources=["core"]),
        ]
        result = analyze_source_disagreement(articles)
        # Should have 3 pairwise correlations: core↔openalex, core↔pubmed, openalex↔pubmed
        assert len(result.rank_correlation) == 3
        assert result.cross_source_articles >= 2  # articles 1 and 3


# =============================================================================
# Utility Function Tests
# =============================================================================


class TestArticleKey:
    """Tests for _article_key."""

    def test_pmid_key(self):
        article = _make_article(pmid="12345")
        assert _article_key(article) == "pmid:12345"

    def test_doi_key(self):
        article = _make_article(doi="10.1234/test")
        assert _article_key(article) == "doi:10.1234/test"

    def test_title_hash_key(self):
        article = _make_article(title="Unique Title")
        key = _article_key(article)
        assert key.startswith("title:")


class TestJaccardSimilarity:
    """Tests for Jaccard similarity."""

    def test_identical_sets(self):
        assert _jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self):
        assert _jaccard_similarity({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial_overlap(self):
        # {a,b,c} ∩ {b,c,d} = {b,c}, |union| = {a,b,c,d} = 4
        assert _jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"}) == pytest.approx(0.5)

    def test_empty_sets(self):
        assert _jaccard_similarity(set(), set()) == 0.0

    def test_one_empty(self):
        assert _jaccard_similarity({"a"}, set()) == 0.0


class TestAveragePairwiseDistance:
    """Tests for average pairwise distance."""

    def test_identical_sets(self):
        sets = [{"a", "b"}, {"a", "b"}]
        assert _average_pairwise_distance(sets) == 0.0  # Distance=0 for identical

    def test_disjoint_sets(self):
        sets = [{"a"}, {"b"}]
        assert _average_pairwise_distance(sets) == 1.0

    def test_single_set(self):
        assert _average_pairwise_distance([{"a"}]) == 1.0  # Trivial

    def test_empty_list(self):
        assert _average_pairwise_distance([]) == 1.0
