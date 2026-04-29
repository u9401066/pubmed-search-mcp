# Progress (Updated: 2026-04-29)

## Done

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
- ✅ **FastMCP Context 擴充** — timeline tools 與 Europe PMC fulltext/text-mining 支援 progress/log
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
- ✅ **Peer Review Filter** — 預設維持 peer-reviewed 結果，可用 `options="all_types"` 放寬
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
- v0.5.7 release: segmented commits on `master`, push, then tag/publish

## Next

| 優先級 | 項目 | 說明 |
|:------:|------|------|
| ⭐⭐⭐ | Watch v0.5.7 publish workflow | tag 推上遠端後檢查 GitHub Actions / PyPI 發布狀態 |
| ⭐⭐⭐ | Session cache dedup cleanup | 評估 `ArticleCache` 與 `SessionManager.article_cache` 是否收斂成單一路徑 |
| ⭐⭐⭐ | ARCHITECTURE.md 更新 | 仍顯示舊的目錄結構 |
| ⭐⭐ | Algorithm innovation impl | BM25/RRF/PRF 等算法實作 |
| ⭐⭐ | clinical_trials + preprints → async httpx | 仍用 sync httpx |

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
