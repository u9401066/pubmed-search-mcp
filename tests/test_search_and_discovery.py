"""
Tests for search.py module and discovery tools functions.
"""

import pytest
from unittest.mock import patch, MagicMock
import json


class TestSearchModule:
    """Tests for search.py SearchMixin."""
    
    @pytest.fixture
    def search_mixin(self):
        """Create a test instance with SearchMixin."""
        from pubmed_search.infrastructure.ncbi.search import SearchMixin
        
        class TestSearcher(SearchMixin):
            def __init__(self):
                self.email = "test@example.com"
        
        return TestSearcher()
    
    def test_search_basic(self, search_mixin):
        """Test basic search functionality."""
        with patch('pubmed_search.entrez.search.Entrez.esearch') as mock_esearch, \
             patch('pubmed_search.entrez.search.Entrez.read') as mock_read, \
             patch.object(search_mixin, 'fetch_details', return_value=[]):
            
            mock_read.return_value = {"IdList": ["123", "456"], "Count": "2"}
            mock_esearch.return_value = MagicMock()
            
            results = search_mixin.search("test query", limit=10)
            
            # Should call esearch
            mock_esearch.assert_called_once()
    
    def test_search_with_date_filters(self, search_mixin):
        """Test search with date filters."""
        with patch('pubmed_search.entrez.search.Entrez.esearch') as mock_esearch, \
             patch('pubmed_search.entrez.search.Entrez.read') as mock_read, \
             patch.object(search_mixin, 'fetch_details', return_value=[]):
            
            mock_read.return_value = {"IdList": [], "Count": "0"}
            mock_esearch.return_value = MagicMock()
            
            results = search_mixin.search(
                "test", 
                limit=10,
                date_from="2024/01/01",
                date_to="2024/12/31",
                date_type="edat"
            )
    
    def test_fetch_details_basic(self, search_mixin):
        """Test fetching article details."""
        with patch('pubmed_search.entrez.search.Entrez.efetch') as mock_efetch, \
             patch('pubmed_search.entrez.search.Entrez.read') as mock_read:
            
            mock_read.return_value = {
                'PubmedArticle': [{
                    'MedlineCitation': {
                        'PMID': '12345',
                        'Article': {
                            'ArticleTitle': 'Test Title',
                            'AuthorList': [],
                            'Journal': {
                                'Title': 'Test Journal',
                                'JournalIssue': {'PubDate': {'Year': '2024'}}
                            },
                            'Abstract': {'AbstractText': ['Test abstract']}
                        },
                        'MeshHeadingList': []
                    },
                    'PubmedData': {
                        'ArticleIdList': []
                    }
                }]
            }
            mock_efetch.return_value = MagicMock()
            
            results = search_mixin.fetch_details(["12345"])
            
            assert len(results) == 1
            assert results[0]["pmid"] == "12345"


class TestDiscoveryToolsComplete:
    """Complete tests for discovery tools."""
    
    @pytest.fixture
    def registered_tools(self):
        """Register discovery tools and capture them."""
        from pubmed_search.presentation.mcp_server.tools.discovery import register_discovery_tools
        
        mcp = MagicMock()
        searcher = MagicMock()
        
        tools = {}
        def capture_tool():
            def decorator(fn):
                tools[fn.__name__] = fn
                return fn
            return decorator
        
        mcp.tool = capture_tool
        register_discovery_tools(mcp, searcher)
        
        return tools, searcher
    
    # v0.1.21: search_literature has been integrated into unified_search
    @pytest.mark.skip(reason="v0.1.21: search_literature integrated into unified_search")
    def test_search_literature_tool(self, registered_tools):
        """Test search_literature tool function."""
        pass  # This tool has been integrated into unified_search
    
    @pytest.mark.skip(reason="v0.1.21: search_literature integrated into unified_search")
    def test_search_literature_empty_query(self, registered_tools):
        """Test search_literature with empty query."""
        pass  # This tool has been integrated into unified_search
    
    @pytest.mark.skip(reason="v0.1.21: search_literature integrated into unified_search")
    def test_search_literature_with_ambiguous_term(self, registered_tools):
        """Test search_literature with ambiguous journal name."""
        pass  # This tool has been integrated into unified_search
    
    def test_find_related_articles_tool(self, registered_tools):
        """Test find_related_articles tool."""
        tools, searcher = registered_tools
        
        searcher.get_related_articles.return_value = [
            {"pmid": "456", "title": "Related Article", "authors": [], "year": "2024"}
        ]
        
        result = tools["find_related_articles"](pmid="123", limit=5)
        
        assert "Related" in result or "456" in result
    
    def test_find_related_articles_no_results(self, registered_tools):
        """Test find_related_articles with no results."""
        tools, searcher = registered_tools
        
        searcher.get_related_articles.return_value = []
        
        result = tools["find_related_articles"](pmid="123", limit=5)
        
        # Updated to match unified "No results found" format
        assert "No related" in result or "No results" in result
    
    def test_find_related_articles_error(self, registered_tools):
        """Test find_related_articles with error."""
        tools, searcher = registered_tools
        
        searcher.get_related_articles.return_value = [{"error": "API Error"}]
        
        result = tools["find_related_articles"](pmid="123", limit=5)
        
        assert "Error" in result
    
    def test_find_citing_articles_tool(self, registered_tools):
        """Test find_citing_articles tool."""
        tools, searcher = registered_tools
        
        searcher.get_citing_articles.return_value = [
            {"pmid": "789", "title": "Citing Article", "authors": [], "year": "2024"}
        ]
        
        result = tools["find_citing_articles"](pmid="123", limit=10)
        
        assert "Citing" in result or "789" in result
    
    def test_find_citing_articles_no_results(self, registered_tools):
        """Test find_citing_articles with no results."""
        tools, searcher = registered_tools
        
        searcher.get_citing_articles.return_value = []
        
        result = tools["find_citing_articles"](pmid="123", limit=10)
        
        # Updated to match unified "No results found" format
        assert "No citing" in result or "No results" in result or "not indexed" in result.lower()
    
    def test_get_article_references_tool(self, registered_tools):
        """Test get_article_references tool."""
        tools, searcher = registered_tools
        
        searcher.get_article_references.return_value = [
            {"pmid": "111", "title": "Reference Article", "authors": [], "year": "2020"}
        ]
        
        result = tools["get_article_references"](pmid="123", limit=20)
        
        assert "References" in result or "111" in result
    
    def test_get_article_references_no_results(self, registered_tools):
        """Test get_article_references with no results."""
        tools, searcher = registered_tools
        
        searcher.get_article_references.return_value = []
        
        result = tools["get_article_references"](pmid="123", limit=20)
        
        # Updated to match unified "No results found" format
        assert "No references" in result or "No results" in result
    
    def test_fetch_article_details_tool(self, registered_tools):
        """Test fetch_article_details tool."""
        tools, searcher = registered_tools
        
        searcher.fetch_details.return_value = [
            {"pmid": "123", "title": "Article 1", "authors": [], "year": "2024", "doi": "10.1/a"},
            {"pmid": "456", "title": "Article 2", "authors": [], "year": "2023", "doi": "10.1/b"}
        ]
        
        result = tools["fetch_article_details"](pmids="123,456")
        
        assert "123" in result or "Article" in result
    
    def test_fetch_article_details_no_results(self, registered_tools):
        """Test fetch_article_details with no results."""
        tools, searcher = registered_tools
        
        searcher.fetch_details.return_value = []
        
        result = tools["fetch_article_details"](pmids="999999")
        
        # Updated to match unified "No results found" format
        assert "No articles" in result or "No results" in result
    
    def test_get_citation_metrics_tool(self, registered_tools):
        """Test get_citation_metrics tool."""
        tools, searcher = registered_tools
        
        searcher.get_citation_metrics.return_value = {
            "123": {
                "pmid": 123,
                "title": "Test Article",
                "year": 2024,
                "journal": "Test Journal",
                "citation_count": 50,
                "relative_citation_ratio": 2.5,
                "nih_percentile": 85.0,
                "citations_per_year": 10.0,
                "apt": 0.8
            }
        }
        
        result = tools["get_citation_metrics"](pmids="123")
        
        assert "Citation Metrics" in result
        assert "50" in result or "citations" in result.lower()
    
    def test_get_citation_metrics_no_results(self, registered_tools):
        """Test get_citation_metrics with no data."""
        tools, searcher = registered_tools
        
        searcher.get_citation_metrics.return_value = {}
        
        result = tools["get_citation_metrics"](pmids="999999")
        
        # Updated to match unified "No results found" format
        assert "No citation data" in result or "No results" in result
    
    def test_get_citation_metrics_with_filters(self, registered_tools):
        """Test get_citation_metrics with filtering."""
        tools, searcher = registered_tools
        
        searcher.get_citation_metrics.return_value = {
            "123": {"pmid": 123, "title": "High", "citation_count": 100, "relative_citation_ratio": 3.0, "nih_percentile": 90, "year": 2024, "journal": "J"},
            "456": {"pmid": 456, "title": "Low", "citation_count": 5, "relative_citation_ratio": 0.3, "nih_percentile": 20, "year": 2024, "journal": "J"}
        }
        
        # Filter by min_citations
        result = tools["get_citation_metrics"](
            pmids="123,456",
            min_citations=50
        )
        
        # Should only show high citation article
        assert "100" in result or "High" in result
    
    def test_get_citation_metrics_last_keyword(self, registered_tools):
        """Test get_citation_metrics with 'last' keyword."""
        tools, searcher = registered_tools
        
        with patch('pubmed_search.mcp.tools._common.get_last_search_pmids', return_value=[]):
            result = tools["get_citation_metrics"](pmids="last")
            
            assert "No previous search" in result


class TestExportToolsFunctions:
    """Tests for export tools functions."""
    
    @pytest.fixture
    def registered_export_tools(self):
        """Register export tools and capture them."""
        from pubmed_search.presentation.mcp_server.tools.export import register_export_tools
        
        mcp = MagicMock()
        searcher = MagicMock()
        
        tools = {}
        def capture_tool():
            def decorator(fn):
                tools[fn.__name__] = fn
                return fn
            return decorator
        
        mcp.tool = capture_tool
        register_export_tools(mcp, searcher)
        
        return tools, searcher
    
    def test_prepare_export_empty_pmids(self, registered_export_tools):
        """Test prepare_export with empty PMIDs."""
        tools, searcher = registered_export_tools
        
        with patch('pubmed_search.mcp.tools.export._resolve_pmids', return_value=[]):
            result = tools["prepare_export"](pmids="", format="ris")
            
            # Result could be JSON or plain text error message
            try:
                parsed = json.loads(result)
                assert parsed.get("status") == "error" or "error" in str(parsed).lower()
            except json.JSONDecodeError:
                # Plain text error message
                assert "error" in result.lower() or "no" in result.lower()
