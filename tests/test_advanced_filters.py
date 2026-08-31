#!/usr/bin/env python3
"""Test advanced PubMed filters (Phase 2.1).

This is an integration test that makes REAL network calls to NCBI.
Skip in normal test runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pubmed_search.infrastructure.ncbi import LiteratureSearcher


@pytest.mark.skip(reason="Integration test - makes real NCBI API calls, not for CI")
async def test_advanced_filters():
    """Test age_group, sex, species, language, clinical_query filters."""
    searcher = LiteratureSearcher()

    # Test 1: aged + therapy filter
    print("=== Test 1: diabetes + aged + therapy + humans ===")
    page = await searcher.search_page(
        query="diabetes treatment",
        limit=3,
        age_group="aged",
        clinical_query="therapy",
        species="humans",
    )
    print(f"Results: {len(page.items)}")
    for r in page.items[:3]:
        if r and "title" in r:
            print(f"  - {r['title'][:60]}...")
            print(f"    PMID: {r.get('pmid', 'N/A')}")

    # Test 2: sex filter
    print()
    print("=== Test 2: breast cancer + female + humans ===")
    page2 = await searcher.search_page(query="breast cancer screening", limit=3, sex="female", species="humans")
    print(f"Results: {len(page2.items)}")
    for r in page2.items[:3]:
        if r and "title" in r:
            print(f"  - {r['title'][:60]}...")

    # Test 3: language filter (English only)
    print()
    print("=== Test 3: COVID + language=english ===")
    page3 = await searcher.search_page(query="COVID-19 vaccine", limit=3, language="english")
    print(f"Results: {len(page3.items)}")
    for r in page3.items[:3]:
        if r and "title" in r:
            print(f"  - {r['title'][:60]}...")

    # Test 4: clinical query - diagnosis
    print()
    print("=== Test 4: lung cancer + diagnosis filter ===")
    page4 = await searcher.search_page(query="lung cancer", limit=3, clinical_query="diagnosis")
    print(f"Results: {len(page4.items)}")
    for r in page4.items[:3]:
        if r and "title" in r:
            print(f"  - {r['title'][:60]}...")

    # Test 5: pediatric (child age group)
    print()
    print("=== Test 5: asthma + child age group ===")
    page5 = await searcher.search_page(query="asthma treatment", limit=3, age_group="child")
    print(f"Results: {len(page5.items)}")
    for r in page5.items[:3]:
        if r and "title" in r:
            print(f"  - {r['title'][:60]}...")

    print()
    print("??All advanced filter tests completed!")


if __name__ == "__main__":
    test_advanced_filters()
