# Progress (Updated: 2026-02-10)

## Done

### 2026-02-10: P2 Async-First 架構全面遷移
- ✅ 8 source clients → httpx.AsyncClient (core, crossref, unpaywall, openi, europe_pmc, openalex, semantic_scholar, ncbi_extended)
- ✅ 9 ncbi/ modules → asyncio.to_thread(Entrez.*) (base, search, citation, batch, strategy, utils, icite, pdf, citation_exporter)
- ✅ sources/__init__.py → 5 async functions (cross_search → asyncio.gather)
- ✅ Application layer → async (timeline_builder, image_search/service, export/links)
- ✅ 13 MCP tool files (~49 functions) → async def
- ✅ unified.py: ThreadPoolExecutor → asyncio.gather (major refactor)
- ✅ openurl.py: urllib → httpx.AsyncClient
- ✅ europe_pmc.py: removed asyncio.run workaround
- ✅ 7 tool test files → async
- ✅ ruff check + format pass; 41 files changed, +990/-872 lines

### 2026-02-09: 圖片搜尋 + Agent-Friendly 改善
- ✅ Open-i API 全參數整合 (13 params) - commit `46df404`
- ✅ Agent-friendly 非英文偵測 - commit `ac40d6d`
- ✅ ImageQueryAdvisor 擴展至 10 種 image types
- ✅ docs/IMAGE_SEARCH_API.md 完整重寫
- ✅ ROADMAP 更新：設計原則、Phase 4 完成

## Doing

- 🔄 修復 43 non-tool test files (492 failures due to missing await)

## Next

| 優先級 | 項目 | 說明 |
|:------:|------|------|
| ⭐⭐⭐⭐⭐ | 修復 43 test files | async def + await (492 failures) |
| ⭐⭐⭐⭐⭐ | Group H 文件規則 | CONSTITUTION/ARCHITECTURE async 規則 |
| ⭐⭐⭐⭐ | Token 效率優化 | `output_format="compact"` 省 60% token |
| ⭐⭐⭐⭐ | 研究時間軸增強 | NLP 里程碑偵測 |
| ⭐⭐⭐ | 刪除 unused code | http/client.py |

## Design Decisions Log

| 日期 | 決策 | 原因 |
|------|------|------|
| 2026-02-10 | 全面 async-first | 使用者選擇「立即重構 P2 + 加規則」 |
| 2026-02-10 | Entrez → asyncio.to_thread | BioPython sync library, wrap 不改源碼 |
| 2026-02-10 | ThreadPoolExecutor → asyncio.gather | 原生 async 更高效 |
| 2026-02-09 | Agent 翻譯，MCP 偵測 | Agent 有 LLM 能力 |
