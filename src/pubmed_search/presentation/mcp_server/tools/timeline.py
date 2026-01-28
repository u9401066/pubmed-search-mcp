"""
Timeline MCP Tools - Research Timeline Exploration

Provides tools for building and exploring research timelines:
- build_research_timeline: Build timeline from a topic
- build_timeline_from_pmids: Build timeline from specific articles
- get_timeline_milestones: Get detected milestones
- format_timeline_mermaid: Generate Mermaid visualization
- format_timeline_json: Generate JSON for visualization libraries
- get_milestone_patterns: View detection patterns

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
from pubmed_search.application.timeline.milestone_detector import get_milestone_patterns
from pubmed_search.application.timeline.timeline_builder import format_timeline_text
from pubmed_search.infrastructure.ncbi import LiteratureSearcher

from ._common import InputNormalizer, ResponseFormatter

logger = logging.getLogger(__name__)


def register_timeline_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """Register timeline exploration tools."""

    # Create shared instances
    detector = MilestoneDetector()
    builder = TimelineBuilder(searcher, detector)

    @mcp.tool()
    async def build_research_timeline(
        topic: str,
        max_events: int = 30,
        min_year: int | None = None,
        max_year: int | None = None,
        include_all: bool = False,
        output_format: str = "text",
    ) -> str:
        """
        Build a research timeline for a topic showing key milestones.

        Automatically detects significant milestones including:
        - First reports and mechanism discoveries
        - Clinical trial phases (Phase 1/2/3/4)
        - FDA/EMA approvals
        - Meta-analyses and systematic reviews
        - Guidelines and consensus statements
        - Safety alerts and label updates
        - High-impact landmark studies

        Args:
            topic: Research topic (drug name, gene, disease, etc.)
                   Examples: "remimazolam", "BRCA1", "pembrolizumab melanoma"
            max_events: Maximum number of events to include (default: 30)
            min_year: Filter articles from this year (optional)
            max_year: Filter articles until this year (optional)
            include_all: Include non-milestone articles as generic events
            output_format: Output format - "text", "mermaid", "json"

        Returns:
            Research timeline with detected milestones in requested format.

        Example:
            build_research_timeline("remimazolam", max_events=20)
            build_research_timeline("CAR-T therapy", min_year=2015, output_format="mermaid")
        """
        try:
            timeline = await builder.build_timeline(
                topic=topic,
                max_events=max_events,
                min_year=min_year,
                max_year=max_year,
                include_all=include_all,
            )

            if not timeline.events:
                return ResponseFormatter.no_results(
                    query=topic,
                    suggestions=[
                        "Try a more specific topic",
                        "Check spelling",
                        "Try broader date range",
                    ],
                )

            if output_format == "mermaid":
                return timeline.to_mermaid()
            elif output_format == "json":
                return json.dumps(timeline.to_dict(), indent=2, ensure_ascii=False)
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
    async def build_timeline_from_pmids(
        pmids: str,
        topic: str = "Custom Timeline",
        output_format: str = "text",
    ) -> str:
        """
        Build a timeline from a specific list of PMIDs.

        Useful when you have pre-selected articles and want to
        see their temporal relationship and milestones.

        Args:
            pmids: Comma-separated PMIDs or "last" for previous search results
                   Example: "12345678,23456789,34567890"
            topic: Name for the timeline (for display purposes)
            output_format: "text", "mermaid", or "json"

        Returns:
            Timeline showing milestones in the provided articles.

        Example:
            build_timeline_from_pmids("12345678,23456789,34567890", "Propofol Studies")
        """
        try:
            pmid_list = InputNormalizer.normalize_pmids(pmids)

            if not pmid_list:
                return ResponseFormatter.error(
                    error="No valid PMIDs provided",
                    suggestion="Use comma-separated PMIDs or 'last' for previous search",
                    tool_name="build_timeline_from_pmids",
                )

            timeline = await builder.build_timeline_from_pmids(
                pmids=pmid_list,
                topic=topic,
            )

            if not timeline.events:
                return ResponseFormatter.no_results(
                    query="provided PMIDs",
                    suggestions=["These may be regular studies without clear milestones"],
                )

            if output_format == "mermaid":
                return timeline.to_mermaid()
            elif output_format == "json":
                return json.dumps(timeline.to_dict(), indent=2, ensure_ascii=False)
            else:
                return format_timeline_text(timeline)

        except Exception as e:
            logger.error(f"Timeline from PMIDs failed: {e}")
            return ResponseFormatter.error(error=str(e), tool_name="build_timeline_from_pmids")

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
    async def get_timeline_visualization(
        topic: str,
        format: str = "mermaid",
        max_events: int = 20,
    ) -> str:
        """
        Generate timeline visualization code.

        Supports multiple visualization formats:
        - mermaid: Mermaid timeline (renders in VS Code, GitHub, etc.)
        - timeline_js: JSON for TimelineJS library
        - d3: JSON for D3.js visualization

        Args:
            topic: Research topic
            format: Visualization format (mermaid, timeline_js, d3)
            max_events: Maximum events to include

        Returns:
            Visualization code in requested format.

        Example:
            get_timeline_visualization("CRISPR gene therapy", format="mermaid")
        """
        try:
            timeline = await builder.build_timeline(
                topic=topic,
                max_events=max_events,
            )

            if not timeline.events:
                return f"No events found for visualization of: {topic}"

            if format == "mermaid":
                return timeline.to_mermaid()
            elif format == "timeline_js":
                return json.dumps(timeline.to_json_timeline(), indent=2)
            elif format == "d3":
                # D3-friendly format
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
                return f"Unknown format: {format}. Use: mermaid, timeline_js, or d3"

        except Exception as e:
            logger.error(f"Visualization failed: {e}")
            return ResponseFormatter.error(error=str(e), tool_name="get_timeline_visualization")

    @mcp.tool()
    def list_milestone_patterns() -> str:
        """
        List all milestone detection patterns.

        Shows the regex patterns used to identify different types
        of research milestones. Useful for understanding how
        milestones are detected and for debugging.

        Returns:
            List of patterns with their milestone types and confidence scores.
        """
        patterns = get_milestone_patterns()

        lines = [
            "## Milestone Detection Patterns",
            "",
            "These patterns are used to identify research milestones:",
            "",
        ]

        # Group by milestone type
        by_type: dict[str, list] = {}
        for p in patterns:
            m_type = p["milestone_type"]
            if m_type not in by_type:
                by_type[m_type] = []
            by_type[m_type].append(p)

        for m_type, type_patterns in sorted(by_type.items()):
            lines.append(f"### {m_type.replace('_', ' ').title()}")
            for p in type_patterns:
                lines.append(f"- **{p['label']}** (confidence: {p['confidence']:.0%})")
                lines.append(f"  - Pattern: `{p['pattern']}`")
            lines.append("")

        return "\n".join(lines)

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

    logger.info("Registered 6 timeline tools")
