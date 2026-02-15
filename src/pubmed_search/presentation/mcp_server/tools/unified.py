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

import asyncio
import logging
from typing import TYPE_CHECKING, Literal, Union

from pubmed_search.application.search.query_analyzer import (
    QueryAnalyzer,
)
from pubmed_search.application.search.result_aggregator import (
    RankingConfig,
    ResultAggregator,
)
from pubmed_search.application.search.semantic_enhancer import (
    EnhancedQuery,
    SearchPlan,
    get_semantic_enhancer,
)
from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.infrastructure.sources.preprints import PreprintSearcher

from ._common import InputNormalizer, ResponseFormatter, _record_search_only

# ---------------------------------------------------------------------------
# Extracted sub-modules
# ---------------------------------------------------------------------------
from .unified_enrichment import (
    _enrich_with_api_similarity,
    _enrich_with_crossref,
    _enrich_with_journal_metrics,
    _enrich_with_similarity_scores,
    _enrich_with_unpaywall,
    _extract_openalex_source_id,
    _is_preprint,
)
from .unified_formatting import _format_as_json, _format_unified_results
from .unified_helpers import (
    DispatchStrategy,
    ICD10_PATTERN,
    ICD9_PATTERN,
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
from .unified_source_search import (
    _auto_relax_search,
    _execute_deep_search,
    _search_core,
    _search_europe_pmc,
    _search_openalex,
    _search_pubmed,
    _search_semantic_scholar,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

logger = logging.getLogger(__name__)

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


def register_unified_search_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """Register unified search MCP tools."""

    @mcp.tool()
    async def unified_search(
        query: str,
        limit: Union[int, str] = 10,
        sources: Union[str, None] = None,
        ranking: Literal["balanced", "impact", "recency", "quality"] = "balanced",
        output_format: Literal["markdown", "json"] = "markdown",
        filters: Union[str, None] = None,
        options: Union[str, None] = None,
        pipeline: Union[str, None] = None,
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
                     "europe_pmc", "crossref".
                     Default: auto-select based on query complexity.
                     Examples: "pubmed,openalex" or "europe_pmc"
            ranking: Ranking strategy:
                - "balanced": Default, considers all factors
                - "impact": Prioritize high-citation papers
                - "recency": Prioritize recent publications
                - "quality": Prioritize high-evidence studies (RCTs, meta-analyses)
            output_format: "markdown" (human-readable) or "json" (programmatic)
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

        try:
            # ============================================================
            # Pipeline Mode — execute structured DAG when pipeline is set
            # ============================================================
            if pipeline:
                return await _execute_pipeline_mode(pipeline, output_format, searcher)

            # === Step 0: Normalize Inputs ===
            query = InputNormalizer.normalize_query(query)
            if not query:
                return ResponseFormatter.error(
                    "Empty query",
                    suggestion="Provide a search query",
                    example='unified_search(query="machine learning in anesthesia")',
                    tool_name="unified_search",
                )

            limit = InputNormalizer.normalize_limit(limit, default=10, max_val=100)

            # === Step 0.1: Parse composite parameters ===
            parsed_filters = _parse_filters(filters)
            parsed_options = _parse_options(options)

            # Extract filter values (with defaults)
            min_year: int | None = parsed_filters.get("min_year")
            max_year: int | None = parsed_filters.get("max_year")
            age_group: str | None = parsed_filters.get("age_group")
            sex: str | None = parsed_filters.get("sex")
            species: str | None = parsed_filters.get("species")
            language: str | None = parsed_filters.get("language")
            clinical_query: str | None = parsed_filters.get("clinical_query")

            # Extract option flags (with defaults)
            include_oa_links: bool = parsed_options.get("include_oa_links", True)
            show_analysis: bool = parsed_options.get("show_analysis", True)
            include_similarity_scores: bool = parsed_options.get("include_similarity_scores", True)
            include_preprints: bool = parsed_options.get("include_preprints", False)
            peer_reviewed_only: bool = parsed_options.get("peer_reviewed_only", True)
            auto_relax: bool = parsed_options.get("auto_relax", True)
            deep_search: bool = parsed_options.get("deep_search", True)

            # === Step 0.5: ICD Code Detection and Expansion ===
            icd_matches: list[dict] = []
            expanded_query, icd_matches = detect_and_expand_icd_codes(query)
            if icd_matches:
                query = expanded_query
                logger.info(f"ICD codes detected: {[i['code'] for i in icd_matches]}")

            # === Step 1: Analyze Query ===
            analyzer = QueryAnalyzer()
            analysis = analyzer.analyze(query)

            logger.info(f"Query analysis: complexity={analysis.complexity.value}, intent={analysis.intent.value}")

            # === Step 1.5: Semantic Enhancement (Phase 3) ===
            # Skip PubTator3 for SIMPLE/LOOKUP queries (saves 1-3s latency)
            enhanced_query: EnhancedQuery | None = None
            matched_entity_names: list[str] = []

            skip_enhancement = analysis.complexity.value == "simple" or analysis.intent.value == "lookup"

            if skip_enhancement:
                logger.info("Skipping semantic enhancement for simple/lookup query")
            else:
                try:
                    enhancer = get_semantic_enhancer()
                    enhanced_query = await asyncio.wait_for(enhancer.enhance(query), timeout=3.0)

                    if enhanced_query and enhanced_query.entities:
                        # Extract entity names for ranking
                        matched_entity_names = [e.resolved_name for e in enhanced_query.entities]
                        logger.info(
                            f"Semantic enhancement: {len(enhanced_query.entities)} entities, "
                            f"{len(enhanced_query.strategies)} strategies"
                        )
                except asyncio.TimeoutError:
                    logger.warning("Semantic enhancement timeout - continuing without")
                except Exception as e:
                    logger.debug(f"Semantic enhancement skipped: {e}")

            # === Step 2: Determine Sources ===
            valid_sources = {"pubmed", "openalex", "semantic_scholar", "europe_pmc", "crossref", "core"}
            user_sources: list[str] | None = None

            if sources:
                # User explicitly specified sources — parse and validate
                parsed = [s.strip().lower() for s in sources.split(",") if s.strip()]
                invalid = [s for s in parsed if s not in valid_sources]
                if invalid:
                    return ResponseFormatter.error(
                        f"Invalid source(s): {', '.join(invalid)}",
                        suggestion=f"Available sources: {', '.join(sorted(valid_sources))}",
                        example='unified_search(query="...", sources="pubmed,openalex")',
                        tool_name="unified_search",
                    )
                user_sources = parsed
                logger.info(f"User-specified sources: {user_sources}")

            dispatch_sources = user_sources or DispatchStrategy.get_sources(analysis)
            logger.info(f"Selected sources: {dispatch_sources}")

            # === Step 3: Get Ranking Config ===
            if ranking == "impact":
                config = RankingConfig.impact_focused()
            elif ranking == "recency":
                config = RankingConfig.recency_focused()
            elif ranking == "quality":
                config = RankingConfig.quality_focused()
            else:
                config = DispatchStrategy.get_ranking_config(analysis)

            # Phase 3: Pass entity information to ranking config
            if matched_entity_names:
                config.matched_entities = matched_entity_names

            # === Step 4: Search Each Source (Parallel) ===
            all_results: list[list[UnifiedArticle]] = []
            pubmed_total_count: int | None = None
            source_api_counts: dict[str, tuple[int, int | None]] = {}
            preprint_results: dict = {}
            deep_search_metrics: SearchDepthMetrics | None = None

            # === Pre-fetch: Start clinical trials search in background ===
            # This runs in parallel with the main search to avoid blocking formatting
            clinical_trials_task: asyncio.Task | None = None
            if output_format != "json":
                try:
                    from pubmed_search.infrastructure.sources.clinical_trials import (
                        search_related_trials,
                    )

                    trial_query = " ".join(query.split()[:5])
                    clinical_trials_task = asyncio.create_task(search_related_trials(trial_query, limit=3))
                except Exception:
                    logger.debug("Clinical trials module not available, skipping")
            advanced_filters = {
                k: v
                for k, v in {
                    "age_group": age_group,
                    "sex": sex,
                    "species": species,
                    "language": language,
                    "clinical_query": clinical_query,
                }.items()
                if v is not None
            }

            effective_min_year = min_year or analysis.year_from
            effective_max_year = max_year or analysis.year_to

            # *** DEEP SEARCH: Use SemanticEnhancer strategies ***
            if deep_search and enhanced_query and enhanced_query.strategies and len(enhanced_query.strategies) > 0:
                # Filter strategies to user-specified sources if provided
                if user_sources:
                    original_count = len(enhanced_query.strategies)
                    enhanced_query.strategies = [s for s in enhanced_query.strategies if s.source in user_sources]
                    # If all strategies were filtered out, add back at least one per source
                    if not enhanced_query.strategies:
                        for src in user_sources:
                            if src in ("pubmed", "europe_pmc", "openalex"):
                                enhanced_query.strategies.append(
                                    SearchPlan(
                                        name=f"user_specified_{src}",
                                        query=enhanced_query.original_query,
                                        source=src,
                                        priority=1,
                                        expected_precision=0.5,
                                        expected_recall=0.5,
                                    )
                                )
                    filtered_count = original_count - len(enhanced_query.strategies)
                    if filtered_count > 0:
                        logger.info(f"Filtered {filtered_count} strategies to match user sources: {user_sources}")

                logger.info(f"Executing DEEP SEARCH with {len(enhanced_query.strategies)} strategies")
                (
                    all_results,
                    deep_search_metrics,
                    pubmed_total_count,
                    source_api_counts,
                ) = await _execute_deep_search(
                    searcher,
                    enhanced_query,
                    limit,
                    effective_min_year,
                    effective_max_year,
                    advanced_filters,
                )
                logger.info(
                    f"Deep search: {deep_search_metrics.strategies_executed} strategies, "
                    f"{deep_search_metrics.strategies_with_results} with results, "
                    f"depth score: {deep_search_metrics.depth_score:.0f}"
                )

            else:
                # *** FALLBACK: Traditional source-based search ***
                logger.info("Using traditional source-based search (no deep search)")

                # Async parallel search
                async def search_source(
                    source: str,
                ) -> tuple[str, list[UnifiedArticle], int | None]:
                    """Search a single source and return (source_name, articles, total_count)."""
                    if source == "pubmed":
                        articles, total_count = await _search_pubmed(
                            searcher,
                            query,
                            limit,
                            effective_min_year,
                            effective_max_year,
                            **advanced_filters,
                        )
                        return ("pubmed", articles, total_count)

                    if source == "openalex":
                        articles, total_count = await _search_openalex(
                            query,
                            limit,
                            effective_min_year,
                            effective_max_year,
                        )
                        return ("openalex", articles, total_count)

                    if source == "semantic_scholar":
                        articles, total_count = await _search_semantic_scholar(
                            query,
                            limit,
                            effective_min_year,
                            effective_max_year,
                        )
                        return ("semantic_scholar", articles, total_count)

                    if source == "core":
                        articles, total_count = await _search_core(
                            query,
                            limit,
                            effective_min_year,
                            effective_max_year,
                        )
                        return ("core", articles, total_count)

                    if source == "crossref":
                        # CrossRef is used for enrichment, not primary search
                        return ("crossref", [], None)

                    return (source, [], None)

                # Filter out crossref from parallel search (it's enrichment only)
                search_sources = [s for s in dispatch_sources if s != "crossref"]

                # Execute searches in parallel with asyncio.gather
                search_results = await asyncio.gather(
                    *[search_source(s) for s in search_sources],
                    return_exceptions=True,
                )

                for result in search_results:
                    if isinstance(result, Exception):
                        logger.error(f"Search failed: {result}")
                        continue
                    # Type narrowing: result is now tuple, not Exception
                    name, articles, total_count = result  # type: ignore[misc]
                    if articles:
                        all_results.append(articles)
                    # Track per-source API counts: (returned, total_available)
                    source_api_counts[name] = (len(articles), total_count)
                    if name == "pubmed" and total_count is not None:
                        pubmed_total_count = total_count
                    logger.info(
                        "%s: %d results%s", name, len(articles), f" (total: {total_count})" if total_count else ""
                    )

            # === Step 4.5: Search Preprints (if enabled) ===
            if include_preprints:
                try:
                    preprint_searcher = PreprintSearcher()
                    # Use original query for preprints (without MeSH expansion)
                    preprint_query = query.split("[MeSH]")[0].replace('"', "").strip() if "[MeSH]" in query else query
                    preprint_results = await preprint_searcher.search_medical_preprints(
                        query=preprint_query,
                        limit=min(limit, 10),
                    )
                    logger.info(f"Preprints: {preprint_results.get('total', 0)} results")
                except Exception as e:
                    logger.warning(f"Preprint search failed: {e}")
                    preprint_results = {}

            # === Step 5: Aggregate and Deduplicate ===
            aggregator = ResultAggregator(config)
            articles, stats = aggregator.aggregate(all_results)

            logger.info(f"Aggregation: {stats.unique_articles} unique from {stats.total_input} total")

            # === Step 5.5: Auto-Relaxation (when 0 results) ===
            relaxation_result: RelaxationResult | None = None

            if (
                auto_relax and stats.unique_articles == 0 and not analysis.identifiers  # Don't relax PMID/DOI lookups
            ):
                logger.info("0 results — attempting auto-relaxation")
                relaxation_result = await _auto_relax_search(
                    searcher,
                    query,
                    limit,
                    min_year or analysis.year_from,
                    max_year or analysis.year_to,
                    advanced_filters,
                )

                if relaxation_result and relaxation_result.successful_step:
                    step = relaxation_result.successful_step
                    # Re-aggregate with relaxed results
                    relaxed_articles, _ = await _search_pubmed(
                        searcher,
                        step.query,
                        limit,
                        step.min_year,
                        step.max_year,
                        **step.advanced_filters,
                    )
                    all_results = [relaxed_articles]
                    articles, stats = aggregator.aggregate(all_results)
                    # Update pubmed_total_count
                    pubmed_total_count = relaxation_result.total_results
                    logger.info(
                        f"Auto-relaxation: {stats.unique_articles} results at level {step.level} ({step.action})"
                    )

            # === Step 6: Enrich with CrossRef (if in sources) ===
            if "crossref" in dispatch_sources:
                await _enrich_with_crossref(articles)

            # === Step 6.25: Enrich with Journal Metrics (OpenAlex Sources API) ===
            if "openalex" in dispatch_sources:
                await _enrich_with_journal_metrics(articles)

            # === Step 6.5: Filter non-peer-reviewed articles ===
            if peer_reviewed_only and articles:
                from pubmed_search.domain.entities.article import ArticleType

                pre_filter_count = len(articles)
                articles = [a for a in articles if not _is_preprint(a, ArticleType)]
                filtered_count = pre_filter_count - len(articles)
                if filtered_count > 0:
                    logger.info(f"Peer-review filter: removed {filtered_count} non-peer-reviewed articles")

            # === Step 7: Enrich with Unpaywall OA Links ===
            if include_oa_links and DispatchStrategy.should_enrich_with_unpaywall(analysis):
                await _enrich_with_unpaywall(articles)

            # === Step 8: Rank Results ===
            ranked = aggregator.rank(articles, config, query)

            # Apply limit
            if limit and len(ranked) > limit:
                ranked = ranked[:limit]

            # === Step 8.5: Enrich with Similarity Scores ===
            if include_similarity_scores:
                _enrich_with_similarity_scores(ranked, query)

            # === Step 8.6: Source Disagreement Analysis ===
            source_disagreement = None
            if len(source_api_counts) > 1:
                from pubmed_search.application.search.ranking_algorithms import (
                    analyze_source_disagreement,
                )

                source_disagreement = analyze_source_disagreement(ranked)

            # === Step 8.7: Reproducibility Score ===
            from pubmed_search.application.search.reproducibility import (
                calculate_reproducibility,
            )

            sources_queried_list = list(source_api_counts.keys()) if source_api_counts else [s for s in dispatch_sources if s != "crossref"]
            sources_responded_list = [s for s in sources_queried_list if source_api_counts.get(s, (0, None))[0] > 0] if source_api_counts else sources_queried_list
            reproducibility = calculate_reproducibility(
                query=query,
                sources_queried=sources_queried_list,
                sources_responded=sources_responded_list,
                articles=ranked,
                has_source_counts=bool(source_api_counts),
            )

            # === Step 8.8: Record to Session ===
            _record_search_only(ranked, analysis.original_query)

            # === Step 9: Format Output ===
            if output_format == "json":
                if clinical_trials_task:
                    clinical_trials_task.cancel()
                return _format_as_json(
                    ranked, analysis, stats, relaxation_result, deep_search_metrics,
                    source_disagreement=source_disagreement,
                    reproducibility_score=reproducibility,
                )
            # Collect pre-fetched clinical trials
            prefetched_trials: list | None = None
            if clinical_trials_task:
                try:
                    prefetched_trials = await asyncio.wait_for(clinical_trials_task, timeout=5.0)
                except (asyncio.TimeoutError, Exception):
                    prefetched_trials = None

            return await _format_unified_results(
                ranked,
                analysis,
                stats,
                show_analysis,
                pubmed_total_count,
                icd_matches,
                preprint_results if include_preprints else None,
                include_trials=True,
                original_query=analysis.original_query,
                enhanced_entities=matched_entity_names if matched_entity_names else None,
                relaxation_result=relaxation_result,
                deep_search_metrics=deep_search_metrics,
                prefetched_trials=prefetched_trials,
                source_api_counts=source_api_counts if source_api_counts else None,
                source_disagreement=source_disagreement,
                reproducibility_score=reproducibility,
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
