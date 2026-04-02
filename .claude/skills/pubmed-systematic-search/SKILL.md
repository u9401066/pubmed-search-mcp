---
name: pubmed-systematic-search
description: "Comprehensive search using generate_search_queries and unified_search. Triggers: 系統性搜尋, 完整搜尋, 文獻回顧, systematic search, comprehensive, MeSH expansion, 同義詞"
---

# 系統性文獻搜尋

## 描述
這個 workflow 用在「要找得完整」而不是「先快速看一下」的情境。核心做法是先用 generate_search_queries 取得 MeSH、同義詞與建議查詢，再由 Agent 或使用者組裝成明確的 Boolean 查詢，最後用 unified_search 執行。

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
→ 手動或由 Agent 組 Boolean 查詢
→ analyze_search_query
→ unified_search
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

- `comprehensive`: 預設，適合完整搜尋
- `focused`: 收斂到較高證據等級
- `exploratory`: 放寬，找更多變體與同義詞

### 你真正要用的欄位

- `mesh_terms`: 標準詞彙與對應同義詞
- `all_synonyms`: 可直接組 OR 群組
- `suggested_queries`: 當作參考，不是最後答案
- `pubmed_translation`: 檢查 PubMed 實際如何理解查詢

---

## Step 2: 組裝 Boolean 查詢

### 範例：從素材組出可執行查詢

```python
query = '''
("Intensive Care Units"[Title/Abstract] OR ICU[Title/Abstract] OR "critical care"[Title/Abstract])
AND
(remimazolam[Title/Abstract] OR "CNS 7056"[Title/Abstract] OR "ONO 2745"[Title/Abstract])
AND
(sedation[Title/Abstract] OR "procedural sedation"[Title/Abstract])
'''
```

### 兩個原則

1. 主概念之間通常用 `AND`
2. 同義詞與別名通常用 `OR`

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
    sources="pubmed,europe_pmc,openalex",
    limit=50,
    ranking="quality",
    filters="year:2020-2025, species:humans, clinical:therapy",
    output_format="json"
)
```

### 常用調整方式

- 想更完整：加入 `options="preprints"`
- 想更快：加入 `options="shallow"`
- 不要自動放寬：加入 `options="no_relax"`
- 重視新近性：`ranking="recency"`
- 重視證據品質：`ranking="quality"`

---

## 完整範例

### 情境：完整搜尋 remimazolam ICU sedation

```python
# Step 1: 取得 MeSH 與同義詞素材
materials = generate_search_queries(
    topic="remimazolam ICU sedation",
    strategy="comprehensive"
)

# Step 2: 組裝查詢
query = '''
("intensive care"[Title/Abstract] OR ICU[Title/Abstract] OR "critical care"[Title/Abstract])
AND
(remimazolam[Title/Abstract] OR "CNS 7056"[Title/Abstract] OR "ONO 2745"[Title/Abstract])
AND
(sedation[Title/Abstract] OR "procedural sedation"[Title/Abstract])
'''

# Step 3: 先分析
analyze_search_query(query=query)

# Step 4: 再執行
unified_search(
    query=query,
    limit=50,
    ranking="quality",
    filters="year:2020-2025, species:humans, clinical:therapy",
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
- 把 sources 收斂到 `pubmed,europe_pmc`

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
