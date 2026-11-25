"""PRISMA-S search records for persisted pipeline runs.

PRISMA-S (Rethlefsen et al., 2021) asks a systematic review to report, for
every database search: the database and platform, the exact search strategy,
limits and filters, the date the search was run, and the number of records
found. This module derives that record from executor evidence (never from
the agent's recollection), fingerprints the strategy that produced a run,
and renders one or more runs as a Markdown table and as CSV.

The record distinguishes three query forms:

* ``logical_query`` — the strategy as saved in the pipeline (as entered);
* ``physical_query`` — what was sent to the provider, including limits;
* ``query_translation`` — PubMed's own interpretation (``QueryTranslation``),
  captured for exhaustive retrieval steps from the ESearch snapshot.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from typing import TYPE_CHECKING, Any

from pubmed_search.application.pipeline.exhaustive import PUBMED_PLATFORM, SEARCH_FILTER_KEYS
from pubmed_search.application.pipeline.store import _config_to_dict
from pubmed_search.application.pipeline.validator import compute_config_hash
from pubmed_search.shared.markdown import escape_markdown_code, escape_markdown_text

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from pubmed_search.domain.entities.pipeline import PipelineConfig, PipelineRun, StepResult

SERVER_NAME = "pubmed-search-mcp"

DATABASE_NAMES: dict[str, str] = {
    "pubmed": "PubMed",
    "europe_pmc": "Europe PMC",
    "openalex": "OpenAlex",
    "semantic_scholar": "Semantic Scholar",
    "core": "CORE",
    "scopus": "Scopus",
    "web_of_science": "Web of Science",
}
PLATFORMS: dict[str, str] = {
    "pubmed": "NCBI E-utilities (ESearch + EFetch)",
    "europe_pmc": "Europe PMC REST API",
    "openalex": "OpenAlex API",
    "semantic_scholar": "Semantic Scholar Graph API",
    "core": "CORE API v3",
    "scopus": "Elsevier Scopus Search API",
    "web_of_science": "Clarivate Web of Science Starter API",
}

PRISMA_S_COLUMNS: tuple[str, ...] = (
    "run_id",
    "run_started_utc",
    "step_id",
    "database",
    "platform",
    "interface",
    "search_date_utc",
    "search_strategy",
    "executed_query",
    "pubmed_query_translation",
    "limits_and_filters",
    "records_found",
    "records_retrieved",
    "exhaustive",
    "retrieval_mode",
    "query_sha256",
    "config_hash",
    "config_sha256",
    "status",
    "notes",
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def query_fingerprint(query: str | None) -> str | None:
    """Return a short, stable fingerprint of one executed query string."""
    return _sha256(query)[:12] if isinstance(query, str) and query else None


def _filters_text(filters: Mapping[str, Any]) -> str:
    if not filters:
        return "none"
    parts: list[str] = []
    min_year, max_year = filters.get("min_year"), filters.get("max_year")
    if min_year is not None or max_year is not None:
        parts.append(f"publication year {min_year or '…'}–{max_year or '…'}")
    parts.extend(f"{key}={filters[key]}" for key in SEARCH_FILTER_KEYS[2:] if filters.get(key) is not None)
    return "; ".join(parts)


def config_provenance(
    saved_config: PipelineConfig | None,
    executed_config: PipelineConfig | None,
) -> dict[str, Any]:
    """Fingerprint and snapshot the strategy that produced one run.

    ``config_hash`` matches the short hash ``save_pipeline``/``list_pipelines``
    show for the saved YAML; ``config_sha256`` covers the full canonical
    snapshot, which is stored immutably with the run so a later YAML edit
    cannot change what the run claims to have executed.
    """
    reference = saved_config or executed_config
    if reference is None:
        return {}
    saved = _config_to_dict(reference, include_output_defaults=True)
    snapshot: dict[str, Any] = {"saved": saved}
    if executed_config is not None and executed_config is not reference:
        snapshot["executed_steps"] = [
            {"id": step.id, "action": step.action, "params": step.params, "inputs": list(step.inputs)}
            for step in executed_config.steps
        ]
    canonical = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, default=str)
    return {
        "config_hash": compute_config_hash(reference),
        "config_sha256": _sha256(canonical),
        "config_snapshot": snapshot,
    }


def _bounded_search_records(step_id: str, result: StepResult, server_version: str | None) -> list[dict[str, Any]]:
    metadata = result.metadata
    source_queries = dict(metadata.get("source_queries") or {})
    source_results = dict(metadata.get("source_results") or {})
    counts = dict(metadata.get("source_api_counts") or {})
    errors_by_source = {
        str(error.get("source")): error for error in metadata.get("source_errors") or [] if isinstance(error, dict)
    }
    filters = dict(metadata.get("filters") or {})
    records: list[dict[str, Any]] = []
    for source in dict.fromkeys([*source_queries, *source_results, *counts]):
        provider = dict(source_results.get(source) or {})
        provenance = dict(provider.get("provenance") or {})
        logical = provenance.get("logical_query") or source_queries.get(source) or metadata.get("query")
        physical = provenance.get("physical_query") or logical
        error = errors_by_source.get(source)
        total = provider.get("total_count")
        records.append(
            {
                "step_id": step_id,
                "source": source,
                "database": DATABASE_NAMES.get(source, source),
                "platform": PLATFORMS.get(source, source),
                "interface": f"{SERVER_NAME} {server_version or ''}".strip(),
                "logical_query": logical,
                "physical_query": physical,
                "query_translation": None,
                "translation_set": [],
                "provider_notes": {},
                "filters": filters,
                "limits_text": _filters_text(filters),
                "total_count": total if isinstance(total, int) and not isinstance(total, bool) else None,
                "retrieved_count": int(counts.get(source, 0) or 0),
                "exhaustive": False,
                "retrieval_mode": "bounded",
                "bounded_limit": dict(metadata.get("retrieval") or {}).get("limit"),
                "executed_at": metadata.get("executed_at"),
                "status": "error" if error else ("ok" if result.ok else "error"),
                "query_sha256": query_fingerprint(physical if isinstance(physical, str) else None),
                "notes": "Bounded relevance window; not a complete record set."
                if not error
                else str(error.get("message")),
            }
        )
    return records


def _exhaustive_search_record(step_id: str, result: StepResult, server_version: str | None) -> dict[str, Any]:
    metadata = result.metadata
    retrieval = dict(metadata.get("retrieval") or {})
    history = dict(metadata.get("pubmed_history") or {})
    physical = history.get("physical_query") or metadata.get("physical_query") or metadata.get("query")
    notes = {
        key: value
        for group in ("provider_errors", "provider_warnings")
        for key, value in dict(history.get(group) or {}).items()
        if value
    }
    note_parts: list[str] = []
    if result.error:
        note_parts.append(result.error)
    if notes.get("phrases_not_found"):
        note_parts.append(f"PubMed phrases not found: {', '.join(notes['phrases_not_found'])}")
    if notes.get("quoted_phrases_not_found"):
        note_parts.append(f"Quoted phrases not found: {', '.join(notes['quoted_phrases_not_found'])}")
    if notes.get("phrases_ignored"):
        note_parts.append(f"Phrases ignored: {', '.join(notes['phrases_ignored'])}")
    if retrieval.get("metadata_complete") is False and retrieval.get("metadata_requested"):
        note_parts.append(f"Metadata for {retrieval.get('metadata_count', 0)} records; export completes the rest")
    filters = dict(metadata.get("filters") or {})
    return {
        "step_id": step_id,
        "source": "pubmed",
        "database": DATABASE_NAMES["pubmed"],
        "platform": PUBMED_PLATFORM,
        "interface": f"{SERVER_NAME} {server_version or ''}".strip(),
        "logical_query": history.get("logical_query") or metadata.get("query"),
        "physical_query": physical,
        "query_translation": history.get("query_translation"),
        "translation_set": list(history.get("translation_set") or []),
        "provider_notes": notes,
        "filters": filters,
        "limits_text": _filters_text(filters),
        "total_count": retrieval.get("total_count"),
        "retrieved_count": int(retrieval.get("retrieved_count") or 0),
        "exhaustive": bool(retrieval.get("exhaustive")) and result.ok,
        "retrieval_mode": "exhaustive",
        "cap": retrieval.get("cap"),
        "executed_at": metadata.get("executed_at"),
        "status": "ok" if result.ok else "error",
        "query_sha256": query_fingerprint(physical if isinstance(physical, str) else None),
        "notes": "; ".join(note_parts),
    }


def build_search_records(
    step_results: Mapping[str, StepResult],
    *,
    server_version: str | None,
) -> list[dict[str, Any]]:
    """Return one PRISMA-S search record per executed search step and source."""
    records: list[dict[str, Any]] = []
    for step_id, result in step_results.items():
        if result.action != "search" or result.metadata.get("dry_run") is True:
            continue
        retrieval = result.metadata.get("retrieval")
        if isinstance(retrieval, dict) and retrieval.get("mode") == "exhaustive":
            records.append(_exhaustive_search_record(step_id, result, server_version))
        else:
            records.extend(_bounded_search_records(step_id, result, server_version))
    return records


def strategy_fingerprint(run: PipelineRun) -> str | None:
    """Short fingerprint of every executed query in a run (order-sensitive)."""
    queries = [str(search.get("physical_query") or "") for search in run.searches]
    if not any(queries):
        return None
    return _sha256("\n".join(queries))[:12]


def prisma_s_rows(runs: Iterable[PipelineRun]) -> list[dict[str, str]]:
    """Flatten runs into PRISMA-S rows (one per database search)."""
    rows: list[dict[str, str]] = []
    for run in runs:
        started = run.started.isoformat().replace("+00:00", "Z") if run.started else ""
        if not run.searches:
            rows.append(
                {
                    **dict.fromkeys(PRISMA_S_COLUMNS, ""),
                    "run_id": run.run_id,
                    "run_started_utc": started,
                    "status": run.status,
                    "notes": "Run recorded before PRISMA-S provenance was captured (record version 1)",
                }
            )
            continue
        for search in run.searches:
            total = search.get("total_count")
            rows.append(
                {
                    "run_id": run.run_id,
                    "run_started_utc": started,
                    "step_id": str(search.get("step_id") or ""),
                    "database": str(search.get("database") or ""),
                    "platform": str(search.get("platform") or ""),
                    "interface": str(search.get("interface") or ""),
                    "search_date_utc": str(search.get("executed_at") or started),
                    "search_strategy": str(search.get("logical_query") or ""),
                    "executed_query": str(search.get("physical_query") or ""),
                    "pubmed_query_translation": str(search.get("query_translation") or ""),
                    "limits_and_filters": str(search.get("limits_text") or "none"),
                    "records_found": "" if total is None else str(total),
                    "records_retrieved": str(search.get("retrieved_count", "")),
                    "exhaustive": "yes" if search.get("exhaustive") else "no",
                    "retrieval_mode": str(search.get("retrieval_mode") or ""),
                    "query_sha256": str(search.get("query_sha256") or ""),
                    "config_hash": run.config_hash or "",
                    "config_sha256": run.config_sha256 or "",
                    "status": str(search.get("status") or run.status),
                    "notes": str(search.get("notes") or ""),
                }
            )
    return rows


def render_prisma_s_csv(runs: Iterable[PipelineRun]) -> str:
    """Render PRISMA-S rows as RFC 4180 CSV with a fixed header."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(PRISMA_S_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in prisma_s_rows(runs):
        writer.writerow(row)
    return buffer.getvalue()


def _code_cell(value: str) -> str:
    text = escape_markdown_code(value)
    return f"`{text.replace('|', '¦')}`" if text else "—"


def _text_cell(value: str) -> str:
    return escape_markdown_text(value) or "—"


def render_prisma_s_markdown(runs: Iterable[PipelineRun], *, title: str) -> str:
    """Render PRISMA-S rows as a Markdown table (queries as inert code spans)."""
    rows = prisma_s_rows(runs)
    parts = [
        f"## PRISMA-S search record: {escape_markdown_text(title)}",
        "",
        "| Run | Database / platform | Date searched (UTC) | Search strategy (as saved) | Executed query "
        "| PubMed translation | Limits | Found | Retrieved | Complete | Strategy hash |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        parts.append(
            f"| `{escape_markdown_code(row['run_id'])}` | {_text_cell(row['database'])} — "
            f"{_text_cell(row['platform'])} | {_text_cell(row['search_date_utc'])} "
            f"| {_code_cell(row['search_strategy'])} | {_code_cell(row['executed_query'])} "
            f"| {_code_cell(row['pubmed_query_translation'])} | {_text_cell(row['limits_and_filters'])} "
            f"| {row['records_found'] or '—'} | {row['records_retrieved'] or '—'} | {row['exhaustive'] or '—'} "
            f"| `{escape_markdown_code(row['config_hash'] or '—')}` |"
        )
    notes = [row for row in rows if row["notes"]]
    if notes:
        parts.append("")
        parts.append("Notes:")
        parts.extend(
            f"- `{escape_markdown_code(row['run_id'])}` / {_text_cell(row['step_id'] or 'run')}: "
            f"{_text_cell(row['notes'])}"
            for row in notes
        )
    parts.append("")
    parts.append(
        "Pipe characters inside queries are shown as ¦ in this table; the CSV below keeps every query verbatim."
    )
    return "\n".join(parts)


__all__ = [
    "DATABASE_NAMES",
    "PRISMA_S_COLUMNS",
    "build_search_records",
    "config_provenance",
    "prisma_s_rows",
    "query_fingerprint",
    "render_prisma_s_csv",
    "render_prisma_s_markdown",
    "strategy_fingerprint",
]
