"""Regressions from the v0.11.0 Research Chronicle review.

Chronicle quotes abstract sentences as the authors' own words and labels study
designs. Each case below reproduces a reviewed failure: boilerplate quoted as a
conclusion, abbreviations that cut a quote in half, outcome sentences taken as
conclusions, silent abstract truncation, non-randomized studies and protocols
labelled as completed RCTs, notices labelled as trial milestones, milestones
suppressed relative to master, background mentions treated as self-description,
and unknown citation counts displayed as zero.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pubmed_search.application.chronicle import assemble_chronicle, audit_chronicle
from pubmed_search.application.chronicle.highlights import (
    select_extractive_highlight,
    sentence_spans,
    verify_highlight,
)
from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.application.timeline import MilestoneDetector, TimelineBuilder
from pubmed_search.domain.entities.timeline import EvidenceLevel, MilestoneType, ResearchTimeline
from pubmed_search.domain.services.study_design import (
    BASIS_PUBLICATION_TYPE,
    BASIS_TEXT,
    FAMILY_NOTICE,
    FAMILY_PROTOCOL,
    classify_study_design,
)

# ── Extractive highlights: boilerplate is never the authors' conclusion ──────

_FINDING = "Exacerbations were reduced by half with the antibody."
_BASE = f"We enrolled 120 adults with severe asthma in a crossover study. {_FINDING} "


@pytest.mark.parametrize(
    "tail",
    [
        "(Funded by Novo Nordisk; ClinicalTrials.gov number, NCT01234567.)",
        "Registered at ClinicalTrials.gov (NCT01234567).",
        "This trial was registered with ClinicalTrials.gov, NCT01234567.",
        "Supported by the National Institutes of Health and the Wellcome Trust.",
        "The study was funded by the Bill and Melinda Gates Foundation.",
        "Published by Elsevier Ltd. All rights reserved.",
        "Copyright © 2024 Wiley Periodicals LLC.",
        "© 2024 The Authors. Published by Elsevier B.V. on behalf of the society.",
        "(PsycInfo Database Record (c) 2024 APA, all rights reserved).",
        "This is an open access article under the CC BY-NC-ND license.",
        "Systematic review registration: PROSPERO CRD42020123456.",
        "Trial registration number ISRCTN12345678 (retrospectively registered).",
        "The protocol was registered in the Chinese Clinical Trial Registry (ChiCTR2000031234).",
    ],
)
def test_funding_registration_and_publisher_statements_are_never_quoted(tail: str) -> None:
    abstract = _BASE + tail
    highlight = select_extractive_highlight(abstract)

    assert highlight is not None
    assert highlight.text == _FINDING
    assert abstract[highlight.char_start : highlight.char_end] == highlight.text


def test_short_abstract_fallback_skips_boilerplate_and_never_quotes_only_boilerplate() -> None:
    short = select_extractive_highlight("We studied 5 rats. Copyright 2020.")
    assert short is not None
    assert short.text == "We studied 5 rats."

    assert select_extractive_highlight("Funded by NIH.") is None
    assert select_extractive_highlight("(Funded by the NIH; NCT01234567.)") is None


def test_structured_conclusions_skip_a_glued_funding_sentence() -> None:
    parts = [
        ("RESULTS", "RESULTS", "Mortality was 12% in both groups."),
        (
            "CONCLUSIONS",
            "CONCLUSIONS",
            "(Funded by the NHLBI; ClinicalTrials.gov number, NCT00000620.) Drug X did not help.",
        ),
    ]
    abstract = " ".join(text for _, _, text in parts)
    sections, offset = [], 0
    for label, category, text in parts:
        sections.append({"label": label, "nlm_category": category, "start": offset, "end": offset + len(text)})
        offset += len(text) + 1

    highlight = select_extractive_highlight(abstract, sections)
    assert highlight is not None
    assert highlight.text == "Drug X did not help."


# ── Sentence splitting: abbreviations do not end a quoted sentence ──────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Drug A was compared with drug B (e.g. Placebo) in 40 patients. We found no effect.",
            ["Drug A was compared with drug B (e.g. Placebo) in 40 patients.", "We found no effect."],
        ),
        (
            "Low-dose ketamine (e.g. 0.5 mg/kg) reduced opioid use. Delirium was unchanged.",
            ["Low-dose ketamine (e.g. 0.5 mg/kg) reduced opioid use.", "Delirium was unchanged."],
        ),
        (
            "Ketamine [i.e. S-ketamine] shortened recovery. Nausea was rare.",
            ["Ketamine [i.e. S-ketamine] shortened recovery.", "Nausea was rare."],
        ),
        (
            "Mortality was 5% (vs. 10% with placebo) at day 28. Harms were similar.",
            ["Mortality was 5% (vs. 10% with placebo) at day 28.", "Harms were similar."],
        ),
        (
            "As reported by Smith et al. (2019), BIS reduced exposure. We confirm this.",
            ["As reported by Smith et al. (2019), BIS reduced exposure.", "We confirm this."],
        ),
        (
            "Recovery was faster (Fig. 2) and nausea rarer (Figs. 3 and 4). Costs fell.",
            ["Recovery was faster (Fig. 2) and nausea rarer (Figs. 3 and 4).", "Costs fell."],
        ),
        (
            "Doses (approx. 50 mg) were titrated (cf. Table 2) over ca. 10 min. Pain fell.",
            ["Doses (approx. 50 mg) were titrated (cf. Table 2) over ca. 10 min.", "Pain fell."],
        ),
        (
            "Enrolment ran from Jan. 2019 to Dec. 2020 at No. 3 Hospital. Sites were academic.",
            ["Enrolment ran from Jan. 2019 to Dec. 2020 at No. 3 Hospital.", "Sites were academic."],
        ),
        (
            "The dose was 0.5 mg/kg. Patients recovered within 24 h. P < .05 was significant.",
            ["The dose was 0.5 mg/kg.", "Patients recovered within 24 h.", "P < .05 was significant."],
        ),
    ],
)
def test_sentence_spans_keep_abbreviations_decimals_and_units_inside_sentences(text: str, expected: list[str]) -> None:
    spans = sentence_spans(text)
    assert [text[start:end] for start, end in spans] == expected


def test_conclusion_quote_keeps_its_subject_before_an_abbreviation() -> None:
    parts = [
        ("RESULTS", "RESULTS", "Opioid use fell by 30%."),
        (
            "CONCLUSIONS",
            "CONCLUSIONS",
            "Low-dose ketamine (e.g. 0.5 mg/kg) reduced postoperative opioid consumption without excess delirium.",
        ),
    ]
    abstract = " ".join(text for _, _, text in parts)
    sections, offset = [], 0
    for label, category, text in parts:
        sections.append({"label": label, "nlm_category": category, "start": offset, "end": offset + len(text)})
        offset += len(text) + 1

    highlight = select_extractive_highlight(abstract, sections)
    assert highlight is not None
    assert highlight.text == parts[1][2]
    assert abstract[highlight.char_start : highlight.char_end] == highlight.text


# ── Conclusion cues: an outcome noun is not a summary cue ───────────────────


def test_overall_survival_is_not_mistaken_for_a_conclusion_cue() -> None:
    abstract = (
        "We randomly assigned 600 patients with metastatic disease to drug X or docetaxel. "
        "Overall survival was 14.2 months with drug X and 10.1 months with docetaxel (HR 0.70; 95% CI, 0.58-0.85). "
        "Grade 3 or higher adverse events occurred in 20% and 45% of patients. "
        "Drug X should be considered a new standard of second-line therapy."
    )
    highlight = select_extractive_highlight(abstract)
    assert highlight is not None
    assert (highlight.selection_rule, highlight.text) == (
        "final_sentence_of_abstract",
        "Drug X should be considered a new standard of second-line therapy.",
    )

    cue = select_extractive_highlight(
        "We studied 80 adults after surgery. Overall, guided dosing shortened recovery. Larger trials are planned."
    )
    assert cue is not None
    assert (cue.selection_rule, cue.text) == ("conclusion_cue_sentence", "Overall, guided dosing shortened recovery.")


# ── Abstract truncation is disclosed and the cut fragment is never quoted ──


def test_pubmed_truncation_marker_and_cut_fragment_are_not_quoted() -> None:
    abstract = (
        "Forty patients received the drug. Pain scores fell by half within one day. "
        "Recovery of bowel function was faster in the treated (ABSTRACT TRUNCATED AT 250 WORDS)"
    )
    highlight = select_extractive_highlight(abstract)

    assert highlight is not None
    assert highlight.text == "Pain scores fell by half within one day."
    assert highlight.truncated is True
    assert highlight.selection_rule == "last_complete_sentence_before_truncation"
    provenance = highlight.to_provenance(abstract=abstract, evidence_id="pmid:1", pmid="1")
    assert provenance["abstract_truncated"] is True
    assert provenance["truncation_basis"] == ["pubmed_truncation_marker"]
    assert verify_highlight(provenance, abstract) == []


def _long_structured_article(pmid: str = "424242") -> dict[str, Any]:
    background = "Background sentence about perioperative monitoring and recovery. " * 330
    parts = [
        ("BACKGROUND", "BACKGROUND", background.strip()),
        ("RESULTS", "RESULTS", "Recovery was faster with guidance. Nausea was rarer with guidance overall."),
        ("CONCLUSIONS", "CONCLUSIONS", "Guided anaesthesia shortened recovery in older adults."),
    ]
    abstract = " ".join(text for _, _, text in parts)
    sections, offset = [], 0
    for label, category, text in parts:
        sections.append({"label": label, "nlm_category": category, "start": offset, "end": offset + len(text)})
        offset += len(text) + 1
    return {
        "pmid": pmid,
        "year": 2020,
        "title": "Guided anaesthesia and recovery",
        "publication_types": ["Randomized Controlled Trial"],
        "abstract": abstract,
        "abstract_sections": sections,
    }


def test_stored_abstract_prefix_limit_is_disclosed_and_audited() -> None:
    article = _long_structured_article()
    assert len(article["abstract"]) > 20_000
    event = MilestoneDetector().detect_milestone(article)
    assert event is not None
    assert event.metadata["abstract_truncated"] is True
    assert event.metadata["abstract_source_char_length"] == len(article["abstract"])
    # The section that straddles the cut is kept (clipped), not discarded.
    assert event.metadata["abstract_sections"][0]["label"] == "BACKGROUND"

    snapshot = assemble_chronicle(topic="anaesthesia", timeline=ResearchTimeline("anaesthesia", [event]))
    entry = snapshot.entries[0]
    stored = entry.evidence.supporting_articles[0].abstract
    assert stored is not None
    assert len(stored) == 20_000
    truncation = entry.provenance["abstract_truncation"]
    assert truncation == {
        "truncated": True,
        "basis": ["stored_abstract_character_limit"],
        "stored_char_length": 20_000,
        "source_char_length": len(article["abstract"]),
    }
    highlight = entry.provenance["extractive_highlight"]
    assert highlight["abstract_truncated"] is True
    assert highlight["char_end"] < len(stored)
    assert verify_highlight(highlight, stored) == []

    finding = next(item for item in audit_chronicle(snapshot).findings if item.check == "extractive_highlights")
    assert finding.status == "warn"
    assert finding.details["truncated_abstracts"][0]["entry_id"] == entry.entry_id
    assert "truncated" in finding.message


def test_untruncated_abstract_records_no_truncation() -> None:
    article = {
        "pmid": "7",
        "year": 2020,
        "title": "A trial",
        "publication_types": ["Randomized Controlled Trial"],
        "abstract": "We studied forty adults after surgery. Guided dosing shortened recovery overall.",
    }
    event = MilestoneDetector().detect_milestone(article)
    assert event is not None
    snapshot = assemble_chronicle(topic="t", timeline=ResearchTimeline("t", [event]))
    entry = snapshot.entries[0]
    assert entry.provenance["abstract_truncation"] is None
    assert entry.provenance["extractive_highlight"]["abstract_truncated"] is False
    finding = next(item for item in audit_chronicle(snapshot).findings if item.check == "extractive_highlights")
    assert finding.status == "pass"


# ── Study-design labels: non-randomized studies and protocols are not RCTs ──


@pytest.mark.parametrize(
    ("title", "key", "label"),
    [
        (
            "A non-randomized controlled trial of early mobilisation after hip fracture",
            "non_randomized_trial",
            "Non-randomized Trial",
        ),
        ("Nonrandomised, controlled trial of nurse-led sedation", "non_randomized_trial", "Non-randomized Trial"),
        ("A non‐randomised trial of chlorhexidine bathing", "non_randomized_trial", "Non-randomized Trial"),
        ("Quasi-randomised trial of chlorhexidine bathing", "quasi_randomized_trial", "Quasi-randomized Trial"),
        ("Protocol for a randomised controlled trial of ketamine", "trial_protocol", "Clinical Trial Protocol"),
        (
            "Ketamine versus placebo (KETA): study protocol for a randomised controlled trial",
            "trial_protocol",
            "Clinical Trial Protocol",
        ),
        ("Rationale and design of the ENGAGES randomized trial", "trial_protocol", "Clinical Trial Protocol"),
        (
            "Effect of an enhanced recovery protocol for colorectal surgery: a randomized clinical trial",
            "rct",
            "Randomized Controlled Trial",
        ),
        ("Protocol-driven weaning from ventilation: a randomized trial", "rct", "Randomized Controlled Trial"),
    ],
)
def test_title_heuristics_do_not_call_non_randomized_studies_or_protocols_rcts(
    title: str, key: str, label: str
) -> None:
    design = classify_study_design(["Journal Article"], [], title=title)
    assert (design.key, design.label, design.basis) == (key, label, BASIS_TEXT)


def test_abstract_heuristics_ignore_background_randomized_trials() -> None:
    previous = classify_study_design(
        ["Journal Article"],
        [],
        title="Ketamine",
        abstract="In a previous randomized trial, ketamine reduced pain. We now report a cohort.",
    )
    assert previous.key == "unspecified"
    pooled = classify_study_design(
        ["Journal Article"],
        [],
        title="Ketamine for depression",
        abstract="We searched MEDLINE for trials in which adults were randomized to ketamine or placebo.",
    )
    assert pooled.key == "unspecified"
    # A self-describing allocation sentence is still recognised.
    own = classify_study_design(
        ["Journal Article"], [], title="Ketamine", abstract="Ninety adults were randomized to ketamine or placebo."
    )
    assert (own.key, own.basis) == ("rct", BASIS_TEXT)


def test_protocol_publication_type_outranks_rct_and_phase_types() -> None:
    design = classify_study_design(["Clinical Trial Protocol", "Randomized Controlled Trial", "Journal Article"])
    assert (design.key, design.family, design.basis) == ("trial_protocol", FAMILY_PROTOCOL, BASIS_PUBLICATION_TYPE)
    assert design.display_label == "Clinical Trial Protocol (randomized)"
    assert set(design.matched) == {"Clinical Trial Protocol", "Randomized Controlled Trial"}

    phased = classify_study_design(["Clinical Trial, Phase III", "Clinical Trial Protocol"])
    assert phased.display_label == "Clinical Trial Protocol (Phase III)"

    # A completed RCT is unchanged.
    rct = classify_study_design(["Randomized Controlled Trial", "Multicenter Study"])
    assert (rct.key, rct.display_label) == ("rct", "Randomized Controlled Trial (multicenter)")


@pytest.mark.parametrize("notice", ["Published Erratum", "Retraction of Publication", "Expression of Concern"])
def test_publication_notices_have_their_own_family(notice: str) -> None:
    design = classify_study_design([notice, "Randomized Controlled Trial"], title="Erratum: Phase 3 trial of X")
    assert (design.key, design.family) == ("notice", FAMILY_NOTICE)


# ── Milestones: notices and protocols are not completed trials ──────────────


@pytest.mark.parametrize(
    "article",
    [
        {"publication_types": ["Published Erratum"], "title": "Erratum: Phase 3 trial of X"},
        {"publication_types": ["Retraction of Publication"], "title": "Retraction: A randomized phase 3 trial of X"},
        {"publication_types": ["Expression of Concern"], "title": "Expression of concern: pivotal trial of X"},
        {
            "publication_types": ["Clinical Trial Protocol", "Randomized Controlled Trial"],
            "title": "Protocol for a phase 3 trial of X",
        },
        {"publication_types": ["Clinical Trial Protocol", "Clinical Trial, Phase III"], "title": "The X-3 protocol"},
        {"publication_types": ["Journal Article"], "title": "Study protocol for a phase 2 dose-finding trial of X"},
    ],
)
def test_notices_and_protocols_are_never_trial_milestones(article: dict[str, Any]) -> None:
    detector = MilestoneDetector()
    full = {"pmid": "9", "year": 2021, **article}
    assert detector.detect_milestone(full) is None
    assert detector.infer_evidence_level(full) is EvidenceLevel.UNKNOWN


def test_protocol_entry_is_labelled_as_a_protocol_in_the_chronicle() -> None:
    article = {
        "pmid": "31",
        "year": 2019,
        "title": "Protocol for a randomised trial of BIS-guided anaesthesia",
        "publication_types": ["Clinical Trial Protocol", "Randomized Controlled Trial"],
        "abstract": "This trial will randomise 1000 adults. The primary outcome will be delirium incidence.",
    }
    assert MilestoneDetector().detect_milestone(article) is None

    generic = TimelineBuilder(MagicMock())._create_generic_event(article)
    snapshot = assemble_chronicle(topic="bis", timeline=ResearchTimeline("bis", [generic]))
    entry = snapshot.entries[0]
    assert entry.title == "Clinical Trial Protocol (randomized)"
    assert entry.provenance["milestone_type"] != MilestoneType.RANDOMIZED_TRIAL.value
    assert "randomized_trial" not in entry.tags


# ── Milestones: no suppression relative to master ───────────────────────────


@pytest.mark.parametrize(
    ("article", "expected"),
    [
        # An indexed observational study may still carry a trial phase...
        (
            {"publication_types": ["Observational Study"], "title": "Long-term outcomes of a phase 3 trial of X"},
            MilestoneType.PHASE_3,
        ),
        # ...or an explicit safety communication / signal (pharmacovigilance).
        (
            {
                "publication_types": ["Observational Study"],
                "title": "Prescribing after the FDA boxed warning for X: a cohort study",
            },
            MilestoneType.SAFETY_ALERT,
        ),
        (
            {"publication_types": ["Observational Study"], "title": "A hepatotoxicity safety signal for X in FAERS"},
            MilestoneType.SAFETY_ALERT,
        ),
        # MeSH design descriptors are not authoritative enough to veto a milestone.
        (
            {
                "publication_types": ["Journal Article"],
                "mesh_terms": ["Prospective Studies", "Humans"],
                "title": "A phase 2 trial of drug X",
            },
            MilestoneType.PHASE_2,
        ),
        (
            {
                "publication_types": ["Journal Article"],
                "mesh_terms": ["Retrospective Studies"],
                "title": "Outcomes after FDA approval of X",
            },
            MilestoneType.FDA_APPROVAL,
        ),
        (
            {
                "publication_types": ["Journal Article"],
                "mesh_terms": ["Cohort Studies"],
                "title": "X outcomes",
                "abstract": "We performed a meta-analysis of individual cohort data.",
            },
            MilestoneType.META_ANALYSIS,
        ),
        # Indexed trials still cannot become safety alerts from wording.
        (
            {
                "publication_types": ["Randomized Controlled Trial"],
                "title": "A safety signal for X: a randomised trial",
            },
            MilestoneType.RANDOMIZED_TRIAL,
        ),
    ],
)
def test_observational_and_mesh_only_designs_keep_master_milestones(
    article: dict[str, Any], expected: MilestoneType
) -> None:
    event = MilestoneDetector().detect_milestone({"pmid": "11", "year": 2018, **article})
    assert event is not None
    assert event.milestone_type is expected


@pytest.mark.asyncio
async def test_mesh_only_design_does_not_drop_a_phase_trial_from_the_topic_timeline() -> None:
    items = [
        {
            "pmid": str(100 + index),
            "title": f"Study {index}",
            "year": str(2000 + index),
            "abstract": "study",
            "publication_types": ["Journal Article"],
        }
        for index in range(30)
    ]
    items.append(
        {
            "pmid": "999",
            "title": "A phase 2 trial of drug X",
            "year": "2015",
            "publication_types": ["Journal Article"],
            "mesh_terms": ["Prospective Studies"],
        }
    )
    searcher = MagicMock()
    searcher.search_page = AsyncMock(
        return_value=SourceSearchPage(
            source="pubmed",
            items=items,
            total=len(items),
            query="x",
            metadata={"physical_query": "x", "query_executed": True},
        )
    )
    searcher.get_citation_metrics = AsyncMock(return_value={})

    timeline = await TimelineBuilder(searcher).build_timeline("x", max_events=4, include_all=True)

    kept = {event.pmid: event for event in timeline.events}
    assert "999" in kept
    assert kept["999"].milestone_type is MilestoneType.PHASE_2


def _event_with(publication_types: list[str], milestone: MilestoneType, title: str) -> Any:
    event = MilestoneDetector().detect_milestone({"pmid": "21", "year": 2019, "title": title, "publication_types": []})
    assert event is not None
    return replace(
        event,
        milestone_type=milestone,
        metadata={**event.metadata, "publication_types": publication_types},
    )


def test_safety_category_on_an_observational_study_is_heuristic_not_a_conflict() -> None:
    observational = _event_with(
        ["Observational Study"], MilestoneType.SAFETY_ALERT, "A hepatotoxicity safety signal for X in FAERS"
    )
    trial = _event_with(["Randomized Controlled Trial"], MilestoneType.SAFETY_ALERT, "FDA safety communication on X")
    snapshot = assemble_chronicle(topic="x", timeline=ResearchTimeline("x", [observational, trial]))
    finding = next(item for item in audit_chronicle(snapshot).findings if item.check == "study_design_labels")

    conflicts = finding.details["category_conflicts_with_indexed_design"]
    assert [row["indexed_design"] for row in conflicts] == ["Randomized Controlled Trial"]
    assert finding.status == "warn"
