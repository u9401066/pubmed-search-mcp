# Active Context

## Current Focus

- Released **v0.6.0**. Five landed cycles: (1) MCP Python SDK v1 -> v2 migration, (2) Research Chronicle implemented and the three timeline tools consolidated into it, (3) multi-agent service mode with per-tenant isolation and bearer auth, (4) durable-storage-requires-auth security model, (5) shared per-service upstream rate limiting.

## Validation Snapshot

- `uv run pytest -q --no-header -p no:randomly --deselect tests/test_fulltext_urls.py`: 3601 passed, 33 skipped
- `uv run mypy src/ tests/`: passed
- `uv run python scripts/check_async_tests.py`: passed
- `uv run ruff check .`: passed
- `uv run python scripts/count_mcp_tools.py`: 45 tools / 16 categories, validation passed
- `uv run pre-commit run --all-files`: passed (only `no-commit-to-branch` blocks, as expected on master)
- Mutation-checked: 10 deliberate regressions across tenancy, rate limiting, and the tool registry were all caught by the suite.

## Session Notes

- Migrated to `mcp>=2,<3` (protocol 2026-07-28): `FastMCP` -> `MCPServer`, transport keywords moved off the constructor into `build_asgi_app()`, experimental MCP tasks removed with the spec, in-memory tests now use `Client(server)`.
- Research Chronicle shipped: `domain/entities/chronicle.py`, `application/chronicle/`, and two MCP tools `build_research_chronicle` / `read_research_chronicle`. Chronology is the primary axis; branches are a secondary projection of the same snapshot.
- `build_research_timeline`, `analyze_timeline_milestones`, and `compare_timelines` were retired into the chronicle. `application/timeline/` is unchanged and now feeds the chronicle assembler.
- Multi-agent service mode: `shared/tenancy.py`, `application/session/registry.py`, `infrastructure/auth/`, plus tenancy middleware and an auxiliary-API guard. Previously every client shared one process-wide `SessionManager`, so concurrent agents read each other's data.
- **Durable storage requires authentication.** `mcp-session-id` changes on every reconnect and is client-supplied, so it isolates without authenticating. Chronicle / pipeline / notes tools refuse such callers; ephemeral tenants get an in-memory session manager and never create a directory.
- **One shared rate-limit budget per upstream.** `BaseAPIClient` keyed its limiter by `id(self)`; ad-hoc client construction therefore multiplied the real request rate. Circuit breakers deliberately stay per instance.
- Shared asyncio primitives are keyed by the event loop object via `WeakKeyDictionary`, never `id(loop)` (ids get recycled and handed stale state to new loops).
- Tenancy invariants that are easy to break are recorded in `.clinerules/70-pubmed-mcp-tools.md` and enforced by the `tenant-scoped-storage` hook.
- Added `pubmed_search.api` for external Python callers: `PubMedSearchClient`, `PubMedSearchConfig`, and `UnifiedSearchResult`.
- Added `pubmed_search.application.unified` service contracts and a presentation `unified_runner` so MCP `unified_search` and the SDK can share the runtime path without making SDK imports load MCP.
- Added packaged `pubmed-search-mcp-http` entrypoint; `run_server.py` remains a source-tree development wrapper.
- Documentation now distinguishes three contracts: MCP tool surface, Python SDK facade, and HTTP MCP server CLI / auxiliary read-only HTTP APIs.
- `unified_search` artifacts now use a `research-artifact/v1` envelope: `audit.json`, `query_strategy.json`, `results.json` / `results.toon`, `query.md`, and optional `response.md`.
- MCP responses stay compact but include counts, warnings, `artifact_summary`, audit status, and retrieval hints so agents can answer first and page through artifacts.
- Artifact locators now include schema version, audit status, read order, URI-first read hints, and remote/sandbox-friendly paging metadata.
- Repo optimization work added complexity/import-surface reports, lazy import surfaces, cache/aggregation/pipeline/export/fulltext hardening, and regression coverage.
- README, generated docs site content, CHANGELOG, and memory-bank are synchronized for v0.5.15.

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

- **v0.5.7 release** — publish pipeline diagnostics, structured output, local literature note export, and AI-client guidance updates

## 📊 測試結果

- `uv run ruff check`: ✅ passed
- `uv run mypy src/ tests/`: ✅ passed
- `uv run python scripts/check_async_tests.py`: ✅ passed
- `uv run pytest -q`: ✅ 3236 passed, 34 skipped
- `uv run python scripts/count_mcp_tools.py -q`: ✅ 45
- `git diff --check`: ✅ passed

## ✅ 已完成本 session

### v0.5.7: Pipeline Persistence + Local Literature Notes
- **Local note export**: added `save_literature_notes` with wiki/Foam/Markdown/MedPaper-style layouts, citation frontmatter, CSL JSON sidecars, and index notes.
- **Pipeline diagnostics**: added filter before/after counts, full exclusion reasons, article type mappings, warnings, and excluded examples.
- **Structured pipeline output**: `output.format: json` and `output_format="json"` now return structured pipeline JSON with articles and per-step metadata.
- **Pipeline controls**: added `globals`, `variables`, `dry_run`, and ancestor-only `stop_at`; saved pipeline serialization preserves globals/variables.
- **Agent/docs alignment**: updated AGENTS/Copilot/Cline/Claude skills/docs site guidance and kept Zotero Keeper as an external integration boundary.

### v0.5.6: Integrated Local Feature Work + Release Candidate
- **Branch integration**: created `codex/integrate-local-v0.5.6`, committed the local workspace feature set, and merged all reachable remote release/feature branches; they were already contained in the current history.
- **New MCP capability**: added `verify_reference_list` for PubMed-backed reference-list verification using PMID, DOI, ECitMatch, and title-search evidence.
- **Agent workspace assets**: added shared `AGENTS.md`, Cline rules/workflows, Copilot guidance sync, VS Code extension recommendations, and setup harness docs/scripts.
- **Runtime hardening**: tightened Entrez isolation/retry behavior, source-client contracts, fulltext/browser fallback boundaries, cache cleanup, and MCP callback wrappers.
- **Release metadata**: bumped package metadata to 0.5.6 and documented the integrated release scope.

### v0.5.5: Windows Python 3.14 Startup Fix
- **Root cause**: Windows installs using Python 3.14 failed before MCP startup because `dependency-injector` loaded a native DLL extension during `pubmed_search.container` import.
- **Fix**: Replaced the external DI dependency with a pure-Python provider layer preserving config, singleton, override, and reset behavior.
- **Release scope**: version bump to 0.5.5, changelog update, lockfile metadata update, package build metadata verification.

### v0.5.0: Release Candidate Hardening + Docs Site
- **Docs site**: `docs/index.html` + generated `docs/site-content/*` + `scripts/build_docs_site.py`
- **Source contracts**: `docs/SOURCE_CONTRACTS.md` clarifies provenance, rate policy, credentials, and OA/fulltext promises
- **Shared abstractions**: `shared/source_contracts.py` + `shared/cache_substrate.py`
- **Policy extraction**: image search and timeline scoring/detection split into smaller policy/diagnostics modules
- **Release hardening**: deterministic mutation gate, in-memory MCP protocol test, local MCP RC validation, BaseAPIClient param-path fix, Unpaywall email fallback fix

## 📈 Version History
- v0.5.7: pipeline diagnostics + structured JSON output + local literature notes + Zotero boundary docs
- v0.5.6: integrated local feature work; reference verification tool; AI workspace harness; source/runtime hardening
- v0.5.5: Windows/Python 3.14 MCP startup fix; removed native dependency-injector runtime dependency
- v0.5.0: docs site + source contracts + shared adapter/cache substrate + release hardening
- v0.4.5: MCP SDK expansion + anti-reinvention cleanup
- v0.4.4: Article Figure Extraction (40 tools / 15 categories)
- v0.4.3: Landmark Paper Detection + Research Lineage Tree
- v0.3.10: mypy 168→0 + pre-commit 41 hooks
- v0.3.9: 品質嚴格化 + pre-commit 17 hooks + noqa 消除
- v0.3.8: QueryValidator + JournalMetrics + preprint detection
- v0.3.5: 品質強化 + 測試零失敗
- v0.3.4: async-first migration

## 🔜 下一步 (low priority)
- Watch v0.5.15 GitHub Actions / PyPI publish workflow after tag push
- Algorithm innovation implementation (BM25/RRF/PRF)

---
*Last updated: 2026-06-05 - v0.5.15 release*
