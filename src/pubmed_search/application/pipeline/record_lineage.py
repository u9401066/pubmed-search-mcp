"""Which steps feed a pipeline run's final record set, and what that set claims.

A run persists one record set (its final step) and makes two claims about it:
whether it is the *complete* result of its searches (``retrieval.exhaustive``)
and how many records its searches *identified* (the PRISMA identification
count). Both claims must describe the records that actually reach the final
step, not whatever else the DAG happened to run.

Records flow from **source** steps (``search``, ``details``, ``related``,
``citing``, ``references``) through **pass-through** steps (``merge``,
``filter``, ``metrics``) into the final step. :func:`record_lineage` walks that
flow backwards from the final step:

* every source on the way is upstream of the final set; one bounded source
  makes the whole set ``mixed`` and never exhaustive, while a bounded search
  that only feeds an analysis step (or nothing) does not;
* the identification set is the final set re-evaluated with every ``filter``
  step keeping all of its input, i.e. the records the searches (and merges)
  produced before pipeline filters marked some ineligible.

Filters cannot judge a record whose bibliographic metadata was never fetched
(an exhaustive step with ``fetch_metadata: false`` or interrupted metadata);
:func:`article_lacks_metadata` identifies those so filters keep them and
report ``metadata_missing`` instead of dropping them silently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pubmed_search.domain.entities.pipeline import PipelineStep, StepResult

FINAL_STEP_METADATA_KEY = "pipeline_final_step"
RECORD_LINEAGE_METADATA_KEY = "record_lineage"
RECORD_SOURCE_ACTIONS = frozenset({"search", "details", "related", "citing", "references"})
RECORD_PASS_THROUGH_ACTIONS = frozenset({"merge", "filter", "metrics"})


def is_exhaustive_step(result: StepResult) -> bool:
    """Whether a step ran PubMed exhaustive retrieval (successfully or not)."""
    retrieval = result.metadata.get("retrieval")
    return isinstance(retrieval, dict) and retrieval.get("mode") == "exhaustive"


def final_record_set(step_results: Mapping[str, StepResult]) -> tuple[str | None, list[str]]:
    """Return the final step ID and its complete PMID set before ranking/limits."""
    for step_id, result in step_results.items():
        if result.metadata.get(FINAL_STEP_METADATA_KEY) is True:
            if not result.ok:
                return step_id, []
            return step_id, list(dict.fromkeys(result.pmids or [a.pmid for a in result.articles if a.pmid]))
    return None, []


def collected_records(step_results: Mapping[str, StepResult]) -> dict[str, dict[str, Any]]:
    """Merge provider-native records gathered by exhaustive steps, keyed by PMID."""
    records: dict[str, dict[str, Any]] = {}
    for result in step_results.values():
        for pmid, row in result.records.items():
            records.setdefault(pmid, row)
    return records


def article_lacks_metadata(article: Any) -> bool:
    """Whether an article is an identifier-only placeholder (no bibliographic metadata)."""
    return not str(getattr(article, "title", "") or "").strip()


def record_lineage(
    steps: Sequence[PipelineStep],
    results: Mapping[str, StepResult],
    final_step_id: str,
) -> dict[str, Any]:
    """Return the source/pass-through steps feeding ``final_step_id`` and its identification count."""
    by_id = {step.id: step for step in steps}
    sources: dict[str, None] = {}
    pass_through: dict[str, None] = {}
    memo: dict[str, list[str]] = {}

    def unfiltered(step_id: str) -> list[str]:
        if step_id in memo:
            return memo[step_id]
        memo[step_id] = []  # the validated DAG is acyclic; this only guards re-entry
        step, result = by_id.get(step_id), results.get(step_id)
        if step is None or result is None:
            return []
        if step.action not in RECORD_PASS_THROUGH_ACTIONS:
            sources[step_id] = None
            pmids = list(dict.fromkeys(result.pmids)) if result.ok else []
        else:
            pass_through[step_id] = None
            # Failed inputs contribute no records but stay in the lineage, so a
            # failed exhaustive source still makes the final set incomplete.
            input_sets = [unfiltered(input_id) for input_id in step.inputs]
            usable = [
                pmids
                for input_id, pmids in zip(step.inputs, input_sets, strict=True)
                if results.get(input_id) is not None and results[input_id].ok
            ]
            if not result.ok or not usable:
                pmids = []
            elif step.action == "merge" and step.params.get("method") == "intersection":
                common = set(usable[0]).intersection(*usable[1:])
                pmids = [pmid for pmid in usable[0] if pmid in common]
            else:
                pmids = list(dict.fromkeys(pmid for input_pmids in usable for pmid in input_pmids))
        memo[step_id] = pmids
        return pmids

    identified = unfiltered(final_step_id)
    final = results.get(final_step_id)
    final_pmids = (
        [pmid for pmid in [*final.pmids, *(a.pmid for a in final.articles)] if pmid] if final and final.ok else []
    )
    return {
        "final_step": final_step_id,
        "source_steps": list(sources),
        "pass_through_steps": list(pass_through),
        "identified_count": len(set(identified).union(final_pmids)),
    }


def _exhaustive_row(step_id: str, result: StepResult) -> dict[str, Any]:
    retrieval = dict(result.metadata.get("retrieval") or {})
    return {
        "step_id": step_id,
        "total_count": retrieval.get("total_count"),
        "retrieved_count": retrieval.get("retrieved_count"),
        "exhaustive": bool(retrieval.get("exhaustive")) and result.ok,
        "cap": retrieval.get("cap"),
        "metadata_count": retrieval.get("metadata_count"),
        "metadata_complete": retrieval.get("metadata_complete"),
        "metadata_error": retrieval.get("metadata_error"),
        "terminal_reason": retrieval.get("terminal_reason"),
    }


def _bounded_row(step_id: str, result: StepResult) -> dict[str, Any]:
    retrieval = dict(result.metadata.get("retrieval") or {})
    totals: list[int] = []
    for provider in dict(result.metadata.get("source_results") or {}).values():
        total = provider.get("total_count") if isinstance(provider, dict) else None
        if isinstance(total, int) and not isinstance(total, bool):
            totals.append(total)
    return {
        "step_id": step_id,
        "action": result.action,
        "limit": retrieval.get("limit"),
        "retrieved_count": len(dict.fromkeys(result.pmids)),
        "total_count": max(totals) if totals else None,
        "ok": result.ok,
    }


def retrieval_summary(step_results: Mapping[str, StepResult], record_count: int) -> dict[str, Any]:
    """Summarize retrieval completeness of the searches that feed the final record set.

    ``mode`` is ``exhaustive`` when every upstream source is an exhaustive
    PubMed step, ``mixed`` when bounded sources also feed the final set, and
    ``bounded`` otherwise. ``exhaustive`` is true only for ``mode ==
    "exhaustive"`` with every upstream exhaustive step complete.
    """
    final_step_id, _pmids = final_record_set(step_results)
    lineage = step_results[final_step_id].metadata.get(RECORD_LINEAGE_METADATA_KEY) if final_step_id else None
    if isinstance(lineage, dict):
        source_ids = [step_id for step_id in lineage.get("source_steps") or [] if step_id in step_results]
        filter_ids = [
            step_id
            for step_id in lineage.get("pass_through_steps") or []
            if step_id in step_results and step_results[step_id].action == "filter"
        ]
    else:  # no lineage recorded: every source in the run counts as upstream
        source_ids = [
            step_id
            for step_id, result in step_results.items()
            if result.action in RECORD_SOURCE_ACTIONS or is_exhaustive_step(result)
        ]
        filter_ids = [step_id for step_id, result in step_results.items() if result.action == "filter"]

    exhaustive_steps = [
        _exhaustive_row(step_id, step_results[step_id])
        for step_id in source_ids
        if is_exhaustive_step(step_results[step_id])
    ]
    bounded_steps = [
        _bounded_row(step_id, step_results[step_id])
        for step_id in source_ids
        if not is_exhaustive_step(step_results[step_id])
    ]
    unused_exhaustive = [
        step_id for step_id, result in step_results.items() if is_exhaustive_step(result) and step_id not in source_ids
    ]
    warnings: list[str] = []
    if not exhaustive_steps:
        summary: dict[str, Any] = {"mode": "bounded", "exhaustive": False, "record_count": record_count}
        if unused_exhaustive:
            warnings.append(
                f"Exhaustive step(s) {', '.join(unused_exhaustive)} do not feed the final record set; "
                "it is not a complete record set"
            )
            summary["warnings"] = warnings
        return summary

    mode = "mixed" if bounded_steps else "exhaustive"
    if bounded_steps:
        warnings.append(
            f"The final record set combines exhaustive PubMed retrieval with bounded step(s) "
            f"{', '.join(row['step_id'] for row in bounded_steps)}; it is not a complete record set and is not "
            "registered as complete identification"
        )
    for row in exhaustive_steps:
        if not row["exhaustive"]:
            warnings.append(
                f"Exhaustive step {row['step_id']} did not collect its complete PMID set "
                f"({row['terminal_reason'] or 'step failed'}); the record set is incomplete"
            )
    for step_id in filter_ids:
        missing = step_results[step_id].metadata.get("metadata_missing")
        if isinstance(missing, dict) and missing.get("count"):
            warnings.append(
                f"Filter step {step_id} kept {missing['count']} records without metadata that it could not evaluate"
            )
    summary = {
        "mode": mode,
        "exhaustive": mode == "exhaustive" and all(row["exhaustive"] for row in exhaustive_steps),
        "record_count": record_count,
        "steps": exhaustive_steps,
    }
    if bounded_steps:
        summary["bounded_steps"] = bounded_steps
    if isinstance(lineage, dict) and isinstance(lineage.get("identified_count"), int):
        identified = max(int(lineage["identified_count"]), record_count)
        summary["identified_count"] = identified
        summary["removed_by_filters"] = identified - record_count
    if len(exhaustive_steps) == 1:
        only = exhaustive_steps[0]
        summary.update(
            {
                "total_count": only["total_count"],
                "retrieved_count": only["retrieved_count"],
                "metadata_count": only["metadata_count"],
            }
        )
    if warnings:
        summary["warnings"] = warnings
    return summary


__all__ = [
    "FINAL_STEP_METADATA_KEY",
    "RECORD_LINEAGE_METADATA_KEY",
    "RECORD_PASS_THROUGH_ACTIONS",
    "RECORD_SOURCE_ACTIONS",
    "article_lacks_metadata",
    "collected_records",
    "final_record_set",
    "is_exhaustive_step",
    "record_lineage",
    "retrieval_summary",
]
