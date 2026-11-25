"""How PubMed spells its Boolean operators; shared by every query parser here.

Design:
    PubMed Help says to "enter Boolean operators in uppercase characters" but
    does not say what other spellings do. Live ESearch (db=pubmed,
    2026-11-25) shows:

    - ``AND``, ``OR`` and ``NOT`` are operators.
    - ``or`` and ``not`` are operators too: ``delirium[tiab] not pacu[tiab]``
      and ``delirium[tiab] NOT pacu[tiab]`` have the same translation and
      count, and so do ``or`` and ``OR``.
    - ``and`` is a stopword, not an operator. Between untagged words it is
      ignored (``PhraseIgnored: ["and"]``) and the default AND applies; before
      a bare tagged phrase it becomes part of that phrase:
      ``delirium[tiab] and pacu[tiab]`` is searched as
      ``"delirium"[Title/Abstract] AND "and pacu"[Title/Abstract]`` (0 hits).
    - Mixed case (``Not``, ``Or``, ``And``, ``oR``) is never an operator:
      PubMed searches the word (``"Not"[All Fields]``) or makes it part of the
      next tagged phrase (``"or pacu"[Title/Abstract]``).

Maintenance:
    ``boolean_query``, ``query_validator``, the MeSH correction clause parser
    and topic phrase segmentation all use these rules; change them together
    and re-probe PubMed first.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

PUBMED_BOOLEAN_OPERATORS: Mapping[str, str] = MappingProxyType(
    {"AND": "AND", "OR": "OR", "or": "OR", "NOT": "NOT", "not": "NOT"}
)
_OPERATOR_WORDS = frozenset({"and", "or", "not"})


def boolean_operator(word: str) -> str | None:
    """The operator (``AND``/``OR``/``NOT``) PubMed reads ``word`` as, or None when it is a word."""
    return PUBMED_BOOLEAN_OPERATORS.get(word)


def resembles_operator(word: str) -> bool:
    """Whether ``word`` spells and/or/not in any case, whether or not PubMed treats it as an operator."""
    return word.casefold() in _OPERATOR_WORDS


def misspelled_operator(word: str) -> bool:
    """A spelling of and/or/not that PubMed searches as a word (``Or``, ``Not``, ``aND``; not ``and``)."""
    return resembles_operator(word) and boolean_operator(word) is None and word != "and"


__all__ = ["PUBMED_BOOLEAN_OPERATORS", "boolean_operator", "misspelled_operator", "resembles_operator"]
