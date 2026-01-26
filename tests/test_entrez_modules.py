"""
Tests for Entrez modules - citation, icite, batch, pdf.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestCitationMixin:
    """Tests for CitationMixin methods."""
    
    @pytest.fixture
    def mock_entrez_read(self):
        """Mock Entrez.read response."""
        return [{
            'LinkSetDb': [
                {
                    'LinkName': 'pubmed_pubmed',
                    'Link': [{'Id': '12345'}, {'Id': '67890'}]
                }
            ]
        }]
    
    def test_get_related_articles_success(self, mock_entrez_read):
        """Test getting related articles successfully."""
        from pubmed_search.infrastructure.ncbi.citation import CitationMixin
        
        class TestSearcher(CitationMixin):
            def fetch_details(self, pmids):
                return [{"pmid": pmid, "title": f"Article {pmid}"} for pmid in pmids]
        
        searcher = TestSearcher()
        
        with patch('pubmed_search.infrastructure.ncbi.citation.Entrez.elink') as mock_elink, \
             patch('pubmed_search.infrastructure.ncbi.citation.Entrez.read') as mock_read:
            
            mock_read.return_value = mock_entrez_read
            mock_elink.return_value = MagicMock()
            
            results = searcher.get_related_articles("999", limit=5)
            
            assert len(results) == 2
            assert results[0]["pmid"] == "12345"
    
    def test_get_related_articles_empty(self):
        """Test getting related articles when none exist."""
        from pubmed_search.infrastructure.ncbi.citation import CitationMixin
        
        class TestSearcher(CitationMixin):
            def fetch_details(self, pmids):
                return []
        
        searcher = TestSearcher()
        
        with patch('pubmed_search.infrastructure.ncbi.citation.Entrez.elink') as mock_elink, \
             patch('pubmed_search.infrastructure.ncbi.citation.Entrez.read') as mock_read:
            
            mock_read.return_value = [{}]  # No LinkSetDb
            mock_elink.return_value = MagicMock()
            
            results = searcher.get_related_articles("999", limit=5)
            assert results == []
    
    def test_get_related_articles_error(self):
        """Test getting related articles with error."""
        from pubmed_search.infrastructure.ncbi.citation import CitationMixin
        
        class TestSearcher(CitationMixin):
            def fetch_details(self, pmids):
                return []
        
        searcher = TestSearcher()
        
        with patch('pubmed_search.infrastructure.ncbi.citation.Entrez.elink') as mock_elink:
            mock_elink.side_effect = Exception("API Error")
            
            results = searcher.get_related_articles("999")
            assert len(results) == 1
            assert "error" in results[0]
    
    def test_get_citing_articles_success(self):
        """Test getting citing articles successfully."""
        from pubmed_search.infrastructure.ncbi.citation import CitationMixin
        
        class TestSearcher(CitationMixin):
            def fetch_details(self, pmids):
                return [{"pmid": pmid, "title": f"Article {pmid}"} for pmid in pmids]
        
        searcher = TestSearcher()
        
        with patch('pubmed_search.infrastructure.ncbi.citation.Entrez.elink') as mock_elink, \
             patch('pubmed_search.infrastructure.ncbi.citation.Entrez.read') as mock_read:
            
            mock_read.return_value = [{
                'LinkSetDb': [{
                    'LinkName': 'pubmed_pubmed_citedin',
                    'Link': [{'Id': '111'}, {'Id': '222'}]
                }]
            }]
            mock_elink.return_value = MagicMock()
            
            results = searcher.get_citing_articles("999", limit=10)
            
            assert len(results) == 2
    
    def test_get_article_references_success(self):
        """Test getting article references successfully."""
        from pubmed_search.infrastructure.ncbi.citation import CitationMixin
        
        class TestSearcher(CitationMixin):
            def fetch_details(self, pmids):
                return [{"pmid": pmid, "title": f"Ref {pmid}"} for pmid in pmids]
        
        searcher = TestSearcher()
        
        with patch('pubmed_search.infrastructure.ncbi.citation.Entrez.elink') as mock_elink, \
             patch('pubmed_search.infrastructure.ncbi.citation.Entrez.read') as mock_read:
            
            mock_read.return_value = [{
                'LinkSetDb': [{
                    'LinkName': 'pubmed_pubmed_refs',
                    'Link': [{'Id': 'ref1'}, {'Id': 'ref2'}]
                }]
            }]
            mock_elink.return_value = MagicMock()
            
            results = searcher.get_article_references("999", limit=20)
            
            assert len(results) == 2
    
    def test_aliases_work(self):
        """Test that alias methods work."""
        from pubmed_search.infrastructure.ncbi.citation import CitationMixin
        
        class TestSearcher(CitationMixin):
            def fetch_details(self, pmids):
                return []
        
        searcher = TestSearcher()
        
        with patch.object(searcher, 'get_related_articles', return_value=[]) as mock_get:
            searcher.find_related_articles("123")
            mock_get.assert_called_once_with("123", 5)
        
        with patch.object(searcher, 'get_citing_articles', return_value=[]) as mock_get:
            searcher.find_citing_articles("123")
            mock_get.assert_called_once_with("123", 10)


class TestICiteMixin:
    """Tests for ICiteMixin methods."""
    
    @pytest.fixture
    def mock_icite_response(self):
        """Mock iCite API response."""
        return {
            "data": [
                {
                    "pmid": 12345678,
                    "year": 2024,
                    "title": "Test Article",
                    "journal": "Test Journal",
                    "citation_count": 50,
                    "relative_citation_ratio": 2.5,
                    "nih_percentile": 85.0,
                    "citations_per_year": 10.0,
                    "apt": 0.8
                }
            ]
        }
    
    def test_get_citation_metrics_success(self, mock_icite_response):
        """Test getting citation metrics successfully."""
        from pubmed_search.infrastructure.ncbi.icite import ICiteMixin
        
        class TestSearcher(ICiteMixin):
            pass
        
        searcher = TestSearcher()
        
        with patch('pubmed_search.infrastructure.ncbi.icite.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_icite_response
            mock_get.return_value = mock_response
            
            results = searcher.get_citation_metrics(["12345678"])
            
            assert "12345678" in results
            assert results["12345678"]["citation_count"] == 50
            assert results["12345678"]["relative_citation_ratio"] == 2.5
    
    def test_get_citation_metrics_empty(self):
        """Test getting citation metrics with no PMIDs."""
        from pubmed_search.infrastructure.ncbi.icite import ICiteMixin
        
        class TestSearcher(ICiteMixin):
            pass
        
        searcher = TestSearcher()
        results = searcher.get_citation_metrics([])
        
        assert results == {}
    
    def test_get_citation_metrics_batch(self, mock_icite_response):
        """Test getting citation metrics in batches."""
        from pubmed_search.infrastructure.ncbi.icite import ICiteMixin, MAX_PMIDS_PER_REQUEST
        
        class TestSearcher(ICiteMixin):
            pass
        
        searcher = TestSearcher()
        
        # Create more PMIDs than the batch limit
        pmids = [str(i) for i in range(MAX_PMIDS_PER_REQUEST + 50)]
        
        with patch('pubmed_search.infrastructure.ncbi.icite.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"data": []}
            mock_get.return_value = mock_response
            
            searcher.get_citation_metrics(pmids)
            
            # Should make 2 API calls (one full batch + one partial)
            assert mock_get.call_count == 2
    
    def test_get_citation_metrics_api_error(self):
        """Test getting citation metrics with API error."""
        from pubmed_search.infrastructure.ncbi.icite import ICiteMixin
        
        class TestSearcher(ICiteMixin):
            pass
        
        searcher = TestSearcher()
        
        with patch('pubmed_search.infrastructure.ncbi.icite.requests.get') as mock_get:
            mock_get.side_effect = Exception("API Error")
            
            results = searcher.get_citation_metrics(["12345"])
            # Should return empty dict on error
            assert results == {}


class TestBatchMixin:
    """Tests for BatchMixin methods."""
    
    def test_search_with_history_success(self):
        """Test search with history server."""
        from pubmed_search.infrastructure.ncbi.batch import BatchMixin
        
        class TestSearcher(BatchMixin):
            pass
        
        searcher = TestSearcher()
        
        with patch('pubmed_search.infrastructure.ncbi.batch.Entrez.esearch') as mock_search, \
             patch('pubmed_search.infrastructure.ncbi.batch.Entrez.read') as mock_read:
            
            mock_read.return_value = {
                "WebEnv": "WEB_ENV_123",
                "QueryKey": "1",
                "Count": "500"
            }
            mock_search.return_value = MagicMock()
            
            result = searcher.search_with_history("cancer therapy")
            
            assert result["webenv"] == "WEB_ENV_123"
            assert result["query_key"] == "1"
            assert result["count"] == 500
    
    def test_search_with_history_error(self):
        """Test search with history server error."""
        from pubmed_search.infrastructure.ncbi.batch import BatchMixin
        
        class TestSearcher(BatchMixin):
            pass
        
        searcher = TestSearcher()
        
        with patch('pubmed_search.infrastructure.ncbi.batch.Entrez.esearch') as mock_search:
            mock_search.side_effect = Exception("API Error")
            
            result = searcher.search_with_history("test")
            assert "error" in result
    
    def test_fetch_batch_from_history_success(self):
        """Test fetching batch from history."""
        from pubmed_search.infrastructure.ncbi.batch import BatchMixin
        
        class TestSearcher(BatchMixin):
            pass
        
        searcher = TestSearcher()
        
        with patch('pubmed_search.infrastructure.ncbi.batch.Entrez.efetch') as mock_fetch, \
             patch('pubmed_search.infrastructure.ncbi.batch.Entrez.read') as mock_read:
            
            mock_read.return_value = {
                'PubmedArticle': [
                    {
                        'MedlineCitation': {
                            'PMID': '12345',
                            'Article': {
                                'ArticleTitle': 'Test Article',
                                'AuthorList': [{'LastName': 'Smith', 'ForeName': 'John'}],
                                'Journal': {'Title': 'Test Journal', 'JournalIssue': {'PubDate': {'Year': '2024'}}}
                            }
                        }
                    }
                ]
            }
            mock_fetch.return_value = MagicMock()
            
            results = searcher.fetch_batch_from_history("WEB_ENV", "1", 0, 10)
            
            assert len(results) == 1
            assert results[0]["pmid"] == "12345"
            assert results[0]["title"] == "Test Article"
    
    def test_fetch_batch_from_history_error(self):
        """Test fetching batch with error."""
        from pubmed_search.infrastructure.ncbi.batch import BatchMixin
        
        class TestSearcher(BatchMixin):
            pass
        
        searcher = TestSearcher()
        
        with patch('pubmed_search.infrastructure.ncbi.batch.Entrez.efetch') as mock_fetch:
            mock_fetch.side_effect = Exception("API Error")
            
            results = searcher.fetch_batch_from_history("WEB_ENV", "1", 0, 10)
            assert len(results) == 1
            assert "error" in results[0]
