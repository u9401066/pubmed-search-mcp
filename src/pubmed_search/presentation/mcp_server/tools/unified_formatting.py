"""
Unified Search — Result Formatting Module.

Contains functions that format UnifiedArticle results into human-readable
Markdown or machine-readable JSON output.

Extracted from unified.py to keep each module under 400 lines.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Literal, cast

from pubmed_search.application.unified.clinical_trials import (
    ClinicalTrialsCoverage,
    ClinicalTrialsFormatError,
    clinical_trials_error_payload,
)
from pubmed_search.infrastructure.sources.openurl import (
    get_openurl_config,
    get_openurl_link,
)
from pubmed_search.shared.markdown import escape_markdown_text as _escape_markdown_text
from pubmed_search.shared.markdown import safe_markdown_url as _safe_markdown_url

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
    from collections.abc import Mapping, Sequence

    from pubmed_search.application.search.query_analyzer import AnalyzedQuery
    from pubmed_search.application.search.ranking_algorithms import SourceDisagreement
    from pubmed_search.application.search.reproducibility import ReproducibilityScore
    from pubmed_search.application.search.result_aggregator import AggregationStats
    from pubmed_search.application.unified.helpers import RelaxationResult, SearchDepthMetrics
    from pubmed_search.domain.entities.article import UnifiedArticle

logger = logging.getLogger(__name__)
DEFAULT_STRUCTURED_RESPONSE_MAX_CHARS = 500_000
TINY_STRUCTURED_RESPONSE_CAP_CHARS = 100
PRETRUNCATE_STRUCTURED_RESPONSE_CAP_CHARS = 1_000
_TOOL_ARGUMENT_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


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


def _format_source_warnings(source_errors: list[dict[str, Any]] | None) -> str | None:
    """Render source-level partial failure diagnostics for markdown responses."""
    if not source_errors:
        return None

    warning_parts = []
    for error in source_errors:
        source = _escape_markdown_text(error.get("source", "unknown"))
        status = _escape_markdown_text(error.get("status") or error.get("kind") or "error")
        status_code = error.get("status_code")
        suggestion = error.get("suggestion")
        message = f"{source} {status}"
        if status_code:
            message += f" (HTTP {status_code})"
        if suggestion:
            message += f": {_escape_markdown_text(suggestion)}"
        warning_parts.append(message)
    return f"**Source warnings**: {'; '.join(warning_parts)}"


def _format_clinical_trials_coverage(coverage: ClinicalTrialsCoverage | None) -> str | None:
    """Render a concise adjunct outcome that distinguishes empty from failure."""
    if coverage is None or not coverage.requested:
        return None
    status = coverage.status
    if status == "complete":
        outcome = f"complete; {coverage.returned} related trial(s)"
    elif status == "empty":
        outcome = "complete; 0 related trials"
    elif status == "timeout":
        outcome = "incomplete; request timed out"
    elif status == "format_error":
        outcome = f"incomplete; {coverage.returned} trial(s) retrieved but rendering failed"
    elif status == "pending":
        outcome = "incomplete; request did not finish"
    else:
        outcome = "incomplete; request failed"
    return f"**ClinicalTrials.gov adjunct**: {outcome}"


def _prepare_clinical_trials_section(
    *,
    include_trials: bool,
    prefetched_trials: list[dict[str, Any]] | None,
    coverage: ClinicalTrialsCoverage | None,
    source_errors: list[dict[str, Any]],
) -> str:
    """Render prevalidated trials and surface any formatting failure."""
    if not include_trials or coverage is None or coverage.retrieval_status != "complete":
        return ""

    def _validated_section(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ClinicalTrialsFormatError
        return value

    try:
        from pubmed_search.infrastructure.sources.clinical_trials import format_trials_section

        section = _validated_section(format_trials_section(list(prefetched_trials or []), max_display=3))
        coverage.record_format_success()
        return section
    except Exception as exc:
        coverage.record_format_failure(exc)
        error_payload = clinical_trials_error_payload(coverage)
        if error_payload is not None and error_payload not in source_errors:
            source_errors.append(error_payload)
        logger.debug("Clinical trials rendering failed (%s)", type(exc).__name__)
        return ""


def _escape_tool_argument(value: str) -> str:
    """Escape a value for display inside example MCP tool calls."""
    normalized = _TOOL_ARGUMENT_CONTROL_RE.sub(" ", value).replace("\r\n", "\n").replace("\r", "\n")
    escaped = normalized.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\u0060")
    return escaped.replace("\n", "\\n")


def _build_next_actions(
    articles: list[UnifiedArticle],
    analysis: AnalyzedQuery,
    source_rows: list[SourceCountRow],
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
            "save_literature_notes",
            "Persist the current PMID-backed result set as local LLM wiki notes with stable Foam-compatible links.",
            'save_literature_notes(pmids="last", note_format="wiki")',
        )

    if lead_article and getattr(lead_article, "pmc", None):
        lead_pmc = str(lead_article.pmc)
        add_action(
            "get_article_figures",
            "A PMC-backed result is available; extract figures first when the next decision depends on evidence visuals.",
            (
                f'get_article_figures(source={{"kind":"pmcid","value":"{lead_pmc}"}}, '
                f'output_format="{structured_output_format}")'
            ),
        )
        add_action(
            "get_fulltext",
            "Retrieve structured fulltext with inline figures from the PMC-backed lead article.",
            (
                f'get_fulltext(source={{"kind":"pmcid","value":"{lead_pmc}"}}, include_figures=True, '
                f'output_format="{structured_output_format}")'
            ),
        )

    if lead_article and getattr(lead_article, "pmid", None):
        lead_pmid = str(lead_article.pmid)
        add_action(
            "find_related_articles",
            "Follow the strongest seed article into its related-paper neighborhood.",
            f'find_related_articles(pmid="{lead_pmid}", limit=10)',
        )

    if articles and any(getattr(article, "pmid", None) for article in articles):
        add_action(
            "build_research_chronicle",
            "You have PMID-backed results; build a persistent chronicle before moving to export or citation chasing.",
            f'build_research_chronicle(pmids="last", topic="{escaped_query}")',
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
        signal = "unknown" if row["has_more"] is None else "backlog" if row["has_more"] else "sampled"
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


def _relaxation_step_status_text(step: Any) -> str:
    """Render an attempt without treating provider failure as zero results."""
    if step.status == "ok":
        return f"✅ {step.result_count} results"
    if step.status == "empty":
        return "❌ 0 results"
    if step.status == "error":
        kind = getattr(step.error, "kind", "unexpected")
        return f"⚠️ request failed ({_escape_markdown_text(kind)})"
    return "⚠️ not completed"


def _relaxation_step_payload(step: Any) -> dict[str, Any]:
    """Serialize one relaxation attempt with bounded failure provenance."""
    payload: dict[str, Any] = {
        "level": step.level,
        "action": step.action,
        "description": step.description,
        "query": step.query,
        "result_count": step.result_count,
        "status": step.status,
    }
    if step.error is not None:
        payload["error"] = {
            "kind": step.error.kind,
            "message": step.error.message,
            "retryable": step.error.retryable,
            "status_code": step.error.status_code,
        }
    return payload


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
    include_trials: bool = True,
    include_rank_scores: bool = True,
    original_query: str = "",
    enhanced_entities: list[str] | None = None,
    relaxation_result: RelaxationResult | None = None,
    deep_search_metrics: SearchDepthMetrics | None = None,
    prefetched_trials: list[dict[str, Any]] | None = None,
    clinical_trials_coverage: ClinicalTrialsCoverage | None = None,
    source_api_counts: dict[str, tuple[int, int | None]] | None = None,
    source_disagreement: SourceDisagreement | None = None,
    reproducibility_score: ReproducibilityScore | None = None,
    source_errors: list[dict[str, Any]] | None = None,
    source_metadata: dict[str, dict[str, Any]] | None = None,
    enrichment_metadata: dict[str, Any] | None = None,
    counts_first: bool = False,
    result_filter_counts: Mapping[str, int] | None = None,
) -> str:
    """Format unified search results for MCP response.

    Args:
        source_api_counts: Per-source raw API counts {source: (returned, total_available)}.
            - returned: how many articles the API actually returned to us
            - total_available: how many total matches the API reports (None if unknown)
    """
    output_parts: list[str] = []
    mutable_source_errors = source_errors if source_errors is not None else []
    clinical_trials_section = _prepare_clinical_trials_section(
        include_trials=include_trials,
        prefetched_trials=prefetched_trials,
        coverage=clinical_trials_coverage,
        source_errors=mutable_source_errors,
    )
    source_rows = _serialize_source_counts(source_api_counts, stats)
    next_actions = _build_next_actions(articles, analysis, source_rows)

    # Header with analysis summary
    if include_analysis:
        output_parts.append("## 🔍 Unified Search Results\n")
        output_parts.append(f"**Query**: {_escape_markdown_text(analysis.original_query)}")
        output_parts.append(f"**Analysis**: {analysis.complexity.value} complexity, {analysis.intent.value} intent")
        if analysis.pico:
            pico_str = ", ".join(
                f"{_escape_markdown_text(k)}={_escape_markdown_text(v)}"
                for k, v in analysis.pico.to_dict().items()
                if v
            )
            output_parts.append(f"**PICO**: {pico_str}")

        # ICD code expansion info
        if icd_matches:
            icd_info = ", ".join(
                f"{_escape_markdown_text(m['code'])}→{_escape_markdown_text(m['mesh'])}" for m in icd_matches
            )
            output_parts.append(f"**ICD Expansion**: {icd_info}")

        # Phase 3: Show PubTator3 resolved entities
        if enhanced_entities:
            entity_str = ", ".join(_escape_markdown_text(entity) for entity in enhanced_entities[:5])  # Show max 5
            if len(enhanced_entities) > 5:
                entity_str += f" (+{len(enhanced_entities) - 5} more)"
            output_parts.append(f"**🧬 Entities**: {entity_str}")

        # Deep Search Metrics (if enabled)
        if deep_search_metrics:
            output_parts.append(
                f"**🔬 深度搜索**: "
                f"Depth Score {deep_search_metrics.depth_score:.0f}/100 | "
                f"{deep_search_metrics.strategies_executed}/{deep_search_metrics.strategies_generated} 策略執行 | "
                f"啟發式召回代理 {deep_search_metrics.heuristic_recall_proxy:.0%}（非已驗證 recall）"
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

        if source_metadata:
            modes = [
                f"{source}={metadata.get('provider_mode', 'default')}" for source, metadata in source_metadata.items()
            ]
            output_parts.append(f"**Retrieval modes**: {', '.join(modes)}")

        if enrichment_metadata:
            output_parts.append(
                "**Enrichment**: "
                f"{enrichment_metadata.get('status', 'not_requested')} | "
                f"attempted {int(enrichment_metadata.get('attempted', 0) or 0)}, "
                f"succeeded {int(enrichment_metadata.get('succeeded', 0) or 0)}, "
                f"skipped {int(enrichment_metadata.get('skipped', 0) or 0)}, "
                f"failed {int(enrichment_metadata.get('failed', 0) or 0)}"
            )

        # Show total count info with PubMed total
        returned_count = int((result_filter_counts or {}).get("returned", len(articles)))
        eligible_count = int((result_filter_counts or {}).get("eligible_unique", stats.unique_articles))
        excluded_count = int((result_filter_counts or {}).get("excluded_detected_preprints", 0))
        results_str = (
            f"{returned_count} returned from {eligible_count} eligible unique "
            f"({stats.duplicates_removed} duplicates removed)"
        )
        if pubmed_total_count is not None and pubmed_total_count > eligible_count:
            results_str += f"; PubMed reports {pubmed_total_count} total matches"
        if excluded_count:
            results_str += (
                f"; {excluded_count} detected preprints excluded by heuristic "
                "(remaining records are not thereby proven peer reviewed)"
            )
        output_parts.append(f"**Results**: {results_str}")
        output_parts.append("")

    source_warning_text = _format_source_warnings(mutable_source_errors)
    if source_warning_text:
        output_parts.append(source_warning_text)
        output_parts.append("")

    capability_warnings = [
        f"- **{_escape_markdown_text(source)}**: {_escape_markdown_text(warning)}"
        for source, metadata in (source_metadata or {}).items()
        for warning in metadata.get("warnings", [])
        if isinstance(warning, str) and warning
    ]
    if capability_warnings:
        output_parts.append("### ⚠️ Retrieval capability notes\n")
        output_parts.extend(capability_warnings)
        output_parts.append("")

    clinical_trials_coverage_text = _format_clinical_trials_coverage(clinical_trials_coverage)
    if clinical_trials_coverage_text:
        output_parts.append(clinical_trials_coverage_text)
        output_parts.append("")

    if counts_first and source_rows:
        output_parts.extend(_format_counts_first_section(source_rows, stats, next_actions))

    # Relaxation info (if auto-relaxation was triggered)
    if relaxation_result:
        if relaxation_result.successful_step:
            step = relaxation_result.successful_step
            output_parts.append("### ⚠️ 搜尋自動放寬 (Auto-Relaxed)\n")
            output_parts.append(
                f"原始查詢：{_escape_markdown_text(relaxation_result.original_query)}；返回 **0** 筆結果。"
            )
            output_parts.append(f"已自動放寬至 **Level {step.level}**: {_escape_markdown_text(step.description)}")
            output_parts.append(f"放寬後查詢：{_escape_markdown_text(relaxation_result.relaxed_query)}")

            # Show all attempted steps for transparency
            if len(relaxation_result.steps_tried) > 1:
                output_parts.append("\n**放寬嘗試過程** (由窄到寬):")
                for s in relaxation_result.steps_tried:
                    status = _relaxation_step_status_text(s)
                    output_parts.append(
                        f"  - Level {s.level} ({_escape_markdown_text(s.action)}): "
                        f"{_escape_markdown_text(s.description)} → {status}"
                    )
            output_parts.append("")
        else:
            output_parts.append("### ⚠️ 搜尋自動放寬未取得結果\n")
            output_parts.append(
                f"原始查詢：{_escape_markdown_text(relaxation_result.original_query)}；返回 **0** 筆結果。"
            )
            if relaxation_result.incomplete:
                output_parts.append("部分放寬請求失敗，因此無法宣稱所有較寬查詢皆為零結果；目前涵蓋範圍不完整。")
            else:
                output_parts.append("所有已規劃的放寬查詢均成功執行，且皆為零結果。")
            if relaxation_result.steps_tried:
                output_parts.append("\n**已嘗試:**")
                for s in relaxation_result.steps_tried:
                    output_parts.append(
                        f"  - Level {s.level}: {_escape_markdown_text(s.description)} → "
                        f"{_relaxation_step_status_text(s)}"
                    )
            output_parts.append("\n**建議:** 嘗試不同的搜尋詞，或使用 `generate_search_queries()` 取得 MeSH 同義詞。")
            output_parts.append("")

    # Articles
    if not articles:
        output_parts.append("No results found.")
        if clinical_trials_section:
            output_parts.append(clinical_trials_section)
        return "\n".join(output_parts)

    output_parts.append("---\n")

    for i, article in enumerate(articles, 1):
        # Article header
        score_str = (
            f" (ranking score: {article.ranking_score:.2f})" if include_rank_scores and article.ranking_score else ""
        )
        output_parts.append(f"### {i}. {_escape_markdown_text(article.title)}{score_str}")

        # Identifiers
        ids = []
        if article.pmid:
            ids.append(f"PMID: {_escape_markdown_text(article.pmid)}")
        if article.doi:
            ids.append(f"DOI: {_escape_markdown_text(article.doi)}")
        if article.pmc:
            ids.append(f"PMC: {_escape_markdown_text(article.pmc)}")
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
        output_parts.append(f"**Authors**: {_escape_markdown_text(article.author_string)}")
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
            output_parts.append(f"**Journal**: {_escape_markdown_text(journal_str)}")

        # Open Access status
        if article.has_open_access:
            oa_link = article.best_oa_link
            safe_oa_url = _safe_markdown_url(oa_link.url) if oa_link else None
            if safe_oa_url:
                output_parts.append(f"**OA**: ✅ [{_escape_markdown_text(article.oa_status.value)}]({safe_oa_url})")
            else:
                output_parts.append(f"**OA**: ✅ {_escape_markdown_text(article.oa_status.value)}")

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
            safe_openurl = _safe_markdown_url(openurl)
            if safe_openurl:
                output_parts.append(f"**Library**: 🏛️ [Find via Library]({safe_openurl})")

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

        if include_rank_scores and article.rank_percentile is not None:
            percentile = f"**Rank percentile**: {article.rank_percentile:.0%}"
            if article.rank_percentile_source:
                percentile += f" ({_escape_markdown_text(article.rank_percentile_source)})"
            output_parts.append(percentile)

        # Abstract (truncated)
        if article.abstract:
            abstract = article.abstract
            if len(abstract) > 300:
                abstract = abstract[:300] + "..."
            output_parts.append(f"\n&#8203;{_escape_markdown_text(abstract)}")

        # Sources
        sources = [_escape_markdown_text(s.source) for s in article.sources]
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
        if source_disagreement.pairwise_overlap:
            corr_parts = [f"{pair}: {val:.2f}" for pair, val in source_disagreement.pairwise_overlap.items()]
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

    # === Related Clinical Trials (use pre-fetched results) ===
    # Preprints are now first-class UnifiedArticle entries in the main results
    # list (article_type=PREPRINT); no separate section needed.

    if clinical_trials_section:
        output_parts.append(clinical_trials_section)

    return "\n".join(output_parts)


def _compact_article_payload(article: UnifiedArticle, *, include_rank_scores: bool = True) -> dict[str, Any]:
    """Build a small article preview for agent-facing structured output."""
    best_oa_link = article.best_oa_link
    publication_date = article.publication_date.isoformat() if article.publication_date else None
    payload: dict[str, Any] = {
        "title": article.title,
        "pmid": article.pmid,
        "doi": article.doi,
        "pmc": article.pmc,
        "journal": article.journal,
        "year": article.year,
        "publication_date": publication_date,
        "article_type": article.article_type.value,
        "open_access": article.has_open_access,
        "oa_status": article.oa_status.value,
        "pdf_available": bool(best_oa_link and best_oa_link.is_pdf),
        "pdf_url": best_oa_link.url if best_oa_link and best_oa_link.is_pdf else None,
    }
    if include_rank_scores:
        if article.ranking_score is not None:
            payload["ranking_score"] = round(article.ranking_score, 4)
        if article.rank_percentile is not None:
            payload["rank_percentile"] = round(article.rank_percentile, 4)
    return payload


def _article_payload(
    article: UnifiedArticle,
    *,
    compact_output: bool,
    include_rank_scores: bool,
) -> dict[str, Any]:
    if compact_output:
        return _compact_article_payload(article, include_rank_scores=include_rank_scores)

    payload = article.to_dict()
    if not include_rank_scores:
        payload.pop("_ranking_score", None)
        payload.pop("rank_percentile", None)
        payload.pop("rank_percentile_source", None)
        payload.pop("rank_percentile_details", None)
    return payload


def _should_pretruncate_structured_response(
    articles: list[UnifiedArticle],
    *,
    max_response_chars: int | None,
    compact_output: bool,
) -> bool:
    if max_response_chars is None:
        return False
    if max_response_chars <= TINY_STRUCTURED_RESPONSE_CAP_CHARS:
        return True
    return not compact_output and len(articles) > 3 and max_response_chars <= PRETRUNCATE_STRUCTURED_RESPONSE_CAP_CHARS


def _serialize_truncated_response_payload(
    payload: dict[str, Any],
    *,
    articles: list[UnifiedArticle],
    stats: AggregationStats,
    output_format: OutputFormat,
    max_response_chars: int | None,
    include_next_tools: bool,
) -> str:
    total_available = max(len(articles), int(getattr(stats, "unique_articles", 0) or 0))
    preview_count = min(len(articles), 3)
    truncated_payload: dict[str, Any] = {
        "tool": "unified_search",
        "status": "truncated",
        "reason": "response_size_exceeded",
        "result_id": "last",
        "returned_articles": preview_count,
        "total_available": total_available,
        "articles": [
            _compact_article_payload(article, include_rank_scores=False) for article in articles[:preview_count]
        ],
        "source_counts": payload.get("source_counts", []),
    }
    if include_next_tools:
        truncated_payload["next"] = (
            'Use read_session(request={"action":"pmids","search_index":-1}) or '
            'read_session(request={"action":"article","pmid":"..."}) to retrieve cached details.'
        )
    if payload.get("artifact"):
        truncated_payload["artifact"] = payload["artifact"]
        if include_next_tools:
            truncated_payload["next"] += " Full output is also available through the artifact locator."
    if payload.get("artifact_summary"):
        truncated_payload["artifact_summary"] = payload["artifact_summary"]
    if payload.get("source_errors"):
        truncated_payload["source_errors"] = payload["source_errors"]
    if payload.get("clinical_trials"):
        truncated_payload["clinical_trials"] = payload["clinical_trials"]
    if payload.get("enrichment"):
        truncated_payload["enrichment"] = payload["enrichment"]
    if payload.get("search_status"):
        truncated_payload["search_status"] = payload["search_status"]
    if payload.get("search_run"):
        truncated_payload["search_run"] = payload["search_run"]

    capped = serialize_structured_payload(truncated_payload, output_format)
    while max_response_chars is not None and len(capped) > max_response_chars and preview_count > 0:
        preview_count -= 1
        truncated_payload["returned_articles"] = preview_count
        truncated_payload["articles"] = [
            _compact_article_payload(article, include_rank_scores=False) for article in articles[:preview_count]
        ]
        capped = serialize_structured_payload(truncated_payload, output_format)

    minimal_payload: dict[str, Any] | None = None
    if max_response_chars is not None and len(capped) > max_response_chars:
        minimal_payload = {"status": "truncated"}
        if payload.get("search_run"):
            search_run = payload["search_run"]
            minimal_payload["search_run"] = {
                key: search_run.get(key)
                for key in ("run_id", "status", "recoverable")
                if search_run.get(key) not in (None, "", [])
            }
        if payload.get("source_errors"):
            minimal_payload["source_errors"] = [
                {
                    key: error.get(key)
                    for key in ("source", "status", "status_code", "suggestion")
                    if error.get(key) not in (None, "", [])
                }
                for error in payload["source_errors"]
                if isinstance(error, dict)
            ]
        if payload.get("clinical_trials"):
            clinical_trials = payload["clinical_trials"]
            if isinstance(clinical_trials, dict):
                minimal_payload["clinical_trials"] = {
                    "coverage": clinical_trials.get("coverage"),
                }
        if payload.get("artifact"):
            artifact = payload["artifact"]
            candidate_artifacts = [
                {
                    "artifact_id": artifact.get("artifact_id"),
                    "artifact_uri": artifact.get("artifact_uri"),
                    "primary_file": artifact.get("primary_file"),
                    "read_via": artifact.get("read_via"),
                },
                {"artifact_id": artifact.get("artifact_id"), "artifact_uri": artifact.get("artifact_uri")},
                {"artifact_id": artifact.get("artifact_id")},
            ]
            for candidate_artifact in candidate_artifacts:
                minimal_payload["artifact"] = {
                    key: value for key, value in candidate_artifact.items() if value not in (None, "", [])
                }
                capped = serialize_structured_payload(minimal_payload, output_format)
                if max_response_chars is None or len(capped) <= max_response_chars:
                    break
            else:
                minimal_payload.pop("artifact", None)
                capped = serialize_structured_payload(minimal_payload, output_format)
        else:
            capped = serialize_structured_payload(minimal_payload, output_format)

    if (
        max_response_chars is not None
        and len(capped) > max_response_chars
        and payload.get("source_errors")
        and minimal_payload is not None
    ):
        minimal_payload.pop("source_errors", None)
        capped = serialize_structured_payload(minimal_payload, output_format)

    if max_response_chars is not None and len(capped) > max_response_chars:
        capped = serialize_structured_payload({"status": "truncated"}, output_format)

    return capped


def _serialize_with_response_cap(
    payload: dict[str, Any],
    *,
    articles: list[UnifiedArticle],
    stats: AggregationStats,
    output_format: OutputFormat,
    max_response_chars: int | None,
    include_next_tools: bool,
) -> str:
    serialized = serialize_structured_payload(payload, output_format)
    if max_response_chars is None or len(serialized) <= max_response_chars:
        return serialized

    return _serialize_truncated_response_payload(
        payload,
        articles=articles,
        stats=stats,
        output_format=output_format,
        max_response_chars=max_response_chars,
        include_next_tools=include_next_tools,
    )


def _artifact_response_summary(artifact_manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    """Build a compact token-offload note for structured responses."""
    if not artifact_manifest:
        return None

    files = list(artifact_manifest.get("files") or [])
    read_order = list(artifact_manifest.get("read_order") or files)
    read_files = cast(
        "dict[str, Any]",
        artifact_manifest.get("read_files") if isinstance(artifact_manifest.get("read_files"), dict) else {},
    )
    read_files_by_uri = cast(
        "dict[str, Any]",
        artifact_manifest.get("read_files_by_uri")
        if isinstance(artifact_manifest.get("read_files_by_uri"), dict)
        else {},
    )
    first_file = str((read_order[0] if read_order else artifact_manifest.get("primary_file")) or "")
    remote_retrieval = cast(
        "dict[str, Any]",
        artifact_manifest.get("remote_retrieval")
        if isinstance(artifact_manifest.get("remote_retrieval"), dict)
        else {},
    )
    start_with_uri = read_files_by_uri.get(first_file) or remote_retrieval.get("read_via") or ""
    start_with = start_with_uri or read_files.get(first_file) or artifact_manifest.get("read_via") or ""
    return {
        "note": (
            "This MCP response is a compact summary. Use the artifact files for complete results, "
            "query strategy, and audit evidence."
        ),
        "artifact_id": artifact_manifest.get("artifact_id"),
        "artifact_uri": artifact_manifest.get("artifact_uri"),
        "primary_file": artifact_manifest.get("primary_file"),
        "audit_status": artifact_manifest.get("audit_status"),
        "available_files": files,
        "recommended_read_order": read_order,
        "start_with": start_with,
        "start_with_uri": start_with_uri,
        "read_files_by_uri": read_files_by_uri,
        "supports_paging": bool(remote_retrieval.get("supports_paging", True)),
    }


def _build_search_status(
    *,
    articles: list[UnifiedArticle],
    source_rows: Sequence[Mapping[str, Any]],
    source_errors: list[dict[str, Any]] | None,
    source_metadata: dict[str, dict[str, Any]] | None,
    source_statuses: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a truthful, machine-oriented bounded-search outcome summary."""
    errors = [error for error in list(source_errors or []) if isinstance(error, dict)]
    error_sources = {str(error.get("source")) for error in errors if error.get("source")}
    statuses = dict(source_statuses or {})
    responding_statuses = {"ok", "empty", "partial", "completed"}
    failed_sources = sorted(
        source for source in error_sources if statuses.get(source, "error") not in responding_statuses
    )
    retryable_sources = sorted(
        {str(error.get("source")) for error in errors if error.get("source") and error.get("retryable")}
    )
    attempted_sources = [str(row.get("source")) for row in source_rows if row.get("source")]
    for source in failed_sources:
        if source not in attempted_sources:
            attempted_sources.append(source)
    successful_sources = [
        source
        for source in attempted_sources
        if statuses.get(source) in responding_statuses or (source not in error_sources and source not in failed_sources)
    ]
    continuation_sources = sorted(
        source
        for source, metadata in dict(source_metadata or {}).items()
        if isinstance(metadata, dict) and metadata.get("continuation_available") is True
    )
    unknown_completeness_sources = sorted(
        str(row.get("source")) for row in source_rows if row.get("source") and row.get("has_more") is None
    )

    if errors and (articles or successful_sources):
        state = "partial"
    elif errors:
        state = "failed"
    elif articles:
        state = "completed"
    else:
        state = "empty"

    return {
        "state": state,
        "bounded": True,
        "exhaustive": False,
        "returned": len(articles),
        "attempted_sources": attempted_sources,
        "successful_sources": successful_sources,
        "failed_sources": failed_sources,
        "retryable_sources": retryable_sources,
        "continuation_available_sources": continuation_sources,
        "unknown_completeness_sources": unknown_completeness_sources,
    }


def _format_as_json(
    articles: list[UnifiedArticle],
    analysis: AnalyzedQuery,
    stats: AggregationStats,
    relaxation_result: RelaxationResult | None = None,
    deep_search_metrics: SearchDepthMetrics | None = None,
    source_api_counts: dict[str, tuple[int, int | None]] | None = None,
    source_disagreement: SourceDisagreement | None = None,
    reproducibility_score: ReproducibilityScore | None = None,
    source_errors: list[dict[str, Any]] | None = None,
    source_metadata: dict[str, dict[str, Any]] | None = None,
    enrichment_metadata: dict[str, Any] | None = None,
    source_statuses: Mapping[str, str] | None = None,
    counts_first: bool = False,
    compact_output: bool = False,
    include_analysis: bool = True,
    include_rank_scores: bool = True,
    include_next_tools: bool = True,
    include_section_provenance: bool = True,
    max_response_chars: int | None = DEFAULT_STRUCTURED_RESPONSE_MAX_CHARS,
    output_format: OutputFormat = "json",
    artifact_manifest: dict[str, Any] | None = None,
    search_run_handoff: dict[str, Any] | None = None,
    result_filter_counts: Mapping[str, int] | None = None,
    clinical_trials_coverage: ClinicalTrialsCoverage | None = None,
    prefetched_trials: list[dict[str, Any]] | None = None,
) -> str:
    """Format results as JSON or TOON for programmatic access."""
    source_rows = _serialize_source_counts(source_api_counts, stats)
    artifact_summary = _artifact_response_summary(artifact_manifest)
    search_status = _build_search_status(
        articles=articles,
        source_rows=source_rows,
        source_errors=source_errors,
        source_metadata=source_metadata,
        source_statuses=source_statuses,
    )
    clinical_trials_payload = (
        {
            "coverage": clinical_trials_coverage.to_dict(),
            "trials": list(prefetched_trials or []),
        }
        if clinical_trials_coverage is not None
        else None
    )
    if _should_pretruncate_structured_response(
        articles,
        max_response_chars=max_response_chars,
        compact_output=compact_output,
    ):
        cap_context: dict[str, Any] = {
            "tool": "unified_search",
            "source_counts": source_rows,
            "search_status": search_status,
            "result_filter_counts": dict(result_filter_counts or {}),
        }
        if source_errors:
            cap_context["source_errors"] = source_errors
        if clinical_trials_payload is not None:
            cap_context["clinical_trials"] = clinical_trials_payload
        if source_metadata:
            cap_context["source_metadata"] = source_metadata
        if enrichment_metadata:
            cap_context["enrichment"] = enrichment_metadata
        if artifact_manifest:
            cap_context["artifact"] = artifact_manifest
        if artifact_summary:
            cap_context["artifact_summary"] = artifact_summary
        if search_run_handoff:
            cap_context["search_run"] = search_run_handoff
        return _serialize_truncated_response_payload(
            cap_context,
            articles=articles,
            stats=stats,
            output_format=output_format,
            max_response_chars=max_response_chars,
            include_next_tools=include_next_tools,
        )

    structured_output_format = preferred_structured_output_format(output_format)
    next_actions = _build_next_actions(articles, analysis, source_rows, structured_output_format)
    next_tools, next_commands = finalize_next_tools(next_actions)
    result = {
        "tool": "unified_search",
        "statistics": stats.to_dict(),
        "articles": [
            _article_payload(a, compact_output=compact_output, include_rank_scores=include_rank_scores)
            for a in articles
        ],
        "source_counts": source_rows,
        "search_status": search_status,
        "result_filter_counts": dict(result_filter_counts or {}),
    }
    if include_analysis:
        result["analysis"] = analysis.to_dict()
    if include_next_tools:
        result["next_tools"] = next_tools
        result["next_commands"] = next_commands

    if source_errors:
        result["source_errors"] = source_errors
    if source_metadata:
        result["source_metadata"] = source_metadata
    if enrichment_metadata:
        result["enrichment"] = enrichment_metadata
    if clinical_trials_payload is not None:
        result["clinical_trials"] = clinical_trials_payload

    if artifact_manifest:
        result["artifact"] = artifact_manifest
    if artifact_summary:
        result["artifact_summary"] = artifact_summary
    if search_run_handoff:
        result["search_run"] = search_run_handoff

    # Add deep search metrics if available
    if include_analysis and deep_search_metrics:
        result["deep_search"] = {
            "enabled": True,
            "depth_score": deep_search_metrics.depth_score,
            "entities_resolved": deep_search_metrics.entities_resolved,
            "mesh_terms_used": deep_search_metrics.mesh_terms_used,
            "synonyms_expanded": deep_search_metrics.synonyms_expanded,
            "strategies_generated": deep_search_metrics.strategies_generated,
            "strategies_executed": deep_search_metrics.strategies_executed,
            "strategies_with_results": deep_search_metrics.strategies_with_results,
            "heuristic_recall_proxy": deep_search_metrics.heuristic_recall_proxy,
            "heuristic_precision_proxy": deep_search_metrics.heuristic_precision_proxy,
            "proxy_note": "Heuristic proxies only; not validated recall or precision estimates.",
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
            "outcome": "partial_success" if relaxation_result.incomplete else "success",
            "original_query": relaxation_result.original_query,
            "relaxed_query": relaxation_result.relaxed_query,
            "successful_level": step.level,
            "successful_action": step.action,
            "description": step.description,
            "steps_tried": [_relaxation_step_payload(s) for s in relaxation_result.steps_tried],
        }
    elif relaxation_result and not relaxation_result.successful_step:
        result["relaxation"] = {
            "was_relaxed": False,
            "original_query": relaxation_result.original_query,
            "outcome": "incomplete" if relaxation_result.incomplete else "empty",
            "note": (
                "Some relaxation requests failed; broader-query completeness is unknown"
                if relaxation_result.incomplete
                else "All planned relaxation queries completed with 0 results"
            ),
            "steps_tried": [_relaxation_step_payload(s) for s in relaxation_result.steps_tried],
        }

    # Source disagreement analysis
    if include_analysis and source_disagreement:
        result["source_disagreement"] = source_disagreement.to_dict()

    # Reproducibility score
    if include_analysis and reproducibility_score:
        result["reproducibility"] = reproducibility_score.to_dict()

    if counts_first:
        orientation: dict[str, Any] = {
            "mode": "counts_first",
            "source_counts": source_rows,
            "responded_sources": sum(1 for row in source_rows if int(row["returned"] or 0) > 0),
            "queried_sources": len(source_rows),
        }
        if include_next_tools:
            orientation["next_actions"] = next_actions
            orientation["next_tools"] = next_tools
            orientation["next_commands"] = next_commands
        result["orientation"] = orientation

    if include_section_provenance:
        result["section_provenance"] = _build_unified_section_provenance(
            source_rows,
            include_deep_search=include_analysis and deep_search_metrics is not None,
            include_relaxation=relaxation_result is not None,
            include_source_disagreement=include_analysis and source_disagreement is not None,
            include_reproducibility=include_analysis and reproducibility_score is not None,
        )

    return _serialize_with_response_cap(
        result,
        articles=articles,
        stats=stats,
        output_format=output_format,
        max_response_chars=max_response_chars,
        include_next_tools=include_next_tools,
    )
