"""Measured outcomes and paired comparisons for literature-search agents."""

from __future__ import annotations

import random
import re
import string
from typing import TYPE_CHECKING

from pubmed_search.application.search.retrieval_metrics import evaluate_ranking

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import Any


def summarize_product_comparison(
    results: Mapping[str, Sequence[Mapping[str, Mapping[str, Any]]]],
    *,
    repeats: int,
    development_query_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Compare only complete pairs; average repeats within each query first.

    Invalid answers and task timeouts remain scored outcomes. Infrastructure
    failures must remain pending in the caller rather than becoming zero scores.
    """
    complete = {
        qid: runs
        for qid, runs in results.items()
        if len(runs) == repeats and all(set(pair) == {"native", "package"} for pair in runs)
    }
    primary = {qid: runs for qid, runs in complete.items() if qid not in development_query_ids}
    comparison = {}
    for metric in ("answer_exact_match", "source_pmid_hit"):
        means = {
            arm: {qid: sum(pair[arm]["metrics"][metric] for pair in runs) / repeats for qid, runs in primary.items()}
            for arm in ("native", "package")
        }
        if primary:
            comparison[metric] = paired_comparison(means["native"], means["package"])
    return {
        "complete_query_count": len(complete),
        "primary_query_count": len(primary),
        "comparison": comparison,
    }


def score_factoid_answer(
    answer: str, aliases: Sequence[str], cited_pmids: Sequence[str], source_pmid: str
) -> dict[str, float]:
    """PaperSearchQA-style normalized exact match plus a separate source hit.

    Source hit identifies the question's originating paper, not whether every
    citation supports the answer. Other relevant supporting papers may exist.
    """

    def normalize(text: str) -> str:
        unpunctuated = text.lower().translate(str.maketrans("", "", string.punctuation))
        return " ".join(re.sub(r"\b(?:a|an|the)\b", " ", unpunctuated).split())

    prediction = normalize(answer)
    return {
        "answer_exact_match": float(bool(prediction) and any(prediction == normalize(alias) for alias in aliases)),
        "source_pmid_hit": float(source_pmid in cited_pmids),
    }


def score_agent_search(
    selected_ids: Sequence[str], retrieved_ids: Sequence[str], judgments: Mapping[str, int]
) -> dict[str, float]:
    """Separate discovery from selection; refuse unseen or duplicate answers."""
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError("Selected IDs must be unique")
    retrieved = set(retrieved_ids)
    if not set(selected_ids) <= retrieved:
        raise ValueError("Selected IDs must have been retrieved or read")
    relevant = {doc_id for doc_id, grade in judgments.items() if grade > 0}
    found = retrieved & relevant
    selected = set(selected_ids) & relevant
    precision = len(selected) / len(selected_ids) if selected_ids else 0.0
    recall = len(selected) / len(relevant) if relevant else 0.0
    return {
        **evaluate_ranking(selected_ids, judgments),
        "retrieval_recall": len(found) / len(relevant) if relevant else 0.0,
        "selection_precision": precision,
        "selection_recall": recall,
        "selection_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "gold_discard_rate": len(found - selected) / len(found) if found else 0.0,
    }


def paired_comparison(
    baseline: Mapping[str, float], treatment: Mapping[str, float], *, samples: int = 10000, seed: int = 20260909
) -> dict[str, float | int | list[float]]:
    """Bootstrap paired query means, never treat unmatched tasks as successes.

    For repeated runs, callers must average repetitions within each query first.
    This exploratory interval is not a substitute for a held-out evaluation.
    """
    if not baseline or baseline.keys() != treatment.keys():
        raise ValueError("Non-empty, matching query IDs are required")
    if samples < 100:
        raise ValueError("At least 100 bootstrap samples are required")
    differences = [treatment[key] - baseline[key] for key in sorted(baseline)]
    rng = random.Random(seed)  # noqa: S311 - reproducible statistical resampling, not cryptography
    bootstrapped = sorted(sum(rng.choices(differences, k=len(differences))) / len(differences) for _ in range(samples))
    return {
        "query_count": len(differences),
        "baseline_mean": sum(baseline.values()) / len(baseline),
        "treatment_mean": sum(treatment.values()) / len(treatment),
        "delta": sum(differences) / len(differences),
        "paired_bootstrap_95_interval": [bootstrapped[int(samples * 0.025)], bootstrapped[int(samples * 0.975)]],
    }
