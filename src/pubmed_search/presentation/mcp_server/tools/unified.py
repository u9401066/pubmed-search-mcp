"""
Unified Search Tool - Single Entry Point for Multi-Source Academic Search

Design Philosophy:
    單一入口 + 後端自動分流（像 Google 一樣）
    每次搜尋都又深又廣！

Architecture (Phase 3 Enhanced):
    User Query
         │
         ▼
    QueryAnalyzer → SemanticEnhancer → DispatchStrategy
         │
    ┌────┴────┬──────────┐
    ▼         ▼          ▼
  PubMed   CrossRef   OpenAlex  (parallel)
    │         │          │
    └────┬────┴──────────┘
         │
    ResultAggregator → UnifiedArticle[]

This module is the thin orchestration layer.
Implementation details are in:
  - unified_helpers.py      — ICD detection, dispatch, parsers, dataclasses
  - unified_source_search.py — source searches, deep search, auto-relax
  - unified_enrichment.py   — CrossRef, journal metrics, Unpaywall, similarity
  - unified_formatting.py   — Markdown & JSON output formatting
  - unified_pipeline.py     — pipeline execution & report auto-save
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, TypeVar, Union, cast

from mcp.server.fastmcp import Context  # noqa: TC002 - FastMCP needs runtime access for type annotation injection

from pubmed_search.application.search.query_analyzer import (
    QueryAnalyzer,
)
from pubmed_search.application.search.semantic_enhancer import get_semantic_enhancer
from pubmed_search.application.timeline import TimelineBuilder, build_research_tree
from pubmed_search.infrastructure.sources.registry import SourceSelectionError, get_source_registry

from .agent_output import is_structured_output_format
from .tool_input import InputNormalizer
from .tool_response import ResponseFormatter
from .unified_enrichment import (
    _enrich_with_api_similarity,
    _enrich_with_crossref,
    _enrich_with_journal_metrics,
    _enrich_with_similarity_scores,
    _enrich_with_unpaywall,
    _extract_openalex_source_id,
    _is_preprint,
)
from .unified_execution import execute_unified_search
from .unified_formatting import _format_as_json, _format_unified_results
from .unified_helpers import (
    ICD9_PATTERN,
    ICD10_PATTERN,
    DispatchStrategy,
    RelaxationResult,
    RelaxationStep,
    SearchDepthMetrics,
    StrategyResult,
    _generate_relaxation_steps,
    _parse_filters,
    _parse_options,
    detect_and_expand_icd_codes,
)
from .unified_pipeline import (
    _auto_save_pipeline_report,
    _execute_pipeline_mode,
    _parse_pipeline_config,
)
from .unified_planning import build_unified_search_plan
from .unified_request import normalize_unified_search_request
from .unified_source_search import (
    _auto_relax_search,
    _execute_deep_search,
    _search_core,
    _search_europe_pmc,
    _search_openalex,
    _search_pubmed,
    _search_scopus,
    _search_semantic_scholar,
    _search_web_of_science,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)
ToolFunc = TypeVar("ToolFunc", bound=Callable[..., Any])

# ---------------------------------------------------------------------------
# Backward-compatible re-exports (used by tests and __init__.py)
# ---------------------------------------------------------------------------
__all__ = [
    "register_unified_search_tools",
    # helpers
    "DispatchStrategy",
    "ICD10_PATTERN",
    "ICD9_PATTERN",
    "detect_and_expand_icd_codes",
    "_parse_filters",
    "_parse_options",
    "StrategyResult",
    "SearchDepthMetrics",
    "RelaxationStep",
    "RelaxationResult",
    "_generate_relaxation_steps",
    # source search
    "_auto_relax_search",
    "_execute_deep_search",
    "_search_pubmed",
    "_search_openalex",
    "_search_semantic_scholar",
    "_search_core",
    "_search_europe_pmc",
    "_search_web_of_science",
    # enrichment
    "_enrich_with_api_similarity",
    "_enrich_with_crossref",
    "_enrich_with_journal_metrics",
    "_extract_openalex_source_id",
    "_enrich_with_unpaywall",
    "_is_preprint",
    "_enrich_with_similarity_scores",
    # formatting
    "_format_unified_results",
    "_format_as_json",
    # pipeline
    "_execute_pipeline_mode",
    "_parse_pipeline_config",
    "_auto_save_pipeline_report",
]


# ============================================================================
# MCP Tool Registration
# ============================================================================


def _tool_decorator_with_optional_meta(mcp: FastMCP) -> Callable[[ToolFunc], ToolFunc]:
    """Return a tool decorator that tolerates simple test doubles without keyword support."""
    tool = cast("Any", mcp.tool)
    with contextlib.suppress(TypeError):
        return cast(
            "Callable[[ToolFunc], ToolFunc]",
            tool(meta={"pubmedSearch": {"experimentalTaskSupport": "optional"}}),
        )
    return cast("Callable[[ToolFunc], ToolFunc]", tool())


def register_unified_search_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """Register unified search MCP tools."""

    @_tool_decorator_with_optional_meta(mcp)
    async def unified_search(
        query: str,
        limit: Union[int, str] = 10,
        sources: Union[str, None] = None,
        ranking: Literal["balanced", "impact", "recency", "quality"] = "balanced",
        output_format: Literal["markdown", "json", "toon"] = "markdown",
        filters: Union[str, None] = None,
        options: Union[str, None] = None,
        pipeline: Union[str, None] = None,
        ctx: Context | None = None,
    ) -> str:
        """
        🔍 Unified Search - Single entry point for multi-source academic search.

        Automatically analyzes your query and searches the best sources.
        No need to choose between PubMed, OpenAlex, CrossRef, etc.

        ═══════════════════════════════════════════════════════════════════
        WHAT IT DOES:
        ═══════════════════════════════════════════════════════════════════
        1. Analyzes your query (complexity, intent, PICO elements)
        2. Automatically selects best sources based on query type
        3. Searches multiple sources in parallel
        4. Deduplicates and merges results
        5. Ranks by configurable criteria
        6. Enriches with OA links (Unpaywall)
        7. Auto-detects ICD-9/10 codes and expands to MeSH terms
        8. Optionally searches preprints (arXiv, medRxiv, bioRxiv)

        ═══════════════════════════════════════════════════════════════════
        EXAMPLES (most calls only need 1-2 params):
        ═══════════════════════════════════════════════════════════════════

        Simple (1 param):
            unified_search("remimazolam ICU sedation")

        With limit (2 params):
            unified_search("machine learning in anesthesia", limit=20)

        Specify sources:
            unified_search("CRISPR gene therapy", sources="pubmed,openalex")

        Auto minus one source:
            unified_search("sepsis biomarkers", sources="auto,-semantic_scholar")

        Search all enabled sources except enrichment-only CrossRef:
            unified_search("icu sedation", sources="all,-crossref")

        Clinical filters:
            unified_search("diabetes treatment",
                          filters="year:2020-2025, age:aged, clinical:therapy")

        Include preprints + shallow search:
            unified_search("COVID-19 vaccine", options="preprints, shallow")

        Full control:
            unified_search("propofol vs remimazolam",
                          sources="pubmed,semantic_scholar,europe_pmc",
                          ranking="impact",
                          filters="year:2020-, sex:female, species:humans",
                          options="preprints, no_relax")

        ICD Code Auto-Detection:
            unified_search("E11 complications")
            → Auto-expands E11 to "Diabetes Mellitus, Type 2"[MeSH]

        Args:
            query: Your search query (natural language, ICD codes, or structured)
            limit: Maximum results per source (default 10, max 100)
            sources: Comma-separated list of sources to search.
                     Available: "pubmed", "openalex", "semantic_scholar",
                     "europe_pmc", "crossref", "core".
                     Commercial connectors may also appear when enabled via env,
                     e.g. "scopus" when `SCOPUS_ENABLED=true` and
                     `SCOPUS_API_KEY` are configured, or "web_of_science"
                     when `WEB_OF_SCIENCE_ENABLED=true` and
                     `WEB_OF_SCIENCE_API_KEY` are configured.
                     Default: auto-select based on query complexity.
                     Supports "auto" and "all" with exclusions.
                     Examples: "pubmed,openalex", "auto,-semantic_scholar",
                     or "all,-crossref"
                     Global disable env: `PUBMED_SEARCH_DISABLED_SOURCES`
                     Example: `PUBMED_SEARCH_DISABLED_SOURCES=semantic_scholar,core`
            ranking: Ranking strategy:
                - "balanced": Default, considers all factors
                - "impact": Prioritize high-citation papers
                - "recency": Prioritize recent publications
                - "quality": Prioritize high-evidence studies (RCTs, meta-analyses)
            output_format: "markdown" (human-readable), "json", or "toon" (programmatic)
            filters: Comma-separated key:value pairs for filtering results.
                     Supported keys:
                       year:2020-2025    → publication year range
                       year:2020-        → from 2020 onwards
                       year:-2025        → up to 2025
                       year:2024         → from 2024 onwards
                       age:<value>       → age group filter (PubMed).
                                           Values: newborn, infant, preschool, child,
                                           adolescent, young_adult, adult, middle_aged,
                                           aged, aged_80
                       sex:<value>       → sex filter: male, female
                       species:<value>   → species filter: humans, animals
                       lang:<value>      → language filter: english, chinese, etc.
                       clinical:<value>  → clinical query filter (PubMed EBM).
                                           Values: therapy, therapy_narrow, diagnosis,
                                           diagnosis_narrow, prognosis, prognosis_narrow,
                                           etiology, etiology_narrow,
                                           clinical_prediction, clinical_prediction_narrow
                     Example: "year:2020-2025, age:aged, sex:female, clinical:therapy"
            options: Comma-separated flags to toggle behaviors.
                     Supported flags:
                       preprints      → also search arXiv, medRxiv, bioRxiv
                       all_types      → include non-peer-reviewed articles
                       no_oa          → skip Unpaywall OA link enrichment
                       no_analysis    → hide query analysis section in output
                       no_scores      → hide similarity/relevance scores
                       no_relax       → disable auto-relaxation on 0 results
                       shallow        → disable deep search (faster, keyword-only)
                     Example: "preprints, shallow" or "no_analysis, no_scores"
            pipeline: JSON string defining a multi-step search pipeline.
                     When provided, other parameters (except output_format) are
                     ignored and the pipeline DAG is executed instead.

                     Accepts **YAML** (recommended, human-friendly) or **JSON** format.

                     **Template mode — YAML** (shortcut for common workflows):
                       template: pico
                       params:
                         P: ICU patients
                         I: remimazolam
                         C: propofol
                         O: sedation

                     Other templates:
                       template: comprehensive
                       params:
                         query: CRISPR gene therapy

                       template: exploration
                       params:
                         pmid: "12345678"

                       template: gene_drug
                       params:
                         term: BRCA1

                     **Custom pipeline — YAML** (full DAG control, max 20 steps):
                       name: My Custom Search
                       steps:
                         - id: s1
                           action: search
                           params:
                             query: remimazolam ICU
                             sources: pubmed,europe_pmc
                             limit: 50
                         - id: s2
                           action: search
                           params:
                             query: propofol ICU
                             sources: pubmed
                             limit: 50
                         - id: merged
                           action: merge
                           inputs: [s1, s2]
                           params:
                             method: rrf
                         - id: enriched
                           action: metrics
                           inputs: [merged]
                       output:
                         format: markdown
                         limit: 20
                         ranking: impact

                     **JSON also supported** (for programmatic use):
                       {"template": "pico", "params": {"P": "ICU patients", "I": "remimazolam"}}

                     Available actions:
                       search      — literature search (params: query, sources, limit, min_year, max_year)
                       pico        — PICO elements (params: P, I, C, O)
                       expand      — MeSH/synonym expansion (params: topic)
                       details     — fetch article details (params: pmids)
                       related     — find related articles (params: pmid, limit)
                       citing      — find citing articles (params: pmid, limit)
                       references  — get article references (params: pmid, limit)
                       metrics     — enrich with iCite citation metrics (inputs only)
                       merge       — combine results (params: method=union|intersection|rrf)
                       filter      — post-filter (params: min_year, max_year, article_types, min_citations, has_abstract)

        Returns:
            Formatted search results with:
            - Query analysis (complexity, intent, PICO)
            - ICD code expansions (if detected)
            - Search statistics (sources, dedup count)
            - Ranked articles with metadata
            - Open access links where available
            - Preprints (if options includes "preprints")
            - Relaxation info (if auto_relax triggered)
            - Pipeline step summary (if pipeline mode)
        """
        logger.info(f"Unified search: query='{query}', limit={limit}, ranking='{ranking}'")

        # --- Helper for progress reporting ---
        async def _progress(progress: float, total: float, message: str) -> None:
            """Report progress to MCP client if context is available."""
            if ctx is not None:
                with contextlib.suppress(Exception):
                    await ctx.report_progress(progress, total, message)

        try:
            # ============================================================
            # Pipeline Mode — execute structured DAG when pipeline is set
            # ============================================================
            if pipeline:
                return await _execute_pipeline_mode(pipeline, output_format, searcher)

            try:
                request = normalize_unified_search_request(
                    query=query,
                    limit=limit,
                    sources=sources,
                    ranking=ranking,
                    output_format=output_format,
                    filters=filters,
                    options=options,
                    pipeline=pipeline,
                )
            except ValueError:
                return ResponseFormatter.error(
                    "Empty query",
                    suggestion="Provide a search query",
                    example='unified_search(query="machine learning in anesthesia")',
                    tool_name="unified_search",
                )

            try:
                plan = await build_unified_search_plan(
                    request,
                    progress=_progress,
                    analyzer_factory=QueryAnalyzer,
                    enhancer_factory=get_semantic_enhancer,
                    source_registry_factory=get_source_registry,
                )
            except SourceSelectionError as selection_error:
                available_sources = get_source_registry().list_unified_sources()
                return ResponseFormatter.error(
                    str(selection_error),
                    suggestion=(
                        f"Available sources: {', '.join(selection_error.available_sources)}"
                        if selection_error.available_sources
                        else f"Available sources: {', '.join(available_sources)}"
                    ),
                    example='unified_search(query="...", sources="auto,-semantic_scholar")',
                    tool_name="unified_search",
                )
            except ValueError as exc:
                return ResponseFormatter.error(
                    str(exc),
                    suggestion="Unset PUBMED_SEARCH_DISABLED_SOURCES or specify an enabled source",
                    example='unified_search(query="...", sources="pubmed")',
                    tool_name="unified_search",
                )

            execution = await execute_unified_search(
                plan,
                searcher,
                progress=_progress,
                ctx=ctx,
                search_functions={
                    "pubmed": lambda search_query, search_limit, min_year, max_year, advanced_filters: _search_pubmed(
                        searcher,
                        search_query,
                        search_limit,
                        min_year,
                        max_year,
                        **advanced_filters,
                    ),
                    "openalex": lambda search_query,
                    search_limit,
                    min_year,
                    max_year,
                    _advanced_filters: _search_openalex(
                        search_query,
                        search_limit,
                        min_year,
                        max_year,
                    ),
                    "europe_pmc": lambda search_query,
                    search_limit,
                    min_year,
                    max_year,
                    _advanced_filters: _search_europe_pmc(
                        search_query,
                        search_limit,
                        min_year,
                        max_year,
                    ),
                    "semantic_scholar": lambda search_query,
                    search_limit,
                    min_year,
                    max_year,
                    _advanced_filters: _search_semantic_scholar(
                        search_query,
                        search_limit,
                        min_year,
                        max_year,
                    ),
                    "core": lambda search_query, search_limit, min_year, max_year, _advanced_filters: _search_core(
                        search_query,
                        search_limit,
                        min_year,
                        max_year,
                    ),
                    "scopus": lambda search_query, search_limit, min_year, max_year, _advanced_filters: _search_scopus(
                        search_query,
                        search_limit,
                        min_year,
                        max_year,
                    ),
                    "web_of_science": lambda search_query,
                    search_limit,
                    min_year,
                    max_year,
                    _advanced_filters: _search_web_of_science(
                        search_query,
                        search_limit,
                        min_year,
                        max_year,
                    ),
                },
                timeline_builder_cls=TimelineBuilder,
                research_tree_builder=build_research_tree,
            )

            # === Step 9: Format Output ===
            await _progress(9, 10, "Formatting output...")
            if is_structured_output_format(request.output_format):
                return _format_as_json(
                    execution.ranked,
                    plan.analysis,
                    execution.stats,
                    execution.relaxation_result,
                    execution.deep_search_metrics,
                    source_api_counts=execution.source_api_counts or None,
                    source_disagreement=execution.source_disagreement,
                    reproducibility_score=execution.reproducibility_score,
                    research_context=execution.research_context_data,
                    counts_first=request.counts_first,
                    output_format=request.output_format,
                )

            return await _format_unified_results(
                execution.ranked,
                plan.analysis,
                execution.stats,
                request.show_analysis,
                execution.pubmed_total_count,
                plan.icd_matches,
                execution.preprint_results if request.include_preprints else None,
                include_trials=True,
                original_query=plan.analysis.original_query,
                enhanced_entities=plan.matched_entity_names or None,
                relaxation_result=execution.relaxation_result,
                deep_search_metrics=execution.deep_search_metrics,
                prefetched_trials=execution.prefetched_trials,
                source_api_counts=execution.source_api_counts or None,
                source_disagreement=execution.source_disagreement,
                reproducibility_score=execution.reproducibility_score,
                research_context_preview=execution.research_context_preview,
                counts_first=request.counts_first,
            )

        except Exception as e:
            logger.exception("Unified search failed: %s", e)
            return f"Error: Unified search failed - {e!s}"

    @mcp.tool()
    async def analyze_search_query(query: str) -> str:
        """
        Analyze a search query without executing the search.

        Useful for understanding how unified_search will process your query
        before actually running it.

        Args:
            query: The search query to analyze

        Returns:
            Analysis including:
            - Complexity level (SIMPLE/MODERATE/COMPLEX/AMBIGUOUS)
            - Intent (LOOKUP/EXPLORATION/COMPARISON/SYSTEMATIC)
            - PICO elements (if detected)
            - Recommended sources
            - Recommended strategies
        """
        # Normalize input
        query = InputNormalizer.normalize_query(query)
        if not query:
            return ResponseFormatter.error(
                "Empty query",
                suggestion="Provide a search query to analyze",
                example='analyze_search_query(query="remimazolam vs propofol")',
                tool_name="analyze_search_query",
            )

        try:
            analyzer = QueryAnalyzer()
            analysis = analyzer.analyze(query)

            # Get dispatch strategy
            sources = DispatchStrategy.get_sources(analysis)
            config = DispatchStrategy.get_ranking_config(analysis)
            enrich_oa = DispatchStrategy.should_enrich_with_unpaywall(analysis)

            output = [
                "## 🔬 Query Analysis\n",
                f"**Original Query**: {analysis.original_query}",
                f"**Normalized**: {analysis.normalized_query}",
                "",
                "### Classification",
                f"- **Complexity**: {analysis.complexity.value}",
                f"- **Intent**: {analysis.intent.value}",
                f"- **Confidence**: {analysis.confidence:.0%}",
            ]

            if analysis.clinical_category:
                output.append(f"- **Clinical Category**: {analysis.clinical_category}")

            if analysis.pico:
                output.append("\n### PICO Elements")
                for key, value in analysis.pico.to_dict().items():
                    if value:
                        output.append(f"- **{key}**: {value}")

            if analysis.identifiers:
                output.append("\n### Extracted Identifiers")
                for ident in analysis.identifiers:
                    output.append(f"- {ident.type.upper()}: {ident.value}")

            if analysis.keywords:
                output.append(f"\n### Keywords: {', '.join(analysis.keywords)}")

            if analysis.year_from or analysis.year_to:
                year_str = []
                if analysis.year_from:
                    year_str.append(f"from {analysis.year_from}")
                if analysis.year_to:
                    year_str.append(f"to {analysis.year_to}")
                output.append(f"\n### Year Constraint: {' '.join(year_str)}")

            output.extend(
                [
                    "\n### Dispatch Strategy",
                    f"- **Sources**: {' → '.join(sources)}",
                    f"- **Ranking**: {config.normalized_weights()}",
                    f"- **OA Enrichment**: {'Yes' if enrich_oa else 'No'}",
                ]
            )

            return "\n".join(output)

        except Exception as e:
            logger.exception(f"Query analysis failed: {e}")
            return f"Error: Query analysis failed - {e!s}"
