"""
Round 6 Coverage Tests - Target: 90%+

Focused on filling coverage gaps in:
- unified.py: _search_* functions, _enrich_* functions, _format_* functions
- query_analyzer.py: more analyzer paths
- _common.py: ResponseFormatter, caching functions
- fulltext_download.py: more async methods
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

# ===========================================================================
# unified.py - Search and Enrich Functions
# ===========================================================================


class TestSearchPubMed:
    """Test _search_pubmed function."""

    async def test_search_pubmed_success(self):
        """Test successful PubMed search."""
        from pubmed_search.domain.entities.article import UnifiedArticle
        from pubmed_search.presentation.mcp_server.tools.unified import _search_pubmed

        mock_searcher = Mock()
        mock_searcher.search = AsyncMock(
            return_value=[
                {
                    "pmid": "12345678",
                    "title": "Test Article",
                    "authors": ["Author A"],
                    "journal": "Test Journal",
                    "year": "2024",
                    "abstract": "Test abstract",
                }
            ]
        )

        articles, total = await _search_pubmed(mock_searcher, "test query", 10, None, None)

        assert len(articles) == 1
        assert isinstance(articles[0], UnifiedArticle)
        assert articles[0].pmid == "12345678"

    async def test_search_pubmed_with_metadata(self):
        """Test PubMed search with _search_metadata in results."""
        from pubmed_search.presentation.mcp_server.tools.unified import _search_pubmed

        mock_searcher = Mock()
        mock_searcher.search = AsyncMock(
            return_value=[
                {"_search_metadata": {"total_count": 500}},
                {
                    "pmid": "12345678",
                    "title": "Test Article",
                    "authors": [],
                    "journal": "J",
                    "year": "2024",
                },
            ]
        )

        articles, total = await _search_pubmed(mock_searcher, "test query", 10, 2020, 2024)

        assert total == 500
        assert len(articles) == 1

    async def test_search_pubmed_empty_metadata(self):
        """Test PubMed search with empty dict after metadata extraction."""
        from pubmed_search.presentation.mcp_server.tools.unified import _search_pubmed

        mock_searcher = Mock()
        mock_searcher.search = AsyncMock(
            return_value=[
                {"_search_metadata": {"total_count": 100}},
            ]
        )

        articles, total = await _search_pubmed(mock_searcher, "test", 10, None, None)

        assert total == 100
        assert len(articles) == 0

    async def test_search_pubmed_error_entry(self):
        """Test PubMed search skips error entries."""
        from pubmed_search.presentation.mcp_server.tools.unified import _search_pubmed

        mock_searcher = Mock()
        mock_searcher.search = AsyncMock(
            return_value=[
                {"error": "Rate limit exceeded"},
                {
                    "pmid": "12345678",
                    "title": "Good Article",
                    "authors": [],
                    "journal": "J",
                    "year": "2024",
                },
            ]
        )

        articles, total = await _search_pubmed(mock_searcher, "test", 10, None, None)

        assert len(articles) == 1
        assert articles[0].pmid == "12345678"

    async def test_search_pubmed_exception(self):
        """Test PubMed search handles exception."""
        from pubmed_search.presentation.mcp_server.tools.unified import _search_pubmed

        mock_searcher = Mock()
        mock_searcher.search = AsyncMock(side_effect=Exception("Network error"))

        articles, total = await _search_pubmed(mock_searcher, "test", 10, None, None)

        assert articles == []
        assert total is None


class TestSearchOpenAlex:
    """Test _search_openalex function."""

    @patch(
        "pubmed_search.presentation.mcp_server.tools.unified.search_alternate_source",
        new_callable=AsyncMock,
    )
    async def test_search_openalex_success(self, mock_search):
        """Test successful OpenAlex search."""
        from pubmed_search.presentation.mcp_server.tools.unified import _search_openalex

        mock_search.return_value = [
            {
                "id": "W12345",
                "title": "OpenAlex Article",
                "doi": "10.1234/test",
                "publication_year": 2024,
                "authorships": [{"author": {"display_name": "Author A"}}],
                "primary_location": {"source": {"display_name": "Journal"}},
                "cited_by_count": 10,
            }
        ]

        articles, total = await _search_openalex("test query", 10, None, None)

        assert len(articles) == 1
        mock_search.assert_called_once_with(
            query="test query",
            source="openalex",
            limit=10,
            min_year=None,
            max_year=None,
        )

    @patch(
        "pubmed_search.presentation.mcp_server.tools.unified.search_alternate_source",
        new_callable=AsyncMock,
    )
    async def test_search_openalex_exception(self, mock_search):
        """Test OpenAlex search handles exception."""
        from pubmed_search.presentation.mcp_server.tools.unified import _search_openalex

        mock_search.side_effect = Exception("API error")

        articles, total = await _search_openalex("test", 10, 2020, 2024)

        assert articles == []
        assert total is None


class TestSearchSemanticScholar:
    """Test _search_semantic_scholar function."""

    @patch(
        "pubmed_search.presentation.mcp_server.tools.unified.search_alternate_source",
        new_callable=AsyncMock,
    )
    async def test_search_s2_success(self, mock_search):
        """Test successful Semantic Scholar search."""
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _search_semantic_scholar,
        )

        mock_search.return_value = [
            {
                "paperId": "abc123",
                "title": "S2 Article",
                "externalIds": {"DOI": "10.1234/test"},
                "year": 2024,
                "authors": [{"name": "Author A"}],
                "citationCount": 5,
            }
        ]

        articles, total = await _search_semantic_scholar("test query", 10, 2020, None)

        assert len(articles) == 1
        mock_search.assert_called_once()

    @patch(
        "pubmed_search.presentation.mcp_server.tools.unified.search_alternate_source",
        new_callable=AsyncMock,
    )
    async def test_search_s2_exception(self, mock_search):
        """Test S2 search handles exception."""
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _search_semantic_scholar,
        )

        mock_search.side_effect = Exception("Rate limit")

        articles, total = await _search_semantic_scholar("test", 10, None, None)

        assert articles == []


class TestSearchCore:
    """Test _search_core function."""

    @patch(
        "pubmed_search.presentation.mcp_server.tools.unified.get_core_client",
    )
    async def test_search_core_success(self, mock_get_client):
        """Test successful CORE search."""
        from pubmed_search.presentation.mcp_server.tools.unified import _search_core

        mock_client = AsyncMock()
        mock_client.search.return_value = {
            "total_hits": 42,
            "results": [
                {
                    "core_id": 152480964,
                    "title": "CORE Article",
                    "authors": ["Author A"],
                    "doi": "10.1234/core-test",
                    "year": 2024,
                    "has_fulltext": True,
                    "download_url": "https://core.ac.uk/download/152480964.pdf",
                }
            ],
        }
        mock_get_client.return_value = mock_client

        articles, total = await _search_core("test query", 10, 2020, None)

        assert len(articles) == 1
        assert articles[0].primary_source == "core"
        assert articles[0].core_id == "152480964"
        assert articles[0].doi == "10.1234/core-test"
        assert total == 42
        mock_client.search.assert_called_once_with(
            query="test query",
            limit=10,
            year_from=2020,
            year_to=None,
        )

    @patch(
        "pubmed_search.presentation.mcp_server.tools.unified.get_core_client",
    )
    async def test_search_core_exception(self, mock_get_client):
        """Test CORE search handles exception."""
        from pubmed_search.presentation.mcp_server.tools.unified import _search_core

        mock_client = AsyncMock()
        mock_client.search.side_effect = Exception("CORE API error")
        mock_get_client.return_value = mock_client

        articles, total = await _search_core("test", 10, None, None)

        assert articles == []
        assert total is None

    @patch(
        "pubmed_search.presentation.mcp_server.tools.unified.get_core_client",
    )
    async def test_search_core_empty_results(self, mock_get_client):
        """Test CORE search with no results."""
        from pubmed_search.presentation.mcp_server.tools.unified import _search_core

        mock_client = AsyncMock()
        mock_client.search.return_value = {"total_hits": 0, "results": []}
        mock_get_client.return_value = mock_client

        articles, total = await _search_core("obscure query", 10, None, None)

        assert articles == []
        assert total == 0


class TestEnrichWithCrossRef:
    """Test _enrich_with_crossref function."""

    @patch("pubmed_search.presentation.mcp_server.tools.unified.get_crossref_client")
    async def test_enrich_no_articles(self, mock_get_client):
        """Test enrichment with empty list."""
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_crossref,
        )

        await _enrich_with_crossref([])
        # Function exits early after getting client, no work calls
        mock_get_client.assert_called_once()

    @patch("pubmed_search.presentation.mcp_server.tools.unified.get_crossref_client")
    async def test_enrich_no_doi(self, mock_get_client):
        """Test enrichment skips articles without DOI."""
        from pubmed_search.domain.entities.article import UnifiedArticle
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_crossref,
        )

        article = UnifiedArticle(pmid="123", title="Test", doi=None, primary_source="pubmed")

        await _enrich_with_crossref([article])
        mock_get_client.assert_called_once()

    @patch("pubmed_search.presentation.mcp_server.tools.unified.get_crossref_client")
    async def test_enrich_with_metrics(self, mock_get_client):
        """Test enrichment skips articles that already have metrics."""
        from pubmed_search.domain.entities.article import (
            CitationMetrics,
            UnifiedArticle,
        )
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_crossref,
        )

        article = UnifiedArticle(
            pmid="123",
            title="Test",
            doi="10.1234/test",
            primary_source="pubmed",
            citation_metrics=CitationMetrics(citation_count=10),
        )

        await _enrich_with_crossref([article])
        mock_get_client.assert_called_once()

    @patch("pubmed_search.presentation.mcp_server.tools.unified.get_crossref_client")
    async def test_enrich_crossref_success(self, mock_get_client):
        """Test successful CrossRef enrichment."""
        from pubmed_search.domain.entities.article import UnifiedArticle
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_crossref,
        )

        mock_client = Mock()
        mock_client.get_work = AsyncMock(
            return_value={
                "DOI": "10.1234/test",
                "title": ["Test Title"],
                "is-referenced-by-count": 50,
            }
        )
        mock_get_client.return_value = mock_client

        article = UnifiedArticle(pmid="123", title="Test", doi="10.1234/test", primary_source="pubmed")

        await _enrich_with_crossref([article])
        mock_client.get_work.assert_called()

    @patch("pubmed_search.presentation.mcp_server.tools.unified.get_crossref_client")
    async def test_enrich_crossref_exception(self, mock_get_client):
        """Test CrossRef enrichment handles exception."""
        from pubmed_search.domain.entities.article import UnifiedArticle
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_crossref,
        )

        mock_get_client.side_effect = Exception("API error")

        article = UnifiedArticle(pmid="123", title="Test", doi="10.1234/test", primary_source="pubmed")

        # Should not raise
        await _enrich_with_crossref([article])


class TestEnrichWithUnpaywall:
    """Test _enrich_with_unpaywall function."""

    @patch("pubmed_search.presentation.mcp_server.tools.unified.get_unpaywall_client")
    async def test_enrich_no_articles(self, mock_get_client):
        """Test enrichment with empty list."""
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_unpaywall,
        )

        await _enrich_with_unpaywall([])
        # Function exits early after getting client, no work calls
        mock_get_client.assert_called_once()

    @patch("pubmed_search.presentation.mcp_server.tools.unified.get_unpaywall_client")
    async def test_enrich_already_oa(self, mock_get_client):
        """Test enrichment skips articles that already have OA."""
        from pubmed_search.domain.entities.article import UnifiedArticle
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_unpaywall,
        )

        article = UnifiedArticle(
            pmid="123",
            title="Test",
            doi="10.1234/test",
            primary_source="pubmed",
            is_open_access=True,
        )

        await _enrich_with_unpaywall([article])
        mock_get_client.assert_called_once()

    @patch("pubmed_search.presentation.mcp_server.tools.unified.get_unpaywall_client")
    async def test_enrich_unpaywall_success(self, mock_get_client):
        """Test successful Unpaywall enrichment."""
        from pubmed_search.domain.entities.article import UnifiedArticle
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_unpaywall,
        )

        mock_client = Mock()
        mock_client.enrich_article = AsyncMock(
            return_value={
                "is_oa": True,
                "oa_status": "gold",
                "oa_links": [{"url": "https://example.com/pdf", "version": "published"}],
            }
        )
        mock_get_client.return_value = mock_client

        article = UnifiedArticle(pmid="123", title="Test", doi="10.1234/test", primary_source="pubmed")

        await _enrich_with_unpaywall([article])

        assert article.is_open_access is True

    @patch("pubmed_search.presentation.mcp_server.tools.unified.get_unpaywall_client")
    async def test_enrich_unpaywall_exception(self, mock_get_client):
        """Test Unpaywall enrichment handles exception."""
        from pubmed_search.domain.entities.article import UnifiedArticle
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_unpaywall,
        )

        mock_get_client.side_effect = Exception("API error")

        article = UnifiedArticle(pmid="123", title="Test", doi="10.1234/test", primary_source="pubmed")

        # Should not raise
        await _enrich_with_unpaywall([article])


class TestEnrichWithSimilarityScores:
    """Test _enrich_with_similarity_scores function."""

    async def test_enrich_empty_articles(self):
        """Test enrichment with empty list."""
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_similarity_scores,
        )

        _enrich_with_similarity_scores([], "test query")

    async def test_enrich_single_article(self):
        """Test enrichment with single article."""
        from pubmed_search.domain.entities.article import UnifiedArticle
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_similarity_scores,
        )

        article = UnifiedArticle(pmid="123", title="Test", primary_source="pubmed")

        _enrich_with_similarity_scores([article], "test query")

        assert article.similarity_score is not None
        assert article.similarity_score >= 0.1
        assert article.similarity_score <= 1.0

    async def test_enrich_multiple_articles(self):
        """Test enrichment with multiple articles."""
        from pubmed_search.domain.entities.article import UnifiedArticle
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_similarity_scores,
        )

        articles = [
            UnifiedArticle(pmid="1", title="First", primary_source="pubmed"),
            UnifiedArticle(pmid="2", title="Second", primary_source="openalex"),
            UnifiedArticle(pmid="3", title="Third", primary_source="semantic_scholar"),
        ]

        _enrich_with_similarity_scores(articles, "test query")

        # First article should have highest score
        score0 = articles[0].similarity_score or 0
        score1 = articles[1].similarity_score or 0
        score2 = articles[2].similarity_score or 0
        assert score0 > score1
        assert score1 > score2


class TestEnrichWithApiSimilarity:
    """Test _enrich_with_api_similarity function."""

    async def test_no_seed_pmid(self):
        """Test skips without seed PMID."""
        from pubmed_search.domain.entities.article import UnifiedArticle
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_api_similarity,
        )

        articles = [UnifiedArticle(pmid="123", title="Test", primary_source="pubmed")]

        await _enrich_with_api_similarity(articles, None)

    async def test_empty_articles(self):
        """Test skips with empty list."""
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_api_similarity,
        )

        await _enrich_with_api_similarity([], "seed123")

    @patch("pubmed_search.infrastructure.sources.semantic_scholar.SemanticScholarClient")
    async def test_api_similarity_success(self, mock_s2_class):
        """Test successful API similarity enrichment."""
        from pubmed_search.domain.entities.article import UnifiedArticle
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_api_similarity,
        )

        mock_client = Mock()
        mock_client.get_recommendations = AsyncMock(
            return_value=[
                {"pmid": "123", "similarity_score": 0.9},
                {"doi": "10.1234/test", "similarity_score": 0.8},
            ]
        )
        mock_s2_class.return_value = mock_client

        articles = [
            UnifiedArticle(pmid="123", title="Article 1", primary_source="pubmed"),
            UnifiedArticle(
                pmid="456",
                title="Article 2",
                doi="10.1234/test",
                primary_source="pubmed",
            ),
        ]

        await _enrich_with_api_similarity(articles, "seed_pmid")

        assert articles[0].similarity_score == 0.9
        assert articles[0].similarity_source == "semantic_scholar"

    @patch("pubmed_search.infrastructure.sources.semantic_scholar.SemanticScholarClient")
    async def test_api_similarity_exception(self, mock_s2_class):
        """Test API similarity handles exception."""
        from pubmed_search.domain.entities.article import UnifiedArticle
        from pubmed_search.presentation.mcp_server.tools.unified import (
            _enrich_with_api_similarity,
        )

        mock_s2_class.side_effect = Exception("API error")

        articles = [UnifiedArticle(pmid="123", title="Test", primary_source="pubmed")]

        # Should not raise
        await _enrich_with_api_similarity(articles, "seed")


class TestICDCodeDetection:
    """Test detect_and_expand_icd_codes function."""

    async def test_no_icd_codes(self):
        """Test query with no ICD codes."""
        from pubmed_search.presentation.mcp_server.tools.unified import (
            detect_and_expand_icd_codes,
        )

        query = "diabetes treatment"
        expanded, matches = detect_and_expand_icd_codes(query)

        assert expanded == query
        assert matches == []

    @patch("pubmed_search.presentation.mcp_server.tools.unified.lookup_icd_to_mesh")
    async def test_icd10_code(self, mock_lookup):
        """Test ICD-10 code detection."""
        from pubmed_search.presentation.mcp_server.tools.unified import (
            detect_and_expand_icd_codes,
        )

        mock_lookup.return_value = {
            "mesh": "Diabetes Mellitus, Type 2",
            "description": "Type 2 diabetes",
        }

        query = "E11 complications"
        expanded, matches = detect_and_expand_icd_codes(query)

        assert len(matches) == 1
        assert matches[0]["code"] == "E11"
        assert matches[0]["type"] == "ICD-10"

    @patch("pubmed_search.presentation.mcp_server.tools.unified.lookup_icd_to_mesh")
    async def test_icd9_code(self, mock_lookup):
        """Test ICD-9 code detection."""
        from pubmed_search.presentation.mcp_server.tools.unified import (
            detect_and_expand_icd_codes,
        )

        mock_lookup.return_value = {"mesh": "Heart Infarction", "description": "MI"}

        query = "410.1 treatment"
        expanded, matches = detect_and_expand_icd_codes(query)

        assert len(matches) == 1
        assert matches[0]["type"] == "ICD-9"

    @patch("pubmed_search.presentation.mcp_server.tools.unified.lookup_icd_to_mesh")
    async def test_icd_no_mesh_match(self, mock_lookup):
        """Test ICD code with no MeSH match."""
        from pubmed_search.presentation.mcp_server.tools.unified import (
            detect_and_expand_icd_codes,
        )

        mock_lookup.return_value = None

        query = "E99 treatment"
        expanded, matches = detect_and_expand_icd_codes(query)

        assert matches == []


class TestDispatchStrategyExtended:
    """Extended tests for DispatchStrategy."""

    async def test_get_sources_lookup_with_identifiers(self):
        """Test LOOKUP intent with identifiers."""
        from pubmed_search.application.search.query_analyzer import (
            AnalyzedQuery,
            ExtractedIdentifier,
            QueryComplexity,
            QueryIntent,
        )
        from pubmed_search.presentation.mcp_server.tools.unified import DispatchStrategy

        analysis = AnalyzedQuery(
            original_query="PMID:12345678",
            normalized_query="PMID:12345678",
            complexity=QueryComplexity.SIMPLE,
            intent=QueryIntent.LOOKUP,
            identifiers=[ExtractedIdentifier(type="pmid", value="12345678")],
        )

        sources = DispatchStrategy.get_sources(analysis)
        assert sources == ["pubmed"]

    async def test_get_sources_complex_comparison(self):
        """Test COMPLEX + COMPARISON."""
        from pubmed_search.application.search.query_analyzer import (
            AnalyzedQuery,
            QueryComplexity,
            QueryIntent,
        )
        from pubmed_search.presentation.mcp_server.tools.unified import DispatchStrategy

        analysis = AnalyzedQuery(
            original_query="A vs B",
            normalized_query="A vs B",
            complexity=QueryComplexity.COMPLEX,
            intent=QueryIntent.COMPARISON,
        )

        sources = DispatchStrategy.get_sources(analysis)
        assert sources == ["pubmed", "openalex", "semantic_scholar"]

    async def test_get_sources_complex_systematic(self):
        """Test COMPLEX + SYSTEMATIC."""
        from pubmed_search.application.search.query_analyzer import (
            AnalyzedQuery,
            QueryComplexity,
            QueryIntent,
        )
        from pubmed_search.presentation.mcp_server.tools.unified import DispatchStrategy

        analysis = AnalyzedQuery(
            original_query="systematic review",
            normalized_query="systematic review",
            complexity=QueryComplexity.COMPLEX,
            intent=QueryIntent.SYSTEMATIC,
        )

        sources = DispatchStrategy.get_sources(analysis)
        assert "pubmed" in sources
        assert "europe_pmc" in sources

    async def test_get_ranking_config_comparison(self):
        """Test ranking config for COMPARISON intent."""
        from pubmed_search.application.search.query_analyzer import (
            AnalyzedQuery,
            QueryComplexity,
            QueryIntent,
        )
        from pubmed_search.presentation.mcp_server.tools.unified import DispatchStrategy

        analysis = AnalyzedQuery(
            original_query="A vs B",
            normalized_query="A vs B",
            complexity=QueryComplexity.COMPLEX,
            intent=QueryIntent.COMPARISON,
        )

        config = DispatchStrategy.get_ranking_config(analysis)
        # Should be impact focused
        assert config is not None

    async def test_get_ranking_config_exploration_recent(self):
        """Test ranking config for EXPLORATION with year constraint."""
        from pubmed_search.application.search.query_analyzer import (
            AnalyzedQuery,
            QueryComplexity,
            QueryIntent,
        )
        from pubmed_search.presentation.mcp_server.tools.unified import DispatchStrategy

        analysis = AnalyzedQuery(
            original_query="recent research",
            normalized_query="recent research",
            complexity=QueryComplexity.MODERATE,
            intent=QueryIntent.EXPLORATION,
            year_from=2020,
        )

        config = DispatchStrategy.get_ranking_config(analysis)
        assert config is not None

    async def test_should_enrich_systematic(self):
        """Test should_enrich_with_unpaywall for systematic."""
        from pubmed_search.application.search.query_analyzer import (
            AnalyzedQuery,
            QueryComplexity,
            QueryIntent,
        )
        from pubmed_search.presentation.mcp_server.tools.unified import DispatchStrategy

        analysis = AnalyzedQuery(
            original_query="systematic review",
            normalized_query="systematic review",
            complexity=QueryComplexity.COMPLEX,
            intent=QueryIntent.SYSTEMATIC,
        )

        assert DispatchStrategy.should_enrich_with_unpaywall(analysis) is True

    async def test_should_enrich_simple(self):
        """Test should_enrich_with_unpaywall for simple query."""
        from pubmed_search.application.search.query_analyzer import (
            AnalyzedQuery,
            QueryComplexity,
            QueryIntent,
        )
        from pubmed_search.presentation.mcp_server.tools.unified import DispatchStrategy

        analysis = AnalyzedQuery(
            original_query="diabetes",
            normalized_query="diabetes",
            complexity=QueryComplexity.SIMPLE,
            intent=QueryIntent.EXPLORATION,
        )

        assert DispatchStrategy.should_enrich_with_unpaywall(analysis) is False


# ===========================================================================
# query_analyzer.py - Additional paths
# ===========================================================================


class TestQueryAnalyzerExtended:
    """Extended tests for QueryAnalyzer."""

    async def test_detect_intent_citation_tracking(self):
        """Test detection of citation tracking intent - PMID triggers LOOKUP."""
        from pubmed_search.application.search.query_analyzer import (
            QueryAnalyzer,
            QueryIntent,
        )

        # When query contains PMID, intent becomes LOOKUP (direct identifier)
        analyzer = QueryAnalyzer()
        result = analyzer.analyze("papers citing PMID:12345678")

        # PMID in query triggers LOOKUP intent with direct_lookup strategy
        assert result.intent == QueryIntent.LOOKUP
        assert "direct_lookup" in result.recommended_strategies

    async def test_detect_intent_author_search(self):
        """Test detection of author search intent."""
        from pubmed_search.application.search.query_analyzer import (
            QueryAnalyzer,
            QueryIntent,
        )

        analyzer = QueryAnalyzer()
        result = analyzer.analyze("publications by John Smith Harvard")

        assert result.intent == QueryIntent.AUTHOR_SEARCH

    async def test_detect_pico_with_comparison(self):
        """Test PICO detection with comparison structure."""
        from pubmed_search.application.search.query_analyzer import QueryAnalyzer

        analyzer = QueryAnalyzer()
        result = analyzer.analyze("metformin vs glipizide for diabetes patients on glucose control")

        assert result.pico is not None
        assert result.pico.intervention is not None

    async def test_detect_clinical_etiology(self):
        """Test detection of etiology clinical category."""
        from pubmed_search.application.search.query_analyzer import QueryAnalyzer

        analyzer = QueryAnalyzer()
        result = analyzer.analyze("cause of heart failure pathogenesis")

        assert result.clinical_category == "etiology"

    async def test_detect_clinical_prognosis(self):
        """Test detection of prognosis clinical category."""
        from pubmed_search.application.search.query_analyzer import QueryAnalyzer

        analyzer = QueryAnalyzer()
        result = analyzer.analyze("cancer prognosis survival outcomes")

        assert result.clinical_category == "prognosis"

    async def test_extract_year_range(self):
        """Test year range extraction."""
        from pubmed_search.application.search.query_analyzer import QueryAnalyzer

        analyzer = QueryAnalyzer()
        result = analyzer.analyze("diabetes treatment 2018-2024")

        assert result.year_from == 2018
        assert result.year_to == 2024

    async def test_extract_recent_years(self):
        """Test 'recent' keyword year extraction."""
        from pubmed_search.application.search.query_analyzer import QueryAnalyzer

        analyzer = QueryAnalyzer()
        result = analyzer.analyze("recent diabetes research")

        assert result.year_from is not None
        assert result.year_to is not None

    async def test_ambiguous_single_broad_term(self):
        """Test complexity for single broad term - treated as SIMPLE."""
        from pubmed_search.application.search.query_analyzer import (
            QueryAnalyzer,
            QueryComplexity,
        )

        analyzer = QueryAnalyzer()
        result = analyzer.analyze("cancer")

        # Single clear topic is SIMPLE, but with lower confidence
        assert result.complexity == QueryComplexity.SIMPLE
        assert result.confidence < 0.8  # Low confidence for broad term

    async def test_moderate_multi_term(self):
        """Test moderate complexity for multi-term query."""
        from pubmed_search.application.search.query_analyzer import (
            QueryAnalyzer,
            QueryComplexity,
        )

        analyzer = QueryAnalyzer()
        result = analyzer.analyze("diabetes mellitus treatment guidelines medication")

        assert result.complexity in [QueryComplexity.MODERATE, QueryComplexity.COMPLEX]

    async def test_recommend_strategies_comparison(self):
        """Test strategy recommendations for comparison."""
        from pubmed_search.application.search.query_analyzer import QueryAnalyzer

        analyzer = QueryAnalyzer()
        result = analyzer.analyze("drug A versus drug B")

        assert "pico_search" in result.recommended_strategies or "comparison_filter" in result.recommended_strategies

    async def test_recommend_strategies_systematic(self):
        """Test strategy recommendations for systematic."""
        from pubmed_search.application.search.query_analyzer import QueryAnalyzer

        analyzer = QueryAnalyzer()
        result = analyzer.analyze("systematic review of heart failure treatment")

        assert "pico_search" in result.recommended_strategies

    async def test_to_dict(self):
        """Test AnalyzedQuery to_dict export."""
        from pubmed_search.application.search.query_analyzer import QueryAnalyzer

        analyzer = QueryAnalyzer()
        result = analyzer.analyze("test query 2024")

        d = result.to_dict()

        assert "original_query" in d
        assert "complexity" in d
        assert "intent" in d

    async def test_calculate_confidence_boost(self):
        """Test confidence calculation with boosts."""
        from pubmed_search.application.search.query_analyzer import QueryAnalyzer

        analyzer = QueryAnalyzer()
        result = analyzer.analyze("PMID:12345678")

        # Should have high confidence due to identifier
        assert result.confidence >= 0.7


class TestPICOElements:
    """Test PICOElements dataclass."""

    async def test_is_complete(self):
        """Test is_complete property."""
        from pubmed_search.application.search.query_analyzer import PICOElements

        complete = PICOElements(population="adults", intervention="drug A", outcome="blood pressure")
        assert complete.is_complete is True

        incomplete = PICOElements(population="adults")
        assert incomplete.is_complete is False

    async def test_has_comparison(self):
        """Test has_comparison property."""
        from pubmed_search.application.search.query_analyzer import PICOElements

        with_comp = PICOElements(population="adults", intervention="drug A", comparison="placebo")
        assert with_comp.has_comparison is True

        without_comp = PICOElements(population="adults")
        assert without_comp.has_comparison is False


class TestAnalyzeQueryConvenience:
    """Test analyze_query convenience function."""

    async def test_analyze_query_function(self):
        """Test the convenience function."""
        from pubmed_search.application.search.query_analyzer import analyze_query

        result = analyze_query("test query")
        assert result.original_query == "test query"


# ===========================================================================
# _common.py - ResponseFormatter and caching
# ===========================================================================


class TestResponseFormatterExtended:
    """Extended tests for ResponseFormatter."""

    async def test_success_json_format(self):
        """Test success response in JSON format."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            ResponseFormatter,
        )

        result = ResponseFormatter.success(
            data={"key": "value"},
            message="Success!",
            metadata={"count": 1},
            output_format="json",
        )

        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["data"]["key"] == "value"
        assert parsed["message"] == "Success!"

    async def test_success_markdown_format(self):
        """Test success response in markdown format."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            ResponseFormatter,
        )

        result = ResponseFormatter.success(data="Test result", message="Done", output_format="markdown")

        assert "✅ Done" in result
        assert "Test result" in result

    async def test_success_dict_data(self):
        """Test success with dict data in markdown."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            ResponseFormatter,
        )

        result = ResponseFormatter.success(data={"key": "value"}, output_format="markdown")

        assert '"key"' in result

    async def test_error_json_format(self):
        """Test error response in JSON format."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            ResponseFormatter,
        )

        result = ResponseFormatter.error(
            error="Something failed",
            suggestion="Try again",
            example="do_thing(param=123)",
            tool_name="do_thing",
            output_format="json",
        )

        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "Something failed"
        assert parsed["suggestion"] == "Try again"

    async def test_error_markdown_format(self):
        """Test error response in markdown format."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            ResponseFormatter,
        )

        result = ResponseFormatter.error(
            error="Failed",
            suggestion="Retry",
            example="foo()",
            tool_name="foo",
            output_format="markdown",
        )

        assert "❌" in result
        assert "foo" in result
        assert "💡" in result

    async def test_error_pubmed_search_error(self):
        """Test error with PubMedSearchError."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            ResponseFormatter,
        )
        from pubmed_search.shared import PubMedSearchError

        error = PubMedSearchError("Test error")

        result = ResponseFormatter.error(error, output_format="markdown")
        assert "Test error" in result

    async def test_no_results(self):
        """Test no_results response."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            ResponseFormatter,
        )

        result = ResponseFormatter.no_results(
            query="diabetes",
            suggestions=["Try broader terms", "Check spelling"],
            alternative_tools=["search_europe_pmc"],
        )

        assert "No results found" in result
        assert "diabetes" in result
        assert "broader terms" in result

    async def test_partial_success(self):
        """Test partial_success response."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            ResponseFormatter,
        )

        result = ResponseFormatter.partial_success(
            successful=[1, 2, 3],
            failed=[{"id": "4", "error": "Not found"}],
            message="3 processed, 1 failed",
        )

        assert "3 processed" in result
        assert "Not found" in result


class TestCacheFunctions:
    """Test caching functions."""

    async def test_get_last_search_pmids_no_manager(self):
        """Test get_last_search_pmids without session manager."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            get_last_search_pmids,
            set_session_manager,
        )

        set_session_manager(None)
        result = get_last_search_pmids()
        assert result == []

    async def test_get_last_search_pmids_with_manager(self):
        """Test get_last_search_pmids with session manager."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            get_last_search_pmids,
            set_session_manager,
        )

        mock_session = Mock()
        mock_search = Mock()
        mock_search.pmids = ["123", "456"]
        mock_session.search_history = [mock_search]

        mock_manager = Mock()
        mock_manager.get_or_create_session.return_value = mock_session

        set_session_manager(mock_manager)
        result = get_last_search_pmids()

        assert result == ["123", "456"]
        set_session_manager(None)

    async def test_get_last_search_pmids_empty_history(self):
        """Test get_last_search_pmids with empty history."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            get_last_search_pmids,
            set_session_manager,
        )

        mock_session = Mock()
        mock_session.search_history = []

        mock_manager = Mock()
        mock_manager.get_or_create_session.return_value = mock_session

        set_session_manager(mock_manager)
        result = get_last_search_pmids()

        assert result == []
        set_session_manager(None)

    async def test_check_cache_no_manager(self):
        """Test check_cache without session manager."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            check_cache,
            set_session_manager,
        )

        set_session_manager(None)
        result = check_cache("test query")
        assert result is None

    async def test_cache_results_no_manager(self):
        """Test _cache_results without session manager."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            _cache_results,
            set_session_manager,
        )

        set_session_manager(None)
        # Should not raise
        _cache_results([{"pmid": "123"}], "test")


class TestApplyKeyAliases:
    """Test apply_key_aliases function."""

    async def test_year_aliases(self):
        """Test year parameter aliases."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            apply_key_aliases,
        )

        result = apply_key_aliases({"year_from": 2020, "year_to": 2024})
        assert "min_year" in result
        assert "max_year" in result
        assert result["min_year"] == 2020

    async def test_limit_aliases(self):
        """Test limit parameter aliases."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            apply_key_aliases,
        )

        result = apply_key_aliases({"max_results": 50})
        assert "limit" in result
        assert result["limit"] == 50

    async def test_no_override(self):
        """Test alias doesn't override existing key."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            apply_key_aliases,
        )

        result = apply_key_aliases({"limit": 10, "max_results": 50})
        assert result["limit"] == 10


class TestFormatSearchResults:
    """Test format_search_results function."""

    async def test_format_empty(self):
        """Test formatting empty results."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            format_search_results,
        )

        result = format_search_results([])
        assert "No results found" in result

    async def test_format_error(self):
        """Test formatting error results."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            format_search_results,
        )

        result = format_search_results([{"error": "API failed"}])
        assert "Error" in result

    async def test_format_success(self):
        """Test formatting successful results."""
        from pubmed_search.presentation.mcp_server.tools._common import (
            format_search_results,
        )

        results = [
            {
                "pmid": "12345678",
                "title": "Test Article",
                "authors": ["Author A", "Author B", "Author C", "Author D"],
                "journal": "Test Journal",
                "year": "2024",
                "volume": "10",
                "pages": "1-10",
                "doi": "10.1234/test",
                "pmc_id": "PMC123",
                "abstract": "This is a test abstract that is fairly long.",
            }
        ]

        formatted = format_search_results(results)

        assert "Test Article" in formatted
        assert "12345678" in formatted
        assert "et al." in formatted
        assert "10.1234/test" in formatted
        assert "PMC123" in formatted


# ===========================================================================
# Additional InputNormalizer tests
# ===========================================================================


class TestInputNormalizerAdditional:
    """Additional InputNormalizer tests for coverage."""

    async def test_normalize_identifier_doi_url(self):
        """Test identifier detection for DOI URL."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_identifier("https://doi.org/10.1234/test")

        assert result["type"] == "doi"
        assert result["value"] == "10.1234/test"

    async def test_normalize_identifier_pmcid(self):
        """Test identifier detection for PMC ID."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_identifier("PMC7096777")

        assert result["type"] == "pmcid"
        assert result["value"] == "PMC7096777"

    async def test_normalize_identifier_explicit_pmid(self):
        """Test identifier detection for explicit PMID."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_identifier("PMID:12345678")

        assert result["type"] == "pmid"
        assert result["value"] == "12345678"

    async def test_normalize_identifier_bare_number(self):
        """Test identifier detection for bare number."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_identifier("12345678")

        assert result["type"] == "pmid"
        assert result["value"] == "12345678"

    async def test_normalize_identifier_unrecognized(self):
        """Test identifier detection for unrecognized."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_identifier("abc")

        assert result["type"] is None

    async def test_normalize_year_string_with_suffix(self):
        """Test year normalization with Chinese suffix."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_year("2024年")
        assert result == 2024

    async def test_normalize_year_before_prefix(self):
        """Test year normalization with 'before' prefix."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_year("before 2024")
        assert result == 2024

    async def test_normalize_year_out_of_range(self):
        """Test year normalization out of range."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_year(1800)
        assert result is None

    async def test_normalize_pmids_semicolon(self):
        """Test PMID normalization with semicolons."""
        from pubmed_search.presentation.mcp_server.tools._common import InputNormalizer

        result = InputNormalizer.normalize_pmids("12345678;87654321")
        assert "12345678" in result
        assert "87654321" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
