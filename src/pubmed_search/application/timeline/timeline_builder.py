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
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from pubmed_search.domain.entities.timeline import (
    LandmarkScore,
    MilestoneType,
    ResearchTimeline,
    TimelineEvent,
    TimelinePeriod,
)

from .landmark_scorer import LandmarkScorer, evidence_level_to_score
from .milestone_detector import MilestoneDetector

if TYPE_CHECKING:
    from pubmed_search.domain.entities.research_tree import ResearchTree
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
        scorer: LandmarkScorer | None = None,
    ):
        """
        Initialize the builder.

        Args:
            searcher: LiteratureSearcher instance for PubMed queries
            detector: Optional custom MilestoneDetector
            scorer: Optional custom LandmarkScorer
        """
        self.searcher = searcher
        self.detector = detector or MilestoneDetector()
        self.scorer = scorer or LandmarkScorer()

    async def build_timeline(
        self,
        topic: str,
        max_events: int = 50,
        include_all: bool = False,
        min_year: int | None = None,
        max_year: int | None = None,
        sort_by_citations: bool = True,
        auto_periods: bool = True,
        highlight_landmarks: bool = True,
        source_counts: dict[str, int] | None = None,
    ) -> ResearchTimeline:
        """
        Build a research timeline for a topic.

        When highlight_landmarks=True (default), uses multi-signal landmark
        scoring to identify the most important papers:
        - Field-normalized citation impact (RCR/NIH percentile from iCite)
        - Milestone pattern detection (regex-based)
        - Evidence quality (publication type hierarchy)
        - Citation velocity (citations per year growth)
        - Multi-source agreement (if source_counts provided)

        Args:
            topic: Research topic (drug name, gene, disease, etc.)
            max_events: Maximum events to include in timeline
            include_all: If True, include non-milestone articles
            min_year: Filter articles from this year
            max_year: Filter articles until this year
            sort_by_citations: Sort results by citation count first
            auto_periods: Automatically group into periods
            highlight_landmarks: Use multi-signal landmark scoring (default: True)
            source_counts: Optional dict mapping PMID → number of sources
                           that found this article (from unified search)

        Returns:
            ResearchTimeline with detected milestones and landmark scores
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

        # Step 3: Compute landmark scores (if enabled)
        landmark_map: dict[str, LandmarkScore] = {}
        if highlight_landmarks and articles:
            landmark_map = self._compute_landmark_scores(articles, source_counts=source_counts)
            # Sort by landmark score to prioritize important articles
            articles = sorted(
                articles,
                key=lambda a: landmark_map.get(str(a.get("pmid", "")), LandmarkScore(overall=0.0)).overall,
                reverse=True,
            )
            # Keep top candidates for milestone detection
            articles = articles[: max_events * 2]

        # Step 4: Detect milestones
        events: list[TimelineEvent] = []

        # Sort for first-report detection (chronological)
        def get_sort_key(a: dict) -> tuple:
            raw_year = a.get("year") or a.get("pub_year") or 9999
            year = int(raw_year) if raw_year else 9999
            return (year, str(a.get("pmid", "")))

        sorted_articles = sorted(articles, key=get_sort_key)

        for i, article in enumerate(sorted_articles):
            is_first = i == 0
            event = self.detector.detect_milestone(article, is_first=is_first)

            if event:
                # Attach landmark score if available
                if event.pmid in landmark_map:
                    event = replace(event, landmark_score=landmark_map[event.pmid])
                events.append(event)
            elif include_all:
                generic = self._create_generic_event(article)
                if generic.pmid in landmark_map:
                    generic = replace(generic, landmark_score=landmark_map[generic.pmid])
                events.append(generic)

            if len(events) >= max_events:
                break

        logger.info(f"Detected {len(events)} timeline events")

        # Step 5: Build timeline
        landmark_count = sum(1 for e in events if e.landmark_score and e.landmark_score.tier == "landmark")
        timeline = ResearchTimeline(
            topic=topic,
            events=events,
            metadata={
                "total_searched": len(articles),
                "milestones_detected": len(events),
                "landmarks_detected": landmark_count,
                "highlight_landmarks": highlight_landmarks,
                "min_year": min_year,
                "max_year": max_year,
            },
        )

        # Step 6: Auto-group into periods if requested
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

    async def build_research_tree(
        self,
        topic: str,
        max_events: int = 50,
        min_year: int | None = None,
        max_year: int | None = None,
        include_all: bool = True,
    ) -> ResearchTree:
        """
        Build a research lineage tree — branching by sub-topics.

        Reuses the full timeline pipeline (search → iCite → milestones →
        landmark scoring) then organizes events into thematic branches
        using BranchDetector.

        Args:
            topic: Research topic
            max_events: Maximum events to include
            min_year: Filter from this year
            max_year: Filter until this year
            include_all: Include non-milestone articles (recommended for trees
                         since they fill out branch coverage)

        Returns:
            ResearchTree with thematic branches
        """
        from .branch_detector import build_research_tree as _build_tree

        timeline = await self.build_timeline(
            topic=topic,
            max_events=max_events,
            include_all=include_all,
            min_year=min_year,
            max_year=max_year,
            highlight_landmarks=True,
        )

        return _build_tree(timeline)

    async def _search_topic(
        self,
        topic: str,
        max_results: int = 150,
        sort_by_citations: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Search for articles on a topic.

        Uses PubMed search with iCite enrichment. Stores full iCite metrics
        on each article (not just citation_count) for landmark scoring.
        """
        try:
            results = await self.searcher.search(topic, limit=max_results)

            # Fetch iCite metrics for all articles
            if results:
                pmids = [str(r.get("pmid", "")) for r in results if r.get("pmid")]
                if pmids:
                    try:
                        citation_data = await self.searcher.get_citation_metrics(pmids)
                        if citation_data:
                            for article in results:
                                pmid = str(article.get("pmid", ""))
                                if pmid in citation_data:
                                    metrics = citation_data[pmid]
                                    # Keep full iCite data for landmark scoring
                                    article["icite"] = metrics
                                    article["citation_count"] = metrics.get("citation_count", 0)

                            # Sort by citations if requested
                            if sort_by_citations:
                                results.sort(
                                    key=lambda x: x.get("citation_count", 0),
                                    reverse=True,
                                )
                    except Exception as e:
                        logger.debug(f"iCite enrichment failed: {e}")

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

    def _compute_landmark_scores(
        self,
        articles: list[dict[str, Any]],
        source_counts: dict[str, int] | None = None,
    ) -> dict[str, LandmarkScore]:
        """
        Compute landmark scores for all articles using multi-signal scoring.

        Pre-computes milestone confidence and evidence quality for each article,
        then feeds all signals into the LandmarkScorer for composite scoring.

        Args:
            articles: Articles with optional 'icite' field from _search_topic
            source_counts: Optional PMID → source count mapping

        Returns:
            Dict mapping PMID → LandmarkScore
        """
        # Extract per-article signals
        icite_data: dict[str, dict[str, Any]] = {}
        milestone_scores: dict[str, float] = {}
        evidence_scores: dict[str, float] = {}

        for article in articles:
            pmid = str(article.get("pmid", ""))
            if not pmid:
                continue

            # iCite metrics (already on article from _search_topic)
            if article.get("icite"):
                icite_data[pmid] = article["icite"]

            # Pre-compute milestone confidence by running detection
            event = self.detector.detect_milestone(article, is_first=False)
            if event:
                milestone_scores[pmid] = event.confidence_score
                evidence_scores[pmid] = evidence_level_to_score(event.evidence_level.value)
            else:
                # Still compute evidence level from pub type
                evidence_level = self.detector.infer_evidence_level(article)
                evidence_scores[pmid] = evidence_level_to_score(evidence_level.value)

        # Run batch scoring
        scored = self.scorer.score_articles(
            articles=articles,
            icite_data=icite_data,
            source_counts=source_counts or {},
            milestone_scores=milestone_scores,
            evidence_scores=evidence_scores,
        )

        # Build PMID → LandmarkScore mapping
        return {str(article.get("pmid", "")): score for article, score in scored if article.get("pmid")}

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

    Highlights landmark papers with star ratings and multi-signal scores.
    """
    if not timeline.events:
        return f"No timeline events found for: {timeline.topic}"

    # Header
    lines = [
        f"## Research Timeline: {timeline.topic}",
        f"**Period**: {timeline.year_range[0]} - {timeline.year_range[1]} ({timeline.duration_years} years)"
        if timeline.year_range
        else "",
        f"**Total Events**: {timeline.total_events}",
    ]

    # Landmark summary (if any)
    landmark_events = timeline.get_landmark_events(min_landmark_score=0.50)
    if landmark_events:
        lines.append(f"**Landmark Papers**: {len(landmark_events)} identified via multi-signal scoring")

    lines.extend(["", "### Milestone Summary"])

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

        # Build event line with landmark indicator
        parts = []

        # Star rating from landmark score
        if event.landmark_score and event.landmark_score.stars:
            parts.append(event.landmark_score.stars)

        parts.append(f"[{event.milestone_label}]")
        title_text = event.title[:80] + ("..." if len(event.title) > 80 else "")
        parts.append(title_text)
        parts.append(f"(PMID: {event.pmid})")

        # Landmark details
        if event.landmark_score and event.landmark_score.overall >= 0.25:
            ls = event.landmark_score
            details: list[str] = [f"Score: {ls.overall:.2f}"]
            if ls.citation_impact > 0:
                details.append(f"Impact: {ls.citation_impact:.2f}")
            if ls.source_agreement > 0.1:
                details.append(f"Sources: {ls.source_agreement:.2f}")
            if ls.citation_velocity > 0:
                details.append(f"Velocity: {ls.citation_velocity:.2f}")
            parts.append(f"[{' | '.join(details)}]")

        lines.append(f"- {' '.join(parts)}")

    return "\n".join(lines)
