---
name: pubmed-gene-drug-research
description: "Gene, compound, and variant research using search_gene, search_compound, and search_clinvar. Triggers: 基因, gene, 藥物, drug, compound, PubChem, ClinVar, 變異, variant, 臨床意義"
---

# 基因與藥物研究

## 描述
這個 workflow 用在基因、化合物、藥物與臨床變異查詢。公開 MCP 工具已經收斂成一組新的 NCBI extended 介面：基因用 `search_gene` / `get_gene_details` / `get_gene_literature`，化合物用 `search_compound` / `get_compound_details` / `get_compound_literature`，變異則用 `search_clinvar`。

## 觸發條件
- 「這個基因的功能是什麼？」
- 「這個藥物的結構或機轉？」
- 「這個變異的臨床意義？」
- 提到 BRCA1、TP53、CYP2C9、warfarin、PubChem、ClinVar

---

## 工具對照

| 主題 | 工具 |
|------|------|
| Gene 搜尋 | `search_gene`, `get_gene_details`, `get_gene_literature` |
| Compound 搜尋 | `search_compound`, `get_compound_details`, `get_compound_literature` |
| Variant / ClinVar | `search_clinvar` |
| 後續文獻追蹤 | `fetch_article_details`, `unified_search` |

---

## Gene 工作流

### 1. 搜尋基因

```python
search_gene(query="BRCA1", organism="human")
```

### 2. 取得基因詳情

```python
get_gene_details(gene_id="672")
```

### 3. 取得基因相關文獻

```python
get_gene_literature(gene_id="672", limit=20)
```

### 4. 展開 PubMed 細節

```python
fetch_article_details(pmids="12345678,87654321")
```

> `get_gene_literature` 走的是 NCBI curated gene-to-publication links，通常比單純 keyword 搜尋更準。

---

## Compound / Drug 工作流

### 1. 搜尋化合物

```python
search_compound(query="remimazolam")
```

### 2. 取得化合物詳情

```python
get_compound_details(cid="11526795")
```

### 3. 取得化合物相關文獻

```python
get_compound_literature(cid="11526795", limit=20)
```

### 4. 做更廣泛的機轉或比較搜尋

```python
unified_search(
    query="remimazolam mechanism action",
    limit=20,
    ranking="quality"
)
```

---

## ClinVar / Variant 工作流

### 搜尋變異

```python
search_clinvar(query="BRCA1 pathogenic")
search_clinvar(query="NM_007294.4:c.5266dupC")
search_clinvar(query="CYP2C9 drug response")
```

### 使用方式重點

- 查 gene-level 臨床意義：`search_clinvar(query="BRCA1 pathogenic")`
- 查精確變異：用 HGVS，例如 `NM_007294.4:c.5266dupC`
- 查藥物基因體學：用基因 + phenotype，例如 `CYP2C9 drug response`

> 目前公開介面沒有獨立的 ClinVar detail 工具。要更精準，就把 `search_clinvar` 的查詢寫得更具體。

---

## 常見整合流程

### 情境 1：基因到文獻

```python
search_gene(query="TP53", organism="human")
get_gene_details(gene_id="7157")
get_gene_literature(gene_id="7157", limit=20)
```

### 情境 2：藥物到文獻

```python
search_compound(query="propofol")
get_compound_details(cid="4943")
get_compound_literature(cid="4943", limit=20)
```

### 情境 3：變異到機轉與文獻

```python
search_clinvar(query="BRCA1 pathogenic")
search_gene(query="BRCA1", organism="human")
unified_search(
    query="BRCA1 pathogenic variant DNA repair",
    limit=20,
    ranking="quality"
)
```

### 情境 4：藥物基因組學

```python
search_compound(query="warfarin")
search_gene(query="CYP2C9 warfarin metabolism", organism="human")
search_clinvar(query="CYP2C9 drug response")
unified_search(
    query="warfarin CYP2C9 pharmacogenomics",
    limit=30,
    ranking="quality"
)
```

---

## 實務建議

### Gene

- 優先用官方 symbol，例如 `TP53`，不要先用模糊別名
- 常常要補 `organism="human"`，避免混到小鼠或其他物種

### Compound

- 優先用 generic name，不要先用商品名
- 一旦拿到 CID，後續都用 CID 最穩定

### ClinVar

- 最精確的是 HGVS 命名
- 次佳是 `gene + pathogenic` 或 `gene + condition`

---

## 最後原則

新的公開工具名應統一為：

- `search_gene`
- `get_gene_details`
- `get_gene_literature`
- `search_compound`
- `get_compound_details`
- `get_compound_literature`
- `search_clinvar`
