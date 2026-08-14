<!-- Generated from docs/OPENALEX_API.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# OpenAlex：Capability-aware Search、Cursor 與 Snapshot

> Verified against the official service on **2026-08-14**. OpenAlex is an
> internal source of `unified_search`; it is not a separate MCP search tool.

## 決策摘要

OpenAlex 在本專案有三種不同尺度：

1. **Keyword API**：一般跨領域 discovery。
2. **Native semantic API**：使用者或 planner 明確需要語意檢索時的 bounded mode。
3. **Snapshot/sync data plane**：operator 管理的大型本地資料流程。

Cursor、semantic 與 snapshot 都是 broker/application capability，不新增
`search_openalex`、`semantic_search` 或 `snapshot_search` MCP tool；通用文獻搜尋
仍只有 `unified_search`。

### 本輪 runtime 狀態

| 能力 | 已落地行為 | 公開邊界 |
| --- | --- | --- |
| Keyword | raw works DTO 經 `SourceSearchPage` 只 map 一次；`per_page <= 100`、root-only `select` | `unified_search(sources="openalex")` |
| Native semantic | `options="native_semantic"` 選 `search.semantic`；2,000 chars、50 results、獨立 1 RPS limiter | 同一個 `unified_search` |
| Systematic | `options="systematic"` 使用 publication-date ascending 的 bounded cursor traversal | 同一個 `unified_search`；public `limit <= 100` |
| Cost/provenance | 保存 safe `x_query` / OQL、`meta.cost_usd` 與 allowlisted rate headers；低 credit 產生 warning | JSON/TOON `source_metadata` 與 artifact query strategy |
| Snapshot | registry 宣告 provider 有 operator data plane | 尚未實作 local snapshot downloader/index adapter |

有 API key 時，本 repo 以 `Authorization: Bearer ...` 傳送，避免 secret 進入
query string；`mailto` 仍是非秘密 contact hint。Key 在 settings 中以 secret
型別保存，只有建立 client 時解包。

## 官方契約

- [API endpoints](https://help.openalex.org/api/endpoints/)
- [Authentication and budgets](https://help.openalex.org/api/authentication/)
- [Searching](https://help.openalex.org/api/searching/)
- [Semantic search](https://help.openalex.org/api/semantic-search/)
- [Filtering](https://help.openalex.org/api/filtering/)
- [Paging and cursor](https://help.openalex.org/api/paging/)
- [Selecting fields](https://help.openalex.org/api/selecting-fields/)
- [Errors](https://help.openalex.org/api/errors/)
- [Snapshot](https://help.openalex.org/access/snapshot/)
- [Sync](https://help.openalex.org/access/sync/)
- [Full-text rights](https://help.openalex.org/access/fulltext/)

OpenAlex 的 budget/pricing 與 corpus size 會變動。程式以 response headers、
`meta.cost_usd`、manifest 與當前 operator plan 為準，不把文件快照寫成永久 SLA。

## Endpoint families

OpenAlex 不只 `/works`。目前主要 entity families 包括 works、authors、sources、
institutions、publishers、funders、awards、topics/subfields/fields/domains、keywords、
SDGs，以及 vocabulary endpoints。`concepts` 已 deprecated；新知識工作流應優先
使用 topics/keywords，並標記它們是 OpenAlex model inference。

本 repo 的文獻 broker 以 `/works` 為主；其他 entity metadata 應作 enrichment 或
Research Chronicle/knowledge graph 的明確 section，不直接擴張 MCP 搜尋工具表面。

## Keyword search

Works `search` 查 title、abstract 與可用 full text。重要限制：

- supported `per_page <= 100`；舊有 200 頁面大小不得再使用
- basic paging 視窗最多 10,000；更深的 bounded traversal 使用 cursor
- OR values 每組最多 100
- `select` 只能選 root-level fields，不能 dotted nested select
- URL 長度有限；大型 OR query 要由 compiler 分塊、union/dedup 並保存 physical
  query provenance
- `search`、`search.exact`、`search.semantic` 一次只能使用一種

為避免大 payload，works search 只取 mapper 所需 root fields，例如 identifiers、
title/display name、abstract inverted index、publication date/year、authorships、
primary location、OA locations、citation count 與 type。

## Native semantic search

`search.semantic` 使用 title/abstract embeddings。官方限制：

- input 最多 2,000 characters
- 最多 50 results
- 1 request/second
- 只有 works endpoint
- 部分 filters 不支援，包括官方列出的 country/citation-related filters

Semantic mode 必須是 capability-aware plan：

1. validate query length、limit 與 filters；
2. 使用獨立 shared limiter；
3. 保存 mode、canonical query 與 warnings；
4. 若 policy 允許 fallback keyword，必須明示語意改變，不能 silent fallback。

目前明確指定不支援 semantic mode 的 source 會在 network call 前拒絕；未指定
`sources` 時 planner 只保留／補入有 semantic capability 的 OpenAlex。Runtime
不做 silent keyword fallback：

```python
unified_search(
    query="mechanisms of treatment resistance",
    sources="openalex",
    options="native_semantic",
    limit=50,
    output_format="json",
)
```

## Cursor 與 bounded pagination

Cursor 起始為 `cursor=*`，每頁使用 `meta.next_cursor`，null 表示終止。Broker
必須：

- 設定 max pages/results/time/cost
- 偵測 repeated cursor
- partial failure 時回傳已取得資料與 structured warning
- 把 opaque cursor 視為短期 continuation/checkpoint，不當永久 record ID
- 保存 `meta.count`、`meta.x_query`、`meta.cost_usd` 與 page provenance

官方明示不應用 cursor 下載整個 corpus；整庫與本地 mirror 使用 snapshot。

`options="systematic"` 會以 `publication_date:asc` 執行 bounded cursor，
並保存 `pages_fetched`、`bounded`、canonical query、continuation 與 cost。
由於 public `unified_search limit <= 100`，目前這是有界 reproducibility mode，
不是通往全 corpus 的隱藏下載路徑。

## Authentication、credits 與 resilience

- anonymous casual usage 仍可運作，但 budget 很小且不是 SLA。
- API key 提供較高的日 credit budget；上游可接受 query param 或 Bearer，本 repo
  固定使用 Bearer，避免把 key 放進 loggable URL。
- 最大 request rate 與 daily credits 是兩個不同限制；低於 RPS 仍可能耗盡 credits。
- 保存並解析 `X-RateLimit-Limit`、`Remaining`、`Credits-Used`、`Reset` 與
  `meta.cost_usd`，讓 broker 做 bounded budget 決策。
- 400 不重試；429/5xx 遵守 Retry-After/backoff/circuit breaker。
- 多 worker service 不能讓每個 process 各自放大同一 credential budget；正式水平
  擴展需要 shared ledger/limiter。

## Snapshot 與 sync data plane

Public snapshot 提供壓縮 JSONL/Parquet，規模是數百 GB、解壓後數 TB；不屬於預設
安裝或 MCP request 路徑。

- manifest 最後發布；指定 format/entity 的 manifest 存在才代表 release 完成
- 下載前後重取 manifest；若 release 改變，不 commit 混合版本
- partitions 依 updated date 移動，local index 以 OpenAlex ID upsert
- 必須 reconciliation 消失／deleted records；不能自行猜 merged aliases
- current snapshot 與 API shape 大致相同，但不是所有欄位完全一致
- 預設只規劃 selective profile；full corpus、content、TEI/PDF 全部 opt-in

這些 snapshot/sync 條目是後續 operator contract。本輪 registry 的
`operator_data_plane="provider_available"` 只表示官方路徑存在；repo 尚未宣稱已
建立 manifest checkpoint、downloader 或可搜尋的 local OpenAlex index。

OpenAlex metadata 是 CC0，但 linked PDF/full text 保留原始 copyright/license。
Metadata openness 不能推導出全文或 figure 的再散布權。

## 正規化與 provenance

OpenAlex payload 只 map 一次：

```text
OpenAlex response DTO + meta/rate headers
  -> source response envelope
  -> article mapper
  -> UnifiedArticle
  -> aggregation / ranking / Chronicle
```

不得先把原生 authorships/IDs/OA fields 改成 PubMed-like dict，再交給期待原生
OpenAlex schema 的 mapper。Envelope 應保留：

- items、total、next cursor
- keyword/semantic mode
- canonical `x_query` 與 physical chunks
- cost/rate metadata
- access path、fetched/release time
- unsupported-filter/fallback warnings

Topics、keywords 與 related-work signals 要標記 `inferred_by_openalex`；它們可協助
branching/ranking，但不能被敘述成作者明示的研究結論。

## 測試契約

- runtime search tool group exact 等於 `['unified_search']`
- raw fixture 經 client→runner→mapper 保留 OpenAlex ID、authors、DOI/PMID、OA、
  article type 與 citation metrics
- 所有 list endpoints page size <=100
- root-only select、OR 100、URL chunk union/dedup
- cursor null/repeat/resume/budget/partial failure
- semantic 2,000-char、50-result、1-RPS 與 unsupported filters
- cost/rate headers、429 reset、400 no-retry、5xx backoff
- snapshot manifest-before/after consistency、atomic publish、partition reconciliation

Gated live smoke 最多查少量 keyword records；semantic/cursor smoke 只有在 operator
明確提供 key 與 budget 時才執行，永不以 live cursor 擷取整庫。
