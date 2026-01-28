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


# ============================================================================
# Milestone Patterns (Extensible)
# ============================================================================

# Pattern structure: (regex_pattern, milestone_type, label_template, confidence)
# Label template can use {match} for the matched text

TITLE_PATTERNS: list[tuple[str, MilestoneType, str, float]] = [
    # Regulatory Approvals
    (
        r"\b(FDA|US Food and Drug Administration)\s+(approv|clear|authoriz)",
        MilestoneType.FDA_APPROVAL,
        "FDA Approval",
        0.95,
    ),
    (
        r"\b(EMA|European Medicines Agency)\s+(approv|authoriz)",
        MilestoneType.EMA_APPROVAL,
        "EMA Approval",
        0.95,
    ),
    (
        r"\bregulatory\s+approv",
        MilestoneType.REGULATORY_APPROVAL,
        "Regulatory Approval",
        0.8,
    ),
    # Clinical Trials
    (
        r"\b(phase\s*(?:III|3)|pivotal\s+trial)",
        MilestoneType.PHASE_3,
        "Phase 3 Trial",
        0.9,
    ),
    (
        r"\b(phase\s*(?:II|2)|dose[- ]?find)",
        MilestoneType.PHASE_2,
        "Phase 2 Trial",
        0.85,
    ),
    (
        r"\b(phase\s*(?:I|1)|first[- ]?in[- ]?human|FIH)",
        MilestoneType.PHASE_1,
        "Phase 1 Trial",
        0.85,
    ),
    (
        r"\b(phase\s*(?:IV|4)|post[- ]?market)",
        MilestoneType.PHASE_4,
        "Phase 4 Study",
        0.85,
    ),
    # Evidence Synthesis
    (
        r"\b(meta[- ]?analysis|pooled\s+analysis)",
        MilestoneType.META_ANALYSIS,
        "Meta-Analysis",
        0.9,
    ),
    (
        r"\bsystematic\s+review",
        MilestoneType.SYSTEMATIC_REVIEW,
        "Systematic Review",
        0.9,
    ),
    (
        r"\b(guideline|recommendation|consensus\s+statement)",
        MilestoneType.GUIDELINE,
        "Clinical Guideline",
        0.85,
    ),
    (
        r"\b(expert\s+consensus|panel\s+recommendation)",
        MilestoneType.CONSENSUS,
        "Expert Consensus",
        0.8,
    ),
    # Mechanism & Discovery
    (
        r"\b(mechanism\s+of\s+action|pharmacodynamic|receptor\s+binding)",
        MilestoneType.MECHANISM_DISCOVERY,
        "Mechanism Discovery",
        0.75,
    ),
    (
        r"\b(preclinical|animal\s+model|in\s+vivo\s+study)",
        MilestoneType.PRECLINICAL,
        "Preclinical Study",
        0.7,
    ),
    # Safety Events
    (
        r"\b(safety\s+alert|warning|adverse\s+event|black\s+box)",
        MilestoneType.SAFETY_ALERT,
        "Safety Alert",
        0.85,
    ),
    (
        r"\b(label\s+update|indication.*expand|new\s+indication)",
        MilestoneType.LABEL_UPDATE,
        "Label Update",
        0.8,
    ),
    (
        r"\b(withdraw|recall|market\s+removal)",
        MilestoneType.WITHDRAWAL,
        "Market Withdrawal",
        0.9,
    ),
    # Breakthrough/Landmark
    (
        r"\b(breakthrough|paradigm\s+shift|revolutioniz)",
        MilestoneType.BREAKTHROUGH,
        "Breakthrough Discovery",
        0.7,
    ),
    (
        r"\b(controver|debate|challenge|dispute)",
        MilestoneType.CONTROVERSY,
        "Scientific Debate",
        0.65,
    ),
]

# Publication types that indicate milestones
PUBTYPE_PATTERNS: dict[str, tuple[MilestoneType, str, float]] = {
    "Randomized Controlled Trial": (MilestoneType.PHASE_3, "RCT", 0.7),
    "Clinical Trial, Phase I": (MilestoneType.PHASE_1, "Phase 1 Trial", 0.9),
    "Clinical Trial, Phase II": (MilestoneType.PHASE_2, "Phase 2 Trial", 0.9),
    "Clinical Trial, Phase III": (MilestoneType.PHASE_3, "Phase 3 Trial", 0.95),
    "Clinical Trial, Phase IV": (MilestoneType.PHASE_4, "Phase 4 Study", 0.9),
    "Meta-Analysis": (MilestoneType.META_ANALYSIS, "Meta-Analysis", 0.95),
    "Systematic Review": (MilestoneType.SYSTEMATIC_REVIEW, "Systematic Review", 0.95),
    "Guideline": (MilestoneType.GUIDELINE, "Clinical Guideline", 0.95),
    "Practice Guideline": (MilestoneType.GUIDELINE, "Practice Guideline", 0.95),
    "Consensus Development Conference": (
        MilestoneType.CONSENSUS,
        "Consensus Conference",
        0.9,
    ),
}

# Citation thresholds for landmark detection
LANDMARK_CITATION_THRESHOLDS = {
    "exceptional": 500,  # Exceptional impact
    "high": 200,  # High impact
    "notable": 100,  # Notable impact
    "moderate": 50,  # Moderate impact
}


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

        # Pre-compile regex patterns for efficiency
        self._compiled_patterns = [
            (re.compile(p[0], re.IGNORECASE), p[1], p[2], p[3])
            for p in self.title_patterns
        ]

    def detect_milestone(
        self, article: dict[str, Any], is_first: bool = False
    ) -> TimelineEvent | None:
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

    def detect_milestones_batch(
        self, articles: list[dict[str, Any]]
    ) -> list[TimelineEvent]:
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
            articles, key=lambda a: (a.get("year") or a.get("pub_year") or 9999, a.get("pmid", ""))
        )

        events = []
        for i, article in enumerate(sorted_articles):
            is_first = i == 0
            event = self.detect_milestone(article, is_first=is_first)
            if event:
                events.append(event)

        return events

    def _detect_from_pubtype(
        self, article: dict[str, Any]
    ) -> TimelineEvent | None:
        """Detect milestone from publication type."""
        pub_types = article.get("publication_types", [])
        if isinstance(pub_types, str):
            pub_types = [pub_types]

        for pub_type in pub_types:
            if pub_type in self.pubtype_patterns:
                m_type, label, confidence = self.pubtype_patterns[pub_type]
                if confidence >= self.min_confidence:
                    return self._create_event(article, m_type, label, confidence)

        return None

    def _detect_from_title(
        self, article: dict[str, Any], text: str, confidence_penalty: float = 0.0
    ) -> TimelineEvent | None:
        """Detect milestone from title or abstract text."""
        for pattern, m_type, label, base_confidence in self._compiled_patterns:
            match = pattern.search(text)
            if match:
                confidence = base_confidence - confidence_penalty
                if confidence >= self.min_confidence:
                    return self._create_event(article, m_type, label, confidence)

        return None

    def _detect_from_citations(self, article: dict[str, Any]) -> TimelineEvent | None:
        """Detect landmark based on citation count."""
        citations = article.get("citation_count") or article.get("citations", 0)
        if not citations:
            return None

        if citations >= LANDMARK_CITATION_THRESHOLDS["exceptional"]:
            return self._create_event(
                article, MilestoneType.LANDMARK_STUDY, "Landmark Study", 0.9
            )
        elif citations >= LANDMARK_CITATION_THRESHOLDS["high"]:
            return self._create_event(
                article, MilestoneType.LANDMARK_STUDY, "High-Impact Study", 0.8
            )
        elif citations >= LANDMARK_CITATION_THRESHOLDS["notable"]:
            return self._create_event(
                article, MilestoneType.LANDMARK_STUDY, "Notable Study", 0.7
            )

        return None

    def _create_event(
        self,
        article: dict[str, Any],
        milestone_type: MilestoneType,
        label: str,
        confidence: float,
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
            "jan": 1, "january": 1,
            "feb": 2, "february": 2,
            "mar": 3, "march": 3,
            "apr": 4, "april": 4,
            "may": 5,
            "jun": 6, "june": 6,
            "jul": 7, "july": 7,
            "aug": 8, "august": 8,
            "sep": 9, "sept": 9, "september": 9,
            "oct": 10, "october": 10,
            "nov": 11, "november": 11,
            "dec": 12, "december": 12,
        }
        
        return month_names.get(month_str.lower())

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
        level3_types = {"Clinical Trial, Phase II", "Cohort Study", "Case-Control Study"}
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
    for regex, m_type, label, confidence in TITLE_PATTERNS:
        patterns.append(
            {
                "pattern": regex,
                "milestone_type": m_type.value,
                "label": label,
                "confidence": confidence,
            }
        )
    return patterns
