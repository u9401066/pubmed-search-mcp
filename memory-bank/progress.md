# Progress (Updated: 2026-02-10)

## Done

### 2026-02-10: v0.3.5 — 品質強化與測試零失敗
- ✅ **P0: batch.py 速率限制** — Entrez.esearch/efetch 前加 `await _rate_limit()`
- ✅ **P1: 8 source clients 429 retry** — 指數退避重試 (1s→2s→4s, max 3) + safe Retry-After 解析
- ✅ **copilot_tools.py 完整重寫** — 移除 11 個重複工具註冊，加入 async/await
- ✅ **Code Review P0/P1 修正** — 缺少的 exception handlers, 錯誤訊息, 重複 handler
- ✅ **60+ 測試檔案修復** — MagicMock→AsyncMock, with→async with, urllib/requests→httpx mocks
- ✅ **4 整合測試標記 skip** — test_integration, test_advanced_filters, test_citation_tree, test_perf
- ✅ **檔案衛生規範** — CONSTITUTION.md 第 7.1.1 條, copilot-instructions.md, .gitignore
- ✅ **最終結果: 2181 passed, 0 failed, 27 skipped** (107.81s)

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
- (none — ready for commit + tag)

## Next

| 優先級 | 項目 | 說明 |
|:------:|------|------|
| ⭐⭐⭐ | ARCHITECTURE.md 更新 | 仍顯示舊的 14-tool layout |
| ⭐⭐⭐ | run_copilot.py 修復 | 舊的 import 路徑 |
| ⭐⭐⭐ | run_server.py 修復 | 錯誤 import 路徑, version "0.1.18" |
| ⭐⭐ | clinical_trials + preprints → async httpx | 仍用 sync httpx |
| ⭐⭐ | 刪除 unused http/client.py | dead code |

## Design Decisions Log

| 日期 | 決策 | 原因 |
|------|------|------|
| 2026-02-10 | v0.3.5 品質強化 | 429 retry + 測試零失敗 + 檔案衛生 |
| 2026-02-10 | 全面 async-first | 使用者選擇「立即重構 P2 + 加規則」 |
| 2026-02-10 | Entrez → asyncio.to_thread | BioPython sync library, wrap 不改源碼 |
| 2026-02-09 | Agent 翻譯，MCP 偵測 | Agent 有 LLM 能力 |
