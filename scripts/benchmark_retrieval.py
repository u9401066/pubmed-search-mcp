"""Evaluate production BM25 on a local BEIR corpus without API/LLM calls.

Usage: uv run python scripts/benchmark_retrieval.py /path/to/nfcorpus --split dev --output /tmp/run.json

This measures the lexical ranking component over the supplied corpus, not
end-to-end agent performance or live PubMed candidate generation. No data is
downloaded implicitly. Obtain datasets under their respective terms of use.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from pubmed_search.application.search.ranking_algorithms import BM25Corpus, bm25_score
from pubmed_search.application.search.retrieval_metrics import evaluate_ranking
from pubmed_search.domain.entities.article import UnifiedArticle


def run_benchmark(dataset: Path, *, split: str, query_limit: int | None = None) -> dict[str, Any]:
    """Read BEIR JSONL/TSV files and evaluate all judged queries in ID order."""
    if split not in {"train", "dev", "test"}:
        raise ValueError("split must be train, dev, or test")
    if query_limit is not None and query_limit <= 0:
        raise ValueError("query_limit must be positive")
    corpus_path = dataset / "corpus.jsonl"
    queries_path = dataset / "queries.jsonl"
    qrels_path = dataset / "qrels" / f"{split}.tsv"
    articles: dict[str, UnifiedArticle] = {}
    with corpus_path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            doc_id = str(row["_id"])
            if doc_id in articles:
                raise ValueError(f"Duplicate corpus ID: {doc_id}")
            articles[doc_id] = UnifiedArticle(
                title=row.get("title", ""), abstract=row.get("text", ""), primary_source="benchmark"
            )
    with queries_path.open(encoding="utf-8") as stream:
        queries = {str(row["_id"]): row["text"] for row in map(json.loads, stream)}
    judgments: dict[str, dict[str, int]] = {}
    with qrels_path.open(encoding="utf-8") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            query_id, doc_id = row["query-id"], row["corpus-id"]
            if query_id not in queries or doc_id not in articles:
                raise ValueError(f"Judgment references missing query/document: {query_id}/{doc_id}")
            judgments.setdefault(query_id, {})[doc_id] = int(row["score"])
    if not judgments or not articles:
        raise ValueError("Dataset must contain documents and judged queries")

    corpus = BM25Corpus.from_articles(list(articles.values()))
    query_ids = sorted(judgments)[:query_limit]
    per_query: dict[str, dict[str, Any]] = {}
    for query_id in query_ids:
        # Sorting IDs resolves equal scores reproducibly, independent of file order.
        scores = [(doc_id, bm25_score(article, queries[query_id], corpus)) for doc_id, article in articles.items()]
        ranked_ids = [doc_id for doc_id, _ in sorted(scores, key=lambda item: (-item[1], item[0]))[:100]]
        metrics = {
            **evaluate_ranking(ranked_ids, judgments[query_id], k=10),
            **evaluate_ranking(ranked_ids, judgments[query_id], k=100),
        }
        per_query[query_id] = {"metrics": metrics, "ranked_ids": ranked_ids}

    metric_names = next(iter(per_query.values()))["metrics"]
    return {
        "schema_version": 1,
        "evaluation": "production_bm25_full_corpus_component",
        "ndcg_gain": "linear",
        "unjudged_policy": "zero_gain",
        "split": split,
        "corpus_size": len(articles),
        "query_count": len(query_ids),
        "query_limit": query_limit,
        "sha256": {
            str(path.relative_to(dataset)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (corpus_path, queries_path, qrels_path)
        },
        "metrics": {
            name: sum(result["metrics"][name] for result in per_query.values()) / len(per_query)
            for name in metric_names
        },
        "per_query": per_query,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--split", choices=("train", "dev", "test"), default="dev")
    parser.add_argument("--query-limit", type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run_benchmark(args.dataset, split=args.split, query_limit=args.query_limit)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "per_query"}, indent=2))


if __name__ == "__main__":
    main()
