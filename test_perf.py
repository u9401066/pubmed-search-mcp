"""
Performance test for unified_search
"""
import time
import logging

# Enable logging to see what's happening
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

print('='*60)
print('Testing unified_search performance')
print('='*60)

# Test 1: Simple query - should be fast
query = 'aspirin mechanism'
print(f'\nTest 1: Simple query "{query}"')
print('-'*40)

start = time.time()
try:
    from pubmed_search.unified.query_analyzer import QueryAnalyzer
    analyzer = QueryAnalyzer()
    analysis = analyzer.analyze(query)
    analyze_time = time.time() - start
    print(f'  Query analysis: {analyze_time:.2f}s')
    print(f'  Complexity: {analysis.complexity.value}')
    print(f'  Intent: {analysis.intent.value}')
    print(f'  Recommended sources: {analysis.recommended_sources}')
except Exception as e:
    print(f'  Error: {e}')

# Test 2: PubMed search timing
print(f'\nTest 2: PubMed search timing')
print('-'*40)
start = time.time()
try:
    from pubmed_search.entrez import LiteratureSearcher
    searcher = LiteratureSearcher()
    results = searcher.search(query='aspirin mechanism', limit=5)
    pubmed_time = time.time() - start
    print(f'  PubMed search: {pubmed_time:.2f}s')
    print(f'  Results: {len(results)}')
except Exception as e:
    print(f'  Error: {e}')

# Test 3: OpenAlex search timing
print(f'\nTest 3: OpenAlex search timing')
print('-'*40)
start = time.time()
try:
    from pubmed_search.sources.openalex import OpenAlexClient
    client = OpenAlexClient()
    results = client.search('aspirin mechanism', limit=5)
    openalex_time = time.time() - start
    print(f'  OpenAlex search: {openalex_time:.2f}s')
    print(f'  Results: {len(results)}')
except Exception as e:
    print(f'  Error: {e}')

# Test 4: Semantic Scholar search timing
print(f'\nTest 4: Semantic Scholar search timing')
print('-'*40)
start = time.time()
try:
    from pubmed_search.sources.semantic_scholar import SemanticScholarClient
    client = SemanticScholarClient()
    results = client.search('aspirin mechanism', limit=5)
    s2_time = time.time() - start
    print(f'  Semantic Scholar search: {s2_time:.2f}s')
    print(f'  Results: {len(results)}')
except Exception as e:
    print(f'  Error: {e}')

print(f'\n' + '='*60)
print('Done.')
