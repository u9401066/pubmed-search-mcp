"""
Tests for PubMedClient and SearchResult classes.
"""

import pytest
from pubmed_search.client import PubMedClient, SearchResult, SearchStrategy


class TestSearchResult:
    """Tests for SearchResult dataclass."""
    
    def test_create_search_result(self, mock_article_data):
        """Test creating a SearchResult from data."""
        result = SearchResult.from_dict(mock_article_data)
        
        assert result.pmid == "12345678"
        assert result.title == "Test Article: Effects of Drug X on Condition Y"
        assert len(result.authors) == 3
        assert result.journal == "Journal of Test Medicine"
        assert result.year == "2024"
        assert result.doi == "10.1000/test.2024.001"
    
    def test_search_result_to_dict(self, mock_article_data):
        """Test converting SearchResult back to dict."""
        result = SearchResult.from_dict(mock_article_data)
        data = result.to_dict()
        
        assert data["pmid"] == "12345678"
        assert data["title"] == mock_article_data["title"]
        assert data["authors"] == mock_article_data["authors"]
    
    def test_search_result_default_values(self):
        """Test SearchResult with minimal data."""
        minimal_data = {
            "pmid": "99999999",
            "title": "Minimal Article",
            "authors": [],
            "authors_full": [],
            "abstract": "",
            "journal": "",
            "journal_abbrev": "",
            "year": ""
        }
        result = SearchResult.from_dict(minimal_data)
        
        assert result.pmid == "99999999"
        assert result.keywords == []
        assert result.mesh_terms == []
        assert result.doi == ""
        assert result.pmc_id == ""
    
    def test_search_result_keywords_none_handling(self):
        """Test that None keywords/mesh_terms are converted to empty lists."""
        result = SearchResult(
            pmid="123",
            title="Test",
            authors=[],
            authors_full=[],
            abstract="",
            journal="",
            journal_abbrev="",
            year="",
            keywords=None,
            mesh_terms=None
        )
        assert result.keywords == []
        assert result.mesh_terms == []


class TestSearchStrategy:
    """Tests for SearchStrategy enum."""
    
    def test_strategy_values(self):
        """Test that all expected strategies exist."""
        assert SearchStrategy.RECENT.value == "recent"
        assert SearchStrategy.MOST_CITED.value == "most_cited"
        assert SearchStrategy.RELEVANCE.value == "relevance"
        assert SearchStrategy.IMPACT.value == "impact"
        assert SearchStrategy.AGENT_DECIDED.value == "agent_decided"


class TestPubMedClient:
    """Tests for PubMedClient class."""
    
    def test_client_initialization(self, mock_email):
        """Test client can be initialized."""
        # Note: This creates a real client but doesn't make API calls
        client = PubMedClient(email=mock_email)
        assert client is not None
        # PubMedClient wraps LiteratureSearcher, check it exists
        assert client.searcher is not None
    
    def test_client_with_api_key(self, mock_email):
        """Test client initialization with API key."""
        from Bio import Entrez
        
        client = PubMedClient(email=mock_email, api_key="test_key")
        # API key is stored in the underlying searcher
        assert client.searcher is not None
        
        # IMPORTANT: Clear the invalid API key to not affect other tests
        # Entrez.api_key is global state
        Entrez.api_key = None
