"""Tests for Unified Search MCP tools — unified_search, analyze_search_query, helpers."""

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
            "pubmed_search.presentation.mcp_server.tools.unified.lookup_icd_to_mesh",
            return_value={"mesh": "Diabetes Mellitus, Type 2", "description": "T2DM"},
        ):
            expanded, matches = detect_and_expand_icd_codes("E11 complications")
        assert len(matches) == 1
        assert matches[0]["code"] == "E11"
        assert "MeSH" in expanded

    async def test_no_mapping_found(self):
        with patch(
            "pubmed_search.presentation.mcp_server.tools.unified.lookup_icd_to_mesh",
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


# ============================================================
# Format functions
# ============================================================


class TestFormatAsJson:
    async def test_basic(self):
        analysis = MagicMock(spec=AnalyzedQuery)
        analysis.to_dict.return_value = {"query": "test"}
        stats = MagicMock(spec=AggregationStats)
        stats.to_dict.return_value = {"unique": 0}
        result = _format_as_json([], analysis, stats)
        parsed = json.loads(result)
        assert "analysis" in parsed
        assert "articles" in parsed


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


# ============================================================
# Tool capture and registration
# ============================================================


def _capture_tools(mcp, searcher):
    tools = {}
    mcp.tool = lambda: lambda func: (tools.__setitem__(func.__name__, func), func)[1]
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
                show_analysis=False,
                include_similarity_scores=False,
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
            result = await tools["unified_search"](query="test", output_format="json", include_similarity_scores=False)
        assert isinstance(result, str)
        # Result is either valid JSON or an error/no-results message
        try:
            parsed = json.loads(result)
            assert isinstance(parsed, dict)
        except json.JSONDecodeError:
            assert "no results" in result.lower() or "error" in result.lower()

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
