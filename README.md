# PubMed Search MCP

> **AI Agent 的專業文獻研究助理** - 不只是 API 包裝器

A Domain-Driven Design (DDD) based MCP server that serves as an intelligent research assistant for AI agents, providing task-oriented literature search and analysis capabilities.

## 🎯 設計理念

- **Agent-First** - 為 AI Agent 設計，輸出優化為機器決策
- **任務導向** - Tool 以研究任務為單位，而非底層 API
- **DDD 架構** - 以文獻研究領域知識為核心建模
- **上下文感知** - 透過 Resources 維持研究狀態

## Features

- **Search PubMed**: Full-text and advanced query support
- **Related Articles**: Find papers related to a given PMID
- **Citing Articles**: Find papers that cite a given PMID
- **Parallel Search**: Generate multiple queries for comprehensive searches
- **PDF Access**: Get open-access PDF URLs from PubMed Central
- **MCP Integration**: Use with VS Code + GitHub Copilot or any MCP client
- **Remote Server**: Deploy as HTTP service for multi-machine access
- **Submodule Ready**: Use as a Git submodule in larger projects

## 🛠️ MCP Tools

### 探索型 (Discovery)
| Tool | 說明 |
|------|------|
| `search_literature` | 搜尋 PubMed 文獻 (自動快取) |
| `find_related_articles` | 尋找相關文章 |
| `find_citing_articles` | 尋找引用文章 |
| `generate_search_queries` | 生成多重搜尋策略 |

### 分析型 (Analysis)
| Tool | 說明 |
|------|------|
| `fetch_article_details` | 取得文章完整資訊 |
| `merge_search_results` | 合併去重搜尋結果 |
| `expand_search_queries` | 擴展搜尋策略 |

### Session 管理 (Context Management)
| Tool | 說明 |
|------|------|
| `get_session_status` | 取得當前研究 session 狀態 |
| `start_research_session` | 開始新的研究主題 |
| `list_sessions` | 列出所有研究 sessions |
| `switch_session` | 切換到不同的 session |
| `get_cached_article` | 從快取取得文章 (無需 API) |
| `check_cached_pmids` | 檢查哪些 PMID 已快取 |
| `add_to_reading_list` | 加入閱讀清單 (含優先順序) |
| `get_reading_list` | 取得閱讀清單 |
| `exclude_article` | 標記文章為不相關 |
| `get_search_history` | 取得搜尋歷史 |

### MCP Resources
| Resource URI | 說明 |
|--------------|------|
| `session://current` | 當前 session 摘要 |
| `session://reading-list` | 閱讀清單 |
| `session://cache-stats` | 快取統計 |

詳細 API 文件請參考 [ROADMAP.md](ROADMAP.md)。

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

### As a Git Submodule

```bash
# Add as submodule to your project
git submodule add https://github.com/u9401066/pubmed-search-mcp.git src/pubmed_search

# Install dependencies
pip install biopython requests mcp
```

Then import in your code:
```python
from src.pubmed_search import PubMedClient
# or add src to your Python path
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
