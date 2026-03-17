# PubMed Search MCP

[![PyPI version](https://badge.fury.io/py/pubmed-search-mcp.svg)](https://badge.fury.io/py/pubmed-search-mcp)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)
[![Test Coverage](https://img.shields.io/badge/coverage-84%25-green.svg)](https://github.com/u9401066/pubmed-search-mcp)

> **Professional Literature Research Assistant for AI Agents** - More than just an API wrapper

A Domain-Driven Design (DDD) based MCP server that serves as an intelligent research assistant for AI agents, providing task-oriented literature search and analysis capabilities.

**✨ What's Included:**
- 🔧 **40 MCP Tools** - Streamlined PubMed, Europe PMC, CORE, NCBI database access, and **Research Timeline / Context Graph**
- 📚 **22 Claude Skills** - Ready-to-use workflow guides for AI agents (Claude Code-specific)
- 📖 **Copilot Instructions** - VS Code GitHub Copilot integration guide

**🌐 Language**: **English** | [繁體中文](README.zh-TW.md)

---

## 🚀 Quick Install

### Prerequisites

- **Python 3.10+** — [Download](https://www.python.org/downloads/)
- **uv** (recommended) — [Install uv](https://docs.astral.sh/uv/getting-started/installation/)
  ```bash
  # macOS / Linux
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # Windows
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
- **NCBI Email** — Required by [NCBI API policy](https://www.ncbi.nlm.nih.gov/books/NBK25497/#chapter2.Usage_Guidelines_and_Requiremen). Any valid email address.
- **NCBI API Key** *(optional)* — [Get one here](https://www.ncbi.nlm.nih.gov/account/settings/) for higher rate limits (10 req/s vs 3 req/s)

### Install & Run

```bash
# Option 1: Zero-install with uvx (recommended for trying out)
uvx pubmed-search-mcp

# Option 2: Add as project dependency
uv add pubmed-search-mcp

# Option 3: pip install
pip install pubmed-search-mcp
```

---

## ⚙️ Configuration

This MCP server works with **any MCP-compatible AI tool**. Choose your preferred client:

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

> **Config file location**:
> - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
> - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
> - Linux: `~/.config/Claude/claude_desktop_config.json`

### Claude Code

```bash
claude mcp add pubmed-search -- uvx pubmed-search-mcp
```

Or add to `.mcp.json` in your project root:

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

### Zed AI (`settings.json`)

Zed editor ([z.ai](https://zed.dev)) supports MCP servers natively. Add to your Zed `settings.json`:

```json
{
  "context_servers": {
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

> **Tip**: Open Command Palette → `zed: open settings` to edit, or go to Agent Panel → Settings → "Add Custom Server".

### OpenClaw 🦞 (`~/.openclaw/openclaw.json`)

[OpenClaw](https://docs.openclaw.ai/) uses MCP servers via the [mcp-adapter plugin](https://github.com/androidStern-personal/openclaw-mcp-adapter). Install the adapter first:

```bash
openclaw plugins install mcp-adapter
```

Then add to `~/.openclaw/openclaw.json`:

```json
{
  "plugins": {
    "entries": {
      "mcp-adapter": {
        "enabled": true,
        "config": {
          "servers": [
            {
              "name": "pubmed-search",
              "transport": "stdio",
              "command": "uvx",
              "args": ["pubmed-search-mcp"],
              "env": {
                "NCBI_EMAIL": "your@email.com"
              }
            }
          ]
        }
      }
    }
  }
}
```

Restart the gateway after configuration:

```bash
openclaw gateway restart
openclaw plugins list  # Should show: mcp-adapter | loaded
```

### Cline (`cline_mcp_settings.json`)

```json
{
  "mcpServers": {
    "pubmed-search": {
      "command": "uvx",
      "args": ["pubmed-search-mcp"],
      "env": {
        "NCBI_EMAIL": "your@email.com"
      },
      "alwaysAllow": [],
      "disabled": false
    }
  }
}
```

### Other MCP Clients

Any MCP-compatible client can use this server via stdio transport:

```bash
# Command
uvx pubmed-search-mcp

# With environment variable
NCBI_EMAIL=your@email.com uvx pubmed-search-mcp
```

> **Note**: `NCBI_EMAIL` is required by NCBI API policy. Optionally set `NCBI_API_KEY` for higher rate limits (10 req/s vs 3 req/s).

> 📖 **Detailed Integration Guides**: See [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) for all environment variables, Copilot Studio setup, Docker deployment, proxy configuration, and troubleshooting.

---

## 🎯 Design Philosophy

> **Core Positioning**: The **intelligent middleware** between AI Agents and academic search engines.

### Why This Server?

Other tools give you raw API access. We give you **vocabulary translation + intelligent routing + research analysis**:

| Challenge | Our Solution |
|-----------|-------------|
| Agent uses ICD codes, PubMed needs MeSH | ✅ **Auto ICD→MeSH conversion** |
| Multiple databases, different APIs | ✅ **Unified Search** single entry point |
| Clinical questions need structured search | ✅ **PICO toolkit** (`parse_pico` + `generate_search_queries` for Agent-driven workflow) |
| Typos in medical terms | ✅ **ESpell auto-correction** |
| Too many results from one source | ✅ **Parallel multi-source** with dedup |
| Need to trace research evolution | ✅ **Research Timeline & Tree** with landmark detection and sub-topic branching |
| Citation context is unclear | ✅ **Citation Tree** forward/backward/network |
| Can't access full text | ✅ **Multi-source fulltext** (Europe PMC, CORE, CrossRef) |
| Gene/drug info scattered across DBs | ✅ **NCBI Extended** (Gene, PubChem, ClinVar) |
| Need cutting-edge preprints | ✅ **Preprint search** (arXiv, medRxiv, bioRxiv) with peer-review filtering |
| Export to reference managers | ✅ **One-click export** (RIS, BibTeX, CSV, MEDLINE) |

### Key Differentiators

1. **Vocabulary Translation Layer** - Agent speaks naturally, we translate to each database's terminology (MeSH, ICD-10, text-mined entities)
2. **Unified Search Gateway** - One `unified_search()` call, auto-dispatch to PubMed/Europe PMC/CORE/OpenAlex
3. **PICO Toolkit** - `parse_pico()` decomposes clinical questions into P/I/C/O elements; Agent then calls `generate_search_queries()` per element and builds Boolean query
4. **Research Timeline & Lineage Tree** - Detect milestones (FDA approvals, Phase 3, guidelines), identify landmark papers via multi-signal scoring, and visualize research evolution as branching trees by sub-topic
5. **Citation Network Analysis** - Build multi-level citation trees to map an entire research landscape from a single paper
6. **Full Research Lifecycle** - From search → discovery → full text → analysis → export, all in one server
7. **Agent-First Design** - Output optimized for machine decision-making, not human reading

---

## 📡 External APIs & Data Sources

This MCP server integrates with multiple academic databases and APIs:

### Core Data Sources

| Source | Coverage | Vocabulary | Auto-Convert | Description |
|--------|----------|------------|--------------|-------------|
| **NCBI PubMed** | 36M+ articles | MeSH | ✅ Native | Primary biomedical literature |
| **NCBI Entrez** | Multi-DB | MeSH | ✅ Native | Gene, PubChem, ClinVar |
| **Europe PMC** | 33M+ | Text-mined | ✅ Extraction | Full text XML access |
| **CORE** | 200M+ | None | ➡️ Free-text | Open access aggregator |
| **Semantic Scholar** | 200M+ | S2 Fields | ➡️ Free-text | AI-powered recommendations |
| **OpenAlex** | 250M+ | Concepts | ➡️ Free-text | Open scholarly metadata |
| **NIH iCite** | PubMed | N/A | N/A | Citation metrics (RCR) |

> **🔑 Key**: ✅ = Full vocabulary support | ➡️ = Query pass-through (no controlled vocabulary)
>
> **ICD Codes**: Auto-detected and converted to MeSH before PubMed search

### Environment Variables

```bash
# Required
NCBI_EMAIL=your@email.com          # Required by NCBI policy

# Optional - For higher rate limits
NCBI_API_KEY=your_ncbi_api_key     # Get from: https://www.ncbi.nlm.nih.gov/account/settings/
CORE_API_KEY=your_core_api_key     # Get from: https://core.ac.uk/services/api
S2_API_KEY=your_s2_api_key         # Get from: https://www.semanticscholar.org/product/api

# Optional - Network settings
HTTP_PROXY=http://proxy:8080       # HTTP proxy for API requests
HTTPS_PROXY=https://proxy:8080     # HTTPS proxy for API requests
```


## 🔄 How It Works: The Middleware Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AI AGENT                                        │
│                                                                              │
│   "Find papers about I10 hypertension treatment in diabetic patients"       │
│                                                                              │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     🔄 PUBMED SEARCH MCP (MIDDLEWARE)                        │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │  1️⃣ VOCABULARY TRANSLATION                                              ││
│  │     • ICD-10 "I10" → MeSH "Hypertension"                                ││
│  │     • "diabetic" → MeSH "Diabetes Mellitus"                             ││
│  │     • ESpell: "hypertention" → "hypertension"                           ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │  2️⃣ INTELLIGENT ROUTING                                                 ││
│  │     ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐             ││
│  │     │ PubMed   │  │Europe PMC│  │   CORE   │  │ OpenAlex │             ││
│  │     │  36M+    │  │   33M+   │  │  200M+   │  │  250M+   │             ││
│  │     │  (MeSH)  │  │(fulltext)│  │  (OA)    │  │(metadata)│             ││
│  │     └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘             ││
│  │          └──────────────┴──────────────┴──────────────┘                 ││
│  │                              ▼                                          ││
│  │  3️⃣ RESULT AGGREGATION: Dedupe + Rank + Enrich                         ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         UNIFIED RESULTS                                      │
│   • 150 unique papers (deduplicated from 4 sources)                          │
│   • Ranked by relevance + citation impact (RCR)                              │
│   • Full text links enriched from Europe PMC                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🛠️ MCP Tools Overview

### 🔍 Search & Query Intelligence

```
┌─────────────────────────────────────────────────────────────────┐
│                      SEARCH ENTRY POINT                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   unified_search()          ← 🌟 Single entry for all sources    │
│        │                                                         │
│        ├── Quick search     → Direct multi-source query          │
│        ├── PICO hints       → Detects comparison, shows P/I/C/O  │
│        └── ICD expansion    → Auto ICD→MeSH conversion           │
│                                                                  │
│   Sources: PubMed · Europe PMC · CORE · OpenAlex                 │
│   Auto: Deduplicate → Rank → Enrich full-text links              │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│   QUERY INTELLIGENCE                                             │
│                                                                  │
│   generate_search_queries() → MeSH expansion + synonym discovery │
│   parse_pico()              → PICO element decomposition         │
│   analyze_search_query()    → Query analysis without execution   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 🔬 Discovery Tools (After Finding Key Papers)

```
                        Found important paper (PMID)
                                   │
           ┌───────────────────────┼───────────────────────┐
           │                       │                       │
           ▼                       ▼                       ▼
    ┌─────────────┐        ┌─────────────┐        ┌─────────────┐
    │  BACKWARD   │        │  SIMILAR    │        │  FORWARD    │
    │  ◀──────    │        │  ≈≈≈≈≈≈     │        │  ──────▶    │
    │             │        │             │        │             │
    │ get_article │        │find_related │        │find_citing  │
    │ _references │        │ _articles   │        │ _articles   │
    │             │        │             │        │             │
    │ Foundation  │        │  Similar    │        │ Follow-up   │
    │  papers     │        │   topic     │        │  research   │
    └─────────────┘        └─────────────┘        └─────────────┘

    fetch_article_details()   → Detailed article metadata
    get_citation_metrics()    → iCite RCR, citation percentile
    build_citation_tree()     → Full network visualization (6 formats)

```

### 📚 Full Text & Export

| Category | Tools |
|----------|-------|
| **Full Text** | `get_fulltext` → Multi-source retrieval (Europe PMC, CORE, PubMed, CrossRef) |
| **Text Mining** | `get_text_mined_terms` → Extract genes, diseases, chemicals |
| **Export** | `prepare_export` → RIS, BibTeX, CSV, MEDLINE, JSON |

### 🧬 NCBI Extended Databases

| Tool | Description |
|------|-------------|
| `search_gene` | Search NCBI Gene database |
| `get_gene_details` | Gene details by NCBI Gene ID |
| `get_gene_literature` | PubMed articles linked to a gene |
| `search_compound` | Search PubChem compounds |
| `get_compound_details` | Compound details by PubChem CID |
| `get_compound_literature` | PubMed articles linked to a compound |
| `search_clinvar` | Search ClinVar clinical variants |

### 🕰️ Research Timeline & Lineage Tree

| Tool | Description |
|------|-------------|
| `build_research_timeline` | Build timeline/tree with landmark detection. Output: text, tree, mermaid, mindmap, json |
| `analyze_timeline_milestones` | Analyze milestone distribution |
| `compare_timelines` | Compare multiple topic timelines |

### 🏥 Institutional Access & ICD Conversion

| Tool | Description |
|------|-------------|
| `configure_institutional_access` | Configure institution's link resolver |
| `get_institutional_link` | Generate OpenURL access link |
| `list_resolver_presets` | List resolver presets |
| `test_institutional_access` | Test resolver configuration |
| `convert_icd_mesh` | Convert between ICD codes and MeSH terms (bidirectional) |

### 💾 Session Management

| Tool | Description |
|------|-------------|
| `get_session_pmids` | Retrieve cached PMID lists |
| `get_cached_article` | Get article from session cache (no API cost) |
| `get_session_summary` | Session status overview |

### � Pipeline Management

| Tool | Description |
|------|-------------|
| `save_pipeline` | Save a pipeline config for later reuse (YAML/JSON, auto-validated) |
| `list_pipelines` | List saved pipelines (filter by tag/scope) |
| `load_pipeline` | Load pipeline from name or file for review/editing |
| `delete_pipeline` | Delete pipeline and its execution history |
| `get_pipeline_history` | View execution history with article diff analysis |
| `schedule_pipeline` | Schedule periodic execution (Phase 4) |

### �👁️ Vision & Image Search

| Tool | Description |
|------|-------------|
| `analyze_figure_for_search` | Analyze scientific figure for search |
| `search_biomedical_images` | Search biomedical images across Open-i (X-ray, microscopy, photos, diagrams) |

### 📄 Preprint Search

Search **arXiv**, **medRxiv**, and **bioRxiv** preprint servers via `unified_search` `options=`:

| Option Flag | Default | Description |
|-------------|---------|-------------|
| `preprints` | off | Enable dedicated preprint search. Results appear in a **separate section** |
| `all_types` | off | Keep non-peer-reviewed results in the main ranked list |

**Recommended combinations:**

| `options` | Behavior |
|-----------|----------|
| _(empty)_ | Peer-reviewed results only |
| `preprints` | Main results stay peer-reviewed; preprints shown in a separate section |
| `preprints, all_types` | Preprints shown separately and can also remain in the main list |

**Preprint detection** — articles are identified as preprints by:
- Article type from source API (OpenAlex, CrossRef, Semantic Scholar)
- arXiv ID present without PubMed ID
- Known preprint server source or journal name
- DOI prefix matching preprint servers (e.g., `10.1101/` → bioRxiv/medRxiv, `10.48550/` → arXiv)

### 🌳 Research Context Graph

`unified_search` can append a lightweight research lineage view built from PMID-backed ranked results:

| Option Flag | Description |
|-------------|-------------|
| `context_graph` | Append a Research Context Graph preview to Markdown output and include `research_context` in JSON output |

This is useful when an agent needs quick thematic branching without making a second `build_research_timeline` call.

### ⏱️ MCP Progress Reporting

When the MCP client provides a progress token, `unified_search` now emits progress updates for major phases such as query analysis, semantic enhancement, deep search, enrichment, ranking, and final formatting.
This reduces the "black box" wait time for agents during longer searches.

---

## 📋 Agent Usage Examples

### 1️⃣ Quick Search (Simplest)

```python
# Agent just asks naturally - middleware handles everything
unified_search(query="remimazolam ICU sedation", limit=20)

# Or with clinical codes - auto-converted to MeSH
unified_search(query="I10 treatment in E11.9 patients")
#                     ↑ ICD-10           ↑ ICD-10
#                     Hypertension       Type 2 Diabetes
```

### 2️⃣ PICO Clinical Question

**Simple path** — `unified_search` can search directly (no PICO decomposition):

```python
# unified_search searches as-is; detects "A vs B" pattern and shows PICO hints in metadata
unified_search(query="Is remimazolam better than propofol for ICU sedation?")
# → Multi-source keyword search + PICO hint metadata in output
# ⚠️ This does NOT auto-decompose PICO or expand MeSH!
# For structured PICO search, use the Agent workflow below
```

**Agent workflow** — PICO decomposition + MeSH expansion (recommended for clinical questions):

```
┌─────────────────────────────────────────────────────────────────────────┐
│  "Is remimazolam better than propofol for ICU sedation?"                │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         parse_pico()                                     │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐                     │
│  │    P    │  │    I    │  │    C    │  │    O    │                     │
│  │  ICU    │  │remimaz- │  │propofol │  │sedation │                     │
│  │patients │  │  olam   │  │         │  │outcomes │                     │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘                     │
└───────┼────────────┼────────────┼────────────┼──────────────────────────┘
        │            │            │            │
        ▼            ▼            ▼            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              generate_search_queries() × 4 (parallel)                    │
│                                                                          │
│  P → "Intensive Care Units"[MeSH]                                        │
│  I → "remimazolam" [Supplementary Concept], "CNS 7056"                   │
│  C → "Propofol"[MeSH], "Diprivan"                                        │
│  O → "Conscious Sedation"[MeSH], "Deep Sedation"[MeSH]                   │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              Agent combines with Boolean logic                           │
│                                                                          │
│  (P) AND (I) AND (C) AND (O)  ← High precision                           │
│  (P) AND (I OR C) AND (O)     ← High recall                              │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              unified_search() (auto multi-source + dedup)                │
│                                                                          │
│  PubMed + Europe PMC + CORE + OpenAlex → Auto deduplicate & rank         │
└─────────────────────────────────────────────────────────────────────────┘
```

```python
# Step 1: Parse clinical question
parse_pico("Is remimazolam better than propofol for ICU sedation?")
# Returns: P=ICU patients, I=remimazolam, C=propofol, O=sedation outcomes

# Step 2: Get MeSH for each element (parallel!)
generate_search_queries(topic="ICU patients")   # P
generate_search_queries(topic="remimazolam")    # I
generate_search_queries(topic="propofol")       # C
generate_search_queries(topic="sedation")       # O

# Step 3: Agent combines with Boolean
query = '("Intensive Care Units"[MeSH]) AND (remimazolam OR "CNS 7056") AND propofol AND sedation'

# Step 4: Search (auto multi-source, dedup, rank)
unified_search(query=query)
```

### 3️⃣ Explore from Key Paper

```python
# Found landmark paper PMID: 33475315
find_related_articles(pmid="33475315")   # Similar methodology
find_citing_articles(pmid="33475315")    # Who built on this?
get_article_references(pmid="33475315")  # What's the foundation?

# Build complete research map
build_citation_tree(pmid="33475315", depth=2, output_format="mermaid")
```

### 4️⃣ Gene/Drug Research

```python
# Research a gene
search_gene(query="BRCA1", organism="human")
get_gene_literature(gene_id="672", limit=20)

# Research a drug compound
search_compound(query="propofol")
get_compound_literature(cid="4943", limit=20)
```

### 5️⃣ Export Results

```python
# Export last search results
prepare_export(pmids="last", format="ris")      # → EndNote/Zotero
prepare_export(pmids="last", format="bibtex")   # → LaTeX

# Check open access availability
analyze_fulltext_access(pmids="last")
```

### 6️⃣ Preprint Search

```python
# Include preprints alongside peer-reviewed results
unified_search("COVID-19 vaccine efficacy", options="preprints")
# → Main results (peer-reviewed) + Separate preprint section (arXiv, medRxiv, bioRxiv)

# Include preprints mixed into main results
unified_search("CRISPR gene therapy", options="preprints, all_types")
# → All results mixed together, preprints marked as such

# Only peer-reviewed (default behavior)
unified_search("diabetes treatment")
# → Preprints from any source automatically filtered out

# Add a research context graph preview to the same search response
unified_search("remimazolam ICU sedation", options="context_graph")
```

### 7️⃣ Pipeline (Reusable Search Plans)

```python
# Save a template-based pipeline
save_pipeline(
    name="icu_sedation_weekly",
    config="template: pico\nparams:\n  P: ICU patients\n  I: remimazolam\n  C: propofol\n  O: delirium",
    tags="anesthesia,sedation",
    description="Weekly ICU sedation monitoring"
)

# Save a custom DAG pipeline
save_pipeline(
    name="brca1_comprehensive",
    config="""
steps:
  - id: expand
    action: expand
    params: { topic: BRCA1 breast cancer }
  - id: pubmed
    action: search
    params: { query: BRCA1, sources: pubmed, limit: 50 }
  - id: expanded
    action: search
    inputs: [expand]
    params: { strategy: mesh, sources: pubmed,openalex, limit: 50 }
  - id: merged
    action: merge
    inputs: [pubmed, expanded]
    params: { method: rrf }
  - id: enriched
    action: metrics
    inputs: [merged]
output:
  limit: 30
  ranking: quality
"""
)

# Execute a saved pipeline
unified_search(pipeline="saved:icu_sedation_weekly")

# List & manage
list_pipelines(tag="anesthesia")
load_pipeline(source="brca1_comprehensive")  # Review YAML
get_pipeline_history(name="icu_sedation_weekly")  # View past runs
```

---

## 🔍 Search Mode Comparison

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        SEARCH MODE DECISION TREE                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   "What kind of search do I need?"                                       │
│         │                                                                │
│         ├── Know exactly what to search?                                 │
│         │   └── unified_search(query="topic keywords")                   │
│         │       → Quick, auto-routing to best sources                    │
│         │                                                                │
│         ├── Have a clinical question (A vs B)?                           │
│         │   └── parse_pico() → generate_search_queries() × N             │
│         │       → Agent builds Boolean → unified_search()                │
│         │                                                                │
│         ├── Need comprehensive systematic coverage?                      │
│         │   └── generate_search_queries() → parallel search              │
│         │       → MeSH expansion, multiple strategies, merge             │
│         │                                                                │
│         └── Exploring from a key paper?                                  │
│             └── find_related/citing/references → build_citation_tree     │
│                 → Citation network, research context                     │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

| Mode | Entry Point | Best For | Auto-Features |
|------|-------------|----------|---------------|
| **Quick** | `unified_search()` | Fast topic search | ICD→MeSH, multi-source, dedup |
| **PICO** | `parse_pico()` → Agent | Clinical questions | Agent: decompose → MeSH expand → Boolean |
| **Systematic** | `generate_search_queries()` | Literature reviews | MeSH expansion, synonyms |
| **Exploration** | `find_*_articles()` | From key paper | Citation network, related |

---

## 🤖 Claude Skills (AI Agent Workflows)

Pre-built workflow guides in `.claude/skills/`, divided into **Usage Skills** (for using the MCP server) and **Development Skills** (for maintaining the project):

### 📚 Usage Skills (9) — For AI Agents Using This MCP Server

| Skill | Description |
|-------|-------------|
| `pubmed-quick-search` | Basic search with filters |
| `pubmed-systematic-search` | MeSH expansion, comprehensive |
| `pubmed-pico-search` | Clinical question decomposition |
| `pubmed-paper-exploration` | Citation tree, related articles |
| `pubmed-gene-drug-research` | Gene/PubChem/ClinVar |
| `pubmed-fulltext-access` | Europe PMC, CORE full text |
| `pubmed-export-citations` | RIS/BibTeX/CSV export |
| `pubmed-multi-source-search` | Cross-database unified search |
| `pubmed-mcp-tools-reference` | Complete tool reference guide |
| `pipeline-persistence` | Save, load, reuse search plans |

### 🔧 Development Skills (13) — For Project Contributors

| Skill | Description |
|-------|-------------|
| `changelog-updater` | Auto-update CHANGELOG.md |
| `code-refactor` | DDD architecture refactoring |
| `code-reviewer` | Code quality & security review |
| `ddd-architect` | DDD scaffold for new features |
| `git-doc-updater` | Sync docs before commits |
| `git-precommit` | Pre-commit workflow orchestration |
| `memory-checkpoint` | Save context to Memory Bank |
| `memory-updater` | Update Memory Bank files |
| `project-init` | Initialize new projects |
| `readme-i18n` | Multilingual README sync |
| `readme-updater` | Sync README with code changes |
| `roadmap-updater` | Update ROADMAP.md status |
| `test-generator` | Generate test suites |

> 📁 **Location**: `.claude/skills/*/SKILL.md` (Claude Code-specific)

---

## 🏗️ Architecture (DDD)

This project uses **Domain-Driven Design (DDD)** architecture, with literature research domain knowledge as the core model.

```
src/pubmed_search/
├── domain/                     # Core business logic
│   └── entities/article.py     # UnifiedArticle, Author, etc.
├── application/                # Use cases
│   ├── search/                 # QueryAnalyzer, ResultAggregator
│   ├── export/                 # Citation export (RIS, BibTeX...)
│   └── session/                # SessionManager
├── infrastructure/             # External systems
│   ├── ncbi/                   # Entrez, iCite, Citation Exporter
│   ├── sources/                # Europe PMC, CORE, CrossRef...
│   └── http/                   # HTTP clients
├── presentation/               # User interfaces
│   ├── mcp_server/             # MCP tools, prompts, resources
│   │   └── tools/              # discovery, strategy, pico, export...
│   └── api/                    # REST API (Copilot Studio)
└── shared/                     # Cross-cutting concerns
    ├── exceptions.py           # Unified error handling
    └── async_utils.py          # Rate limiter, retry, circuit breaker
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

### Vocabulary Translation Layer (Key Feature)

> **Our Core Value**: We are the **intelligent middleware** between Agent and Search Engines, automatically handling vocabulary standardization so Agent doesn't need to know each database's terminology.

Different data sources use different controlled vocabulary systems. This server provides automatic conversion:

| API / Database | Vocabulary System | Auto-Conversion |
|----------------|-------------------|-----------------|
| **PubMed / NCBI** | MeSH (Medical Subject Headings) | ✅ Full support via `expand_with_mesh()` |
| **ICD Codes** | ICD-10-CM / ICD-9-CM | ✅ Auto-detect & convert to MeSH |
| **Europe PMC** | Text-mined entities (Gene, Disease, Chemical) | ✅ `get_text_mined_terms()` extraction |
| **OpenAlex** | OpenAlex Concepts (deprecated) | ❌ Free-text only |
| **Semantic Scholar** | S2 Field of Study | ❌ Free-text only |
| **CORE** | None | ❌ Free-text only |
| **CrossRef** | None | ❌ Free-text only |

#### Automatic ICD → MeSH Conversion

When searching with ICD codes (e.g., `I10` for Hypertension), `unified_search()` automatically:
1. Detects ICD-10/ICD-9 patterns via `detect_and_expand_icd_codes()`
2. Looks up corresponding MeSH terms from internal mapping (`ICD10_TO_MESH`, `ICD9_TO_MESH`)
3. Expands query with MeSH synonyms for comprehensive search

```python
# Agent calls unified_search with clinical terminology
unified_search(query="I10 treatment outcomes")

# Server auto-expands to PubMed-compatible query
"(I10 OR Hypertension[MeSH]) treatment outcomes"
```

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

---

## 🏢 Microsoft Copilot Studio Integration

Integrate PubMed Search MCP with **Microsoft 365 Copilot** (Word, Teams, Outlook)!

### Quick Start

```bash
# Start with Streamable HTTP transport (required by Copilot Studio)
python run_server.py --transport streamable-http --port 8765

# Or use the dedicated script with ngrok
./scripts/start-copilot-studio.sh --with-ngrok
```

### Copilot Studio Configuration

| Field | Value |
|-------|-------|
| **Server name** | `PubMed Search` |
| **Server URL** | `https://your-server.com/mcp` |
| **Authentication** | `None` (or API Key) |

> 📖 **Full documentation**: [copilot-studio/README.md](copilot-studio/README.md)
>
> ⚠️ **Note**: SSE transport deprecated since Aug 2025. Use `streamable-http`.

---

> 📖 **More documentation**:
> - Architecture → [ARCHITECTURE.md](ARCHITECTURE.md)
> - Deployment guide → [DEPLOYMENT.md](DEPLOYMENT.md)
> - Copilot Studio → [copilot-studio/README.md](copilot-studio/README.md)

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

## 📄 License

Apache License 2.0 - see [LICENSE](LICENSE)

---

## 🔗 Links

- [GitHub Repository](https://github.com/u9401066/pubmed-search-mcp)
- [PyPI Package](https://pypi.org/project/pubmed-search/)
- [NCBI Entrez Programming Utilities](https://www.ncbi.nlm.nih.gov/books/NBK25497/)
