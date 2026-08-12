# System Patterns

> 📌 此檔案記錄專案中使用的模式和慣例，新模式出現時更新。

## 🏗️ 架構模式

### Async-First Architecture (2026-02-10)
```
所有 IO 操作必須使用 async/await:
- HTTP: httpx.AsyncClient (取代 urllib/requests)
- NCBI Entrez: await asyncio.to_thread(Entrez.*)
- Local sync stores: await asyncio.to_thread(store.*)
- Rate limit: await asyncio.sleep() (取代 time.sleep)
- 並行: asyncio.gather() (取代 ThreadPoolExecutor)
- MCP tools: async def (MCP Python SDK v2 原生支援)
```

`async def` alone does not make a path non-blocking. Filesystem-backed
Chronicle/session/pipeline/artifact operations must be moved to
`asyncio.to_thread` when invoked from async application or MCP code.

### DDD Dependency Direction

```text
presentation -> application -> domain
infrastructure -------> application/domain contracts
```

- MCP tools validate/adapt requests and delegate; they do not own Chronicle,
  search, export, pipeline, or persistence business rules.
- Domain entities and rules do not import MCP/HTTP presentation modules.
- Infrastructure errors are normalized before they become application results;
  an error sentinel must never be mapped into a paper/evidence entity.

### Research Chronicle Projection Pattern (2026-08-12)

```text
authoritative Chronicle snapshot
        |
        +--> audit / diff / narrative / graph
        `--> structured Mermaid projection
                  `--> rich -> safe -> minimal
```

- Canonical Mermaid is `flowchart LR` with a horizontal year-anchor spine;
  date precision governs stable global and within-branch entry order.
- Repeated MeSH/keyword signals create semantic branches only when at least two
  supported branches cover 60% of events; otherwise disclose
  `research_stage_fallback`. One paper has one primary branch; matched signals
  and cross-links preserve overlap.
- Branches are not causal lineage. Definite chronology may produce `PRECEDES`;
  ordering alone never produces `SUPERSEDES`.
- Absence from a later retrieval is `not_observed_in_revision`.
- Selection caps preserve earliest/latest evidence, explicit landmarks,
  citations, and temporal spread before filling remaining slots.

### Deterministic Mermaid Repair Pattern (2026-08-12)

- Build graphs from structured nodes/edges; never interpolate untrusted labels
  directly into Mermaid syntax.
- Normalize line breaks, directives, control/bidi characters, invalid Unicode,
  identifiers, quotes, and HTML-sensitive text.
- Repair duplicate ids, orphans, self-loops, cycles, malformed rows, invalid
  dates, and output-size limits deterministically.
- Surface corrections, warnings, omissions, fallback tier, and structural
  validation status. A fallback must remain valid and must not silently claim
  completeness.
- Pin a real Mermaid parser/renderer in CI and render runtime fixtures plus
  repository/documentation code blocks to SVG.

### Immutable Revision + Rebuildable Index Pattern (2026-08-12)

```text
atomic immutable revision JSON  <-- authority
              |
              `--> index.json   <-- rebuildable cache
```

- Use stable evidence identity (PMID, then DOI, then bibliographic fallback)
  independent of mutable year/classifier output.
- Protect append/rebuild paths with process/thread locks and atomic file
  replacement; reject non-finite JSON values.
- Recover missing, corrupt, or stale indices from revision files.
- A post-commit index-refresh failure must not erase or falsely fail an already
  authoritative revision.
- Refuse to publish an empty evidence revision.

### MCP Tool 模式
```
MCP client → presentation tool adapter → application service → domain
                                      `→ infrastructure adapter → External API
```
- Tool 只處理 schema、request adaptation、progress/log bridge 與 response formatting
- 搜尋、Chronicle、pipeline、export 與持久化規則屬於 application/domain
- Entrez 與其他來源藏在 infrastructure adapter 後；presentation 不直接擁有來源邏輯
- 需要重用的搜尋結果透過 application-owned SearchSession 快取

### 多來源整合模式
```
PubMed (Primary) ←→ Semantic Scholar / OpenAlex (Supplementary)
```
- PubMed 為主要來源
- 其他來源提供額外資訊（引用數、影響力）

### Shared Transport Pattern (2026-03-17)
```
External API Client → BaseAPIClient → httpx.AsyncClient
```
- 外部來源 client 優先重用 `BaseAPIClient`
- 共用 rate limiting、429 retry、circuit breaker、client lifecycle
- 禁止在單一 client 內重複手寫 request/retry/backoff loop，除非 API 有無法共用的特殊協定

### Shared Cache Pattern (2026-03-17)
```
TTL / LRU cache → cachetools.TTLCache
```
- 通用 TTL cache 優先使用 `cachetools`
- 僅在需要 domain-specific adapter 時外包一層薄封裝
- 避免再新增第二套手寫 timestamp + eviction cache

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
| MCP Tool | snake_case 動詞 | `unified_search`, `parse_pico` |
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
- 參數使用嚴格 JSON Schema；枚舉/範圍明確，未知欄位拒絕
- 應用層再次驗證 topic、year、limit、positive ASCII PMID 與 revision
- 回傳 structured content/errors；Mermaid code fence 僅包裝已驗證的純 `.mmd`

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
*Last updated: 2026-08-12 — v0.6.2 Chronicle patterns*
