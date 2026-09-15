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

This module only registers the MCP transport adapter.  Provider-independent
request, planning, execution, and policy code lives in ``application/unified``;
``infrastructure/sources/unified_broker.py`` and ``unified_enrichment.py``
implement its ports.  Presentation retains only composition, progress,
formatting, pipeline handoff, journal, and artifact concerns.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Literal

from mcp.server.mcpserver import Context  # noqa: TC002 - MCPServer needs runtime access for type annotation injection
from pydantic import Field

from pubmed_search.application.search.query_analyzer import (
    QueryAnalyzer,
)
from pubmed_search.application.unified.helpers import DispatchStrategy
from pubmed_search.application.unified.request import (
    MAX_UNIFIED_FILTERS_CHARS,
    MAX_UNIFIED_OPTIONS_CHARS,
    MAX_UNIFIED_PIPELINE_CHARS,
    MAX_UNIFIED_QUERY_CHARS,
    MAX_UNIFIED_SOURCES_CHARS,
    MAX_UNIFIED_STOP_AT_CHARS,
)
from pubmed_search.infrastructure.pubtator.semantic_adapter import get_semantic_enhancer
from pubmed_search.infrastructure.sources.registry import get_source_registry

from .tool_input import InputNormalizer
from .tool_response import ResponseFormatter
from .unified_runner import (
    run_unified_search,
)

if TYPE_CHECKING:
    from mcp.server import MCPServer

    from pubmed_search.infrastructure.ncbi import LiteratureSearcher

    from .pipeline_tools import PipelineToolRuntime

logger = logging.getLogger(__name__)

__all__ = ["register_unified_search_tools"]


# ============================================================================
# MCP tool registration
# ============================================================================


def register_unified_search_tools(
    mcp: MCPServer,
    searcher: LiteratureSearcher,
    *,
    pipeline_runtime: PipelineToolRuntime,
):
    """Register unified search tools bound to this server's pipeline runtime."""

    @mcp.tool()
    async def unified_search(
        query: Annotated[str, Field(max_length=MAX_UNIFIED_QUERY_CHARS)] = "",
        limit: Annotated[int, Field(ge=1, le=100)] = 10,
        sources: Annotated[str, Field(max_length=MAX_UNIFIED_SOURCES_CHARS)] | None = None,
        ranking: Literal["balanced", "impact", "recency", "quality"] = "balanced",
        output_format: Literal["markdown", "json", "toon"] = "markdown",
        filters: Annotated[str, Field(max_length=MAX_UNIFIED_FILTERS_CHARS)] | None = None,
        options: Annotated[str, Field(max_length=MAX_UNIFIED_OPTIONS_CHARS)] | None = None,
        pipeline: Annotated[str, Field(max_length=MAX_UNIFIED_PIPELINE_CHARS)] | None = None,
        dry_run: bool = False,
        stop_at: Annotated[str, Field(max_length=MAX_UNIFIED_STOP_AT_CHARS)] = "",
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
                          filters="year:2020-2025,age_group:aged,clinical_query:therapy")

        Include preprints + shallow search:
            unified_search("COVID-19 vaccine", options="preprints,shallow")

        Provider-native semantic retrieval (OpenAlex capability):
            unified_search("mechanisms of treatment resistance",
                          sources="openalex", options="native_semantic")

        Reproducible systematic retrieval (bulk/cursor where supported):
            unified_search("melanoma AND immunotherapy",
                          sources="openalex,semantic_scholar",
                          options="systematic")

        Full control:
            unified_search("propofol vs remimazolam",
                          sources="pubmed,semantic_scholar,europe_pmc",
                          ranking="impact",
                          filters="year:2020-,sex:female,species:humans",
                          options="preprints,no_relax")

        ICD Code Auto-Detection:
            unified_search("E11 complications")
            → Auto-expands E11 to "Diabetes Mellitus, Type 2"[MeSH]

        Args:
            query: Search query (natural language, ICD codes, or structured).
                   Required unless pipeline is provided.
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
                     Source keys are exact and canonical; legacy hyphenated,
                     spaced, abbreviated, or case-folded aliases are rejected.
                     Examples: "pubmed,openalex", "auto,-semantic_scholar",
                     or "all,-crossref"
                     Global disable env: `PUBMED_SEARCH_DISABLED_SOURCES`
                     Example: `PUBMED_SEARCH_DISABLED_SOURCES=semantic_scholar,core`
            ranking: Ranking strategy:
                - "balanced": Default, considers all factors
                - "impact": Prioritize high-citation papers
                - "recency": Prioritize recent publications
                - "quality": Prioritize publication-type heuristics (RCTs, meta-analyses); not a quality assessment
            output_format: "markdown" (human-readable), "json", or "toon" (programmatic)
            filters: Comma-separated key:value pairs for filtering results.
                     Supported keys:
                       year:2020-2025    → publication year range
                       year:2020-        → from 2020 onwards
                       year:-2025        → up to 2025
                       year:2024         → from 2024 onwards
                       age_group:<value> → age group filter (PubMed).
                                           Values: newborn, infant, preschool, child,
                                           adolescent, young_adult, adult, middle_aged,
                                           aged, aged_80
                       sex:<value>       → sex filter: male, female
                       species:<value>   → species filter: humans, animals
                       language:<value>  → language filter: english, chinese, etc.
                       clinical_query:<value>
                                        → clinical query filter (PubMed EBM).
                                           Values: therapy, therapy_narrow, diagnosis,
                                           diagnosis_narrow, prognosis, prognosis_narrow,
                                           etiology, etiology_narrow,
                                           clinical_prediction, clinical_prediction_narrow
                     Tokens, keys, and values use exact canonical spelling with
                     no surrounding whitespace.
                     Example: "year:2020-2025,age_group:aged,sex:female,clinical_query:therapy"
            options: Comma-separated flags to toggle behaviors.
                     Supported flags:
                       preprints      → also search arXiv, medRxiv, bioRxiv
                       include_detected_preprints
                                      → retain records identified by the preprint
                                        heuristic in otherwise selected sources;
                                        this does not establish peer-review status
                       clinical_trials → add a bounded ClinicalTrials.gov adjunct
                                        section to Markdown output (explicit opt-in)
                       no_oa          → skip Unpaywall OA link enrichment
                       no_analysis    → hide query analysis section in output
                       no_scores      → hide ranking scores and rank percentiles
                       compact        → compact structured JSON/TOON output
                       no_next        → hide next-tool suggestions in structured output
                       no_provenance  → hide section provenance in structured output
                       no_relax       → disable auto-relaxation on 0 results
                       native_semantic → use provider-native semantic retrieval;
                                         currently OpenAlex, max 50 results
                       systematic     → use deterministic bulk/cursor retrieval where
                                         supported (for example S2 and OpenAlex)
                       shallow        → disable deep search (faster, keyword-only)
                     `native_semantic` and `systematic` are mutually exclusive
                     Option tokens use exact canonical spelling with no
                     surrounding whitespace.
                     and automatically disable multi-strategy query expansion.
                     Tokens use exact canonical spelling without surrounding
                     whitespace or duplicates.
                     Example: "preprints,shallow" or "no_analysis,no_scores"
            pipeline: YAML/JSON string defining a multi-step search pipeline.
                     When provided, other parameters (except output_format) are
                     ignored and the pipeline DAG is executed instead.

                     Accepts **YAML** (recommended, human-friendly) or **JSON** format.

                     **Template mode — YAML** (shortcut for common workflows):
                       template: pico
                       template_params:
                         P: ICU patients
                         I: remimazolam
                         C: propofol
                         O: sedation

                     Other templates:
                       template: comprehensive
                       template_params:
                         query: CRISPR gene therapy

                       template: exploration
                       template_params:
                         pmid: "12345678"

                       template: gene_drug
                       template_params:
                         term: BRCA1

                     **Custom pipeline — YAML** (full DAG control, max 20 steps):
                       name: My Custom Search
                       steps:
                         - id: s1
                           action: search
                           params:
                             query: remimazolam ICU
                             sources: [pubmed, europe_pmc]
                             limit: 50
                         - id: s2
                           action: search
                           params:
                             query: propofol ICU
                             sources: [pubmed]
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

                     Shared params:
                       globals: default params inherited only by actions that
                                declare the same canonical parameter key
                       variables: typed values available as ${name} placeholders;
                                  embedded replacements must be strings

                     Debugging controls:
                       dry_run: validate/preview the pipeline without searches
                       stop_at: execute through one step id, e.g. "merged"

                     **JSON also supported** (for programmatic use):
                       {"template": "pico", "template_params": {"P": "ICU patients", "I": "remimazolam"}}

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
        return await run_unified_search(
            searcher=searcher,
            query=query,
            limit=limit,
            sources=sources,
            ranking=ranking,
            output_format=output_format,
            filters=filters,
            options=options,
            pipeline=pipeline,
            dry_run=dry_run,
            stop_at=stop_at,
            ctx=ctx,
            analyzer_factory=QueryAnalyzer,
            enhancer_factory=get_semantic_enhancer,
            source_registry_factory=get_source_registry,
            pipeline_runtime=pipeline_runtime,
        )

    @mcp.tool()
    async def analyze_search_query(
        query: Annotated[str, Field(min_length=1, max_length=MAX_UNIFIED_QUERY_CHARS)],
    ) -> str:
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
            sources = DispatchStrategy.get_sources(analysis, registry=get_source_registry())
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

        except Exception as exc:
            logger.warning("Query analysis failed (%s)", type(exc).__name__)
            return ResponseFormatter.error(
                "Query analysis failed",
                suggestion="Check the bounded query and retry",
                tool_name="analyze_search_query",
            )
