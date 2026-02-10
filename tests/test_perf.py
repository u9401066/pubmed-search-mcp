"""
Performance test for unified_search.

Integration test - makes real API calls. Not for CI.
"""

import time
import logging

import pytest

# Enable logging to see what's happening
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger()


@pytest.mark.skip(reason="Integration test - makes real API calls, not for CI")
def test_perf_integration():
    print("=" * 60)
    print("Testing unified_search performance")
    print("=" * 60)

    # Test 1: Simple query - should be fast
    query = "aspirin mechanism"
    print(f'\nTest 1: Simple query "{query}"')
    print("-" * 40)

    start = time.time()
    try:
        from pubmed_search.application.search.query_analyzer import QueryAnalyzer

        analyzer = QueryAnalyzer()
        analysis = analyzer.analyze(query)
        analyze_time = time.time() - start
        print(f"  Query analysis: {analyze_time:.2f}s")
        print(f"  Complexity: {analysis.complexity.value}")
        print(f"  Intent: {analysis.intent.value}")
        print(f"  Recommended sources: {analysis.recommended_sources}")
    except Exception as e:
        print(f"  Error: {e}")

    # Test 2: PubMed search timing
    print("\nTest 2: PubMed search timing")
    print("-" * 40)
    start = time.time()
    try:
        from pubmed_search.infrastructure.ncbi import LiteratureSearcher

        searcher = LiteratureSearcher()
        results = searcher.search(query="aspirin mechanism", limit=5)
        pubmed_time = time.time() - start
        print(f"  PubMed search: {pubmed_time:.2f}s")
        print(f"  Results: {len(results)}")
    except Exception as e:
        print(f"  Error: {e}")

    # Test 3: OpenAlex search timing
    print("\nTest 3: OpenAlex search timing")
    print("-" * 40)
    start = time.time()
    try:
        from pubmed_search.infrastructure.sources.openalex import OpenAlexClient

        client = OpenAlexClient()
        results = client.search("aspirin mechanism", limit=5)
        openalex_time = time.time() - start
        print(f"  OpenAlex search: {openalex_time:.2f}s")
        print(f"  Results: {len(results)}")
    except Exception as e:
        print(f"  Error: {e}")

    # Test 4: Semantic Scholar search timing
    print("\nTest 4: Semantic Scholar search timing")
    print("-" * 40)
    start = time.time()
    try:
        from pubmed_search.infrastructure.sources.semantic_scholar import (
            SemanticScholarClient,
        )

        client = SemanticScholarClient()
        results = client.search("aspirin mechanism", limit=5)
        s2_time = time.time() - start
        print(f"  Semantic Scholar search: {s2_time:.2f}s")
        print(f"  Results: {len(results)}")
    except Exception as e:
        print(f"  Error: {e}")

    print("\n" + "=" * 60)
    print("Done.")
