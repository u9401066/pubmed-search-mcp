"""Deterministic NCBI boundary for MeSH-correction tests.

``FakeEntrez`` stands in for Bio.Entrez only (ESearch with WarningList and
ErrorList, the exact-term MeSH index with ESummary, and MEDLINE-format EFetch),
so the production gateway, exact MeSH lookup, MEDLINE parsing, transport kernel
and services run for real.

Fixture provenance (2026-11-25):

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
- Joint counts (evidence AND heading) are synthetic, sized like the shares
  above over the 3717 evidence records.
- ``"Ischemia/Reperfusion Injury"[Mesh]`` came back as ``QuotedPhraseNotFound``
  and so did the same phrase as a quoted db=mesh ``[MeSH Terms]`` clause, while
  ``"Ischemia-Reperfusion Injury"[MeSH Terms]`` found D015427 (Reperfusion
  Injury), whose live ESummary lists that hyphenated entry term. The Ischemia
  record is reduced to its preferred term.
"""

from __future__ import annotations

import re
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from pubmed_search.application.search.mesh_correction import MeshCorrectionPolicy, MeshCorrectionService
from pubmed_search.infrastructure.ncbi.mesh_evidence import NCBIMeshEvidenceGateway
from pubmed_search.infrastructure.ncbi.strategy import SearchStrategyGenerator

if TYPE_CHECKING:
    from collections.abc import Iterator

PACU = '"Post-Anesthesia Care Units"[Mesh]'
PACU_QUERY = f"{PACU} AND delirium[tiab]"
EVIDENCE_TOTAL = 3717
FIXED_NOW = datetime(2026, 11, 25, 8, 30, tzinfo=timezone.utc)
_EXACT_CLAUSE = re.compile(r'"([^"]+)"\[(MeSH Terms|Substance Name)\]')
_BACKGROUND = re.compile(r'^"([^"]+)"\[mh:noexp\]$')
_JOINT = re.compile(r' AND medline\[sb\] AND "([^"]+)"\[mh:noexp\]$')
_QUOTED_MESH = re.compile(r'"[^"]+"\[(?:mesh|mh|majr|mesh terms|mesh major topic)(?::noexp)?\]', re.IGNORECASE)

# Headings per sampled record: (descriptor, records) over 93 indexed records.
PACU_DISTRIBUTION = [
    ("Humans", 93),
    ("Female", 75),
    ("Male", 67),
    ("Middle Aged", 59),
    ("Adult", 48),
    ("Aged", 41),
    ("Postoperative Pain", 32),
    ("Anesthesia Recovery Period", 24),
    ("Retrospective Studies", 20),
    ("Postoperative Complications", 20),
    ("Prospective Studies", 20),
    ("Anesthesia, General", 19),
    ("Treatment Outcome", 12),
    ("Length of Stay", 10),
    ("Pain Measurement", 8),
    ("Recovery Room", 11),
]
BACKGROUND_COUNTS = {
    "Anesthesia Recovery Period": 6140,
    "Postoperative Pain": 59724,
    "Postoperative Complications": 690806,
    "Anesthesia, General": 25000,
    "Length of Stay": 120182,
    "Pain Measurement": 70000,
    "Recovery Room": 1394,
}
JOINT_COUNTS = {
    "Anesthesia Recovery Period": 966,
    "Postoperative Pain": 1264,
    "Postoperative Complications": 818,
    "Anesthesia, General": 743,
    "Length of Stay": 400,
    "Pain Measurement": 320,
    "Recovery Room": 440,
}


def _doc(uid: str, *terms: str, trees: tuple[str, ...] = ("X00",), scr: bool = False) -> dict[str, Any]:
    return {
        "Id": uid,
        "DS_MeshTerms": list(terms),
        "DS_IdxLinks": [{"TreeNum": tree} for tree in trees],
        "DS_HeadingMappedToList": [68001569] if scr else [],
        "DS_PaList": [],
    }


MESH_DOCS = [
    _doc(
        "2016453",
        "Emergence Delirium",
        "Delirium, Emergence",
        "Anesthesia Emergence Delirium",
        "Postoperative Delirium",
        "Post-Operative Delirium",
        trees=("C10.597.606.337.500.500",),
    ),
    _doc("68003693", "Delirium", "Deliriums", trees=("F01.700.250.500",)),
    _doc("68011997", "Recovery Room", "Recovery Rooms", "Hospital Recovery Room", trees=("N02.278.388.493.592",)),
    _doc("68019990", "Anesthesia Recovery Period", "Recovery Period, Anesthesia", trees=("E03.155.086",)),
    _doc("67522201", "remimazolam", "CNS 7056", trees=("@167407",), scr=True),
    _doc(
        "68015427",
        "Reperfusion Injury",
        "Reperfusion Injuries",
        "Injury, Ischemia-Reperfusion",
        "Ischemia-Reperfusion Injury",
        "Ischemia Reperfusion Injury",
        "Reperfusion Damage",
        trees=("C14.907.725", "C23.550.767.877"),
    ),
    _doc("68007511", "Ischemia", trees=("C14.907.553", "C23.550.513")),
]


def _pacu_headings() -> dict[str, list[str]]:
    """150 PMIDs; the first 93 carry the distribution above, the rest no MeSH."""
    pmids = [str(40_000_000 + index) for index in range(150)]
    headings: dict[str, list[str]] = {pmid: [] for pmid in pmids}
    for descriptor, records in PACU_DISTRIBUTION:
        for pmid in pmids[:records]:
            prefix = "*" if descriptor == "Anesthesia Recovery Period" else ""
            headings[pmid].append(f"{prefix}{descriptor}/statistics & numerical data" if prefix else descriptor)
    return headings


class _Handle:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def read(self) -> Any:
        return self.payload

    def close(self) -> None:
        return None


class FakeEntrez:
    """PubMed ESearch with diagnostics, exact-term MeSH index and MEDLINE EFetch."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.mesh_docs = {doc["Id"]: doc for doc in MESH_DOCS}
        self.bad_quoted = {
            '"post-anesthesia care units"[mesh]',
            '"emergence deliriums"[mesh]',
            '"recovery rooms"[mesh:noexp]',
            '"remimazolam"[mesh]',
            '"post-operative deliriums"[majr]',
            '"postanesthesia recovery wards"[mesh]',
            '"ischemia/reperfusion injury"[mesh]',
        }
        self.bad_bare = {"pacu": "PACU", "units": "units"}
        self.headings = _pacu_headings()
        self.evidence_total = EVIDENCE_TOTAL
        self.background = dict(BACKGROUND_COUNTS)
        self.joint = dict(JOINT_COUNTS)
        self.counts: dict[str, int] = {}
        self.medline_extra_pmid: str | None = None
        self.fail_probe = False

    # -- PubMed -------------------------------------------------------------
    def _pubmed(self, term: str, retmax: int) -> dict[str, Any]:
        record: dict[str, Any] = {"Count": "0", "IdList": [], "TranslationSet": [], "QueryTranslation": term}
        joint = _JOINT.search(term)
        if joint:
            record["Count"] = str(self.joint.get(joint.group(1), 0))
            return record
        if term.endswith("AND medline[sb]"):
            if "processed" in term:
                record["Count"] = "250000"
                record["IdList"] = [str(30_000_000 + index) for index in range(retmax)]
                return record
            pmids = list(self.headings)[:retmax]
            record["Count"], record["IdList"] = str(self.evidence_total), pmids
            if '"Postanesthesia Care Unit"[tiab]' in term:
                record["WarningList"] = {
                    "QuotedPhraseNotFound": ['"Postanesthesia Care Unit"[tiab]'],
                    "PhraseIgnored": [],
                    "OutputMessage": [],
                }
            return record
        background = _BACKGROUND.match(term)
        if background:
            record["Count"] = str(self.background.get(background.group(1), 0))
            return record
        if self.fail_probe:
            raise RuntimeError("probe outage")
        quoted_missing = [clause for clause in _QUOTED_MESH.findall(term) if clause.casefold() in self.bad_quoted]
        bare_missing = [
            self.bad_bare[word.casefold()]
            for word in re.findall(r"([\w-]+)\[mh\]", term)
            if word.casefold() in self.bad_bare
        ]
        if quoted_missing or bare_missing:
            record["WarningList"] = {
                "QuotedPhraseNotFound": quoted_missing,
                "PhraseIgnored": [],
                "OutputMessage": ["No items found."],
            }
            if bare_missing:
                record["ErrorList"] = {"PhraseNotFound": bare_missing, "FieldNotFound": []}
            return record
        record["Count"] = str(self.counts.get(term, 412))
        return record

    def esearch(self, *, db: str, term: str, retmax: int = 20, **_: Any) -> _Handle:
        self.calls.append(("esearch", db, term))
        if db == "pubmed":
            return _Handle(self._pubmed(term, retmax))
        assert db == "mesh"
        hits: list[str] = []
        for clause in term.split(" OR "):
            match = _EXACT_CLAUSE.fullmatch(clause)
            assert match, f"non-exact MeSH search issued: {clause!r}"
            phrase, field = match.groups()
            for uid, doc in self.mesh_docs.items():
                if (field == "Substance Name") != bool(doc["DS_HeadingMappedToList"]):
                    continue
                if any(name.casefold() == phrase.casefold() for name in doc["DS_MeshTerms"]):
                    hits.append(uid)
        unique = list(dict.fromkeys(hits))
        return _Handle({"Count": str(len(unique)), "IdList": unique[:retmax]})

    def esummary(self, *, db: str, id: str, **_: Any) -> _Handle:  # noqa: A002 - Entrez keyword
        assert db == "mesh"
        self.calls.append(("esummary", db, id))
        return _Handle([self.mesh_docs[uid] for uid in id.split(",")])

    def efetch(self, *, db: str, id: str, rettype: str, retmode: str, **_: Any) -> _Handle:  # noqa: A002
        assert (db, rettype, retmode) == ("pubmed", "medline", "text")
        self.calls.append(("efetch", db, id))
        pmids = id.split(",")
        if self.medline_extra_pmid:
            pmids.append(self.medline_extra_pmid)
        blocks = []
        for pmid in pmids:
            lines = [f"PMID- {pmid}", "TI  - Synthetic record"]
            lines.extend(f"MH  - {heading}" for heading in self.headings.get(pmid, []))
            blocks.append("\n".join(lines))
        return _Handle("\n\n".join(blocks) + "\n")

    def count(self, kind: str, db: str | None = None) -> int:
        return sum(1 for call_kind, call_db, _ in self.calls if call_kind == kind and db in {None, call_db})

    @contextmanager
    def installed(self) -> Iterator[FakeEntrez]:
        with ExitStack() as stack:
            stack.enter_context(patch("Bio.Entrez.esearch", side_effect=self.esearch))
            stack.enter_context(patch("Bio.Entrez.esummary", side_effect=self.esummary))
            stack.enter_context(patch("Bio.Entrez.efetch", side_effect=self.efetch))
            stack.enter_context(patch("Bio.Entrez.read", side_effect=lambda handle: handle.payload))
            yield self


def make_service(policy: MeshCorrectionPolicy | None = None) -> MeshCorrectionService:
    vocabulary = SearchStrategyGenerator(email="test@example.com", api_key="test-key")
    gateway = NCBIMeshEvidenceGateway(
        email="test@example.com", api_key="test-key", vocabulary=vocabulary, clock=lambda: FIXED_NOW
    )
    return MeshCorrectionService(gateway, policy)
