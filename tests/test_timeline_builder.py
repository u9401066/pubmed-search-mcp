"""Tests for TimelineBuilder and format_timeline_text."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.application.timeline.timeline_builder import (
    TimelineBuilder,
    TimelineRetrievalError,
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


def _pubmed_page(items, *, total=None, query="topic"):
    return SourceSearchPage(
        source="pubmed",
        items=list(items),
        total=total,
        query=query,
        metadata={"physical_query": query, "query_executed": True},
    )


@pytest.fixture
def mock_searcher():
    searcher = MagicMock()
    searcher.search_page = AsyncMock(return_value=_pubmed_page([], total=0))
    searcher.fetch_details = AsyncMock(return_value=[])
    searcher.get_citation_metrics = AsyncMock(return_value={})
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
        mock_searcher.search_page.return_value = _pubmed_page([], total=0)
        timeline = await builder.build_timeline("nonexistent drug")
        assert isinstance(timeline, ResearchTimeline)
        assert timeline.topic == "nonexistent drug"
        assert len(timeline.events) == 0
        assert timeline.metadata["source_counts"] == {"pubmed": {"returned": 0, "available": 0}}
        assert timeline.metadata["search_status"] == "no_results"
        assert timeline.metadata["retrieval"]["ranking"] == "pubmed_relevance"
        assert timeline.metadata["retrieval"]["citation_metrics"]["status"] == "not_requested"

    @pytest.mark.asyncio
    async def test_with_articles(self, builder, mock_searcher, sample_articles):
        mock_searcher.search_page.return_value = _pubmed_page(sample_articles)
        timeline = await builder.build_timeline("drug X", max_events=50)
        assert timeline.topic == "drug X"
        # Milestone detection should find at least some events
        assert isinstance(timeline.events, list)
        assert "diagnostics" in timeline.metadata
        assert timeline.metadata["source_counts"] == {"pubmed": {"returned": len(sample_articles), "available": None}}

    @pytest.mark.asyncio
    async def test_year_filter(self, builder, mock_searcher, sample_articles):
        mock_searcher.search_page.return_value = _pubmed_page(sample_articles)
        timeline = await builder.build_timeline("drug X", min_year=2015, max_year=2020)
        assert mock_searcher.search_page.await_args.kwargs["min_year"] == 2015
        assert mock_searcher.search_page.await_args.kwargs["max_year"] == 2020
        # Only articles from 2015-2020 should be included
        for event in timeline.events:
            assert 2015 <= event.year <= 2020

    @pytest.mark.asyncio
    async def test_include_all(self, builder, mock_searcher, sample_articles):
        mock_searcher.search_page.return_value = _pubmed_page(sample_articles)
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
        mock_searcher.search_page.return_value = _pubmed_page(articles)
        timeline = await builder.build_timeline(
            "topic",
            max_events=5,
            include_all=True,
            highlight_landmarks=False,
        )
        assert len(timeline.events) == 5
        assert timeline.events[0].pmid == "0"
        assert timeline.events[-1].pmid == "19"
        assert timeline.metadata["events_before_output_cap"] == 20
        assert timeline.metadata["diagnostics"]["search"]["event_selection"].startswith("chronological_boundaries")

    @pytest.mark.asyncio
    async def test_auto_periods(self, builder, mock_searcher, sample_articles):
        mock_searcher.search_page.return_value = _pubmed_page(sample_articles)
        timeline = await builder.build_timeline("drug X", auto_periods=True)
        # Periods may or may not be created depending on milestone detection
        assert isinstance(timeline.periods, list)

    @pytest.mark.asyncio
    async def test_no_auto_periods(self, builder, mock_searcher, sample_articles):
        mock_searcher.search_page.return_value = _pubmed_page(sample_articles)
        timeline = await builder.build_timeline("drug X", auto_periods=False)
        assert timeline.periods == []

    @pytest.mark.asyncio
    async def test_citation_sorting(self, builder, mock_searcher, sample_articles):
        mock_searcher.search_page.return_value = _pubmed_page(sample_articles)
        mock_searcher.get_citation_metrics.return_value = {
            "11111": {"pmid": "11111", "citation_count": 100},
            "22222": {"pmid": "22222", "citation_count": 500},
            "33333": {"pmid": "33333", "citation_count": 50},
        }
        timeline = await builder.build_timeline("drug X", sort_by_citations=True)
        assert isinstance(timeline, ResearchTimeline)
        retrieval = timeline.metadata["retrieval"]
        assert retrieval["ranking_requested"] == "icite_citation_count_then_pubmed_relevance"
        assert retrieval["ranking"] == "icite_citation_count_then_pubmed_relevance"
        assert retrieval["citation_metrics"] == {
            "schema_version": "citation-metrics-coverage/v1",
            "source": "nih_icite",
            "status": "complete",
            "requested": 3,
            "returned": 3,
            "applied": 3,
            "citation_counts_applied": 3,
            "complete": True,
            "error": None,
        }


# ============================================================
# build_timeline_from_pmids
# ============================================================


class TestBuildTimelineFromPmids:
    async def test_ordering_and_event_dates_use_the_same_month_policy(self, builder, mock_searcher):
        mock_searcher.fetch_details.return_value = [
            {"pmid": "3", "title": "March background", "year": "2024", "month": "+3"},
            {"pmid": "2", "title": "January background", "year": "2024", "month": "Jan"},
            {"pmid": "1", "title": "Randomized controlled trial", "year": "2024", "month": True},
        ]

        timeline = await builder.build_timeline_from_pmids(["3", "2", "1"], auto_periods=False)

        assert [(event.pmid, event.month) for event in timeline.events] == [("1", None), ("2", 1), ("3", 3)]
        # Earliest-in-scope selection happens before event construction. A
        # different parser there used to choose the March paper as the first.
        assert timeline.events[2].metadata.get("earliest_observed_in_scope") is not True

    @pytest.mark.asyncio
    async def test_empty_pmids(self, builder):
        timeline = await builder.build_timeline_from_pmids([])
        assert timeline.topic == "Custom Timeline"
        assert len(timeline.events) == 0
        assert timeline.metadata["source_counts"] == {"pubmed": {"returned": 0, "available": 0}}

    @pytest.mark.asyncio
    async def test_with_pmids(self, builder, mock_searcher, sample_articles):
        mock_searcher.fetch_details.return_value = sample_articles
        timeline = await builder.build_timeline_from_pmids(["11111", "22222", "33333"], topic="My Timeline")
        assert timeline.topic == "My Timeline"
        assert isinstance(timeline.events, list)
        assert "diagnostics" in timeline.metadata
        assert timeline.metadata["source_counts"] == {
            "pubmed": {"returned": len(sample_articles), "available": len(sample_articles)}
        }

    @pytest.mark.asyncio
    async def test_fetch_returns_empty(self, builder, mock_searcher):
        mock_searcher.fetch_details.return_value = []
        timeline = await builder.build_timeline_from_pmids(["99999"])
        assert len(timeline.events) == 0
        assert timeline.metadata["source_counts"] == {"pubmed": {"returned": 0, "available": 1}}


# ============================================================
# _search_topic
# ============================================================


class TestSearchTopic:
    @pytest.mark.asyncio
    async def test_basic_search(self, builder, mock_searcher):
        mock_searcher.search_page.return_value = _pubmed_page([{"pmid": "1", "title": "Test"}])
        results = await builder._search_topic("topic")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_with_citation_sorting(self, builder, mock_searcher):
        mock_searcher.search_page.return_value = _pubmed_page(
            [
                {"pmid": "1", "title": "Low cited"},
                {"pmid": "2", "title": "High cited"},
            ]
        )
        mock_searcher.get_citation_metrics.return_value = {
            "1": {"pmid": "1", "citation_count": 10},
            "2": {"pmid": "2", "citation_count": 1000},
        }
        results = await builder._search_topic("topic", sort_by_citations=True)
        assert results[0]["citation_count"] == 1000

    @pytest.mark.asyncio
    async def test_search_exception(self, builder, mock_searcher):
        mock_searcher.search_page.side_effect = Exception("fail")
        with pytest.raises(TimelineRetrievalError, match="PubMed search failed"):
            await builder._search_topic("topic")

    @pytest.mark.asyncio
    async def test_malformed_source_row_never_becomes_empty_timeline(self, builder, mock_searcher):
        mock_searcher.search_page.return_value = _pubmed_page([{"unexpected": "private upstream payload"}])

        with pytest.raises(TimelineRetrievalError, match="malformed article row") as exc_info:
            await builder.build_timeline("topic", include_all=True)

        assert "private upstream payload" not in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_retired_untyped_search_result_is_rejected(self, builder, mock_searcher):
        mock_searcher.search_page.return_value = [{"_search_metadata": {"total_count": 12}}]

        with pytest.raises(TimelineRetrievalError, match="invalid search page"):
            await builder.build_timeline("topic", include_all=True)

    @pytest.mark.asyncio
    async def test_total_available_is_preserved(self, builder, mock_searcher):
        mock_searcher.search_page.return_value = _pubmed_page(
            [{"pmid": "1", "title": "Paper", "year": "2020"}], total=99, query="physical query"
        )

        timeline = await builder.build_timeline("topic", include_all=True)

        assert timeline.metadata["source_counts"] == {"pubmed": {"returned": 1, "available": 99}}
        assert timeline.metadata["retrieval"]["physical_query"] == "physical query"

    @pytest.mark.asyncio
    async def test_citation_sorting_failure_graceful(self, builder, mock_searcher):
        mock_searcher.search_page.return_value = _pubmed_page([{"pmid": "1", "title": "Test"}])
        secret = "iCite down at https://private.invalid/?token=secret"
        mock_searcher.get_citation_metrics.side_effect = RuntimeError(secret)

        timeline = await builder.build_timeline(
            "topic",
            include_all=True,
            highlight_landmarks=False,
            sort_by_citations=True,
        )

        assert len(timeline.events) == 1
        retrieval = timeline.metadata["retrieval"]
        assert retrieval["ranking_requested"] == "icite_citation_count_then_pubmed_relevance"
        assert retrieval["ranking"] == "pubmed_relevance"
        coverage = retrieval["citation_metrics"]
        assert coverage["status"] == "error"
        assert coverage["requested"] == 1
        assert coverage["applied"] == 0
        assert coverage["error"] == {
            "source": "nih_icite",
            "operation": "citation_metrics",
            "kind": "unexpected",
            "message": "Source adapter failed",
            "retryable": False,
            "status_code": None,
            "exception_type": "RuntimeError",
        }
        assert secret not in str(coverage)

        from pubmed_search.application.chronicle import assemble_chronicle, audit_chronicle

        snapshot = assemble_chronicle(topic="topic", timeline=timeline)
        audit_finding = next(
            finding for finding in audit_chronicle(snapshot).findings if finding.check == "citation_metrics_coverage"
        )
        assert audit_finding.status == "warn"
        assert audit_finding.details["status"] == "error"
        assert secret not in str(audit_finding.to_dict())

    @pytest.mark.asyncio
    async def test_partial_citation_coverage_records_effective_ranking(self, builder, mock_searcher):
        mock_searcher.search_page.return_value = _pubmed_page(
            [
                {"pmid": "1", "title": "No iCite row", "year": "2020"},
                {"pmid": "2", "title": "Covered", "year": "2021"},
            ]
        )
        mock_searcher.get_citation_metrics.return_value = {
            "2": {"pmid": "2", "citation_count": 7},
        }

        timeline = await builder.build_timeline(
            "topic",
            include_all=True,
            highlight_landmarks=False,
            sort_by_citations=True,
        )

        retrieval = timeline.metadata["retrieval"]
        assert retrieval["ranking"] == "icite_citation_count_then_pubmed_relevance"
        assert retrieval["citation_metrics"]["status"] == "partial"
        assert retrieval["citation_metrics"]["applied"] == 1
        assert retrieval["citation_metrics"]["citation_counts_applied"] == 1

    @pytest.mark.asyncio
    async def test_invalid_citation_response_does_not_claim_icite_ranking(self, builder, mock_searcher):
        mock_searcher.search_page.return_value = _pubmed_page([{"pmid": "1", "title": "Paper", "year": "2020"}])
        mock_searcher.get_citation_metrics.return_value = [{"pmid": "1", "citation_count": 10}]

        timeline = await builder.build_timeline("topic", include_all=True, highlight_landmarks=False)

        retrieval = timeline.metadata["retrieval"]
        assert retrieval["ranking"] == "pubmed_relevance"
        assert retrieval["citation_metrics"]["status"] == "error"
        assert retrieval["citation_metrics"]["error"]["kind"] == "validation"

    @pytest.mark.asyncio
    async def test_unrequested_icite_row_invalidates_the_whole_enrichment(self, builder, mock_searcher):
        mock_searcher.search_page.return_value = _pubmed_page([{"pmid": "1", "title": "Paper", "year": "2020"}])
        mock_searcher.get_citation_metrics.return_value = {
            "1": {"pmid": "1", "citation_count": 10},
            "private-unrequested-id": {"pmid": "private-unrequested-id", "citation_count": 999},
        }

        timeline = await builder.build_timeline(
            "topic",
            include_all=True,
            highlight_landmarks=False,
            sort_by_citations=True,
        )

        retrieval = timeline.metadata["retrieval"]
        assert retrieval["ranking"] == "pubmed_relevance"
        assert retrieval["citation_metrics"]["status"] == "error"
        assert "private-unrequested-id" not in str(retrieval)


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
            "mesh_terms": ["Drug Safety"],
            "keywords": ["pharmacovigilance"],
        }
        event = builder._create_generic_event(article)
        assert isinstance(event, TimelineEvent)
        assert event.pmid == "12345"
        assert event.year == 2023
        assert event.month == 1
        assert event.milestone_type == MilestoneType.OTHER
        assert event.first_author == "Smith J"
        assert event.metadata["mesh_terms"] == ["Drug Safety"]
        assert event.metadata["keywords"] == ["pharmacovigilance"]

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
        assert event.date_label == "Undated"

    async def test_undated_events_sort_last_and_do_not_expand_year_range(self, builder):
        undated = builder._create_generic_event({"pmid": "2", "title": "Undated", "authors": []})
        dated = builder._create_generic_event({"pmid": "1", "title": "Dated", "year": "2020", "authors": []})

        timeline = ResearchTimeline("topic", [undated, dated])

        assert [event.pmid for event in timeline.events] == ["1", "2"]
        assert timeline.year_range == (2020, 2020)

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
        from pubmed_search.domain.entities.timeline import LandmarkScore

        ls_high = LandmarkScore(overall=0.82, citation_impact=0.9)
        events = [
            TimelineEvent(
                pmid="1",
                year=2010,
                milestone_type=MilestoneType.FIRST_REPORT,
                title="First Discovery",
                milestone_label="First Report",
                confidence_score=0.9,
                landmark_score=ls_high,
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
        assert "⭐" in result  # Landmark star rating

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
