# Progress (Updated: 2026-01-28)

## Done

- v0.2.3 工具註冊架構重構
- 工具統計自動化腳本 scripts/count_mcp_tools.py
- **v0.2.8 Research Timeline 功能 (Phase 13.1 MVP)**
-   - domain/entities/timeline.py - TimelineEvent, ResearchTimeline 實體
-   - application/timeline/ - TimelineBuilder, MilestoneDetector
-   - tools/timeline.py - 6 個新 MCP 工具
-   - 里程碑偵測：FDA/EMA 批准、臨床試驗階段、Meta-Analysis 等
-   - Mermaid/JSON 視覺化輸出

## Doing

- 發布 v0.2.8 版本 (Research Timeline MVP)

## Next

- Phase 13.2 - NLP 增強里程碑偵測
- Phase 13.3 - 知識演化分析
- PRISMA flow tracking
- Evidence level classification
