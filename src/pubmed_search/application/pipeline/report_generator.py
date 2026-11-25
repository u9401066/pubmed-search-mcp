"""
Pipeline Report Generator — 產生生產級 Markdown 研究報告.

從 PipelineExecutor 的執行結果自動生成結構化報告，供人類閱讀和 Agent 消費。

Generated report structure:
  1. Executive Summary — 名稱、步驟成功率、文章總數、來源統計
  2. Search Strategy — DAG 步驟細節表 (action, 輸入/輸出, 狀態)
  3. Source Statistics — 每來源 API 回傳量、佔比
  4. Top Findings — 完整文章清單 (標題、作者、期刊、OA、引用指標)
  5. Evidence Distribution — 研究類型統計
  6. Methodology Notes — 搜尋限制與建議
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pubmed_search.application.pipeline.executor import classify_pipeline_outcome
from pubmed_search.application.pipeline.mesh_suggestions import ADOPT_INSTRUCTION, suggestion_note
from pubmed_search.application.pipeline.record_lineage import final_record_set, retrieval_summary
from pubmed_search.shared.markdown import (
    escape_markdown_block,
    escape_markdown_code,
    escape_markdown_identifier,
    escape_markdown_text,
    markdown_link,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pubmed_search.domain.entities.article import UnifiedArticle
    from pubmed_search.domain.entities.pipeline import PipelineConfig, PipelineRun, StepResult

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────
_ABSTRACT_MAX_LEN = 400
_TOP_ARTICLES_DEFAULT = 30
_FILTER_REASON_LABELS = {
    "year_before_min": "year before min_year",
    "year_after_max": "year after max_year",
    "article_type_mismatch": "article type mismatch",
    "unknown_article_type_filter": "unknown article_types requested",
    "citation_count_below_min": "citation count below min_citations",
    "missing_abstract": "missing abstract",
}


def generate_pipeline_report(
    articles: list[UnifiedArticle],
    step_results: dict[str, StepResult],
    config: PipelineConfig,
) -> str:
    """Generate a comprehensive Markdown report from pipeline execution results.

    This is the single entry point. It delegates to section builders and
    concatenates all parts into a complete report.

    Args:
        articles: Final deduplicated articles (after ranking).
        step_results: Per-step execution results.
        config: The pipeline configuration that was executed.

    Returns:
        Complete Markdown report string.
    """
    parts: list[str] = []

    parts.append(_section_header(config))
    parts.append(_section_executive_summary(articles, step_results, config))
    parts.append(_section_step_details(step_results, config))
    parts.append(_section_exhaustive_retrieval(step_results))
    parts.append(_section_block_analysis(step_results))
    parts.append(_section_mesh_corrections(step_results))
    parts.append(_section_source_statistics(step_results))
    parts.append(_section_filter_diagnostics(step_results))
    parts.append(_section_evidence_distribution(articles))
    parts.append(_section_articles(articles, config))
    parts.append(_section_methodology_notes(articles, step_results, config))

    return "\n".join(parts)


def generate_pipeline_changes(
    articles: list[UnifiedArticle], run: PipelineRun, *, previous_run: PipelineRun | None
) -> str:
    """Render observed changes against the previous successful execution."""
    parts = ["## Changes since previous successful run\n"]
    if previous_run is None:
        parts.append("This run is the baseline; there is no previous successful run.\n")
        return "\n".join(parts)

    new_pmids = set(run.new_pmids)
    new_articles = [article for article in articles if article.pmid in new_pmids]
    parts.append(f"### New articles ({len(new_articles)})\n")
    for article in new_articles[:20]:
        parts.append(f"- PMID {escape_markdown_text(article.pmid)}: {escape_markdown_text(article.title)}")
    if len(new_articles) > 20:
        parts.append(f"+{len(new_articles) - 20} more")
    if run.removed_pmids:
        parts.append(f"\n### Removed PMIDs ({len(run.removed_pmids)})\n")
        parts.extend(f"- PMID {escape_markdown_text(pmid)}" for pmid in run.removed_pmids[:20])
        if len(run.removed_pmids) > 20:
            parts.append(f"+{len(run.removed_pmids) - 20} more")
    parts.append("")
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# Section Builders
# ═══════════════════════════════════════════════════════════════════════════


def _section_header(
    config: PipelineConfig,
) -> str:
    """Report title and generation timestamp."""
    name = escape_markdown_text(config.name or "Pipeline")
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"# 📋 Pipeline Research Report: {name}\n\n*Generated: {now}*\n"


def _section_executive_summary(
    articles: list[UnifiedArticle],
    step_results: dict[str, StepResult],
    config: PipelineConfig,
) -> str:
    """High-level overview: steps, articles, sources."""
    parts: list[str] = ["## Executive Summary\n"]

    total_steps = len(step_results)
    ok_steps = sum(1 for r in step_results.values() if r.ok)
    error_steps = total_steps - ok_steps

    parts.append("| Metric | Value |")
    parts.append("|--------|-------|")
    parts.append(f"| Pipeline | {escape_markdown_text(config.name or '(unnamed)')} |")
    parts.append(
        f"| Steps executed | {ok_steps}/{total_steps}{' (' + str(error_steps) + ' errors)' if error_steps else ''} |"
    )
    parts.append(f"| Outcome | {classify_pipeline_outcome(articles, step_results)} |")
    parts.append(f"| Returned articles | {len(articles)} |")
    parts.append(f"| Output limit | {config.output.limit} |")
    if config.output.ranking:
        parts.append(f"| Ranking | {escape_markdown_text(config.output.ranking)} |")

    # Year range from articles
    years = [a.year for a in articles if a.year]
    if years:
        parts.append(f"| Year range | {min(years)}–{max(years)} |")

    parts.append("")
    return "\n".join(parts)


def _section_step_details(
    step_results: dict[str, StepResult],
    config: PipelineConfig,
) -> str:
    """Detailed step-by-step execution table."""
    parts: list[str] = ["## Search Strategy — Step Details\n"]

    parts.append("| # | Step ID | Action | Inputs | Status | Output |")
    parts.append("|---|---------|--------|--------|--------|--------|")

    for idx, step in enumerate(config.steps, 1):
        sr = step_results.get(step.id)
        inputs_str = ", ".join(escape_markdown_identifier(item) for item in step.inputs) if step.inputs else "—"
        step_id = escape_markdown_code(step.id)
        action = escape_markdown_text(step.action)

        if sr is None:
            parts.append(f"| {idx} | `{step_id}` | {action} | {inputs_str} | ⏭ skipped | — |")
        elif not sr.ok:
            err_msg = escape_markdown_text((sr.error or "unknown")[:80])
            parts.append(f"| {idx} | `{step_id}` | {action} | {inputs_str} | ❌ error | {err_msg} |")
        else:
            output = _step_output_summary(sr)
            parts.append(f"| {idx} | `{step_id}` | {action} | {inputs_str} | ✅ | {output} |")

    parts.append("")

    # Error details (if any)
    errors = [(s.id, step_results[s.id]) for s in config.steps if s.id in step_results and not step_results[s.id].ok]
    if errors:
        parts.append("### ⚠️ Step Errors\n")
        for step_id, sr in errors:
            parts.append(f"- **{escape_markdown_identifier(step_id)}**: {escape_markdown_text(sr.error)}")
        parts.append("")

    return "\n".join(parts)


def _section_exhaustive_retrieval(step_results: dict[str, StepResult]) -> str:
    """Disclose completeness of every exhaustive PubMed retrieval step."""
    rows: list[str] = []
    for step_id, sr in step_results.items():
        retrieval = sr.metadata.get("retrieval")
        if not isinstance(retrieval, dict) or retrieval.get("mode") != "exhaustive":
            continue
        history = sr.metadata.get("pubmed_history") if isinstance(sr.metadata.get("pubmed_history"), dict) else {}
        translation = history.get("query_translation") if isinstance(history, dict) else None
        rows.append(
            f"| `{escape_markdown_code(step_id)}` | {retrieval.get('total_count', '—')} "
            f"| {retrieval.get('retrieved_count', '—')} | {'yes' if retrieval.get('exhaustive') else 'no'} "
            f"| {retrieval.get('cap', '—')} | {retrieval.get('metadata_count', 0)} "
            f"| {'captured' if translation else '—'} |"
        )
    if not rows:
        return ""
    _final_step, final_pmids = final_record_set(step_results)
    summary = retrieval_summary(step_results, len(final_pmids))
    complete = "yes" if summary.get("exhaustive") is True else "no"
    return "\n".join(
        [
            "## Exhaustive PubMed Retrieval\n",
            "| Step | PubMed count | Retrieved | Exhaustive | Cap | Metadata | Query translation |",
            "|------|--------------|-----------|------------|-----|----------|-------------------|",
            *rows,
            "",
            f"Final record set: {escape_markdown_text(summary.get('mode'))} retrieval, complete record set {complete}.",
            *(f"- ⚠️ {escape_markdown_text(warning)}" for warning in summary.get("warnings") or []),
            "",
            "The record set is persisted with the saved run; the article list below is the ranked preview.",
            "",
        ]
    )


def _count_cell(value: Any) -> str:
    return "—" if value is None else f"{value:,}" if isinstance(value, int) else escape_markdown_text(value)


def mesh_correction_warnings(step_results: Mapping[str, StepResult]) -> list[str]:
    """One warning per step whose PubMed query had a MeSH clause PubMed could not resolve."""
    warnings: list[str] = []
    for step_id, result in step_results.items():
        suggestions = [result.metadata.get("mesh_correction")]
        analysis = result.metadata.get("block_analysis")
        if isinstance(analysis, dict):
            suggestions.append(analysis.get("mesh_correction"))
        for suggestion in suggestions:
            note = suggestion_note(suggestion if isinstance(suggestion, dict) else None)
            if note:
                warnings.append(f"Step {step_id}: {note}")
    return warnings


def _section_mesh_corrections(step_results: dict[str, StepResult]) -> str:
    warnings = mesh_correction_warnings(step_results)
    if not warnings:
        return ""
    parts = ["## ⚠️ PubMed MeSH clauses that matched nothing\n"]
    parts.extend(f"- {escape_markdown_text(warning)}" for warning in warnings)
    parts.append("")
    parts.append(f"{escape_markdown_text(ADOPT_INSTRUCTION)}\n")
    return "\n".join(parts)


def render_block_analysis_markdown(analysis: dict[str, Any], *, heading: str = "###") -> str:
    """Render one strategy block analysis as Markdown tables."""
    step_id = escape_markdown_code(str(analysis.get("step_id") or "block_analysis"))
    parts = [f"{heading} Strategy block analysis (`{step_id}`)\n"]
    if not analysis.get("decomposable"):
        parts.append(f"Not decomposable: {escape_markdown_text(analysis.get('reason') or 'unknown reason')}\n")
        return "\n".join(parts)
    parts.append(f"Full strategy: {_count_cell(analysis.get('full_count'))} records")
    filters = analysis.get("filters") or {}
    if filters:
        parts.append(f"Filters: {escape_markdown_text(', '.join(f'{k}={v}' for k, v in filters.items()))}")
    parts.append("")
    cumulative = list(analysis.get("cumulative") or [])
    parts.append("| Block | Terms | Hits alone | Cumulative (AND so far) |")
    parts.append("|-------|-------|------------|-------------------------|")
    for index, block in enumerate(analysis.get("blocks") or []):
        cumulative_count = cumulative[index]["count"] if index < len(cumulative) else None
        parts.append(
            f"| {escape_markdown_text(block.get('label'))} | {block.get('term_count')} "
            f"| {_count_cell(block.get('count'))} | {_count_cell(cumulative_count)} |"
        )
    for not_block in analysis.get("not_blocks") or []:
        parts.append(
            f"| {escape_markdown_text(not_block.get('label'))} (NOT) | — | — "
            f"| removes {_count_cell(not_block.get('records_removed'))} |"
        )
    parts.append("")
    parts.append("| Block | Term | Unique records (lost if removed) | Status |")
    parts.append("|-------|------|----------------------------------|--------|")
    for term in analysis.get("terms") or []:
        parts.append(
            f"| {escape_markdown_text(term.get('block'))} | `{escape_markdown_code(term.get('term'))}` "
            f"| {_count_cell(term.get('unique_contribution'))} | {escape_markdown_text(term.get('status'))} |"
        )
    unresolved = analysis.get("unresolved_terms") or []
    if unresolved:
        parts.append("")
        parts.append(
            "⚠️ PubMed did not find these terms, so they match nothing and their unique contribution "
            "is meaningless: " + ", ".join(f"`{escape_markdown_code(str(item['term']))}`" for item in unresolved)
        )
        note = suggestion_note(analysis.get("mesh_correction"))
        if note:
            parts.append(escape_markdown_text(note))
    zero = analysis.get("zero_contribution_terms") or []
    if zero:
        parts.append("")
        parts.append(
            "Terms with zero unique contribution in this strategy (review, do not delete blindly): "
            + ", ".join(f"`{escape_markdown_code(item['term'])}`" for item in zero)
        )
    queries = analysis.get("count_queries") or {}
    parts.append("")
    parts.append(
        f"Count queries: {queries.get('executed', 0)} executed of {queries.get('planned', 0)} planned "
        f"(max {queries.get('max')}, {queries.get('cache_hits', 0)} cached)."
    )
    if queries.get("truncated"):
        parts.append(
            f"⚠️ Truncated ({escape_markdown_text(queries.get('truncation_reason'))}): "
            f"{queries.get('terms_not_evaluated', 0)} terms were not evaluated."
        )
    parts.append("")
    return "\n".join(parts)


def _section_block_analysis(step_results: dict[str, StepResult]) -> str:
    analyses = [
        sr.metadata["block_analysis"]
        for sr in step_results.values()
        if sr.action == "block_analysis" and isinstance(sr.metadata.get("block_analysis"), dict)
    ]
    if not analyses:
        return ""
    return "## Strategy Block Analysis\n\n" + "\n".join(
        render_block_analysis_markdown(analysis) for analysis in analyses
    )


def _step_output_summary(sr: StepResult) -> str:
    """Summarize a successful step's output for the table."""
    details: list[str] = []

    if sr.action == "filter" and sr.metadata.get("before_count") is not None:
        before = sr.metadata.get("before_count", 0)
        after = sr.metadata.get("after_count", len(sr.articles))
        removed = sr.metadata.get("removed_count", max(0, int(before) - int(after)))
        details.append(f"{before} -> {after} articles")
        if removed:
            details.append(f"removed {removed}")
        reasons = sr.metadata.get("removal_reasons") or {}
        if reasons:
            top_reason, top_count = max(reasons.items(), key=lambda item: item[1])
            label = escape_markdown_identifier(_FILTER_REASON_LABELS.get(str(top_reason), str(top_reason)))
            details.append(f"top reason: {label} ({escape_markdown_text(top_count)})")

    elif sr.articles:
        src_counts = sr.metadata.get("source_api_counts")
        if src_counts:
            breakdown = ", ".join(
                f"{escape_markdown_identifier(source)}: {escape_markdown_text(count)}"
                for source, count in src_counts.items()
            )
            details.append(f"{len(sr.articles)} articles ({breakdown})")
        else:
            details.append(f"{len(sr.articles)} articles")

    if sr.action == "expand" and sr.metadata.get("expanded_query"):
        query = str(sr.metadata["expanded_query"])
        preview = f"{query[:60]}{'…' if len(query) > 60 else ''}"
        details.append(f"query: `{escape_markdown_code(preview)}`")

    if sr.action == "metrics" and sr.articles:
        with_metrics = sum(
            1 for a in sr.articles if a.citation_metrics and a.citation_metrics.citation_count is not None
        )
        details.append(f"{with_metrics}/{len(sr.articles)} enriched")

    if sr.action == "merge" and sr.metadata.get("duplicates_removed") is not None:
        details.append(f"{escape_markdown_text(sr.metadata['duplicates_removed'])} dups removed")

    if not details:
        # Fallback: show metadata keys
        if sr.metadata:
            keys = ", ".join(escape_markdown_text(key) for key in sorted(sr.metadata.keys())[:4])
            return f"metadata: {keys}"
        return "ok"

    return " · ".join(details)


def _section_source_statistics(step_results: dict[str, StepResult]) -> str:
    """Aggregate per-source API return counts across all search steps."""
    aggregated: dict[str, int] = {}
    for sr in step_results.values():
        if sr.ok and sr.metadata.get("source_api_counts"):
            for src, count in sr.metadata["source_api_counts"].items():
                aggregated[src] = aggregated.get(src, 0) + count

    if not aggregated:
        return ""

    parts: list[str] = ["## Source Statistics\n"]
    total = sum(aggregated.values())

    parts.append("| Source | Articles | Share |")
    parts.append("|--------|----------|-------|")
    for src, count in sorted(aggregated.items(), key=lambda x: -x[1]):
        pct = count / total * 100 if total else 0
        parts.append(f"| {escape_markdown_identifier(src)} | {count} | {pct:.0f}% |")
    parts.append(f"| **Total** | **{total}** | **100%** |")
    parts.append("")

    return "\n".join(parts)


def _section_filter_diagnostics(step_results: dict[str, StepResult]) -> str:
    """Show per-filter before/after counts and exclusion reasons."""
    filter_results = [
        sr
        for sr in step_results.values()
        if sr.ok and sr.action == "filter" and sr.metadata.get("before_count") is not None
    ]
    if not filter_results:
        return ""

    parts: list[str] = ["## Filter Diagnostics\n"]
    parts.append("| Step | Before | After | Removed | Exclusion Reasons |")
    parts.append("|------|--------|-------|---------|-----------------------|")
    for sr in filter_results:
        reasons = sr.metadata.get("removal_reasons") or {}
        reason_text = "—"
        if reasons:
            reason_text = ", ".join(
                f"{escape_markdown_identifier(_FILTER_REASON_LABELS.get(str(reason), str(reason)))}: "
                f"{escape_markdown_text(count)}"
                for reason, count in sorted(reasons.items(), key=lambda item: -item[1])
            )
        parts.append(
            f"| `{escape_markdown_code(sr.step_id)}` | {escape_markdown_text(sr.metadata.get('before_count', 0))} | "
            f"{escape_markdown_text(sr.metadata.get('after_count', 0))} | "
            f"{escape_markdown_text(sr.metadata.get('removed_count', 0))} | {reason_text} |"
        )

    for sr in filter_results:
        diagnostics = sr.metadata.get("article_type_diagnostics") or {}
        warning = sr.metadata.get("warning")
        examples = sr.metadata.get("excluded_examples") or []
        if diagnostics or warning or examples:
            parts.append("")
            parts.append(f"### `{escape_markdown_code(sr.step_id)}` Details\n")
        if diagnostics:
            mappings = diagnostics.get("mappings") or {}
            unknown = diagnostics.get("unknown") or []
            if mappings:
                mapping_text = ", ".join(
                    f"`{escape_markdown_code(raw)}` -> `{escape_markdown_code(canonical)}`"
                    for raw, canonical in mappings.items()
                )
                parts.append(f"- Article type mapping: {mapping_text}")
            if unknown:
                unknown_items = ", ".join(f"`{escape_markdown_code(item)}`" for item in unknown)
                parts.append(f"- Unknown article_types: {unknown_items}")
        if warning:
            parts.append(f"- Warning: {escape_markdown_text(warning)}")
        if examples:
            parts.append("- Excluded examples:")
            for item in examples[:3]:
                title = escape_markdown_text((item.get("title") or "Untitled")[:70])
                reasons = ", ".join(
                    escape_markdown_text(_FILTER_REASON_LABELS.get(reason, reason))
                    for reason in item.get("reasons", [])
                )
                pmid = escape_markdown_text(item.get("pmid") or "no PMID")
                year = escape_markdown_text(item.get("year") or "no year")
                article_type = escape_markdown_text(item.get("article_type") or "unknown")
                parts.append(f"  - PMID {pmid} ({year}, {article_type}): {title} — {reasons}")

    parts.append("")
    return "\n".join(parts)


def _section_evidence_distribution(articles: list[UnifiedArticle]) -> str:
    """Classify articles by study type and show distribution."""
    from pubmed_search.domain.entities.article import ArticleType

    if not articles:
        return ""

    type_counter: Counter[str] = Counter()
    for a in articles:
        if a.article_type and a.article_type != ArticleType.UNKNOWN:
            type_counter[a.article_type.value] += 1
        else:
            type_counter["unknown"] += 1

    # Only show if there's meaningful data (not all unknown)
    non_unknown = sum(c for t, c in type_counter.items() if t != "unknown")
    if non_unknown == 0:
        return ""

    # Display ordering of publication types; metadata alone cannot grade evidence.
    evidence_order = {
        "meta-analysis": 1,
        "systematic-review": 2,
        "randomized-controlled-trial": 3,
        "clinical-trial": 4,
        "review": 5,
        "journal-article": 6,
        "case-report": 7,
        "letter": 8,
        "editorial": 9,
        "preprint": 10,
    }

    parts: list[str] = ["## Evidence Distribution\n"]
    parts.append("| Study Type | Count | Metadata category |")
    parts.append("|------------|-------|----------------|")

    level_labels = {
        "meta-analysis": "Evidence synthesis",
        "systematic-review": "Evidence synthesis",
        "randomized-controlled-trial": "Randomized trial",
        "clinical-trial": "Clinical trial",
        "review": "Narrative review",
        "case-report": "Case report",
        "preprint": "Preprint metadata",
    }

    sorted_types = sorted(
        type_counter.items(),
        key=lambda x: (evidence_order.get(x[0], 99), -x[1]),
    )
    for article_type, count in sorted_types:
        if article_type == "unknown":
            continue
        level = level_labels.get(article_type, "—")
        parts.append(f"| {escape_markdown_text(article_type)} | {count} | {level} |")

    if type_counter.get("unknown", 0):
        parts.append(f"| *(unclassified)* | {type_counter['unknown']} | — |")

    parts.append("")
    return "\n".join(parts)


def _section_articles(
    articles: list[UnifiedArticle],
    config: PipelineConfig,
) -> str:
    """Full article listing with all available metadata."""
    if not articles:
        return "## Results\n\n*No articles found.*\n"

    limit = config.output.limit or _TOP_ARTICLES_DEFAULT
    shown = articles[:limit]

    parts: list[str] = [f"## Results — Top {len(shown)} Articles\n"]

    for i, article in enumerate(shown, 1):
        parts.append(_format_article(i, article))

    if len(articles) > limit:
        parts.append(
            f"\n*… and {len(articles) - limit} more articles not shown. "
            f'Use `read_session(request={{"action":"pmids"}})` or `prepare_export(pmids="last")` '
            f"to access all results.*\n"
        )

    return "\n".join(parts)


def _format_article(index: int, article: UnifiedArticle) -> str:
    """Format a single article with full metadata."""
    from pubmed_search.domain.entities.article import ArticleType

    parts: list[str] = []
    title = escape_markdown_text(article.title or "Unknown Title")

    # Score annotation
    score_str = ""
    if article.ranking_score:
        score_str = f" *(score: {article.ranking_score:.2f})*"

    parts.append(f"### {index}. {title}{score_str}\n")

    # Identifiers
    ids: list[str] = []
    if article.pmid:
        ids.append(f"PMID: {escape_markdown_text(article.pmid)}")
    if article.doi:
        ids.append(f"DOI: {escape_markdown_text(article.doi)}")
    if getattr(article, "pmc", None):
        ids.append(f"PMC: {escape_markdown_text(article.pmc)}")
    if ids:
        parts.append(" | ".join(ids))

    # Study type badge
    if article.article_type and article.article_type != ArticleType.UNKNOWN:
        _type_badges: dict[Any, str] = {
            ArticleType.META_ANALYSIS: "🟢 Meta-Analysis",
            ArticleType.SYSTEMATIC_REVIEW: "🟢 Systematic Review",
            ArticleType.RANDOMIZED_CONTROLLED_TRIAL: "🟢 RCT",
            ArticleType.CLINICAL_TRIAL: "🟡 Clinical Trial",
            ArticleType.REVIEW: "⚪ Review",
            ArticleType.CASE_REPORT: "🟠 Case Report",
        }
        badge = _type_badges.get(article.article_type, f"📄 {escape_markdown_text(article.article_type.value)}")
        parts.append(f"**Type**: {badge}")

    # Authors
    author_str = getattr(article, "author_string", None)
    if author_str:
        parts.append(f"**Authors**: {escape_markdown_text(author_str)}")

    # Journal + bibliographic details
    if article.journal:
        journal_str = escape_markdown_text(article.journal)
        if article.year:
            journal_str += f" ({escape_markdown_text(article.year)})"
        if getattr(article, "volume", None):
            journal_str += f"; {escape_markdown_text(article.volume)}"
            if getattr(article, "issue", None):
                journal_str += f"({escape_markdown_text(article.issue)})"
        if getattr(article, "pages", None):
            journal_str += f": {escape_markdown_text(article.pages)}"
        parts.append(f"**Journal**: {journal_str}")
    elif article.year:
        parts.append(f"**Year**: {escape_markdown_text(article.year)}")

    # Open Access
    if getattr(article, "has_open_access", False):
        oa_link = getattr(article, "best_oa_link", None)
        oa_status = escape_markdown_text(article.oa_status.value)
        if oa_link:
            parts.append(f"**OA**: ✅ {markdown_link(article.oa_status.value, oa_link.url)}")
        else:
            parts.append(f"**OA**: ✅ {oa_status}")

    # Citation metrics
    _cm = getattr(article, "citation_metrics", None)
    if _cm is not None:
        metric_parts: list[str] = []
        if _cm.citation_count is not None:
            metric_parts.append(f"Citations: {_cm.citation_count}")
        if _cm.nih_percentile is not None:
            metric_parts.append(f"Percentile: {_cm.nih_percentile:.0f}%")
        if _cm.relative_citation_ratio is not None:
            metric_parts.append(f"RCR: {_cm.relative_citation_ratio:.2f}")
        if metric_parts:
            parts.append(f"**Impact**: {', '.join(metric_parts)}")

    # Journal metrics
    _jm = getattr(article, "journal_metrics", None)
    if _jm is not None:
        jm_parts: list[str] = []
        if _jm.two_year_mean_citedness is not None:
            jm_parts.append(f"2-year mean citedness: {_jm.two_year_mean_citedness:.2f}")
        if _jm.h_index is not None:
            jm_parts.append(f"h-index: {_jm.h_index}")
        if _jm.impact_tier and _jm.impact_tier != "unknown":
            tier_icons = {
                "top": "🏆",
                "high": "⭐",
                "medium": "📊",
                "low": "📄",
                "minimal": "📄",
            }
            icon = tier_icons.get(_jm.impact_tier, "")
            jm_parts.append(f"{icon} {_jm.impact_tier.capitalize()}-tier")
        if jm_parts:
            parts.append(f"**Journal Metrics**: {', '.join(jm_parts)}")

    # Abstract
    if article.abstract:
        abstract = article.abstract
        if len(abstract) > _ABSTRACT_MAX_LEN:
            abstract = abstract[:_ABSTRACT_MAX_LEN] + "..."
        safe_abstract = escape_markdown_block(abstract)
        quoted_abstract = "\n".join(f"> {line}" if line else ">" for line in safe_abstract.splitlines())
        parts.append(f"\n{quoted_abstract}")

    # Sources
    if getattr(article, "sources", None):
        source_names = [escape_markdown_text(source.source) for source in article.sources]
        parts.append(f"\n*Sources: {', '.join(source_names)}*")

    parts.append("")
    return "\n".join(parts)


def _section_methodology_notes(
    articles: list[UnifiedArticle],
    step_results: dict[str, StepResult],
    config: PipelineConfig,
) -> str:
    """Add methodology notes and actionable suggestions."""
    parts: list[str] = ["## Methodology Notes\n"]

    # Pipeline config summary
    step_actions = [escape_markdown_text(step.action) for step in config.steps]
    parts.append(f"- **Pipeline type**: {escape_markdown_text(config.name or 'custom')}")
    parts.append(f"- **Steps**: {' → '.join(step_actions)}")
    parts.append(f"- **Ranking**: {escape_markdown_text(config.output.ranking or 'default')}")
    parts.append(f"- **Output limit**: {config.output.limit}")

    # Warnings / suggestions
    suggestions: list[str] = []

    # Check if metrics step was included
    has_metrics = any(s.action == "metrics" for s in config.steps)
    if not has_metrics and articles:
        suggestions.append("Consider adding a `metrics` step to enrich results with iCite citation data.")

    if any(sr.metadata.get("dry_run") for sr in step_results.values()):
        suggestions.append("Dry-run mode validated the plan only; run again without `dry_run` to fetch articles.")

    # Check for error steps
    error_steps = [s.id for s in config.steps if s.id in step_results and not step_results[s.id].ok]
    if error_steps:
        safe_error_steps = ", ".join(escape_markdown_identifier(step_id) for step_id in error_steps)
        suggestions.append(f"Steps with errors: {safe_error_steps}. Review step parameters or retry.")

    # Check output truncation
    if len(articles) > config.output.limit:
        suggestions.append(
            f"Results truncated from {len(articles)} to {config.output.limit}. "
            'Use `prepare_export(pmids="last")` to export all.'
        )

    # Check if any articles lack abstracts
    no_abstract = sum(1 for a in articles[: config.output.limit] if not a.abstract)
    if no_abstract > 0:
        suggestions.append(f"{no_abstract} articles have no abstract. Use `fetch_article_details()` for full metadata.")

    for step_id, result in step_results.items():
        if result.metadata.get("source_errors"):
            suggestions.append(
                f"Source failures in {escape_markdown_identifier(step_id)} reduced retrieval coverage; inspect the saved step diagnostics."
            )
        if result.metadata.get("warning"):
            suggestions.append(escape_markdown_text(result.metadata["warning"]))

    if suggestions:
        parts.append("\n### 💡 Suggestions\n")
        for s in suggestions:
            parts.append(f"- {s}")

    # Session hint
    parts.append("\n### 📦 Next Steps\n")
    parts.append('- `read_session(request={"action":"pmids"})` — retrieve all PMIDs from this pipeline run')
    parts.append('- `prepare_export(pmids="last", format="ris")` — export to reference manager')
    parts.append('- `save_literature_notes(pmids="last", note_format="wiki")` — save local wiki/FOAM-compatible notes')
    parts.append('- `get_fulltext(source={"kind":"pmcid","value":"PMC..."})` — retrieve full text for key articles')
    parts.append('- `build_citation_tree(pmid="...")` — explore citation network')
    parts.append("")

    return "\n".join(parts)
