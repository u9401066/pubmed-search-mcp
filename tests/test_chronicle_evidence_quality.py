"""Evidence-quality regressions for Research Chronicle content labels.

The 14-PMID PACU processed-EEG set reproduces a v0.10.0 field report: every
highlight fell back to a chronological tie-break because explicit-PMID builds
skipped iCite, two indexed RCTs were labelled "Safety Alert" because their
abstracts mention adverse events, the main branch was the topic descriptor
itself (Electroencephalography), and highlights were template sentences.
The fixture fakes only the PubMed fetch and iCite boundaries.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from Bio.Entrez.Parser import StringElement

from pubmed_search.application.chronicle import (
    ChronicleService,
    ChronicleStore,
    assemble_chronicle,
    audit_chronicle,
    build_chronicle_lineage,
    diff_chronicles,
    narrate_chronicle,
)
from pubmed_search.application.chronicle.highlights import (
    select_extractive_highlight,
    sentence_spans,
    verify_highlight,
)
from pubmed_search.application.timeline import MilestoneDetector, TimelineBuilder
from pubmed_search.domain.entities.chronicle import ChronicleEntryType, ChronicleSnapshot, EvidenceArticle
from pubmed_search.domain.entities.timeline import MilestoneType, ResearchTimeline, TimelineEvent
from pubmed_search.domain.services.study_design import (
    BASIS_MESH,
    BASIS_NOT_INDEXED,
    BASIS_PUBLICATION_TYPE,
    BASIS_TEXT,
    classify_study_design,
)
from pubmed_search.infrastructure.ncbi import LiteratureSearcher
from pubmed_search.presentation.mcp_server.tools.chronicle import _format_summary

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "chronicle_pacu_peeg_14.json").read_text(encoding="utf-8"),
)
TOPIC = FIXTURE["topic"]
PMIDS = [article["pmid"] for article in FIXTURE["articles"]]
INDEXED_RCTS = {"30721296", "40391028", "40987656", "40987659"}


def _article_row(article: dict[str, Any]) -> dict[str, Any]:
    """Mirror the PubMed fetch row, joining sections exactly as the parser does."""
    parts = article["abstract_parts"]
    sections = []
    offset = 0
    for part in parts:
        sections.append(
            {
                "label": part["label"],
                "nlm_category": part["nlm_category"],
                "start": offset,
                "end": offset + len(part["text"]),
            }
        )
        offset += len(part["text"]) + 1
    row = {key: value for key, value in article.items() if key != "abstract_parts"}
    row["abstract"] = " ".join(part["text"] for part in parts)
    row["abstract_sections"] = sections
    return row


class FakeSearcher:
    """PubMed/iCite boundary with call accounting."""

    def __init__(self, *, icite_error: Exception | None = None) -> None:
        self.icite_error = icite_error
        self.fetch_calls: list[list[str]] = []
        self.icite_calls: list[list[str]] = []

    async def fetch_details(self, pmids: list[str]) -> list[dict[str, Any]]:
        self.fetch_calls.append(list(pmids))
        rows = {article["pmid"]: _article_row(article) for article in FIXTURE["articles"]}
        return [rows[pmid] for pmid in pmids if pmid in rows]

    async def get_citation_metrics(self, pmids: list[str]) -> dict[str, dict[str, Any]]:
        self.icite_calls.append(list(pmids))
        if self.icite_error is not None:
            raise self.icite_error
        return {pmid: dict(FIXTURE["icite"][pmid]) for pmid in pmids if pmid in FIXTURE["icite"]}


async def _build(tmp_path: Path, searcher: FakeSearcher | None = None) -> tuple[ChronicleSnapshot, FakeSearcher]:
    fake = searcher or FakeSearcher()
    service = ChronicleService(TimelineBuilder(fake), ChronicleStore(tmp_path / "chronicles"))
    snapshot = await service.build(pmids=list(PMIDS), topic=TOPIC)
    return snapshot, fake


def _entries_by_pmid(snapshot: ChronicleSnapshot) -> dict[str, Any]:
    return {entry.evidence.supporting_articles[0].pmid: entry for entry in snapshot.entries}


def _finding(snapshot: ChronicleSnapshot, check: str) -> Any:
    return next(finding for finding in snapshot.audit.findings if finding.check == check)


# ── End-to-end: the 14-PMID field report ─────────────────────────────────────


@pytest.mark.asyncio
async def test_indexed_rcts_are_labelled_rct_from_pubmed_publication_type(tmp_path: Path) -> None:
    snapshot, _ = await _build(tmp_path)
    entries = _entries_by_pmid(snapshot)

    for pmid in INDEXED_RCTS:
        design = entries[pmid].provenance["study_design"]
        assert (design["key"], design["basis"], design["heuristic"]) == ("rct", BASIS_PUBLICATION_TYPE, False)
        assert entries[pmid].title.startswith("Randomized Controlled Trial")
        assert entries[pmid].evidence.supporting_articles[0].article_type.startswith("Randomized Controlled Trial")
        assert f"study_design:{design['key']}" in entries[pmid].tags
    assert entries["30721296"].title == "Randomized Controlled Trial (pragmatic)"
    assert entries["30721296"].provenance["milestone_type"] == MilestoneType.RANDOMIZED_TRIAL.value

    expected = {
        "15277912": ("meta_analysis", BASIS_PUBLICATION_TYPE),
        "31557307": ("systematic_review", BASIS_PUBLICATION_TYPE),
        "36038444": ("systematic_review_meta_analysis", BASIS_PUBLICATION_TYPE),
        "23965209": ("observational", BASIS_PUBLICATION_TYPE),
        "30915984": ("observational", BASIS_PUBLICATION_TYPE),
        "37364282": ("observational", BASIS_PUBLICATION_TYPE),
        "36706658": ("unspecified", BASIS_NOT_INDEXED),
        "37616326": ("unspecified", BASIS_NOT_INDEXED),
        # PubMed has not yet indexed a design for these two; titles state one.
        "39246973": ("rct", BASIS_TEXT),
        "42962495": ("systematic_review_meta_analysis", BASIS_TEXT),
    }
    for pmid, (key, basis) in expected.items():
        design = entries[pmid].provenance["study_design"]
        assert (design["key"], design["basis"]) == (key, basis), pmid
    assert entries["23965209"].title == "Observational Study (prospective)"
    assert entries["39246973"].title == "Randomized Controlled Trial [heuristic]"
    assert entries["42962495"].provenance["study_design"]["indexed_publication_types"] == ["Review"]

    finding = _finding(snapshot, "study_design_labels")
    assert finding.status == "warn"
    assert {row["evidence_ids"][0] for row in finding.details["heuristic_design_labels"]} == {
        "pmid:39246973",
        "pmid:42962495",
    }
    assert finding.details["category_conflicts_with_indexed_design"] == []


@pytest.mark.asyncio
async def test_no_safety_alert_is_assigned_without_safety_evidence(tmp_path: Path) -> None:
    snapshot, _ = await _build(tmp_path)

    # ENGAGES, the 2025 BIS RCT and the 2024 BIS trial all mention adverse
    # events in their abstracts; none is a safety communication.
    assert all(entry.entry_type is not ChronicleEntryType.SAFETY for entry in snapshot.entries)
    for entry in snapshot.entries:
        assert "Safety Alert" not in entry.title
        assert entry.provenance["milestone_type"] != MilestoneType.SAFETY_ALERT.value
        assert MilestoneType.SAFETY_ALERT.value not in entry.tags
    entries = _entries_by_pmid(snapshot)
    assert entries["40391028"].provenance["milestone_type"] == MilestoneType.RANDOMIZED_TRIAL.value
    assert entries["39246973"].provenance["milestone_detection"] == {}


@pytest.mark.asyncio
async def test_topic_restating_descriptor_does_not_form_the_dominant_branch(tmp_path: Path) -> None:
    snapshot, _ = await _build(tmp_path)
    diagnostics = snapshot.metadata["lineage_diagnostics"]
    excluded = {row["key"]: row for row in diagnostics["excluded_topic_signals"]}

    assert diagnostics["basis"] == "topic_signals"
    assert excluded["electroencephalography"]["reason"] == "dominant_cross_cutting_descriptor"
    assert excluded["electroencephalography"]["matched_event_count"] == 9
    assert excluded["eeg"]["reason"] == "topic_query_terms"
    assert excluded["pacu"]["reason"] == "topic_query_terms"
    branch_names = {branch.name.casefold() for branch in snapshot.branches}
    assert "electroencephalography" not in branch_names
    assert "eeg" not in branch_names

    semantic = [branch for branch in snapshot.branches if branch.branch_id != "topic-cross-cutting"]
    assert len(semantic) >= 3
    assert max(len(branch.entry_ids) for branch in snapshot.branches) < len(snapshot.entries) / 2
    assert {"Delirium", "Monitoring, Intraoperative", "bispectral index"} <= {branch.name for branch in semantic}
    # Primary assignment still keeps multi-signal matches as explicit links.
    assert "cross_signal_links" in diagnostics
    assert diagnostics["signal_selection"] == "greedy_marginal_coverage"


@pytest.mark.asyncio
async def test_explicit_pmids_apply_icite_once_with_coverage_envelope(tmp_path: Path) -> None:
    snapshot, searcher = await _build(tmp_path)
    retrieval = snapshot.metadata["timeline_metadata"]["retrieval"]
    coverage = retrieval["citation_metrics"]

    assert searcher.icite_calls == [sorted(PMIDS)]
    assert retrieval["mode"] == "explicit_pmids"
    assert retrieval["evidence_selection"] == "explicit_pmid_set_without_ranking"
    assert coverage["schema_version"] == "citation-metrics-coverage/v1"
    assert (coverage["status"], coverage["requested"], coverage["applied"]) == ("partial", 14, 13)
    assert coverage["citation_counts_applied"] == 13

    entries = _entries_by_pmid(snapshot)
    assert entries["30721296"].evidence.supporting_articles[0].citation_count == 385
    assert all(entry.provenance["landmark_importance_score"] is not None for entry in snapshot.entries)

    finding = _finding(snapshot, "citation_metrics_coverage")
    assert finding.status == "warn"
    assert finding.details["retrieval_mode"] == "explicit_pmids"
    assert "13 of 14" in finding.message

    summary = _format_summary(snapshot)
    assert "Citation metrics \\(NIH iCite\\): partial, 13 of 14" in summary
    assert "chronological tie-break" not in summary
    assert "landmark importance" in summary
    assert "iCite citations" in summary


@pytest.mark.asyncio
async def test_icite_outage_is_disclosed_and_invents_no_landmark_scores(tmp_path: Path) -> None:
    snapshot, _ = await _build(tmp_path, FakeSearcher(icite_error=TimeoutError("icite down")))
    coverage = snapshot.metadata["timeline_metadata"]["retrieval"]["citation_metrics"]

    assert coverage["status"] == "error"
    assert coverage["error"]["kind"] in {"timeout", "retryable", "unexpected"}
    assert all(entry.provenance["landmark_importance_score"] is None for entry in snapshot.entries)
    finding = _finding(snapshot, "citation_metrics_coverage")
    assert finding.status == "warn"
    assert "landmark scores were not computed" in finding.message
    assert "chronological tie-break (iCite metrics unavailable)" in _format_summary(snapshot)
    # Labels do not depend on citation metrics.
    assert _entries_by_pmid(snapshot)["30721296"].title == "Randomized Controlled Trial (pragmatic)"


@pytest.mark.asyncio
async def test_highlights_quote_verifiable_abstract_spans(tmp_path: Path) -> None:
    snapshot, _ = await _build(tmp_path)
    store = ChronicleStore(tmp_path / "chronicles")
    persisted = store.load(snapshot.chronicle_id)
    assert persisted is not None

    for current in (snapshot, ChronicleSnapshot.from_dict(json.loads(json.dumps(snapshot.to_dict()))), persisted):
        for entry in current.entries:
            highlight = entry.provenance["extractive_highlight"]
            article = entry.evidence.supporting_articles[0]
            assert highlight["kind"] == "extractive_abstract_sentence"
            assert highlight["verbatim"] is True
            assert highlight["evidence_id"] == article.evidence_id
            assert article.abstract is not None
            assert article.abstract[highlight["char_start"] : highlight["char_end"]] == highlight["text"]
            assert article.claim_excerpt == highlight["text"]
            assert verify_highlight(highlight, article.abstract) == []
            assert highlight["selection_rule"] == "first_sentence_of_conclusions_section"
            assert "registration" not in highlight["text"].casefold()
            assert f'"{highlight["text"]}"' in entry.summary_claim
            assert f"chars {highlight['char_start']}-{highlight['char_end']}" in entry.summary_claim

    engages = _entries_by_pmid(snapshot)["30721296"].provenance["extractive_highlight"]
    assert engages["section_label"] == "CONCLUSIONS AND RELEVANCE"
    assert engages["text"].startswith("Among older adults undergoing major surgery")
    cochrane = _entries_by_pmid(snapshot)["31557307"].provenance["extractive_highlight"]
    assert cochrane["section_label"] == "AUTHORS' CONCLUSIONS"

    finding = _finding(snapshot, "extractive_highlights")
    assert finding.status == "pass"
    assert finding.details["verified_highlights"] == 14


@pytest.mark.asyncio
async def test_tampered_highlight_span_fails_the_audit(tmp_path: Path) -> None:
    snapshot, _ = await _build(tmp_path)
    entry = snapshot.entries[0]
    entry.provenance["extractive_highlight"] = {
        **entry.provenance["extractive_highlight"],
        "char_start": entry.provenance["extractive_highlight"]["char_start"] + 1,
    }

    finding = next(item for item in audit_chronicle(snapshot).findings if item.check == "extractive_highlights")
    assert finding.status == "fail"
    assert finding.details["integrity_problems"][0]["entry_id"] == entry.entry_id


@pytest.mark.asyncio
async def test_narrative_and_summary_use_extractive_highlights(tmp_path: Path) -> None:
    snapshot, _ = await _build(tmp_path)
    narrative = narrate_chronicle(snapshot, mode="full")
    summary = _format_summary(snapshot)

    assert "verbatim from each paper's PubMed abstract" in narrative
    assert "did not decrease the incidence of postoperative delirium" in narrative
    assert "a background publication concerning" not in narrative
    assert "quoted from the abstract" in summary
    assert _finding(snapshot, "narrative_citations").status == "pass"


@pytest.mark.asyncio
async def test_abstracts_are_reduced_to_digests_in_revision_diffs(tmp_path: Path) -> None:
    before, _ = await _build(tmp_path)
    after = ChronicleSnapshot.from_dict(json.loads(json.dumps(before.to_dict())))
    after.revision = before.revision + 1
    article = after.entries[0].evidence.supporting_articles[0]
    after.entries[0].evidence.supporting_articles[0] = EvidenceArticle.from_dict(
        {**article.to_dict(), "abstract": f"{article.abstract} Updated."}
    )

    delta = diff_chronicles(before, after)
    change = delta["evidence"]["updated"][0]["changes"]["abstract"]
    assert set(change["from"]) == {"sha256", "chars"}
    assert change["to"]["chars"] == change["from"]["chars"] + len(" Updated.")


# ── Unit regressions ─────────────────────────────────────────────────────────


def test_study_design_prefers_publication_type_and_ignores_as_topic_descriptors() -> None:
    meta = classify_study_design(
        ["Journal Article", "Meta-Analysis"],
        ["Randomized Controlled Trials as Topic", "Humans"],
        title="A randomized trial overview",
    )
    assert (meta.key, meta.basis) == ("meta_analysis", BASIS_PUBLICATION_TYPE)

    mesh_only = classify_study_design(["Journal Article"], ["Retrospective Studies", "Cohort Studies/methods"])
    assert (mesh_only.key, mesh_only.basis, mesh_only.qualifiers) == (
        "observational",
        BASIS_MESH,
        ("cohort", "retrospective"),
    )

    topic_only = classify_study_design(["Journal Article"], ["Randomized Controlled Trials as Topic"])
    assert (topic_only.key, topic_only.basis) == ("unspecified", BASIS_NOT_INDEXED)

    retracted = classify_study_design(["Randomized Controlled Trial", "Retracted Publication"])
    assert retracted.flags == ("retracted",)
    assert retracted.display_label == "Randomized Controlled Trial [RETRACTED]"


def test_study_design_text_heuristics_are_disclosed_and_limited() -> None:
    abstract_rct = classify_study_design(
        ["Journal Article"],
        [],
        title="Monitoring and recovery",
        abstract="Methods: Ninety patients were randomized into three groups.",
    )
    assert (abstract_rct.key, abstract_rct.basis, abstract_rct.heuristic) == ("rct", BASIS_TEXT, True)
    assert abstract_rct.matched == ("abstract: were randomized into",)

    # A narrative review citing meta-analyses is not relabelled from its abstract.
    review = classify_study_design(
        ["Journal Article", "Review"],
        [],
        title="Depth of anaesthesia monitoring",
        abstract="Several meta-analyses of randomized trials were summarized.",
    )
    assert (review.key, review.basis) == ("review", BASIS_PUBLICATION_TYPE)

    # An indexed design is never overridden by text patterns.
    cohort = classify_study_design(["Observational Study"], [], title="A randomized controlled trial reanalysis")
    assert (cohort.key, cohort.basis) == ("observational", BASIS_PUBLICATION_TYPE)


@pytest.mark.parametrize(
    ("article", "expected"),
    [
        (
            {
                "publication_types": ["Randomized Controlled Trial"],
                "title": "BIS-guided anaesthesia",
                "abstract": "Serious adverse events and warning signs were recorded.",
            },
            MilestoneType.RANDOMIZED_TRIAL,
        ),
        (
            {
                "publication_types": ["Journal Article"],
                "title": "BIS-guided anaesthesia",
                "abstract": "Adverse events.",
            },
            None,
        ),
        (
            {"publication_types": ["Randomized Controlled Trial"], "title": "Safety warning after a challenge test"},
            MilestoneType.RANDOMIZED_TRIAL,
        ),
        (
            {"publication_types": ["Journal Article"], "title": "FDA drug safety communication on remimazolam"},
            MilestoneType.SAFETY_ALERT,
        ),
        (
            {"publication_types": ["News"], "title": "FDA approves remimazolam for procedural sedation"},
            MilestoneType.FDA_APPROVAL,
        ),
        (
            {"publication_types": ["Randomized Controlled Trial"], "title": "A phase III trial of remimazolam"},
            MilestoneType.PHASE_3,
        ),
        (
            {"publication_types": ["Observational Study"], "abstract": "This phase III programme informed the cohort."},
            None,
        ),
    ],
)
def test_indexed_publication_types_outrank_text_milestone_heuristics(
    article: dict[str, Any], expected: MilestoneType | None
) -> None:
    event = MilestoneDetector().detect_milestone({"pmid": "1", "year": 2024, "title": "", **article})
    assert (event.milestone_type if event else None) is expected


def test_highlight_selection_prefers_conclusions_and_skips_boilerplate() -> None:
    parts = [
        ("BACKGROUND", "BACKGROUND", "Context sentence for the study."),
        (
            "RESULTS",
            "RESULTS",
            "Delirium fell from 20% vs. 30% in Smith et al. cohorts. Recovery to discharge was faster with guidance.",
        ),
        ("CONCLUSIONS", None, "BIS guidance shortened recovery in older adults. More trials are needed."),
        ("TRIAL REGISTRATION", "BACKGROUND", "ClinicalTrials.gov NCT00000000."),
    ]
    abstract = " ".join(text for _, _, text in parts)
    sections, offset = [], 0
    for label, category, text in parts:
        sections.append({"label": label, "nlm_category": category, "start": offset, "end": offset + len(text)})
        offset += len(text) + 1

    highlight = select_extractive_highlight(abstract, sections)
    assert highlight is not None
    assert highlight.text == "BIS guidance shortened recovery in older adults."
    assert abstract[highlight.char_start : highlight.char_end] == highlight.text
    assert (highlight.selection_rule, highlight.section_label) == (
        "first_sentence_of_conclusions_section",
        "CONCLUSIONS",
    )

    results_only = select_extractive_highlight(abstract, sections[:2])
    assert results_only is not None
    assert (results_only.selection_rule, results_only.text) == (
        "last_sentence_of_results_section",
        "Recovery to discharge was faster with guidance.",
    )
    spans = sentence_spans(parts[1][2])
    assert [parts[1][2][start:end] for start, end in spans] == [
        "Delirium fell from 20% vs. 30% in Smith et al. cohorts.",
        "Recovery to discharge was faster with guidance.",
    ]

    unstructured = "We studied 40 patients. In conclusion, BIS shortened recovery. Copyright 2024 the authors."
    cue = select_extractive_highlight(unstructured)
    assert cue is not None
    assert (cue.selection_rule, cue.text) == ("conclusion_cue_sentence", "In conclusion, BIS shortened recovery.")
    assert select_extractive_highlight("   ") is None


def test_entries_without_abstracts_keep_conservative_template_claims() -> None:
    event = TimelineEvent(
        pmid="77",
        year=2020,
        milestone_type=MilestoneType.RANDOMIZED_TRIAL,
        title="A trial",
        milestone_label="RCT",
        metadata={"publication_types": ["Randomized Controlled Trial"], "mesh_terms": [], "keywords": []},
    )
    snapshot = assemble_chronicle(topic="therapy", timeline=ResearchTimeline("therapy", [event]))
    entry = snapshot.entries[0]

    assert entry.title == "Randomized Controlled Trial"
    assert entry.provenance["extractive_highlight"] is None
    assert "categorized as Randomized Controlled Trial" in entry.summary_claim
    finding = next(item for item in audit_chronicle(snapshot).findings if item.check == "extractive_highlights")
    assert (finding.status, finding.details["entries_without_stored_abstract"]) == ("pass", 1)


@pytest.mark.parametrize(
    ("article", "title", "label_basis"),
    [
        (
            {"publication_types": ["Randomized Controlled Trial"], "title": "A phase III trial of remimazolam"},
            "Randomized Controlled Trial; Phase 3 Trial [heuristic]",
            "study_design:pubmed_publication_type+milestone_detection:title_pattern",
        ),
        (
            {"publication_types": ["News"], "title": "FDA approves remimazolam for procedural sedation"},
            "News; FDA Approval [heuristic]",
            "study_design:pubmed_publication_type+milestone_detection:title_pattern",
        ),
        (
            {"publication_types": ["Journal Article"], "title": "FDA approves remimazolam for procedural sedation"},
            "FDA Approval [heuristic]",
            "milestone_detection:title_pattern",
        ),
    ],
)
def test_text_milestone_refinements_stay_marked_heuristic(
    article: dict[str, Any], title: str, label_basis: str
) -> None:
    event = MilestoneDetector().detect_milestone({"pmid": "5", "year": 2020, **article})
    assert event is not None
    snapshot = assemble_chronicle(topic="remimazolam", timeline=ResearchTimeline("remimazolam", [event]))
    entry = snapshot.entries[0]

    assert (entry.title, entry.provenance["entry_label_basis"]) == (title, label_basis)
    finding = next(item for item in audit_chronicle(snapshot).findings if item.check == "study_design_labels")
    assert finding.status == "warn"
    assert finding.details["heuristic_category_labels"][0]["label"] == title


def _signal_event(pmid: str, year: int, *, mesh: list[str] | None = None, keywords: list[str] | None = None) -> Any:
    return TimelineEvent(
        pmid=pmid,
        year=year,
        milestone_type=MilestoneType.OTHER,
        title=f"Paper {pmid}",
        milestone_label="Study",
        metadata={"mesh_terms": mesh or [], "keywords": keywords or []},
    )


def test_topic_acronym_expansions_and_query_terms_cannot_form_branches() -> None:
    events = [
        _signal_event("1", 2001, keywords=["Post-anesthesia care unit", "Delirium screening"]),
        _signal_event("2", 2002, keywords=["Post-anesthesia care unit", "Delirium screening"]),
        _signal_event("3", 2003, keywords=["monitoring", "Recovery time"]),
        _signal_event("4", 2004, keywords=["monitoring", "Recovery time"]),
    ]
    tree = build_chronicle_lineage(ResearchTimeline("PACU monitoring", events))
    diagnostics = tree.metadata["lineage_diagnostics"]

    reasons = {row["label"]: row["reason"] for row in diagnostics["excluded_topic_signals"]}
    assert reasons == {"Post-anesthesia care unit": "topic_acronym_expansion", "monitoring": "topic_query_terms"}
    assert {branch.label for branch in tree.branches} == {"Delirium screening", "Recovery time"}


def test_marginal_coverage_selection_skips_signals_that_add_one_paper() -> None:
    events = [_signal_event(str(index), 2000 + index, mesh=["Alpha Pathway", "Beta Pathway"]) for index in range(5)]
    events.append(_signal_event("5", 2005, mesh=["Alpha Pathway"]))
    events.append(_signal_event("6", 2006, mesh=["Beta Pathway"]))
    tree = build_chronicle_lineage(ResearchTimeline("therapy", events))
    diagnostics = tree.metadata["lineage_diagnostics"]

    assert diagnostics["basis"] == "research_stage_fallback"
    assert diagnostics["signal_extraction"]["signals_not_selected_low_marginal_coverage"] == 1
    assert diagnostics["signal_extraction"]["signals_pruned_after_assignment"] == 0


def test_pubmed_parser_reports_structured_abstract_section_offsets() -> None:
    parts = [
        StringElement("Background text.", "AbstractText", {"Label": "BACKGROUND", "NlmCategory": "BACKGROUND"}, None),
        StringElement("Main finding. Second sentence.", "AbstractText", {"Label": "CONCLUSIONS AND RELEVANCE"}, None),
    ]
    article = {
        "MedlineCitation": {
            "PMID": "123",
            "Article": {"ArticleTitle": "Title", "Abstract": {"AbstractText": parts}},
        },
        "PubmedData": {},
    }
    row = LiteratureSearcher._parse_pubmed_article(object.__new__(LiteratureSearcher), article)

    assert row["abstract"] == "Background text. Main finding. Second sentence."
    assert [(item["label"], item["nlm_category"]) for item in row["abstract_sections"]] == [
        ("BACKGROUND", "BACKGROUND"),
        ("CONCLUSIONS AND RELEVANCE", None),
    ]
    assert [row["abstract"][item["start"] : item["end"]] for item in row["abstract_sections"]] == [
        str(part) for part in parts
    ]
    unstructured = {**article["MedlineCitation"]["Article"], "Abstract": {"AbstractText": ["Plain abstract."]}}
    assert LiteratureSearcher._extract_abstract_sections(object.__new__(LiteratureSearcher), unstructured) == []
