"""Tests for TimelineBuilder and format_timeline_text."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pubmed_search.application.timeline.timeline_builder import (
    TimelineBuilder,
    format_timeline_text,
)
from pubmed_search.domain.entities.timeline import (
    MilestoneType,
    ResearchTimeline,
    TimelineEvent,
)

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_searcher():
    searcher = MagicMock()
    searcher.search = AsyncMock(return_value=[])
    searcher.fetch_details = AsyncMock(return_value=[])
    searcher.get_citation_metrics = AsyncMock(return_value=None)
    return searcher


@pytest.fixture
def builder(mock_searcher):
    return TimelineBuilder(mock_searcher)


@pytest.fixture
def sample_articles():
    return [
        {
            "pmid": "11111",
            "title": "First report of drug X",
            "year": "2010",
            "month": "Jan",
            "authors": [{"name": "Smith J"}],
            "journal": "Nature",
            "doi": "10.1/a",
            "abstract": "First report of a novel drug X.",
        },
        {
            "pmid": "22222",
            "title": "Phase 3 randomized trial of drug X",
            "year": "2015",
            "month": "6",
            "authors": [{"name": "Doe A"}],
            "journal": "NEJM",
            "doi": "10.1/b",
            "abstract": "Phase 3 randomized controlled trial.",
        },
        {
            "pmid": "33333",
            "title": "Meta-analysis of drug X efficacy",
            "year": "2020",
            "month": "Dec",
            "authors": ["Johnson B"],
            "journal": "Lancet",
            "doi": "10.1/c",
            "abstract": "Systematic review and meta-analysis.",
        },
    ]


# ============================================================
# Init
# ============================================================


class TestInit:
    async def test_default_detector(self, mock_searcher):
        b = TimelineBuilder(mock_searcher)
        assert b.detector is not None

    async def test_custom_detector(self, mock_searcher):
        from pubmed_search.application.timeline.milestone_detector import (
            MilestoneDetector,
        )

        detector = MilestoneDetector()
        b = TimelineBuilder(mock_searcher, detector=detector)
        assert b.detector is detector


# ============================================================
# build_timeline
# ============================================================


class TestBuildTimeline:
    @pytest.mark.asyncio
    async def test_empty_results(self, builder, mock_searcher):
        mock_searcher.search.return_value = []
        timeline = await builder.build_timeline("nonexistent drug")
        assert isinstance(timeline, ResearchTimeline)
        assert timeline.topic == "nonexistent drug"
        assert len(timeline.events) == 0

    @pytest.mark.asyncio
    async def test_with_articles(self, builder, mock_searcher, sample_articles):
        mock_searcher.search.return_value = sample_articles
        timeline = await builder.build_timeline("drug X", max_events=50)
        assert timeline.topic == "drug X"
        # Milestone detection should find at least some events
        assert isinstance(timeline.events, list)

    @pytest.mark.asyncio
    async def test_year_filter(self, builder, mock_searcher, sample_articles):
        mock_searcher.search.return_value = sample_articles
        timeline = await builder.build_timeline("drug X", min_year=2015, max_year=2020)
        # Only articles from 2015-2020 should be included
        for event in timeline.events:
            assert 2015 <= event.year <= 2020

    @pytest.mark.asyncio
    async def test_include_all(self, builder, mock_searcher, sample_articles):
        mock_searcher.search.return_value = sample_articles
        timeline = await builder.build_timeline("drug X", include_all=True, max_events=50)
        # With include_all, even non-milestone articles should appear
        assert len(timeline.events) >= len(sample_articles) or len(timeline.events) > 0

    @pytest.mark.asyncio
    async def test_max_events_limit(self, builder, mock_searcher):
        # Create many articles
        articles = [
            {
                "pmid": str(i),
                "title": f"Study {i}",
                "year": str(2000 + i),
                "authors": [],
                "journal": "J",
                "abstract": "study",
            }
            for i in range(20)
        ]
        mock_searcher.search.return_value = articles
        timeline = await builder.build_timeline("topic", max_events=5, include_all=True)
        assert len(timeline.events) <= 5

    @pytest.mark.asyncio
    async def test_auto_periods(self, builder, mock_searcher, sample_articles):
        mock_searcher.search.return_value = sample_articles
        timeline = await builder.build_timeline("drug X", auto_periods=True)
        # Periods may or may not be created depending on milestone detection
        assert isinstance(timeline.periods, list)

    @pytest.mark.asyncio
    async def test_no_auto_periods(self, builder, mock_searcher, sample_articles):
        mock_searcher.search.return_value = sample_articles
        timeline = await builder.build_timeline("drug X", auto_periods=False)
        assert timeline.periods == []

    @pytest.mark.asyncio
    async def test_citation_sorting(self, builder, mock_searcher, sample_articles):
        mock_searcher.search.return_value = sample_articles
        mock_searcher.get_citation_metrics.return_value = [
            {"pmid": "11111", "citation_count": 100},
            {"pmid": "22222", "citation_count": 500},
            {"pmid": "33333", "citation_count": 50},
        ]
        timeline = await builder.build_timeline("drug X", sort_by_citations=True)
        assert isinstance(timeline, ResearchTimeline)


# ============================================================
# build_timeline_from_pmids
# ============================================================


class TestBuildTimelineFromPmids:
    @pytest.mark.asyncio
    async def test_empty_pmids(self, builder):
        timeline = await builder.build_timeline_from_pmids([])
        assert timeline.topic == "Custom Timeline"
        assert len(timeline.events) == 0

    @pytest.mark.asyncio
    async def test_with_pmids(self, builder, mock_searcher, sample_articles):
        mock_searcher.fetch_details.return_value = sample_articles
        timeline = await builder.build_timeline_from_pmids(["11111", "22222", "33333"], topic="My Timeline")
        assert timeline.topic == "My Timeline"
        assert isinstance(timeline.events, list)

    @pytest.mark.asyncio
    async def test_fetch_returns_empty(self, builder, mock_searcher):
        mock_searcher.fetch_details.return_value = []
        timeline = await builder.build_timeline_from_pmids(["99999"])
        assert len(timeline.events) == 0


# ============================================================
# _search_topic
# ============================================================


class TestSearchTopic:
    @pytest.mark.asyncio
    async def test_basic_search(self, builder, mock_searcher):
        mock_searcher.search.return_value = [{"pmid": "1", "title": "Test"}]
        results = await builder._search_topic("topic")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_with_citation_sorting(self, builder, mock_searcher):
        mock_searcher.search.return_value = [
            {"pmid": "1", "title": "Low cited"},
            {"pmid": "2", "title": "High cited"},
        ]
        mock_searcher.get_citation_metrics.return_value = {
            "1": {"pmid": "1", "citation_count": 10},
            "2": {"pmid": "2", "citation_count": 1000},
        }
        results = await builder._search_topic("topic", sort_by_citations=True)
        assert results[0]["citation_count"] == 1000

    @pytest.mark.asyncio
    async def test_search_exception(self, builder, mock_searcher):
        mock_searcher.search.side_effect = Exception("fail")
        results = await builder._search_topic("topic")
        assert results == []

    @pytest.mark.asyncio
    async def test_citation_sorting_failure_graceful(self, builder, mock_searcher):
        mock_searcher.search.return_value = [{"pmid": "1", "title": "Test"}]
        mock_searcher.get_citation_metrics.side_effect = Exception("iCite down")
        results = await builder._search_topic("topic", sort_by_citations=True)
        assert len(results) == 1  # Still returns results despite citation failure


# ============================================================
# _filter_by_year
# ============================================================


class TestFilterByYear:
    async def test_min_year(self, builder):
        articles = [
            {"year": "2010"},
            {"year": "2015"},
            {"year": "2020"},
        ]
        filtered = builder._filter_by_year(articles, min_year=2015, max_year=None)
        assert len(filtered) == 2

    async def test_max_year(self, builder):
        articles = [
            {"year": "2010"},
            {"year": "2015"},
            {"year": "2020"},
        ]
        filtered = builder._filter_by_year(articles, min_year=None, max_year=2015)
        assert len(filtered) == 2

    async def test_both(self, builder):
        articles = [
            {"year": "2010"},
            {"year": "2015"},
            {"year": "2020"},
        ]
        filtered = builder._filter_by_year(articles, min_year=2012, max_year=2018)
        assert len(filtered) == 1

    async def test_no_year(self, builder):
        articles = [{"title": "No year"}]
        filtered = builder._filter_by_year(articles, min_year=2010, max_year=None)
        assert len(filtered) == 0

    async def test_pub_year_field(self, builder):
        articles = [{"pub_year": "2020"}]
        filtered = builder._filter_by_year(articles, min_year=2015, max_year=None)
        assert len(filtered) == 1


# ============================================================
# _create_generic_event
# ============================================================


class TestCreateGenericEvent:
    async def test_basic(self, builder):
        article = {
            "pmid": "12345",
            "title": "Test Study",
            "year": "2023",
            "month": "Jan",
            "authors": [{"name": "Smith J"}],
            "journal": "Nature",
            "doi": "10.1/test",
        }
        event = builder._create_generic_event(article)
        assert isinstance(event, TimelineEvent)
        assert event.pmid == "12345"
        assert event.year == 2023
        assert event.month == 1
        assert event.milestone_type == MilestoneType.OTHER
        assert event.first_author == "Smith J"

    async def test_string_author(self, builder):
        article = {"pmid": "1", "title": "T", "year": "2023", "authors": ["Doe A"]}
        event = builder._create_generic_event(article)
        assert event.first_author == "Doe A"

    async def test_dict_author_full_name(self, builder):
        article = {
            "pmid": "1",
            "title": "T",
            "year": "2023",
            "authors": [{"full_name": "Jane Doe"}],
        }
        event = builder._create_generic_event(article)
        assert event.first_author == "Jane Doe"

    async def test_no_year(self, builder):
        article = {"pmid": "1", "title": "T", "authors": []}
        event = builder._create_generic_event(article)
        assert event.year == 0

    async def test_source_field(self, builder):
        article = {
            "pmid": "1",
            "title": "T",
            "year": "2023",
            "source": "JAMA",
            "authors": [],
        }
        event = builder._create_generic_event(article)
        assert event.journal == "JAMA"


# ============================================================
# _parse_month
# ============================================================


class TestParseMonth:
    async def test_int(self, builder):
        assert builder._parse_month(6) == 6

    async def test_int_out_of_range(self, builder):
        assert builder._parse_month(13) is None
        assert builder._parse_month(0) is None

    async def test_string_number(self, builder):
        assert builder._parse_month("3") == 3

    async def test_month_name(self, builder):
        assert builder._parse_month("Jan") == 1
        assert builder._parse_month("february") == 2
        assert builder._parse_month("mar") == 3
        assert builder._parse_month("sept") == 9
        assert builder._parse_month("December") == 12

    async def test_none(self, builder):
        assert builder._parse_month(None) is None

    async def test_invalid(self, builder):
        assert builder._parse_month("xyz") is None

    async def test_string_number_out_of_range(self, builder):
        assert builder._parse_month("15") is None


# ============================================================
# _create_periods
# ============================================================


class TestCreatePeriods:
    async def test_groups_by_milestone_type(self, builder):
        events = [
            TimelineEvent(
                pmid="1",
                year=2010,
                milestone_type=MilestoneType.FIRST_REPORT,
                title="First",
                milestone_label="First Report",
            ),
            TimelineEvent(
                pmid="2",
                year=2015,
                milestone_type=MilestoneType.PHASE_3,
                title="Phase 3",
                milestone_label="Phase 3",
            ),
            TimelineEvent(
                pmid="3",
                year=2020,
                milestone_type=MilestoneType.META_ANALYSIS,
                title="Meta",
                milestone_label="Meta-Analysis",
            ),
        ]
        periods = builder._create_periods(events)
        assert isinstance(periods, list)
        assert len(periods) >= 1
        # Should have Discovery, Clinical Development, Evidence Synthesis
        period_names = [p.name for p in periods]
        assert "Discovery" in period_names

    async def test_empty_events(self, builder):
        assert builder._create_periods([]) == []

    async def test_sorted_by_start_year(self, builder):
        events = [
            TimelineEvent(
                pmid="1",
                year=2020,
                milestone_type=MilestoneType.META_ANALYSIS,
                title="Meta",
                milestone_label="Meta",
            ),
            TimelineEvent(
                pmid="2",
                year=2010,
                milestone_type=MilestoneType.FIRST_REPORT,
                title="First",
                milestone_label="First",
            ),
        ]
        periods = builder._create_periods(events)
        if len(periods) >= 2:
            assert periods[0].start_year <= periods[1].start_year


# ============================================================
# format_timeline_text
# ============================================================


class TestFormatTimelineText:
    async def test_empty_timeline(self):
        timeline = ResearchTimeline(topic="Test")
        result = format_timeline_text(timeline)
        assert "No timeline events found" in result

    async def test_with_events(self):
        events = [
            TimelineEvent(
                pmid="1",
                year=2010,
                milestone_type=MilestoneType.FIRST_REPORT,
                title="First Discovery",
                milestone_label="First Report",
                confidence_score=0.9,
            ),
            TimelineEvent(
                pmid="2",
                year=2020,
                milestone_type=MilestoneType.META_ANALYSIS,
                title="Comprehensive Meta-Analysis",
                milestone_label="Meta-Analysis",
                confidence_score=0.6,
            ),
        ]
        timeline = ResearchTimeline(topic="Drug X", events=events)
        result = format_timeline_text(timeline)
        assert "Drug X" in result
        assert "2010" in result
        assert "2020" in result
        assert "First Report" in result
        assert "⭐" in result  # High confidence event

    async def test_long_title_truncated(self):
        long_title = "A" * 100
        events = [
            TimelineEvent(
                pmid="1",
                year=2023,
                milestone_type=MilestoneType.OTHER,
                title=long_title,
                milestone_label="Study",
            ),
        ]
        timeline = ResearchTimeline(topic="Test", events=events)
        result = format_timeline_text(timeline)
        assert "..." in result
