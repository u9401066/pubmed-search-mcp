# Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2025-01 | 採用 MCP 協定作為主要介面 | AI Agent 工具標準，支援 Claude/GPT |
| 2025-01 | 使用 Biopython Entrez 作為 NCBI 客戶端 | 成熟穩定，自動 rate limiting |
| 2025-01 | 90% 測試覆蓋率目標 | 確保程式碼品質和穩定性 |
| 2025-01 | 多來源整合 (Semantic Scholar, OpenAlex) | 補充 PubMed 的引用分析能力 |
| 2025-01 | 導入 Claude Skills 系統 | 標準化 AI 輔助開發流程 |
| 2025-01 | 導入憲法-子法架構 | 建立專案治理框架 |

---

## [2025-01] 採用 MCP 協定

### 背景
需要讓 AI Agent 能使用 PubMed 搜尋功能。

### 選項
1. REST API - 傳統但需要額外整合
2. MCP Server - AI Agent 原生支援
3. CLI Tool - 簡單但不適合 Agent

### 決定
採用 MCP Server，支援 SSE 和 STDIO 兩種傳輸方式。

### 理由
- MCP 是 Anthropic 推動的標準
- Claude Desktop 原生支援
- 可透過 SSE 支援遠端存取

---

## [2025-01] 90% 測試覆蓋率

### 背景
確保程式碼品質，為發布到 PyPI 做準備。

### 決定
設定 90% 測試覆蓋率為釋出標準。

### 理由
- 高覆蓋率減少回歸 bug
- 測試即文檔
- 增加使用者信心

### 結果
達成 90% 覆蓋率，411 個測試通過。

---

## [2025-01] 導入治理框架

### 背景
從 template-is-all-you-need 導入開發治理框架。

### 導入內容
- CONSTITUTION.md (專案憲法)
- .github/bylaws/ (4 個子法)
- .claude/skills/ (13 個 Skills)
- memory-bank/ (7 個記憶檔案)

### 理由
- 標準化 AI 輔助開發流程
- 跨對話記憶保持專案脈絡
- Skills 自動化常見任務
