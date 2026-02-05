# Progress (Updated: 2026-02-06)

## Done

- v0.2.3 工具註冊架構重構
- 工具統計自動化腳本 scripts/count_mcp_tools.py
- v0.2.8 Research Timeline 功能 (Phase 13.1 MVP)
-   - domain/entities/timeline.py - TimelineEvent, ResearchTimeline 實體
-   - application/timeline/ - TimelineBuilder, MilestoneDetector
-   - tools/timeline.py - 6 個新 MCP 工具
-   - 里程碑偵測：FDA/EMA 批准、臨床試驗階段、Meta-Analysis 等
-   - Mermaid/JSON 視覺化輸出
- v0.2.8.1 Timeline Bug Fixes
-   - ResponseFormatter API 修正 (format_error→error, format_info→no_results)
-   - 搜尋參數修正 (max_results→limit)
-   - BioPython 類型轉換 (StringElement→int)
-   - 月份字串解析 (_parse_month: 'Jan'→1)
-   - unified_search Session 記錄修復
- v0.2.8.2 FulltextDownloader 增強 + Code Review
-   - 新增 Retry (exponential backoff, max 3 retries)
-   - 新增 Rate Limiting (asyncio.Semaphore, 5 concurrent)
-   - 新增 Streaming Download (8KB chunks)
-   - get_fulltext 新增 extended_sources 參數 (15 來源)
-   - 修復 test_package_imports.py API 簽名
-   - 修復 Mypy 型別錯誤 (session/manager.py, openurl.py)
-   - 新增 4 個全文 API (CrossRef, DOAJ, Zenodo, PubMed LinkOut)

## Doing

- Git commit + push v0.2.8.2

## Next

- Phase 14 - Research Gap Detection 實作
- Phase 13.2 - NLP 增強里程碑偵測
- 提升測試覆蓋率到 50%+
- PRISMA flow tracking
- Evidence level classification
