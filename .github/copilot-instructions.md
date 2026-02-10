# GitHub Copilot Instructions for PubMed Search MCP

This document provides guidance for AI assistants working with the PubMed Search MCP server.

---

## ⚡ 開發環境規範 (CRITICAL)

### 套件管理：使用 UV (NOT pip)

本專案**必須**使用 [UV](https://github.com/astral-sh/uv) 管理所有 Python 依賴。
**所有命令（包括測試、lint、type check）一律透過 `uv run` 執行**，確保使用正確的虛擬環境與依賴版本。

> 💡 **UV 非常高效**：UV 使用 Rust 實作，比 pip 快 10-100 倍。即使是 `uv run pytest`，UV 也會在毫秒級確認環境一致後直接執行，幾乎零開銷。

```bash
# ❌ 禁止使用 (一律禁止直接呼叫，必須透過 uv run)
pip install <package>
python -m pytest
pytest
ruff check .
mypy src/

# ✅ 正確使用
uv add <package>           # 新增依賴
uv add --dev <package>     # 新增開發依賴
uv remove <package>        # 移除依賴
uv sync                    # 同步依賴
uv run pytest              # 透過 uv 執行測試
uv run python script.py    # 透過 uv 執行 Python
```

### 程式碼品質工具（全部透過 uv run 執行）

```bash
uv run ruff check .        # Lint 檢查
uv run ruff check . --fix  # Lint 自動修復
uv run ruff format .       # 格式化
uv run mypy src/ tests/    # 型別檢查（含 src 和 tests）
uv run pytest              # 測試
uv run pytest --cov        # 覆蓋率
uv run pytest --timeout=60 # 帶超時的測試
```

> ⚠️ **永遠不要**直接呼叫 `pytest`、`ruff`、`mypy`，一律使用 `uv run` 前綴。

### 依賴管理檔案

- `pyproject.toml` - 主要依賴定義
- `uv.lock` - 鎖定版本 (自動生成，勿手動編輯)

### 🧹 檔案衛生規範 (File Hygiene - MANDATORY)

AI Agent 在工作過程中**絕對禁止**在專案中留下臨時檔案。違反此規範等同程式碼品質問題。

#### 禁止事項

```
# ❌ 禁止：將測試結果導向檔案
uv run pytest > test_results.txt
uv run pytest 2>&1 | Out-File result.txt

# ❌ 禁止：在 scripts/ 放一次性修復腳本
scripts/auto_fix_something.py
scripts/fix_async_tests_v3.py

# ❌ 禁止：在根目錄放任何臨時產出物
failed_lines.txt, test_summary.txt, v3_result.txt
```

#### 正確做法

```bash
# ✅ 正確：直接在終端看測試結果
uv run pytest --timeout=60

# ✅ 正確：若真需要臨時檔案，放在 scripts/_tmp/ (已被 .gitignore 排除)
uv run pytest > scripts/_tmp/result.txt

# ✅ 正確：修復腳本執行完畢後立即刪除
Remove-Item scripts/_tmp/fix_script.py

# ✅ 正確：commit 前確認無臨時檔案
git status --short | Where-Object { $_ -match '^\?\?' }
```

#### 允許在根目錄的檔案（白名單）

| 類型 | 檔案 |
|------|------|
| 設定 | `pyproject.toml`, `Dockerfile`, `docker-compose*.yml`, `.gitignore`, `uv.lock` |
| 文檔 | `README.md`, `CHANGELOG.md`, `CONSTITUTION.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `CONTRIBUTING.md`, `DEPLOYMENT.md`, `LICENSE` |
| 入口 | `run_copilot.py`, `run_server.py`, `start.sh` |

> ⚠️ **任何不在白名單的檔案出現在根目錄都是錯誤。**

---

## �️ 專案架構 (DDD v0.2.0)

本專案採用 **Domain-Driven Design (DDD)** 分層架構：

```
src/pubmed_search/
├── domain/                 # 核心業務邏輯
│   └── entities/           # 實體 (UnifiedArticle, TimelineEvent)
├── application/            # 應用服務/用例
│   ├── search/             # QueryAnalyzer, ResultAggregator
│   ├── export/             # 引用匯出 (RIS, BibTeX...)
│   ├── session/            # SessionManager
│   └── timeline/           # TimelineBuilder, MilestoneDetector
├── infrastructure/         # 外部系統整合
│   ├── ncbi/               # Entrez, iCite, Citation Exporter
│   ├── sources/            # Europe PMC, CORE, CrossRef...
│   └── http/               # HTTP 客戶端
├── presentation/           # 使用者介面
│   ├── mcp_server/         # MCP 工具、提示、資源
│   └── api/                # REST API
└── shared/                 # 跨層共用
    ├── exceptions.py       # 例外處理
    └── async_utils.py      # 非同步工具
```

### 導入規則

```python
# ✅ 正確：從頂層 pubmed_search 導入
from pubmed_search import LiteratureSearcher, export_articles

# ✅ 正確：絕對導入
from pubmed_search.infrastructure.ncbi import LiteratureSearcher

# ❌ 避免：深層相對導入
from ...infrastructure.ncbi import LiteratureSearcher
```

---

## 🎯 Project Overview

PubMed Search MCP is a **professional literature research assistant** that provides:
- **40 MCP Tools** for literature search and analysis
- **Multi-source search**: PubMed, Europe PMC (33M+), CORE (200M+)
- **NCBI databases**: Gene, PubChem, ClinVar
- **Full text access**: Direct XML/text retrieval
- **Research Timeline**: Milestone detection, temporal evolution analysis
- **Official Citation Export**: NCBI Citation Exporter API (RIS, MEDLINE, CSL)

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

### 搜尋工具
*文獻搜索入口*

| Tool | Purpose |
|------|---------|
| `unified_search` | Unified Search - Single entry point for multi-source academic search. |


### 查詢智能
*MeSH 擴展、PICO 解析*

| Tool | Purpose |
|------|---------|
| `parse_pico` | Parse a clinical question into PICO elements OR accept pre-parsed PICO. |
| `generate_search_queries` | Gather search intelligence for a topic - returns RAW MATERIALS for Agent to decide. |
| `analyze_search_query` | Analyze a search query without executing the search. |


### 文章探索
*相關文章、引用網路*

| Tool | Purpose |
|------|---------|
| `fetch_article_details` | Fetch detailed information for one or more PubMed articles. |
| `find_related_articles` | Find articles related to a given PubMed article. |
| `find_citing_articles` | Find articles that cite a given PubMed article. |
| `get_article_references` | Get the references (bibliography) of a PubMed article. |
| `get_citation_metrics` | Get citation metrics from NIH iCite for articles. |


### 全文工具
*全文取得與文本挖掘*

| Tool | Purpose |
|------|---------|
| `get_fulltext` | Enhanced multi-source fulltext retrieval. |
| `get_text_mined_terms` | Get text-mined annotations from Europe PMC. |


### NCBI 延伸
*Gene, PubChem, ClinVar*

| Tool | Purpose |
|------|---------|
| `search_gene` | Search NCBI Gene database for gene information. |
| `get_gene_details` | Get detailed information about a gene by NCBI Gene ID. |
| `get_gene_literature` | Get PubMed articles linked to a gene. |
| `search_compound` | Search PubChem for chemical compounds. |
| `get_compound_details` | Get detailed information about a compound by PubChem CID. |
| `get_compound_literature` | Get PubMed articles linked to a compound. |
| `search_clinvar` | Search ClinVar for clinical variants. |


### 引用網絡
*引用樹建構與探索*

| Tool | Purpose |
|------|---------|
| `build_citation_tree` | Build a citation tree (network) from a single article. |


### 匯出工具
*引用格式匯出*

| Tool | Purpose |
|------|---------|
| `prepare_export` | Export citations to reference manager formats. |


### Session 管理
*PMID 暫存與歷史*

| Tool | Purpose |
|------|---------|
| `get_session_pmids` | 取得 session 中暫存的 PMID 列表。 |
| `get_cached_article` | 從 session 快取取得文章詳情。 |
| `get_session_summary` | 取得當前 session 的摘要資訊。 |


### 機構訂閱
*OpenURL Link Resolver*

| Tool | Purpose |
|------|---------|
| `configure_institutional_access` | Configure your institution's link resolver for full-text access. |
| `get_institutional_link` | Generate institutional access link (OpenURL) for an article. |
| `list_resolver_presets` | List available institutional link resolver presets. |
| `test_institutional_access` | Test your institutional link resolver configuration. |


### 視覺搜索
*圖片分析與搜索 (實驗性)*

| Tool | Purpose |
|------|---------|
| `analyze_figure_for_search` | Analyze a scientific figure or image for literature search. |


### ICD 轉換
*ICD-10 與 MeSH 轉換*

| Tool | Purpose |
|------|---------|
| `convert_icd_mesh` | Convert between ICD codes and MeSH terms (bidirectional). |
| `search_by_icd` | Search PubMed using ICD code (auto-converts to MeSH). |


### 研究時間軸
*研究演化追蹤與里程碑偵測*

| Tool | Purpose |
|------|---------|
| `build_research_timeline` | Build a research timeline for a topic OR specific PMIDs. |
| `analyze_timeline_milestones` | Analyze milestone distribution for a research topic. |
| `compare_timelines` | Compare research timelines of multiple topics. |


### 圖片搜尋
*生物醫學圖片搜尋*

| Tool | Purpose |
|------|---------|
| `search_biomedical_images` | Search biomedical images across Open-i and Europe PMC. |

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

## 📌 文檔自動同步規則 (IMPORTANT)

當 MCP 工具被 **新增、移除、或重新命名** 時，以下文件必須同步更新：

### 手動修改（AI Agent 負責）
1. `tool_registry.py` — 更新 `TOOL_CATEGORIES` dict
2. `tools/__init__.py` — import + 呼叫 `register_*_tools()`

### 自動同步（腳本負責）
```bash
uv run python scripts/count_mcp_tools.py --update-docs
```

此腳本自動更新以下 6 個文件：
- `instructions.py` — SERVER_INSTRUCTIONS 工具列表
- `.github/copilot-instructions.md` — Tool Categories 表格
- `.claude/skills/pubmed-mcp-tools-reference/SKILL.md` — 完整工具參考
- `TOOLS_INDEX.md` — 工具索引
- `README.md` / `README.zh-TW.md` — 工具數量

> ⚠️ **必須在 git commit 前執行**。詳見 `.claude/skills/tool-sync/SKILL.md`。

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
