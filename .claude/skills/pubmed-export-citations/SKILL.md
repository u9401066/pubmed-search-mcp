---
name: pubmed-export-citations
description: "Export citations and local wiki notes with prepare_export/save_literature_notes. Triggers: 匯出, export, RIS, BibTeX, EndNote, Zotero, Mendeley, 引用格式, wiki note, reference manager"
---

# 引用匯出指南

## 描述
引用匯出現在統一使用 `prepare_export`。若要把搜尋結果留成本機知識庫筆記，使用 `save_literature_notes`，預設輸出 wiki note（Foam-compatible wikilinks）並可附 CSL JSON。

---

## 快速決策樹

```text
需要匯出引用？
├── EndNote / Zotero / Mendeley → prepare_export(pmids="last", format="ris")
├── LaTeX / Overleaf → prepare_export(pmids="last", format="bibtex", source="local")
├── Excel / 分析 → prepare_export(pmids="last", format="csv", source="local")
├── 程式處理 → prepare_export(pmids="last", format="csl")
└── 本機知識庫 / Foam / Markdown → save_literature_notes(pmids="last")
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

save_literature_notes(
    pmids="last",
    note_format="wiki",
    output_dir=None,
    include_csl_json=True
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
| 本機 wiki note / Foam | `save_literature_notes(pmids="last")` |
| MedPaper-compatible reference note | `save_literature_notes(pmids="last", note_format="medpaper")` |

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

### 5. 搜尋後存成本機 wiki note

```python
unified_search(query="remimazolam ICU sedation", limit=30)
save_literature_notes(pmids="last")
```

預設輸出：

- 每篇文章一個 `.md` wiki note
- Foam-compatible `[[wikilink|title]]`
- YAML frontmatter with PMID/DOI/journal/year/citation_key
- `references.csl.json` for citation-manager handoff

如需使用者自訂模板：

```python
save_literature_notes(
    pmids="last",
    template_file="./reference-template.md",
    output_dir="./references"
)
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
