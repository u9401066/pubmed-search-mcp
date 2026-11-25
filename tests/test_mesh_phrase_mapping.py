"""MeSH phrase mapping accepts only preferred-term or entry-term equality.

The fake NCBI boundary below answers db=mesh ESearch only for quoted exact-term
clauses and fails the test on any other MeSH search, so a regression to
free-text MeSH lookups (which match scope notes) cannot pass silently. Record
terms mirror NCBI ESummary output observed on 2026-11-25 unless noted.
"""

from __future__ import annotations

import re
from contextlib import ExitStack
from typing import Any
from unittest.mock import patch

import pytest

from pubmed_search.domain.services.mesh_phrase_matching import (
    MeshRecord,
    contains_phrase,
    lookup_variants,
    match_term,
    matches_for,
    parse_topic,
    resolve_matches,
    select_mappings,
    term_key,
)
from pubmed_search.infrastructure.ncbi.base import NCBIInfrastructureError
from pubmed_search.infrastructure.ncbi.strategy import SearchStrategyGenerator, _mesh_record_from_summary

TOPIC = (
    "processed electroencephalography monitoring in post-anesthesia care unit adults "
    "emergence delirium recovery of consciousness length of stay"
)
STRATEGY = "pubmed_search.infrastructure.ncbi.strategy"
_EXACT_CLAUSE = re.compile(r'"([^"]+)"\[(MeSH Terms|Substance Name)\]')


def _doc(uid: str, *terms: str, trees: tuple[str, ...] = ("X00",), scr: bool = False, **extra: Any) -> dict:
    return {
        "Id": uid,
        "DS_MeshTerms": list(terms),
        "DS_IdxLinks": [{"TreeNum": tree} for tree in trees],
        "DS_HeadingMappedToList": [68001569] if scr else [],
        "DS_PaList": [],
        **extra,
    }


LIVE_RECORDS = [
    # No post-anesthesia care unit / PACU entry term exists in the live record.
    _doc(
        "68011997",
        "Recovery Room",
        "Recovery Rooms, Hospital",
        "Room, Hospital Recovery",
        "Rooms, Hospital Recovery",
        "Hospital Recovery Room",
        "Recovery Room, Hospital",
        "Recovery Rooms",
        "Room, Recovery",
        "Rooms, Recovery",
        "Hospital Recovery Rooms",
        trees=("N02.278.388.493.592",),
    ),
    _doc(
        "68007902",
        "Length of Stay",
        "Stay Length",
        "Stay Lengths",
        "Hospital Stay",
        "Hospital Stays",
        "Stay, Hospital",
        "Stays, Hospital",
        trees=("E02.760.400.480", "N02.421.585.400.480"),
    ),
    _doc(
        "68004569",
        "Electroencephalography",
        "EEG",
        "Electroencephalogram",
        "Electroencephalograms",
        trees=("E01.370.376.300", "E01.370.405.245"),
    ),
    _doc("68003243", "Consciousness", "Consciousnesses", trees=("F02.463.188.409", "F02.830.233")),
    _doc("68000328", "Adult", "Adults", trees=("M01.060.116",)),
    _doc(
        "2016453",
        "Emergence Delirium",
        "Delirium, Emergence",
        "Emergence Agitation",
        "Anesthesia Emergence Delirium",
        "Postoperative Delirium",
        "Post-Operative Delirium",
        trees=("C10.597.606.337.500.500", "F01.700.250.500.500"),
    ),
]

# Descriptors the pre-fix fuzzy lookup returned for stopword-bounded n-grams.
DECOY_RECORDS = [
    _doc("68000001", "Neurophysiological Monitoring", "Monitoring, Neurophysiological"),
    _doc("68000002", "Delayed Emergence from Anesthesia", "Emergence from Anesthesia, Delayed"),
    _doc("68000003", "Postanesthesia Nursing", "Post-Anesthesia Nursing", "Nursing, Postanesthesia"),
    _doc("68000004", "Hospital Rapid Response Team", "Rapid Response Team"),
    _doc("68000005", "Lysholm Knee Score"),
    _doc("68000006", "Consciousness Monitors", "Monitors, Consciousness"),
    _doc("68000007", "3-Hydroxyacyl-CoA Dehydrogenase", "Long-Chain 3-Hydroxyacyl-CoA Dehydrogenase"),
    _doc("68000008", "Utilization Review", "Review, Utilization"),
    _doc("68000009", "Diet, Western", "Western Diet"),
    _doc("68000010", "Intensive Care Units", "Intensive Care Unit", "Care Units, Intensive"),
]

LIVE_TRANSLATION_SET = [
    {"From": "processed", "To": '"process"[All Fields] OR "processed"[All Fields]'},
    {
        "From": "electroencephalography",
        "To": '"electroencephalographies"[All Fields] OR "electroencephalography"[MeSH Terms] OR '
        '"electroencephalography"[All Fields]',
    },
    {"From": "monitoring", "To": '"monitor"[All Fields] OR "monitoring"[All Fields]'},
    {"From": "adults", "To": '"adult"[MeSH Terms] OR "adult"[All Fields] OR "adults"[All Fields]'},
    {
        "From": "emergence delirium",
        "To": '"emergence delirium"[MeSH Terms] OR ("emergence"[All Fields] AND "delirium"[All Fields])',
    },
    {"From": "recovery", "To": '"recoveries"[All Fields] OR "recovery"[All Fields]'},
    {"From": "consciousness", "To": '"consciousness"[MeSH Terms] OR "consciousness"[All Fields]'},
    {"From": "length of stay", "To": '"length of stay"[MeSH Terms] OR ("length"[All Fields] AND "stay"[All Fields])'},
]

JUNK_INPUTS = {
    "monitoring in",
    "in post-anesthesia",
    "post-anesthesia care",
    "care unit",
    "recovery of",
    "of consciousness",
    "length of",
    "of stay",
    "processed",
}


class _Handle:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def close(self) -> None:
        return None


class FakeNCBI:
    """Exact-term MeSH index plus a fixed PubMed automatic term mapping."""

    def __init__(self, docs: list[dict], translation_set: list[dict] | None = None) -> None:
        self.docs = {doc["Id"]: doc for doc in docs}
        self.translation_set = translation_set or []
        self.calls: list[tuple[str, str, str]] = []
        self.mesh_clauses: list[str] = []
        self.fail_summary = False
        self.fail_translation = False

    def esearch(self, *, db: str, term: str, retmax: int, **_: Any) -> _Handle:
        self.calls.append(("esearch", db, term))
        if db == "pubmed":
            if self.fail_translation:
                raise RuntimeError("translation outage")
            return _Handle(
                {
                    "Count": "0",
                    "IdList": [],
                    "QueryTranslation": term,
                    "TranslationSet": self.translation_set,
                    "TranslationStack": [],
                }
            )
        assert db == "mesh"
        hits: list[str] = []
        for clause in term.split(" OR "):
            match = _EXACT_CLAUSE.fullmatch(clause)
            assert match, f"non-exact MeSH search issued: {clause!r}"
            self.mesh_clauses.append(clause)
            phrase, field = match.groups()
            for uid, doc in self.docs.items():
                if (field == "Substance Name") != bool(doc.get("DS_HeadingMappedToList")):
                    continue
                if any(term.casefold() == phrase.casefold() for term in doc["DS_MeshTerms"]):
                    hits.append(uid)
        unique = list(dict.fromkeys(hits))
        return _Handle({"Count": str(len(unique)), "IdList": unique[:retmax]})

    def esummary(self, *, db: str, id: str, **_: Any) -> _Handle:  # noqa: A002 - Entrez keyword
        assert db == "mesh"
        self.calls.append(("esummary", db, id))
        if self.fail_summary:
            raise RuntimeError("summary outage")
        return _Handle([self.docs[uid] for uid in id.split(",")])

    def count(self, kind: str, db: str) -> int:
        return sum(1 for call_kind, call_db, _ in self.calls if (call_kind, call_db) == (kind, db))

    def install(self, stack: ExitStack) -> None:
        stack.enter_context(patch(f"{STRATEGY}.Entrez.esearch", side_effect=self.esearch))
        stack.enter_context(patch(f"{STRATEGY}.Entrez.esummary", side_effect=self.esummary))
        stack.enter_context(patch(f"{STRATEGY}.Entrez.read", side_effect=lambda handle: handle.payload))


async def _generate(fake: FakeNCBI, topic: str, generator: SearchStrategyGenerator | None = None, **kwargs: Any):
    generator = generator or SearchStrategyGenerator(email="test@example.com")
    options = {"check_spelling": False, "include_suggestions": False, **kwargs}
    with ExitStack() as stack:
        fake.install(stack)
        return await generator.generate_strategies(topic=topic, **options)


# ---------------------------------------------------------------------------
# Phrase extraction and acceptance rules (pure domain)
# ---------------------------------------------------------------------------


def test_candidates_are_stopword_bounded_longest_first_and_keep_hyphenated_compounds():
    phrases = parse_topic(TOPIC)
    texts = [candidate.text for candidate in phrases.candidates]

    # Stopword-bounded fragments are never built; the remaining junk inputs are
    # valid phrases that the acceptance rule must reject instead.
    assert not {"monitoring in", "in post-anesthesia", "recovery of", "of consciousness", "length of", "of stay"} & set(
        texts
    )
    for candidate in texts:
        words = candidate.split()
        assert words[0] not in {"in", "of"} and words[-1] not in {"in", "of"}, candidate
    assert "post-anesthesia care unit" in texts
    assert "length of stay" in texts and "recovery of consciousness" in texts
    assert "post" not in phrases.tokens and "anesthesia" not in phrases.tokens
    sizes = [candidate.size for candidate in phrases.candidates]
    assert sizes == sorted(sizes, reverse=True)
    assert max(sizes) == 6


def test_candidates_never_cross_punctuation_quotes_field_tags_or_boolean_operators():
    phrases = parse_topic('"heart failure"[tiab] AND (dapagliflozin OR placebo), COVID-19; Alzheimer\'s disease.')
    texts = {candidate.text for candidate in phrases.candidates}
    assert {"heart failure", "dapagliflozin", "placebo", "COVID-19", "Alzheimer's disease"} <= texts
    assert not any(word in text.split() for text in texts for word in ("AND", "OR", "tiab"))
    assert "failure dapagliflozin" not in texts and "placebo COVID-19" not in texts


def test_lowercase_or_and_not_split_a_topic_like_pubmed_but_and_does_not():
    texts = {
        candidate.text
        for candidate in parse_topic("delirium or agitation not dementia; head and neck neoplasms").candidates
    }
    assert "delirium or agitation" not in texts and "agitation not dementia" not in texts
    assert {"delirium", "agitation", "dementia", "head and neck neoplasms"} <= texts


def test_long_topics_are_bounded_and_flagged():
    phrases = parse_topic(" ".join(f"word{index}" for index in range(80)))
    assert len(phrases.tokens) == 48 and phrases.truncated


@pytest.mark.parametrize(
    ("phrase", "term"),
    [
        ("post-anesthesia care unit", "Post-Anesthesia Care Units"),
        ("postanesthesia care unit", "Post-Anesthesia Care Units"),
        ("ADULTS", "Adult"),
        ("therapies", "Therapy"),
        ("Alzheimer's disease", "Alzheimer Disease"),
        ("length of stay", "Length of Stay"),
    ],
)
def test_term_key_folds_case_hyphen_spacing_and_simple_plurals(phrase: str, term: str):
    assert term_key(phrase) == term_key(term)


@pytest.mark.parametrize(
    ("phrase", "term"),
    [
        ("care unit", "Intensive Care Units"),
        ("length of", "Length of Stay"),
        ("monitoring", "Neurophysiological Monitoring"),
        ("emergence delirium", "Delirium, Emergence"),
    ],
)
def test_partial_or_reordered_terms_never_match(phrase: str, term: str):
    assert match_term(phrase, MeshRecord(uid="1", preferred=term)) is None


def test_lookup_variants_share_the_phrase_key():
    variants = lookup_variants("post-anesthesia care unit")
    assert "post-anesthesia care units" in variants
    assert "postanesthesia care unit" in variants and "post anesthesia care unit" in variants
    assert {term_key(variant) for variant in variants} == {term_key("post-anesthesia care unit")}
    assert lookup_variants("consciousness") == ("consciousness",)


def test_literal_entry_term_is_reported_before_normalized_preferred_term():
    record = MeshRecord(uid="68000328", preferred="Adult", entry_terms=("Adults",))
    match = match_term("adults", record)
    assert match is not None
    assert (match.matched_on, match.matched_term) == ("entry_term", "Adults")
    preferred = match_term("Adult", record)
    assert preferred is not None and preferred.matched_on == "preferred"


def test_phrase_claimed_by_several_records_is_not_resolved():
    cold = [
        MeshRecord(uid="1", preferred="Common Cold", entry_terms=("Cold",)),
        MeshRecord(uid="2", preferred="Cold Temperature", entry_terms=("Cold",)),
    ]
    assert resolve_matches(matches_for("cold", cold)) is None
    shadow = [
        MeshRecord(uid="82014151", preferred="Anti-Anxiety Agents"),
        MeshRecord(uid="68014151", preferred="Anti-Anxiety Agents", tree_numbers=("D27.505",)),
    ]
    chosen = resolve_matches(matches_for("anti-anxiety agents", shadow))
    assert chosen is not None and chosen.record.uid == "68014151"


def test_greedy_cover_prefers_longest_phrase_and_reports_unmapped_text():
    phrases = parse_topic("emergence delirium after surgery")
    records = {
        "emergencedelirium": (MeshRecord(uid="1", preferred="Emergence Delirium"),),
        "delirium": (MeshRecord(uid="2", preferred="Delirium"),),
    }
    selection = select_mappings(phrases, records)
    assert [mapping.phrase.text for mapping in selection.confirmed] == ["emergence delirium"]
    assert selection.unmapped == ("surgery",)
    assert contains_phrase("emergence delirium", "Delirium") and not contains_phrase("delirium", "emergence")


def test_summary_parser_classifies_records_and_skips_qualifiers_and_actions():
    scr = _mesh_record_from_summary(
        _doc("67522201", "remimazolam", "CNS 7056", trees=("@167407",), scr=True)  # live SCR shape
    )
    assert scr is not None and scr.record_type == "supplementary_concept" and scr.tree_numbers == ()
    assert scr.search_field == "Supplementary Concept"
    pt = _mesh_record_from_summary(_doc("68016449", "Randomized Controlled Trial", trees=("V03.175.250.500.500",)))
    assert pt is not None and pt.search_field == "Publication Type"
    assert _mesh_record_from_summary(_doc("81000628", "therapy", "treatment", trees=("Y11",))) is None
    assert (
        _mesh_record_from_summary(_doc("82014151", "Anti-Anxiety Agents", trees=(), DS_PaList=["Chalazepam"])) is None
    )
    with pytest.raises(ValueError, match="identifier"):
        _mesh_record_from_summary(_doc("D003920", "Diabetes Mellitus"))


def test_summary_parser_keeps_a_descriptors_allowable_qualifiers():
    # Live Bio.Entrez key and spelling (ESummary 2026-11-25): "DS_Subheading", "and" for "&".
    descriptor = _mesh_record_from_summary(
        _doc("68020927", "Dexmedetomidine", DS_Subheading=["administration and dosage", "adverse effects"])
    )
    assert descriptor is not None
    assert descriptor.allowed_qualifiers == ("administration and dosage", "adverse effects")
    unlisted = _mesh_record_from_summary(_doc("68003920", "Diabetes Mellitus"))
    assert unlisted is not None and unlisted.allowed_qualifiers == ()  # unknown, not "none allowed"


# ---------------------------------------------------------------------------
# generate_strategies through the fake Entrez boundary
# ---------------------------------------------------------------------------


async def test_pacu_topic_rejects_junk_ngrams_and_maps_exact_terms_only():
    fake = FakeNCBI(LIVE_RECORDS + DECOY_RECORDS, LIVE_TRANSLATION_SET)

    result = await _generate(fake, TOPIC)

    mapped = {mesh["input"]: mesh for mesh in result["mesh_terms"]}
    assert {phrase: mesh["preferred"] for phrase, mesh in mapped.items()} == {
        "electroencephalography": "Electroencephalography",
        "adults": "Adult",
        "emergence delirium": "Emergence Delirium",
        "consciousness": "Consciousness",
        "length of stay": "Length of Stay",
    }
    assert [mesh["input"] for mesh in result["mesh_terms"]] == list(mapped)  # topic order
    assert mapped["electroencephalography"]["matched_on"] == "preferred"
    assert (mapped["adults"]["matched_on"], mapped["adults"]["matched_term"]) == ("entry_term", "Adults")
    assert mapped["length of stay"]["mesh_id"] == "68007902"
    assert mapped["emergence delirium"]["search_field"] == "MeSH Terms"
    assert {mesh["pubmed_atm"] for mesh in result["mesh_terms"]} == {"agrees"}

    assert not JUNK_INPUTS & set(mapped)
    decoys = {doc["DS_MeshTerms"][0] for doc in DECOY_RECORDS}
    assert not decoys & {mesh["preferred"] for mesh in result["mesh_terms"]}
    assert result["mesh_candidates"] == []
    assert result["unmapped_phrases"] == ["processed", "monitoring", "post-anesthesia care unit", "recovery"]
    assert "Recovery Room" not in str(result["mesh_terms"])

    coverage = result["coverage"]["mesh"]
    assert coverage["status"] == "completed" and coverage["matched"] == 5 and coverage["unconfirmed"] == 0
    assert result["coverage"]["pubmed_atm"]["status"] == "completed"
    # One ATM translation, batched exact ESearch, one ESummary; previously ~50 requests.
    assert fake.count("esearch", "pubmed") == 1
    assert 1 <= fake.count("esearch", "mesh") <= 2
    assert fake.count("esummary", "mesh") == 1
    assert '"post-anesthesia care units"[MeSH Terms]' in fake.mesh_clauses


async def test_suggested_queries_use_confirmed_mappings_only():
    fake = FakeNCBI(LIVE_RECORDS + DECOY_RECORDS, LIVE_TRANSLATION_SET)

    result = await _generate(fake, TOPIC, include_suggestions=True, analyze_queries=False)

    mesh_queries = [query["query"] for query in result["suggested_queries"] if query["id"].endswith("_mesh")]
    assert mesh_queries == ['"Electroencephalography"[MeSH Terms]', '"Adult"[MeSH Terms]']
    rendered = str(result["suggested_queries"])
    for decoy in DECOY_RECORDS:
        assert decoy["DS_MeshTerms"][0] not in rendered
    assert set(result["all_synonyms"]) <= {synonym for doc in LIVE_RECORDS for synonym in doc["DS_MeshTerms"]}


async def test_entry_term_match_maps_pacu_phrase_to_recovery_room():
    # Synthetic record: live MeSH (2026-11-25) lists no PACU entry term for
    # Recovery Room. This proves hyphen/plural folding through an entry term.
    recovery_room = _doc(
        "68011997",
        "Recovery Room",
        "Post-Anesthesia Care Units",
        "PACU",
        "Recovery Rooms",
        trees=("N02.278.388.493.592",),
    )
    fake = FakeNCBI([recovery_room, *LIVE_RECORDS[1:]])

    result = await _generate(fake, "post-anesthesia care unit length of stay")

    pacu, stay = result["mesh_terms"]
    assert pacu["input"] == "post-anesthesia care unit"
    assert pacu["preferred"] == "Recovery Room"
    assert (pacu["matched_on"], pacu["matched_term"]) == ("entry_term", "Post-Anesthesia Care Units")
    assert pacu["pubmed_atm"] == "not_mapped"
    assert (stay["input"], stay["preferred"], stay["matched_on"]) == ("length of stay", "Length of Stay", "preferred")
    assert result["unmapped_phrases"] == []


async def test_pubmed_atm_only_link_is_an_unconfirmed_candidate():
    diabetes = _doc("68003920", "Diabetes Mellitus", trees=("C18.452.394.750", "C19.246"))
    translation = [{"From": "diabetes", "To": '"diabetes mellitus"[MeSH Terms] OR "diabetes"[All Fields]'}]
    fake = FakeNCBI([diabetes], translation)

    result = await _generate(fake, "diabetes", include_suggestions=True, analyze_queries=False)

    assert result["mesh_terms"] == []
    assert result["mesh_candidates"] == [
        {
            "input": "diabetes",
            "preferred": "Diabetes Mellitus",
            "mesh_id": "68003920",
            "record_type": "descriptor",
            "reason": "pubmed_atm_only",
            "note": result["mesh_candidates"][0]["note"],
        }
    ]
    assert result["unmapped_phrases"] == ["diabetes"]
    assert not any("[MeSH Terms]" in query["query"] for query in result["suggested_queries"])
    assert result["coverage"]["mesh"]["unconfirmed"] == 1


async def test_ambiguous_exact_term_is_not_presented_as_a_mapping():
    fake = FakeNCBI(
        [
            _doc("1", "Common Cold", "Cold", trees=("C01.925",)),
            _doc("2", "Cold Temperature", "Cold", trees=("G01.358",)),
        ]
    )

    result = await _generate(fake, "cold")

    assert result["mesh_terms"] == []
    (candidate,) = result["mesh_candidates"]
    assert candidate["reason"] == "ambiguous_exact_term"
    assert {item["preferred"] for item in candidate["candidates"]} == {"Common Cold", "Cold Temperature"}
    assert result["unmapped_phrases"] == []


async def test_supplementary_concept_uses_its_own_search_field():
    remimazolam = _doc("67522201", "remimazolam", "CNS 7056", "ONO 2745", trees=("@167407",), scr=True)
    translation = [{"From": "remimazolam", "To": '"remimazolam"[Supplementary Concept] OR "remimazolam"[All Fields]'}]
    fake = FakeNCBI([remimazolam], translation)

    result = await _generate(fake, "remimazolam", include_suggestions=True, analyze_queries=False)

    (mesh,) = result["mesh_terms"]
    assert (mesh["record_type"], mesh["pubmed_atm"]) == ("supplementary_concept", "agrees")
    assert '"remimazolam"[Supplementary Concept]' in [query["query"] for query in result["suggested_queries"]]


async def test_mesh_lookups_are_cached_including_misses():
    generator = SearchStrategyGenerator(email="test@example.com")
    fake = FakeNCBI(LIVE_RECORDS, LIVE_TRANSLATION_SET)

    first = await _generate(fake, TOPIC, generator)
    lookups = fake.count("esearch", "mesh") + fake.count("esummary", "mesh")
    second = await _generate(fake, TOPIC, generator)

    assert fake.count("esearch", "mesh") + fake.count("esummary", "mesh") == lookups
    assert first["mesh_terms"] == second["mesh_terms"]
    assert first["unmapped_phrases"] == second["unmapped_phrases"]


async def test_summary_outage_fails_closed_without_mappings():
    fake = FakeNCBI(LIVE_RECORDS, LIVE_TRANSLATION_SET)
    fake.fail_summary = True

    with patch(f"{STRATEGY}.MAX_RETRIES", 1):
        result = await _generate(fake, "emergence delirium")

    assert result["mesh_terms"] == [] and result["mesh_candidates"] == []
    assert result["coverage"]["mesh"]["status"] == "failed"
    assert result["unmapped_phrases"] == ["emergence delirium"]
    assert "NCBI MeSH analysis was unavailable for one or more terms." in result["warnings"]

    generator = SearchStrategyGenerator(email="test@example.com")
    with ExitStack() as stack, patch(f"{STRATEGY}.MAX_RETRIES", 1):
        fake.install(stack)
        with pytest.raises(NCBIInfrastructureError):
            await generator.get_mesh_info("emergence delirium")
    fake.fail_summary = False
    with ExitStack() as stack:
        fake.install(stack)
        info = await generator.get_mesh_info("Emergence Delirium")
    assert info is not None and info["matched_on"] == "preferred"


async def test_translation_outage_keeps_exact_mappings_without_corroboration():
    fake = FakeNCBI(LIVE_RECORDS, LIVE_TRANSLATION_SET)
    fake.fail_translation = True

    with patch(f"{STRATEGY}.MAX_RETRIES", 1):
        result = await _generate(fake, "emergence delirium length of stay")

    assert [(mesh["input"], mesh["pubmed_atm"]) for mesh in result["mesh_terms"]] == [
        ("emergence delirium", None),
        ("length of stay", None),
    ]
    assert result["mesh_candidates"] == []
    assert result["coverage"]["pubmed_atm"]["status"] == "failed"
    assert result["coverage"]["mesh"]["status"] == "completed"
