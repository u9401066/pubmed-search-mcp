# PubMed Search MCP

[![PyPI version](https://badge.fury.io/py/pubmed-search-mcp.svg)](https://badge.fury.io/py/pubmed-search-mcp)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)
[![Smithery](https://smithery.ai/badge/pubmed-search-mcp)](https://smithery.ai/server/pubmed-search-mcp)

> **AI Agent 的專業文獻研究助理** - 不只是 API 包裝器

A Domain-Driven Design (DDD) based MCP server that serves as an intelligent research assistant for AI agents, providing task-oriented literature search and analysis capabilities.

## 🚀 Quick Install

### Via Smithery (Recommended for Claude Desktop)

```bash
npx -y @smithery/cli install pubmed-search-mcp --client claude
```

### Via pip

```bash
pip install pubmed-search-mcp
```

### Via uv

```bash
uv add pubmed-search-mcp
```

### Via uvx (Zero Install)

```bash
uvx pubmed-search-mcp
```

## ⚙️ Configuration

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "pubmed-search": {
      "command": "uvx",
      "args": ["pubmed-search-mcp"],
      "env": {
        "NCBI_EMAIL": "your@email.com"
      }
    }
  }
}
```

### VS Code / Cursor (`.vscode/mcp.json`)

```json
{
  "servers": {
    "pubmed-search": {
      "type": "stdio",
      "command": "uvx",
      "args": ["pubmed-search-mcp"],
      "env": {
        "NCBI_EMAIL": "your@email.com"
      }
    }
  }
}
```

> **Note**: `NCBI_EMAIL` is required by NCBI API policy. Optionally set `NCBI_API_KEY` for higher rate limits.

---

## 🎯 設計理念

- **Agent-First** - 為 AI Agent 設計，輸出優化為機器決策
- **任務導向** - Tool 以研究任務為單位，而非底層 API
- **DDD 架構** - 以文獻研究領域知識為核心建模
- **上下文感知** - 透過 Session 維持研究狀態

**定位**：PubMed 專精的 AI 研究助理
- ✅ MeSH 專業詞彙整合 ← 其他來源沒有
- ✅ PICO 結構化查詢 ← 醫學專業
- ✅ ESpell 拼字校正 ← 自動糾錯
- ✅ 批次並行搜尋 ← 高效率

## Features

- **Search PubMed**: Full-text and advanced query support
- **Related Articles**: Find papers related to a given PMID
- **Citing Articles**: Find papers that cite a given PMID
- **Parallel Search**: Generate multiple queries for comprehensive searches
- **PDF Access**: Get open-access PDF URLs from PubMed Central
- **Export Formats**: RIS, BibTeX, CSV, MEDLINE, JSON (EndNote/Zotero/Mendeley compatible)
- **MCP Integration**: Use with VS Code + GitHub Copilot or any MCP client
- **Remote Server**: Deploy as HTTP service for multi-machine access
- **Submodule Ready**: Use as a Git submodule in larger projects

## 🛠️ MCP Tools (11 個工具)

### 探索型 (Discovery)
| Tool | 說明 |
|------|------|
| `search_literature` | 搜尋 PubMed 文獻 |
| `find_related_articles` | 尋找相關文章 (by PMID) |
| `find_citing_articles` | 尋找引用文章 (by PMID) |
| `fetch_article_details` | 取得文章完整資訊 |

### 批次搜尋 (Parallel Search)
| Tool | 說明 |
|------|------|
| `parse_pico` | 🆕 解析 PICO 臨床問題 (搜尋入口) |
| `generate_search_queries` | 產生多個搜尋策略 (ESpell + MeSH) |
| `merge_search_results` | 合併去重搜尋結果 |
| `expand_search_queries` | 擴展搜尋策略 |

### 匯出工具 (Export)
| Tool | 說明 |
|------|------|
| `prepare_export` | 匯出引用格式 (RIS/BibTeX/CSV/MEDLINE/JSON) |
| `get_article_fulltext_links` | 取得全文連結 (PMC/DOI) |
| `analyze_fulltext_access` | 分析開放取用可用性 |

> **設計原則**: 專注搜尋。Session/Cache/Reading List 皆為**內部機制**，自動運作，Agent 無需管理。

---

## 📋 Agent 使用流程

### 快速搜尋 (Simple Search)
```
search_literature(query="remimazolam ICU sedation", limit=10)
```

### 使用 PubMed 官方語法
```
# MeSH 標準詞彙
search_literature(query='"Diabetes Mellitus"[MeSH]')

# 欄位限定
search_literature(query='(BRAF[Gene Name]) AND (melanoma[Title/Abstract])')

# 日期範圍
search_literature(query='COVID-19[Title] AND 2024[dp]')

# 文章類型
search_literature(query='propofol sedation AND Review[pt]')

# 組合搜尋
search_literature(query='("Intensive Care Units"[MeSH]) AND (remimazolam[tiab] OR "CNS 7056"[tiab])')
```

### PubMed 官方欄位標籤 (Field Tags)

| 標籤 | 說明 | 範例 |
|------|------|------|
| `[Title]` 或 `[ti]` | 標題 | `COVID-19[ti]` |
| `[Title/Abstract]` 或 `[tiab]` | 標題+摘要 | `sedation[tiab]` |
| `[MeSH]` 或 `[mh]` | MeSH 標準詞彙 | `"Diabetes Mellitus"[MeSH]` |
| `[MeSH Major Topic]` 或 `[majr]` | MeSH 主要主題 | `"Anesthesia"[majr]` |
| `[Author]` 或 `[au]` | 作者 | `Smith J[au]` |
| `[Journal]` 或 `[ta]` | 期刊縮寫 | `Nature[ta]` |
| `[Publication Type]` 或 `[pt]` | 文章類型 | `Review[pt]`, `Clinical Trial[pt]` |
| `[Date - Publication]` 或 `[dp]` | 出版日期 | `2024[dp]`, `2020:2024[dp]` |
| `[Gene Name]` | 基因名稱 | `BRAF[Gene Name]` |
| `[Substance Name]` | 物質名稱 | `propofol[Substance Name]` |

> **完整語法參考**: [PubMed Search Field Tags](https://pubmed.ncbi.nlm.nih.gov/help/#search-tags)

### 深入探索 (找到重要論文後)
```
find_related_articles(pmid="12345678")   # 相關文章
find_citing_articles(pmid="12345678")    # 引用這篇的後續研究
```

---

## 🔍 深度搜尋：兩種入口模式

本工具提供兩種深度搜尋入口，最終都透過 **並行搜尋 + 合併去重** 完成：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         深度搜尋流程圖                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌───────────────────┐         ┌───────────────────┐                   │
│   │  關鍵字導向入口     │         │  PICO 臨床問題入口  │                   │
│   │  (知道要搜什麼)     │         │  (有臨床問題描述)   │                   │
│   └─────────┬─────────┘         └─────────┬─────────┘                   │
│             │                             │                              │
│             │                             ▼                              │
│             │                   ┌───────────────────┐                   │
│             │                   │   parse_pico()    │                   │
│             │                   │   解析 P/I/C/O    │                   │
│             │                   └─────────┬─────────┘                   │
│             │                             │                              │
│             ▼                             ▼                              │
│   ┌─────────────────────────────────────────────────────────────┐       │
│   │              generate_search_queries()                       │       │
│   │              (ESpell 校正 + MeSH 擴展 + 同義詞)                │       │
│   │                                                              │       │
│   │   關鍵字模式: 呼叫 1 次                                        │       │
│   │   PICO 模式:  對每個元素 (P/I/C/O) 各呼叫 1 次 (並行)          │       │
│   └──────────────────────────┬──────────────────────────────────┘       │
│                              │                                           │
│                              ▼                                           │
│   ┌─────────────────────────────────────────────────────────────┐       │
│   │              Agent 組合查詢策略                               │       │
│   │                                                              │       │
│   │   • 使用返回的 suggested_queries                              │       │
│   │   • 或用 mesh_terms + all_synonyms 自行組合                   │       │
│   │   • PICO 模式: 用 Boolean 邏輯組合 (P) AND (I) AND (O)        │       │
│   └──────────────────────────┬──────────────────────────────────┘       │
│                              │                                           │
│                              ▼                                           │
│   ┌─────────────────────────────────────────────────────────────┐       │
│   │              search_literature() × N (並行執行)               │       │
│   └──────────────────────────┬──────────────────────────────────┘       │
│                              │                                           │
│                              ▼                                           │
│   ┌─────────────────────────────────────────────────────────────┐       │
│   │              merge_search_results()                          │       │
│   │              合併去重 + 標記高相關性文章                        │       │
│   └─────────────────────────────────────────────────────────────┘       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 入口 1️⃣：關鍵字導向 (Keyword Search)

**適用場景**: 已知要搜尋的關鍵字或主題

```python
# Step 1: 取得搜尋素材 (ESpell + MeSH + 同義詞)
generate_search_queries(topic="remimazolam ICU sedation")

# 返回內容:
{
  "corrected_topic": "remimazolam icu sedation",   # 拼字校正
  "mesh_terms": [
    {"input": "remimazolam", "preferred": "remimazolam [Supplementary Concept]", 
     "synonyms": ["CNS 7056", "ONO 2745"]},
    {"input": "sedation", "preferred": "Deep Sedation", 
     "synonyms": ["Sedation, Deep"]}
  ],
  "all_synonyms": ["CNS 7056", "ONO 2745", "Sedation, Deep", ...],
  "suggested_queries": [
    {"id": "q1_title", "query": "(remimazolam icu sedation)[Title]"},
    {"id": "q2_tiab", "query": "(remimazolam icu sedation)[Title/Abstract]"},
    {"id": "q4_mesh", "query": "\"remimazolam [Supplementary Concept]\"[MeSH Terms]"},
    {"id": "q6_syn", "query": "(CNS 7056)[Title/Abstract]"},
    ...
  ]
}

# Step 2: 並行執行搜尋
search_literature(query="(remimazolam icu sedation)[Title]")          # 並行
search_literature(query="(remimazolam icu sedation)[Title/Abstract]") # 並行
search_literature(query="\"Deep Sedation\"[MeSH Terms]")              # 並行
...

# Step 3: 合併結果
merge_search_results(results_json='[["pmid1","pmid2"],["pmid2","pmid3"]]')
# → unique_pmids: 去重後的 PMID 列表
# → high_relevance_pmids: 多策略命中的高相關文章
```

### 入口 2️⃣：PICO 臨床問題 (Clinical Question)

**適用場景**: 有臨床問題需要拆解成結構化搜尋

```python
# Step 1: 解析 PICO 結構
parse_pico(description="remimazolam 在 ICU 鎮靜比 propofol 好嗎？會減少 delirium 嗎？")

# 返回內容:
{
  "pico": {
    "P": "ICU patients requiring sedation",
    "I": "remimazolam",
    "C": "propofol", 
    "O": "delirium incidence"
  },
  "question_type": "therapy",  # 建議的 Clinical Query filter
  "next_steps": "對每個 PICO 元素呼叫 generate_search_queries()"
}

# Step 2: 對每個 PICO 元素取得搜尋素材 (並行!)
generate_search_queries(topic="ICU patients")  # P → MeSH: "Intensive Care Units"
generate_search_queries(topic="remimazolam")   # I → MeSH: "remimazolam [Supplementary Concept]"
generate_search_queries(topic="propofol")      # C → MeSH: "Propofol"
generate_search_queries(topic="delirium")      # O → MeSH: "Delirium"

# Step 3: Agent 組合查詢 (使用 Boolean 邏輯)
# 高精確度: (P) AND (I) AND (C) AND (O)
query_precise = '("Intensive Care Units"[MeSH] OR ICU[tiab]) AND ' \
                '(remimazolam[tiab] OR "CNS 7056"[tiab]) AND ' \
                '(propofol[tiab] OR Diprivan[tiab]) AND ' \
                '(delirium[tiab] OR "Emergence Delirium"[MeSH])'

# 高召回率: (P) AND (I OR C) AND (O)
query_recall = '(ICU[tiab]) AND (remimazolam[tiab] OR propofol[tiab]) AND (delirium[tiab])'

# Step 4: 並行搜尋 + 合併
search_literature(query=query_precise)  # 並行
search_literature(query=query_recall)   # 並行
merge_search_results(...)
```

### 兩種入口對比

| 特性 | 關鍵字導向 | PICO 臨床問題 |
|------|-----------|---------------|
| **入口工具** | `generate_search_queries(topic)` | `parse_pico(description)` |
| **適用場景** | 知道要搜什麼詞 | 有臨床問題需要拆解 |
| **MeSH 擴展** | 1 次呼叫 | 4 次呼叫 (P/I/C/O 各一次) |
| **查詢組合** | 使用 suggested_queries | Agent 用 Boolean 組合 |
| **範例輸入** | "remimazolam ICU sedation" | "remimazolam 在 ICU 比 propofol 好嗎？" |

> **設計哲學**: 工具提供素材 (MeSH terms, synonyms)，Agent 做決策 (如何組合查詢)

---

## 🏗️ Architecture (DDD)

```
src/pubmed_search/
├── mcp/
│   └── tools/
│       ├── discovery.py    # 探索型 (search, related, citing, details)
│       ├── strategy.py     # 策略型 (generate_queries, expand)
│       ├── pico.py         # PICO 解析
│       ├── merge.py        # 結果合併
│       └── export.py       # 匯出工具
├── entrez/                 # NCBI Entrez API 封裝
├── exports/                # 匯出格式 (RIS, BibTeX, CSV)
└── session.py              # Session 管理 (內部機制)
```

### 內部機制 (對 Agent 透明)

| 機制 | 說明 |
|------|------|
| **Session** | 自動建立、自動切換 |
| **Cache** | 搜尋結果自動快取，避免重複 API |
| **Rate Limit** | 自動遵守 NCBI API 限制 (0.34s/0.1s) |
| **MeSH Lookup** | `generate_search_queries()` 自動查詢 NCBI MeSH 資料庫 |
| **ESpell** | 自動拼字校正 (`remifentanyl` → `remifentanil`) |
| **Query Analysis** | 🆕 每個 suggested query 顯示 PubMed 實際解讀方式 |

### MeSH 自動擴展 + Query Analysis

當呼叫 `generate_search_queries("remimazolam sedation")` 時，內部自動：

1. **ESpell 校正** - 修正拼字錯誤
2. **MeSH 查詢** - `Entrez.esearch(db="mesh")` 取得標準詞彙
3. **同義詞提取** - 從 MeSH Entry Terms 取得同義詞
4. **🆕 Query Analysis** - 分析 PubMed 如何解讀每個 query

```json
{
  "mesh_terms": [
    {
      "input": "remimazolam",
      "preferred": "remimazolam [Supplementary Concept]",
      "synonyms": ["CNS 7056", "ONO 2745"]
    }
  ],
  "all_synonyms": ["CNS 7056", "ONO 2745", ...],
  "suggested_queries": [
    {
      "id": "q1_title",
      "query": "(remimazolam sedation)[Title]",
      "purpose": "Exact title match - highest precision",
      "estimated_count": 8,
      "pubmed_translation": "\"remimazolam sedation\"[Title]"
    },
    {
      "id": "q3_and",
      "query": "(remimazolam AND sedation)",
      "purpose": "All keywords required",
      "estimated_count": 561,
      "pubmed_translation": "(\"remimazolam\"[Supplementary Concept] OR \"remimazolam\"[All Fields]) AND (\"sedate\"[All Fields] OR ...)"
    }
  ]
}
```

> **Query Analysis 的價值**: Agent 以為 `remimazolam AND sedation` 只搜這兩個詞，但 PubMed 實際會展開成 Supplementary Concept + 同義詞，結果從 8 篇變成 561 篇。這讓 Agent 理解 **意圖** 與 **實際搜尋** 的差異。
```

---

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
| `prepare_export` | Export citations in RIS/BibTeX/CSV/MEDLINE/JSON |
| `get_article_fulltext_links` | Get PMC/DOI full-text links |
| `analyze_fulltext_access` | Analyze open access availability |

## 📤 Export Formats

Export your search results in formats compatible with major reference managers:

| Format | Compatible With | Use Case |
|--------|-----------------|----------|
| **RIS** | EndNote, Zotero, Mendeley | Universal import |
| **BibTeX** | LaTeX, Overleaf, JabRef | Academic writing |
| **CSV** | Excel, Google Sheets | Data analysis |
| **MEDLINE** | PubMed native format | Archiving |
| **JSON** | Programmatic access | Custom processing |

### Exported Fields
- **Core**: PMID, Title, Authors, Journal, Year, Volume, Issue, Pages
- **Identifiers**: DOI, PMC ID, ISSN
- **Content**: Abstract (HTML tags cleaned)
- **Metadata**: Language, Publication Type, Keywords
- **Access**: DOI URL, PMC URL, Full-text availability

### Special Character Handling
- BibTeX exports use **pylatexenc** for proper LaTeX encoding
- Nordic characters (ø, æ, å), umlauts (ü, ö, ä), and accents are correctly converted
- Example: `Søren Hansen` → `S{\o}ren Hansen`

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
