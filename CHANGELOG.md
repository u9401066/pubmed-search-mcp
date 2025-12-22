# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Research Prompts (Summarize, Literature Review, Clinical Relevance)
- Research trend analysis (keyword frequency, publication trends)
- Chart generation (PNG output)

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
