"""Extractive abstract highlights with verifiable character offsets.

A Chronicle highlight quotes one sentence of a paper's own PubMed abstract so a
reader sees what the paper reports, not a template about it. Selection is
deterministic and extractive: the quoted text is always exactly
``abstract[char_start:char_end]`` of the abstract stored on the evidence
article, so any reader can re-locate and verify it. Nothing here paraphrases,
summarizes or interprets the source.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

HIGHLIGHT_SCHEMA_VERSION = "chronicle-extractive-highlight/v1"
HIGHLIGHT_KIND = "extractive_abstract_sentence"

_MIN_SENTENCE_CHARS = 25
_DISPLAY_LIMIT = 320

_CONCLUSION_LABEL = re.compile(r"conclusion|interpretation", re.IGNORECASE)
_CONCLUSION_LABEL_PREFIX = re.compile(
    r"^(?:clinical\s+)?(?:implications?|relevance|significance)\b|^summary\b(?!\s+of)",
    re.IGNORECASE,
)
_RESULTS_LABEL = re.compile(r"result|finding", re.IGNORECASE)
_BOILERPLATE_LABEL = re.compile(
    r"regist|trial\s+(?:number|id)|fund|sponsor|grant|prospero|clinicaltrials|conflicts?\s+of|competing|"
    r"declaration|disclosure|copyright|level\s+of\s+evidence|keywords?|abbreviations?",
    re.IGNORECASE,
)
# Statements about the paper rather than findings of the paper: registration,
# funding, competing interests, licensing and publisher notices. A sentence
# that *opens* with one of these is never quoted as the authors' conclusion.
# Each cue needs its boilerplate context, so findings such as "Registered
# nurses ...", "Funding cuts ..." or "Disclosure of HIV status ..." stay quotable.
_BOILERPLATE_SENTENCE = re.compile(
    r"^\W*(?:"
    r"(?:(?:clinical\s+)?trials?|systematic\s+review|study|protocol|prospero)\s+registration\b|"
    r"registration\s*(?:number|no\b|id\b|details|information|:)|"
    r"(?:prospectively|retrospectively)\s+registered\b|registered\s+(?:at|with|in|on|under|as)\b|"
    r"clinicaltrials\.gov\s*(?:identifier|id\b|number|registration|registry|:|\(|nct)|"
    r"prospero\s*(?:registration|id\b|number|:|\(|crd)|"
    r"(?:this|the)\s+(?:work|study|trial|research|project|review|protocol|authors?)\s+"
    r"(?:was|were|is|are|has\s+been|have\s+been)\s+(?:(?:partly|partially|jointly|financially|in\s+part|"
    r"prospectively|retrospectively)\s+)?(?:funded|sponsored|financed|registered)\b|"
    r"funding\s*(?:[:.]|sources?\b|statement|information|for\s+(?:this|the)\b|was\s+(?:provided|received)|"
    r"(?:and|&)\s+support)|funded\s+by\b|sponsored\s+by\b|(?:grant|financial)\s+support\b|"
    r"sources?\s+of\s+(?:funding|support)|role\s+of\s+the\s+fund|no\s+(?:specific\s+|external\s+)?funding|"
    r"(?:the\s+)?authors?\s+(?:declare|have\s+no|received\s+no|report\s+no|disclose)|"
    r"(?:no\s+)?(?:conflicts?\s+of\s+interests?|competing\s+interests?)\s*(?:[:.]|statement|none|declared?|exist)|"
    r"declarations?\s+of\s+(?:competing\s+)?interests?|(?:financial\s+)?disclosures?\s*(?:[:.]|statement)|"
    r"copyright\b|©|\(c\)\s|crown\s+copyright|all\s+rights\s+reserved|this\s+article\s+is\s+protected|"
    r"published\s+by\b|this\s+is\s+an\s+open[- ]access|licensee\b|"
    r"the\s+authors?(?:\(s\))?\s*,?\s*\d{4}|\d{4}\s+the\s+authors?|psycinfo\b|"
    r"level\s+of\s+evidence|key\s*words?\s*:|abbreviations?\s*:"
    r")",
    re.IGNORECASE,
)
# "Supported by ..." is a funding note only when it names a funder.
_SUPPORT_SENTENCE = re.compile(
    r"^\W*(?:(?:this|the)\s+(?:work|study|trial|research|project|protocol|review|authors?)\s+"
    r"(?:was|were|is|are|has\s+been|have\s+been)\s+(?:(?:partly|partially|jointly|financially|in\s+part)\s+)?)?"
    r"supported\s+(?:in\s+part\s+)?by\b",
    re.IGNORECASE,
)
_FUNDER = re.compile(
    r"\b(?:grants?|fund(?:s|ing|ed)?|foundation|institutes?|council|ministry|agency|trust|award|fellowship|"
    r"scholarship|sponsor\w*|program(?:me)?|department\s+of|NIH|NIHR|NSF|NSFC)\b",
    re.IGNORECASE,
)
# Registry identifiers and licence/publisher notices mark a sentence as
# boilerplate wherever they occur (for example a parenthetical funding note).
_BOILERPLATE_ANYWHERE = re.compile(
    r"\bNCT\s?\d{8}\b|\bISRCTN\s?\d{6,}|\bChiCTR[-\s]?[A-Z]*\d{6,}|\bACTRN\s?\d{10,}|\bCRD\s?\d{8,}|"
    r"\bEudraCT\b|\bDRKS\s?\d{6,}|\bUMIN\s?\d{6,}|\bjRCT\w*\d{5,}|\bIRCT\s?\d{6,}|\bCTRI/\d{4}|"
    r"\bKCT\s?\d{5,}|\bPACTR\s?\d{6,}|\bTCTR\s?\d{6,}|\bINPLASY\s?\d|"
    r"all\s+rights\s+reserved|©|\bcopyright\s+(?:©|\(c\)|\d{4})|"
    r"\bpublished\s+by\s+(?:elsevier|springer|wiley|john\s+wiley|oxford\s+university|cambridge\s+university|"
    r"bmj|the\s+bmj|taylor\s*(?:&|and)\s*francis|informa|wolters|lippincott|sage|s\.?\s*karger|karger|thieme|"
    r"mdpi|frontiers|ovid)|"
    r"\bwiley\s+periodicals\b|\bpsycinfo\s+database\s+record\b|\bcreative\s+commons\b|\blicensee\b|"
    r"\bunder\s+the\s+(?:terms\s+of\s+the\s+)?cc[- ]by\b|\bcc[- ]by(?:-nc)?(?:-nd)?(?:-sa)?\s+licen[cs]e\b",
    re.IGNORECASE,
)
# "Overall survival..." states an outcome; "Overall, ..." summarizes.
_CUE_SENTENCE = re.compile(
    r"^\W*(?:in\s+conclusion|to\s+conclude|we\s+conclude|in\s+summary|"
    r"overall(?=\s*,|\s+(?:we|our|these|this|the|there|it|in)\b)|taken\s+together|collectively|"
    r"these\s+(?:results|findings|data)|our\s+(?:results|findings|data)|"
    r"this\s+study\s+(?:shows|showed|demonstrates|demonstrated|suggests|suggested|indicates|indicated|found))\b",
    re.IGNORECASE,
)
# Older MEDLINE records end with a source-side truncation notice.
_SOURCE_TRUNCATION_MARKER = re.compile(
    r"\(?\s*abstract\s+truncated(?:\s+at\s+\d+\s+words)?\s*\)?[\s.]*$",
    re.IGNORECASE,
)
TRUNCATION_STORED_LIMIT = "stored_abstract_character_limit"
TRUNCATION_SOURCE_MARKER = "pubmed_truncation_marker"
# A boundary is terminal punctuation, optional closing quotes/brackets, then
# whitespace before something that can start a sentence: an uppercase letter
# (any script), a digit, or an opening bracket, quote or copyright sign.
_BOUNDARY = re.compile(r"[.!?][\"'”’)\]]*(?=\s+(\S))")
_SENTENCE_OPENERS = "([\"'“‘©"
# Opening brackets and quotes glued to an abbreviation, as in "(e.g." or "[i.e.".
_WORD_OPENERS = "([{\"'“‘<"
_ABBREVIATIONS = frozenset(
    {
        "approx",
        "apr",
        "aug",
        "avg",
        "ca",
        "cf",
        "chap",
        "co",
        "dec",
        "dept",
        "dr",
        "e.g",
        "eq",
        "eqs",
        "est",
        "et al",
        "excl",
        "feb",
        "fig",
        "figs",
        "i.e",
        "inc",
        "incl",
        "jan",
        "jr",
        "jul",
        "jun",
        "ltd",
        "mar",
        "max",
        "mr",
        "mrs",
        "ms",
        "no",
        "nos",
        "nov",
        "oct",
        "pp",
        "prof",
        "ref",
        "refs",
        "resp",
        "sect",
        "sep",
        "sept",
        "sp",
        "spp",
        "sr",
        "st",
        "subsp",
        "suppl",
        "u.k",
        "u.s",
        "univ",
        "viz",
        "vol",
        "vs",
    }
)


@dataclass(frozen=True)
class ExtractiveHighlight:
    """One verbatim abstract sentence and where it sits in the abstract."""

    text: str
    char_start: int
    char_end: int
    selection_rule: str
    section_label: str | None = None
    section_category: str | None = None
    truncation_basis: tuple[str, ...] = ()

    @property
    def truncated(self) -> bool:
        """Whether the quoted abstract is known to be incomplete."""
        return bool(self.truncation_basis)

    def to_provenance(self, *, abstract: str, evidence_id: str, pmid: str | None) -> dict[str, Any]:
        """Serialize as durable, self-verifying Chronicle provenance."""
        return {
            "schema_version": HIGHLIGHT_SCHEMA_VERSION,
            "kind": HIGHLIGHT_KIND,
            "verbatim": True,
            "interpretation": "none; verbatim author text from the stored PubMed abstract",
            "evidence_id": evidence_id,
            "pmid": pmid,
            "text": self.text,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "offset_unit": "unicode_code_points",
            "offset_target": "EvidenceArticle.abstract",
            "section_label": self.section_label,
            "section_category": self.section_category,
            "selection_rule": self.selection_rule,
            "abstract_sha256": abstract_digest(abstract),
            "abstract_char_length": len(abstract),
            "abstract_truncated": self.truncated,
            "truncation_basis": list(self.truncation_basis),
        }


def abstract_digest(abstract: str) -> str:
    """Return the SHA-256 digest that pins a highlight to one abstract text."""
    return hashlib.sha256(abstract.encode("utf-8")).hexdigest()


def sentence_spans(text: str, start: int = 0, end: int | None = None) -> list[tuple[int, int]]:
    """Split ``text[start:end]`` into whitespace-trimmed sentence spans.

    Offsets index *text* itself. Common biomedical abbreviations, initials and
    decimals do not end a sentence; an imperfect split still yields a verbatim,
    locatable span.
    """
    stop = len(text) if end is None else min(end, len(text))
    spans: list[tuple[int, int]] = []
    cursor = max(0, start)
    for match in _BOUNDARY.finditer(text, cursor, stop):
        opener = match.group(1)
        if not (opener.isupper() or opener.isdigit() or opener in _SENTENCE_OPENERS):
            continue
        punctuation = match.start()
        preceding = text[cursor:punctuation].rsplit(maxsplit=1)
        word = preceding[-1].lstrip(_WORD_OPENERS) if preceding else ""
        if text[punctuation] == "." and (
            word.casefold().rstrip(".") in _ABBREVIATIONS
            or text[max(cursor, punctuation - 6) : punctuation].casefold().endswith("et al")
            # An initial ("J. Smith"); lowercase single letters are units ("24 h.").
            or (len(word) == 1 and word.isalpha() and word.isupper())
        ):
            continue
        span = _trim(text, cursor, match.end())
        if span is not None:
            spans.append(span)
        cursor = match.end()
    span = _trim(text, cursor, stop)
    if span is not None:
        spans.append(span)
    return spans


def _trim(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if end > start else None


def _valid_sections(sections: Any, length: int) -> list[dict[str, Any]]:
    if not isinstance(sections, list):
        return []
    valid: list[dict[str, Any]] = []
    for row in sections:
        if not isinstance(row, dict):
            return []
        start, end = row.get("start"), row.get("end")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or not 0 <= start <= end <= length
        ):
            return []
        valid.append(row)
    return valid


def _label(section: dict[str, Any]) -> str:
    value = section.get("label")
    return value if isinstance(value, str) else ""


def _category(section: dict[str, Any]) -> str:
    value = section.get("nlm_category")
    return value.upper() if isinstance(value, str) else ""


def _is_boilerplate_section(section: dict[str, Any]) -> bool:
    return bool(_BOILERPLATE_LABEL.search(_label(section)))


def _is_conclusion_section(section: dict[str, Any]) -> bool:
    label = _label(section)
    if _is_boilerplate_section(section):
        return False
    return (
        _category(section) == "CONCLUSIONS"
        or bool(_CONCLUSION_LABEL.search(label))
        or bool(_CONCLUSION_LABEL_PREFIX.search(label))
    )


def _is_results_section(section: dict[str, Any]) -> bool:
    return not _is_boilerplate_section(section) and (
        _category(section) == "RESULTS" or bool(_RESULTS_LABEL.search(_label(section)))
    )


def is_boilerplate_sentence(sentence: str) -> bool:
    """Whether *sentence* is registration, funding, interest or publisher text."""
    return bool(
        _BOILERPLATE_SENTENCE.search(sentence)
        or _BOILERPLATE_ANYWHERE.search(sentence)
        or (_SUPPORT_SENTENCE.search(sentence) and _FUNDER.search(sentence))
    )


def abstract_truncation_basis(abstract: str, *, stored_prefix_truncated: bool = False) -> tuple[str, ...]:
    """Return why *abstract* is known to be incomplete (empty when it is not).

    Args:
        abstract: The abstract text as stored.
        stored_prefix_truncated: Whether the stored text is a prefix of a longer
            retrieved abstract.
    """
    basis: list[str] = []
    if _SOURCE_TRUNCATION_MARKER.search(abstract):
        basis.append(TRUNCATION_SOURCE_MARKER)
    if stored_prefix_truncated:
        basis.append(TRUNCATION_STORED_LIMIT)
    return tuple(basis)


def _quotable_end(abstract: str) -> int:
    """Return where quotable author text ends, before any truncation notice."""
    marker = _SOURCE_TRUNCATION_MARKER.search(abstract)
    return marker.start() if marker else len(abstract)


def _highlight(
    abstract: str,
    span: tuple[int, int],
    rule: str,
    section: dict[str, Any] | None = None,
    truncation_basis: tuple[str, ...] = (),
) -> ExtractiveHighlight:
    return ExtractiveHighlight(
        text=abstract[span[0] : span[1]],
        char_start=span[0],
        char_end=span[1],
        selection_rule=rule,
        section_label=_label(section) or None if section else None,
        section_category=_category(section) or None if section else None,
        truncation_basis=truncation_basis,
    )


def select_extractive_highlight(
    abstract: Any,
    sections: Any = None,
    *,
    truncated: bool = False,
) -> ExtractiveHighlight | None:
    """Choose one conclusion-bearing sentence from an abstract.

    Preference order:

    1. the first substantive sentence of a structured CONCLUSIONS section
       (label or NLM category, e.g. ``CONCLUSIONS AND RELEVANCE``);
    2. the last sentence of a RESULTS section;
    3. in unstructured text, the last sentence opening with a conclusion cue
       (``In conclusion``, ``Overall,``, ``These findings``...);
    4. the final substantive sentence of the abstract.

    Registration, funding, competing-interest, licence and publisher text is
    never quoted. When the abstract is known to be incomplete (a PubMed
    ``ABSTRACT TRUNCATED`` notice, or *truncated* for a stored prefix), the
    notice and the possibly cut final fragment are never quoted either.

    Args:
        abstract: The stored abstract text.
        sections: Structured-section offsets into *abstract*.
        truncated: Whether *abstract* is a prefix of a longer retrieved text.

    Returns:
        The highlight, or ``None`` when there is no quotable author sentence.
    """
    if not isinstance(abstract, str) or not abstract.strip():
        return None
    truncation = abstract_truncation_basis(abstract, stored_prefix_truncated=truncated)
    limit = _quotable_end(abstract)
    every_span = sentence_spans(abstract, 0, limit)
    # The last fragment before a cut may stop mid-sentence.
    cut = every_span[-1][1] if truncation and every_span else None

    def usable(span: tuple[int, int], *, minimum: int = _MIN_SENTENCE_CHARS) -> bool:
        sentence = abstract[span[0] : span[1]]
        return span[1] != cut and len(sentence) >= minimum and not is_boilerplate_sentence(sentence)

    structured = [
        {**section, "end": min(section["end"], limit)}
        for section in _valid_sections(sections, len(abstract))
        if section["start"] < limit
    ]

    for section in structured:
        if not _is_conclusion_section(section):
            continue
        spans = sentence_spans(abstract, section["start"], section["end"])
        chosen = next((span for span in spans if usable(span)), None)
        chosen = chosen or next((span for span in spans if usable(span, minimum=1)), None)
        if chosen is not None:
            return _highlight(abstract, chosen, "first_sentence_of_conclusions_section", section, truncation)

    for section in reversed(structured):
        if not _is_results_section(section):
            continue
        spans = [span for span in sentence_spans(abstract, section["start"], section["end"]) if usable(span)]
        if spans:
            return _highlight(abstract, spans[-1], "last_sentence_of_results_section", section, truncation)

    final_rule = "last_complete_sentence_before_truncation" if truncation else "final_sentence_of_abstract"
    spans = [span for span in every_span if usable(span)]
    cue = next((span for span in reversed(spans) if _CUE_SENTENCE.search(abstract[span[0] : span[1]])), None)
    if cue is not None:
        return _highlight(abstract, cue, "conclusion_cue_sentence", truncation_basis=truncation)
    if spans:
        return _highlight(abstract, spans[-1], final_rule, truncation_basis=truncation)
    fallback = [span for span in every_span if usable(span, minimum=1)]
    return _highlight(abstract, fallback[-1], final_rule, truncation_basis=truncation) if fallback else None


def verify_highlight(highlight: Any, abstract: Any) -> list[str]:
    """Return integrity problems for one stored highlight (empty when valid)."""
    if not isinstance(highlight, dict):
        return ["highlight is not an object"]
    if not isinstance(abstract, str):
        return ["evidence article has no stored abstract"]
    problems: list[str] = []
    start, end, text = highlight.get("char_start"), highlight.get("char_end"), highlight.get("text")
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
        or not 0 <= start < end <= len(abstract)
    ):
        problems.append("character offsets are outside the stored abstract")
    elif abstract[start:end] != text:
        problems.append("quoted text does not match the stored abstract at its offsets")
    if highlight.get("abstract_sha256") != abstract_digest(abstract):
        problems.append("abstract digest does not match the stored abstract")
    if highlight.get("abstract_char_length") != len(abstract):
        problems.append("abstract length does not match the stored abstract")
    return problems


def highlight_display_text(highlight: dict[str, Any], *, limit: int = _DISPLAY_LIMIT) -> str:
    """Return the quote on one line, visibly truncated when it is long."""
    text = " ".join(str(highlight.get("text") or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def highlight_locator(highlight: dict[str, Any]) -> str:
    """Return a compact locator such as ``CONCLUSIONS, chars 1513-1570``."""
    section = highlight.get("section_label") or highlight.get("section_category")
    where = (
        str(section)
        if section
        else {
            "conclusion_cue_sentence": "conclusion cue sentence",
            "final_sentence_of_abstract": "final sentence",
            "last_complete_sentence_before_truncation": "last complete sentence before truncation",
        }.get(str(highlight.get("selection_rule")), "abstract")
    )
    return f"{where}, chars {highlight.get('char_start')}-{highlight.get('char_end')}"


__all__ = [
    "HIGHLIGHT_KIND",
    "HIGHLIGHT_SCHEMA_VERSION",
    "TRUNCATION_SOURCE_MARKER",
    "TRUNCATION_STORED_LIMIT",
    "ExtractiveHighlight",
    "abstract_digest",
    "abstract_truncation_basis",
    "highlight_display_text",
    "highlight_locator",
    "is_boilerplate_sentence",
    "select_extractive_highlight",
    "sentence_spans",
    "verify_highlight",
]
