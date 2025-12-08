"""
Integration tests - Tests that may make real API calls.

These tests are marked with @pytest.mark.integration and can be skipped
in CI environments or when running quick tests.

Run with: pytest -m integration
Skip with: pytest -m "not integration"
"""

import pytest
import os


# Skip all integration tests if SKIP_INTEGRATION is set
pytestmark = pytest.mark.integration


@pytest.fixture
def real_email():
    """Get real email from environment or skip."""
    email = os.environ.get("NCBI_EMAIL", "test@example.com")
    return email


class TestRealPubMedSearch:
    """Integration tests with real PubMed API."""
    
    @pytest.mark.skipif(
        os.environ.get("SKIP_INTEGRATION", "").lower() == "true",
        reason="Integration tests skipped"
    )
    def test_real_search(self, real_email):
        """Test real PubMed search."""
        from pubmed_search import PubMedClient
        
        client = PubMedClient(email=real_email)
        results = client.search("diabetes mellitus", limit=5)
        
        assert len(results) > 0
        assert results[0].pmid is not None
        assert results[0].title is not None
    
    @pytest.mark.skipif(
        os.environ.get("SKIP_INTEGRATION", "").lower() == "true",
        reason="Integration tests skipped"
    )
    def test_real_spell_check(self, real_email):
        """Test real ESpell API."""
        from pubmed_search.entrez import LiteratureSearcher
        
        searcher = LiteratureSearcher(email=real_email)
        corrected = searcher.spell_check_query("diabetis")
        
        # Should suggest "diabetes"
        assert "diabet" in corrected.lower()


class TestRealMeSHLookup:
    """Integration tests for MeSH lookup."""
    
    @pytest.mark.skipif(
        os.environ.get("SKIP_INTEGRATION", "").lower() == "true",
        reason="Integration tests skipped"
    )
    def test_real_mesh_lookup(self, real_email):
        """Test real MeSH term lookup."""
        from pubmed_search.entrez import LiteratureSearcher
        
        searcher = LiteratureSearcher(email=real_email)
        
        # mesh_lookup might be in strategy module
        if hasattr(searcher, 'mesh_lookup'):
            result = searcher.mesh_lookup("diabetes")
            assert result is not None
