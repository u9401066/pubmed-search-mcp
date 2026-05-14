# PubMed Search MCP 改善報告：大型搜尋回傳造成 OOM / PDF fallback 不一致

日期：2026-05-14  
工作區：`D:\workspace260514_clinetest`  
任務情境：搜尋 2026 年、麻醉領域、AI 影響醫療／臨床流程／決策支援、且可取回 PDF 的高品質期刊文章。

## 1. 摘要

本次使用 PubMed Search MCP 執行文獻搜尋時，曾發生 OOM / 對話中斷。根據工具輸出與行為觀察，最可能原因不是 PubMed API 查詢本身錯誤，而是 **`unified_search` 在 JSON 模式下回傳 payload 過大**，導致 Cline / VS Code / LLM client 端上下文或記憶體壓力過高。

同時也發現 `get_fulltext` 的 PDF 取得流程存在不一致：同一篇文章用 PMID 查不到直接 PDF，但改用 DOI 查詢即可透過 Unpaywall 找到 publisher PDF。這表示 `get_fulltext(pmid=...)` 需要更穩定地解析 DOI 並接續 DOI-based fulltext workflow。

主要問題：

1. 大型 `unified_search(..., output_format="json")` 回傳過肥，包含大量 article metadata、abstract、authors、provenance、deep search、reproducibility 等區塊。
2. `limit` 語意容易誤導：設定 `limit=50`，但 multi-source / deep-search 內部可能處理 100–150 筆以上資料。
3. `no_analysis` 等減量 options 對 JSON 輸出不夠有效，仍可能回傳大型 metadata。
4. `get_fulltext(pmid=...)` 沒有穩定執行 PMID → DOI → Unpaywall / CORE / CrossRef fallback。
5. 缺乏 response-size guardrail：沒有在 payload 超過安全門檻時自動縮減、分頁或改回 session result ID。

---

## 2. 本次觀察到的症狀

### 2.1 大型搜尋回傳內容過多

曾使用類似查詢：

```text
unified_search(
  query="(artificial intelligence OR machine learning OR large language model OR ChatGPT OR clinical decision support) AND (anesthesiology OR anesthesia OR perioperative ...)",
  limit=50,
  sources="pubmed,openalex,europe_pmc",
  ranking="impact",
  output_format="json",
  filters="year:2026, lang:english",
  options="all_types,no_analysis"
)
```

工具回傳不只是文章清單，而是包含：

- `analysis`
- `statistics`
- `articles`，且每篇含完整 abstract、authors、identifiers、journal metrics、OA links、ranking / similarity 等
- `source_counts`
- `next_tools`
- `next_commands`
- `deep_search`
- `source_disagreement`
- `reproducibility`
- `section_provenance`

搜尋統計曾出現：

```text
total_input: 150
unique_articles: 142
pubmed returned: 100
europe_pmc returned: 50
```

這代表即使使用者只想看 top 50，MCP 實際處理與輸出的資料量仍非常大。

### 2.2 `no_analysis` 沒有有效縮減 JSON payload

本次曾使用：

```text
options="all_types,no_analysis"
```

但 JSON 回應仍包含 `analysis`、`deep_search`、`section_provenance`、`source_disagreement`、`reproducibility` 等大型區塊。

判讀：

- `no_analysis` 可能只影響 markdown 顯示，或沒有完整套用到 JSON serializer。
- 使用者以為已減量，但實際仍會產生大型 payload。

### 2.3 PMID fulltext lookup 與 DOI fulltext lookup 結果不一致

同一篇文章：

```text
Perioperative Best Practices and Delirium in Patients With Cognitive Impairment
PMID: 41817525
DOI: 10.1001/jamanetworkopen.2026.1515
```

用 PMID 查詢：

```text
get_fulltext(pmid="41817525", extended_sources=true)
```

結果只找到 publisher landing page。

用 DOI 查詢：

```text
get_fulltext(doi="10.1001/jamanetworkopen.2026.1515", extended_sources=true)
```

成功找到 Unpaywall publisher PDF：

```text
https://jamanetwork.com/journals/jamanetworkopen/articlepdf/2846289/scharp_2026_oi_260076_1772728690.10478.pdf
```

判讀：

- `get_fulltext(pmid=...)` 應先解析 PubMed metadata 的 DOI。
- 若 DOI 存在，應自動接續 DOI-based Unpaywall / CORE / CrossRef / publisher link workflow。
- PMID path 與 DOI path 應共用同一個 resolver pipeline。

---

## 3. 根因分析

### 3.1 搜尋結果 serializer 過度完整

`unified_search` 對 agent 很有用，但目前 JSON 回傳像是完整 debug / audit dump，而不是互動式搜尋摘要。

大型欄位包括：

- 完整 abstract
- 完整 authors list
- journal metrics
- source / provenance metadata
- next tool suggestions
- deep search execution traces
- reproducibility audit
- source disagreement matrix

這些資訊適合 debug 或 audit mode，不適合每次大型搜尋預設回傳。

### 3.2 `limit` 同時扮演多種角色

目前 `limit` 容易被理解為「最後最多回傳 N 篇」。但 deep search / source adapter 可能把它用於：

- 每個來源的 query limit
- 每個 strategy 的 limit
- 最終合併排序後的 limit
- detail enrichment 的 limit

因此 `limit=50` 在 multi-source + deep-search 時，實際可能造成 100–150+ records 被處理與部分輸出。

### 3.3 沒有 payload safety cap

回傳前缺少類似：

```text
max_response_chars
max_articles_with_abstract
max_author_count_per_article
max_provenance_entries
```

因此某些查詢會一次把大量 JSON 塞給 client。

### 3.4 fulltext pipeline 的 identifier normalization 不一致

PMID、DOI、PMCID path 應先做 identifier resolution，再進入同一個 fulltext resolver pipeline。

目前觀察到：

```text
PMID path → publisher landing page only
DOI path → Unpaywall publisher PDF found
```

代表 resolver pipeline 需要統一。

---

## 4. 改善建議

### P0：新增 compact / minimal response mode

建議讓大型搜尋預設或可選回傳 compact fields：

```json
{
  "articles": [
    {
      "title": "...",
      "pmid": "...",
      "doi": "...",
      "journal": "...",
      "year": 2026,
      "publication_date": "...",
      "article_type": "...",
      "open_access": true,
      "pdf_available": true,
      "pdf_url": "...",
      "score": 0.93
    }
  ],
  "result_id": "search_xxx",
  "truncated": false
}
```

完整 abstract / authors / provenance 改由後續工具取得：

```text
fetch_article_details(pmids="...")
read_session(action="article", pmid="...")
```

### P0：加入 `fields` / `include` / `exclude` 參數

建議 `unified_search` 支援：

```text
fields="title,pmid,doi,journal,year,oa_status,pdf_url,score"
```

或：

```text
include="abstract,authors,journal_metrics"
exclude="analysis,provenance,next_tools,deep_search,source_disagreement,reproducibility"
```

讓 agent 可以明確控制 payload。

### P0：加入 response hard cap 與 graceful truncation

建議新增：

```text
max_response_chars=50000
```

當回應超過門檻時，自動改成：

```json
{
  "status": "truncated",
  "reason": "response_size_exceeded",
  "result_id": "search_20260514_xxx",
  "returned_articles": 20,
  "total_available": 142,
  "next": "read_session(action='pmids') or unified_search(..., page=2)"
}
```

### P0：修正 `no_analysis` / `no_scores` / `shallow` 對 JSON 的行為

目前 `no_analysis` 不應只影響 markdown。建議對 JSON serializer 也生效：

```text
no_analysis   → remove analysis, source_disagreement, reproducibility
no_scores     → remove ranking/similarity details
shallow       → disable deep_search and remove deep_search traces
no_next       → remove next_tools / next_commands
no_provenance → remove section_provenance
```

若為 backward compatibility，可新增：

```text
options="compact"
```

等同：

```text
no_analysis,no_scores,no_next,no_provenance,shallow
```

### P0：修正 PMID → DOI → PDF fallback

建議 `get_fulltext` 流程改成：

```text
input identifier
  ↓
normalize identifiers:
  - pmid
  - doi
  - pmcid
  ↓
if pmcid: try PMC / Europe PMC
if doi: try Unpaywall / CORE / CrossRef / publisher
if pmid only: fetch PubMed details → resolve DOI/PMCID → retry above
  ↓
merge and dedupe links
```

PMID path 和 DOI path 應使用同一個 resolver，不應出現同文獻 PMID 查不到、DOI 查得到的差異。

### P1：拆分 `limit` 語意

建議把目前的 `limit` 拆成：

```text
per_source_limit=20
strategy_limit=20
final_limit=20
detail_limit=10
```

或至少在回應中清楚標示：

```json
{
  "limits": {
    "requested_limit": 50,
    "per_source_limit": 50,
    "final_limit": 50,
    "detail_enriched": 50
  }
}
```

### P1：session-first 大型搜尋

對大型搜尋，建議預設把完整結果寫入 session cache，只回簡表：

```json
{
  "result_id": "search_xxx",
  "pmids": ["..."],
  "articles_preview": []
}
```

再用：

```text
read_session(action="pmids", search_index=-1)
read_session(action="article", pmid="...")
```

逐步取資料。

已實作補強：`unified_search` 與 `get_fulltext` 會在 session persistence
啟用時產生 persistent artifact。回應只放精簡 locator，包含
`artifact_id`、`artifact_uri`、`local_path`、`manifest_path`、`primary_file`
與 `read_session(...)` 提示；完整 payload 會落在本機 artifact 檔案。

遠端 client 無法讀本機路徑時，可用：

```text
read_session(action="list_artifacts")
read_session(action="artifact", artifact_uri="artifact://...")
read_session(action="artifact", artifact_id="...", artifact_file="payload.json", offset=0, max_chars=200000)
read_session(action="list_artifacts", include_local_paths=true)
```

artifact 是由已完成的搜尋/全文結果序列化而來，不會重新呼叫 Semantic
Scholar、Europe PMC、Unpaywall 或 PDF fallback。`unified_search` 即使因
response hard cap 被截斷，也會保留 artifact locator，避免大型輸出時丟失
後續檢索入口。`read_session` 預設隱去 local paths；本機 server 工作流可
用 `include_local_paths=true` 顯示檔案路徑。

Release note: `local_path` and `manifest_path` are MCP server-host paths, not
portable remote-client paths. They are hidden from primary responses unless
`PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS=true` is set, and `read_session` keeps them
redacted unless `include_local_paths=true` is requested. Large `get_fulltext`
responses are capped inline when an artifact exists; the artifact contains the
saved full content. `get_fulltext` artifacts may contain article body text,
including subscription or institutionally accessed content; production
deployments should follow publisher license, institutional access, sharing, and
retention policies.

When one source fails but the overall search can continue, `unified_search`
JSON returns `source_errors` and markdown responses show `Source warnings`.
Semantic Scholar HTTP 429 warnings recommend setting `S2_API_KEY` /
`SEMANTIC_SCHOLAR_API_KEY`, retrying later, or excluding the source with
`sources="auto,-semantic_scholar"` /
`PUBMED_SEARCH_DISABLED_SOURCES=semantic_scholar`.

### P1：加入 PDF-only / OA-only search mode

本次需求是「需要能取回 PDF 的文章才要」。目前流程是先搜尋，再逐篇 `get_fulltext`。建議支援：

```text
filters="year:2026, lang:english, pdf:true"
options="require_pdf"
```

或：

```text
unified_search(..., require_pdf=true)
```

行為：

- 搜尋後自動嘗試 DOI/PMCID PDF resolution。
- 最終只回 `pdf_available=true` 的文章。
- PDF URL 欄位預設出現在 compact output。

### P2：新增 OOM / payload regression tests

建議新增測試：

1. `unified_search(limit=50, output_format=json, options=compact)` 回應大小不得超過門檻。
2. `options=no_analysis` 時 JSON 不含 `analysis`、`deep_search`、`source_disagreement`、`reproducibility`。
3. `get_fulltext(pmid=41817525)` 應能解析 DOI 並找到 JAMA PDF。
4. `require_pdf=true` 時，不回傳無 PDF 文章。
5. large author list / long abstract 應截斷或轉 detail endpoint。

---

## 5. 建議實作順序

### 第一階段：快速止血

1. 新增 `options="compact"`。
2. `no_analysis` 對 JSON 真正移除大型區塊。
3. 預設限制 authors 顯示最多 3–5 位，abstract 預設不回或截斷。
4. `get_fulltext(pmid=...)` 自動解析 DOI 並走 DOI resolver。

### 第二階段：穩定大型搜尋

1. 加入 `max_response_chars` hard cap。
2. 大型結果寫入 session，只回 `result_id`。
3. 拆分 `per_source_limit` / `final_limit` / `detail_limit`。
4. 加入 pagination。

### 第三階段：改善使用者任務流程

1. 支援 `require_pdf=true`。
2. 支援 `fields` / `include` / `exclude`。
3. 加入 search workflow templates：
   - `quick_compact`
   - `pdf_only`
   - `systematic_audit`
   - `zotero_import_ready`

---

## 6. 建議使用者端暫時操作方式

在 MCP 修正前，建議採取以下安全流程，避免再次 OOM：

```text
1. unified_search limit 先用 10–20
2. output_format 優先 markdown 或 toon，避免大型 json
3. sources 先限 pubmed,europe_pmc
4. options 加 shallow,no_analysis,no_scores
5. 不一次要求 journal_metrics / provenance / deep_search
6. 只對入選 PMID/DOI 做 get_fulltext
7. 查 PDF 時 DOI 優先於 PMID
8. extended_sources=true 只對少數重點文章開啟
```

對本次任務，較安全的查詢形態會是：

```text
unified_search(
  query="artificial intelligence anesthesiology perioperative clinical decision support",
  sources="pubmed,europe_pmc",
  limit=15,
  ranking="impact",
  output_format="markdown",
  filters="year:2026, lang:english",
  options="shallow,no_analysis,no_scores"
)
```

然後針對候選 DOI：

```text
get_fulltext(doi="...", extended_sources=true)
```

---

## 7. 結論

本次 PubMed Search MCP 問題主要是 **大型 JSON 輸出缺少尺寸控制**，加上 **fulltext PMID path 與 DOI path 不一致**。

最優先修正：

- **compact response mode**
- **JSON options 真正減量**
- **response hard cap + session result ID**
- **PMID → DOI → Unpaywall/PDF fallback**
- **大型搜尋 regression tests**

修正後，像「找 2026 年麻醉 AI 高分期刊且需 PDF」這類任務，就能先安全取得短清單，再逐篇取 fulltext/PDF，不會因一次回傳過量 metadata 而造成 OOM。
