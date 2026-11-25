"""Candidate comparison, ranking, and correction rules for reference verification.

These rules decide whether a PubMed record is the cited work and, if it is,
which cited fields disagree with it. They are deliberately conservative:

- ``verified`` still requires every supplied field to agree (see the service).
- A record found by a search that ignored the cited year is only *accepted* as
  the cited work when its title agrees with the cited title and the first
  author or journal also agree (or, without a cited title, when author,
  journal, volume and first page all agree).
- Field-level corrections are offered only when the cited title (or, without a
  title, the identifier / locator) anchors the record's identity. A conflicting
  title means the identifier or locator may point to a different work, so no
  correction is proposed.

This module performs no I/O.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import TYPE_CHECKING, Any

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
_IZE_RE = re.compile(r"(?<=[a-z])is(ation|ations|e|ed|es|ing)$")


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
    """Tokenize a title, folding British/American spelling variants."""
    tokens: list[str] = []
    for word in re.findall(r"[a-z0-9]+", fold_text(title)):
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
        comparisons["title"] = cited_title == normalize_article_title(fold_text(record_title)) or (
            bool(cited_title) and title_tokens(parsed.title) == title_tokens(record_title)
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


def identity_supported(parsed: ParsedReference, article: dict[str, Any], comparison: dict[str, bool | None]) -> bool:
    """Whether the record is anchored as the cited work strongly enough to propose corrections."""
    if parsed.title:
        return is_strong_title_match(parsed.title, article.get("title", ""))
    if comparison.get("doi") is True or comparison.get("pmid") is True:
        return True
    return sum(1 for field in _LOCATOR_FIELDS if comparison.get(field) is True) >= MIN_IDENTITY_LOCATOR_MATCHES


def build_corrections(
    parsed: ParsedReference,
    article: dict[str, Any],
    comparison: dict[str, bool | None],
) -> list[dict[str, str]]:
    """List cited-vs-PubMed values for every mismatched field the record can correct."""
    record_values = {
        "year": str(article.get("year", "") or ""),
        "volume": str(article.get("volume", "") or ""),
        "first_page": first_page_token(article.get("pages", "")),
        "journal": str(article.get("journal_abbrev", "") or article.get("journal", "") or ""),
        "first_author": article_first_author(article),
        "title": str(article.get("title", "") or "").strip(),
        "doi": str(article.get("doi", "") or ""),
        "pmid": str(article.get("pmid", "") or ""),
    }
    corrections: list[dict[str, str]] = []
    for field in CORRECTABLE_FIELDS:
        pubmed_value = record_values[field]
        if comparison.get(field) is False and pubmed_value:
            corrections.append({"field": field, "cited": str(getattr(parsed, field)), "pubmed": pubmed_value})
    return corrections


def _year_gap(cited: str, record: object) -> int | None:
    """Absolute year difference, or ``None`` when either side is not a year."""
    record_text = str(record or "")
    if not (cited.isdigit() and record_text.isdigit()):
        return None
    return abs(int(cited) - int(record_text))
