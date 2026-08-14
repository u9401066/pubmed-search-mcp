---
name: pubmed-systematic-search
description: "Bounded, reproducible review-seed search using generate_search_queries and unified_search. Triggers: 系統性搜尋, 完整搜尋, 文獻回顧, systematic search, comprehensive, MeSH expansion, 同義詞"
---

# 系統性回顧種子搜尋

## 描述
這個 workflow 用來建立可重現、可稽核的系統性回顧搜尋種子，而不是宣稱已找完所有文獻。核心做法是先用 `generate_search_queries` 取得 MeSH、同義詞與建議查詢，再由 Agent 或使用者組裝 provider-neutral Boolean 查詢，最後以唯一公開的文字文獻搜尋入口 `unified_search(options="systematic")` 執行有界檢索。

> `systematic` 是 bounded retrieval primitive：公開介面每個來源最多取回 100 筆，適合 review seed 與可重現的 coverage expansion，不代表 exhaustive systematic-review coverage。正式回顧仍需保存完整策略、逐來源檢索日期、後續分頁/補充來源與篩選紀錄。

## 觸發條件
- 「系統性搜尋」
- 「完整搜尋」
- 「文獻回顧」
- 「comprehensive search」
- 「systematic review」
- 提到 MeSH、同義詞擴展、搜尋策略

---

## 正確工作流程

```text
generate_search_queries
→ 整理 MeSH / 同義詞 / suggested_queries
→ 手動或由 Agent 組 provider-neutral Boolean 查詢
→ analyze_search_query
→ unified_search(options="systematic")
→ fetch_article_details / prepare_export / save_pipeline
```

> 目前沒有公開的獨立合併工具工作流。每一次 `unified_search` 本身就會做多來源整合與去重；如果你跑多輪策略，做法應該是比較各輪結果、調整查詢，或把流程保存成 pipeline，而不是依賴舊版 merge 思路。

---

## Step 1: 取得搜尋素材

```python
generate_search_queries(
    topic="remimazolam ICU sedation",
    strategy="comprehensive"
)
```

### `strategy` 選項

- `comprehensive`: 預設，適合完整展開查詢素材；不代表結果已窮盡
- `focused`: 收斂到較高證據等級
- `exploratory`: 放寬，找更多變體與同義詞

### 你真正要用的欄位

- `mesh_terms`: 標準詞彙與對應同義詞
- `all_synonyms`: 可直接組 OR 群組
- `suggested_queries`: 當作參考，不是最後答案
- `pubmed_translation`: 檢查 PubMed 實際如何理解查詢

---

## Step 2: 組裝 Boolean 查詢

### 範例：從素材組出跨來源可執行查詢

```python
query = '''
("intensive care" OR ICU OR "critical care")
AND
(remimazolam OR "CNS 7056" OR "ONO 2745")
AND
(sedation OR "procedural sedation")
'''
```

### 兩個原則

1. 主概念之間通常用 `AND`
2. 同義詞與別名通常用 `OR`

PubMed 的 `[Title/Abstract]`、`[MeSH Terms]` 等 field tags 不是 provider-neutral 語法。含這些 tags 的查詢只送 `sources="pubmed"`；跨來源 systematic leg 使用上面的無欄位標籤 Boolean 查詢，讓各 provider adapter 依自身契約編譯。

---

## Step 3: 執行前先分析

```python
analyze_search_query(query=query)
```

這一步用來確認：

- 查詢是否太寬或太窄
- PubMed translation 是否符合預期
- 有沒有拼字或概念錯置

---

## Step 4: 執行搜尋

```python
unified_search(
    query=query,
    sources="pubmed,openalex,semantic_scholar",
    options="systematic",
    limit=100,
    ranking="quality",
    filters="year:2020-2025",
    output_format="json"
)
```

`options="systematic"` 會關閉 deep expansion 與自動放寬，並在 I/O 前拒絕不支援此模式的 explicit source。現在的 bounded systematic sources 是 PubMed、OpenAlex 與 Semantic Scholar；Europe PMC、CORE、Scopus、Web of Science 與 preprint adapters 目前是 keyword-only，若要納入需另跑並標記為 supplemental search。

### 常用調整方式

- 想補最新未同行評審研究：另跑 `options="preprints"` 的 keyword search，並標成補充來源
- 想做快速探索：另跑 `options="shallow"`，不要把它標成 systematic run
- systematic mode 已停用自動放寬；不要用放寬後的結果冒充原始策略命中
- 重視新近性：`ranking="recency"`
- 重視證據品質：`ranking="quality"`

---

## 端到端範例

### 情境：建立 remimazolam ICU sedation 的 bounded review seed

```python
# Step 1: 取得 MeSH 與同義詞素材
materials = generate_search_queries(
    topic="remimazolam ICU sedation",
    strategy="comprehensive"
)

# Step 2: 組裝查詢
query = '''
("intensive care" OR ICU OR "critical care")
AND
(remimazolam OR "CNS 7056" OR "ONO 2745")
AND
(sedation OR "procedural sedation")
'''

# Step 3: 先分析
analyze_search_query(query=query)

# Step 4: 再執行
unified_search(
    query=query,
    sources="pubmed,openalex,semantic_scholar",
    options="systematic",
    limit=100,
    ranking="quality",
    filters="year:2020-2025",
    output_format="json"
)
```

### PubMed-only fielded leg

如果 protocol 需要 PubMed 欄位限定，另建一個只送 PubMed 的 leg，不要把同一字串傳給其他 provider：

```python
pubmed_fielded_query = '''
("intensive care"[Title/Abstract] OR ICU[Title/Abstract])
AND
(remimazolam[Title/Abstract] OR "CNS 7056"[Title/Abstract])
AND
(sedation[Title/Abstract] OR "procedural sedation"[Title/Abstract])
'''

unified_search(
    query=pubmed_fielded_query,
    sources="pubmed",
    options="systematic",
    limit=100,
    filters="year:2020-2025",
    output_format="json"
)
```

---

## 如果結果太少或太多

### 結果太少

- 把 `strategy` 改成 `exploratory`
- 移除部分限制條件
- 減少 `AND`、增加同義詞 `OR`
- 移除 `clinical` 或過窄的年齡/性別限制

### 結果太多

- 把 `strategy` 改成 `focused`
- 增加主題限定詞
- 加上 `filters="year:..., clinical:..."`
- 把 sources 收斂到支援 systematic 的必要來源；若使用 PubMed field tags，則只送 `pubmed`

---

## 可重複使用時

當搜尋策略已經穩定，不要每次重組：

```python
save_pipeline(name="icu_sedation_review", pipeline_config="...")
```

之後可以：

```python
unified_search(pipeline="saved:icu_sedation_review")
```
