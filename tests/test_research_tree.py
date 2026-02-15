"""
Tests for Research Tree — domain entities and branch detection.

Covers:
    - ResearchBranch: properties, serialization, sub-branches
    - ResearchTree: aggregation, text tree, mermaid mindmap
    - build_research_tree: milestone-type-based branching, clinical sub-branches
"""

from __future__ import annotations

import json

from pubmed_search.application.timeline.branch_detector import (
    build_research_tree,
)
from pubmed_search.domain.entities.research_tree import (
    ResearchBranch,
    ResearchTree,
)
from pubmed_search.domain.entities.timeline import (
    LandmarkScore,
    MilestoneType,
    ResearchTimeline,
    TimelineEvent,
)

# ─────────────────────────────────────────────────────────────────────
# Fixtures / Helpers
# ─────────────────────────────────────────────────────────────────────


def _event(
    pmid: str,
    year: int,
    milestone_type: MilestoneType,
    label: str = "Label",
    title: str = "Title",
    landmark_overall: float | None = None,
) -> TimelineEvent:
    """Helper to create a TimelineEvent."""
    ls = LandmarkScore(overall=landmark_overall) if landmark_overall is not None else None
    return TimelineEvent(
        pmid=pmid,
        year=year,
        milestone_type=milestone_type,
        title=title,
        milestone_label=label,
        landmark_score=ls,
    )


def _make_timeline(events: list[TimelineEvent], topic: str = "TestTopic") -> ResearchTimeline:
    return ResearchTimeline(
        topic=topic,
        events=events,
        metadata={"total_searched": len(events) * 3},
    )


# ─────────────────────────────────────────────────────────────────────
# ResearchBranch Tests
# ─────────────────────────────────────────────────────────────────────


class TestResearchBranch:
    def test_empty_branch(self):
        b = ResearchBranch(branch_id="test", label="Test")
        assert b.is_empty
        assert b.total_events == 0
        assert b.year_range is None
        assert b.all_events == []

    def test_branch_with_events(self):
        events = [
            _event("1", 2020, MilestoneType.FIRST_REPORT),
            _event("2", 2018, MilestoneType.MECHANISM_DISCOVERY),
        ]
        b = ResearchBranch(branch_id="disc", label="Discovery", events=events)
        assert not b.is_empty
        assert b.total_events == 2
        assert b.year_range == (2018, 2020)
        # Events are sorted chronologically
        assert b.events[0].year == 2018
        assert b.events[1].year == 2020

    def test_branch_with_sub_branches(self):
        sub1 = ResearchBranch(
            branch_id="phase1",
            label="Phase I",
            events=[_event("1", 2015, MilestoneType.PHASE_1)],
            order=1,
        )
        sub2 = ResearchBranch(
            branch_id="phase3",
            label="Phase III",
            events=[
                _event("2", 2020, MilestoneType.PHASE_3),
                _event("3", 2022, MilestoneType.PHASE_3),
            ],
            order=2,
        )
        parent = ResearchBranch(
            branch_id="clinical",
            label="Clinical",
            sub_branches=[sub2, sub1],  # Out of order to test sorting
        )
        assert parent.total_events == 3
        assert parent.year_range == (2015, 2022)
        # Sub-branches sorted by order
        assert parent.sub_branches[0].branch_id == "phase1"
        assert parent.sub_branches[1].branch_id == "phase3"
        # all_events returns all chronologically
        all_ev = parent.all_events
        assert len(all_ev) == 3
        assert all_ev[0].year == 2015

    def test_to_dict(self):
        b = ResearchBranch(
            branch_id="safety",
            label="Safety",
            icon="\u26a0\ufe0f",
            events=[_event("1", 2020, MilestoneType.SAFETY_ALERT)],
        )
        d = b.to_dict()
        assert d["branch_id"] == "safety"
        assert d["label"] == "Safety"
        assert d["total_events"] == 1
        assert d["year_range"] == (2020, 2020)
        assert len(d["events"]) == 1

    def test_to_dict_with_sub_branches(self):
        sub = ResearchBranch(
            branch_id="sub",
            label="Sub",
            events=[_event("1", 2020, MilestoneType.PHASE_1)],
        )
        empty_sub = ResearchBranch(branch_id="empty", label="Empty")
        parent = ResearchBranch(
            branch_id="parent",
            label="Parent",
            sub_branches=[sub, empty_sub],
        )
        d = parent.to_dict()
        # Empty sub-branches excluded
        assert len(d["sub_branches"]) == 1
        assert d["sub_branches"][0]["branch_id"] == "sub"


# ─────────────────────────────────────────────────────────────────────
# ResearchTree Tests
# ─────────────────────────────────────────────────────────────────────


class TestResearchTree:
    def test_empty_tree(self):
        tree = ResearchTree(topic="Empty")
        assert tree.total_events == 0
        assert tree.active_branches == []
        assert tree.year_range is None

    def test_tree_with_branches(self):
        b1 = ResearchBranch(
            branch_id="a",
            label="A",
            events=[_event("1", 2010, MilestoneType.FIRST_REPORT)],
        )
        b2 = ResearchBranch(
            branch_id="b",
            label="B",
            events=[_event("2", 2020, MilestoneType.META_ANALYSIS)],
        )
        empty = ResearchBranch(branch_id="c", label="C")
        tree = ResearchTree(topic="Test", branches=[b1, b2, empty])
        assert tree.total_events == 2
        assert len(tree.active_branches) == 2
        assert tree.year_range == (2010, 2020)

    def test_to_dict(self):
        tree = ResearchTree(
            topic="Test",
            branches=[
                ResearchBranch(
                    branch_id="a",
                    label="A",
                    events=[_event("1", 2020, MilestoneType.FIRST_REPORT)],
                ),
            ],
            total_articles=100,
        )
        d = tree.to_dict()
        assert d["topic"] == "Test"
        assert d["total_events"] == 1
        assert d["total_branches"] == 1
        assert d["year_range"] == (2020, 2020)
        assert len(d["branches"]) == 1

    def test_to_text_tree_basic(self):
        tree = ResearchTree(
            topic="Remimazolam",
            branches=[
                ResearchBranch(
                    branch_id="discovery",
                    label="Discovery",
                    icon="\U0001f52c",
                    events=[
                        _event("1", 2010, MilestoneType.FIRST_REPORT, title="First synthesis"),
                        _event("2", 2016, MilestoneType.MECHANISM_DISCOVERY, title="Mechanism found"),
                    ],
                ),
                ResearchBranch(
                    branch_id="safety",
                    label="Safety",
                    icon="\u26a0\ufe0f",
                    events=[
                        _event("3", 2020, MilestoneType.SAFETY_ALERT, title="Safety concern", landmark_overall=0.8),
                    ],
                ),
            ],
        )
        text = tree.to_text_tree()
        assert "## Research Tree: Remimazolam" in text
        assert "Branches" in text
        assert "\U0001f52c" in text  # Discovery icon
        assert "2010" in text
        assert "First synthesis" in text
        assert "PMID: 1" in text
        assert "\u26a0\ufe0f" in text  # Safety icon
        assert "\u2b50" in text  # Star from landmark score 0.8

    def test_to_text_tree_with_sub_branches(self):
        tree = ResearchTree(
            topic="Drug X",
            branches=[
                ResearchBranch(
                    branch_id="clinical",
                    label="Clinical Development",
                    icon="\U0001f3e5",
                    sub_branches=[
                        ResearchBranch(
                            branch_id="early",
                            label="Phase I/II",
                            events=[_event("1", 2015, MilestoneType.PHASE_1, title="Phase 1 trial")],
                            order=1,
                        ),
                        ResearchBranch(
                            branch_id="late",
                            label="Phase III/IV",
                            events=[_event("2", 2020, MilestoneType.PHASE_3, title="Phase 3 pivotal")],
                            order=2,
                        ),
                    ],
                ),
            ],
        )
        text = tree.to_text_tree()
        assert "Phase I/II" in text
        assert "Phase III/IV" in text
        assert "2015" in text
        assert "2020" in text

    def test_to_mermaid_mindmap(self):
        tree = ResearchTree(
            topic="TopicX",
            branches=[
                ResearchBranch(
                    branch_id="a",
                    label="Branch A",
                    icon="\U0001f52c",
                    events=[_event("1", 2020, MilestoneType.FIRST_REPORT, label="First")],
                ),
            ],
        )
        mm = tree.to_mermaid_mindmap()
        assert "mindmap" in mm
        assert "root((TopicX))" in mm
        assert "Branch A" in mm
        assert "2020" in mm

    def test_to_dict_serializable(self):
        """Ensure to_dict output is JSON-serializable."""
        tree = ResearchTree(
            topic="Test",
            branches=[
                ResearchBranch(
                    branch_id="a",
                    label="A",
                    events=[_event("1", 2020, MilestoneType.FIRST_REPORT, landmark_overall=0.7)],
                ),
            ],
        )
        # Should not raise
        json_str = json.dumps(tree.to_dict(), ensure_ascii=False)
        parsed = json.loads(json_str)
        assert parsed["topic"] == "Test"


# ─────────────────────────────────────────────────────────────────────
# build_research_tree Tests (BranchDetector)
# ─────────────────────────────────────────────────────────────────────


class TestBuildResearchTree:
    def test_empty_timeline(self):
        timeline = _make_timeline([])
        tree = build_research_tree(timeline)
        assert tree.total_events == 0
        assert tree.active_branches == []
        assert tree.topic == "TestTopic"

    def test_single_branch(self):
        events = [
            _event("1", 2010, MilestoneType.FIRST_REPORT),
            _event("2", 2015, MilestoneType.MECHANISM_DISCOVERY),
        ]
        tree = build_research_tree(_make_timeline(events))
        assert len(tree.active_branches) == 1
        assert tree.active_branches[0].branch_id == "discovery"
        assert tree.active_branches[0].total_events == 2

    def test_multiple_branches(self):
        events = [
            _event("1", 2010, MilestoneType.FIRST_REPORT),
            _event("2", 2018, MilestoneType.FDA_APPROVAL),
            _event("3", 2020, MilestoneType.META_ANALYSIS),
            _event("4", 2022, MilestoneType.SAFETY_ALERT),
        ]
        tree = build_research_tree(_make_timeline(events))
        # Should have: discovery, regulatory, evidence, safety
        branch_ids = {b.branch_id for b in tree.active_branches}
        assert branch_ids == {"discovery", "regulatory", "evidence", "safety"}
        assert tree.total_events == 4

    def test_clinical_sub_branches(self):
        """Clinical branch splits into Phase I/II and Phase III/IV when both exist."""
        events = [
            _event("1", 2014, MilestoneType.PHASE_1),
            _event("2", 2016, MilestoneType.PHASE_2),
            _event("3", 2020, MilestoneType.PHASE_3),
            _event("4", 2022, MilestoneType.PHASE_4),
        ]
        tree = build_research_tree(_make_timeline(events))
        clinical = [b for b in tree.active_branches if b.branch_id == "clinical"]
        assert len(clinical) == 1
        clinic = clinical[0]
        # Should have sub-branches
        assert len(clinic.sub_branches) == 2
        assert clinic.sub_branches[0].label == "Phase I/II"
        assert clinic.sub_branches[0].total_events == 2
        assert clinic.sub_branches[1].label == "Phase III/IV"
        assert clinic.sub_branches[1].total_events == 2
        # Parent branch events should be empty (all in sub-branches)
        assert len(clinic.events) == 0
        assert clinic.total_events == 4

    def test_clinical_single_phase_no_sub_branches(self):
        """Clinical branch stays flat when only one phase group exists."""
        events = [
            _event("1", 2014, MilestoneType.PHASE_1),
            _event("2", 2016, MilestoneType.PHASE_2),
        ]
        tree = build_research_tree(_make_timeline(events))
        clinical = [b for b in tree.active_branches if b.branch_id == "clinical"]
        assert len(clinical) == 1
        # No sub-branches, events directly on branch
        assert len(clinical[0].sub_branches) == 0
        assert len(clinical[0].events) == 2

    def test_branch_ordering(self):
        """Branches appear in the defined research order."""
        events = [
            _event("1", 2022, MilestoneType.GUIDELINE),  # practice = order 5
            _event("2", 2010, MilestoneType.FIRST_REPORT),  # discovery = order 1
            _event("3", 2020, MilestoneType.SAFETY_ALERT),  # safety = order 6
            _event("4", 2018, MilestoneType.FDA_APPROVAL),  # regulatory = order 3
        ]
        tree = build_research_tree(_make_timeline(events))
        orders = [b.order for b in tree.active_branches]
        assert orders == sorted(orders), "Branches should be in research progression order"

    def test_general_branch(self):
        """OTHER milestone type goes to general branch."""
        events = [
            _event("1", 2020, MilestoneType.OTHER),
        ]
        tree = build_research_tree(_make_timeline(events))
        assert len(tree.active_branches) == 1
        assert tree.active_branches[0].branch_id == "general"

    def test_landmark_breakthrough_branch(self):
        """LANDMARK_STUDY and BREAKTHROUGH go to landmark branch."""
        events = [
            _event("1", 2020, MilestoneType.LANDMARK_STUDY),
            _event("2", 2022, MilestoneType.BREAKTHROUGH),
        ]
        tree = build_research_tree(_make_timeline(events))
        assert len(tree.active_branches) == 1
        assert tree.active_branches[0].branch_id == "landmark"
        assert tree.active_branches[0].total_events == 2

    def test_metadata_preserved(self):
        timeline = _make_timeline(
            [_event("1", 2020, MilestoneType.FIRST_REPORT)],
            topic="MyTopic",
        )
        tree = build_research_tree(timeline)
        assert tree.topic == "MyTopic"
        assert "tree_branches" in tree.metadata

    def test_events_chronological_within_branch(self):
        """Events within a branch should be in chronological order."""
        events = [
            _event("3", 2022, MilestoneType.META_ANALYSIS),
            _event("1", 2018, MilestoneType.SYSTEMATIC_REVIEW),
            _event("2", 2020, MilestoneType.META_ANALYSIS),
        ]
        tree = build_research_tree(_make_timeline(events))
        evidence = tree.active_branches[0]
        years = [e.year for e in evidence.events]
        assert years == [2018, 2020, 2022]

    def test_landmark_scores_preserved(self):
        """Landmark scores flow through to tree events."""
        events = [
            _event("1", 2020, MilestoneType.FIRST_REPORT, landmark_overall=0.85),
            _event("2", 2022, MilestoneType.META_ANALYSIS, landmark_overall=0.60),
        ]
        tree = build_research_tree(_make_timeline(events))
        for branch in tree.active_branches:
            for event in branch.events:
                assert event.landmark_score is not None

    def test_full_spectrum(self):
        """Full research lifecycle with all branch types."""
        events = [
            _event("01", 2005, MilestoneType.FIRST_REPORT),
            _event("02", 2008, MilestoneType.MECHANISM_DISCOVERY),
            _event("03", 2010, MilestoneType.PRECLINICAL),
            _event("04", 2012, MilestoneType.PHASE_1),
            _event("05", 2014, MilestoneType.PHASE_2),
            _event("06", 2016, MilestoneType.PHASE_3),
            _event("07", 2017, MilestoneType.PHASE_4),
            _event("08", 2018, MilestoneType.FDA_APPROVAL),
            _event("09", 2019, MilestoneType.EMA_APPROVAL),
            _event("10", 2020, MilestoneType.META_ANALYSIS),
            _event("11", 2021, MilestoneType.SYSTEMATIC_REVIEW),
            _event("12", 2022, MilestoneType.GUIDELINE),
            _event("13", 2023, MilestoneType.SAFETY_ALERT),
            _event("14", 2024, MilestoneType.LANDMARK_STUDY),
            _event("15", 2024, MilestoneType.OTHER),
        ]
        tree = build_research_tree(_make_timeline(events, topic="FullSpectrum"))
        assert tree.topic == "FullSpectrum"
        assert tree.total_events == 15
        assert tree.year_range == (2005, 2024)

        branch_ids = {b.branch_id for b in tree.active_branches}
        expected = {"discovery", "clinical", "regulatory", "evidence", "practice", "safety", "landmark", "general"}
        assert branch_ids == expected

        # Clinical should have sub-branches (both early and late phases)
        clinical = next(b for b in tree.active_branches if b.branch_id == "clinical")
        assert len(clinical.sub_branches) == 2

    def test_to_text_tree_output(self):
        """build_research_tree → to_text_tree produces readable output."""
        events = [
            _event("1", 2010, MilestoneType.FIRST_REPORT, title="First Report of Drug X"),
            _event("2", 2018, MilestoneType.PHASE_3, title="Phase 3 Pivotal Trial"),
            _event("3", 2020, MilestoneType.FDA_APPROVAL, title="FDA Approves Drug X", landmark_overall=0.9),
        ]
        tree = build_research_tree(_make_timeline(events, topic="Drug X"))
        text = tree.to_text_tree()
        assert "## Research Tree: Drug X" in text
        assert "Discovery" in text
        assert "Regulatory" in text
        assert "2010" in text
        assert "2020" in text
        assert "PMID: 3" in text

    def test_to_mermaid_mindmap_output(self):
        """build_research_tree → to_mermaid_mindmap produces valid syntax."""
        events = [
            _event("1", 2010, MilestoneType.FIRST_REPORT, label="First Report"),
            _event("2", 2020, MilestoneType.META_ANALYSIS, label="Meta-Analysis"),
        ]
        tree = build_research_tree(_make_timeline(events, topic="TopicY"))
        mm = tree.to_mermaid_mindmap()
        assert "mindmap" in mm
        assert "root((TopicY))" in mm
        assert "Discovery" in mm
        assert "Evidence Synthesis" in mm

    def test_to_json_tree_serializable(self):
        """build_research_tree → to_dict → JSON round-trip."""
        events = [
            _event("1", 2020, MilestoneType.FIRST_REPORT, landmark_overall=0.7),
            _event("2", 2022, MilestoneType.PHASE_3, landmark_overall=0.5),
        ]
        tree = build_research_tree(_make_timeline(events))
        json_str = json.dumps(tree.to_dict(), ensure_ascii=False)
        parsed = json.loads(json_str)
        assert parsed["total_events"] == 2
        assert len(parsed["branches"]) >= 1
