"""Parse PubMed Boolean strategies into concept blocks of OR'd terms.

Systematic-review strategies are usually written as concept blocks joined by
``AND`` (each block an ``OR`` list of MeSH and free-text terms) with optional
``NOT`` exclusions::

    (A[Mesh] OR "b c"[tiab] OR d*[tiab]) AND (E[Mesh] OR f[tiab]) NOT (g[pt])

This module tokenizes PubMed syntax conservatively (quoted phrases, field
tags such as ``[Mesh]``/``[Title/Abstract]``/``[tiab:~3]``, wildcards, MeSH
subheadings, nested parentheses) and decomposes the top level into AND blocks
and NOT blocks. Rendering always reuses the caller's original text spans, so
a recombined query never rewrites a term.

PubMed evaluates Boolean operators strictly left to right with no precedence.
A top level that mixes ``OR`` with ``AND``/``NOT`` therefore has no unambiguous
block structure and is reported as not decomposable instead of being guessed.
Only upper-case ``AND``/``OR``/``NOT`` are operators; lower-case words stay part
of a term, matching PubMed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

MAX_QUERY_CHARS = 20_000
MAX_NESTING_DEPTH = 50
_OPERATORS = frozenset({"AND", "OR", "NOT"})
_WORD_BREAKS = frozenset('()"[')

TokenKind = Literal["lparen", "rparen", "op", "term"]


class QueryDecompositionError(ValueError):
    """The query is not valid or not decomposable into concept blocks."""


@dataclass(frozen=True)
class _Token:
    kind: TokenKind
    start: int
    end: int
    value: str


@dataclass
class QueryNode:
    """A term (verbatim text) or a parenthesized/top-level Boolean sequence."""

    text: str
    operands: list[QueryNode] = field(default_factory=list)
    operators: list[str] = field(default_factory=list)
    parenthesized: bool = False

    @property
    def is_term(self) -> bool:
        return not self.operands


@dataclass(frozen=True)
class ConceptBlock:
    """One AND (or NOT) block and its top-level OR terms."""

    label: str
    text: str
    terms: tuple[str, ...]
    or_list: bool

    def render(self) -> str:
        return self.text

    def render_without(self, term_index: int) -> str:
        """Render this block with one OR term removed (verbatim term text)."""
        remaining = [term for index, term in enumerate(self.terms) if index != term_index]
        if not remaining:
            raise QueryDecompositionError("A block cannot be rendered without its only term")
        return remaining[0] if len(remaining) == 1 else "(" + " OR ".join(remaining) + ")"


@dataclass(frozen=True)
class DecomposedQuery:
    """AND blocks and NOT blocks of one PubMed strategy."""

    query: str
    and_blocks: tuple[ConceptBlock, ...]
    not_blocks: tuple[ConceptBlock, ...]

    def combine(self, and_texts: Sequence[str], not_texts: Sequence[str] | None = None) -> str:
        """Join rendered blocks with PubMed's left-to-right AND/NOT semantics."""
        query = " AND ".join(and_texts)
        for text in [block.render() for block in self.not_blocks] if not_texts is None else not_texts:
            query += f" NOT {text}"
        return query

    def full(self) -> str:
        return self.combine([block.render() for block in self.and_blocks])


def _tokenize(query: str) -> list[_Token]:
    tokens: list[_Token] = []
    index = 0
    length = len(query)
    while index < length:
        char = query[index]
        if char.isspace():
            index += 1
            continue
        if char == "(":
            tokens.append(_Token("lparen", index, index + 1, char))
            index += 1
            continue
        if char == ")":
            tokens.append(_Token("rparen", index, index + 1, char))
            index += 1
            continue
        if char == '"':
            closing = query.find('"', index + 1)
            if closing < 0:
                raise QueryDecompositionError("Unbalanced double quote")
            tokens.append(_Token("term", index, closing + 1, query[index : closing + 1]))
            index = closing + 1
            continue
        if char == "[":
            closing = query.find("]", index + 1)
            if closing < 0:
                raise QueryDecompositionError("Unbalanced field tag bracket")
            if not tokens or tokens[-1].kind != "term":
                raise QueryDecompositionError("A field tag must follow a term")
            tokens.append(_Token("term", index, closing + 1, query[index : closing + 1]))
            index = closing + 1
            continue
        if char == "]":
            raise QueryDecompositionError("Unbalanced field tag bracket")
        end = index
        while end < length and not query[end].isspace() and query[end] not in _WORD_BREAKS:
            if query[end] == "]":
                raise QueryDecompositionError("Unbalanced field tag bracket")
            end += 1
        word = query[index:end]
        tokens.append(_Token("op" if word in _OPERATORS else "term", index, end, word))
        index = end

    # Adjacent term fragments (words, phrases, tags) form one verbatim term.
    merged: list[_Token] = []
    for token in tokens:
        if token.kind == "term" and merged and merged[-1].kind == "term":
            previous = merged[-1]
            merged[-1] = _Token("term", previous.start, token.end, query[previous.start : token.end])
            continue
        merged.append(token)
    return merged


class _Parser:
    def __init__(self, query: str, tokens: list[_Token]) -> None:
        self._query = query
        self._tokens = tokens
        self._position = 0

    def _peek(self) -> _Token | None:
        return self._tokens[self._position] if self._position < len(self._tokens) else None

    def parse(self) -> QueryNode:
        node = self._sequence(depth=0)
        if self._peek() is not None:
            raise QueryDecompositionError("Unbalanced closing parenthesis")
        return node

    def _sequence(self, *, depth: int) -> QueryNode:
        if depth > MAX_NESTING_DEPTH:
            raise QueryDecompositionError(f"Parentheses are nested deeper than {MAX_NESTING_DEPTH} levels")
        first = self._operand(depth=depth)
        node = QueryNode(text="", operands=[first])
        while (token := self._peek()) is not None and token.kind == "op":
            self._position += 1
            node.operators.append(token.value)
            node.operands.append(self._operand(depth=depth))
        if len(node.operands) == 1 and not node.operators:
            return first
        return node

    def _operand(self, *, depth: int) -> QueryNode:
        token = self._peek()
        if token is None:
            raise QueryDecompositionError("Boolean operator is missing an operand")
        if token.kind == "term":
            self._position += 1
            return QueryNode(text=token.value)
        if token.kind == "lparen":
            self._position += 1
            inner = self._sequence(depth=depth + 1)
            closing = self._peek()
            if closing is None or closing.kind != "rparen":
                raise QueryDecompositionError("Unbalanced opening parenthesis")
            self._position += 1
            return QueryNode(
                text=self._query[token.start : closing.end],
                operands=inner.operands if not inner.is_term else [inner],
                operators=inner.operators,
                parenthesized=True,
            )
        if token.kind == "op":
            raise QueryDecompositionError(f"Operator {token.value} is missing its left operand")
        raise QueryDecompositionError("Empty parentheses or unbalanced closing parenthesis")


def parse_pubmed_query(query: str) -> QueryNode:
    """Parse a PubMed Boolean query; raise QueryDecompositionError when invalid."""
    if not isinstance(query, str) or not query.strip():
        raise QueryDecompositionError("Query is empty")
    if len(query) > MAX_QUERY_CHARS:
        raise QueryDecompositionError(f"Query exceeds {MAX_QUERY_CHARS} characters")
    tokens = _tokenize(query)
    if not tokens:
        raise QueryDecompositionError("Query is empty")
    return _Parser(query, tokens).parse()


def _unwrap(node: QueryNode) -> QueryNode:
    while node.parenthesized and len(node.operands) == 1 and not node.operators and not node.operands[0].is_term:
        node = node.operands[0]
    return node


def _block(node: QueryNode, label: str) -> ConceptBlock:
    inner = _unwrap(node)
    if inner.is_term or (len(inner.operands) == 1 and not inner.operators):
        term = inner.text if inner.is_term else inner.operands[0].text
        return ConceptBlock(label=label, text=node.text, terms=(term,), or_list=True)
    if all(operator == "OR" for operator in inner.operators):
        return ConceptBlock(
            label=label,
            text=node.text,
            terms=tuple(operand.text for operand in inner.operands),
            or_list=True,
        )
    # Nested AND/NOT inside a block: keep it whole; terms are not separable.
    return ConceptBlock(label=label, text=node.text, terms=(node.text,), or_list=False)


def decompose_pubmed_query(query: str) -> DecomposedQuery:
    """Split a PubMed strategy into AND blocks of OR terms plus NOT blocks.

    Raises:
        QueryDecompositionError: invalid syntax, or a top level whose meaning
            depends on PubMed's left-to-right evaluation (mixed OR with AND/NOT).
    """
    root = _unwrap(parse_pubmed_query(query))
    if root.is_term:
        return DecomposedQuery(query, (ConceptBlock("B1", root.text, (root.text,), True),), ())
    operators = set(root.operators)
    if operators <= {"OR"}:
        top = QueryNode(text=query.strip(), operands=root.operands, operators=root.operators)
        return DecomposedQuery(query, (_block(top, "B1"),), ())
    if "OR" in operators:
        raise QueryDecompositionError(
            "The top level mixes OR with AND/NOT; PubMed evaluates operators left to right, so wrap each "
            "concept block in parentheses, e.g. (a OR b) AND (c OR d)"
        )
    and_nodes = [root.operands[0]]
    not_nodes: list[QueryNode] = []
    for operator, operand in zip(root.operators, root.operands[1:], strict=True):
        (and_nodes if operator == "AND" else not_nodes).append(operand)
    return DecomposedQuery(
        query,
        tuple(_block(node, f"B{index}") for index, node in enumerate(and_nodes, start=1)),
        tuple(_block(node, f"NOT{index}") for index, node in enumerate(not_nodes, start=1)),
    )


__all__ = [
    "ConceptBlock",
    "DecomposedQuery",
    "QueryDecompositionError",
    "QueryNode",
    "decompose_pubmed_query",
    "parse_pubmed_query",
]
