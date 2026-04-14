"""Tests for Unified Search MCP tools — unified_search, analyze_search_query, helpers."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pubmed_search.application.search.query_analyzer import (
    AnalyzedQuery,
    QueryComplexity,
    QueryIntent,
)
from pubmed_search.application.search.result_aggregator import (
    AggregationStats,
    RankingConfig,
)
from pubmed_search.presentation.mcp_server.tools.unified import (
    DispatchStrategy,
    _format_as_json,
    _format_unified_results,
    _is_preprint,
    detect_and_expand_icd_codes,
    register_unified_search_tools,
)

# ============================================================
# ICD Detection
# ============================================================


class TestDetectAndExpandIcdCodes:
    async def test_no_icd_codes(self):
        expanded, matches = detect_and_expand_icd_codes("diabetes treatment")
        assert matches == []
        assert expanded == "diabetes treatment"

    async def test_icd10_code_detected(self):
        with patch(
            "pubmed_search.presentation.mcp_server.tools.unified_helpers.lookup_icd_to_mesh",
            return_value={"mesh": "Diabetes Mellitus, Type 2", "description": "T2DM"},
        ):
            expanded, matches = detect_and_expand_icd_codes("E11 complications")
        assert len(matches) == 1
        assert matches[0]["code"] == "E11"
        assert "MeSH" in expanded

    async def test_no_mapping_found(self):
        with patch(
            "pubmed_search.presentation.mcp_server.tools.unified_helpers.lookup_icd_to_mesh",
            return_value=None,
        ):
            expanded, matches = detect_and_expand_icd_codes("E11 complications")
        assert matches == []


# ============================================================
# DispatchStrategy
# ============================================================


class TestDispatchStrategy:
    def _make_analysis(self, complexity, intent, identifiers=None, year_from=None):
        a = MagicMock(spec=AnalyzedQuery)
        a.complexity = complexity
        a.intent = intent
        a.identifiers = identifiers or []
        a.year_from = year_from
        return a

    async def test_lookup_with_identifiers(self):
        a = self._make_analysis(QueryComplexity.SIMPLE, QueryIntent.LOOKUP, identifiers=["PMID:123"])
        sources = DispatchStrategy.get_sources(a)
        assert sources == ["pubmed"]

    async def test_lookup_without_identifiers(self):
        a = self._make_analysis(QueryComplexity.SIMPLE, QueryIntent.LOOKUP)
        sources = DispatchStrategy.get_sources(a)
        assert "crossref" in sources

    async def test_simple_exploration(self):
        a = self._make_analysis(QueryComplexity.SIMPLE, QueryIntent.EXPLORATION)
        sources = DispatchStrategy.get_sources(a)
        assert sources == ["pubmed"]

    async def test_moderate(self):
        a = self._make_analysis(QueryComplexity.MODERATE, QueryIntent.EXPLORATION)
        sources = DispatchStrategy.get_sources(a)
        assert "crossref" in sources

    async def test_complex_comparison(self):
        a = self._make_analysis(QueryComplexity.COMPLEX, QueryIntent.COMPARISON)
        sources = DispatchStrategy.get_sources(a)
        assert "openalex" in sources

    async def test_complex_systematic(self):
        a = self._make_analysis(QueryComplexity.COMPLEX, QueryIntent.SYSTEMATIC)
        sources = DispatchStrategy.get_sources(a)
        assert "europe_pmc" in sources

    async def test_ambiguous(self):
        a = self._make_analysis(QueryComplexity.AMBIGUOUS, QueryIntent.EXPLORATION)
        sources = DispatchStrategy.get_sources(a)
        assert "openalex" in sources

    async def test_ranking_config_systematic(self):
        a = self._make_analysis(QueryComplexity.COMPLEX, QueryIntent.SYSTEMATIC)
        config = DispatchStrategy.get_ranking_config(a)
        assert isinstance(config, RankingConfig)

    async def test_ranking_config_comparison(self):
        a = self._make_analysis(QueryComplexity.COMPLEX, QueryIntent.COMPARISON)
        config = DispatchStrategy.get_ranking_config(a)
        assert isinstance(config, RankingConfig)

    async def test_ranking_config_recency(self):
        a = self._make_analysis(QueryComplexity.SIMPLE, QueryIntent.EXPLORATION, year_from=2023)
        config = DispatchStrategy.get_ranking_config(a)
        assert isinstance(config, RankingConfig)

    async def test_should_enrich_systematic(self):
        a = self._make_analysis(QueryComplexity.COMPLEX, QueryIntent.SYSTEMATIC)
        assert DispatchStrategy.should_enrich_with_unpaywall(a) is True

    async def test_should_not_enrich_simple(self):
        a = self._make_analysis(QueryComplexity.SIMPLE, QueryIntent.EXPLORATION)
        assert DispatchStrategy.should_enrich_with_unpaywall(a) is False

    async def test_disabled_sources_are_filtered(self):
        a = self._make_analysis(QueryComplexity.COMPLEX, QueryIntent.COMPARISON)
        with patch.dict("os.environ", {"PUBMED_SEARCH_DISABLED_SOURCES": "semantic_scholar"}, clear=False):
            sources = DispatchStrategy.get_sources(a)
        assert "semantic_scholar" not in sources
        assert "openalex" in sources

    async def test_enabled_commercial_sources_are_not_auto_dispatched(self):
        a = self._make_analysis(QueryComplexity.COMPLEX, QueryIntent.SYSTEMATIC)
        with patch.dict(
            "os.environ",
            {
                "SCOPUS_ENABLED": "true",
                "SCOPUS_API_KEY": "licensed-key",
                "WEB_OF_SCIENCE_ENABLED": "true",
                "WEB_OF_SCIENCE_API_KEY": "licensed-key",
            },
            clear=False,
        ):
            sources = DispatchStrategy.get_sources(a)
        assert "scopus" not in sources
        assert "web_of_science" not in sources


# ============================================================
# Format functions
# ============================================================


class TestFormatAsJson:
    async def test_basic(self):
        analysis = MagicMock(spec=AnalyzedQuery)
        analysis.original_query = "test"
        analysis.intent = QueryIntent.EXPLORATION
        analysis.to_dict.return_value = {"query": "test"}
        stats = MagicMock(spec=AggregationStats)
        stats.to_dict.return_value = {"unique": 0}
        result = _format_as_json([], analysis, stats)
        parsed = json.loads(result)
        assert "analysis" in parsed
        assert "articles" in parsed

    async def test_counts_first_orientation_payload(self):
        analysis = MagicMock(spec=AnalyzedQuery)
        analysis.original_query = "remimazolam sedation"
        analysis.intent = QueryIntent.EXPLORATION
        analysis.to_dict.return_value = {"query": "remimazolam sedation"}

        stats = MagicMock(spec=AggregationStats)
        stats.to_dict.return_value = {"unique_articles": 2}
        stats.by_source = {"pubmed": 2}

        article = MagicMock()
        article.pmid = "12345678"
        article.pmc = "PMC1234567"
        article.to_dict.return_value = {"pmid": "12345678"}

        result = _format_as_json(
            [article],
            analysis,
            stats,
            source_api_counts={"pubmed": (2, 25)},
            counts_first=True,
        )

        parsed = json.loads(result)
        assert parsed["orientation"]["mode"] == "counts_first"
        assert parsed["orientation"]["source_counts"][0]["source"] == "pubmed"
        assert parsed["orientation"]["next_actions"]
        assert parsed["orientation"]["next_actions"][0]["tool"] == "unified_search"
        assert parsed["tool"] == "unified_search"
        assert parsed["source_counts"][0]["source"] == "pubmed"
        assert parsed["next_tools"]
        assert parsed["next_commands"]
        assert parsed["section_provenance"]["articles"]["provenance"] == "mixed"


class TestFormatUnifiedResults:
    async def test_no_articles(self):
        analysis = MagicMock(spec=AnalyzedQuery)
        analysis.original_query = "test"
        analysis.complexity = QueryComplexity.SIMPLE
        analysis.intent = QueryIntent.EXPLORATION
        analysis.pico = None
        stats = MagicMock(spec=AggregationStats)
        stats.by_source = {}
        stats.unique_articles = 0
        stats.duplicates_removed = 0

        result = await _format_unified_results([], analysis, stats, include_analysis=False, include_trials=False)
        assert "No results" in result

    async def test_source_api_counts_displayed(self):
        """Per-source API return counts MUST be displayed to agents (critical feature)."""
        analysis = MagicMock(spec=AnalyzedQuery)
        analysis.original_query = "test query"
        analysis.complexity = QueryComplexity.SIMPLE
        analysis.intent = QueryIntent.EXPLORATION
        analysis.pico = None

        stats = MagicMock(spec=AggregationStats)
        stats.by_source = {"pubmed": 8, "openalex": 5}
        stats.unique_articles = 10
        stats.duplicates_removed = 3

        # With explicit source_api_counts (returned/total)
        result = await _format_unified_results(
            [],
            analysis,
            stats,
            include_analysis=True,
            include_trials=False,
            source_api_counts={"pubmed": (8, 150), "openalex": (5, None)},
        )
        assert "pubmed (8/150)" in result
        assert "openalex (5)" in result

    async def test_source_counts_fallback_to_by_source(self):
        """When source_api_counts is None, use stats.by_source with counts."""
        analysis = MagicMock(spec=AnalyzedQuery)
        analysis.original_query = "test query"
        analysis.complexity = QueryComplexity.SIMPLE
        analysis.intent = QueryIntent.EXPLORATION
        analysis.pico = None

        stats = MagicMock(spec=AggregationStats)
        stats.by_source = {"pubmed": 8, "europe_pmc": 5}
        stats.unique_articles = 10
        stats.duplicates_removed = 3

        result = await _format_unified_results(
            [],
            analysis,
            stats,
            include_analysis=True,
            include_trials=False,
            source_api_counts=None,
        )
        # Should still show counts, not just source names
        assert "pubmed (8)" in result
        assert "europe_pmc (5)" in result

    async def test_source_counts_never_names_only(self):
        """GUARD: Sources line must NEVER show only names without counts."""
        analysis = MagicMock(spec=AnalyzedQuery)
        analysis.original_query = "guard test"
        analysis.complexity = QueryComplexity.MODERATE
        analysis.intent = QueryIntent.EXPLORATION
        analysis.pico = None

        stats = MagicMock(spec=AggregationStats)
        stats.by_source = {"pubmed": 12, "semantic_scholar": 7}
        stats.unique_articles = 15
        stats.duplicates_removed = 4

        result = await _format_unified_results(
            [],
            analysis,
            stats,
            include_analysis=True,
            include_trials=False,
        )
        # Ensure counts appear — NOT just "pubmed, semantic_scholar"
        assert "**Sources**:" in result
        sources_line = [line for line in result.split("\\n") if "**Sources**:" in line]
        if not sources_line:
            sources_line = [line for line in result.split("\n") if "**Sources**:" in line]
        assert sources_line, "Sources line must exist in output"
        # Must contain parenthesized counts
        line = sources_line[0]
        assert "(" in line and ")" in line, f"Source counts missing in: {line}"

    async def test_does_not_fetch_trials_inline_during_formatting(self):
        from pubmed_search.domain.entities.article import UnifiedArticle

        analysis = MagicMock(spec=AnalyzedQuery)
        analysis.original_query = "dexmedetomidine bladder discomfort"
        analysis.complexity = QueryComplexity.MODERATE
        analysis.intent = QueryIntent.COMPARISON
        analysis.pico = None

        stats = MagicMock(spec=AggregationStats)
        stats.by_source = {"pubmed": 1}
        stats.unique_articles = 1
        stats.duplicates_removed = 0

        article = UnifiedArticle(title="Trial article", primary_source="pubmed")

        with patch(
            "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
            new=AsyncMock(),
        ) as mock_search_trials:
            result = await _format_unified_results(
                [article],
                analysis,
                stats,
                include_trials=True,
                original_query=analysis.original_query,
                prefetched_trials=None,
            )

        mock_search_trials.assert_not_awaited()
        assert "Clinical Trials" not in result

    async def test_counts_first_section_includes_next_tools(self):
        analysis = MagicMock(spec=AnalyzedQuery)
        analysis.original_query = "remimazolam sedation"
        analysis.complexity = QueryComplexity.MODERATE
        analysis.intent = QueryIntent.EXPLORATION
        analysis.pico = None

        stats = MagicMock(spec=AggregationStats)
        stats.by_source = {"pubmed": 2, "openalex": 1}
        stats.unique_articles = 2
        stats.duplicates_removed = 1

        article = MagicMock()
        article.title = "Lead Article"
        article.ranking_score = 0.9
        article.pmid = "12345678"
        article.pmc = "PMC1234567"
        article.doi = None
        article.article_type = None
        article.author_string = "A B"
        article.journal = "Journal"
        article.year = 2025
        article.volume = None
        article.issue = None
        article.pages = None
        article.has_open_access = False
        article.best_oa_link = None
        article.citation_metrics = None
        article.journal_metrics = None
        article.similarity_score = None
        article.similarity_source = None
        article.abstract = "Short abstract"
        article.sources = [MagicMock(source="pubmed")]

        result = await _format_unified_results(
            [article],
            analysis,
            stats,
            include_analysis=True,
            include_trials=False,
            source_api_counts={"pubmed": (2, 25), "openalex": (1, None)},
            counts_first=True,
        )

        assert "Count-First Orientation" in result
        assert "| pubmed | 2 | 25 | backlog |" in result
        assert "Next Tools" in result
        assert "fetch_article_details" in result
        assert "get_article_figures" in result
        assert "**Sources**:" not in result


# ============================================================
# Tool capture and registration
# ============================================================


def _capture_tools(mcp, searcher):
    tools = {}

    def _tool(*decorator_args, **decorator_kwargs):
        del decorator_args, decorator_kwargs

        def _decorator(func):
            tools[func.__name__] = func
            return func

        return _decorator

    mcp.tool = _tool
    register_unified_search_tools(mcp, searcher)
    return tools


class TestUnifiedSearch:
    @pytest.mark.asyncio
    async def test_empty_query(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        tools = _capture_tools(mcp, searcher)
        result = await tools["unified_search"](query="")
        assert "error" in result.lower() or "empty" in result.lower()

    @pytest.mark.asyncio
    async def test_simple_pubmed_search(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        searcher.search.return_value = [{"pmid": "123", "title": "Test Article", "authors": ["A B"]}]
        tools = _capture_tools(mcp, searcher)

        with patch(
            "pubmed_search.presentation.mcp_server.tools.unified.get_semantic_enhancer",
        ) as mock_enhancer:
            mock_enhancer.return_value.enhance.side_effect = Exception("skip")
            result = await tools["unified_search"](
                query="diabetes",
                limit=5,
                options="no_analysis, no_scores",
            )
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_json_output(self):
        """unified_search with json format - may return JSON or error string depending on dispatch."""
        mcp = MagicMock()
        searcher = AsyncMock()
        searcher.search.return_value = [{"pmid": "123", "title": "Test", "authors": ["X"]}]
        tools = _capture_tools(mcp, searcher)

        with patch(
            "pubmed_search.presentation.mcp_server.tools.unified.get_semantic_enhancer",
        ) as mock_enhancer:
            mock_enhancer.return_value.enhance.side_effect = Exception("skip")
            result = await tools["unified_search"](query="test", output_format="json", options="no_scores")
        assert isinstance(result, str)
        # Result is either valid JSON or an error/no-results message
        try:
            parsed = json.loads(result)
            assert isinstance(parsed, dict)
        except json.JSONDecodeError:
            assert "no results" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_context_graph_markdown_output(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        searcher.search.return_value = [{"pmid": "123", "title": "Test Article", "authors": ["A B"]}]
        searcher.fetch_details.return_value = [{"pmid": "123", "title": "Timeline Article", "year": 2020}]
        tools = _capture_tools(mcp, searcher)

        fake_timeline = MagicMock()
        fake_timeline.events = [MagicMock()]
        fake_tree = MagicMock()
        fake_tree.to_text_tree.return_value = "## Research Tree: test\nBranch A"

        with (
            patch("pubmed_search.presentation.mcp_server.tools.unified.get_semantic_enhancer") as mock_enhancer,
            patch("pubmed_search.presentation.mcp_server.tools.unified.TimelineBuilder") as MockTimelineBuilder,
            patch("pubmed_search.presentation.mcp_server.tools.unified.build_research_tree", return_value=fake_tree),
        ):
            mock_enhancer.return_value.enhance.side_effect = Exception("skip")
            MockTimelineBuilder.return_value.build_timeline_from_pmids = AsyncMock(return_value=fake_timeline)
            result = await tools["unified_search"](query="test", options="context_graph,no_scores")

        assert "Research Context Graph" in result
        assert "Research Tree: test" in result

    @pytest.mark.asyncio
    async def test_context_graph_json_output(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        searcher.search.return_value = [{"pmid": "123", "title": "Test Article", "authors": ["A B"]}]
        searcher.fetch_details.return_value = [{"pmid": "123", "title": "Timeline Article", "year": 2020}]
        tools = _capture_tools(mcp, searcher)

        fake_timeline = MagicMock()
        fake_timeline.events = [MagicMock()]
        fake_tree = MagicMock()
        fake_tree.to_text_tree.return_value = "## Research Tree: test\nBranch A"
        fake_tree.to_dict.return_value = {"topic": "test", "branches": [{"label": "Branch A"}]}

        with (
            patch("pubmed_search.presentation.mcp_server.tools.unified.get_semantic_enhancer") as mock_enhancer,
            patch("pubmed_search.presentation.mcp_server.tools.unified.TimelineBuilder") as MockTimelineBuilder,
            patch("pubmed_search.presentation.mcp_server.tools.unified.build_research_tree", return_value=fake_tree),
        ):
            mock_enhancer.return_value.enhance.side_effect = Exception("skip")
            MockTimelineBuilder.return_value.build_timeline_from_pmids = AsyncMock(return_value=fake_timeline)
            result = await tools["unified_search"](
                query="test", output_format="json", options="context_graph,no_scores"
            )

        parsed = json.loads(result)
        assert parsed["research_context"]["topic"] == "test"
        assert parsed["research_context"]["branches"][0]["label"] == "Branch A"

    @pytest.mark.asyncio
    async def test_exception_handling(self):
        """When PubMed search fails internally, unified_search still returns results (empty)."""
        mcp = MagicMock()
        searcher = AsyncMock()
        searcher.search.side_effect = RuntimeError("Network error")
        tools = _capture_tools(mcp, searcher)

        with patch(
            "pubmed_search.presentation.mcp_server.tools.unified.get_semantic_enhancer",
        ) as mock_enhancer:
            mock_enhancer.return_value.enhance.side_effect = Exception("skip")
            result = await tools["unified_search"](query="test")
        # PubMed exception is caught in _search_pubmed, so result is "No results"
        assert "no results" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_markdown_output_does_not_block_on_slow_clinical_trials(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        searcher.search.return_value = [
            {
                "pmid": "12345",
                "title": "Dexmedetomidine and CRBD",
                "authors": ["A B"],
            }
        ]
        tools = _capture_tools(mcp, searcher)

        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def _slow_trials(*args, **kwargs):
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.unified.get_semantic_enhancer",
            ) as mock_enhancer,
            patch(
                "pubmed_search.infrastructure.sources.clinical_trials.search_related_trials",
                side_effect=_slow_trials,
            ),
        ):
            mock_enhancer.return_value.enhance.side_effect = Exception("skip")
            result = await asyncio.wait_for(
                tools["unified_search"](
                    query="dexmedetomidine bladder discomfort",
                    output_format="markdown",
                    options="no_scores",
                ),
                timeout=2.0,
            )

        assert started.is_set()
        assert cancelled.is_set()
        assert "Dexmedetomidine and CRBD" in result

    @pytest.mark.asyncio
    async def test_auto_source_exclusion_skips_semantic_scholar(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        searcher.search.return_value = [{"pmid": "123", "title": "Test Article", "authors": ["A B"]}]
        tools = _capture_tools(mcp, searcher)

        analysis = MagicMock(spec=AnalyzedQuery)
        analysis.original_query = "comparison query"
        analysis.complexity = QueryComplexity.COMPLEX
        analysis.intent = QueryIntent.COMPARISON
        analysis.identifiers = []
        analysis.year_from = None
        analysis.year_to = None
        analysis.pico = None

        with (
            patch("pubmed_search.presentation.mcp_server.tools.unified.QueryAnalyzer") as MockAnalyzer,
            patch("pubmed_search.presentation.mcp_server.tools.unified.get_semantic_enhancer") as mock_enhancer,
            patch("pubmed_search.presentation.mcp_server.tools.unified._search_openalex", new_callable=AsyncMock) as mock_openalex,
            patch(
                "pubmed_search.presentation.mcp_server.tools.unified._search_semantic_scholar",
                new_callable=AsyncMock,
            ) as mock_semantic,
        ):
            MockAnalyzer.return_value.analyze.return_value = analysis
            mock_enhancer.return_value.enhance.side_effect = Exception("skip")
            mock_openalex.return_value = ([], None)
            mock_semantic.return_value = ([], None)

            await tools["unified_search"](
                query="comparison query",
                sources="auto,-semantic_scholar",
                options="no_analysis, no_scores, shallow",
            )

        mock_openalex.assert_awaited_once()
        mock_semantic.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_explicit_scopus_source_uses_scopus_runner_when_enabled(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        tools = _capture_tools(mcp, searcher)

        analysis = MagicMock(spec=AnalyzedQuery)
        analysis.original_query = "licensed query"
        analysis.complexity = QueryComplexity.SIMPLE
        analysis.intent = QueryIntent.EXPLORATION
        analysis.identifiers = []
        analysis.year_from = None
        analysis.year_to = None
        analysis.pico = None

        with (
            patch.dict("os.environ", {"SCOPUS_ENABLED": "true", "SCOPUS_API_KEY": "licensed-key"}, clear=False),
            patch("pubmed_search.presentation.mcp_server.tools.unified.QueryAnalyzer") as MockAnalyzer,
            patch("pubmed_search.presentation.mcp_server.tools.unified._search_scopus", new_callable=AsyncMock) as mock_scopus,
        ):
            MockAnalyzer.return_value.analyze.return_value = analysis
            mock_scopus.return_value = ([], None)

            await tools["unified_search"](
                query="licensed query",
                sources="scopus",
                options="no_analysis, no_scores, shallow",
            )

        mock_scopus.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_explicit_web_of_science_source_uses_runner_when_enabled(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        tools = _capture_tools(mcp, searcher)

        analysis = MagicMock(spec=AnalyzedQuery)
        analysis.original_query = "licensed query"
        analysis.complexity = QueryComplexity.SIMPLE
        analysis.intent = QueryIntent.EXPLORATION
        analysis.identifiers = []
        analysis.year_from = None
        analysis.year_to = None
        analysis.pico = None

        with (
            patch.dict(
                "os.environ",
                {"WEB_OF_SCIENCE_ENABLED": "true", "WEB_OF_SCIENCE_API_KEY": "licensed-key"},
                clear=False,
            ),
            patch("pubmed_search.presentation.mcp_server.tools.unified.QueryAnalyzer") as MockAnalyzer,
            patch(
                "pubmed_search.presentation.mcp_server.tools.unified._search_web_of_science",
                new_callable=AsyncMock,
            ) as mock_wos,
        ):
            MockAnalyzer.return_value.analyze.return_value = analysis
            mock_wos.return_value = ([], None)

            await tools["unified_search"](
                query="licensed query",
                sources="web_of_science",
                options="no_analysis, no_scores, shallow",
            )

        mock_wos.assert_awaited_once()


class TestAnalyzeSearchQuery:
    @pytest.mark.asyncio
    async def test_empty_query(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        tools = _capture_tools(mcp, searcher)
        result = await tools["analyze_search_query"](query="")
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_basic_analysis(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        tools = _capture_tools(mcp, searcher)
        result = await tools["analyze_search_query"](query="diabetes treatment")
        assert "Query Analysis" in result or "Complexity" in result

    @pytest.mark.asyncio
    async def test_exception(self):
        mcp = MagicMock()
        searcher = AsyncMock()
        tools = _capture_tools(mcp, searcher)

        with patch("pubmed_search.presentation.mcp_server.tools.unified.QueryAnalyzer") as MockAnalyzer:
            MockAnalyzer.return_value.analyze.side_effect = RuntimeError("fail")
            result = await tools["analyze_search_query"](query="test")
        assert "error" in result.lower()


# ============================================================
# _is_preprint helper
# ============================================================


class TestIsPreprint:
    async def test_article_type_preprint(self):
        """Articles with article_type=PREPRINT are preprints."""
        from pubmed_search.domain.entities.article import ArticleType, UnifiedArticle

        a = UnifiedArticle(
            title="T",
            primary_source="openalex",
            article_type=ArticleType.PREPRINT,
        )
        assert _is_preprint(a, ArticleType) is True

    async def test_arxiv_without_pmid(self):
        """ArXiv ID + no PMID = preprint."""
        from pubmed_search.domain.entities.article import ArticleType, UnifiedArticle

        a = UnifiedArticle(
            title="T",
            primary_source="semantic_scholar",
            arxiv_id="2301.12345",
            article_type=ArticleType.UNKNOWN,
        )
        assert _is_preprint(a, ArticleType) is True

    async def test_arxiv_with_pmid_not_preprint(self):
        """ArXiv ID + PMID = published, not preprint."""
        from pubmed_search.domain.entities.article import ArticleType, UnifiedArticle

        a = UnifiedArticle(
            title="T",
            primary_source="semantic_scholar",
            arxiv_id="2301.12345",
            pmid="12345",
            article_type=ArticleType.JOURNAL_ARTICLE,
        )
        assert _is_preprint(a, ArticleType) is False

    async def test_preprint_primary_source(self):
        """Primary source from preprint server = preprint."""
        from pubmed_search.domain.entities.article import ArticleType, UnifiedArticle

        for source in ["arxiv", "medrxiv", "biorxiv"]:
            a = UnifiedArticle(
                title="T",
                primary_source=source,
                article_type=ArticleType.UNKNOWN,
            )
            assert _is_preprint(a, ArticleType) is True

    async def test_normal_journal_not_preprint(self):
        """Normal journal article is not a preprint."""
        from pubmed_search.domain.entities.article import ArticleType, UnifiedArticle

        a = UnifiedArticle(
            title="T",
            primary_source="pubmed",
            pmid="12345",
            article_type=ArticleType.JOURNAL_ARTICLE,
        )
        assert _is_preprint(a, ArticleType) is False

    async def test_unknown_type_not_preprint(self):
        """UNKNOWN type without arxiv_id is not a preprint."""
        from pubmed_search.domain.entities.article import ArticleType, UnifiedArticle

        a = UnifiedArticle(
            title="T",
            primary_source="openalex",
            article_type=ArticleType.UNKNOWN,
        )
        assert _is_preprint(a, ArticleType) is False

    async def test_doi_biorxiv_medrxiv_prefix(self):
        """DOI starting with 10.1101/ (bioRxiv/medRxiv) is preprint."""
        from pubmed_search.domain.entities.article import ArticleType, UnifiedArticle

        a = UnifiedArticle(
            title="T",
            primary_source="openalex",
            doi="10.1101/2024.01.15.575123",
            article_type=ArticleType.UNKNOWN,
        )
        assert _is_preprint(a, ArticleType) is True

    async def test_doi_arxiv_prefix(self):
        """DOI starting with 10.48550/ (arXiv) is preprint."""
        from pubmed_search.domain.entities.article import ArticleType, UnifiedArticle

        a = UnifiedArticle(
            title="T",
            primary_source="openalex",
            doi="10.48550/arXiv.2301.12345",
            article_type=ArticleType.UNKNOWN,
        )
        assert _is_preprint(a, ArticleType) is True

    async def test_doi_chemrxiv_prefix(self):
        """DOI starting with 10.26434/ (chemRxiv) is preprint."""
        from pubmed_search.domain.entities.article import ArticleType, UnifiedArticle

        a = UnifiedArticle(
            title="T",
            primary_source="openalex",
            doi="10.26434/chemrxiv-2024-abc",
            article_type=ArticleType.UNKNOWN,
        )
        assert _is_preprint(a, ArticleType) is True

    async def test_doi_ssrn_prefix(self):
        """DOI starting with 10.2139/ (SSRN) is preprint."""
        from pubmed_search.domain.entities.article import ArticleType, UnifiedArticle

        a = UnifiedArticle(
            title="T",
            primary_source="openalex",
            doi="10.2139/ssrn.4567890",
            article_type=ArticleType.UNKNOWN,
        )
        assert _is_preprint(a, ArticleType) is True

    async def test_doi_research_square_prefix(self):
        """DOI starting with 10.21203/ (Research Square) is preprint."""
        from pubmed_search.domain.entities.article import ArticleType, UnifiedArticle

        a = UnifiedArticle(
            title="T",
            primary_source="openalex",
            doi="10.21203/rs.3.rs-1234567/v1",
            article_type=ArticleType.UNKNOWN,
        )
        assert _is_preprint(a, ArticleType) is True

    async def test_normal_doi_not_preprint(self):
        """Normal DOI (e.g. 10.1016/) is not a preprint."""
        from pubmed_search.domain.entities.article import ArticleType, UnifiedArticle

        a = UnifiedArticle(
            title="T",
            primary_source="openalex",
            doi="10.1016/j.bja.2024.01.001",
            article_type=ArticleType.UNKNOWN,
        )
        assert _is_preprint(a, ArticleType) is False

    async def test_journal_name_arxiv(self):
        """Journal name containing 'arxiv' is preprint."""
        from pubmed_search.domain.entities.article import ArticleType, UnifiedArticle

        a = UnifiedArticle(
            title="T",
            primary_source="openalex",
            journal="ArXiv",
            article_type=ArticleType.UNKNOWN,
        )
        assert _is_preprint(a, ArticleType) is True

    async def test_journal_name_medrxiv(self):
        """Journal name containing 'medrxiv' is preprint."""
        from pubmed_search.domain.entities.article import ArticleType, UnifiedArticle

        a = UnifiedArticle(
            title="T",
            primary_source="openalex",
            journal="medRxiv (Cold Spring Harbor Laboratory Press)",
            article_type=ArticleType.UNKNOWN,
        )
        assert _is_preprint(a, ArticleType) is True

    async def test_journal_name_biorxiv(self):
        """Journal name containing 'biorxiv' is preprint."""
        from pubmed_search.domain.entities.article import ArticleType, UnifiedArticle

        a = UnifiedArticle(
            title="T",
            primary_source="openalex",
            journal="bioRxiv",
            article_type=ArticleType.UNKNOWN,
        )
        assert _is_preprint(a, ArticleType) is True

    async def test_normal_journal_name_not_preprint(self):
        """Normal journal name is not a preprint."""
        from pubmed_search.domain.entities.article import ArticleType, UnifiedArticle

        a = UnifiedArticle(
            title="T",
            primary_source="openalex",
            journal="British Journal of Anaesthesia",
            article_type=ArticleType.UNKNOWN,
        )
        assert _is_preprint(a, ArticleType) is False
