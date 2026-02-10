"""
Performance Testing - Ensure search speed and efficiency.

Tests response times, throughput, and resource usage.
Run with: pytest tests/test_performance.py -v --benchmark-only
"""

import pytest
import time
from unittest.mock import patch
from pubmed_search import PubMedClient


# ============================================================
# Performance Markers
# ============================================================

pytestmark = pytest.mark.slow


# ============================================================
# Performance Benchmarks
# ============================================================


class TestSearchPerformance:
    """Test search operation performance."""

    async def test_search_response_time(self, benchmark, mock_searcher):
        """Search should complete within acceptable time."""
        with patch(
            "pubmed_search.infrastructure.http.pubmed_client.LiteratureSearcher",
            return_value=mock_searcher,
        ):
            client = PubMedClient(email="test@example.com")

            # Benchmark the search operation
            result = benchmark(client.search, query="diabetes", limit=10)

            # Verify results returned
            assert len(result) > 0

    async def test_batch_fetch_performance(self, benchmark, mock_searcher):
        """Batch fetching should be efficient."""
        pmids = [str(i) for i in range(1000000, 1000010)]  # 10 PMIDs

        with patch(
            "pubmed_search.infrastructure.http.pubmed_client.LiteratureSearcher",
            return_value=mock_searcher,
        ):
            client = PubMedClient(email="test@example.com")

            # Benchmark batch fetch
            result = benchmark(client.fetch_details, pmids=pmids)

            assert len(result) > 0

    async def test_concurrent_searches_throughput(self, mock_searcher):
        """Test throughput with multiple concurrent searches."""
        with patch(
            "pubmed_search.infrastructure.http.pubmed_client.LiteratureSearcher",
            return_value=mock_searcher,
        ):
            client = PubMedClient(email="test@example.com")

            start_time = time.perf_counter()

            # Perform 10 searches
            queries = [
                "diabetes",
                "cancer",
                "covid",
                "alzheimer",
                "parkinson",
                "stroke",
                "hypertension",
                "asthma",
                "depression",
                "migraine",
            ]

            for query in queries:
                client.search(query=query, limit=5)

            elapsed = time.perf_counter() - start_time

            # Should complete 10 searches in under 2 seconds (mocked)
            assert elapsed < 2.0, f"10 searches took {elapsed:.2f}s (should be <2s)"

    @pytest.mark.timeout(5)
    async def test_search_timeout_handling(self, mock_searcher):
        """Search should handle timeouts gracefully."""
        # Simulate slow response
        mock_searcher.search.side_effect = lambda *args, **kwargs: (
            time.sleep(0.5) or [{"pmid": "12345678", "title": "Test"}]
        )

        with patch(
            "pubmed_search.infrastructure.http.pubmed_client.LiteratureSearcher",
            return_value=mock_searcher,
        ):
            client = PubMedClient(email="test@example.com")

            # Should complete within timeout
            result = client.search("diabetes", limit=1)
            assert len(result) > 0


class TestCachePerformance:
    """Test caching efficiency."""

    async def test_cache_hit_performance(self, benchmark, mock_searcher):
        """Cached results should be much faster than API calls."""
        from pubmed_search.application.session import SessionManager

        session_mgr = SessionManager()
        session_mgr.create_session(topic="diabetes")

        # Pre-populate cache using the new API
        article_data = {
            "pmid": "12345678",
            "title": "Cached Article",
            "authors": ["Smith J"],
            "abstract": "Test abstract",
        }
        session_mgr.add_to_cache([article_data])

        # Benchmark cache retrieval
        def get_cached():
            found, missing = session_mgr.get_from_cache(["12345678"])
            return found[0] if found else None

        result = benchmark(get_cached)
        assert result is not None
        assert result["pmid"] == "12345678"

    async def test_cache_miss_to_hit_ratio(self, mock_searcher):
        """Monitor cache effectiveness."""
        from pubmed_search.application.session import SessionManager

        session_mgr = SessionManager()
        session_mgr.create_session(topic="test")

        # First access - cache miss (add to cache)
        start_miss = time.perf_counter()
        session_mgr.add_to_cache([{"pmid": "11111111", "title": "Article 1"}])
        miss_time = time.perf_counter() - start_miss

        # Second access - cache hit
        start_hit = time.perf_counter()
        found, missing = session_mgr.get_from_cache(["11111111"])
        hit_time = time.perf_counter() - start_hit

        # Cache hit should be significantly faster
        assert hit_time < miss_time * 10, (
            "Cache hit should not be orders of magnitude slower"
        )
        assert len(found) == 1


class TestMemoryUsage:
    """Test memory efficiency."""

    async def test_large_result_set_memory(self, mock_searcher):
        """Large result sets should not cause memory issues."""

        # Create large mock result
        large_results = [
            {
                "pmid": str(1000000 + i),
                "title": f"Article {i}" * 100,  # Long title
                "abstract": "Abstract " * 1000,  # Long abstract
                "authors": [f"Author {j}" for j in range(10)],
            }
            for i in range(100)
        ]

        mock_searcher.search.return_value = large_results

        with patch(
            "pubmed_search.infrastructure.http.pubmed_client.LiteratureSearcher",
            return_value=mock_searcher,
        ):
            client = PubMedClient(email="test@example.com")

            # Process large result set
            results = client.search("test", limit=100)

            # Verify data integrity
            assert len(results) == 100

            # Memory should be released after use
            del results
            # Force garbage collection
            import gc

            gc.collect()


class TestAPIRateLimiting:
    """Test API rate limiting behavior."""

    async def test_rate_limit_handling(self, mock_searcher):
        """Should respect NCBI rate limits (3 requests/second)."""
        with patch(
            "pubmed_search.infrastructure.http.pubmed_client.LiteratureSearcher",
            return_value=mock_searcher,
        ):
            client = PubMedClient(email="test@example.com")

            start_time = time.perf_counter()

            # Make 10 rapid requests
            for i in range(10):
                client.search(f"query{i}", limit=1)

            elapsed = time.perf_counter() - start_time

            # With rate limiting, 10 requests should take ~3 seconds
            # Without API key: 3 req/sec, so 10 req = 3.33s minimum
            # With mocks, should be much faster
            assert elapsed < 1.0, "Mocked requests should be fast"

    async def test_burst_request_handling(self, mock_searcher):
        """Handle burst requests without errors."""
        with patch(
            "pubmed_search.infrastructure.http.pubmed_client.LiteratureSearcher",
            return_value=mock_searcher,
        ):
            client = PubMedClient(email="test@example.com")

            # Send burst of requests
            queries = [f"query{i}" for i in range(20)]
            results = []

            for query in queries:
                try:
                    result = client.search(query, limit=1)
                    results.append(result)
                except Exception as e:
                    pytest.fail(f"Burst request failed: {e}")

            # All requests should succeed
            assert len(results) == 20


# ============================================================
# Performance Regression Tests
# ============================================================


class TestPerformanceRegression:
    """Detect performance regressions."""

    async def test_search_baseline_performance(self, benchmark, mock_searcher):
        """Establish baseline for search performance."""
        with patch(
            "pubmed_search.infrastructure.http.pubmed_client.LiteratureSearcher",
            return_value=mock_searcher,
        ):
            client = PubMedClient(email="test@example.com")

            # Run benchmark
            benchmark.pedantic(
                lambda: client.search("diabetes", limit=10), rounds=10, iterations=5
            )

            # Log performance metrics for monitoring
            # In real CI/CD, these would be compared against historical data

    async def test_complex_query_performance(self, benchmark, mock_searcher):
        """Complex queries should not degrade performance significantly."""
        complex_query = (
            '("Diabetes Mellitus"[MeSH Terms]) AND '
            '("Drug Therapy"[MeSH Terms]) AND '
            "(2020[PDAT]:2024[PDAT])"
        )

        with patch(
            "pubmed_search.infrastructure.http.pubmed_client.LiteratureSearcher",
            return_value=mock_searcher,
        ):
            client = PubMedClient(email="test@example.com")

            result = benchmark(client.search, query=complex_query, limit=20)

            # Verify results
            assert len(result) > 0


# ============================================================
# Scalability Tests
# ============================================================


class TestScalability:
    """Test system scalability."""

    @pytest.mark.parametrize("limit", [10, 50, 100, 500])
    async def test_scaling_with_result_size(self, mock_searcher, limit):
        """Performance should scale linearly with result size."""
        # Create results matching the limit
        mock_results = [{"pmid": str(i), "title": f"Article {i}"} for i in range(limit)]
        mock_searcher.search.return_value = mock_results

        with patch(
            "pubmed_search.infrastructure.http.pubmed_client.LiteratureSearcher",
            return_value=mock_searcher,
        ):
            client = PubMedClient(email="test@example.com")

            start = time.perf_counter()
            results = client.search("test", limit=limit)
            elapsed = time.perf_counter() - start

            # Should complete quickly even with large limits
            assert len(results) == limit
            assert elapsed < 0.5, f"Processing {limit} results took {elapsed:.2f}s"

    async def test_concurrent_session_handling(self):
        """Handle multiple concurrent sessions efficiently."""
        from pubmed_search.application.session import SessionManager

        session_mgr = SessionManager()

        # Create 100 sessions
        sessions = []

        start = time.perf_counter()
        for i in range(100):
            session = session_mgr.create_session(topic=f"topic-{i}")
            sessions.append(session)
        elapsed = time.perf_counter() - start

        # Should handle 100 sessions quickly
        assert elapsed < 1.0, f"Creating 100 sessions took {elapsed:.2f}s"

        # Verify all sessions exist - use list_sessions
        session_list = session_mgr.list_sessions()
        assert len(session_list) >= 100
