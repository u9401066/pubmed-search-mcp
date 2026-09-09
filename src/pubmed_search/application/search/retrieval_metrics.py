"""Offline retrieval metrics against explicit relevance judgments.

These are measured metrics, independent of the heuristic recall estimates in
search planning. Unjudged documents receive zero gain. nDCG uses linear gains
as in trec_eval; every supplied query, including an empty run, must be scored.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def evaluate_ranking(
    ranked_ids: Sequence[str],
    judgments: Mapping[str, int],
    *,
    k: int = 10,
) -> dict[str, float]:
    """Measure a unique ranked list without giving duplicates extra credit.

    Recall's denominator includes relevant documents outside the returned pool.
    Precision always divides by k, including when fewer documents are returned.
    Grades > 0 are relevant for binary metrics; negative grades are unjudged.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if len(set(ranked_ids)) != len(ranked_ids):
        raise ValueError("Ranked document IDs must be unique")

    top = ranked_ids[:k]
    gains = [max(judgments.get(doc_id, 0), 0) for doc_id in top]
    relevant = sum(grade > 0 for grade in judgments.values())
    hits = sum(gain > 0 for gain in gains)
    precision = hits / k
    recall = hits / relevant if relevant else 0.0
    dcg = sum(gain / math.log2(rank + 2) for rank, gain in enumerate(gains))
    ideal = sorted((max(grade, 0) for grade in judgments.values()), reverse=True)[:k]
    idcg = sum(gain / math.log2(rank + 2) for rank, gain in enumerate(ideal))
    reciprocal_rank = next((1.0 / rank for rank, gain in enumerate(gains, 1) if gain > 0), 0.0)
    return {
        f"precision@{k}": precision,
        f"recall@{k}": recall,
        f"f1@{k}": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        f"ndcg@{k}": dcg / idcg if idcg else 0.0,
        f"mrr@{k}": reciprocal_rank,
        f"judged@{k}": sum(doc_id in judgments and judgments[doc_id] >= 0 for doc_id in top) / k,
    }
