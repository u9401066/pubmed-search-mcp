# Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2025-01 | 採用 MCP 協定作為主要介面 | AI Agent 工具標準，支援 Claude/GPT |
| 2025-01 | 使用 Biopython Entrez 作為 NCBI 客戶端 | 成熟穩定，自動 rate limiting |
| 2025-01 | 90% 測試覆蓋率目標 | 確保程式碼品質和穩定性 |
| 2025-01 | 多來源整合 (Semantic Scholar, OpenAlex) | 補充 PubMed 的引用分析能力 |
| 2025-01 | 導入 Claude Skills 系統 | 標準化 AI 輔助開發流程 |
| 2025-01 | 導入憲法-子法架構 | 建立專案治理框架 |
| 2026-01 | Streamable HTTP 取代 SSE | Copilot Studio 不支援 SSE (deprecated Aug 2025) |
| 2026-01 | 添加 json_response 參數 | Copilot Studio 要求 Accept: application/json |
| 2026-01 | 202→200 Middleware | Copilot Studio 無法處理 202 Accepted |
| 2026-01 | Stateless HTTP 模式 | Microsoft 官方 MCP 範例使用 `sessionIdGenerator: undefined` |
| 2026-01 | Python 3.12 升級 | 支援 Python 3.12+ 泛型語法，使用 uv 管理虛擬環境 |

---

## [2026-01] Microsoft Copilot Studio 整合

### 背景
用戶希望在 Word Copilot 中使用 PubMed Search MCP 進行文獻搜尋。

### 技術挑戰
1. SSE transport 已於 2025-08 deprecated，需改用 Streamable HTTP
2. Copilot Studio 發送 `Accept: application/json` 而非 `text/event-stream`
3. MCP SDK 對 notification 回傳 202 Accepted，Copilot Studio 無法處理

### 解決方案
1. 使用 FastMCP 的 `streamable_http_app()` 
2. 添加 `json_response=True` 參數
3. 創建 CopilotStudioMiddleware 轉換 202→200
4. 使用 ngrok 固定網域提供公開 HTTPS 端點

### 相關檔案
- `run_copilot.py`: 專用啟動器
- `copilot-studio/`: 整合文檔
- `scripts/start-copilot-ngrok.sh`: ngrok 腳本

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
