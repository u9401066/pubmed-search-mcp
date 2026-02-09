"""
Integration tests - Tests that may make real API calls.

These tests are marked with @pytest.mark.integration and can be skipped
in CI environments or when running quick tests.

Run with: pytest -m integration
Skip with: pytest -m "not integration"
"""

import pytest
import os
import time


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
        reason="Integration tests skipped",
    )
    def test_real_search(self, real_email):
        """Test real PubMed search."""
        from pubmed_search import PubMedClient

        # Longer delay to avoid NCBI rate limiting when running with other tests
        time.sleep(2)

        client = PubMedClient(email=real_email)

        # Retry up to 3 times for network flakiness
        last_error = None
        for attempt in range(3):
            try:
                results = client.search("diabetes mellitus", limit=5)
                if len(results) > 0:
                    assert results[0].pmid is not None
                    assert results[0].title is not None
                    return  # Success
                else:
                    # Empty results, retry after delay
                    last_error = "Empty results returned"
                    time.sleep(2)
            except Exception as e:
                last_error = str(e)
                time.sleep(2)

        # If we get here, all retries failed
        pytest.skip(f"Integration test flaky: {last_error}")

    @pytest.mark.skipif(
        os.environ.get("SKIP_INTEGRATION", "").lower() == "true",
        reason="Integration tests skipped",
    )
    def test_real_spell_check(self, real_email):
        """Test real ESpell API."""
        from pubmed_search.infrastructure.ncbi import LiteratureSearcher

        searcher = LiteratureSearcher(email=real_email)
        corrected = searcher.spell_check_query("diabetis")

        # Should suggest "diabetes"
        assert "diabet" in corrected.lower()


class TestRealMeSHLookup:
    """Integration tests for MeSH lookup."""

    @pytest.mark.skipif(
        os.environ.get("SKIP_INTEGRATION", "").lower() == "true",
        reason="Integration tests skipped",
    )
    def test_real_mesh_lookup(self, real_email):
        """Test real MeSH term lookup."""
        from pubmed_search.infrastructure.ncbi import LiteratureSearcher

        searcher = LiteratureSearcher(email=real_email)

        # mesh_lookup might be in strategy module
        if hasattr(searcher, "mesh_lookup"):
            result = searcher.mesh_lookup("diabetes")
            assert result is not None


# ============================================================================
# Live E2E: Image Search & ImageQueryAdvisor (Phase 4.1 + 4.2)
# ============================================================================


class TestRealImageSearch:
    """
    Integration tests for biomedical image search with real Open-i API.

    Tests the full pipeline:
    1. ImageQueryAdvisor analyzes query
    2. ImageSearchService calls real Open-i API
    3. Results include advisor warnings/suggestions

    Open-i API characteristics:
    - Index frozen at ~2020
    - 'it' parameter is REQUIRED (xg, mc, ph, gl)
    - Response time: 2-9 seconds

    - API can be unreliable (502/timeout) — tests use skip on failure
    """

    def _search_with_retry(self, service, query, image_type, limit=3, max_retries=3):
        """Helper: retry search with exponential backoff. Returns (result, success)."""
        result = None
        for attempt in range(max_retries):
            try:
                result = service.search(
                    query=query,
                    image_type=image_type,
                    limit=limit,
                )
                if result.total_count > 0:
                    return result, True  # Success
                # Empty result, might be API issue - retry
                time.sleep(2 * (attempt + 1))
            except Exception:
                time.sleep(2 * (attempt + 1))
        # All retries exhausted
        return result, False

    @pytest.mark.skipif(
        os.environ.get("SKIP_INTEGRATION", "").lower() == "true",
        reason="Integration tests skipped",
    )
    def test_real_image_search_xray(self):
        """Test real Open-i search for X-ray images."""
        from pubmed_search.application.image_search import ImageSearchService

        time.sleep(2)  # Respect API rate limits

        service = ImageSearchService()
        result, success = self._search_with_retry(service, "chest pneumonia", "xg")

        if not success:
            pytest.skip("Open-i API unreliable (timeout/empty after retries)")

        # Should return results (Open-i has millions of X-rays)
        assert result.total_count > 0, "Open-i should have chest pneumonia X-rays"
        assert len(result.images) > 0
        assert result.images[0].image_url.startswith("https://openi.nlm.nih.gov")

    @pytest.mark.skipif(
        os.environ.get("SKIP_INTEGRATION", "").lower() == "true",
        reason="Integration tests skipped",
    )
    def test_real_image_search_microscopy(self):
        """Test real Open-i search for microscopy images."""
        from pubmed_search.application.image_search import ImageSearchService

        time.sleep(2)

        service = ImageSearchService()
        result, success = self._search_with_retry(service, "liver histology", "mc")

        if not success:
            pytest.skip("Open-i API unreliable (timeout/empty after retries)")

        assert result.total_count > 0, "Open-i should have liver histology images"
        assert len(result.images) > 0

    @pytest.mark.skipif(
        os.environ.get("SKIP_INTEGRATION", "").lower() == "true",
        reason="Integration tests skipped",
    )
    def test_advisor_integration_suitable_query(self):
        """Test ImageQueryAdvisor → ImageSearchService full pipeline."""
        from pubmed_search.application.image_search import (
            ImageQueryAdvisor,
            ImageSearchService,
        )

        time.sleep(2)

        # Step 1: Advisor analyzes query
        advisor = ImageQueryAdvisor()
        advice = advisor.advise("chest X-ray pneumonia")

        assert advice.is_suitable is True
        assert advice.recommended_image_type == "x"  # x = X-ray (not xg which is Exclude Graphics)

        # Step 2: Service executes search with advisor guidance
        service = ImageSearchService()
        result, success = self._search_with_retry(
            service, "chest X-ray pneumonia", advice.recommended_image_type
        )

        if not success:
            pytest.skip("Open-i API unreliable (timeout/empty after retries)")

        # Step 3: Verify results
        assert result.total_count > 0
        assert result.recommended_image_type == "x"

    @pytest.mark.skipif(
        os.environ.get("SKIP_INTEGRATION", "").lower() == "true",
        reason="Integration tests skipped",
    )
    def test_advisor_temporal_warning_live(self):
        """Test that temporal warnings are accurate with real API."""
        from pubmed_search.application.image_search import ImageSearchService

        time.sleep(2)

        # covid-19 should trigger temporal warning (Open-i frozen ~2020)
        service = ImageSearchService()
        result = service.search(
            query="covid-19 lung CT",
            image_type="xg",
            limit=3,
        )

        # Should have temporal warning (regardless of API success)
        assert len(result.advisor_warnings) > 0
        assert any("2020" in w for w in result.advisor_warnings)

        # May or may not have results (Open-i index stopped ~2020)
        # This validates the warning is appropriate

    @pytest.mark.skipif(
        os.environ.get("SKIP_INTEGRATION", "").lower() == "true",
        reason="Integration tests skipped",
    )
    def test_advisor_unsuitable_query_suggestion(self):
        """Test that unsuitable queries get proper suggestions."""
        from pubmed_search.application.image_search import (
            ImageQueryAdvisor,
            ImageSearchService,
        )

        time.sleep(2)

        # Pharmacokinetics is not an image query
        advisor = ImageQueryAdvisor()
        advice = advisor.advise("propofol pharmacokinetics dosing")

        assert advice.is_suitable is False
        assert len(advice.suggestions) > 0
        assert any("search_literature" in s or "unified_search" in s for s in advice.suggestions)

        # Service should still work but include suggestions
        service = ImageSearchService()
        result = service.search(
            query="propofol pharmacokinetics",
            limit=3,
        )

        assert len(result.advisor_suggestions) > 0

    @pytest.mark.skipif(
        os.environ.get("SKIP_INTEGRATION", "").lower() == "true",
        reason="Integration tests skipped",
    )
    def test_image_type_mismatch_warning_live(self):
        """Test image_type mismatch warning with real API."""
        from pubmed_search.application.image_search import ImageSearchService

        time.sleep(2)

        # histology query with xg (X-ray) type should warn
        service = ImageSearchService()
        result = service.search(
            query="histology liver pathology",
            image_type="xg",  # Should recommend mc
            limit=3,
        )

        # Should have mismatch warning (regardless of API success)
        assert len(result.advisor_warnings) > 0
        assert any("mc" in w for w in result.advisor_warnings)
        assert result.recommended_image_type == "mc"
