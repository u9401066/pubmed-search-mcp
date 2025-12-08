# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added - Query Analysis Integration
- **PubMed Query Interpretation** in `generate_search_queries()`
  - `estimated_count`: How many results PubMed would return for each suggested query
  - `pubmed_translation`: How PubMed actually interprets the query (vs Agent's understanding)
  - Helps Agent understand the gap between intended query and PubMed's actual search

### Planned
- Research Prompts (Summarize, Literature Review, Clinical Relevance)
- Research trend analysis (keyword frequency, publication trends)
- Chart generation (PNG output)

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
