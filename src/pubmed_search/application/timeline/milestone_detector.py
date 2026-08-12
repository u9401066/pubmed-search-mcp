"""
Milestone Detector - Pattern-based Research Milestone Detection

Detects significant milestones in research history using:
1. Publication type patterns (FDA, Phase 3, etc.)
2. Title/abstract keyword matching
3. Citation impact analysis

Architecture:
    Pure domain logic, no external dependencies.
    Uses regex patterns for efficiency and transparency.

Example:
    >>> detector = MilestoneDetector()
    >>> milestone = detector.detect_milestone(article)
    >>> if milestone:
    ...     print(f"Found: {milestone.milestone_type}")
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from pubmed_search.domain.entities.timeline import (
    EvidenceLevel,
    MilestoneType,
    TimelineEvent,
)

from .milestone_policy import (
    DEFAULT_CITATION_THRESHOLD_POLICIES,
    DEFAULT_PUBTYPE_POLICIES,
    DEFAULT_TITLE_PATTERN_POLICIES,
    LANDMARK_CITATION_THRESHOLDS,
    PUBTYPE_PATTERNS,
    TITLE_PATTERNS,
    PublicationTypeMilestonePolicy,
    RegexMilestonePolicy,
)

__all__ = [
    "TITLE_PATTERNS",
    "PUBTYPE_PATTERNS",
    "LANDMARK_CITATION_THRESHOLDS",
    "MilestoneDetector",
    "get_milestone_patterns",
]


class MilestoneDetector:
    """
    Detects research milestones from article metadata.

    Uses a multi-signal approach:
    1. Title pattern matching (regex)
    2. Publication type matching
    3. Citation impact analysis
    4. Temporal position (first report detection)

    The detector is stateless and can be used concurrently.
    """

    def __init__(
        self,
        title_patterns: list[tuple[str, MilestoneType, str, float]] | None = None,
        pubtype_patterns: dict[str, tuple[MilestoneType, str, float]] | None = None,
        min_confidence: float = 0.5,
    ):
        """
        Initialize the detector.

        Args:
            title_patterns: Custom title patterns (or use defaults)
            pubtype_patterns: Custom publication type patterns
            min_confidence: Minimum confidence threshold for detection
        """
        self.title_patterns = title_patterns or TITLE_PATTERNS
        self.pubtype_patterns = pubtype_patterns or PUBTYPE_PATTERNS
        self.min_confidence = min_confidence
        self._title_pattern_policies = self._build_title_policies(title_patterns)
        self._pubtype_policies = self._build_pubtype_policies(pubtype_patterns)
        self._citation_threshold_policies = DEFAULT_CITATION_THRESHOLD_POLICIES

        # Pre-compile regex patterns for efficiency
        self._compiled_patterns = [
            (re.compile(policy.pattern, re.IGNORECASE), policy) for policy in self._title_pattern_policies
        ]

    def detect_milestone(self, article: dict[str, Any], is_first: bool = False) -> TimelineEvent | None:
        """
        Detect milestone from a single article.

        Args:
            article: Article dict with title, pmid, year, publication_types, etc.
            is_first: Whether this is the first article (chronologically)

        Returns:
            TimelineEvent if milestone detected, None otherwise.
        """
        pmid = str(article.get("pmid", ""))
        title = str(article.get("title") or "")
        year = article.get("year") or article.get("pub_year")
        abstract = str(article.get("abstract") or "")

        if not pmid or self._parse_year(year) is None:
            return None

        # Earliest-in-scope is provenance, not a scientific milestone type.
        # Detect the article's actual milestone first so an early FDA approval,
        # guideline, or trial cannot be overwritten by a generic "first" tag.
        result = self._detect_from_pubtype(article, include_unphased_rct=False)

        # 2. Title pattern matching
        if not result:
            result = self._detect_from_title(article, title)

        # 3. Abstract pattern matching (lower confidence)
        if not result and abstract:
            result = self._detect_from_title(article, abstract, confidence_penalty=0.2)

        # 4. A generic RCT publication type is meaningful, but it is less
        # specific than an explicit phase or regulatory title signal.
        if not result:
            result = self._detect_from_pubtype(article, include_unphased_rct=True)

        # 5. Citation-based landmark detection
        if not result:
            result = self._detect_from_citations(article)

        if result is not None and is_first:
            metadata = dict(result.metadata)
            metadata.update(
                {
                    "earliest_observed_in_scope": True,
                    "earliest_observed_scope_note": (
                        "Earliest dated article in the retrieved candidate scope; "
                        "this does not establish the first publication in the field."
                    ),
                }
            )
            result = replace(result, metadata=metadata)
        return result

    def detect_milestones_batch(self, articles: list[dict[str, Any]]) -> list[TimelineEvent]:
        """
        Detect milestones from a batch of articles.

        Marks the earliest dated input article when it is a milestone, without
        changing its scientific milestone classification.

        Args:
            articles: List of article dicts

        Returns:
            List of detected TimelineEvents (chronologically sorted)
        """
        if not articles:
            return []

        # Sort by year for first-report detection
        sorted_articles = sorted(
            articles,
            key=lambda a: (
                self._parse_year(a.get("year") or a.get("pub_year")) or 9999,
                str(a.get("pmid", "")),
            ),
        )

        events: list[TimelineEvent] = []
        for index, article in enumerate(sorted_articles):
            is_first = index == 0
            event = self.detect_milestone(article, is_first=is_first)
            if event:
                events.append(event)

        return events

    def _detect_from_pubtype(
        self,
        article: dict[str, Any],
        *,
        include_unphased_rct: bool = True,
    ) -> TimelineEvent | None:
        """Detect milestone from publication type."""
        pub_types = article.get("publication_types", [])
        if isinstance(pub_types, str):
            pub_types = [pub_types]

        for raw_pub_type in pub_types:
            pub_type = str(raw_pub_type)
            for policy in self._pubtype_policies:
                if not include_unphased_rct and policy.milestone_type is MilestoneType.RANDOMIZED_TRIAL:
                    continue
                if pub_type.casefold() != policy.publication_type.casefold():
                    continue
                if policy.confidence >= self.min_confidence:
                    return self._create_event(
                        article,
                        policy.milestone_type,
                        policy.label,
                        policy.confidence,
                        metadata={
                            "milestone_detection": {
                                "strategy": "publication_type",
                                "policy": policy.name,
                                "matched_value": pub_type,
                                "reason": policy.reason,
                                "confidence": policy.confidence,
                            }
                        },
                    )

        return None

    def _detect_from_title(
        self, article: dict[str, Any], text: str, confidence_penalty: float = 0.0
    ) -> TimelineEvent | None:
        """Detect milestone from title or abstract text."""
        strategy = "abstract_pattern" if confidence_penalty else "title_pattern"
        for pattern, policy in self._compiled_patterns:
            match = pattern.search(text)
            if match:
                confidence = policy.confidence - confidence_penalty
                if confidence >= self.min_confidence:
                    return self._create_event(
                        article,
                        policy.milestone_type,
                        policy.label,
                        confidence,
                        metadata={
                            "milestone_detection": {
                                "strategy": strategy,
                                "policy": policy.name,
                                "rule": policy.pattern,
                                "matched_value": match.group(0),
                                "reason": policy.reason,
                                "confidence": confidence,
                                "confidence_penalty": confidence_penalty,
                            }
                        },
                    )

        return None

    def _detect_from_citations(self, article: dict[str, Any]) -> TimelineEvent | None:
        """Detect landmark based on citation count."""
        citations = article.get("citation_count") or article.get("citations", 0)
        if not citations:
            return None

        try:
            citation_count = int(citations)
        except (TypeError, ValueError):
            return None
        for policy in self._citation_threshold_policies:
            if citation_count < policy.minimum_citations or not policy.emit_event:
                continue
            if policy.confidence >= self.min_confidence:
                return self._create_event(
                    article,
                    MilestoneType.LANDMARK_STUDY,
                    policy.label,
                    policy.confidence,
                    metadata={
                        "milestone_detection": {
                            "strategy": "citation_threshold",
                            "policy": policy.name,
                            "threshold": policy.minimum_citations,
                            "matched_value": str(citation_count),
                            "reason": policy.reason,
                            "confidence": policy.confidence,
                        }
                    },
                )

        return None

    def _create_event(
        self,
        article: dict[str, Any],
        milestone_type: MilestoneType,
        label: str,
        confidence: float,
        metadata: dict[str, Any] | None = None,
    ) -> TimelineEvent:
        """Create a TimelineEvent from article data."""
        pmid = str(article.get("pmid", ""))

        # Ensure year and month are int (BioPython may return StringElement)
        raw_year = article.get("year") or article.get("pub_year")
        year = self._parse_year(raw_year) or 0

        raw_month = article.get("month") or article.get("pub_month")
        month = self._parse_month(raw_month)

        # Extract author info
        authors = article.get("authors", [])
        first_author = None
        if authors:
            if isinstance(authors[0], dict):
                first_author = authors[0].get("name") or authors[0].get("full_name")
            else:
                first_author = str(authors[0])

        # Determine evidence level from publication type
        evidence_level = self._infer_evidence_level(article)

        event_metadata = self.article_context_metadata(article)
        event_metadata.update(metadata or {})

        return TimelineEvent(
            pmid=pmid,
            year=year,
            month=month,
            milestone_type=milestone_type,
            title=str(article.get("title") or ""),
            milestone_label=label,
            description=article.get("abstract", "")[:200] if article.get("abstract") else None,
            evidence_level=evidence_level,
            citation_count=article.get("citation_count") or article.get("citations", 0),
            journal=article.get("journal") or article.get("source"),
            first_author=first_author,
            doi=article.get("doi"),
            confidence_score=confidence,
            metadata=event_metadata,
        )

    @staticmethod
    def article_context_metadata(article: dict[str, Any]) -> dict[str, Any]:
        """Preserve article signals needed by downstream lineage analysis.

        Milestone detection explains why an article became a timeline event;
        MeSH descriptors and author keywords explain which topical research
        line it belongs to.  Both kinds of provenance must survive the
        article-to-event boundary.
        """

        def _strings(value: Any) -> list[str]:
            if isinstance(value, str):
                return [value] if value.strip() else []
            if not isinstance(value, (list, tuple, set)):
                return []
            return [str(item) for item in value if str(item).strip()]

        publication_types = _strings(article.get("publication_types"))
        return {
            "mesh_terms": _strings(article.get("mesh_terms")),
            "keywords": _strings(article.get("keywords")),
            "publication_types": publication_types,
            "publication_type": publication_types[0] if publication_types else None,
            "pmcid": article.get("pmc_id") or article.get("pmcid"),
        }

    def _build_title_policies(
        self, title_patterns: list[tuple[str, MilestoneType, str, float]] | None
    ) -> tuple[RegexMilestonePolicy, ...]:
        if title_patterns is None:
            return DEFAULT_TITLE_PATTERN_POLICIES
        return tuple(
            RegexMilestonePolicy(
                name=f"custom_title_{index}",
                pattern=pattern,
                milestone_type=milestone_type,
                label=label,
                confidence=confidence,
                reason="使用自訂 title pattern 規則",
            )
            for index, (pattern, milestone_type, label, confidence) in enumerate(title_patterns)
        )

    def _build_pubtype_policies(
        self, pubtype_patterns: dict[str, tuple[MilestoneType, str, float]] | None
    ) -> tuple[PublicationTypeMilestonePolicy, ...]:
        if pubtype_patterns is None:
            return DEFAULT_PUBTYPE_POLICIES
        return tuple(
            PublicationTypeMilestonePolicy(
                name=f"custom_pubtype_{index}",
                publication_type=publication_type,
                milestone_type=milestone_type,
                label=label,
                confidence=confidence,
                reason="使用自訂 publication type 規則",
            )
            for index, (publication_type, (milestone_type, label, confidence)) in enumerate(pubtype_patterns.items())
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

    def infer_evidence_level(self, article: dict[str, Any]) -> EvidenceLevel:
        """Infer evidence level from publication type."""
        return self._infer_evidence_level(article)

    def _infer_evidence_level(self, article: dict[str, Any]) -> EvidenceLevel:
        """Infer evidence level from publication type."""
        pub_types = article.get("publication_types", [])
        if isinstance(pub_types, str):
            pub_types = [pub_types]

        # Level 1: Systematic reviews, Meta-analyses
        level1_types = {"Meta-Analysis", "Systematic Review"}
        if any(pt in level1_types for pt in pub_types):
            return EvidenceLevel.LEVEL_1

        # Level 2: RCTs
        level2_types = {
            "Randomized Controlled Trial",
            "Clinical Trial, Phase III",
            "Clinical Trial, Phase IV",
        }
        if any(pt in level2_types for pt in pub_types):
            return EvidenceLevel.LEVEL_2

        # Level 3: Cohort, Case-control
        level3_types = {
            "Clinical Trial, Phase II",
            "Cohort Study",
            "Case-Control Study",
        }
        if any(pt in level3_types for pt in pub_types):
            return EvidenceLevel.LEVEL_3

        # Level 4: Case reports, opinions
        level4_types = {"Case Reports", "Editorial", "Letter", "Comment"}
        if any(pt in level4_types for pt in pub_types):
            return EvidenceLevel.LEVEL_4

        return EvidenceLevel.UNKNOWN


def get_milestone_patterns() -> list[dict[str, Any]]:
    """
    Return all patterns for inspection/debugging.

    Useful for understanding what the detector looks for.
    """
    patterns = []
    for policy in DEFAULT_TITLE_PATTERN_POLICIES:
        patterns.append(
            {
                "policy": policy.name,
                "pattern": policy.pattern,
                "milestone_type": policy.milestone_type.value,
                "label": policy.label,
                "confidence": policy.confidence,
            }
        )
    return patterns
