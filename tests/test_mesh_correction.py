"""Automatic, disclosed MeSH correction through a deterministic NCBI boundary.

``tests/fixtures/mesh_entrez.FakeEntrez`` stands in for Bio.Entrez only; the
production gateway, exact MeSH lookup, MEDLINE parsing, transport kernel and
services run for real. Fixture provenance (2026-11-25), see the fixture module:

- Diagnostics shapes are live: ``"Post-Anesthesia Care Units"[Mesh]``,
  ``"Emergence Deliriums"[Mesh]``, ``"Recovery Rooms"[mesh:noexp]`` and
  ``"remimazolam"[Mesh]`` each came back as ``QuotedPhraseNotFound``; bare
  ``PACU[mh]`` as ``ErrorList.PhraseNotFound=["PACU"]`` and bare
  ``post-anesthesia care units[mh]`` as ``PhraseNotFound=["units"]``.
- The PACU heading distribution is the maintainer's analysis of 150 recent
  records with PACU in title/abstract (93 with MeSH): Humans 100%, Female
  81%, Male 72%, Middle Aged 63%, Adult 52%, Aged 44%, Postoperative Pain
  34%, Anesthesia Recovery Period 26%, Retrospective Studies 22%,
  Postoperative Complications 22%, Prospective Studies 22%, Anesthesia,
  General 20%. Smaller rows (Recovery Room, Length of Stay, Pain Measurement,
  Treatment Outcome) are synthetic fill.
- Evidence total 3717 and background counts for Anesthesia Recovery Period
  (6140), Postoperative Pain (59724), Postoperative Complications (690806),
  Length of Stay (120182) and Recovery Room (1394) are live counts; the
  Anesthesia, General and Pain Measurement backgrounds are synthetic.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.search.mesh_correction import (
    MeshCorrectionPolicy,
    MeshCorrectionService,
    cooccurrence_candidate_entry,
)
from pubmed_search.application.search.query_materials import attach_cooccurrence_candidates
from pubmed_search.domain.services.mesh_correction import (
    DescriptorShare,
    apply_replacements,
    descriptor_shares,
    find_mesh_terms,
    flag_unresolved_terms,
    rank_descriptors,
    score_descriptor,
    text_word_variants,
)
from pubmed_search.domain.value_objects.query_diagnostics import PubMedQueryDiagnostics
from tests.fixtures.mesh_entrez import (
    BACKGROUND_COUNTS,
    EVIDENCE_TOTAL,
    JOINT_COUNTS,
    PACU,
    PACU_DISTRIBUTION,
    PACU_QUERY,
    FakeEntrez,
    make_service,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def fake() -> Iterator[FakeEntrez]:
    entrez = FakeEntrez()
    with entrez.installed():
        yield entrez


# ---------------------------------------------------------------------------
# Pure domain rules
# ---------------------------------------------------------------------------


def test_mesh_clauses_are_found_in_every_tag_form_and_only_there():
    query = (
        '("Delirium/prevention and control"[Majr] OR delirium[tiab]) AND PACU[mh] AND '
        'post-anesthesia care units[mh] AND "Recovery Rooms"[mesh:noexp] AND therapy[sh] AND '
        '"remimazolam"[nm] AND "heart [mh] attack"[tiab] AND "Adult"[MeSH Major Topic]'
    )

    terms = find_mesh_terms(query)

    assert [(term.clause, term.descriptor, term.qualifier) for term in terms] == [
        ('"Delirium/prevention and control"[Majr]', "Delirium", "prevention and control"),
        ("PACU[mh]", "PACU", None),
        ("post-anesthesia care units[mh]", "post-anesthesia care units", None),
        ('"Recovery Rooms"[mesh:noexp]', "Recovery Rooms", None),
        ('"Adult"[MeSH Major Topic]', "Adult", None),
    ]
    assert [(term.major, term.noexp, term.quoted) for term in terms] == [
        (True, False, True),
        (False, False, False),
        (False, False, False),
        (False, True, True),
        (True, False, True),
    ]
    assert all(query[term.start : term.end] == term.clause for term in terms)


def test_only_clauses_named_by_ncbi_are_flagged():
    terms = find_mesh_terms(f'{PACU} AND "Delirium"[Mesh] AND PACU[mh] AND post-anesthesia care units[mh]')
    diagnostics = PubMedQueryDiagnostics(
        quoted_phrases_not_found=('"Post-Anesthesia Care Units"[Mesh]',),
        phrases_not_found=("PACU", "units"),
    )

    flagged = flag_unresolved_terms(terms, diagnostics)

    assert [(item.term.clause, item.reason) for item in flagged] == [
        (PACU, 'NCBI WarningList.QuotedPhraseNotFound: "Post-Anesthesia Care Units"[Mesh]'),
        ("PACU[mh]", "NCBI ErrorList.PhraseNotFound: PACU"),
        ("post-anesthesia care units[mh]", "NCBI ErrorList.PhraseNotFound: units"),
    ]


def test_shares_exclude_check_tags_and_study_design_and_count_indexed_records_only():
    table = descriptor_shares(
        {
            "1": ["Humans", "*Recovery Room/statistics & numerical data", "Retrospective Studies"],
            "2": ["Humans", "Recovery Room", "Recovery Room/methods", "Randomized Controlled Trials as Topic"],
            "3": [],
        }
    )

    assert table.records_with_mesh == 2
    assert table.shares == (DescriptorShare("Recovery Room", 2, 1.0),)
    assert table.excluded == {"check_tag": 1, "study_design": 2}


def test_exact_counts_prefer_the_specific_heading_over_the_frequent_one():
    shares = {name: DescriptorShare(name, records, records / 93) for name, records in PACU_DISTRIBUTION}
    scored = [
        score_descriptor(
            shares[name], evidence_total=EVIDENCE_TOTAL, background_count=count, joint_count=JOINT_COUNTS[name]
        )
        for name, count in BACKGROUND_COUNTS.items()
    ]

    ranked = rank_descriptors(scored)

    # Raw share alone would pick Postoperative Pain (34% vs 26%).
    assert max(scored, key=lambda item: item.share).descriptor == "Postoperative Pain"
    assert [item.descriptor for item in ranked[:2]] == ["Anesthesia Recovery Period", "Recovery Room"]
    best = ranked[0]
    assert (best.recall, best.precision) == (pytest.approx(966 / EVIDENCE_TOTAL), pytest.approx(966 / 6140))


def test_a_rare_new_heading_cannot_win_on_a_sample_share_alone():
    # Live 2026-11-25: "Pediatric Anesthesia" (531 records) appeared in 16% of a recent sample; a
    # sample-based precision estimate (0.16 x 3717 / 531) capped at 1 and ranked it first.
    new_heading = score_descriptor(
        DescriptorShare("Pediatric Anesthesia", 24, 0.16), evidence_total=3717, background_count=531, joint_count=60
    )
    recovery_period = score_descriptor(
        DescriptorShare("Anesthesia Recovery Period", 39, 0.26),
        evidence_total=3717,
        background_count=6140,
        joint_count=966,
    )
    assert rank_descriptors([new_heading, recovery_period])[0].descriptor == "Anesthesia Recovery Period"


def test_text_word_variants_fold_hyphen_space_duplicates_and_use_canonical_casing():
    assert text_word_variants("Post-Anesthesia Care Units") == (
        "Post-Anesthesia Care Units",
        "Post-Anesthesia Care Unit",
        "Postanesthesia Care Units",
        "Postanesthesia Care Unit",
    )
    assert text_word_variants("PACU") == ("PACU",)
    assert all("PostAnesthesia" not in variant for variant in text_word_variants("Post-Anesthesia care unit"))


def test_overlapping_replacements_are_rejected():
    with pytest.raises(ValueError, match="overlap"):
        apply_replacements("abcdef", [(0, 3, "x"), (2, 4, "y")])


# ---------------------------------------------------------------------------
# MeshCorrectionService through the production gateway
# ---------------------------------------------------------------------------


async def test_pacu_heading_is_rescued_by_cooccurrence_with_full_disclosure(fake: FakeEntrez):
    result = await make_service().correct_query(PACU_QUERY)

    assert result.status == "corrected" and result.detection == "ncbi_diagnostics"
    (correction,) = result.corrections
    assert correction.tier == "co_occurrence"
    assert correction.replacement_mesh == "Anesthesia Recovery Period"
    assert correction.reason == 'NCBI WarningList.QuotedPhraseNotFound: "Post-Anesthesia Care Units"[Mesh]'
    assert correction.confidence == "low"  # a related heading is never "high"
    # The concept is kept as the agent's own words; the heading is OR-ed in.
    # Hyphen/space duplicates are folded; the variant PubMed did not find is pruned.
    assert result.corrected_query == (
        '("Post-Anesthesia Care Units"[tiab] OR "Post-Anesthesia Care Unit"[tiab] OR '
        '"Postanesthesia Care Units"[tiab] OR "Anesthesia Recovery Period"[Mesh]) AND delirium[tiab]'
    )
    evidence = correction.evidence
    assert evidence["query"].endswith("AND medline[sb]") and '"Postanesthesia Care Unit"[tiab]' in evidence["query"]
    assert (evidence["evidence_total"], evidence["sample_size"], evidence["records_with_mesh"]) == (3717, 150, 93)
    assert evidence["retrieved_at"] == "2026-11-25T08:30:00+00:00" and evidence["sort"] == "relevance"
    candidates = evidence["candidates"]
    assert [item["descriptor"] for item in candidates[:2]] == ["Anesthesia Recovery Period", "Recovery Room"]
    assert candidates[0]["share"] == pytest.approx(0.258, abs=1e-3) and candidates[0]["background_count"] == 6140
    named = {item["descriptor"] for item in candidates}
    assert not named & {"Humans", "Female", "Male", "Middle Aged", "Adult", "Aged", "Retrospective Studies"}
    assert evidence["excluded_descriptors"] == {"check_tag": 6, "study_design": 3}
    # AND-query rescue: 0 hits before, >0 after, both from count-only ESearch.
    assert (result.before_count, result.after_count) == (0, 412)
    assert result.improves_recall and result.changed
    assert result.diagnostics_after is not None and not result.diagnostics_after.has_issues
    assert result.budget["reserved"] <= result.budget["max_ncbi_requests"] and not result.budget["truncated"]
    assert fake.count("efetch") == 1
    json.dumps(result.to_dict())  # the disclosure is JSON-safe


async def test_plural_hyphen_and_noexp_variants_are_fixed_by_exact_lookup(fake: FakeEntrez):
    query = '"Emergence Deliriums"[Mesh] AND "Post-Operative Deliriums"[Majr] AND "Recovery Rooms"[mesh:noexp]'

    result = await make_service().correct_query(query)

    assert result.corrected_query == (
        '"Emergence Delirium"[Mesh] AND "Emergence Delirium"[Majr] AND "Recovery Room"[mesh:noexp]'
    )
    assert {item.tier for item in result.corrections} == {"exact"}
    assert {item.confidence for item in result.corrections} == {"high"}
    by_original = {item.original: item.evidence for item in result.corrections}
    assert by_original['"Post-Operative Deliriums"[Majr]']["matched_term"] == "Postoperative Delirium"
    assert by_original['"Recovery Rooms"[mesh:noexp]']["matched_on"] == "entry_term"
    assert fake.count("efetch") == 0  # exact matches need no co-occurrence evidence
    assert result.after_count == 412


async def test_supplementary_concept_moves_to_its_own_field(fake: FakeEntrez):
    result = await make_service().correct_query('"remimazolam"[Mesh] AND sedation[tiab]')

    assert result.corrected_query == '"remimazolam"[Supplementary Concept] AND sedation[tiab]'
    assert result.corrections[0].evidence["record_type"] == "supplementary_concept"


async def test_valid_headings_are_never_touched(fake: FakeEntrez):
    query = '"Delirium"[Mesh] AND "Recovery Room"[Mesh]'

    result = await make_service().correct_query(query)

    assert (result.status, result.corrected_query, result.corrections) == ("valid", query, ())
    assert result.valid_terms == ('"Delirium"[Mesh]', '"Recovery Room"[Mesh]')
    assert fake.calls == [("esearch", "pubmed", query)]  # one probe, no lookups


async def test_only_the_unresolved_clause_changes_in_a_mixed_query(fake: FakeEntrez):
    result = await make_service().correct_query('"Delirium"[Mesh] AND "Emergence Deliriums"[Mesh]')

    assert result.corrected_query == '"Delirium"[Mesh] AND "Emergence Delirium"[Mesh]'
    assert result.valid_terms == ('"Delirium"[Mesh]',)


async def test_query_without_mesh_tags_costs_nothing(fake: FakeEntrez):
    result = await make_service().correct_query("delirium[tiab] AND recovery")

    assert result.status == "not_applicable" and fake.calls == []


async def test_caller_supplied_diagnostics_skip_the_first_probe(fake: FakeEntrez):
    diagnostics = PubMedQueryDiagnostics(quoted_phrases_not_found=('"Emergence Deliriums"[Mesh]',))

    result = await make_service().correct_query(
        '"Emergence Deliriums"[Mesh]', diagnostics=diagnostics, observed_count=0
    )

    assert result.corrected_query == '"Emergence Delirium"[Mesh]'
    assert [call for call in fake.calls if call[:2] == ("esearch", "pubmed")] == [
        ("esearch", "pubmed", '"Emergence Delirium"[Mesh]')
    ]


async def test_unquoted_heading_flagged_by_error_list_is_corrected(fake: FakeEntrez):
    result = await make_service().correct_query("post-anesthesia care units[mh] AND delirium[tiab]")

    (correction,) = result.corrections
    assert correction.reason == "NCBI ErrorList.PhraseNotFound: units"
    assert correction.replacement_mesh == "Anesthesia Recovery Period"
    assert result.corrected_query.endswith('"Anesthesia Recovery Period"[mh]) AND delirium[tiab]')


async def test_budget_truncation_is_disclosed_and_respected(fake: FakeEntrez):
    policy = MeshCorrectionPolicy(max_ncbi_requests=8)

    result = await make_service(policy).correct_query(PACU_QUERY)

    issued = len(fake.calls)
    assert issued <= 8
    assert result.budget["truncated"] is True
    assert any(item.startswith("background and joint counts") for item in result.budget["skipped"])
    evidence = result.corrections[0].evidence
    assert evidence["unscored_candidates"] > 0
    assert result.after_count == 412  # the after-count is always kept in reserve


async def test_headings_beyond_max_terms_fall_back_to_text_words(fake: FakeEntrez):
    policy = MeshCorrectionPolicy(max_terms=1)

    result = await make_service(policy).correct_query(f'"Emergence Deliriums"[Mesh] AND {PACU}')

    tiers = {item.original: item.tier for item in result.corrections}
    assert tiers == {'"Emergence Deliriums"[Mesh]': "exact", PACU: "text_words"}
    assert any("max_terms=1" in item for item in result.budget["skipped"])
    assert fake.count("efetch") == 0


async def test_without_diagnostics_exact_lookup_detects_unknown_headings(fake: FakeEntrez):
    fake.fail_probe = True

    with patch("pubmed_search.infrastructure.ncbi.mesh_evidence.MAX_ATTEMPTS", 1):
        result = await make_service().correct_query('"Delirium"[Mesh] AND "Postanesthesia Recovery Wards"[Mesh]')

    assert result.detection == "exact_lookup"
    assert result.valid_terms == ('"Delirium"[Mesh]',)
    (correction,) = result.corrections
    assert correction.original == '"Postanesthesia Recovery Wards"[Mesh]'
    assert result.before_count is None and result.after_count is None
    assert any("diagnostics probe" in warning for warning in result.warnings)


async def test_total_outage_leaves_the_query_unchanged():
    gateway = MagicMock()
    gateway.probe = AsyncMock(side_effect=RuntimeError("down"))
    gateway.lookup_exact = AsyncMock(side_effect=RuntimeError("down"))

    result = await MeshCorrectionService(gateway).correct_query(PACU_QUERY)

    assert (result.status, result.corrected_query) == ("unavailable", PACU_QUERY)
    assert result.warnings


async def test_malformed_medline_degrades_to_text_words_with_a_warning(fake: FakeEntrez):
    fake.medline_extra_pmid = "999"

    with patch("pubmed_search.infrastructure.ncbi.mesh_evidence.MAX_ATTEMPTS", 1):
        result = await make_service().correct_query(PACU_QUERY)

    (correction,) = result.corrections
    assert correction.tier == "text_words" and correction.replacement_mesh is None
    assert "[Mesh]" not in result.corrected_query and '"Post-Anesthesia Care Units"[tiab]' in result.corrected_query
    assert any("MEDLINE" in note for note in correction.notes)


async def test_evidence_is_cached_across_calls(fake: FakeEntrez):
    service = make_service()
    await service.correct_query(PACU_QUERY)
    first = len(fake.calls)

    await service.correct_query(PACU_QUERY)

    repeated = fake.calls[first:]
    assert [kind for kind, *_ in repeated] == ["esearch", "esearch"]  # only the two count probes
    assert fake.count("efetch") == 1


# ---------------------------------------------------------------------------
# generate_search_queries: candidates for unmapped phrases
# ---------------------------------------------------------------------------


def _materials() -> dict[str, Any]:
    return {
        "mesh_terms": [{"input": "emergence delirium", "preferred": "Emergence Delirium"}],
        "mesh_candidates": [],
        "unmapped_phrases": ["processed", "monitoring", "post-anesthesia care unit", "recovery"],
        "suggested_queries": [{"id": "q1", "query": "x"}],
        "coverage": {"mesh": {"status": "completed"}},
        "warnings": [],
    }


async def test_unmapped_phrases_get_labeled_cooccurrence_candidates(fake: FakeEntrez):
    materials = await attach_cooccurrence_candidates(_materials(), make_service())

    (entry,) = materials["mesh_candidates"]
    assert entry["input"] == "post-anesthesia care unit" and entry["reason"] == "co_occurrence"
    first = entry["candidates"][0]
    assert first["preferred"] == "Anesthesia Recovery Period"
    assert first["search_clause"] == '"Anesthesia Recovery Period"[MeSH Terms]'
    assert first["share"] == pytest.approx(0.258, abs=1e-3)
    assert entry["evidence"]["records_with_mesh"] == 93
    # Never promoted to confirmed mappings or suggested queries.
    assert materials["mesh_terms"] == [{"input": "emergence delirium", "preferred": "Emergence Delirium"}]
    assert materials["suggested_queries"] == [{"id": "q1", "query": "x"}]
    coverage = materials["coverage"]["mesh_cooccurrence"]
    assert coverage["phrases"] == {"post-anesthesia care unit": "completed", "processed": "too_common"}
    assert coverage["phrases_not_considered"] == ["monitoring", "recovery"]
    assert coverage["budget"]["reserved"] <= 16
    assert fake.count("efetch") == 1  # the too-common phrase fetched no headings


async def test_cooccurrence_is_skipped_when_exact_lookup_failed_or_service_missing():
    failed = _materials()
    failed["coverage"]["mesh"]["status"] = "failed"
    gateway = MagicMock()

    await attach_cooccurrence_candidates(failed, MeshCorrectionService(gateway))
    disabled = await attach_cooccurrence_candidates(_materials(), None)

    assert failed["coverage"]["mesh_cooccurrence"]["status"] == "skipped"
    assert disabled["coverage"]["mesh_cooccurrence"]["status"] == "disabled"
    assert failed["mesh_candidates"] == disabled["mesh_candidates"] == []
    assert not gateway.method_calls


async def test_generate_search_queries_tool_attaches_candidates(fake: FakeEntrez):
    from pubmed_search.presentation.mcp_server.tools.strategy import register_strategy_tools

    tools: dict[str, Any] = {}
    mcp = MagicMock()
    mcp.tool = lambda: lambda func: tools.setdefault(func.__name__, func)
    register_strategy_tools(mcp, MagicMock())
    generator = AsyncMock()
    generator.generate_strategies.return_value = _materials()
    module = "pubmed_search.presentation.mcp_server.tools.strategy"

    with (
        patch(f"{module}.get_strategy_generator", return_value=generator),
        patch(f"{module}.get_mesh_correction_service", return_value=make_service()),
    ):
        payload = json.loads(await tools["generate_search_queries"](topic="PACU delirium"))

    assert [entry["reason"] for entry in payload["mesh_candidates"]] == ["co_occurrence"]
    assert "co_occurrence" in payload["_hint"]["mesh_review"]


def test_candidate_entry_shape_is_stable():
    from pubmed_search.application.search.mesh_correction import CooccurrenceReport
    from pubmed_search.domain.services.mesh_correction import ScoredDescriptor

    entry = cooccurrence_candidate_entry(
        CooccurrenceReport(
            phrase="pacu",
            status="completed",
            evidence_query='"pacu"[tiab] AND medline[sb]',
            variants=("pacu",),
            candidates=(ScoredDescriptor("Recovery Room", 3, 0.1, 1394, 440, 0.118, 0.316, 0.172),),
        )
    )

    assert set(entry) == {"input", "reason", "note", "candidates", "evidence"}
    assert set(entry["candidates"][0]) == {
        "preferred",
        "search_clause",
        "records",
        "share",
        "background_count",
        "joint_count",
        "recall",
        "precision",
        "score",
    }


def test_server_runtime_installs_the_correctionmake_service(tmp_path):
    from pubmed_search.presentation.mcp_server.server import create_server

    server = create_server(email="test@example.com", data_dir=str(tmp_path), mode="local")

    assert isinstance(server.get_tool_session_runtime().mesh_correction, MeshCorrectionService)


def test_policy_rejects_out_of_range_values():
    with pytest.raises(ValueError, match="max_ncbi_requests"):
        MeshCorrectionPolicy(max_ncbi_requests=0)
    with pytest.raises(ValueError, match="min_share"):
        MeshCorrectionPolicy(min_share=1.5)
