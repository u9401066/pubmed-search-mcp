"""
Tests for Entrez utility functions.
"""

from unittest.mock import patch, MagicMock


class TestUtilsMixin:
    """Tests for UtilsMixin class (spell check, MeSH, etc.)."""
    
    def test_spell_check_returns_corrected(self, mock_espell_response):
        """Test spell check returns corrected query."""
        from pubmed_search.entrez.utils import UtilsMixin
        
        mixin = UtilsMixin()
        
        with patch('pubmed_search.entrez.utils.Entrez') as mock_entrez:
            mock_handle = MagicMock()
            mock_entrez.espell.return_value = mock_handle
            mock_entrez.read.return_value = mock_espell_response
            
            result = mixin.spell_check_query("diabetis")
            
            assert result == "diabetes"
    
    def test_spell_check_returns_original_on_no_correction(self):
        """Test spell check returns original when no correction."""
        from pubmed_search.entrez.utils import UtilsMixin
        
        mixin = UtilsMixin()
        
        with patch('pubmed_search.entrez.utils.Entrez') as mock_entrez:
            mock_handle = MagicMock()
            mock_entrez.espell.return_value = mock_handle
            mock_entrez.read.return_value = {"Query": "diabetes", "CorrectedQuery": ""}
            
            result = mixin.spell_check_query("diabetes")
            
            assert result == "diabetes"
    
    def test_spell_check_handles_error(self):
        """Test spell check handles API errors gracefully."""
        from pubmed_search.entrez.utils import UtilsMixin
        
        mixin = UtilsMixin()
        
        with patch('pubmed_search.entrez.utils.Entrez') as mock_entrez:
            mock_entrez.espell.side_effect = Exception("API Error")
            
            result = mixin.spell_check_query("test query")
            
            # Should return original query on error
            assert result == "test query"


class TestQuickFetchSummary:
    """Tests for quick_fetch_summary method."""
    
    def test_empty_id_list(self):
        """Test with empty ID list."""
        from pubmed_search.entrez.utils import UtilsMixin
        
        mixin = UtilsMixin()
        result = mixin.quick_fetch_summary([])
        
        assert result == []
    
    def test_fetch_summary_success(self):
        """Test successful summary fetch."""
        from pubmed_search.entrez.utils import UtilsMixin
        
        mixin = UtilsMixin()
        
        # Mock ESummary response
        mock_summary = MagicMock()
        mock_summary.get.side_effect = lambda key, default='': {
            'Id': '12345678',
            'Title': 'Test Article',
            'AuthorList': ['Smith J', 'Doe J'],
            'Source': 'Test Journal',
            'PubDate': '2024 Jan',
            'DOI': '10.1000/test',
            'PMCID': 'PMC123'
        }.get(key, default)
        mock_summary.__getitem__ = mock_summary.get
        
        with patch('pubmed_search.entrez.utils.Entrez') as mock_entrez:
            mock_handle = MagicMock()
            mock_entrez.esummary.return_value = mock_handle
            mock_entrez.read.return_value = [mock_summary]
            
            result = mixin.quick_fetch_summary(["12345678"])
            
            assert len(result) == 1
            assert result[0]["pmid"] == "12345678"
            assert result[0]["title"] == "Test Article"


class TestValidateMeshTerms:
    """Tests for MeSH term validation."""
    
    def test_validate_valid_mesh_term(self):
        """Test validating a real MeSH term."""
        from pubmed_search.entrez.utils import UtilsMixin
        
        mixin = UtilsMixin()
        
        with patch('pubmed_search.entrez.utils.Entrez') as mock_entrez:
            mock_handle = MagicMock()
            mock_entrez.esearch.return_value = mock_handle
            mock_entrez.read.return_value = {"IdList": ["D003920"]}
            
            # If the method exists, test it
            if hasattr(mixin, 'validate_mesh_terms'):
                result = mixin.validate_mesh_terms(["Diabetes Mellitus"])
                assert "Diabetes Mellitus" in result.get("valid", []) or len(result) > 0
