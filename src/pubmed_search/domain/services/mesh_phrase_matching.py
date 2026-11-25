"""Deterministic MeSH phrase candidates and exact-term acceptance.

Design:
    Topic text is split into phrase candidates that never start or end with a
    function word or preposition and that keep hyphenated compounds intact.
    Candidates are tried longest first, and a vocabulary record is accepted
    only when the normalized phrase equals its preferred term or one of its
    entry terms. Normalization covers case, punctuation/hyphen spacing and
    simple plurals; it never widens a phrase into a related concept. Anything
    weaker is a candidate for review, not a mapping.

Maintenance:
    Keep this module free of network access and provider payload shapes. NCBI
    adapters translate their responses into ``MeshRecord`` before matching.
    Lookup variants must normalize to the same key as their source phrase so a
    record found through a variant can still be verified by ``match_term``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

MAX_PHRASE_TOKENS = 6
MAX_TOPIC_TOKENS = 48
_MIN_SINGLE_TOKEN_CHARS = 2
# Plural folding only touches alphabetic words longer than this ("gas", "bus" stay intact).
_MIN_PLURAL_CHARS = 4

RecordType = Literal["descriptor", "supplementary_concept", "publication_type"]
MatchedOn = Literal["preferred", "entry_term"]

# Case-sensitive PubMed Boolean operators split a topic into independent segments.
_BOOLEAN_OPERATORS = frozenset({"AND", "OR", "NOT"})

# Words that may occur inside a MeSH term ("Length of Stay", "Head and Neck
# Neoplasms") but never begin or end one.
PHRASE_EDGE_STOPWORDS = frozenset(
    {
        "a",
        "about",
        "across",
        "after",
        "against",
        "among",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "before",
        "between",
        "but",
        "by",
        "during",
        "for",
        "from",
        "in",
        "into",
        "is",
        "its",
        "nor",
        "not",
        "of",
        "on",
        "onto",
        "or",
        "over",
        "per",
        "than",
        "that",
        "the",
        "their",
        "these",
        "this",
        "those",
        "through",
        "to",
        "toward",
        "towards",
        "under",
        "upon",
        "versus",
        "via",
        "vs",
        "was",
        "were",
        "with",
        "within",
        "without",
    }
)

_FIELD_TAG = re.compile(r"\[[^\]]*\]")
_TOKEN = re.compile(r"[^\W_]+(?:['’.\-][^\W_]+)*")
_KEY_TOKEN = re.compile(r"[^\W_]+")
_POSSESSIVE = re.compile(r"'s\b")
_SEARCH_FIELDS: dict[RecordType, str] = {
    "descriptor": "MeSH Terms",
    "supplementary_concept": "Supplementary Concept",
    "publication_type": "Publication Type",
}


@dataclass(frozen=True)
class PhraseCandidate:
    """A contiguous topic phrase identified by its token span."""

    text: str
    start: int
    end: int

    @property
    def size(self) -> int:
        return self.end - self.start

    def overlaps(self, covered: set[int]) -> bool:
        return any(index in covered for index in range(self.start, self.end))


@dataclass(frozen=True)
class TopicPhrases:
    """Topic tokens, their segment membership and longest-first candidates."""

    tokens: tuple[str, ...]
    segment_ids: tuple[int, ...]
    candidates: tuple[PhraseCandidate, ...]
    truncated: bool = False


@dataclass(frozen=True)
class MeshRecord:
    """Vocabulary record reduced to the fields needed for exact matching."""

    uid: str
    preferred: str
    entry_terms: tuple[str, ...] = ()
    tree_numbers: tuple[str, ...] = ()
    record_type: RecordType = "descriptor"

    @property
    def terms(self) -> tuple[str, ...]:
        return (self.preferred, *self.entry_terms)

    @property
    def term_keys(self) -> frozenset[str]:
        return frozenset(term_key(term) for term in self.terms)

    @property
    def search_field(self) -> str:
        return _SEARCH_FIELDS[self.record_type]

    def text_synonyms(self, limit: int) -> list[str]:
        """Entry terms in natural word order first; inverted "Room, Recovery" forms last."""
        ordered = sorted(self.entry_terms, key=lambda term: "," in term)
        return ordered[:limit]


@dataclass(frozen=True)
class TermMatch:
    """Evidence that a phrase equals one term of a record."""

    record: MeshRecord
    matched_on: MatchedOn
    matched_term: str


@dataclass(frozen=True)
class PhraseMapping:
    phrase: PhraseCandidate
    match: TermMatch


@dataclass(frozen=True)
class AmbiguousPhrase:
    phrase: PhraseCandidate
    matches: tuple[TermMatch, ...]


@dataclass(frozen=True)
class MappingSelection:
    """Confirmed mappings, ambiguous exact matches and topic text left unmapped."""

    confirmed: tuple[PhraseMapping, ...]
    ambiguous: tuple[AmbiguousPhrase, ...]
    unmapped: tuple[str, ...]


def _is_edge_word(token: str) -> bool:
    return token.casefold() in PHRASE_EDGE_STOPWORDS


def _has_letter(token: str) -> bool:
    return any(character.isalpha() for character in token)


def _segments(topic: str) -> list[list[str]]:
    """Split on punctuation, quotes, field tags and Boolean operators; keep hyphenated words."""
    text = _FIELD_TAG.sub(" | ", unicodedata.normalize("NFKC", topic))
    segments: list[list[str]] = [[]]
    last_end = 0
    for match in _TOKEN.finditer(text):
        gap = text[last_end : match.start()]
        last_end = match.end()
        token = match.group()
        if (gap.strip() or token in _BOOLEAN_OPERATORS) and segments[-1]:
            segments.append([])
        if token not in _BOOLEAN_OPERATORS:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def parse_topic(
    topic: str,
    *,
    max_phrase_tokens: int = MAX_PHRASE_TOKENS,
    max_topic_tokens: int = MAX_TOPIC_TOKENS,
) -> TopicPhrases:
    """Return stopword-bounded phrase candidates ordered longest first, then left to right."""
    tokens: list[str] = []
    segment_ids: list[int] = []
    truncated = False
    for segment_id, segment in enumerate(_segments(topic)):
        for token in segment:
            if len(tokens) >= max_topic_tokens:
                truncated = True
                break
            tokens.append(token)
            segment_ids.append(segment_id)

    candidates: list[PhraseCandidate] = []
    for start, first in enumerate(tokens):
        if _is_edge_word(first):
            continue
        for end in range(start + 1, min(start + max_phrase_tokens, len(tokens)) + 1):
            if segment_ids[end - 1] != segment_ids[start]:
                break
            span = tokens[start:end]
            if _is_edge_word(span[-1]) or not any(_has_letter(token) for token in span):
                continue
            if len(span) == 1 and len(first) < _MIN_SINGLE_TOKEN_CHARS:
                continue
            candidates.append(PhraseCandidate(" ".join(span), start, end))
    candidates.sort(key=lambda candidate: (-candidate.size, candidate.start))
    return TopicPhrases(tuple(tokens), tuple(segment_ids), tuple(candidates), truncated)


def _singular(token: str) -> str:
    if not token.isalpha() or len(token) < _MIN_PLURAL_CHARS:
        return token
    if token.endswith("ies") and len(token) > _MIN_PLURAL_CHARS:
        return token[:-3] + "y"
    if token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def _key_tokens(text: str) -> tuple[str, ...]:
    folded = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    return tuple(_singular(token) for token in _KEY_TOKEN.findall(_POSSESSIVE.sub("", folded)))


def term_key(text: str) -> str:
    """Comparison key ignoring case, punctuation/hyphen spacing and simple plurals."""
    return "".join(_key_tokens(text))


def contains_phrase(container: str, phrase: str) -> bool:
    """Whether ``phrase`` is a contiguous word sequence of ``container`` under term normalization."""
    outer, inner = _key_tokens(container), _key_tokens(phrase)
    if not inner:
        return False
    return any(outer[index : index + len(inner)] == inner for index in range(len(outer) - len(inner) + 1))


def _toggle_plural(word: str) -> str | None:
    """Inverse of ``_singular`` for the last word, so both forms share one term key."""
    if not word.isalpha() or len(word) < _MIN_PLURAL_CHARS:
        return None
    lower = word.casefold()
    if lower.endswith("ies") and len(word) > _MIN_PLURAL_CHARS:
        return word[:-3] + "y"
    if lower.endswith("s") and not lower.endswith(("ss", "us", "is")):
        return word[:-1]
    if lower.endswith("y") and lower[-2] not in "aeiou":
        return word[:-1] + "ies"
    if lower.endswith(("ss", "us", "is")):
        return None
    return word + "s"


def lookup_variants(phrase: str) -> tuple[str, ...]:
    """Surface forms to search exactly: as written, hyphen spaced/closed, last-word plural toggled."""
    forms = [phrase]
    if "-" in phrase:
        forms.extend([phrase.replace("-", " "), phrase.replace("-", "")])
    variants: list[str] = []
    for form in forms:
        variants.append(form)
        head, _, last = form.rpartition(" ")
        toggled = _toggle_plural(last)
        if toggled:
            variants.append(f"{head} {toggled}" if head else toggled)
    key = term_key(phrase)
    unique: dict[str, str] = {}
    for variant in variants:
        if term_key(variant) == key:
            unique.setdefault(variant.casefold(), variant)
    return tuple(unique.values())


def _exact(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def match_term(phrase: str, record: MeshRecord) -> TermMatch | None:
    """Accept only a preferred-term or entry-term equality; literal equality wins over normalization."""
    terms = record.terms
    literal = _exact(phrase)
    for index, term in enumerate(terms):
        if _exact(term) == literal:
            return TermMatch(record, "preferred" if index == 0 else "entry_term", term)
    key = term_key(phrase)
    if not key:
        return None
    for index, term in enumerate(terms):
        if term_key(term) == key:
            return TermMatch(record, "preferred" if index == 0 else "entry_term", term)
    return None


def resolve_matches(matches: Sequence[TermMatch]) -> TermMatch | None:
    """Return the single defensible match, or None when several records claim the phrase."""
    unique = list({match.record.uid: match for match in matches}.values())
    if len(unique) == 1:
        return unique[0]
    preferred = [match for match in unique if match.matched_on == "preferred"]
    if len(preferred) > 1:
        # A pharmacological-action shadow can repeat a descriptor heading.
        preferred = [match for match in preferred if match.record.tree_numbers] or preferred
    return preferred[0] if len(preferred) == 1 else None


def matches_for(phrase: str, records: Iterable[MeshRecord]) -> list[TermMatch]:
    return [match for record in records if (match := match_term(phrase, record)) is not None]


def _unmapped(topic: TopicPhrases, covered: set[int]) -> tuple[str, ...]:
    phrases: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if run and any(_has_letter(token) for token in run):
            phrases.append(" ".join(run))
        run.clear()

    for index, token in enumerate(topic.tokens):
        if index and topic.segment_ids[index] != topic.segment_ids[index - 1]:
            flush()
        if index in covered or _is_edge_word(token):
            flush()
            continue
        run.append(token)
    flush()
    return tuple(dict.fromkeys(phrases))


def select_mappings(topic: TopicPhrases, records_by_key: Mapping[str, Sequence[MeshRecord]]) -> MappingSelection:
    """Greedy longest-first cover: a confirmed or ambiguous phrase hides overlapping shorter ones."""
    covered: set[int] = set()
    confirmed: list[PhraseMapping] = []
    ambiguous: list[AmbiguousPhrase] = []
    for candidate in topic.candidates:
        if candidate.overlaps(covered):
            continue
        matches = matches_for(candidate.text, records_by_key.get(term_key(candidate.text), ()))
        if not matches:
            continue
        chosen = resolve_matches(matches)
        if chosen is None:
            unique = tuple({match.record.uid: match for match in matches}.values())
            ambiguous.append(AmbiguousPhrase(candidate, unique))
        else:
            confirmed.append(PhraseMapping(candidate, chosen))
        covered.update(range(candidate.start, candidate.end))
    confirmed.sort(key=lambda mapping: mapping.phrase.start)
    ambiguous.sort(key=lambda item: item.phrase.start)
    return MappingSelection(tuple(confirmed), tuple(ambiguous), _unmapped(topic, covered))
