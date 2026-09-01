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

### Strict Canonical MCP Surface (2026-08-31)

```text
41 tools / 16 categories
        |
        +--> stdio
        +--> Streamable HTTP
        `--> Copilot launcher
```

- Every launcher registers the same tools and schemas. Do not create a reduced
  compatibility registry or re-export a retired public alias.
- Action families receive one discriminated request object. In particular,
  `read_session(request=...)` and `read_research_chronicle(request=...)` reject
  legacy flat arguments and unknown fields.
- Pipeline configuration has one `output` shape. Retired `execution` input and
  loose delimiter-based PMID lists fail validation rather than being guessed.
  Template pipelines accept only `template_params`; top-level template `params`
  is not an alias for the per-step `params` mapping.
- Infer pipeline `kind` only when it is absent. A caller-supplied discriminator
  is authoritative and must reach strict union validation unchanged, including
  when it contradicts the supplied fields.
- Action/template/dependency identifiers, enums, and every action parameter are
  schema-exact. Do not fuzzy-match aliases or coerce strings, numbers, scalars,
  arrays, mappings, or explicit nulls into another accepted value. Defaults are
  for omitted documented fields; safety caps bound work without repairing
  caller intent.
- Shared response formatting sanitizes Markdown/code spans and enforces the
  global MCP output cap.

### Page, Failure, and Persistence Contracts (2026-08-31)

- A search client returns one typed page containing records, total, position,
  continuation, warnings, source, and operation. Do not pair a list result with
  mutable `_search_metadata` or a separate count side channel.
- A successful empty page is evidence that the provider answered with zero
  matches. Transport, quota, authentication, timeout, and malformed-payload
  conditions must raise or return a typed failure and remain visible to the
  orchestrator.
- Do not encode failure as an article-shaped row and filter it later.
- Session/index payloads are exact-versioned. Runtime loading validates the
  complete nested shape and never projects old history/cache fields into the
  current model.
- A pipeline run budget belongs to the whole DAG, not individual steps. Parallel
  reservation of external calls must be atomic and deadline-aware.
- Do not publish host filesystem paths to authenticated callers; convert note
  artifacts to tenant-relative logical locators at the presentation boundary.
- Persisted history is not best-effort: if a selected pipeline run cannot be
  decoded, fail the history read with a sanitized typed error.
- Treat OpenURL bases as origins/paths, never query-bearing credential stores;
  report PMID-to-DOI outage separately from a confirmed absent DOI.
- Validate provider envelopes and requested-row identity before mapping NCBI
  records. An explicit adjunct must carry one versioned coverage object through
  all response/artifact projections; output format does not decide whether the
  requested ClinicalTrials.gov retrieval runs.
- Image adapters must validate both page and row contracts before aggregation.
  Preserve rejected-row issues as partial coverage, keep failed-source totals
  unknown, and never turn a provider failure into an empty Markdown result.

### Server-Owned Runtime Pattern (2026-08-31)

```text
server instance
  +--> ToolSessionRuntime ---- tenant/session/strategy call binding
  +--> application container / pipeline runtime / scheduler
  `--> SourceRuntime -------- source contacts/clients/shared HTTP lifecycle

SDK client
  `--> lazy SourceRuntime ---- closed by async context or aclose()
```

- Capture mutable dependencies when the server is built; bind them
  context-locally only while one call executes.
- Bind the owning source and shared-HTTP runtime around the complete scheduled
  pipeline DAG, not only one alternate-source adapter call.
- Process globals are not ownership boundaries and must not be mutated to
  configure a newly constructed server.
- Closing server B cannot close server A's source clients. Runtime isolation
  tests must exercise two live servers and event-loop reuse.
- A `PubMedSearchClient` is also a lifecycle owner: create provider state
  lazily and close it through `async with` or `await client.aclose()`.

### Shared Bounded Task Supervisor Pattern (2026-08-31)

```text
ToolSessionRuntime
  +--> HostCallbackRuntime ---- BoundedTaskSupervisor(max 32)
  |             `--> asyncio.wait deadline -> cancel + yield
  `--> CitationTaskSupervisor - BoundedTaskSupervisor(max 128)
```

- `BoundedTaskSupervisor` owns scheduling, capacity rejection, disposal of
  unstarted awaitables, completion reaping, and bounded `aclose()` semantics.
  Features subclass it thinly and keep independent state/capacities.
- Schedule host notifications through the `HostCallbackRuntime` owned by the
  active `ToolSessionRuntime`; do not create an unowned task.
- Use `asyncio.wait` for the hard tool deadline. On timeout, request
  cancellation and yield once; do not wait indefinitely for a callback that
  suppresses cancellation.
- Retain cancellation-resistant work in a bounded supervisor, reject and
  dispose new callbacks at capacity, reap completed tasks, and invoke
  `aclose()` from server lifespan shutdown.
- Host timeout/failure is best-effort, but cancellation of the enclosing tool
  must still propagate.
- Citation expansion schedules through the owning server's
  `CitationTaskSupervisor`, capped at 128. Server lifespan closes both host and
  citation supervisors; do not add another detached-task lifecycle engine.

### Canonical HTTP Surface Pattern (2026-08-31)

```text
stdio -> canonical 41-tool registry (no HTTP listener)

pubmed-search-mcp-http
  +--> canonical MCP application / same 41-tool registry
  `--> tenant-guarded companion cache/session routes
```

- Environment flags do not install a profiling monkeypatch or register a
  hidden `get_performance_metrics` tool.
- The standalone FastAPI presentation app and stdio background-HTTP bridge are
  deleted. Do not recreate a shadow server or alternate registry.
- Companion HTTP routes share the canonical launcher's auth, tenant, and
  runtime ownership. They are operational conveniences, not MCP tools and not a
  second product surface.

### Research Chronicle Projection Pattern (2026-08-31)

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
- A nested topic links both to its thematic parent and to its own chronological
  year anchor; neither edge claims causal descent.
- Selection caps preserve earliest/latest evidence, explicit landmarks,
  citations, and temporal spread before filling remaining slots.
- Persist ranking intent and effective ranking separately. Validate the full
  PMID-keyed iCite mapping before enrichment, retain typed coverage counts and
  sanitized failure state, and never claim citation ordering without an
  applied nonnegative citation count.

### Deterministic Mermaid Repair Pattern (2026-08-31)

- Build every feature graph through the shared structured node/edge kernel;
  never interpolate untrusted labels directly into Mermaid syntax or fork a
  feature-specific repair implementation.
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

### Typed Source Outcome Pattern (2026-08-31)

```text
SourceAdapterCall
      |
      v
execute/gather --> validate_source_adapter_result --> application broker
                       |
                       `--> fail-closed SourceAdapterError
```

- `SourceAdapterResult` carries exact source/operation provenance, items,
  status, errors, total, cursor/cost, and metadata across shallow, relaxed,
  deep, full-text, preprint, and image paths.
- Validate expected source/operation identity, allowed runtime types, nested
  error provenance, status/items/errors coherence, and
  `total_count >= len(items) >= 0`. Reject booleans masquerading as integers.
- Preserve partial failures and provider diagnostics; never reinterpret a
  malformed provider dictionary as a successful empty result.
- Full-text link discovery specializes the same rule with immutable
  `PDFLinkDiscoveryResult`: links, attempted/completed canonical source keys,
  and sanitized errors travel together through download and extraction. Only
  HTTP 204/404 or a successfully parsed zero-link response is absence;
  transport/other HTTP/parse failure yields sanitized `partial` or
  `unavailable` coverage.
- Treat spelling, MeSH, and PubMed query analysis as separate covered
  operations. Unchanged spelling, a completed no-match lookup, and a real zero
  result are `completed`; an outage is `partial`/`failed` with a generic
  warning, never a repaired success value.

### Application-Owned Unified Search Pattern (2026-09-01)

```text
MCP adapter -- journal/progress/format/artifact --+
                                                 v
SDK adapter -- typed projection ----------> UnifiedSearchUseCase
                                                 |
                    planner/executor/ports <-----+
                                                 |
                       +-------------------------+------------------+
                       v                         v                  v
               UnifiedSourceBroker   UnifiedEnrichmentAdapter  SourceRegistry
                  infrastructure          infrastructure       infrastructure
```

- `application/unified` owns request normalization, plans, execution policy,
  deterministic ranking, typed outcomes, and the planner/executor/broker/
  registry/enrichment/progress/observer ports.
- The MCP runner adapts rejected inputs, SearchRun journaling, host progress,
  output formats, artifacts, and recovery hints. These are protocol/persistence
  concerns and must not move into `UnifiedSearchUseCase`.
- `PubMedSearchClient` composes the same use case and projects typed articles,
  coverage, errors, and filter counts. SDK search does not import presentation
  or create MCP/session/journal/artifact side effects.
- Concrete source, enrichment, PubTator, cache, and provider lifecycle objects
  are outer adapters supplied by the composition root.

### Deterministic Typed Enrichment Pattern (2026-09-01)

- Concurrent Crossref, journal-metrics, and Unpaywall tasks return immutable
  `ArticleEnrichmentPatch`/`EnrichmentOutcome` values; they do not mutate the
  shared article list while I/O is in flight.
- Candidate selection uses the requested rank with a canonical-identity tie,
  patches apply centrally in fixed provider/article order, and final ranking is
  recomputed after all outcomes are gathered.
- Failures retain only stable categories and attempted/succeeded/skipped/failed
  counts. Optional-provider failure remains `partial`/`failed`, never a silent
  success or authoritative empty search.
- `BaseAPIClient` has one transport-kernel rate/retry path and no `strict_errors`,
  last-error side channel, duplicate rate limiter, raw-reason log, or
  duplicate CORE/Europe PMC/Crossref/Unpaywall convenience facade.

### Runtime-Derived Tool Schema Audit Pattern (2026-09-01)

- Audit the tools actually registered by the server: 41 unique owners in 16
  categories, with no missing/extra/duplicate owner.
- Recursively require `additionalProperties: false` for all 74 object schemas,
  explicit bounds for all 215 string/array/integer/number nodes, and a required
  discriminator plus constant variant value for all 10 tagged unions.
- Verify required parameters, optional defaults, and behavior annotations
  against runtime definitions rather than duplicating a hand-maintained schema
  manifest.

### Explicit ICD and Image Ports Pattern (2026-09-01)

- ICD/MeSH crosswalk data, code validation, and lookup live in
  `application/search/icd.py`; the MCP module only registers the direction and
  formats the result.
- Image orchestration depends on application-defined `ImageSourceAdapter` and
  `OpenIClientPort`. The server composition root injects a factory backed by its
  own `SourceRuntime`; application code neither imports nor constructs Open-i.
- New image sources implement the port and require explicit registration.
  Unknown, duplicate, whitespace-padded, or absent source selections fail
  closed.

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

### Safe Outbound Pattern (2026-08-31)

```text
requested URL -> scheme/credential check -> DNS/IP policy -> bounded request
       ^                                                   |
       `---------------- revalidate every redirect --------'
```

- Full-text, figures, institutional access, and other URL-following paths use
  the shared safe-outbound implementation.
- Block local/private/reserved/link-local destinations, DNS rebinding, and
  public-to-private redirects. Apply response-byte and end-to-end deadline
  limits in addition to ordinary socket timeouts.
- Sanitize provider failures before they cross the application or MCP boundary.

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
| MCP Tool | snake_case 動詞 | `unified_search`, `validate_pico_plan` |
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
*Last updated: 2026-09-01 — v0.7.0 strict runtime, source, and graph patterns*
