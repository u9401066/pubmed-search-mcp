"""Translate a PubMed-dialect query for providers that do not read field tags.

Hybrid search sends the caller's query to PubMed unchanged and a
provider-neutral sibling to full-text and semantic channels. The translation
is deliberately lossy and says so:

* content terms (MeSH headings, title/abstract words, substance names) keep
  their text and Boolean structure;
* a MeSH heading becomes its plain words, because full-text and semantic
  indexes match article text, not NLM indexing;
* clauses that only restrict the record type (publication type, language,
  date, subset, journal, author) are dropped and reported, because no neutral
  equivalent exists.

The result is a recall-oriented reformulation. It is never presented as the
caller's query: records it alone finds are labelled by channel.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Tags whose term text describes the topic and survives translation.
_CONTENT_TAGS = frozenset(
    {
        "mesh",
        "mesh terms",
        "mh",
        "majr",
        "mesh major topic",
        "mesh:noexp",
        "mh:noexp",
        "majr:noexp",
        "mesh subheading",
        "sh",
        "tiab",
        "title/abstract",
        "ti",
        "title",
        "ab",
        "abstract",
        "tw",
        "text word",
        "all fields",
        "all",
        "nm",
        "substance name",
        "supplementary concept",
        "pharmacological action",
        "pa",
        "ot",
        "other term",
    }
)
_MESH_TAGS = frozenset(tag for tag in _CONTENT_TAGS if tag.startswith(("mesh", "mh", "majr")))

_TAGGED_TERM = re.compile(
    r"""
    (?P<term>"[^"]+"|[^\s()\[\]"]+(?:\s+[^\s()\[\]"]+)*?)   # quoted phrase or bare words
    \s*\[(?P<tag>[^\]]+)\]
    """,
    re.VERBOSE,
)
_OPERATORS = frozenset({"AND", "OR", "NOT"})
_WORD = re.compile(r"[^\W_]+(?:[-'/.][^\W_]+)*", re.UNICODE)


@dataclass(frozen=True)
class NeutralQuery:
    """Provider-neutral forms of one PubMed-dialect query."""

    boolean: str
    """Boolean keyword query for full-text indexes (Europe PMC syntax subset)."""
    semantic: str
    """Deduplicated content terms for embedding-based search."""
    dropped: tuple[str, ...]
    """Restriction clauses with no neutral equivalent, e.g. ``Randomized Controlled Trial[pt]``."""
    translated: bool
    """Whether any PubMed field tag was present and rewritten."""


def _plain_words(term: str) -> str:
    return " ".join(_WORD.findall(term.strip('"')))


def _split_bare_term(term: str) -> tuple[str, str]:
    """Split ``a AND b c`` (bare words before a tag) into prefix and the tagged term.

    PubMed applies a tag to the whole untagged run before it, but a Boolean
    operator ends that run.
    """
    tokens = term.split()
    for index in range(len(tokens) - 1, -1, -1):
        if tokens[index] in _OPERATORS:
            return " ".join(tokens[: index + 1]), " ".join(tokens[index + 1 :])
    return "", term


def _tidy_boolean(text: str) -> str:
    """Remove operators and parentheses left dangling by dropped clauses."""
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\(\s*\)", " ", text)
        text = re.sub(r"\(\s*(?:AND|OR|NOT)\b", "(", text)
        text = re.sub(r"\b(?:AND|OR|NOT)\s*\)", ")", text)
        text = re.sub(r"\b(AND|OR|NOT)(?:\s+(?:AND|OR|NOT)\b)+", r"\1", text)
        text = re.sub(r"^\s*(?:AND|OR|NOT)\b", " ", text)
        text = re.sub(r"\b(?:AND|OR|NOT)\s*$", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
    # A group that now holds one term needs no parentheses.
    return re.sub(r"\(\s*((?:\"[^\"]+\")|[^\s()]+)\s*\)", r"\1", text)


def neutralize_pubmed_query(query: str) -> NeutralQuery:
    """Return provider-neutral forms of ``query``.

    A query without field tags is returned unchanged in both forms.
    """
    if "[" not in query:
        cleaned = " ".join(query.split())
        return NeutralQuery(boolean=cleaned, semantic=cleaned, dropped=(), translated=False)

    dropped: list[str] = []
    parts: list[str] = []
    cursor = 0
    for match in _TAGGED_TERM.finditer(query):
        parts.append(query[cursor : match.start()])
        cursor = match.end()
        term = match.group("term")
        tag = " ".join(match.group("tag").lower().split())
        prefix = ""
        if not term.startswith('"'):
            prefix, term = _split_bare_term(term)
        if prefix:
            parts.append(prefix + " ")
        if tag not in _CONTENT_TAGS:
            dropped.append(f"{term}[{match.group('tag')}]")
            continue
        words = _plain_words(term)
        if not words:
            continue
        if tag in _MESH_TAGS or not term.startswith('"'):
            # Headings and bare runs match as words, not as an exact phrase.
            parts.append(f"({words})" if " " in words else words)
        else:
            parts.append(f'"{words}"')
    parts.append(query[cursor:])
    boolean = _tidy_boolean("".join(parts))

    seen: set[str] = set()
    semantic_terms: list[str] = []
    for word in _WORD.findall(boolean):
        key = word.casefold()
        if word in _OPERATORS or key in seen:
            continue
        seen.add(key)
        semantic_terms.append(word)
    return NeutralQuery(
        boolean=boolean,
        semantic=" ".join(semantic_terms),
        dropped=tuple(dropped),
        translated=True,
    )


__all__ = ["NeutralQuery", "neutralize_pubmed_query"]
