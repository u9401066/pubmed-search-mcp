"""
Unified Search — Result Formatting Module.

Contains functions that format UnifiedArticle results into human-readable
Markdown or machine-readable JSON output.

Extracted from unified.py to keep each module under 400 lines.
"""

from __future__ import annotations

import json
import logging

from pubmed_search.application.search.query_analyzer import AnalyzedQuery
from pubmed_search.application.search.result_aggregator import AggregationStats
from pubmed_search.domain.entities.article import UnifiedArticle
from pubmed_search.infrastructure.sources.openurl import (
    get_openurl_config,
    get_openurl_link,
)

from .unified_helpers import (
    RelaxationResult,
    SearchDepthMetrics,
)

logger = logging.getLogger(__name__)


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
    source_api_counts: dict[str, tuple[int, int | None]] | None = None,
) -> str:
    """Format unified search results for MCP response.

    Args:
        source_api_counts: Per-source raw API counts {source: (returned, total_available)}.
            - returned: how many articles the API actually returned to us
            - total_available: how many total matches the API reports (None if unknown)
    """
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

        # Per-source result counts (critical for agent decision-making)
        if source_api_counts:
            # Show detailed per-source API return counts
            source_parts = []
            for src, (returned, total) in source_api_counts.items():
                if total is not None and total > returned:
                    source_parts.append(f"{src} ({returned}/{total})")
                else:
                    source_parts.append(f"{src} ({returned})")
            output_parts.append(f"**Sources**: {', '.join(source_parts)}")
        elif stats.by_source:
            # Fallback: use aggregation stats (pre-dedup per-source counts)
            source_parts = [f"{src} ({count})" for src, count in stats.by_source.items()]
            output_parts.append(f"**Sources**: {', '.join(source_parts)}")

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
