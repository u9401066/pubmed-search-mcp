"""Export a persisted pipeline run's complete record set.

Screening tools (Rayyan, Covidence) and reference managers (Zotero, EndNote)
need every identified record, not the ranked preview a pipeline response
shows. This service reads the run's persisted record artifact, fills metadata
that was not materialized during the run (bounded, on demand), and formats the
records with the shared application export layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pubmed_search.application.export import export_articles, export_csl_json

if TYPE_CHECKING:
    from pubmed_search.application.pipeline.store import PipelineStore
    from pubmed_search.domain.entities.pipeline import PipelineRun

PIPELINE_RUN_EXPORT_FORMATS = ("ris", "csv", "csl", "bibtex", "medline", "json")
# Records whose metadata may be fetched during one export call (batches of 200).
MAX_EXPORT_METADATA_BACKFILL = 2_000
_BACKFILL_BATCH = 200
_RUN_REF_RE = re.compile(r"^(?P<name>[a-z0-9][a-z0-9_-]{0,63})(?:@(?P<run>[A-Za-z0-9][A-Za-z0-9_.-]{0,127}))?$")


@dataclass
class RunExport:
    """Formatted export plus completeness disclosure.

    ``complete_record_set`` is true only for a run that persisted its full
    final-step set (``record_basis == "final_step_full"``) from exhaustive
    retrieval; a ranked preview, a mixed or an incomplete run is exported
    with ``warnings`` saying why it is not the systematic-review record set.
    """

    pipeline_name: str
    run_id: str
    content: str
    format: str
    record_count: int
    metadata_missing: list[str] = field(default_factory=list)
    backfilled: int = 0
    backfill_error: str | None = None
    record_basis: str = "ranked_output"
    retrieval_mode: str | None = None
    exhaustive: bool = False
    run_status: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def complete_record_set(self) -> bool:
        return self.record_basis == "final_step_full" and self.exhaustive

    def summary(self) -> dict[str, Any]:
        return {
            "pipeline": self.pipeline_name,
            "run_id": self.run_id,
            "run_status": self.run_status,
            "record_count": self.record_count,
            "record_basis": self.record_basis,
            "retrieval_mode": self.retrieval_mode,
            "exhaustive": self.exhaustive,
            "complete_record_set": self.complete_record_set,
            "warnings": list(self.warnings),
            "records_with_metadata": self.record_count - len(self.metadata_missing),
            "metadata_missing_count": len(self.metadata_missing),
            "metadata_missing_preview": self.metadata_missing[:20],
            "metadata_backfilled": self.backfilled,
            "metadata_backfill_error": self.backfill_error,
        }


def _completeness_warnings(run: PipelineRun) -> list[str]:
    """Explain why a run's persisted records are not a complete record set."""
    retrieval = run.retrieval or {}
    if run.record_basis != "final_step_full":
        return [
            f"This run persisted only its ranked preview ({len(run.pmids)} records, record_basis "
            f"{run.record_basis}); it is not the complete search result. Use a saved pipeline with "
            "retrieval: exhaustive for a complete record set."
        ]
    if retrieval.get("exhaustive") is True:
        return []
    detail = list(retrieval.get("warnings") or [])
    return [
        f"This run's record set is not complete (retrieval mode {retrieval.get('mode') or 'unknown'}); "
        "do not report it as the complete search result.",
        *detail,
    ]


def parse_pipeline_run_ref(reference: str) -> tuple[str, str | None]:
    """Parse ``<pipeline>`` or ``<pipeline>@<run_id>`` (``saved:`` prefix allowed)."""
    candidate = reference.strip().removeprefix("saved:")
    match = _RUN_REF_RE.fullmatch(candidate)
    if match is None:
        raise ValueError('pipeline_run must be "<pipeline>" or "<pipeline>@<run_id>"')
    return match.group("name"), match.group("run")


def _has_metadata(row: dict[str, Any]) -> bool:
    return not row.get("metadata_missing") and bool(str(row.get("title") or "").strip())


async def export_pipeline_run(
    store: PipelineStore,
    reference: str,
    *,
    fmt: str,
    include_abstract: bool,
    searcher: Any | None,
) -> RunExport:
    """Format every record of one persisted run (latest run when no run ID).

    Raises:
        ValueError: invalid reference or format, or the run has no record set.
        FileNotFoundError: unknown pipeline or run.
    """
    if fmt not in PIPELINE_RUN_EXPORT_FORMATS:
        raise ValueError(f"Pipeline run exports support: {', '.join(PIPELINE_RUN_EXPORT_FORMATS)}")
    name, run_id = parse_pipeline_run_ref(reference)
    if not store.exists(name):
        raise FileNotFoundError(f"Pipeline '{name}' not found")
    run: PipelineRun = store.get_run(name, run_id)
    has_artifact = bool(run.artifacts.get("records"))
    rows = store.load_run_records(name, run.run_id) if has_artifact else []
    if not rows:
        rows = [{"pmid": pmid, "metadata_missing": True} for pmid in run.pmids]
    if not rows:
        raise ValueError("This run has no persisted records to export")

    missing = [str(row["pmid"]) for row in rows if not _has_metadata(row)]
    backfilled = 0
    backfill_error: str | None = None
    fetch_details = getattr(searcher, "fetch_details", None)
    if missing and callable(fetch_details):
        fetched: dict[str, dict[str, Any]] = {}
        for start in range(0, min(len(missing), MAX_EXPORT_METADATA_BACKFILL), _BACKFILL_BATCH):
            batch = missing[start : start + _BACKFILL_BATCH]
            try:
                result = await fetch_details(batch)
            except Exception as exc:  # export what is available; disclose the gap
                backfill_error = type(exc).__name__
                break
            expected = set(batch)
            for item in result if isinstance(result, list) else []:
                if isinstance(item, dict) and str(item.get("pmid") or "") in expected:
                    fetched[str(item["pmid"])] = item
        if fetched:
            rows = [fetched.get(str(row["pmid"]), row) for row in rows]
            backfilled = len(fetched)
            if has_artifact:
                # Cache backfilled metadata; the identifier set itself is unchanged.
                store.save_run_records(name, run.run_id, rows)
            missing = [str(row["pmid"]) for row in rows if not _has_metadata(row)]

    export_rows = [{key: value for key, value in row.items() if key != "metadata_missing"} for row in rows]
    content = (
        export_csl_json(export_rows, include_abstract=include_abstract)
        if fmt == "csl"
        else export_articles(export_rows, fmt=fmt, include_abstract=include_abstract)
    )
    retrieval = run.retrieval or {}
    return RunExport(
        pipeline_name=name,
        run_id=run.run_id,
        content=content,
        format=fmt,
        record_count=len(rows),
        metadata_missing=missing,
        backfilled=backfilled,
        backfill_error=backfill_error,
        record_basis=run.record_basis,
        retrieval_mode=retrieval.get("mode") if isinstance(retrieval.get("mode"), str) else None,
        exhaustive=retrieval.get("exhaustive") is True,
        run_status=run.status,
        warnings=_completeness_warnings(run),
    )


__all__ = [
    "MAX_EXPORT_METADATA_BACKFILL",
    "PIPELINE_RUN_EXPORT_FORMATS",
    "RunExport",
    "export_pipeline_run",
    "parse_pipeline_run_ref",
]
