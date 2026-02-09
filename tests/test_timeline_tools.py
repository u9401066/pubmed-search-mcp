"""Tests for timeline MCP tools."""

import json
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from pubmed_search.presentation.mcp_server.tools.timeline import (
    register_timeline_tools,
)


def _capture_tools(mcp, searcher):
    tools = {}
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
    register_timeline_tools(mcp, searcher)
    return tools


class _FakeEvent:
    def __init__(self, pmid="111", year=2020, title="T", milestone_type=None,
                 milestone_label="label", citation_count=0):
        self.pmid = pmid
        self.year = year
        self.title = title
        self.milestone_label = milestone_label
        self.citation_count = citation_count

        class _MT:
            value = "generic"
        self.milestone_type = milestone_type or _MT()

    def to_dict(self):
        return {"pmid": self.pmid, "year": self.year, "title": self.title}


class _FakePeriod:
    def to_dict(self):
        return {"name": "period1"}


class _FakeTimeline:
    def __init__(self, events=None, empty=False):
        self.events = [] if empty else (events or [_FakeEvent()])
        self.total_events = len(self.events)
        self.year_range = (2020, 2024) if self.events else None
        self.duration_years = 4 if self.events else 0
        self.milestone_summary = {"generic": 1} if self.events else {}
        self.periods = [_FakePeriod()] if self.events else []

    def get_landmark_events(self, min_citations=50):
        return [e for e in self.events if e.citation_count >= min_citations]

    def to_mermaid(self):
        return "gantt\n  title Timeline"

    def to_dict(self):
        return {"events": [e.to_dict() for e in self.events]}

    def to_json_timeline(self):
        return {"events": []}


@pytest.fixture
def setup():
    mcp = MagicMock()
    searcher = MagicMock()
    tools = _capture_tools(mcp, searcher)
    return tools


# ============================================================
# build_research_timeline
# ============================================================

class TestBuildResearchTimeline:
    @pytest.mark.asyncio
    async def test_success_text(self, setup):
        tools = setup
        with patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.TimelineBuilder"
        ) as MockBuilder:
            instance = MockBuilder.return_value
            instance.build_timeline = AsyncMock(return_value=_FakeTimeline())
            # Re-capture with mocked builder
            mcp = MagicMock()
            searcher = MagicMock()
            _tools2 = _capture_tools(mcp, searcher)
            # Tools use the builder created during registration, need to patch differently

        # Direct approach: patch the builder instance's method
        # Since builder is created inside register_timeline_tools, we need to
        # patch TimelineBuilder before registration
        mcp = MagicMock()
        searcher = MagicMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.TimelineBuilder"
        ) as MockTB, patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.MilestoneDetector"
        ):
            mock_builder = MockTB.return_value
            mock_builder.build_timeline = AsyncMock(return_value=_FakeTimeline())
            tools = _capture_tools(mcp, searcher)

        result = await tools["build_research_timeline"](topic="test drug")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_no_events(self):
        mcp = MagicMock()
        searcher = MagicMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.TimelineBuilder"
        ) as MockTB, patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.MilestoneDetector"
        ):
            mock_builder = MockTB.return_value
            mock_builder.build_timeline = AsyncMock(return_value=_FakeTimeline(empty=True))
            tools = _capture_tools(mcp, searcher)

        result = await tools["build_research_timeline"](topic="zzznonexistent")
        assert "no" in result.lower() or "suggest" in result.lower()

    @pytest.mark.asyncio
    async def test_mermaid_format(self):
        mcp = MagicMock()
        searcher = MagicMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.TimelineBuilder"
        ) as MockTB, patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.MilestoneDetector"
        ):
            mock_builder = MockTB.return_value
            mock_builder.build_timeline = AsyncMock(return_value=_FakeTimeline())
            tools = _capture_tools(mcp, searcher)

        result = await tools["build_research_timeline"](
            topic="test", output_format="mermaid"
        )
        assert "gantt" in result

    @pytest.mark.asyncio
    async def test_json_format(self):
        mcp = MagicMock()
        searcher = MagicMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.TimelineBuilder"
        ) as MockTB, patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.MilestoneDetector"
        ):
            mock_builder = MockTB.return_value
            mock_builder.build_timeline = AsyncMock(return_value=_FakeTimeline())
            tools = _capture_tools(mcp, searcher)

        result = await tools["build_research_timeline"](
            topic="test", output_format="json"
        )
        parsed = json.loads(result)
        assert "events" in parsed

    @pytest.mark.asyncio
    async def test_exception(self):
        mcp = MagicMock()
        searcher = MagicMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.TimelineBuilder"
        ) as MockTB, patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.MilestoneDetector"
        ):
            mock_builder = MockTB.return_value
            mock_builder.build_timeline = AsyncMock(side_effect=RuntimeError("fail"))
            tools = _capture_tools(mcp, searcher)

        result = await tools["build_research_timeline"](topic="test")
        assert "error" in result.lower()


# ============================================================
# build_timeline_from_pmids
# ============================================================

class TestBuildTimelineFromPmids:
    @pytest.mark.asyncio
    async def test_empty_pmids(self):
        mcp = MagicMock()
        searcher = MagicMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.TimelineBuilder"
        ) as _MockTB, patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.MilestoneDetector"
        ):
            tools = _capture_tools(mcp, searcher)

        result = await tools["build_timeline_from_pmids"](pmids="")
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_success(self):
        mcp = MagicMock()
        searcher = MagicMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.TimelineBuilder"
        ) as MockTB, patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.MilestoneDetector"
        ):
            mock_builder = MockTB.return_value
            mock_builder.build_timeline_from_pmids = AsyncMock(
                return_value=_FakeTimeline()
            )
            tools = _capture_tools(mcp, searcher)

        result = await tools["build_timeline_from_pmids"](
            pmids="111,222,333", topic="My Study"
        )
        assert isinstance(result, str)


# ============================================================
# analyze_timeline_milestones
# ============================================================

class TestAnalyzeTimelineMilestones:
    @pytest.mark.asyncio
    async def test_success(self):
        events = [
            _FakeEvent(pmid="1", year=2020, citation_count=100),
            _FakeEvent(pmid="2", year=2022, citation_count=5),
        ]
        mcp = MagicMock()
        searcher = MagicMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.TimelineBuilder"
        ) as MockTB, patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.MilestoneDetector"
        ):
            mock_builder = MockTB.return_value
            mock_builder.build_timeline = AsyncMock(
                return_value=_FakeTimeline(events=events)
            )
            tools = _capture_tools(mcp, searcher)

        result = await tools["analyze_timeline_milestones"](topic="test")
        parsed = json.loads(result)
        assert parsed["total_milestones"] == 2
        assert "landmark_studies" in parsed

    @pytest.mark.asyncio
    async def test_no_events(self):
        mcp = MagicMock()
        searcher = MagicMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.TimelineBuilder"
        ) as MockTB, patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.MilestoneDetector"
        ):
            mock_builder = MockTB.return_value
            mock_builder.build_timeline = AsyncMock(
                return_value=_FakeTimeline(empty=True)
            )
            tools = _capture_tools(mcp, searcher)

        result = await tools["analyze_timeline_milestones"](topic="zzz")
        assert "no" in result.lower() or "suggest" in result.lower()


# ============================================================
# get_timeline_visualization
# ============================================================

class TestGetTimelineVisualization:
    @pytest.mark.asyncio
    async def test_mermaid(self):
        mcp = MagicMock()
        searcher = MagicMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.TimelineBuilder"
        ) as MockTB, patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.MilestoneDetector"
        ):
            mock_builder = MockTB.return_value
            mock_builder.build_timeline = AsyncMock(return_value=_FakeTimeline())
            tools = _capture_tools(mcp, searcher)

        result = await tools["get_timeline_visualization"](
            topic="test", format="mermaid"
        )
        assert "gantt" in result

    @pytest.mark.asyncio
    async def test_unknown_format(self):
        mcp = MagicMock()
        searcher = MagicMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.TimelineBuilder"
        ) as MockTB, patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.MilestoneDetector"
        ):
            mock_builder = MockTB.return_value
            mock_builder.build_timeline = AsyncMock(return_value=_FakeTimeline())
            tools = _capture_tools(mcp, searcher)

        result = await tools["get_timeline_visualization"](
            topic="test", format="unknown"
        )
        assert "Unknown format" in result

    @pytest.mark.asyncio
    async def test_no_events(self):
        mcp = MagicMock()
        searcher = MagicMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.TimelineBuilder"
        ) as MockTB, patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.MilestoneDetector"
        ):
            mock_builder = MockTB.return_value
            mock_builder.build_timeline = AsyncMock(return_value=_FakeTimeline(empty=True))
            tools = _capture_tools(mcp, searcher)

        result = await tools["get_timeline_visualization"](topic="zzz")
        assert "no events" in result.lower() or "No events" in result


# ============================================================
# list_milestone_patterns
# ============================================================

class TestListMilestonePatterns:
    def test_returns_markdown(self):
        mcp = MagicMock()
        searcher = MagicMock()
        tools = _capture_tools(mcp, searcher)

        result = tools["list_milestone_patterns"]()
        assert "Milestone Detection Patterns" in result
        assert "confidence" in result.lower()


# ============================================================
# compare_timelines
# ============================================================

class TestCompareTimelines:
    @pytest.mark.asyncio
    async def test_less_than_2_topics(self):
        mcp = MagicMock()
        searcher = MagicMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.TimelineBuilder"
        ) as _MockTB, patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.MilestoneDetector"
        ):
            tools = _capture_tools(mcp, searcher)

        result = await tools["compare_timelines"](topics="single_topic")
        assert "error" in result.lower() or "2 topics" in result

    @pytest.mark.asyncio
    async def test_too_many_topics(self):
        mcp = MagicMock()
        searcher = MagicMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.TimelineBuilder"
        ) as _MockTB, patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.MilestoneDetector"
        ):
            tools = _capture_tools(mcp, searcher)

        result = await tools["compare_timelines"](topics="a,b,c,d,e,f")
        assert "5" in result or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_success(self):
        mcp = MagicMock()
        searcher = MagicMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.TimelineBuilder"
        ) as MockTB, patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.MilestoneDetector"
        ):
            mock_builder = MockTB.return_value
            mock_builder.build_timeline = AsyncMock(return_value=_FakeTimeline())
            tools = _capture_tools(mcp, searcher)

        result = await tools["compare_timelines"](
            topics="drugA,drugB", max_events_per_topic=5
        )
        parsed = json.loads(result)
        assert len(parsed["topics"]) == 2
        assert "summary" in parsed

    @pytest.mark.asyncio
    async def test_exception(self):
        mcp = MagicMock()
        searcher = MagicMock()
        with patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.TimelineBuilder"
        ) as MockTB, patch(
            "pubmed_search.presentation.mcp_server.tools.timeline.MilestoneDetector"
        ):
            mock_builder = MockTB.return_value
            mock_builder.build_timeline = AsyncMock(side_effect=RuntimeError("fail"))
            tools = _capture_tools(mcp, searcher)

        result = await tools["compare_timelines"](topics="a,b")
        assert "error" in result.lower()
