"""MCP tool for screening a saved pipeline's records and reporting PRISMA 2020 flow.

Screening decisions are the one systematic-review write operation with no
home in the existing pipeline tools: saving a pipeline changes the strategy,
and history/export are read-only views of runs. This tool keeps the review
workflow thin: validation and flow arithmetic live in
``application.pipeline.screening``; storage is a per-pipeline SQLite log.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from pubmed_search.application.pipeline.screening import (
    MAX_DECISIONS_PER_REQUEST,
    ScreeningService,
    render_prisma_flow_markdown,
)
from pubmed_search.application.pipeline.store import PipelineHistoryError
from pubmed_search.application.pipeline.validator import PIPELINE_NAME_PATTERN
from pubmed_search.domain.entities.pipeline import PipelineScope
from pubmed_search.infrastructure.pipeline_screening import SQLiteScreeningStore
from pubmed_search.presentation.mcp_server.tenancy import durable_storage_denied

from .tool_response import ResponseFormatter

if TYPE_CHECKING:
    from pathlib import Path

    from mcp.server.mcpserver import MCPServer

    from pubmed_search.application.pipeline.run_recorder import RunObserver
    from pubmed_search.application.pipeline.store import PipelineStore
    from pubmed_search.domain.entities.pipeline import PipelineRun

    from .pipeline_tools import PipelineToolRuntime

logger = logging.getLogger(__name__)

TOOL_NAME = "pipeline_screening"
_ABSTRACT_CHARS = 3_000

PipelineName = Annotated[str, Field(strict=True, min_length=1, max_length=64, pattern=PIPELINE_NAME_PATTERN)]
RunId = Annotated[str, Field(strict=True, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]
Pmid = Annotated[str, Field(strict=True, pattern=r"^[1-9][0-9]{0,9}$")]
Offset = Annotated[int, Field(ge=0, le=1_000_000)]
PageSize = Annotated[int, Field(ge=1, le=100)]
Stage = Literal["title_abstract", "full_text"]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ScreeningDecision(_Request):
    pmid: Pmid
    stage: Stage
    decision: Literal["include", "exclude", "maybe"]
    reason: Annotated[str, Field(min_length=1, max_length=500)] | None = Field(
        default=None, description="Required for full-text exclusions; use 'not retrieved' for unobtainable reports."
    )
    reviewer: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,63}$")] | None = Field(
        default=None, description="Reviewer label (default reviewer_1); different labels expose conflicts."
    )
    decision_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")] | None = Field(
        default=None,
        description=(
            "Optional idempotency key: resending it is always a replay. Without it, only an exact repeat of "
            "this reviewer's latest decision for the PMID and stage is a replay; any other decision is recorded."
        ),
    )
    note: Annotated[str, Field(min_length=1, max_length=2000)] | None = None


class _RecordDecisions(_Request):
    action: Literal["record"]
    pipeline: PipelineName
    decisions: Annotated[list[ScreeningDecision], Field(min_length=1, max_length=MAX_DECISIONS_PER_REQUEST)]


class _Queue(_Request):
    action: Literal["queue"]
    pipeline: PipelineName
    stage: Stage = "title_abstract"
    run_id: RunId | None = Field(default=None, description="Only records first identified by this run.")
    offset: Offset = 0
    limit: PageSize = 25
    include_abstract: bool = False


class _Flow(_Request):
    action: Literal["flow"]
    pipeline: PipelineName
    format: Literal["markdown", "json"] = "markdown"


class _Log(_Request):
    action: Literal["log"]
    pipeline: PipelineName
    pmid: Pmid | None = None
    offset: Offset = 0
    limit: PageSize = 50


class _RegisterRun(_Request):
    action: Literal["register_run"]
    pipeline: PipelineName
    run_id: RunId | None = Field(default=None, description="Run to add to identification (default: latest run).")


ScreeningRequest = Annotated[
    _RecordDecisions | _Queue | _Flow | _Log | _RegisterRun,
    Field(discriminator="action"),
]


def screening_service(store: PipelineStore, name: str) -> ScreeningService:
    """Bind the screening service to one pipeline's log in its owning scope."""
    return ScreeningService(SQLiteScreeningStore(store.screening_db_path(name)))


def screening_log_at(path: Path) -> SQLiteScreeningStore:
    """Open the screening log at ``path`` (deletion retires it atomically)."""
    return SQLiteScreeningStore(path)


def screening_run_observer(store: PipelineStore) -> RunObserver:
    """Return a run observer that queues new records of complete runs for screening."""

    def observe(name: str, run: PipelineRun) -> None:
        # The record artifact names the scope the run was persisted to; register
        # into that scope's log even if a same-name pipeline exists elsewhere.
        artifact = run.artifacts.get("records")
        scope = artifact.get("scope") if isinstance(artifact, dict) else None
        target = store.pinned_to(PipelineScope(scope)) if scope in {"workspace", "global"} else store
        screening_service(target, name).register_if_complete(run)

    return observe


def _enrich_queue(store: PipelineStore, name: str, page: dict[str, Any], *, include_abstract: bool) -> None:
    """Attach title/abstract metadata from each record's first identifying run."""
    cache: dict[str, dict[str, dict[str, Any]]] = {}
    for item in page["items"]:
        run_id = item["first_run_id"]
        if run_id not in cache:
            try:
                cache[run_id] = {str(row["pmid"]): row for row in store.load_run_records(name, run_id)}
            except (OSError, ValueError, PipelineHistoryError):
                cache[run_id] = {}
        row = cache[run_id].get(item["pmid"]) or {}
        item["title"] = str(row.get("title") or "")
        item["year"] = str(row.get("year") or "")
        item["journal"] = str(row.get("journal") or "")
        item["doi"] = str(row.get("doi") or "")
        if include_abstract:
            abstract = str(row.get("abstract") or "")
            item["abstract"] = abstract[:_ABSTRACT_CHARS] + ("…" if len(abstract) > _ABSTRACT_CHARS else "")
        if not row or row.get("metadata_missing"):
            item["metadata_missing"] = True


def _execute(store: PipelineStore, request: Any) -> str:
    name = request.pipeline
    if not store.exists(name):
        raise FileNotFoundError(name)
    service = screening_service(store, name)
    if isinstance(request, _RecordDecisions):
        result = service.record([decision.model_dump(exclude_none=True) for decision in request.decisions])
        return json.dumps({"pipeline": name, **result}, ensure_ascii=False)
    if isinstance(request, _Queue):
        page = service.queue(stage=request.stage, run_id=request.run_id, offset=request.offset, limit=request.limit)
        _enrich_queue(store, name, page, include_abstract=request.include_abstract)
        return json.dumps({"pipeline": name, **page}, ensure_ascii=False)
    if isinstance(request, _Log):
        return json.dumps(
            {"pipeline": name, **service.log(pmid=request.pmid, offset=request.offset, limit=request.limit)},
            ensure_ascii=False,
        )
    if isinstance(request, _RegisterRun):
        run = store.get_run(name, request.run_id)
        result = service.register_run(run)
        if not result["exhaustive"]:
            result["warning"] = "This run was not exhaustive; PRISMA identification counts will be incomplete"
        return json.dumps({"pipeline": name, **result}, ensure_ascii=False, default=str)
    flow = service.flow()
    if request.format == "json":
        return json.dumps({"pipeline": name, **flow}, ensure_ascii=False)
    return render_prisma_flow_markdown(name, flow)


def register_pipeline_screening_tools(mcp: MCPServer, *, runtime: PipelineToolRuntime) -> None:
    """Register the screening tool bound to one server-scoped pipeline runtime."""

    @mcp.tool()
    async def pipeline_screening(request: ScreeningRequest) -> str:
        """Screen a saved pipeline's records and report PRISMA 2020 flow counts.

        A saved pipeline is the review project. Runs with retrieval: exhaustive
        register their complete PMID set automatically, so records first found
        by an update run enter the title/abstract queue on their own.

        Actions:
        - record: append decisions (pmid, stage title_abstract|full_text,
          decision include|exclude|maybe, reason, reviewer). Full-text
          exclusions need a reason; full-text screening needs a prior
          title/abstract include or maybe. Without decision_id, a decision is a
          replay only when it repeats the same reviewer's latest decision for
          that PMID and stage (same decision, reason and note); every other
          decision, including a return to an earlier one, is recorded and
          counted. Pass a stable decision_id to make retries idempotent even
          after later decisions; reusing one for different content is an error.
        - queue: page records awaiting a decision at a stage (optionally only
          those first identified by run_id), with titles from the run artifact.
        - flow: PRISMA 2020 counts (identified per run/database, duplicates
          removed, screened, excluded, sought, assessed, excluded with
          reasons, included) as Markdown or JSON.
        - log: page the decision audit trail, optionally for one PMID.
        - register_run: add a run's records to identification (latest by default).
        """
        denied = durable_storage_denied(TOOL_NAME, output_format="json")
        if denied:
            return denied
        store = runtime.store_for_current_tenant()
        if store is None:
            return ResponseFormatter.error("Pipeline store not initialized", tool_name=TOOL_NAME, output_format="json")
        try:
            return await asyncio.to_thread(_execute, store, request)
        except FileNotFoundError:
            return ResponseFormatter.error(
                "Saved pipeline or run was not found",
                suggestion="Use list_pipelines() and get_pipeline_history(name=...) to find names and run IDs",
                tool_name=TOOL_NAME,
                output_format="json",
            )
        except (ValueError, PipelineHistoryError) as exc:
            return ResponseFormatter.error(exc, tool_name=TOOL_NAME, output_format="json")
        except (OSError, sqlite3.Error) as exc:
            logger.warning("Pipeline screening storage failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                "Could not access pipeline screening storage",
                suggestion=(
                    "Check data directory availability and retry; pass decision_id values to make a retried "
                    "batch idempotent."
                ),
                tool_name=TOOL_NAME,
                output_format="json",
            )


__all__ = [
    "ScreeningDecision",
    "ScreeningRequest",
    "register_pipeline_screening_tools",
    "screening_log_at",
    "screening_run_observer",
    "screening_service",
]
