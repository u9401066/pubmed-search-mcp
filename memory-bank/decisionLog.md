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
| 2026-01-26 | **HTTP Client 重構 (中度)** | 統一錯誤處理 + 自動重試機制 |
| 2026-01-13 | **建立簡化 Copilot 工具集** | **解決 anyOf schema truncation 問題** |

---

## [2026-01-26] HTTP Client 重構 (Option B: 中度重構)

### 背景
HTTP 錯誤處理不一致：76 個 `return None` vs 4 個 `raise Exception`，無法區分錯誤類型。

### 選項評估
- **Option A (輕度)**: 只添加 logging - 治標不治本
- **Option B (中度)**: 統一異常層級 + retry - **已選擇**
- **Option C (重度)**: asyncio 改寫 - 過度工程

### 實作決策
1. **新增異常層級** (`shared/exceptions.py`):
   - `RateLimitError` - 429 API rate limit
   - `NetworkError` - 網路連線問題
   - `ServiceUnavailableError` - 503/502/504
   - `ParseError` - JSON/XML 解析失敗

2. **Retry Decorator**:
   ```python
   @with_retry(max_retries=3, base_delay=1.0)
   def http_get(url, ...):
       # Exponential backoff: 1s, 2s, 4s
   ```

3. **Backward Compatibility**:
   - 保留 `http_get_safe()`, `http_post_safe()` 返回 None
   - 新增 `http_get()`, `http_post()` 拋出異常

### 測試修復
批量修復 40+ 測試檔案的 DDD 導入路徑：
- `pubmed_search.client` → `infrastructure.http`
- `pubmed_search.entrez` → `infrastructure.ncbi`
- `pubmed_search.mcp` → `presentation.mcp_server`
- `pubmed_search.sources` → `infrastructure.sources`

### 影響
- **Before**: 322 passed, 121 failed, 15 errors
- **After**: **672 passed, 14 skipped** ✅

### 理由
- 中度重構平衡收益與風險
- 異常層級讓上層可精細處理錯誤
- Retry decorator 提高穩定性（處理暫時性網路問題）
- 保留 backward compatibility 避免破壞現有代碼

---

## [2026-01-13] Copilot Studio Schema 相容性修復

### 背景
儘管 MCP 伺服器本地測試通過，Copilot Studio 仍回報 "SystemError"。

### 根本原因發現
查閱 Microsoft 官方 troubleshooting 文檔發現 Known Issues：
1. `anyOf` 多類型陣列會導致 schema truncation
2. `exclusiveMinimum` 必須是 Boolean 非 integer
3. Reference type ($ref) 不支援
4. Enum type 被解釋為 string

**我們的問題**: 25/31 個工具使用了 `Union[int, str]`、`Union[bool, str]`、`Optional[str]` 等類型，
在 JSON Schema 中轉換成 `anyOf: [{"type": "integer"}, {"type": "string"}]`，被 Copilot Studio 截斷。

### 解決方案
建立 `src/pubmed_search/mcp/copilot_tools.py` 模組：
- 11 個簡化工具，僅使用單一類型 (`str`, `int`, `bool`)
- 內部使用 `InputNormalizer` 處理彈性輸入
- 避免任何 `anyOf`、`oneOf`、`$ref` 模式

### 新工具集
```
search_pubmed          - 搜尋 PubMed
get_article           - 取得文章詳情
find_related          - 尋找相關文章
find_citations        - 尋找引用文章
get_references        - 取得參考文獻
analyze_clinical_question - 解析 PICO
expand_search_terms   - MeSH 擴展
get_fulltext          - 取得全文
export_citations      - 匯出引用
search_gene           - 搜尋基因
search_compound       - 搜尋化合物
```

### 使用方式
```bash
# Copilot 相容模式（預設）
python run_copilot.py --port 8765

# 完整工具集（可能有問題）
python run_copilot.py --port 8765 --full-tools
```

### 驗證結果
- Schema 測試：11/11 工具無 anyOf ✅
- 連線測試：search_pubmed, get_article 正常 ✅
- 待驗證：Copilot Studio 實際連線

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
