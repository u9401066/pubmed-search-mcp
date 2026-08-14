"""Application service for executing persisted pipelines and storing run artifacts."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pubmed_search.application.pipeline.executor import (
    PipelineExecutor,
    classify_pipeline_outcome,
    pipeline_outcome_message,
    pipeline_run_status,
)
from pubmed_search.application.pipeline.report_generator import generate_pipeline_report
from pubmed_search.application.pipeline.templates import materialize_pipeline_config
from pubmed_search.domain.entities.pipeline import PipelineRun

if TYPE_CHECKING:
    from pubmed_search.application.pipeline.executor import (
        AlternateSearchFn,
        AlternateSearchPageFn,
        SourceKeyResolver,
    )
    from pubmed_search.application.pipeline.store import PipelineStore
    from pubmed_search.domain.entities.article import UnifiedArticle

logger = logging.getLogger(__name__)


class StoredPipelineRunner:
    """Execute a saved pipeline by name and persist its run metadata."""

    def __init__(
        self,
        *,
        store: PipelineStore,
        searcher: Any,
        alternate_search_fn: AlternateSearchFn | None = None,
        source_key_resolver: SourceKeyResolver | None = None,
        alternate_search_page_fn: AlternateSearchPageFn | None = None,
    ) -> None:
        self._store = store
        self._searcher = searcher
        self._alternate_search_fn = alternate_search_fn
        self._alternate_search_page_fn = alternate_search_page_fn
        self._source_key_resolver = source_key_resolver

    async def execute_saved_pipeline(self, name: str) -> PipelineRun:
        """Execute one saved pipeline and persist report + run history."""
        pipeline_name = name.strip().lower()
        config, meta = self._store.load(pipeline_name)
        config = materialize_pipeline_config(config, default_name=meta.name)

        executor = PipelineExecutor(
            searcher=self._searcher,
            alternate_search_fn=self._alternate_search_fn,
            source_key_resolver=self._source_key_resolver,
            alternate_search_page_fn=self._alternate_search_page_fn,
        )

        started = datetime.now(timezone.utc)
        run_id = self._store.create_run_id(meta.name, started)
        previous_run = self._store.get_latest_run(meta.name)
        previous_pmids = set(previous_run.pmids) if previous_run else set()

        try:
            articles, step_results = await executor.execute(config)
            finished = datetime.now(timezone.utc)
            report = generate_pipeline_report(articles, step_results, config)
            pmids = self._extract_pmids(articles)
            current_pmids = set(pmids)
            outcome_status = classify_pipeline_outcome(articles, step_results)
            run = PipelineRun(
                run_id=run_id,
                pipeline_name=meta.name,
                started=started,
                finished=finished,
                status=pipeline_run_status(outcome_status),
                article_count=len(articles),
                pmids=pmids,
                new_pmids=[pmid for pmid in pmids if pmid not in previous_pmids],
                # A partial/failed provider run cannot prove that previously
                # observed articles disappeared from the evidence set.
                removed_pmids=sorted(previous_pmids - current_pmids) if outcome_status == "completed" else [],
                error_message=pipeline_outcome_message(outcome_status),
                top_articles=self._summarize_articles(articles),
            )
            self._store.save_report(meta.name, run_id, report)
            self._store.save_run(meta.name, run)
            return run
        except Exception as exc:
            from pubmed_search.shared.source_contracts import normalize_source_adapter_error

            safe_error = normalize_source_adapter_error("pipeline", "execute_saved", exc)
            safe_message = (
                f"Unexpected upstream error ({type(exc).__name__})"
                if safe_error.kind == "unexpected"
                else safe_error.message
            )
            logger.error(  # noqa: TRY400 - traceback may contain the saved query
                "Saved pipeline execution failed (%s)",
                type(exc).__name__,
            )
            failed_run = PipelineRun(
                run_id=run_id,
                pipeline_name=meta.name,
                started=started,
                finished=datetime.now(timezone.utc),
                status="error",
                error_message=safe_message,
            )
            self._store.save_run(meta.name, failed_run)
            raise RuntimeError(safe_message) from None

    @staticmethod
    def _extract_pmids(articles: list[UnifiedArticle]) -> list[str]:
        """Collect PMIDs from the executed article list."""
        return [article.pmid for article in articles if article.pmid]

    @staticmethod
    def _summarize_articles(articles: list[UnifiedArticle], limit: int = 5) -> list[dict[str, Any]]:
        """Store a compact article summary alongside the run record."""
        summary: list[dict[str, Any]] = []
        for article in articles[:limit]:
            summary.append(
                {
                    "pmid": article.pmid,
                    "title": article.title,
                    "year": article.year,
                    "doi": article.doi,
                    "source": article.primary_source,
                }
            )
        return summary
