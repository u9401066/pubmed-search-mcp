"""Tests for the pipeline report generator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pubmed_search.application.pipeline.report_generator import (
    _format_article,
    _section_articles,
    _section_evidence_distribution,
    _section_executive_summary,
    _section_header,
    _section_methodology_notes,
    _section_source_statistics,
    _section_step_details,
    _step_output_summary,
    generate_pipeline_report,
)
from pubmed_search.domain.entities.pipeline import (
    PipelineConfig,
    PipelineOutput,
    PipelineStep,
    StepResult,
)

# ═══════════════════════════════════════════════════════════════════════════
# Test Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class _FakeOALink:
    url: str = "https://example.com/oa"
    version: str = "publishedVersion"
    host_type: str | None = "publisher"


@dataclass
class _FakeSourceMeta:
    source: str = "pubmed"


@dataclass
class _FakeCitationMetrics:
    citation_count: int | None = 42
    nih_percentile: float | None = 85.0
    relative_citation_ratio: float | None = 2.5


@dataclass
class _FakeJournalMetrics:
    two_year_mean_citedness: float | None = 5.2
    h_index: int | None = 120
    impact_tier: str | None = "high"
    is_in_doaj: bool = False


class _FakeArticleType:
    def __init__(self, value: str) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        if hasattr(other, "value"):
            return self.value == other.value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.value)


_UNKNOWN_TYPE = _FakeArticleType("unknown")


@dataclass
class FakeArticle:
    """Minimal article-like object for report tests."""

    title: str = "Test Article"
    pmid: str | None = "12345678"
    doi: str | None = "10.1234/test"
    pmc: str | None = None
    year: int | None = 2024
    journal: str | None = "Test Journal"
    volume: str | None = "10"
    issue: str | None = "2"
    pages: str | None = "100-110"
    abstract: str | None = "This is a test abstract for the article."
    primary_source: str = "pubmed"
    article_type: Any = None
    ranking_score: float | None = 0.75
    relevance_score: float | None = None
    quality_score: float | None = None
    author_string: str = "Smith J, Doe A, Lee B"
    has_open_access: bool = False
    oa_status: Any = None
    best_oa_link: Any = None
    citation_metrics: Any = None
    journal_metrics: Any = None
    sources: list = field(default_factory=list)


def _make_articles(n: int, prefix: str = "Article") -> list[FakeArticle]:
    return [
        FakeArticle(
            title=f"{prefix} {i}",
            pmid=str(10000000 + i),
            doi=f"10.1234/{prefix.lower()}{i}",
            year=2020 + (i % 5),
            sources=[_FakeSourceMeta(source="pubmed")],
        )
        for i in range(n)
    ]


def _make_config(
    name: str = "Test Pipeline",
    steps: list[PipelineStep] | None = None,
    limit: int = 20,
    ranking: str = "quality",
) -> PipelineConfig:
    if steps is None:
        steps = [
            PipelineStep(id="search_1", action="search", params={"query": "test"}),
            PipelineStep(id="metrics_1", action="metrics", inputs=["search_1"]),
        ]
    return PipelineConfig(
        name=name,
        steps=steps,
        output=PipelineOutput(format="markdown", limit=limit, ranking=ranking),
    )


def _make_step_results(
    config: PipelineConfig,
    article_counts: dict[str, int] | None = None,
    errors: dict[str, str] | None = None,
    source_counts: dict[str, dict[str, int]] | None = None,
) -> dict[str, StepResult]:
    """Build step results matching a config."""
    article_counts = article_counts or {}
    errors = errors or {}
    source_counts = source_counts or {}
    results: dict[str, StepResult] = {}

    for step in config.steps:
        if step.id in errors:
            results[step.id] = StepResult(
                step_id=step.id,
                action=step.action,
                error=errors[step.id],
            )
        else:
            n = article_counts.get(step.id, 0)
            articles = _make_articles(n, prefix=step.id) if n > 0 else []
            metadata: dict[str, Any] = {}
            if step.id in source_counts:
                metadata["source_api_counts"] = source_counts[step.id]
            results[step.id] = StepResult(
                step_id=step.id,
                action=step.action,
                articles=articles,
                pmids=[a.pmid for a in articles if a.pmid],
                metadata=metadata,
            )

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Tests: generate_pipeline_report (integration)
# ═══════════════════════════════════════════════════════════════════════════


class TestGeneratePipelineReport:
    """Integration tests for the full report."""

    def test_basic_report_structure(self) -> None:
        config = _make_config()
        articles = _make_articles(5)
        step_results = _make_step_results(config, article_counts={"search_1": 5})
        report = generate_pipeline_report(articles, step_results, config)

        assert "# 📋 Pipeline Research Report:" in report
        assert "## Executive Summary" in report
        assert "## Search Strategy — Step Details" in report
        assert "## Results — Top 5 Articles" in report
        assert "## Methodology Notes" in report

    def test_empty_articles(self) -> None:
        config = _make_config()
        step_results = _make_step_results(config)
        report = generate_pipeline_report([], step_results, config)

        assert "*No articles found.*" in report

    def test_report_contains_pipeline_name(self) -> None:
        config = _make_config(name="CRISPR Gene Therapy Review")
        articles = _make_articles(3)
        step_results = _make_step_results(config, article_counts={"search_1": 3})
        report = generate_pipeline_report(articles, step_results, config)

        assert "CRISPR Gene Therapy Review" in report

    def test_report_with_errors(self) -> None:
        config = _make_config()
        step_results = _make_step_results(
            config,
            errors={"metrics_1": "iCite API timeout"},
        )
        report = generate_pipeline_report([], step_results, config)

        assert "❌ error" in report
        assert "iCite API timeout" in report
        assert "⚠️ Step Errors" in report

    def test_article_count_respects_output_limit(self) -> None:
        config = _make_config(limit=3)
        articles = _make_articles(10)
        step_results = _make_step_results(config, article_counts={"search_1": 10})
        report = generate_pipeline_report(articles, step_results, config)

        # Should show top 3
        assert "Top 3 Articles" in report
        # Should mention remaining
        assert "7 more articles not shown" in report


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _section_header
# ═══════════════════════════════════════════════════════════════════════════


class TestSectionHeader:
    def test_contains_name(self) -> None:
        config = _make_config(name="My Pipeline")
        header = _section_header(config)
        assert "My Pipeline" in header

    def test_contains_timestamp(self) -> None:
        config = _make_config()
        header = _section_header(config)
        assert "Generated:" in header
        assert "UTC" in header

    def test_unnamed_pipeline(self) -> None:
        config = _make_config(name="")
        config.name = None
        header = _section_header(config)
        assert "Pipeline" in header


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _section_executive_summary
# ═══════════════════════════════════════════════════════════════════════════


class TestSectionExecutiveSummary:
    def test_step_counts(self) -> None:
        config = _make_config()
        step_results = _make_step_results(config, article_counts={"search_1": 5})
        result = _section_executive_summary([], step_results, config)

        assert "2/2" in result  # Both steps OK

    def test_error_annotation(self) -> None:
        config = _make_config()
        step_results = _make_step_results(config, errors={"metrics_1": "fail"})
        result = _section_executive_summary([], step_results, config)

        assert "1/2" in result
        assert "1 errors" in result

    def test_year_range(self) -> None:
        articles = [
            FakeArticle(year=2020),
            FakeArticle(year=2024),
            FakeArticle(year=2022),
        ]
        config = _make_config()
        step_results = _make_step_results(config)
        result = _section_executive_summary(articles, step_results, config)

        assert "2020–2024" in result

    def test_no_year_range_when_no_years(self) -> None:
        articles = [FakeArticle(year=None)]
        config = _make_config()
        step_results = _make_step_results(config)
        result = _section_executive_summary(articles, step_results, config)

        assert "Year range" not in result


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _section_step_details
# ═══════════════════════════════════════════════════════════════════════════


class TestSectionStepDetails:
    def test_table_headers(self) -> None:
        config = _make_config()
        step_results = _make_step_results(config)
        result = _section_step_details(step_results, config)

        assert "| # | Step ID | Action | Inputs | Status | Output |" in result

    def test_shows_step_ids(self) -> None:
        config = _make_config()
        step_results = _make_step_results(config, article_counts={"search_1": 5})
        result = _section_step_details(step_results, config)

        assert "`search_1`" in result
        assert "`metrics_1`" in result

    def test_skipped_step(self) -> None:
        config = _make_config()
        # Remove one step from results to simulate skip
        step_results = _make_step_results(config)
        del step_results["metrics_1"]
        result = _section_step_details(step_results, config)

        assert "⏭ skipped" in result

    def test_error_step(self) -> None:
        config = _make_config()
        step_results = _make_step_results(config, errors={"search_1": "Connection refused"})
        result = _section_step_details(step_results, config)

        assert "❌ error" in result
        assert "Connection refused" in result

    def test_error_details_section(self) -> None:
        config = _make_config()
        step_results = _make_step_results(config, errors={"search_1": "API timeout after 30s"})
        result = _section_step_details(step_results, config)

        assert "⚠️ Step Errors" in result
        assert "**search_1**" in result

    def test_inputs_column(self) -> None:
        config = _make_config()
        step_results = _make_step_results(config, article_counts={"search_1": 5})
        result = _section_step_details(step_results, config)

        # metrics_1 has input [search_1]
        assert "search_1" in result


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _step_output_summary
# ═══════════════════════════════════════════════════════════════════════════


class TestStepOutputSummary:
    def test_article_count(self) -> None:
        sr = StepResult(
            step_id="s1",
            action="search",
            articles=_make_articles(5),
        )
        result = _step_output_summary(sr)
        assert "5 articles" in result

    def test_source_breakdown(self) -> None:
        sr = StepResult(
            step_id="s1",
            action="search",
            articles=_make_articles(3),
            metadata={"source_api_counts": {"pubmed": 2, "openalex": 1}},
        )
        result = _step_output_summary(sr)
        assert "pubmed: 2" in result
        assert "openalex: 1" in result

    def test_expand_action(self) -> None:
        sr = StepResult(
            step_id="expand1",
            action="expand",
            metadata={"expanded_query": '"CRISPR"[MeSH] OR "gene editing"'},
        )
        result = _step_output_summary(sr)
        assert "query:" in result

    def test_metrics_action(self) -> None:
        article = FakeArticle(citation_metrics=_FakeCitationMetrics())
        sr = StepResult(
            step_id="m1",
            action="metrics",
            articles=[article],
        )
        result = _step_output_summary(sr)
        assert "1/1 enriched" in result

    def test_filter_action(self) -> None:
        sr = StepResult(
            step_id="f1",
            action="filter",
            metadata={"removed_count": 7},
        )
        result = _step_output_summary(sr)
        assert "removed 7" in result

    def test_merge_action(self) -> None:
        sr = StepResult(
            step_id="m1",
            action="merge",
            articles=_make_articles(10),
            metadata={"duplicates_removed": 3},
        )
        result = _step_output_summary(sr)
        assert "3 dups removed" in result

    def test_fallback_metadata_keys(self) -> None:
        sr = StepResult(
            step_id="x1",
            action="search",
            metadata={"foo": 1, "bar": 2},
        )
        result = _step_output_summary(sr)
        assert "metadata:" in result

    def test_empty_step(self) -> None:
        sr = StepResult(step_id="x1", action="search")
        result = _step_output_summary(sr)
        assert result == "ok"


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _section_source_statistics
# ═══════════════════════════════════════════════════════════════════════════


class TestSectionSourceStatistics:
    def test_aggregates_sources(self) -> None:
        step_results = {
            "s1": StepResult(
                step_id="s1",
                action="search",
                metadata={"source_api_counts": {"pubmed": 10, "openalex": 5}},
            ),
            "s2": StepResult(
                step_id="s2",
                action="search",
                metadata={"source_api_counts": {"pubmed": 3, "europe_pmc": 7}},
            ),
        }
        result = _section_source_statistics(step_results)

        assert "pubmed" in result
        assert "13" in result  # 10 + 3
        assert "openalex" in result
        assert "europe_pmc" in result
        assert "Total" in result

    def test_empty_when_no_sources(self) -> None:
        step_results = {
            "s1": StepResult(step_id="s1", action="merge"),
        }
        result = _section_source_statistics(step_results)
        assert result == ""

    def test_percentage_calculation(self) -> None:
        step_results = {
            "s1": StepResult(
                step_id="s1",
                action="search",
                metadata={"source_api_counts": {"pubmed": 50, "openalex": 50}},
            ),
        }
        result = _section_source_statistics(step_results)
        assert "50%" in result


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _section_evidence_distribution
# ═══════════════════════════════════════════════════════════════════════════


class TestSectionEvidenceDistribution:
    def test_shows_study_types(self) -> None:
        from pubmed_search.domain.entities.article import ArticleType

        articles = [
            FakeArticle(article_type=ArticleType.META_ANALYSIS),
            FakeArticle(article_type=ArticleType.RANDOMIZED_CONTROLLED_TRIAL),
            FakeArticle(article_type=ArticleType.RANDOMIZED_CONTROLLED_TRIAL),
            FakeArticle(article_type=ArticleType.REVIEW),
        ]
        result = _section_evidence_distribution(articles)

        assert "meta-analysis" in result
        assert "randomized-controlled-trial" in result
        assert "🟢" in result

    def test_empty_when_no_articles(self) -> None:
        result = _section_evidence_distribution([])
        assert result == ""

    def test_empty_when_all_unknown(self) -> None:
        from pubmed_search.domain.entities.article import ArticleType

        articles = [
            FakeArticle(article_type=ArticleType.UNKNOWN),
            FakeArticle(article_type=ArticleType.UNKNOWN),
        ]
        result = _section_evidence_distribution(articles)
        assert result == ""

    def test_none_article_type_treated_as_unknown(self) -> None:
        articles = [FakeArticle(article_type=None)]
        result = _section_evidence_distribution(articles)
        assert result == ""


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _format_article
# ═══════════════════════════════════════════════════════════════════════════


class TestFormatArticle:
    def test_basic_fields(self) -> None:
        article = FakeArticle()
        result = _format_article(1, article)

        assert "### 1. Test Article" in result
        assert "PMID: 12345678" in result
        assert "DOI: 10.1234/test" in result
        assert "Smith J, Doe A, Lee B" in result
        assert "Test Journal" in result
        assert "2024" in result

    def test_journal_with_volume_issue_pages(self) -> None:
        article = FakeArticle(
            journal="Nature Medicine",
            year=2023,
            volume="29",
            issue="4",
            pages="850-860",
        )
        result = _format_article(1, article)
        assert "Nature Medicine (2023); 29(4): 850-860" in result

    def test_open_access(self) -> None:
        article = FakeArticle(
            has_open_access=True,
            oa_status=type("OA", (), {"value": "gold"})(),
            best_oa_link=_FakeOALink(),
        )
        result = _format_article(1, article)
        assert "✅" in result
        assert "gold" in result

    def test_citation_metrics(self) -> None:
        article = FakeArticle(
            citation_metrics=_FakeCitationMetrics(),
        )
        result = _format_article(1, article)

        assert "Citations: 42" in result
        assert "Percentile: 85%" in result
        assert "RCR: 2.50" in result

    def test_journal_metrics(self) -> None:
        article = FakeArticle(
            journal_metrics=_FakeJournalMetrics(),
        )
        result = _format_article(1, article)

        assert "IF≈5.20" in result
        assert "h-index: 120" in result
        assert "High-tier" in result

    def test_abstract_truncation(self) -> None:
        article = FakeArticle(abstract="A" * 500)
        result = _format_article(1, article)
        assert "..." in result
        # Should not contain full 500 chars
        assert "A" * 500 not in result

    def test_no_abstract(self) -> None:
        article = FakeArticle(abstract=None)
        result = _format_article(1, article)
        # Should not have blockquote
        assert "> " not in result

    def test_ranking_score(self) -> None:
        article = FakeArticle(ranking_score=0.92)
        result = _format_article(1, article)
        assert "score: 0.92" in result

    def test_no_ranking_score(self) -> None:
        article = FakeArticle(ranking_score=None)
        result = _format_article(1, article)
        assert "score:" not in result

    def test_sources_listed(self) -> None:
        article = FakeArticle(
            sources=[_FakeSourceMeta("pubmed"), _FakeSourceMeta("openalex")],
        )
        result = _format_article(1, article)
        assert "pubmed" in result
        assert "openalex" in result

    def test_pmc_id(self) -> None:
        article = FakeArticle(pmc="PMC7096777")
        result = _format_article(1, article)
        assert "PMC: PMC7096777" in result

    def test_article_type_badge(self) -> None:
        from pubmed_search.domain.entities.article import ArticleType

        article = FakeArticle(article_type=ArticleType.META_ANALYSIS)
        result = _format_article(1, article)
        assert "🟢 Meta-Analysis (1a)" in result


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _section_articles
# ═══════════════════════════════════════════════════════════════════════════


class TestSectionArticles:
    def test_respects_limit(self) -> None:
        articles = _make_articles(10)
        config = _make_config(limit=5)
        result = _section_articles(articles, config)

        assert "Top 5 Articles" in result
        assert "5 more articles not shown" in result

    def test_no_overflow_message_when_within_limit(self) -> None:
        articles = _make_articles(3)
        config = _make_config(limit=10)
        result = _section_articles(articles, config)

        assert "more articles not shown" not in result

    def test_empty_articles(self) -> None:
        config = _make_config()
        result = _section_articles([], config)
        assert "*No articles found.*" in result


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _section_methodology_notes
# ═══════════════════════════════════════════════════════════════════════════


class TestSectionMethodologyNotes:
    def test_pipeline_config_summary(self) -> None:
        config = _make_config(name="My Pipeline", ranking="quality")
        step_results = _make_step_results(config)
        result = _section_methodology_notes([], step_results, config)

        assert "My Pipeline" in result
        assert "quality" in result
        assert "search → metrics" in result

    def test_suggests_metrics_when_missing(self) -> None:
        config = _make_config(
            steps=[PipelineStep(id="s1", action="search", params={"query": "test"})],
        )
        articles = _make_articles(3)
        step_results = _make_step_results(config, article_counts={"s1": 3})
        result = _section_methodology_notes(articles, step_results, config)

        assert "metrics" in result.lower()

    def test_warns_about_error_steps(self) -> None:
        config = _make_config()
        step_results = _make_step_results(config, errors={"metrics_1": "timeout"})
        result = _section_methodology_notes([], step_results, config)

        assert "metrics_1" in result
        assert "errors" in result.lower()

    def test_truncation_warning(self) -> None:
        config = _make_config(limit=5)
        articles = _make_articles(10)
        step_results = _make_step_results(config)
        result = _section_methodology_notes(articles, step_results, config)

        assert "truncated" in result.lower()

    def test_no_abstract_warning(self) -> None:
        articles = [
            FakeArticle(abstract=None),
            FakeArticle(abstract="Has abstract"),
            FakeArticle(abstract=None),
        ]
        config = _make_config(limit=10)
        step_results = _make_step_results(config)
        result = _section_methodology_notes(articles, step_results, config)

        assert "2 articles have no abstract" in result

    def test_next_steps_section(self) -> None:
        config = _make_config()
        step_results = _make_step_results(config)
        result = _section_methodology_notes([], step_results, config)

        assert "Next Steps" in result
        assert "get_session_pmids" in result
        assert "prepare_export" in result


# ═══════════════════════════════════════════════════════════════════════════
# Tests: Edge Cases
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_unnamed_pipeline(self) -> None:
        config = _make_config(name="")
        config.name = None
        step_results = _make_step_results(config)
        report = generate_pipeline_report([], step_results, config)

        assert "Pipeline" in report

    def test_very_long_error_message(self) -> None:
        config = _make_config()
        long_error = "E" * 200
        step_results = _make_step_results(config, errors={"search_1": long_error})
        result = _section_step_details(step_results, config)

        # Error should be truncated to 80 chars in table
        assert "E" * 80 in result
        # Full error in detail section
        assert long_error in result

    def test_single_step_pipeline(self) -> None:
        config = _make_config(
            steps=[PipelineStep(id="s1", action="search", params={"query": "test"})],
        )
        articles = _make_articles(3)
        step_results = _make_step_results(config, article_counts={"s1": 3})
        report = generate_pipeline_report(articles, step_results, config)

        assert "1/1" in report

    def test_large_article_set(self) -> None:
        """Ensure report renders cleanly with many articles."""
        config = _make_config(limit=100)
        articles = _make_articles(50)
        step_results = _make_step_results(config, article_counts={"search_1": 50})
        report = generate_pipeline_report(articles, step_results, config)

        assert "Top 50 Articles" in report
        # Check first and last article are present
        assert "Article 0" in report
        assert "Article 49" in report

    def test_multi_source_aggregation(self) -> None:
        """Test source statistics with overlapping sources across steps."""
        steps = [
            PipelineStep(id="s1", action="search", params={"query": "a"}),
            PipelineStep(id="s2", action="search", params={"query": "b"}),
            PipelineStep(id="m1", action="merge", inputs=["s1", "s2"]),
        ]
        config = _make_config(steps=steps)
        step_results = _make_step_results(
            config,
            article_counts={"s1": 10, "s2": 8, "m1": 15},
            source_counts={
                "s1": {"pubmed": 10},
                "s2": {"pubmed": 5, "openalex": 3},
            },
        )
        result = _section_source_statistics(step_results)

        assert "pubmed" in result
        assert "15" in result  # 10 + 5
        assert "openalex" in result
