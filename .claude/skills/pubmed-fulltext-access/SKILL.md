---
name: pubmed-fulltext-access
description: "Full text access using get_fulltext, figure extraction, and institutional link tools. Triggers: 全文, fulltext, PDF, open access, 免費下載, PMC, 開放取用"
---

# 全文取得指南

## 描述
目前的全文 workflow 以 `get_fulltext` 為核心。它會自動嘗試 Europe PMC、Unpaywall、CORE，必要時可擴展到更多來源。若需要圖表、文字探勘或機構訂閱連結，則搭配其他專用工具。

## 觸發條件
- 「我要看全文」
- 「有 PDF 嗎？」
- 「這篇有 open access 嗎？」
- 「幫我抓方法或結果段落」
- 提到 PMC、全文、PDF、開放取用

---

## 核心工具

### 1. `get_fulltext`

```python
get_fulltext(identifier="PMC7096777")
get_fulltext(pmid="12345678")
get_fulltext(doi="10.1038/s41586-021-03819-2")
```

### 參數重點

- `identifier`: 自動判斷 PMID、PMCID、DOI
- `pmcid` / `pmid` / `doi`: 也可分開傳
- `sections`: 只抓特定段落，例如 `"introduction,methods,results"`
- `include_pdf_links`: 是否回傳 PDF 連結
- `include_figures`: 是否一起帶 figure metadata
- `extended_sources`: 是否擴展到更多來源

---

## 最常用範例

### 1. 直接抓 PMC 全文

```python
get_fulltext(identifier="PMC7096777")
```

### 2. 只看方法與結果

```python
get_fulltext(
    pmid="12345678",
    sections="methods,results"
)
```

### 3. 用 DOI 找 OA 版本

```python
get_fulltext(
    doi="10.1038/s41586-021-03819-2",
    extended_sources=True
)
```

### 4. 全文連同 figures

```python
get_fulltext(
    pmcid="PMC7096777",
    include_figures=True
)
```

---

## 圖表與視覺資料

### 取得文章圖表

```python
get_article_figures(identifier="PMC12086443")
get_article_figures(pmid="40384072")
```

適合用在：

- 要單獨抽 figure caption 與 image URL
- 想快速找到流程圖、結果圖、顯微圖
- 需要比全文更結構化的圖像資料

---

## 文字探勘

### 取得 text-mined terms

```python
get_text_mined_terms(pmcid="PMC7096777")
get_text_mined_terms(pmid="12345678", semantic_type="CHEMICAL")
```

常用 `semantic_type`:

- `GENE_PROTEIN`
- `DISEASE`
- `CHEMICAL`
- `ORGANISM`
- `GO_TERM`

---

## 沒有 open access 時

### 機構訂閱工作流

```python
list_resolver_presets()
configure_institutional_access(preset="exlibris_sfx", base_url="https://your-library...")
test_institutional_access()
get_institutional_link(pmid="12345678")
```

這一組工具適合：

- 已知機構有訂閱，但文章不是 OA
- 想把 PubMed/DOI 轉成圖書館 resolver 連結

---

## 建議工作流程

### 情境 1：從文章直接拿全文

```python
fetch_article_details(pmids="12345678")
get_fulltext(pmid="12345678", sections="abstract,results")
```

### 情境 2：搜尋後挑代表性文章讀全文

```python
unified_search(
    query="remimazolam ICU sedation",
    limit=10,
    ranking="quality"
)

# 對選中的 PMID 再做全文抓取
get_fulltext(pmid="12345678", extended_sources=True)
```

### 情境 3：先抓全文，再抽圖表與實體

```python
get_fulltext(pmcid="PMC7096777", include_figures=True)
get_article_figures(pmcid="PMC7096777")
get_text_mined_terms(pmcid="PMC7096777", semantic_type="CHEMICAL")
```

---

## 工具選擇規則

### 只想拿全文或 PDF

先用 `get_fulltext`

### 想抓圖表

用 `get_article_figures`

### 想抽 gene / disease / chemical

用 `get_text_mined_terms`

### 文章不是 OA，但你有圖書館帳號

用 `configure_institutional_access` + `get_institutional_link`

---

## 最後原則

全文工作流已經收斂成單一公開入口：先用 `get_fulltext`，需要圖表或 text mining 時再補用專用工具。
