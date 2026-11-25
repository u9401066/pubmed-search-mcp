"""PubMed query construction for reference-verification fallbacks.

Both queries deliberately omit the cited publication year, because a wrong
year is the most common citation error.

Title search uses AND-ed title words rather than one quoted phrase: E-utilities
ESearch only matches quoted phrases present in PubMed's phrase index, so long
article titles return ``QuotedPhraseNotFound`` and zero hits. PubMed stopwords
are dropped because a tagged stopword (``among[ti]``) matches nothing, and
common British/American spelling pairs are OR-ed so ``anaesthetic`` still finds
``anesthetic``.

This module performs no I/O.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .parsing import fold_ascii

if TYPE_CHECKING:
    from .parsing import ParsedReference

MAX_TITLE_QUERY_TERMS = 12
MIN_TITLE_QUERY_TERMS = 2
_MIN_TERM_LENGTH = 2

# PubMed's documented stopword list (https://pubmed.ncbi.nlm.nih.gov/help/#help-stopwords).
PUBMED_STOPWORDS = frozenset(
    [
        "a",
        "about",
        "again",
        "all",
        "almost",
        "also",
        "although",
        "always",
        "among",
        "an",
        "and",
        "another",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "done",
        "due",
        "during",
        "each",
        "either",
        "enough",
        "especially",
        "etc",
        "for",
        "found",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "here",
        "how",
        "however",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "itself",
        "just",
        "kg",
        "km",
        "made",
        "mainly",
        "make",
        "may",
        "mg",
        "might",
        "ml",
        "mm",
        "most",
        "mostly",
        "must",
        "nearly",
        "neither",
        "no",
        "nor",
        "obtained",
        "of",
        "often",
        "on",
        "our",
        "overall",
        "perhaps",
        "pmid",
        "quite",
        "rather",
        "really",
        "regarding",
        "seem",
        "seen",
        "several",
        "should",
        "show",
        "showed",
        "shown",
        "shows",
        "significantly",
        "since",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "then",
        "there",
        "therefore",
        "these",
        "they",
        "this",
        "those",
        "through",
        "thus",
        "to",
        "upon",
        "use",
        "used",
        "using",
        "various",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "which",
        "while",
        "with",
        "within",
        "without",
        "would",
    ]
)

# American -> British stems; each match adds the other spelling as an OR alternative.
_SPELLING_STEMS = (
    ("anesth", "anaesth"),
    ("ischemi", "ischaemi"),
    ("esophag", "oesophag"),
    ("pediatr", "paediatr"),
    ("leukemi", "leukaemi"),
    ("anemi", "anaemi"),
    ("edema", "oedema"),
    ("estrogen", "oestrogen"),
    ("diarrhea", "diarrhoea"),
    ("orthoped", "orthopaed"),
    ("gynecol", "gynaecol"),
)
_SPELLING_PREFIXES = (("hemorrh", "haemorrh"), ("hemat", "haemat"), ("hemo", "haemo"), ("hema", "haema"))
# ``oe`` is British only word-initially (oesophagus) or in a few stems; elsewhere
# it is ordinary spelling (electroencephalography).
_BRITISH_OE_RE = re.compile(r"^oe|foet|coeli|oea|oeuv")
_IZE_RE = re.compile(r"iz(e|ed|es|ing|ation|ations)$")
_ISE_RE = re.compile(r"(?<=[a-z]{3})is(e|ed|es|ing|ation|ations)$")
_QUERY_UNSAFE_RE = re.compile(r'["\[\]()]')
_QUERY_NAME_UNSAFE_RE = re.compile(r"[^\w\s'.-]")


def title_search_terms(title: str) -> list[str]:
    """Return distinctive lowercase title words in cited order (stopwords removed)."""
    terms: list[str] = []
    for word in re.findall(r"[a-z0-9]+", fold_ascii(title).lower()):
        if len(word) < _MIN_TERM_LENGTH or word in PUBMED_STOPWORDS or word in terms:
            continue
        terms.append(word)
        if len(terms) >= MAX_TITLE_QUERY_TERMS:
            break
    return terms


def spelling_variants(word: str) -> list[str]:
    """Return ``word`` plus its common British/American spelling counterparts."""
    variants = [word]

    def add(candidate: str) -> None:
        if candidate and candidate not in variants:
            variants.append(candidate)

    for american, british in _SPELLING_STEMS:
        if british in word:
            add(word.replace(british, american))
        elif american in word:
            add(word.replace(american, british))
    for american, british in _SPELLING_PREFIXES:
        if word.startswith(british):
            add(american + word[len(british) :])
            break
        if word.startswith(american):
            add(british + word[len(american) :])
            break
    if "ae" in word:
        add(word.replace("ae", "e"))
    if _BRITISH_OE_RE.search(word):
        add(word.replace("oe", "e"))
    if _IZE_RE.search(word):
        add(_IZE_RE.sub(r"is\1", word))
    elif _ISE_RE.search(word):
        add(_ISE_RE.sub(r"iz\1", word))
    return variants


def title_word_query(title: str) -> str | None:
    """Build ``word[ti] AND (variant[ti] OR variant[ti]) ...`` for one cited title."""
    terms = title_search_terms(title)
    if len(terms) < MIN_TITLE_QUERY_TERMS:
        return None
    clauses = []
    for term in terms:
        variants = spelling_variants(term)
        if len(variants) == 1:
            clauses.append(f"{term}[ti]")
        else:
            clauses.append("(" + " OR ".join(f"{variant}[ti]" for variant in variants) + ")")
    return " AND ".join(clauses)


def safe_phrase(text: str) -> str:
    """Remove characters that would break a quoted PubMed phrase or field tag."""
    return re.sub(r"\s+", " ", _QUERY_UNSAFE_RE.sub(" ", text)).strip()


def metadata_query(parsed: ParsedReference) -> str | None:
    """Build ``Surname[1au] AND "Journal"[ta] AND ("vol"[vi] OR "page"[pg])``.

    The author term stays unquoted so PubMed matches any initials; volume and
    first page are alternatives so one mis-cited locator does not hide the
    record.
    """
    author = re.sub(r"\s+", " ", _QUERY_NAME_UNSAFE_RE.sub(" ", fold_ascii(parsed.first_author))).strip(" .'-")
    journal = safe_phrase(parsed.journal)
    locators = [
        f'"{value}"[{tag}]'
        for value, tag in ((safe_phrase(parsed.volume), "vi"), (safe_phrase(parsed.first_page), "pg"))
        if value
    ]
    if not author or not journal or not locators:
        return None
    locator_clause = locators[0] if len(locators) == 1 else f"({' OR '.join(locators)})"
    return f'{author}[1au] AND "{journal}"[ta] AND {locator_clause}'
