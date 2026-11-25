"""MeSH/concept block contribution analysis for PubMed search strategies.

For a strategy of AND blocks (each an OR list of terms) with optional NOT
blocks, this computes count-only ESearch hit counts for:

1. the full strategy;
2. each AND block on its own;
3. cumulative AND combinations (B1, B1∧B2, …, all AND blocks);
4. records removed by each NOT block;
5. each term's *unique contribution*: how many records of the full strategy
   would be lost if that term were removed from its block.

A zero unique contribution means the term retrieves nothing the rest of its
block does not already find *within this strategy* — a prompt to review the
term, not proof it is useless. Every count is one provider operation that
reserves the run's count-query quota first; the number of count queries per
analysis is bounded and any unevaluated item is disclosed, never guessed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pubmed_search.application.pipeline.boolean_query import (
    DecomposedQuery,
    QueryDecompositionError,
    decompose_pubmed_query,
)
from pubmed_search.application.pipeline.budgets import PipelineBudgetExceededError

CountFn = Callable[[str], Awaitable[int]]


class _CountBudget:
    """Per-analysis count cache with a hard query cap."""

    def __init__(self, count: CountFn, max_queries: int) -> None:
        self._count = count
        self._max_queries = max_queries
        self._cache: dict[str, int] = {}
        self.executed = 0
        self.cache_hits = 0
        self.stop_reason: str | None = None

    @property
    def stopped(self) -> bool:
        return self.stop_reason is not None

    async def get(self, query: str) -> int | None:
        if query in self._cache:
            self.cache_hits += 1
            return self._cache[query]
        if self.stopped:
            return None
        if self.executed >= self._max_queries:
            self.stop_reason = "max_count_queries"
            return None
        try:
            value = await self._count(query)
        except PipelineBudgetExceededError as exc:
            self.stop_reason = exc.reason
            return None
        except Exception as exc:  # keep completed counts; disclose why the rest are missing
            self.stop_reason = f"provider_error ({type(exc).__name__})"
            return None
        self.executed += 1
        self._cache[query] = value
        return value


def planned_count_queries(decomposed: DecomposedQuery) -> int:
    """Upper bound of distinct count queries a full analysis needs."""
    blocks = len(decomposed.and_blocks)
    cumulative = max(0, blocks - 2) + (1 if decomposed.not_blocks and blocks > 1 else 0)
    nots = len(decomposed.not_blocks) if len(decomposed.not_blocks) > 1 else 0
    terms = sum(len(block.terms) for block in decomposed.and_blocks if len(block.terms) > 1 and block.or_list)
    return 1 + blocks + cumulative + nots + terms


def not_decomposable(query: str, reason: str) -> dict[str, Any]:
    return {"query": query, "decomposable": False, "reason": reason}


async def analyze_strategy_blocks(query: str, *, count: CountFn, max_count_queries: int) -> dict[str, Any]:
    """Return a persisted-ready block contribution analysis for ``query``.

    Provider errors other than budget exhaustion propagate to the caller.
    """
    try:
        decomposed = decompose_pubmed_query(query)
    except QueryDecompositionError as exc:
        return not_decomposable(query, str(exc))

    budget = _CountBudget(count, max_count_queries)
    full_count = await budget.get(query.strip())
    and_texts = [block.render() for block in decomposed.and_blocks]
    not_texts = [block.render() for block in decomposed.not_blocks]

    blocks: list[dict[str, Any]] = []
    for block in decomposed.and_blocks:
        blocks.append(
            {
                "label": block.label,
                "text": block.text,
                "term_count": len(block.terms),
                "or_list": block.or_list,
                "count": await budget.get(block.render()),
            }
        )

    cumulative: list[dict[str, Any]] = []
    for size in range(1, len(and_texts) + 1):
        combined = decomposed.combine(and_texts[:size], [])
        cumulative.append(
            {
                "blocks": [block.label for block in decomposed.and_blocks[:size]],
                "query": combined,
                "count": blocks[0]["count"]
                if size == 1
                else full_count
                if size == len(and_texts) and not not_texts
                else await budget.get(combined),
            }
        )
    if not_texts:
        cumulative.append(
            {
                "blocks": [block.label for block in decomposed.and_blocks]
                + [block.label for block in decomposed.not_blocks],
                "query": decomposed.full(),
                "count": full_count,
            }
        )

    all_and_count = cumulative[len(and_texts) - 1]["count"]
    not_blocks: list[dict[str, Any]] = []
    for index, block in enumerate(decomposed.not_blocks):
        if len(not_texts) == 1:
            without = all_and_count
        else:
            without = await budget.get(
                decomposed.combine(and_texts, [text for other, text in enumerate(not_texts) if other != index])
            )
        not_blocks.append(
            {
                "label": block.label,
                "text": block.text,
                "records_removed": None if without is None or full_count is None else without - full_count,
            }
        )

    terms: list[dict[str, Any]] = []
    for block_index, block in enumerate(decomposed.and_blocks):
        for term_index, term in enumerate(block.terms):
            entry: dict[str, Any] = {"block": block.label, "term": term}
            if not block.or_list:
                entry.update({"status": "not_separable", "unique_contribution": None})
            elif len(block.terms) == 1:
                entry.update({"status": "sole_term", "unique_contribution": None})
            else:
                variant = list(and_texts)
                variant[block_index] = block.render_without(term_index)
                without = await budget.get(decomposed.combine(variant))
                if without is None or full_count is None:
                    entry.update({"status": "not_evaluated", "unique_contribution": None})
                else:
                    entry.update(
                        {
                            "status": "evaluated",
                            "count_without": without,
                            "unique_contribution": full_count - without,
                        }
                    )
            terms.append(entry)

    not_evaluated = [term for term in terms if term["status"] == "not_evaluated"]
    return {
        "query": query,
        "decomposable": True,
        "reason": None,
        "full_count": full_count,
        "blocks": blocks,
        "not_blocks": not_blocks,
        "cumulative": cumulative,
        "terms": terms,
        "zero_contribution_terms": [
            {"block": term["block"], "term": term["term"]}
            for term in terms
            if term["status"] == "evaluated" and term["unique_contribution"] == 0
        ],
        "count_queries": {
            "planned": planned_count_queries(decomposed),
            "executed": budget.executed,
            "cache_hits": budget.cache_hits,
            "max": max_count_queries,
            "truncated": budget.stopped,
            "truncation_reason": budget.stop_reason,
            "terms_not_evaluated": len(not_evaluated),
        },
    }


__all__ = ["analyze_strategy_blocks", "not_decomposable", "planned_count_queries"]
