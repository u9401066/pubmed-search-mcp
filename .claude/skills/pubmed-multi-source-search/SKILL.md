---
name: pubmed-multi-source-search
description: "Cross-database search using unified_search across academic sources. Triggers: 跨資料庫, multi-source, Semantic Scholar, OpenAlex, CORE, Europe PMC, 綜合搜尋"
---

# 多來源綜合搜尋

## 描述
目前公開且唯一的 generic literature search 入口是 `unified_search`。它會在 PubMed、OpenAlex、Semantic Scholar、Europe PMC 等 primary search adapters 之間分流，並在單次搜尋內整合與去重。Crossref 是以文章識別資料執行的 enrichment leg，不是接收原始查詢的 primary search source。

> 多來源搜尋是 bounded coverage expansion，不代表完整或 exhaustive coverage。回傳量受公開 `limit`、provider mode 與各來源能力限制；要做正式系統性回顧，使用 `options="systematic"` 的 bounded review-seed workflow，並另外保存後續補充檢索與篩選紀錄。

## 觸發條件
- 「跨資料庫搜尋」
- 「綜合搜尋」
- 「不要只看 PubMed」
- 提到 OpenAlex、Semantic Scholar、Europe PMC、preprint
- 需要跨來源擴充 coverage

---

## 核心原則

> 新 workflow 不再直接依賴多個來源別 MCP 工具。對大多數文獻搜尋情境，應優先使用 `unified_search`，而不是舊的來源別工具名稱。

跨來源 query 應使用 provider-neutral Boolean 語法。PubMed `[Title/Abstract]`、`[MeSH Terms]` 等 field tags 只能用於 `sources="pubmed"` 的獨立 leg。

---

## 核心工具

```python
unified_search(
    query="machine learning drug discovery",
    sources="pubmed,openalex,semantic_scholar,europe_pmc",
    limit=25,
    ranking="balanced",
    output_format="json"
)
```

### `sources` 可選值

- Primary search：
  - `pubmed`
  - `openalex`
  - `semantic_scholar`
  - `europe_pmc`
  - `core`
  - `arxiv`、`medrxiv`、`biorxiv`
- Licensed、default-off primary search：`scopus`、`web_of_science`
- Enrichment-only：`crossref`；它以已找到文章的 DOI/標題補 metadata，不是獨立 query leg，也不能作為唯一 primary source

如果不指定，系統會依 query profile、來源能力與可用設定自動選擇。選到 Crossref 時，它只在 primary results 之後做 enrichment。

---

## 常見用法

### 1. 廣泛 coverage expansion

```python
unified_search(
    query="machine learning drug discovery",
    limit=30,
    ranking="balanced"
)
```

### 2. 只看生醫核心來源

```python
unified_search(
    query="sepsis biomarkers",
    sources="pubmed,europe_pmc",
    limit=25,
    ranking="quality"
)
```

### 3. 納入預印本

```python
unified_search(
    query="COVID-19 vaccine efficacy",
    sources="pubmed,europe_pmc,openalex",
    options="preprints",
    limit=30,
    ranking="recency"
)
```

### 4. 看高影響力跨領域文獻

```python
unified_search(
    query="foundation models pathology",
    sources="pubmed,openalex,semantic_scholar",
    limit=30,
    ranking="impact"
)
```

### 5. 程式化後處理

```python
unified_search(
    query="CRISPR gene therapy",
    sources="pubmed,openalex,semantic_scholar,europe_pmc",
    limit=20,
    output_format="json"
)
```

---

## 建議工作流程

### 情境 1：跨來源做 bounded coverage expansion

```python
unified_search(
    query="remimazolam sedation",
    sources="pubmed,europe_pmc,openalex,semantic_scholar",
    limit=30,
    ranking="balanced"
)
```

### 情境 2：先找文獻，再補全文

```python
unified_search(
    query="machine learning radiology",
    limit=20,
    output_format="json"
)

# 對選中的 PMID / DOI 進一步抓全文
get_fulltext(pmid="12345678", extended_sources=True)
```

### 情境 3：跨來源搜尋後做探索

```python
unified_search(
    query="CAR-T lymphoma",
    limit=15,
    ranking="impact"
)

find_related_articles(pmid="12345678")
find_citing_articles(pmid="12345678")
get_citation_metrics(pmids="12345678,23456789")
```

---

## 何時調整 ranking

- `balanced`: 預設，一般探索
- `impact`: 先找高影響力代表作
- `recency`: 先看最新研究與更新動態
- `quality`: 偏向高證據等級與較可靠研究

---

## 何時使用 options

```python
options="preprints, shallow"
```

### 常見組合

- `preprints`: 想補最新未正式出版研究
- `shallow`: 只想快速掃過
- `no_relax`: 不希望零結果時自動放寬
- `no_analysis`: 程式輸出較乾淨
- `systematic`: 使用 capability-validated 的 bounded review-seed mode；每個來源最多 100 筆，並非窮盡檢索

---

## 不是這個 skill 的情境

- 要建立 MeSH / 同義詞 review-seed query：改用 `pubmed-systematic-search`
- 是臨床比較問題：改用 `pubmed-pico-search`
- 想找圖像：用 `search_biomedical_images`
- 想抓全文：用 `pubmed-fulltext-access`

---

## 最後原則

公開 MCP 介面中的 generic literature search 只有 `unified_search`，不再拆成來源別搜尋工作流。每次回報都要把 primary search、enrichment、bounded limits 與 supplemental runs 分清楚，不能把多來源合併等同於完整 coverage。

多來源 federation 允許 partial success。structured `source_counts`／`source_errors` 是權威狀態；
若有 artifact，先用 `read_session` 讀 `audit.json`、`query_strategy.json` 與完整 results，
再決定是否只重試失敗來源。不要用 Markdown 長度、PMID 文字出現次數或 agent hook 的
complexity hint 判斷搜尋是否成功。

一般 JSON/TOON result envelope 的 `search_status` 才是 agent routing contract：它會區分
`completed`／合法 `empty`／`partial`／`failed`，並固定揭露 bounded、
non-exhaustive、source sets 與 continuation/unknown-completeness。一般 deep mode 的
`limit` 是單一來源所有 strategies 共用的總額度；未知或格式錯誤的 filters/options
會在 provider I/O 前 fail closed。

需要回復歷程時，依序使用
`read_session(action="search_runs")`、`search_run`、`replay_search`。Replay 只回傳
已移除 credentials 的 `unified_search` kwargs，不會自動執行；provider cursor/token
目前只保存在 provenance，尚不能透過公開 facade 就地續頁。

同一套 search-run handoff 也涵蓋 inline、`saved:<name>` 與 `dry_run=true` pipeline
mode；非 dry-run saved pipeline 另外保留 PipelineStore history。若 pipeline text 含
credential material，系統會拒絕 execution 並留下 failed run。看到
`status="history_unavailable"`／`history_available=false` 時，不要嘗試不存在的
inspect/replay actions；這表示 durable history commit 無法保證。
