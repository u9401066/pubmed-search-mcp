"""Thin presentation bridge to the durable application search-run journal.

The unified-search executor stays independent of session persistence.  This
adapter snapshots its request, plan, source attempts, and terminal result into
the tenant-scoped :class:`SessionManager` without teaching provider adapters
about MCP or durable storage.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .tool_session import get_session_manager

if TYPE_CHECKING:
    from pubmed_search.application.session.manager import SessionManager

logger = logging.getLogger(__name__)


def _article_reference(article: Any) -> dict[str, Any]:
    """Return a compact stable reference; full records live in the artifact."""
    reference = {
        "pmid": getattr(article, "pmid", None),
        "pmc": getattr(article, "pmc", None),
        "doi": getattr(article, "doi", None),
        "openalex_id": getattr(article, "openalex_id", None),
        "semantic_scholar_id": getattr(article, "s2_id", None),
        "title": getattr(article, "title", None),
        "primary_source": getattr(article, "primary_source", None),
    }
    return {key: value for key, value in reference.items() if value not in (None, "")}


def _plan_snapshot(plan: Any) -> dict[str, Any]:
    analysis = getattr(plan, "analysis", None)
    to_dict = getattr(analysis, "to_dict", None)
    analysis_payload = to_dict() if callable(to_dict) else {}
    return {
        "query": getattr(plan, "query", ""),
        "provider_neutral_query": getattr(plan, "provider_neutral_query", ""),
        "retrieval_mode": getattr(getattr(plan, "request", None), "retrieval_mode", "auto"),
        "effective_min_year": getattr(plan, "effective_min_year", None),
        "effective_max_year": getattr(plan, "effective_max_year", None),
        "analysis": analysis_payload if isinstance(analysis_payload, dict) else {},
        "strategies": [
            {
                "name": getattr(strategy, "name", ""),
                "source": getattr(strategy, "source", ""),
                "query": getattr(strategy, "query", ""),
                "priority": getattr(strategy, "priority", None),
            }
            for strategy in list(getattr(plan, "deep_strategies", []) or [])
        ],
    }


def classify_search_run_status(execution: Any) -> str:
    """Classify terminal search state without calling a valid empty response a failure."""
    source_errors = list(getattr(execution, "source_errors", []) or [])
    if not source_errors:
        return "completed"
    if list(getattr(execution, "ranked", []) or []):
        return "partial"
    statuses = dict(getattr(execution, "source_statuses", {}) or {})
    if any(status in {"ok", "empty", "partial", "completed"} for status in statuses.values()):
        return "partial"
    return "failed"


@dataclass
class SearchRunJournal:
    """Best-effort lifecycle writer bound to one tenant-scoped manager."""

    manager: SessionManager | None
    run_id: str | None = None
    warnings: list[str] = field(default_factory=list)
    persistence_available: bool = True

    def _history_unavailable(self, intended_status: str) -> dict[str, Any]:
        """Return a truthful transient handoff when the terminal write failed."""
        self.persistence_available = False
        warning = "Search history terminal commit was unavailable; recovery is not guaranteed"
        if warning not in self.warnings:
            self.warnings.append(warning)
        return {
            "run_id": self.run_id,
            "status": "history_unavailable",
            "intended_status": intended_status,
            "recoverable": False,
            "history_available": False,
            "warning": warning,
        }

    def provisional_run(self, intended_status: str) -> dict[str, Any] | None:
        """Describe the pre-terminal state embedded in an immutable artifact."""
        if self.run_id is None:
            return None
        if not self.persistence_available:
            return self._history_unavailable(intended_status)
        return {
            "run_id": self.run_id,
            "status": "running",
            "intended_status": intended_status,
            "recoverable": True,
            "history_available": True,
            "terminal_pending": True,
        }

    async def _recover_terminal_write(self, intended_status: str) -> dict[str, Any]:
        """Read back a committed run or fail it durably after a transition error."""
        if self.manager is None or self.run_id is None:
            return self._history_unavailable(intended_status)
        try:
            existing = await asyncio.to_thread(self.manager.get_search_run, self.run_id)
            if isinstance(existing, dict) and existing.get("status") in {
                "completed",
                "partial",
                "failed",
                "cancelled",
                "interrupted",
            }:
                return existing
            return await asyncio.to_thread(
                self.manager.fail_search_run,
                self.run_id,
                "Search history terminal commit failed",
                stage="persistence",
                retryable=True,
            )
        except Exception as exc:
            logger.warning("Search-run persistence recovery failed (%s)", type(exc).__name__)
            return self._history_unavailable(intended_status)

    @classmethod
    async def start(
        cls,
        *,
        query: str,
        request: dict[str, Any],
        manager: SessionManager | None = None,
    ) -> SearchRunJournal:
        resolved_manager = manager if manager is not None else get_session_manager()
        journal = cls(manager=resolved_manager)
        if resolved_manager is None:
            return journal
        journal.run_id = uuid.uuid4().hex
        start_task = asyncio.create_task(
            asyncio.to_thread(
                resolved_manager.start_search_run,
                query,
                request=copy.deepcopy(request),
                run_id=journal.run_id,
            )
        )
        try:
            run = await asyncio.shield(start_task)
            journal.run_id = str(run.get("run_id") or "") or None
        except asyncio.CancelledError:
            # ``to_thread`` cannot stop a synchronous atomic write once it has
            # started.  Wait for that bounded write, then terminalize the
            # known run id so a long-lived server never retains a phantom
            # ``started`` record.
            try:
                run = await start_task
                journal.run_id = str(run.get("run_id") or "") or journal.run_id
                if journal.run_id:
                    await asyncio.to_thread(
                        resolved_manager.complete_search_run,
                        journal.run_id,
                        pmids=[],
                        result_count=0,
                        warnings=["Search was cancelled while durable history was starting"],
                        status="cancelled",
                    )
            except Exception as exc:
                logger.warning("Cancelled search-run cleanup failed (%s)", type(exc).__name__)
            raise
        except Exception as exc:
            logger.warning("Search-run journal start failed (%s)", type(exc).__name__)
            journal.persistence_available = False
            journal.warnings.append("Search history persistence was unavailable at run start")
        return journal

    async def plan(self, plan: Any) -> None:
        if self.manager is None or self.run_id is None or not self.persistence_available:
            return
        try:
            await asyncio.to_thread(
                self.manager.plan_search_run,
                self.run_id,
                plan=_plan_snapshot(plan),
                sources=list(getattr(plan, "dispatch_sources", []) or []),
            )
        except Exception as exc:
            logger.warning("Search-run plan persistence failed (%s)", type(exc).__name__)
            self.warnings.append("Search plan could not be added to durable history")

    async def plan_pipeline(self, pipeline_text: str, *, dry_run: bool, stop_at: str) -> None:
        """Persist a bounded pipeline plan without duplicating its raw replay input."""
        if self.manager is None or self.run_id is None or not self.persistence_available:
            return
        plan = {
            "mode": "pipeline",
            "pipeline_sha256": hashlib.sha256(pipeline_text.encode("utf-8", errors="replace")).hexdigest(),
            "pipeline_length": len(pipeline_text),
            "dry_run": dry_run,
            "stop_at": stop_at or None,
        }
        try:
            await asyncio.to_thread(
                self.manager.plan_search_run,
                self.run_id,
                plan=plan,
                sources=[],
            )
        except Exception as exc:
            logger.warning("Pipeline search-run plan persistence failed (%s)", type(exc).__name__)
            self.warnings.append("Pipeline plan could not be added to durable history")

    async def record_pipeline_outcome(self, outcome: Any) -> None:
        """Persist compact step outcomes from unified_search pipeline mode."""
        if self.manager is None or self.run_id is None or not self.persistence_available:
            return
        for step_id, result in dict(getattr(outcome, "step_results", {}) or {}).items():
            metadata = dict(getattr(result, "metadata", {}) or {})
            source_errors = [error for error in list(metadata.get("source_errors") or []) if isinstance(error, dict)]
            articles = list(getattr(result, "articles", []) or [])
            if getattr(result, "error", None):
                status = "error"
            elif source_errors:
                status = "partial"
            else:
                status = "ok" if articles else "empty"
            try:
                await asyncio.to_thread(
                    self.manager.record_search_source_attempt,
                    self.run_id,
                    f"pipeline:{step_id}",
                    status,
                    logical_query=metadata.get("query") if isinstance(metadata.get("query"), str) else None,
                    returned=len(articles),
                    metadata={
                        "action": str(getattr(result, "action", "")),
                        "source_api_counts": dict(metadata.get("source_api_counts") or {}),
                        "source_errors": source_errors,
                    },
                    error=(
                        {"message": str(result.error), "type": "PipelineStepFailure"}
                        if getattr(result, "error", None)
                        else source_errors[0]
                        if source_errors
                        else None
                    ),
                )
            except Exception as exc:
                logger.warning("Pipeline step history persistence failed (%s)", type(exc).__name__)
                self.warnings.append(f"Pipeline step history could not be persisted for {step_id}")

    async def complete_pipeline(self, outcome: Any) -> dict[str, Any] | None:
        """Commit a pipeline-mode invocation into the same durable run journal."""
        if self.manager is None or self.run_id is None:
            return None
        if not self.persistence_available:
            return self._history_unavailable(str(getattr(outcome, "status", "failed")))
        articles = list(getattr(outcome, "articles", []) or [])
        status = str(getattr(outcome, "status", "failed"))
        warnings = list(self.warnings)
        failure = getattr(outcome, "error", None) or "Pipeline execution failed"
        try:
            return await asyncio.to_thread(
                self.manager.complete_search_run,
                self.run_id,
                pmids=[str(article.pmid) for article in articles if getattr(article, "pmid", None)],
                result_count=len(articles),
                result_refs=[_article_reference(article) for article in articles],
                warnings=warnings,
                status=status,
                failure=failure if status == "failed" else None,
                retryable=status != "completed",
            )
        except Exception as exc:
            logger.warning("Pipeline search-run completion failed (%s)", type(exc).__name__)
            return await self._recover_terminal_write(status)

    async def record_execution(self, execution: Any, plan: Any) -> None:
        """Persist one terminal attempt row for every source the broker ran."""
        if self.manager is None or self.run_id is None or not self.persistence_available:
            return

        counts = dict(getattr(execution, "source_api_counts", {}) or {})
        statuses = dict(getattr(execution, "source_statuses", {}) or {})
        metadata_by_source = dict(getattr(execution, "source_metadata", {}) or {})
        errors = list(getattr(execution, "source_errors", []) or [])
        errors_by_source: dict[str, dict[str, Any]] = {
            str(error.get("source")): error for error in errors if isinstance(error, dict) and error.get("source")
        }
        sources = list(dict.fromkeys([*counts, *statuses, *metadata_by_source, *errors_by_source]))

        for source in sources:
            returned, available = counts.get(source, (0, None))
            metadata = dict(metadata_by_source.get(source, {}) or {})
            logical_query = metadata.get("logical_query")
            if not isinstance(logical_query, str):
                logical_query = (
                    getattr(plan, "query", "") if source == "pubmed" else getattr(plan, "provider_neutral_query", "")
                )
            physical_query = metadata.get("physical_query")
            if not isinstance(physical_query, str):
                physical_query = None
            error_payload = errors_by_source.get(source)
            status = str((error_payload or {}).get("status") or statuses.get(source) or "error")
            try:
                await asyncio.to_thread(
                    self.manager.record_search_source_attempt,
                    self.run_id,
                    source,
                    status,
                    logical_query=logical_query,
                    physical_query=physical_query,
                    returned=returned,
                    available=available,
                    metadata=metadata,
                    error=error_payload,
                )
            except Exception as exc:
                logger.warning("Search source-attempt persistence failed (%s)", type(exc).__name__)
                self.warnings.append(f"Source history could not be persisted for {source}")

    async def complete(self, execution: Any, *, artifact: dict[str, Any] | None) -> dict[str, Any] | None:
        if self.manager is None or self.run_id is None:
            return None
        if not self.persistence_available:
            return self._history_unavailable(classify_search_run_status(execution))
        ranked = list(getattr(execution, "ranked", []) or [])
        pmids = [str(article.pmid) for article in ranked if getattr(article, "pmid", None)]
        source_errors = list(getattr(execution, "source_errors", []) or [])
        warnings = [str(error.get("message") or "Source failed") for error in source_errors if isinstance(error, dict)]
        warnings.extend(self.warnings)
        status = classify_search_run_status(execution)
        failed_sources = sorted(
            {str(error.get("source")) for error in source_errors if isinstance(error, dict) and error.get("source")}
        )
        failure = (
            {
                "type": "AllSourcesFailed",
                "stage": "sources",
                "message": (
                    f"All selected search sources failed: {', '.join(failed_sources)}"
                    if failed_sources
                    else "All selected search sources failed"
                ),
            }
            if status == "failed"
            else None
        )
        retryable = any(bool(error.get("retryable")) for error in source_errors if isinstance(error, dict))
        try:
            return await asyncio.to_thread(
                self.manager.complete_search_run,
                self.run_id,
                pmids=pmids,
                result_count=len(ranked),
                result_refs=[_article_reference(article) for article in ranked],
                artifact=artifact,
                warnings=warnings,
                status=status,
                failure=failure,
                retryable=retryable,
            )
        except Exception as exc:
            logger.warning("Search-run completion persistence failed (%s)", type(exc).__name__)
            return await self._recover_terminal_write(status)

    async def fail(
        self,
        error: BaseException | str,
        *,
        stage: str,
        retryable: bool,
    ) -> dict[str, Any] | None:
        if self.manager is None or self.run_id is None:
            return None
        if not self.persistence_available:
            return self._history_unavailable("failed")
        try:
            return await asyncio.to_thread(
                self.manager.fail_search_run,
                self.run_id,
                error,
                stage=stage,
                retryable=retryable,
            )
        except Exception as exc:
            logger.warning("Search-run failure persistence failed (%s)", type(exc).__name__)
            return self._history_unavailable("failed")

    async def cancel(self) -> dict[str, Any] | None:
        if self.manager is None or self.run_id is None:
            return None
        if not self.persistence_available:
            return self._history_unavailable("cancelled")
        try:
            return await asyncio.to_thread(
                self.manager.complete_search_run,
                self.run_id,
                pmids=[],
                result_count=0,
                warnings=[*self.warnings, "Search was cancelled before completion"],
                status="cancelled",
            )
        except Exception as exc:
            logger.warning("Search-run cancellation persistence failed (%s)", type(exc).__name__)
            return self._history_unavailable("cancelled")


def compact_search_run_handoff(run: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return bounded recovery instructions for structured MCP responses."""
    if not run or not run.get("run_id"):
        return None
    run_id = str(run["run_id"])
    raw_artifact = run.get("artifact")
    artifact: dict[str, Any] = dict(raw_artifact) if isinstance(raw_artifact, dict) else {}
    handoff: dict[str, Any] = {
        "run_id": run_id,
        "status": run.get("status"),
        "recoverable": bool(run.get("recoverable", False)),
    }
    if run.get("history_available", True) is False:
        handoff.update(
            {
                "history_available": False,
                "intended_status": run.get("intended_status"),
                "warning": run.get("warning") or "Search history is unavailable",
            }
        )
        return handoff
    handoff.update(
        {
            "history_available": True,
            "inspect": {
                "tool": "read_session",
                "arguments": {"action": "search_run", "run_id": run_id},
            },
            "replay": {
                "tool": "read_session",
                "arguments": {"action": "replay_search", "run_id": run_id},
            },
        }
    )
    if artifact.get("artifact_uri"):
        handoff["artifact_uri"] = artifact["artifact_uri"]
    return handoff


def search_run_markdown_note(run: dict[str, Any] | None) -> str:
    """Render a compact recovery note for human-readable responses."""
    handoff = compact_search_run_handoff(run)
    if handoff is None:
        return ""
    run_id = str(handoff["run_id"])
    status = str(handoff.get("status") or "unknown")
    if handoff.get("history_available") is False:
        intended = str(handoff.get("intended_status") or "unknown")
        return (
            "\n\n---\n"
            f"Search run `{run_id}` reached `{intended}`, but its terminal history commit was unavailable; "
            "recovery is not guaranteed."
        )
    return (
        "\n\n---\n"
        f"Search run: `{run_id}` ({status}). "
        f'Inspect with `read_session(action="search_run", run_id="{run_id}")`; '
        f'recover replay arguments with `read_session(action="replay_search", run_id="{run_id}")`.'
    )


__all__ = [
    "SearchRunJournal",
    "classify_search_run_status",
    "compact_search_run_handoff",
    "search_run_markdown_note",
]
