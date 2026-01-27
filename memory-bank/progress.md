# Progress (Updated: 2026-01-27)

## Done

- v0.2.3 工具註冊架構重構
  - 新增 `tool_registry.py` - 集中式工具註冊
  - 新增 `instructions.py` - AI Agent 使用說明
  - 新增 `tools/icd.py` - ICD 轉換工具模組化
  - 新增 `TOOLS_INDEX.md` - 工具索引文檔
- 工具統計自動化腳本 `scripts/count_mcp_tools.py`
  - 從 FastMCP runtime 取得真實工具數量
  - 自動更新 README, copilot-instructions, TOOLS_INDEX
- README 工具數量同步：21 → 34 tools
- Git pre-commit skill 更新（新增 tool-count-sync 步驟）

## Doing

- 發布 v0.2.3 版本

## Next

- PRISMA flow tracking
- Evidence level classification
