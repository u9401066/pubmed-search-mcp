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
from pubmed_search.domain.services.study_design import (
    classify_study_design,
    indexed_design_family,
    is_background_mention,
)

from .dates import parse_publication_month, parse_publication_year
from .milestone_policy import (
    ABSTRACT_CONFIDENCE_PENALTY,
    ABSTRACT_SELF_DESCRIPTION_PATTERNS,
    DEFAULT_CITATION_THRESHOLD_POLICIES,
    DEFAULT_PUBTYPE_POLICIES,
    DEFAULT_TITLE_PATTERN_POLICIES,
    LANDMARK_CITATION_THRESHOLDS,
    NON_MILESTONE_DESIGN_FAMILIES,
    PUBTYPE_PATTERNS,
    TEXT_MILESTONES_COMPATIBLE_WITH_INDEXED_DESIGN,
    TITLE_PATTERNS,
    PublicationTypeMilestonePolicy,
    RegexMilestonePolicy,
)

#: Abstract text is attached to timeline-event metadata up to this many chars.
_MAX_ABSTRACT_METADATA_CHARS = 20_000
_MAX_ABSTRACT_SECTIONS = 32

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
        self.title_patterns = TITLE_PATTERNS if title_patterns is None else title_patterns
        self.pubtype_patterns = PUBTYPE_PATTERNS if pubtype_patterns is None else pubtype_patterns
        self.min_confidence = min_confidence
        self._title_pattern_policies = self._build_title_policies(title_patterns)
        self._pubtype_policies = self._build_pubtype_policies(pubtype_patterns)
        self._citation_threshold_policies = DEFAULT_CITATION_THRESHOLD_POLICIES

        # Pre-compile regex patterns for efficiency
        self._compiled_patterns = [
            (re.compile(policy.pattern, re.IGNORECASE), policy) for policy in self._title_pattern_policies
        ]
        # Abstracts accept only self-describing design phrases; custom
        # patterns are the caller's own rules and are applied as given.
        self._compiled_abstract_patterns = [
            (
                re.compile(ABSTRACT_SELF_DESCRIPTION_PATTERNS.get(policy.name, policy.pattern), re.IGNORECASE),
                policy,
            )
            for policy in self._title_pattern_policies
            if policy.name in ABSTRACT_SELF_DESCRIPTION_PATTERNS or policy.name.startswith("custom_")
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

        if not pmid or parse_publication_year(year) is None:
            return None

        # PubMed publication types are authoritative about what kind of
        # publication this is. Text patterns may refine an indexed design (a
        # trial phase) but cannot relabel an indexed trial as, say, a safety
        # alert. MeSH design descriptors alone never veto a text milestone.
        design_family = indexed_design_family(article.get("publication_types"))
        if classify_study_design(article.get("publication_types"), title=title).family in NON_MILESTONE_DESIGN_FAMILIES:
            # A protocol (indexed or stated by its title) or an erratum/retraction
            # notice reports no results; it stays in the timeline as a
            # background record, never a milestone.
            return None

        # Earliest-in-scope is provenance, not a scientific milestone type.
        # Detect the article's actual milestone first so an early FDA approval,
        # guideline, or trial cannot be overwritten by a generic "first" tag.
        result = self._detect_from_pubtype(article, include_unphased_rct=False)

        # 2. Title pattern matching, limited to refinements of indexed designs
        if not result:
            result = self._detect_from_title(article, title, design_family=design_family)

        # 3. A generic RCT publication type is less specific than an explicit
        # phase title, but indexed evidence outranks abstract wording.
        if not result:
            result = self._detect_from_pubtype(article, include_unphased_rct=True)

        # 4. Abstract pattern matching (lower confidence): self-describing
        # design phrases only, within what an indexed design is compatible
        # with, never a sentence about other work.
        if not result and abstract:
            result = self._detect_from_abstract(article, abstract, design_family=design_family)

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
                parse_publication_year(a.get("year") or a.get("pub_year")) or 9999,
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
        pub_types = article.get("publication_types") or []
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

    @staticmethod
    def _compatible_text_milestones(design_family: str | None) -> frozenset[MilestoneType] | None:
        """Return the text milestones an indexed design accepts (``None``: all)."""
        if design_family is None:
            return None
        return TEXT_MILESTONES_COMPATIBLE_WITH_INDEXED_DESIGN.get(design_family, frozenset())

    def _detect_from_title(
        self,
        article: dict[str, Any],
        text: str,
        *,
        design_family: str | None = None,
    ) -> TimelineEvent | None:
        """Detect milestone from title text.

        Args:
            article: Source article mapping.
            text: Title text to match.
            design_family: Indexed PubMed design family, if any. Text patterns
                that would contradict it are skipped.
        """
        compatible = self._compatible_text_milestones(design_family)
        for pattern, policy in self._compiled_patterns:
            if compatible is not None and policy.milestone_type not in compatible:
                continue
            match = pattern.search(text)
            if match and policy.confidence >= self.min_confidence:
                return self._create_event(
                    article,
                    policy.milestone_type,
                    policy.label,
                    policy.confidence,
                    metadata={
                        "milestone_detection": {
                            "strategy": "title_pattern",
                            "policy": policy.name,
                            "rule": policy.pattern,
                            "matched_value": match.group(0),
                            "reason": policy.reason,
                            "confidence": policy.confidence,
                            "confidence_penalty": 0.0,
                            "indexed_design_family": design_family,
                        }
                    },
                )

        return None

    def _detect_from_abstract(
        self,
        article: dict[str, Any],
        abstract: str,
        *,
        design_family: str | None = None,
    ) -> TimelineEvent | None:
        """Detect a design milestone the abstract states about the paper itself.

        Args:
            article: Source article mapping.
            abstract: Abstract text to match.
            design_family: Indexed PubMed design family, if any. Milestones it
                is not compatible with are skipped.
        """
        compatible = self._compatible_text_milestones(design_family)
        text = abstract[:_MAX_ABSTRACT_METADATA_CHARS]
        confidence_penalty = ABSTRACT_CONFIDENCE_PENALTY
        for pattern, policy in self._compiled_abstract_patterns:
            if compatible is not None and policy.milestone_type not in compatible:
                continue
            confidence = policy.confidence - confidence_penalty
            if confidence < self.min_confidence:
                continue
            match = next(
                (
                    candidate
                    for candidate in pattern.finditer(text)
                    if not is_background_mention(text, candidate.start(), candidate.end())
                ),
                None,
            )
            if match is None:
                continue
            return self._create_event(
                article,
                policy.milestone_type,
                policy.label,
                confidence,
                metadata={
                    "milestone_detection": {
                        "strategy": "abstract_pattern",
                        "basis": (
                            "custom_pattern"
                            if policy.name not in ABSTRACT_SELF_DESCRIPTION_PATTERNS
                            else "self_describing_abstract_phrase"
                        ),
                        "policy": policy.name,
                        "rule": pattern.pattern,
                        "matched_value": " ".join(match.group(0).split()),
                        "reason": policy.reason,
                        "confidence": confidence,
                        "confidence_penalty": confidence_penalty,
                        "indexed_design_family": design_family,
                    }
                },
            )

        return None

    def _detect_from_citations(self, article: dict[str, Any]) -> TimelineEvent | None:
        """Detect landmark based on citation count."""
        citations = article.get("citation_count")
        if citations is None:
            citations = article.get("citations", 0)
        if not citations:
            return None

        try:
            citation_count = int(citations)
        except (TypeError, ValueError, OverflowError):
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
        year = parse_publication_year(raw_year) or 0

        raw_month = article.get("month") or article.get("pub_month")
        month = parse_publication_month(raw_month)

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
            citation_count=event_metadata["observed_citation_count"] or 0,
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
        raw_count = article.get("citation_count")
        if raw_count is None:
            raw_count = article.get("citations")
        raw_abstract = article.get("abstract")
        abstract = raw_abstract[:_MAX_ABSTRACT_METADATA_CHARS] if isinstance(raw_abstract, str) else ""
        return {
            "observed_citation_count": (
                raw_count if isinstance(raw_count, int) and not isinstance(raw_count, bool) and raw_count >= 0 else None
            ),
            "mesh_terms": _strings(article.get("mesh_terms")),
            "keywords": _strings(article.get("keywords")),
            "publication_types": publication_types,
            "evidence_level_basis": "publication_type_heuristic_not_quality_assessment",
            "publication_type": publication_types[0] if publication_types else None,
            "pmcid": article.get("pmc_id") or article.get("pmcid"),
            # The full abstract and its structured-section offsets let the
            # Chronicle quote an exact, locatable sentence as evidence.
            "abstract": abstract or None,
            "abstract_truncated": isinstance(raw_abstract, str) and len(raw_abstract) > len(abstract),
            "abstract_source_char_length": len(raw_abstract) if isinstance(raw_abstract, str) else None,
            "abstract_sections": _abstract_sections(
                article.get("abstract_sections"),
                len(abstract),
                source_length=len(raw_abstract) if isinstance(raw_abstract, str) else 0,
            ),
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

    def infer_evidence_level(self, article: dict[str, Any]) -> EvidenceLevel:
        """Infer evidence level from publication type."""
        return self._infer_evidence_level(article)

    def _infer_evidence_level(self, article: dict[str, Any]) -> EvidenceLevel:
        """Infer evidence level from publication type."""
        pub_types = article.get("publication_types") or []
        if isinstance(pub_types, str):
            pub_types = [pub_types]

        # Protocols and notices carry no results of their own.
        if indexed_design_family(pub_types) in NON_MILESTONE_DESIGN_FAMILIES:
            return EvidenceLevel.UNKNOWN

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


def _abstract_sections(value: Any, abstract_length: int, *, source_length: int) -> list[dict[str, Any]]:
    """Keep well-formed, ordered section offsets, clipped to the stored abstract.

    Offsets are validated against the retrieved abstract (*source_length*).
    When only a prefix is stored, sections starting past the cut are dropped
    and the section straddling it is clipped rather than discarding the whole
    structure.
    """
    if not isinstance(value, list):
        return []
    sections: list[dict[str, Any]] = []
    previous_end = 0
    for row in value[:_MAX_ABSTRACT_SECTIONS]:
        if not isinstance(row, dict):
            return []
        start, end = row.get("start"), row.get("end")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or isinstance(start, bool)
            or isinstance(end, bool)
            or not previous_end <= start <= end <= source_length
        ):
            return []
        if start >= abstract_length and abstract_length < source_length:
            break
        label = row.get("label")
        category = row.get("nlm_category")
        sections.append(
            {
                "label": str(label)[:120] if isinstance(label, str) and label.strip() else None,
                "nlm_category": str(category)[:60] if isinstance(category, str) and category.strip() else None,
                "start": start,
                "end": min(end, abstract_length),
            }
        )
        previous_end = end
    return sections


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
