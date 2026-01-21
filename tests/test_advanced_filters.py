#!/usr/bin/env python3
"""Test advanced PubMed filters (Phase 2.1)."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pubmed_search.entrez import LiteratureSearcher


def test_advanced_filters():
    """Test age_group, sex, species, language, clinical_query filters."""
    searcher = LiteratureSearcher()

    # Test 1: aged + therapy filter
    print('=== Test 1: diabetes + aged + therapy + humans ===')
    results = searcher.search(
        query='diabetes treatment',
        limit=3,
        age_group='aged',
        clinical_query='therapy',
        species='humans'
    )
    print(f'Results: {len(results)}')
    for r in results[:3]:
        if r and 'title' in r:
            print(f"  - {r['title'][:60]}...")
            print(f"    PMID: {r.get('pmid', 'N/A')}")

    # Test 2: sex filter
    print()
    print('=== Test 2: breast cancer + female + humans ===')
    results2 = searcher.search(
        query='breast cancer screening',
        limit=3,
        sex='female',
        species='humans'
    )
    print(f'Results: {len(results2)}')
    for r in results2[:3]:
        if r and 'title' in r:
            print(f"  - {r['title'][:60]}...")

    # Test 3: language filter (English only)
    print()
    print('=== Test 3: COVID + language=english ===')
    results3 = searcher.search(
        query='COVID-19 vaccine',
        limit=3,
        language='english'
    )
    print(f'Results: {len(results3)}')
    for r in results3[:3]:
        if r and 'title' in r:
            print(f"  - {r['title'][:60]}...")

    # Test 4: clinical query - diagnosis
    print()
    print('=== Test 4: lung cancer + diagnosis filter ===')
    results4 = searcher.search(
        query='lung cancer',
        limit=3,
        clinical_query='diagnosis'
    )
    print(f'Results: {len(results4)}')
    for r in results4[:3]:
        if r and 'title' in r:
            print(f"  - {r['title'][:60]}...")

    # Test 5: pediatric (child age group)
    print()
    print('=== Test 5: asthma + child age group ===')
    results5 = searcher.search(
        query='asthma treatment',
        limit=3,
        age_group='child'
    )
    print(f'Results: {len(results5)}')
    for r in results5[:3]:
        if r and 'title' in r:
            print(f"  - {r['title'][:60]}...")

    print()
    print('✅ All advanced filter tests completed!')


if __name__ == '__main__':
    test_advanced_filters()
