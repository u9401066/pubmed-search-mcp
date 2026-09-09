"""Hand-computed quality metrics, including incomplete and empty retrieval."""

from __future__ import annotations

import math

import pytest

from pubmed_search.application.search.retrieval_metrics import evaluate_ranking


def test_graded_gains_and_missing_relevant_documents():
    scores = evaluate_ranking(["wrong", "partial", "full"], {"full": 2, "partial": 1, "missing": 2}, k=3)
    assert scores["precision@3"] == pytest.approx(2 / 3)
    assert scores["recall@3"] == pytest.approx(2 / 3)
    assert scores["mrr@3"] == 0.5
    assert scores["ndcg@3"] == pytest.approx((1 / math.log2(3) + 1) / (2 + 2 / math.log2(3) + 0.5))
    assert scores["judged@3"] == pytest.approx(2 / 3)


def test_short_run_uses_cutoff_for_precision_and_all_qrels_for_recall():
    scores = evaluate_ranking(["a"], {"a": 1, "b": 1}, k=10)
    assert scores["precision@10"] == 0.1
    assert scores["recall@10"] == 0.5


@pytest.mark.parametrize("judgments", [{}, {"a": 0}, {"a": 1}])
def test_empty_runs_are_zero(judgments):
    assert all(value == 0 for value in evaluate_ranking([], judgments).values())


def test_perfect_run():
    scores = evaluate_ranking(["a", "b"], {"a": 2, "b": 1}, k=2)
    assert all(value == 1 for value in scores.values())


def test_duplicate_ids_cannot_inflate_metrics():
    with pytest.raises(ValueError, match="unique"):
        evaluate_ranking(["a", "a"], {"a": 1})


def test_invalid_cutoff():
    with pytest.raises(ValueError, match="positive"):
        evaluate_ranking([], {}, k=0)
