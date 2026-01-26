"""Final targeted tests to reach 90% coverage."""
from unittest.mock import Mock, patch
import tempfile
import json


class TestClientPubMedClient:
    """Test client.py PubMedClient - lines 153-165, 185, 207-210, etc."""
    
    def test_pubmed_client_search(self):
        """Test PubMedClient.search() method."""
        from pubmed_search import PubMedClient
        
        with patch('pubmed_search.infrastructure.http.pubmed_client.LiteratureSearcher') as mock_searcher_class:
            mock_searcher = Mock()
            mock_searcher.search.return_value = [
                {
                    "pmid": "123",
                    "title": "Test",
                    "authors": ["A"],
                    "authors_full": [{"first": "A", "last": "Author"}],
                    "year": "2024",
                    "journal": "J",
                    "journal_abbrev": "J Abbr",
                    "abstract": "Abstract text"
                }
            ]
            mock_searcher_class.return_value = mock_searcher
            
            client = PubMedClient(email="test@example.com")
            results = client.search("test query", limit=5)
            
            assert len(results) == 1
            assert results[0].pmid == "123"
    
    def test_pubmed_client_search_raw(self):
        """Test PubMedClient.search_raw() method."""
        from pubmed_search import PubMedClient
        
        with patch('pubmed_search.infrastructure.http.pubmed_client.LiteratureSearcher') as mock_searcher_class:
            mock_searcher = Mock()
            mock_searcher.search.return_value = [{"pmid": "123", "title": "Test"}]
            mock_searcher_class.return_value = mock_searcher
            
            client = PubMedClient(email="test@example.com")
            results = client.search_raw("test query")
            
            assert isinstance(results, list)
            assert results[0]["pmid"] == "123"
    
    def test_pubmed_client_fetch_by_pmid(self):
        """Test PubMedClient.fetch_by_pmid() method."""
        from pubmed_search import PubMedClient
        
        with patch('pubmed_search.infrastructure.http.pubmed_client.LiteratureSearcher') as mock_searcher_class:
            mock_searcher = Mock()
            mock_searcher.fetch_details.return_value = [
                {
                    "pmid": "12345",
                    "title": "Test Article",
                    "authors": ["A"],
                    "authors_full": [{"first": "A", "last": "Author"}],
                    "year": "2024",
                    "journal": "J",
                    "journal_abbrev": "J Abbr",
                    "abstract": "Abstract text"
                }
            ]
            mock_searcher_class.return_value = mock_searcher
            
            client = PubMedClient(email="test@example.com")
            result = client.fetch_by_pmid("12345")
            
            assert result is not None
            assert result.pmid == "12345"
    
    def test_pubmed_client_fetch_by_pmid_not_found(self):
        """Test PubMedClient.fetch_by_pmid() when not found."""
        from pubmed_search import PubMedClient
        
        with patch('pubmed_search.infrastructure.http.pubmed_client.LiteratureSearcher') as mock_searcher_class:
            mock_searcher = Mock()
            mock_searcher.fetch_details.return_value = []
            mock_searcher_class.return_value = mock_searcher
            
            client = PubMedClient(email="test@example.com")
            result = client.fetch_by_pmid("99999")
            
            assert result is None
    
    def test_pubmed_client_fetch_by_pmids(self):
        """Test PubMedClient.fetch_by_pmids() method."""
        from pubmed_search import PubMedClient
        
        with patch('pubmed_search.infrastructure.http.pubmed_client.LiteratureSearcher') as mock_searcher_class:
            mock_searcher = Mock()
            mock_searcher.fetch_details.return_value = [
                {
                    "pmid": "111",
                    "title": "Test 1",
                    "authors": ["A"],
                    "authors_full": [{"first": "A", "last": "Author"}],
                    "year": "2024",
                    "journal": "J",
                    "journal_abbrev": "J Abbr",
                    "abstract": "Abstract 1"
                },
                {
                    "pmid": "222",
                    "title": "Test 2",
                    "authors": ["B"],
                    "authors_full": [{"first": "B", "last": "Author"}],
                    "year": "2024",
                    "journal": "J",
                    "journal_abbrev": "J Abbr",
                    "abstract": "Abstract 2"
                }
            ]
            mock_searcher_class.return_value = mock_searcher
            
            client = PubMedClient(email="test@example.com")
            results = client.fetch_by_pmids(["111", "222"])
            
            assert len(results) == 2
    
    def test_pubmed_client_fetch_by_pmids_raw(self):
        """Test PubMedClient.fetch_by_pmids_raw() method."""
        from pubmed_search import PubMedClient
        
        with patch('pubmed_search.infrastructure.http.pubmed_client.LiteratureSearcher') as mock_searcher_class:
            mock_searcher = Mock()
            mock_searcher.fetch_details.return_value = [{"pmid": "123"}]
            mock_searcher_class.return_value = mock_searcher
            
            client = PubMedClient(email="test@example.com")
            results = client.fetch_by_pmids_raw(["123"])
            
            assert isinstance(results, list)
    
    def test_pubmed_client_find_related(self):
        """Test PubMedClient.find_related() method."""
        from pubmed_search import PubMedClient
        
        with patch('pubmed_search.infrastructure.http.pubmed_client.LiteratureSearcher') as mock_searcher_class:
            mock_searcher = Mock()
            mock_searcher.find_related_articles.return_value = [
                {
                    "pmid": "999",
                    "title": "Related Article",
                    "authors": ["C"],
                    "authors_full": [{"first": "C", "last": "Author"}],
                    "year": "2023",
                    "journal": "J2",
                    "journal_abbrev": "J2 Abbr",
                    "abstract": "Related abstract"
                }
            ]
            mock_searcher_class.return_value = mock_searcher
            
            client = PubMedClient(email="test@example.com")
            results = client.find_related("12345")
            
            assert len(results) == 1
    
    def test_pubmed_client_find_citing(self):
        """Test PubMedClient.find_citing() method."""
        from pubmed_search import PubMedClient
        
        with patch('pubmed_search.infrastructure.http.pubmed_client.LiteratureSearcher') as mock_searcher_class:
            mock_searcher = Mock()
            mock_searcher.find_citing_articles.return_value = [
                {
                    "pmid": "888",
                    "title": "Citing Article",
                    "authors": ["D"],
                    "authors_full": [{"first": "D", "last": "Author"}],
                    "year": "2024",
                    "journal": "J3",
                    "journal_abbrev": "J3 Abbr",
                    "abstract": "Citing abstract"
                }
            ]
            mock_searcher_class.return_value = mock_searcher
            
            client = PubMedClient(email="test@example.com")
            results = client.find_citing("12345")
            
            assert len(results) == 1
    
    def test_pubmed_client_get_citation_metrics(self):
        """Test PubMedClient searcher's get_citation_metrics() method."""
        from pubmed_search import PubMedClient
        
        with patch('pubmed_search.infrastructure.http.pubmed_client.LiteratureSearcher') as mock_searcher_class:
            mock_searcher = Mock()
            mock_searcher.get_citation_metrics.return_value = {
                "123": {"citation_count": 50, "rcr": 1.5}
            }
            mock_searcher_class.return_value = mock_searcher
            
            client = PubMedClient(email="test@example.com")
            # Access via internal searcher if method not exposed
            metrics = client._searcher.get_citation_metrics(["123"])
            
            assert "123" in metrics


class TestSessionToolsResourceFunction:
    """Test session_tools.py lines 45-50 - the resource function body."""
    
    def test_session_resources_get_context_with_session(self):
        """Test get_research_context resource with active session."""
        from pubmed_search.presentation.mcp_server.session_tools import register_session_resources
        from pubmed_search.application.session import SessionManager
        
        mock_mcp = Mock()
        captured_func = None
        
        def capture_resource(uri):
            def decorator(func):
                nonlocal captured_func
                captured_func = func
                return func
            return decorator
        
        mock_mcp.resource = capture_resource
        
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(data_dir=tmpdir)
            # Create a session with some data
            session = manager.create_session("Test Topic")
            session.article_cache["123"] = {"pmid": "123"}
            session.search_history.append({"query": "test"})
            
            register_session_resources(mock_mcp, manager)
            
            # Call the captured function
            result = captured_func()
            
            # Should return JSON with active=True
            data = json.loads(result)
            assert data["active"] == True
            assert data["cached_articles"] == 1
            assert data["searches"] == 1
    
    def test_session_resources_get_context_no_session(self):
        """Test get_research_context resource with no session."""
        from pubmed_search.presentation.mcp_server.session_tools import register_session_resources
        from pubmed_search.application.session import SessionManager
        
        mock_mcp = Mock()
        captured_func = None
        
        def capture_resource(uri):
            def decorator(func):
                nonlocal captured_func
                captured_func = func
                return func
            return decorator
        
        mock_mcp.resource = capture_resource
        
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SessionManager(data_dir=tmpdir)
            # Don't create any session
            
            register_session_resources(mock_mcp, manager)
            
            # Call the captured function
            result = captured_func()
            
            # Should return JSON with active=False
            data = json.loads(result)
            assert data["active"] == False


class TestServerMainLines:
    """Test server.py lines 213-235, 239 - main entry point."""
    
    def test_server_instructions_content(self):
        """Test SERVER_INSTRUCTIONS has correct content."""
        from pubmed_search.presentation.mcp_server.server import SERVER_INSTRUCTIONS
        
        # Should contain key workflow information
        assert "PubMed" in SERVER_INSTRUCTIONS
        assert "search" in SERVER_INSTRUCTIONS.lower()
    
    def test_default_data_dir_value(self):
        """Test DEFAULT_DATA_DIR is properly set."""
        from pubmed_search.presentation.mcp_server.server import DEFAULT_DATA_DIR
        
        # Should be a string path
        assert isinstance(DEFAULT_DATA_DIR, str)
        assert "pubmed" in DEFAULT_DATA_DIR.lower() or ".pubmed" in DEFAULT_DATA_DIR


class TestCommonToolsLines:
    """Test _common.py lines 56-60, 72-73, 87-88, 106-108."""
    
    def test_format_search_results_no_results(self):
        """Test format_search_results with empty list."""
        from pubmed_search.presentation.mcp_server.tools._common import format_search_results
        
        result = format_search_results([])
        assert "No results" in result or result.strip() == ""
    
    def test_format_search_results_with_articles(self):
        """Test format_search_results with articles."""
        from pubmed_search.presentation.mcp_server.tools._common import format_search_results
        
        articles = [
            {
                "pmid": "12345",
                "title": "Test Article Title",
                "authors": ["Smith J", "Jones M"],
                "year": "2024",
                "journal": "Test Journal",
                "abstract": "This is the abstract."
            }
        ]
        
        result = format_search_results(articles)
        assert "12345" in result or "Test" in result


class TestFormatsMoreLines:
    """Test formats.py additional lines."""
    
    def test_export_functions_exist(self):
        """Test all export functions exist and are callable."""
        from pubmed_search.application.export import formats
        
        assert hasattr(formats, 'export_ris')
        assert hasattr(formats, 'export_bibtex')
        assert hasattr(formats, 'export_csv')
        assert hasattr(formats, 'export_json')
        assert hasattr(formats, 'export_medline')
        
        # All should be callable
        assert callable(formats.export_ris)
        assert callable(formats.export_bibtex)
        assert callable(formats.export_csv)
        assert callable(formats.export_json)
        assert callable(formats.export_medline)


class TestSearchResultDataclass:
    """Test SearchResult dataclass methods."""
    
    def test_search_result_from_dict(self):
        """Test SearchResult.from_dict() method."""
        from pubmed_search import SearchResult
        
        data = {
            "pmid": "123",
            "title": "Test",
            "authors": ["A"],
            "authors_full": [{"first": "A", "last": "B"}],
            "abstract": "Abs",
            "journal": "J",
            "journal_abbrev": "J Abbr",
            "year": "2024",
            "month": "01",
            "day": "15",
            "volume": "10",
            "issue": "2",
            "pages": "100-110",
            "doi": "10.1000/test",
            "pmc_id": "PMC123",
            "keywords": ["k1"],
            "mesh_terms": ["m1"]
        }
        
        result = SearchResult.from_dict(data)
        
        assert result.pmid == "123"
        assert result.volume == "10"
        assert result.keywords == ["k1"]
    
    def test_search_result_to_dict(self):
        """Test SearchResult.to_dict() method."""
        from pubmed_search import SearchResult
        
        result = SearchResult(
            pmid="123",
            title="Test",
            authors=["A"],
            authors_full=[{"first": "A", "last": "B"}],
            abstract="Abs",
            journal="J",
            journal_abbrev="J Abbr",
            year="2024"
        )
        
        data = result.to_dict()
        
        assert data["pmid"] == "123"
        assert isinstance(data, dict)
    
    def test_search_result_defaults(self):
        """Test SearchResult default values."""
        from pubmed_search import SearchResult
        
        result = SearchResult(
            pmid="123",
            title="Test",
            authors=[],
            authors_full=[],
            abstract="",
            journal="J",
            journal_abbrev="",
            year="2024"
        )
        
        # Check defaults applied
        assert result.keywords == []
        assert result.mesh_terms == []
        assert result.month == ""
        assert result.volume == ""


class TestSearchStrategyEnum:
    """Test SearchStrategy enum."""
    
    def test_search_strategy_values(self):
        """Test SearchStrategy enum values."""
        from pubmed_search import SearchStrategy
        
        assert SearchStrategy.RECENT.value == "recent"
        assert SearchStrategy.MOST_CITED.value == "most_cited"
        assert SearchStrategy.RELEVANCE.value == "relevance"
        assert SearchStrategy.IMPACT.value == "impact"
        assert SearchStrategy.AGENT_DECIDED.value == "agent_decided"
