# Progress (Updated: 2026-02-09)

## Done

### 2026-02-09: 圖片搜尋 + Agent-Friendly 改善
- ✅ Open-i API 全參數整合 (13 params) - commit `46df404`
- ✅ Agent-friendly 非英文偵測 - commit `ac40d6d`
  - NON_LATIN_PATTERN 偵測 CJK/Cyrillic/Arabic/Thai
  - Tool docstring 新增 CRITICAL LANGUAGE REQUIREMENT
  - Instructions 新增圖片搜尋工作流
  - Vision tool 自動搜尋引導
- ✅ 設計決策：Agent vs MCP 職責劃分
  - 翻譯：Agent 負責 (有 LLM 能力)
  - MCP：偵測 + 警告，不翻譯
- ✅ ImageQueryAdvisor 擴展至 10 種 image types
- ✅ docs/IMAGE_SEARCH_API.md 完整重寫 (Swagger 規格)
- ✅ ROADMAP 更新：設計原則、Phase 4 完成、版本歷程
- ✅ 152 測試全部通過

## Doing

(無進行中任務)

## Next

| 優先級 | 項目 | 說明 |
|:------:|------|------|
| ⭐⭐⭐⭐⭐ | Token 效率優化 | `output_format="compact"` 省 60% token |
| ⭐⭐⭐⭐⭐ | 研究時間軸 | 里程碑偵測、知識演化追蹤 |
| ⭐⭐⭐⭐ | PRISMA 流程追蹤 | Systematic Review 工作流 |
| ⭐⭐⭐ | 智能引用 API | Semantic Scholar Intent, OpenAlex Concepts |

## Design Decisions Log

| 日期 | 決策 | 原因 |
|------|------|------|
| 2026-02-09 | Agent 翻譯，MCP 偵測 | Agent 有 LLM 能力，MCP 維護字典不實際 |
| 2026-02-09 | 模式選擇由 Agent 決定 | Agent 理解用戶意圖，MCP 提供工具選項 |
