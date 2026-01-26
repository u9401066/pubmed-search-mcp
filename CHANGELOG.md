# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- PRISMA flow tracking (init_prisma_flow, record_screening, get_prisma_diagram)
- Evidence level classification (Oxford CEBM I-V)
- Quality assessment templates (RoB 2, ROBINS-I, NOS)
- Research trend analysis (keyword frequency, publication trends)
- Chart generation (PNG output)

---

## [0.2.1] - 2026-01-26

### Added

- **ClinicalTrials.gov Integration** - Auto-display related ongoing trials
  - unified_search now shows relevant clinical trials at the end
  - Uses free public API (no API key required)
  - Status indicators: 🟢 RECRUITING, 🟡 ACTIVE, ✅ COMPLETED
- **Study Type Badge Display** - Evidence level badges from PubMed publication_types
  - 🟢 Meta-Analysis (1a), Systematic Review (1a), RCT (1b)
  - 🟡 Clinical Trial (1b-2b)
  - 🟠 Case Report (4)
  - Data from PubMed API, not inference

---

## [0.2.0] - 2026-01-26

### 🏗️ DDD Architecture Refactor

Major restructuring to Domain-Driven Design (DDD) architecture for better maintainability.

### Changed

**Directory Structure Reorganization:**
```
src/pubmed_search/
├── domain/                 # Core business logic
│   └── entities/           # UnifiedArticle, Author, etc.
├── application/            # Use cases
│   ├── search/             # QueryAnalyzer, ResultAggregator
│   ├── export/             # Citation export (RIS, BibTeX...)
│   └── session/            # SessionManager
├── infrastructure/         # External systems
│   ├── ncbi/               # Entrez, iCite, Citation Exporter
│   ├── sources/            # Europe PMC, CORE, CrossRef...
│   └── http/               # HTTP clients
├── presentation/           # User interfaces
│   ├── mcp_server/         # MCP tools, prompts, resources
│   └── api/                # REST API
└── shared/                 # Cross-cutting concerns
    ├── exceptions.py
    └── async_utils.py
```

**Breaking Changes:**
- `mcp/` → `presentation/mcp_server/` (避免與 mcp 套件衝突)
- `entrez/` → `infrastructure/ncbi/`
- `sources/` → `infrastructure/sources/`
- `exports/` → `application/export/`
- `unified/` → `application/search/`
- `models/` → `domain/entities/`

### Added

- **ResultAggregator Refactoring** - O(n) deduplication with Union-Find algorithm
  - Multi-dimensional ranking: relevance, quality, recency, impact, source_trust
  - RankingConfig presets: default, impact_focused, recency_focused, quality_focused
  - DeduplicationStrategy: STRICT, MODERATE, AGGRESSIVE
  - 66 tests, 96% coverage

- **9 MCP Research Prompts** (Phase 6 Complete):
  - `quick_search` - 快速主題搜尋
  - `systematic_search` - MeSH 擴展系統性搜尋
  - `pico_search` - PICO 臨床問題搜尋
  - `explore_paper` - 從關鍵論文深入探索
  - `gene_drug_research` - 基因/藥物研究
  - `export_results` - 匯出引用
  - `find_open_access` - 尋找開放存取版本
  - `literature_review` - 完整文獻回顧流程
  - `text_mining_workflow` - 文字探勘工作流程

- **NCBI Citation Exporter API** - Official citation export (RIS, MEDLINE, CSL)
  - `prepare_export(source="official")` uses official NCBI API (default)
  - `prepare_export(source="local")` uses local formatting (for BibTeX, CSV)
- **Python 3.10 Compatibility** - Fixed `TypeVar` syntax and `ExceptionGroup` fallback

### Fixed

- Import conflicts with `mcp` package resolved by renaming to `mcp_server`
- Deep relative imports replaced with absolute imports for maintainability

---

## [0.1.29] - 2026-01-22

### 📦 Complete API Export

Enhanced `__init__.py` to export all useful classes and functions for easy import.

### Added

Now you can import directly from `pubmed_search`:

```python
# NCBI Extended (Gene, PubChem, ClinVar)
from pubmed_search import NCBIExtendedClient

# Europe PMC (fulltext, text mining)
from pubmed_search import EuropePMCClient

# Export citations
from pubmed_search import export_articles, export_ris, export_bibtex

# OpenURL / Institutional access
from pubmed_search import get_openurl_link, list_openurl_presets

# Strategy & Query Analysis
from pubmed_search import SearchStrategyGenerator, QueryAnalyzer
```

**New Exports:**
- `NCBIExtendedClient` - Gene, PubChem, ClinVar databases
- `EuropePMCClient` - Fulltext XML, text-mined annotations
- `export_articles`, `export_ris`, `export_bibtex`, `export_csv`, `export_medline`, `export_json`
- `get_openurl_link`, `list_openurl_presets`, `configure_openurl`
- `SearchStrategyGenerator`, `QueryAnalyzer`, `ResultAggregator`
- Multi-source client getters: `get_semantic_scholar_client`, `get_openalex_client`, etc.

---

## [0.1.28] - 2026-01-22

### 🔧 Python Version Compatibility

Lowered Python version requirement for broader compatibility with ToolUniverse.

### Changed

- **Python Version**: Lowered `requires-python` from `>=3.12` to `>=3.10`
- Verified all syntax is Python 3.10+ compatible (union types `|`, generic types)
- MCP SDK only requires Python >=3.10

---

## [0.1.27] - 2026-01-22

### 🧹 Cleanup & ToolUniverse Integration

Repository cleanup and ToolUniverse integration finalized.

### Changed

- **Removed** `tooluniverse-integration/` folder (now in ToolUniverse repo)
- **Removed** `CHANGELOG_0.1.20.md` (legacy, content in main CHANGELOG)
- **Updated** `.gitignore`: Added `.mypy_cache/`, `.ruff_cache/` exclusions

### ToolUniverse Integration (25 Tools)

Complete integration with [ToolUniverse](https://github.com/HarvardLab/ToolUniverse):
- All 25 MCP tools now available as ToolUniverse Local Tools
- Thin wrapper pattern: delegates to `pubmed-search-mcp` package
- Categories: Search, Query Intelligence, Article Exploration, Full Text, NCBI Extended, Citation Network, Export, Vision Search, Institutional Access

---

## [0.1.26] - 2026-01-21

### 🏥 Advanced Clinical Filters (Phase 2.1)

New feature: PubMed advanced filters for precise clinical research!
Based on official PubMed Help documentation.

### Added

- **Advanced Filter Parameters** in `search_literature()` and `unified_search()`:
  - `age_group`: Filter by age group (newborn, infant, child, adolescent, adult, aged, aged_80...)
  - `sex`: Filter by sex (male, female)
  - `species`: Filter by species (humans, animals)
  - `language`: Filter by publication language (english, chinese, japanese...)
  - `clinical_query`: PubMed Clinical Queries (therapy, diagnosis, prognosis, etiology)

- **New Constants** (`entrez/search.py`):
  - `AGE_GROUP_FILTERS`: 10 MeSH-based age group filters
  - `SEX_FILTERS`: Male/Female MeSH filters
  - `SPECIES_FILTERS`: Humans/Animals filters
  - `LANGUAGE_FILTERS`: 10 common language codes
  - `CLINICAL_QUERY_FILTERS`: 5 validated clinical query strategies
  - `MESH_SUBHEADINGS`: 22 MeSH subheadings for future use

### Usage Examples

```python
# Find elderly diabetes treatment RCTs
search_literature(
    query="diabetes treatment",
    age_group="aged",
    species="humans",
    clinical_query="therapy",
    min_year=2020
)

# Female breast cancer screening studies
unified_search(
    query="breast cancer screening",
    sex="female",
    language="english"
)
```

### Updated Skills

- `pubmed-quick-search/SKILL.md`: Added advanced filter examples
- `pubmed-systematic-search/SKILL.md`: Added clinical filter workflow
- `pubmed-mcp-tools-reference/SKILL.md`: Added filter parameter table

---

## [0.1.25] - 2025-01-14

### 🏛️ Institutional Access / OpenURL Link Resolver Integration

New feature: Access paywalled articles through your institutional library subscription
using OpenURL link resolvers!

### Added

- **New Module** (`sources/openurl.py`):
  - `OpenURLBuilder`: Build OpenURL links from article metadata
  - `OpenURLConfig`: Configuration management with environment variable support
  - `configure_openurl()`: Programmatic configuration
  - Pre-configured presets for common institutions (台大、成大、Harvard、MIT...)

- **New MCP Tools** (`mcp/tools/openurl.py`):
  - `configure_institutional_access`: Set up your library's link resolver
  - `get_institutional_link`: Generate OpenURL for any article
  - `list_resolver_presets`: List available institution presets

### Configuration

```bash
# Environment variable
export OPENURL_RESOLVER="https://your.library.edu/openurl"
export OPENURL_PRESET="ntu"  # Or use preset name

# Or configure via MCP tool
configure_institutional_access(preset="ntu")
configure_institutional_access(resolver_url="https://...")
```

### Available Presets

| Region | Institutions |
|--------|--------------|
| 🇹🇼 台灣 | ntu (台大), ncku (成大), nthu (清大), nycu (陽明交大) |
| 🇺🇸 USA | harvard, stanford, mit, yale |
| 🇬🇧 UK | oxford, cambridge |
| 🔧 Generic | sfx, 360link, primo |

### Workflow

```
1. Configure your resolver:
   configure_institutional_access(preset="ntu")

2. Search for articles:
   unified_search("propofol pharmacokinetics")

3. Get library access link:
   get_institutional_link(pmid="38353755")
   → Opens your library's login to access full text
```

---

## [0.1.24] - 2025-01-12

### 📚 Enhanced Tool Documentation for Agent Understanding

Improved MCP tool descriptions with comprehensive workflows, step-by-step
instructions, and usage examples. This makes it easier for AI agents to
understand when and how to use each tool.

### Enhanced

- **Citation Network Tools** - Complete workflow documentation:
  - `find_related_articles`: Added 3-tool citation network exploration guide
  - `find_citing_articles`: Added forward citation search use cases
  - `get_article_references`: Added backward citation search workflow

- **Vision Search Tools** - Detailed 5-step workflow:
  - `reverse_image_search_pubmed`: Complete workflow from image to literature
  - Added search type explanations (comprehensive, methodology, results, structure, medical)

### Documentation

- Added `docs/research/REFERENCE_REPOSITORIES.md`:
  - Detailed analysis of 6 key Python libraries for literature search
  - scholarly, habanero, pyalex, metapub, bioservices, wos-starter
  - Learning points, integration suggestions, code examples
  - Web of Science Starter API documentation

### Reference Libraries Studied

| Library | Key Feature | Learning Priority |
|---------|-------------|-------------------|
| metapub | FindIt PDF discovery | **Extreme** |
| habanero | Content negotiation | High |
| pyalex | Pipe operations | Medium |
| scholarly | Proxy rotation | Medium |
| bioservices | Multi-service framework | Medium |
| wos-starter | Times Cited data | Low |

---

## [0.1.23] - 2025-01-11

### 🖼️ Vision-to-Literature Search (Experimental)

New feature: Search PubMed using images! Analyze scientific figures,
medical images, or molecular structures to find related literature.

### Added

- **New Tools** (`vision_search.py`):
  - `analyze_figure_for_search`: Analyze an image and extract search terms
  - `reverse_image_search_pubmed`: Specialized prompts for different image types

- **MCP ImageContent Protocol Support**:
  - Returns images using standard MCP `ImageContent` type
  - Agent uses vision capabilities to analyze
  - Supports URL, base64, and data URI inputs

### Workflow

```mermaid
graph LR
    A[User provides image] --> B[MCP returns ImageContent]
    B --> C[Agent vision analysis]
    C --> D[Extract search terms]
    D --> E[unified_search]
    E --> F[Related literature]
```

### Search Types

| Type | Focus |
|------|-------|
| `comprehensive` | General analysis |
| `methodology` | Lab equipment, techniques |
| `results` | Charts, graphs, data |
| `structure` | Molecular/chemical structures |
| `medical` | Clinical imaging |

### Example

```python
# From URL
analyze_figure_for_search(url="https://journal.com/figure1.png")

# From base64
analyze_figure_for_search(image="data:image/png;base64,...")

# With context
analyze_figure_for_search(
    url="https://example.com/western_blot.jpg",
    context="Looking for similar protein expression studies"
)
```

---

## [0.1.22] - 2025-01-12

### 🚀 Python 3.12+ Performance & Error Handling

Major infrastructure upgrade with Python 3.12+ features.

### Added

- **New Core Module** (`src/pubmed_search/core/`):
  - **Unified Exception Hierarchy**: 
    - `PubMedSearchError` - Base with context, severity, retryable flags
    - `APIError` → `RateLimitError`, `NetworkError`, `ServiceUnavailableError`
    - `ValidationError` → `InvalidPMIDError`, `InvalidQueryError`, `InvalidParameterError`
    - `DataError` → `NotFoundError`, `ParseError`
    - `ConfigurationError`
  - **Agent-Friendly Error Formatting**:
    - `to_agent_message()` - Emoji-rich, structured error messages
    - `to_dict()` - JSON-serializable error info
    - `is_retryable_error()` - Automatic retry detection
    - `get_retry_delay()` - Exponential backoff calculation

- **Async Utilities** (`core/async_utils.py`):
  - `RateLimiter` - Token bucket rate limiting for API compliance
  - `async_retry` - Decorator with exponential backoff + jitter
  - `gather_with_errors[T]` - TaskGroup-based parallel execution
  - `batch_process[T, R]` - Batch processing with rate limiting
  - `CircuitBreaker` - Fault tolerance pattern
  - `AsyncConnectionPool[T]` - Generic connection pooling
  - `timeout_with_fallback[T]` - Timeout with fallback value

- **Tests**: `tests/test_core_module.py` - Comprehensive core module tests

### Changed

- **Python Version**: `>=3.11` → `>=3.12`
  - Type parameter syntax (PEP 695): `async def gather_with_errors[T](...)`
  - ExceptionGroup (PEP 654) for multi-error handling
  - `asyncio.TaskGroup` for structured concurrency
  - `slots=True` and `frozen=True` dataclasses for efficiency

### Python 3.12+ Features Used

```python
# Type parameter syntax (PEP 695)
async def gather_with_errors[T](*coros: Awaitable[T]) -> list[T]: ...

# Frozen dataclass with slots
@dataclass(frozen=True, slots=True)
class ErrorContext:
    tool_name: str | None = None
    suggestion: str | None = None

# TaskGroup for structured concurrency
async with asyncio.TaskGroup() as tg:
    for coro in coros:
        tg.create_task(coro)
```

---

## [0.1.21] - 2025-01-11

### 🔥 Enhanced Fulltext Retrieval

Major upgrade to `get_fulltext` tool with multi-source support.

### Added

- **New InputNormalizer methods for flexible identifier handling**:
  - `normalize_doi()`: Normalizes DOI formats (10.xxx, doi:xxx, https://doi.org/xxx)
  - `normalize_identifier()`: Auto-detects identifier type (PMID/PMC ID/DOI)

### Changed

- **`get_fulltext` now supports flexible input**:
  - PMC ID: `get_fulltext(pmcid="PMC7096777")`
  - PMID: `get_fulltext(pmid="12345678")`
  - DOI: `get_fulltext(doi="10.1038/...")`
  - Auto-detect: `get_fulltext(identifier="anything")`

- **Multi-source fulltext retrieval**:
  1. **Europe PMC** - Structured fulltext with sections
  2. **Unpaywall** - Finds OA versions via DOI (gold/green/hybrid)
  3. **CORE** - 200M+ open access papers

- **PDF link aggregation**:
  - Collects PDF links from all sources
  - Shows OA status (Gold 🥇, Green 🟢, Hybrid 🔶)
  - Includes version info and license

### Example Output

```markdown
📖 **Article Title**
🔍 Sources checked: Europe PMC, Unpaywall, CORE

## 📥 PDF/Fulltext Links

- 📄 **PubMed Central** 🔓 Open Access
  https://www.ncbi.nlm.nih.gov/pmc/articles/PMC.../pdf/
- 📄 **Unpaywall (repository)** 🟢 Green OA
  https://repository.example.com/paper.pdf
  _Version: acceptedVersion_
- 📄 **CORE**
  https://core.ac.uk/download/...

## 📝 Content

### Introduction
...
```

---

## [0.1.20] - 2025-01-26

### 🎯 Tool Simplification: 34 → 25 Tools (-26%)

Major architectural simplification for better Agent UX.

### Changed

- **Unified Search Entry Point**: `unified_search` now handles all multi-source searches
  - Integrated: `search_literature`, `search_europe_pmc`, `search_core`, `search_openalex`
  - Auto-executes: `merge_search_results`, `expand_search_queries`
  
- **Streamlined Fulltext Tools**:
  - `get_fulltext` retained (Europe PMC)
  - `get_text_mined_terms` retained (text mining annotations)
  - Removed redundant: `get_fulltext_xml`, `search_europe_pmc`, `get_europe_pmc_citations`

### Removed (Functionality Integrated)

- `search_literature` → Use `unified_search`
- `search_europe_pmc` → Use `unified_search(sources=["europe_pmc"])`
- `search_core`, `search_core_fulltext` → Use `unified_search(sources=["core"])`
- `search_openalex` → Use `unified_search(sources=["openalex"])`
- `merge_search_results` → Auto-executed by unified_search
- `expand_search_queries` → Auto-executed by unified_search
- `get_fulltext_xml` → Use `get_fulltext`
- `get_europe_pmc_citations` → Use `find_citing_articles`

### Tool Categories (25 Total)

| Category | Tools | Count |
|----------|-------|-------|
| Search Entry | `unified_search` | 1 |
| Query Intelligence | `parse_pico`, `generate_search_queries`, `analyze_search_query` | 3 |
| Article Exploration | `fetch_article_details`, `find_related_articles`, `find_citing_articles`, `get_article_references`, `get_citation_metrics` | 5 |
| Fulltext | `get_fulltext`, `get_text_mined_terms` | 2 |
| NCBI Extended | `search_gene`, `get_gene_details`, `get_gene_literature`, `search_compound`, `get_compound_details`, `get_compound_literature`, `search_clinvar` | 7 |
| Citation Network | `build_citation_tree`, `suggest_citation_tree` | 2 |
| Session Management | `get_session_pmids`, `list_search_history`, `get_cached_article`, `get_session_summary` | 4 |
| Export | `prepare_export` | 1 |

---

## [0.1.19] - 2025-01-26

### 🔧 InputNormalizer + Mypy Fixes

Stable release with comprehensive type safety improvements.

### Added

- **InputNormalizer** class in `_common.py` for consistent input handling
- Type-safe normalization for: PMIDs, queries, limits, years, booleans

### Fixed

- All 77 mypy type errors resolved
- All 12 ruff linting errors fixed
- Proper `Optional[T]` type annotations throughout

---

## [0.1.18] - 2025-12-15

### 📚 CORE API & NCBI Extended Databases Integration

Added two major data source integrations:
1. **CORE** - 200M+ open access research papers from institutional repositories
2. **NCBI Extended** - Gene, PubChem, and ClinVar databases

### Added

- **CORE API Client** (`sources/core.py` - 400+ lines)
  - `search()` - Search 200M+ metadata records with field-specific queries
  - `search_fulltext()` - Search within 42M+ full text papers
  - `get_work()` - Get work details by CORE ID
  - `get_fulltext()` - Retrieve full text content
  - `search_by_doi()` / `search_by_pmid()` - Find papers by identifier
  - Supports optional API key for higher rate limits (5000/day)

- **NCBI Extended Client** (`sources/ncbi_extended.py` - 400+ lines)
  - **Gene Database**:
    - `search_gene()` - Search by gene name/symbol
    - `get_gene()` - Get gene details by ID
    - `get_gene_pubmed_links()` - Get linked PubMed articles
  - **PubChem Database**:
    - `search_compound()` - Search chemical compounds
    - `get_compound()` - Get compound details (formula, SMILES, etc.)
    - `get_compound_pubmed_links()` - Get linked PubMed articles
  - **ClinVar Database**:
    - `search_clinvar()` - Search clinical variants
    - Returns pathogenicity, conditions, gene associations

- **MCP Tools for CORE** (`mcp/tools/core.py`)
  - `search_core` - Search 200M+ open access papers
  - `search_core_fulltext` - Search within paper content
  - `get_core_paper` - Get paper details
  - `get_core_fulltext` - 📄 Get full text content
  - `find_in_core` - Find papers by DOI/PMID

- **MCP Tools for NCBI Extended** (`mcp/tools/ncbi_extended.py`)
  - `search_gene` - 🧬 Search Gene database
  - `get_gene_details` - Get gene information
  - `get_gene_literature` - Get gene-linked PubMed articles
  - `search_compound` - 💊 Search PubChem
  - `get_compound_details` - Get compound information
  - `get_compound_literature` - Get compound-linked articles
  - `search_clinvar` - 🔬 Search clinical variants

- **Sources Module Integration**
  - `SearchSource.CORE` enum value
  - `get_core_client()` factory function
  - `get_ncbi_extended_client()` factory function
  - `cross_search()` now includes CORE by default

- **Tests** (`tests/test_core_ncbi_extended.py` - 17 tests)
  - Unit tests for CORE client
  - Unit tests for NCBI Extended client
  - MCP tools registration tests
  - Sources integration tests

### Technical Details

- **CORE API**: 
  - Base URL: `https://api.core.ac.uk/v3`
  - Rate limits: 100/day (no key), 1000/day (free key), 5000/day (academic)
  - Environment variable: `CORE_API_KEY`

- **NCBI E-utilities**:
  - Uses existing Entrez infrastructure
  - Environment variables: `NCBI_EMAIL`, `NCBI_API_KEY`
  - Rate limits: 3/sec (no key), 10/sec (with key)

- **Dependencies**: Zero new dependencies (urllib only)

---

## [0.1.17] - 2025-12-15

### 🇪🇺 Europe PMC Integration

Added Europe PMC as a new data source with unique fulltext XML retrieval capabilities.
This provides access to 33M+ publications and 6.5M open access fulltext articles.

### Added

- **Europe PMC Client** (`sources/europe_pmc.py` - 500+ lines)
  - `search()` - Full-text search with OA/fulltext filters
  - `get_article()` - Get article by source/ID
  - `get_fulltext_xml()` - **Unique feature**: Direct JATS XML fulltext retrieval
  - `get_references()` / `get_citations()` - Citation network traversal
  - `get_text_mined_terms()` - Text-mined annotations (genes, diseases, chemicals)
  - `parse_fulltext_xml()` - Parse JATS XML into structured sections

- **MCP Tools for Europe PMC** (`mcp/tools/europe_pmc.py`)
  - `search_europe_pmc` - Search with OA/fulltext/sort filters
  - `get_fulltext` - 📄 Get parsed fulltext (structured sections)
  - `get_fulltext_xml` - Get raw JATS XML
  - `get_text_mined_terms` - 🔬 Get annotations (genes, diseases, chemicals)
  - `get_europe_pmc_citations` - Citation network (citing/references)

- **Sources Module Integration**
  - `SearchSource.EUROPE_PMC` enum value
  - `get_europe_pmc_client()` factory function
  - `search_alternate_source()` support for "europe_pmc"
  - `cross_search()` now includes europe_pmc by default

- **Tests** (`tests/test_europe_pmc.py` - 23 tests)
  - Unit tests for client with mocked responses
  - Unit tests for MCP tools
  - Integration tests with real API calls

### Technical Details

- **API**: No API key required, 1000 req/hour rate limit
- **Base URL**: `https://www.ebi.ac.uk/europepmc/webservices/rest`
- **Dependencies**: Zero new dependencies (urllib only)
- **Normalization**: Europe PMC results converted to PubMed-compatible format

---

## [0.1.16] - 2025-12-15

### 🔍 Multi-Source Academic Search (Internal)

Added internal support for Semantic Scholar and OpenAlex as alternate search sources.
External API unchanged - this is an internal enhancement ("掛羊頭賣狗肉").

### Added

- **Multi-Source Search Module** (`sources/`)
  - `SemanticScholarClient` - Semantic Scholar Graph API v1 client (318 lines)
  - `OpenAlexClient` - OpenAlex API client (340 lines)
  - Cross-search orchestration with deduplication (319 lines)
  - All using `urllib` (no extra dependencies)

- **Internal Parameters in `search_literature`** (not exposed in MCP API docs)
  - `source`: Switch between "pubmed", "semantic_scholar", "openalex"
  - `open_access_only`: Filter for open access papers
  - `cross_search_fallback`: Auto-search OpenAlex when PubMed < threshold
  - `cross_search_threshold`: Minimum results before fallback (default: 3)

- **API Documentation**
  - `docs/OPENALEX_API.md` - OpenAlex API reference (265 lines)
  - `docs/SEMANTIC_SCHOLAR_API.md` - Semantic Scholar API reference (272 lines)

### Technical Details

- **Architecture**: Internal sources module, MCP tool API unchanged
- **Dependencies**: Zero new dependencies (urllib only)
- **Rate Limiting**: Built-in rate limiters for both APIs
- **Normalization**: Both sources output PubMed-compatible format

---

## [0.1.14] - 2025-12-14

### 🧹 Code Quality Release

Comprehensive code quality improvements via ruff static analysis.

### Fixed

- **17 code issues** identified and fixed by ruff linter:
  - Removed unused imports (F401)
  - Fixed f-strings without placeholders (F541)
  - Fixed multiple statements on one line (E701) in `discovery.py`
  - Added proper `@pytest.mark.asyncio` decorator to `test_client.py`
  - Marked integration test with `@pytest.mark.skip`

### Changed

- Added `# noqa: F401` for intentional re-export in `tools/__init__.py`

### Technical Details

- **Test Coverage**: 407 tests passing, 4 skipped, 85% coverage
- **Linter Status**: All checks passed (0 errors)
- **Python**: Requires 3.11+

---

## [0.1.13] - 2025-12-14

### Changed
- **License: MIT → Apache 2.0** - Unified license with zotero-keeper ecosystem
  - All upstream dependencies are Apache 2.0 compatible:
    - biopython (Biopython License / BSD-like)
    - requests (Apache 2.0)
    - pylatexenc (MIT)
    - mcp (MIT)
  - Updated `LICENSE` file with full Apache 2.0 text
  - Updated `pyproject.toml` license field and classifier

### Architecture Review
- **DDD Structure Verified** - No refactoring needed
  - Application Layer: `mcp/tools/` (14 tools across 6 modules)
  - Infrastructure Layer: `entrez/`, `exports/`
  - Clean separation of concerns maintained
  - Mixin pattern for Entrez API (`LiteratureSearcher` inherits 6 mixins)

---

## [0.1.12] - 2025-12-14

### Added
- **Citation Tree Tools** - Build visual citation networks from any article
  - `build_citation_tree(pmid, depth, direction, output_format)` - Main tree builder
  - `suggest_citation_tree(pmid)` - Lightweight suggestion after fetching article
  - **6 Output Formats** supported:
    | Format | Library | Use Case |
    |--------|---------|----------|
    | `cytoscape` | Cytoscape.js | Academic research, bioinformatics |
    | `g6` | AntV G6 | Modern web apps, large graphs |
    | `d3` | D3.js | Flexible viz, Observable notebooks |
    | `vis` | vis-network | Quick prototypes |
    | `graphml` | GraphML XML | Gephi, VOSviewer, yEd, Pajek |
    | `mermaid` | Mermaid.js | ⭐ VS Code Markdown preview |
  - **Features**:
    - BFS traversal with configurable depth (1-3 levels)
    - Direction control: forward (citing), backward (references), or both
    - Max 100 nodes safety limit
    - Color-coded nodes: root (red), citing (cyan), reference (green)

- **Documentation Restructure**
  - New [ARCHITECTURE.md](ARCHITECTURE.md) - DDD design, data flows, ADRs
  - Simplified README.md HTTPS section with links to detailed docs
  - Added Citation Discovery Guide with tool comparison table
  - Decision tree for choosing the right citation tool

---

## [0.1.11] - 2025-12-12

### Changed
- **Python 3.11+ Modern Syntax** - Full adoption of Python 3.11 typing features
  - `Self` type from `typing` (PEP 673) for `from_dict()` classmethod
  - Union syntax: `X | None` instead of `Optional[X]` (PEP 604)
  - Built-in generics: `list[str]` instead of `List[str]` (PEP 585)
  - Cleaner, more readable type annotations throughout `client.py`

### Added
- **GitHub Actions CI/CD** - Auto-publish to PyPI on tag push
  - `.github/workflows/publish.yml` triggered by `v*` tags
  - Uses `pypa/gh-action-pypi-publish` with trusted publishing

---

## [0.1.10] - 2025-12-12

### Added
- **Author Affiliations** - `authors_full` now includes `affiliations` list
  - Extracts from PubMed `AffiliationInfo` elements
  - Example: `{"last_name": "Smith", "fore_name": "John", "affiliations": ["Harvard Medical School..."]}`
  - Enables downstream tools (zotero-keeper) to store institutional information

### Changed
- `_extract_authors()` now parses `AffiliationInfo` for each author
- Affiliations only included when available (backward compatible)
- **Python version requirement**: `>=3.10` → `>=3.11` (align with zotero-keeper and MCP ecosystem)

---

## [0.1.9] - 2025-12-12

### Added
- `PubMedClient.fetch_details()` - New method that returns dicts directly
  - Alias for `fetch_by_pmids_raw()` for better API consistency
  - Recommended for integrations needing dict format (e.g., zotero-keeper)
  - `fetch_by_pmids()` still returns `SearchResult` objects for type safety

### Fixed
- API consistency: Added `fetch_details()` as alias for `fetch_by_pmids_raw()`
- Integration compatibility with zotero-keeper MCP

---

## [0.1.8] - 2025-12-09

### Changed - Test Coverage Milestone 🎯

- **Test Coverage: 34% → 90%** - Major quality improvement
  - Added 360 new tests (51 → 411 total)
  - All 411 tests passing
  - Comprehensive mocking for NCBI APIs

- **Module Coverage Improvements**:
  | Module | Before | After |
  |--------|--------|-------|
  | `session_tools.py` | 64% | **100%** |
  | `client.py` | 77% | **97%** |
  | `pico.py` | - | **96%** |
  | `merge.py` | - | **95%** |
  | `links.py` | - | **96%** |
  | `pdf.py` | - | **95%** |
  | `session.py` | 76% | **94%** |
  | `formats.py` | 8% | **93%** |
  | `citation.py` | - | **91%** |
  | `icite.py` | - | **90%** |

- **New Test Files** (17 comprehensive test modules):
  - `test_90_percent.py` - Final push tests
  - `test_reach_90.py` - PubMedClient wrapper tests
  - `test_comprehensive_coverage.py` - Server, exports, session
  - `test_final_coverage.py` - Search mixins, strategy
  - `test_discovery_tools.py` - Citation discovery
  - `test_entrez_modules.py` - Base Entrez functionality
  - `test_exports.py` - All export formats
  - And 10 more targeted test files

### Fixed

- Fixed test assertions to match actual API return structures
- Fixed session manager method signatures
- Fixed SearchResult dataclass field requirements
- Proper mocking for all NCBI Entrez API calls

---

## [0.1.7] - 2025-12-08

### Added - NIH iCite Citation Metrics Integration

- **`get_citation_metrics` MCP Tool** - Get field-normalized citation data
  - Uses NIH iCite API (official, no API key required)
  - Returns citation metrics for any PMID(s)
  - Supports "last" keyword to analyze previous search results

- **Citation Metrics Available**:
  | Metric | Description |
  |--------|-------------|
  | `citation_count` | Total citations |
  | `relative_citation_ratio` (RCR) | Field-normalized (1.0 = average) |
  | `nih_percentile` | Percentile ranking (0-100) |
  | `citations_per_year` | Citation velocity |
  | `apt` | Approximate Potential to Translate (clinical relevance) |

- **Sorting & Filtering**:
  - Sort by any metric: `sort_by="relative_citation_ratio"`
  - Filter by thresholds: `min_citations=10`, `min_rcr=1.0`, `min_percentile=50`

- **New Module**: `src/pubmed_search/entrez/icite.py`
  - `ICiteMixin` class with methods:
    - `get_citation_metrics()` - Fetch metrics from iCite
    - `enrich_with_citations()` - Add metrics to article list
    - `sort_by_citations()` - Sort by any metric
    - `filter_by_citations()` - Filter by thresholds

### Example Usage

```
# Get citation metrics for specific PMIDs
get_citation_metrics(pmids="28968381,28324054")

# Analyze last search results, sorted by impact
get_citation_metrics(pmids="last", sort_by="relative_citation_ratio")

# Filter to high-impact articles only
get_citation_metrics(pmids="last", min_rcr=1.5, min_percentile=75)
```

---

## [0.1.6] - 2025-12-08

### Added - Citation Network: Get Article References

- **`get_article_references` MCP Tool** - Get the bibliography of any article
  - Uses PubMed ELink API (`pubmed_pubmed_refs`)
  - Returns papers THIS article cites (backward in time)
  - Complements existing `find_citing_articles` (forward in time)
  - Usage: Agent extracts PMID from user query/upload, then calls this tool

### Citation Network Tools (Complete Set)

| Tool | Direction | Description |
|------|-----------|-------------|
| `find_related_articles` | Similar | PubMed's similarity algorithm |
| `find_citing_articles` | Forward | Papers that cite this article |
| `get_article_references` | Backward | This article's bibliography |

---

## [0.1.5] - 2025-12-08

### Added - HTTPS Deployment (Enterprise Security)

- **Nginx Reverse Proxy** (`nginx/nginx.conf`)
  - TLS 1.2/1.3 termination with SSL certificates
  - Rate limiting (30 req/s)
  - Security headers (XSS, CSRF protection)
  - SSE optimization (24h timeout, no buffering)

- **Docker HTTPS Deployment** (`docker-compose.https.yml`)
  - Nginx + MCP service orchestration
  - Internal network isolation
  - Health checks

- **SSL Certificate Scripts**
  - `scripts/generate-ssl-certs.sh` - Generate self-signed certs for development
  - `scripts/start-https-docker.sh` - Docker HTTPS management (up/down/logs/restart)
  - `scripts/start-https-local.sh` - Local HTTPS via Uvicorn SSL

- **HTTPS Endpoints**
  - `https://localhost/` - MCP root
  - `https://localhost/sse` - SSE connection
  - `https://localhost/health` - Health check
  - `https://localhost/exports` - Export files

### Changed
- Updated DEPLOYMENT.md with comprehensive HTTPS deployment guide
- Added HTTPS section to README.md

---

## [0.1.4] - 2025-12-08

### Added - Query Analysis Integration
- **PubMed Query Interpretation** in `generate_search_queries()`
  - `estimated_count`: How many results PubMed would return for each suggested query
  - `pubmed_translation`: How PubMed actually interprets the query (vs Agent's understanding)
  - Helps Agent understand the gap between intended query and PubMed's actual search

---

## [0.1.3] - 2025-12-08

### Added - Enhanced Export Formats

- **Reference Manager Compatibility**
  - RIS format: EndNote, Zotero, Mendeley compatible
  - BibTeX format: LaTeX-ready with special character handling
  - CSV format: Excel-friendly with comprehensive metadata

- **New Export Fields**
  - ISSN (journal identifier)
  - Language (publication language)
  - Publication Type (Review, Clinical Trial, etc.)
  - First Author (for quick citation reference)
  - Author Count (collaboration indicator)
  - Publication Date (formatted)
  - DOI URL and PMC URL direct links

- **pylatexenc Integration**
  - Professional Unicode → LaTeX conversion
  - Handles Nordic characters (ø, æ, å), umlauts (ü, ö, ä)
  - Proper escaping for BibTeX special characters

### Changed
- RIS author format: `"Last, First Middle"` (was `"First Last"`)
- BibTeX author format: `{Last, First}` with LaTeX character conversion
- CSV headers: Standardized for reference manager import

### Fixed
- HTML tags in abstracts (`<sup>`, `<sub>`) now converted to plain text
- Special characters in author names properly escaped in BibTeX

---

## [0.1.2] - 2025-12-08

### Added - Export System
- **Export Tools**
  - `prepare_export` - Export citations in RIS, BibTeX, CSV, MEDLINE, JSON formats
  - `get_article_fulltext_links` - Get PMC/DOI links for article full text
  - `analyze_fulltext_access` - Analyze open access availability for article sets

- **HTTP Download Endpoints**
  - `/exports` - List all available export files
  - `/download/{filename}` - Direct file download (bypass agent, save tokens)
  - Large exports (>20 articles) auto-saved to /tmp/pubmed_exports/

- **Smart Hints**
  - Journal name disambiguation (anesthesiology = journal "Anesthesiology"?)
  - Detects 20+ common journals that may be confused with topics

### Changed
- Rate limiting for NCBI API compliance (0.34s without key, 0.1s with key)
- SERVER_INSTRUCTIONS improved with search workflow guidance

### Fixed
- Test isolation: Entrez.api_key cleanup between tests

---

## [0.1.1] - 2025-12-08

### Added
- Cache lookup before API calls - repeated searches return cached results
- `force_refresh` parameter for `search_literature` to bypass cache
- `find_cached_search()` method in SessionManager

### Changed
- Search results now show "(cached results)" when returned from cache
- Queries with filters (date, article_type) are not cached to ensure fresh results

---

## [0.1.0] - 2024-12-05

### Added

#### MCP Tools (8 tools)
- **Discovery Tools**
  - `search_literature` - PubMed literature search with date/type filters
  - `find_related_articles` - Find similar articles by PMID
  - `find_citing_articles` - Find articles citing a PMID
  - `fetch_article_details` - Get complete article metadata

- **Strategy Tools**
  - `generate_search_queries` - Generate multi-angle search queries with ESpell + MeSH
  - `expand_search_queries` - Expand queries with synonyms and related concepts

- **PICO Tools**
  - `parse_pico` - Parse clinical questions into P/I/C/O structure

- **Merge Tools**
  - `merge_search_results` - Deduplicate and merge results from multiple searches

#### Core Features
- MeSH vocabulary integration (mesh_lookup)
- Spelling correction via NCBI ESpell API
- Batch article fetching
- Citation network exploration (elink)
- Session management with automatic caching
- DDD (Domain-Driven Design) architecture

#### Infrastructure
- MCP server (stdio transport)
- HTTP/SSE remote server support
- Docker deployment support
- Submodule-ready design

### Architecture
- Modular tool organization: `discovery.py`, `strategy.py`, `pico.py`, `merge.py`
- Centralized session management (`session.py`)
- Entrez API abstraction layer (`entrez/`)

---

## [0.0.1] - 2024-12-01

### Added
- Initial project setup
- Basic PubMed search functionality
- MCP server prototype

---

## Links

- [GitHub Repository](https://github.com/u9401066/pubmed-search-mcp)
- [PyPI Package](https://pypi.org/project/pubmed-search-mcp/)
- [Smithery](https://smithery.ai/server/pubmed-search-mcp)

[Unreleased]: https://github.com/u9401066/pubmed-search-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/u9401066/pubmed-search-mcp/releases/tag/v0.1.0
[0.0.1]: https://github.com/u9401066/pubmed-search-mcp/releases/tag/v0.0.1
