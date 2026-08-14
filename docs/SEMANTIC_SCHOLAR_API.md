# Semantic Scholar：Live Search 與 Dataset Data Plane

> Verified against the official service on **2026-08-14**. Semantic Scholar is
> an internal provider of `unified_search`; it is not a separate MCP search
> tool.

## 決策摘要

本專案把 Semantic Scholar 分成兩條彼此隔離的路徑：

1. **Live query plane**：Graph API 的 relevance search、bounded bulk search、
   batch enrichment、citations、references 與 recommendations。
2. **Operator data plane**：Datasets API 的 release catalog、manifest 與
   incremental diff。大型 partition 不會在 MCP request 中下載。

MCP 的通用文獻搜尋入口仍只有 `unified_search`。`semantic_scholar` 是
broker 內部 source key；不得新增 `search_semantic_scholar`、
`dataset_search` 或其他 provider-shaped MCP tool。

### 本輪 runtime 狀態

| 能力 | 已落地行為 | 公開邊界 |
| --- | --- | --- |
| Relevance | `SourceSearchPage` 保留 raw DTO、`total`、offset/`next` 與 warnings，之後只 map 一次 | `unified_search(sources="semantic_scholar")` |
| Systematic | `options="systematic"` 將一般 Boolean 的 `AND` / `OR` / `NOT` 編譯成 S2 bulk `+` / `|` / `-`，保留 quoted phrase 與 logical/physical query | 同一個 `unified_search`；public `limit <= 100` |
| Batch | client 支援最多 500 個 paper IDs，保留 response 順序與 null slots | infrastructure/application enrichment capability；不是 MCP tool |
| Dataset metadata | 可列 release、讀 release/dataset/diff manifest；signed file URLs 不出現在 repr/error | operator-side metadata client；不下載 partition、沒有 local index |

S2 bulk compiler 遇到 PubMed field tag（例如 `[Title/Abstract]`）、不平衡引號或
括號會在 network call 前 fail closed。它不會猜測無法等價轉換的 provider syntax。
一般 `unified_search` 的 public limit 上限是 100；Graph API bulk 的單頁 1,000
與大型搜尋空間是 provider capability，不會自動放大一次 MCP 回應。

## 官方契約

- [API tutorial](https://www.semanticscholar.org/product/api/tutorial)
- [API overview and key request](https://www.semanticscholar.org/product/api)
- [Graph API OpenAPI](https://api.semanticscholar.org/graph/v1/swagger.json)
- [Datasets API](https://api.semanticscholar.org/api-docs/datasets)
- [API licence](https://www.semanticscholar.org/product/api/license)
- [Dataset licence surface](https://api.semanticscholar.org/license/)

官方服務可能在文件更新後調整 quota、release 或資料集清單。程式應依
response、manifest 與 license metadata 做決策，不把本頁的觀察值當永久 SLA。

## Live query plane

### Relevance search

`GET /graph/v1/paper/search` 適合一般自然語言檢索：

- 單頁 `limit <= 100`
- offset 視窗最多 1,000 筆
- plain-text relevance query；不要把 provider-specific Boolean syntax 假設成
  普通 search 的共同語法
- 只請求必要 `fields`，避免 10 MB response 上限與 token 浪費
- envelope 應保存 `total`、`offset`、`next`，不能在正規化時丟棄

### Bulk search

`GET /graph/v1/paper/search/bulk` 適合由 broker 判定的 bounded systematic
retrieval：

- 支援 Boolean、phrase、wildcard、fuzzy/proximity 等 bulk syntax
- token pagination，單頁最多 1,000 筆
- 官方搜尋空間上限很大，不代表本專案可以無界擷取
- broker 必須同時施加 `max_results`、`max_pages`、time budget 與 repeated-token
  防護
- systematic/reproducible plan 優先使用 deterministic sort，並保存 logical
  query、compiled physical query 與 page token provenance

Bulk search 是 `unified_search` 的內部 execution mode，不是新的 tool。

實際呼叫方式：

```python
unified_search(
    query='melanoma AND (immunotherapy OR "targeted therapy") NOT review',
    sources="semantic_scholar",
    options="systematic",
    limit=100,
    output_format="json",
)
```

Structured output 的 `source_metadata.semantic_scholar` 會標示
`requested_mode="systematic"`、`provider_mode="bulk"`、logical/physical
query、continuation 是否可用、bounded/pages/sort 與 warnings。Continuation
目前是 audit metadata，不是另一個公開 paging tool。

### Batch enrichment

`POST /graph/v1/paper/batch` 每次最多 500 個 identifiers。適合在跨來源去重後
補齊 S2 ID、citation metrics 或 OA hints，避免 N+1 singleton requests。partial
或 missing IDs 必須保留對位結果，不可把資料缺口當成整批失敗。

### Citation graph

Citations/references 可補 `contexts`、`intents` 與 `isInfluential`。這些欄位是
provider annotations，不是原論文的作者主張；寫入 Research Chronicle 或
citation graph 時要保留：

- provider 與 endpoint
- fetched timestamp
- source/target paper identifiers
- annotation type
- 缺失或 publisher elision 的狀態

## Rate limit 與 resilience

- 無 key 請求使用共享池，可能在低流量時仍收到 429；它不是可靠 SLA。
- 新 API key 通常從跨 endpoints 合計約 1 request/second 起步，實際 grant 以
  帳號設定與 response 為準。
- `S2_API_KEY` 與 `SEMANTIC_SCHOLAR_API_KEY` 都可設定；只以
  `x-api-key` header 傳送，不可出現在 URL、log、artifact 或 error detail。
- 所有 client instances 共用同一 upstream budget；429 尊重 `Retry-After`，
  exhausted retry 要進 cooldown，避免 parallel retry storm。
- live provider 失敗時 `unified_search` 應回 structured source warning，而不是
  把 mapper exception 偽裝成成功的零結果。

## Dataset data plane

Datasets API 用於可重現的大型本地資料流程，不用來直接回答 MCP request。

### Release 與 manifest

- release catalog 與 release metadata 可公開讀取
- partition 的 temporary download URLs 與 diffs 需要有效 `x-api-key`
- 每次 ingestion 保存 release ID、dataset name、原始 README/license URL、
  manifest hash 與接受時間
- release 頻率與 dataset 規模只視為觀察值，不硬編成 SLA

常見 dataset 包含 papers、abstracts、authors、citations、paper IDs、venues、
SPECTER embeddings、S2ORC 與 TLDR；實際清單以該 release manifest 為準。

### Incremental diff

`/datasets/v1/diffs/{start}/to/{end}/{dataset}` 的語意是：

- update records 依 primary key upsert/replace
- delete records 移除
- 逐 release transactional apply
- 成功 publish index 後才 advance checkpoint
- presigned URL 過期時重取 manifest，不把 URL 當持久 identifier

### 大檔安全

- JSON/JSONL partition 必須 streaming decode，不可整檔載入記憶體
- 下載前做 disk preflight，使用高 entropy staging directory
- 驗證 hash/size 後 atomic publish；失敗時舊 index 仍可讀
- 預設只規劃 selective biomedical profile；S2ORC、全文與億級 embeddings 全部
  opt-in
- Dataset metadata 的授權與底層論文／全文權利分開記錄；不得把 dataset access
  推論成所有 content 可任意再散布

上述下載、checkpoint、atomic publish 與 selective local profile 是下一階段
operator ingestion contract；本輪只完成 metadata-only client。不得把
`operator_data_plane="metadata_only"` 解讀成已經存在可供搜尋的 local S2 index。

## 正規化邊界

Provider payload 只正規化一次：

```text
official response DTO
  -> source response envelope
  -> deterministic provider mapper
  -> UnifiedArticle / citation edge
  -> aggregation, ranking, Chronicle
```

Client 不應先改成 PubMed-like dictionary，再交給期待原生 S2 schema 的 mapper。
Envelope 至少要保留：

- `items`
- `total`
- `next_token` / `offset`
- query mode 與 compiled query
- access path (`live_api` / future local index)
- warnings、usage 與 fetched timestamp

目前共用 `SourceSearchPage` 已落地 `items`、`total`、continuation、
query/mode、cost、warnings 與 metadata；完整 usage timestamp/local snapshot
reference 仍屬後續一致化項目。

## Data rights 與 evidence semantics

- Semantic Scholar 提供 metadata、graph annotations 與 OA hints；OA URL 的實際
  license 仍取決於最終 host。
- TLDR 是 machine-generated，不能當原文 evidence。
- SPECTER embeddings 適合 candidate retrieval，不是 factual evidence。
- S2ORC/full text 必須依 release 與原始文章權利處理。
- final answer 應引用原始論文；不要把 provider summary 當可替代的學術引用。

## 測試契約

Deterministic tests 必須涵蓋：

- runtime search tool group exact 等於 `['unified_search']`
- raw S2 fixture 經 client、runner、mapper 後保留 S2 ID、authors、DOI/PMID、OA
  與 citation metrics
- relevance limit/total/next；bulk token termination、repeat detection 與 budgets
- batch 500 boundary、partial IDs
- dataset release/manifest/diff auth、schema drift 與 checkpoint replay
- 429 cooldown、timeout、5xx retry/circuit breaker
- secret redaction 與 source failure 不被轉成「成功空集合」

Gated live smoke 只能取少量 results 或只讀 release catalog；一般 CI 不下載 dataset partition。
