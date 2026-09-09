# Progress (Updated: 2026-09-09)

## v0.7.2 Retrieval, Reliability, and Evaluation — Published

- Integrated the work with upstream v0.7.1, preserving the strict 41-tool
  protocol instead of restoring retired aliases or global runtime lookups.
- Corrected BM25 tokenization, duplicate/absent RRF votes, final pipeline query
  ranking, article identity normalization, reference consistency and identifier
  parsing, per-key/per-loop cache locking, and fulltext section selection.
- Added public-corpus metrics and separate frozen-agent/online-product runners
  with immutable manifests, per-attempt checkpoints, resume, and budget controls.
- Preserved historical NFCorpus measurements and the small native Codex pilot;
  neither is a measured full-agent score for v0.7.2. Long runs remain unstarted.
- Added README explanations and website/Wiki entries for benchmark and audit
  reports. Local validation passes **4,562 tests, 53 intentional skips**, all
  three complete MCP acceptance paths, Ruff/format, mypy across 426 files,
  async/DDD/skill audits, Bandit, deptry, vulture, and wheel/sdist builds.
- Prepared a separate v0.7.2 full-dataset manifest after evaluator/lockfile
  changes and verified resume without model calls. Historical experiments and
  the original `dbcf0c8` product baseline remain unchanged; attempts stay zero.
- Initial Windows CI caught the frozen evaluator's unconditional `AF_UNIX`
  lookup. The guard now supports platforms without that constant and a local
  regression simulates its absence while asserting external sockets stay blocked.
- Nine focused commits merged through PR #14 at `c331ac5`, then the identical
  tested tree was tagged `v0.7.2`. Both branch/PR suites (`34330391447`,
  `34330395431`) and master CI (`34331042992`) passed. The tag workflow
  (`34331096208`) passed all three distribution verification/publication jobs.
- PyPI and GitHub expose the same verified wheel and sdist, with matching
  SHA-256 values. Pages (`34331042963`) and Wiki (`34331043013`) deployed
  successfully; their public content was checked. Playwright also passed the
  public site's desktop/mobile navigation, search, language, and menu flows.
- Publication receipts and distribution hashes are saved in
  [release verification](../docs/reports/release_v072_2026-09-09.json).
  Public release:
  https://github.com/u9401066/pubmed-search-mcp/releases/tag/v0.7.2
  and https://pypi.org/project/pubmed-search-mcp/0.7.2/.

## v0.7.1 Complete MCP Protocol Acceptance and Release

- Added a deterministic child-server fixture that keeps the canonical MCP
  registry, strict schemas, tool adapters, application services, durable stores,
  artifacts, note exports, Chronicle revisions, pipeline execution, and
  scheduling real while replacing external-provider boundaries.
- Added an independent 41-tool manifest and semantic assertions for every public
  tool. Stateful action coverage performs 60 real `tools/call` requests per run,
  including all nine `read_session` actions, all six Chronicle read actions,
  two Chronicle revisions, comparison, saved-pipeline execution, artifact reads,
  and persisted note-file checks.
- Actual Chronicle and citation Mermaid responses now require exact source
  fences/JSON, matching SHA-256 and size metadata, structural validity, hostile
  label repair, and successful SVG rendering with pinned Mermaid 11.16.1 in CI.
- Added a real-stdio rejection pass for retired tool names, flat legacy action
  shapes, invalid scalar types, and stringified arrays/objects; the no-compat
  boundary is therefore checked across an actual child process as well as the
  existing in-memory protocol tests.
- Added three real protocol/package paths: source stdio, source Streamable HTTP,
  and stdio from a freshly built wheel installed into a blank virtual
  environment. Unexpected outbound DNS/socket access fails closed.
- All three protocol paths pass. The acceptance file reports five passes: one
  hermetic-environment contract, source stdio, real-stdio breaking-contract
  rejection, source Streamable HTTP, and fresh-wheel stdio. The repository-wide
  gate reports **4,475 passed, 53 skipped**; Ruff, format checking, mypy across
  413 source files, and the async test audit also pass. All 105 repository and
  generated smoke Mermaid diagrams render to SVG with pinned Mermaid 11.16.1.
- The stateful pipeline call exposed a production regression that narrow tests
  had missed: executing `saved:<name>` returned an empty pipeline identity.
  Materialization now preserves the saved name, and both the MCP acceptance
  assertion and a narrow regression test protect it.
- CI now has explicit source stdio/HTTP and fresh-wheel complete acceptance
  gates; the regular cross-platform matrix also runs the non-slow source paths.
- Segmented commits were merged through PR #11 at `4237ed0` and tagged as
  `v0.7.1`. Both duplicate push/PR check suites completed successfully; the
  release workflow (`33483446706`) then rebuilt and verified the distributions,
  installed the wheel, smoke-tested the container, published through PyPI
  Trusted Publishing, and created the GitHub Release.
- Public verification confirms
  `https://pypi.org/project/pubmed-search-mcp/0.7.1/` exposes the 0.7.1 wheel and
  source distribution, while
  `https://github.com/u9401066/pubmed-search-mcp/releases/tag/v0.7.1` exposes the
  same two release assets. Ordinary CI deliberately skips credentialed live API
  probes; the release claim is deterministic full MCP integration, not universal
  third-party availability.

## v0.7.0 Release Candidate

- Consolidated the public surface to **41 tools / 16 categories** across stdio,
  Streamable HTTP, Copilot, registry tests, and documentation. Removed public
  aliases, compatibility wrappers, the reduced Copilot tool registry, and other
  duplicate presentation paths instead of keeping silent fallbacks.
- Made `read_session` and `read_research_chronicle` strict
  action-discriminated request tools. Search-run replay now returns canonical
  nested `{"request": {...}}` arguments.
- Removed the pipeline `execution` compatibility shape and retired top-level
  template `params`; template mode accepts only `template_params`. Pipeline
  `kind` is inferred only when omitted and an explicit discriminator is never
  overwritten. Action/template/dependency identifiers, enums, and all
  action-specific parameters reject unknown fields, fuzzy aliases, scalar/CSV
  repair, and type coercion; defaults apply only to omitted documented fields.
- Unified source execution around validated `SourceAdapterCall`,
  `SourceAdapterResult`, and `SourceAdapterError`. Source/operation identity,
  runtime types, nested error provenance, status coherence, and
  `total_count >= len(items) >= 0` are enforced across shallow, relaxed, deep,
  full-text, preprint, and image paths.
- Moved normal unified-search orchestration into the application-owned
  `UnifiedSearchUseCase` with explicit planner, executor, source-broker,
  source-registry, enrichment, progress, and observer ports. The MCP runner now
  owns only preflight, SearchRun journal, host progress, formatting, artifact,
  and recovery concerns around the typed application outcome.
- Changed `PubMedSearchClient.unified_search()` to compose that use case
  directly and return typed articles, source coverage/errors, and filter
  counts. The SDK no longer imports the MCP runner or creates serialized MCP,
  journal, session, or artifact side effects.
- Replaced PubMed, Scopus, and Web of Science list/search-metadata dual APIs
  with one typed page contract. Removed NCBI article-shaped failure rows and
  changed Europe PMC, CORE, OpenAlex, Semantic Scholar, ClinicalTrials.gov, and
  preprint clients so provider faults cannot silently report an empty result.
- Removed provider soft-fail and convenience surfaces: `BaseAPIClient` no
  longer has `strict_errors`, mutable last-error state, a duplicate rate
  limiter, or raw upstream-reason logging; duplicate CORE/Europe PMC
  search/getter and Crossref/Unpaywall lookup functions were deleted in favor
  of the runtime-owned package boundary and typed failures.
- Made session persistence exact-versioned (`research-session/v1` and
  `research-session-index/v1`), removed article-cache warmup payloads and
  history-to-run projection, and retained `search_history` only as an explicit
  summary read model.
- Consolidated full-text coordination under `application/fulltext`; deleted the
  duplicate infrastructure service/registry facades and pass-through download
  wrappers. Link discovery now has one immutable typed result and preserves
  canonical attempted/completed sources plus sanitized partial failures through
  download, extraction, MCP output, and artifacts. Only HTTP 204/404 or a valid
  parsed zero-link response is absence; outage/parse failure produces
  `partial`/`unavailable`. Source selection accepts only exact canonical keys,
  and only `SEMANTIC_SCHOLAR_API_KEY` configures Semantic Scholar.
- Made `generate_search_queries` publish separate
  `completed`/`partial`/`failed` coverage for spelling, MeSH, and PubMed query
  analysis. Unchanged spelling, completed no-match, and genuine zero results
  remain successful; outages produce only sanitized generic warnings.
- Hardened late-stage storage/access boundaries: authenticated note exports
  expose tenant-relative locators instead of host paths, OpenURL bases reject
  query credentials and non-resolver search presets, PMID-to-DOI diagnosis
  separates missing metadata from outage, and corrupt pipeline history fails
  closed instead of becoming a partial or empty report.
- The browser broker now requires an explicitly provisioned bearer token of at
  least 32 characters and never generates or logs authentication secrets.
- Reference-verification timeout handling now uses the cross-version
  `asyncio.TimeoutError` contract, keeping Python 3.10 behavior aligned with
  Python 3.11–3.13 for both batch prefetch and single-reference deadlines.
- Made PubMed EFetch and all seven NCBI Extended provider paths validate exact
  envelopes and row identity. Added `clinical-trials-adjunct/v1` so explicit
  Markdown/JSON/TOON adjunct requests preserve retrieval/format coverage and
  sanitized failures consistently through every artifact projection.
- Made Open-i return a strict provider page and typed per-source image coverage:
  explicit zero is empty, mixed valid/invalid rows are partial, malformed/all-
  invalid results fail, and Markdown cannot rewrite failure as no images.
- Added one deadline and external-call quota across each complete pipeline DAG,
  including parallel steps; validation no longer exposes an auto-fix contract.
- Isolated mutable session, tenant, strategy, container, pipeline,
  source-contact, source-client, and HTTP lifecycle state per MCP server.
  Constructing or closing one server no longer replaces another server's
  runtime. Scheduled pipeline DAGs rebind the creating server's runtime, while
  `PubMedSearchClient` owns a separate lazy runtime closed by `async with` or
  `aclose()`.
- Added a server-owned `HostCallbackRuntime` with a hard `asyncio.wait`
  deadline. A stalled progress/log/resource callback is cancelled and yielded
  once; cancellation-resistant work is quarantined in a bounded 32-task
  supervisor, new callbacks are rejected at capacity, and lifespan shutdown
  invokes bounded cleanup. Host failure stays non-fatal and enclosing tool
  cancellation still propagates.
- Extracted the reusable `BoundedTaskSupervisor` so host callbacks and citation
  expansion share one ownership/capacity/reaping implementation without sharing
  state. `ToolSessionRuntime` owns the 32-task host supervisor and 128-task
  citation supervisor, and server lifespan closes both.
- Deleted the profiling monkeypatch and hidden `get_performance_metrics` tool,
  the orphan standalone FastAPI presentation app, and the stdio background-HTTP
  launcher. The supported HTTP launcher owns its tenant-guarded companion
  routes; those routes are not a second MCP registry.
- Routed full-text and other URL-following retrieval through shared safe
  outbound handling with scheme/credential checks, DNS/IP policy, redirect-hop
  revalidation, DNS-rebinding protection, response byte caps, and total
  deadlines.
- Extended the canonical Chronicle `flowchart LR`: the year spine preserves
  sequence, thematic branches expose divergence, and nested branches link to
  both their parent theme and their own chronological anchor.
- Added `citation-metrics-coverage/v1` and separate requested/effective ranking
  provenance. Chronicle uses iCite ordering only after applying a validated
  citation count; partial, empty, malformed, and outage outcomes are audited
  without raw provider details.
- Consolidated Mermaid production around a shared structured graph kernel with
  deterministic `rich -> safe -> minimal` repair, bounds, and visible audit
  diagnostics.
- Made optional Crossref, journal-metrics, and Unpaywall enrichment return
  immutable typed patches and sanitized coverage outcomes. Stable candidate
  ties, fixed provider/article application order, and final re-ranking remove
  mutation and provider-completion-order bias.
- Moved the curated ICD/MeSH crosswalk and lookup behavior into
  `application/search/icd.py`; the MCP registrar now only dispatches and
  formats. Image search now depends on `ImageSourceAdapter`/`OpenIClientPort`,
  with the composition root injecting an Open-i factory owned by each server's
  `SourceRuntime`.
- Completed a runtime-derived schema audit: **41 unique tool owners / 16
  categories**, **74 recursively closed object schemas**, **215 bounded
  primitive/array nodes**, and **10 exact tagged unions**, with required/default
  and annotation/side-effect coherence checked against the registered tools.
- Added complete bilingual unified-search architecture/function inventory and
  all-tool quality audit pages, including Mermaid architecture, relationship,
  request-flow, and improvement diagrams; synchronized README and generated
  website sources with the strict registry.
- The definitive local gate passed: **4,470 tests / 53 intentional skips**,
  Ruff, mypy across 411 files, DDD/async/security/dependency checks, all changed
  pre-commit policies, **102 Mermaid diagrams rendered to SVG**, Playwright
  desktop/mobile docs QA, sdist/wheel metadata checks, and an isolated Python
  3.10 wheel install. The segmented release branch and duplicate push/PR CI
  matrices passed before the annotated v0.7.0 release gate.

## Done

### 2026-08-12: v0.6.2 Research Chronicle Integrity and Mermaid Hardening

- Reworked the canonical Chronicle diagram into a horizontal `flowchart LR`
  year-anchor spine with observational topic branches. Repeated MeSH/keyword
  signals are accepted only when at least two supported branches cover 60% of
  events; otherwise diagnostics disclose `research_stage_fallback`. Date
  precision controls stable entry ordering; undated evidence is explicit and
  placed last.
- Made lineage claims conservative: definite chronology may produce
  `PRECEDES`, but the classifier does not invent `SUPERSEDES`; evidence absent
  from a later revision is `not_observed_in_revision`, not automatically
  retired. Branch overlap and cross-links are reported without causal wording.
- Improved capped selection so earliest/latest boundaries, explicit landmarks,
  citations, and temporal spread survive instead of retaining only the first
  chronological block. Empty retrieval and PubMed error sentinels cannot create
  a false paper or publish an empty evidence revision.
- Added deterministic Mermaid normalization and repair for unsafe Unicode and
  directives, malformed labels/rows, duplicate ids, orphaned parents,
  self-loops, cycles, invalid dates, and size limits. Rendering uses auditable
  `rich -> safe -> minimal` fallback tiers with corrections, warnings, and
  omitted counts.
- Added pinned Mermaid 11.16.1/jsdom 26.1.0 CI that parses and renders runtime
  fixtures plus repository/documentation diagrams to SVG. Forty-seven diagrams
  passed real rendering, alongside seeded hostile-input and 1,000-case
  structural/determinism fuzz coverage.
- Hardened Chronicle persistence: immutable revision JSON is authoritative,
  the index is a rebuildable cache, publication is atomic and lock-protected,
  and stale/corrupt/missing indices recover from revisions. Store calls from
  async application/MCP paths use `asyncio.to_thread`.
- Tightened topic/year/PMID/revision/MCP input validation, canonical topic and
  evidence identity, exact explicit-PMID auditing, source-coverage diagnostics,
  prepared artifact file-set preflight, artifact-store locator/checksum
  validation, snapshot completeness, and forward-only revision diffs.
- Synchronized README, bilingual handbook/site content, Chronicle spec,
  CHANGELOG, skills, Copilot/Cline guidance, hooks, and generated references.
- Deterministic quality gate: `3910 passed, 24 skipped, 30 deselected`; strict
  mypy (355 files), Ruff, async-test checker, docs checks, and Mermaid rendering
  passed. One opt-in live run had three CORE/Unpaywall timeouts caused by
  upstream connectivity; no deterministic Chronicle gate failed.
- Removed a release-gate session flake by injecting the server-owned tenant
  registry into registered tools/resources. A leaked process registry can no
  longer override an explicitly supplied single-user or SDK session manager.
- Published annotated tag `v0.6.2` from verified commit `f253fd7` through PyPI
  trusted publishing, then attached the identical workflow-built wheel and
  source distribution to the GitHub Release. Cross-platform CI, including
  Windows PowerShell 5.1 hook coverage, completed successfully.

### 2026-08-10: MCP v2 / Broker / Deployment Hardening
- Synchronized the workspace to upstream v0.6.0 and verified the locked MCP
  Python SDK and `mcp-types` are both 2.0.0.
- Removed remaining production use of MCP private tool/middleware state and
  replaced the stale initialize/session-based Copilot diagnostic with the
  2026-07-28 modern request contract.
- Split HTTP into trusted loopback `local` and fail-closed authenticated
  `service` profiles; preserved cross-request local session state while keeping
  service sessions, caches, exports, chronicles, and pipelines principal-scoped.
- Added tenant-safe opaque exports, shared `PUBMED_DATA_DIR` injection, global
  Host/Origin guards, trusted-proxy allowlists, and safe opt-in stdio auxiliary
  HTTP behavior.
- Hardened the local browser fetch broker against DNS rebinding, remote binds,
  and published default tokens.
- Made every public Copilot/ngrok path start authenticated service mode, kept
  local Copilot/HTTPS helpers loopback-only, and aligned `/health` plus `/ready`
  probes with deployment documentation.
- Removed tenant-id normalization collisions (including forged `default` and
  blank principals) and corrected token-bucket post-wait accounting that could
  otherwise double an upstream request budget.
- Corrected broker planning for explicit/deep/preprint sources, PubMed-only
  relaxation, conservative provider quotas, normalized partial failures, and
  provider-identifier deduplication.
- Made session/cache/pipeline/chronicle/artifact/note persistence safe under MCP
  v2 worker-thread execution with process locks, atomic publication, detached
  snapshots, containment checks, and concurrent lost-update regressions.
- Refreshed bilingual README/site/wiki/deployment diagrams, 45-tool capability
  routing, source broker contracts, Compose profiles, Nginx, Copilot schema,
  GitHub metadata/topics/labels, and release workflows.
- Fixed generated handbook links so routed anchors stay valid and repository-
  only files resolve to GitHub; cloud examples now build to an operator-owned
  registry instead of referring to an unpublished project image.
- Added real stdio/Streamable HTTP/fresh-wheel smoke tests plus local/service,
  export, Host/Origin, browser-broker, rate, source-selection, and identity edge
  regressions.
- Restored the declared Python 3.10 contract with compatible task cleanup,
  timeout handling, atomic publication, RFC 3339 `Z` parsing, and direct
  compatibility dependencies; also stabilized the macOS auxiliary-HTTP probe.
- Final local gates: `3762 passed, 22 skipped, 30 deselected` for the complete
  non-integration suite; `28 passed, 2 skipped` for opt-in live providers;
  Python 3.10's PR condition passed `3745 passed, 22 skipped, 47 deselected`;
  `33 passed` for release transport/fresh-wheel smoke; `27 passed` for
  documentation/site/wiki integrity; Ruff, format, mypy, async checker, and
  browser QA all pass.

### 2026-08-03: v0.6.0 — SDK v2, Research Chronicle, Multi-Agent Service Mode
- Migrated to MCP Python SDK v2 (`mcp>=2,<3`, protocol 2026-07-28); experimental tasks removed with the spec, transport keywords moved into `build_asgi_app()`.
- Research Chronicle shipped as the single research-evolution entry point; `build_research_timeline` / `analyze_timeline_milestones` / `compare_timelines` retired into it (48 → 45 tools, 17 → 16 categories). v0.7.0 later reduced the canonical surface to 41 tools.
- Multi-agent service mode: per-tenant sessions/cache/artifacts, bearer-token auth, per-tenant fair-share concurrency, `/ready`.
- Security model at the v0.6.0 boundary: legacy `mcp-session-id` was correlation only, never identity. The 2026-08-09 modern profile supersedes it with authenticated service principals and an explicit durable loopback-local tenant; other HTTP callers never touch disk.
- Cross-tenant leaks closed in chronicle, pipeline, and literature-note storage; `tenant-scoped-storage` pre-commit hook added so the class of bug cannot recur.
- Upstream rate limiting consolidated to one shared budget per service; loop-scoped primitives re-keyed by loop object to stop stale-state reuse.
- Verification: 3601 tests passing; 10 mutation regressions all caught; boundary tests for hostile tenant ids and rate-limiter budgets; protocol smoke tests for the tool surface and both HTTP transports.
- Known limitation: the pipeline scheduler is process-wide and bound to the default tenant, so `schedule_pipeline` is refused for isolated tenants.

### 2026-06-06: Research Chronicle Rebuild Spec Alignment
- Rewrote `docs/RESEARCH_CHRONICLE_REFACTOR_SPEC.md` as the canonical pre-rebuild contract for timeline, lineage tree, context graph preview, citation graph, artifacts, and the planned persistent Research Chronicle.
- Cross-checked implementation, documentation, and test gaps with multiple read-only subagents.
- Historical terminology: `build_research_chronicle` became the single research-evolution entry point (timeline / lineage tree / milestones / comparison are projections or actions of it). The former `unified_search(options="context_graph")` preview was retired in v0.7.0; `build_citation_tree` remains the citation-network tool.
- Captured rebuild blockers: broken/untested `pmids="last"` timeline path, incomplete timeline format coverage, context graph boundary tests, citation tree response-contract tests, presentation-layer citation graph logic, and projection formatting in domain entities.

### 2026-06-05: Python SDK Facade + Packaged HTTP CLI
- Stable package API: added `pubmed_search.api` with `PubMedSearchClient`, `PubMedSearchConfig`, and `UnifiedSearchResult` for in-process Python callers.
- Unified search runner split: MCP `unified_search` now delegates to `presentation.mcp_server.tools.unified_runner`, keeping old patch points while reducing wrapper logic.
- Application contract: added `pubmed_search.application.unified` request/service contracts so SDK callers do not import MCP presentation modules at import time.
- Packaged HTTP entrypoint: added `pubmed-search-mcp-http` for Streamable HTTP/SSE server deployment; `run_server.py` is now documented as a source-tree development wrapper.
- Docs alignment: README, integrations guide, developer guide, agent rules, and design docs now distinguish MCP tool surface, Python SDK facade, and auxiliary HTTP APIs.

### 2026-06-05: v0.5.15 - Research Artifact Envelope + Repo Hardening
- Research artifact envelope: `unified_search` now persists `audit.json`, `query_strategy.json`, complete `results.json` / `results.toon`, `query.md`, and optional `response.md`.
- Token offload contract: MCP responses stay compact but include counts, source warnings, artifact summary, audit status, read order, and retrieval hints so agents can answer first and read artifacts repeatedly.
- Remote/sandbox retrieval: artifact locators expose `artifact_uri`-based read commands, available files, paging metadata, and local path redaction by default.
- Performance/import hardening: added complexity/import-surface audits, lazy package barrels, and targeted optimizations in aggregation, cache/session, pipeline, export, fulltext, and async cleanup paths.
- Docs/site/MEM sync: README, tools usage guide, advanced workflows, generated docs-site content, CHANGELOG, and memory-bank updated for release.
- Quality gate: non-integration pytest (`3403 passed, 21 skipped, 30 deselected`), Ruff, Ruff format, mypy, async-test checker, MCP tool count, and lockfile check passed.

### 2026-05-14: v0.5.12 - LLM Wiki Compatibility + PICO Handoff
- Stable LLM wiki export: `save_literature_notes` writes wiki/Foam notes with stable PMID/DOI/PMCID/fallback targets and reports `wiki_validation`.
- Unified search handoff: PMID-backed `unified_search` results now suggest `save_literature_notes(pmids="last", note_format="wiki")`.
- PICO handoff: the then-public `parse_pico` validated agent-provided P/I/C/O and returned a runnable `template: pico` backend pipeline. v0.7.0 later replaced that public surface with `validate_pico_plan`.
- Docs/site sync: README, usage/user guides, generated docs-site content, and agent harness guidance were aligned.
- Quality gate: full pytest (`3379 passed, 31 skipped`), mypy, async-test checker, Ruff, and docs-site JavaScript syntax checks passed.

### 2026-04-29: v0.5.7 — Pipeline Persistence + Local Literature Notes
- ✅ **Guided local note export** — added `save_literature_notes` for wiki/Foam/Markdown/MedPaper-style notes with citation frontmatter, triage sections, index notes, and CSL JSON sidecars
- ✅ **Pipeline filter diagnostics** — reports now show filter before/after counts, full exclusion reasons, article type mappings, warnings, and excluded examples
- ✅ **Pipeline structured output** — `output.format: json` and `output_format="json"` now return structured pipeline JSON with articles and per-step metadata
- ✅ **Pipeline authoring controls** — added `globals`, `variables`, `dry_run`, and ancestor-only `stop_at`, with saved-pipeline roundtrip coverage
- ✅ **Zotero boundary** — documented Zotero Keeper as an external integration that consumes RIS/CSL/JSON/wiki exports instead of living in PubMed MCP core
- ✅ **Quality gate** — Ruff, mypy, async-test checker, full pytest (`3236 passed, 34 skipped`), MCP tool count (`45`), docs generation, and diff whitespace checks passed

### 2026-04-24: v0.5.6 — Integrated Local Feature Work + Release Candidate
- ✅ **Integrated local workspace feature set** — committed local changes on `codex/integrate-local-v0.5.6` and confirmed reachable remote release/feature branches were already merged
- ✅ **Reference verification MCP surface** — added `verify_reference_list` backed by PMID, DOI, ECitMatch, and title-search evidence paths
- ✅ **AI workspace harness** — added shared `AGENTS.md`, Cline rules/workflows, Copilot guidance sync, VS Code extension recommendations, and setup harness docs/scripts
- ✅ **Source/runtime hardening** — strengthened Entrez runtime isolation, retry/timeout behavior, source-client contracts, fulltext/browser fallback boundaries, and cache cleanup
- ✅ **Release metadata** — bumped package metadata and lockfile to 0.5.6 with changelog coverage
- ✅ **Local quality gate** — Ruff, mypy, async-test checker, full pytest (`3207 passed, 34 skipped`), MCP smoke, and `uv build` passed
- ✅ **CI timing stabilization** — converted high-pressure Entrez runtime isolation tests from runner-specific throughput budgets to cross-platform serialization behavior checks

### 2026-04-24: v0.5.5 — Windows Python 3.14 MCP Startup Fix
- ✅ **Removed native DI runtime dependency** — `dependency-injector` is no longer required or imported by the MCP startup path
- ✅ **Pure-Python application container** — preserved config, singleton, override, and reset provider behavior used by server/tests
- ✅ **Package metadata verified** — built wheel/sdist do not declare `dependency-injector`
- ✅ **Quality gate** — `3207 passed, 34 skipped`; mypy and async-test checker passed

### 2026-04-03: v0.5.0 — Docs Site + Source Contracts + Release Hardening
- ✅ **Docs site** — `docs/index.html`, generated `docs/site-content/*`, `docs/site.css`, `docs/site.js`, `scripts/build_docs_site.py`
- ✅ **Source contracts** — `docs/SOURCE_CONTRACTS.md` clarifies provenance, rate policy, credentials, and OA/fulltext promises
- ✅ **Shared adapter/cache substrate** — `shared/source_contracts.py` + `shared/cache_substrate.py`
- ✅ **Image/timeline policy extraction** — split advisor and timeline heuristics into policy/diagnostics modules
- ✅ **Release hardening** — `scripts/run_mutation_gate.py`, `tests/test_mcp_protocol_in_memory.py`, local MCP RC validation
- ✅ **0.5.0 blockers fixed** — BaseAPIClient `params=` override mismatch, Unpaywall email fallback, Windows lifecycle log encoding
- ✅ **Quality gate** — `uv run pre-commit run --all-files` 全綠

### 2026-03-17: v0.4.5 — MCP SDK 擴充 + 反重造輪子重構
- ✅ **MCP Context 擴充** — chronicle tools 與 Europe PMC fulltext/text-mining 支援 progress/log
- ✅ **Dynamic session resources** — `session://last-search*` 讓 Agent 直接讀取最近搜尋狀態
- ✅ **MCP 版本下限收斂** — `mcp>=1.23.3`
- ✅ **PubTatorClient 重構** — 改走 `BaseAPIClient` 共用 transport
- ✅ **iCite cache 收斂** — 改用 `cachetools.TTLCache`
- ✅ **Docs synced** — README / README.zh-TW / copilot-instructions / CHANGELOG
- ✅ **驗證完成** — 2970 passed, 28 skipped；ruff / mypy / async-test-checker 全綠

### 2026-02-25: v0.4.4 — Article Figure Extraction
- ✅ **New MCP tool**: `get_article_figures` — extract figure metadata + image URLs + PDF links from PMC articles
- ✅ **Multi-source fallback**: Europe PMC XML → PMC efetch XML → BioC JSON
- ✅ **Domain entity**: `ArticleFigure` + `ArticleFiguresResult` dataclasses
- ✅ **Infrastructure**: `FigureClient(BaseAPIClient)` with JATS XML parsing, BioC JSON parsing
- ✅ **SSRF protection**: URL validation against allowed academic domain whitelist
- ✅ **get_fulltext enhancement**: `include_figures=True` for inline figure data
- ✅ **58 new tests**: entity (10) + client (30) + tools (18)
- ✅ **40 tools / 15 categories** (new category: 圖表擷取)
- ✅ **Spec document**: `docs/MCP_Visual_Data_Retrieval_Spec.md` v1.1.0

### 2026-02-14: v0.3.10 — mypy 168→0 + Pre-commit 41 hooks
- ✅ **mypy 0 errors** — 168→0 under `strict = true` (91 source files clean)
- ✅ **2 real bugs found** — missing `await` in fulltext_download.py (S2 & OpenAlex PDF links broken)
- ✅ **1 logic bug found** — timeline_builder.py citation_data iteration
- ✅ **Pre-commit 41 hooks** — bandit, vulture, deptry, semgrep + 7 custom hooks
- ✅ **`from __future__ import annotations`** — enforced across all files
- ✅ **Tests: 2372 passed, 0 failed, 27 skipped** in ~47s

### 2026-02-14: v0.3.9 — 品質嚴格化 + Pre-commit + Noqa 消除
- ✅ **ruff `select=["ALL"]`** — 最嚴格 lint，~40 justified ignores
- ✅ **mypy `strict=true`** — 326→176 errors with module overrides
- ✅ **Pre-commit 17 hooks** — ruff, mypy, file-hygiene, async-test, tool-sync, evolution-cycle
- ✅ **`# noqa` 消除 18→9** — 9 個根因修復（field rename, dead code removal, logging）
- ✅ **MCP profiling system** — `profiling.py` + 20 tests
- ✅ **pytest-xdist** — 多核測試 `-n 4 --timeout=60`（~47s）
- ✅ **最終結果: 2400 passed, 0 failed, 27 skipped**

### 2026-02-12: v0.3.8.1 — Algorithm Innovation Research
- ✅ **Algorithm Innovation Research Document** — 60% API wrapping 誠實評估
- ✅ **ROADMAP Phase 10.5** — BM25/RRF/PRF, Main Path/Burst/MeSH, SPECTER2/PubMedBERT

### 2026-02-10: v0.3.8 — QueryValidator + JournalMetrics + Preprint
- ✅ **QueryValidator** — PubMed query 語法驗證 + 自動修正
- ✅ **Journal Metrics** — OpenAlex h-index, impact tier
- ✅ **Historical peer-review heuristic** — v0.3.8 曾使用 `options="all_types"`；v0.7.0 已移除這個不精確宣稱，改用明確的 `include_detected_preprints` retention policy 與 `preprints` source crawl policy
- ✅ **Preprint Search** — arXiv/medRxiv/bioRxiv detection

### 2026-02-10: P2 Async-First 架構全面遷移 (v0.3.4)
- ✅ 8 source clients → httpx.AsyncClient
- ✅ 9 ncbi/ modules → asyncio.to_thread(Entrez.*)
- ✅ sources/__init__.py → 5 async functions (cross_search → asyncio.gather)
- ✅ Application layer → async (timeline_builder, image_search/service, export/links)
- ✅ 13 MCP tool files (~49 functions) → async def
- ✅ unified.py: ThreadPoolExecutor → asyncio.gather (major refactor)
- ✅ 41 files changed, +990/-872 lines

### 2026-02-09: 圖片搜尋 + Agent-Friendly 改善
- ✅ Open-i API 全參數整合 (13 params)
- ✅ ImageQueryAdvisor 擴展至 10 種 image types
- ✅ docs/IMAGE_SEARCH_API.md 完整重寫

## Doing

- No release work remains for v0.7.1. Preserve the 41-tool official-client MCP
  acceptance suite as a required gate for future registry, transport, packaging,
  Chronicle, pipeline, and Mermaid changes.

## Next

| 優先級 | 項目 | 說明 |
|:------:|------|------|
| ⭐⭐⭐ | Distributed service state | 多 worker 前先導入 shared transactional store、distributed locks、object storage 與 scheduler leader election |
| ⭐⭐ | Cross-feature source consolidation | 讓 pipeline/search/fulltext/image 最終都只經過同一 typed adapter execution policy，持續移除殘留 provider-specific orchestration |
| ⭐⭐ | Provider admission | 只有具不同 corpus、identifier 或 access path 且有 rate/provenance contract 的來源才加入 broker |
| ⭐⭐ | Session cache dedup cleanup | 評估 `ArticleCache` 與 `SessionManager.article_cache` 是否收斂成單一路徑 |
| ⭐⭐ | Algorithm innovation | 評估 BM25/RRF/PRF 等排序功能，不把無驗證 heuristics 混入目前 broker |

## Design Decisions Log

| 日期 | 決策 | 原因 |
|------|------|------|
| 2026-04-29 | v0.5.7 將 Zotero Keeper 維持為外部整合 | PubMed MCP core 應負責文獻搜尋、匯出與本機 note 產物；Zotero 匯入、去重與 library policy 由外部 client 處理，避免 core 綁定特定 VSIX 行為 |
| 2026-04-29 | PICO/pipeline 結構化功能優先做 diagnostics + guided export，而非把 note storage 做成大型內部機制 | PICO 是結構化臨床議題，最有價值的是可審計的搜尋/篩選/匯出脈絡；保留輕量 `save_literature_notes` 比複製完整外部 repo 存檔機制更可維護 |
| 2026-04-24 | v0.5.6 先用 integration branch 跑完整 local/CI，再 merge/tag/publish | 這次包含大型本地 feature set 與多來源 runtime hardening，先保留 branch gate 比直接在 master 發版更容易定位回歸 |
| 2026-04-24 | v0.5.5 移除 `dependency-injector` runtime dependency | Windows Python 3.14 使用者安裝後啟動 MCP server 時因 native DLL import failed 崩潰；本專案只需要小型 provider 行為，純 Python container 更穩定 |
| 2026-03-17 | v0.4.5 MCP SDK 擴充 + anti-reinvention | 長任務工具回報 progress/log，並收斂重複 transport/cache 基礎設施 |
| 2026-02-14 | v0.3.9 品質嚴格化 | ruff ALL + mypy strict + pre-commit 17 hooks + noqa 18→9 |
| 2026-02-10 | 全面 async-first | 使用者選擇「立即重構 P2 + 加規則」 |
| 2026-02-10 | Entrez → asyncio.to_thread | BioPython sync library, wrap 不改源碼 |
| 2026-02-09 | Agent 翻譯，MCP 偵測 | Agent 有 LLM 能力 |
