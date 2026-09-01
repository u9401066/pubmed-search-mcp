# Decision Log

## [2026-09-01] Gate Every Public Tool Through Real MCP Transports

### Decision

Maintain an independent expected manifest for the canonical 41-tool registry
and call every tool through the official MCP client. Exercise source-tree stdio,
source-tree Streamable HTTP, and stdio from a fresh wheel installation. Replace
external-provider boundaries inside the child server; keep the registry, strict
schemas, presentation/application layers, persistence, artifacts, Chronicle,
pipelines, and scheduler real. Fail on unexpected outbound network access.

### Consequences

- Direct-function tests and schema inventories remain useful narrow checks but
  cannot substitute for protocol acceptance.
- A renamed, missing, unregistered, schema-incompatible, state-disconnected, or
  unpackaged tool fails CI through the same `tools/list`/`tools/call` boundary a
  client uses.
- Provider availability and credentials are not conflated with deterministic
  product integration; live probes remain explicitly opt-in.
- MCP surface changes must update the independent acceptance manifest and add a
  semantic success assertion before the PR CI/release gate can pass.
- Mermaid returned through MCP must match its declared digest/size and render
  with the pinned engine; structural metadata alone is not a rendering gate.
- Retired tools and legacy/coerced argument shapes are tested as real stdio
  protocol rejections so no-compatibility refactors cannot silently regress.

---

## [2026-09-01] Require Explicit Browser-Broker Secrets

### Decision

Require the local browser fetch broker to receive a caller-provisioned bearer
token through `--token`, `BROWSER_FETCH_BROKER_TOKEN`, or
`BROWSER_FETCH_TOKEN`. Reject missing, whitespace-bearing, or shorter-than-32-
character values before Uvicorn starts. Never generate or log a broker secret.

### Consequences

- Process logs cannot become a bearer-token disclosure channel.
- Broker and MCP configuration share one deliberate secret instead of relying
  on an unusable server-only runtime token.
- Existing broker launchers without an explicit strong token fail closed and
  must adopt the documented token-generation command.

---

## [2026-09-01] Fail Closed at Note, Pipeline-History, and OpenURL Boundaries

### Decision

Return only tenant-relative logical locators from authenticated literature-note
exports. Reject query-bearing or credential-bearing OpenURL bases and remove
ordinary search endpoints from resolver presets. Record PMID-to-DOI resolution
as `resolved`, `not_found`, or `error`. Abort a pipeline-history read when any
selected persisted run is invalid instead of skipping it.

### Consequences

- Remote callers cannot learn server directory layouts from note results.
- A PubMed outage cannot be described as evidence that an article lacks a DOI.
- Pipeline history is complete or explicitly unavailable, never silently
  partial, and corrupt-record logs contain neither host paths nor raw content.

---

## [2026-09-01] Make Provider Absence and Query-Intelligence Coverage Exact

### Decision

For full-text link discovery, classify only HTTP 204/404 or a successfully
parsed zero-link response as absence. Convert timeouts, transport/other HTTP
failures, and parse failures into sanitized source errors so sibling success is
`partial` and total source failure is `unavailable`.

For `generate_search_queries`, report spelling, MeSH, and PubMed query analysis
as separate `completed`/`partial`/`failed` coverage. Preserve unchanged
spelling, a completed no-match MeSH lookup, and a genuine zero-result analysis
as successful outcomes; provider failure emits only generic warnings.

Validate PubMed EFetch and NCBI Extended ESearch/ESummary/ELink envelopes and
requested-row identities before mapping. Run an explicitly requested
ClinicalTrials.gov adjunct for every output format and carry one
`clinical-trials-adjunct/v1` retrieval/formatting record through output and
artifacts.

Require Open-i to return a strict image-provider page. Treat mixed row validity
as partial, invalid/all-invalid results as failed, and only a valid explicit
zero page as empty; carry this source coverage into Markdown unchanged.

### Consequences

- Absence and outage cannot make the same full-text availability claim.
- Query-building output remains usable during optional-provider failure without
  claiming that spelling, vocabulary, or PubMed translation was verified.
- Raw provider messages do not cross either public coverage boundary.
- NCBI malformed payloads cannot become no-results, and structured output no
  longer disables a caller-requested ClinicalTrials.gov adjunct.
- Open-i outages/malformed payloads cannot inflate source-use or total claims
  and cannot be rendered as “no images.”

---

## [2026-09-01] Make Unified Search Application-Owned and SDK-Side-Effect-Free

### Decision

Make `application/unified.UnifiedSearchUseCase` the canonical normal-search
orchestrator shared by MCP and the Python SDK. Define explicit planner,
executor, source-broker, source-registry, enrichment, progress, and
plan-observer ports, and return one typed `UnifiedSearchOutcome`. Keep source
brokering, enrichment, PubTator resolution, caches, and provider clients in
infrastructure implementations injected through those ports.

Restrict the MCP runner to protocol concerns: rejected-input handling,
SearchRun journaling, host progress, response formatting, artifact persistence,
and recovery handoffs. Make `PubMedSearchClient.unified_search()` compose the
same use case directly and return typed articles, source coverage/errors, and
filter counts without importing presentation or creating MCP/session/journal/
artifact side effects.

### Consequences

- MCP and SDK execute the same planning, source, enrichment, filtering, and
  ranking policy without importing one another.
- SDK callers no longer receive an MCP-formatted or serialized artifact facade;
  durable artifacts and SearchRun journals remain an explicit MCP adapter
  capability.
- Application code has no runtime dependency on presentation or infrastructure
  modules; outer composition selects concrete broker, enrichment, registry,
  semantic resolver, cache, and lifecycle owners.
- Future entries must add application behavior through the use case or its
  ports rather than placing orchestration back into an MCP tool module.

---

## [2026-09-01] Make Enrichment Deterministic and Delete Provider Soft-Fail Facades

### Decision

Run optional Crossref, journal-metrics, and Unpaywall enrichment as immutable
typed patch/outcome tasks. Select candidates through the requested ranking
policy with canonical identity tie-breaks, apply patches centrally in fixed
provider/article order, then compute the final rank. Preserve only sanitized
failure categories and explicit completed/partial/failed coverage.

Make `BaseAPIClient` use one transport-kernel rate/retry path that raises
sanitized typed failures. Delete `strict_errors`, mutable last-error state, the
second rate limiter, raw upstream reason logging, duplicate CORE/Europe PMC
search/getter facades, and Crossref/Unpaywall lookup facades. Runtime-owned
factories remain at the infrastructure package boundary.

### Consequences

- Concurrent provider completion order cannot mutate shared articles or change
  public ranking.
- Optional-provider failure remains visible in output, artifact, and audit
  diagnostics instead of masquerading as successful enrichment or an empty
  search.
- There is one provider lifecycle/factory seam and one transport policy; dead
  module-level facades cannot bypass typed result validation.

---

## [2026-09-01] Derive Tool Schema Quality From the Runtime and Inject Feature Ports

### Decision

Audit the registered MCP runtime rather than maintaining a hand-written schema
claim. Require 41 unique tool owners in 16 categories, recursive closure of all
74 object schemas, explicit bounds for all 215 string/array/integer/number
nodes, and exact required discriminator/constant-variant mappings for all 10
tagged unions. Also verify required/default coherence and annotation/side-effect
agreement.

Move the curated ICD/MeSH crosswalk and lookup policy into
`application/search/icd.py`, leaving the MCP module as registration/formatting
only. Define `ImageSourceAdapter` and `OpenIClientPort` in the image-search
application package and inject the server-owned Open-i factory from the
composition root through `SourceRuntime`.

### Consequences

- Registry additions or schema regressions fail against the actual exported
  surface, including nested objects and discriminated variants.
- ICD domain data no longer lives in presentation, and image orchestration no
  longer constructs or imports a concrete infrastructure client.
- A new image provider must implement the application port and be explicitly
  installed by composition; unknown or absent sources fail closed.

---

## [2026-09-01] Preserve Full-Text Partial Coverage End to End

### Decision

Make `PDFLinkDiscoveryResult` the only extended full-text link-discovery
contract. It carries immutable links, exact attempted/completed source keys,
sanitized typed source errors, and computed `complete`/`partial`/`unavailable`
coverage through download, extraction, the application service, MCP output,
and artifacts. Remove the list-only facade and never expose raw downstream
error strings.

### Consequences

- A successful link or extracted article cannot erase a sibling-source
  failure; callers can distinguish complete from partial access coverage.
- Machine-readable coverage uses stable canonical source keys; human display
  labels remain presentation metadata.
- Provider URL, response, credential, and local-path details do not cross the
  public failure boundary.

---

## [2026-08-31] Use Exact Page and Failure Contracts Without Read-Time Migration

### Decision

Make a typed source page the only PubMed/licensed-search result and make typed
provider failure the only representation of an unsuccessful upstream call.
Persist sessions only in the exact v1 session/index schemas with first-class
search runs. Remove list facades, mutable search metadata, error-sentinel rows,
soft `[]` failure paths, cache warmup payloads, and legacy history projection.

### Consequences

- Empty means the provider successfully reported no matching records; timeout,
  rate limit, authentication, malformed payload, and provider failure remain
  distinguishable to unified search, pipelines, artifacts, and users.
- Total count, offset, continuation, warnings, source identity, and operation
  provenance travel together instead of through mutable client state.
- Old persisted payloads fail closed and require an explicit offline migration
  if one is ever designed; production reads do not guess or rewrite them.
- `application/fulltext` remains the single full-text coordinator, and exact
  source keys plus `SEMANTIC_SCHOLAR_API_KEY` are the only runtime contract.

---

## [2026-08-31] Publish One Strict 41-Tool Registry Without Public Compatibility Aliases

### Decision

Expose exactly 41 tools in 16 categories through stdio, Streamable HTTP,
Copilot, tests, and generated documentation. Remove retired public aliases,
alternate Copilot registries, presentation facades, and loose request
normalizers. Require one discriminated request for session and Chronicle reads,
canonical pipeline `output`, and typed/bounded PMID inputs.

### Consequences

- A removed tool name or legacy flat request fails clearly instead of silently
  choosing a new action. This is an intentional v0.7.0 breaking boundary.
- `run_copilot.py` launches the canonical registry; transport compatibility
  middleware may adapt HTTP acknowledgements but does not define another tool
  surface.
- Registry, READMEs, handbook/site, OpenAPI/Copilot material, tool index, tests,
  and agent guidance must agree on the same count and schemas.
- Future aliases require an explicit product decision and a removal plan; they
  cannot be added incidentally inside MCP wrappers.
- Delete the hidden profiling tool/monkeypatch, orphan standalone FastAPI app,
  and stdio background-HTTP bridge. Supported HTTP companion routes remain on
  the canonical server with the same tenant/auth/runtime ownership and do not
  define another registry.

---

## [2026-08-31] Make Pipeline Discrimination and Action Parameters Schema-Exact

### Decision

Template pipelines accept only the top-level `template_params` field; the
retired template `params` alias and `execution` output shape fail closed. Infer
pipeline `kind` only when the discriminator is omitted. If the caller supplies
`kind`, preserve it unchanged so contradictory mode fields reach strict
discriminated-union validation instead of being silently reclassified.

Require exact action/template names, step and dependency identifiers, enums,
and action-specific parameter schemas. Reject unknown fields, fuzzy or alias
matching, scalar/CSV-to-array repair, numeric/string conversion, and other
explicit-value coercion. Documented defaults may fill omitted fields; bounded
safety budgets may cap work but do not reinterpret caller intent.

### Consequences

- A typo or contradictory discriminator produces a validation error rather
  than executing a different pipeline.
- Template-level `params` cannot be confused with the canonical per-step
  `params` mapping.
- Persisted configs, inline `unified_search` pipelines, templates, scheduler
  runs, and dry runs share the same parsing and action-contract boundary.
- Compatibility helpers and fuzzy normalization must not be restored below the
  presentation layer.

---

## [2026-08-31] Make Typed Source Outcomes the Only Unified-Search Boundary

### Decision

Route source work through `SourceAdapterCall`, `SourceAdapterResult`, and
`SourceAdapterError`, with one fail-closed validator shared by shallow search,
auto-relaxation, deep execution, full-text, preprint, and image paths. Validate
the expected source and operation, supported runtime types, nested error
identity, status/items/errors coherence, and
`total_count >= len(items) >= 0`.

### Consequences

- Provider dictionaries and compatibility facades no longer bypass provenance
  or status validation.
- Partial failures retain items and typed diagnostics; an errored or malformed
  outcome cannot be misreported as a successful empty search.
- Pipeline/search integration should converge on this same outcome type rather
  than reconstructing totals, cursor, cost, or provenance independently.
- Search handoffs expose directly executable canonical arguments and shared
  response bounds/sanitation apply after application formatting.

---

## [2026-08-31] Scope Mutable Runtime and Source Lifecycles to Each MCP Server

### Decision

Each `PubMedMCPServer` owns its `ToolSessionRuntime`, tenant/session manager,
strategy registry, application container, pipeline runtime, source contacts,
source-client pool, and outbound-client lifecycle. Use context-local binding to
carry the owning runtime through a call, never mutable process globals as an
ownership mechanism.

### Consequences

- Constructing server B cannot overwrite server A's tenant, strategy, source
  contact, cache, or container configuration.
- Closing one server closes only the clients it owns and cannot poison another
  event loop or live server.
- Saved scheduler jobs bind the creating server's source and shared-HTTP
  runtime around the complete DAG.
- The Python SDK owns a separate lazy `SourceRuntime`, bound around
  `unified_search` and closed through `async with` or `aclose()`.
- Provider/event-loop rate and resilience policy can remain shared explicitly;
  mutable clients, contacts, caches, exporters, and HTTP pools are owned by one
  server or SDK client.
- Two-server construction/call/close regressions are release-gating tests.

---

## [2026-08-31] Share Bounded Task Ownership Across Host and Citation Work

### Decision

Use one reusable `BoundedTaskSupervisor` for capacity, ownership, disposal,
reaping, and bounded shutdown. Schedule MCP progress, logging, and
resource-update callbacks through the thin `HostCallbackRuntime` owned by the
active server. Observe each with
`asyncio.wait` under its configured hard deadline. If the host stalls, request
cancellation and yield once; quarantine callbacks that suppress cancellation
in the owning runtime, capped at 32 pending tasks. Reject and dispose new
callbacks when the supervisor is full, and invoke bounded `aclose()` cleanup
from server lifespan. Citation expansion uses an independently owned thin
`CitationTaskSupervisor` with the same primitive and a 128-task cap.

### Consequences

- Best-effort notifications cannot block core tool work indefinitely.
- Cancellation-resistant callbacks remain owned and observable without
  accumulating beyond the fixed capacity.
- Saturation produces load shedding rather than more background work.
- Tests must cover cooperative and cancellation-resistant callbacks, capacity
  rejection, per-server isolation, lifecycle cleanup, and propagation of
  enclosing cancellation.
- Host and citation work retain separate capacities and semantics without
  duplicating detached-task lifecycle code; the owning server closes both.

---

## [2026-08-31] Use One Redirect-Aware Safe-Outbound Boundary

### Decision

All URL-following provider paths, including full text, figures, and
institutional access, use the shared outbound implementation. Validate scheme,
embedded credentials, DNS/IP destination, and every redirect hop; block
private/local/reserved targets and DNS rebinding; bound response bytes and the
end-to-end deadline.

### Consequences

- A provider-supplied public URL cannot redirect to a local service.
- Timeout and size policy includes the entire redirect/read sequence, not only
  one socket operation.
- New URL-retrieval features must reuse this boundary rather than implement
  another whitelist or raw `httpx` redirect loop.

---

## [2026-09-01] Make Chronicle Ranking Claims Evidence-Effective

### Decision

Persist caller ranking intent separately from the ranking that actually ran.
Record iCite enrichment in `citation-metrics-coverage/v1`, validate the complete
PMID-keyed response before mutation, and claim iCite ordering only when at least
one valid citation count was applied.

### Consequences

- Empty, partial, malformed, and outage outcomes remain distinct and sanitized.
- PubMed relevance remains the effective ranking when no sortable iCite count
  exists.
- Chronicle audit warns on incomplete enrichment and fails provenance that
  claims an unavailable or unrequested ranking.

---

## [2026-08-31] Share Mermaid Repair and Preserve Nested Chronicle Chronology

### Decision

Generate Chronicle and other supported Mermaid diagrams through the shared
structured graph kernel with deterministic `rich -> safe -> minimal` repair.
In the Chronicle projection, connect nested topics both to their thematic
parent and to the year anchor of their own evidence.

### Consequences

- A viewer can read chronological order and thematic divergence from one
  horizontal diagram without mistaking the thematic edge for causality.
- Identifier, label, Unicode, topology, cycle, orphan, and size repair behavior
  is consistent across features and exposes corrections/omissions/fallback
  metadata.
- Real Mermaid parse/render smoke tests remain part of the release boundary.

---

## [2026-08-12] Make Chronicle Projections Chronological, Observational, and Repairable

### Decision

Use a left-to-right year-anchor spine as the canonical Chronicle view and
attach evidence to topic branches inferred from repeated signals when at least
two supported branches cover 60% of events. Otherwise disclose a deterministic
research-stage fallback. Treat all branches as observational groupings, not
causal descent. Generate Mermaid from a structured projection, normalize and
repair it deterministically, and expose `rich -> safe -> minimal` diagnostics.

### Consequences

- Date precision determines the stable entry ordering; equal-time ties preserve
  input order for display without asserting `PRECEDES`. Undated evidence is
  retained explicitly after dated evidence.
- A paper has one primary branch while matched signals and cross-links preserve
  multi-topic evidence without duplicating its identity.
- `PRECEDES` requires definite chronology. `SUPERSEDES` is never inferred from
  ordering alone, and absence means `not_observed_in_revision` rather than
  scientific retirement.
- Mermaid labels, identifiers, graph topology, and output bounds are repaired
  before delivery. Corrections, omissions, fallback tier, and validation status
  are part of the projection contract.
- CI pins Mermaid 11.16.1 and jsdom 26.1.0 and must parse and render repository,
  documentation, and runtime-fixture diagrams to real SVG.

---

## [2026-08-12] Treat Revision Files as Chronicle Authority and the Index as Cache

### Decision

Persist every Chronicle revision as an immutable, atomically published JSON
record. Derive list/latest/topic lookup state from those revisions and treat the
index only as a rebuildable performance cache. Move blocking store work off the
async event loop with `asyncio.to_thread`.

### Consequences

- Missing, corrupt, or stale indices are repaired from revision files instead
  of becoming a second source of truth.
- Process/thread locks protect local append and index-rebuild paths; a failed
  post-commit index refresh cannot turn a successfully persisted revision into
  a false build failure.
- Empty retrieval cannot publish an evidence-free revision, and failed PubMed
  responses cannot be represented as papers.
- Local filesystem persistence remains a single-process/single-replica service
  boundary; distributed deployment still needs a transactional shared store,
  distributed locks, and object storage.
- Service and MCP boundaries validate topic identity, years, positive ASCII
  PMIDs, revision direction, exact evidence sets, prepared artifact file sets,
  and source coverage. The artifact store separately verifies persisted
  locators and checksums.

---

## [2026-08-09] Separate Local Trust From Multi-User Service Identity

### Decision
Treat stdio and explicit loopback HTTP as one trusted single-user deployment
profile with a durable `default` tenant. Treat remote/team HTTP as a distinct
service profile that cannot start without bearer principals, tenant isolation,
a public MCP resource URL, and explicit Host/Origin allowlists.

### Consequences
- Modern HTTP no longer derives a security identity from `Mcp-Session-Id` or
  `clientInfo`; only a verified token principal is a service tenant boundary.
- Local HTTP preserves `pmids="last"`, cache, session, and exports across calls,
  but may never be exposed merely by changing the bind address.
- Filesystem-backed service deployment remains one process/replica until a
  transactional shared store, distributed locks, and an external artifact
  backend are implemented.
- Every HTTP surface, including auxiliary routes and the browser-session broker,
  must enforce its own Host/Origin boundary because SDK middleware protects only
  the MCP route.

---

## [2026-08-09] Serialize File-Backed State Under MCP v2 Worker Threads

### Decision
Treat every sync MCP handler as concurrently executable. Protect in-process
read/modify/write paths with shared locks, publish files and artifact
directories atomically, and return detached snapshots instead of mutable store
objects. Do not advertise horizontal service scaling while state is local.

### Consequences
- Pipeline indices, sessions, chronicles, notes, caches, exports, and artifacts
  have concurrent lost-update/collision/corruption regressions.
- Persistence failures propagate to the caller rather than being logged as a
  false success.
- Multi-worker service requires a transactional shared store, distributed
  locking, object storage, and scheduler leader election before enablement.

---

## [2026-08-09] Make Unified Search A Registry-Backed Broker Contract

### Decision
Keep `unified_search` as the stable gateway rather than adding more top-level
tools or APIs without a distinct evidence role. Explicit source selection is
binding; every provider uses shared conservative quotas and normalized outcomes,
and new adapters must prove corpus/identifier/access value plus edge coverage.

### Consequences
- An empty explicit OpenAlex/preprint search cannot silently substitute PubMed.
- PubMed relaxation runs only when PubMed was planned and reuses its successful
  result.
- Disabled-source policy applies to automatic, explicit, `all`, and preprint
  expansion paths.
- This historical broker decision kept a larger compatibility surface. It is
  superseded by the 2026-08-31 v0.7.0 decision: the canonical surface is 41
  strict tools in 16 categories, with duplicate timeline and other retired
  aliases removed.

---

## [2026-06-05] Separate MCP, Python SDK, And HTTP CLI Contracts

### Context
External package users needed a stable Python import surface, while agent users needed the existing MCP tool registry and remote deployments needed an installed HTTP launcher. Mixing these contracts encouraged imports from `presentation.mcp_server.tools`.

### Decision
Expose `pubmed_search.api` as the stable Python SDK facade, keep MCP tools as presentation adapters, and add `pubmed-search-mcp-http` as the packaged HTTP server CLI. Keep `run_server.py` as a source-tree development wrapper.

### Consequences
- SDK imports must stay lightweight and must not load MCP, MCPServer, settings, or source clients.
- `unified_search` runtime logic is delegated through an application-facing
  runner so the SDK avoids presentation imports at import time. v0.7.0 removes
  the old presentation compatibility wrappers; both supported surfaces consume
  canonical application/source contracts.
- Docs must distinguish MCP tool surface, Python SDK facade, and auxiliary HTTP APIs.

---
## Earlier Decision Index

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-06-06 | **Make Research Chronicle a planned persisted source-of-truth, not a synonym for timeline** | At the time, the code had timeline/tree previews but no persistent Chronicle. The resulting auditable aggregate, revisions, deltas, evidence bundles, and projections shipped before the v0.6.2 hardening. |
| 2026-06-05 | **Treat research artifacts as the durable evidence channel** | MCP responses should remain small enough for agents to answer immediately, while complete search results, query strategy, source-count audit, and retrieval metadata live in paged artifact files that local, remote, and sandboxed clients can read repeatedly without rerunning external APIs. |
| 2026-04-29 | **Keep Zotero Keeper outside PubMed MCP core** | PubMed MCP should expose stable exports and guided local notes; Zotero import, duplicate handling, and VSIX-specific library policies belong in Zotero Keeper or another external client. |
| 2026-04-29 | **Pipeline PICO support should emphasize diagnostics and guided outputs** | PICO/pipeline runs are structured clinical questions. The valuable artifact is an auditable search/filter/export trail, not a copied storage subsystem from another repository. |
| 2026-04-24 | **Gate v0.5.6 through an integration branch before release** | The local workspace contained a broad feature and hardening set. Keeping it on `codex/integrate-local-v0.5.6` until local tests and GitHub Actions are green makes regressions easier to isolate before merging, tagging, and publishing. |
| 2026-04-24 | **Remove `dependency-injector` from the runtime startup path** | Windows Python 3.14 installs failed before MCP startup because the native extension could not load. The server only needs config, singleton, override, and reset provider behavior, so a pure-Python container removes the platform-sensitive dependency while preserving the application boundary. |
| 2026-04-03 | **建立 shared source adapter contract 層** | 多來源 orchestration 需要一致的 partial-failure、status、error envelope，不應在 search/fulltext/image 各自重造。 |
| 2026-04-03 | **建立 shared cache substrate** | session/entity 類快取已經出現重複結構；收斂為 memory/json backend + 統一 stats/warmup/invalidation API。 |
| 2026-04-03 | **將 docs site 產物納入版本控制** | README、ARCH、deployment、tool index 已足夠形成靜態 docs surface；直接提交生成結果可讓發布版立即可瀏覽。 |
| 2026-03-17 | **PubTatorClient 改走 BaseAPIClient** | PubTator 原本手寫 retry / rate limit / request loop，與專案既有 `BaseAPIClient` 重複。統一路徑可避免 transport 行為漂移。 |
| 2026-03-17 | **ICiteMixin 改用 cachetools.TTLCache** | 專案已依賴 `cachetools`，不再維護第二套手寫 TTL cache；保留薄封裝即可。 |
| 2026-03-17 | **FastMCP Context 擴展到長任務工具** | `unified_search` 之外的 timeline 與 Europe PMC 長任務也需要 progress/log，降低 Agent 黑箱等待時間。 |
| 2026-03-17 | **Session 最近搜尋改用 MCP resources 暴露** | `session://last-search*` 比從聊天上下文重建 session state 更穩定，且更方便 Agent 直接取用。 |
| 2026-02-14 | **ruff select=["ALL"] + mypy strict=true** | 生產級別程式碼品質：啟用所有 lint 規則，嚴格型別檢查。~40 justified ignores in pyproject.toml |
| 2026-02-14 | **`# noqa` 消除優先於壓制** | 修復根因（field rename, dead code removal, parameter rename）而非壓制警告。18→9 noqa |
| 2026-02-14 | **Pre-commit 17 hooks 自演化系統** | instruction↔skill↔hook 閉迴循環，evolution-cycle hook 自動驗證一致性 |
| 2026-02-14 | **`_ranking_score` → `ranking_score` (public)** | 跨模組使用的欄位不應該是 private（SLF001 violation）。保留 to_dict() key 為 `_ranking_score` 向後相容 |
| 2026-02-14 | **刪除 `retryable_status_codes` 死碼** | with_retry() 裝飾器的參數從未被使用，retry 邏輯使用 typed exception classes |
| 2026-02-10 | **全面 Async-First 架構** | 使用者審計後選擇「立即重構 P2 + 加規則」，消除所有 sync/async 混用 |
| 2026-02-10 | BioPython Entrez → asyncio.to_thread | BioPython 是 sync library，用 to_thread wrap 不修改源碼最安全 |
| 2026-02-10 | ThreadPoolExecutor → asyncio.gather | unified.py 原用 ThreadPool 做並行搜尋，改用原生 asyncio.gather 更高效 |
| 2026-02-10 | httpx.AsyncClient 取代 urllib/requests | httpx 支援 async，統一 HTTP client，消除 sync blocking |
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
| 2026-01-13 | **建立簡化 Copilot 工具集（已由 2026-08-31 決策取代）** | 當時用於避開 anyOf schema truncation；v0.7.0 改由同一 41-tool strict registry 處理所有 launcher |

---

## [2026-01-26] HTTP Client 重構 (Option B: 中度重構；歷史決策)

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

3. **當時的相容策略（不等同 v0.7.0 公開工具相容層）**:
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
- 當時保留低階 HTTP helper 以避免一次破壞內部呼叫；v0.7.0 的公開
  tool/source contract 不因此保留舊 alias 或 presentation facade

---

## [2026-01-13] Copilot Studio Schema 相容性修復（已由 v0.7.0 取代）

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

> Historical note: v0.7.0 deletes this reduced registry. `run_copilot.py` now
> uses the same canonical strict 41-tool registry as every other launcher.

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
# 當時的 Copilot 相容模式（已移除）
python run_copilot.py --port 8765

# 當時的完整工具集切換（已移除）
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
| 2026-01-26 | CI/CD Pipeline 現代化：使用 UV 替代 pip + 完整品質檢查 | 問題：原 publish.yml 使用 pip/python -m build，未進行品質檢查，導致可能發布有問題的代碼。

解決方案：
1. 改用 uv（符合專案標準，更快更可靠）
2. 添加 test job（先測試再發布）
3. 集成 ruff check + format check
4. 只有所有檢查通過才允許發布

影響：
- 提升代碼品質保證
- 防止有問題的版本發布到 PyPI
- 建立 production-level CI 標準

技術決策：
- uv build 替代 python -m build
- needs: test 確保執行順序
- 保持 trusted publishing（無需 API token） |
| 2026-01-28 | 在 ROADMAP.md 新增 Phase 14: 研究缺口偵測 (Research Gap Detection)，包含 5 種缺口類型和完整實作規格 | 研究缺口偵測是差異化競爭優勢，目前無競品提供全自動多類型缺口偵測。對研究者有高實用價值（找論文題目、基金申請亮點）。 |
| 2026-02-09 | Agent vs MCP 職責劃分：翻譯由 Agent 負責，MCP 只負責偵測+警告 | 1. Agent 有 LLM 翻譯能力，比 MCP 維護字典更好 2. MCP 維護字典更新困難、覆蓋不全 3. 符合「MCP 是工具提供者，Agent 是決策者」原則 4. 非英文偵測使用 NON_LATIN_PATTERN regex，警告 Agent 需要翻譯 |
