---
name: pubmed-multi-source-search
description: "Cross-database search using unified_search across academic sources. Triggers: 跨資料庫, multi-source, Semantic Scholar, OpenAlex, CORE, Europe PMC, 綜合搜尋"
---

# 多來源綜合搜尋

## 描述
目前公開的多來源搜尋入口是 `unified_search`。它會自動在 PubMed、OpenAlex、Semantic Scholar、Europe PMC、CrossRef 之間分流，並在單次搜尋內做整合與去重。

## 觸發條件
- 「跨資料庫搜尋」
- 「綜合搜尋」
- 「不要只看 PubMed」
- 提到 OpenAlex、Semantic Scholar、Europe PMC、preprint
- 需要跨來源補足 coverage

---

## 核心原則

> 新 workflow 不再直接依賴多個來源別 MCP 工具。對大多數文獻搜尋情境，應優先使用 `unified_search`，而不是舊的來源別工具名稱。

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

- `pubmed`
- `openalex`
- `semantic_scholar`
- `europe_pmc`
- `crossref`

如果不指定，系統會自動選來源。

---

## 常見用法

### 1. 廣泛覆蓋

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

### 情境 1：跨來源找完整 coverage

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

---

## 不是這個 skill 的情境

- 要做 MeSH / 同義詞完整展開：改用 `pubmed-systematic-search`
- 是臨床比較問題：改用 `pubmed-pico-search`
- 想找圖像：用 `search_biomedical_images`
- 想抓全文：用 `pubmed-fulltext-access`

---

## 最後原則

公開 MCP 介面中的文字文獻搜尋，應以 `unified_search` 為主，不再拆成來源別搜尋工作流。
