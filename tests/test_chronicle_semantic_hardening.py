"""Scientific-semantic hardening regressions for Research Chronicle inputs."""

from __future__ import annotations

from typing import Any

import pytest

from pubmed_search.application.chronicle import (
    assemble_chronicle,
    audit_chronicle,
    build_chronicle_lineage,
)
from pubmed_search.application.timeline import build_research_tree
from pubmed_search.application.timeline.milestone_detector import MilestoneDetector
from pubmed_search.application.timeline.timeline_builder import TimelineBuilder
from pubmed_search.domain.entities.chronicle import ChronicleEntryStatus
from pubmed_search.domain.entities.timeline import (
    LandmarkScore,
    MilestoneType,
    ResearchTimeline,
    TimelineEvent,
)


def _event(
    pmid: str,
    year: int,
    *,
    milestone_type: MilestoneType = MilestoneType.OTHER,
    mesh_terms: list[str] | None = None,
    keywords: list[str] | None = None,
    confidence: float = 0.7,
    landmark: LandmarkScore | None = None,
) -> TimelineEvent:
    return TimelineEvent(
        pmid=pmid,
        year=year,
        milestone_type=milestone_type,
        title=f"Paper {pmid}",
        milestone_label=milestone_type.value,
        confidence_score=confidence,
        landmark_score=landmark,
        metadata={"mesh_terms": mesh_terms or [], "keywords": keywords or []},
    )


def test_earliest_observed_provenance_does_not_mask_actual_milestone() -> None:
    event = MilestoneDetector().detect_milestone(
        {"pmid": "1", "year": 2020, "title": "FDA approves a new therapy"},
        is_first=True,
    )

    assert event is not None
    assert event.milestone_type is MilestoneType.FDA_APPROVAL
    assert event.metadata["earliest_observed_in_scope"] is True
    assert "does not establish the first publication" in event.metadata["earliest_observed_scope_note"]


def test_generic_rct_is_not_inferred_to_be_phase_three() -> None:
    event = MilestoneDetector().detect_milestone(
        {
            "pmid": "2",
            "year": 2021,
            "title": "Randomized comparison",
            "publication_types": ["Randomized Controlled Trial"],
        }
    )

    assert event is not None
    assert event.milestone_type is MilestoneType.RANDOMIZED_TRIAL

    tree = build_research_tree(
        ResearchTimeline(
            "therapy",
            [
                _event("early", 2018, milestone_type=MilestoneType.PHASE_1),
                event,
                _event("late", 2023, milestone_type=MilestoneType.PHASE_3),
            ],
        )
    )
    clinical = next(branch for branch in tree.branches if branch.branch_id == "clinical")
    assert [item.pmid for item in clinical.events] == ["2"]
    assert {child.branch_id for child in clinical.sub_branches} == {"clinical_early", "clinical_late"}


def test_explicit_phase_signal_takes_priority_over_generic_rct_type() -> None:
    event = MilestoneDetector().detect_milestone(
        {
            "pmid": "phase-3",
            "year": 2022,
            "title": "Phase III randomized trial",
            "publication_types": ["Randomized Controlled Trial"],
        }
    )

    assert event is not None
    assert event.milestone_type is MilestoneType.PHASE_3


@pytest.mark.asyncio
async def test_explicit_pmid_mode_preserves_non_milestone_articles_as_background() -> None:
    class Searcher:
        async def fetch_details(self, pmids: list[str]) -> list[dict[str, Any]]:
            return [
                {"pmid": pmid, "year": 2020 + index, "title": f"Routine observational paper {pmid}"}
                for index, pmid in enumerate(pmids)
            ]

    timeline = await TimelineBuilder(Searcher()).build_timeline_from_pmids(["1", "2", "3"], topic="topic")

    assert [event.pmid for event in timeline.events] == ["1", "2", "3"]
    assert all(event.milestone_type is MilestoneType.OTHER for event in timeline.events)
    assert timeline.events[0].metadata["earliest_observed_in_scope"] is True
    snapshot = assemble_chronicle(topic="topic", timeline=timeline)
    assert all(entry.status is ChronicleEntryStatus.BACKGROUND for entry in snapshot.entries)


@pytest.mark.asyncio
async def test_landmark_candidate_cap_preserves_earliest_retrieved_article() -> None:
    class Searcher:
        async def search(self, topic: str, limit: int) -> list[dict[str, Any]]:
            del topic, limit
            return [
                {"pmid": "1", "year": 2000, "title": "Earliest retrieved", "rank": 0.01},
                *[
                    {
                        "pmid": str(index),
                        "year": 2008 + index,
                        "title": f"Later paper {index}",
                        "rank": 1 - index / 100,
                    }
                    for index in range(2, 7)
                ],
            ]

        async def get_citation_metrics(self, pmids: list[str]) -> dict[str, Any]:
            del pmids
            return {}

    class Scorer:
        def score_articles(
            self,
            articles: list[dict[str, Any]],
            **kwargs: Any,
        ) -> list[tuple[dict[str, Any], LandmarkScore]]:
            del kwargs
            return sorted(
                ((article, LandmarkScore(overall=float(article["rank"]))) for article in articles),
                key=lambda row: row[1].overall,
                reverse=True,
            )

    searcher: Any = Searcher()
    scorer: Any = Scorer()
    timeline = await TimelineBuilder(searcher, scorer=scorer).build_timeline(
        "topic",
        max_events=2,
        include_all=True,
    )

    assert timeline.events[0].pmid == "1"
    assert timeline.events[0].metadata["earliest_observed_in_scope"] is True
    assert timeline.events[-1].pmid == "6"


def test_slash_terms_are_preserved_except_for_controlled_mesh_qualifiers() -> None:
    timeline = ResearchTimeline(
        "immunotherapy",
        [
            _event("1", 2020, keywords=["PD-1/PD-L1"]),
            _event("2", 2021, keywords=["PD-1/PD-L1"]),
            _event("3", 2022, mesh_terms=["Neoplasms/drug therapy"]),
            _event("4", 2023, mesh_terms=["Neoplasms/drug therapy"]),
        ],
    )

    tree = build_chronicle_lineage(timeline)

    assert tree.metadata["lineage_diagnostics"]["basis"] == "topic_signals"
    assert {branch.label for branch in tree.branches} == {"PD-1/PD-L1", "Neoplasms"}


def test_singleton_signals_cannot_be_reported_as_semantic_lineage() -> None:
    timeline = ResearchTimeline(
        "therapy",
        [
            _event("1", 2020, mesh_terms=["Alpha Pathway"]),
            _event("2", 2021, mesh_terms=["Beta Pathway"]),
        ],
    )

    tree = build_chronicle_lineage(timeline)

    diagnostics = tree.metadata["lineage_diagnostics"]
    assert diagnostics["basis"] == "research_stage_fallback"
    assert diagnostics["signal_extraction"]["minimum_papers_per_signal"] == 2


def test_overlap_cannot_leave_a_high_confidence_single_paper_branch() -> None:
    events = [_event(str(index), 2000 + index, mesh_terms=["Alpha Pathway", "Beta Pathway"]) for index in range(7)]
    events.extend(
        [
            _event("7", 2007, mesh_terms=["Alpha Pathway"]),
            _event("8", 2008, mesh_terms=["Beta Pathway"]),
        ]
    )

    tree = build_chronicle_lineage(ResearchTimeline("therapy", events))
    diagnostics = tree.metadata["lineage_diagnostics"]

    assert diagnostics["basis"] == "research_stage_fallback"
    assert diagnostics["signal_extraction"]["signals_pruned_after_assignment"] == 1


def test_multi_signal_membership_is_preserved_and_significant_overlap_warns() -> None:
    timeline = ResearchTimeline(
        "therapy",
        [
            _event("1", 2001, mesh_terms=["Alpha Pathway"]),
            _event("2", 2002, mesh_terms=["Alpha Pathway"]),
            _event("3", 2003, mesh_terms=["Beta Pathway"]),
            _event("4", 2004, mesh_terms=["Beta Pathway"]),
            _event("5", 2005, mesh_terms=["Alpha Pathway", "Beta Pathway"]),
        ],
    )

    tree = build_chronicle_lineage(timeline)
    diagnostics = tree.metadata["lineage_diagnostics"]

    assert diagnostics["basis"] == "topic_signals"
    assert diagnostics["assignment_semantics"] == "single_primary_branch_with_cross_signal_links"
    assert diagnostics["overlap_event_count"] == 1
    assert diagnostics["overlap_ratio"] == 0.2
    assert diagnostics["overlap_ratio_among_assigned"] == 0.2
    assert diagnostics["max_signals_per_event"] == 2
    assert len(diagnostics["event_signal_memberships"]) == len(timeline.events)
    selected_by_label = {signal["label"]: signal for signal in diagnostics["selected_signals"]}
    assert selected_by_label["Alpha Pathway"]["primary_event_count"] == 3
    assert selected_by_label["Alpha Pathway"]["matched_event_count"] == 3
    assert selected_by_label["Beta Pathway"]["primary_event_count"] == 2
    assert selected_by_label["Beta Pathway"]["matched_event_count"] == 3

    cross_link = diagnostics["cross_signal_links"][0]
    assert cross_link["pmid"] == "5"
    assert len(cross_link["secondary_branch_ids"]) == 1
    assert {signal["label"] for signal in cross_link["matched_signals"]} == {
        "Alpha Pathway",
        "Beta Pathway",
    }

    snapshot = assemble_chronicle(topic="therapy", timeline=timeline, tree=tree)
    assert all("lineage_primary_signal" in entry.provenance for entry in snapshot.entries)
    assert all("lineage_matched_signals" in entry.provenance for entry in snapshot.entries)
    overlap_entry = next(entry for entry in snapshot.entries if entry.evidence.supporting_articles[0].pmid == "5")
    assert overlap_entry.provenance["lineage_primary_signal"]["label"] == "Alpha Pathway"
    assert overlap_entry.provenance["lineage_primary_signal"]["branch_id"] == overlap_entry.branch_id
    assert {signal["label"] for signal in overlap_entry.provenance["lineage_matched_signals"]} == {
        "Alpha Pathway",
        "Beta Pathway",
    }
    assert overlap_entry.provenance["lineage_matched_signal_count"] == 2
    assert overlap_entry.provenance["lineage_overlap"] is True
    assert overlap_entry.provenance["lineage_secondary_branch_ids"] == cross_link["secondary_branch_ids"]
    assert overlap_entry.provenance["lineage_cross_links"][0]["relationship"] == "also_matches_topic_signal"

    finding = next(item for item in audit_chronicle(snapshot).findings if item.check == "lineage_semantics")
    assert finding.status == "warn"
    assert finding.details["overlap_event_count"] == 1
    assert finding.details["overlap_ratio"] == 0.2
    assert "primary assignments with explicit cross-links" in finding.message
    assert "not cleanly separated or causal lineages" in finding.message


def test_low_topic_overlap_remains_auditable_without_overstating_lineage() -> None:
    events = [
        *[_event(f"a{index}", 2000 + index, mesh_terms=["Alpha Pathway"]) for index in range(1, 6)],
        *[_event(f"b{index}", 2010 + index, mesh_terms=["Beta Pathway"]) for index in range(1, 6)],
    ]
    events[-1].metadata["mesh_terms"] = ["Alpha Pathway", "Beta Pathway"]
    timeline = ResearchTimeline("therapy", events)
    tree = build_chronicle_lineage(timeline)
    snapshot = assemble_chronicle(topic="therapy", timeline=timeline, tree=tree)

    diagnostics = tree.metadata["lineage_diagnostics"]
    assert diagnostics["overlap_event_count"] == 1
    assert diagnostics["overlap_ratio"] == 0.1
    finding = next(item for item in audit_chronicle(snapshot).findings if item.check == "lineage_semantics")
    assert finding.status == "pass"
    assert "primary assignments rather than causal lineages" in finding.message


def test_signal_extraction_is_bounded_and_reports_omissions() -> None:
    events = [
        _event(
            str(event_index),
            2000 + event_index,
            mesh_terms=[
                f"{event_index}-{'x' * 1000}" if term_index == 0 else f"Specific signal {event_index} {term_index}"
                for term_index in range(65)
            ],
        )
        for event_index in range(65)
    ]

    tree = build_chronicle_lineage(ResearchTimeline("bounded topic", events))
    extraction = tree.metadata["lineage_diagnostics"]["signal_extraction"]

    assert extraction["max_terms_per_event"] == 64
    assert extraction["terms_omitted_per_event_limit"] == 65
    assert extraction["oversized_terms_truncated"] == 65
    assert extraction["unique_signals_retained"] == extraction["max_unique_topic_signals"]
    assert extraction["unique_signals_omitted_limit"] > 0


def test_chronicle_claims_are_conservative_and_scores_have_distinct_semantics() -> None:
    timeline = ResearchTimeline(
        "therapy",
        [
            _event(
                "10",
                2024,
                milestone_type=MilestoneType.META_ANALYSIS,
                confidence=0.73,
                landmark=LandmarkScore(overall=0.99, citation_impact=1.0),
            )
        ],
    )

    entry = assemble_chronicle(topic="therapy", timeline=timeline).entries[0]

    assert entry.confidence == 0.73
    assert entry.provenance["confidence_semantics"] == "milestone_detection_confidence"
    assert entry.provenance["landmark_importance_score"] == 0.99
    assert "categorized as" in entry.summary_claim
    assert "reframed" not in entry.summary_claim


def test_withdrawal_is_a_historical_event_not_an_automatically_superseded_claim() -> None:
    timeline = ResearchTimeline(
        "drug",
        [_event("20", 2020, milestone_type=MilestoneType.WITHDRAWAL)],
    )

    entry = assemble_chronicle(topic="drug", timeline=timeline).entries[0]

    assert entry.status is ChronicleEntryStatus.ACTIVE
