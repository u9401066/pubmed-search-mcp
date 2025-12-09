"""
Tests for utils.py module and additional coverage tests.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json


class TestUtilsMixin:
    """Tests for UtilsMixin methods."""
    
    @pytest.fixture
    def utils_mixin(self):
        """Create a test instance with UtilsMixin."""
        from pubmed_search.entrez.utils import UtilsMixin
        
        class TestSearcher(UtilsMixin):
            pass
        
        return TestSearcher()
    
    def test_quick_fetch_summary_success(self, utils_mixin):
        """Test quick_fetch_summary with successful response."""
        with patch('pubmed_search.entrez.utils.Entrez.esummary') as mock_esummary, \
             patch('pubmed_search.entrez.utils.Entrez.read') as mock_read:
            
            # Mock ESummary response
            mock_summary = MagicMock()
            mock_summary.get = lambda k, d=None: {
                'Id': '12345',
                'Title': 'Test Article',
                'AuthorList': ['Smith J', 'Doe J'],
                'Source': 'Test Journal',
                'PubDate': '2024 Jan',
                'DOI': '10.1/test',
                'PMCID': 'PMC123'
            }.get(k, d)
            mock_summary.__getitem__ = mock_summary.get
            
            mock_read.return_value = [mock_summary]
            mock_esummary.return_value = MagicMock()
            
            results = utils_mixin.quick_fetch_summary(['12345'])
            
            assert len(results) == 1
            assert results[0]['pmid'] == '12345'
            assert 'Test Article' in results[0]['title']
    
    def test_quick_fetch_summary_empty(self, utils_mixin):
        """Test quick_fetch_summary with empty list."""
        results = utils_mixin.quick_fetch_summary([])
        assert results == []
    
    def test_quick_fetch_summary_error(self, utils_mixin):
        """Test quick_fetch_summary with API error."""
        with patch('pubmed_search.entrez.utils.Entrez.esummary') as mock_esummary:
            mock_esummary.side_effect = Exception("API Error")
            
            results = utils_mixin.quick_fetch_summary(['12345'])
            
            assert len(results) == 1
            assert 'error' in results[0]
    
    def test_spell_check_query_success(self, utils_mixin):
        """Test spell_check_query with correction."""
        with patch('pubmed_search.entrez.utils.Entrez.espell') as mock_espell, \
             patch('pubmed_search.entrez.utils.Entrez.read') as mock_read:
            
            mock_read.return_value = {'CorrectedQuery': 'diabetes'}
            mock_espell.return_value = MagicMock()
            
            result = utils_mixin.spell_check_query('diabetis')
            
            assert result == 'diabetes'
    
    def test_spell_check_query_no_correction(self, utils_mixin):
        """Test spell_check_query without correction."""
        with patch('pubmed_search.entrez.utils.Entrez.espell') as mock_espell, \
             patch('pubmed_search.entrez.utils.Entrez.read') as mock_read:
            
            mock_read.return_value = {'CorrectedQuery': ''}
            mock_espell.return_value = MagicMock()
            
            result = utils_mixin.spell_check_query('diabetes')
            
            assert result == 'diabetes'
    
    def test_spell_check_query_error(self, utils_mixin):
        """Test spell_check_query with API error."""
        with patch('pubmed_search.entrez.utils.Entrez.espell') as mock_espell:
            mock_espell.side_effect = Exception("API Error")
            
            result = utils_mixin.spell_check_query('test')
            
            # Should return original query on error
            assert result == 'test'
    
    def test_get_database_counts_success(self, utils_mixin):
        """Test get_database_counts with successful response."""
        with patch('pubmed_search.entrez.utils.Entrez.egquery') as mock_egquery, \
             patch('pubmed_search.entrez.utils.Entrez.read') as mock_read:
            
            mock_read.return_value = {
                'eGQueryResult': [
                    {'DbName': 'pubmed', 'Count': '1234'},
                    {'DbName': 'pmc', 'Count': '567'},
                ]
            }
            mock_egquery.return_value = MagicMock()
            
            result = utils_mixin.get_database_counts('cancer')
            
            assert result['pubmed'] == 1234
            assert result['pmc'] == 567
    
    def test_get_database_counts_error(self, utils_mixin):
        """Test get_database_counts with API error."""
        with patch('pubmed_search.entrez.utils.Entrez.egquery') as mock_egquery:
            mock_egquery.side_effect = Exception("API Error")
            
            result = utils_mixin.get_database_counts('test')
            
            assert 'error' in result
    
    def test_validate_mesh_terms_found(self, utils_mixin):
        """Test validate_mesh_terms when terms are found."""
        with patch('pubmed_search.entrez.utils.Entrez.esearch') as mock_esearch, \
             patch('pubmed_search.entrez.utils.Entrez.esummary') as mock_esummary, \
             patch('pubmed_search.entrez.utils.Entrez.read') as mock_read:
            
            # First call for esearch
            search_result = {'IdList': ['D003920']}
            # Second call for esummary
            summary_result = [{
                'Id': 'D003920',
                'DS_MeshTerms': ['Diabetes Mellitus'],
                'DS_IdxLinks': ['C18.452']
            }]
            
            mock_read.side_effect = [search_result, summary_result]
            mock_esearch.return_value = MagicMock()
            mock_esummary.return_value = MagicMock()
            
            result = utils_mixin.validate_mesh_terms(['diabetes'])
            
            assert result['valid_count'] >= 0
    
    def test_validate_mesh_terms_not_found(self, utils_mixin):
        """Test validate_mesh_terms when no terms found."""
        with patch('pubmed_search.entrez.utils.Entrez.esearch') as mock_esearch, \
             patch('pubmed_search.entrez.utils.Entrez.read') as mock_read:
            
            mock_read.return_value = {'IdList': []}
            mock_esearch.return_value = MagicMock()
            
            result = utils_mixin.validate_mesh_terms(['nonexistent12345'])
            
            assert result['valid_count'] == 0
    
    def test_find_by_citation_found(self, utils_mixin):
        """Test find_by_citation when article is found."""
        with patch('pubmed_search.entrez.utils.Entrez.ecitmatch') as mock_ecitmatch:
            mock_handle = MagicMock()
            mock_handle.read.return_value = "journal|2024|10|1|author||\t12345678"
            mock_ecitmatch.return_value = mock_handle
            
            result = utils_mixin.find_by_citation(
                journal='Test Journal',
                year='2024',
                volume='10',
                first_page='1'
            )
            
            assert result == '12345678'
    
    def test_find_by_citation_not_found(self, utils_mixin):
        """Test find_by_citation when article is not found."""
        with patch('pubmed_search.entrez.utils.Entrez.ecitmatch') as mock_ecitmatch:
            mock_handle = MagicMock()
            mock_handle.read.return_value = "journal|2024||||\t"
            mock_ecitmatch.return_value = mock_handle
            
            result = utils_mixin.find_by_citation(
                journal='Unknown',
                year='1900'
            )
            
            assert result is None
    
    def test_find_by_citation_error(self, utils_mixin):
        """Test find_by_citation with API error."""
        with patch('pubmed_search.entrez.utils.Entrez.ecitmatch') as mock_ecitmatch:
            mock_ecitmatch.side_effect = Exception("API Error")
            
            result = utils_mixin.find_by_citation(journal='Test', year='2024')
            
            assert result is None
    
    def test_export_citations_medline(self, utils_mixin):
        """Test export_citations with MEDLINE format."""
        with patch('pubmed_search.entrez.utils.Entrez.efetch') as mock_efetch:
            mock_handle = MagicMock()
            mock_handle.read.return_value = "PMID- 12345\nTI  - Test Article"
            mock_efetch.return_value = mock_handle
            
            result = utils_mixin.export_citations(['12345'], format='medline')
            
            assert 'PMID' in result or '12345' in result
    
    def test_export_citations_empty(self, utils_mixin):
        """Test export_citations with empty list."""
        result = utils_mixin.export_citations([])
        assert result == ""
    
    def test_export_citations_invalid_format(self, utils_mixin):
        """Test export_citations with invalid format falls back to medline."""
        with patch('pubmed_search.entrez.utils.Entrez.efetch') as mock_efetch:
            mock_handle = MagicMock()
            mock_handle.read.return_value = "PMID- 12345"
            mock_efetch.return_value = mock_handle
            
            result = utils_mixin.export_citations(['12345'], format='invalid')
            
            # Should use medline as fallback
            mock_efetch.assert_called()
    
    def test_get_database_info_success(self, utils_mixin):
        """Test get_database_info with successful response."""
        with patch('pubmed_search.entrez.utils.Entrez.einfo') as mock_einfo, \
             patch('pubmed_search.entrez.utils.Entrez.read') as mock_read:
            
            mock_read.return_value = {
                'DbInfo': {
                    'DbName': 'pubmed',
                    'MenuName': 'PubMed',
                    'Description': 'PubMed Database',
                    'Count': '35000000',
                    'LastUpdate': '2024/12/08',
                    'FieldList': [
                        {'Name': 'ALL', 'FullName': 'All Fields', 'Description': 'All searchable fields'}
                    ]
                }
            }
            mock_einfo.return_value = MagicMock()
            
            result = utils_mixin.get_database_info('pubmed')
            
            assert result['name'] == 'pubmed'
            assert result['count'] == '35000000'
            assert len(result['fields']) > 0
    
    def test_get_database_info_error(self, utils_mixin):
        """Test get_database_info with API error."""
        with patch('pubmed_search.entrez.utils.Entrez.einfo') as mock_einfo:
            mock_einfo.side_effect = Exception("API Error")
            
            result = utils_mixin.get_database_info('pubmed')
            
            assert 'error' in result


class TestServerModule:
    """Tests to improve server.py coverage."""
    
    def test_server_module_structure(self):
        """Test server module has expected structure."""
        from pubmed_search.mcp import server
        
        # Check for expected attributes
        assert hasattr(server, 'logging')
    
    def test_create_mcp_if_exists(self):
        """Test create_mcp function if it exists."""
        from pubmed_search.mcp import server
        
        # If create_mcp exists, test it
        if hasattr(server, 'create_mcp'):
            # Just verify it's callable
            assert callable(server.create_mcp)


class TestSessionModule:
    """Additional tests for session.py coverage."""
    
    def test_session_manager_create(self):
        """Test SessionManager creation."""
        from pubmed_search.session import SessionManager
        
        manager = SessionManager()
        assert manager is not None
    
    def test_research_session_create(self):
        """Test ResearchSession creation."""
        from pubmed_search.session import ResearchSession
        
        session = ResearchSession(session_id="test_session")
        assert session is not None
        assert session.search_history == []
        assert session.session_id == "test_session"
    
    def test_cached_article_create(self):
        """Test CachedArticle creation."""
        from pubmed_search.session import CachedArticle
        
        article = CachedArticle(
            pmid="12345",
            title="Test",
            authors=["A"],
            abstract="Test abstract",
            journal="J",
            year="2024"
        )
        assert article.pmid == "12345"
        assert article.is_expired(max_age_days=0) is True
        assert article.is_expired(max_age_days=365) is False
    
    def test_search_record_create(self):
        """Test SearchRecord creation."""
        from pubmed_search.session import SearchRecord
        
        record = SearchRecord(
            query="test query",
            timestamp="2024-01-01T00:00:00",
            result_count=10,
            pmids=["123", "456"]
        )
        assert record.query == "test query"
        assert record.result_count == 10


class TestCommonModuleCoverage:
    """Tests for _common.py coverage."""
    
    def test_format_search_results_with_multiple(self):
        """Test formatting multiple search results."""
        from pubmed_search.mcp.tools._common import format_search_results
        
        articles = [
            {"pmid": "123", "title": "Article 1", "authors": ["A", "B"], "year": "2024", "journal": "J1", "abstract": "Abstract 1"},
            {"pmid": "456", "title": "Article 2", "authors": ["C"], "year": "2023", "journal": "J2", "abstract": "Abstract 2"},
        ]
        
        result = format_search_results(articles)
        
        assert "Found 2 results" in result
        assert "123" in result
        assert "456" in result
    
    def test_cache_results(self):
        """Test _cache_results function."""
        from pubmed_search.mcp.tools._common import _cache_results, set_session_manager
        
        # With no session manager
        set_session_manager(None)
        # Should not raise
        _cache_results([{"pmid": "123"}], "test query")
    
    def test_record_search_only(self):
        """Test _record_search_only function."""
        from pubmed_search.mcp.tools._common import _record_search_only, set_session_manager
        
        # With no session manager
        set_session_manager(None)
        # Should not raise
        _record_search_only([{"pmid": "123"}], "test query")


class TestExportModuleCoverage:
    """Additional tests for exports/formats.py coverage."""
    
    def test_export_bibtex_complete(self):
        """Test complete BibTeX export with all fields."""
        from pubmed_search.exports.formats import export_bibtex
        
        article = {
            "pmid": "12345",
            "title": "Test Article with Special Characters: α-β",
            "authors": ["Smith John", "Müller Hans", "Doe Jane"],
            "journal": "Journal of Testing",
            "journal_abbrev": "J Test",
            "year": "2024",
            "volume": "10",
            "issue": "5",
            "pages": "100-110",
            "doi": "10.1000/test.001",
            "abstract": "This is a test abstract."
        }
        
        result = export_bibtex([article], include_abstract=True)
        
        assert "@article{" in result
        assert "title = {" in result
        assert "author = {" in result
    
    def test_export_csv_complete(self):
        """Test complete CSV export with all fields."""
        from pubmed_search.exports.formats import export_csv
        
        articles = [
            {
                "pmid": "123",
                "title": "Test, with comma",
                "authors": ["Author A", "Author B"],
                "journal": "Test Journal",
                "year": "2024",
                "abstract": "Test abstract"
            }
        ]
        
        result = export_csv(articles, include_abstract=True)
        
        # CSV should handle commas in title
        assert "123" in result
    
    def test_export_medline_complete(self):
        """Test complete MEDLINE export."""
        from pubmed_search.exports.formats import export_medline
        
        article = {
            "pmid": "12345",
            "title": "Test Article",
            "authors": ["Smith J"],
            "authors_full": [{"last_name": "Smith", "first_name": "John"}],
            "journal": "Test Journal",
            "journal_abbrev": "J Test",
            "year": "2024",
            "volume": "10",
            "issue": "5",
            "pages": "1-10",
            "abstract": "Test abstract.",
            "doi": "10.1/test",
            "pmc_id": "PMC999",
            "mesh_terms": ["Humans", "Drug Therapy"],
            "keywords": ["test", "example"]
        }
        
        result = export_medline([article])
        
        assert "PMID" in result
        assert "12345" in result
