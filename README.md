# PubMed Search

A standalone Python library for searching PubMed and interacting with NCBI Entrez APIs.

Designed to be used as a submodule in other projects (e.g., `med-paper-assistant`).

## Features

- **PubMed Search**: Search with various strategies (recent, relevance, most cited)
- **Date Filtering**: Precise date range filtering with multiple date types
- **Related Articles**: Discover related articles using PubMed's algorithm
- **Citation Network**: Find citing articles and references
- **PDF Download**: Download full-text PDFs from PubMed Central Open Access
- **Batch Processing**: Efficiently process large result sets using NCBI History Server
- **MeSH Validation**: Validate MeSH terms
- **Citation Matching**: Find articles by citation details

## Installation

### As a standalone package

```bash
pip install -e .
```

### As a Git submodule

```bash
# In your project
git submodule add https://github.com/u9401066/pubmed-search-mcp integrations/pubmed-search-mcp
pip install -e integrations/pubmed-search-mcp
```

## Quick Start

```python
from pubmed_search import PubMedClient, SearchStrategy

# Initialize client (email required by NCBI)
client = PubMedClient(email="your@email.com")

# Basic search
results = client.search("diabetes treatment", limit=5)
for article in results:
    print(f"{article.pmid}: {article.title}")

# Search with date range (YYYY/MM/DD format)
results = client.search(
    "COVID-19 vaccine",
    limit=10,
    date_from="2024/01/01",
    date_to="2024/12/31",
    date_type="edat"  # Entrez date (when added to PubMed)
)

# Search with strategy
results = client.search(
    "machine learning diagnosis",
    limit=10,
    strategy=SearchStrategy.RECENT
)

# Find related articles
related = client.find_related("12345678", limit=5)

# Find citing articles
citing = client.find_citing("12345678", limit=10)

# Download PDF (if available from PMC Open Access)
pdf_bytes = client.download_pdf("12345678")
if pdf_bytes:
    with open("article.pdf", "wb") as f:
        f.write(pdf_bytes)
```

## Low-Level API

For advanced operations, use the `LiteratureSearcher` class directly:

```python
from pubmed_search.entrez import LiteratureSearcher

searcher = LiteratureSearcher(email="your@email.com")

# Get raw dictionaries instead of SearchResult objects
results = searcher.search("cancer therapy", limit=10)

# Use History Server for large result sets
history = searcher.search_with_history("diabetes")
print(f"Total results: {history['count']}")

# Fetch in batches
for start in range(0, min(history['count'], 1000), 100):
    batch = searcher.fetch_batch_from_history(
        history['webenv'],
        history['query_key'],
        start,
        100
    )
    # Process batch...

# Validate MeSH terms
valid = searcher.validate_mesh_terms(["Diabetes Mellitus", "Insulin"])

# Export citations
medline_format = searcher.export_citations(["12345678", "87654321"], format="medline")
```

## Date Type Options

When searching, you can specify which date field to use:

- `edat` (default): **Entrez date** - when the article was added to PubMed. Best for finding newly published articles.
- `pdat`: **Publication date** - the official publication date.
- `mdat`: **Modification date** - when the record was last modified.

## API Key

For higher rate limits (10 requests/second instead of 3), register for an NCBI API key:

1. Go to https://www.ncbi.nlm.nih.gov/account/
2. Create an account or sign in
3. Go to Settings → API Key Management
4. Generate a new key

```python
client = PubMedClient(
    email="your@email.com",
    api_key="your_api_key_here"
)
```

## License

MIT License
