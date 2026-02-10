# System Patterns

> 📌 此檔案記錄專案中使用的模式和慣例，新模式出現時更新。

## 🏗️ 架構模式

### Async-First Architecture (2026-02-10)
```
所有 IO 操作必須使用 async/await:
- HTTP: httpx.AsyncClient (取代 urllib/requests)
- NCBI Entrez: await asyncio.to_thread(Entrez.*)
- Rate limit: await asyncio.sleep() (取代 time.sleep)
- 並行: asyncio.gather() (取代 ThreadPoolExecutor)
- MCP tools: async def (FastMCP 原生支援)
```

### MCP Tool 模式
```
MCP Server → Tools → Entrez/Sources → External APIs
```
- 每個 Tool 是獨立的 MCP function
- Tools 組合使用 Entrez 模組
- 結果透過 SearchSession 快取

### 多來源整合模式
```
PubMed (Primary) ←→ Semantic Scholar / OpenAlex (Supplementary)
```
- PubMed 為主要來源
- 其他來源提供額外資訊（引用數、影響力）

## 🛠️ 設計模式

### Session Pattern (SearchSession)
- 用於快取搜尋結果
- 支援 "last" 關鍵字引用上次結果
- 減少重複 API 呼叫

### Strategy Pattern (Search Strategies)
- `comprehensive`: 多角度搜尋
- `focused`: 高精準度 (RCT filter)
- `exploratory`: 廣泛搜尋

### Builder Pattern (Query Building)
- generate_search_queries 回傳建構材料
- Agent 決定如何組合查詢

## 📝 命名慣例

| 類型 | 慣例 | 範例 |
|------|------|------|
| MCP Tool | snake_case 動詞 | `search_literature`, `parse_pico` |
| Entrez Function | 動詞_名詞 | `search_pubmed`, `fetch_details` |
| Module | 單數名詞 | `search.py`, `citation.py` |
| Test | test_模組_功能 | `test_search_basic` |

## 📚 程式碼慣例

### Python
- 使用 `snake_case` 命名
- 檔案名全小寫
- 類別使用 `PascalCase`
- 優先使用 type hints
- async/await 用於 MCP server

### 測試
- 測試檔案以 `test_` 開頭
- 使用 pytest markers: `@pytest.mark.integration`
- Mocking 外部 API 呼叫

### MCP Tools
- 每個 tool 有獨立的 docstring
- 參數使用 JSON Schema
- 回傳格式統一為 JSON string

## 🔧 API 使用模式

### NCBI Rate Limiting
```python
# 無 API Key: 3 req/sec
# 有 API Key: 10 req/sec
Entrez.email = "user@example.com"
Entrez.api_key = "your_key"
```

### 錯誤處理
```python
try:
    result = search_pubmed(query)
except HTTPError as e:
    # 429: Rate limit → 等待重試
    # 400: Bad query → 返回錯誤訊息
```

---
*Last updated: 2025-01-XX*