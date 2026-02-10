# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

- **P2 Async-First 架構遷移** — 全面轉換為 async/await，httpx.AsyncClient + asyncio.to_thread(Entrez)

## 📝 進行中的變更

| 層級 | 變更內容 | 狀態 |
|------|----------|------|
| **Infrastructure/sources/** (8 files) | urllib.request → httpx.AsyncClient, time.sleep → asyncio.sleep | ✅ |
| **Infrastructure/ncbi/** (9 files) | Entrez → asyncio.to_thread(Entrez.*), requests → httpx.AsyncClient | ✅ |
| **Infrastructure/sources/__init__.py** | 5 functions async, cross_search → asyncio.gather() 並行 | ✅ |
| **Application layer** (3 files) | timeline_builder, image_search/service, export/links → async | ✅ |
| **MCP tools** (13 files, ~49 functions) | 全部 async def, ThreadPoolExecutor → asyncio.gather | ✅ |
| **Tool tests** (7 files) | async def + await + @pytest.mark.asyncio | ✅ |
| **Non-tool tests** (43 files, 492 failures) | 仍為 sync, 呼叫 async 方法未 await | ❌ 待修 |

## ✅ 已完成本 session

- 全部 8 個 source clients: urllib → httpx.AsyncClient
- 全部 9 個 ncbi/ 模組: Entrez → asyncio.to_thread
- sources/__init__.py: 5 functions → async (cross_search 用 asyncio.gather)
- Application layer: 3 files → async
- 13 個 MCP tool 檔案 (~49 functions) → async def
- unified.py: ThreadPoolExecutor → asyncio.gather (重大重構)
- openurl.py: urllib → httpx.AsyncClient for _test_resolver_url
- europe_pmc.py: 移除 asyncio.run workaround
- 7 個 tool test files → async (test_citation_tree_tools, test_europe_pmc_tools, test_export_tools, test_openurl_tools, test_strategy_tools, test_timeline_tools, test_unified_tools)
- ruff check + format: 全部通過
- 34 MCP tools / 13 categories (tool sync 通過)

## ⚠️ 已知問題

- 492/2205 測試失敗 (43 個非 tool 測試檔案仍為 sync)
- 根本原因: 測試直接呼叫 async 方法但未 await, 取得 coroutine 而非結果
- Group H 文件規則尚未新增 (CONSTITUTION.md, ARCHITECTURE.md)
- infrastructure/http/client.py 未刪除 (unused)

## 🔜 下一步

1. 修復 43 個非 tool 測試檔案 (492 failures → async def + await)
2. Group H: 新增 async-first 設計規則到 CONSTITUTION.md, ARCHITECTURE.md
3. 刪除 unused http/client.py
4. 檢查 clinical_trials.py, copilot_tools.py 是否需要 async 轉換

---
*Last updated: 2026-02-10 — P2 async migration session*