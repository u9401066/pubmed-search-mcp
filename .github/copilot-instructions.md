# GitHub Copilot Instructions for PubMed Search MCP

This document provides guidance for AI assistants working with the PubMed Search MCP server.

---

## ⚡ 開發環境規範 (CRITICAL)

### 套件管理：使用 UV (NOT pip)

本專案**必須**使用 [UV](https://github.com/astral-sh/uv) 管理所有 Python 依賴：

```bash
# ❌ 禁止使用
pip install <package>
pip install -r requirements.txt

# ✅ 正確使用
uv add <package>           # 新增依賴
uv add --dev <package>     # 新增開發依賴
uv remove <package>        # 移除依賴
uv sync                    # 同步依賴
uv run pytest              # 透過 uv 執行命令
uv run python script.py    # 透過 uv 執行 Python
```

### 程式碼品質工具

```bash
uv run ruff check .        # Lint 檢查
uv run ruff format .       # 格式化
uv run mypy src/           # 型別檢查
uv run pytest              # 測試
uv run pytest --cov        # 覆蓋率
```

### 依賴管理檔案

- `pyproject.toml` - 主要依賴定義
- `uv.lock` - 鎖定版本 (自動生成，勿手動編輯)

---

## 🎯 Project Overview

PubMed Search MCP is a **professional literature research assistant** that provides:
- **35+ MCP Tools** for literature search and analysis
- **Multi-source search**: PubMed, Europe PMC (33M+), CORE (200M+)
- **NCBI databases**: Gene, PubChem, ClinVar
- **Full text access**: Direct XML/text retrieval

---

## 🔍 Search Strategy Selection

### Quick Search (Default)
**Trigger**: "find papers about...", "search for...", "any articles on..."
```python
search_literature(query="<topic>", limit=10)
```

### Systematic Search
**Trigger**: "comprehensive search", "systematic review", "find all papers"
```python
# Step 1: Get MeSH terms and synonyms
generate_search_queries(topic="<topic>")

# Step 2: Execute multiple strategies (parallel)
search_literature(query="<query1>")
search_literature(query="<query2>")
# ...

# Step 3: Merge results
merge_search_results(results_json='[[...],[...]]')
```

### PICO Clinical Question
**Trigger**: "Is A better than B?", "Does X reduce Y?", comparative questions
```python
# Step 1: Parse PICO
parse_pico(description="<clinical question>")

# Step 2: Get materials for each PICO element (parallel!)
generate_search_queries(topic="<P>")
generate_search_queries(topic="<I>")
generate_search_queries(topic="<C>")
generate_search_queries(topic="<O>")

# Step 3: Combine with Boolean logic
# (P) AND (I) AND (C) AND (O)
```

---

## 📚 Tool Categories

### Core Search Tools
| Tool | Purpose |
|------|---------|
| `search_literature` | PubMed search |
| `search_europe_pmc` | Europe PMC (with OA/fulltext filters) |
| `search_core` | CORE 200M+ open access papers |
| `search_core_fulltext` | Search within paper content |

### Discovery Tools
| Tool | Direction | Use Case |
|------|-----------|----------|
| `find_related_articles` | Similarity | Similar topic/method |
| `find_citing_articles` | Forward → | Follow-up research |
| `get_article_references` | ← Backward | Foundation papers |
| `build_citation_tree` | Both ↔ | Research landscape |

### Full Text Access
| Tool | Source | Format |
|------|--------|--------|
| `get_fulltext` | Europe PMC | Structured sections |
| `get_fulltext_xml` | Europe PMC | Raw JATS XML |
| `get_core_fulltext` | CORE | Plain text |

### NCBI Extended
| Tool | Database | Returns |
|------|----------|---------|
| `search_gene` | Gene | Gene info, aliases |
| `get_gene_literature` | Gene→PubMed | Curated PMIDs |
| `search_compound` | PubChem | Formula, SMILES |
| `get_compound_literature` | PubChem→PubMed | Curated PMIDs |
| `search_clinvar` | ClinVar | Clinical variants |

### Text Mining
| Tool | Purpose |
|------|---------|
| `get_text_mined_terms` | Extract genes, diseases, chemicals from papers |

---

## 📋 Common Workflows

### 1. Find Papers on a Topic
```python
search_literature(query="remimazolam ICU sedation", limit=10)
```

### 2. Explore from a Key Paper
```python
# Found an important paper (PMID: 12345678)
find_related_articles(pmid="12345678")   # Similar papers
find_citing_articles(pmid="12345678")    # Who cited this?
get_article_references(pmid="12345678")  # What did it cite?
```

### 3. Get Full Text
```python
# From Europe PMC (structured)
get_fulltext(pmcid="PMC7096777", sections="introduction,results")

# From CORE (plain text)
search_core(query="<topic>", has_fulltext=True)
get_core_fulltext(core_id="<id>")
```

### 4. Research a Gene
```python
search_gene(query="BRCA1", organism="human")
get_gene_details(gene_id="672")
get_gene_literature(gene_id="672", limit=20)
```

### 5. Research a Drug
```python
search_compound(query="propofol")
get_compound_details(cid="4943")
get_compound_literature(cid="4943", limit=20)
```

### 6. Export Results
```python
prepare_export(pmids="last", format="ris")  # Last search
analyze_fulltext_access(pmids="last")       # Check OA availability
```

---

## ⚠️ Important Notes

1. **Session Auto-management**: Search results are automatically cached. Use `pmids="last"` to reference previous searches.

2. **Parallel Execution**: When generating search strategies or PICO elements, call `generate_search_queries()` in parallel for efficiency.

3. **MeSH Expansion**: `generate_search_queries()` automatically expands terms using NCBI MeSH database. This finds papers using different terminology but same concepts.

4. **Rate Limits**: The server automatically handles NCBI API rate limits. No manual throttling needed.

5. **Full Text Priority**:
   - Europe PMC: Best for medical/biomedical, structured XML
   - CORE: Best for broader coverage, includes preprints

6. **Citation Metrics**: Use `get_citation_metrics()` with `sort_by="rcr"` to find high-impact papers (RCR = Relative Citation Ratio).

---

## 🔗 MCP Prompts Available

The server provides pre-defined prompts for common workflows:
- `quick_search` - Fast topic search
- `systematic_search` - Comprehensive MeSH-expanded search
- `pico_search` - Clinical question decomposition
- `explore_paper` - Deep exploration from a key paper
- `gene_drug_research` - Gene or drug focused research
- `export_results` - Export and full text access
- `find_open_access` - Find OA versions
- `literature_review` - Full review workflow
- `text_mining_workflow` - Extract entities from papers

Use `prompts/list` to see available prompts, `prompts/get` to retrieve guidance.
