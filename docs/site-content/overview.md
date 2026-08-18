<!-- Generated from README.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# PubMed Search MCP

[![PyPI version](https://badge.fury.io/py/pubmed-search-mcp.svg)](https://badge.fury.io/py/pubmed-search-mcp)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)
[![CI](https://github.com/u9401066/pubmed-search-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/u9401066/pubmed-search-mcp/actions/workflows/ci.yml)

> **Professional Literature Research Assistant for AI Agents** - More than just an API wrapper

![PubMed Search MCP research workflow](images/research-workflow.svg)

A Domain-Driven Design (DDD) based MCP server that serves as an intelligent research assistant for AI agents, providing task-oriented literature search and analysis capabilities.

**✨ What's Included:**

- 🔧 **45 MCP Tools** - Streamlined PubMed, Europe PMC, CORE, NCBI database access, and **Research Chronicle / Context Graph**
- 🛡️ **Multi-Agent Service Mode** - Deploy once and serve many agents: per-tenant sessions, caches, and artifacts, bearer-token auth, and per-tenant fair-share limits. See [DEPLOYMENT.md](#/deployment)
- 🖼️ **OA Figure Extraction** - Pull figure captions, direct image URLs, and PDF links from PMC Open Access articles
- 📘 **Docs Site** - Browse the complete language-switchable handbook: user workflows, architecture, 45-tool reference, pipeline tutorials, source/broker contracts, integrations and operations, security, and deployment at [u9401066.github.io/pubmed-search-mcp](https://u9401066.github.io/pubmed-search-mcp/)
- 📖 **GitHub Wiki** - GitHub-native mirror of the same canonical documentation at [github.com/u9401066/pubmed-search-mcp/wiki](https://github.com/u9401066/pubmed-search-mcp/wiki)
- 📚 **26 Claude Skills** - Ready-to-use workflow guides for AI agents (Claude Code-specific)
- 📖 **Copilot Instructions** - VS Code GitHub Copilot integration guide

**🌐 Language**: **English** | [繁體中文](#/overview-zh)

**📘 Documentation Map**: README is the quick project entry point. Use the [Docs Site](https://u9401066.github.io/pubmed-search-mcp/) for the best reading experience, the [GitHub Wiki](https://github.com/u9401066/pubmed-search-mcp/wiki) for GitHub-native navigation, and source docs for edits: [User guide](#/user-guide) | [Advanced workflows](#/advanced-workflows) | [Capability-first guide](#/tools-usage-guide) | [Provider data planes](#/semantic-scholar-api) | [BioMCP architecture analysis](#/biomcp-analysis) | [Developer guide](#/developer-guide) | [Complete index](#/quick-reference)

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

- **NCBI Email** — Required by [NCBI API policy](https://www.ncbi.nlm.nih.gov/books/NBK25497/#chapter2.Usage_Guidelines_and_Requirements). Any valid email address.
- **NCBI API Key** *(optional)* — [Get one here](https://www.ncbi.nlm.nih.gov/account/settings/) for higher rate limits (10 req/s vs 3 req/s)
- **OpenAlex API Key** *(optional)* — set `OPENALEX_API_KEY` to use an authenticated credit allocation; without it, requests use OpenAlex's current anonymous casual-use budget. `mailto` is contact metadata, not authentication. Without source-specific emails, the server reuses the configured runtime contact email for OpenAlex, CrossRef, and Unpaywall.

### Install & Run

```bash
# Option 1: Zero-install with uvx (recommended for trying out)
uvx pubmed-search-mcp

# Option 2: Add as project dependency
uv add pubmed-search-mcp

# Option 3: pip install
pip install pubmed-search-mcp
```

### Python SDK Facade

For in-process Python integrations, use the stable SDK facade instead of
importing MCP tool modules:

```python
from pubmed_search.api import PubMedSearchClient, PubMedSearchConfig

client = PubMedSearchClient(PubMedSearchConfig(email="your@email.com"))
result = await client.unified_search("remimazolam ICU sedation", limit=20)

print(result.articles)
print(result.source_counts)
print(result.artifact)  # artifact locator when persistence is enabled
```

Use `uvx pubmed-search-mcp` or `/mcp` for agent tool discovery. Use the SDK for
Python package/notebook calls where a typed object is easier than parsing an MCP
response string.

### Choose a Runtime Contract

| Contract | Command | Network and trust boundary |
| --- | --- | --- |
| **Local stdio** | `uvx pubmed-search-mcp` | Recommended for one local AI client; no listening MCP port |
| **Local loopback HTTP** | `pubmed-search-mcp-http --mode local --host 127.0.0.1` | Trusted single-user integration; MCP requests share the durable `default` tenant, and the port must never be published |
| **Multi-user service** | `pubmed-search-mcp-http --mode service` | Remote/team use behind HTTPS; bearer auth, allowed hosts/origins, and per-principal storage are mandatory |

Local and service deployments are intentionally separate contracts. Do not turn
the local HTTP command into a public service by changing only its bind address.
The explicit local profile retains `pmids="last"`, sessions, cache, and exports
across MCP requests and reconnects in its durable `default` tenant; this is safe
only inside the enforced loopback/Host/Origin boundary. Service mode never
inherits that trust: it fails closed without a bearer principal. Use
[DEPLOYMENT.md](#/deployment) for the service environment and Compose profile.
The current service profile supports many authenticated principals in one
server process; keep one replica until sessions, locks, artifacts, and
subscriptions have shared backends.

The protocol baseline is MCP SDK v2 (`mcp>=2.0,<3`). Modern 2026-07-28 clients
send `tools/list` and `tools/call` directly, without an `initialize` handshake or
`Mcp-Session-Id`. Local mode retains filesystem features. Authenticated service
callers cannot load `file:` pipelines, select note `output_dir`/`template_file`,
or inherit a process-wide pipeline workspace; the service Compose scheduler is
disabled. See the [Integrations & Operations Guide](#/troubleshooting) for the
capability matrix.

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

Optional: enable browser-session PDF fallback once and let tools auto-use it:

```json
{
  "servers": {
    "pubmed-search": {
      "type": "stdio",
      "command": "uvx",
      "args": ["pubmed-search-mcp"],
      "env": {
        "NCBI_EMAIL": "your@email.com",
        "BROWSER_FETCH_CONFIG": "{\"enabled\":true,\"auto_enabled\":true,\"broker_url\":\"http://127.0.0.1:8766/fetch\",\"token\":\"<random-32-byte-token>\",\"allowed_hosts\":[\"jamanetwork.com\",\"*.jamanetwork.com\",\"nejm.org\",\"*.nejm.org\"]}"
      }
    }
  }
}
```

With this setting, get_fulltext will automatically try the local broker for institutional or publisher landing pages. Pass allow_browser_session=false only when you want to suppress it for a specific call.

Run the local broker with download interception:

```bash
uv sync --extra browser-broker
uv run playwright install chromium
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
uv run pubmed-browser-fetch-broker --token "<same-random-32-byte-token>"
```

Copy the generated value into both commands/configurations; never reuse a
published example token. If `--token` is omitted, the broker generates and
prints a high-entropy runtime token. The broker launches a persistent browser
profile with download interception enabled. Log in once inside that
broker-controlled browser window, and subsequent PDF downloads will be captured
automatically without a native "Save As" dialog.

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
>
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
        "NCBI_EMAIL": "your@email.com",
        "S2_API_KEY": "your_semantic_scholar_key",
        "PUBMED_SEARCH_DISABLED_SOURCES": ""
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
> 📖 **Detailed Integration Guides**: See [docs/INTEGRATIONS.md](#/troubleshooting) for all environment variables, Copilot Studio setup, Docker deployment, proxy configuration, and troubleshooting.

---

## 🎯 Design Philosophy

> **Core Positioning**: The **intelligent middleware** between AI Agents and academic search engines.

### Why This Server?

Other tools give you raw API access. We give you **vocabulary translation + intelligent routing + research analysis**:

| Challenge | Our Solution |
| --------- | ------------ |
| Agent uses ICD codes, PubMed needs MeSH | ✅ **Auto ICD→MeSH conversion** |
| Multiple databases, different APIs | ✅ **Unified Search** single entry point |
| Clinical questions need structured search | ✅ **PICO handoff + pipeline** (`parse_pico` validates agent-provided P/I/C/O and returns a runnable `template: pico` pipeline) |
| Typos in medical terms | ✅ **ESpell auto-correction** |
| Too many results from one source | ✅ **Parallel multi-source** with dedup |
| Need to trace research evolution | ✅ **Research Chronicle & Tree** with landmark detection, diagnostics, sub-topic branching, and versioned revisions |
| Citation context is unclear | ✅ **Citation Tree** forward/backward/network |
| Can't access full text | ✅ **Multi-source fulltext** (Europe PMC XML, Unpaywall OA locations, institutional direct/EZproxy, CORE, and downloader fallbacks) |
| Gene/drug info scattered across DBs | ✅ **NCBI Extended** (Gene, PubChem, ClinVar) |
| Need cutting-edge preprints | ✅ **Preprint search** (arXiv, medRxiv, bioRxiv) with peer-review filtering |
| Export to reference managers | ✅ **One-click export** (official RIS/MEDLINE/CSL JSON; local RIS/BibTeX/CSV/MEDLINE/JSON) |

### Key Differentiators

1. **Vocabulary Translation Layer** - Agent speaks naturally, we translate to each database's terminology (MeSH, ICD-10, text-mined entities)
2. **Unified Search Gateway** - One `unified_search()` call, capability-aware dispatch across PubMed, Europe PMC, CORE, OpenAlex, Semantic Scholar, and enabled preprint/commercial sources
3. **PICO Handoff + Pipeline** - the Agent extracts P/I/C/O, `parse_pico()` validates that structured handoff, and the backend `template: pico` pipeline executes O-aware precision/recall searches
4. **Research Chronicle & Lineage Tree** - Detect milestones with policy-driven heuristics, identify landmark papers via multi-signal scoring, surface diagnostics, persist versioned revisions you can diff, and visualize research evolution as branching trees by sub-topic
5. **Citation Network Analysis** - Build multi-level citation trees to map an entire research landscape from a single paper
6. **Full Research Lifecycle** - From search → discovery → full text → analysis → export, all in one server
7. **Agent-First Design** - Output optimized for machine decision-making, not human reading

---

## 📡 External APIs & Data Sources

This MCP server integrates with multiple academic databases and APIs:

### Core Data Sources

| Source | Coverage | Vocabulary | Auto-Convert | Description |
| ------ | -------- | ---------- | ------------ | ----------- |
| **NCBI PubMed** | 36M+ articles | MeSH | ✅ Native | Primary biomedical literature |
| **NCBI Entrez** | Multi-DB | MeSH | ✅ Native | Gene, PubChem, ClinVar |
| **Europe PMC** | 33M+ | Text-mined | ✅ Extraction | Full text XML access |
| **CORE** | 200M+ | None | ➡️ Free-text | Open access aggregator |
| **Semantic Scholar** | Evolving graph + operator datasets | S2 fields / bulk syntax | ✅ Broker-compiled modes | Relevance, bounded bulk, batch, citation graph, and metadata-only release/diff plane; no partition download |
| **OpenAlex** | Evolving open research graph | Topics / keywords | ✅ Keyword + bounded native semantic | Cursor, cost provenance, entity graph, and declared operator snapshot path; no local index yet |
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
CROSSREF_EMAIL=your@email.com      # Optional override; defaults to server/NCBI email
UNPAYWALL_EMAIL=your@email.com     # Optional override; defaults to server/NCBI email
S2_API_KEY=your_s2_api_key         # Alias: SEMANTIC_SCHOLAR_API_KEY
OPENALEX_API_KEY=your_openalex_key # Raises the OpenAlex credit budget; actual grant is response-driven
PUBMED_SEARCH_DISABLED_SOURCES=    # Example: semantic_scholar

# Optional - Network settings
HTTP_PROXY=http://proxy:8080       # HTTP proxy for API requests
HTTPS_PROXY=https://proxy:8080     # HTTPS proxy for API requests

# Optional - Institutional fulltext access
INSTITUTIONAL_DIRECT_FETCH=true    # Try DOI publisher pages before CORE fallback
EZPROXY_ENABLED=false              # Enable only after configuring EZPROXY_HOST + cookie
EZPROXY_HOST=ezproxy.example.edu
EZPROXY_COOKIE_FILE=/path/to/cookies.json

# Optional - Local note export
PUBMED_NOTES_DIR=/path/to/wiki/references  # save_literature_notes target folder
PUBMED_WORKSPACE_DIR=/path/to/project       # fallback: references/ under this workspace
PUBMED_DATA_DIR=~/.pubmed-search-mcp        # fallback: references/ under this data dir
```

CrossRef and Unpaywall reuse the runtime server contact email (`NCBI_EMAIL`,
CLI `--email`, or detected git email) unless a source-specific email is
configured. OpenAlex accepts casual anonymous use and an optional API key; the
broker reads its response credit/rate metadata instead of assuming a permanent
"polite pool" quota.

Local note export resolves directories in this order: `output_dir` argument, `PUBMED_NOTES_DIR`, `PUBMED_WORKSPACE_DIR/references`, `PUBMED_DATA_DIR/references`, then `~/.pubmed-search-mcp/references`.
This path/template selection applies only to trusted local mode. Authenticated
service notes always use a built-in format below the current tenant's isolated
`references/` directory.
For LLM wiki compatibility, `wiki` and `foam` exports use stable link targets based on PMID, DOI, PMCID, or fallback identifiers; titles remain aliases/display labels, and the response includes `wiki_validation` for unresolved wikilink checks.

## 🔄 How It Works: The Middleware Architecture

```text
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

If you want to understand the tool surface as a usable system, do not start by memorizing 45 tool names.

Start with the [Tools Usage Guide](#/tools-usage-guide): it compresses the current 45 tools into 8 capability families, explains the theoretical lower bound, and gives intent-based routing for both humans and agents.

### 🔍 Search & Query Intelligence

![Search and query intelligence workflow](images/search-query-workflow.svg)

```text
┌─────────────────────────────────────────────────────────────────┐
│                      SEARCH ENTRY POINT                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   unified_search()          ← 🌟 Single entry for all sources    │
│        │                                                         │
│        ├── Quick search     → Direct multi-source query          │
│        ├── Native semantic → Bounded OpenAlex semantic mode    │
│        ├── Systematic       → Bounded provider bulk/cursor mode  │
│        ├── PICO hints       → Detects comparison, shows P/I/C/O  │
│        └── ICD expansion    → Auto ICD→MeSH conversion           │
│                                                                  │
│   Sources: PubMed · Europe PMC · CORE · OpenAlex · S2            │
│   Auto: Deduplicate → Rank → Enrich full-text links              │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│   QUERY INTELLIGENCE                                             │
│                                                                  │
│   generate_search_queries() → MeSH expansion + synonym discovery │
│   parse_pico()              → Agent-provided PICO handoff        │
│   analyze_search_query()    → Query analysis without execution   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### One search entry, three retrieval policies

Generic literature discovery is intentionally exposed through exactly one MCP
tool: `unified_search`. Provider-specific APIs remain internal broker
capabilities:

```python
# Default relevance/keyword routing across enabled sources
unified_search(query="treatment resistance")

# OpenAlex native semantic search (provider maximum 50 results)
unified_search(
    query="mechanisms of treatment resistance",
    sources="openalex",
    options="native_semantic",
)

# Deterministic/bounded retrieval: OpenAlex cursor and S2 bulk where selected
unified_search(
    query="melanoma AND immunotherapy",
    sources="pubmed,openalex,semantic_scholar",
    options="systematic",
)
```

`native_semantic` and `systematic` are mutually exclusive and disable the
multi-strategy deep-search expansion. Explicit source selections fail before a
network call when a requested retrieval mode is unsupported; automatic source
selection retains only capable providers. `limit` remains at most 100 per
source, so `systematic` means deterministic, bounded provider execution—not an
exhaustive systematic-review guarantee. Structured output and artifacts record
`retrieval_mode` plus per-source `source_metadata` (requested/provider mode,
canonical or compiled query, continuation availability, cost/rate metadata,
and warnings when available).

The public request boundary is fail-closed. `limit` must be an integer from 1
through 100; unknown or malformed `filters` / `options`, reversed or out-of-range
years, and unsupported ranking or output modes return a validation error before
provider I/O. In the default deep-search policy, `limit` is one **total budget
per source** divided across that source's query strategies—not `limit` results
for every strategy. Strategy calls use bounded global/per-source concurrency
and timeouts, and successful sources remain usable when another source times
out, is rate-limited, or fails.

Europe PMC, Scopus, and Web of Science remain keyword-only in this release;
explicit systematic requests for those sources fail before I/O instead of
mislabeling a single page as systematic coverage.

See [Source Contracts](#/source-contracts),
[Semantic Scholar](#/semantic-scholar-api), and
[OpenAlex](#/openalex-api) for provider limits and operator data-plane
boundaries.

### 🔬 Discovery Tools (After Finding Key Papers)

![Article discovery and citation workflow](images/discovery-citation-workflow.svg)

```text
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

### 📚 Full Text, Figure Extraction & Export

![Full text, figures, and biomedical image workflow](images/visual-evidence-workflow.svg)

| Category | Tools |
| -------- | ----- |
| **Full Text** | `get_fulltext` → Europe PMC XML when a PMCID is available; DOI-backed Unpaywall, institutional direct/EZproxy, CORE, and downloader fallbacks when needed |
| **Figures** | `get_article_figures` → Extract figure labels, captions, image URLs, and PDF links from PMC Open Access articles |
| **Figure-aware Full Text** | `get_fulltext(include_figures=True)` → Embed figure metadata alongside structured fulltext |
| **Text Mining** | `get_text_mined_terms` → Extract genes, diseases, chemicals |
| **Export** | `prepare_export` → official RIS/MEDLINE/CSL JSON or local RIS/BibTeX/CSV/MEDLINE/JSON; `save_literature_notes` → local wiki/Foam-compatible/Markdown/MedPaper-style notes plus collection-level CSL JSON |

### 🖼️ OA Figure-First Exploration

Use the PMC Open Access path when an agent needs evidence figures, not just article text:

- `get_article_figures(identifier="PMC12086443")` → Figure labels, captions, image URLs, and PDF/article links
- `get_fulltext(pmcid="PMC7096777", include_figures=True)` → Structured fulltext with figures inline
- Figure output preserves article context, so agents can connect each figure back to the sections where it is mentioned

### 🧬 NCBI Extended Databases

![NCBI extended biomedical data workflow](images/ncbi-extended-workflow.svg)

| Tool | Description |
| ---- | ----------- |
| `search_gene` | Search NCBI Gene database |
| `get_gene_details` | Gene details by NCBI Gene ID |
| `get_gene_literature` | PubMed articles linked to a gene |
| `search_compound` | Search PubChem compounds |
| `get_compound_details` | Compound details by PubChem CID |
| `get_compound_literature` | PubMed articles linked to a compound |
| `search_clinvar` | Search ClinVar clinical variants |

### 🕰️ Research Chronicle & Lineage Tree

![Research Chronicle Architecture and Lineage Flow](images/research-chronicle-lineage-flow.svg)
![Evaluation and timeline workflow](images/timeline-evaluation-workflow.svg)

| Tool | Description |
| ---- | ----------- |
| `build_research_chronicle` | Build a persisted, versioned chronicle with landmark detection. Output: summary, chronicle_map, timeline, tree, graph, evidence, milestones, mermaid, timeline_mermaid, mindmap, narrative, json |
| `read_research_chronicle` | Load, list, diff revisions, narrate with citations, analyze milestone distribution, or compare up to five topics |

```python
# 1. Build from topic (retrieves PubMed, scores landmarks, clusters lineages)
build_research_chronicle(topic="remimazolam intraoperative", output="mermaid", max_events=30)

# 2. Continue an existing chronicle (inherits stored topic and filters to produce Revision N+1)
build_research_chronicle(chronicle_id="remimazolam-intraoperative-08c229f3")

# 3. Read revision diff, milestone analytics, or cross-topic comparison
read_research_chronicle(action="diff", chronicle_id="remimazolam-intraoperative-08c229f3", from_revision=1)
read_research_chronicle(action="milestones", chronicle_id="remimazolam-intraoperative-08c229f3")
read_research_chronicle(action="compare", topics="remimazolam intraoperative,propofol intraoperative")
```

`mermaid` is the canonical combined view: a horizontal year spine (X-axis) with each
observed research line (Y-axis) branching at its earliest dated paper **within the
retrieved scope**. This is an explainable grouping, not a causal genealogy or a
claim about the field's true first paper. Lineages prefer MeSH descriptors and
author keywords shared by multiple papers; singleton-only or insufficient
signals trigger a warned research-stage fallback. Same-year display order is
stable, but does not assert precedence when publication precision cannot prove
it. `timeline_mermaid` preserves the older flat timeline view. See
[Advanced Research Workflows (docs/ADVANCED_RESEARCH_WORKFLOWS.md)](#/advanced-workflows) and
[docs/RESEARCH_CHRONICLE_REFACTOR_SPEC.md](#/research-chronicle-rebuild-spec).

Chronicle Mermaid output is built from structured nodes and edges, with safe
label escaping, cycle/orphan repair, collision-resistant IDs, and bounded graph
size. It falls back from rich to safe to minimal syntax instead of failing the
whole chronicle. `mermaid_validation.json` records every correction, fallback,
and omitted visual item; `chronicle.mmd` remains pure Mermaid source.

Chronicle revisions are immutable and appended atomically. When session
artifact persistence is enabled, artifact failure is surfaced explicitly while
the saved Chronicle revision remains available.

Topic builds send year limits to PubMed before bounded retrieval, then preserve
the first and last observed papers while filling the cap with landmarks and
temporal spread. The audit records PubMed `returned` / `available` counts and
warns when availability is unknown or any retrieval/selection cap makes the
view non-exhaustive. PubMed errors or a scope with no article evidence do not
publish an empty revision.

Explicit PMID input is strict (`12345678` or `PMID:12345678`, positive ASCII
digits, at most 20 digits); DOI or mixed text is rejected instead of being
coerced. Records without a reliable publication date appear as `Undated` after
dated entries and are excluded from the displayed year span. Entry IDs follow PMID/DOI evidence
identity across date or classifier corrections, and topic continuity uses one
Unicode/case/whitespace canonical key. Multi-signal papers keep one primary
branch plus explicit cross-links; overlap of 20% or more is audited as a
warning. In revision diffs, absence means `not_observed_in_revision` /
`removed_from_view`, never conclusive retirement.

### 🏥 Institutional Access & ICD Conversion

![Institutional access workflow](images/institutional-access-workflow.svg)

| Tool | Description |
| ---- | ----------- |
| `configure_institutional_access` | Configure institution's link resolver |
| `get_institutional_link` | Generate OpenURL access link |
| `list_resolver_presets` | List resolver presets |
| `test_institutional_access` | Test resolver configuration |
| `diagnose_institutional_access` | Diagnose direct DOI, EZproxy, and OpenURL handoff paths |
| `convert_icd_mesh` | Convert between ICD codes and MeSH terms (bidirectional) |
| `unified_search` | Auto-detect ICD codes in queries and expand them to MeSH |

### 💾 Session Management

![Session and pipeline workflow](images/session-pipeline-workflow.svg)

| Tool | Description |
| ---- | ----------- |
| `get_session_pmids` | Retrieve cached PMID lists |
| `get_cached_article` | Get article from session cache (no API cost) |
| `get_session_summary` | Session status overview |
| `read_session` | Facade for PMIDs, cached articles, durable search runs, replay arguments, history, and persistent artifacts |

Dynamic MCP resources are also available for agents that can read resources directly:

- `session://context` — active session status
- `session://last-search` — latest search metadata
- `session://last-search/pmids` — latest PMID list + CSV form
- `session://last-search/results` — cached article payloads for the latest search

### Persistent Artifacts

Persistent MCP output artifacts are saved for reusable `unified_search` and
`get_fulltext` responses when session persistence is configured. Tool responses
act like index cards: they include enough counts, source warnings, and artifact
hints for an agent to answer immediately, while the full evidence payload stays
in files that can be read repeatedly. The compact `artifact` locator includes
`artifact_id`, `artifact_uri`, `primary_file`, `summary`, file inventory,
`read_order`, audit status, and exact `read_session(...)` retrieval hints. Set
`PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS=true` only when a local MCP client should
also receive `local_path` and `manifest_path` directly.

Remote clients that cannot read the server filesystem can retrieve the same
content through the session facade:

```text
read_session(action="list_artifacts")
read_session(action="artifact", artifact_id="...")
read_session(action="artifact", artifact_uri="artifact://...")
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="audit.json")
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="query_strategy.json")
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="results.json", offset=0, max_chars=200000)
read_session(action="list_artifacts", include_local_paths=true)
```

### Recoverable search runs

When session management is active, every `unified_search` invocation receives a
stable run ID. This includes normal searches, validation/planning failures, and
inline, `saved:<name>`, or `dry_run=true` pipeline execution. Structured results
and errors attach the `search_run` handoff; Markdown returns the same run ID as
a compact recovery note. Normal literature-result envelopes expose two separate
machine contracts:

- `search_status` describes the bounded retrieval outcome: `state`
  (`completed`, `empty`, `partial`, or `failed`), `bounded=true`,
  `exhaustive=false`, returned count, attempted/successful/failed/retryable
  sources, and continuation/unknown-completeness source lists.
- `search_run` is the recovery handoff: stable `run_id`, journal status,
  `recoverable`, exact `read_session` inspect/replay arguments, and the artifact
  URI when one was committed.

The tenant-scoped `search-run/v1` journal is published before provider I/O or a
terminal validation response and records the sanitized request, plan,
physical per-source or per-pipeline-step attempts, counts, safe failures,
result references, and artifact locator when applicable. It reaches a terminal
`completed`, `partial`, `failed`, or `cancelled` state; a valid zero-result
search is a `completed` run whose `search_status.state` is `empty`. On restart,
an unfinished `started` / `planned` / `running` entry is recovered once as
`interrupted` instead of disappearing. A non-dry-run saved pipeline additionally
keeps its PipelineStore report/run history; that is complementary to the
invocation-level search journal, not a replacement for it.

Pipeline replay preserves the original inline or `saved:<name>` argument plus
`dry_run` / `stop_at`. Pipeline text containing keys, tokens, cookies, passwords,
or other credential material is rejected and recorded as a failed run; provider
credentials belong in server environment/configuration, never pipeline YAML or
JSON.

```text
read_session(action="search_runs")
read_session(action="search_runs", run_status="partial")
read_session(action="search_run", run_id="...")
read_session(action="replay_search", run_id="...")
```

`replay_search` only returns the original credential-free `unified_search`
kwargs. It never executes a network call automatically; the agent or user must
review and explicitly submit them. Provider cursor/token values are retained
as opaque provenance in `source_metadata` and `query_strategy.json`, but there
is no public cursor-resume parameter yet, so replay starts a new bounded search.

If the terminal journal write cannot be recovered, the response reports
`search_run.status="history_unavailable"`, `history_available=false`, the
intended terminal status, and a warning. It deliberately omits inspect/replay
actions because durable recovery is not guaranteed; the search result itself
may still be usable.

`unified_search` artifacts use a research envelope. Start with `audit.json` for
source-count and completeness warnings, then `query_strategy.json` for the exact
executed plan, and finally `results.json` / `results.toon` for the complete
article list. This keeps MCP response tokens small without losing academic
traceability.

Artifacts are generated from the already-computed result object, so reading an
artifact does not rerun searches or fulltext retrieval.
If a crash occurs after an artifact directory is atomically published but
before the session index is updated, session reload discovers only complete,
checksum-indexed manifests and relinks the orphaned artifact to its search run
by `search_run_id` (with a conservative query match for older artifacts).
`read_session` redacts local filesystem paths by default; `local_path` and
`manifest_path` are server-local paths, not portable client paths. Artifacts
from `get_fulltext` may contain article body text, including subscription or
institutionally accessed content. Store and share them according to publisher,
license, and institutional access terms.
Large `get_fulltext` responses are returned inline as a preview when an artifact
is available; use the artifact locator to retrieve the saved full content.

When one source fails but the overall search can continue, JSON responses may
include `source_errors`; markdown responses show a `Source warnings` line. For
Semantic Scholar HTTP 429s, set `S2_API_KEY` / `SEMANTIC_SCHOLAR_API_KEY`, retry
later, or temporarily exclude it with `sources="auto,-semantic_scholar"` or
`PUBMED_SEARCH_DISABLED_SOURCES=semantic_scholar`.

### Pipeline Management

![Session and pipeline workflow](images/session-pipeline-workflow.svg)

`manage_pipeline` is the primary facade for pipeline CRUD, history, and scheduling. The more specific pipeline tools remain available as compatibility wrappers.

| Tool | Description |
| ---- | ----------- |
| `manage_pipeline` | Primary facade for save, list, load, delete, history, and schedule actions |
| `save_pipeline` | Save a pipeline config for later reuse (YAML/JSON, auto-validated) |
| `list_pipelines` | List saved pipelines (filter by tag/scope) |
| `load_pipeline` | Load by saved name; trusted local callers may also load a file |
| `delete_pipeline` | Delete pipeline and its execution history |
| `get_pipeline_history` | View execution history with article diff analysis |
| `schedule_pipeline` | Create, update, or remove recurring pipeline schedules |

Authenticated service callers use named pipelines in their tenant-derived
store; `workspace` and `file:` access are local-only. The service Compose
profile does not execute schedules without a separately designed single leader.

Step-by-step tutorials:

- English: [docs/PIPELINE_MODE_TUTORIAL.en.md](#/pipeline-tutorial)
- 繁體中文: [docs/PIPELINE_MODE_TUTORIAL.md](#/pipeline-tutorial-zh)

### 👁️ Vision & Image Search

![Full text, figures, and biomedical image workflow](images/visual-evidence-workflow.svg)

| Tool | Description |
| ---- | ----------- |
| `analyze_figure_for_search` | Handoff an uploaded image, image URL, or data URI to agent vision for search-term extraction |
| `search_biomedical_images` | Search biomedical images across Open-i (X-ray, microscopy, photos, diagrams) |

Use `analyze_figure_for_search` when the user supplies an image and the agent
must interpret its meaning first. The tool returns MCP `ImageContent` plus
instructions for the LLM agent to extract English biomedical terms, then
continue with `search_biomedical_images` for similar Open-i images or
`unified_search` for related papers.

### 📄 Preprint Search

Search **arXiv**, **medRxiv**, and **bioRxiv** preprint servers via `unified_search` `options` flags:

- `preprints`: Search preprint servers and merge preprints into the main aggregated result set with `article_type=PREPRINT`.
- `all_types`: Keep non-peer-reviewed content already returned by selected scholarly sources even without a preprint-server crawl.

**Recommended combinations:**

- Empty `options`: Peer-reviewed results only; preprint-like records are filtered.
- `options="preprints"`: Searches arXiv, medRxiv, and bioRxiv, then ranks/dedupes those preprints with the main results.
- `options="preprints, all_types"`: Same preprint-server crawl, plus other non-peer-reviewed records from selected sources are retained.
- `options="all_types"`: No preprint-server crawl, but non-peer-reviewed items from searched sources are retained.

**Preprint detection** — articles are identified as preprints by:

- Article type from source API (OpenAlex, CrossRef, Semantic Scholar)
- arXiv ID present without PubMed ID
- Known preprint server source or journal name
- DOI prefix matching preprint servers (e.g., `10.1101/` → bioRxiv/medRxiv, `10.48550/` → arXiv)

### 🌳 Research Context Graph

`unified_search` can append a lightweight research lineage view built from PMID-backed ranked results:

| Option Flag | Description |
| ----------- | ----------- |
| `context_graph` | Append a lightweight Research Context Graph preview from the current PMID-backed ranked set to Markdown output and include `research_context` in JSON output |

This is useful when an agent needs quick thematic branching without making a second `build_research_chronicle` call.

### 🧪 Clinical-Trial Registry Adjunct

ClinicalTrials.gov is never queried implicitly. Add `options="trials"` to a
Markdown search when a bounded registry adjunct is useful. It remains separate
from the literature-source plan and source counts; the durable artifact records
its truncated physical query and outcome under `adjunct_queries`. Structured
JSON/TOON searches do not run this display-only adjunct.

```python
unified_search(query="remimazolam ICU sedation", options="trials")
```

### 📊 Count-First Orientation

`unified_search` can also front-load the existing source coverage and decision hints for agents that want routing help before reading the ranked list:

| Option Flag | Description |
| ----------- | ----------- |
| `counts_first` | Add a source-count table, coverage summary, and next-tool recommendations to the response |

Example:

```python
unified_search(query="remimazolam ICU sedation", options="counts_first")
```

This mode is useful when the agent should decide whether to expand a source, inspect the lead PMID, fetch fulltext, extract figures, or pivot into timeline exploration.

### ⏱️ MCP Progress Reporting

When the MCP client provides a progress token, `unified_search`, `build_research_chronicle`, `get_fulltext`, and `get_text_mined_terms` emit progress updates for their major phases.
This reduces the "black box" wait time for agents during longer searches.
Progress callbacks are best-effort and are not cancelled by the server while a
tool call is active, which avoids host-side `Canceled: Canceled` messages caused
by progress-notification backpressure.

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

![PICO clinical search workflow](images/pico-clinical-workflow.svg)

**Simple path** — `unified_search` can search directly (no PICO decomposition):

```python
# unified_search searches as-is; detects "A vs B" pattern and shows PICO hints in metadata
unified_search(query="Is remimazolam better than propofol for ICU sedation?")
# → Multi-source keyword search + PICO hint metadata in output
# ⚠️ This does NOT auto-decompose PICO or expand MeSH!
# For structured PICO search, use the Agent workflow below
```

**Agent workflow** — agent-provided PICO + backend pipeline search (recommended for clinical questions):

```text
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
# Step 1: Agent extracts P/I/C/O, then validates the structured handoff
pico = parse_pico(
    description="Is remimazolam better than propofol for ICU sedation?",
    p="ICU patients requiring sedation",
    i="remimazolam",
    c="propofol",
    o="sedation efficacy, delirium, hypotension"
)
# Returns validation plus a ready-to-run `template: pico` pipeline.

# Step 2: Get MeSH for each element (parallel!)
generate_search_queries(topic="ICU patients")   # P
generate_search_queries(topic="remimazolam")    # I
generate_search_queries(topic="propofol")       # C
generate_search_queries(topic="sedation")       # O

# Step 3: Either pass expanded fragments back as p_query/i_query/c_query/o_query
# or let the backend pipeline use the structured P/I/C/O labels.

# Step 4: Search (backend runs O-aware precision/recall searches, dedup, rank)
unified_search(
    query="Is remimazolam better than propofol for ICU sedation?",
    pipeline=pico["pipeline"]
)
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
prepare_export(pmids="last", format="bibtex", source="local")  # → LaTeX
prepare_export(pmids="last", format="csl")      # → CSL JSON from the official NCBI Citation API
save_literature_notes(pmids="last")              # → local wiki note + Foam-compatible wikilinks + CSL JSON
save_literature_notes(pmids="last", note_format="medpaper", output_dir="./references")
save_literature_notes(pmids="last", template_file="./reference-template.md")

# Retrieve full text for a selected paper from the last search
get_fulltext(pmid="12345678", extended_sources=True)
```

### 6️⃣ Preprint Search

```python
# Include preprints alongside peer-reviewed results
unified_search(query="COVID-19 vaccine efficacy", options="preprints")
# → Main aggregated results include labelled arXiv, medRxiv, and bioRxiv preprints

# Include preprints and retain non-peer-reviewed items in main results
unified_search(query="CRISPR gene therapy", options="preprints, all_types")
# → Preprint-server crawl + non-peer-reviewed items retained in main results

# Only peer-reviewed (default behavior)
unified_search("diabetes treatment")
# → Preprints from any source automatically filtered out

# Add a research context graph preview to the same search response
unified_search("remimazolam ICU sedation", options="context_graph")
```

### 7️⃣ Pipeline (Reusable Search Plans)

```python
# Save a template-based pipeline through the primary facade
manage_pipeline(
  action="save",
    name="icu_sedation_weekly",
    config="template: pico\nparams:\n  P: ICU patients\n  I: remimazolam\n  C: propofol\n  O: delirium",
    tags="anesthesia,sedation",
    description="Weekly ICU sedation monitoring"
)

# Save a custom DAG pipeline
manage_pipeline(
  action="save",
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
manage_pipeline(action="list", tag="anesthesia")
manage_pipeline(action="load", source="brca1_comprehensive")  # Review YAML
manage_pipeline(action="history", name="icu_sedation_weekly")  # View past runs
```

---

## 🔍 Search Mode Comparison

```text
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
│         │   └── Agent P/I/C/O → parse_pico() handoff                  │
│         │       → unified_search(template:pico) or expanded Boolean    │
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
| ---- | ----------- | -------- | ------------- |
| **Quick** | `unified_search()` | Fast topic search | ICD→MeSH, multi-source, dedup |
| **PICO** | Agent P/I/C/O -> `parse_pico()` | Clinical questions | Validate handoff -> `template:pico` backend search |
| **Systematic** | `generate_search_queries()` → `unified_search(options="systematic")` | Reproducible review seed | MeSH/synonyms plus bounded bulk/cursor execution; not an exhaustiveness claim |
| **Native semantic** | `unified_search(options="native_semantic")` | Conceptual similarity in title/abstract space | Capability validation; OpenAlex semantic mode, max 50 |
| **Exploration** | `find_*_articles()` | From key paper | Citation network, related |

---

## 🤖 Claude Skills (AI Agent Workflows)

Pre-built workflow guides in `.claude/skills/`, divided into **Usage Skills** (for using the MCP server) and **Development Skills** (for maintaining the project):

### 📚 Usage Skills (11) — For AI Agents Using This MCP Server

| Skill | Description |
| ----- | ----------- |
| `pubmed-quick-search` | Basic search with filters |
| `pubmed-systematic-search` | MeSH expansion, comprehensive |
| `pubmed-pico-search` | Clinical question decomposition |
| `pubmed-paper-exploration` | Citation tree, related articles |
| `pubmed-research-chronicle` | Persistent, versioned research evolution |
| `pubmed-gene-drug-research` | Gene/PubChem/ClinVar |
| `pubmed-fulltext-access` | Europe PMC, CORE full text |
| `pubmed-export-citations` | RIS/BibTeX/CSV/CSL export guidance |
| `pubmed-multi-source-search` | Cross-database unified search |
| `pubmed-mcp-tools-reference` | Complete tool reference guide |
| `pipeline-persistence` | Save, load, reuse search plans |

### 🔧 Development Skills (15) — For Project Contributors

| Skill | Description |
| ----- | ----------- |
| `changelog-updater` | Auto-update CHANGELOG.md |
| `code-refactor` | DDD architecture refactoring |
| `code-reviewer` | Code quality & security review |
| `ddd-architect` | DDD scaffold for new features |
| `git-doc-updater` | Sync docs before commits |
| `git-precommit` | Pre-commit workflow orchestration |
| `memory-checkpoint` | Save context to Memory Bank |
| `memory-updater` | Update Memory Bank files |
| `pdf-asset-extractor` | Extract and inventory citation-ready PDF assets |
| `project-init` | Initialize new projects |
| `readme-i18n` | Multilingual README sync |
| `readme-updater` | Sync README with code changes |
| `roadmap-updater` | Update ROADMAP.md status |
| `test-generator` | Generate test suites |
| `tool-sync` | Keep the MCP registry and generated tool documentation aligned |

> 📁 **Location**: `.claude/skills/*/SKILL.md` (Claude Code-specific, and the single source of truth for repo skills)
> Do not mirror or split repo skills into `.github/skills/`.
> These repo skills are project-scoped and should remain version-controlled. Personal cross-project skills belong in a user directory such as `~/.copilot/skills/` or `~/.claude/skills/`, not in this repository.

---

## 🏗️ Architecture (DDD)

This project uses **Domain-Driven Design (DDD)** architecture, with literature research domain knowledge as the core model.

```text
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
│   └── api/                    # Auxiliary HTTP API routes (not pubmed_search.api)
└── shared/                     # Cross-cutting concerns
    ├── exceptions.py           # Unified error handling
    └── async_utils.py          # Rate limiter, retry, circuit breaker
```

### Internal Mechanisms (Transparent to Agent)

| Mechanism | Description |
| --------- | ----------- |
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
| -------------- | ----------------- | --------------- |
| **PubMed / NCBI** | MeSH (Medical Subject Headings) | ✅ Full support via `expand_with_mesh()` |
| **ICD Codes** | ICD-10-CM / ICD-9-CM | ✅ Auto-detect & convert to MeSH |
| **Europe PMC** | Text-mined entities (Gene, Disease, Chemical) | ✅ `get_text_mined_terms()` extraction |
| **OpenAlex** | Topics / keywords (model-inferred) | ✅ Broker keyword mode; bounded native semantic mode when selected |
| **Semantic Scholar** | S2 fields / bulk query syntax | ✅ Broker chooses relevance or bounded bulk mode; provider annotations keep provenance |
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

> 📖 **Full architecture documentation**: [ARCHITECTURE.md](#/architecture)

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

## 🔒 Local HTTPS Demo and Service Deployment

The bundled self-signed certificates and `curl -k` flow are a **local TLS demo**,
not a production security profile. For a shared service, use the authenticated
service Compose file and a trusted certificate as described in
[DEPLOYMENT.md](#/deployment).

### Local HTTPS Smoke Test

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
| ------- | --- | ----------- |
| MCP | `https://localhost/mcp` | Streamable HTTP MCP endpoint |
| Health | `https://localhost/health` | Health check |
| Ready | `https://localhost/ready` | Readiness check |
| Info | `https://localhost/info` | Runtime transport and endpoint metadata |
| Exports | `https://localhost/exports` | Local prepared export listing; service mode requires bearer auth and tenant scope |

### Remote MCP Client Configuration

```json
{
  "mcpServers": {
    "pubmed-search": {
      "url": "https://localhost/mcp"
    }
  }
}
```

---

## 🏢 Microsoft Copilot Studio Integration

Integrate PubMed Search MCP with **Microsoft 365 Copilot** (Word, Teams, Outlook)!

### Quick Start

```bash
# Unpublished local schema/protocol smoke only; never tunnel local mode
pubmed-search-mcp-http --mode local --transport streamable-http \
  --copilot-compatible --host 127.0.0.1 --port 8765

# Public Copilot endpoint: authenticated service mode is mandatory
export PUBMED_AUTH_TOKENS="copilot:$(openssl rand -hex 32)"
export NGROK_DOMAIN="your-assigned-domain.ngrok.dev"
./scripts/start-copilot-studio.sh --with-ngrok
```

### Copilot Studio Configuration

| Field | Value |
| ----- | ----- |
| **Server name** | `PubMed Search` |
| **Server URL** | `https://your-server.com/mcp` |
| **Authentication** | Bearer token for service mode; `None` only for an unpublished local demo |

> 📖 **Full documentation**: [copilot-studio/README.md](https://github.com/u9401066/pubmed-search-mcp/blob/master/copilot-studio/README.md)
>
> Use `pubmed-search-mcp-http --copilot-compatible` for packaged Copilot HTTP semantics. `run_server.py` remains a source-tree development wrapper; use `run_copilot.py` only for loopback-only 12-tool primitive-schema smoke tests. That simplified surface still calls the shared runner through `unified_search(query, limit, min_year, max_year, sources, options)` and exposes primitive-schema `read_session` for search-run, replay-argument, and artifact recovery; it does not expose a PubMed-only generic-search alias. The tunnel script requires an assigned `NGROK_DOMAIN`, refuses occupied backend ports, and publishes only after `--mode service` passes readiness and unauthenticated-rejection checks.
>
> ⚠️ **Note**: SSE transport deprecated since Aug 2025. Use `streamable-http`.

---

> 📖 **More documentation**:
>
> - Architecture → [ARCHITECTURE.md](#/architecture)
> - Pipeline tutorial (English) → [docs/PIPELINE_MODE_TUTORIAL.en.md](#/pipeline-tutorial)
> - Pipeline tutorial (zh-TW) → [docs/PIPELINE_MODE_TUTORIAL.md](#/pipeline-tutorial-zh)
> - Deployment guide → [DEPLOYMENT.md](#/deployment)
> - Copilot Studio → [copilot-studio/README.md](https://github.com/u9401066/pubmed-search-mcp/blob/master/copilot-studio/README.md)

---

## 🔐 Security

### Security Features

| Layer | Feature | Description |
| ----- | ------- | ----------- |
| **HTTPS** | TLS termination | Required for remote credentials; the bundled self-signed profile is local-only |
| **Bearer authentication** | Stable principal | Mandatory in service mode and used for tenant authorization |
| **Tenant storage** | Filesystem isolation | Sessions, artifacts, exports, chronicles, and pipelines are stored below the authenticated principal |
| **Fairness and rate policy** | Tenant concurrency + shared upstream budgets | Prevents one caller from multiplying an upstream API allowance |
| **Security headers** | Clickjacking/MIME hardening | Reverse-proxy headers complement authentication; they are not CSRF authorization |
| **Secret handling** | Runtime secret injection | API keys and bearer tokens must come from deployment secrets/environment and must not be committed or logged |

See [DEPLOYMENT.md](#/deployment) for detailed deployment instructions.

---

## 📤 Export Formats

![Export and local notes workflow](images/export-notes-workflow.svg)

Export your search results in formats compatible with major reference managers:

| Format | Source | Compatible With | Use Case |
| ------ | ------ | --------------- | -------- |
| **RIS** | official or local | EndNote, Zotero, Mendeley | Universal import |
| **MEDLINE** | official or local | PubMed tools | Native PubMed-style archiving |
| **CSL JSON** | official | Citation processors | Programmatic citation styling |
| **BibTeX** | local | LaTeX, Overleaf, JabRef | Academic writing |
| **CSV** | local | Excel, Google Sheets | Data analysis |
| **JSON** | local | Programmatic access | Custom processing |

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

## 📚 Citation

GitHub will show **Cite this repository** from [CITATION.cff](https://github.com/u9401066/pubmed-search-mcp/blob/master/CITATION.cff). If you use PubMed Search MCP in research, methods sections, or internal technical reports, prefer the GitHub-generated citation or reuse the repository metadata directly.

```bibtex
@software{pubmed_search_mcp,
  title = {PubMed Search MCP},
  author = {u9401066},
  url = {https://github.com/u9401066/pubmed-search-mcp}
}
```

---

## 📄 License

Apache License 2.0 - see [LICENSE](https://github.com/u9401066/pubmed-search-mcp/blob/master/LICENSE)

---

## 🔗 Links

- [GitHub Repository](https://github.com/u9401066/pubmed-search-mcp)
- [PyPI Package](https://pypi.org/project/pubmed-search-mcp/)
- [NCBI Entrez Programming Utilities](https://www.ncbi.nlm.nih.gov/books/NBK25497/)
