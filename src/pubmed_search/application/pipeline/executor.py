"""
PipelineExecutor — DAG-based search pipeline execution engine.

Executes a PipelineConfig by:
1. Validating step graph (no cycles, valid actions, valid references)
2. Topological-sorting steps into parallel batches (Kahn's algorithm)
3. Executing each batch concurrently via asyncio.gather
4. Passing StepResult between dependent steps
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Coroutine, Mapping
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Literal, cast

from pubmed_search.application.pipeline.action_contracts import (
    PIPELINE_SEARCH_SOURCES,
    allowed_pipeline_action_param_keys,
    canonical_article_type_values,
    validate_pipeline_action_contracts,
    validate_pipeline_details_pmids,
    validate_pipeline_discovery_pmid,
)
from pubmed_search.application.pipeline.budgets import (
    PipelineBudgetExceededError,
    PipelineExecutionPolicy,
    PipelineRunBudget,
    action_limit,
    validate_pipeline_budgets,
)
from pubmed_search.application.search.source_models import SourceSearchPage
from pubmed_search.domain.entities.article import CitationMetrics
from pubmed_search.domain.entities.pipeline import (
    MAX_PIPELINE_STEPS,
    VALID_ACTIONS,
    PipelineConfig,
    PipelineStep,
    StepResult,
)
from pubmed_search.domain.services.article_mapper import (
    article_from_core,
    article_from_europe_pmc,
    article_from_openalex,
    article_from_pubmed,
    article_from_scopus,
    article_from_semantic_scholar,
    article_from_web_of_science,
)
from pubmed_search.shared.article_identity import canonical_article_key
from pubmed_search.shared.source_contracts import (
    SourceAdapterResult,
    normalize_source_adapter_error,
    validate_source_adapter_mapping_result,
    validate_source_adapter_result,
)

if TYPE_CHECKING:
    from pubmed_search.domain.entities.article import UnifiedArticle

# Dependency-injection contracts for alternate-source search.
#
# ``AlternateSearchAdapterFn`` is the sole contract: items are provider DTOs and
# are mapped exactly once below.
AlternateSearchAdapterFn = Callable[
    ...,
    Coroutine[Any, Any, SourceAdapterResult[dict[str, Any]]],
]

logger = logging.getLogger(__name__)
_VARIABLE_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.-]*)\}")
_FULL_VARIABLE_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_.-]*)\}$")
_PIPELINE_ALTERNATE_SOURCES = frozenset(PIPELINE_SEARCH_SOURCES - {"pubmed"})
PipelineOutcomeStatus = Literal["completed", "partial", "failed"]


def classify_pipeline_outcome(
    articles: list[Any],
    step_results: Mapping[str, StepResult],
) -> PipelineOutcomeStatus:
    """Classify a pipeline execution from its structured step evidence.

    A source error alongside a valid response is partial, while a failed step
    with no final evidence is failed.  Keeping this classifier in the
    application layer prevents MCP responses, saved-run history, and scheduled
    execution metadata from assigning contradictory terminal states.
    """

    failed_steps = [result for result in step_results.values() if not result.ok]
    has_source_errors = any(
        isinstance(error, dict)
        for result in step_results.values()
        for error in list(result.metadata.get("source_errors") or [])
    )
    if failed_steps:
        return "partial" if articles else "failed"
    if has_source_errors:
        return "partial"
    return "completed"


def pipeline_run_status(status: PipelineOutcomeStatus) -> Literal["success", "partial", "error"]:
    """Map the shared outcome contract to the persisted PipelineRun schema."""

    if status == "completed":
        return "success"
    if status == "partial":
        return "partial"
    return "error"


def pipeline_outcome_message(status: PipelineOutcomeStatus) -> str | None:
    """Return a stable query-safe diagnostic for non-complete runs."""

    if status == "partial":
        return "Pipeline execution completed with source warnings or failed steps"
    if status == "failed":
        return "Pipeline execution completed with failed steps"
    return None


def _query_safe_action_failure(
    action: str,
    error: Exception,
    *,
    unexpected_message: str,
) -> tuple[str, dict[str, Any]]:
    """Normalize an action failure without persisting raw exception text."""
    normalized = normalize_source_adapter_error("pipeline", action, error)
    messages = {
        "http": "Pipeline action failed with an upstream HTTP error",
        "timeout": "Pipeline action timed out",
        "transport": "Pipeline action could not reach its upstream service",
        "retryable": "Pipeline action failed after a retryable upstream error",
        "unexpected": unexpected_message,
    }
    metadata: dict[str, Any] = {
        "error_type": type(error).__name__,
        "error_kind": normalized.kind,
        "retryable": normalized.retryable,
    }
    if normalized.status_code is not None:
        metadata["status_code"] = normalized.status_code
    return messages[normalized.kind], metadata


class PipelineExecutor:
    """Executes a search pipeline DAG with automatic parallelisation."""

    def __init__(
        self,
        searcher: Any = None,
        alternate_search_adapter: AlternateSearchAdapterFn | None = None,
        execution_policy: PipelineExecutionPolicy | None = None,
        semantic_enhancer_factory: Callable[[], Any] | None = None,
    ) -> None:
        """Create an executor with one validated provider-adapter seam."""

        self._searcher = searcher
        self._alternate_search_adapter = alternate_search_adapter
        self._execution_policy = execution_policy or PipelineExecutionPolicy()
        self._semantic_enhancer_factory = semantic_enhancer_factory
        self._run_budget: ContextVar[PipelineRunBudget | None] = ContextVar(
            "pipeline_run_budget",
            default=None,
        )

    # =====================================================================
    # Public API
    # =====================================================================

    async def execute(
        self,
        config: PipelineConfig,
        *,
        stop_at: str | None = None,
    ) -> tuple[list[UnifiedArticle], dict[str, StepResult]]:
        """Execute pipeline and return ``(final_articles, all_step_results)``."""
        config = self.prepare_config(config)
        self._validate(config)
        self._validate_stop_at(config, stop_at)

        steps_to_run = self._steps_through_stop_at(config.steps, stop_at)
        batches = self._topological_batches(steps_to_run)

        budget = PipelineRunBudget(self._execution_policy)
        budget_token = self._run_budget.set(budget)
        results: dict[str, StepResult] = {}
        try:
            for batch_index, batch in enumerate(batches):
                remaining = budget.remaining_seconds()
                if remaining <= 0:
                    budget.mark_deadline_exhausted()
                    self._record_unexecuted_budget_steps(
                        results,
                        [step for pending_batch in batches[batch_index:] for step in pending_batch],
                        budget,
                        reason="deadline_exhausted",
                    )
                    break

                tasks: list[asyncio.Task[StepResult]] = []
                for step in batch:
                    step_inputs = {sid: results[sid] for sid in step.inputs if sid in results}
                    tasks.append(asyncio.create_task(self._execute_step(step, step_inputs)))

                _done, pending = await asyncio.wait(tasks, timeout=remaining)
                for step, task in zip(batch, tasks):
                    if task in pending:
                        continue
                    try:
                        outcome: StepResult | BaseException = task.result()
                    except BaseException as exc:  # task results preserve cancellation semantics below
                        outcome = exc
                    self._record_step_outcome(results, step, outcome, budget)

                if pending:
                    budget.mark_deadline_exhausted()
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    pending_steps = [step for step, task in zip(batch, tasks) if task in pending]
                    future_steps = [step for pending_batch in batches[batch_index + 1 :] for step in pending_batch]
                    self._record_unexecuted_budget_steps(
                        results,
                        [*pending_steps, *future_steps],
                        budget,
                        reason="deadline_exhausted",
                    )
                    break

            # Attach the aggregate budget to the terminal step even when it
            # completed normally, so callers can audit actual resource use.
            terminal_step = next((step for step in reversed(steps_to_run) if step.id in results), None)
            if terminal_step is not None:
                results[terminal_step.id].metadata["run_budget"] = budget.snapshot()

            # Collect final articles from the last step. If a run budget ended
            # the DAG, retain the latest completed evidence as a typed partial.
            final_step_id = stop_at if stop_at else steps_to_run[-1].id
            if final_step_id not in results and results:
                final_step_id = next(reversed(results))
            final_step = results.get(final_step_id)
            final_articles: list[UnifiedArticle] = final_step.articles if final_step and final_step.ok else []
            budget_exhausted = budget.snapshot()["exhausted_reason"] is not None
            if budget_exhausted and not final_articles:
                for step in reversed(steps_to_run):
                    candidate = results.get(step.id)
                    if candidate and candidate.ok and candidate.articles:
                        final_articles = candidate.articles
                        break

            # Apply ranking & limit from output config
            if final_articles:
                final_articles = self._apply_ranking(final_articles, config)
            limit = config.output.limit
            if limit and len(final_articles) > limit:
                final_articles = final_articles[:limit]

            return final_articles, results
        finally:
            self._run_budget.reset(budget_token)

    def _record_step_outcome(
        self,
        results: dict[str, StepResult],
        step: PipelineStep,
        outcome: StepResult | BaseException,
        budget: PipelineRunBudget,
    ) -> None:
        """Record one task outcome using query-safe typed budget failures."""
        if not isinstance(outcome, BaseException):
            results[step.id] = outcome
            return
        if not isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, PipelineBudgetExceededError):
            results[step.id] = self._budget_failure_result(step, budget, outcome.reason)
        else:
            safe_error = normalize_source_adapter_error("pipeline", step.action, outcome)
            safe_message = (
                f"Unexpected upstream error ({type(outcome).__name__})"
                if safe_error.kind == "unexpected"
                else safe_error.message
            )
            results[step.id] = StepResult(
                step_id=step.id,
                action=step.action,
                error=safe_message,
            )
        if step.on_error == "abort":
            msg = f"Pipeline aborted at step '{step.id}' ({type(outcome).__name__})"
            raise RuntimeError(msg)

    @classmethod
    def _record_unexecuted_budget_steps(
        cls,
        results: dict[str, StepResult],
        steps: list[PipelineStep],
        budget: PipelineRunBudget,
        *,
        reason: str,
    ) -> None:
        for step in steps:
            results[step.id] = cls._budget_failure_result(step, budget, reason)

    @staticmethod
    def _budget_failure_result(
        step: PipelineStep,
        budget: PipelineRunBudget,
        reason: str,
    ) -> StepResult:
        message = (
            "Pipeline run deadline exhausted"
            if reason == "deadline_exhausted"
            else "Pipeline external-call quota exhausted"
        )
        return StepResult(
            step_id=step.id,
            action=step.action,
            error=message,
            metadata={
                "terminal_reason": reason,
                "retryable": True,
                "run_budget": budget.snapshot(),
            },
        )

    async def _reserve_external_call(self) -> None:
        budget = self._run_budget.get()
        if budget is not None:
            await budget.reserve_external_call()

    def dry_run(
        self,
        config: PipelineConfig,
        *,
        stop_at: str | None = None,
    ) -> tuple[list[UnifiedArticle], dict[str, StepResult]]:
        """Validate and resolve a pipeline without making external API calls."""
        config = self.prepare_config(config)
        self._validate(config)
        self._validate_stop_at(config, stop_at)

        results: dict[str, StepResult] = {}
        for batch in self._topological_batches(self._steps_through_stop_at(config.steps, stop_at)):
            for step in batch:
                results[step.id] = StepResult(
                    step_id=step.id,
                    action=step.action,
                    metadata={
                        "dry_run": True,
                        "planned_inputs": list(step.inputs),
                        "resolved_params": dict(step.params),
                        "note": "No searches or external API calls were executed.",
                    },
                )
        return [], results

    def prepare_config(self, config: PipelineConfig) -> PipelineConfig:
        """Apply globals and variable substitution to step parameters."""
        validate_pipeline_action_contracts(config, allow_variable_references=True)
        variables = dict(config.variables or {})
        resolved_globals = self._resolve_value(dict(config.globals or {}), variables)
        variable_scope = {**variables, **resolved_globals}

        prepared_steps: list[PipelineStep] = []
        for step in config.steps:
            action_global_params = {
                key: value
                for key, value in resolved_globals.items()
                if key in allowed_pipeline_action_param_keys(step.action)
            }
            merged_params = {**action_global_params, **dict(step.params or {})}
            resolved_params = self._resolve_value(merged_params, variable_scope)
            prepared_steps.append(
                PipelineStep(
                    id=step.id,
                    action=step.action,
                    params=resolved_params,
                    inputs=list(step.inputs),
                    on_error=step.on_error,
                )
            )

        return PipelineConfig(
            steps=prepared_steps,
            name=config.name,
            output=config.output,
            globals=resolved_globals,
            variables=variables,
            template=config.template,
            template_params=config.template_params,
        )

    @classmethod
    def _resolve_value(cls, value: Any, variables: dict[str, Any]) -> Any:
        if isinstance(value, str):
            full_match = _FULL_VARIABLE_PATTERN.match(value)
            if full_match and full_match.group(1) in variables:
                return variables[full_match.group(1)]

            def _replace(match: re.Match[str]) -> str:
                key = match.group(1)
                if key not in variables:
                    return match.group(0)
                replacement = variables[key]
                if not isinstance(replacement, str):
                    msg = f"Embedded pipeline variable '{key}' must resolve to a string"
                    raise TypeError(msg)
                return replacement

            return _VARIABLE_PATTERN.sub(_replace, value)
        if isinstance(value, list):
            return [cls._resolve_value(item, variables) for item in value]
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                msg = "Pipeline parameter keys must be strings"
                raise TypeError(msg)
            return {key: cls._resolve_value(item, variables) for key, item in value.items()}
        return value

    # =====================================================================
    # Validation
    # =====================================================================

    def _validate(self, config: PipelineConfig) -> None:
        if not config.steps:
            msg = "Pipeline must have at least one step"
            raise ValueError(msg)
        if len(config.steps) > MAX_PIPELINE_STEPS:
            msg = f"Pipeline exceeds maximum of {MAX_PIPELINE_STEPS} steps"
            raise ValueError(msg)
        validate_pipeline_budgets(config)
        validate_pipeline_action_contracts(config)

        seen_ids: set[str] = set()
        for step in config.steps:
            if not step.id:
                msg = "Every step must have a non-empty 'id'"
                raise ValueError(msg)
            if step.id in seen_ids:
                msg = f"Duplicate step id: '{step.id}'"
                raise ValueError(msg)
            seen_ids.add(step.id)

            if step.action not in VALID_ACTIONS:
                msg = f"Unknown action '{step.action}' in step '{step.id}'. Valid actions: {sorted(VALID_ACTIONS)}"
                raise ValueError(msg)

            for inp in step.inputs:
                if inp not in seen_ids:
                    msg = f"Step '{step.id}' references unknown input '{inp}'. Inputs must reference earlier steps."
                    raise ValueError(msg)

    @staticmethod
    def _validate_stop_at(config: PipelineConfig, stop_at: str | None) -> None:
        if not stop_at:
            return
        if stop_at not in {step.id for step in config.steps}:
            msg = f"stop_at step '{stop_at}' not found in pipeline"
            raise ValueError(msg)

    @staticmethod
    def _steps_through_stop_at(steps: list[PipelineStep], stop_at: str | None) -> list[PipelineStep]:
        if not stop_at:
            return steps

        step_map = {step.id: step for step in steps}
        required_ids: set[str] = set()

        def _visit(step_id: str) -> None:
            if step_id in required_ids:
                return
            step = step_map[step_id]
            for input_id in step.inputs:
                _visit(input_id)
            required_ids.add(step_id)

        _visit(stop_at)
        return [step for step in steps if step.id in required_ids]

    # =====================================================================
    # Topological Sort (Kahn's algorithm — batch by layer)
    # =====================================================================

    def _topological_batches(self, steps: list[PipelineStep]) -> list[list[PipelineStep]]:
        step_map = {s.id: s for s in steps}
        in_degree = {s.id: len(s.inputs) for s in steps}
        dependents: dict[str, list[str]] = defaultdict(list)
        for s in steps:
            for inp in s.inputs:
                dependents[inp].append(s.id)

        batches: list[list[PipelineStep]] = []
        ready = [s for s in steps if in_degree[s.id] == 0]

        while ready:
            batches.append(ready)
            next_ready: list[PipelineStep] = []
            for s in ready:
                for dep_id in dependents[s.id]:
                    in_degree[dep_id] -= 1
                    if in_degree[dep_id] == 0:
                        next_ready.append(step_map[dep_id])
            ready = next_ready

        executed_count = sum(len(b) for b in batches)
        if executed_count != len(steps):
            msg = "Pipeline contains a dependency cycle"
            raise ValueError(msg)

        return batches

    # =====================================================================
    # Step Dispatch
    # =====================================================================

    async def _execute_step(self, step: PipelineStep, inputs: dict[str, StepResult]) -> StepResult:
        handler_map: dict[str, Any] = {
            "search": self._action_search,
            "pico": self._action_pico,
            "expand": self._action_expand,
            "details": self._action_details,
            "related": self._action_related,
            "citing": self._action_citing,
            "references": self._action_references,
            "metrics": self._action_metrics,
            "merge": self._action_merge,
            "filter": self._action_filter,
        }
        handler = handler_map.get(step.action)
        if handler is None:
            return StepResult(
                step_id=step.id,
                action=step.action,
                error=f"No handler for action '{step.action}'",
            )
        try:
            result: StepResult = await handler(step, inputs)
            return result
        except Exception as exc:
            logger.warning("Pipeline step '%s' (%s) failed (%s)", step.id, step.action, type(exc).__name__)
            raise

    # =====================================================================
    # Actions — Search
    # =====================================================================

    async def _action_search(self, step: PipelineStep, inputs: dict[str, StepResult]) -> StepResult:
        """Execute parallel multi-source literature search."""
        query = self._resolve_query(step, inputs)
        if not query:
            return StepResult(
                step_id=step.id,
                action="search",
                error="No query provided or derivable from inputs",
            )

        sources_value = step.params.get("sources", ["pubmed"])
        if not isinstance(sources_value, list) or any(not isinstance(source, str) for source in sources_value):
            return StepResult(
                step_id=step.id,
                action="search",
                error="Pipeline search sources must be an array of canonical strings",
                metadata={"source_api_counts": {}, "source_errors": []},
            )
        source_list = sources_value

        try:
            limit = action_limit("search", step.params.get("limit"))
        except ValueError as exc:
            message, error_metadata = _query_safe_action_failure(
                "search",
                exc,
                unexpected_message="Invalid pipeline search limit",
            )
            return StepResult(
                step_id=step.id,
                action="search",
                error=message,
                metadata={
                    "source_api_counts": {},
                    "source_errors": [],
                    **error_metadata,
                },
            )

        unsupported_sources = [source for source in source_list if source not in PIPELINE_SEARCH_SOURCES]
        if unsupported_sources:
            return StepResult(
                step_id=step.id,
                action="search",
                error=f"Unsupported pipeline search source(s): {', '.join(unsupported_sources)}",
                metadata={
                    "requested_sources": source_list,
                    "source_api_counts": {},
                    "source_errors": [],
                },
            )

        unavailable_sources = [
            source
            for source in source_list
            if (source == "pubmed" and self._searcher is None)
            or (source in _PIPELINE_ALTERNATE_SOURCES and self._alternate_search_adapter is None)
        ]
        if unavailable_sources:
            return StepResult(
                step_id=step.id,
                action="search",
                error=f"Pipeline search adapter unavailable for: {', '.join(unavailable_sources)}",
                metadata={
                    "requested_sources": source_list,
                    "source_api_counts": {},
                    "source_errors": [],
                },
            )

        min_year = step.params.get("min_year")
        max_year = step.params.get("max_year")

        all_articles: list[UnifiedArticle] = []
        coros: list[Any] = []
        source_order: list[str] = []

        for source in source_list:
            if source == "pubmed" and self._searcher:
                coros.append(self._search_pubmed(query, limit, min_year, max_year, step.params))
                source_order.append("pubmed")
                continue

            if source in _PIPELINE_ALTERNATE_SOURCES and self._alternate_search_adapter:
                coros.append(self._search_alternate(source, query, limit, min_year, max_year))
                source_order.append(source)

        # Track per-source API return counts
        source_api_counts: dict[str, int] = {}
        source_errors: list[dict[str, Any]] = []
        source_results: dict[str, dict[str, Any]] = {}
        failed_sources: set[str] = set()
        if not coros:
            return StepResult(
                step_id=step.id,
                action="search",
                error="No runnable search sources were selected",
                metadata={"source_api_counts": {}, "source_errors": []},
            )
        outcomes = await asyncio.gather(*coros, return_exceptions=True)
        for i, outcome in enumerate(outcomes):
            src = source_order[i] if i < len(source_order) else "unknown"
            if isinstance(outcome, BaseException):
                if not isinstance(outcome, Exception):
                    raise outcome
                if isinstance(outcome, PipelineBudgetExceededError):
                    source_api_counts[src] = 0
                    failed_sources.add(src)
                    source_errors.append(
                        {
                            "source": src,
                            "operation": "pipeline_search",
                            "message": str(outcome),
                            "kind": "budget",
                            "retryable": True,
                            "status_code": None,
                            "status": "budget_exhausted",
                            "terminal_reason": outcome.reason,
                        }
                    )
                    continue
                normalized_error = normalize_source_adapter_error(src, "pipeline_search", outcome)
                safe_message = (
                    f"Unexpected upstream error ({type(outcome).__name__})"
                    if normalized_error.kind == "unexpected"
                    else normalized_error.message
                )
                logger.warning("Pipeline source %s failed (%s)", src, type(outcome).__name__)
                source_api_counts[src] = 0
                failed_sources.add(src)
                source_errors.append(
                    {
                        "source": src,
                        "operation": normalized_error.operation,
                        "message": safe_message,
                        "kind": normalized_error.kind,
                        "retryable": normalized_error.retryable,
                        "status_code": normalized_error.status_code,
                        "status": "rate_limited" if normalized_error.status_code == 429 else "error",
                    }
                )
                continue

            adapter_result = validate_source_adapter_result(
                outcome,
                expected_source=src,
                expected_operation="search",
            )
            all_articles.extend(adapter_result.items)
            source_api_counts[src] = len(adapter_result.items)
            source_results[src] = {
                "status": adapter_result.status,
                "total_count": adapter_result.total_count,
                "next_token": adapter_result.next_token,
                "cursor": adapter_result.cursor,
                "cost": adapter_result.cost,
                "provenance": adapter_result.provenance,
            }
            if adapter_result.status == "error":
                failed_sources.add(src)
            for adapter_error in adapter_result.errors:
                source_errors.append(
                    {
                        "source": src,
                        "operation": adapter_error.operation,
                        "message": f"{src} search failed safely ({adapter_error.kind})",
                        "kind": adapter_error.kind,
                        "retryable": adapter_error.retryable,
                        "status_code": adapter_error.status_code,
                        "status": "rate_limited" if adapter_error.status_code == 429 else "error",
                    }
                )

        # Deduplicate when multiple sources
        if len(source_list) > 1 and len(all_articles) > 1:
            from pubmed_search.application.search.result_aggregator import (
                ResultAggregator,
            )

            aggregator = ResultAggregator()
            all_articles, _ = aggregator.aggregate([all_articles])

        pmids = [a.pmid for a in all_articles if a.pmid]
        all_sources_failed = bool(source_order) and len(failed_sources) == len(source_order)
        return StepResult(
            step_id=step.id,
            action="search",
            articles=all_articles,
            pmids=pmids,
            metadata={
                "query": query,
                "source_api_counts": source_api_counts,
                "source_errors": source_errors,
                "source_results": source_results,
            },
            error="All selected search sources failed" if all_sources_failed else None,
        )

    async def _search_pubmed(
        self,
        query: str,
        limit: int,
        min_year: int | None,
        max_year: int | None,
        params: dict[str, Any],
    ) -> SourceAdapterResult[UnifiedArticle]:
        kwargs: dict[str, Any] = {}
        if min_year is not None:
            kwargs["min_year"] = min_year
        if max_year is not None:
            kwargs["max_year"] = max_year
        for key in ("age_group", "sex", "species", "language", "clinical_query"):
            if key in params:
                kwargs[key] = params[key]

        assert self._searcher is not None  # noqa: S101
        await self._reserve_external_call()
        page = await self._searcher.search_page(query=query, limit=limit, **kwargs)
        if not isinstance(page, SourceSearchPage) or page.source != "pubmed":
            raise TypeError("PubMed search must return a pubmed SourceSearchPage")
        if any(not isinstance(item, dict) or not str(item.get("pmid") or "").strip() for item in page.items):
            raise TypeError("PubMed search page contains an invalid article")
        if page.total is not None and (
            not isinstance(page.total, int) or isinstance(page.total, bool) or page.total < len(page.items)
        ):
            raise TypeError("PubMed search page contains an invalid total")
        articles = [article_from_pubmed(record) for record in page.items]
        physical_query = page.metadata.get("physical_query") or page.query
        return SourceAdapterResult(
            source="pubmed",
            operation="search",
            items=articles,
            total_count=page.total if page.total is not None else len(articles),
            status="ok" if articles else "empty",
            metadata={
                "total_available": page.total,
                "provider_mode": page.mode,
                "logical_query": query,
                "physical_query": physical_query,
                "query_executed": True,
                "provider_metadata": dict(page.metadata),
                "warnings": list(page.warnings),
            },
            next_token=page.next_token,
            cursor=page.cursor,
            cost=page.cost,
            provenance={
                "logical_query": query,
                "physical_query": physical_query,
                "provider_mode": page.mode,
                "query_executed": True,
                "provider_metadata": dict(page.metadata),
            },
        )

    async def _search_alternate(
        self,
        source: str,
        query: str,
        limit: int,
        min_year: int | None,
        max_year: int | None,
    ) -> SourceAdapterResult[UnifiedArticle]:
        kwargs = {
            "query": query,
            "source": source,
            "limit": limit,
            "min_year": min_year,
            "max_year": max_year,
        }
        if self._alternate_search_adapter is None:
            return SourceAdapterResult.empty(source=source, operation="search")
        await self._reserve_external_call()
        raw_result = validate_source_adapter_mapping_result(
            await self._alternate_search_adapter(**kwargs),
            expected_source=source,
            expected_operation="search",
        )
        mapped_items = self._map_provider_items(source, raw_result.items)
        mapped = SourceAdapterResult(
            source=raw_result.source,
            operation=raw_result.operation,
            items=mapped_items,
            total_count=raw_result.total_count,
            status=raw_result.status,
            errors=list(raw_result.errors),
            metadata=dict(raw_result.metadata),
            next_token=raw_result.next_token,
            cursor=raw_result.cursor,
            cost=raw_result.cost,
            provenance=dict(raw_result.provenance),
        )
        return cast(
            "SourceAdapterResult[UnifiedArticle]",
            validate_source_adapter_result(
                mapped,
                expected_source=source,
                expected_operation="search",
            ),
        )

    @staticmethod
    def _map_provider_items(source: str, raw: list[dict[str, Any]]) -> list[UnifiedArticle]:
        """Map provider DTOs from the validated adapter seam exactly once."""

        if source == "openalex":
            return [article_from_openalex(r) for r in raw]
        if source == "semantic_scholar":
            return [article_from_semantic_scholar(r) for r in raw]
        if source == "scopus":
            return [article_from_scopus(r) for r in raw]
        if source == "web_of_science":
            return [article_from_web_of_science(r) for r in raw]
        if source == "core":
            return [article_from_core(r) for r in raw]

        if source == "europe_pmc":
            return [article_from_europe_pmc(r) for r in raw]

        return [article_from_pubmed(r) for r in raw]

    # =====================================================================
    # Actions — Intelligence (PICO, Expand)
    # =====================================================================

    async def _action_pico(self, step: PipelineStep, inputs: dict[str, StepResult]) -> StepResult:
        """Accept pre-parsed PICO elements and generate query components."""
        elements: dict[str, str] = {}
        for key in ("P", "I", "C", "O"):
            val = step.params.get(key, "")
            if val:
                if not isinstance(val, str):
                    raise TypeError(f"PICO {key} must be a string")
                elements[key] = val

        if not elements:
            return StepResult(
                step_id=step.id,
                action="pico",
                error="No PICO elements provided (need at least P and I)",
            )
        missing_required = [key for key in ("P", "I") if key not in elements]
        if missing_required:
            return StepResult(
                step_id=step.id,
                action="pico",
                error=f"PICO step requires P and I; missing: {', '.join(missing_required)}",
            )

        query_elements: dict[str, str] = {}
        for key, value in elements.items():
            query_value = step.params.get(f"{key}_query") or value
            if not isinstance(query_value, str):
                raise TypeError(f"PICO {key}_query must be a string")
            query_elements[key] = query_value

        # High-precision: all elements ANDed
        combined_precision = " AND ".join(f"({v})" for v in query_elements.values())

        # High-recall: P AND (I OR C) AND O when O exists.
        recall_parts: list[str] = []
        if "P" in query_elements:
            recall_parts.append(f"({query_elements['P']})")
        ic = [query_elements[k] for k in ("I", "C") if k in query_elements]
        if ic:
            recall_parts.append("(" + " OR ".join(ic) + ")")
        if "O" in query_elements:
            recall_parts.append(f"({query_elements['O']})")
        combined_recall = " AND ".join(recall_parts)

        combined_intervention_outcome = ""
        if "I" in query_elements and "O" in query_elements:
            combined_intervention_outcome = f"({query_elements['I']}) AND ({query_elements['O']})"

        combined_comparison_outcome = ""
        if "C" in query_elements and "O" in query_elements:
            combined_comparison_outcome = f"({query_elements['C']}) AND ({query_elements['O']})"

        return StepResult(
            step_id=step.id,
            action="pico",
            metadata={
                "elements": elements,
                "query_elements": query_elements,
                "combined_precision": combined_precision,
                "combined_recall": combined_recall,
                "combined_intervention_outcome": combined_intervention_outcome,
                "combined_comparison_outcome": combined_comparison_outcome,
            },
        )

    async def _action_expand(self, step: PipelineStep, inputs: dict[str, StepResult]) -> StepResult:
        """Expand a topic via PubTator3 / MeSH semantic enhancement."""
        topic = step.params.get("topic", "")
        if not topic:
            return StepResult(step_id=step.id, action="expand", error="No 'topic' provided")

        try:
            if self._semantic_enhancer_factory is None:
                return StepResult(
                    step_id=step.id,
                    action="expand",
                    error="Semantic enhancer adapter is not configured",
                )
            enhancer = self._semantic_enhancer_factory()
            await self._reserve_external_call()
            enhanced = await enhancer.enhance(topic)

            strategies = [
                {
                    "name": sp.name,
                    "query": sp.query,
                    "source": sp.source,
                    "priority": sp.priority,
                }
                for sp in (enhanced.strategies or [])
            ]

            expanded_terms = []
            for t in enhanced.expanded_terms or []:
                expanded_terms.append(
                    {
                        "term": getattr(t, "term", str(t)),
                        "source": getattr(t, "source", "unknown"),
                        "confidence": getattr(t, "confidence", 1.0),
                    }
                )

            entities = []
            for e in enhanced.entities or []:
                entities.append(
                    {
                        "text": getattr(e, "text", str(e)),
                        "type": getattr(e, "type", "unknown"),
                    }
                )

            return StepResult(
                step_id=step.id,
                action="expand",
                metadata={
                    "original_query": topic,
                    "expanded_query": (strategies[0]["query"] if strategies else topic),
                    "strategies": strategies,
                    "expanded_terms": expanded_terms,
                    "entities": entities,
                },
            )
        except PipelineBudgetExceededError:
            raise
        except Exception as exc:
            logger.warning("Semantic enhancement failed, using original (%s)", type(exc).__name__)
            return StepResult(
                step_id=step.id,
                action="expand",
                metadata={
                    "original_query": topic,
                    "expanded_query": topic,
                    "strategies": [
                        {
                            "name": "original",
                            "query": topic,
                            "source": "pubmed",
                            "priority": 1,
                        }
                    ],
                },
            )

    # =====================================================================
    # Actions — Discovery (details, related, citing, references)
    # =====================================================================

    async def _action_details(self, step: PipelineStep, inputs: dict[str, StepResult]) -> StepResult:
        """Fetch article details by PMIDs."""
        pmids = validate_pipeline_details_pmids(step.params.get("pmids", []))
        for inp in inputs.values():
            if inp.ok and inp.pmids:
                pmids.extend(inp.pmids)
        pmids = validate_pipeline_details_pmids(pmids)

        if not pmids or not self._searcher:
            return StepResult(
                step_id=step.id,
                action="details",
                error="No PMIDs or searcher unavailable",
            )

        await self._reserve_external_call()
        raw = await self._searcher.fetch_details(pmids)
        articles = [article_from_pubmed(row) for row in self._require_pubmed_rows(raw, operation="fetch_details")]
        return StepResult(
            step_id=step.id,
            action="details",
            articles=articles,
            pmids=[a.pmid for a in articles if a.pmid],
        )

    async def _action_related(self, step: PipelineStep, inputs: dict[str, StepResult]) -> StepResult:
        raw_pmid = step.params.get("pmid")
        pmid = validate_pipeline_discovery_pmid(raw_pmid, action="related") if raw_pmid is not None else ""
        try:
            limit = action_limit("related", step.params.get("limit"))
        except ValueError as exc:
            message, metadata = _query_safe_action_failure(
                "related",
                exc,
                unexpected_message="Invalid pipeline related-article limit",
            )
            return StepResult(step_id=step.id, action="related", error=message, metadata=metadata)
        if not pmid or not self._searcher:
            return StepResult(step_id=step.id, action="related", error="No PMID or searcher")

        await self._reserve_external_call()
        raw = await self._searcher.get_related_articles(pmid, limit)
        articles = [
            article_from_pubmed(row) for row in self._require_pubmed_rows(raw, operation="get_related_articles")
        ]
        return StepResult(
            step_id=step.id,
            action="related",
            articles=articles,
            pmids=[a.pmid for a in articles if a.pmid],
        )

    async def _action_citing(self, step: PipelineStep, inputs: dict[str, StepResult]) -> StepResult:
        raw_pmid = step.params.get("pmid")
        pmid = validate_pipeline_discovery_pmid(raw_pmid, action="citing") if raw_pmid is not None else ""
        try:
            limit = action_limit("citing", step.params.get("limit"))
        except ValueError as exc:
            message, metadata = _query_safe_action_failure(
                "citing",
                exc,
                unexpected_message="Invalid pipeline citing-article limit",
            )
            return StepResult(step_id=step.id, action="citing", error=message, metadata=metadata)
        if not pmid or not self._searcher:
            return StepResult(step_id=step.id, action="citing", error="No PMID or searcher")

        await self._reserve_external_call()
        raw = await self._searcher.get_citing_articles(pmid, limit)
        articles = [article_from_pubmed(row) for row in self._require_pubmed_rows(raw, operation="get_citing_articles")]
        return StepResult(
            step_id=step.id,
            action="citing",
            articles=articles,
            pmids=[a.pmid for a in articles if a.pmid],
        )

    async def _action_references(self, step: PipelineStep, inputs: dict[str, StepResult]) -> StepResult:
        raw_pmid = step.params.get("pmid")
        pmid = validate_pipeline_discovery_pmid(raw_pmid, action="references") if raw_pmid is not None else ""
        try:
            limit = action_limit("references", step.params.get("limit"))
        except ValueError as exc:
            message, metadata = _query_safe_action_failure(
                "references",
                exc,
                unexpected_message="Invalid pipeline reference limit",
            )
            return StepResult(step_id=step.id, action="references", error=message, metadata=metadata)
        if not pmid or not self._searcher:
            return StepResult(step_id=step.id, action="references", error="No PMID or searcher")

        await self._reserve_external_call()
        raw = await self._searcher.get_article_references(pmid, limit)
        articles = [
            article_from_pubmed(row) for row in self._require_pubmed_rows(raw, operation="get_article_references")
        ]
        return StepResult(
            step_id=step.id,
            action="references",
            articles=articles,
            pmids=[a.pmid for a in articles if a.pmid],
        )

    @staticmethod
    def _require_pubmed_rows(value: object, *, operation: str) -> list[dict[str, Any]]:
        """Validate PubMed client rows without legacy error-sentinel filtering."""
        if not isinstance(value, list):
            raise TypeError(f"{operation} must return a list of article dictionaries")
        if any(not isinstance(row, dict) or not row for row in value):
            raise TypeError(f"{operation} returned an invalid article row")
        return cast("list[dict[str, Any]]", value)

    # =====================================================================
    # Actions — Enrichment (metrics)
    # =====================================================================

    async def _action_metrics(self, step: PipelineStep, inputs: dict[str, StepResult]) -> StepResult:
        """Enrich input articles with iCite citation metrics."""
        articles: list[UnifiedArticle] = []
        for inp in inputs.values():
            if inp.ok:
                articles.extend(inp.articles)

        pmids = [a.pmid for a in articles if a.pmid]
        if not pmids or not self._searcher:
            return StepResult(step_id=step.id, action="metrics", articles=articles, pmids=pmids)

        metadata: dict[str, Any] = {"metrics_requested": len(pmids), "metrics_enriched": 0}
        try:
            await self._reserve_external_call()
            metrics_data = await self._searcher.get_citation_metrics(pmids)
            pmid_map = self._require_icite_mapping(metrics_data)

            for article in articles:
                if not article.pmid or article.pmid not in pmid_map:
                    continue
                self._apply_icite_metrics(article, pmid_map[article.pmid])
                metadata["metrics_enriched"] += 1
        except PipelineBudgetExceededError:
            raise
        except Exception as exc:
            logger.warning("iCite enrichment failed (%s)", type(exc).__name__)
            metadata["warning"] = f"iCite enrichment failed safely ({type(exc).__name__})"

        return StepResult(
            step_id=step.id,
            action="metrics",
            articles=articles,
            pmids=pmids,
            metadata=metadata,
        )

    @staticmethod
    def _require_icite_mapping(value: object) -> dict[str, dict[str, Any]]:
        """Validate the canonical PMID-keyed iCite response contract."""
        if not isinstance(value, dict):
            raise TypeError("get_citation_metrics must return a PMID-keyed mapping")
        normalized: dict[str, dict[str, Any]] = {}
        for raw_pmid, raw_metrics in value.items():
            if not isinstance(raw_metrics, dict):
                raise TypeError("get_citation_metrics returned a non-mapping metric row")
            normalized[str(raw_pmid)] = raw_metrics
        return normalized

    @classmethod
    def _apply_icite_metrics(cls, article: UnifiedArticle, raw: dict[str, Any]) -> None:
        """Merge one canonical iCite row into the article domain model."""
        metrics = article.citation_metrics or CitationMetrics()
        citation_count = cls._optional_int(raw.get("citation_count"))
        rcr = cls._optional_float(raw.get("relative_citation_ratio"))
        percentile = cls._optional_float(raw.get("nih_percentile"))
        apt = cls._optional_float(raw.get("apt"))
        citations_per_year = cls._optional_float(raw.get("citations_per_year"))
        if citation_count is not None:
            metrics.citation_count = citation_count
        if rcr is not None:
            metrics.relative_citation_ratio = rcr
        if percentile is not None:
            metrics.nih_percentile = percentile
        if apt is not None:
            metrics.apt = apt
        if citations_per_year is not None:
            metrics.citations_per_year = citations_per_year
        article.citation_metrics = metrics

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return parsed if math.isfinite(parsed) else None

    # =====================================================================
    # Actions — Aggregation (merge, filter)
    # =====================================================================

    async def _action_merge(self, step: PipelineStep, inputs: dict[str, StepResult]) -> StepResult:
        """Merge articles from multiple input steps."""
        method = step.params.get("method", "union")

        input_lists: list[list[UnifiedArticle]] = []
        for inp in inputs.values():
            if inp.ok and inp.articles:
                input_lists.append(inp.articles)

        if not input_lists:
            return StepResult(step_id=step.id, action="merge", articles=[], pmids=[])

        if method == "intersection":
            articles = self._intersect_articles(input_lists)
        elif method == "rrf":
            articles = self._rrf_merge(input_lists)
        elif method == "union":
            from pubmed_search.application.search.result_aggregator import (
                ResultAggregator,
            )

            aggregator = ResultAggregator()
            articles, _ = aggregator.aggregate(input_lists)
        else:
            msg = "Pipeline merge method must be one of: intersection, rrf, union"
            raise ValueError(msg)

        pmids = [a.pmid for a in articles if a.pmid]
        return StepResult(step_id=step.id, action="merge", articles=articles, pmids=pmids)

    async def _action_filter(self, step: PipelineStep, inputs: dict[str, StepResult]) -> StepResult:
        """Post-filter articles by year, type, citations, etc."""
        articles: list[UnifiedArticle] = []
        for inp in inputs.values():
            if inp.ok:
                articles.extend(inp.articles)

        min_year = step.params.get("min_year")
        max_year = step.params.get("max_year")
        article_types_value = step.params.get("article_types", [])
        if not isinstance(article_types_value, list):
            raise TypeError("Pipeline filter article_types must be an array of canonical strings")
        requested_article_types = article_types_value
        min_citations = step.params.get("min_citations")
        require_abstract = step.params.get("has_abstract", False)

        filtered: list[UnifiedArticle] = []
        reason_counter: Counter[str] = Counter()
        excluded_examples: list[dict[str, Any]] = []
        for a in articles:
            reasons: list[str] = []
            year = getattr(a, "year", None)
            if min_year is not None and year and year < min_year:
                reasons.append("year_before_min")
            if max_year is not None and year and year > max_year:
                reasons.append("year_after_max")
            if requested_article_types:
                type_val = self._canonical_article_type_value(getattr(a, "article_type", None))
                if type_val not in requested_article_types:
                    reasons.append("article_type_mismatch")
            if min_citations is not None:
                cc = self._article_citation_count(a)
                if cc < min_citations:
                    reasons.append("citation_count_below_min")
            if require_abstract and not getattr(a, "abstract", None):
                reasons.append("missing_abstract")
            if reasons:
                reason_counter.update(reasons)
                if len(excluded_examples) < 5:
                    excluded_examples.append(self._excluded_article_example(a, reasons))
                continue
            filtered.append(a)

        pmids = [a.pmid for a in filtered if a.pmid]
        metadata: dict[str, Any] = {
            "before_count": len(articles),
            "after_count": len(filtered),
            "removed_count": len(articles) - len(filtered),
            "filters": {
                "min_year": min_year,
                "max_year": max_year,
                "article_types": requested_article_types,
                "normalized_article_types": requested_article_types,
                "min_citations": min_citations,
                "has_abstract": require_abstract,
            },
            "removal_reasons": dict(reason_counter),
            "excluded_examples": excluded_examples,
        }
        if articles and requested_article_types and not filtered:
            metadata["warning"] = "Article type filter removed all articles. Check article_types and removal_reasons."
        return StepResult(step_id=step.id, action="filter", articles=filtered, pmids=pmids, metadata=metadata)

    @classmethod
    def _article_citation_count(cls, article: UnifiedArticle) -> int:
        direct = getattr(article, "citation_count", None)
        if direct is not None:
            return cls._coerce_int(direct)

        metrics = getattr(article, "citation_metrics", None)
        if metrics is not None:
            count = getattr(metrics, "citation_count", None)
            if count is not None:
                return cls._coerce_int(count)

        pipeline_metrics = getattr(article, "_pipeline_metrics", None)
        if isinstance(pipeline_metrics, dict):
            for key in ("citation_count", "citations", "cited_by_count", "citedByCount"):
                count = pipeline_metrics.get(key)
                if count is not None:
                    return cls._coerce_int(count)

        return 0

    @staticmethod
    def _coerce_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _canonical_article_type_value(value: Any) -> str:
        if value is None:
            return "unknown"
        raw = value.value if hasattr(value, "value") else value
        if isinstance(raw, str) and raw in canonical_article_type_values():
            return raw
        return "unknown"

    @classmethod
    def _excluded_article_example(cls, article: UnifiedArticle, reasons: list[str]) -> dict[str, Any]:
        return {
            "pmid": getattr(article, "pmid", None),
            "title": getattr(article, "title", None),
            "year": getattr(article, "year", None),
            "article_type": cls._canonical_article_type_value(getattr(article, "article_type", None)),
            "reasons": reasons,
        }

    # =====================================================================
    # Merge Utilities
    # =====================================================================

    @staticmethod
    def _article_key(article: UnifiedArticle) -> str:
        """Canonical key for dedup / set operations."""
        return canonical_article_key(article)

    def _intersect_articles(self, article_lists: list[list[UnifiedArticle]]) -> list[UnifiedArticle]:
        """Keep only articles present in ALL input lists."""
        if not article_lists:
            return []
        if len(article_lists) == 1:
            return list(article_lists[0])

        key_to_article: dict[str, UnifiedArticle] = {}
        key_sets: list[set[str]] = []
        for articles in article_lists:
            keys: set[str] = set()
            for a in articles:
                k = self._article_key(a)
                keys.add(k)
                if k not in key_to_article:
                    key_to_article[k] = a
            key_sets.append(keys)

        common = key_sets[0]
        for ks in key_sets[1:]:
            common &= ks

        return [key_to_article[k] for k in common if k in key_to_article]

    def _rrf_merge(
        self,
        article_lists: list[list[UnifiedArticle]],
        k: int = 60,
    ) -> list[UnifiedArticle]:
        """Reciprocal Rank Fusion across multiple ranked lists."""
        rrf_scores: dict[str, float] = defaultdict(float)
        key_to_article: dict[str, UnifiedArticle] = {}

        for articles in article_lists:
            for rank_pos, article in enumerate(articles):
                key = self._article_key(article)
                rrf_scores[key] += 1.0 / (k + rank_pos + 1)
                if key not in key_to_article:
                    key_to_article[key] = article

        sorted_keys = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)
        return [key_to_article[k] for k in sorted_keys if k in key_to_article]

    # =====================================================================
    # Query Resolution
    # =====================================================================

    @staticmethod
    def _resolve_query(step: PipelineStep, inputs: dict[str, StepResult]) -> str:
        """Derive search query from step params or upstream step results."""
        # 1. Explicit query param
        query = step.params.get("query")
        if query is not None:
            if not isinstance(query, str):
                raise TypeError("Pipeline search query must be a string")
            return query

        # 2. Derive from upstream inputs
        for inp_result in inputs.values():
            if not inp_result.ok:
                continue

            # From PICO step
            if inp_result.action == "pico":
                element = step.params.get("element")
                query_elements = inp_result.metadata.get("query_elements", {})
                if not isinstance(query_elements, dict):
                    raise TypeError("PICO query_elements metadata must be a mapping")
                if element and element in query_elements:
                    return PipelineExecutor._require_query_metadata(query_elements[element], "PICO query element")
                elements = inp_result.metadata.get("elements", {})
                if not isinstance(elements, dict):
                    raise TypeError("PICO elements metadata must be a mapping")
                if element and element in elements:
                    return PipelineExecutor._require_query_metadata(elements[element], "PICO element")
                use_combined = step.params.get("use_combined", "precision")
                metadata_key = {
                    "precision": "combined_precision",
                    "recall": "combined_recall",
                    "intervention_outcome": "combined_intervention_outcome",
                    "comparison_outcome": "combined_comparison_outcome",
                }.get(use_combined)
                if metadata_key is None:
                    raise ValueError(f"Unknown PICO combined query mode: {use_combined}")
                return PipelineExecutor._require_query_metadata(
                    inp_result.metadata.get(metadata_key, ""),
                    f"PICO {use_combined} query",
                )

            # From expand step
            if inp_result.action == "expand":
                strategy_name = step.params.get("strategy")
                if strategy_name is None:
                    return PipelineExecutor._require_query_metadata(
                        inp_result.metadata.get("expanded_query", ""),
                        "expanded query",
                    )
                strategies = inp_result.metadata.get("strategies", [])
                if not isinstance(strategies, list):
                    raise TypeError("Expansion strategies metadata must be an array")
                for strategy in strategies:
                    if isinstance(strategy, dict) and strategy.get("name") == strategy_name:
                        return PipelineExecutor._require_query_metadata(
                            strategy.get("query", ""),
                            f"expansion strategy '{strategy_name}'",
                        )
                raise ValueError(f"Expansion strategy '{strategy_name}' was not produced by the upstream step")

        return ""

    @staticmethod
    def _require_query_metadata(value: Any, label: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{label} metadata must be a string")
        return value

    # =====================================================================
    # Output Ranking
    # =====================================================================

    @staticmethod
    def _apply_ranking(articles: list[UnifiedArticle], config: PipelineConfig) -> list[UnifiedArticle]:
        from pubmed_search.application.search.result_aggregator import (
            RankingConfig,
            ResultAggregator,
        )

        preset_map = {
            "balanced": RankingConfig.default,
            "impact": RankingConfig.impact_focused,
            "recency": RankingConfig.recency_focused,
            "quality": RankingConfig.quality_focused,
        }
        factory = preset_map.get(config.output.ranking, RankingConfig.default)
        return ResultAggregator().rank(articles, factory())
