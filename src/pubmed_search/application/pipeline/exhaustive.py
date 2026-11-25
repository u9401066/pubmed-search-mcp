"""Exhaustive PubMed retrieval for systematic-review pipeline search steps.

A bounded relevance window (``limit`` <= 100) cannot support screening or a
PRISMA flow diagram. ``retrieval: exhaustive`` instead creates one PubMed
History Server snapshot, pages through *every* PMID in that snapshot, and
optionally materializes bibliographic metadata in EFetch batches so the run's
full record set can be exported and screened.

Every provider operation (ESearch snapshot, each PMID page, each metadata
batch) reserves one unit of the pipeline run budget before any I/O. The
complete PMID set is required for an exhaustive claim: a run that stops early
is reported as incomplete instead of being persisted as if it were the full
search result. Metadata is a convenience layer — when the budget runs out
during metadata batches the identifier set remains complete and the missing
metadata is disclosed (and can be fetched again at export time). The run
deadline is treated the same way: metadata stops (an in-flight batch is
cancelled) ``PIPELINE_EXHAUSTIVE_FINALIZE_SECONDS`` before the deadline, so
the scheduler never cancels a step that already holds its complete PMID set.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pubmed_search.application.pipeline.budgets import (
    PIPELINE_EXHAUSTIVE_FINALIZE_SECONDS,
    PIPELINE_EXHAUSTIVE_METADATA_BATCH,
    PIPELINE_EXHAUSTIVE_PAGE_SIZE,
    PipelineBudgetExceededError,
)

PUBMED_DATABASE = "PubMed"
PUBMED_PLATFORM = "NCBI E-utilities (ESearch History Server + EFetch)"
SEARCH_FILTER_KEYS = ("min_year", "max_year", "age_group", "sex", "species", "language", "clinical_query")

ReserveCall = Callable[[], Awaitable[None]]
RemainingSeconds = Callable[[], float]


class ExhaustiveCapExceededError(ValueError):
    """The PubMed count is above the disclosed exhaustive safety cap."""

    def __init__(self, total_count: int, cap: int, snapshot: dict[str, Any]) -> None:
        self.total_count = total_count
        self.cap = cap
        self.snapshot = snapshot
        super().__init__(
            f"PubMed reports {total_count} records, above the exhaustive retrieval cap of {cap}; "
            "narrow the strategy (e.g. add date limits) or split it into several saved pipelines"
        )


class ExhaustiveRetrievalIncompleteError(RuntimeError):
    """The complete PMID set could not be collected; nothing is claimed as exhaustive."""

    def __init__(self, reason: str, *, total_count: int, retrieved: int, snapshot: dict[str, Any]) -> None:
        self.reason = reason
        self.total_count = total_count
        self.retrieved = retrieved
        self.snapshot = snapshot
        super().__init__(
            f"Exhaustive PubMed retrieval stopped after {retrieved} of {total_count} PMIDs ({reason}); "
            "no partial set is reported as complete"
        )


@dataclass
class ExhaustiveRetrieval:
    """Outcome of one exhaustive PubMed retrieval."""

    snapshot: dict[str, Any]
    total_count: int
    pmids: list[str]
    cap: int
    pages: int
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata_requested: bool = True
    metadata_batches: int = 0
    metadata_error: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def exhaustive(self) -> bool:
        """Whether every PMID PubMed counted was collected exactly once."""
        return len(self.pmids) == self.total_count

    @property
    def metadata_count(self) -> int:
        return sum(1 for pmid in self.pmids if pmid in self.records)

    def stop_metadata(self, error: dict[str, Any], warning: str) -> None:
        """Record why metadata stopped; the identifier set is unaffected."""
        self.metadata_error = error
        self.warnings.append(warning)

    @property
    def metadata_complete(self) -> bool:
        return self.metadata_count == len(self.pmids)

    def summary(self) -> dict[str, Any]:
        """Return query-safe, bounded metadata for responses and run records."""
        return {
            "mode": "exhaustive",
            "database": PUBMED_DATABASE,
            "platform": PUBMED_PLATFORM,
            "total_count": self.total_count,
            "retrieved_count": len(self.pmids),
            "exhaustive": self.exhaustive,
            "cap": self.cap,
            "history_pages": self.pages,
            "metadata_requested": self.metadata_requested,
            "metadata_count": self.metadata_count,
            "metadata_complete": self.metadata_complete if self.metadata_requested else False,
            "metadata_batches": self.metadata_batches,
            "metadata_error": dict(self.metadata_error) if self.metadata_error is not None else None,
            "warnings": list(self.warnings),
        }


def _require_snapshot(value: object) -> dict[str, Any]:
    """Validate the provider snapshot contract at the application boundary."""
    if not isinstance(value, dict):
        raise TypeError("PubMed history snapshot must be a mapping")
    count = value.get("count")
    pmids = value.get("pmids")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise TypeError("PubMed history snapshot contains an invalid count")
    if not isinstance(pmids, list) or any(not isinstance(pmid, str) or not pmid.isdigit() for pmid in pmids):
        raise TypeError("PubMed history snapshot contains invalid PMIDs")
    if len(pmids) > count:
        raise TypeError("PubMed history snapshot returned more PMIDs than its count")
    return value


def _require_pmid_page(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(pmid, str) or not pmid.isdigit() for pmid in value):
        raise TypeError("PubMed history page contains invalid PMIDs")
    return value


def _require_metadata_rows(value: object, expected: list[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise TypeError("PubMed metadata batch must be a list")
    expected_set = set(expected)
    rows: dict[str, dict[str, Any]] = {}
    for row in value:
        if not isinstance(row, dict):
            raise TypeError("PubMed metadata batch contains an invalid row")
        pmid = str(row.get("pmid") or "").strip()
        if pmid not in expected_set:
            raise TypeError("PubMed metadata batch returned an unexpected PMID")
        rows[pmid] = row
    return rows


def search_filters(params: dict[str, Any]) -> dict[str, Any]:
    """Return the PubMed filter parameters a search step actually applied."""
    return {key: params[key] for key in SEARCH_FILTER_KEYS if params.get(key) is not None}


def _consume_outcome(task: asyncio.Future[Any]) -> None:
    if not task.cancelled():
        task.exception()


async def _finished_within(awaitable: Awaitable[Any], timeout: float | None) -> tuple[bool, Any]:
    """Await ``awaitable`` for at most ``timeout`` seconds; ``(False, None)`` if it was cut off.

    Unlike ``wait_for``, a provider's own ``TimeoutError`` stays a provider
    failure, and the unfinished call is cancelled rather than left running.
    """
    if timeout is None:
        return True, await awaitable
    task = asyncio.ensure_future(awaitable)
    try:
        done, _pending = await asyncio.wait({task}, timeout=max(0.0, timeout))
    except BaseException:
        task.cancel()
        task.add_done_callback(_consume_outcome)
        raise
    if not done:
        task.cancel()
        task.add_done_callback(_consume_outcome)
        return False, None
    return True, task.result()


async def retrieve_pubmed_exhaustive(
    searcher: Any,
    query: str,
    *,
    filters: dict[str, Any],
    max_records: int,
    reserve_call: ReserveCall,
    fetch_metadata: bool = True,
    page_size: int = PIPELINE_EXHAUSTIVE_PAGE_SIZE,
    metadata_batch_size: int = PIPELINE_EXHAUSTIVE_METADATA_BATCH,
    remaining_seconds: RemainingSeconds | None = None,
    finalize_seconds: float = PIPELINE_EXHAUSTIVE_FINALIZE_SECONDS,
) -> ExhaustiveRetrieval:
    """Collect every PMID for ``query`` from one History Server snapshot.

    ``remaining_seconds`` reports the run deadline. Once every PMID is held,
    metadata only runs while more than ``finalize_seconds`` remain; a batch
    still in flight at that point is cancelled and disclosed as
    ``metadata_error={"kind": "deadline", ...}`` with the complete set kept.

    Raises:
        ExhaustiveCapExceededError: PubMed's count is above ``max_records``.
        ExhaustiveRetrievalIncompleteError: paging stopped before all PMIDs
            were collected (budget, deadline, or an inconsistent provider page).
    """
    if page_size < 1 or metadata_batch_size < 1:
        raise ValueError("page_size and metadata_batch_size must be positive")

    await reserve_call()
    snapshot = _require_snapshot(
        await searcher.esearch_snapshot(query, retmax=min(page_size, max_records), use_history=True, **filters)
    )
    total_count = int(snapshot["count"])
    public_snapshot = {key: value for key, value in snapshot.items() if key not in {"pmids", "webenv", "query_key"}}
    if total_count > max_records:
        raise ExhaustiveCapExceededError(total_count, max_records, public_snapshot)

    pmids = list(dict.fromkeys(snapshot["pmids"]))
    seen = set(pmids)
    # History offsets count provider rows, not unique PMIDs.
    offset = len(snapshot["pmids"])
    pages = 1
    warnings: list[str] = []
    webenv = snapshot.get("webenv")
    query_key = snapshot.get("query_key")
    while offset < total_count:
        if not isinstance(webenv, str) or not isinstance(query_key, str):
            raise ExhaustiveRetrievalIncompleteError(
                "missing_history_keys", total_count=total_count, retrieved=len(pmids), snapshot=public_snapshot
            )
        try:
            await reserve_call()
        except PipelineBudgetExceededError as exc:
            raise ExhaustiveRetrievalIncompleteError(
                exc.reason, total_count=total_count, retrieved=len(pmids), snapshot=public_snapshot
            ) from None
        page = _require_pmid_page(
            await searcher.fetch_history_pmids(
                webenv,
                query_key,
                retstart=offset,
                retmax=min(page_size, total_count - offset),
            )
        )
        pages += 1
        if not page:
            break
        offset += len(page)
        for pmid in page:
            if pmid not in seen:
                seen.add(pmid)
                pmids.append(pmid)

    if len(pmids) != total_count:
        raise ExhaustiveRetrievalIncompleteError(
            "provider_count_mismatch", total_count=total_count, retrieved=len(pmids), snapshot=public_snapshot
        )

    retrieval = ExhaustiveRetrieval(
        snapshot=public_snapshot,
        total_count=total_count,
        pmids=pmids,
        cap=max_records,
        pages=pages,
        metadata_requested=fetch_metadata,
        warnings=warnings,
    )
    if not fetch_metadata:
        return retrieval

    def stop_for_deadline() -> None:
        retrieval.stop_metadata(
            {"kind": "deadline", "terminal_reason": "deadline_exhausted", "retryable": True},
            f"Metadata stopped after {retrieval.metadata_count} of {len(pmids)} records (run deadline); "
            "the PMID set is complete and export fetches the remaining metadata on demand",
        )

    for start in range(0, len(pmids), metadata_batch_size):
        batch = pmids[start : start + metadata_batch_size]
        window = None if remaining_seconds is None else remaining_seconds() - finalize_seconds
        if window is not None and window <= 0:
            stop_for_deadline()
            break
        try:
            await reserve_call()
        except PipelineBudgetExceededError as exc:
            retrieval.stop_metadata(
                {"kind": "budget", "terminal_reason": exc.reason, "retryable": True},
                f"Metadata stopped after {retrieval.metadata_count} of {len(pmids)} records ({exc.reason}); "
                "the PMID set is complete and export fetches the remaining metadata on demand",
            )
            break
        try:
            finished, payload = await _finished_within(searcher.fetch_details(batch), window)
            if not finished:
                stop_for_deadline()
                break
            rows = _require_metadata_rows(payload, batch)
        except Exception as exc:  # metadata is recoverable at export time; identifiers stay complete
            retrieval.stop_metadata(
                {"kind": "provider", "error_type": type(exc).__name__, "retryable": True},
                f"Metadata batch failed after {retrieval.metadata_count} of {len(pmids)} records "
                f"({type(exc).__name__}); export fetches the remaining metadata on demand",
            )
            break
        retrieval.metadata_batches += 1
        retrieval.records.update(rows)
    return retrieval


__all__ = [
    "PUBMED_DATABASE",
    "PUBMED_PLATFORM",
    "SEARCH_FILTER_KEYS",
    "ExhaustiveCapExceededError",
    "ExhaustiveRetrieval",
    "ExhaustiveRetrievalIncompleteError",
    "retrieve_pubmed_exhaustive",
    "search_filters",
]
