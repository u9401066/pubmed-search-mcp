"""
Tests for Landmark Scorer - Multi-Signal Importance Scoring

Tests cover:
- LandmarkScore dataclass (tier, stars, to_dict)
- LandmarkScorer component computations (citation_impact, source_agreement, velocity)
- Batch scoring and sorting
- Edge cases (missing data, zero values, None metrics)
- Integration with milestone detection signals
"""

from __future__ import annotations

import math

import pytest

from pubmed_search.application.timeline.landmark_scorer import (
    EVIDENCE_LEVEL_SCORES,
    MAX_CITATIONS_FOR_NORMALIZATION,
    MAX_RCR_FOR_NORMALIZATION,
    MAX_VELOCITY_FOR_NORMALIZATION,
    SOURCE_AGREEMENT_SCORES,
    LandmarkScorer,
    evidence_level_to_score,
)
from pubmed_search.domain.entities.timeline import LandmarkScore

# =============================================================================
# LandmarkScore Dataclass Tests
# =============================================================================


class TestLandmarkScore:
    """Test the LandmarkScore dataclass."""

    def test_tier_landmark(self):
        score = LandmarkScore(overall=0.85)
        assert score.tier == "landmark"

    def test_tier_notable(self):
        score = LandmarkScore(overall=0.55)
        assert score.tier == "notable"

    def test_tier_minor(self):
        score = LandmarkScore(overall=0.30)
        assert score.tier == "minor"

    def test_tier_standard(self):
        score = LandmarkScore(overall=0.10)
        assert score.tier == "standard"

    def test_tier_boundary_landmark(self):
        score = LandmarkScore(overall=0.75)
        assert score.tier == "landmark"

    def test_tier_boundary_notable(self):
        score = LandmarkScore(overall=0.50)
        assert score.tier == "notable"

    def test_tier_boundary_minor(self):
        score = LandmarkScore(overall=0.25)
        assert score.tier == "minor"

    def test_stars_three(self):
        score = LandmarkScore(overall=0.80)
        assert "⭐" in score.stars
        assert score.stars.count("⭐") == 3

    def test_stars_two(self):
        score = LandmarkScore(overall=0.60)
        assert score.stars.count("⭐") == 2

    def test_stars_one(self):
        score = LandmarkScore(overall=0.30)
        assert score.stars.count("⭐") == 1

    def test_stars_none(self):
        score = LandmarkScore(overall=0.10)
        assert score.stars == ""

    def test_to_dict(self):
        score = LandmarkScore(
            overall=0.756,
            citation_impact=0.8123,
            source_agreement=0.5,
            milestone_confidence=0.9,
            evidence_quality=0.75,
            citation_velocity=0.6543,
        )
        d = score.to_dict()
        assert d["overall"] == 0.756
        assert d["tier"] == "landmark"
        assert d["citation_impact"] == 0.812
        assert d["citation_velocity"] == 0.654
        assert "source_agreement" in d
        assert "milestone_confidence" in d
        assert "evidence_quality" in d

    def test_frozen(self):
        score = LandmarkScore(overall=0.5)
        with pytest.raises(AttributeError):
            score.overall = 0.9  # type: ignore[misc]

    def test_default_components(self):
        score = LandmarkScore(overall=0.5)
        assert score.citation_impact == 0.0
        assert score.source_agreement == 0.0
        assert score.milestone_confidence == 0.0
        assert score.evidence_quality == 0.0
        assert score.citation_velocity == 0.0


# =============================================================================
# LandmarkScorer Tests
# =============================================================================


class TestLandmarkScorer:
    """Test the LandmarkScorer class."""

    @pytest.fixture()
    def scorer(self) -> LandmarkScorer:
        return LandmarkScorer()

    @pytest.fixture()
    def sample_article(self) -> dict:
        return {
            "pmid": "12345678",
            "title": "A study on drug X",
            "year": 2020,
            "citation_count": 150,
        }

    # ----- Initialization -----

    def test_default_weights(self, scorer: LandmarkScorer):
        """Default weights should sum to ~1.0."""
        total = sum(scorer.weights.values())
        assert abs(total - 1.0) < 0.001

    def test_custom_weights_normalized(self):
        """Custom weights should be normalized to sum to 1.0."""
        scorer = LandmarkScorer(weights={"citation_impact": 2, "source_agreement": 1})
        total = sum(scorer.weights.values())
        assert abs(total - 1.0) < 0.001
        assert abs(scorer.weights["citation_impact"] - 2 / 3) < 0.001

    # ----- Citation Impact -----

    def test_citation_impact_from_percentile(self, scorer: LandmarkScorer):
        """NIH percentile → direct 0-100 → 0-1 mapping."""
        article = {"pmid": "1", "year": 2020}
        metrics = {"nih_percentile": 95.0}
        score = scorer.score_article(article, icite_metrics=metrics)
        assert score.citation_impact == pytest.approx(0.95, abs=0.01)

    def test_citation_impact_from_rcr(self, scorer: LandmarkScorer):
        """RCR → log-scaled normalization."""
        article = {"pmid": "1", "year": 2020}
        metrics = {"relative_citation_ratio": 4.0}
        score = scorer.score_article(article, icite_metrics=metrics)
        expected = math.log2(1 + 4.0) / math.log2(1 + MAX_RCR_FOR_NORMALIZATION)
        assert score.citation_impact == pytest.approx(expected, abs=0.01)

    def test_citation_impact_from_raw_citations(self, scorer: LandmarkScorer):
        """Fallback to raw citation count when RCR unavailable."""
        article = {"pmid": "1", "year": 2020, "citation_count": 200}
        score = scorer.score_article(article)
        expected = math.log2(1 + 200) / math.log2(1 + MAX_CITATIONS_FOR_NORMALIZATION)
        assert score.citation_impact == pytest.approx(expected, abs=0.01)

    def test_citation_impact_priority_order(self, scorer: LandmarkScorer):
        """Percentile should be preferred over RCR when both available."""
        article = {"pmid": "1", "year": 2020}
        metrics = {"nih_percentile": 80.0, "relative_citation_ratio": 2.0}
        score = scorer.score_article(article, icite_metrics=metrics)
        # Should use percentile (80/100 = 0.80), not RCR
        assert score.citation_impact == pytest.approx(0.80, abs=0.01)

    def test_citation_impact_max_rcr(self, scorer: LandmarkScorer):
        """Very high RCR should cap at 1.0."""
        article = {"pmid": "1", "year": 2020}
        metrics = {"relative_citation_ratio": 50.0}
        score = scorer.score_article(article, icite_metrics=metrics)
        assert score.citation_impact == 1.0

    def test_citation_impact_zero(self, scorer: LandmarkScorer):
        """No citation data → 0.0."""
        article = {"pmid": "1", "year": 2020}
        score = scorer.score_article(article)
        assert score.citation_impact == 0.0

    # ----- Source Agreement -----

    def test_source_agreement_single(self, scorer: LandmarkScorer):
        article = {"pmid": "1", "year": 2020}
        score = scorer.score_article(article, source_count=1)
        assert score.source_agreement == SOURCE_AGREEMENT_SCORES[1]

    def test_source_agreement_dual(self, scorer: LandmarkScorer):
        article = {"pmid": "1", "year": 2020}
        score = scorer.score_article(article, source_count=2)
        assert score.source_agreement == SOURCE_AGREEMENT_SCORES[2]

    def test_source_agreement_triple(self, scorer: LandmarkScorer):
        article = {"pmid": "1", "year": 2020}
        score = scorer.score_article(article, source_count=3)
        assert score.source_agreement == SOURCE_AGREEMENT_SCORES[3]

    def test_source_agreement_max(self, scorer: LandmarkScorer):
        article = {"pmid": "1", "year": 2020}
        score = scorer.score_article(article, source_count=5)
        assert score.source_agreement == 1.0

    def test_source_agreement_many(self, scorer: LandmarkScorer):
        article = {"pmid": "1", "year": 2020}
        score = scorer.score_article(article, source_count=10)
        assert score.source_agreement == 1.0

    # ----- Citation Velocity -----

    def test_velocity_from_icite(self, scorer: LandmarkScorer):
        """Direct citations_per_year from iCite."""
        article = {"pmid": "1", "year": 2020}
        metrics = {"citations_per_year": 25.0}
        score = scorer.score_article(article, icite_metrics=metrics)
        expected = math.log2(1 + 25.0) / math.log2(1 + MAX_VELOCITY_FOR_NORMALIZATION)
        assert score.citation_velocity == pytest.approx(expected, abs=0.01)

    def test_velocity_fallback_estimated(self, scorer: LandmarkScorer):
        """Estimate velocity from total citations / age."""
        article = {"pmid": "1", "year": 2016, "citation_count": 100}
        score = scorer.score_article(article)
        # Age ≈ 10 years, velocity ≈ 10 citations/year
        assert score.citation_velocity > 0

    def test_velocity_zero(self, scorer: LandmarkScorer):
        """No citation data → 0.0."""
        article = {"pmid": "1", "year": 2020}
        score = scorer.score_article(article)
        assert score.citation_velocity == 0.0

    def test_velocity_high(self, scorer: LandmarkScorer):
        """Very high velocity should cap at 1.0."""
        article = {"pmid": "1", "year": 2020}
        metrics = {"citations_per_year": 200.0}
        score = scorer.score_article(article, icite_metrics=metrics)
        assert score.citation_velocity == 1.0

    # ----- Milestone Confidence & Evidence Quality -----

    def test_milestone_confidence_passthrough(self, scorer: LandmarkScorer):
        """Milestone confidence should be passed through."""
        article = {"pmid": "1", "year": 2020}
        score = scorer.score_article(article, milestone_confidence=0.85)
        assert score.milestone_confidence == 0.85

    def test_evidence_quality_passthrough(self, scorer: LandmarkScorer):
        """Evidence quality should be passed through."""
        article = {"pmid": "1", "year": 2020}
        score = scorer.score_article(article, evidence_level_score=0.75)
        assert score.evidence_quality == 0.75

    # ----- Overall Score -----

    def test_overall_weighted_combination(self, scorer: LandmarkScorer):
        """Overall should be weighted combination of components."""
        article = {"pmid": "1", "year": 2020}
        metrics = {"nih_percentile": 90.0, "citations_per_year": 20.0}
        score = scorer.score_article(
            article,
            icite_metrics=metrics,
            source_count=3,
            milestone_confidence=0.8,
            evidence_level_score=0.75,
        )
        # All components should be non-zero
        assert score.citation_impact > 0
        assert score.source_agreement > 0
        assert score.milestone_confidence > 0
        assert score.evidence_quality > 0
        assert score.citation_velocity > 0
        # Overall should be in (0, 1]
        assert 0 < score.overall <= 1.0

    def test_overall_max_capped_at_one(self):
        """Overall should never exceed 1.0."""
        scorer = LandmarkScorer()
        article = {"pmid": "1", "year": 2020}
        metrics = {"nih_percentile": 100.0, "citations_per_year": 100.0}
        score = scorer.score_article(
            article,
            icite_metrics=metrics,
            source_count=10,
            milestone_confidence=1.0,
            evidence_level_score=1.0,
        )
        assert score.overall <= 1.0

    def test_overall_zero_when_no_data(self, scorer: LandmarkScorer):
        """All-zero components → near-zero overall (only source_agreement minimum)."""
        article = {"pmid": "1", "year": 2020}
        score = scorer.score_article(article)
        # Only source_agreement has a minimum (0.1 for single source)
        assert score.overall < 0.1

    # ----- Batch Scoring -----

    def test_score_articles_sorted(self, scorer: LandmarkScorer):
        """Batch scoring should return articles sorted by score desc."""
        articles = [
            {"pmid": "1", "year": 2020, "citation_count": 10},
            {"pmid": "2", "year": 2020, "citation_count": 500},
            {"pmid": "3", "year": 2020, "citation_count": 100},
        ]
        scored = scorer.score_articles(articles)
        scores = [s.overall for _, s in scored]
        assert scores == sorted(scores, reverse=True)

    def test_score_articles_with_icite(self, scorer: LandmarkScorer):
        """Batch scoring with iCite data."""
        articles = [
            {"pmid": "1", "year": 2020},
            {"pmid": "2", "year": 2020},
        ]
        icite_data = {
            "1": {"nih_percentile": 30.0},
            "2": {"nih_percentile": 95.0},
        }
        scored = scorer.score_articles(articles, icite_data=icite_data)
        # Article 2 with higher percentile should rank first
        assert scored[0][0]["pmid"] == "2"

    def test_score_articles_with_source_counts(self, scorer: LandmarkScorer):
        """Source counts boost articles found in multiple sources."""
        articles = [
            {"pmid": "1", "year": 2020, "citation_count": 50},
            {"pmid": "2", "year": 2020, "citation_count": 50},
        ]
        source_counts = {"1": 1, "2": 4}
        scored = scorer.score_articles(articles, source_counts=source_counts)
        # Article 2 with more sources should rank higher
        assert scored[0][0]["pmid"] == "2"

    def test_score_articles_with_milestones(self, scorer: LandmarkScorer):
        """Milestone scores boost articles."""
        articles = [
            {"pmid": "1", "year": 2020},
            {"pmid": "2", "year": 2020},
        ]
        milestone_scores = {"2": 0.95}
        scored = scorer.score_articles(articles, milestone_scores=milestone_scores)
        assert scored[0][0]["pmid"] == "2"

    def test_score_articles_empty(self, scorer: LandmarkScorer):
        """Empty article list should return empty."""
        scored = scorer.score_articles([])
        assert scored == []

    # ----- Edge Cases -----

    def test_none_icite_metrics(self, scorer: LandmarkScorer):
        """None iCite metrics should work without errors."""
        article = {"pmid": "1", "year": 2020}
        score = scorer.score_article(article, icite_metrics=None)
        assert score.overall >= 0

    def test_missing_pmid(self, scorer: LandmarkScorer):
        """Article without pmid should still score."""
        article = {"title": "Test", "year": 2020}
        score = scorer.score_article(article)
        assert score.overall >= 0

    def test_zero_rcr(self, scorer: LandmarkScorer):
        """RCR=0 should result in 0 citation_impact."""
        article = {"pmid": "1", "year": 2020}
        metrics = {"relative_citation_ratio": 0.0}
        score = scorer.score_article(article, icite_metrics=metrics)
        assert score.citation_impact == 0.0

    def test_negative_percentile_ignored(self, scorer: LandmarkScorer):
        """Negative percentile should be treated as unavailable."""
        article = {"pmid": "1", "year": 2020}
        metrics = {"nih_percentile": -1.0}
        score = scorer.score_article(article, icite_metrics=metrics)
        # Should fall through to RCR or raw citations
        assert score.citation_impact == 0.0

    def test_string_year(self, scorer: LandmarkScorer):
        """String year should be handled for velocity calculation."""
        article = {"pmid": "1", "year": "2015", "citation_count": 50}
        score = scorer.score_article(article)
        assert score.citation_velocity > 0


# =============================================================================
# Utility Function Tests
# =============================================================================


class TestEvidenceLevelToScore:
    """Test the evidence_level_to_score utility."""

    def test_level_1(self):
        assert evidence_level_to_score("1") == 1.0

    def test_level_2(self):
        assert evidence_level_to_score("2") == 0.75

    def test_level_3(self):
        assert evidence_level_to_score("3") == 0.50

    def test_level_4(self):
        assert evidence_level_to_score("4") == 0.25

    def test_unknown(self):
        assert evidence_level_to_score("unknown") == 0.0

    def test_invalid(self):
        assert evidence_level_to_score("invalid") == 0.0

    def test_all_levels_defined(self):
        """All documented levels should be in the mapping."""
        for level in ["1", "2", "3", "4", "unknown"]:
            assert level in EVIDENCE_LEVEL_SCORES


# =============================================================================
# Integration: LandmarkScore with Timeline
# =============================================================================


class TestLandmarkScoreIntegration:
    """Test LandmarkScore integration with TimelineEvent."""

    def test_timeline_event_with_landmark(self):
        """TimelineEvent should accept landmark_score."""
        from pubmed_search.domain.entities.timeline import MilestoneType, TimelineEvent

        ls = LandmarkScore(
            overall=0.82,
            citation_impact=0.9,
            source_agreement=0.75,
        )
        event = TimelineEvent(
            pmid="12345",
            year=2020,
            milestone_type=MilestoneType.LANDMARK_STUDY,
            title="Test study",
            milestone_label="Landmark",
            landmark_score=ls,
        )
        assert event.landmark_score is not None
        assert event.landmark_score.overall == 0.82
        assert event.landmark_score.tier == "landmark"

    def test_timeline_event_to_dict_with_landmark(self):
        """to_dict should include landmark_score when present."""
        from pubmed_search.domain.entities.timeline import MilestoneType, TimelineEvent

        ls = LandmarkScore(overall=0.6, citation_impact=0.7)
        event = TimelineEvent(
            pmid="12345",
            year=2020,
            milestone_type=MilestoneType.META_ANALYSIS,
            title="Test",
            milestone_label="Meta-Analysis",
            landmark_score=ls,
        )
        d = event.to_dict()
        assert d["landmark_score"] is not None
        assert d["landmark_score"]["overall"] == 0.6
        assert d["landmark_score"]["tier"] == "notable"

    def test_timeline_event_to_dict_without_landmark(self):
        """to_dict should have null landmark_score when not set."""
        from pubmed_search.domain.entities.timeline import MilestoneType, TimelineEvent

        event = TimelineEvent(
            pmid="12345",
            year=2020,
            milestone_type=MilestoneType.OTHER,
            title="Test",
            milestone_label="Study",
        )
        d = event.to_dict()
        assert d["landmark_score"] is None

    def test_research_timeline_get_landmarks_by_score(self):
        """ResearchTimeline.get_landmark_events with min_landmark_score."""
        from pubmed_search.domain.entities.timeline import (
            MilestoneType,
            ResearchTimeline,
            TimelineEvent,
        )

        events = [
            TimelineEvent(
                pmid="1",
                year=2020,
                milestone_type=MilestoneType.OTHER,
                title="Low",
                milestone_label="Study",
                landmark_score=LandmarkScore(overall=0.2),
            ),
            TimelineEvent(
                pmid="2",
                year=2021,
                milestone_type=MilestoneType.PHASE_3,
                title="High",
                milestone_label="Phase 3",
                landmark_score=LandmarkScore(overall=0.8),
            ),
            TimelineEvent(
                pmid="3",
                year=2022,
                milestone_type=MilestoneType.META_ANALYSIS,
                title="Medium",
                milestone_label="Meta-Analysis",
                landmark_score=LandmarkScore(overall=0.55),
            ),
        ]
        timeline = ResearchTimeline(topic="test", events=events)

        # Filter by landmark score
        landmarks = timeline.get_landmark_events(min_landmark_score=0.5)
        assert len(landmarks) == 2
        pmids = {e.pmid for e in landmarks}
        assert "2" in pmids
        assert "3" in pmids

        # Fallback to citation count (no landmark_score filter)
        all_events = timeline.get_landmark_events(min_citations=0)
        assert len(all_events) == 3
