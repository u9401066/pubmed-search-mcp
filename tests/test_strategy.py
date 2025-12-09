"""
Tests for Search Strategy Generator and related functions.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json


class TestSearchStrategyGenerator:
    """Tests for SearchStrategyGenerator class."""
    
    @pytest.fixture
    def strategy_generator(self):
        """Create a strategy generator for testing."""
        from pubmed_search.entrez.strategy import SearchStrategyGenerator
        return SearchStrategyGenerator(email="test@example.com")
    
    def test_init(self, strategy_generator):
        """Test strategy generator initialization."""
        assert strategy_generator is not None
    
    def test_spell_check_no_correction(self, strategy_generator):
        """Test spell check when no correction needed."""
        with patch('pubmed_search.entrez.strategy.Entrez.espell') as mock_espell, \
             patch('pubmed_search.entrez.strategy.Entrez.read') as mock_read:
            
            mock_read.return_value = {"CorrectedQuery": "diabetes"}
            mock_espell.return_value = MagicMock()
            
            corrected, was_corrected = strategy_generator.spell_check("diabetes")
            
            assert corrected == "diabetes"
            assert was_corrected is False
    
    def test_spell_check_with_correction(self, strategy_generator):
        """Test spell check when correction is made."""
        with patch('pubmed_search.entrez.strategy.Entrez.espell') as mock_espell, \
             patch('pubmed_search.entrez.strategy.Entrez.read') as mock_read:
            
            mock_read.return_value = {"CorrectedQuery": "diabetes"}
            mock_espell.return_value = MagicMock()
            
            corrected, was_corrected = strategy_generator.spell_check("diabetis")
            
            assert corrected == "diabetes"
            assert was_corrected is True
    
    def test_spell_check_error(self, strategy_generator):
        """Test spell check handles errors gracefully."""
        with patch('pubmed_search.entrez.strategy.Entrez.espell') as mock_espell:
            mock_espell.side_effect = Exception("API Error")
            
            corrected, was_corrected = strategy_generator.spell_check("test")
            
            assert corrected == "test"
            assert was_corrected is False
    
    def test_get_mesh_info_found(self, strategy_generator):
        """Test getting MeSH info when term is found."""
        with patch('pubmed_search.entrez.strategy.Entrez.esearch') as mock_esearch, \
             patch('pubmed_search.entrez.strategy.Entrez.efetch') as mock_efetch, \
             patch('pubmed_search.entrez.strategy.Entrez.read') as mock_read:
            
            mock_read.return_value = {"IdList": ["D003920"]}
            mock_esearch.return_value = MagicMock()
            
            # Mock text response
            mock_fetch_handle = MagicMock()
            mock_fetch_handle.read.return_value = """1: Diabetes Mellitus
Entry Terms:
    Diabetes
    Type 2 Diabetes
Tree Number(s): C18.452.394.750"""
            mock_efetch.return_value = mock_fetch_handle
            
            result = strategy_generator.get_mesh_info("diabetes")
            
            assert result is not None
            assert result["mesh_id"] == "D003920"
            assert "Diabetes Mellitus" in result["preferred_term"]
    
    def test_get_mesh_info_not_found(self, strategy_generator):
        """Test getting MeSH info when term is not found."""
        with patch('pubmed_search.entrez.strategy.Entrez.esearch') as mock_esearch, \
             patch('pubmed_search.entrez.strategy.Entrez.read') as mock_read:
            
            mock_read.return_value = {"IdList": []}
            mock_esearch.return_value = MagicMock()
            
            result = strategy_generator.get_mesh_info("nonexistentterm12345")
            
            assert result is None
    
    def test_get_mesh_info_error(self, strategy_generator):
        """Test getting MeSH info handles errors gracefully."""
        with patch('pubmed_search.entrez.strategy.Entrez.esearch') as mock_esearch:
            mock_esearch.side_effect = Exception("API Error")
            
            result = strategy_generator.get_mesh_info("test")
            
            assert result is None
    
    def test_analyze_query(self, strategy_generator):
        """Test query analysis."""
        with patch('pubmed_search.entrez.strategy.Entrez.esearch') as mock_esearch, \
             patch('pubmed_search.entrez.strategy.Entrez.read') as mock_read:
            
            mock_read.return_value = {
                "Count": "1234",
                "QueryTranslation": '"diabetes mellitus"[MeSH Terms]',
                "TranslationSet": [],
                "TranslationStack": []
            }
            mock_esearch.return_value = MagicMock()
            
            result = strategy_generator.analyze_query("diabetes")
            
            assert result["original"] == "diabetes"
            assert result["count"] == 1234
            assert "MeSH Terms" in result["translated_query"]
    
    def test_analyze_query_error(self, strategy_generator):
        """Test query analysis handles errors."""
        with patch('pubmed_search.entrez.strategy.Entrez.esearch') as mock_esearch:
            mock_esearch.side_effect = Exception("API Error")
            
            result = strategy_generator.analyze_query("test")
            
            assert result["original"] == "test"
            assert result["count"] == 0
    
    def test_generate_strategies_basic(self, strategy_generator):
        """Test generating search strategies."""
        with patch.object(strategy_generator, 'spell_check', return_value=("diabetes", False)), \
             patch.object(strategy_generator, 'get_mesh_info', return_value=None), \
             patch.object(strategy_generator, 'analyze_query', return_value={"count": 100}):
            
            result = strategy_generator.generate_strategies(
                topic="diabetes treatment",
                use_mesh=False,
                check_spelling=True,
                include_suggestions=True
            )
            
            assert "topic" in result
            assert "corrected_topic" in result
            assert "suggested_queries" in result
    
    def test_generate_strategies_with_mesh(self, strategy_generator):
        """Test generating strategies with MeSH lookup."""
        mesh_info = {
            "mesh_id": "D003920",
            "preferred_term": "Diabetes Mellitus",
            "synonyms": ["Diabetes", "Type 2 Diabetes"],
            "tree_numbers": ["C18.452"]
        }
        
        with patch.object(strategy_generator, 'spell_check', return_value=("diabetes", False)), \
             patch.object(strategy_generator, 'get_mesh_info', return_value=mesh_info), \
             patch.object(strategy_generator, 'analyze_query', return_value={"count": 100}):
            
            result = strategy_generator.generate_strategies(
                topic="diabetes",
                use_mesh=True,
                include_suggestions=True
            )
            
            assert len(result.get("mesh_terms", [])) > 0 or result.get("mesh_terms") is not None


class TestRetryLogic:
    """Tests for retry logic in strategy module."""
    
    def test_is_retryable_true(self):
        """Test identifying retryable errors."""
        from pubmed_search.entrez.strategy import _is_retryable
        
        assert _is_retryable(Exception("Database is not supported")) is True
        assert _is_retryable(Exception("Backend failed")) is True
        assert _is_retryable(Exception("Server Error")) is True
    
    def test_is_retryable_false(self):
        """Test identifying non-retryable errors."""
        from pubmed_search.entrez.strategy import _is_retryable
        
        assert _is_retryable(Exception("Invalid API key")) is False
        assert _is_retryable(Exception("Rate limit exceeded")) is False


class TestExpandSearchQueries:
    """Tests for expand_search_queries tool."""
    
    def test_expand_mesh_fallback(self):
        """Test MeSH expansion fallback."""
        from pubmed_search.mcp.tools.strategy import register_strategy_tools
        from pubmed_search.mcp.tools._common import set_strategy_generator
        
        set_strategy_generator(None)  # Force fallback
        
        mcp = MagicMock()
        searcher = MagicMock()
        
        registered_fns = {}
        def capture_tool():
            def decorator(fn):
                registered_fns[fn.__name__] = fn
                return fn
            return decorator
        
        mcp.tool = capture_tool
        register_strategy_tools(mcp, searcher)
        
        result = registered_fns["expand_search_queries"](
            topic="icu sedation",
            expansion_type="mesh"
        )
        parsed = json.loads(result)
        
        assert "suggested_queries" in parsed
        # Should have some synonym expansions for 'icu' or 'sedation'
    
    def test_expand_broader(self):
        """Test broader expansion."""
        from pubmed_search.mcp.tools.strategy import register_strategy_tools
        from pubmed_search.mcp.tools._common import set_strategy_generator
        
        set_strategy_generator(None)
        
        mcp = MagicMock()
        searcher = MagicMock()
        
        registered_fns = {}
        def capture_tool():
            def decorator(fn):
                registered_fns[fn.__name__] = fn
                return fn
            return decorator
        
        mcp.tool = capture_tool
        register_strategy_tools(mcp, searcher)
        
        result = registered_fns["expand_search_queries"](
            topic="diabetes treatment",
            expansion_type="broader"
        )
        parsed = json.loads(result)
        
        # Should have broader queries with OR
        queries = parsed.get("suggested_queries", [])
        assert len(queries) > 0
        
        # Check for OR-based query
        or_query_found = any("OR" in q.get("query", "") for q in queries)
        assert or_query_found or any("All Fields" in q.get("query", "") for q in queries)
    
    def test_expand_narrower(self):
        """Test narrower expansion (filters)."""
        from pubmed_search.mcp.tools.strategy import register_strategy_tools
        from pubmed_search.mcp.tools._common import set_strategy_generator
        
        set_strategy_generator(None)
        
        mcp = MagicMock()
        searcher = MagicMock()
        
        registered_fns = {}
        def capture_tool():
            def decorator(fn):
                registered_fns[fn.__name__] = fn
                return fn
            return decorator
        
        mcp.tool = capture_tool
        register_strategy_tools(mcp, searcher)
        
        result = registered_fns["expand_search_queries"](
            topic="diabetes treatment",
            expansion_type="narrower"
        )
        parsed = json.loads(result)
        
        queries = parsed.get("suggested_queries", [])
        assert len(queries) > 0
        
        # Should have RCT or meta-analysis filters
        purposes = [q.get("purpose", "") for q in queries]
        assert any("RCT" in p or "Meta" in p or "recent" in p.lower() for p in purposes)
    
    def test_expand_with_existing_queries(self):
        """Test expansion respects existing query IDs."""
        from pubmed_search.mcp.tools.strategy import register_strategy_tools
        from pubmed_search.mcp.tools._common import set_strategy_generator
        
        set_strategy_generator(None)
        
        mcp = MagicMock()
        searcher = MagicMock()
        
        registered_fns = {}
        def capture_tool():
            def decorator(fn):
                registered_fns[fn.__name__] = fn
                return fn
            return decorator
        
        mcp.tool = capture_tool
        register_strategy_tools(mcp, searcher)
        
        result = registered_fns["expand_search_queries"](
            topic="test",
            existing_query_ids="q1_title,q2_tiab",
            expansion_type="narrower"
        )
        parsed = json.loads(result)
        
        assert "q1_title" in parsed["existing_queries"]
        assert "q2_tiab" in parsed["existing_queries"]
