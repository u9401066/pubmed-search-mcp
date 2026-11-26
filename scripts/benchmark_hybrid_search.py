"""Compare PubMed Best Match, default unified_search and hybrid search on live providers.

Usage:
    uv run python scripts/benchmark_hybrid_search.py --output build/hybrid-benchmark.json

Each topic is a published systematic review. Gold records are the primary
studies in its PubMed reference list (``pubmed_pubmed_refs``), a proxy for the
review's included studies. Every arm searches up to the review's publication
year and the review itself is removed from each ranking.

Arms, for a MeSH-style query and for a plain-language question:

* ``pubmed``  PubMed Best Match alone (what a PubMed-only tool returns)
* ``default`` ``unified_search`` as shipped
* ``hybrid``  ``unified_search(options="hybrid")``
* ``hybrid_quota``  hybrid with the opt-in breadth quota

This measures retrieval only. It makes live NCBI, Europe PMC and OpenAlex
requests and no LLM call. Six topics is a pilot: report per-topic numbers and
do not read small mean differences as effects.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

from pubmed_search.api import PubMedSearchClient, PubMedSearchConfig
from pubmed_search.application.search.retrieval_metrics import evaluate_ranking

DEFAULT_TOPICS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "hybrid_benchmark" / "topics.json"
CUTOFFS = (10, 20, 50)
DEPTH = max(CUTOFFS)
MIN_GOLD = 5
ARMS = ("pubmed", "default", "hybrid", "hybrid_quota")
ARM_OPTIONS = {"default": "no_oa", "hybrid": "hybrid,no_oa", "hybrid_quota": "hybrid,breadth_quota,no_oa"}
QUERY_STYLES = {"mesh": "pubmed_query", "question": "question"}
#: Publication types that are not primary studies and so cannot be a review's included study.
SECONDARY_TYPES = frozenset(
    {
        "review",
        "systematic review",
        "meta-analysis",
        "network meta-analysis",
        "practice guideline",
        "guideline",
        "editorial",
        "comment",
        "letter",
        "news",
        "published erratum",
        "retraction of publication",
        "consensus development conference",
    }
)


def primary_study_pmids(references: list[dict[str, Any]], *, max_year: int) -> list[str]:
    """Return reference PMIDs that are primary studies published by ``max_year``."""
    gold: list[str] = []
    for row in references:
        pmid = str(row.get("pmid") or "").strip()
        types = {str(item).casefold() for item in row.get("publication_types") or ()}
        year = str(row.get("year") or "")
        if not pmid or types & SECONDARY_TYPES:
            continue
        if year.isdigit() and int(year) > max_year:
            continue
        if pmid not in gold:
            gold.append(pmid)
    return gold


def ranking_ids(records: list[Any], *, exclude: str) -> list[str]:
    """Return unique ranking ids (PMID when known) in order, without the review itself."""
    ids: list[str] = []
    for index, record in enumerate(records):
        pmid = record.get("pmid") if isinstance(record, dict) else getattr(record, "pmid", None)
        doi = record.get("doi") if isinstance(record, dict) else getattr(record, "doi", None)
        identifier = str(pmid) if pmid else f"doi:{doi}" if doi else f"unidentified:{index}"
        if identifier != exclude and identifier not in ids:
            ids.append(identifier)
    return ids


def score(ranked: list[str], gold: list[str]) -> dict[str, float]:
    judgments = dict.fromkeys(gold, 1)
    metrics: dict[str, float] = {}
    for cutoff in CUTOFFS:
        result = evaluate_ranking(ranked, judgments, k=cutoff)
        metrics[f"recall@{cutoff}"] = round(result[f"recall@{cutoff}"], 4)
        metrics[f"ndcg@{cutoff}"] = round(result[f"ndcg@{cutoff}"], 4)
    metrics["gold_found"] = float(len(set(ranked[:DEPTH]) & set(gold)))
    return metrics


async def _run_arm(client: PubMedSearchClient, arm: str, query: str, topic: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    review = str(topic["review_pmid"])
    max_year = int(topic["max_year"])
    extra: dict[str, Any] = {}
    try:
        if arm == "pubmed":
            page = await client.search_pubmed_page(query, limit=DEPTH, max_year=max_year, detail_level="summary")
            ranked = ranking_ids(list(page.items), exclude=review)
        else:
            result = await client.unified_search(
                query,
                limit=DEPTH,
                filters=f"year:-{max_year}",
                options=ARM_OPTIONS[arm],
            )
            ranked = ranking_ids(list(result.articles), exclude=review)
            extra["sources"] = {row.source: row.returned for row in result.source_counts}
            extra["source_errors"] = [str(error.get("source")) for error in result.source_errors]
            extra["source_error_details"] = [
                {
                    "source": str(error.get("source")),
                    "code": str(error.get("code") or error.get("kind") or "unknown"),
                    "status_code": error.get("status_code"),
                }
                for error in result.source_errors
            ]
            if result.hybrid:
                extra["hybrid"] = result.hybrid
                extra["breadth_only_ids"] = [
                    str(article.pmid)
                    for article in result.articles
                    if article.channels and not article.found_by("pubmed")
                ]
    except Exception as exc:  # A failed arm is a result, not a reason to lose the run.
        return {"status": "error", "error": type(exc).__name__, "seconds": round(time.perf_counter() - started, 2)}
    return {"status": "ok", "ranked": ranked, "seconds": round(time.perf_counter() - started, 2), **extra}


async def run_topic(client: PubMedSearchClient, topic: dict[str, Any]) -> dict[str, Any]:
    references = await client.searcher.get_article_references(str(topic["review_pmid"]), limit=500)
    gold = primary_study_pmids(references, max_year=int(topic["max_year"]))
    row: dict[str, Any] = {
        "id": topic["id"],
        "review_pmid": topic["review_pmid"],
        "references": len(references),
        "gold": gold,
        "arms": {},
    }
    if len(gold) < MIN_GOLD:
        row["skipped"] = f"only {len(gold)} primary-study references in PubMed"
        return row
    for style, field in QUERY_STYLES.items():
        for arm in ARMS:
            outcome = await _run_arm(client, arm, str(topic[field]), topic)
            if outcome["status"] == "ok":
                outcome["metrics"] = score(outcome["ranked"], gold)
                breadth = set(outcome.pop("breadth_only_ids", []))
                if arm.startswith("hybrid"):
                    outcome["metrics"]["gold_found_breadth_only"] = float(len(breadth & set(gold)))
            row["arms"][f"{style}:{arm}"] = outcome
            await asyncio.sleep(1.0)
    return row


def summarize(topics: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Mean of each metric per arm over topics where every arm completed."""
    arm_names = [f"{style}:{arm}" for style in QUERY_STYLES for arm in ARMS]
    complete = [
        topic
        for topic in topics
        if not topic.get("skipped") and all(topic["arms"].get(name, {}).get("status") == "ok" for name in arm_names)
    ]
    summary: dict[str, dict[str, float]] = {}
    for name in arm_names:
        rows = [topic["arms"][name] for topic in complete]
        if not rows:
            continue
        keys = sorted({key for row in rows for key in row["metrics"]})
        summary[name] = {key: round(statistics.fmean(row["metrics"].get(key, 0.0) for row in rows), 4) for key in keys}
        summary[name]["seconds"] = round(statistics.fmean(row["seconds"] for row in rows), 2)
        summary[name]["topics"] = float(len(rows))
    return summary


def to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "## Hybrid search retrieval benchmark",
        "",
        f"Topics scored: {report['topics_scored']} of {report['topics_total']} (pilot; proxy gold = primary studies "
        "cited by each review).",
        "",
        "| Query | Arm | recall@10 | recall@20 | recall@50 | nDCG@20 | gold found (top 50) | sec |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, metrics in report["summary"].items():
        style, arm = name.split(":")
        lines.append(
            f"| {style} | {arm} | {metrics['recall@10']:.3f} | {metrics['recall@20']:.3f} | "
            f"{metrics['recall@50']:.3f} | {metrics['ndcg@20']:.3f} | {metrics['gold_found']:.1f} | "
            f"{metrics['seconds']:.1f} |"
        )
    failures: dict[str, int] = {}
    fallbacks = 0
    for topic in report["topics"]:
        for arm in topic.get("arms", {}).values():
            for detail in arm.get("source_error_details", []):
                key = f"{detail['source']}: {detail['code']}" + (
                    f" (HTTP {detail['status_code']})" if detail.get("status_code") else ""
                )
                failures[key] = failures.get(key, 0) + 1
            queries = (arm.get("hybrid") or {}).get("modes") or {}
            fallbacks += sum(1 for mode in queries.values() if mode == "keyword_fallback")
    lines += ["", "### Channel failures (all arms)", ""]
    lines += [f"- {key}: {count}" for key, count in sorted(failures.items())] or ["- none"]
    lines.append(f"- semantic channel fell back to keyword search: {fallbacks}")
    lines += ["", "### Per topic (recall@20 / gold found in top 50)", ""]
    arm_names = list(report["summary"]) or [f"{style}:{arm}" for style in QUERY_STYLES for arm in ARMS]
    lines.append("| Topic | gold | " + " | ".join(arm_names) + " |")
    lines.append("|---|---|" + "---|" * len(arm_names))
    for topic in report["topics"]:
        if topic.get("skipped"):
            lines.append(f"| {topic['id']} | {len(topic['gold'])} | skipped: {topic['skipped']} |")
            continue
        cells = []
        for name in arm_names:
            arm = topic["arms"].get(name, {})
            if arm.get("status") != "ok":
                cells.append(f"error: {arm.get('error', 'missing')}")
            else:
                cell = f"{arm['metrics']['recall@20']:.2f} / {int(arm['metrics']['gold_found'])}"
                if arm.get("source_errors"):
                    cell += f" (failed: {', '.join(arm['source_errors'])})"
                cells.append(cell)
        lines.append(f"| {topic['id']} | {len(topic['gold'])} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


async def run(topics_path: Path, *, email: str, api_key: str | None) -> dict[str, Any]:
    topics = json.loads(topics_path.read_text(encoding="utf-8"))["topics"]
    rows: list[dict[str, Any]] = []
    async with PubMedSearchClient(PubMedSearchConfig(email=email, api_key=api_key)) as client:
        for topic in topics:
            print(f"Topic {topic['id']}...", flush=True)
            try:
                rows.append(await run_topic(client, topic))
            except Exception as exc:
                rows.append(
                    {"id": topic["id"], "gold": [], "arms": {}, "skipped": f"gold lookup failed: {type(exc).__name__}"}
                )
    summary = summarize(rows)
    return {
        "schema_version": 1,
        "evaluation": "hybrid_search_retrieval_pilot",
        "gold": "primary-study references of each review (proxy for included studies)",
        "depth": DEPTH,
        "topics_total": len(rows),
        "topics_scored": int(next(iter(summary.values()))["topics"]) if summary else 0,
        "summary": summary,
        "topics": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--topics", type=Path, default=DEFAULT_TOPICS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(
        run(
            args.topics,
            email=os.environ.get("NCBI_EMAIL", "pubmed-search@example.com"),
            api_key=os.environ.get("NCBI_API_KEY") or None,
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown = to_markdown(report)
    args.output.with_suffix(".md").write_text(markdown, encoding="utf-8")
    print(markdown)
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(markdown)


if __name__ == "__main__":
    main()
