"""Plain-text bibliographic parsing for reference-list verification.

The parser is heuristic but position-aware. The publication year is taken from
the citation locator (``Journal. 2019 Feb 5;321(5):473-483``) instead of the
first four-digit number in the entry, so a year inside a title such as
``...anaesthesia and surgery-2018.`` keeps the title and journal intact.

Supported shapes, in order of preference:
    - Vancouver / AMA: ``Authors. Title. Journal. Year[ Mon[ Day]];Vol(Issue):Pages.``
      including issue-only locators (``2012;(6):CD003843``), e-pages, and
      supplements.
    - Author-year (APA / Harvard): ``Authors (Year). Title. Journal, Vol(Issue), Pages.``
    - A bare trailing year (``Title. Journal. 2024.``) as a last resort.

Identifier text (DOI / PMID) is removed before bibliographic fields are read.
This module performs no I/O.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

from pubmed_search.shared.article_identity import normalize_article_doi

REFERENCE_MARKER_RE = re.compile(r"^\s*(?:\[\d+\]|\d+[.)])\s*")
DOI_RE = re.compile(r"\b(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b", re.IGNORECASE)
PMID_RE = re.compile(r"\bPMID\s*:?\s*([1-9][0-9]{0,19})\b", re.IGNORECASE)

MAX_PARSED_AUTHORS = 12

_YEAR_TOKEN_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_MONTH = (
    r"(?i:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
    r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?|Spring|Summer|Autumn|Fall|Winter)\.?"
)
# Optional disambiguation letter (2018a), then an optional month/season range and day.
_DATE_SUFFIX_RE = re.compile(
    rf"(?:[a-z](?![A-Za-z]))?(?:\s+{_MONTH}(?:\s*[-–/]\s*{_MONTH})?(?:\s+\d{{1,2}}(?:\s*[-–]\s*\d{{1,2}})?)?)?"
)
# A year in citation position is followed by ``;volume``, ``;(issue)`` or ``, volume(``.
_STRONG_TAIL_RE = re.compile(
    r"\s*(?:;\s*(?:[A-Za-z]{0,4}\d|\(|(?i:suppl))|,\s*[A-Za-z]?\d+[A-Za-z]?\s*[(:])",
)
_WEAK_TAIL_RE = re.compile(r"\s*(?:[.;,)]|$)")
_WORD_RE = re.compile(r"[A-Za-z]{3,}")
_PAREN_YEAR_RE = re.compile(
    rf"\(\s*((?:19|20)\d{{2}})[a-z]?(?:\s*,\s*{_MONTH}(?:\s+\d{{1,2}})?)?\s*\)",
)
_PAGE = r"[A-Za-z]{0,4}\d+[A-Za-z]?"
_PAGE_RANGE = rf"{_PAGE}(?:\s*[-–—]\s*{_PAGE})?"
_LOCATOR_RE = re.compile(
    r"\s*[;,]\s*"
    r"(?P<volume>[A-Za-z]?\d+[A-Za-z]?(?:\s+(?i:suppl)\.?(?:\s*\d+[A-Za-z]?)?)?)?"
    r"\s*(?:\((?P<issue>[^()]{1,30})\))?"
    rf"(?:\s*[:,]\s*(?:(?i:pp?)\.\s*)?(?P<pages>{_PAGE_RANGE}))?",
)
_TRAILING_LOCATOR_RE = re.compile(
    r"(?:[,;:]\s*|\s+)(?P<volume>[A-Za-z]?\d+[A-Za-z]?)"
    r"\s*(?:\((?P<issue>[^()]{1,30})\))?"
    rf"\s*[:,]\s*(?:(?i:pp?)\.\s*)?(?P<pages>{_PAGE_RANGE})[\s.]*$",
)
_FIRST_PAGE_RE = re.compile(rf"\s*({_PAGE})")
_SEGMENT_BREAK_RE = re.compile(r"\.\s+|\.(?=[A-Z][a-z])|(?<=[?!])\s+")
_SEGMENT_STRIP = " .;,("
_SEGMENT_LEFT_STRIP = " .;,"
_JOURNAL_NOISE_RE = re.compile(r"\s*\[(?:Internet|serial on the Internet)\]\s*$", re.IGNORECASE)
_INITIALS_ONLY_RE = re.compile(r"^(?:[A-Z]\.?\s*-?\s*){1,4}$")
_ONLINE_MARKER_RE = re.compile(
    r"^(?:published online|epub|online ahead of print|\[epub ahead of print\])", re.IGNORECASE
)
_ET_AL_RE = re.compile(r"\bet\s*al\b\.?", re.IGNORECASE)
_AUTHOR_SPLIT_RE = re.compile(r"\s*(?:[,;&]|\band\b)\s*")
_NON_NAME_CHARS_RE = re.compile(r"[^\w\s'’-]|[\d_]")
_MAX_INITIALS_TOKEN_LENGTH = 4
_MAX_UNDOTTED_INITIALS = 2

CitationStyle = Literal["vancouver", "author_year", "unknown"]


@dataclass(slots=True)
class ParsedReference:
    """Structured fields extracted from one reference entry.

    Attributes:
        index: 1-based position in the provided reference list.
        raw_text: Original reference string as received.
        cleaned_text: Whitespace-normalized reference string without numbering.
        first_author: Parsed first author surname chunk.
        authors: Parsed author surnames in cited order (``et al.`` removed).
        year: Four-digit publication year taken from the citation locator.
        journal: Parsed journal name or abbreviation.
        volume: Parsed volume token.
        issue: Parsed issue token (used for ranking, not for verification).
        first_page: Parsed first page or article-number token.
        title: Parsed article title candidate.
        doi: Normalized DOI if present.
        pmid: Explicit PMID if present in the reference text.
    """

    index: int
    raw_text: str
    cleaned_text: str
    first_author: str = ""
    year: str = ""
    journal: str = ""
    volume: str = ""
    first_page: str = ""
    title: str = ""
    doi: str = ""
    pmid: str = ""
    issue: str = ""
    authors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the parsed reference for JSON output."""
        return {
            "index": self.index,
            "raw_text": self.raw_text,
            "cleaned_text": self.cleaned_text,
            "first_author": self.first_author,
            "authors": list(self.authors),
            "year": self.year,
            "journal": self.journal,
            "volume": self.volume,
            "issue": self.issue,
            "first_page": self.first_page,
            "title": self.title,
            "doi": self.doi,
            "pmid": self.pmid,
        }


@dataclass(frozen=True, slots=True)
class _YearAnchor:
    """Location of the publication year chosen for one reference."""

    year: str
    start: int
    end: int
    style: CitationStyle


@dataclass(frozen=True, slots=True)
class _Locator:
    """Volume / issue / first-page tokens read from a citation tail."""

    volume: str = ""
    issue: str = ""
    first_page: str = ""


def clean_reference_text(reference_text: str) -> str:
    """Normalize whitespace and remove one leading numbering marker."""
    cleaned = REFERENCE_MARKER_RE.sub("", reference_text.strip(), count=1)
    return re.sub(r"\s+", " ", cleaned).strip()


def fold_ascii(value: str) -> str:
    """Remove combining diacritics (``Müller`` -> ``Muller``) without lowercasing."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def first_page_token(pages: object) -> str:
    """Return the first page / article number of a pages string (``1338-44`` -> ``1338``)."""
    match = _FIRST_PAGE_RE.match(str(pages or ""))
    return match.group(1) if match else ""


def parse_reference_text(reference_text: str, *, index: int) -> ParsedReference:
    """Extract verification fields from one already-validated reference entry."""
    cleaned = clean_reference_text(reference_text)
    doi_match = DOI_RE.search(cleaned)
    pmid_match = PMID_RE.search(cleaned)
    # Identifier text is not bibliographic author, journal, or date evidence.
    bibliography = PMID_RE.sub("", DOI_RE.sub("", cleaned)).strip(" .;")

    anchor = _locate_publication_year(bibliography)
    if anchor is None:
        authors_text, title, journal, locator = _parse_without_year(bibliography)
        year = ""
    elif anchor.style == "author_year":
        authors_text, title, journal, locator = _parse_author_year(bibliography, anchor)
        year = anchor.year
    else:
        authors_text, title, journal, locator = _parse_vancouver(bibliography, anchor)
        year = anchor.year

    authors = parse_author_surnames(authors_text)
    return ParsedReference(
        index=index,
        raw_text=reference_text,
        cleaned_text=cleaned,
        first_author=authors[0] if authors else "",
        authors=authors,
        year=year,
        journal=journal,
        volume=locator.volume,
        issue=locator.issue,
        first_page=locator.first_page,
        title=title,
        doi=normalize_article_doi(doi_match.group(1)) if doi_match else "",
        pmid=pmid_match.group(1) if pmid_match else "",
    )


def parse_author_surnames(authors_text: str) -> tuple[str, ...]:
    """Return cited author surnames in order, ignoring initials and ``et al.``."""
    text = _ET_AL_RE.sub(" ", authors_text or "")
    surnames: list[str] = []
    for chunk in _AUTHOR_SPLIT_RE.split(text):
        surname = _surname_from_chunk(chunk)
        if surname:
            surnames.append(surname)
        if len(surnames) >= MAX_PARSED_AUTHORS:
            break
    return tuple(surnames)


def _is_initials(text: str) -> bool:
    """Whether a fragment is only author initials (``A``, ``J.A``, ``D. S.``).

    Undotted runs longer than two letters (``JAMA``, ``BMJ``) are journal
    abbreviations, not initials.
    """
    stripped = text.strip()
    if not _INITIALS_ONLY_RE.match(stripped):
        return False
    return "." in stripped or len(re.sub(r"[^A-Za-z]", "", stripped)) <= _MAX_UNDOTTED_INITIALS


def _surname_from_chunk(chunk: str) -> str:
    """Drop trailing initials from one ``Surname AB`` author chunk."""
    stripped = chunk.strip()
    if not stripped or _is_initials(stripped):
        return ""
    tokens = _NON_NAME_CHARS_RE.sub(" ", stripped).split()
    while len(tokens) > 1 and (
        len(tokens[-1]) == 1 or (tokens[-1].isupper() and len(tokens[-1]) <= _MAX_INITIALS_TOKEN_LENGTH)
    ):
        tokens.pop()
    return " ".join(tokens).strip(" '’-")


def _locate_publication_year(bibliography: str) -> _YearAnchor | None:
    """Choose the year in citation position rather than the first year in the text."""
    # 1. Vancouver/AMA: the first year directly followed by ``;volume`` / ``;(issue)``.
    for match in _YEAR_TOKEN_RE.finditer(bibliography):
        date = _DATE_SUFFIX_RE.match(bibliography, match.end())
        date_end = date.end() if date else match.end()
        if _STRONG_TAIL_RE.match(bibliography, date_end):
            return _YearAnchor(match.group(1), match.start(), date_end, "vancouver")

    # Every check below is O(1) per candidate year (no prefix/suffix slicing),
    # so an adversarial 4,000-character entry stays linear.
    last_word_start = _last_word_start(bibliography)

    # 2. Author-year: ``Authors (2018). Title. Journal, 121(5), 1005-1012.``
    for match in _PAREN_YEAR_RE.finditer(bibliography):
        if last_word_start >= match.end():
            return _YearAnchor(match.group(1), match.start(), match.end(), "author_year")

    # 3. A standalone year that opens a segment (``cohort. 2024.``) or ends the
    #    entry (``Lancet 2015``); prefer the last one, which follows the title
    #    in every common style. Years inside title prose (``1990 to 2010``) or
    #    glued to a hyphen (``surgery-2018``) are not publication dates.
    content_end = len(bibliography.rstrip(" .;,)"))
    weak: _YearAnchor | None = None
    for match in _YEAR_TOKEN_RE.finditer(bibliography):
        start = match.start()
        date = _DATE_SUFFIX_RE.match(bibliography, match.end())
        date_end = date.end() if date else match.end()
        opens_segment = _opens_segment(bibliography, start)
        ends_entry = date_end >= content_end
        glued = start > 0 and bibliography[start - 1] in "-–/"
        if not glued and (opens_segment or ends_entry) and _WEAK_TAIL_RE.match(bibliography, date_end):
            weak = _YearAnchor(match.group(1), start, date_end, "vancouver")
    if weak is None:
        return None
    pre_segments = _segment_spans(bibliography[: weak.start])
    if len(pre_segments) <= 1 and last_word_start >= weak.end:
        return _YearAnchor(weak.year, weak.start, weak.end, "author_year")
    return weak


def _last_word_start(text: str) -> int:
    """Start of the last window of three ASCII letters, or ``-1``.

    ``text[pos:]`` contains a three-letter word iff the result is ``>= pos``.
    """
    last = -1
    for match in _WORD_RE.finditer(text):
        last = match.end() - 3
    return last


def _opens_segment(text: str, start: int) -> bool:
    """Whether ``start`` begins the entry or follows ``.``, ``,``, ``;`` or ``(`` (and spaces)."""
    if start == 0:
        return True
    end = start
    while end > 0 and text[end - 1].isspace():
        end -= 1
    return end > 0 and text[end - 1] in ".,;("


def _parse_vancouver(bibliography: str, anchor: _YearAnchor) -> tuple[str, str, str, _Locator]:
    """Parse ``Authors. Title. Journal. Year;Vol(Issue):Pages`` around the year anchor."""
    pre_year = bibliography[: anchor.start]
    segments = _merge_initials_segments(pre_year, _segment_spans(pre_year))
    while len(segments) > 1 and _ONLINE_MARKER_RE.match(_span_text(pre_year, segments[-1])):
        segments.pop()

    authors_text = _span_text(pre_year, segments[0]) if segments else ""
    journal = _clean_journal(_span_text(pre_year, segments[-1])) if len(segments) >= 2 else ""
    title = pre_year[segments[1][0] : segments[-2][1]].strip() if len(segments) >= 3 else ""

    locator_match = _LOCATOR_RE.match(bibliography, anchor.end)
    locator = _locator_from_match(locator_match) if locator_match else _Locator()
    return authors_text, title, journal, locator


def _parse_author_year(bibliography: str, anchor: _YearAnchor) -> tuple[str, str, str, _Locator]:
    """Parse ``Authors (Year). Title. Journal, Vol(Issue), Pages`` styles."""
    authors_text = bibliography[: anchor.start].strip(_SEGMENT_STRIP)
    body = bibliography[anchor.end :].lstrip(" .,;:)")
    locator_match = _TRAILING_LOCATOR_RE.search(body)
    locator = _locator_from_match(locator_match) if locator_match else _Locator()
    if locator_match:
        body = body[: locator_match.start()]

    segments = _segment_spans(body)
    if len(segments) >= 2:
        title = body[segments[0][0] : segments[-2][1]].strip()
        journal = _clean_journal(_span_text(body, segments[-1]))
    elif segments:
        title = _span_text(body, segments[0])
        journal = ""
    else:
        title = journal = ""
    return authors_text, title, journal, locator


def _parse_without_year(bibliography: str) -> tuple[str, str, str, _Locator]:
    """Keep the legacy segment split when no publication year can be located."""
    segments = _merge_initials_segments(bibliography, _segment_spans(bibliography))
    authors_text = _span_text(bibliography, segments[0]) if segments else ""
    journal = _clean_journal(_span_text(bibliography, segments[-1])) if len(segments) >= 2 else ""
    title = bibliography[segments[1][0] : segments[-2][1]].strip() if len(segments) >= 3 else ""
    return authors_text, title, journal, _Locator()


def _locator_from_match(match: re.Match[str]) -> _Locator:
    """Convert a locator regex match into normalized tokens."""
    volume = (match.group("volume") or "").strip(" .;")
    issue = (match.group("issue") or "").strip()
    pages = match.group("pages") or ""
    return _Locator(volume=volume, issue=issue, first_page=first_page_token(pages))


def _segment_spans(text: str) -> list[tuple[int, int]]:
    """Split on sentence-like boundaries and return trimmed, non-empty spans."""
    raw_spans: list[tuple[int, int]] = []
    start = 0
    for separator in _SEGMENT_BREAK_RE.finditer(text):
        raw_spans.append((start, separator.start()))
        start = separator.end()
    raw_spans.append((start, len(text)))

    spans: list[tuple[int, int]] = []
    for span_start, span_end in raw_spans:
        segment = text[span_start:span_end]
        left = len(segment) - len(segment.lstrip(_SEGMENT_LEFT_STRIP))
        right = len(segment.rstrip(_SEGMENT_STRIP))
        if right > left:
            spans.append((span_start + left, span_start + right))
    return spans


def _merge_initials_segments(text: str, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Re-attach dotted initials (``Aldrete J. A.``) that split the author block."""
    if not spans:
        return spans
    merged = [spans[0]]
    index = 1
    while index < len(spans) and _is_initials(_span_text(text, spans[index])):
        merged[0] = (merged[0][0], spans[index][1])
        index += 1
    return merged + spans[index:]


def _clean_journal(journal: str) -> str:
    """Drop medium markers such as ``[Internet]`` from a journal segment."""
    return _JOURNAL_NOISE_RE.sub("", journal).lstrip(_SEGMENT_LEFT_STRIP).rstrip(_SEGMENT_STRIP)


def _span_text(text: str, span: tuple[int, int]) -> str:
    """Return one trimmed segment (a leading parenthesis belongs to the text)."""
    return text[span[0] : span[1]].lstrip(_SEGMENT_LEFT_STRIP).rstrip(_SEGMENT_STRIP)
