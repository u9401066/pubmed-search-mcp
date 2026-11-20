"""Scientific-importance ranking regressions for Chronicle analytics and narrative."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from pubmed_search.application.chronicle.analytics import analyze_milestones
from pubmed_search.application.chronicle.assembler import assemble_chronicle
from pubmed_search.application.chronicle.narrator import narrate_chronicle
from pubmed_search.application.chronicle.service import ChronicleService
from pubmed_search.application.timeline.landmark_scorer import LandmarkScorer
from pubmed_search.application.timeline.timeline_builder import TimelineBuilder
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
    citations: int | None,
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


def test_milestones_explain_recorded_scores_and_distinguish_missing_inputs_from_zero() -> None:
    scorer = LandmarkScorer()
    entries = []
    for pmid, metrics in [("1", {}), ("2", {"citation_count": 0})]:
        score = scorer.score_article(article={"pmid": pmid}, icite_metrics=metrics, milestone_confidence=0.5)
        entry = _entry(pmid, 2000, detection_confidence=0.5, citations=0, importance=score.overall)
        entry.provenance["landmark_score"] = score.to_dict()
        entries.append(entry)
    # Some historical snapshots stored only the overall score.
    entries.append(_entry("3", 2010, detection_confidence=0.5, citations=0, importance=0.7))
    snapshot = ChronicleSnapshot.from_dict(_snapshot(entries).to_dict())
    report = ChronicleService.render(snapshot, "milestones")
    assert isinstance(report, dict)
    rows = {row["entry_id"]: row for row in report["landmark_entries"]}
    assert rows["1"]["evidence_ids"] == ["pmid:1"]
    missing = {hit["component"]: hit for hit in rows["1"]["score_components"]}
    measured = {hit["component"]: hit for hit in rows["2"]["score_components"]}
    assert (missing["citation_impact"]["policy"], missing["citation_impact"]["raw_value"]) == ("none", None)
    assert (measured["citation_impact"]["policy"], measured["citation_impact"]["raw_value"]) == ("citation_count", 0)
    assert missing["milestone_confidence"]["weight"] == 0.20
    assert missing["milestone_confidence"]["weighted_score"] == 0.10
    assert rows["3"]["score_components"] is None
    assert rows["1"]["observed_max_citations"] is None
    assert rows["2"]["observed_max_citations"] == 0
    assert rows["3"]["observed_max_citations"] is None
    quality = report["evidence_quality"]
    assert (quality["with_citation_count"], quality["max_citations"], quality["median_citations"]) == (1, 0, 0)
    assert report["landmark_ranking"]["scope"] == "entries_in_this_revision"


def test_legacy_unverified_zero_leaves_revision_citation_statistics_unknown() -> None:
    entry = _entry("10", 1990, detection_confidence=0.2, citations=0)
    report = ChronicleService.render(ChronicleSnapshot.from_dict(_snapshot([entry]).to_dict()), "milestones")
    assert isinstance(report, dict)
    quality = report["evidence_quality"]
    assert (quality["with_citation_count"], quality["max_citations"], quality["median_citations"]) == (0, None, None)
    assert report["landmark_entries"][0]["observed_max_citations"] is None


def test_citation_statistics_count_each_observed_paper_once_across_entries_and_roles() -> None:
    measured_zero = _entry("10", 1990, detection_confidence=0.2, citations=0)
    measured_zero.provenance["citation_count_observed"] = True
    measured_zero.evidence.contradicting_articles = [EvidenceArticle("Different paper", pmid="11", citation_count=0)]
    measured_zero.evidence.updating_articles = [EvidenceArticle("Updated paper", pmid="12")]

    updated = _entry("12", 2005, detection_confidence=0.2, citations=8)
    updated.evidence.updating_articles = [EvidenceArticle("Updated paper", pmid="12", citation_count=12)]

    ambiguous = _entry("13", 2006, detection_confidence=0.2, citations=0)
    ambiguous.evidence.supporting_articles.append(EvidenceArticle("Another source", pmid="14", citation_count=0))
    ambiguous.provenance["citation_count_observed"] = True

    unmeasured = _entry("15", 2007, detection_confidence=0.2, citations=None)
    unmeasured.provenance["citation_count_observed"] = True
    unmeasured.evidence.updating_articles = [
        EvidenceArticle("Unattributed zero", pmid="16", citation_count=0),
        EvidenceArticle("Invalid negative", pmid="17", citation_count=-1),
        EvidenceArticle("Invalid boolean", pmid="18", citation_count=True),
    ]

    entries = [measured_zero, updated, ambiguous, unmeasured]
    for ordered in (entries, list(reversed(entries))):
        report = ChronicleService.render(ChronicleSnapshot.from_dict(_snapshot(ordered).to_dict()), "milestones")
        assert isinstance(report, dict)
        quality = report["evidence_quality"]
        assert (quality["with_citation_count"], quality["max_citations"], quality["median_citations"]) == (2, 12, 6)
        observed = {row["entry_id"]: row["observed_max_citations"] for row in report["landmark_entries"]}
        assert observed == {"10": 0, "12": 12, "13": None, "15": None}


@pytest.mark.asyncio
async def test_explicit_pmids_keep_observed_zero_and_missing_counts_through_both_event_paths() -> None:
    searcher = AsyncMock()
    searcher.fetch_details.return_value = [
        {"pmid": "10", "year": 2000, "title": "A routine report", "citation_count": 0},
        {"pmid": "11", "year": 2001, "title": "A routine report"},
        {"pmid": "12", "year": 2002, "title": "A Phase III trial", "citation_count": 0},
        {"pmid": "13", "year": 2003, "title": "A Phase III trial"},
        {"pmid": "14", "year": 2004, "title": "A Phase III trial", "citation_count": 3},
    ]
    timeline = await TimelineBuilder(searcher).build_timeline_from_pmids(
        ["10", "11", "12", "13", "14"], topic="Mobility"
    )
    snapshot = assemble_chronicle(topic="Mobility", timeline=timeline)
    analysis = analyze_milestones(ChronicleSnapshot.from_dict(snapshot.to_dict()))
    rows = {row["evidence_ids"][0]: row for row in analysis["landmark_entries"]}
    assert [rows[f"pmid:{pmid}"]["observed_max_citations"] for pmid in range(10, 15)] == [0, None, 0, None, 3]
    assert [rows[f"pmid:{pmid}"]["citations"] for pmid in range(10, 15)] == [0, 0, 0, 0, 3]
    assert all(row["score_components"] is None for row in rows.values())
    assert rows["pmid:11"]["selection_signal"] == "chronological_display_order_then_entry_id"
    assert rows["pmid:14"]["selection_signal"] == "citation_count"


def test_branch_reading_sample_keeps_a_small_line_outside_global_landmarks_and_excludes_uncertain_members() -> None:
    global_entries = [_entry(str(i), 2000 + i, detection_confidence=0.2, citations=i + 10) for i in range(5)]
    minor = [_entry(str(i), 1990, detection_confidence=0.2, citations=0) for i in (6, 5)]
    for entry in minor:
        entry.branch_id = "minor"
    ambiguous = _entry("7", 1985, detection_confidence=0.9, citations=1)
    no_paper = _entry("8", 1980, detection_confidence=0.9, citations=0)
    no_paper.branch_id = "unbacked"
    no_paper.evidence = EvidenceBundle()
    snapshot = _snapshot(global_entries + minor + [ambiguous, no_paper])
    snapshot.branches = [
        ChronicleBranch("main", "Large", entry_ids=[e.entry_id for e in global_entries] + ["7"]),
        ChronicleBranch("minor", "Small", entry_ids=["6", "5", "7"]),
        ChronicleBranch("empty", "Empty"),
        ChronicleBranch("unbacked", "Unbacked", entry_ids=["8"]),
    ]
    report = analyze_milestones(snapshot)
    assert [row["entry_id"] for row in report["landmark_entries"]] == ["4", "3", "2", "1", "0"]
    reps = {row["branch_id"]: row for row in report["branch_representatives"]}
    assert set(reps) == {"main", "minor"}
    assert (reps["main"]["entry_id"], reps["main"]["selection_basis"], reps["main"]["in_global_landmarks"]) == (
        "4",
        "citation_count",
        True,
    )
    assert reps["minor"]["entry_id"] == "5"
    assert reps["minor"]["evidence_ids"] == ["pmid:5"]
    assert reps["minor"]["selection_basis"] == "chronological_display_order_then_entry_id"
    assert reps["minor"]["observed_max_citations"] is None
    assert reps["minor"]["in_global_landmarks"] is False
