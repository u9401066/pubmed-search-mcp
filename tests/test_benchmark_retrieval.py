"""Verify dataset loading and scoring with a tiny, independently judged corpus."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from scripts.benchmark_retrieval import run_benchmark

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def beir_dataset(tmp_path: Path) -> Path:
    (tmp_path / "corpus.jsonl").write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"_id": "a", "title": "Sepsis diagnosis", "text": "Infection"},
                {"_id": "b", "title": "Diabetes treatment", "text": "Insulin"},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "queries.jsonl").write_text(
        "\n".join(json.dumps(row) for row in [{"_id": "q1", "text": "sepsis"}, {"_id": "q2", "text": "diabetes"}])
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "qrels").mkdir()
    (tmp_path / "qrels/dev.tsv").write_text("query-id\tcorpus-id\tscore\nq1\ta\t2\nq2\tb\t1\n", encoding="utf-8")
    return tmp_path


def test_local_evaluation_is_reproducible_and_macro_averaged(beir_dataset: Path):
    run = run_benchmark(beir_dataset, split="dev")
    assert run == run_benchmark(beir_dataset, split="dev")
    assert run["corpus_size"] == 2
    assert run["query_count"] == 2
    assert run["metrics"]["ndcg@10"] == 1
    assert run["metrics"]["precision@10"] == 0.1
    assert run["per_query"]["q2"]["ranked_ids"] == ["b", "a"]
    assert len(run["sha256"]["corpus.jsonl"]) == 64


def test_limit_selects_query_ids_deterministically(beir_dataset: Path):
    run = run_benchmark(beir_dataset, split="dev", query_limit=1)
    assert list(run["per_query"]) == ["q1"]


def test_missing_judged_document_is_an_error(beir_dataset: Path):
    (beir_dataset / "qrels/dev.tsv").write_text("query-id\tcorpus-id\tscore\nq1\tmissing\t1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing query/document"):
        run_benchmark(beir_dataset, split="dev")


def test_query_limit_must_be_positive(beir_dataset: Path):
    with pytest.raises(ValueError, match="positive"):
        run_benchmark(beir_dataset, split="dev", query_limit=0)
