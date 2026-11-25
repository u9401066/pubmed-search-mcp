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
    r"regist|trial\s+(?:number|id)|funding|prospero|clinicaltrials|conflicts?\s+of|disclosure|"
    r"level\s+of\s+evidence|keywords?",
    re.IGNORECASE,
)
_BOILERPLATE_SENTENCE = re.compile(
    r"^\W*(?:trial\s+registration|registration|clinicaltrials\.gov|prospero|copyright|©|\(c\)\s|"
    r"all\s+rights\s+reserved|level\s+of\s+evidence|funding|this\s+article\s+is\s+protected)",
    re.IGNORECASE,
)
_CUE_SENTENCE = re.compile(
    r"^\W*(?:in\s+conclusion|to\s+conclude|we\s+conclude|in\s+summary|overall|taken\s+together|collectively|"
    r"these\s+(?:results|findings|data)|our\s+(?:results|findings|data)|"
    r"this\s+study\s+(?:shows|showed|demonstrates|demonstrated|suggests|suggested|indicates|indicated|found))\b",
    re.IGNORECASE,
)
# A boundary is terminal punctuation, optional closing quotes/brackets, then
# whitespace before something that can start a sentence.
_BOUNDARY = re.compile(r"[.!?][\"'”’)\]]*(?=\s+[A-Z0-9(\[\"'“‘])")
_ABBREVIATIONS = frozenset(
    {
        "approx",
        "ca",
        "cf",
        "co",
        "dept",
        "dr",
        "e.g",
        "eq",
        "est",
        "et al",
        "fig",
        "figs",
        "i.e",
        "inc",
        "incl",
        "jr",
        "ltd",
        "mr",
        "mrs",
        "ms",
        "no",
        "nos",
        "pp",
        "prof",
        "ref",
        "resp",
        "sr",
        "st",
        "u.k",
        "u.s",
        "univ",
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
        punctuation = match.start()
        preceding = text[cursor:punctuation].rsplit(maxsplit=1)
        token = preceding[-1].casefold() if preceding else ""
        if text[punctuation] == "." and (
            token.rstrip(".") in _ABBREVIATIONS
            or text[max(cursor, punctuation - 6) : punctuation].casefold().endswith("et al")
            or (len(token) == 1 and token.isalpha())
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


def _usable(text: str, span: tuple[int, int], *, minimum: int = _MIN_SENTENCE_CHARS) -> bool:
    sentence = text[span[0] : span[1]]
    return len(sentence) >= minimum and not _BOILERPLATE_SENTENCE.search(sentence)


def _highlight(
    abstract: str,
    span: tuple[int, int],
    rule: str,
    section: dict[str, Any] | None = None,
) -> ExtractiveHighlight:
    return ExtractiveHighlight(
        text=abstract[span[0] : span[1]],
        char_start=span[0],
        char_end=span[1],
        selection_rule=rule,
        section_label=_label(section) or None if section else None,
        section_category=_category(section) or None if section else None,
    )


def select_extractive_highlight(abstract: Any, sections: Any = None) -> ExtractiveHighlight | None:
    """Choose one conclusion-bearing sentence from an abstract.

    Preference order:

    1. the first substantive sentence of a structured CONCLUSIONS section
       (label or NLM category, e.g. ``CONCLUSIONS AND RELEVANCE``);
    2. the last sentence of a RESULTS section;
    3. in unstructured text, the last sentence opening with a conclusion cue
       (``In conclusion``, ``These findings``...);
    4. the final substantive sentence of the abstract.

    Registration, funding and copyright boilerplate is never quoted.

    Returns:
        The highlight, or ``None`` when there is no usable abstract text.
    """
    if not isinstance(abstract, str) or not abstract.strip():
        return None
    structured = _valid_sections(sections, len(abstract))

    for section in structured:
        if not _is_conclusion_section(section):
            continue
        spans = sentence_spans(abstract, section["start"], section["end"])
        chosen = next((span for span in spans if _usable(abstract, span)), None)
        chosen = chosen or next((span for span in spans if _usable(abstract, span, minimum=1)), None)
        if chosen is not None:
            return _highlight(abstract, chosen, "first_sentence_of_conclusions_section", section)

    for section in reversed(structured):
        if not _is_results_section(section):
            continue
        spans = [span for span in sentence_spans(abstract, section["start"], section["end"]) if _usable(abstract, span)]
        if spans:
            return _highlight(abstract, spans[-1], "last_sentence_of_results_section", section)

    spans = [span for span in sentence_spans(abstract) if _usable(abstract, span)]
    cue = next((span for span in reversed(spans) if _CUE_SENTENCE.search(abstract[span[0] : span[1]])), None)
    if cue is not None:
        return _highlight(abstract, cue, "conclusion_cue_sentence")
    if spans:
        return _highlight(abstract, spans[-1], "final_sentence_of_abstract")
    fallback = sentence_spans(abstract)
    return _highlight(abstract, fallback[-1], "final_sentence_of_abstract") if fallback else None


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
        }.get(str(highlight.get("selection_rule")), "abstract")
    )
    return f"{where}, chars {highlight.get('char_start')}-{highlight.get('char_end')}"


__all__ = [
    "HIGHLIGHT_KIND",
    "HIGHLIGHT_SCHEMA_VERSION",
    "ExtractiveHighlight",
    "abstract_digest",
    "highlight_display_text",
    "highlight_locator",
    "select_extractive_highlight",
    "sentence_spans",
    "verify_highlight",
]
