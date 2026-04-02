---
name: pubmed-export-citations
description: "Export citations with prepare_export. Triggers: 匯出, export, RIS, BibTeX, EndNote, Zotero, Mendeley, 引用格式, reference manager"
---

# 引用匯出指南

## 描述
引用匯出現在統一使用 `prepare_export`。最常見的做法是先搜尋，再用 `pmids="last"` 匯出上一輪搜尋結果；若只想匯出指定文章，則直接傳 PMID 清單。

---

## 快速決策樹

```text
需要匯出引用？
├── EndNote / Zotero / Mendeley → prepare_export(pmids="last", format="ris")
├── LaTeX / Overleaf → prepare_export(pmids="last", format="bibtex", source="local")
├── Excel / 分析 → prepare_export(pmids="last", format="csv", source="local")
└── 程式處理 → prepare_export(pmids="last", format="csl")
```

---

## 核心工具

```python
prepare_export(
    pmids="last",
    format="ris",
    include_abstract=True,
    source="official"
)
```

### `pmids` 可接受

- `"last"`
- `"12345678,87654321"`
- `["12345678", "87654321"]`
- `"PMID:12345678"`

---

## 來源與格式

| source | 支援格式 | 何時用 |
|--------|----------|--------|
| `official` | `ris`, `medline`, `csl` | 預設首選，品質最好 |
| `local` | `ris`, `bibtex`, `csv`, `medline`, `json` | 需要 BibTeX、CSV 或離線替代 |

### 常用格式

| 用途 | 呼叫方式 |
|------|----------|
| EndNote / Zotero / Mendeley | `prepare_export(pmids="last", format="ris")` |
| LaTeX / Overleaf | `prepare_export(pmids="last", format="bibtex", source="local")` |
| Excel / 數據分析 | `prepare_export(pmids="last", format="csv", source="local")` |
| 程式處理 | `prepare_export(pmids="last", format="csl")` |
| MEDLINE / NBIB 交換 | `prepare_export(pmids="last", format="medline")` |

---

## 常見工作流程

### 1. 搜尋後直接匯出

```python
unified_search(query="remimazolam ICU sedation", limit=30)
prepare_export(pmids="last", format="ris")
```

### 2. 匯出指定 PMID

```python
prepare_export(
    pmids="30217674,28523456,35678901",
    format="ris"
)
```

### 3. 匯出 BibTeX 給 LaTeX

```python
prepare_export(
    pmids="last",
    format="bibtex",
    source="local"
)
```

### 4. 同一批結果同時輸出兩種格式

```python
prepare_export(pmids="last", format="ris")
prepare_export(pmids="last", format="csv", source="local")
```

---

## 建議搭配工具

### 先確認上次搜尋結果有哪些 PMID

```python
get_session_pmids()
```

### 要先看文章細節再決定是否匯出

```python
fetch_article_details(pmids="12345678,87654321")
```

---

## 回傳結果你要關注什麼

- `status`
- `article_count`
- `format`
- `source`
- `export_text`

如果是較大量匯出，回傳也可能包含可下載的檔案路徑或檔案資訊。

---

## 實務建議

- 不確定時，先用 `format="ris"`, `source="official"`
- 只有 BibTeX 需要 `source="local"`
- 若要保留摘要，維持 `include_abstract=True`
- 若只要少數重點文章，不要直接匯出整個 `last`，改傳明確 PMID 清單
