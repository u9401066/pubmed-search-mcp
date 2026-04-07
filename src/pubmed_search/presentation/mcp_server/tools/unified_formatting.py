"""
Unified Search — Result Formatting Module.

Contains functions that format UnifiedArticle results into human-readable
Markdown or machine-readable JSON output.

Extracted from unified.py to keep each module under 400 lines.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal, cast

from pubmed_search.infrastructure.sources.openurl import (
    get_openurl_config,
    get_openurl_link,
)

from .agent_output import (
    OutputFormat,
    SourceCountRow,
    finalize_next_tools,
    make_next_tool,
    make_section_provenance,
    make_source_count_row,
    preferred_structured_output_format,
    serialize_structured_payload,
    sort_source_count_rows,
)

if TYPE_CHECKING:
    from pubmed_search.application.search.query_analyzer import AnalyzedQuery
    from pubmed_search.application.search.ranking_algorithms import SourceDisagreement
    from pubmed_search.application.search.reproducibility import ReproducibilityScore
    from pubmed_search.application.search.result_aggregator import AggregationStats
    from pubmed_search.domain.entities.article import UnifiedArticle

    from .unified_helpers import RelaxationResult, SearchDepthMetrics

logger = logging.getLogger(__name__)


def _serialize_source_counts(
    source_api_counts: dict[str, tuple[int, int | None]] | None,
    stats: AggregationStats,
) -> list[SourceCountRow]:
    """Normalize source counts into a common structure for markdown and JSON output."""
    by_source = getattr(stats, "by_source", {}) or {}

    if source_api_counts:
        rows: list[SourceCountRow] = [
            make_source_count_row(source, returned, total) for source, (returned, total) in source_api_counts.items()
        ]
    else:
        rows = [make_source_count_row(source, count) for source, count in by_source.items()]

    return sort_source_count_rows(rows)


def _escape_tool_argument(value: str) -> str:
    """Escape a value for display inside example MCP tool calls."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _build_next_actions(
    articles: list[UnifiedArticle],
    analysis: AnalyzedQuery,
    source_rows: list[SourceCountRow],
    research_context_preview: str | None,
    structured_output_format: Literal["json", "toon"] = "json",
) -> list[dict[str, str]]:
    """Infer pragmatic next-tool suggestions from current result shape."""
    escaped_query = _escape_tool_argument(analysis.original_query)
    next_actions: list[dict[str, str]] = []
    seen_tools: set[str] = set()

    def add_action(tool: str, reason: str, example: str) -> None:
        if tool in seen_tools or len(next_actions) >= 4:
            return
        next_actions.append(cast("dict[str, str]", dict(make_next_tool(tool, reason, example))))
        seen_tools.add(tool)

    if source_rows:
        high_yield = next(
            (
                row
                for row in source_rows
                if row["total_available"] is not None and row["total_available"] > row["returned"]
            ),
            None,
        )
        if high_yield:
            source_name = str(high_yield["source"])
            current_returned = int(high_yield["returned"] or 0)
            expanded_limit = max(min(current_returned * 2, 50), 20)
            add_action(
                "unified_search",
                f"{source_name} reports more matches than were sampled here; expand the highest-yield source before pivoting.",
                (
                    f'unified_search(query="{escaped_query}", sources="{source_name}", '
                    f'limit={expanded_limit}, options="counts_first", output_format="{structured_output_format}")'
                ),
            )

    intent_value = getattr(analysis.intent, "value", "")
    if intent_value in {"comparison", "systematic"}:
        add_action(
            "generate_search_queries",
            "This query looks like a comparison or review question; generate controlled-vocabulary variants before broadening the search.",
            f'generate_search_queries(topic="{escaped_query}")',
        )

    lead_article = next(
        (article for article in articles if getattr(article, "pmid", None) or getattr(article, "pmc", None)), None
    )
    if lead_article and getattr(lead_article, "pmid", None):
        lead_pmid = str(lead_article.pmid)
        add_action(
            "fetch_article_details",
            "Inspect the lead PubMed record in detail before deciding whether to branch, export, or fetch fulltext.",
            f'fetch_article_details(pmids="{lead_pmid}", output_format="{structured_output_format}")',
        )
        add_action(
            "find_related_articles",
            "Follow the strongest seed article into its related-paper neighborhood.",
            f'find_related_articles(pmid="{lead_pmid}", limit=10)',
        )

    if lead_article and getattr(lead_article, "pmc", None):
        lead_pmc = str(lead_article.pmc)
        add_action(
            "get_article_figures",
            "A PMC-backed result is available; extract figures first when the next decision depends on evidence visuals.",
            f'get_article_figures(identifier="{lead_pmc}", output_format="{structured_output_format}")',
        )
        add_action(
            "get_fulltext",
            "Retrieve structured fulltext with inline figures from the PMC-backed lead article.",
            (f'get_fulltext(pmcid="{lead_pmc}", include_figures=True, output_format="{structured_output_format}")'),
        )

    if articles and not research_context_preview and any(getattr(article, "pmid", None) for article in articles):
        add_action(
            "build_research_timeline",
            "You have PMID-backed results; build a lineage view before moving to export or citation chasing.",
            f'build_research_timeline(pmids="last", topic="{escaped_query}", output_format="tree")',
        )

    if len(articles) >= 5:
        add_action(
            "prepare_export",
            "Export the current result set once you have enough candidates to shortlist offline.",
            'prepare_export(pmids="last", format="ris")',
        )

    if not next_actions:
        add_action(
            "generate_search_queries",
            "No obvious downstream pivot was detected; start by expanding controlled vocabulary and synonyms.",
            f'generate_search_queries(topic="{escaped_query}")',
        )

    return next_actions


def _build_unified_section_provenance(
    source_rows: list[SourceCountRow],
    *,
    include_research_context: bool,
    include_deep_search: bool,
    include_relaxation: bool,
    include_source_disagreement: bool,
    include_reproducibility: bool,
) -> dict[str, dict[str, object]]:
    """Describe where each JSON section came from for agent chaining."""
    upstream_sources = [str(row["source"]) for row in source_rows]
    provenance = {
        "analysis": make_section_provenance(
            surfacing_source="pubmed-search-mcp",
            canonical_host="pubmed-search-mcp",
            provenance="derived",
            note="Query analysis is computed locally from the incoming request.",
        ),
        "statistics": make_section_provenance(
            surfacing_source="pubmed-search-mcp",
            canonical_host="pubmed-search-mcp",
            provenance="derived",
            note="Aggregate statistics are computed after cross-source deduplication and ranking.",
            upstream_sources=upstream_sources,
        ),
        "source_counts": make_section_provenance(
            surfacing_source="pubmed-search-mcp",
            canonical_host=None,
            provenance="derived",
            note="Counts are normalized from upstream API responses; see upstream_sources for contributing corpora.",
            upstream_sources=upstream_sources,
        ),
        "articles": make_section_provenance(
            surfacing_source="pubmed-search-mcp",
            canonical_host=None,
            provenance="mixed",
            note="Ranked articles are aggregated across multiple sources; inspect each article.sources entry for record-level provenance.",
            upstream_sources=upstream_sources,
        ),
        "next_tools": make_section_provenance(
            surfacing_source="pubmed-search-mcp",
            canonical_host="pubmed-search-mcp",
            provenance="derived",
            note="Next-tool suggestions are inferred locally from the result shape and available identifiers.",
        ),
    }

    if include_deep_search:
        provenance["deep_search"] = make_section_provenance(
            surfacing_source="pubmed-search-mcp",
            canonical_host="pubmed-search-mcp",
            provenance="derived",
            note="Deep-search metrics summarize locally executed semantic expansion strategies.",
            upstream_sources=upstream_sources,
        )
    if include_relaxation:
        provenance["relaxation"] = make_section_provenance(
            surfacing_source="pubmed-search-mcp",
            canonical_host="pubmed-search-mcp",
            provenance="derived",
            note="Relaxation history is generated locally from automatic fallback steps.",
        )
    if include_source_disagreement:
        provenance["source_disagreement"] = make_section_provenance(
            surfacing_source="pubmed-search-mcp",
            canonical_host="pubmed-search-mcp",
            provenance="derived",
            note="Agreement metrics are computed from the cross-source overlap of the ranked result set.",
            upstream_sources=upstream_sources,
        )
    if include_reproducibility:
        provenance["reproducibility"] = make_section_provenance(
            surfacing_source="pubmed-search-mcp",
            canonical_host="pubmed-search-mcp",
            provenance="derived",
            note="Reproducibility grades are computed locally from query formality, coverage, and failure signals.",
            upstream_sources=upstream_sources,
        )
    if include_research_context:
        provenance["research_context"] = make_section_provenance(
            surfacing_source="pubmed-search-mcp",
            canonical_host="pubmed-search-mcp",
            provenance="derived",
            note="Research context is synthesized locally from PMID-backed timeline and tree builders.",
        )

    return provenance


def _format_counts_first_section(
    source_rows: list[SourceCountRow],
    stats: AggregationStats,
    next_actions: list[dict[str, str]],
) -> list[str]:
    """Render the counts-first orientation block for markdown output."""
    output_parts = ["### 📊 Count-First Orientation\n"]
    output_parts.append("| Source | Returned | Total Known | Signal |")
    output_parts.append("| --- | ---: | ---: | --- |")

    for row in source_rows:
        total = row["total_available"] if row["total_available"] is not None else "?"
        signal = "backlog" if row["has_more"] else "sampled"
        output_parts.append(f"| {row['source']} | {row['returned']} | {total} | {signal} |")

    responded = sum(1 for row in source_rows if int(row["returned"] or 0) > 0)
    output_parts.append("")
    output_parts.append(
        f"**Coverage**: {responded}/{len(source_rows)} sources returned results | "
        f"{stats.unique_articles} unique articles | {stats.duplicates_removed} duplicates removed"
    )

    if next_actions:
        output_parts.append("")
        output_parts.append("### ⏭️ Next Tools\n")
        for action in next_actions:
            output_parts.append(f"- **{action['tool']}**: {action['reason']} Example: `{action['example']}`")
        output_parts.append("")

    return output_parts


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
    source_disagreement: SourceDisagreement | None = None,
    reproducibility_score: ReproducibilityScore | None = None,
    research_context_preview: str | None = None,
    counts_first: bool = False,
) -> str:
    """Format unified search results for MCP response.

    Args:
        source_api_counts: Per-source raw API counts {source: (returned, total_available)}.
            - returned: how many articles the API actually returned to us
            - total_available: how many total matches the API reports (None if unknown)
    """
    output_parts: list[str] = []
    source_rows = _serialize_source_counts(source_api_counts, stats)
    next_actions = _build_next_actions(articles, analysis, source_rows, research_context_preview)

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
        if not counts_first and source_api_counts:
            # Show detailed per-source API return counts
            source_parts = []
            for row in source_rows:
                src = str(row["source"])
                returned = int(row["returned"] or 0)
                total = row["total_available"]
                if total is not None and total > returned:
                    source_parts.append(f"{src} ({returned}/{total})")
                else:
                    source_parts.append(f"{src} ({returned})")
            output_parts.append(f"**Sources**: {', '.join(source_parts)}")
        elif not counts_first and stats.by_source:
            # Fallback: use aggregation stats (pre-dedup per-source counts)
            source_parts = [f"{row['source']} ({row['returned']})" for row in source_rows]
            output_parts.append(f"**Sources**: {', '.join(source_parts)}")

        # Show total count info with PubMed total
        results_str = f"{stats.unique_articles} unique ({stats.duplicates_removed} duplicates removed)"
        if pubmed_total_count is not None and pubmed_total_count > stats.unique_articles:
            results_str = f"📊 返回 **{stats.unique_articles}** 篇 (PubMed 總共 **{pubmed_total_count}** 篇符合) | {stats.duplicates_removed} 去重"
        output_parts.append(f"**Results**: {results_str}")
        output_parts.append("")

    if counts_first and source_rows:
        output_parts.extend(_format_counts_first_section(source_rows, stats, next_actions))

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

    # === Source Disagreement Analysis Section ===
    if source_disagreement and len(source_disagreement.per_source_unique) > 1:
        output_parts.append("\n---")
        output_parts.append("\n## 📊 Source Agreement Analysis\n")
        sas = source_disagreement.source_agreement_score
        sas_label = "High" if sas >= 0.7 else ("Moderate" if sas >= 0.4 else "Low")
        output_parts.append(f"**Source Agreement Score (SAS)**: {sas:.2f} ({sas_label})")
        output_parts.append(
            f"**Complementarity**: {source_disagreement.source_complementarity:.0%} "
            f"({source_disagreement.single_source_articles} single-source / "
            f"{source_disagreement.cross_source_articles} cross-source)"
        )
        if source_disagreement.per_source_unique:
            unique_parts = [f"{src}: {cnt}" for src, cnt in source_disagreement.per_source_unique.items() if cnt > 0]
            if unique_parts:
                output_parts.append(f"**Exclusive findings**: {', '.join(unique_parts)}")
        if source_disagreement.rank_correlation:
            corr_parts = [f"{pair}: {val:.2f}" for pair, val in source_disagreement.rank_correlation.items()]
            output_parts.append(f"**Pairwise overlap**: {', '.join(corr_parts)}")
        output_parts.append("")

    # === Reproducibility Score Section ===
    if reproducibility_score:
        output_parts.append("\n---")
        output_parts.append("\n## 🔄 Reproducibility Score\n")
        rs = reproducibility_score
        output_parts.append(f"**Grade**: {rs.grade} ({rs.overall_score:.0%})")
        det_icon = "✅" if rs.deterministic else "⚠️"
        output_parts.append(
            f"| Component | Score |\n"
            f"|-----------|-------|\n"
            f"| {det_icon} Deterministic | {'Yes' if rs.deterministic else 'No (LLM/sampling)'} |\n"
            f"| Query Formality | {rs.query_formality:.0%} |\n"
            f"| Source Coverage | {rs.source_coverage:.0%} |\n"
            f"| Result Stability | {rs.result_stability:.0%} |\n"
            f"| Audit Completeness | {rs.audit_completeness:.0%} |"
        )
        if rs.sources_failed:
            output_parts.append(f"\n**⚠️ Failed sources**: {', '.join(rs.sources_failed)}")
        output_parts.append("")

    # === Research Context Graph Preview ===
    if research_context_preview:
        output_parts.append("\n---")
        output_parts.append("\n## 🌳 Research Context Graph\n")
        output_parts.append(
            "This preview is generated from PMID-backed results in the current ranked set. "
            "It shows thematic branches rather than the full cross-source knowledge graph."
        )
        output_parts.append("")
        output_parts.append(research_context_preview)
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
    source_api_counts: dict[str, tuple[int, int | None]] | None = None,
    source_disagreement: SourceDisagreement | None = None,
    reproducibility_score: ReproducibilityScore | None = None,
    research_context: dict | None = None,
    counts_first: bool = False,
    output_format: OutputFormat = "json",
) -> str:
    """Format results as JSON or TOON for programmatic access."""
    source_rows = _serialize_source_counts(source_api_counts, stats)
    structured_output_format = preferred_structured_output_format(output_format)
    next_actions = _build_next_actions(articles, analysis, source_rows, None, structured_output_format)
    next_tools, next_commands = finalize_next_tools(next_actions)
    result = {
        "tool": "unified_search",
        "analysis": analysis.to_dict(),
        "statistics": stats.to_dict(),
        "articles": [a.to_dict() for a in articles],
        "source_counts": source_rows,
        "next_tools": next_tools,
        "next_commands": next_commands,
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

    # Source disagreement analysis
    if source_disagreement:
        result["source_disagreement"] = source_disagreement.to_dict()

    # Reproducibility score
    if reproducibility_score:
        result["reproducibility"] = reproducibility_score.to_dict()

    if research_context:
        result["research_context"] = research_context

    if counts_first:
        result["orientation"] = {
            "mode": "counts_first",
            "source_counts": source_rows,
            "responded_sources": sum(1 for row in source_rows if int(row["returned"] or 0) > 0),
            "queried_sources": len(source_rows),
            "next_actions": next_actions,
            "next_tools": next_tools,
            "next_commands": next_commands,
        }

    result["section_provenance"] = _build_unified_section_provenance(
        source_rows,
        include_research_context=research_context is not None,
        include_deep_search=deep_search_metrics is not None,
        include_relaxation=relaxation_result is not None,
        include_source_disagreement=source_disagreement is not None,
        include_reproducibility=reproducibility_score is not None,
    )

    return serialize_structured_payload(result, output_format)
