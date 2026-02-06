"""
Tests for Timeline modules: MilestoneDetector and TimelineBuilder.

Target: milestone_detector.py (18% → 90%), timeline_builder.py (14% → 90%)
"""

import pytest

from pubmed_search.application.timeline.milestone_detector import (
    LANDMARK_CITATION_THRESHOLDS,
    PUBTYPE_PATTERNS,
    TITLE_PATTERNS,
    MilestoneDetector,
    get_milestone_patterns,
)
from pubmed_search.domain.entities.timeline import (
    EvidenceLevel,
    MilestoneType,
    TimelineEvent,
)


# =============================================================================
# MilestoneDetector - Basic Tests
# =============================================================================


class TestMilestoneDetectorBasic:
    """Basic tests for MilestoneDetector."""

    def test_init_default(self):
        """Test initialization with defaults."""
        detector = MilestoneDetector()
        assert detector.title_patterns == TITLE_PATTERNS
        assert detector.pubtype_patterns == PUBTYPE_PATTERNS
        assert detector.min_confidence == 0.5

    def test_init_custom_patterns(self):
        """Test initialization with custom patterns."""
        custom_patterns = [
            (r"\bcustom\b", MilestoneType.BREAKTHROUGH, "Custom", 0.9),
        ]
        detector = MilestoneDetector(title_patterns=custom_patterns)
        assert detector.title_patterns == custom_patterns

    def test_init_custom_min_confidence(self):
        """Test initialization with custom min_confidence."""
        detector = MilestoneDetector(min_confidence=0.8)
        assert detector.min_confidence == 0.8

    def test_detect_milestone_missing_pmid(self):
        """Test detect_milestone returns None without PMID."""
        detector = MilestoneDetector()
        article = {"title": "Test", "year": 2024}
        assert detector.detect_milestone(article) is None

    def test_detect_milestone_missing_year(self):
        """Test detect_milestone returns None without year."""
        detector = MilestoneDetector()
        article = {"pmid": "12345678", "title": "Test"}
        assert detector.detect_milestone(article) is None


# =============================================================================
# MilestoneDetector - First Report Tests
# =============================================================================


class TestMilestoneDetectorFirstReport:
    """Tests for first report detection."""

    def test_detect_first_report(self):
        """Test first report detection."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "First study on new drug",
            "year": 2020,
        }
        event = detector.detect_milestone(article, is_first=True)
        assert event is not None
        assert event.milestone_type == MilestoneType.FIRST_REPORT
        assert event.milestone_label == "First Report"

    def test_detect_non_first_article(self):
        """Test non-first article without other milestones."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Regular study",
            "year": 2020,
        }
        event = detector.detect_milestone(article, is_first=False)
        assert event is None


# =============================================================================
# MilestoneDetector - Publication Type Tests
# =============================================================================


class TestMilestoneDetectorPubType:
    """Tests for publication type detection."""

    def test_detect_rct_pubtype(self):
        """Test RCT detection from publication type."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Test",
            "year": 2024,
            "publication_types": ["Randomized Controlled Trial"],
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.PHASE_3

    def test_detect_phase1_pubtype(self):
        """Test Phase 1 detection from publication type."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Test",
            "year": 2024,
            "publication_types": ["Clinical Trial, Phase I"],
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.PHASE_1

    def test_detect_phase2_pubtype(self):
        """Test Phase 2 detection from publication type."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Test",
            "year": 2024,
            "publication_types": ["Clinical Trial, Phase II"],
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.PHASE_2

    def test_detect_phase3_pubtype(self):
        """Test Phase 3 detection from publication type."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Test",
            "year": 2024,
            "publication_types": ["Clinical Trial, Phase III"],
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.PHASE_3

    def test_detect_phase4_pubtype(self):
        """Test Phase 4 detection from publication type."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Test",
            "year": 2024,
            "publication_types": ["Clinical Trial, Phase IV"],
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.PHASE_4

    def test_detect_meta_analysis_pubtype(self):
        """Test Meta-Analysis detection from publication type."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Test",
            "year": 2024,
            "publication_types": ["Meta-Analysis"],
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.META_ANALYSIS

    def test_detect_systematic_review_pubtype(self):
        """Test Systematic Review detection from publication type."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Test",
            "year": 2024,
            "publication_types": ["Systematic Review"],
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.SYSTEMATIC_REVIEW

    def test_detect_guideline_pubtype(self):
        """Test Guideline detection from publication type."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Test",
            "year": 2024,
            "publication_types": ["Guideline"],
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.GUIDELINE

    def test_detect_consensus_pubtype(self):
        """Test Consensus detection from publication type."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Test",
            "year": 2024,
            "publication_types": ["Consensus Development Conference"],
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.CONSENSUS

    def test_pubtype_string_input(self):
        """Test publication type as string (not list)."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Test",
            "year": 2024,
            "publication_types": "Meta-Analysis",
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.META_ANALYSIS


# =============================================================================
# MilestoneDetector - Title Pattern Tests
# =============================================================================


class TestMilestoneDetectorTitlePatterns:
    """Tests for title pattern detection."""

    def test_detect_fda_approval(self):
        """Test FDA approval detection from title."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "FDA approves new treatment for depression",
            "year": 2024,
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.FDA_APPROVAL

    def test_detect_ema_approval(self):
        """Test EMA approval detection from title."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "EMA authorizes new cancer therapy",
            "year": 2024,
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.EMA_APPROVAL

    def test_detect_phase3_from_title(self):
        """Test Phase 3 detection from title."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Phase III trial of drug X in diabetes",
            "year": 2024,
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.PHASE_3

    def test_detect_phase3_pivotal(self):
        """Test pivotal trial detection."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Pivotal trial results for new therapy",
            "year": 2024,
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.PHASE_3

    def test_detect_phase2_from_title(self):
        """Test Phase 2 detection from title."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Phase II dose-finding study",
            "year": 2024,
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.PHASE_2

    def test_detect_phase1_from_title(self):
        """Test Phase 1 detection from title."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "First-in-human study of new compound",
            "year": 2024,
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.PHASE_1

    def test_detect_meta_analysis_from_title(self):
        """Test meta-analysis detection from title."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "A meta-analysis of treatment outcomes",
            "year": 2024,
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.META_ANALYSIS

    def test_detect_systematic_review_from_title(self):
        """Test systematic review detection from title."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Systematic review of diabetes treatments",
            "year": 2024,
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.SYSTEMATIC_REVIEW

    def test_detect_safety_alert(self):
        """Test safety alert detection from title."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Safety alert: serious adverse events",
            "year": 2024,
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.SAFETY_ALERT

    def test_detect_guideline_from_title(self):
        """Test guideline detection from title."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Clinical guideline for heart failure",
            "year": 2024,
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.GUIDELINE


# =============================================================================
# MilestoneDetector - Abstract Pattern Tests
# =============================================================================


class TestMilestoneDetectorAbstract:
    """Tests for abstract pattern detection."""

    def test_detect_from_abstract(self):
        """Test milestone detection from abstract."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "A study results",
            "year": 2024,
            "abstract": "This phase III trial evaluated the efficacy...",
        }
        event = detector.detect_milestone(article)
        assert event is not None
        # Abstract detection has lower confidence


# =============================================================================
# MilestoneDetector - Citation Tests
# =============================================================================


class TestMilestoneDetectorCitations:
    """Tests for citation-based detection."""

    def test_detect_exceptional_landmark(self):
        """Test exceptional landmark detection."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Regular study",
            "year": 2020,
            "citation_count": 600,
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.milestone_type == MilestoneType.LANDMARK_STUDY
        assert "Landmark" in event.milestone_label

    def test_detect_high_impact(self):
        """Test high impact detection."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Regular study",
            "year": 2020,
            "citation_count": 250,
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert "High-Impact" in event.milestone_label

    def test_detect_notable(self):
        """Test notable study detection."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Regular study",
            "year": 2020,
            "citation_count": 120,
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert "Notable" in event.milestone_label

    def test_detect_citations_alternative_field(self):
        """Test citation detection with 'citations' field."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Regular study",
            "year": 2020,
            "citations": 600,
        }
        event = detector.detect_milestone(article)
        assert event is not None

    def test_no_detection_low_citations(self):
        """Test no detection with low citations."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Regular study",
            "year": 2020,
            "citation_count": 30,
        }
        event = detector.detect_milestone(article)
        assert event is None


# =============================================================================
# MilestoneDetector - Batch Detection Tests
# =============================================================================


class TestMilestoneDetectorBatch:
    """Tests for batch milestone detection."""

    def test_detect_milestones_batch_empty(self):
        """Test batch detection with empty list."""
        detector = MilestoneDetector()
        events = detector.detect_milestones_batch([])
        assert events == []

    def test_detect_milestones_batch_single(self):
        """Test batch detection with single article."""
        detector = MilestoneDetector()
        articles = [
            {"pmid": "1", "title": "First study", "year": 2020},
        ]
        events = detector.detect_milestones_batch(articles)
        assert len(events) == 1
        assert events[0].milestone_type == MilestoneType.FIRST_REPORT

    def test_detect_milestones_batch_chronological(self):
        """Test batch detection sorts chronologically."""
        detector = MilestoneDetector()
        articles = [
            {"pmid": "2", "title": "A systematic review study", "year": 2022},
            {"pmid": "1", "title": "FDA approves new drug", "year": 2020},
        ]
        events = detector.detect_milestones_batch(articles)
        # First article (2020) gets FDA approval (higher priority than first report)
        # Second article (2022) gets systematic review
        assert len(events) == 2
        # Events should be from chronological order: 2020 then 2022
        assert events[0].year == 2020
        assert events[1].year == 2022

    def test_detect_milestones_batch_pub_year_field(self):
        """Test batch detection with pub_year field."""
        detector = MilestoneDetector()
        articles = [
            {"pmid": "1", "title": "Study", "pub_year": 2020},
        ]
        events = detector.detect_milestones_batch(articles)
        assert len(events) == 1


# =============================================================================
# MilestoneDetector - Event Creation Tests
# =============================================================================


class TestMilestoneDetectorEventCreation:
    """Tests for event creation logic."""

    def test_event_includes_all_fields(self):
        """Test event includes all expected fields."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Test Study Title",
            "year": 2024,
            "month": 6,
            "abstract": "This is the abstract text.",
            "journal": "Nature Medicine",
            "doi": "10.1000/example",
            "citation_count": 50,
            "authors": ["Smith J", "Doe J"],
            "publication_types": ["Meta-Analysis"],
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.pmid == "12345678"
        assert event.year == 2024
        assert event.month == 6
        assert event.title == "Test Study Title"
        assert event.journal == "Nature Medicine"
        assert event.doi == "10.1000/example"
        assert event.first_author == "Smith J"

    def test_event_author_dict_format(self):
        """Test event with dict author format."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Test",
            "year": 2024,
            "authors": [{"name": "John Smith", "affiliation": "MIT"}],
            "publication_types": ["Meta-Analysis"],
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.first_author == "John Smith"

    def test_event_author_full_name_dict(self):
        """Test event with full_name in author dict."""
        detector = MilestoneDetector()
        article = {
            "pmid": "12345678",
            "title": "Test",
            "year": 2024,
            "authors": [{"full_name": "Jane Doe"}],
            "publication_types": ["Meta-Analysis"],
        }
        event = detector.detect_milestone(article)
        assert event is not None
        assert event.first_author == "Jane Doe"


# =============================================================================
# MilestoneDetector - Month Parsing Tests
# =============================================================================


class TestMilestoneDetectorMonthParsing:
    """Tests for month parsing logic."""

    def test_parse_month_int(self):
        """Test month parsing with integer."""
        detector = MilestoneDetector()
        assert detector._parse_month(6) == 6

    def test_parse_month_int_string(self):
        """Test month parsing with numeric string."""
        detector = MilestoneDetector()
        assert detector._parse_month("06") == 6
        assert detector._parse_month("12") == 12

    def test_parse_month_name_full(self):
        """Test month parsing with full month name."""
        detector = MilestoneDetector()
        assert detector._parse_month("January") == 1
        assert detector._parse_month("December") == 12

    def test_parse_month_name_short(self):
        """Test month parsing with short month name."""
        detector = MilestoneDetector()
        assert detector._parse_month("Jan") == 1
        assert detector._parse_month("Feb") == 2
        assert detector._parse_month("Mar") == 3
        assert detector._parse_month("Apr") == 4
        assert detector._parse_month("May") == 5
        assert detector._parse_month("Jun") == 6
        assert detector._parse_month("Jul") == 7
        assert detector._parse_month("Aug") == 8
        assert detector._parse_month("Sep") == 9
        assert detector._parse_month("Sept") == 9
        assert detector._parse_month("Oct") == 10
        assert detector._parse_month("Nov") == 11
        assert detector._parse_month("Dec") == 12

    def test_parse_month_case_insensitive(self):
        """Test month parsing is case insensitive."""
        detector = MilestoneDetector()
        assert detector._parse_month("JANUARY") == 1
        assert detector._parse_month("january") == 1

    def test_parse_month_invalid(self):
        """Test month parsing with invalid values."""
        detector = MilestoneDetector()
        assert detector._parse_month(0) is None
        assert detector._parse_month(13) is None
        assert detector._parse_month("invalid") is None
        assert detector._parse_month(None) is None
        assert detector._parse_month("") is None


# =============================================================================
# MilestoneDetector - Evidence Level Tests
# =============================================================================


class TestMilestoneDetectorEvidenceLevel:
    """Tests for evidence level inference."""

    def test_infer_level1_meta_analysis(self):
        """Test level 1 for meta-analysis."""
        detector = MilestoneDetector()
        article = {"publication_types": ["Meta-Analysis"]}
        level = detector._infer_evidence_level(article)
        assert level == EvidenceLevel.LEVEL_1

    def test_infer_level1_systematic_review(self):
        """Test level 1 for systematic review."""
        detector = MilestoneDetector()
        article = {"publication_types": ["Systematic Review"]}
        level = detector._infer_evidence_level(article)
        assert level == EvidenceLevel.LEVEL_1

    def test_infer_level2_rct(self):
        """Test level 2 for RCT."""
        detector = MilestoneDetector()
        article = {"publication_types": ["Randomized Controlled Trial"]}
        level = detector._infer_evidence_level(article)
        assert level == EvidenceLevel.LEVEL_2

    def test_infer_level2_phase3(self):
        """Test level 2 for Phase III."""
        detector = MilestoneDetector()
        article = {"publication_types": ["Clinical Trial, Phase III"]}
        level = detector._infer_evidence_level(article)
        assert level == EvidenceLevel.LEVEL_2

    def test_infer_level3_phase2(self):
        """Test level 3 for Phase II."""
        detector = MilestoneDetector()
        article = {"publication_types": ["Clinical Trial, Phase II"]}
        level = detector._infer_evidence_level(article)
        assert level == EvidenceLevel.LEVEL_3

    def test_infer_level4_case_report(self):
        """Test level 4 for case reports."""
        detector = MilestoneDetector()
        article = {"publication_types": ["Case Reports"]}
        level = detector._infer_evidence_level(article)
        assert level == EvidenceLevel.LEVEL_4

    def test_infer_level_unknown(self):
        """Test unknown level."""
        detector = MilestoneDetector()
        article = {"publication_types": ["Other"]}
        level = detector._infer_evidence_level(article)
        assert level == EvidenceLevel.UNKNOWN

    def test_infer_level_string_pubtype(self):
        """Test evidence level with string publication type."""
        detector = MilestoneDetector()
        article = {"publication_types": "Meta-Analysis"}
        level = detector._infer_evidence_level(article)
        assert level == EvidenceLevel.LEVEL_1


# =============================================================================
# Module Level Functions Tests
# =============================================================================


class TestModuleFunctions:
    """Tests for module-level functions."""

    def test_get_milestone_patterns(self):
        """Test get_milestone_patterns returns patterns."""
        patterns = get_milestone_patterns()
        assert len(patterns) > 0
        assert all("pattern" in p for p in patterns)
        assert all("milestone_type" in p for p in patterns)
        assert all("label" in p for p in patterns)
        assert all("confidence" in p for p in patterns)


# =============================================================================
# Constants Tests
# =============================================================================


class TestConstants:
    """Tests for module constants."""

    def test_title_patterns_non_empty(self):
        """Test TITLE_PATTERNS is not empty."""
        assert len(TITLE_PATTERNS) > 0

    def test_pubtype_patterns_non_empty(self):
        """Test PUBTYPE_PATTERNS is not empty."""
        assert len(PUBTYPE_PATTERNS) > 0

    def test_landmark_thresholds(self):
        """Test landmark citation thresholds."""
        assert LANDMARK_CITATION_THRESHOLDS["exceptional"] > LANDMARK_CITATION_THRESHOLDS["high"]
        assert LANDMARK_CITATION_THRESHOLDS["high"] > LANDMARK_CITATION_THRESHOLDS["notable"]
        assert LANDMARK_CITATION_THRESHOLDS["notable"] > LANDMARK_CITATION_THRESHOLDS["moderate"]
