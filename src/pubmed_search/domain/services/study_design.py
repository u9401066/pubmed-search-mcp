"""Deterministic study-design labels from PubMed indexing.

PubMed ``PublicationType`` values (the MeSH Publication Characteristics
vocabulary) are the primary source. MeSH study-design descriptors such as
``Cohort Studies`` or ``Prospective Studies`` only refine an observational
label or label a record whose publication types carry no design. Title and
abstract text patterns are a disclosed fallback for records PubMed has not yet
indexed with a design; such labels are always marked heuristic. Protocols and
publication notices (errata, retractions, expressions of concern) report no
results, so they are never labelled as the completed design they describe.

The classifier is pure and order-independent with respect to its inputs so the
same record always receives the same label across revisions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

STUDY_DESIGN_SCHEMA_VERSION = "study-design-label/v1"

#: Label basis values, from strongest to weakest.
BASIS_PUBLICATION_TYPE = "pubmed_publication_type"
BASIS_MESH = "mesh_study_design_descriptor"
BASIS_TEXT = "text_pattern_heuristic"
BASIS_NOT_INDEXED = "publication_type_without_design"
BASIS_UNAVAILABLE = "no_indexing_metadata"

INDEXED_BASES = frozenset({BASIS_PUBLICATION_TYPE, BASIS_MESH})

#: Design families used to judge whether a text heuristic contradicts indexing.
FAMILY_TRIAL = "trial"
FAMILY_SYNTHESIS = "evidence_synthesis"
FAMILY_GUIDANCE = "guidance"
FAMILY_OBSERVATIONAL = "observational"
FAMILY_REVIEW = "review"
FAMILY_CASE_REPORT = "case_report"
FAMILY_COMMENTARY = "commentary"
FAMILY_PROTOCOL = "protocol"
FAMILY_NOTICE = "publication_notice"
FAMILY_OTHER = "other"
FAMILY_UNSPECIFIED = "unspecified"

_MAX_TEXT_CHARS = 20_000


@dataclass(frozen=True)
class StudyDesign:
    """One study-design label and the indexing evidence behind it.

    Attributes:
        key: Stable machine key, e.g. ``rct`` or ``observational``.
        label: Human-readable design label.
        family: Coarse design family used for consistency checks.
        basis: Where the label came from (see the ``BASIS_*`` constants).
        matched: Publication types, descriptors, or text phrases that matched.
        qualifiers: Refinements such as ``pragmatic`` or ``prospective``.
        flags: Integrity notices such as ``retracted``.
        indexed_publication_types: Design-relevant PubMed types present on the
            record, kept when a heuristic refines a coarser indexed type.
    """

    key: str
    label: str
    family: str
    basis: str
    matched: tuple[str, ...] = ()
    qualifiers: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    indexed_publication_types: tuple[str, ...] = ()

    @property
    def heuristic(self) -> bool:
        """Whether the label comes from text patterns rather than indexing."""
        return self.basis == BASIS_TEXT

    @property
    def indexed(self) -> bool:
        """Whether PubMed indexing (publication type or MeSH) supports the label."""
        return self.basis in INDEXED_BASES

    @property
    def classified(self) -> bool:
        """Whether any design (indexed or heuristic) was recognized."""
        return self.family != FAMILY_UNSPECIFIED

    @property
    def display_label(self) -> str:
        """Return the label with qualifiers, integrity flags and heuristic marker."""
        label = self.label
        if self.qualifiers:
            label += f" ({', '.join(self.qualifiers)})"
        if "retracted" in self.flags:
            label += " [RETRACTED]"
        if self.heuristic:
            label += " [heuristic]"
        return label

    def to_dict(self) -> dict[str, Any]:
        """Serialize for durable Chronicle provenance."""
        return {
            "schema_version": STUDY_DESIGN_SCHEMA_VERSION,
            "key": self.key,
            "label": self.label,
            "display_label": self.display_label,
            "family": self.family,
            "basis": self.basis,
            "indexed": self.indexed,
            "heuristic": self.heuristic,
            "matched": list(self.matched),
            "qualifiers": list(self.qualifiers),
            "flags": list(self.flags),
            "indexed_publication_types": list(self.indexed_publication_types),
        }


@dataclass(frozen=True)
class _TypeRule:
    key: str
    label: str
    family: str
    publication_types: frozenset[str]


def _types(*values: str) -> frozenset[str]:
    return frozenset(value.casefold() for value in values)


_NOTICE_TYPES = _types("Published Erratum", "Retraction of Publication", "Expression of Concern")
_PROTOCOL_TYPES = _types("Clinical Trial Protocol")

# Precedence matters: the first rule with a matching publication type wins. A
# notice or protocol outranks the design types it carries: an erratum to an RCT
# or a protocol indexed as an RCT reports no trial results.
_PUBLICATION_TYPE_RULES: tuple[_TypeRule, ...] = (
    _TypeRule("notice", "Publication Notice", FAMILY_NOTICE, _NOTICE_TYPES),
    _TypeRule("trial_protocol", "Clinical Trial Protocol", FAMILY_PROTOCOL, _PROTOCOL_TYPES),
    _TypeRule("guideline", "Guideline", FAMILY_GUIDANCE, _types("Practice Guideline", "Guideline")),
    _TypeRule(
        "consensus",
        "Consensus Statement",
        FAMILY_GUIDANCE,
        _types("Consensus Development Conference", "Consensus Development Conference, NIH", "Consensus Statement"),
    ),
    _TypeRule("meta_analysis", "Meta-Analysis", FAMILY_SYNTHESIS, _types("Meta-Analysis", "Network Meta-Analysis")),
    _TypeRule("systematic_review", "Systematic Review", FAMILY_SYNTHESIS, _types("Systematic Review")),
    _TypeRule(
        "rct",
        "Randomized Controlled Trial",
        FAMILY_TRIAL,
        _types("Randomized Controlled Trial", "Randomized Controlled Trial, Veterinary"),
    ),
    _TypeRule(
        "clinical_trial",
        "Clinical Trial",
        FAMILY_TRIAL,
        _types(
            "Clinical Trial",
            "Clinical Trial, Phase I",
            "Clinical Trial, Phase II",
            "Clinical Trial, Phase III",
            "Clinical Trial, Phase IV",
            "Controlled Clinical Trial",
            "Pragmatic Clinical Trial",
            "Adaptive Clinical Trial",
            "Equivalence Trial",
            "Clinical Trial, Veterinary",
        ),
    ),
    _TypeRule(
        "observational",
        "Observational Study",
        FAMILY_OBSERVATIONAL,
        _types("Observational Study", "Observational Study, Veterinary", "Twin Study"),
    ),
    _TypeRule("case_report", "Case Report", FAMILY_CASE_REPORT, _types("Case Reports")),
    _TypeRule("validation_study", "Validation Study", FAMILY_OTHER, _types("Validation Study")),
    _TypeRule("evaluation_study", "Evaluation Study", FAMILY_OTHER, _types("Evaluation Study")),
    _TypeRule("scoping_review", "Scoping Review", FAMILY_REVIEW, _types("Scoping Review")),
    _TypeRule("review", "Review", FAMILY_REVIEW, _types("Review")),
    _TypeRule("comparative_study", "Comparative Study", FAMILY_OTHER, _types("Comparative Study")),
    _TypeRule("multicenter_study", "Multicenter Study", FAMILY_OTHER, _types("Multicenter Study")),
    _TypeRule("editorial", "Editorial", FAMILY_COMMENTARY, _types("Editorial")),
    _TypeRule("comment", "Comment", FAMILY_COMMENTARY, _types("Comment")),
    _TypeRule("letter", "Letter", FAMILY_COMMENTARY, _types("Letter")),
    _TypeRule("news", "News", FAMILY_COMMENTARY, _types("News", "Newspaper Article", "Interview")),
    _TypeRule("preprint", "Preprint", FAMILY_OTHER, _types("Preprint")),
)

_QUALIFIER_TYPES: dict[str, str] = {
    "pragmatic clinical trial": "pragmatic",
    "equivalence trial": "equivalence",
    "adaptive clinical trial": "adaptive",
    "controlled clinical trial": "controlled",
    "clinical trial, phase i": "Phase I",
    "clinical trial, phase ii": "Phase II",
    "clinical trial, phase iii": "Phase III",
    "clinical trial, phase iv": "Phase IV",
    "multicenter study": "multicenter",
    "network meta-analysis": "network",
}
_QUALIFIER_FAMILIES = frozenset({FAMILY_TRIAL, FAMILY_OBSERVATIONAL, FAMILY_SYNTHESIS, FAMILY_PROTOCOL})
#: Trial types a protocol may describe; kept as provenance and qualifiers.
_PROTOCOL_DESIGN_TYPES = _types(
    "Randomized Controlled Trial",
    "Clinical Trial",
    "Clinical Trial, Phase I",
    "Clinical Trial, Phase II",
    "Clinical Trial, Phase III",
    "Clinical Trial, Phase IV",
    "Controlled Clinical Trial",
    "Pragmatic Clinical Trial",
    "Adaptive Clinical Trial",
    "Equivalence Trial",
)

# MeSH design descriptors. "X as Topic" descriptors describe what a paper is
# about (for example a meta-analysis *of* trials) and are never used here.
_MESH_OBSERVATIONAL_QUALIFIERS: dict[str, str] = {
    "cohort studies": "cohort",
    "prospective studies": "prospective",
    "retrospective studies": "retrospective",
    "longitudinal studies": "longitudinal",
    "case-control studies": "case-control",
    "cross-sectional studies": "cross-sectional",
}
_MESH_PILOT = _types("Pilot Projects", "Feasibility Studies")

_FLAG_TYPES: dict[str, str] = {
    "retracted publication": "retracted",
    "expression of concern": "expression_of_concern",
}

_GENERIC_PUBLICATION_TYPES = _types(
    "Journal Article",
    "English Abstract",
    "Research Support, N.I.H., Extramural",
    "Research Support, N.I.H., Intramural",
    "Research Support, Non-U.S. Gov't",
    "Research Support, U.S. Gov't, P.H.S.",
    "Research Support, U.S. Gov't, Non-P.H.S.",
    "Research Support, American Recovery and Reinvestment Act",
    "Research Support, U.S. Gov't",
)


@dataclass(frozen=True)
class _TextRule:
    key: str
    label: str
    family: str
    pattern: re.Pattern[str]
    #: Whether the rule asserts genuine randomization (negations are rejected).
    randomized: bool = False


def _text_rule(key: str, label: str, family: str, pattern: str, *, randomized: bool = False) -> _TextRule:
    return _TextRule(key, label, family, re.compile(pattern, re.IGNORECASE), randomized)


_DASHES = r"[\s\-\u2010-\u2013]?"
_RANDOMIZATION = re.compile(r"randomi[sz]", re.IGNORECASE)
# "non-randomized", "quasi-randomised", "pseudo-randomized", "not randomized".
_NEGATED_RANDOMIZATION_PREFIX = re.compile(rf"(?:\b(?:non|quasi|pseudo){_DASHES}|\bnot\s+)$", re.IGNORECASE)
# Wording that refers to other studies rather than to the paper itself.
_BACKGROUND_CUE = re.compile(
    r"\b(?:previous(?:ly)?|prior|earlier|recent(?:ly)?|past|published|existing|landmark|seminal|"
    r"(?:trials|studies|RCTs)\s+(?:in\s+which|where|that)|we\s+searched)\b",
    re.IGNORECASE,
)


def negated_randomization(text: str, start: int, end: int) -> bool:
    """Whether a randomization word inside ``text[start:end]`` is negated."""
    for match in _RANDOMIZATION.finditer(text, start, end):
        if _NEGATED_RANDOMIZATION_PREFIX.search(text[max(0, match.start() - 8) : match.start()]):
            return True
    return False


def is_background_mention(text: str, start: int, end: int) -> bool:
    """Whether ``text[start:end]`` describes other studies, not the paper itself.

    Only the sentence up to the end of the match is inspected, so "A recent
    meta-analysis suggested..." and "In a previous randomized trial..." are
    background while "We performed a randomized trial of recently extubated
    patients" is not.
    """
    sentence_start = max(text.rfind(mark, 0, start) for mark in (". ", "? ", "! ", "; "))
    window = text[sentence_start + 1 if sentence_start >= 0 else 0 : end]
    return bool(_BACKGROUND_CUE.search(window))


_SR_MA = ("systematic_review_meta_analysis", "Systematic Review & Meta-Analysis", FAMILY_SYNTHESIS)

# Titles state the design deliberately, so they may label an unindexed record
# or refine a coarse "Review" publication type.
_TITLE_RULES: tuple[_TextRule, ...] = (
    # A protocol announces a design; it reports no results. "Protocol-driven"
    # or "protocol-based" care is an intervention, not a protocol paper.
    _text_rule(
        "trial_protocol",
        "Clinical Trial Protocol",
        FAMILY_PROTOCOL,
        r"^\W*(?:study\s+)?protocol\b(?![-‐‑]\w)|\b(?:study|trial)\s+protocol\b(?![-‐‑]\w)"
        r"|\bprotocol\s+(?:for|of)\s+(?:a|an|the)\s+(?:[\w,-]+\s+){0,5}(?:trial|study)\b"
        r"|\brationale\s+and\s+design\b|\bdesign\s+and\s+rationale\b",
    ),
    _text_rule(
        *_SR_MA,
        r"\bsystematic\s+(?:literature\s+)?review\b.{0,80}\bmeta-?\s?analys[ie]s\b"
        r"|\bmeta-?\s?analys[ie]s\b.{0,80}\bsystematic\s+review\b",
    ),
    _text_rule("meta_analysis", "Meta-Analysis", FAMILY_SYNTHESIS, r"\b(?:network\s+)?meta-?\s?analys[ie]s\b"),
    _text_rule("systematic_review", "Systematic Review", FAMILY_SYNTHESIS, r"\bsystematic\s+review\b"),
    _text_rule(
        "quasi_randomized_trial",
        "Quasi-randomized Trial",
        FAMILY_TRIAL,
        rf"\b(?:quasi|pseudo){_DASHES}randomi[sz]ed\b.{{0,60}}\b(?:trial|study)\b",
    ),
    _text_rule(
        "non_randomized_trial",
        "Non-randomized Trial",
        FAMILY_TRIAL,
        rf"\bnon{_DASHES}randomi[sz]ed\b.{{0,60}}\b(?:trial|study)\b",
    ),
    _text_rule(
        "rct",
        "Randomized Controlled Trial",
        FAMILY_TRIAL,
        r"\brandomi[sz]ed\b.{0,60}\btrial\b|\brandomi[sz]ed\s+controlled\b",
        randomized=True,
    ),
    _text_rule(
        "observational",
        "Observational Study",
        FAMILY_OBSERVATIONAL,
        r"\b(?:cohort|observational|case-control|cross-sectional)\s+(?:study|analysis)\b",
    ),
    _text_rule("case_report", "Case Report", FAMILY_CASE_REPORT, r"\bcase\s+report\b"),
    _text_rule(
        "guideline",
        "Guideline",
        FAMILY_GUIDANCE,
        r"\b(?:clinical\s+practice|practice|clinical)\s+guidelines?\b|\bguidelines?\s+(?:for|on)\b"
        r"|\bconsensus\s+(?:statement|recommendations?|guidelines?)\b",
    ),
    _text_rule("scoping_review", "Scoping Review", FAMILY_REVIEW, r"\bscoping\s+review\b"),
    _text_rule("review", "Review", FAMILY_REVIEW, r"\b(?:narrative|literature)\s+review\b|:\s*a\s+review\b"),
)

# Abstract text is noisier: methods sections describe the cited literature as
# well as the study itself, so only self-descriptive phrasings are accepted.
_ABSTRACT_RULES: tuple[_TextRule, ...] = (
    _text_rule(
        *_SR_MA,
        r"\b(?:we\s+(?:performed|conducted)\s+a|this)\s+systematic\s+(?:literature\s+)?review\s+and\s+meta-?\s?analysis\b",
    ),
    _text_rule(
        "rct",
        "Randomized Controlled Trial",
        FAMILY_TRIAL,
        r"\b(?:this|in\s+a|we\s+(?:performed|conducted)\s+a)\s+(?:[\w-]+\s+){0,4}randomi[sz]ed\s+"
        r"(?:[\w-]+\s+){0,3}trial\b"
        r"|\bwere\s+(?:randomly\s+(?:assigned|allocated|divided)|randomi[sz]ed)\s+(?:in)?to\b",
        randomized=True,
    ),
    _text_rule(
        "observational",
        "Observational Study",
        FAMILY_OBSERVATIONAL,
        r"\b(?:this|in\s+a|we\s+(?:performed|conducted)\s+a)\s+(?:[\w-]+\s+){0,3}"
        r"(?:cohort|observational|case-control|cross-sectional)\s+study\b",
    ),
)


def _clean_strings(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return []
    return [" ".join(str(value).split()) for value in values if isinstance(value, str) and value.strip()]


def _mesh_descriptor(value: str) -> str:
    """Strip qualifiers (``Delirium/diagnosis``) and the major-topic marker."""
    return value.split("/", 1)[0].strip().rstrip("*").strip()


def _publication_type_design(publication_types: list[str]) -> StudyDesign | None:
    present = {value.casefold(): value for value in publication_types}
    for rule in _PUBLICATION_TYPE_RULES:
        matched = tuple(sorted(present[key] for key in present if key in rule.publication_types))
        if not matched:
            continue
        key, label = rule.key, rule.label
        if rule.family == FAMILY_SYNTHESIS and rule.key == "meta_analysis" and "systematic review" in present:
            key, label = _SR_MA[0], _SR_MA[1]
            matched = (*matched, present["systematic review"])
        qualifiers: tuple[str, ...] = ()
        if rule.family in _QUALIFIER_FAMILIES:
            qualifiers = tuple(qualifier for type_key, qualifier in _QUALIFIER_TYPES.items() if type_key in present)
        if rule.family == FAMILY_PROTOCOL:
            # Keep the planned design as provenance without claiming its results.
            planned = tuple(sorted(present[key] for key in present if key in _PROTOCOL_DESIGN_TYPES))
            matched = (*matched, *planned)
            if "randomized controlled trial" in present:
                qualifiers = ("randomized", *qualifiers)
        return StudyDesign(
            key=key,
            label=label,
            family=rule.family,
            basis=BASIS_PUBLICATION_TYPE,
            matched=matched,
            qualifiers=qualifiers,
            indexed_publication_types=matched,
        )
    return None


def _observational_mesh_qualifiers(mesh_terms: list[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    descriptors = {_mesh_descriptor(term).casefold(): _mesh_descriptor(term) for term in mesh_terms}
    matched = tuple(descriptors[key] for key in _MESH_OBSERVATIONAL_QUALIFIERS if key in descriptors)
    qualifiers = tuple(value for key, value in _MESH_OBSERVATIONAL_QUALIFIERS.items() if key in descriptors)
    return matched, qualifiers


def _mesh_design(mesh_terms: list[str]) -> StudyDesign | None:
    matched, qualifiers = _observational_mesh_qualifiers(mesh_terms)
    if matched:
        return StudyDesign(
            key="observational",
            label="Observational Study",
            family=FAMILY_OBSERVATIONAL,
            basis=BASIS_MESH,
            matched=matched,
            qualifiers=qualifiers,
        )
    pilot = tuple(
        sorted({_mesh_descriptor(term) for term in mesh_terms if _mesh_descriptor(term).casefold() in _MESH_PILOT})
    )
    if pilot:
        return StudyDesign(
            key="pilot_study",
            label="Pilot or Feasibility Study",
            family=FAMILY_OTHER,
            basis=BASIS_MESH,
            matched=pilot,
        )
    return None


def _text_design(
    rules: tuple[_TextRule, ...],
    text: str,
    *,
    field: str,
    allowed_families: frozenset[str] | None,
    indexed_types: tuple[str, ...],
    self_describing: bool = False,
) -> StudyDesign | None:
    bounded = text[:_MAX_TEXT_CHARS]
    for rule in rules:
        if allowed_families is not None and rule.family not in allowed_families:
            continue
        match = next(
            (
                candidate
                for candidate in rule.pattern.finditer(bounded)
                if not (rule.randomized and negated_randomization(bounded, candidate.start(), candidate.end()))
                and not (self_describing and is_background_mention(bounded, candidate.start(), candidate.end()))
            ),
            None,
        )
        if match:
            return StudyDesign(
                key=rule.key,
                label=rule.label,
                family=rule.family,
                basis=BASIS_TEXT,
                matched=(f"{field}: {' '.join(match.group(0).split())}",),
                indexed_publication_types=indexed_types,
            )
    return None


def classify_study_design(
    publication_types: Any = None,
    mesh_terms: Any = None,
    *,
    title: str | None = None,
    abstract: str | None = None,
) -> StudyDesign:
    """Classify one PubMed record's study design.

    Args:
        publication_types: PubMed ``PublicationType`` values.
        mesh_terms: MeSH descriptors, optionally with ``/qualifier`` suffixes.
        title: Article title, used only as a disclosed heuristic fallback.
        abstract: Abstract text, used only as a disclosed heuristic fallback for
            records without any indexed design.

    Returns:
        A :class:`StudyDesign`; never ``None``.
    """
    types = _clean_strings(publication_types)
    mesh = _clean_strings(mesh_terms)
    flags = tuple(
        sorted({flag for type_key, flag in _FLAG_TYPES.items() if type_key in {value.casefold() for value in types}})
    )

    design = _publication_type_design(types)
    if design is not None and design.family == FAMILY_OBSERVATIONAL:
        matched, qualifiers = _observational_mesh_qualifiers(mesh)
        if qualifiers:
            design = StudyDesign(
                key=design.key,
                label=design.label,
                family=design.family,
                basis=design.basis,
                matched=(*design.matched, *matched),
                qualifiers=tuple(dict.fromkeys((*qualifiers, *design.qualifiers))),
                indexed_publication_types=design.indexed_publication_types,
            )
    if design is not None and design.family == FAMILY_REVIEW and title:
        # PubMed often indexes new systematic reviews as "Review" until full
        # MEDLINE indexing completes; an explicit title may refine that.
        refined = _text_design(
            _TITLE_RULES,
            title,
            field="title",
            allowed_families=frozenset({FAMILY_SYNTHESIS}),
            indexed_types=design.matched,
        )
        design = refined or design
    if design is None:
        design = _mesh_design(mesh)
    if design is None:
        design = _text_design(_TITLE_RULES, title or "", field="title", allowed_families=None, indexed_types=())
    if design is None and abstract:
        design = _text_design(
            _ABSTRACT_RULES,
            abstract,
            field="abstract",
            allowed_families=None,
            indexed_types=(),
            self_describing=True,
        )
    if design is None:
        generic = tuple(value for value in types if value.casefold() in _GENERIC_PUBLICATION_TYPES)
        design = StudyDesign(
            key="unspecified",
            label="Journal Article (design not indexed)" if types else "Unclassified",
            family=FAMILY_UNSPECIFIED,
            basis=BASIS_NOT_INDEXED if types else BASIS_UNAVAILABLE,
            matched=generic,
        )
    if flags:
        design = StudyDesign(
            key=design.key,
            label=design.label,
            family=design.family,
            basis=design.basis,
            matched=design.matched,
            qualifiers=design.qualifiers,
            flags=flags,
            indexed_publication_types=design.indexed_publication_types,
        )
    return design


def indexed_design_family(publication_types: Any = None) -> str | None:
    """Return the design family PubMed publication types state, or ``None``.

    Text heuristics are deliberately ignored: this answers whether indexed
    metadata already states what kind of publication a record is. MeSH
    study-design descriptors are ignored too: indexers add descriptors such as
    ``Prospective Studies`` to trials as well, so they refine a label but are
    not authoritative enough to veto a milestone.
    """
    design = classify_study_design(publication_types)
    return design.family if design.basis == BASIS_PUBLICATION_TYPE else None


__all__ = [
    "BASIS_MESH",
    "BASIS_NOT_INDEXED",
    "BASIS_PUBLICATION_TYPE",
    "BASIS_TEXT",
    "BASIS_UNAVAILABLE",
    "FAMILY_CASE_REPORT",
    "FAMILY_COMMENTARY",
    "FAMILY_GUIDANCE",
    "FAMILY_NOTICE",
    "FAMILY_OBSERVATIONAL",
    "FAMILY_OTHER",
    "FAMILY_PROTOCOL",
    "FAMILY_REVIEW",
    "FAMILY_SYNTHESIS",
    "FAMILY_TRIAL",
    "FAMILY_UNSPECIFIED",
    "INDEXED_BASES",
    "STUDY_DESIGN_SCHEMA_VERSION",
    "StudyDesign",
    "classify_study_design",
    "indexed_design_family",
    "is_background_mention",
    "negated_randomization",
]
