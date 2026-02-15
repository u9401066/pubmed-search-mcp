"""
Tests for reproducibility.py — Reproducibility Score calculation.

Covers:
- Overall score composition
- Grade system (A-F)
- Query formality scoring (MeSH, Boolean, field tags)
- Source coverage scoring
- Result stability scoring
- Audit completeness scoring
- Edge cases
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pubmed_search.application.search.reproducibility import (
    ReproducibilityScore,
    _score_audit_completeness,
    _score_query_formality,
    _score_result_stability,
    _score_source_coverage,
    calculate_reproducibility,
)


# =============================================================================
# Fixtures
# =============================================================================


def _make_article(
    pmid: str = "1",
    sources: list[str] | None = None,
):
    """Create a mock article for testing."""
    article = MagicMock()
    article.pmid = pmid

    if sources:
        source_metas = []
        for s in sources:
            sm = MagicMock()
            sm.source = s
            source_metas.append(sm)
        article.sources = source_metas
    else:
        article.sources = []

    return article


# =============================================================================
# Overall Score Tests
# =============================================================================


class TestCalculateReproducibility:
    """Tests for the main calculate_reproducibility function."""

    def test_basic_calculation(self):
        articles = [_make_article("1"), _make_article("2")]
        result = calculate_reproducibility(
            query="cancer treatment",
            sources_queried=["pubmed"],
            sources_responded=["pubmed"],
            articles=articles,
        )
        assert isinstance(result, ReproducibilityScore)
        assert 0.0 <= result.overall_score <= 1.0

    def test_deterministic_by_default(self):
        result = calculate_reproducibility(
            query="test",
            sources_queried=["pubmed"],
            sources_responded=["pubmed"],
            articles=[],
        )
        assert result.deterministic is True

    def test_not_deterministic_with_llm(self):
        result = calculate_reproducibility(
            query="test",
            sources_queried=["pubmed"],
            sources_responded=["pubmed"],
            articles=[],
            used_llm=True,
        )
        assert result.deterministic is False
        # LLM usage should significantly reduce score
        result_no_llm = calculate_reproducibility(
            query="test",
            sources_queried=["pubmed"],
            sources_responded=["pubmed"],
            articles=[],
            used_llm=False,
        )
        assert result.overall_score < result_no_llm.overall_score

    def test_not_deterministic_with_sampling(self):
        result = calculate_reproducibility(
            query="test",
            sources_queried=["pubmed"],
            sources_responded=["pubmed"],
            articles=[],
            used_sampling=True,
        )
        assert result.deterministic is False

    def test_mesh_query_higher_score(self):
        mesh_result = calculate_reproducibility(
            query='"Machine Learning"[MeSH] AND "Neoplasms"[MeSH]',
            sources_queried=["pubmed"],
            sources_responded=["pubmed"],
            articles=[_make_article()],
        )
        free_result = calculate_reproducibility(
            query="machine learning cancer",
            sources_queried=["pubmed"],
            sources_responded=["pubmed"],
            articles=[_make_article()],
        )
        assert mesh_result.overall_score > free_result.overall_score

    def test_all_sources_responded_higher(self):
        all_responded = calculate_reproducibility(
            query="test",
            sources_queried=["pubmed", "openalex", "core"],
            sources_responded=["pubmed", "openalex", "core"],
            articles=[_make_article()],
        )
        partial_responded = calculate_reproducibility(
            query="test",
            sources_queried=["pubmed", "openalex", "core"],
            sources_responded=["pubmed"],
            articles=[_make_article()],
        )
        assert all_responded.overall_score > partial_responded.overall_score

    def test_sources_failed_tracked(self):
        result = calculate_reproducibility(
            query="test",
            sources_queried=["pubmed", "openalex", "core"],
            sources_responded=["pubmed"],
            articles=[],
        )
        assert set(result.sources_failed) == {"openalex", "core"}

    def test_to_dict(self):
        result = calculate_reproducibility(
            query="test query [MeSH]",
            sources_queried=["pubmed"],
            sources_responded=["pubmed"],
            articles=[_make_article()],
        )
        d = result.to_dict()
        assert "overall_score" in d
        assert "deterministic" in d
        assert "query_formality" in d
        assert "source_coverage" in d
        assert "result_stability" in d
        assert "audit_completeness" in d
        assert "query_features" in d
        assert isinstance(d["overall_score"], float)


# =============================================================================
# Grade Tests
# =============================================================================


class TestGrade:
    """Tests for the grade property."""

    def test_grade_a(self):
        score = ReproducibilityScore(
            deterministic=True,
            query_formality=1.0,
            source_coverage=1.0,
            result_stability=1.0,
            audit_completeness=1.0,
            overall_score=0.95,
        )
        assert score.grade == "A"

    def test_grade_b(self):
        score = ReproducibilityScore(
            deterministic=True,
            query_formality=0.8,
            source_coverage=0.8,
            result_stability=0.8,
            audit_completeness=0.8,
            overall_score=0.85,
        )
        assert score.grade == "B"

    def test_grade_c(self):
        score = ReproducibilityScore(
            deterministic=True,
            query_formality=0.5,
            source_coverage=0.5,
            result_stability=0.5,
            audit_completeness=0.5,
            overall_score=0.65,
        )
        assert score.grade == "C"

    def test_grade_d(self):
        score = ReproducibilityScore(
            deterministic=False,
            query_formality=0.3,
            source_coverage=0.3,
            result_stability=0.3,
            audit_completeness=0.3,
            overall_score=0.45,
        )
        assert score.grade == "D"

    def test_grade_f(self):
        score = ReproducibilityScore(
            deterministic=False,
            query_formality=0.1,
            source_coverage=0.1,
            result_stability=0.1,
            audit_completeness=0.1,
            overall_score=0.2,
        )
        assert score.grade == "F"


# =============================================================================
# Component Score Tests
# =============================================================================


class TestQueryFormality:
    """Tests for query formality scoring."""

    def test_plain_text_base_score(self):
        score, features = _score_query_formality("cancer treatment")
        assert score == pytest.approx(0.3)  # Base only
        assert features["has_mesh_tags"] is False
        assert features["has_boolean_operators"] is False

    def test_mesh_boost(self):
        score, features = _score_query_formality('"Neoplasms"[MeSH Terms]')
        assert features["has_mesh_tags"] is True
        assert score > 0.5

    def test_boolean_boost(self):
        score, features = _score_query_formality("cancer AND treatment")
        assert features["has_boolean_operators"] is True
        assert score > 0.3

    def test_quoted_phrases(self):
        score, features = _score_query_formality('"cancer treatment"')
        assert features["has_quoted_phrases"] is True
        assert score > 0.3

    def test_field_tags(self):
        score, features = _score_query_formality("cancer[ti]")
        assert features["has_field_tags"] is True
        assert score > 0.3

    def test_max_formality(self):
        query = '"Neoplasms"[MeSH Terms] AND "Drug Therapy"[MeSH] AND "2023"[dp]'
        score, features = _score_query_formality(query)
        assert score == pytest.approx(1.0)  # Capped at 1.0
        assert features["has_mesh_tags"] is True
        assert features["has_boolean_operators"] is True
        assert features["has_date_restriction"] is True

    def test_tiab_tag(self):
        score, features = _score_query_formality("cancer[tiab]")
        assert features["has_mesh_tags"] is True  # [tiab] is a recognized field tag


class TestSourceCoverage:
    """Tests for source coverage scoring."""

    def test_full_coverage(self):
        score = _score_source_coverage(["pubmed"], ["pubmed"])
        assert score >= 1.0  # 100% + diversity bonus possible

    def test_partial_coverage(self):
        score = _score_source_coverage(
            ["pubmed", "openalex", "core"],
            ["pubmed"],
        )
        assert score < 0.5  # Only 1/3 responded

    def test_no_sources(self):
        score = _score_source_coverage([], [])
        assert score == 0.5  # Unknown

    def test_more_sources_is_better(self):
        few = _score_source_coverage(["pubmed"], ["pubmed"])
        many = _score_source_coverage(
            ["pubmed", "openalex", "core", "europe_pmc"],
            ["pubmed", "openalex", "core", "europe_pmc"],
        )
        assert many >= few  # Diversity bonus


class TestResultStability:
    """Tests for result stability scoring."""

    def test_pubmed_most_stable(self):
        stable = _score_result_stability(["pubmed"], [])
        less_stable = _score_result_stability(["core"], [])
        assert stable > less_stable

    def test_multi_source_verification(self):
        articles_single = [_make_article("1", sources=["pubmed"])]
        articles_multi = [_make_article("1", sources=["pubmed", "openalex"])]

        score_single = _score_result_stability(["pubmed", "openalex"], articles_single)
        score_multi = _score_result_stability(["pubmed", "openalex"], articles_multi)
        assert score_multi > score_single

    def test_no_sources(self):
        score = _score_result_stability([], [])
        assert score == 0.5


class TestAuditCompleteness:
    """Tests for audit completeness scoring."""

    def test_full_audit(self):
        score = _score_audit_completeness(
            has_audit_trail=True,
            has_dedup_stats=True,
            has_source_counts=True,
            has_query_analysis=True,
            has_results=True,
        )
        assert score == pytest.approx(1.0)

    def test_no_audit(self):
        score = _score_audit_completeness(
            has_audit_trail=False,
            has_dedup_stats=False,
            has_source_counts=False,
            has_query_analysis=False,
            has_results=False,
        )
        assert score == pytest.approx(0.0)

    def test_partial_audit(self):
        score = _score_audit_completeness(
            has_audit_trail=True,
            has_dedup_stats=True,
            has_source_counts=False,
            has_query_analysis=False,
            has_results=True,
        )
        assert 0.0 < score < 1.0
