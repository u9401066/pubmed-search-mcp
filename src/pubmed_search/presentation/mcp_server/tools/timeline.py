"""
Timeline MCP Tools - Research Timeline Exploration

Provides tools for building and exploring research timelines:
- build_research_timeline: Build timeline from topic OR specific PMIDs
- analyze_timeline_milestones: Analyze milestone distribution
- compare_timelines: Compare multiple topics

Removed tools (v0.3.1):
- build_timeline_from_pmids → merged into build_research_timeline (use pmids param)
- get_timeline_visualization → use build_research_timeline with output_format
- list_milestone_patterns → converted to MCP Resource

These tools enable AI agents to:
1. Understand the temporal evolution of research
2. Identify key milestones in drug/gene/disease research
3. Visualize research progression
4. Trace knowledge development over time
"""

import json
import logging

from mcp.server.fastmcp import FastMCP

from pubmed_search.application.timeline import MilestoneDetector, TimelineBuilder
from pubmed_search.application.timeline.timeline_builder import format_timeline_text
from pubmed_search.infrastructure.ncbi import LiteratureSearcher

from ._common import InputNormalizer, ResponseFormatter

logger = logging.getLogger(__name__)


def register_timeline_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """Register timeline exploration tools (3 tools)."""

    # Create shared instances
    detector = MilestoneDetector()
    builder = TimelineBuilder(searcher, detector)

    @mcp.tool()
    async def build_research_timeline(
        topic: str | None = None,
        pmids: str | None = None,
        max_events: int = 30,
        min_year: int | None = None,
        max_year: int | None = None,
        include_all: bool = False,
        output_format: str = "text",
    ) -> str:
        """
        Build a research timeline for a topic OR specific PMIDs.

        ═══════════════════════════════════════════════════════════════
        🎯 TWO MODES OF OPERATION
        ═══════════════════════════════════════════════════════════════

        Mode 1: Search by topic (default)
            build_research_timeline(topic="remimazolam")

        Mode 2: Build from specific PMIDs
            build_research_timeline(pmids="12345678,23456789", topic="My Timeline")

        ═══════════════════════════════════════════════════════════════
        MILESTONE DETECTION
        ═══════════════════════════════════════════════════════════════

        Automatically detects significant milestones including:
        - First reports and mechanism discoveries
        - Clinical trial phases (Phase 1/2/3/4)
        - FDA/EMA approvals
        - Meta-analyses and systematic reviews
        - Guidelines and consensus statements
        - Safety alerts and label updates
        - High-impact landmark studies

        ═══════════════════════════════════════════════════════════════
        OUTPUT FORMATS (output_format parameter)
        ═══════════════════════════════════════════════════════════════

        - "text": Human-readable text format (default)
        - "mermaid": Mermaid timeline (VS Code, GitHub preview)
        - "json": Full JSON data
        - "timeline_js": TimelineJS library format
        - "d3": D3.js visualization format

        Args:
            topic: Research topic (drug name, gene, disease, etc.)
                   Required if pmids not provided.
                   Examples: "remimazolam", "BRCA1", "pembrolizumab melanoma"
            pmids: Comma-separated PMIDs or "last" for previous search results
                   If provided, builds timeline from these specific articles.
                   Example: "12345678,23456789,34567890"
            max_events: Maximum number of events to include (default: 30)
            min_year: Filter articles from this year (optional, topic mode only)
            max_year: Filter articles until this year (optional, topic mode only)
            include_all: Include non-milestone articles as generic events
            output_format: "text", "mermaid", "json", "timeline_js", or "d3"

        Returns:
            Research timeline with detected milestones in requested format.

        Examples:
            # By topic
            build_research_timeline(topic="remimazolam", max_events=20)
            build_research_timeline(topic="CAR-T therapy", min_year=2015, output_format="mermaid")

            # By PMIDs
            build_research_timeline(pmids="12345678,23456789", topic="Propofol Studies")
            build_research_timeline(pmids="last", topic="Previous Search", output_format="json")
        """
        try:
            # Determine mode: PMIDs or topic search
            if pmids:
                # Mode 2: Build from specific PMIDs
                pmid_list = InputNormalizer.normalize_pmids(pmids)
                if not pmid_list:
                    return ResponseFormatter.error(
                        error="No valid PMIDs provided",
                        suggestion="Use comma-separated PMIDs or 'last' for previous search",
                        tool_name="build_research_timeline",
                    )

                timeline = await builder.build_timeline_from_pmids(
                    pmids=pmid_list,
                    topic=topic or "Custom Timeline",
                )
            elif topic:
                # Mode 1: Search by topic
                timeline = await builder.build_timeline(
                    topic=topic,
                    max_events=max_events,
                    min_year=min_year,
                    max_year=max_year,
                    include_all=include_all,
                )
            else:
                return ResponseFormatter.error(
                    error="Must provide either 'topic' or 'pmids'",
                    suggestion="Examples: topic='remimazolam' OR pmids='12345678,23456789'",
                    tool_name="build_research_timeline",
                )

            if not timeline.events:
                return ResponseFormatter.no_results(
                    query=topic or "provided PMIDs",
                    suggestions=[
                        "Try a more specific topic",
                        "Check spelling",
                        "Try broader date range",
                    ],
                )

            # Format output
            if output_format == "mermaid":
                return timeline.to_mermaid()
            elif output_format == "json":
                return json.dumps(timeline.to_dict(), indent=2, ensure_ascii=False)
            elif output_format == "timeline_js":
                return json.dumps(timeline.to_json_timeline(), indent=2)
            elif output_format == "d3":
                d3_data = {
                    "nodes": [
                        {
                            "id": e.pmid,
                            "year": e.year,
                            "label": e.milestone_label,
                            "type": e.milestone_type.value,
                            "title": e.title,
                        }
                        for e in timeline.events
                    ]
                }
                return json.dumps(d3_data, indent=2)
            else:
                return format_timeline_text(timeline)

        except Exception as e:
            logger.error(f"Timeline build failed: {e}")
            return ResponseFormatter.error(
                error=str(e),
                suggestion="Try a simpler topic or check network connection",
                tool_name="build_research_timeline",
            )

    @mcp.tool()
    async def analyze_timeline_milestones(
        topic: str,
        max_results: int = 100,
    ) -> str:
        """
        Analyze milestone distribution for a research topic.

        Provides statistics on:
        - Milestone type distribution
        - Temporal patterns (which years had most activity)
        - Evidence quality breakdown
        - Key high-impact studies

        Args:
            topic: Research topic to analyze
            max_results: Maximum articles to analyze

        Returns:
            Detailed analysis of milestone patterns.

        Example:
            analyze_timeline_milestones("remdesivir COVID-19")
        """
        try:
            timeline = await builder.build_timeline(
                topic=topic,
                max_events=max_results,
                include_all=False,
            )

            if not timeline.events:
                return ResponseFormatter.no_results(
                    query=topic,
                    suggestions=["Try different search terms"],
                )

            # Build analysis
            analysis = {
                "topic": topic,
                "total_milestones": timeline.total_events,
                "year_range": timeline.year_range,
                "duration_years": timeline.duration_years,
                "milestone_distribution": timeline.milestone_summary,
                "periods": [p.to_dict() for p in timeline.periods],
            }

            # Find landmark studies
            landmarks = timeline.get_landmark_events(min_citations=50)
            if landmarks:
                analysis["landmark_studies"] = [
                    {
                        "pmid": e.pmid,
                        "year": e.year,
                        "title": e.title[:100],
                        "citations": e.citation_count,
                    }
                    for e in landmarks[:5]
                ]

            # Events by year (activity pattern)
            years = {}
            for event in timeline.events:
                years[event.year] = years.get(event.year, 0) + 1
            analysis["activity_by_year"] = dict(sorted(years.items()))

            return json.dumps(analysis, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.error(f"Milestone analysis failed: {e}")
            return ResponseFormatter.error(error=str(e), tool_name="analyze_timeline_milestones")

    @mcp.tool()
    async def compare_timelines(
        topics: str,
        max_events_per_topic: int = 15,
    ) -> str:
        """
        Compare research timelines of multiple topics.

        Useful for:
        - Comparing drug development timelines
        - Contrasting research evolution across conditions
        - Understanding parallel research tracks

        Args:
            topics: Comma-separated topics to compare
                    Example: "remimazolam,propofol,dexmedetomidine"
            max_events_per_topic: Maximum events per topic

        Returns:
            Comparative analysis of the timelines.

        Example:
            compare_timelines("remimazolam,propofol", max_events_per_topic=10)
        """
        try:
            topic_list = [t.strip() for t in topics.split(",") if t.strip()]

            if len(topic_list) < 2:
                return ResponseFormatter.error(
                    error="Need at least 2 topics to compare",
                    suggestion="Separate topics with commas",
                    tool_name="compare_timelines",
                )

            if len(topic_list) > 5:
                return ResponseFormatter.error(
                    error="Maximum 5 topics for comparison",
                    tool_name="compare_timelines",
                )

            comparison = {"topics": [], "summary": {}}

            for topic in topic_list:
                timeline = await builder.build_timeline(
                    topic=topic,
                    max_events=max_events_per_topic,
                )

                topic_data = {
                    "topic": topic,
                    "total_events": timeline.total_events,
                    "year_range": timeline.year_range,
                    "duration_years": timeline.duration_years,
                    "milestone_summary": timeline.milestone_summary,
                    "first_event": timeline.events[0].to_dict() if timeline.events else None,
                    "latest_event": timeline.events[-1].to_dict() if timeline.events else None,
                }
                comparison["topics"].append(topic_data)

            # Generate comparison summary
            comparison["summary"] = {
                "earliest_research": min(
                    (t["year_range"][0] for t in comparison["topics"] if t["year_range"]),
                    default=None,
                ),
                "most_milestones": max(
                    comparison["topics"],
                    key=lambda t: t["total_events"],
                )["topic"],
                "longest_timeline": max(
                    comparison["topics"],
                    key=lambda t: t["duration_years"],
                )["topic"],
            }

            return json.dumps(comparison, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.error(f"Timeline comparison failed: {e}")
            return ResponseFormatter.error(error=str(e), tool_name="compare_timelines")

    logger.info("Registered 3 timeline tools")
