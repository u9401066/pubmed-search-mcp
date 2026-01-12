"""
Unified Search Tool - Single Entry Point for Multi-Source Academic Search

This is the MVP of the Unified Search Gateway (Phase 2.0).

Design Philosophy:
    單一入口 + 後端自動分流（像 Google 一樣）
    
    Old way (Agent must choose):
        search_literature() / search_europe_pmc() / search_core() / ...
    
    New way (Single entry point):
        unified_search(query) → Auto-dispatch to best sources

Architecture:
    User Query
         │
         ▼
    ┌──────────────────┐
    │  QueryAnalyzer   │  ← Determines complexity, detects PICO
    └────────┬─────────┘
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
    │ ResultAggregator │  ← Dedup + Multi-dimensional ranking
    └────────┬─────────┘
             │
             ▼
      UnifiedArticle[]

Features:
    - Automatic query analysis (complexity, intent, PICO)
    - Smart source selection based on query characteristics
    - Multi-source parallel search with deduplication
    - Configurable ranking (impact/recency/quality focused)
    - Transparent operation with analysis metadata
"""

import json
import logging
from typing import Literal, Union

from mcp.server.fastmcp import FastMCP

from ...entrez import LiteratureSearcher
from ...unified.query_analyzer import QueryAnalyzer, QueryComplexity, QueryIntent, AnalyzedQuery
from ...unified.result_aggregator import (
    ResultAggregator, 
    RankingConfig, 
    AggregationStats,
)
from ...models.unified_article import UnifiedArticle
from ...sources import (
    search_alternate_source,
    get_crossref_client,
    get_unpaywall_client,
)
from ...sources.openurl import get_openurl_link, get_openurl_config
from ._common import InputNormalizer, ResponseFormatter

logger = logging.getLogger(__name__)


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
        if analysis.complexity == QueryComplexity.COMPLEX:
            return True
        return False


# ============================================================================
# Source Search Functions
# ============================================================================

def _search_pubmed(
    searcher: LiteratureSearcher,
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
) -> list[UnifiedArticle]:
    """Search PubMed and convert to UnifiedArticle."""
    try:
        results = searcher.search(
            query=query,
            limit=limit,
            min_year=min_year,
            max_year=max_year,
        )
        
        articles = []
        for r in results:
            articles.append(UnifiedArticle.from_pubmed(r))
        
        return articles
    except Exception as e:
        logger.error(f"PubMed search failed: {e}")
        return []


def _search_openalex(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
) -> list[UnifiedArticle]:
    """Search OpenAlex and convert to UnifiedArticle."""
    try:
        results = search_alternate_source(
            query=query,
            source="openalex",
            limit=limit,
            min_year=min_year,
            max_year=max_year,
        )
        
        articles = []
        for r in results:
            articles.append(UnifiedArticle.from_openalex(r))
        
        return articles
    except Exception as e:
        logger.error(f"OpenAlex search failed: {e}")
        return []


def _search_semantic_scholar(
    query: str,
    limit: int,
    min_year: int | None,
    max_year: int | None,
) -> list[UnifiedArticle]:
    """Search Semantic Scholar and convert to UnifiedArticle."""
    try:
        results = search_alternate_source(
            query=query,
            source="semantic_scholar",
            limit=limit,
            min_year=min_year,
            max_year=max_year,
        )
        
        articles = []
        for r in results:
            articles.append(UnifiedArticle.from_semantic_scholar(r))
        
        return articles
    except Exception as e:
        logger.error(f"Semantic Scholar search failed: {e}")
        return []


def _enrich_with_crossref(articles: list[UnifiedArticle]) -> None:
    """Enrich articles with CrossRef metadata (in-place)."""
    try:
        client = get_crossref_client()
        for article in articles:
            if article.doi and not article.citation_metrics:
                work = client.get_work(article.doi)
                if work:
                    crossref_article = UnifiedArticle.from_crossref(work)
                    article.merge_from(crossref_article)
    except Exception as e:
        logger.warning(f"CrossRef enrichment failed: {e}")


def _enrich_with_unpaywall(articles: list[UnifiedArticle]) -> None:
    """Enrich articles with Unpaywall OA links (in-place)."""
    try:
        client = get_unpaywall_client()
        for article in articles:
            if article.doi and not article.has_open_access:
                oa_info = client.enrich_article(article.doi)
                if oa_info.get("is_oa"):
                    from ...models.unified_article import OpenAccessLink, OpenAccessStatus
                    article.is_open_access = True
                    
                    # Map OA status
                    status_map = {
                        "gold": OpenAccessStatus.GOLD,
                        "green": OpenAccessStatus.GREEN,
                        "hybrid": OpenAccessStatus.HYBRID,
                        "bronze": OpenAccessStatus.BRONZE,
                    }
                    article.oa_status = status_map.get(
                        oa_info.get("oa_status", "unknown"),
                        OpenAccessStatus.UNKNOWN
                    )
                    
                    # Add OA links
                    for link_data in oa_info.get("oa_links", []):
                        if link_data.get("url"):
                            article.oa_links.append(OpenAccessLink(
                                url=link_data["url"],
                                version=link_data.get("version", "unknown"),
                                host_type=link_data.get("host_type"),
                                license=link_data.get("license"),
                                is_best=link_data.get("is_best", False),
                            ))
    except Exception as e:
        logger.warning(f"Unpaywall enrichment failed: {e}")


# ============================================================================
# Result Formatting
# ============================================================================

def _format_unified_results(
    articles: list[UnifiedArticle],
    analysis: AnalyzedQuery,
    stats: AggregationStats,
    include_analysis: bool = True,
) -> str:
    """Format unified search results for MCP response."""
    output_parts = []
    
    # Header with analysis summary
    if include_analysis:
        output_parts.append("## 🔍 Unified Search Results\n")
        output_parts.append(f"**Query**: {analysis.original_query}")
        output_parts.append(f"**Analysis**: {analysis.complexity.value} complexity, {analysis.intent.value} intent")
        if analysis.pico:
            pico_str = ", ".join(f"{k}={v}" for k, v in analysis.pico.to_dict().items() if v)
            output_parts.append(f"**PICO**: {pico_str}")
        output_parts.append(f"**Sources**: {', '.join(stats.by_source.keys())}")
        output_parts.append(f"**Results**: {stats.unique_articles} unique ({stats.duplicates_removed} duplicates removed)")
        output_parts.append("")
    
    # Articles
    if not articles:
        output_parts.append("No results found.")
        return "\n".join(output_parts)
    
    output_parts.append("---\n")
    
    for i, article in enumerate(articles, 1):
        # Article header
        score_str = f" (score: {article._ranking_score:.2f})" if article._ranking_score else ""
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
            openurl = get_openurl_link({
                "pmid": article.pmid,
                "doi": article.doi,
                "title": article.title,
                "journal": article.journal,
                "year": article.year,
                "volume": article.volume,
                "issue": article.issue,
                "pages": article.pages,
            })
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
    
    return "\n".join(output_parts)


def _format_as_json(
    articles: list[UnifiedArticle],
    analysis: AnalyzedQuery,
    stats: AggregationStats,
) -> str:
    """Format results as JSON for programmatic access."""
    return json.dumps({
        "analysis": analysis.to_dict(),
        "statistics": stats.to_dict(),
        "articles": [a.to_dict() for a in articles],
    }, ensure_ascii=False, indent=2)


# ============================================================================
# MCP Tool Registration
# ============================================================================

def register_unified_search_tools(mcp: FastMCP, searcher: LiteratureSearcher):
    """Register unified search MCP tools."""
    
    @mcp.tool()
    def unified_search(
        query: str,
        limit: Union[int, str] = 10,
        min_year: Union[int, str, None] = None,
        max_year: Union[int, str, None] = None,
        ranking: Literal["balanced", "impact", "recency", "quality"] = "balanced",
        output_format: Literal["markdown", "json"] = "markdown",
        include_oa_links: Union[bool, str] = True,
        show_analysis: Union[bool, str] = True,
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
        
        Args:
            query: Your search query (natural language or structured)
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
        
        Returns:
            Formatted search results with:
            - Query analysis (complexity, intent, PICO)
            - Search statistics (sources, dedup count)
            - Ranked articles with metadata
            - Open access links where available
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
                    tool_name="unified_search"
                )
            
            limit = InputNormalizer.normalize_limit(limit, default=10, max_val=100)
            min_year = InputNormalizer.normalize_year(min_year)
            max_year = InputNormalizer.normalize_year(max_year)
            include_oa_links = InputNormalizer.normalize_bool(include_oa_links, default=True)
            show_analysis = InputNormalizer.normalize_bool(show_analysis, default=True)
            
            # === Step 1: Analyze Query ===
            analyzer = QueryAnalyzer()
            analysis = analyzer.analyze(query)
            
            logger.info(f"Query analysis: complexity={analysis.complexity.value}, intent={analysis.intent.value}")
            
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
            
            # === Step 4: Search Each Source ===
            all_results: list[list[UnifiedArticle]] = []
            
            for source in sources:
                if source == "pubmed":
                    results = _search_pubmed(
                        searcher, query, limit,
                        min_year or analysis.year_from,
                        max_year or analysis.year_to,
                    )
                    all_results.append(results)
                    logger.info(f"PubMed: {len(results)} results")
                
                elif source == "openalex":
                    results = _search_openalex(
                        query, limit,
                        min_year or analysis.year_from,
                        max_year or analysis.year_to,
                    )
                    all_results.append(results)
                    logger.info(f"OpenAlex: {len(results)} results")
                
                elif source == "semantic_scholar":
                    results = _search_semantic_scholar(
                        query, limit,
                        min_year or analysis.year_from,
                        max_year or analysis.year_to,
                    )
                    all_results.append(results)
                    logger.info(f"Semantic Scholar: {len(results)} results")
                
                elif source == "crossref":
                    # CrossRef is used for enrichment, not primary search
                    pass
            
            # === Step 5: Aggregate and Deduplicate ===
            aggregator = ResultAggregator(config)
            articles, stats = aggregator.aggregate(all_results)
            
            logger.info(f"Aggregation: {stats.unique_articles} unique from {stats.total_input} total")
            
            # === Step 6: Enrich with CrossRef (if in sources) ===
            if "crossref" in sources:
                _enrich_with_crossref(articles)
            
            # === Step 7: Enrich with Unpaywall OA Links ===
            if include_oa_links and DispatchStrategy.should_enrich_with_unpaywall(analysis):
                _enrich_with_unpaywall(articles)
            
            # === Step 8: Rank Results ===
            ranked = aggregator.rank(articles, config, query)
            
            # Apply limit
            if limit and len(ranked) > limit:
                ranked = ranked[:limit]
            
            # === Step 9: Format Output ===
            if output_format == "json":
                return _format_as_json(ranked, analysis, stats)
            else:
                return _format_unified_results(ranked, analysis, stats, show_analysis)
        
        except Exception as e:
            logger.error(f"Unified search failed: {e}", exc_info=True)
            return f"Error: Unified search failed - {str(e)}"
    
    @mcp.tool()
    def analyze_search_query(query: str) -> str:
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
                tool_name="analyze_search_query"
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
            
            output.extend([
                "\n### Dispatch Strategy",
                f"- **Sources**: {' → '.join(sources)}",
                f"- **Ranking**: {config.normalized_weights()}",
                f"- **OA Enrichment**: {'Yes' if enrich_oa else 'No'}",
            ])
            
            return "\n".join(output)
        
        except Exception as e:
            logger.error(f"Query analysis failed: {e}")
            return f"Error: Query analysis failed - {str(e)}"
