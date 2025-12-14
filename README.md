# PubMed Search MCP

[![PyPI version](https://badge.fury.io/py/pubmed-search-mcp.svg)](https://badge.fury.io/py/pubmed-search-mcp)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)
[![Smithery](https://smithery.ai/badge/pubmed-search-mcp)](https://smithery.ai/server/pubmed-search-mcp)
[![Test Coverage](https://img.shields.io/badge/coverage-90%25-brightgreen.svg)](https://github.com/u9401066/pubmed-search-mcp)

> **Professional Literature Research Assistant for AI Agents** - More than just an API wrapper

A Domain-Driven Design (DDD) based MCP server that serves as an intelligent research assistant for AI agents, providing task-oriented literature search and analysis capabilities.

**🌐 Language**: **English** | [繁體中文](README.zh-TW.md)

---

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

---

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

## 🎯 Design Philosophy

- **Agent-First** - Designed for AI Agents, output optimized for machine decision-making
- **Task-Oriented** - Tools organized by research tasks, not low-level APIs
- **DDD Architecture** - Core modeling based on literature research domain knowledge
- **Context-Aware** - Maintains research state through Session

**Positioning**: PubMed-specialized AI research assistant
- ✅ MeSH vocabulary integration - Not available from other sources
- ✅ PICO structured queries - Medical specialty
- ✅ ESpell spelling correction - Auto-correction
- ✅ Batch parallel search - High efficiency

---

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

---

## 🛠️ MCP Tools (14 Tools)

### Discovery Tools

| Tool | Description | Direction |
|------|-------------|-----------|
| `search_literature` | Search PubMed literature | - |
| `find_related_articles` | Find similar articles (PubMed algorithm) | Similarity |
| `find_citing_articles` | Find papers citing this article (follow-up research) | Forward ➡️ |
| `get_article_references` | Get this article's references (research foundation) | Backward ⬅️ |
| `fetch_article_details` | Get full article information | - |
| `get_citation_metrics` | Get citation metrics (iCite RCR/Percentile) | - |
| `build_citation_tree` | Build citation network tree (6 formats) | Both ↔️ |
| `suggest_citation_tree` | Evaluate if building citation tree is worthwhile | - |

### Parallel Search Tools

| Tool | Description |
|------|-------------|
| `parse_pico` | Parse PICO clinical questions (search entry point) |
| `generate_search_queries` | Generate multiple search strategies (ESpell + MeSH) |
| `merge_search_results` | Merge and deduplicate search results |
| `expand_search_queries` | Expand search strategies |

### Export Tools

| Tool | Description |
|------|-------------|
| `prepare_export` | Export citation formats (RIS/BibTeX/CSV/MEDLINE/JSON) |
| `get_article_fulltext_links` | Get full-text links (PMC/DOI) |
| `analyze_fulltext_access` | Analyze open access availability |

> **Design Principle**: Focus on search. Session/Cache/Reading List are all **internal mechanisms** that operate automatically - Agents don't need to manage them.

---

## 📋 Agent Usage Workflow

### Simple Search

```python
search_literature(query="remimazolam ICU sedation", limit=10)
```

### Using PubMed Official Syntax

```python
# MeSH standard vocabulary
search_literature(query='"Diabetes Mellitus"[MeSH]')

# Field-specific search
search_literature(query='(BRAF[Gene Name]) AND (melanoma[Title/Abstract])')

# Date range
search_literature(query='COVID-19[Title] AND 2024[dp]')

# Publication type
search_literature(query='propofol sedation AND Review[pt]')

# Combined search
search_literature(query='("Intensive Care Units"[MeSH]) AND (remimazolam[tiab] OR "CNS 7056"[tiab])')
```

### PubMed Official Field Tags

| Tag | Description | Example |
|-----|-------------|---------|
| `[Title]` or `[ti]` | Title | `COVID-19[ti]` |
| `[Title/Abstract]` or `[tiab]` | Title + Abstract | `sedation[tiab]` |
| `[MeSH]` or `[mh]` | MeSH standard vocabulary | `"Diabetes Mellitus"[MeSH]` |
| `[MeSH Major Topic]` or `[majr]` | MeSH major topic | `"Anesthesia"[majr]` |
| `[Author]` or `[au]` | Author | `Smith J[au]` |
| `[Journal]` or `[ta]` | Journal abbreviation | `Nature[ta]` |
| `[Publication Type]` or `[pt]` | Publication type | `Review[pt]`, `Clinical Trial[pt]` |
| `[Date - Publication]` or `[dp]` | Publication date | `2024[dp]`, `2020:2024[dp]` |
| `[Gene Name]` | Gene name | `BRAF[Gene Name]` |
| `[Substance Name]` | Substance name | `propofol[Substance Name]` |

> **Full syntax reference**: [PubMed Search Field Tags](https://pubmed.ncbi.nlm.nih.gov/help/#search-tags)

### Deep Exploration (After finding important papers)

```python
find_related_articles(pmid="12345678")   # Related articles (PubMed algorithm)
find_citing_articles(pmid="12345678")    # Papers citing this one (forward in time)
get_article_references(pmid="12345678")  # This paper's references (backward in time)
```

---

## 🔬 Citation Discovery Guide

After finding an important paper, there are **5 tools** to explore related literature. Choosing the right tool can greatly improve research efficiency:

### Tool Comparison

| Tool | Direction | Data Source | Use Case | API Calls |
|------|-----------|-------------|----------|-----------|
| `find_related_articles` | Similarity | PubMed algorithm | Find topic/method similar articles | 1 |
| `find_citing_articles` | Forward ➡️ | PMC citations | Find follow-up research | 1 |
| `get_article_references` | Backward ⬅️ | PMC references | Find foundational papers | 1 |
| `build_citation_tree` | Both ↔️ | PMC (BFS traversal) | Build complete citation network | Multiple |
| `suggest_citation_tree` | - | Article info | Evaluate if tree building is worthwhile | 1 |

### Usage Decision Tree

```
Found an important paper (PMID: 12345678)
    │
    ├── Want to find "similar topic" articles?
    │   └── ✅ find_related_articles(pmid="12345678")
    │       → PubMed algorithm finds similar articles by MeSH, keywords, citation patterns
    │
    ├── Want to know "how subsequent research developed"?
    │   └── ✅ find_citing_articles(pmid="12345678")
    │       → Find all papers citing this one (timeline: forward → now)
    │
    ├── Want to understand "what this article is based on"?
    │   └── ✅ get_article_references(pmid="12345678")
    │       → Get this article's reference list (timeline: backward ← past)
    │
    └── Want to build "complete research context network"?
        │
        ├── First evaluate: suggest_citation_tree(pmid="12345678")
        │   → Check citation count to decide if tree building is worthwhile
        │
        └── Build network: build_citation_tree(pmid="12345678", depth=2)
            → Output Mermaid/Cytoscape/GraphML formats
```

### Practical Examples

#### Scenario 1: Quick related paper search
```python
# Found an important RCT on remimazolam, want to see similar studies
find_related_articles(pmid="33475315", limit=10)
```

#### Scenario 2: Track research impact
```python
# What subsequent research did this 2020 paper influence?
find_citing_articles(pmid="33475315", limit=20)
```

#### Scenario 3: Understand research foundation
```python
# What key literature did this article cite? Find foundation papers
get_article_references(pmid="33475315", limit=30)
```

#### Scenario 4: Build research context map (Literature Review)
```python
# Step 1: Evaluate if tree building is worthwhile
suggest_citation_tree(pmid="33475315")

# Step 2: Build 2-level citation network, output Mermaid format (previewable in VS Code)
build_citation_tree(
    pmid="33475315",
    depth=2,
    direction="both",
    output_format="mermaid"
)
```

### Citation Tree Output Formats

| Format | Use Case | Tool |
|--------|----------|------|
| `mermaid` | VS Code Markdown preview | Built-in Mermaid extension |
| `cytoscape` | Academic standard, bioinformatics | Cytoscape.js |
| `g6` | Modern web visualization | AntV G6 |
| `d3` | Flexible customization | D3.js force layout |
| `vis` | Rapid prototyping | vis-network |
| `graphml` | Desktop analysis software | Gephi, VOSviewer, yEd |

---

## 🔍 Deep Search: Two Entry Modes

This tool provides two deep search entry points, both completed through **parallel search + merge deduplication**:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Deep Search Flowchart                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   ┌───────────────────┐         ┌───────────────────┐                   │
│   │  Keyword Entry    │         │  PICO Clinical    │                   │
│   │  (Know what to    │         │  Question Entry   │                   │
│   │   search)         │         │  (Have clinical   │                   │
│   └─────────┬─────────┘         │   description)    │                   │
│             │                   └─────────┬─────────┘                   │
│             │                             │                              │
│             │                             ▼                              │
│             │                   ┌───────────────────┐                   │
│             │                   │   parse_pico()    │                   │
│             │                   │   Parse P/I/C/O   │                   │
│             │                   └─────────┬─────────┘                   │
│             │                             │                              │
│             ▼                             ▼                              │
│   ┌─────────────────────────────────────────────────────────────┐       │
│   │              generate_search_queries()                       │       │
│   │              (ESpell correction + MeSH expansion + synonyms) │       │
│   │                                                              │       │
│   │   Keyword mode: 1 call                                       │       │
│   │   PICO mode: 1 call per element (P/I/C/O) in parallel        │       │
│   └──────────────────────────┬──────────────────────────────────┘       │
│                              │                                           │
│                              ▼                                           │
│   ┌─────────────────────────────────────────────────────────────┐       │
│   │              Agent combines query strategies                 │       │
│   │                                                              │       │
│   │   • Use returned suggested_queries                           │       │
│   │   • Or combine mesh_terms + all_synonyms yourself            │       │
│   │   • PICO mode: Use Boolean logic (P) AND (I) AND (O)         │       │
│   └──────────────────────────┬──────────────────────────────────┘       │
│                              │                                           │
│                              ▼                                           │
│   ┌─────────────────────────────────────────────────────────────┐       │
│   │              search_literature() × N (parallel execution)    │       │
│   └──────────────────────────┬──────────────────────────────────┘       │
│                              │                                           │
│                              ▼                                           │
│   ┌─────────────────────────────────────────────────────────────┐       │
│   │              merge_search_results()                          │       │
│   │              Merge + dedupe + mark high-relevance articles   │       │
│   └─────────────────────────────────────────────────────────────┘       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Entry 1️⃣: Keyword-Oriented

**Use Case**: Already know the keywords or topic to search

```python
# Step 1: Get search materials (ESpell + MeSH + synonyms)
generate_search_queries(topic="remimazolam ICU sedation")

# Returns:
{
  "corrected_topic": "remimazolam icu sedation",   # Spelling corrected
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

# Step 2: Execute searches in parallel
search_literature(query="(remimazolam icu sedation)[Title]")          # parallel
search_literature(query="(remimazolam icu sedation)[Title/Abstract]") # parallel
search_literature(query="\"Deep Sedation\"[MeSH Terms]")              # parallel
...

# Step 3: Merge results
merge_search_results(results_json='[["pmid1","pmid2"],["pmid2","pmid3"]]')
# → unique_pmids: Deduplicated PMID list
# → high_relevance_pmids: High-relevance articles hit by multiple strategies
```

### Entry 2️⃣: PICO Clinical Question

**Use Case**: Have a clinical question that needs to be decomposed into structured search

```python
# Step 1: Parse PICO structure
parse_pico(description="Is remimazolam better than propofol for ICU sedation? Does it reduce delirium?")

# Returns:
{
  "pico": {
    "P": "ICU patients requiring sedation",
    "I": "remimazolam",
    "C": "propofol", 
    "O": "delirium incidence"
  },
  "question_type": "therapy",  # Suggested Clinical Query filter
  "next_steps": "Call generate_search_queries() for each PICO element"
}

# Step 2: Get search materials for each PICO element (in parallel!)
generate_search_queries(topic="ICU patients")  # P → MeSH: "Intensive Care Units"
generate_search_queries(topic="remimazolam")   # I → MeSH: "remimazolam [Supplementary Concept]"
generate_search_queries(topic="propofol")      # C → MeSH: "Propofol"
generate_search_queries(topic="delirium")      # O → MeSH: "Delirium"

# Step 3: Agent combines queries (using Boolean logic)
# High precision: (P) AND (I) AND (C) AND (O)
query_precise = '("Intensive Care Units"[MeSH] OR ICU[tiab]) AND ' \
                '(remimazolam[tiab] OR "CNS 7056"[tiab]) AND ' \
                '(propofol[tiab] OR Diprivan[tiab]) AND ' \
                '(delirium[tiab] OR "Emergence Delirium"[MeSH])'

# High recall: (P) AND (I OR C) AND (O)
query_recall = '(ICU[tiab]) AND (remimazolam[tiab] OR propofol[tiab]) AND (delirium[tiab])'

# Step 4: Parallel search + merge
search_literature(query=query_precise)  # parallel
search_literature(query=query_recall)   # parallel
merge_search_results(...)
```

### Two Entry Points Comparison

| Feature | Keyword-Oriented | PICO Clinical Question |
|---------|------------------|------------------------|
| **Entry Tool** | `generate_search_queries(topic)` | `parse_pico(description)` |
| **Use Case** | Know what keywords to search | Have clinical question to decompose |
| **MeSH Expansion** | 1 call | 4 calls (one for P/I/C/O each) |
| **Query Combination** | Use suggested_queries | Agent combines with Boolean |
| **Example Input** | "remimazolam ICU sedation" | "Is remimazolam better than propofol in ICU?" |

> **Design Philosophy**: Tools provide materials (MeSH terms, synonyms), Agent makes decisions (how to combine queries)

---

## 🏗️ Architecture (DDD)

This project uses **Domain-Driven Design (DDD)** architecture, with literature research domain knowledge as the core model.

```
src/pubmed_search/
├── mcp/
│   └── tools/
│       ├── discovery.py    # Discovery (search, related, citing, details)
│       ├── strategy.py     # Strategy (generate_queries, expand)
│       ├── pico.py         # PICO parsing
│       ├── merge.py        # Result merging
│       ├── export.py       # Export tools
│       └── citation_tree.py # Citation network visualization (6 formats)
├── entrez/                 # NCBI Entrez API wrapper
├── exports/                # Export formats (RIS, BibTeX, CSV)
└── session.py              # Session management (internal mechanism)
```

### Internal Mechanisms (Transparent to Agent)

| Mechanism | Description |
|-----------|-------------|
| **Session** | Auto-create, auto-switch |
| **Cache** | Auto-cache search results, avoid duplicate API calls |
| **Rate Limit** | Auto-comply with NCBI API limits (0.34s/0.1s) |
| **MeSH Lookup** | `generate_search_queries()` auto-queries NCBI MeSH database |
| **ESpell** | Auto spelling correction (`remifentanyl` → `remifentanil`) |
| **Query Analysis** | Each suggested query shows how PubMed actually interprets it |

> 📖 **Full architecture documentation**: [ARCHITECTURE.md](ARCHITECTURE.md)

### MeSH Auto-Expansion + Query Analysis

When calling `generate_search_queries("remimazolam sedation")`, internally it:

1. **ESpell Correction** - Fix spelling errors
2. **MeSH Query** - `Entrez.esearch(db="mesh")` to get standard vocabulary
3. **Synonym Extraction** - Get synonyms from MeSH Entry Terms
4. **Query Analysis** - Analyze how PubMed interprets each query

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

> **Value of Query Analysis**: Agent thinks `remimazolam AND sedation` only searches these two words, but PubMed actually expands to Supplementary Concept + synonyms, results go from 8 to 561. This helps Agent understand the difference between **intent** and **actual search**.

---

## 🔒 HTTPS Deployment

Enable HTTPS secure communication for production environments.

### Quick Start

```bash
# Step 1: Generate SSL certificates
./scripts/generate-ssl-certs.sh

# Step 2: Start HTTPS service (Docker)
./scripts/start-https-docker.sh up

# Verify deployment
curl -k https://localhost/
```

### HTTPS Endpoints

| Service | URL | Description |
|---------|-----|-------------|
| MCP SSE | `https://localhost/sse` | SSE connection (MCP) |
| Messages | `https://localhost/messages` | MCP POST |
| Health | `https://localhost/health` | Health check |

### Claude Desktop Configuration

```json
{
  "mcpServers": {
    "pubmed-search": {
      "url": "https://localhost/sse"
    }
  }
}
```

> 📖 **Full documentation**:
> - Architecture → [ARCHITECTURE.md](ARCHITECTURE.md)
> - Deployment guide → [DEPLOYMENT.md](DEPLOYMENT.md)

---

## 🔐 Security

### Security Features

| Layer | Feature | Description |
|-------|---------|-------------|
| **HTTPS** | TLS 1.2/1.3 encryption | All traffic encrypted via Nginx |
| **Rate Limiting** | 30 req/s | Nginx level protection |
| **Security Headers** | XSS/CSRF protection | X-Frame-Options, X-Content-Type-Options |
| **SSE Optimization** | 24h timeout | Long-lived connections for real-time |
| **No Database** | Stateless | No SQL injection risk |
| **No Secrets** | In-memory only | No credentials stored |

---

## 📦 Installation

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

---

## 📚 Usage

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

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed deployment instructions.

---

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

---

## 📖 API Documentation

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

---

## 📄 License

Apache License 2.0 - see [LICENSE](LICENSE)

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `pytest`
5. Submit a pull request

## 🔗 Links

- [GitHub Repository](https://github.com/u9401066/pubmed-search-mcp)
- [PyPI Package](https://pypi.org/project/pubmed-search/)
- [NCBI Entrez Programming Utilities](https://www.ncbi.nlm.nih.gov/books/NBK25497/)
