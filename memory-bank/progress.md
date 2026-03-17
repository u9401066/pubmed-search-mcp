# Progress (Updated: 2026-03-17)

## Done

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
- ✅ **Peer Review Filter** — `peer_reviewed_only` parameter
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
- (none — ready for tag v0.4.5)

## Next

| 優先級 | 項目 | 說明 |
|:------:|------|------|
| ⭐⭐⭐ | Session cache dedup cleanup | 評估 `ArticleCache` 與 `SessionManager.article_cache` 是否收斂成單一路徑 |
| ⭐⭐⭐ | ARCHITECTURE.md 更新 | 仍顯示舊的目錄結構 |
| ⭐⭐ | Algorithm innovation impl | BM25/RRF/PRF 等算法實作 |
| ⭐⭐ | clinical_trials + preprints → async httpx | 仍用 sync httpx |

## Design Decisions Log

| 日期 | 決策 | 原因 |
|------|------|------|
| 2026-03-17 | v0.4.5 MCP SDK 擴充 + anti-reinvention | 長任務工具回報 progress/log，並收斂重複 transport/cache 基礎設施 |
| 2026-02-14 | v0.3.9 品質嚴格化 | ruff ALL + mypy strict + pre-commit 17 hooks + noqa 18→9 |
| 2026-02-10 | 全面 async-first | 使用者選擇「立即重構 P2 + 加規則」 |
| 2026-02-10 | Entrez → asyncio.to_thread | BioPython sync library, wrap 不改源碼 |
| 2026-02-09 | Agent 翻譯，MCP 偵測 | Agent 有 LLM 能力 |
