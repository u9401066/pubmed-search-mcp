"""Scientific-importance ranking regressions for Chronicle analytics and narrative."""

from __future__ import annotations

from typing import Any

from pubmed_search.application.chronicle.analytics import analyze_milestones
from pubmed_search.application.chronicle.narrator import narrate_chronicle
from pubmed_search.domain.entities.chronicle import (
    ChronicleBranch,
    ChronicleEntry,
    ChronicleEntryType,
    ChronicleInputScope,
    ChronicleSnapshot,
    EvidenceArticle,
    EvidenceBundle,
)

_MISSING = object()


def _entry(
    entry_id: str,
    year: int,
    *,
    detection_confidence: float,
    citations: int,
    importance: Any = _MISSING,
) -> ChronicleEntry:
    """Build an entry whose detection and importance signals can disagree."""
    provenance: dict[str, Any] = {
        "milestone_detection_confidence": detection_confidence,
        "confidence_semantics": "milestone_detection_confidence",
    }
    if importance is not _MISSING:
        provenance["landmark_importance_score"] = importance
    article = EvidenceArticle(
        title=f"Evidence {entry_id}",
        pmid=entry_id,
        year=year,
        citation_count=citations,
    )
    return ChronicleEntry(
        entry_id=entry_id,
        entry_type=ChronicleEntryType.MILESTONE,
        title=f"Title {entry_id}",
        time_start=str(year),
        summary_claim=f"Claim {entry_id}.",
        branch_id="main",
        confidence=detection_confidence,
        evidence=EvidenceBundle(supporting_articles=[article]),
        provenance=provenance,
    )


def _snapshot(entries: list[ChronicleEntry]) -> ChronicleSnapshot:
    """Place entries in one branch for ranking tests."""
    return ChronicleSnapshot(
        chronicle_id="scientific-ranking-00000001",
        topic="Scientific ranking",
        input_scope=ChronicleInputScope(mode="pmids", pmids=[entry.entry_id for entry in entries]),
        entries=entries,
        branches=[ChronicleBranch("main", "Main", entry_ids=[entry.entry_id for entry in entries])],
    )


def test_landmark_analysis_prefers_importance_then_citations_not_detection_confidence() -> None:
    snapshot = _snapshot(
        [
            _entry("importance-high", 2003, detection_confidence=0.05, citations=1, importance=0.9),
            _entry("importance-low", 2002, detection_confidence=0.10, citations=0, importance=0.2),
            _entry("citation-fallback", 2001, detection_confidence=0.20, citations=500),
            _entry("detection-only", 2000, detection_confidence=0.99, citations=1),
        ]
    )

    analysis = analyze_milestones(snapshot)
    landmarks = analysis["landmark_entries"]

    assert [item["entry_id"] for item in landmarks] == [
        "importance-high",
        "importance-low",
        "citation-fallback",
        "detection-only",
    ]
    assert landmarks[0]["ranking_basis"] == "provenance.landmark_importance_score"
    assert landmarks[2]["ranking_basis"] == "citation_count_fallback"
    assert landmarks[3]["milestone_detection_confidence"] == 0.99
    assert all("confidence" not in item for item in landmarks)
    assert analysis["landmark_ranking"]["excluded"] == "milestone detection confidence"


def test_brief_narrative_selects_by_importance_with_citation_fallback_then_displays_chronologically() -> None:
    snapshot = _snapshot(
        [
            _entry("detection-only", 2000, detection_confidence=0.99, citations=1),
            _entry("citation-fallback", 2001, detection_confidence=0.20, citations=500),
            _entry("importance-low", 2002, detection_confidence=0.10, citations=0, importance=0.2),
            _entry("importance-high", 2003, detection_confidence=0.05, citations=1, importance=0.9),
        ]
    )

    narrative = narrate_chronicle(snapshot, mode="brief")

    assert "Claim detection-only." not in narrative
    assert "Claim citation-fallback." in narrative
    assert "Claim importance-low." in narrative
    assert "Claim importance-high." in narrative
    assert narrative.index("Claim citation-fallback.") < narrative.index("Claim importance-low.")
    assert narrative.index("Claim importance-low.") < narrative.index("Claim importance-high.")
    assert "1 further entries omitted in brief mode" in narrative


def test_invalid_importance_uses_citations_without_detection_confidence_tiebreak() -> None:
    snapshot = _snapshot(
        [
            _entry("invalid-score", 2000, detection_confidence=0.99, citations=2, importance="not-a-score"),
            _entry("citation-winner", 2001, detection_confidence=0.01, citations=20),
        ]
    )

    landmarks = analyze_milestones(snapshot)["landmark_entries"]

    assert [item["entry_id"] for item in landmarks] == ["citation-winner", "invalid-score"]
    assert all(item["ranking_basis"] == "citation_count_fallback" for item in landmarks)
    assert all(item["landmark_importance_score"] is None for item in landmarks)
