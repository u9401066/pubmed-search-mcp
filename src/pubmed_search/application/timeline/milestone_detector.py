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
        title = article.get("title", "")
        year = article.get("year") or article.get("pub_year")
        abstract = article.get("abstract", "")

        if not pmid or not year:
            return None

        # Try different detection methods
        result = None

        # 1. First report detection (highest priority for earliest article)
        if is_first:
            result = self._create_event(
                article=article,
                milestone_type=MilestoneType.FIRST_REPORT,
                label="First Report",
                confidence=0.85,
                metadata={
                    "milestone_detection": {
                        "strategy": "first_report",
                        "policy": "first_report",
                        "reason": "最早的時間排序文章預設標記為 First Report",
                        "confidence": 0.85,
                    }
                },
            )

        # 2. Publication type matching (high confidence)
        if not result:
            result = self._detect_from_pubtype(article)

        # 3. Title pattern matching
        if not result:
            result = self._detect_from_title(article, title)

        # 4. Abstract pattern matching (lower confidence)
        if not result and abstract:
            result = self._detect_from_title(article, abstract, confidence_penalty=0.2)

        # 5. Citation-based landmark detection
        if not result:
            result = self._detect_from_citations(article)

        return result

    def detect_milestones_batch(self, articles: list[dict[str, Any]]) -> list[TimelineEvent]:
        """
        Detect milestones from a batch of articles.

        Handles first-report detection by sorting chronologically.

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
                a.get("year") or a.get("pub_year") or 9999,
                a.get("pmid", ""),
            ),
        )

        events = []
        for i, article in enumerate(sorted_articles):
            is_first = i == 0
            event = self.detect_milestone(article, is_first=is_first)
            if event:
                events.append(event)

        return events

    def _detect_from_pubtype(self, article: dict[str, Any]) -> TimelineEvent | None:
        """Detect milestone from publication type."""
        pub_types = article.get("publication_types", [])
        if isinstance(pub_types, str):
            pub_types = [pub_types]

        for pub_type in pub_types:
            for policy in self._pubtype_policies:
                if pub_type != policy.publication_type:
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

        citation_count = int(citations)
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
        raw_year = article.get("year") or article.get("pub_year") or 0
        year = int(raw_year) if raw_year else 0

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

        return TimelineEvent(
            pmid=pmid,
            year=year,
            month=month,
            milestone_type=milestone_type,
            title=article.get("title", ""),
            milestone_label=label,
            description=article.get("abstract", "")[:200] if article.get("abstract") else None,
            evidence_level=evidence_level,
            citation_count=article.get("citation_count") or article.get("citations", 0),
            journal=article.get("journal") or article.get("source"),
            first_author=first_author,
            doi=article.get("doi"),
            confidence_score=confidence,
            metadata=metadata or {},
        )

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
