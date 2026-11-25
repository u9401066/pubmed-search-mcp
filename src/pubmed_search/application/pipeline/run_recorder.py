"""Build and persist one pipeline run record from executor evidence.

Both execution paths — ``unified_search(pipeline="saved:<name>")`` and the
scheduled ``StoredPipelineRunner`` — persist runs through this recorder so a
run's identity, diff against the previous comparable run, retrieval
completeness, and record artifact are computed by one rule.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from pubmed_search import __version__
from pubmed_search.application.pipeline.executor import (
    PipelineOutcomeStatus,
    classify_pipeline_outcome,
    collected_records,
    final_record_set,
    is_exhaustive_step,
    pipeline_outcome_message,
    pipeline_run_status,
    run_uses_exhaustive_retrieval,
)
from pubmed_search.application.pipeline.prisma_s import build_search_records, config_provenance
from pubmed_search.application.pipeline.report_generator import generate_pipeline_changes
from pubmed_search.domain.entities.pipeline import PIPELINE_RUN_RECORD_VERSION, PipelineRun

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pubmed_search.application.pipeline.store import PipelineStore
    from pubmed_search.domain.entities.article import UnifiedArticle
    from pubmed_search.domain.entities.pipeline import PipelineConfig, StepResult

logger = logging.getLogger(__name__)

RunObserver = Callable[[str, PipelineRun], None]


def _article_record(article: UnifiedArticle) -> dict[str, Any]:
    """Convert a non-PubMed-native article into an export-compatible record."""
    authors = [getattr(author, "display_name", None) or str(author) for author in (article.authors or [])]
    article_type = getattr(article.article_type, "value", article.article_type)
    return {
        "pmid": article.pmid,
        "title": article.title or "",
        "authors": [name for name in authors if name],
        "abstract": article.abstract or "",
        "journal": article.journal or "",
        "year": str(article.year) if article.year else "",
        "doi": article.doi or "",
        "pmc_id": article.pmc or "",
        "publication_types": [str(article_type)] if article_type else [],
        "metadata_source": article.primary_source,
    }


def _scalar(value: Any) -> str | int | None:
    """Keep JSON-safe scalar summary values only."""
    return value if isinstance(value, (str, int)) and not isinstance(value, bool) else None


def _summarize_articles(articles: list[UnifiedArticle], limit: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "pmid": _scalar(getattr(article, "pmid", None)),
            "title": _scalar(getattr(article, "title", None)),
            "year": _scalar(getattr(article, "year", None)),
            "doi": _scalar(getattr(article, "doi", None)),
            "source": _scalar(getattr(article, "primary_source", None)),
        }
        for article in articles[:limit]
    ]


def retrieval_summary(step_results: Mapping[str, StepResult], record_count: int) -> dict[str, Any]:
    """Summarize retrieval completeness across all search steps of one run."""
    exhaustive_steps: list[dict[str, Any]] = []
    for step_id, result in step_results.items():
        if not is_exhaustive_step(result):
            continue
        retrieval = dict(result.metadata.get("retrieval") or {})
        exhaustive_steps.append(
            {
                "step_id": step_id,
                "total_count": retrieval.get("total_count"),
                "retrieved_count": retrieval.get("retrieved_count"),
                "exhaustive": bool(retrieval.get("exhaustive")) and result.ok,
                "cap": retrieval.get("cap"),
                "metadata_count": retrieval.get("metadata_count"),
                "metadata_complete": retrieval.get("metadata_complete"),
                "terminal_reason": retrieval.get("terminal_reason"),
            }
        )
    if not exhaustive_steps:
        return {"mode": "bounded", "exhaustive": False, "record_count": record_count}
    summary: dict[str, Any] = {
        "mode": "exhaustive",
        "exhaustive": all(step["exhaustive"] for step in exhaustive_steps),
        "record_count": record_count,
        "steps": exhaustive_steps,
    }
    if len(exhaustive_steps) == 1:
        only = exhaustive_steps[0]
        summary.update(
            {
                "total_count": only["total_count"],
                "retrieved_count": only["retrieved_count"],
                "metadata_count": only["metadata_count"],
            }
        )
    return summary


class PipelineRunRecorder:
    """Persist a pipeline run, its report and (for exhaustive runs) its record set."""

    def __init__(
        self,
        store: PipelineStore,
        *,
        on_recorded: RunObserver | None = None,
    ) -> None:
        self._store = store
        self._on_recorded = on_recorded

    def _previous_comparable_run(self, name: str, record_basis: str) -> PipelineRun | None:
        try:
            previous = self._store.get_latest_run(name, successful_only=True)
        except Exception as exc:
            logger.warning("Previous pipeline run is unavailable for diffing (%s)", type(exc).__name__)
            return None
        if not isinstance(previous, PipelineRun) or previous.record_basis != record_basis:
            return None
        return previous

    def record(
        self,
        *,
        pipeline_name: str,
        articles: list[UnifiedArticle],
        step_results: Mapping[str, StepResult],
        report: str,
        started: datetime,
        finished: datetime | None = None,
        run_id: str | None = None,
        diff_mode: bool = False,
        persist_run: bool = True,
        executed_config: PipelineConfig | None = None,
        saved_config: PipelineConfig | None = None,
        outcome: PipelineOutcomeStatus | None = None,
    ) -> PipelineRun:
        """Save the report and, for saved pipelines, the typed run record.

        ``articles`` is the ranked response list. Exhaustive runs persist the
        complete final-step PMID set instead, with ``record_basis`` recording
        which rule applied so history diffs never compare incompatible sets.
        """
        finished = finished or datetime.now(timezone.utc)
        run_id = run_id or self._store.create_run_id(pipeline_name, started)
        outcome = outcome or classify_pipeline_outcome(articles, step_results)
        exhaustive_run = run_uses_exhaustive_retrieval(step_results)

        record_basis: Literal["ranked_output", "final_step_full"]
        if exhaustive_run:
            _final_step, pmids = final_record_set(step_results)
            record_basis = "final_step_full"
        else:
            pmids = [str(article.pmid) for article in articles if getattr(article, "pmid", None)]
            record_basis = "ranked_output"

        run = PipelineRun(
            run_id=run_id,
            pipeline_name=pipeline_name,
            started=started,
            finished=finished,
            status=pipeline_run_status(outcome),
            article_count=len(pmids) if exhaustive_run else len(articles),
            pmids=pmids,
            error_message=pipeline_outcome_message(outcome),
            top_articles=_summarize_articles(articles),
            record_version=PIPELINE_RUN_RECORD_VERSION,
            record_basis=record_basis,
            retrieval=retrieval_summary(step_results, len(pmids)),
            server_version=__version__,
            searches=build_search_records(step_results, server_version=__version__),
        )
        run.block_analyses = [
            dict(result.metadata["block_analysis"])
            for result in step_results.values()
            if result.action == "block_analysis" and isinstance(result.metadata.get("block_analysis"), dict)
        ]
        provenance = config_provenance(saved_config, executed_config)
        run.config_hash = provenance.get("config_hash")
        run.config_sha256 = provenance.get("config_sha256")
        run.config_snapshot = provenance.get("config_snapshot")

        previous_run = self._previous_comparable_run(pipeline_name, record_basis) if persist_run else None
        previous_pmids = set(previous_run.pmids) if previous_run else set()
        run.new_pmids = [pmid for pmid in pmids if pmid not in previous_pmids] if previous_run else list(pmids)
        # A partial/failed provider run cannot prove that previously observed
        # records disappeared from the evidence set.
        run.removed_pmids = (
            sorted(previous_pmids - set(pmids)) if previous_run is not None and outcome == "completed" else []
        )

        if persist_run and exhaustive_run and pmids:
            run.artifacts["records"] = self._store.save_run_records(
                pipeline_name, run_id, self._records_for(pmids, articles, step_results)
            )
            run.artifacts["records"]["metadata_count"] = sum(
                1 for pmid in pmids if pmid in collected_records(step_results)
            )

        if diff_mode:
            report += "\n" + generate_pipeline_changes(articles, run, previous_run=previous_run)
        self._store.save_report(pipeline_name, run_id, report)
        if persist_run:
            self._store.save_run(pipeline_name, run)
            if self._on_recorded is not None:
                try:
                    self._on_recorded(pipeline_name, run)
                except Exception as exc:  # observers must never undo a persisted run
                    logger.warning("Pipeline run observer failed (%s)", type(exc).__name__)
        return run

    @staticmethod
    def _records_for(
        pmids: list[str],
        articles: list[UnifiedArticle],
        step_results: Mapping[str, StepResult],
    ) -> list[dict[str, Any]]:
        native = collected_records(step_results)
        by_pmid: dict[str, UnifiedArticle] = {}
        for result in step_results.values():
            for article in result.articles:
                if article.pmid and article.pmid not in by_pmid and article.title:
                    by_pmid[article.pmid] = article
        for article in articles:
            if article.pmid and article.pmid not in by_pmid and article.title:
                by_pmid[article.pmid] = article
        rows: list[dict[str, Any]] = []
        for pmid in pmids:
            if pmid in native:
                rows.append(native[pmid])
            elif pmid in by_pmid:
                rows.append(_article_record(by_pmid[pmid]))
            else:
                rows.append({"pmid": pmid, "metadata_missing": True})
        return rows


__all__ = ["PipelineRunRecorder", "RunObserver", "retrieval_summary"]
