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
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Coroutine
from difflib import get_close_matches
from typing import TYPE_CHECKING, Any

from pubmed_search.domain.entities.pipeline import (
    MAX_PIPELINE_STEPS,
    VALID_ACTIONS,
    PipelineConfig,
    PipelineStep,
    StepResult,
)
from pubmed_search.infrastructure.sources.article_mapper import (
    article_from_core,
    article_from_europe_pmc,
    article_from_openalex,
    article_from_pubmed,
    article_from_scopus,
    article_from_semantic_scholar,
    article_from_web_of_science,
)
from pubmed_search.shared.article_identity import canonical_article_key

if TYPE_CHECKING:
    from pubmed_search.domain.entities.article import UnifiedArticle

# Type alias for alternate source search function (dependency injection)
AlternateSearchFn = Callable[..., Coroutine[Any, Any, list[dict[str, Any]]]]

logger = logging.getLogger(__name__)
_VARIABLE_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.-]*)\}")
_FULL_VARIABLE_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_.-]*)\}$")

_ARTICLE_TYPE_FUZZY_CUTOFF = 0.82
_ARTICLE_TYPE_ALIASES: dict[str, str] = {
    "rct": "randomized-controlled-trial",
    "randomizedtrial": "randomized-controlled-trial",
    "randomisedtrial": "randomized-controlled-trial",
    "randomizedcontrolledtrial": "randomized-controlled-trial",
    "randomisedcontrolledtrial": "randomized-controlled-trial",
    "controlledclinicaltrial": "clinical-trial",
    "clinicaltrial": "clinical-trial",
    "trial": "clinical-trial",
    "metaanalysis": "meta-analysis",
    "systematicreview": "systematic-review",
    "sysreview": "systematic-review",
    "journalarticle": "journal-article",
    "originalarticle": "journal-article",
    "casereport": "case-report",
    "casereports": "case-report",
    "conferencepaper": "conference-paper",
    "proceedings": "conference-paper",
    "bookchapter": "book-chapter",
}


class PipelineExecutor:
    """Executes a search pipeline DAG with automatic parallelisation."""

    def __init__(
        self,
        searcher: Any = None,
        alternate_search_fn: AlternateSearchFn | None = None,
    ) -> None:
        self._searcher = searcher
        self._alternate_search_fn = alternate_search_fn

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

        results: dict[str, StepResult] = {}
        for batch in batches:
            coros = []
            for step in batch:
                step_inputs = {sid: results[sid] for sid in step.inputs if sid in results}
                coros.append(self._execute_step(step, step_inputs))

            batch_outcomes = await asyncio.gather(*coros, return_exceptions=True)
            for step, outcome in zip(batch, batch_outcomes):
                if isinstance(outcome, BaseException):
                    results[step.id] = StepResult(
                        step_id=step.id,
                        action=step.action,
                        error=str(outcome),
                    )
                    if step.on_error == "abort":
                        msg = f"Pipeline aborted at step '{step.id}': {outcome}"
                        raise RuntimeError(msg)
                else:
                    results[step.id] = outcome

        # Collect final articles from the last step
        final_step_id = stop_at if stop_at else steps_to_run[-1].id
        if final_step_id not in results and results:
            final_step_id = next(reversed(results))
        final_step = results.get(final_step_id)
        final_articles: list[UnifiedArticle] = final_step.articles if final_step and final_step.ok else []

        # Apply ranking & limit from output config
        if final_articles:
            final_articles = self._apply_ranking(final_articles, config)
        limit = config.output.limit
        if limit and len(final_articles) > limit:
            final_articles = final_articles[:limit]

        return final_articles, results

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
        variables = dict(config.variables or {})
        resolved_globals = self._resolve_value(dict(config.globals or {}), variables)
        variable_scope = {**variables, **resolved_globals}

        prepared_steps: list[PipelineStep] = []
        for step in config.steps:
            merged_params = {**resolved_globals, **dict(step.params or {})}
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
                return str(variables[key])

            return _VARIABLE_PATTERN.sub(_replace, value)
        if isinstance(value, list):
            return [cls._resolve_value(item, variables) for item in value]
        if isinstance(value, dict):
            return {str(key): cls._resolve_value(item, variables) for key, item in value.items()}
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
        except Exception:
            logger.exception("Pipeline step '%s' (%s) failed", step.id, step.action)
            raise

    # =====================================================================
    # Actions — Search
    # =====================================================================

    async def _action_search(self, step: PipelineStep, inputs: dict[str, StepResult]) -> StepResult:
        """Execute parallel multi-source literature search."""
        from pubmed_search.infrastructure.sources.registry import get_source_registry

        query = self._resolve_query(step, inputs)
        if not query:
            return StepResult(
                step_id=step.id,
                action="search",
                error="No query provided or derivable from inputs",
            )

        sources_str: str = step.params.get("sources", "pubmed")
        source_list = [s.strip().lower() for s in sources_str.split(",") if s.strip()]
        limit = int(step.params.get("limit", 50))
        min_year = step.params.get("min_year")
        max_year = step.params.get("max_year")

        all_articles: list[UnifiedArticle] = []
        coros: list[Any] = []
        source_order: list[str] = []
        registry = get_source_registry()

        for source in source_list:
            resolved_source = registry.resolve_key(source) or source
            if resolved_source == "pubmed" and self._searcher:
                coros.append(self._search_pubmed(query, limit, min_year, max_year, step.params))
                source_order.append("pubmed")
                continue

            definition = registry.get(resolved_source)
            if (
                definition
                and definition.key != "pubmed"
                and definition.selectable_in_unified
                and definition.supports_primary_search
                and definition.alternate_search_runner
                and registry.is_enabled(definition.key)
            ):
                coros.append(self._search_alternate(definition.key, query, limit, min_year, max_year))
                source_order.append(definition.key)

        # Track per-source API return counts
        source_api_counts: dict[str, int] = {}
        outcomes = await asyncio.gather(*coros, return_exceptions=True)
        for i, outcome in enumerate(outcomes):
            src = source_order[i] if i < len(source_order) else "unknown"
            if isinstance(outcome, BaseException):
                logger.warning("Source search failed in pipeline: %s", outcome)
                source_api_counts[src] = 0
            else:
                all_articles.extend(outcome)
                source_api_counts[src] = len(outcome)

        # Deduplicate when multiple sources
        if len(source_list) > 1 and len(all_articles) > 1:
            from pubmed_search.application.search.result_aggregator import (
                ResultAggregator,
            )

            aggregator = ResultAggregator()
            all_articles, _ = aggregator.aggregate([all_articles])

        pmids = [a.pmid for a in all_articles if a.pmid]
        return StepResult(
            step_id=step.id,
            action="search",
            articles=all_articles,
            pmids=pmids,
            metadata={"query": query, "source_api_counts": source_api_counts},
        )

    async def _search_pubmed(
        self,
        query: str,
        limit: int,
        min_year: Any,
        max_year: Any,
        params: dict[str, Any],
    ) -> list[UnifiedArticle]:
        kwargs: dict[str, Any] = {}
        if min_year:
            kwargs["min_year"] = int(min_year)
        if max_year:
            kwargs["max_year"] = int(max_year)
        for key in ("age_group", "sex", "species", "language", "clinical_query"):
            if key in params:
                kwargs[key] = params[key]

        assert self._searcher is not None  # noqa: S101
        raw = await self._searcher.search(query=query, limit=limit, **kwargs)
        return [article_from_pubmed(r) for r in raw if r and "error" not in r]

    async def _search_alternate(
        self,
        source: str,
        query: str,
        limit: int,
        min_year: Any,
        max_year: Any,
    ) -> list[UnifiedArticle]:
        if self._alternate_search_fn is None:
            return []

        raw = await self._alternate_search_fn(
            query=query,
            source=source,
            limit=limit,
            min_year=int(min_year) if min_year else None,
            max_year=int(max_year) if max_year else None,
        )

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
                elements[key] = str(val)

        if not elements:
            return StepResult(
                step_id=step.id,
                action="pico",
                error="No PICO elements provided (need at least P and I)",
            )

        # High-precision: all elements ANDed
        combined_precision = " AND ".join(f"({v})" for v in elements.values())

        # High-recall: P AND (I OR C)
        recall_parts: list[str] = []
        if "P" in elements:
            recall_parts.append(f"({elements['P']})")
        ic = [elements[k] for k in ("I", "C") if k in elements]
        if ic:
            recall_parts.append("(" + " OR ".join(ic) + ")")
        combined_recall = " AND ".join(recall_parts)

        return StepResult(
            step_id=step.id,
            action="pico",
            metadata={
                "elements": elements,
                "combined_precision": combined_precision,
                "combined_recall": combined_recall,
            },
        )

    async def _action_expand(self, step: PipelineStep, inputs: dict[str, StepResult]) -> StepResult:
        """Expand a topic via PubTator3 / MeSH semantic enhancement."""
        topic = step.params.get("topic", "")
        if not topic:
            return StepResult(step_id=step.id, action="expand", error="No 'topic' provided")

        try:
            from pubmed_search.application.search.semantic_enhancer import (
                get_semantic_enhancer,
            )

            enhancer = get_semantic_enhancer()
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
        except Exception as exc:
            logger.warning("Semantic enhancement failed, using original: %s", exc)
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
        pmids: list[str] = list(step.params.get("pmids", []))
        for inp in inputs.values():
            if inp.ok and inp.pmids:
                pmids.extend(inp.pmids)
        pmids = list(dict.fromkeys(pmids))  # dedup, preserve order

        if not pmids or not self._searcher:
            return StepResult(
                step_id=step.id,
                action="details",
                error="No PMIDs or searcher unavailable",
            )

        raw = await self._searcher.fetch_details(pmids)
        articles = [article_from_pubmed(r) for r in raw if r and "error" not in r]
        return StepResult(
            step_id=step.id,
            action="details",
            articles=articles,
            pmids=[a.pmid for a in articles if a.pmid],
        )

    async def _action_related(self, step: PipelineStep, inputs: dict[str, StepResult]) -> StepResult:
        pmid = str(step.params.get("pmid", ""))
        limit = int(step.params.get("limit", 20))
        if not pmid or not self._searcher:
            return StepResult(step_id=step.id, action="related", error="No PMID or searcher")

        raw = await self._searcher.get_related_articles(pmid, limit)
        articles = [article_from_pubmed(r) for r in raw if r and "error" not in r]
        return StepResult(
            step_id=step.id,
            action="related",
            articles=articles,
            pmids=[a.pmid for a in articles if a.pmid],
        )

    async def _action_citing(self, step: PipelineStep, inputs: dict[str, StepResult]) -> StepResult:
        pmid = str(step.params.get("pmid", ""))
        limit = int(step.params.get("limit", 20))
        if not pmid or not self._searcher:
            return StepResult(step_id=step.id, action="citing", error="No PMID or searcher")

        raw = await self._searcher.get_citing_articles(pmid, limit)
        articles = [article_from_pubmed(r) for r in raw if r and "error" not in r]
        return StepResult(
            step_id=step.id,
            action="citing",
            articles=articles,
            pmids=[a.pmid for a in articles if a.pmid],
        )

    async def _action_references(self, step: PipelineStep, inputs: dict[str, StepResult]) -> StepResult:
        pmid = str(step.params.get("pmid", ""))
        limit = int(step.params.get("limit", 50))
        if not pmid or not self._searcher:
            return StepResult(step_id=step.id, action="references", error="No PMID or searcher")

        raw = await self._searcher.get_article_references(pmid, limit)
        articles = [article_from_pubmed(r) for r in raw if r and "error" not in r]
        return StepResult(
            step_id=step.id,
            action="references",
            articles=articles,
            pmids=[a.pmid for a in articles if a.pmid],
        )

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

        try:
            metrics_data = await self._searcher.get_citation_metrics(pmids)
            if metrics_data and isinstance(metrics_data, list):
                pmid_map: dict[str, dict[str, Any]] = {
                    str(md.get("pmid", "")): md for md in metrics_data if isinstance(md, dict)
                }
                for article in articles:
                    if article.pmid and article.pmid in pmid_map:
                        md = pmid_map[article.pmid]
                        # Store metrics in article metadata (best-effort)
                        if not hasattr(article, "_pipeline_metrics"):
                            object.__setattr__(article, "_pipeline_metrics", md)
        except Exception as exc:
            logger.warning("iCite enrichment failed: %s", exc)

        return StepResult(step_id=step.id, action="metrics", articles=articles, pmids=pmids)

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
        else:  # union (default)
            from pubmed_search.application.search.result_aggregator import (
                ResultAggregator,
            )

            aggregator = ResultAggregator()
            articles, _ = aggregator.aggregate(input_lists)

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
        requested_article_types = self._coerce_article_type_list(step.params.get("article_types", []))
        normalized_article_types, article_type_diagnostics = self._normalize_requested_article_types(
            requested_article_types
        )
        min_citations = step.params.get("min_citations")
        require_abstract = step.params.get("has_abstract", False)
        unknown_only_article_type_filter = bool(requested_article_types and not normalized_article_types)

        filtered: list[UnifiedArticle] = []
        reason_counter: Counter[str] = Counter()
        excluded_examples: list[dict[str, Any]] = []
        for a in articles:
            reasons: list[str] = []
            year = getattr(a, "year", None)
            if min_year and year and year < int(min_year):
                reasons.append("year_before_min")
            if max_year and year and year > int(max_year):
                reasons.append("year_after_max")
            if unknown_only_article_type_filter:
                reasons.append("unknown_article_type_filter")
            elif normalized_article_types:
                type_val = self._canonical_article_type_value(getattr(a, "article_type", None))
                if type_val not in normalized_article_types:
                    reasons.append("article_type_mismatch")
            if min_citations is not None:
                cc = self._article_citation_count(a)
                if cc < int(min_citations):
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
                "normalized_article_types": normalized_article_types,
                "min_citations": min_citations,
                "has_abstract": require_abstract,
            },
            "removal_reasons": dict(reason_counter),
            "excluded_examples": excluded_examples,
        }
        if article_type_diagnostics:
            metadata["article_type_diagnostics"] = article_type_diagnostics
        if unknown_only_article_type_filter:
            metadata["warning"] = "No requested article_types could be matched; all articles were excluded."
        elif articles and requested_article_types and not filtered:
            metadata["warning"] = (
                "Article type filter removed all articles. Check normalized_article_types and removal_reasons."
            )
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

    @classmethod
    def _coerce_article_type_list(cls, value: Any) -> list[str]:
        if not value:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, (list, tuple, set)):
            items: list[str] = []
            for item in value:
                if isinstance(item, str) and "," in item:
                    items.extend(cls._coerce_article_type_list(item))
                elif item is not None:
                    items.append(str(item).strip())
            return [item for item in items if item]
        return [str(value).strip()]

    @classmethod
    def _normalize_requested_article_types(
        cls,
        requested: list[str],
    ) -> tuple[list[str], dict[str, Any]]:
        normalized: list[str] = []
        mappings: dict[str, str] = {}
        fuzzy_matches: dict[str, str] = {}
        unknown: list[str] = []
        for item in requested:
            canonical, match_kind = cls._normalize_article_type_request(item)
            if canonical:
                if canonical not in normalized:
                    normalized.append(canonical)
                mappings[item] = canonical
                if match_kind == "fuzzy":
                    fuzzy_matches[item] = canonical
            else:
                unknown.append(item)

        diagnostics: dict[str, Any] = {}
        if mappings:
            diagnostics["mappings"] = mappings
        if fuzzy_matches:
            diagnostics["fuzzy_matches"] = fuzzy_matches
        if unknown:
            diagnostics["unknown"] = unknown
        return normalized, diagnostics

    @classmethod
    def _normalize_article_type_request(cls, value: Any) -> tuple[str | None, str]:
        key = cls._article_type_key(value)
        if not key:
            return None, "unknown"

        valid_map = cls._article_type_valid_map()
        alias_map = {**valid_map, **_ARTICLE_TYPE_ALIASES}
        if key in alias_map:
            match_kind = "exact" if key in valid_map else "alias"
            return alias_map[key], match_kind

        match = get_close_matches(key, list(alias_map.keys()), n=1, cutoff=_ARTICLE_TYPE_FUZZY_CUTOFF)
        if match:
            return alias_map[match[0]], "fuzzy"
        return None, "unknown"

    @classmethod
    def _canonical_article_type_value(cls, value: Any) -> str:
        if value is None:
            return "unknown"
        raw = value.value if hasattr(value, "value") else value
        canonical, _match_kind = cls._normalize_article_type_request(raw)
        return canonical or str(raw).strip().lower()

    @staticmethod
    def _article_type_key(value: Any) -> str:
        if value is None:
            return ""
        raw = value.value if hasattr(value, "value") else value
        return re.sub(r"[^a-z0-9]+", "", str(raw).strip().lower())

    @staticmethod
    def _article_type_valid_map() -> dict[str, str]:
        from pubmed_search.domain.entities.article import ArticleType

        mapping: dict[str, str] = {}
        for article_type in ArticleType:
            value = article_type.value
            mapping[re.sub(r"[^a-z0-9]+", "", value)] = value
        return mapping

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
        query = str(step.params.get("query", ""))
        if query:
            return query

        # 2. Derive from upstream inputs
        for inp_result in inputs.values():
            if not inp_result.ok:
                continue

            # From PICO step
            if inp_result.action == "pico":
                element = step.params.get("element")
                if element and element in inp_result.metadata.get("elements", {}):
                    return str(inp_result.metadata["elements"][element])
                use_combined = step.params.get("use_combined", "precision")
                if use_combined == "recall":
                    return str(inp_result.metadata.get("combined_recall", ""))
                return str(inp_result.metadata.get("combined_precision", ""))

            # From expand step
            if inp_result.action == "expand":
                strategy_name = step.params.get("strategy", "original")
                for strat in inp_result.metadata.get("strategies", []):
                    if strat.get("name") == strategy_name:
                        return str(strat.get("query", ""))
                # Fallback to expanded_query
                return str(inp_result.metadata.get("expanded_query", ""))

        return ""

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
