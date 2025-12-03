# PubMed Search MCP

A standalone Python library and MCP (Model Context Protocol) server for PubMed literature search.

## Features

- **Search PubMed**: Full-text and advanced query support
- **Related Articles**: Find papers related to a given PMID
- **Citing Articles**: Find papers that cite a given PMID
- **Parallel Search**: Generate multiple queries for comprehensive searches
- **PDF Access**: Get open-access PDF URLs from PubMed Central
- **MCP Integration**: Use with VS Code + GitHub Copilot or any MCP client
- **Remote Server**: Deploy as HTTP service for multi-machine access

## Installation

### Basic Installation (Library Only)

```bash
pip install pubmed-search
```

### With MCP Server Support

```bash
pip install "pubmed-search[mcp]"
```

### From Source

```bash
git clone https://github.com/u9401066/pubmed-search-mcp.git
cd pubmed-search-mcp
pip install -e ".[all]"
```

## Usage

### As a Python Library

```python
from pubmed_search import PubMedClient

client = PubMedClient(email="your@email.com")

# Search for papers
results = client.search("anesthesia complications", limit=10)
for paper in results:
    print(f"{paper.pmid}: {paper.title}")

# Get related articles
related = client.find_related("12345678", limit=5)

# Get citing articles
citing = client.find_citing("12345678")
```

### As an MCP Server (Local - stdio)

#### VS Code Configuration

Add to your `.vscode/mcp.json`:

```json
{
  "servers": {
    "pubmed-search": {
      "type": "stdio",
      "command": "pubmed-search-mcp",
      "args": ["your@email.com"]
    }
  }
}
```

Or using Python module:

```json
{
  "servers": {
    "pubmed-search": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "pubmed_search.mcp", "your@email.com"]
    }
  }
}
```

#### Running Standalone

```bash
# Using the console script
pubmed-search-mcp your@email.com

# Or using Python
python -m pubmed_search.mcp your@email.com
```

### As a Remote MCP Server (HTTP/SSE)

For serving multiple machines, run the server in HTTP mode:

```bash
# Quick start
./start.sh

# Or with custom options
python run_server.py --transport sse --port 8765 --email your@email.com

# Using Docker
docker compose up -d
```

#### Remote Client Configuration

On other machines, configure `.vscode/mcp.json`:

```json
{
  "servers": {
    "pubmed-search": {
      "type": "sse",
      "url": "http://YOUR_SERVER_IP:8765/sse"
    }
  }
}
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed deployment instructions including:
- systemd service setup
- Docker deployment
- Nginx reverse proxy
- Security considerations

## MCP Tools

| Tool | Description |
|------|-------------|
| `search_literature` | Search PubMed for medical literature |
| `find_related_articles` | Find articles related to a given PMID |
| `find_citing_articles` | Find articles that cite a given PMID |
| `fetch_article_details` | Get full details for specific PMIDs |
| `generate_search_queries` | Generate multiple queries for parallel search |
| `merge_search_results` | Merge and deduplicate results |
| `expand_search_queries` | Expand search with synonyms/related terms |

## API Documentation

### PubMedClient

The main client class for interacting with PubMed.

```python
from pubmed_search import PubMedClient

client = PubMedClient(
    email="your@email.com",  # Required by NCBI
    api_key=None,            # Optional: NCBI API key for higher rate limits
    tool="pubmed-search"     # Tool name for NCBI tracking
)
```

### Low-level Entrez API

For more control, use the low-level Entrez interface:

```python
from pubmed_search.entrez import LiteratureSearcher

searcher = LiteratureSearcher(email="your@email.com")

# Advanced search with filters
results = searcher.search_advanced(
    term="propofol sedation",
    filter_humans=True,
    filter_english=True,
    date_range=("2020", "2024"),
    max_results=50
)
```

## License

MIT License - see [LICENSE](LICENSE)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `pytest`
5. Submit a pull request

## Links

- [GitHub Repository](https://github.com/u9401066/pubmed-search-mcp)
- [PyPI Package](https://pypi.org/project/pubmed-search/)
- [NCBI Entrez Programming Utilities](https://www.ncbi.nlm.nih.gov/books/NBK25497/)
