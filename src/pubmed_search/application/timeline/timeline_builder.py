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
from dataclasses import dataclass, replace
from math import isfinite
from typing import TYPE_CHECKING, Any

from pubmed_search.domain.entities.timeline import (
    LandmarkScore,
    MilestoneType,
    ResearchTimeline,
    TimelineEvent,
    TimelinePeriod,
)

from .diagnostics import build_timeline_diagnostics
from .landmark_scorer import LandmarkScorer, evidence_level_to_score
from .milestone_detector import MilestoneDetector

if TYPE_CHECKING:
    from pubmed_search.domain.entities.research_tree import ResearchTree
    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)


class TimelineRetrievalError(RuntimeError):
    """Raised when PubMed retrieval fails instead of returning article evidence."""


@dataclass(frozen=True)
class _SearchBatch:
    """Sanitized PubMed rows plus retrieval-level provenance."""

    articles: list[dict[str, Any]]
    total_count: int | None = None
    omitted_rows: int = 0


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
        [
            MilestoneType.PHASE_1,
            MilestoneType.PHASE_2,
            MilestoneType.PHASE_3,
            MilestoneType.RANDOMIZED_TRIAL,
        ],
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
        batch = await self._search_topic_batch(
            topic,
            max_results=max_events * 3,  # Fetch more, filter to milestones
            sort_by_citations=sort_by_citations,
            min_year=min_year,
            max_year=max_year,
        )
        articles = batch.articles
        retrieved_count = len(articles)
        available_count = batch.total_count if batch.total_count is not None else (0 if not articles else None)

        if not articles:
            logger.warning(f"No articles found for: {topic}")
            return ResearchTimeline(
                topic=topic,
                metadata={
                    "search_status": "no_results",
                    "source_counts": {
                        "pubmed": {"returned": 0, "available": available_count},
                    },
                    "retrieval": self._retrieval_metadata(
                        query=topic,
                        max_events=max_events,
                        min_year=min_year,
                        max_year=max_year,
                        sort_by_citations=sort_by_citations,
                        omitted_rows=batch.omitted_rows,
                    ),
                },
            )

        logger.info(f"Found {len(articles)} articles for: {topic}")

        # Step 2: Filter by year if specified
        if min_year or max_year:
            articles = self._filter_by_year(articles, min_year, max_year)
        filtered_count = len(articles)

        # Step 3: Compute landmark scores (if enabled)
        landmark_map: dict[str, LandmarkScore] = {}
        if highlight_landmarks and articles:
            earliest_article = self._earliest_dated_article(articles)
            latest_article = self._latest_dated_article(articles)
            landmark_map = self._compute_landmark_scores(articles, source_counts=source_counts)
            # Sort by landmark score to prioritize important articles
            ranked_articles = sorted(
                articles,
                key=lambda a: landmark_map.get(str(a.get("pmid", "")), LandmarkScore(overall=0.0)).overall,
                reverse=True,
            )
            # Keep top candidates for milestone detection while pinning both
            # observed chronological boundaries. Without the latest boundary,
            # a score cap can turn a Chronicle into an early-history fragment.
            candidate_limit = max(0, max_events * 2)
            boundaries: list[dict[str, Any]] = []
            for boundary in (earliest_article, latest_article):
                if boundary is not None and not any(self._same_article(boundary, prior) for prior in boundaries):
                    boundaries.append(boundary)
            boundaries = boundaries[:candidate_limit]
            remaining = [
                article
                for article in ranked_articles
                if not any(self._same_article(article, boundary) for boundary in boundaries)
            ]
            articles = remaining[: max(0, candidate_limit - len(boundaries))] + boundaries
        candidate_count = len(articles)

        # Step 4: Detect milestones
        events: list[TimelineEvent] = []

        sorted_articles = sorted(articles, key=self._article_sort_key)

        for i, article in enumerate(sorted_articles):
            is_first = i == 0 and self._parse_year(article.get("year") or article.get("pub_year")) is not None
            event = self.detector.detect_milestone(article, is_first=is_first)

            if event:
                # Attach landmark score if available
                if event.pmid in landmark_map:
                    event = replace(event, landmark_score=landmark_map[event.pmid])
                events.append(event)
            elif include_all:
                generic = self._create_generic_event(article, earliest_observed_in_scope=is_first)
                if generic.pmid in landmark_map:
                    generic = replace(generic, landmark_score=landmark_map[generic.pmid])
                events.append(generic)

        detected_before_cap = len(events)
        events = self._select_chronological_events(events, max_events=max_events)

        logger.info(f"Detected {detected_before_cap} timeline events; emitted {len(events)}")

        # Step 5: Build timeline
        landmark_count = sum(1 for e in events if e.landmark_score and e.landmark_score.tier == "landmark")
        diagnostics = build_timeline_diagnostics(
            events,
            source="topic_search",
            retrieved_count=retrieved_count,
            filtered_count=filtered_count,
            candidate_count=candidate_count,
            include_all=include_all,
            highlight_landmarks=highlight_landmarks,
        )
        diagnostics["search"].update(
            {
                "events_before_output_cap": detected_before_cap,
                "event_selection": "chronological_boundaries_landmarks_and_temporal_spread",
            }
        )
        timeline = ResearchTimeline(
            topic=topic,
            events=events,
            metadata={
                "total_searched": retrieved_count,
                "articles_after_filters": filtered_count,
                "milestone_candidates": candidate_count,
                "milestones_detected": len(events),
                "events_before_output_cap": detected_before_cap,
                "landmarks_detected": landmark_count,
                "highlight_landmarks": highlight_landmarks,
                "min_year": min_year,
                "max_year": max_year,
                "source_counts": {
                    "pubmed": {"returned": retrieved_count, "available": available_count},
                },
                "retrieval": self._retrieval_metadata(
                    query=topic,
                    max_events=max_events,
                    min_year=min_year,
                    max_year=max_year,
                    sort_by_citations=sort_by_citations,
                    omitted_rows=batch.omitted_rows,
                ),
                "diagnostics": diagnostics,
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
            return ResearchTimeline(
                topic=topic,
                metadata={"source_counts": {"pubmed": {"returned": 0, "available": 0}}},
            )

        # Fetch article details
        try:
            raw_articles = await self.searcher.fetch_details(pmids)
        except Exception as exc:
            msg = f"PubMed detail retrieval failed for {len(pmids)} requested PMIDs: {exc}"
            raise TimelineRetrievalError(msg) from exc

        batch = self._sanitize_search_rows(raw_articles)
        articles = batch.articles

        if not articles:
            return ResearchTimeline(
                topic=topic,
                metadata={
                    "search_status": "no_results",
                    "source_counts": {"pubmed": {"returned": 0, "available": len(pmids)}},
                    "retrieval": {
                        "source": "pubmed",
                        "mode": "explicit_pmids",
                        "requested": len(pmids),
                        "omitted_non_article_rows": batch.omitted_rows,
                        "algorithm_version": "chronicle-timeline/v2",
                    },
                },
            )

        # Explicitly requested PMIDs are part of the source of truth even when
        # they do not match a milestone heuristic. Preserve those records as
        # background events rather than silently dropping them.
        sorted_articles = sorted(articles, key=self._article_sort_key)
        events: list[TimelineEvent] = []
        for index, article in enumerate(sorted_articles):
            is_first = index == 0 and self._parse_year(article.get("year") or article.get("pub_year")) is not None
            event = self.detector.detect_milestone(article, is_first=is_first)
            events.append(event or self._create_generic_event(article, earliest_observed_in_scope=is_first))
        diagnostics = build_timeline_diagnostics(
            events,
            source="pmid_list",
            retrieved_count=len(articles),
            filtered_count=len(articles),
            candidate_count=len(articles),
            include_all=True,
            highlight_landmarks=False,
        )

        timeline = ResearchTimeline(
            topic=topic,
            events=events,
            metadata={
                "source": "pmid_list",
                "pmid_count": len(pmids),
                "retrieved_count": len(articles),
                "total_searched": len(articles),
                "source_counts": {
                    "pubmed": {"returned": len(articles), "available": len(pmids)},
                },
                "retrieval": {
                    "source": "pubmed",
                    "mode": "explicit_pmids",
                    "requested": len(pmids),
                    "omitted_non_article_rows": batch.omitted_rows,
                    "algorithm_version": "chronicle-timeline/v2",
                },
                "diagnostics": diagnostics,
            },
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
        min_year: int | None = None,
        max_year: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search for articles on a topic.

        Uses PubMed search with iCite enrichment. Stores full iCite metrics
        on each article (not just citation_count) for landmark scoring.
        """
        batch = await self._search_topic_batch(
            topic,
            max_results=max_results,
            sort_by_citations=sort_by_citations,
            min_year=min_year,
            max_year=max_year,
        )
        return batch.articles

    async def _search_topic_batch(
        self,
        topic: str,
        *,
        max_results: int,
        sort_by_citations: bool,
        min_year: int | None,
        max_year: int | None,
    ) -> _SearchBatch:
        """Search PubMed and retain count/error provenance separately from rows."""
        try:
            search_kwargs: dict[str, Any] = {"limit": max_results}
            if min_year is not None:
                search_kwargs["min_year"] = min_year
            if max_year is not None:
                search_kwargs["max_year"] = max_year
            raw_results = await self.searcher.search(topic, **search_kwargs)
        except Exception as exc:
            msg = f"PubMed search failed for {topic!r}: {exc}"
            raise TimelineRetrievalError(msg) from exc

        batch = self._sanitize_search_rows(raw_results)
        results = batch.articles

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
                except Exception as exc:
                    logger.debug(f"iCite enrichment failed: {exc}")

        return _SearchBatch(
            articles=results,
            total_count=batch.total_count,
            omitted_rows=batch.omitted_rows,
        )

    @staticmethod
    def _sanitize_search_rows(raw_rows: Any) -> _SearchBatch:
        """Separate PubMed article rows from metadata and error sentinels."""
        if not isinstance(raw_rows, list):
            msg = f"PubMed returned an invalid response type: {type(raw_rows).__name__}"
            raise TimelineRetrievalError(msg)

        articles: list[dict[str, Any]] = []
        errors: list[str] = []
        total_count: int | None = None
        omitted_rows = 0
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                omitted_rows += 1
                continue
            row = dict(raw_row)
            raw_metadata = row.pop("_search_metadata", None)
            if isinstance(raw_metadata, dict):
                raw_total = raw_metadata.get("total_count")
                if isinstance(raw_total, int) and not isinstance(raw_total, bool) and raw_total >= 0:
                    total_count = raw_total
            if "error" in row:
                errors.append(str(row.get("error") or "unknown PubMed retrieval error"))
                omitted_rows += 1
                continue
            # A genuine PubMed article always has a PMID. This prevents
            # metadata-only/error pseudo-rows from becoming undated fake papers.
            if not str(row.get("pmid") or "").strip():
                omitted_rows += 1
                continue
            articles.append(row)

        if errors:
            detail = "; ".join(dict.fromkeys(errors))
            raise TimelineRetrievalError(f"PubMed retrieval returned an error: {detail}")
        return _SearchBatch(articles=articles, total_count=total_count, omitted_rows=omitted_rows)

    @staticmethod
    def _retrieval_metadata(
        *,
        query: str,
        max_events: int,
        min_year: int | None,
        max_year: int | None,
        sort_by_citations: bool,
        omitted_rows: int,
    ) -> dict[str, Any]:
        """Describe the bounded retrieval strategy used for reproducibility."""
        return {
            "source": "pubmed",
            "mode": "topic_search",
            "query": query,
            "server_side_year_filter": True,
            "min_year": min_year,
            "max_year": max_year,
            "returned_limit": max_events * 3,
            "candidate_multiplier": 3,
            "ranking": "pubmed_relevance_then_icite" if sort_by_citations else "pubmed_relevance",
            "omitted_non_article_rows": omitted_rows,
            "algorithm_version": "chronicle-timeline/v2",
        }

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
            year = self._parse_year(raw_year)
            if year is None:
                continue
            if min_year and year < min_year:
                continue
            if max_year and year > max_year:
                continue
            filtered.append(article)
        return filtered

    def _create_generic_event(
        self,
        article: dict[str, Any],
        *,
        earliest_observed_in_scope: bool = False,
    ) -> TimelineEvent:
        """Create a generic event for non-milestone articles."""
        pmid = str(article.get("pmid", ""))

        raw_year = article.get("year") or article.get("pub_year")
        year = self._parse_year(raw_year) or 0

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

        metadata = self.detector.article_context_metadata(article)
        metadata["background_event"] = True
        if earliest_observed_in_scope:
            metadata.update(
                {
                    "earliest_observed_in_scope": True,
                    "earliest_observed_scope_note": (
                        "Earliest dated article in the retrieved candidate scope; "
                        "this does not establish the first publication in the field."
                    ),
                }
            )

        return TimelineEvent(
            pmid=pmid,
            year=year,
            month=month,
            milestone_type=MilestoneType.OTHER,
            title=str(article.get("title") or ""),
            milestone_label="Study",
            description=str(article.get("abstract") or "")[:200] or None,
            evidence_level=self.detector.infer_evidence_level(article),
            journal=article.get("journal") or article.get("source"),
            first_author=first_author,
            doi=article.get("doi"),
            citation_count=article.get("citation_count", 0),
            confidence_score=0.0,
            metadata=metadata,
        )

    @staticmethod
    def _parse_year(raw_year: Any) -> int | None:
        """Parse a plausible four-digit publication year without raising."""
        if isinstance(raw_year, bool) or raw_year is None:
            return None
        text = str(raw_year).strip()
        if len(text) != 4 or not text.isdecimal():
            return None
        year = int(text)
        return year if 1000 <= year <= 9999 else None

    @classmethod
    def _article_sort_key(cls, article: dict[str, Any]) -> tuple[int, int, str]:
        """Return a deterministic chronology key for an article mapping."""
        year = cls._parse_year(article.get("year") or article.get("pub_year")) or 9999
        month = cls._parse_month_value(article.get("month") or article.get("pub_month"))
        return (year, month or 0, str(article.get("pmid") or ""))

    @classmethod
    def _earliest_dated_article(cls, articles: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Return the earliest article with a valid publication year."""
        dated = [article for article in articles if cls._parse_year(article.get("year") or article.get("pub_year"))]
        return min(dated, key=cls._article_sort_key, default=None)

    @classmethod
    def _latest_dated_article(cls, articles: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Return the latest article with a valid publication year."""
        dated = [article for article in articles if cls._parse_year(article.get("year") or article.get("pub_year"))]
        return max(dated, key=cls._article_sort_key, default=None)

    @staticmethod
    def _select_chronological_events(events: list[TimelineEvent], *, max_events: int) -> list[TimelineEvent]:
        """Select a bounded set without truncating the recent end of history.

        The first and last observed events are pinned. Half of the remaining
        capacity favors explicit landmark importance/citations; the rest fills
        the largest chronological gaps. Detection confidence is deliberately
        excluded because it is not scientific importance.
        """
        if max_events <= 0:
            return []
        ordered = sorted(events, key=lambda event: event.sort_key)
        if len(ordered) <= max_events:
            return ordered
        if max_events == 1:
            return ordered[:1]

        dated_indices = [index for index, event in enumerate(ordered) if event.year > 0]
        selected = {dated_indices[0], dated_indices[-1]} if len(dated_indices) >= 2 else {0, len(ordered) - 1}

        def importance(index: int) -> tuple[float, int, tuple[int, int, str]]:
            event = ordered[index]
            raw_score = event.landmark_score.overall if event.landmark_score is not None else -1.0
            score = float(raw_score) if isfinite(float(raw_score)) else -1.0
            citations = max(event.citation_count, 0)
            return (score, citations, (-event.year, -(event.month or 0), event.pmid))

        landmark_slots = min(max_events - len(selected), max_events // 2)
        for index in sorted(range(len(ordered)), key=importance, reverse=True):
            if index in selected:
                continue
            selected.add(index)
            if len(selected) >= 2 + landmark_slots:
                break

        while len(selected) < max_events:
            remaining = [index for index in range(len(ordered)) if index not in selected]
            next_index = max(
                remaining,
                key=lambda index: (
                    min(abs(index - chosen) for chosen in selected),
                    importance(index),
                    -index,
                ),
            )
            selected.add(next_index)

        return [ordered[index] for index in sorted(selected)]

    @staticmethod
    def _same_article(left: dict[str, Any], right: dict[str, Any]) -> bool:
        """Compare article identity without relying on large mapping equality."""
        left_pmid = str(left.get("pmid") or "")
        right_pmid = str(right.get("pmid") or "")
        if left_pmid or right_pmid:
            return bool(left_pmid and left_pmid == right_pmid)
        return (
            str(left.get("doi") or "").casefold(),
            str(left.get("title") or "").casefold(),
            str(left.get("year") or left.get("pub_year") or ""),
        ) == (
            str(right.get("doi") or "").casefold(),
            str(right.get("title") or "").casefold(),
            str(right.get("year") or right.get("pub_year") or ""),
        )

    @staticmethod
    def _parse_month_value(raw_month: Any) -> int | None:
        """Parse month values for sorting without constructing a builder."""
        if isinstance(raw_month, int):
            return raw_month if 1 <= raw_month <= 12 else None
        text = str(raw_month or "").strip().lower()
        if text.isdecimal():
            value = int(text)
            return value if 1 <= value <= 12 else None
        return {
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
        }.get(text)

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
                dated_period_events = [event for event in period_events if event.year > 0]
                if not dated_period_events:
                    continue
                years = [event.year for event in dated_period_events]
                periods.append(
                    TimelinePeriod(
                        name=period_name,
                        start_year=min(years),
                        end_year=max(years),
                        events=sorted(dated_period_events, key=lambda e: e.sort_key),
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
            lines.append(f"\n**{current_year if current_year > 0 else 'Undated'}**")

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
