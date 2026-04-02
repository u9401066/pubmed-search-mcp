---
name: pubmed-quick-search
description: "Quick literature search using unified_search. Triggers: 搜尋, 找論文, search papers, find articles, PubMed, 文獻搜尋, 快速搜尋"
---

# 快速文獻搜尋

## 描述
用 unified_search 做第一輪文獻探索。它會自動分析查詢、選擇來源、合併去重，適合快速確認某個主題是否有研究、有哪些代表性文章，以及是否值得進一步做系統性搜尋。

## 觸發條件
- 「幫我找...的論文」
- 「有沒有關於...的文章」
- 「先快速搜尋一下...」
- 「search papers about...」
- 「find articles on...」

---

## 核心工具

```python
unified_search(
    query="remimazolam ICU sedation",
    limit=10,
    ranking="balanced",
    output_format="markdown"
)
```

### 參數重點

- `query`: 自然語言、Boolean 查詢、或包含 ICD 代碼的查詢都可以
- `limit`: 每個來源最多取回幾篇
- `sources`: 可指定 `pubmed,openalex,semantic_scholar,europe_pmc,crossref`
- `ranking`: `balanced`, `impact`, `recency`, `quality`
- `filters`: 以逗號分隔的篩選條件
- `options`: 額外旗標，例如預印本、是否深搜等

> 快速搜尋時，優先使用自然語言 + `filters`。只有在需要精細組裝查詢時，才切到系統性搜尋 skill。

---

## 最常用範例

### 1. 一般主題搜尋

```python
unified_search(query="remimazolam ICU sedation", limit=10)
```

### 2. 最近幾年的臨床研究

```python
unified_search(
    query="diabetes treatment",
    limit=20,
    ranking="quality",
    filters="year:2020-2025, species:humans, clinical:therapy"
)
```

### 3. 看最新研究

```python
unified_search(
    query="lung cancer liquid biopsy",
    limit=15,
    ranking="recency"
)
```

### 4. 看高影響力文獻

```python
unified_search(
    query="CAR-T therapy lymphoma",
    limit=15,
    ranking="impact"
)
```

### 5. 限定來源

```python
unified_search(
    query="CRISPR gene therapy",
    sources="pubmed,openalex,europe_pmc",
    limit=20
)
```

### 6. 納入預印本

```python
unified_search(
    query="COVID-19 vaccine efficacy",
    limit=20,
    options="preprints"
)
```

---

## `filters` 速查

```python
filters="year:2020-2025, age:aged, sex:female, species:humans, lang:english, clinical:therapy"
```

### 可用欄位

- `year`: `2020-2025`, `2020-`, `-2025`, `2024`
- `age`: `newborn`, `infant`, `preschool`, `child`, `adolescent`, `young_adult`, `adult`, `middle_aged`, `aged`, `aged_80`
- `sex`: `male`, `female`
- `species`: `humans`, `animals`
- `lang`: `english`, `chinese` 等
- `clinical`: `therapy`, `therapy_narrow`, `diagnosis`, `diagnosis_narrow`, `prognosis`, `etiology` 等

---

## `options` 速查

```python
options="preprints, shallow"
```

### 常用旗標

- `preprints`: 納入 arXiv、medRxiv、bioRxiv
- `all_types`: 放寬 peer-reviewed 限制
- `no_oa`: 不做 OA 連結補強
- `no_analysis`: 不顯示查詢分析
- `no_scores`: 不顯示分數
- `no_relax`: 關閉零結果時的自動放寬
- `shallow`: 關閉深搜，速度較快

---

## 查詢不確定時

先分析，不要直接盲搜：

```python
analyze_search_query(query="remimazolam vs propofol for ICU sedation")
```

如果需要 MeSH、同義詞、建議查詢，再用：

```python
generate_search_queries(topic="remimazolam ICU sedation")
```

---

## 搜尋後常見下一步

1. 讀細節：`fetch_article_details(pmids="12345678")`
2. 找相似研究：`find_related_articles(pmid="12345678")`
3. 看誰引用它：`find_citing_articles(pmid="12345678")`
4. 抓全文：`get_fulltext(pmid="12345678")`
5. 匯出引用：`prepare_export(pmids="last", format="ris")`

---

## 什麼時候不要停在這個 skill

- 需要 MeSH 與同義詞完整展開：改用 `pubmed-systematic-search`
- 是臨床比較問題：改用 `pubmed-pico-search`
- 需要全文、圖表、PDF：改用 `pubmed-fulltext-access`
