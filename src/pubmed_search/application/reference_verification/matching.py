"""Candidate comparison, ranking, and correction rules for reference verification.

These rules decide whether a PubMed record is the cited work and, if it is,
which cited fields disagree with it. They are deliberately conservative:

- ``verified`` still requires every supplied field to agree (see the service).
- A record found by a search that ignored the cited year is only *accepted* as
  the cited work when its title agrees with the cited title and the first
  author or journal also agree (or, without a cited title, when author,
  journal, volume and first page all agree).
- Field-level corrections are offered only when at least two independent cited
  fields corroborate the record *beyond the lookup key that found it* (the
  PMID, the DOI, the searched title, the searched first author + journal +
  locator, or the journal + year sent to ECitMatch). A title hit that agrees on
  one other field may be a fabricated reference that happens to share words
  with a real paper, so it is returned for manual review without corrections.
- A conflicting cited title means the identifier or locator may point to a
  different work, so no correction is proposed either.

This module performs no I/O.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pubmed_search.shared.article_identity import normalize_article_doi, normalize_article_title

from .parsing import first_page_token

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .parsing import ParsedReference

COMPARED_FIELDS = ("pmid", "doi", "year", "journal", "volume", "first_page", "first_author", "title")
CORRECTABLE_FIELDS = ("year", "volume", "first_page", "journal", "first_author", "title", "doi", "pmid")

TITLE_DICE_THRESHOLD = 0.8
TITLE_CONTAINMENT_THRESHOLD = 0.9
MIN_CONTAINMENT_TOKENS = 5
MIN_IDENTITY_LOCATOR_MATCHES = 3
MIN_CORROBORATING_FIELDS = 2
NEAR_YEAR_TOLERANCE = 1
AMBIGUITY_SCORE_MARGIN = 5.0

_FIELD_WEIGHTS = {
    "pmid": 100.0,
    "doi": 100.0,
    "journal": 30.0,
    "volume": 20.0,
    "first_page": 20.0,
    "first_author": 15.0,
}
_EXACT_YEAR_WEIGHT = 35.0
_NEAR_YEAR_WEIGHT = 20.0
_NEAR_YEAR_PENALTY_PER_YEAR = 5.0
_TITLE_SIMILARITY_WEIGHT = 40.0
_EXACT_TITLE_WEIGHT = 10.0
_AUTHOR_ORDER_WEIGHT = 15.0
_ISSUE_WEIGHT = 5.0
_LOCATOR_FIELDS = ("first_author", "journal", "volume", "first_page")
_EVIDENCE_FIELDS = ("title", "first_author", "journal", "year", "volume", "first_page", "doi", "pmid")
# Fields each resolution strategy matched by construction: they cannot corroborate its own hit.
_LOOKUP_KEY_FIELDS: dict[str, frozenset[str]] = {
    "pmid": frozenset({"pmid"}),
    "doi_search": frozenset({"doi"}),
    "ecitmatch": frozenset({"journal", "year"}),
    "title_search": frozenset({"title"}),
    "metadata_search": frozenset({"first_author", "journal"}),
}
CorrectionBlocker = Literal["title_conflict", "few_locators", "weak_corroboration"]
_IZE_RE = re.compile(r"(?<=[a-z])is(ation|ations|e|ed|es|ing)$")
_TITLE_WORD_RE = re.compile(r"[^\W_]+")


def fold_text(value: object) -> str:
    """Lowercase and strip diacritics so ``Müller`` and ``Muller`` compare equal."""
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in decomposed if not unicodedata.combining(char)).lower()


def normalize_field(value: object) -> str:
    """Normalize free-text bibliographic fields for comparison."""
    normalized = fold_text(value)
    normalized = re.sub(r"[^\w\s]", "", normalized)
    normalized = re.sub(r"\b(et|al)\b", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def title_tokens(title: object) -> list[str]:
    """Tokenize a title into letter/digit runs of any script, folding British/American spelling.

    Non-Latin titles keep their own words (a CJK run is one token), so two
    different Chinese or Cyrillic titles no longer both reduce to ``[]``.
    """
    tokens: list[str] = []
    for word in _TITLE_WORD_RE.findall(fold_text(title)):
        folded = word.replace("ae", "e").replace("oe", "e")
        tokens.append(_IZE_RE.sub(r"iz\1", folded))
    return tokens


def title_similarity(cited: object, candidate: object) -> float:
    """Return the Dice coefficient of the two titles' token multisets."""
    cited_tokens = Counter(title_tokens(cited))
    candidate_tokens = Counter(title_tokens(candidate))
    total = sum(cited_tokens.values()) + sum(candidate_tokens.values())
    if not total:
        return 0.0
    return 2.0 * sum((cited_tokens & candidate_tokens).values()) / total


def is_strong_title_match(cited: object, candidate: object) -> bool:
    """Accept near-identical titles, or a long cited title fully contained in the record title."""
    cited_tokens = Counter(title_tokens(cited))
    candidate_tokens = Counter(title_tokens(candidate))
    cited_count = sum(cited_tokens.values())
    if not cited_count or not candidate_tokens:
        return False
    if title_similarity(cited, candidate) >= TITLE_DICE_THRESHOLD:
        return True
    containment = sum((cited_tokens & candidate_tokens).values()) / cited_count
    return cited_count >= MIN_CONTAINMENT_TOKENS and containment >= TITLE_CONTAINMENT_THRESHOLD


def article_surnames(article: dict[str, Any]) -> list[str]:
    """Return PubMed author surnames (or collective names) in record order."""
    authors_full = article.get("authors_full") or []
    if isinstance(authors_full, list) and authors_full:
        names: list[str] = []
        for author in authors_full:
            if not isinstance(author, dict):
                continue
            name = author.get("last_name") or author.get("collective_name") or ""
            if isinstance(name, str) and name:
                names.append(name)
        if names:
            return names
    authors = article.get("authors") or []
    if not isinstance(authors, list):
        return []
    return [str(author).split(" ", 1)[0] for author in authors if str(author).strip()]


def article_first_author(article: dict[str, Any]) -> str:
    """Return the first author surname from a fetched article payload."""
    surnames = article_surnames(article)
    return surnames[0] if surnames else ""


def author_order_agreement(cited_authors: Sequence[str], article: dict[str, Any]) -> float:
    """Fraction of cited authors found at the same position in the PubMed author list."""
    if not cited_authors:
        return 0.0
    record = [normalize_field(name) for name in article_surnames(article)]
    hits = sum(
        1
        for position, name in enumerate(cited_authors)
        if position < len(record) and normalize_field(name) == record[position]
    )
    return hits / len(cited_authors)


def build_comparison(parsed: ParsedReference, article: dict[str, Any] | None) -> dict[str, bool | None]:
    """Build field-level comparison evidence for a candidate article."""
    if article is None:
        return {field: (False if getattr(parsed, field) else None) for field in COMPARED_FIELDS}

    comparisons: dict[str, bool | None] = dict.fromkeys(COMPARED_FIELDS)
    if parsed.pmid:
        comparisons["pmid"] = parsed.pmid == str(article.get("pmid", ""))
    if parsed.doi:
        comparisons["doi"] = parsed.doi == normalize_article_doi(article.get("doi", ""))
    if parsed.year:
        comparisons["year"] = parsed.year == str(article.get("year", ""))
    if parsed.journal:
        normalized_journal = normalize_field(parsed.journal)
        comparisons["journal"] = any(
            normalized_journal and normalized_journal == normalize_field(candidate)
            for candidate in (article.get("journal", ""), article.get("journal_abbrev", ""))
        )
    if parsed.volume:
        comparisons["volume"] = normalize_field(parsed.volume) == normalize_field(article.get("volume", ""))
    if parsed.first_page:
        comparisons["first_page"] = normalize_field(parsed.first_page) == normalize_field(
            first_page_token(article.get("pages", ""))
        )
    if parsed.first_author:
        comparisons["first_author"] = normalize_field(parsed.first_author) == normalize_field(
            article_first_author(article)
        )
    if parsed.title:
        # Same words in the same order; punctuation, hyphenation, diacritics and
        # British/American spelling are not citation errors.
        cited_title = normalize_article_title(fold_text(parsed.title))
        record_title = article.get("title", "")
        cited_tokens = title_tokens(parsed.title)
        comparisons["title"] = cited_title == normalize_article_title(fold_text(record_title)) or (
            bool(cited_tokens) and cited_tokens == title_tokens(record_title)
        )
    return comparisons


def score_candidate(parsed: ParsedReference, article: dict[str, Any], comparison: dict[str, bool | None]) -> float:
    """Rank one candidate; a mis-cited year still earns credit for being close."""
    score = sum(weight for field, weight in _FIELD_WEIGHTS.items() if comparison.get(field) is True)
    if parsed.title:
        score += _TITLE_SIMILARITY_WEIGHT * title_similarity(parsed.title, article.get("title", ""))
        if comparison.get("title") is True:
            score += _EXACT_TITLE_WEIGHT
    year_gap = _year_gap(parsed.year, article.get("year", ""))
    if year_gap == 0:
        score += _EXACT_YEAR_WEIGHT
    elif year_gap is not None:
        score += max(0.0, _NEAR_YEAR_WEIGHT - _NEAR_YEAR_PENALTY_PER_YEAR * year_gap)
    if len(parsed.authors) > 1:
        score += _AUTHOR_ORDER_WEIGHT * author_order_agreement(parsed.authors, article)
    if parsed.issue and normalize_field(parsed.issue) == normalize_field(article.get("issue", "")):
        score += _ISSUE_WEIGHT
    return score


def search_candidate_rejection(
    parsed: ParsedReference,
    article: dict[str, Any],
    comparison: dict[str, bool | None],
) -> str | None:
    """Return why a year-tolerant search hit is not the cited work, or ``None`` to accept it."""
    if parsed.title:
        if not is_strong_title_match(parsed.title, article.get("title", "")):
            return "its title does not match the cited title"
        if comparison.get("first_author") is False and comparison.get("journal") is False:
            return "the title matches but both the first author and the journal differ"
        return None
    if all(comparison.get(field) is True for field in _LOCATOR_FIELDS):
        return None
    return "the cited first author, journal, volume and first page do not all agree"


@dataclass(frozen=True, slots=True)
class IdentityEvidence:
    """Cited fields that agree or conflict with a record, excluding the lookup key that found it.

    Attributes:
        lookup_fields: Fields the resolution strategy matched by construction.
        agreeing: Independent cited fields that agree (a strong title match and
            a year within ``NEAR_YEAR_TOLERANCE`` count as agreeing).
        conflicting: Independent cited fields whose PubMed value differs. A
            field the record lacks is unconfirmed, not conflicting.
    """

    lookup_fields: frozenset[str]
    agreeing: tuple[str, ...]
    conflicting: tuple[str, ...]

    @property
    def corroborated(self) -> bool:
        """Whether enough independent fields agree to propose corrections."""
        return len(self.agreeing) >= MIN_CORROBORATING_FIELDS


def lookup_key_fields(method: str | None, comparison: dict[str, bool | None]) -> frozenset[str]:
    """Return the fields a resolution strategy matched by construction."""
    fields = _LOOKUP_KEY_FIELDS.get(method or "", frozenset())
    if method == "metadata_search":
        # The query also required the volume or the first page to match.
        fields |= {"volume" if comparison.get("volume") is True else "first_page"}
    return fields


def record_value(article: dict[str, Any], field: str) -> str:
    """Return the PubMed value of one compared field in citation form."""
    if field == "first_page":
        return first_page_token(article.get("pages", ""))
    if field == "journal":
        return str(article.get("journal_abbrev", "") or article.get("journal", "") or "")
    if field == "first_author":
        return article_first_author(article)
    value = str(article.get(field, "") or "")
    return value.strip() if field == "title" else value


def identity_evidence(
    parsed: ParsedReference,
    article: dict[str, Any],
    comparison: dict[str, bool | None],
    *,
    method: str | None,
) -> IdentityEvidence:
    """Collect the independent cited fields that corroborate or contradict a record."""
    lookup_fields = lookup_key_fields(method, comparison)
    agreeing: list[str] = []
    conflicting: list[str] = []
    for field in _EVIDENCE_FIELDS:
        if field in lookup_fields or not record_value(article, field):
            continue
        agreement = _field_agreement(parsed, article, comparison, field)
        if agreement is True:
            agreeing.append(field)
        elif agreement is False:
            conflicting.append(field)
    return IdentityEvidence(lookup_fields, tuple(agreeing), tuple(conflicting))


def correction_blocker(
    parsed: ParsedReference,
    article: dict[str, Any],
    comparison: dict[str, bool | None],
    *,
    evidence: IdentityEvidence,
) -> CorrectionBlocker | None:
    """Return why the record is not anchored strongly enough to correct the citation, or ``None``."""
    if parsed.title and not is_strong_title_match(parsed.title, article.get("title", "")):
        return "title_conflict"
    anchored_by_identifier = comparison.get("doi") is True or comparison.get("pmid") is True
    if (
        not parsed.title
        and not anchored_by_identifier
        and sum(1 for field in _LOCATOR_FIELDS if comparison.get(field) is True) < MIN_IDENTITY_LOCATOR_MATCHES
    ):
        return "few_locators"
    if not evidence.corroborated:
        return "weak_corroboration"
    return None


def build_corrections(
    parsed: ParsedReference,
    article: dict[str, Any],
    comparison: dict[str, bool | None],
) -> list[dict[str, str]]:
    """List cited-vs-PubMed values for every mismatched field the record can correct."""
    corrections: list[dict[str, str]] = []
    for field in CORRECTABLE_FIELDS:
        pubmed_value = record_value(article, field)
        if comparison.get(field) is False and pubmed_value:
            corrections.append({"field": field, "cited": str(getattr(parsed, field)), "pubmed": pubmed_value})
    return corrections


def _field_agreement(
    parsed: ParsedReference,
    article: dict[str, Any],
    comparison: dict[str, bool | None],
    field: str,
) -> bool | None:
    """Whether one cited field agrees with the record; ``None`` when it was not cited."""
    if field == "title":
        return is_strong_title_match(parsed.title, article.get("title", "")) if parsed.title else None
    if field == "year":
        year_gap = _year_gap(parsed.year, article.get("year", ""))
        if year_gap is not None:
            return year_gap <= NEAR_YEAR_TOLERANCE
    return comparison.get(field)


def _year_gap(cited: str, record: object) -> int | None:
    """Absolute year difference, or ``None`` when either side is not a year."""
    record_text = str(record or "")
    if not (cited.isdigit() and record_text.isdigit()):
        return None
    return abs(int(cited) - int(record_text))
