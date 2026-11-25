"""Pure rules for finding, judging and rewriting MeSH-tagged PubMed query terms.

Design:
    A MeSH-tagged clause (``"X"[Mesh]``, ``X[mh]``, ``"X/therapy"[Majr]``,
    ``"X"[mesh:noexp]``...) is located by its field tag. PubMed itself says
    which clauses it could not resolve (``QuotedPhraseNotFound`` for quoted
    clauses, ``PhraseNotFound`` for bare words); only those clauses are ever
    rewritten, so a valid heading is never "corrected".

    Data-driven candidates come from MEDLINE records whose title/abstract use
    the agent's words. A bounded sample *nominates* headings: each
    descriptor's *share* is the fraction of sampled records indexed with it.
    Check tags (Humans, Male, Adult...) and study-design descriptors
    (Retrospective Studies...) describe the study population or method, not
    the concept, and are excluded. Nominated headings are then *scored
    exactly* with two PubMed counts: the records indexed with the heading
    (``background``) and the evidence records indexed with it (``joint``).
    ``recall = joint / evidence_total`` is how much of the words' literature
    the heading covers and ``precision = joint / background`` how much of the
    heading's literature uses the words; candidates are ranked by their F1.
    A heading frequent everywhere (Postoperative Complications) has low
    precision; a heading introduced recently has few records overall and
    therefore low recall, so neither wins merely by co-occurring in a
    sample. (Hausner et al.'s objective approach likewise compares term
    frequency in a development set with a population set.)

Maintenance:
    No network access and no provider payload shapes here; NCBI adapters
    deliver headings as MEDLINE ``MH`` strings and counts as integers.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from .mesh_phrase_matching import lookup_variants, term_key
from .pubmed_boolean import boolean_operator, resembles_operator

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from pubmed_search.domain.value_objects.query_diagnostics import PubMedQueryDiagnostics

Confidence = Literal["high", "medium", "low"]
ExclusionReason = Literal["check_tag", "study_design"]

MAX_TEXT_WORD_VARIANTS = 6
TEXT_WORD_FIELD = "tiab"
MEDLINE_SUBSET = "medline[sb]"

_MESH_TAG = re.compile(
    r"\[\s*(?P<field>mesh\s+terms|mesh\s+major\s+topic|mesh|mh|majr)(?P<noexp>\s*:\s*noexp)?\s*\]",
    re.IGNORECASE,
)
_DELIMITERS = '()"[]'
_WORD = re.compile(r"\S+")

# The 76 MeSH qualifiers (subheadings) and their two-letter abbreviations, as
# listed by NLM's "Qualifiers - Scope Notes" (checked 2026-11-25). PubMed
# attaches at most one directly to a heading ("Neoplasms/diet therapy",
# "neoplasms/dh"); any other slash belongs to the heading text itself.
MESH_QUALIFIERS: Mapping[str, str] = MappingProxyType(
    {
        "abnormalities": "AB",
        "administration & dosage": "AD",
        "adverse effects": "AE",
        "agonists": "AG",
        "analogs & derivatives": "AA",
        "analysis": "AN",
        "anatomy & histology": "AH",
        "antagonists & inhibitors": "AI",
        "biosynthesis": "BI",
        "blood": "BL",
        "blood supply": "BS",
        "cerebrospinal fluid": "CF",
        "chemical synthesis": "CS",
        "chemically induced": "CI",
        "chemistry": "CH",
        "classification": "CL",
        "complications": "CO",
        "congenital": "CN",
        "cytology": "CY",
        "deficiency": "DF",
        "diagnosis": "DI",
        "diagnostic imaging": "DG",
        "diet therapy": "DH",
        "drug effects": "DE",
        "drug therapy": "DT",
        "economics": "EC",
        "education": "ED",
        "embryology": "EM",
        "enzymology": "EN",
        "epidemiology": "EP",
        "ethics": "ES",
        "ethnology": "EH",
        "etiology": "ET",
        "genetics": "GE",
        "growth & development": "GD",
        "history": "HI",
        "immunology": "IM",
        "injuries": "IN",
        "innervation": "IR",
        "instrumentation": "IS",
        "isolation & purification": "IP",
        "legislation & jurisprudence": "LJ",
        "metabolism": "ME",
        "methods": "MT",
        "microbiology": "MI",
        "mortality": "MO",
        "nursing": "NU",
        "organization & administration": "OG",
        "parasitology": "PS",
        "pathogenicity": "PY",
        "pathology": "PA",
        "pharmacokinetics": "PK",
        "pharmacology": "PD",
        "physiology": "PH",
        "physiopathology": "PP",
        "poisoning": "PO",
        "prevention & control": "PC",
        "psychology": "PX",
        "radiation effects": "RE",
        "radiotherapy": "RT",
        "rehabilitation": "RH",
        "secondary": "SC",
        "standards": "ST",
        "statistics & numerical data": "SN",
        "supply & distribution": "SD",
        "surgery": "SU",
        "therapeutic use": "TU",
        "therapy": "TH",
        "toxicity": "TO",
        "transmission": "TM",
        "transplantation": "TR",
        "trends": "TD",
        "ultrastructure": "UL",
        "urine": "UR",
        "veterinary": "VE",
        "virology": "VI",
    }
)


def qualifier_form(text: str) -> str:
    """Comparison form of a qualifier: case, ``&``/``and`` and spacing folded (ESummary writes ``and``)."""
    return " ".join(text.casefold().replace("&", " and ").split())


_QUALIFIER_BY_FORM = {qualifier_form(name): name for name in MESH_QUALIFIERS} | {
    abbreviation.casefold(): name for name, abbreviation in MESH_QUALIFIERS.items()
}


def canonical_qualifier(text: str) -> str | None:
    """Full MeSH qualifier name for a written name or two-letter abbreviation; None if it is not one."""
    return _QUALIFIER_BY_FORM.get(qualifier_form(text))


def qualifier_spelling(written: str) -> str:
    """The qualifier as written, or its full name when written as a two-letter abbreviation.

    PubMed resolves abbreviations only in unquoted clauses (live 2026-11-25:
    ``neoplasms/dh[mh]`` finds records, ``"Neoplasms/dh"[mh]`` is not found).
    """
    stripped = written.strip()
    name = canonical_qualifier(stripped)
    if name is not None and stripped.casefold() == MESH_QUALIFIERS[name].casefold():
        return name
    return stripped


def qualifier_allowed(written: str, allowed: Sequence[str]) -> bool | None:
    """Whether MeSH allows the qualifier with a heading; None when the allowed list is unknown (empty)."""
    if not allowed:
        return None
    name = canonical_qualifier(written)
    return name is not None and qualifier_form(name) in {qualifier_form(item) for item in allowed}


def split_qualifier(text: str) -> tuple[str, str | None]:
    """``(heading, qualifier)`` of a MeSH clause text; only a real MeSH subheading is a qualifier.

    ``Ischemia/Reperfusion Injury`` stays one heading because "Reperfusion
    Injury" is not a subheading; ``Neoplasms/dh`` is Neoplasms with the diet
    therapy qualifier. A trailing slash is dropped.
    """
    stripped = text.strip()
    head, slash, tail = stripped.rpartition("/")
    if not slash:
        return stripped, None
    if not tail.strip():
        return head.strip(), None
    if canonical_qualifier(tail) is not None:
        return head.strip(), tail.strip()
    return stripped, None


# MEDLINE check tags: population, sex and organism descriptors added to most records.
CHECK_TAG_DESCRIPTORS = frozenset(
    {
        "Humans",
        "Animals",
        "Male",
        "Female",
        "Pregnancy",
        "Infant, Newborn",
        "Infant",
        "Child, Preschool",
        "Child",
        "Adolescent",
        "Young Adult",
        "Adult",
        "Middle Aged",
        "Aged",
        "Aged, 80 and over",
        "Cats",
        "Cattle",
        "Chick Embryo",
        "Cricetinae",
        "Dogs",
        "Guinea Pigs",
        "Horses",
        "Mice",
        "Rabbits",
        "Rats",
        "Sheep",
        "Swine",
    }
)

# Descriptors about how a study was designed, analysed or reported rather than its topic.
STUDY_DESIGN_DESCRIPTORS = frozenset(
    {
        "Case-Control Studies",
        "Cohort Studies",
        "Cross-Over Studies",
        "Cross-Sectional Studies",
        "Double-Blind Method",
        "Feasibility Studies",
        "Follow-Up Studies",
        "Incidence",
        "Logistic Models",
        "Longitudinal Studies",
        "Multivariate Analysis",
        "Odds Ratio",
        "Pilot Projects",
        "Predictive Value of Tests",
        "Prevalence",
        "Prognosis",
        "Proportional Hazards Models",
        "Prospective Studies",
        "ROC Curve",
        "Random Allocation",
        "Regression Analysis",
        "Reproducibility of Results",
        "Research Design",
        "Retrospective Studies",
        "Risk Assessment",
        "Risk Factors",
        "Sensitivity and Specificity",
        "Single-Blind Method",
        "Surveys and Questionnaires",
        "Time Factors",
        "Treatment Outcome",
    }
)


@dataclass(frozen=True, slots=True)
class TaggedMeshTerm:
    """One MeSH-tagged clause located in a query string."""

    clause: str
    start: int
    end: int
    text: str
    descriptor: str
    qualifier: str | None
    tag: str
    major: bool
    noexp: bool
    quoted: bool

    @property
    def key(self) -> str:
        """Normalized descriptor key shared by spelling, hyphen and plural variants."""
        return term_key(self.descriptor)

    def render(self, descriptor: str, *, keep_qualifier: bool = True, qualifier: str | None = None) -> str:
        """The same clause with another heading, keeping the agent's field tag.

        ``qualifier`` replaces the written qualifier (for example its full
        name instead of an abbreviation); ``keep_qualifier=False`` drops it.
        """
        chosen = (qualifier or self.qualifier) if keep_qualifier else None
        text = f"{descriptor}/{chosen}" if chosen else descriptor
        return f'"{text}"[{self.tag}]'


@dataclass(frozen=True, slots=True)
class FlaggedTerm:
    """A MeSH-tagged clause PubMed (or the vocabulary) could not resolve, with the reason."""

    term: TaggedMeshTerm
    reason: str


@dataclass(frozen=True, slots=True)
class EvidenceSample:
    """A bounded PubMed sample for co-occurrence evidence.

    ``pmids`` are the first ``len(pmids)`` of ``total`` records in ``sort``
    order; they are not a random sample.
    """

    query: str
    total: int
    pmids: tuple[str, ...]
    sort: str
    retrieved_at: str
    diagnostics: PubMedQueryDiagnostics


@dataclass(frozen=True, slots=True)
class DescriptorShare:
    """How many sampled MEDLINE records carry a descriptor."""

    descriptor: str
    records: int
    share: float


@dataclass(frozen=True, slots=True)
class ShareTable:
    """Descriptor shares of one sample after check-tag and study-design exclusion."""

    records_with_mesh: int
    shares: tuple[DescriptorShare, ...]
    excluded: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScoredDescriptor:
    """A co-occurring descriptor: sample share plus exact recall, precision and F1."""

    descriptor: str
    records: int
    share: float
    background_count: int | None = None
    joint_count: int | None = None
    recall: float | None = None
    precision: float | None = None
    score: float | None = None

    def to_dict(self) -> dict[str, object]:
        def rounded(value: float | None) -> float | None:
            return None if value is None else round(value, 3)

        return {
            "descriptor": self.descriptor,
            "records": self.records,
            "share": round(self.share, 3),
            "background_count": self.background_count,
            "joint_count": self.joint_count,
            "recall": rounded(self.recall),
            "precision": rounded(self.precision),
            "score": rounded(self.score),
        }


def _quote_balance_is_even(text: str) -> bool:
    return text.count('"') % 2 == 0


def _bare_term_start(query: str, end: int) -> int | None:
    """Start of the unquoted words that a field tag at ``end`` applies to.

    The words stop at a PubMed operator (``AND``, ``OR``/``or``, ``NOT``/``not``).
    A leading ``and`` (a stopword PubMed glues onto the phrase) or a
    mixed-case ``Not``/``Or`` is not part of the heading: PubMed itself then
    reports the heading words (``... and pacu[mh]`` -> PhraseNotFound
    ``pacu``). An inner ``and`` stays (``Delirium/prevention and control``).
    """
    boundary = max(query.rfind(char, 0, end) for char in _DELIMITERS) + 1
    words: list[re.Match[str]] = []
    for match in reversed(list(_WORD.finditer(query, boundary, end))):
        if boolean_operator(match.group()) is not None:
            break
        words.append(match)
    words.reverse()
    while words and resembles_operator(words[0].group()):
        words.pop(0)
    return words[0].start() if words else None


def find_mesh_terms(query: str) -> tuple[TaggedMeshTerm, ...]:
    """Every MeSH descriptor clause in ``query``, in order.

    Recognizes ``[Mesh]``, ``[MeSH Terms]``, ``[mh]``, ``[Majr]``, ``[MeSH Major
    Topic]`` and their ``:noexp`` forms, quoted or bare, with an optional
    ``/qualifier`` (a real MeSH subheading, see :func:`split_qualifier`). Tags
    inside a quoted phrase are ignored.
    """
    terms: list[TaggedMeshTerm] = []
    for match in _MESH_TAG.finditer(query):
        if not _quote_balance_is_even(query[: match.start()]):
            continue
        end_of_term = match.start()
        while end_of_term > 0 and query[end_of_term - 1].isspace():
            end_of_term -= 1
        if end_of_term > 0 and query[end_of_term - 1] == '"':
            opening = query.rfind('"', 0, end_of_term - 1)
            if opening < 0:
                continue
            start, text, quoted = opening, query[opening + 1 : end_of_term - 1], True
        else:
            bare_start = _bare_term_start(query, end_of_term)
            if bare_start is None:
                continue
            start, text, quoted = bare_start, query[bare_start:end_of_term], False
        descriptor, qualifier = split_qualifier(text)
        if not descriptor:
            continue
        tag = " ".join(match.group(0)[1:-1].split())
        field_name = " ".join(match.group("field").lower().split())
        terms.append(
            TaggedMeshTerm(
                clause=query[start : match.end()],
                start=start,
                end=match.end(),
                text=text.strip(),
                descriptor=descriptor,
                qualifier=qualifier,
                tag=tag.replace(" :", ":").replace(": ", ":"),
                major=field_name in {"majr", "mesh major topic"},
                noexp=match.group("noexp") is not None,
                quoted=quoted,
            )
        )
    return tuple(terms)


def _clause_key(clause: str) -> str:
    collapsed = " ".join(clause.casefold().split())
    return re.sub(r"\s*([\[\]:])\s*", r"\1", collapsed)


def flag_unresolved_terms(terms: Sequence[TaggedMeshTerm], diagnostics: PubMedQueryDiagnostics) -> list[FlaggedTerm]:
    """Terms PubMed reported as not found, each with the NCBI list entry as its reason.

    Quoted clauses are matched against ``QuotedPhraseNotFound`` (which echoes
    the clause with its tag); bare clauses against ``PhraseNotFound`` (which
    names the term, or for unquoted multi-word input, the word PubMed tried).
    """
    quoted = {_clause_key(entry): entry for entry in diagnostics.quoted_phrases_not_found}
    missing = {" ".join(entry.casefold().split()): entry for entry in diagnostics.phrases_not_found}
    flagged: list[FlaggedTerm] = []
    for term in terms:
        if term.quoted:
            entry = quoted.get(_clause_key(term.clause))
            if entry is not None:
                flagged.append(FlaggedTerm(term, f"NCBI WarningList.QuotedPhraseNotFound: {entry}"))
            continue
        candidates = [" ".join(term.text.casefold().split()), *(word.casefold() for word in term.text.split())]
        hit = next((missing[key] for key in candidates if key in missing), None)
        if hit is not None:
            flagged.append(FlaggedTerm(term, f"NCBI ErrorList.PhraseNotFound: {hit}"))
    return flagged


def not_found_clauses(text: str, diagnostics: PubMedQueryDiagnostics) -> list[str]:
    """NCBI not-found entries that occur in ``text`` (any field, not only MeSH).

    A quoted entry matches when its normalized clause occurs in the text; a
    bare ``PhraseNotFound`` word matches only directly before a field tag
    (``PACU[mh]``), so an ordinary text word is not misattributed.
    """
    key = _clause_key(text)
    found = [entry for entry in diagnostics.quoted_phrases_not_found if _clause_key(entry) in key]
    found.extend(
        word
        for word in diagnostics.phrases_not_found
        if re.search(rf"(?<![\w-]){re.escape(word)}\s*\[", text, re.IGNORECASE)
    )
    return list(dict.fromkeys(found))


def normalize_heading(raw: str) -> str:
    """Descriptor name of a MEDLINE ``MH`` value (``*Recovery Room/statistics`` -> ``Recovery Room``)."""
    return raw.split("/", 1)[0].strip().lstrip("*").strip()


def exclusion_reason(descriptor: str) -> ExclusionReason | None:
    """Why a descriptor cannot stand for a topic concept, or None if it can."""
    if descriptor in CHECK_TAG_DESCRIPTORS or (descriptor.startswith("History, ") and descriptor.endswith("Century")):
        return "check_tag"
    if descriptor in STUDY_DESIGN_DESCRIPTORS or descriptor.endswith(" as Topic"):
        return "study_design"
    return None


def descriptor_shares(headings_by_record: Mapping[str, Sequence[str]]) -> ShareTable:
    """Share of indexed records carrying each descriptor; records without MeSH are not counted."""
    counts: Counter[str] = Counter()
    excluded: dict[str, set[str]] = {"check_tag": set(), "study_design": set()}
    records_with_mesh = 0
    for headings in headings_by_record.values():
        names = {name for raw in headings if (name := normalize_heading(raw))}
        if not names:
            continue
        records_with_mesh += 1
        for name in names:
            reason = exclusion_reason(name)
            if reason is None:
                counts[name] += 1
            else:
                excluded[reason].add(name)
    shares = tuple(
        DescriptorShare(name, count, count / records_with_mesh)
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )
    return ShareTable(records_with_mesh, shares, {reason: len(names) for reason, names in excluded.items()})


def descriptor_clause(descriptor: str) -> str:
    """PubMed clause for records indexed with the descriptor itself (no explosion)."""
    if '"' in descriptor:
        raise ValueError("Descriptor names cannot contain quotes")
    return f'"{descriptor}"[mh:noexp]'


def joint_query(evidence: str, descriptor: str) -> str:
    """Evidence records that are also indexed with the descriptor."""
    return f"{evidence} AND {descriptor_clause(descriptor)}"


def score_descriptor(
    share: DescriptorShare, *, evidence_total: int, background_count: int, joint_count: int
) -> ScoredDescriptor:
    """Exact recall, precision and F1 of using the heading for the words' literature.

    ``recall = joint / evidence_total`` and ``precision = joint / background``
    are PubMed counts at retrieval time, not sample estimates; ``share``
    (which nominated the heading) is kept for disclosure.
    """
    if background_count <= 0 or evidence_total <= 0 or joint_count < 0:
        return ScoredDescriptor(share.descriptor, share.records, share.share, background_count, joint_count)
    joint = min(joint_count, background_count, evidence_total)
    recall = joint / evidence_total
    precision = joint / background_count
    score = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return ScoredDescriptor(
        share.descriptor, share.records, share.share, background_count, joint_count, recall, precision, score
    )


def rank_descriptors(scored: Iterable[ScoredDescriptor]) -> list[ScoredDescriptor]:
    """Scored descriptors by F1 (then share, then name); unscored ones last by share."""
    return sorted(
        scored,
        key=lambda item: (item.score is None, -(item.score or 0.0), -item.share, item.descriptor),
    )


def cooccurrence_confidence(
    best: ScoredDescriptor, *, records_with_mesh: int, medium_score: float, medium_records: int
) -> Confidence:
    """A related heading is never "high"; "medium" needs a strong F1 on a sizable sample."""
    if best.score is not None and best.score >= medium_score and records_with_mesh >= medium_records:
        return "medium"
    return "low"


def _closed_compound(text: str) -> str:
    """Join hyphenated words with the joined parts lowercased: Post-Anesthesia -> Postanesthesia."""
    return " ".join(
        parts[0] + "".join(part.lower() for part in parts[1:]) if len(parts := token.split("-")) > 1 else token
        for token in text.split()
    )


def pubmed_text_key(text: str) -> str:
    """Key under which PubMed's phrase index treats two text words as the same.

    PubMed searches ``post-anesthesia`` and ``post anesthesia`` identically
    (its translation shows both as ``"post anesthesia ..."[Title/Abstract]``)
    and ignores case, so hyphens and spaces are folded together.
    """
    return " ".join(re.split(r"[\s\-]+", text.casefold())).strip()


def text_word_variants(phrase: str, limit: int = MAX_TEXT_WORD_VARIANTS) -> tuple[str, ...]:
    """Distinct text-word forms of a phrase: as written, hyphen-closed, each with the plural toggled.

    Forms PubMed treats as identical (hyphen vs. space, case) are emitted
    once, and closed compounds use a canonical casing (``Postanesthesia``,
    never ``PostAnesthesia``).
    """
    cleaned = " ".join(phrase.replace('"', " ").split())
    if not cleaned:
        return ()
    canonical: dict[str, str] = {}
    if "-" in cleaned or "/" in cleaned:
        closed = _closed_compound(cleaned.replace("/", "-"))
        canonical = {variant.casefold(): variant for variant in lookup_variants(closed)}
    variants: dict[str, str] = {}
    for raw in lookup_variants(cleaned):
        variant = canonical.get(raw.casefold(), raw)
        variants.setdefault(pubmed_text_key(variant), variant)
    return tuple(variants.values())[:limit]


def text_word_clauses(variants: Sequence[str], field_tag: str = TEXT_WORD_FIELD) -> list[str]:
    """One quoted ``[tiab]`` clause per variant."""
    return [f'"{variant}"[{field_tag}]' for variant in variants]


def text_word_block(variants: Sequence[str], field_tag: str = TEXT_WORD_FIELD) -> str:
    """``"a"[tiab]`` or ``("a"[tiab] OR "b"[tiab])``; empty when there are no variants."""
    clauses = text_word_clauses(variants, field_tag)
    if len(clauses) <= 1:
        return clauses[0] if clauses else ""
    return or_block(*clauses)


def evidence_query(variants: Sequence[str]) -> str:
    """MEDLINE-indexed records using any variant in title/abstract."""
    return f"{text_word_block(variants)} AND {MEDLINE_SUBSET}"


def or_block(*clauses: str) -> str:
    return "(" + " OR ".join(clauses) + ")"


def apply_replacements(query: str, replacements: Sequence[tuple[int, int, str]]) -> str:
    """Replace non-overlapping ``[start, end)`` spans; spans may be given in any order."""
    ordered = sorted(replacements, key=lambda item: item[0])
    for (_, previous_end, _), (start, _, _) in pairwise(ordered):
        if start < previous_end:
            raise ValueError("Replacement spans overlap")
    result = query
    for start, end, text in reversed(ordered):
        result = result[:start] + text + result[end:]
    return result


def fetch_batches(count: int, batch_size: int) -> int:
    """E-utility requests needed to fetch ``count`` records in batches."""
    return math.ceil(count / batch_size) if count > 0 else 0


def phrase_priority(phrases: Sequence[str], limit: int) -> list[str]:
    """Multi-word phrases first (longest first), then single words, each in topic order."""
    indexed = list(enumerate(dict.fromkeys(phrase for phrase in phrases if phrase.strip())))
    indexed.sort(key=lambda item: (-len(item[1].split()), item[0]))
    return [phrase for _, phrase in indexed[:limit]]


__all__ = [
    "CHECK_TAG_DESCRIPTORS",
    "MESH_QUALIFIERS",
    "STUDY_DESIGN_DESCRIPTORS",
    "Confidence",
    "DescriptorShare",
    "EvidenceSample",
    "FlaggedTerm",
    "ScoredDescriptor",
    "ShareTable",
    "TaggedMeshTerm",
    "apply_replacements",
    "canonical_qualifier",
    "cooccurrence_confidence",
    "descriptor_clause",
    "descriptor_shares",
    "evidence_query",
    "exclusion_reason",
    "fetch_batches",
    "find_mesh_terms",
    "flag_unresolved_terms",
    "joint_query",
    "normalize_heading",
    "not_found_clauses",
    "or_block",
    "phrase_priority",
    "pubmed_text_key",
    "qualifier_allowed",
    "qualifier_form",
    "qualifier_spelling",
    "rank_descriptors",
    "score_descriptor",
    "split_qualifier",
    "text_word_block",
    "text_word_clauses",
    "text_word_variants",
]
