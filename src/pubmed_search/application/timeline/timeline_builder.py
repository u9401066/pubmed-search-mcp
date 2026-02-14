"""
Timeline Builder - Construct Research Timelines from Search Results

Orchestrates the timeline building process:
1. Search for articles on a topic
2. Detect milestones in each article
3. Aggregate into a ResearchTimeline
4. Generate visualizations

Example:
    >>> builder = TimelineBuilder(searcher)
    >>> timeline = builder.build_timeline("remimazolam", max_events=50)
    >>> print(timeline.to_mermaid())
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pubmed_search.domain.entities.timeline import (
    MilestoneType,
    ResearchTimeline,
    TimelineEvent,
    TimelinePeriod,
)

from .milestone_detector import MilestoneDetector

if TYPE_CHECKING:
    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)


# Period definitions for auto-grouping
DEFAULT_PERIODS = [
    (
        "Discovery",
        [
            MilestoneType.FIRST_REPORT,
            MilestoneType.MECHANISM_DISCOVERY,
            MilestoneType.PRECLINICAL,
        ],
    ),
    (
        "Clinical Development",
        [MilestoneType.PHASE_1, MilestoneType.PHASE_2, MilestoneType.PHASE_3],
    ),
    (
        "Regulatory",
        [
            MilestoneType.FDA_APPROVAL,
            MilestoneType.EMA_APPROVAL,
            MilestoneType.REGULATORY_APPROVAL,
        ],
    ),
    (
        "Evidence Synthesis",
        [
            MilestoneType.META_ANALYSIS,
            MilestoneType.SYSTEMATIC_REVIEW,
            MilestoneType.GUIDELINE,
        ],
    ),
    (
        "Post-Market",
        [MilestoneType.PHASE_4, MilestoneType.SAFETY_ALERT, MilestoneType.LABEL_UPDATE],
    ),
]


class TimelineBuilder:
    """
    Build research timelines from literature search.

    Combines search, milestone detection, and timeline construction
    into a cohesive workflow.
    """

    def __init__(
        self,
        searcher: LiteratureSearcher,
        detector: MilestoneDetector | None = None,
    ):
        """
        Initialize the builder.

        Args:
            searcher: LiteratureSearcher instance for PubMed queries
            detector: Optional custom MilestoneDetector
        """
        self.searcher = searcher
        self.detector = detector or MilestoneDetector()

    async def build_timeline(
        self,
        topic: str,
        max_events: int = 50,
        include_all: bool = False,
        min_year: int | None = None,
        max_year: int | None = None,
        sort_by_citations: bool = True,
        auto_periods: bool = True,
    ) -> ResearchTimeline:
        """
        Build a research timeline for a topic.

        Args:
            topic: Research topic (drug name, gene, disease, etc.)
            max_events: Maximum events to include in timeline
            include_all: If True, include non-milestone articles
            min_year: Filter articles from this year
            max_year: Filter articles until this year
            sort_by_citations: Sort results by citation count first
            auto_periods: Automatically group into periods

        Returns:
            ResearchTimeline with detected milestones
        """
        logger.info(f"Building timeline for: {topic}")

        # Step 1: Search for articles
        articles = await self._search_topic(
            topic,
            max_results=max_events * 3,  # Fetch more, filter to milestones
            sort_by_citations=sort_by_citations,
        )

        if not articles:
            logger.warning(f"No articles found for: {topic}")
            return ResearchTimeline(topic=topic)

        logger.info(f"Found {len(articles)} articles for: {topic}")

        # Step 2: Filter by year if specified
        if min_year or max_year:
            articles = self._filter_by_year(articles, min_year, max_year)

        # Step 3: Detect milestones
        events: list[TimelineEvent] = []

        # Sort for first-report detection (ensure year is int for proper comparison)
        def get_sort_key(a: dict) -> tuple:
            raw_year = a.get("year") or a.get("pub_year") or 9999
            year = int(raw_year) if raw_year else 9999
            return (year, str(a.get("pmid", "")))

        sorted_articles = sorted(articles, key=get_sort_key)

        for i, article in enumerate(sorted_articles):
            is_first = i == 0
            event = self.detector.detect_milestone(article, is_first=is_first)

            if event:
                events.append(event)
            elif include_all:
                # Include as generic event
                events.append(self._create_generic_event(article))

            if len(events) >= max_events:
                break

        logger.info(f"Detected {len(events)} timeline events")

        # Step 4: Build timeline
        timeline = ResearchTimeline(
            topic=topic,
            events=events,
            metadata={
                "total_searched": len(articles),
                "milestones_detected": len(events),
                "min_year": min_year,
                "max_year": max_year,
            },
        )

        # Step 5: Auto-group into periods if requested
        if auto_periods and events:
            timeline.periods = self._create_periods(events)

        return timeline

    async def build_timeline_from_pmids(
        self,
        pmids: list[str],
        topic: str = "Custom Timeline",
        auto_periods: bool = True,
    ) -> ResearchTimeline:
        """
        Build timeline from a list of PMIDs.

        Useful when user has pre-selected articles.

        Args:
            pmids: List of PubMed IDs
            topic: Timeline topic name
            auto_periods: Automatically group into periods

        Returns:
            ResearchTimeline with detected milestones
        """
        if not pmids:
            return ResearchTimeline(topic=topic)

        # Fetch article details
        articles = await self.searcher.fetch_details(pmids)

        if not articles:
            return ResearchTimeline(topic=topic)

        # Detect milestones
        events = self.detector.detect_milestones_batch(articles)

        timeline = ResearchTimeline(
            topic=topic,
            events=events,
            metadata={"source": "pmid_list", "pmid_count": len(pmids)},
        )

        if auto_periods and events:
            timeline.periods = self._create_periods(events)

        return timeline

    async def _search_topic(
        self,
        topic: str,
        max_results: int = 150,
        sort_by_citations: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Search for articles on a topic.

        Uses PubMed search with citation-based sorting when available.
        """
        # Use searcher to get articles
        try:
            results = await self.searcher.search(topic, limit=max_results)

            # If we want citation sorting and have iCite access
            if sort_by_citations and results:
                pmids = [str(r.get("pmid", "")) for r in results if r.get("pmid")]
                if pmids:
                    try:
                        # Try to get citation data
                        citation_data = await self.searcher.get_citation_metrics(pmids)
                        if citation_data:
                            # Map citations to articles (citation_data is dict[pmid, metrics])
                            citation_map: dict[str, int] = {
                                pmid_key: metrics.get("citation_count", 0)
                                for pmid_key, metrics in citation_data.items()
                            }
                            for article in results:
                                pmid = str(article.get("pmid", ""))
                                article["citation_count"] = citation_map.get(pmid, 0)

                            # Sort by citations
                            results.sort(key=lambda x: x.get("citation_count", 0), reverse=True)
                    except Exception as e:
                        logger.debug(f"Citation sorting failed: {e}")

            return results

        except Exception as e:
            logger.exception(f"Search failed for {topic}: {e}")
            return []

    def _filter_by_year(
        self,
        articles: list[dict[str, Any]],
        min_year: int | None,
        max_year: int | None,
    ) -> list[dict[str, Any]]:
        """Filter articles by publication year."""
        filtered = []
        for article in articles:
            raw_year = article.get("year") or article.get("pub_year")
            if not raw_year:
                continue
            # Ensure int for comparison (BioPython may return StringElement)
            year = int(raw_year)
            if min_year and year < min_year:
                continue
            if max_year and year > max_year:
                continue
            filtered.append(article)
        return filtered

    def _create_generic_event(self, article: dict[str, Any]) -> TimelineEvent:
        """Create a generic event for non-milestone articles."""
        pmid = str(article.get("pmid", ""))

        # Ensure year is int (BioPython may return StringElement)
        raw_year = article.get("year") or article.get("pub_year") or 0
        year = int(raw_year) if raw_year else 0

        # Parse month (may be string like "Jan" or int)
        raw_month = article.get("month") or article.get("pub_month")
        month = self._parse_month(raw_month)

        authors = article.get("authors", [])
        first_author = None
        if authors:
            if isinstance(authors[0], dict):
                first_author = authors[0].get("name") or authors[0].get("full_name")
            else:
                first_author = str(authors[0])

        return TimelineEvent(
            pmid=pmid,
            year=year,
            month=month,
            milestone_type=MilestoneType.OTHER,
            title=article.get("title", ""),
            milestone_label="Study",
            journal=article.get("journal") or article.get("source"),
            first_author=first_author,
            doi=article.get("doi"),
            citation_count=article.get("citation_count", 0),
            confidence_score=0.0,
        )

    def _parse_month(self, raw_month: Any) -> int | None:
        """Parse month from various formats (int, string name, string number)."""
        if not raw_month:
            return None

        # If already int
        if isinstance(raw_month, int):
            return raw_month if 1 <= raw_month <= 12 else None

        # Convert to string
        month_str = str(raw_month).strip()

        # Try numeric
        try:
            month_int = int(month_str)
            return month_int if 1 <= month_int <= 12 else None
        except ValueError:
            pass

        # Month name mapping
        month_names = {
            "jan": 1,
            "january": 1,
            "feb": 2,
            "february": 2,
            "mar": 3,
            "march": 3,
            "apr": 4,
            "april": 4,
            "may": 5,
            "jun": 6,
            "june": 6,
            "jul": 7,
            "july": 7,
            "aug": 8,
            "august": 8,
            "sep": 9,
            "sept": 9,
            "september": 9,
            "oct": 10,
            "october": 10,
            "nov": 11,
            "november": 11,
            "dec": 12,
            "december": 12,
        }

        return month_names.get(month_str.lower())

    def _create_periods(self, events: list[TimelineEvent]) -> list[TimelinePeriod]:
        """
        Auto-group events into research periods.

        Uses milestone type to categorize, then determines year ranges.
        """
        periods: list[TimelinePeriod] = []

        for period_name, milestone_types in DEFAULT_PERIODS:
            period_events = [e for e in events if e.milestone_type in milestone_types]

            if period_events:
                years = [e.year for e in period_events]
                periods.append(
                    TimelinePeriod(
                        name=period_name,
                        start_year=min(years),
                        end_year=max(years),
                        events=sorted(period_events, key=lambda e: e.sort_key),
                    )
                )

        # Sort periods by start year
        periods.sort(key=lambda p: p.start_year)

        return periods


def format_timeline_text(timeline: ResearchTimeline) -> str:
    """
    Format timeline as readable text.

    Useful for agent response formatting.
    """
    if not timeline.events:
        return f"No timeline events found for: {timeline.topic}"

    lines = [
        f"## Research Timeline: {timeline.topic}",
        f"**Period**: {timeline.year_range[0]} - {timeline.year_range[1]} ({timeline.duration_years} years)"
        if timeline.year_range
        else "",
        f"**Total Events**: {timeline.total_events}",
        "",
        "### Milestone Summary",
    ]

    # Add milestone counts
    for m_type, count in timeline.milestone_summary.items():
        lines.append(f"- {m_type.replace('_', ' ').title()}: {count}")

    lines.append("")
    lines.append("### Events")

    # Group by year for readability
    current_year = None
    for event in timeline.events:
        if event.year != current_year:
            current_year = event.year
            lines.append(f"\n**{current_year}**")

        confidence_indicator = "⭐" if event.confidence_score >= 0.8 else ""
        lines.append(
            f"- [{event.milestone_label}] {event.title[:80]}{'...' if len(event.title) > 80 else ''} "
            f"(PMID: {event.pmid}) {confidence_indicator}"
        )

    return "\n".join(lines)
