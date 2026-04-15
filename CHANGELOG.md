# Changelog

<!-- markdownlint-configure-file {"MD024": {"siblings_only": true}} -->
<!-- markdownlint-disable MD022 MD031 MD032 MD034 MD037 MD040 MD053 MD058 MD060 -->

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

## [0.5.4] - 2026-04-15

### Added

- Browser-session PDF fallback flow for `get_fulltext`, including broker-aware retrieval wiring and source exports for institutional or publisher-gated PDFs

### Changed

- Regenerated docs-site overview, troubleshooting, deployment, and quick-reference content to reflect the current browser-session and pipeline behavior
- Updated tool metadata and integration docs so README and docs navigation match the merged server surface

### Fixed

- Reconciled the local integration branch onto `master` for browser-session fulltext retrieval, Europe PMC fallback handling, and pipeline compatibility updates
- `run_server.py` no longer contains the duplicated `workspace_dir` argument introduced during the integration merge
- Result aggregation and pipeline entities now align with the merged compatibility layer expected by the MCP tools and tests

### Tests

- Added and stabilized regression coverage for Europe PMC fulltext fallback paths so Unpaywall / CORE / browser-session tests no longer depend on live external retries
- Revalidated the merged `master` branch with `scripts/check_async_tests.py` and the full `pytest` suite

---

## [0.5.3] - 2026-04-14

### Fixed

- `unified_search` no longer waits on background clinical-trials I/O after the `Formatting output...` phase begins
- Markdown formatting no longer performs fallback clinical-trials fetches inline, preventing post-formatting tool stalls and cancellations
- PubTator autocomplete now fails open after a 404 by disabling that endpoint for the current process instead of repeatedly retrying a missing route

### Tests

- Added regression coverage to ensure markdown output cancels slow clinical-trials work instead of blocking
- Added regression coverage to ensure formatting does not trigger inline clinical-trials fetches
- Added regression coverage to ensure PubTator autocomplete 404 disables subsequent autocomplete lookups

---

## [0.5.2] - 2026-04-07

### Added

- Cross-platform GitHub Actions CI matrix (Linux / macOS / Windows) with `timeout-minutes` and `concurrency` guard
- Bounded Agent Autonomy roadmap direction (planning / execution / critic / approval control plane)

### Fixed

- `run_server.py` export directory now uses OS temporary path instead of hardcoded `/tmp/pubmed_exports` for true cross-platform support
- `run_server.py` replaced `__import__("pathlib")` anti-pattern with proper top-level import

---

## [0.5.1] - 2026-04-07

### Added

- Pydantic-backed runtime settings surface in `shared/settings.py`
  - centralizes environment parsing for MCP server, HTTP API, source gating, profiling, OpenURL, and scheduler settings
- Source registry and source-expression parsing for unified search
  - supports `auto,-source` and `all,-source` expressions plus `PUBMED_SEARCH_DISABLED_SOURCES`
  - adds default-off Scopus and Web of Science connector skeletons for licensed environments
- Facade-style management tools
  - `read_session` consolidates session reads behind one action-based entry point while keeping legacy wrappers
  - `manage_pipeline` consolidates pipeline CRUD/history/scheduling behind one facade while keeping legacy wrappers
- APScheduler-backed persisted pipeline scheduling
  - `schedule_pipeline` now creates and removes real schedules
  - new scheduling infrastructure persists entries to `schedules.json` and restores jobs on server startup
- Pydantic schema layer for pipeline configs in `application/pipeline/schema.py`
  - separates structural parsing/coercion from semantic autofix
- Fulltext retrieval refactored into explicit discovery / fetch / extract phases
  - `fulltext_discovery.py`, `fulltext_fetch.py`, `fulltext_extract.py`, `fulltext_models.py`
  - `fulltext_download.py` preserved as backward-compatible facade
- Centralized Copilot hook policy in `.github/hooks/copilot-tool-policy.json`
  - bash and PowerShell hooks now read a single shared policy source
- Docs site pipeline tutorials, source-contract reference, and troubleshooting pages
- Article mapper extracted from domain entity into `infrastructure/sources/article_mapper.py`

### Changed

- High-level architecture and docs-site architecture pages now reflect the current 42-tool surface, facade tools, source registry, Pydantic settings, and real pipeline scheduling
- ROADMAP now reflects the current tool count, completed facade/scheduler work, updated session validation workflow, and the new default-off status of commercial connector skeletons
- Fulltext retrieval now routes through `fulltext_service.py` and `fulltext_registry.py`
  - keeps `get_fulltext` focused on normalization, progress/log bridging, and output formatting
  - centralizes identifier-aware source orchestration while preserving the existing public tool contract
- Unified search tool internals split into planning, execution, and request modules for testability

### Fixed

- Template-mode pipeline validation now applies the same output semantic autofix as step-mode validation instead of returning before output correction
- `run_server.py` `--no-security` flag now defaults to `False` instead of being always enabled
- Module-level design and maintenance docstrings restored across repository

---

## [0.5.0] - 2026-04-03

### Added

- Docs site surface under `docs/` with generated browseable pages, source-contract reference, and a site build script
- Shared orchestration primitives for multi-source adapters and cache backends
  - `shared/source_contracts.py` normalizes adapter execution, partial failures, and source-level error envelopes
  - `shared/cache_substrate.py` adds reusable in-memory / JSON-backed cache stores plus deterministic tests
- Release hardening utilities
  - `scripts/run_mutation_gate.py` adds deterministic mutation-gate coverage for core shared modules
  - `tests/test_mcp_protocol_in_memory.py` exercises the real FastMCP server in-memory
- Expanded MCP SDK usage beyond `unified_search`
  - Timeline tools now emit progress updates through FastMCP `Context`
  - `get_fulltext` and `get_text_mined_terms` now emit progress updates, and fulltext retrieval logs degraded-source events to MCP clients
  - New dynamic session resources: `session://last-search`, `session://last-search/pmids`, `session://last-search/results`

### Changed

- Raised MCP dependency floor to `mcp>=1.27` to match the runtime APIs now required by the server (`Context.report_progress`, `Context.log`, `FastMCP.list_tools`, task support)
- Reduced duplicated infrastructure in external clients
  - `PubTatorClient` now uses the shared `BaseAPIClient` transport path instead of maintaining its own retry/rate-limit/request loop
  - `ICiteMixin` now uses `cachetools.TTLCache` instead of a handwritten in-memory TTL cache
- Refactored image search and timeline policy logic into smaller, inspectable modules
  - Image query advising now separates policy tables, scoring, aggregation, and source adapter boundaries
  - Timeline milestone / landmark logic now separates policy tables, diagnostics, and scoring helpers
- Hardened runtime and local release workflows
  - `run_server.py`, `run_copilot.py`, Docker/start scripts, and Copilot smoke-test helpers now align around the current local MCP runtime
  - Test and mutation scripts now run through `uv` consistently
- Promoted PMC Open Access figure extraction as a first-class workflow in the public README guides
  - `get_article_figures` is now documented as the primary figure-first exploration path
  - `get_fulltext(include_figures=True)` is now documented as the fulltext+figures path for OA papers

### Fixed

- Release metadata is now consistent across package and server surfaces (`pyproject.toml`, `pubmed_search.__version__`, tool package headers)
- Source client overrides now accept the shared `params=` execution path used by `BaseAPIClient`
- Unpaywall email resolution now falls back to `NCBI_EMAIL` instead of defaulting to a fake example address
- MCP lifecycle logs now use ASCII separators so Windows terminal output no longer garbles startup / shutdown messages

---

## [0.4.5] - 2026-03-17

### Added

- **Research Context Graph preview in `unified_search`**
  - New `options="context_graph"` mode appends a lightweight Research Context Graph to Markdown output
  - JSON output now includes `research_context` when context graph generation succeeds
  - Reuses PMID-backed timeline data to expose thematic branches without a second tool call
- **MCP progress reporting for `unified_search`**
  - Reports progress for query analysis, semantic enhancement, source selection, deep search, aggregation, enrichment, ranking, and formatting
  - Reduces black-box wait time for MCP clients that provide a progress token
- **Deterministic article identity helpers**
  - New shared `canonical_article_key`, DOI normalization, and title normalization utilities in `shared/article_identity.py`
  - Used across ranking, aggregation, and pipeline execution for stable dedup and diagnostics

### Changed

- **Unified enrichment pipeline now runs in parallel**
  - CrossRef enrichment, OpenAlex journal metrics, and Unpaywall OA enrichment execute concurrently instead of sequentially
  - Reduces end-to-end latency for multi-source searches
- **Weighted RRF support** in ranking fusion
  - Reciprocal Rank Fusion now accepts dimension weights so ranking presets influence fused ordering
- **Tool registry validation prefers public FastMCP APIs**
  - Uses `list_tools()` when available and falls back to private registry only when needed

### Fixed

- Updated tests for async rate limiting, network-skippable external endpoints, and modern FastMCP tool registry behavior
- Synced README examples away from removed `include_preprints` / `peer_reviewed_only` direct params to current `options=` interface

---

## [0.4.4] - 2026-02-25

### Added

- **Article Figure Extraction** — New `get_article_figures` MCP tool (40 total tools, 15 categories)
  - Extract structured figure metadata (label, caption, image URL) from PMC Open Access articles
  - Multi-source fallback chain: Europe PMC XML → PMC efetch XML → BioC JSON
  - Direct image URLs via Europe PMC CDN pattern (deterministic, no extra HTTP request)
  - HTML scraping fallback for exact CDN URLs from PMC article pages
  - PDF download links (PubMed Central + Europe PMC) included in every response
  - Smart identifier detection: auto-detects PMID vs PMC ID from input
  - PMID→PMCID resolution via Europe PMC search API
  - Sub-figure parsing (`include_subfigures=True`) for multi-part figures (A, B, C...)
  - Table image extraction (`include_tables=True`) for `<table-wrap>` with `<graphic>`
  - Section reference mapping — shows which sections mention each figure
  - SSRF protection: URL validation against allowed academic domain whitelist
- **`get_fulltext(include_figures=True)`** — Optional inline figure metadata in fulltext responses
- **Domain Entity**: `ArticleFigure` + `ArticleFiguresResult` dataclasses (`domain/entities/figure.py`)
- **Infrastructure**: `FigureClient(BaseAPIClient)` with JATS XML + BioC JSON parsing (`infrastructure/sources/figure_client.py`)
- **New tool category**: "圖表擷取" (Figure Extraction) in tool registry
- **Spec document**: `docs/MCP_Visual_Data_Retrieval_Spec.md` v1.1.0 with review notes (Appendix C)

### Tests

- `test_figure_entity.py` — 10 tests for domain entity serialization and edge cases
- `test_figure_client.py` — 30 tests for SSRF validation, XML/JSON parsing, multi-source fallback, URL resolution
- `test_figure_tools.py` — 18 tests for MCP tool layer, identifier detection, PMID→PMCID resolution, output formatting

---

## [0.4.3] - 2026-02-15

### Added

- **Landmark Paper Detection** (`landmark_scorer.py`, ~250 lines)
  - Multi-signal composite scoring to identify the most important papers
  - 5 weighted components: citation impact (35%), milestone confidence (20%), source agreement (15%), evidence quality (15%), citation velocity (15%)
  - Citation impact uses NIH percentile (priority) → RCR log-scaled → raw count fallback
  - Tier system: landmark (≥0.75) / notable (≥0.50) / minor (≥0.25) / standard
  - Star ratings (⭐⭐⭐ / ⭐⭐ / ⭐) for visual display
  - `LandmarkScore` frozen dataclass in domain entities
  - Integrated into `TimelineBuilder.build_timeline()` via `highlight_landmarks=True` (default)
  - `format_timeline_text()` enhanced with star ratings and score details
- **Research Lineage Tree** (`research_tree.py` domain + `branch_detector.py`)
  - Tree-structured view of research evolution (vs flat timeline)
  - Automatic branching by MilestoneType into 8 categories:
    Discovery, Clinical Development, Regulatory, Evidence Synthesis,
    Guidelines & Practice, Safety, Landmark Studies, Other
  - Clinical Development auto-splits into Phase I/II and Phase III/IV sub-branches
  - `ResearchBranch` dataclass with sub-branches and chronological sorting
  - `ResearchTree` with `to_text_tree()` (ASCII tree), `to_mermaid_mindmap()`, `to_dict()`
  - 3 new output formats in `build_research_timeline`: `tree`, `mindmap`, `json_tree`
- **81 new tests** (54 landmark + 27 tree), total: 2899 passed

### Changed

- `TimelineBuilder._search_topic()` now preserves full iCite data (RCR, percentile, APT, velocity) instead of only citation_count
- `TimelineEvent` gains `landmark_score: LandmarkScore | None` field
- `ResearchTimeline.get_landmark_events()` supports `min_landmark_score` parameter
- `build_research_timeline` MCP tool: new `highlight_landmarks` parameter; new output formats (`tree`, `mindmap`, `json_tree`)

---

## [0.4.2] - 2026-02-15

### Added

- **BM25 Okapi relevance scoring** (`ranking_algorithms.py`)
  - Field-specific boosting: title (2×), MeSH/keywords (1.5×)
  - Micro-corpus construction from search result set
  - Normalized scoring for cross-query comparability
- **Reciprocal Rank Fusion (RRF)** for multi-dimension score fusion
  - Combines BM25, citation, recency, source authority rankings
  - Per-article dimension contribution diagnostics
  - k=60 (Cormack et al., 2009 TREC-optimal)
- **Maximal Marginal Relevance (MMR)** for result diversification
  - MeSH/keyword Jaccard similarity (no ML embeddings needed)
  - Configurable λ parameter (relevance vs diversity balance)
- **Source Disagreement Analysis** (novel contribution)
  - Source Agreement Score (SAS): pairwise overlap coefficient
  - Source Complementarity: fraction of unique-source articles
  - Per-source exclusive findings count
  - Integrated into unified search Markdown & JSON output
- **Reproducibility Score** (novel contribution)
  - 5-component weighted composite: deterministic (0.25), query formality (0.20), source coverage (0.20), result stability (0.15), audit completeness (0.20)
  - Grade system A-F for human interpretation
  - Query feature detection: MeSH tags, Boolean operators, field tags, date restrictions
  - Source stability tiers (PubMed 0.95 → CORE 0.70)
  - Integrated into unified search Markdown & JSON output
- **86 new tests** for all algorithms (BM25, RRF, MMR, Source Disagreement, Reproducibility)

### Changed

- `ResultAggregator.rank()` rewritten with BM25+RRF+MMR pipeline
  - `RankingConfig` extended with `use_bm25`, `use_rrf`, `use_mmr`, `mmr_lambda` fields
  - Original weighted-sum fallback preserved when BM25/RRF disabled
- Unified search output now includes Source Agreement Analysis and Reproducibility Score sections

---

## [0.4.1] - 2026-02-15

### Changed
- **unified.py modular split**: 2802→720 lines (74% reduction)
  - `unified_pipeline.py` — Pipeline execution (~195 lines)
  - `unified_helpers.py` — ICD detection, dispatch strategy, dataclasses (~545 lines)
  - `unified_source_search.py` — Multi-source search + auto-relaxation (~387 lines)
  - `unified_enrichment.py` — CrossRef/Unpaywall/journal metrics enrichment (~363 lines)
  - `unified_formatting.py` — Markdown & JSON result formatting (~349 lines)
  - All 27 symbols re-exported via `__all__` for backward compatibility

### Added
- **Pipeline report auto-save**: Reports automatically saved to workspace `.pubmed-search/reports/`
  - `PipelineStore.save_report()` with dual-scope (workspace + global) support
  - Workspace auto-detection via `.git`/`pyproject.toml` markers

### Fixed
- **source-counts-guard hook**: Updated to scan `unified_formatting.py` (where `_format_unified_results` now lives)
- **Test patch targets**: 6 test files updated to patch functions at their actual module location

---

## [0.4.0] - 2026-02-15

### Added
- **Pipeline System**: DAG-based pipeline executor with dependency resolution
  - 4 built-in templates: quick, standard, deep, custom
  - YAML pipeline definition support
  - Parallel step execution with configurable concurrency
- **Pipeline Persistence**: Save, load, and reuse structured search plans
  - Dual-scope storage: workspace (`.pubmed-search/`) + global (`~/.pubmed-search-mcp/`)
  - 6 management tools: save_pipeline, list_pipelines, load_pipeline, delete_pipeline, get_pipeline_history, schedule_pipeline
  - Auto-validation on save, execution history tracking
  - Pipeline Report Generator with production-grade Markdown reports
- **CORE Integration**: CORE as 6th search source in unified_search
  - 200M+ open access papers from 14,000+ repositories
  - Full text retrieval via CORE API
- **Composite Parameters**: unified_search consolidated from 18 to 7 parameters
  - `filters`: "year:2020-2024, species:human, language:english"
  - `sources`: "pubmed, openalex, semantic_scholar"
  - `options`: "sort:relevance, include_preprints:true"
- **Per-source API Return Counts**: Search results now display per-source counts
  - e.g., "**Sources**: pubmed (8/500), openalex (5)" for agent coverage decisions
  - `source-counts-guard` pre-commit hook to protect this critical feature
- **Research Workflow Tracker**: 7-step TODO-style research guidance via Copilot Hooks
  - Automatic workflow initialization on research intent detection (`analyze-prompt`)
  - Step completion tracking via `postToolUse` hook (`evaluate-results`)
  - Dynamic `instructions` injection for AI context with progress markers (`[x]`/`[ ]`)
  - Intent detection with template mapping (comparison→pico, systematic→comprehensive, etc.)
- **Copilot Hooks Integration**: Three-tier parallel pipeline enforcement via GitHub Copilot Hooks
  - 5 hook events: sessionStart, userPromptSubmitted, preToolUse, postToolUse, sessionEnd
  - 10 scripts (bash + PowerShell) for cross-platform support
  - Three-tier strategy: T1 (simple, allow) / T2 (moderate, allow+suggest) / T3 (complex, deny→pipeline)
  - Quality feedback loop via state files for iterative search improvement
- **Deep Research Architecture Analysis**: Competitive analysis of 8 multi-source search repos

### Changed
- **Single Search Entry Point**: unified_search replaces search_literature as primary entry
- **PipelineExecutor DDD**: Dependency injection for infrastructure layer separation

### Fixed
- **Unpaywall DOI encoding**: Slashes in DOIs were not percent-encoded, causing 422 errors
- **Copilot Hooks encoding/mojibake**: All hook output now ASCII-only (replaced emoji/Chinese with ASCII tags)
  - PowerShell scripts force UTF-8 output encoding
  - All scripts fail-open on errors (`exit 0` instead of `exit 1`)

### Deprecated
- `search_by_icd` — use `convert_icd_mesh` + `unified_search` instead

---

## [0.3.10] - 2026-02-14

### Added

- **14 new pre-commit hooks** — expanded from 17 to 41 hooks total
  - **External tools**: bandit (security), vulture (dead code), deptry (dependency hygiene), semgrep (SAST)
  - **Custom hooks**: future-annotations, no-print-in-src, ddd-layer-imports, no-type-ignore-bare, docstring-tools, no-env-inner-layers, todo-scanner
  - **Standard hooks**: 10 additional pre-commit-hooks (check-builtin-literals, check-case-conflict, check-docstring-first, etc.)
- **vulture_whitelist.py** — Dead code scan whitelist for false positives

### Changed

- **mypy 168→0 errors** — Complete type-safety achievement under `strict = true`
  - Fixed 2 real bugs: missing `await` in `fulltext_download.py` (Semantic Scholar & OpenAlex PDF links were silently broken)
  - Fixed 1 logic bug: `timeline_builder.py` iterated `citation_data` dict keys instead of `.items()`
  - Added proper type annotations across 30+ source files
  - `pyproject.toml` overrides use `disable_error_code` (not `disallow_untyped_defs = false`) for mypy strict compatibility
  - Wrapped `float.__pow__()` returns in `float()` to handle typeshed `Any` return
- **`from __future__ import annotations`** — enforced across all src/ and tests/ files via custom hook
- **Pre-commit hooks expanded** — 17→41 hooks covering security, dead code, dependency hygiene, and SAST

### Fixed

- **Missing `await` in `fulltext_download.py`** — `SemanticScholarClient.get_paper()` and `OpenAlexClient.get_work()` were called without `await`, causing PDF links to never be found (silently caught by try/except)
- **`timeline_builder.py` citation mapping** — `citation_data` dict was iterated by keys instead of `.items()`, causing `citation_count` to never be mapped to articles
- **Test mocks updated** — `Mock()` → `AsyncMock()` for async client methods; citation metrics mock format aligned with actual `dict[str, dict]` return type

---

## [0.3.9] - 2026-02-14

### Added

- **Pre-commit Infrastructure** — 17 automated hooks for code quality enforcement
  - ruff lint + ruff format (auto-fix)
  - mypy strict type checking
  - file-hygiene checker (`scripts/hooks/check_file_hygiene.py`)
  - async-test-checker (`scripts/check_async_tests.py`)
  - tool-count-sync with auto-stage (`scripts/hooks/check_tool_sync.py`)
  - evolution-cycle consistency validator (`scripts/hooks/check_evolution_cycle.py`)
  - Standard hooks: trailing-whitespace, end-of-file-fixer, check-yaml/toml/json, detect-private-key, etc.
  - Pre-push hook: full pytest suite (`-n 4 --timeout=60`)
- **MCP Performance Profiling** — `shared/profiling.py` module with 20 profiling tests
  - Monkey-patches `BaseAPIClient._make_request` for request timing
  - Profiling decorators and context managers

### Changed

- **ruff strictified to maximum** — `select = ["ALL"]` with ~40 justified global ignores in pyproject.toml
- **mypy strictified** — `strict = true` with module overrides; 326→176 errors
- **pytest multi-core enforced** — `-n 4 --timeout=60` via pyproject.toml `addopts`
- **`# noqa` suppressions reduced from 18 to 9** — Root-cause fixes instead of suppression:
  - `_ranking_score` / `_relevance_score` / `_quality_score` renamed to public fields (eliminates SLF001 ×3)
  - `format` → `fmt` parameter rename in `ncbi/utils.py` `export_citations()` (eliminates A001 ×2)
  - Dead `retryable_status_codes` parameter removed from `with_retry()` decorator (eliminates ARG001)
  - Unused `index` parameter removed from `safe_run()` in `async_utils.py` (eliminates ARG001)
  - `RateLimitExceeded` → `RateLimitExceededError` in pubtator client (eliminates N818)
  - Bare `pass` in try-except replaced with `logger.debug()` / explicit `return False` (eliminates S110 ×2)
- **Remaining 9 `# noqa` are all justified** — monkey-patching (SLF001), ExceptionGroup polyfill (N818), security rules (S310, S311, S603), XML import convention (N817), gather error handling (BLE001)

### Fixed

- **Dead code removed** — `retryable_status_codes` parameter in `with_retry()` was never used; retry logic uses typed exception classes (`RateLimitError`, `ServiceUnavailableError`, `NetworkError`)
- **Field visibility corrected** — `_ranking_score`, `_relevance_score`, `_quality_score` in `UnifiedArticle` were accessed cross-module but named as private; now properly public

---

## [0.3.8.1] - 2026-02-12

### Added

- **Algorithm Innovation Research Document** (`docs/ALGORITHM_INNOVATION_RESEARCH.md`)
  - Comprehensive internal research document assessing current algorithm depth
  - Honest evaluation: ~60% API wrapping, ~30% rule engines, ~10% real algorithms
  - Identified 3 core pain points: result indigestibility, cross-search amnesia, ranking-research mismatch
  - Proposed 4 solutions: Search Delta, Smart Top-K (MMR), Result Digest, Cumulative Coverage Tracker
  - Academic positioning: MMR (1998), TREC Session Track, Task-based Retrieval — none implemented in MCP ecosystem
  - 8 sections: motivation, pain points, honest assessment, innovation opportunities, search term analysis, implementation roadmap, validation methodology, references

### Changed

- **ROADMAP.md** — Added Phase 10.5: Algorithm Innovation Upgrade with 3-phase plan (A: BM25/RRF/PRF, B: Main Path/Burst/MeSH, C: SPECTER2/PubMedBERT)

---

## [0.3.8] - 2026-02-10

### Added

- **QueryValidator** — Pre-flight PubMed query syntax validation with auto-correction
  - Parentheses/quote balance checking and auto-fix
  - Field tag validation against 30+ valid PubMed tags
  - Empty Boolean operand detection, dangling operator fix
  - Query length limit enforcement (4096 chars)
  - Convenience function `validate_query()` for one-call usage
  - Integrated into `search.py` — queries auto-validated before NCBI API calls
- **NCBI WarningList Detection** — Post-search warning parsing (QuotedPhraseNotFound, PhraseIgnored, etc.)
- **Journal Metrics Enrichment** — OpenAlex `/sources` API integration in `unified_search`
  - `JournalMetrics` dataclass: h-index, 2-year mean citedness, works count, cited-by count, DOAJ status, subject areas
  - `impact_tier` property: Tier 1 (h≥150) / Tier 2 (h≥50) / Tier 3 (h≥20) / Tier 4
  - `get_source()` and `get_sources_batch()` methods on OpenAlex client
  - Output formatting: 📊 Journal metrics displayed per article
- **Peer Review Filter** — `peer_reviewed_only` parameter in `unified_search` (default=True)
  - `_is_preprint()` helper function for article type detection
  - OpenAlex `type` field mapping to `ArticleType` (article→JOURNAL_ARTICLE, preprint→PREPRINT, etc.)
  - Semantic Scholar preprint detection via `publicationVenue.type` and arXiv ID heuristics
- **Preprint Search** — `include_preprints` parameter in `unified_search` (default=False)
  - Dedicated preprint section in results (arXiv, medRxiv, bioRxiv)
  - Preprint detection via DOI prefix (6 prefixes: bioRxiv, medRxiv, arXiv, chemRxiv, SSRN, Research Square), source name, article type, journal name, arXiv ID

### Changed

- **Shared httpx.AsyncClient** — `get_shared_async_client()` singleton replacing per-request client creation in pdf.py, openurl tools, vision search
- **CI** — Removed test job from `publish.yml` (build+publish only, faster releases)

### Fixed

- **README formatting** — Fixed broken Unicode character in `## 🔗 Links` heading, removed stray empty code block in Security section
- **README tool names** — Synced tool tables with `TOOL_CATEGORIES` in both README.md and README.zh-TW.md (removed 5 non-existent tools, corrected ICD tool names)

### Documentation

- **Preprint Search** — Added preprint search sections to README.md and README.zh-TW.md (parameter table, usage examples, design philosophy)
- **Agent Instructions** — Added 情境 5 (preprint search) to `instructions.py` with `include_preprints`/`peer_reviewed_only` parameter guidance

### Tests

- **2380 passed, 27 skipped** — Full test suite healthy
- New: `test_query_validator.py` — 110 tests for QueryValidator
- New: `test_journal_metrics.py` — 41 tests for JournalMetrics enrichment
- New: 12 tests for `_is_preprint()` enhanced detection (DOI prefix, journal name)
- Updated mocks in multiple test files for shared httpx client singleton

---

## [0.3.7] - 2026-02-10

### Added

- **TRUE Deep Search** — `unified_search` now actually executes SemanticEnhancer strategies instead of just extracting entity names
  - 5 parallel strategies: original, mesh_expanded, entity_semantic, fulltext_epmc, broad_tiab
  - `_execute_deep_search()` runs all strategies via `asyncio.gather()`, aggregates and deduplicates results
  - New `deep_search` parameter (default=True) to control behavior
  - `SearchDepthMetrics` displayed in output (depth score, estimated recall/precision, strategies executed)
- **Auto Search Relaxation** — When 0 results found, progressively relax query across 6 levels
  - New `auto_relax` parameter (default=True)
  - 6 relaxation levels: advanced filters → year range → field tags → AND→OR → core keywords → broadest
  - `RelaxationResult` with step-by-step trace of what was tried
- **BaseAPIClient** — New base class for all 8 source clients (`infrastructure/sources/base_client.py`)
  - Unified retry on HTTP 429 with exponential backoff + `Retry-After` header support
  - Built-in rate limiting (configurable `min_interval`)
  - CircuitBreaker error tolerance
  - Consistent `httpx.AsyncClient` lifecycle management
- **Async test checker script** (`scripts/check_async_tests.py`) — Detect async/sync mismatches in tests

### Changed

- **8 source clients refactored to BaseAPIClient** — core.py, crossref.py, europe_pmc.py, ncbi_extended.py, openalex.py, openi.py, semantic_scholar.py, unpaywall.py now inherit from `BaseAPIClient`, removing ~500 lines of duplicated retry/rate-limit boilerplate
- **SemanticEnhancer** — `SearchPlan` dataclass now includes `source`, `expected_precision`, `expected_recall` fields
- **entity_cache.py** — Refactored for cleaner async patterns
- **strategy.py / search.py** — Improved search strategy dispatching
- **copilot-instructions.md** — Added anti-pattern rules (no reinventing wheel, no over-engineering)

### Fixed

- **unified_search never used SemanticEnhancer strategies** — Critical fix: strategies were generated but only entity names extracted for ranking weights; now all strategies are actually executed
- **`_search_europe_pmc()` field mapping** — Fixed to properly convert results using `from_pubmed()` with correct field name mapping
- **mypy type narrowing** — Fixed 4 locations where `asyncio.gather` results needed `cast()` for proper type inference

### Tests

- **2205 passed, 27 skipped** — Full test suite healthy
- New: 23 tests in `test_auto_relaxation.py` covering relaxation logic
- New: 16 tests in `test_unified_search.py` covering deep search integration
- Multiple test files updated for improved async mock patterns

### Technical Details

- 33 files changed, ~1427 insertions, ~939 deletions
- 3 new files: `base_client.py`, `check_async_tests.py`, `test_auto_relaxation.py`

---

## [0.3.6] - 2026-02-10

### Changed

- **Anti-pattern enforcement** — Added rules against reinventing the wheel and over-engineering to copilot-instructions.md
- **File hygiene** — Enforced `uv run` for all tool commands (ruff, mypy, pytest)
- **ruff format** — Applied consistent formatting across codebase

---

## [0.3.5] - 2026-02-10

### Fixed

- **P0: Rate limiting in batch.py** — Added `await _rate_limit()` before `Entrez.esearch` and `Entrez.efetch` calls to prevent NCBI 429 errors during batch operations
- **P1: HTTP 429 retry for all 8 source clients** — Added exponential backoff retry on 429 Too Many Requests for: core.py, crossref.py, europe_pmc.py, ncbi_extended.py, openalex.py, openi.py, semantic_scholar.py, unpaywall.py
  - Safe `Retry-After` header parsing with `try/except (ValueError, TypeError)` to prevent crashes on malformed headers
- **Code review P0/P1 fixes**:
  - `openalex.py`: Added missing `except Exception` handler for network errors
  - `semantic_scholar.py`: Added missing `except Exception` handler for network errors
  - `europe_pmc.py`: Fixed incorrect error message text
  - `ncbi_extended.py`: Removed duplicate exception handler

### Changed

- **copilot_tools.py** — Full rewrite: removed 11 duplicate tool registrations, added proper async/await, cleaned up docstrings (242 ins, 320 del)
- **File hygiene enforcement** — Added 第 7.1.1 條 to CONSTITUTION.md and 🧹 section to copilot-instructions.md; updated .gitignore with temp file exclusion patterns

### Tests

- **2181 passed, 0 failed, 27 skipped** — Full test suite passing
- Fixed 60+ test files for async compatibility after v0.3.4 async migration:
  - `with` → `async with` for httpx.AsyncClient context managers
  - `MagicMock()` → `AsyncMock()` for all async method mocks
  - `urllib.request.urlopen` / `requests.get` mocks → `httpx.AsyncClient` mocks
  - Removed `await` from sync functions; added `await` for async tool function calls
  - `time.sleep` → `asyncio.sleep` in async test code
- Skipped 4 integration test files that make real API calls (test_integration, test_advanced_filters, test_citation_tree, test_perf)

### Technical Details

- 94 files changed
- All source clients now have consistent 429 retry with exponential backoff (1s → 2s → 4s, max 3 retries)
- `pytest-timeout` added as dev dependency (30s default timeout)

---

## [0.3.4] - 2026-02-10

### Changed

- **Architecture: Full Async-First Migration** — All IO operations now use async/await
  - 8 source clients: `urllib.request` → `httpx.AsyncClient` (core, crossref, unpaywall, openi, europe_pmc, openalex, semantic_scholar, ncbi_extended)
  - 9 ncbi/ modules: `Entrez.*` → `await asyncio.to_thread(Entrez.*)` (base, search, citation, batch, strategy, utils, icite, pdf, citation_exporter)
  - `sources/__init__.py`: 5 functions → async (`cross_search` uses `asyncio.gather()` for parallel execution)
  - Application layer: `timeline_builder`, `image_search/service`, `export/links` → async
  - 13 MCP tool files (~49 functions) → `async def`
  - `time.sleep()` → `await asyncio.sleep()` throughout codebase
- **unified.py major refactor**: `ThreadPoolExecutor` → `asyncio.gather()` for parallel multi-source search; removed `asyncio.new_event_loop()` hack
- **openurl.py**: `urllib.request` → `httpx.AsyncClient` for `_test_resolver_url`
- **europe_pmc.py**: Removed `asyncio.run()` workaround (now natively async)
- 7 tool test files updated for async compatibility

### Technical Details

- 41 files changed, +990 insertions, -872 deletions
- All `requests`/`urllib` HTTP calls replaced with `httpx.AsyncClient`
- BioPython Entrez (sync library) wrapped with `asyncio.to_thread()` — no source modification needed
- `ruff check` + `ruff format` pass on all source files

---

## [0.3.3] - 2026-02-09

### Fixed

- **Critical**: Open-i image search returning irrelevant results (3 bugs)
  - Query parameter name was `q` instead of correct `query` — API ignored all search terms
  - Pagination parameter `n` treated as count but is actually end index — wrong page ranges
  - `it` (image type) was forced as required but is optional — prevented searching all types
- Updated `VALID_IMAGE_TYPES` to match official Swagger spec (`g` not `gl`, added `x`, `u`, `xm`, `m`, `p`, `c`)
- Updated `VALID_COLLECTIONS` to match official spec (added `cxr`, `usc`, `hmd`)
- Aligned `ImageQueryAdvisor` graphics type recommendation from `"gl"` → `"g"`

---

## [0.3.2] - 2026-02-09

### Fixed

- **Critical**: `_record_search_only` was calling `.get()` on `UnifiedArticle` dataclass objects
  - Error: `'UnifiedArticle' object has no attribute 'get'`
  - Now handles both dict and dataclass results using `isinstance`/`getattr`
  - Affects `unified_search` tool when recording search history

---

## [0.3.1] - 2026-02-09

### Changed

- **Tool Consolidation: 41 → 34 tools** (-7 tools) — Simplified API surface while preserving all functionality
  - **Timeline**: 6 → 3 tools
    - `build_timeline_from_pmids` → merged into `build_research_timeline(pmids=...)`
    - `get_timeline_visualization` → merged into `build_research_timeline(output_format=...)`
    - `list_milestone_patterns` → removed (static data, Agent can describe)
  - **Vision**: 2 → 1 tool
    - `reverse_image_search_pubmed` → merged into `analyze_figure_for_search(search_type=...)`
  - **ICD**: 3 → 2 tools
    - `convert_icd_to_mesh` + `convert_mesh_to_icd` → unified `convert_icd_mesh` (auto-detects direction)
  - **Citation**: 2 → 1 tool
    - `suggest_citation_tree` → removed (Agent can decide directly)
  - **Session**: 4 → 3 tools
    - `list_search_history` → merged into `get_session_summary(include_history=True)`
  - **OpenURL**: 4 → 2 tools (signature update only, full implementation deferred)
    - `list_resolver_presets` + `test_institutional_access` → planned merge into `configure_institutional_access`

### Removed

- `build_timeline_from_pmids` — use `build_research_timeline(pmids="123,456")`
- `get_timeline_visualization` — use `build_research_timeline(output_format="mermaid|timeline_js|d3")`
- `list_milestone_patterns` — static reference, will be MCP Resource
- `reverse_image_search_pubmed` — use `analyze_figure_for_search(search_type="medical|methodology|results|structure")`
- `convert_icd_to_mesh` / `convert_mesh_to_icd` — use `convert_icd_mesh(code=...)` or `convert_icd_mesh(mesh_term=...)`
- `suggest_citation_tree` — Agent decides based on fetch_article_details results
- `list_search_history` — use `get_session_summary(include_history=True, history_limit=10)`

### Fixed

- Updated 10+ test files to match consolidated tool API
- `tool_registry.py` TOOL_CATEGORIES updated for 34 tools / 13 categories
- All documentation auto-synced via `count_mcp_tools.py --update-docs`

---

## [0.3.0] - 2026-02-09

### Added

- **Phase 4.1: Biomedical Image Search MVP** — New `search_biomedical_images` tool
  - **Domain**: `ImageResult` dataclass + `ImageSource` enum (DDD entity)
  - **Infrastructure**: `OpenIClient` — Open-i (NLM) image search client with rate limiting, pagination, MeSH extraction
  - **Application**: `ImageSearchService` — coordinates search, source resolution, deduplication
  - **Presentation**: `search_biomedical_images` MCP tool with `InputNormalizer` integration
  - Supports image type filters (`xg`=X-ray, `mc`=Microscopy, `ph`=Photo, `gl`=Graphics) and collection filters (`pmc`, `mpx`, `iu`)
  - 44 tests covering all 4 DDD layers

- **Comprehensive Test Coverage (Round 6 & 7)** - 127+ new tests
  - `test_round6_coverage.py`: 85 tests covering unified.py, query_analyzer.py, _common.py
  - `test_round6_part2.py`: 42 tests covering fulltext_download.py, openurl.py, vision_search.py
  - Tests for: multi-source search, enrichment functions, DispatchStrategy, QueryAnalyzer
  - Tests for: FulltextDownloader async methods, OpenURL builder, Vision tools
  - Coverage improvement from 81.9% to 84%+

- **Tool-sync Auto-Update Skill** (`.claude/skills/tool-sync/SKILL.md`)
  - Documents the `count_mcp_tools.py --update-docs` workflow for keeping tool documentation in sync
  - Dynamic `_get_category_order()` in `count_mcp_tools.py` (replaces hardcoded list)

- **Documentation**: `docs/IMAGE_SEARCH_API.md`, `docs/PHASE_4_IMAGE_SEARCH.md`

### Changed

- MCP tools: 40 → **41 tools** across **13 categories** (new: `image_search`)
- Total tests: 2093 passed, 14 skipped
- README Design Philosophy table expanded (5 → 10 rows), Key Differentiators (4 → 7 items)
- README MCP Tools Overview rewritten to match current 41 tools / 13 categories
- README PICO descriptions: clarified as Agent-driven workflow (not auto server behavior)
- Dev tooling: ruff 0.14.13, mypy 1.19.1 — all lint/type errors resolved
- Unified mypy config in `pyproject.toml` (removed standalone `.mypy.ini`)

### Fixed

- **Open-i API `it` parameter now required** — API silently changed behavior; without `it`, returns `{total: 0, Query-Error: "Invalid request type."}`. Default to `xg` (X-ray, broadest coverage ~1.5M results). Added `ph` (Photo) and `gl` (Graphics) to `VALID_IMAGE_TYPES`
- `pico.py` next_steps referencing removed `search_literature()` + `merge_search_results()` → `unified_search()`
- `ImageResult.to_dict()` now uses `dataclasses.asdict()` (auto-tracks new fields)
- `test_tool_registry.py` updated for 13 categories
- `test_perf.py` moved to `tests/` and fixed stale import paths
- Misleading PICO auto-detect claims corrected in both READMEs (5 locations each)
- 109 ruff lint errors fixed (86 auto + 23 manual: E741 `l`→`lnk`, F841 unused vars)

---

## [0.2.8.2] - 2026-02-06

### Added

- **FulltextDownloader Enhancement** - Robust PDF download with enterprise features
  - **Retry with exponential backoff**: Auto-retry on transient failures (429, 500, 502, 503, 504)
  - **Rate limiting**: `asyncio.Semaphore(5)` limits concurrent requests, global 429 handling
  - **Streaming download**: 8KB chunk streaming prevents memory overflow on large PDFs
  - **4 new fulltext sources**: CrossRef Links, DOAJ (Gold OA), Zenodo, PubMed LinkOut
  - Now supports 15 fulltext sources total (was 11)

- **get_fulltext Tool Enhancement**
  - New `extended_sources` parameter: Enable all 15 sources (default: 3 core sources)
  - Source priority: Europe PMC > Unpaywall > CORE > CrossRef > DOAJ > Zenodo > ...

- **Package Import Tests**
  - 27 comprehensive tests for package exports validation
  - Tests cover: core imports, infrastructure, domain, application, MCP tools
  - Verifies circular import prevention

### Fixed

- **Mypy Type Errors**
  - `session/manager.py`: Fixed `Path | None` operator error with proper null check
  - `openurl.py`: Added proper type annotation for `result` dict

- **Test File API Signatures**
  - Updated `test_package_imports.py` to match current API
  - Fixed `UnifiedArticle` creation (source → primary_source)
  - Fixed `create_mcp_server` parameters (ncbi_api_key → api_key)
  - Fixed export function imports (format_ris → export_ris)

### Changed

- FulltextDownloader now uses httpx streaming instead of buffered download
- Zenodo test allows 403 (Cloudflare protection) as valid response

---

## [0.2.9] - 2026-01-28

### Fixed

- **Timeline Tools Bug Fixes**
  - Fixed ResponseFormatter API calls (format_error→error, format_info→no_results)
  - Fixed search parameter name (max_results→limit) in TimelineBuilder
  - Fixed BioPython StringElement type conversion for year comparison
  - Added `_parse_month()` in MilestoneDetector for month string parsing ("Jan"→1)

- **Session Recording**
  - Fixed `unified_search` not recording results to session
  - Added `_record_search_only()` call for data consistency

### Added

- **ROADMAP Phase 14: Research Gap Detection** - New innovative direction
  - 5 gap types: topic intersection, method transfer, population, outcome, geographic
  - Tools planned: `detect_research_gaps`, `find_topic_intersection_gaps`, etc.
  - Competitive advantage: No competitor offers automated multi-type gap detection

### Changed

- Tool categories increased from 11 to 12 (added "研究時間軸")
- Updated tool_registry.py with timeline tools category

---

## [0.2.8] - 2026-01-28

### Added

- **Research Timeline System (Phase 13.1 MVP)** - 6 new MCP tools for temporal research analysis
  - `build_research_timeline` - Build timeline showing key milestones from a topic
  - `build_timeline_from_pmids` - Build timeline from specific PMID list
  - `analyze_timeline_milestones` - Analyze milestone distribution and patterns
  - `get_timeline_visualization` - Generate Mermaid/TimelineJS/D3 visualization
  - `compare_timelines` - Compare research timelines of multiple topics
  - `list_milestone_patterns` - View detection patterns for debugging

- **Milestone Detection Engine**
  - Pattern-based detection using regex (transparent and extensible)
  - Detects: FDA/EMA approvals, Phase 1/2/3/4 trials, meta-analyses, guidelines
  - Detects: Safety alerts, label updates, landmark studies (by citation count)
  - Evidence level inference (Oxford CEBM simplified)

- **Domain Entities**
  - `TimelineEvent` - Immutable event with milestone type, confidence score
  - `ResearchTimeline` - Complete timeline with period grouping
  - `MilestoneType` - 20+ categorized milestone types
  - `EvidenceLevel` - Evidence quality classification

- **Visualization Outputs**
  - Mermaid timeline (renders in VS Code, GitHub, Markdown)
  - TimelineJS JSON format (for web embedding)
  - D3.js compatible format (for custom visualization)

### Changed

- Tool count increased from 34 to 40 MCP tools

---

## [0.2.7] - 2026-01-28

### Security

- **XML Parsing Security** - Replaced vulnerable `xml.etree.ElementTree` with `defusedxml`
  - Prevents XXE (XML External Entity) attacks
  - Affected files: europe_pmc.py, preprints.py
  - Added `defusedxml>=0.7.1` to dependencies

- **URL Scheme Validation** - Added scheme validation for urlopen calls
  - Prevents SSRF (Server-Side Request Forgery) attacks
  - Only allows http/https schemes
  - Added nosec comments for hardcoded API endpoints (CORE, Europe PMC, CrossRef, etc.)

### Fixed

- **Bandit Security Scan** - Resolved all medium/high severity issues
  - B310: URL scheme validation added
  - B314: XML parsing security fixed
  - 0 security issues remaining

---

## [0.2.6] - 2026-01-27

### Fixed

- **HTTP API Error Handling** - Improved Windows compatibility
  - Handle WinError 10013 (permission denied) gracefully
  - Downgrade all HTTP API startup failures from ERROR to WARNING
  - HTTP API is optional; MCP server works normally without it

---

## [0.2.5] - 2026-01-27

### Fixed

- **Server Startup Bug** - Fixed AttributeError in `main()` function
  - Changed `server._session_manager` to `server._pubmed_session_manager`
  - This bug could cause MCP server startup failure with exit code 1

---

## [0.2.4] - 2026-01-27

### Added

- **Tool Registration Architecture Refactoring** - Centralized management
  - New `tool_registry.py` - Central tool registration with `TOOL_CATEGORIES` and validation
  - New `instructions.py` - AI Agent usage instructions (7KB)
  - New `tools/icd.py` - ICD conversion tools module (moved from resources.py, 379 lines)
  - New `TOOLS_INDEX.md` - Complete tool index documentation
  - `validate_tool_registry()` - Runtime validation to ensure TOOL_CATEGORIES sync with registered tools

- **Automated Tool Statistics Script** (`scripts/count_mcp_tools.py`)
  - Get actual tool count from FastMCP runtime (equals MCP tools/list response)
  - Auto-update README.md, README.zh-TW.md, copilot-instructions.md, TOOLS_INDEX.md
  - Usage: `uv run python scripts/count_mcp_tools.py --update-docs`
  - Supports `--json`, `--verbose`, `--quiet` output modes

### Changed

- **README Tool Count Sync** - 21 → 34 MCP Tools
  - Fixed outdated tool count in all documentation
  - Tool descriptions auto-generated from FastMCP Tool.description

- **Git Pre-commit Skill Update** - Added `tool-count-sync` step
  - Now includes mandatory tool statistics sync before commit
  - Ensures documentation always matches codebase

### Fixed

- **ICD Tools Misplacement** - Moved 379 lines from resources.py to tools/icd.py
  - Proper module separation following DDD architecture
  - Fixed import in unified.py to use new location

---

## [0.2.2] - 2026-01-26

### Changed

- **CI/CD Pipeline Modernization** - Production-level quality gates
  - Migrated from `pip` + `python -m build` to `uv` (faster, more reliable)
  - Added pre-publish test job: tests, ruff check, ruff format check
  - Only publishes to PyPI if all quality checks pass
  - Configured mypy for production-ready type checking
- **HTTP Client Refactoring** - Unified exception handling + auto-retry mechanism
  - Added exception hierarchy: `RateLimitError`, `NetworkError`, `ServiceUnavailableError`, `ParseError`
  - Added `@with_retry` decorator with exponential backoff (max 3 retries)
  - New methods: `http_get()`, `http_post()` (raise exceptions)
  - Backward compatible: `http_get_safe()`, `http_post_safe()` (return None)

### Fixed

- **Code Quality** - Achieved production-level linting standards
  - Fixed all 41 ruff linting errors (unused variables, imports, bare except, comparisons)
  - Auto-formatted 43 files with ruff format
  - Added types-requests for better type coverage
  - All 672 tests passing ✅
- **Test Import Paths** - Mass fix for 40+ test files after DDD refactoring
  - `pubmed_search.client` → `pubmed_search.infrastructure.http`
  - `pubmed_search.entrez` → `pubmed_search.infrastructure.ncbi`
  - `pubmed_search.sources` → `pubmed_search.infrastructure.sources`
  - `pubmed_search.mcp` → `pubmed_search.presentation.mcp_server`
  - `pubmed_search.exports` → `pubmed_search.application.export`
  - Export `SearchResult`, `AggregationStats` from main module
  - Fix `COREClient` import path (shared → core)
  - Update SessionManager test API calls
  - **Test Results**: 672 passed, 14 skipped ✅ (Before: 322 passed, 121 failed)

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

[Unreleased]: https://github.com/u9401066/pubmed-search-mcp/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/u9401066/pubmed-search-mcp/releases/tag/v0.5.0
[0.4.6]: https://github.com/u9401066/pubmed-search-mcp/releases/tag/v0.4.6
[0.4.5]: https://github.com/u9401066/pubmed-search-mcp/releases/tag/v0.4.5
[0.1.0]: https://github.com/u9401066/pubmed-search-mcp/releases/tag/v0.1.0
[0.0.1]: https://github.com/u9401066/pubmed-search-mcp/releases/tag/v0.0.1
