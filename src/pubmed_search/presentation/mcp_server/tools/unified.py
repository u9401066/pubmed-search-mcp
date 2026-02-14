"""
Unified Search Tool - Single Entry Point for Multi-Source Academic Search

This is the MVP of the Unified Search Gateway (Phase 2.0).
Phase 3: Deep+Wide Search with PubTator3 Semantic Enhancement.

Design Philosophy:
    單一入口 + 後端自動分流（像 Google 一樣）
    每次搜尋都又深又廣！

    Old way (Agent must choose):
        search_literature() / search_europe_pmc() / search_core() / ...

    New way (Single entry point):
        unified_search(query) → Auto-dispatch to best sources

Architecture (Phase 3 Enhanced):
    User Query
         │
         ▼
    ┌──────────────────┐
    │  QueryAnalyzer   │  ← Determines complexity, detects PICO
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────────┐
    │  SemanticEnhancer    │  ← NEW: PubTator3 entity resolution
    └────────┬─────────────┘
             │
             ▼
    ┌──────────────────┐
    │ DispatchStrategy │  ← Selects sources based on query type
    └────────┬─────────┘
             │
    ┌────────┴────────┬──────────┐
    ▼                 ▼          ▼
  PubMed          CrossRef    OpenAlex  (parallel or sequential)
    │                 │          │
    └────────┬────────┴──────────┘
             │
             ▼
    ┌──────────────────┐
    │ ResultAggregator │  ← Dedup + 6-dimensional ranking
    └────────┬─────────┘
             │
             ▼
      UnifiedArticle[]

Features:
    - Automatic query analysis (complexity, intent, PICO)
    - PubTator3 entity resolution (Gene, Disease, Chemical, etc.)
    - Smart source selection based on query characteristics
    - Multi-source parallel search with deduplication
    - 6-dimensional ranking (relevance, quality, recency, impact, source_trust, entity_match)
    - Transparent operation with analysis metadata
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Literal, Union

from mcp.server.fastmcp import FastMCP

from pubmed_search.application.search.query_analyzer import (
    AnalyzedQuery,
    QueryAnalyzer,
    QueryComplexity,
    QueryIntent,
)
from pubmed_search.application.search.result_aggregator import (
    AggregationStats,
    RankingConfig,
    ResultAggregator,
)
from pubmed_search.application.search.semantic_enhancer import (
    EnhancedQuery,
    SearchPlan,
    get_semantic_enhancer,
)
from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.infrastructure.ncbi import LiteratureSearcher
from pubmed_search.infrastructure.sources import (
    get_crossref_client,
    get_openalex_client,
    get_unpaywall_client,
    search_alternate_source,
)
from pubmed_search.infrastructure.sources.openurl import (
    get_openurl_config,
    get_openurl_link,
)
from pubmed_search.infrastructure.sources.preprints import PreprintSearcher

from ._common import InputNormalizer, ResponseFormatter, _record_search_only
from .icd import lookup_icd_to_mesh

logger = logging.getLogger(__name__)


# ============================================================================
# ICD Code Detection and Conversion
# ============================================================================


# ICD-10 pattern: Letter + 2-3 digits + optional dot + more digits
ICD10_PATTERN = re.compile(r"\b([A-Z]\d{2}(?:\.\d{1,4})?)\b", re.IGNORECASE)
# ICD-9 pattern: 3-5 digits with optional dot
ICD9_PATTERN = re.compile(r"\b(\d{3}(?:\.\d{1,2})?)\b")


def detect_and_expand_icd_codes(query: str) -> tuple[str, list[dict]]:
    """
    Detect ICD codes in query and expand to MeSH terms.

    Args:
        query: Search query that may contain ICD codes

    Returns:
        Tuple of (expanded_query, icd_matches)
        - expanded_query: Query with ICD codes replaced/augmented by MeSH terms
        - icd_matches: List of detected ICD codes and their mappings
    """
    icd_matches: list[dict] = []

    # Detect ICD-10 codes
    for match in ICD10_PATTERN.finditer(query):
        code = match.group(1).upper()
        result = lookup_icd_to_mesh(code)
        if result:
            icd_matches.append(
                {
                    "code": code,
                    "type": "ICD-10",
                    "mesh": result["mesh"],
                    "description": result.get("description", ""),
                }
            )

    # Detect ICD-9 codes (3-digit numeric)
    for match in ICD9_PATTERN.finditer(query):
        code = match.group(1)
        # Only consider valid ICD-9 ranges (001-999)
        try:
            base = int(code.split(".")[0])
            if 1 <= base <= 999:
                result = lookup_icd_to_mesh(code)
                if result:
                    icd_matches.append(
                        {
                            "code": code,
                            "type": "ICD-9",
                            "mesh": result["mesh"],
                            "description": result.get("description", ""),
                        }
                    )
        except ValueError:
            pass

    if not icd_matches:
        return query, []

    # Build expanded query
    # Replace ICD codes with MeSH terms in the query
    expanded_query = query
    for icd in icd_matches:
        mesh_term = icd["mesh"]
        # Replace or augment the ICD code with MeSH
        expanded_query = re.sub(
            rf"\b{re.escape(icd['code'])}\b",
            f'("{mesh_term}"[MeSH] OR {icd["code"]})',
            expanded_query,
            flags=re.IGNORECASE,
        )

    logger.info(f"ICD codes detected: {[i['code'] for i in icd_matches]}")
    logger.info(f"Expanded query: {expanded_query}")

    return expanded_query, icd_matches


# ============================================================================
# Dispatch Strategy Matrix
# ============================================================================


class DispatchStrategy:
    """
    Determines which sources to query based on query analysis.

    Strategy Matrix:
    ┌─────────────────┬─────────────┬────────────────────────────────────┐
    │ Complexity      │ Intent      │ Sources                            │
    ├─────────────────┼─────────────┼────────────────────────────────────┤
    │ SIMPLE          │ LOOKUP      │ PubMed only (fast)                 │
    │ SIMPLE          │ EXPLORATION │ PubMed                             │
    │ MODERATE        │ *           │ PubMed + CrossRef enrichment       │
    │ COMPLEX         │ COMPARISON  │ PubMed + OpenAlex + S2             │
    │ COMPLEX         │ SYSTEMATIC  │ All sources (max coverage)         │
    │ AMBIGUOUS       │ *           │ PubMed + OpenAlex (broad)          │
    └─────────────────┴─────────────┴────────────────────────────────────┘
    """

    @staticmethod
    def get_sources(analysis: AnalyzedQuery) -> list[str]:
        """Get ordered list of sources to query."""
        complexity = analysis.complexity
        intent = analysis.intent

        # LOOKUP: Direct identifier search
        if intent == QueryIntent.LOOKUP:
            if analysis.identifiers:
                # Has identifiers - just PubMed
                return ["pubmed"]
            return ["pubmed", "crossref"]

        # SIMPLE: PubMed only for speed
        if complexity == QueryComplexity.SIMPLE:
            return ["pubmed"]

        # MODERATE: PubMed + CrossRef for DOI enrichment
        if complexity == QueryComplexity.MODERATE:
            return ["pubmed", "crossref"]

        # COMPLEX - depends on intent
        if complexity == QueryComplexity.COMPLEX:
            if intent == QueryIntent.COMPARISON:
                # Comparison needs diverse results
                return ["pubmed", "openalex", "semantic_scholar"]
            if intent == QueryIntent.SYSTEMATIC:
                # Systematic review needs maximum coverage
                return ["pubmed", "openalex", "semantic_scholar", "europe_pmc"]
            # Default complex
            return ["pubmed", "openalex", "crossref"]

        # AMBIGUOUS: Broad search
        if complexity == QueryComplexity.AMBIGUOUS:
            return ["pubmed", "openalex"]

        # Default fallback
        return ["pubmed"]

    @staticmethod
    def get_ranking_config(analysis: AnalyzedQuery) -> RankingConfig:
        """Get ranking configuration based on query analysis."""
        intent = analysis.intent

        # SYSTEMATIC: Quality focused (favor RCTs, meta-analyses)
        if intent == QueryIntent.SYSTEMATIC:
            return RankingConfig.quality_focused()

        # COMPARISON: Impact focused (favor high-cited comparative studies)
        if intent == QueryIntent.COMPARISON:
            return RankingConfig.impact_focused()

        # EXPLORATION with recent constraint: Recency focused
        if intent == QueryIntent.EXPLORATION and analysis.year_from:
            return RankingConfig.recency_focused()

        # Default: Balanced
        return RankingConfig.default()

    @staticmethod
    def should_enrich_with_unpaywall(analysis: AnalyzedQuery) -> bool:
        """Determine if results should be enriched with Unpaywall OA links."""
        # Always enrich for systematic reviews (need full text)
        if analysis.intent == QueryIntent.SYSTEMATIC:
            return True
        # Enrich for complex queries
        return analysis.complexity == QueryComplexity.COMPLEX


# ============================================================================
# Auto Search Relaxation
# ============================================================================

# Pattern matching PubMed field tags like [Title], [tiab], [MeSH Terms], etc.
_FIELD_TAG_PATTERN = re.compile(
    r"\s*\[(?:Title|tiab|Title/Abstract|MeSH Terms?|All Fields|pt|"
    r"Author|Journal|Affiliation|Publication Type|"
    r"MeSH Major Topic|MeSH Subheading|dp)\]",
    re.IGNORECASE,
)

# Publication type filters like "randomized controlled trial[pt]"
_PUB_TYPE_FILTER_PATTERN = re.compile(
    r"\s+AND\s+(?:\()?(?:randomized controlled trial|meta-analysis|"
    r"systematic review|clinical trial|review|case reports?)"
    r"(?:\[pt\])?(?:\s+OR\s+(?:randomized controlled trial|meta-analysis|"
    r"systematic review|clinical trial|review|case reports?)"
    r"(?:\[pt\])?)*(?:\))?",
    re.IGNORECASE,
)

# Stop words to filter when extracting core keywords
_STOP_WORDS = frozenset(
    {
        "in",
        "of",
        "for",
        "the",
        "a",
        "an",
        "and",
        "or",
        "with",
        "to",
        "on",
        "by",
        "is",
        "vs",
        "versus",
        "from",
        "at",
        "as",
        "not",
        "between",
        "during",
        "after",
        "before",
        "using",
        "through",
        "about",
        "into",
    }
)


# ============================================================================
# Search Depth Metrics (Quantified Deep Search)
# ============================================================================


@dataclass
class StrategyResult:
    """Result from executing one search strategy."""

    strategy_name: str
    query: str
    source: str
    articles_count: int
    expected_precision: float
    expected_recall: float
    execution_time_ms: float = 0.0


@dataclass
class SearchDepthMetrics:
    """
    Quantified metrics for search depth.

    This answers the question: "How deep was this search?"
    """

    # Semantic Enhancement
    entities_resolved: int = 0  # PubTator3 entities found
    mesh_terms_used: int = 0  # MeSH terms in search
    synonyms_expanded: int = 0  # Synonym expansions

    # Strategy Execution
    strategies_generated: int = 0  # How many strategies were planned
    strategies_executed: int = 0  # How many actually ran
    strategies_with_results: int = 0  # How many returned results

    # Coverage Metrics
    estimated_recall: float = 0.0  # Combined recall estimate (0-1)
    estimated_precision: float = 0.0  # Combined precision estimate (0-1)
    depth_score: float = 0.0  # Overall depth score (0-100)

    # Strategy Details
    strategy_results: list[StrategyResult] = field(default_factory=list)

    def calculate_depth_score(self) -> float:
        """
        Calculate overall search depth score (0-100).

        Factors:
        - Entity resolution: up to 30 points (semantic understanding)
        - MeSH coverage: up to 30 points (standardized vocabulary)
        - Strategy diversity: up to 20 points (multiple approaches)
        - Recall estimate: up to 20 points (coverage)
        """
        entity_score = min(30, self.entities_resolved * 10)
        mesh_score = min(30, self.mesh_terms_used * 10)
        strategy_score = min(20, self.strategies_with_results * 5)
        recall_score = self.estimated_recall * 20

        self.depth_score = entity_score + mesh_score + strategy_score + recall_score
        return self.depth_score

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON output."""
        return {
            "entities_resolved": self.entities_resolved,
            "mesh_terms_used": self.mesh_terms_used,
            "synonyms_expanded": self.synonyms_expanded,
            "strategies_generated": self.strategies_generated,
            "strategies_executed": self.strategies_executed,
            "strategies_with_results": self.strategies_with_results,
            "estimated_recall": round(self.estimated_recall, 2),
            "estimated_precision": round(self.estimated_precision, 2),
            "depth_score": round(self.depth_score, 1),
            "strategy_results": [
                {
                    "name": s.strategy_name,
                    "query": s.query[:100] + "..." if len(s.query) > 100 else s.query,
                    "source": s.source,
                    "articles": s.articles_count,
                }
                for s in self.strategy_results
            ],
        }

    def summary(self) -> str:
        """Human-readable summary."""
        self.calculate_depth_score()
        level = "🟢 Deep" if self.depth_score >= 60 else "🟡 Moderate" if self.depth_score >= 30 else "🔴 Shallow"
        return (
            f"{level} (Score: {self.depth_score:.0f}/100) | "
            f"Entities: {self.entities_resolved}, MeSH: {self.mesh_terms_used}, "
            f"Strategies: {self.strategies_with_results}/{self.strategies_executed}"
        )


@dataclass
class RelaxationStep:
    """Describes one step of query relaxation."""

    level: int
    action: str
    description: str
    query: str
    min_year: int | None = None
    max_year: int | None = None
    advanced_filters: dict = field(default_factory=dict)
    result_count: int = 0


@dataclass
class RelaxationResult:
    """Result of auto-relaxation process."""

    original_query: str
    relaxed_query: str
    steps_tried: list[RelaxationStep]
    successful_step: RelaxationStep | None
    total_results: int


def _generate_relaxation_steps(
    query: str,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict,
) -> list[RelaxationStep]:
    """Generate progressive relaxation steps from narrow to broad.

    Scope ordering principle (narrow → broad):
      Level 1: Remove advanced clinical filters (least core impact)
      Level 2: Remove year constraints
      Level 3: Remove publication type filters (e.g., AND RCT[pt])
      Level 4: Remove PubMed field tags ([Title], [MeSH Terms], etc.)
      Level 5: Relax Boolean logic (AND → OR)
      Level 6: Extract core keywords only (most broad)

    Only generates steps that are actually applicable to the given query.
    """
    steps: list[RelaxationStep] = []
    level = 1

    current_query = query
    current_min_year = min_year
    current_max_year = max_year
    current_filters = dict(advanced_filters)

    # --- Level 1: Remove advanced filters ---
    active_filters = {k: v for k, v in current_filters.items() if v is not None}
    if active_filters:
        filter_names = ", ".join(f"{k}={v}" for k, v in active_filters.items())
        steps.append(
            RelaxationStep(
                level=level,
                action="remove_advanced_filters",
                description=f"移除進階篩選條件: {filter_names}",
                query=current_query,
                min_year=current_min_year,
                max_year=current_max_year,
                advanced_filters={},
            )
        )
        current_filters = {}
        level += 1

    # --- Level 2: Remove year constraints ---
    if current_min_year or current_max_year:
        year_parts = []
        if current_min_year:
            year_parts.append(f"min_year={current_min_year}")
        if current_max_year:
            year_parts.append(f"max_year={current_max_year}")
        steps.append(
            RelaxationStep(
                level=level,
                action="remove_year_filter",
                description=f"移除年份限制: {', '.join(year_parts)}",
                query=current_query,
                min_year=None,
                max_year=None,
                advanced_filters=current_filters,
            )
        )
        current_min_year = None
        current_max_year = None
        level += 1

    # --- Level 3: Remove publication type filters ---
    if _PUB_TYPE_FILTER_PATTERN.search(current_query):
        relaxed = _PUB_TYPE_FILTER_PATTERN.sub("", current_query).strip()
        relaxed = re.sub(r"\s+", " ", relaxed).strip()
        if relaxed and relaxed != current_query:
            steps.append(
                RelaxationStep(
                    level=level,
                    action="remove_pub_type_filter",
                    description="移除出版類型篩選 (如 RCT, Meta-analysis 等)",
                    query=relaxed,
                    min_year=current_min_year,
                    max_year=current_max_year,
                    advanced_filters=current_filters,
                )
            )
            current_query = relaxed
            level += 1

    # --- Level 4: Remove field tags ---
    if _FIELD_TAG_PATTERN.search(current_query):
        relaxed = _FIELD_TAG_PATTERN.sub("", current_query)
        # Clean up leftover parentheses and whitespace
        relaxed = re.sub(r"\(\s*\)", "", relaxed)
        relaxed = re.sub(r"\s+", " ", relaxed).strip()
        # Remove leading/trailing Boolean operators
        relaxed = re.sub(r"^\s*(AND|OR)\s+", "", relaxed, flags=re.IGNORECASE)
        relaxed = re.sub(r"\s+(AND|OR)\s*$", "", relaxed, flags=re.IGNORECASE)
        if relaxed and relaxed != current_query:
            steps.append(
                RelaxationStep(
                    level=level,
                    action="remove_field_tags",
                    description="移除 PubMed 欄位限制 (如 [Title], [MeSH Terms])",
                    query=relaxed,
                    min_year=current_min_year,
                    max_year=current_max_year,
                    advanced_filters=current_filters,
                )
            )
            current_query = relaxed
            level += 1

    # --- Level 5: AND → OR ---
    if re.search(r"\bAND\b", current_query, re.IGNORECASE):
        relaxed = re.sub(r"\s+AND\s+", " OR ", current_query, flags=re.IGNORECASE)
        steps.append(
            RelaxationStep(
                level=level,
                action="and_to_or",
                description="放寬布林邏輯: AND → OR (任一關鍵字即可匹配)",
                query=relaxed,
                min_year=current_min_year,
                max_year=current_max_year,
                advanced_filters=current_filters,
            )
        )
        current_query = relaxed
        level += 1

    # --- Level 6: Core keywords only ---
    # Strip all operators, quotes, parentheses, field tags
    core = re.sub(r'"([^"]+)"', r"\1", current_query)  # unquote
    core = re.sub(r"\b(AND|OR|NOT)\b", " ", core, flags=re.IGNORECASE)
    core = re.sub(r"[\[\]()\"']", " ", core)
    core = re.sub(r"\s+", " ", core).strip()

    words = core.split()
    significant = [w for w in words if w.lower() not in _STOP_WORDS and len(w) > 2]

    if len(significant) > 2:
        # Keep at most 2-3 core keywords
        core_keywords = significant[:3]
        core_query = " ".join(core_keywords)
        if core_query.lower() != current_query.lower().strip():
            steps.append(
                RelaxationStep(
                    level=level,
                    action="core_keywords_only",
                    description=f"簡化為核心關鍵字: {core_query}",
                    query=core_query,
                    min_year=None,
                    max_year=None,
                    advanced_filters={},
                )
            )

    return steps


async def _auto_relax_search(
    searcher: LiteratureSearcher,
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict,
) -> RelaxationResult | None:
    """Progressively relax search query until results are found.

    Only re-searches PubMed (primary source) for efficiency.

    Returns:
        RelaxationResult if relaxation was attempted, None if no steps available.
    """
    steps = _generate_relaxation_steps(query, min_year, max_year, advanced_filters)

    if not steps:
        return None

    result = RelaxationResult(
        original_query=query,
        relaxed_query=query,
        steps_tried=[],
        successful_step=None,
        total_results=0,
    )

    for step in steps:
        try:
            articles, total_count = await _search_pubmed(
                searcher,
                step.query,
                limit,
                step.min_year,
                step.max_year,
                **step.advanced_filters,
            )
            step.result_count = len(articles)
            result.steps_tried.append(step)

            if articles:
                result.successful_step = step
                result.relaxed_query = step.query
                result.total_results = total_count or len(articles)
                logger.info(f"Auto-relaxation succeeded at level {step.level} ({step.action}): {len(articles)} results")
                return result

            logger.debug(f"Relaxation level {step.level} ({step.action}): still 0 results")

        except Exception as e:
            logger.warning(f"Relaxation level {step.level} failed: {e}")
            step.result_count = 0
            result.steps_tried.append(step)

    # All steps tried, still 0 results
    return result


# ============================================================================
# Deep Multi-Strategy Search
# ============================================================================


async def _execute_deep_search(
    searcher: LiteratureSearcher,
    enhanced_query: EnhancedQuery,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    advanced_filters: dict,
) -> tuple[list[list[UnifiedArticle]], SearchDepthMetrics, int | None]:
    """
    Execute true deep search using ALL strategies from SemanticEnhancer.

    This is the core of "deep search" - we don't just throw keywords at API,
    we execute multiple semantically-aware strategies in parallel.

    Args:
        searcher: PubMed searcher instance
        enhanced_query: Result from SemanticEnhancer with entities and strategies
        limit: Max results per strategy
        min_year, max_year: Year filters
        advanced_filters: Additional PubMed filters

    Returns:
        Tuple of (all_results, depth_metrics, pubmed_total_count)
    """
    import time

    metrics = SearchDepthMetrics()

    # Populate metrics from enhanced_query
    metrics.entities_resolved = len(enhanced_query.entities)
    metrics.mesh_terms_used = len([e for e in enhanced_query.entities if e.mesh_id])
    metrics.synonyms_expanded = len([t for t in enhanced_query.expanded_terms if t.source != "original"])
    metrics.strategies_generated = len(enhanced_query.strategies)

    all_results: list[list[UnifiedArticle]] = []
    pubmed_total_count: int | None = None
    total_precision = 0.0
    total_recall = 0.0

    # Execute each strategy
    strategies = enhanced_query.strategies or [
        # Fallback: at least search original query
        SearchPlan(
            name="original",
            query=enhanced_query.original_query,
            source="pubmed",
            priority=1,
            expected_precision=0.5,
            expected_recall=0.5,
        )
    ]

    # Sort by priority (highest first)
    strategies = sorted(strategies, key=lambda s: s.priority, reverse=True)

    async def execute_strategy(
        strategy: SearchPlan,
    ) -> tuple[StrategyResult, list[UnifiedArticle], int | None]:
        """Execute one strategy and return results."""
        start_time = time.perf_counter()
        articles: list[UnifiedArticle] = []
        total_count: int | None = None

        try:
            if strategy.source == "pubmed":
                articles, total_count = await _search_pubmed(
                    searcher,
                    strategy.query,
                    limit,
                    min_year,
                    max_year,
                    **advanced_filters,
                )
            elif strategy.source == "europe_pmc":
                articles, total_count = await _search_europe_pmc(
                    strategy.query,
                    limit,
                    min_year,
                    max_year,
                )
            elif strategy.source == "openalex":
                articles, total_count = await _search_openalex(
                    strategy.query,
                    limit,
                    min_year,
                    max_year,
                )
            # Add more sources as needed

        except Exception as e:
            logger.warning(f"Strategy '{strategy.name}' failed: {e}")

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        result = StrategyResult(
            strategy_name=strategy.name,
            query=strategy.query,
            source=strategy.source,
            articles_count=len(articles),
            expected_precision=strategy.expected_precision,
            expected_recall=strategy.expected_recall,
            execution_time_ms=elapsed_ms,
        )

        return result, articles, total_count

    # Execute all strategies in parallel
    tasks = [execute_strategy(s) for s in strategies]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Strategy execution error: {result}")
            continue

        # Type narrowing: result is now tuple, not Exception
        strategy_result, articles, total_count = result  # type: ignore[misc]
        metrics.strategy_results.append(strategy_result)
        metrics.strategies_executed += 1

        if articles:
            all_results.append(articles)
            metrics.strategies_with_results += 1
            total_precision += strategy_result.expected_precision
            total_recall += strategy_result.expected_recall

            # Keep first PubMed total count
            if total_count and pubmed_total_count is None:
                pubmed_total_count = total_count

    # Calculate combined metrics
    if metrics.strategies_with_results > 0:
        # Combined recall: 1 - (1-r1)(1-r2)... (probability of finding at least once)
        combined_recall = 1.0
        for sr in metrics.strategy_results:
            if sr.articles_count > 0:
                combined_recall *= 1 - sr.expected_recall
        metrics.estimated_recall = 1 - combined_recall

        # Average precision (weighted by articles found)
        total_articles = sum(sr.articles_count for sr in metrics.strategy_results)
        if total_articles > 0:
            weighted_precision = sum(sr.expected_precision * sr.articles_count for sr in metrics.strategy_results)
            metrics.estimated_precision = weighted_precision / total_articles
    else:
        metrics.estimated_recall = 0.0
        metrics.estimated_precision = 0.0

    metrics.calculate_depth_score()

    logger.info(
        f"Deep search: {metrics.strategies_executed} strategies, "
        f"{metrics.strategies_with_results} with results, "
        f"depth score: {metrics.depth_score:.0f}"
    )

    return all_results, metrics, pubmed_total_count


async def _search_europe_pmc(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search Europe PMC and convert to UnifiedArticle.

    Europe PMC's normalized format is compatible with PubMed format,
    so we map a few fields and use from_pubmed() for conversion.
    """
    try:
        results = await search_alternate_source(
            query=query,
            source="europe_pmc",
            limit=limit,
            min_year=min_year,
            max_year=max_year,
        )

        articles = []
        for r in results:
            # Map Europe PMC fields to PubMed expected format
            if "pmc_id" in r and not r.get("pmc"):
                r["pmc"] = r["pmc_id"]
            if "journal_abbrev" in r and not r.get("source"):
                r["source"] = r["journal_abbrev"]
            # Mark as coming from Europe PMC for source tracking
            r["_source_origin"] = "europe_pmc"

            try:
                article = UnifiedArticle.from_pubmed(r)
                # Override primary source to reflect true origin
                article.primary_source = "europe_pmc"
                articles.append(article)
            except Exception as e:
                logger.warning(f"Failed to convert Europe PMC result: {e}")

        return articles, None
    except Exception as e:
        logger.exception(f"Europe PMC search failed: {e}")
        return [], None


# ============================================================================
# Source Search Functions
# ============================================================================


async def _search_pubmed(
    searcher: LiteratureSearcher,
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
    **advanced_filters,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search PubMed and convert to UnifiedArticle.

    Returns:
        Tuple of (articles, total_count) where total_count is the total
        number of matching articles in PubMed (not just returned count).

    Advanced Filters (passed via **advanced_filters):
        age_group: newborn, infant, child, adolescent, adult, aged, etc.
        sex: male, female
        species: humans, animals
        language: english, chinese, japanese, etc.
        clinical_query: therapy, diagnosis, prognosis, etiology
    """
    try:
        results = await searcher.search(
            query=query,
            limit=limit,
            min_year=min_year,
            max_year=max_year,
            **advanced_filters,  # Pass all advanced filters
        )

        # Extract total_count from metadata (if present)
        total_count = None
        if results and "_search_metadata" in results[0]:
            total_count = results[0]["_search_metadata"].get("total_count")
            del results[0]["_search_metadata"]
            # Remove empty dict if only metadata was present
            if not results[0] or results[0] == {}:
                results = results[1:] if len(results) > 1 else []

        articles = []
        for r in results:
            if r and "error" not in r:  # Skip error entries
                articles.append(UnifiedArticle.from_pubmed(r))

        return articles, total_count
    except Exception as e:
        logger.exception(f"PubMed search failed: {e}")
        return [], None


async def _search_openalex(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search OpenAlex and convert to UnifiedArticle.

    Returns:
        Tuple of (articles, total_count).
    """
    try:
        results = await search_alternate_source(
            query=query,
            source="openalex",
            limit=limit,
            min_year=min_year,
            max_year=max_year,
        )

        articles = []
        for r in results:
            articles.append(UnifiedArticle.from_openalex(r))

        # OpenAlex doesn't return total count in our current implementation
        return articles, None
    except Exception as e:
        logger.exception(f"OpenAlex search failed: {e}")
        return [], None


async def _search_semantic_scholar(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
) -> tuple[list[UnifiedArticle], int | None]:
    """Search Semantic Scholar and convert to UnifiedArticle.

    Returns:
        Tuple of (articles, total_count).
    """
    try:
        results = await search_alternate_source(
            query=query,
            source="semantic_scholar",
            limit=limit,
            min_year=min_year,
            max_year=max_year,
        )

        articles = []
        for r in results:
            articles.append(UnifiedArticle.from_semantic_scholar(r))

        # Semantic Scholar doesn't return total count in our current implementation
        return articles, None
    except Exception as e:
        logger.exception(f"Semantic Scholar search failed: {e}")
        return [], None


async def _enrich_with_crossref(articles: list[UnifiedArticle]) -> None:
    """Enrich articles with CrossRef metadata (in-place, parallel)."""
    try:
        client = get_crossref_client()

        # Filter articles that need enrichment
        articles_to_enrich = [
            (i, article) for i, article in enumerate(articles) if article.doi and not article.citation_metrics
        ]

        if not articles_to_enrich:
            return

        # Limit to avoid too many parallel requests
        max_parallel = 10
        articles_to_enrich = articles_to_enrich[:max_parallel]

        async def fetch_crossref(idx: int, article: UnifiedArticle) -> tuple[int, dict | None]:
            try:
                doi = article.doi
                if not doi:
                    return (idx, None)
                work = await client.get_work(doi)
                return (idx, work)
            except Exception:
                return (idx, None)

        # Parallel fetch with asyncio.gather
        results = await asyncio.gather(
            *[fetch_crossref(idx, article) for idx, article in articles_to_enrich],
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                logger.debug(f"CrossRef enrichment skipped: {result}")
                continue
            # Type narrowing: result is now tuple, not Exception
            idx, work = result  # type: ignore[misc]
            if work:
                try:
                    crossref_article = UnifiedArticle.from_crossref(work)
                    articles[idx].merge_from(crossref_article)
                except Exception as e:
                    logger.debug(f"CrossRef enrichment skipped: {e}")

    except Exception as e:
        logger.warning(f"CrossRef enrichment failed: {e}")


async def _enrich_with_journal_metrics(articles: list[UnifiedArticle]) -> None:
    """Enrich articles with journal-level metrics from OpenAlex Sources API (in-place).

    Fetches journal h-index, 2yr_mean_citedness (≈ Impact Factor), ISSN, DOAJ status,
    subject areas, etc. Uses batch API for efficiency.

    Strategy:
    1. Collect OpenAlex source IDs from articles that came from OpenAlex
    2. Batch-fetch source metadata
    3. For articles without source IDs, skip (no reliable lookup available)
    4. Create JournalMetrics objects and assign to articles
    """
    from pubmed_search.domain.entities.article import JournalMetrics

    try:
        client = get_openalex_client()

        # Collect unique source IDs from OpenAlex-sourced articles
        # Source ID is stored in raw_data._openalex_source_id
        source_id_to_articles: dict[str, list[int]] = {}  # source_id → [article_idx]

        for i, article in enumerate(articles):
            if article.journal_metrics:
                continue  # Already enriched

            source_id = _extract_openalex_source_id(article)
            if source_id:
                clean_id = source_id.replace("https://openalex.org/", "")
                if clean_id not in source_id_to_articles:
                    source_id_to_articles[clean_id] = []
                source_id_to_articles[clean_id].append(i)

        if not source_id_to_articles:
            return

        # Batch fetch all unique sources
        source_data = await client.get_sources_batch(list(source_id_to_articles.keys()))

        # Map source data to articles
        for source_id, article_indices in source_id_to_articles.items():
            data = source_data.get(source_id)
            if not data:
                continue

            journal_metrics = JournalMetrics(
                issn=data.get("issn"),
                issn_l=data.get("issn_l"),
                openalex_source_id=data.get("openalex_source_id"),
                h_index=data.get("h_index"),
                two_year_mean_citedness=data.get("two_year_mean_citedness"),
                i10_index=data.get("i10_index"),
                works_count=data.get("works_count"),
                cited_by_count=data.get("cited_by_count"),
                is_in_doaj=data.get("is_in_doaj"),
                source_type=data.get("source_type"),
                subject_areas=data.get("subject_areas", []),
            )

            for idx in article_indices:
                articles[idx].journal_metrics = journal_metrics

        enriched = sum(1 for a in articles if a.journal_metrics is not None)
        if enriched > 0:
            logger.info(
                f"Journal metrics: enriched {enriched}/{len(articles)} articles from {len(source_data)} unique journals"
            )

    except Exception as e:
        logger.warning(f"Journal metrics enrichment failed: {e}")


def _extract_openalex_source_id(article: UnifiedArticle) -> str | None:
    """Extract OpenAlex source ID from an article's metadata.

    Checks:
    1. raw_data._openalex_source_id (set by OpenAlex _normalize_work)
    2. raw_data.primary_location.source.id (direct OpenAlex response)
    """
    for source_meta in article.sources:
        if source_meta.source == "openalex" and source_meta.raw_data:
            raw = source_meta.raw_data
            # Check _openalex_source_id (set in _normalize_work)
            if raw.get("_openalex_source_id"):
                return raw["_openalex_source_id"]
            # Fallback: check nested structure
            location = raw.get("primary_location", {})
            if isinstance(location, dict):
                source = location.get("source", {})
                if isinstance(source, dict) and source.get("id"):
                    return source["id"]
    return None


async def _enrich_with_unpaywall(articles: list[UnifiedArticle]) -> None:
    """Enrich articles with Unpaywall OA links (in-place, parallel)."""
    try:
        client = get_unpaywall_client()

        # Filter articles that need enrichment
        articles_to_enrich = [
            (i, article) for i, article in enumerate(articles) if article.doi and not article.has_open_access
        ]

        if not articles_to_enrich:
            return

        # Limit to avoid too many parallel requests
        max_parallel = 10
        articles_to_enrich = articles_to_enrich[:max_parallel]

        async def fetch_unpaywall(idx: int, article: UnifiedArticle) -> tuple[int, dict | None]:
            try:
                doi = article.doi
                if not doi:
                    return (idx, None)
                oa_info = await client.enrich_article(doi)
                return (idx, oa_info if oa_info.get("is_oa") else None)
            except Exception:
                return (idx, None)

        # Parallel fetch with asyncio.gather
        results = await asyncio.gather(
            *[fetch_unpaywall(idx, article) for idx, article in articles_to_enrich],
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                logger.debug(f"Unpaywall enrichment skipped: {result}")
                continue
            # Type narrowing: result is now tuple, not Exception
            idx, oa_info = result  # type: ignore[misc]
            if oa_info:
                try:
                    from pubmed_search.domain.entities.article import (
                        OpenAccessLink,
                        OpenAccessStatus,
                    )

                    articles[idx].is_open_access = True

                    # Map OA status
                    status_map = {
                        "gold": OpenAccessStatus.GOLD,
                        "green": OpenAccessStatus.GREEN,
                        "hybrid": OpenAccessStatus.HYBRID,
                        "bronze": OpenAccessStatus.BRONZE,
                    }
                    articles[idx].oa_status = status_map.get(
                        oa_info.get("oa_status", "unknown"),
                        OpenAccessStatus.UNKNOWN,
                    )

                    # Add OA links
                    for link_data in oa_info.get("oa_links", []):
                        if link_data.get("url"):
                            articles[idx].oa_links.append(
                                OpenAccessLink(
                                    url=link_data["url"],
                                    version=link_data.get("version", "unknown"),
                                    host_type=link_data.get("host_type"),
                                    license=link_data.get("license"),
                                    is_best=link_data.get("is_best", False),
                                )
                            )
                except Exception as e:
                    logger.debug(f"Unpaywall enrichment skipped: {e}")

    except Exception as e:
        logger.warning(f"Unpaywall enrichment failed: {e}")


def _is_preprint(article: UnifiedArticle, _article_type_class: type) -> bool:
    """
    Determine if an article is a non-peer-reviewed preprint.

    Detection heuristics (ordered by confidence):
    1. article_type is PREPRINT (detected from OpenAlex/CrossRef/S2)
    2. Has arXiv ID but no PubMed ID (arXiv-only paper)
    3. Primary source is a known preprint server
    4. DOI prefix matches known preprint servers
    5. Journal name matches known preprint servers

    Returns:
        True if the article is likely a preprint (not peer-reviewed).
    """
    # Check article type
    if article.article_type == _article_type_class.PREPRINT:
        return True

    # Has arXiv ID but no PubMed ID → likely preprint
    if getattr(article, "arxiv_id", None) and not article.pmid:
        return True

    # Primary source is a preprint server
    preprint_sources = {"arxiv", "medrxiv", "biorxiv", "chemrxiv", "ssrn", "preprints.org", "research square"}
    if article.primary_source and article.primary_source.lower() in preprint_sources:
        return True

    # DOI prefix matches known preprint servers
    doi = article.doi or ""
    if doi:
        doi_lower = doi.lower()
        # 10.1101/ → bioRxiv/medRxiv
        # 10.48550/ → arXiv
        # 10.26434/ → chemRxiv
        # 10.2139/ → SSRN
        # 10.20944/ → Preprints.org
        # 10.21203/ → Research Square
        preprint_doi_prefixes = (
            "10.1101/",
            "10.48550/",
            "10.26434/",
            "10.2139/",
            "10.20944/",
            "10.21203/",
        )
        if any(doi_lower.startswith(prefix) for prefix in preprint_doi_prefixes):
            return True

    # Journal name matches known preprint servers
    journal = (article.journal or "").lower()
    if journal:
        preprint_journal_names = (
            "arxiv",
            "medrxiv",
            "biorxiv",
            "chemrxiv",
            "ssrn",
            "preprints",
            "research square",
        )
        if any(name in journal for name in preprint_journal_names):
            return True

    return False


def _enrich_with_similarity_scores(
    articles: list[UnifiedArticle],
    query: str,
) -> None:
    """
    Enrich articles with similarity scores using external APIs (in-place).

    Uses a ranking-based approach:
    - First article from each source gets highest similarity (1.0)
    - Subsequent articles get linearly decreasing scores

    For cross-source similarity, we use the article's ranking position.

    Args:
        articles: Articles to enrich
        query: Original search query (for context)
    """
    try:
        if not articles:
            return

        # Calculate similarity scores based on ranking position
        # This is a simple but effective approach:
        # - Search engines already rank by relevance
        # - We convert ranking position to 0-1 score

        total = len(articles)
        for i, article in enumerate(articles):
            # Base similarity from ranking position
            # First result = 1.0, last = 0.1 (never 0)
            base_score = max(0.1, 1.0 - (i * 0.9 / max(total - 1, 1)))

            # Adjust based on source trust (PubMed results generally more relevant)
            source_boost = {
                "pubmed": 0.1,
                "semantic_scholar": 0.05,
                "openalex": 0.03,
                "crossref": 0.0,
            }
            boost = source_boost.get(article.primary_source, 0.0)

            # Calculate final score (cap at 1.0)
            final_score = min(1.0, base_score + boost)

            # Set similarity fields
            article.similarity_score = round(final_score, 3)
            article.similarity_source = "ranking"
            article.similarity_details = {
                "ranking_score": round(base_score, 3),
                "source_boost": boost,
                "position": i + 1,
            }

        logger.debug(f"Enriched {len(articles)} articles with similarity scores")

    except Exception as e:
        logger.warning(f"Similarity enrichment failed: {e}")


async def _enrich_with_api_similarity(
    articles: list[UnifiedArticle],
    seed_pmid: str | None = None,
) -> None:
    """
    Enrich articles with similarity scores from external APIs.

    Uses Semantic Scholar recommendations and Europe PMC similar articles
    to get pre-computed similarity scores when available.

    Args:
        articles: Articles to enrich
        seed_pmid: Optional seed PMID for API-based similarity lookup
    """
    if not articles or not seed_pmid:
        return

    try:
        from pubmed_search.infrastructure.sources.semantic_scholar import (
            SemanticScholarClient,
        )

        s2_client = SemanticScholarClient()

        # Get recommendations based on seed article
        recommendations = await s2_client.get_recommendations(f"PMID:{seed_pmid}", limit=50)

        if not recommendations:
            return

        # Build lookup table: PMID/DOI -> similarity_score
        sim_lookup: dict[str, float] = {}
        for rec in recommendations:
            pmid = rec.get("pmid", "")
            doi = rec.get("doi", "")
            score = rec.get("similarity_score", 0.5)

            if pmid:
                sim_lookup[pmid] = score
            if doi:
                sim_lookup[doi.lower()] = score

        # Enrich articles with API-based similarity
        for article in articles:
            if article.pmid and article.pmid in sim_lookup:
                article.similarity_score = sim_lookup[article.pmid]
                article.similarity_source = "semantic_scholar"
            elif article.doi and article.doi.lower() in sim_lookup:
                article.similarity_score = sim_lookup[article.doi.lower()]
                article.similarity_source = "semantic_scholar"

        logger.debug("Enriched articles with API similarity scores")

    except Exception as e:
        logger.debug(f"API similarity enrichment skipped: {e}")


# ============================================================================
# Result Formatting
# ============================================================================


async def _format_unified_results(
    articles: list[UnifiedArticle],
    analysis: AnalyzedQuery,
    stats: AggregationStats,
    include_analysis: bool = True,
    pubmed_total_count: int | None = None,
    icd_matches: list | None = None,
    preprint_results: dict | None = None,
    include_trials: bool = True,
    original_query: str = "",
    enhanced_entities: list[str] | None = None,
    relaxation_result: RelaxationResult | None = None,
    deep_search_metrics: SearchDepthMetrics | None = None,
    prefetched_trials: list | None = None,
) -> str:
    """Format unified search results for MCP response."""
    output_parts: list[str] = []

    # Header with analysis summary
    if include_analysis:
        output_parts.append("## 🔍 Unified Search Results\n")
        output_parts.append(f"**Query**: {analysis.original_query}")
        output_parts.append(f"**Analysis**: {analysis.complexity.value} complexity, {analysis.intent.value} intent")
        if analysis.pico:
            pico_str = ", ".join(f"{k}={v}" for k, v in analysis.pico.to_dict().items() if v)
            output_parts.append(f"**PICO**: {pico_str}")

        # ICD code expansion info
        if icd_matches:
            icd_info = ", ".join([f"{m['code']}→{m['mesh']}" for m in icd_matches])
            output_parts.append(f"**ICD Expansion**: {icd_info}")

        # Phase 3: Show PubTator3 resolved entities
        if enhanced_entities:
            entity_str = ", ".join(enhanced_entities[:5])  # Show max 5
            if len(enhanced_entities) > 5:
                entity_str += f" (+{len(enhanced_entities) - 5} more)"
            output_parts.append(f"**🧬 Entities**: {entity_str}")

        # Deep Search Metrics (if enabled)
        if deep_search_metrics:
            output_parts.append(
                f"**🔬 深度搜索**: "
                f"Depth Score {deep_search_metrics.depth_score:.0f}/100 | "
                f"{deep_search_metrics.strategies_executed}/{deep_search_metrics.strategies_generated} 策略執行 | "
                f"估計召回率 {deep_search_metrics.estimated_recall:.0%}"
            )

        output_parts.append(f"**Sources**: {', '.join(stats.by_source.keys())}")

        # Show total count info with PubMed total
        results_str = f"{stats.unique_articles} unique ({stats.duplicates_removed} duplicates removed)"
        if pubmed_total_count is not None and pubmed_total_count > stats.unique_articles:
            results_str = f"📊 返回 **{stats.unique_articles}** 篇 (PubMed 總共 **{pubmed_total_count}** 篇符合) | {stats.duplicates_removed} 去重"
        output_parts.append(f"**Results**: {results_str}")
        output_parts.append("")

    # Relaxation info (if auto-relaxation was triggered)
    if relaxation_result:
        if relaxation_result.successful_step:
            step = relaxation_result.successful_step
            output_parts.append("### ⚠️ 搜尋自動放寬 (Auto-Relaxed)\n")
            output_parts.append(f"原始查詢 `{relaxation_result.original_query}` 返回 **0** 筆結果。")
            output_parts.append(f"已自動放寬至 **Level {step.level}**: {step.description}")
            output_parts.append(f"放寬後查詢: `{relaxation_result.relaxed_query}`")

            # Show all attempted steps for transparency
            if len(relaxation_result.steps_tried) > 1:
                output_parts.append("\n**放寬嘗試過程** (由窄到寬):")
                for s in relaxation_result.steps_tried:
                    status = "✅" if s == relaxation_result.successful_step else "❌ 0 results"
                    output_parts.append(f"  - Level {s.level} ({s.action}): {s.description} → {status}")
            output_parts.append("")
        else:
            # All steps tried, still 0
            output_parts.append("### ⚠️ 搜尋自動放寬失敗\n")
            output_parts.append(f"原始查詢 `{relaxation_result.original_query}` 返回 **0** 筆結果。")
            output_parts.append("已嘗試所有放寬策略，仍無結果。")
            if relaxation_result.steps_tried:
                output_parts.append("\n**已嘗試:**")
                for s in relaxation_result.steps_tried:
                    output_parts.append(f"  - Level {s.level}: {s.description} → ❌ 0 results")
            output_parts.append("\n**建議:** 嘗試不同的搜尋詞，或使用 `generate_search_queries()` 取得 MeSH 同義詞。")
            output_parts.append("")

    # Articles
    if not articles:
        output_parts.append("No results found.")
        return "\n".join(output_parts)

    output_parts.append("---\n")

    for i, article in enumerate(articles, 1):
        # Article header
        score_str = f" (score: {article.ranking_score:.2f})" if article.ranking_score else ""
        output_parts.append(f"### {i}. {article.title}{score_str}")

        # Identifiers
        ids = []
        if article.pmid:
            ids.append(f"PMID: {article.pmid}")
        if article.doi:
            ids.append(f"DOI: {article.doi}")
        if article.pmc:
            ids.append(f"PMC: {article.pmc}")
        if ids:
            output_parts.append(" | ".join(ids))

        # Study type badge (from PubMed publication_types, not hard-coded inference)
        from pubmed_search.domain.entities.article import ArticleType

        if article.article_type and article.article_type != ArticleType.UNKNOWN:
            # Evidence level badge based on study type
            type_badges = {
                ArticleType.META_ANALYSIS: "🟢 Meta-Analysis (1a)",
                ArticleType.SYSTEMATIC_REVIEW: "🟢 Systematic Review (1a)",
                ArticleType.RANDOMIZED_CONTROLLED_TRIAL: "🟢 RCT (1b)",
                ArticleType.CLINICAL_TRIAL: "🟡 Clinical Trial (1b-2b)",
                ArticleType.REVIEW: "⚪ Review",
                ArticleType.CASE_REPORT: "🟠 Case Report (4)",
            }
            badge = type_badges.get(article.article_type, f"📄 {article.article_type.value}")
            output_parts.append(f"**Type**: {badge}")

        # Authors and journal
        output_parts.append(f"**Authors**: {article.author_string}")
        if article.journal:
            journal_str = article.journal
            if article.year:
                journal_str += f" ({article.year})"
            if article.volume:
                journal_str += f"; {article.volume}"
                if article.issue:
                    journal_str += f"({article.issue})"
            if article.pages:
                journal_str += f": {article.pages}"
            output_parts.append(f"**Journal**: {journal_str}")

        # Open Access status
        if article.has_open_access:
            oa_link = article.best_oa_link
            if oa_link:
                output_parts.append(f"**OA**: ✅ [{article.oa_status.value}]({oa_link.url})")
            else:
                output_parts.append(f"**OA**: ✅ {article.oa_status.value}")

        # Institutional access link (OpenURL)
        openurl_config = get_openurl_config()
        if openurl_config.enabled and (openurl_config.resolver_base or openurl_config.preset):
            openurl = get_openurl_link(
                {
                    "pmid": article.pmid,
                    "doi": article.doi,
                    "title": article.title,
                    "journal": article.journal,
                    "year": article.year,
                    "volume": article.volume,
                    "issue": article.issue,
                    "pages": article.pages,
                }
            )
            if openurl:
                output_parts.append(f"**Library**: 🏛️ [Find via Library]({openurl})")

        # Citation metrics
        if article.citation_metrics:
            metrics = article.citation_metrics
            metric_parts = []
            if metrics.citation_count is not None:
                metric_parts.append(f"Citations: {metrics.citation_count}")
            if metrics.nih_percentile is not None:
                metric_parts.append(f"Percentile: {metrics.nih_percentile:.0f}%")
            if metrics.relative_citation_ratio is not None:
                metric_parts.append(f"RCR: {metrics.relative_citation_ratio:.2f}")
            if metric_parts:
                output_parts.append(f"**Impact**: {', '.join(metric_parts)}")

        # Journal metrics
        if article.journal_metrics:
            jm = article.journal_metrics
            jm_parts = []
            if jm.two_year_mean_citedness is not None:
                jm_parts.append(f"IF≈{jm.two_year_mean_citedness:.2f}")
            if jm.h_index is not None:
                jm_parts.append(f"h-index: {jm.h_index}")
            if jm.impact_tier and jm.impact_tier != "unknown":
                tier_icons = {
                    "top": "🏆",
                    "high": "⭐",
                    "medium": "📊",
                    "low": "📄",
                    "minimal": "📄",
                }
                icon = tier_icons.get(jm.impact_tier, "")
                jm_parts.append(f"{icon} {jm.impact_tier.capitalize()}-tier")
            if jm.is_in_doaj:
                jm_parts.append("DOAJ ✓")
            if jm_parts:
                output_parts.append(f"**Journal**: {', '.join(jm_parts)}")

        # Similarity score
        if article.similarity_score is not None:
            sim_str = f"**Relevance**: {article.similarity_score:.0%}"
            if article.similarity_source:
                sim_str += f" ({article.similarity_source})"
            output_parts.append(sim_str)

        # Abstract (truncated)
        if article.abstract:
            abstract = article.abstract
            if len(abstract) > 300:
                abstract = abstract[:300] + "..."
            output_parts.append(f"\n{abstract}")

        # Sources
        sources = [s.source for s in article.sources]
        output_parts.append(f"\n*Sources: {', '.join(sources)}*")
        output_parts.append("")

    # === Preprint Results Section ===
    if preprint_results and preprint_results.get("total", 0) > 0:
        output_parts.append("\n---")
        output_parts.append("\n## 📄 Preprints (Not Peer-Reviewed)\n")
        for src, papers in preprint_results.get("by_source", {}).items():
            if papers:
                output_parts.append(f"### {src.upper()} ({len(papers)} results)")
                for j, paper in enumerate(papers[:5], 1):  # Show max 5 per source
                    output_parts.append(f"\n**{j}. {paper.get('title', 'N/A')}**")
                    if paper.get("authors"):
                        authors_str = ", ".join(paper["authors"][:3])
                        if len(paper["authors"]) > 3:
                            authors_str += " et al."
                        output_parts.append(f"*{authors_str}* ({paper.get('published', 'N/A')})")
                    if paper.get("pdf_url"):
                        output_parts.append(f"PDF: {paper['pdf_url']}")
                    if paper.get("source_url"):
                        output_parts.append(f"Link: {paper['source_url']}")
                output_parts.append("")

    # === Related Clinical Trials (use pre-fetched results) ===
    if include_trials and original_query:
        try:
            from pubmed_search.infrastructure.sources.clinical_trials import (
                format_trials_section,
                search_related_trials,
            )

            trials = prefetched_trials
            if trials is None:
                # Fallback: fetch inline if not pre-fetched
                trial_query = " ".join(original_query.split()[:5])
                trials = await search_related_trials(trial_query, limit=3)
            if trials:
                output_parts.append(format_trials_section(trials, max_display=3))
        except Exception as e:
            logger.debug(f"Clinical trials search skipped: {e}")

    return "\n".join(output_parts)


def _format_as_json(
    articles: list[UnifiedArticle],
    analysis: AnalyzedQuery,
    stats: AggregationStats,
    relaxation_result: RelaxationResult | None = None,
    deep_search_metrics: SearchDepthMetrics | None = None,
) -> str:
    """Format results as JSON for programmatic access."""
    result = {
        "analysis": analysis.to_dict(),
        "statistics": stats.to_dict(),
        "articles": [a.to_dict() for a in articles],
    }

    # Add deep search metrics if available
    if deep_search_metrics:
        result["deep_search"] = {
            "enabled": True,
            "depth_score": deep_search_metrics.depth_score,
            "entities_resolved": deep_search_metrics.entities_resolved,
            "mesh_terms_used": deep_search_metrics.mesh_terms_used,
            "synonyms_expanded": deep_search_metrics.synonyms_expanded,
            "strategies_generated": deep_search_metrics.strategies_generated,
            "strategies_executed": deep_search_metrics.strategies_executed,
            "strategies_with_results": deep_search_metrics.strategies_with_results,
            "estimated_recall": deep_search_metrics.estimated_recall,
            "estimated_precision": deep_search_metrics.estimated_precision,
            "strategy_results": [
                {
                    "name": sr.strategy_name,
                    "query": sr.query,
                    "source": sr.source,
                    "articles_found": sr.articles_count,
                    "execution_time_ms": sr.execution_time_ms,
                }
                for sr in deep_search_metrics.strategy_results
            ],
        }

    if relaxation_result and relaxation_result.successful_step:
        step = relaxation_result.successful_step
        result["relaxation"] = {
            "was_relaxed": True,
            "original_query": relaxation_result.original_query,
            "relaxed_query": relaxation_result.relaxed_query,
            "successful_level": step.level,
            "successful_action": step.action,
            "description": step.description,
            "steps_tried": [
                {
                    "level": s.level,
                    "action": s.action,
                    "description": s.description,
                    "query": s.query,
                    "result_count": s.result_count,
                }
                for s in relaxation_result.steps_tried
            ],
        }
    elif relaxation_result and not relaxation_result.successful_step:
        result["relaxation"] = {
            "was_relaxed": False,
            "original_query": relaxation_result.original_query,
            "note": "All relaxation levels tried, still 0 results",
            "steps_tried": [
                {
                    "level": s.level,
                    "action": s.action,
                    "description": s.description,
                    "query": s.query,
                    "result_count": s.result_count,
                }
                for s in relaxation_result.steps_tried
            ],
        }

    return json.dumps(result, ensure_ascii=False, indent=2)


# ============================================================================
# MCP Tool Registration
# ============================================================================


def register_unified_search_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """Register unified search MCP tools."""

    @mcp.tool()
    async def unified_search(
        query: str,
        limit: Union[int, str] = 10,
        min_year: Union[int, str, None] = None,
        max_year: Union[int, str, None] = None,
        ranking: Literal["balanced", "impact", "recency", "quality"] = "balanced",
        output_format: Literal["markdown", "json"] = "markdown",
        include_oa_links: Union[bool, str] = True,
        show_analysis: Union[bool, str] = True,
        # Similarity scores (Phase 5.10)
        include_similarity_scores: Union[bool, str] = True,
        # Advanced filters (Phase 2.1)
        age_group: Union[str, None] = None,
        sex: Union[str, None] = None,
        species: Union[str, None] = None,
        language: Union[str, None] = None,
        clinical_query: Union[str, None] = None,
        # Preprint search (Phase 2.2)
        include_preprints: Union[bool, str] = False,
        # Peer review filter
        peer_reviewed_only: Union[bool, str] = True,
        # Auto-relaxation (Phase 5.x)
        auto_relax: Union[bool, str] = True,
        # Deep search (Phase 3.x) - Use SemanticEnhancer strategies
        deep_search: Union[bool, str] = True,
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
        EXAMPLES:
        ═══════════════════════════════════════════════════════════════════

        Simple lookup:
            unified_search("PMID:12345678")
            → PubMed only, fast

        Topic exploration:
            unified_search("machine learning in anesthesia", limit=20)
            → PubMed + CrossRef enrichment

        Clinical comparison:
            unified_search("remimazolam vs propofol for ICU sedation")
            → Multi-source, PICO detected, impact-ranked

        Systematic review prep:
            unified_search("CRISPR gene therapy cancer", ranking="quality")
            → All sources, quality-ranked, OA links

        Advanced clinical filters:
            unified_search("diabetes treatment", age_group="aged", clinical_query="therapy")
            → Only elderly population studies with therapy filter

            unified_search("breast cancer screening", sex="female", species="humans")
            → Female human studies only

        ICD Code Auto-Detection:
            unified_search("E11 complications")
            → Auto-expands E11 to "Diabetes Mellitus, Type 2"[MeSH]

            unified_search("I21 treatment outcomes")
            → Auto-expands I21 to "Myocardial Infarction"[MeSH]

        Preprint Search:
            unified_search("COVID-19 vaccine efficacy", include_preprints=True)
            → Also searches arXiv, medRxiv, bioRxiv

        Args:
            query: Your search query (natural language, ICD codes, or structured)
            limit: Maximum results per source (default 10)
            min_year: Filter by minimum publication year
            max_year: Filter by maximum publication year
            ranking: Ranking strategy:
                - "balanced": Default, considers all factors
                - "impact": Prioritize high-citation papers
                - "recency": Prioritize recent publications
                - "quality": Prioritize high-evidence studies (RCTs, meta-analyses)
            output_format: "markdown" (human-readable) or "json" (programmatic)
            include_oa_links: Enrich results with open access links (default True)
            show_analysis: Include query analysis in output (default True)
            include_similarity_scores: Add relevance/similarity scores to each result
                                       based on ranking position and source trust.
                                       (default True). Scores range from 0-100%.
            age_group: Age group filter (PubMed only). Options:
                       "newborn" (0-1mo), "infant" (1-23mo), "preschool" (2-5y),
                       "child" (6-12y), "adolescent" (13-18y), "young_adult" (19-24y),
                       "adult" (19+), "middle_aged" (45-64y), "aged" (65+), "aged_80" (80+)
            sex: Sex filter (PubMed only). Options: "male", "female"
            species: Species filter (PubMed only). Options: "humans", "animals"
            language: Language filter (PubMed only). Options: "english", "chinese", etc.
            clinical_query: Clinical query filter (PubMed only). Options:
                           "therapy" (broad), "therapy_narrow" (high specificity),
                           "diagnosis", "diagnosis_narrow",
                           "prognosis", "prognosis_narrow",
                           "etiology", "etiology_narrow",
                           "clinical_prediction", "clinical_prediction_narrow"
                           These are validated PubMed clinical query strategies for EBM.
            include_preprints: Also search preprint servers (arXiv, medRxiv, bioRxiv)
                              Default: False. Set True for cutting-edge research.
            peer_reviewed_only: Filter out non-peer-reviewed articles (preprints,
                              arXiv papers, etc.) from ALL sources including OpenAlex
                              and Semantic Scholar. Default: True.
                              Set False to include preprints mixed in with results.
                              Note: This is independent of include_preprints — even with
                              peer_reviewed_only=True, you can set include_preprints=True
                              to show preprints in a SEPARATE section.
            auto_relax: Automatically relax search when 0 results (default True).
                        Progressive relaxation from narrow to broad:
                        1. Remove advanced filters (age_group, clinical_query, etc.)
                        2. Remove year constraints
                        3. Remove publication type filters (RCT, Meta-analysis)
                        4. Remove field tags ([Title], [MeSH Terms])
                        5. Relax Boolean logic (AND → OR)
                        6. Extract core keywords only
                        Set False to get exact 0-result feedback without relaxation.
            deep_search: Enable semantic deep search using PubTator3 and MeSH expansion
                        (default True). When enabled, the search:
                        - Resolves biomedical entities via PubTator3
                        - Expands queries with MeSH terms and synonyms
                        - Executes multiple search strategies in parallel:
                          * Original query (baseline)
                          * MeSH-expanded query (high precision)
                          * Entity-semantic query (via PubTator3)
                          * Europe PMC full-text search (high recall)
                          * Broad Title/Abstract search (maximum recall)
                        - Aggregates and deduplicates results from all strategies
                        - Reports depth metrics (entities resolved, strategies executed)
                        Set False for simple keyword-only search (faster but shallower).

        Returns:
            Formatted search results with:
            - Query analysis (complexity, intent, PICO)
            - ICD code expansions (if detected)
            - Search statistics (sources, dedup count)
            - Ranked articles with metadata
            - Open access links where available
            - Preprints (if include_preprints=True)
            - Relaxation info (if auto_relax triggered)
        """
        logger.info(f"Unified search: query='{query}', limit={limit}, ranking='{ranking}'")

        try:
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
            min_year = InputNormalizer.normalize_year(min_year)
            max_year = InputNormalizer.normalize_year(max_year)
            include_oa_links = InputNormalizer.normalize_bool(include_oa_links, default=True)
            show_analysis = InputNormalizer.normalize_bool(show_analysis, default=True)
            include_similarity_scores = InputNormalizer.normalize_bool(include_similarity_scores, default=True)
            include_preprints = InputNormalizer.normalize_bool(include_preprints, default=False)
            peer_reviewed_only = InputNormalizer.normalize_bool(peer_reviewed_only, default=True)
            auto_relax = InputNormalizer.normalize_bool(auto_relax, default=True)
            deep_search = InputNormalizer.normalize_bool(deep_search, default=True)

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
            sources = DispatchStrategy.get_sources(analysis)
            logger.info(f"Selected sources: {sources}")

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
                logger.info(f"Executing DEEP SEARCH with {len(enhanced_query.strategies)} strategies")
                (
                    all_results,
                    deep_search_metrics,
                    pubmed_total_count,
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

                    if source == "crossref":
                        # CrossRef is used for enrichment, not primary search
                        return ("crossref", [], None)

                    return (source, [], None)

                # Filter out crossref from parallel search (it's enrichment only)
                search_sources = [s for s in sources if s != "crossref"]

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
            if "crossref" in sources:
                await _enrich_with_crossref(articles)

            # === Step 6.25: Enrich with Journal Metrics (OpenAlex Sources API) ===
            if "openalex" in sources:
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

            # === Step 8.6: Record to Session ===
            _record_search_only(ranked, analysis.original_query)

            # === Step 9: Format Output ===
            if output_format == "json":
                if clinical_trials_task:
                    clinical_trials_task.cancel()
                return _format_as_json(ranked, analysis, stats, relaxation_result, deep_search_metrics)
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
