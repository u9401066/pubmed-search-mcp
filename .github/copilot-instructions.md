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
uv run pytest              # 透過 uv 執行測試（自動多核）
uv run python script.py    # 透過 uv 執行 Python
```

### 程式碼品質工具（全部透過 uv run 執行）

```bash
uv run ruff check .        # Lint 檢查
uv run ruff check . --fix  # Lint 自動修復
uv run ruff format .       # 格式化
uv run mypy src/ tests/    # 型別檢查（含 src 和 tests）
uv run pytest              # ⩡ 多核平行測試（預設 -n auto --timeout=60）
uv run pytest --cov        # 多核 + 覆蓋率
```

> ⚠️ **永遠不要**直接呼叫 `pytest`、`ruff`、`mypy`，一律使用 `uv run` 前綴。

### 🔒 Pre-commit Hooks (自動品質守門)

本專案使用 [pre-commit](https://pre-commit.com/) 在每次 commit 時自動執行品質檢查。

```bash
# 首次設定（uv sync 安裝依賴後）
uv run pre-commit install                       # 安裝 pre-commit hook
uv run pre-commit install --hook-type pre-push  # 安裝 pre-push hook

# 手動執行所有 hooks
uv run pre-commit run --all-files

# 更新 hook 版本（建議每月一次）
uv run pre-commit autoupdate
```

**Commit 階段自動檢查：**
- trailing-whitespace / end-of-file-fixer (自動修復)
- check-yaml / check-toml / check-json / check-ast
- check-added-large-files / check-merge-conflict / debug-statements / detect-private-key
- check-byte-order-marker / fix-byte-order-marker (自動修復)
- check-builtin-literals / check-case-conflict / check-docstring-first
- check-executables-have-shebangs / check-shebang-scripts-are-executable
- check-symlinks / destroyed-symlinks / check-vcs-permalinks
- check-illegal-windows-names / mixed-line-ending (自動修復)
- no-commit-to-branch (保護 main/master)
- name-tests-test (強制 test_*.py 命名)
- **ruff** lint (自動修復) + **ruff-format** (自動修復)
- **bandit** 安全掃描 (medium+ severity, `pyproject.toml [tool.bandit]`)
- **vulture** 死碼掃描 (`vulture_whitelist.py` 管理白名單)
- **deptry** 依賴衛生 (`pyproject.toml [tool.deptry]`)
- **semgrep** SAST 靜態安全分析 — **已移至 pre-push** (記憶體 300-500MB)
- **mypy** type check — **已移至 pre-push** (記憶體 500MB-1GB)
- **async-test-checker** async/sync 測試一致性 (`scripts/check_async_tests.py`)
- **file-hygiene** 檔案衛生檢查 (`scripts/hooks/check_file_hygiene.py`)
- **commit-size-guard** 限制每次 commit ≤30 檔案 (`scripts/hooks/check_commit_size.py`)
- **tool-count-sync** MCP 工具文檔同步 (`scripts/hooks/check_tool_sync.py`, 自動修復)
- **skills-frontmatter** 驗證 `.claude/skills/*/SKILL.md` 的 YAML frontmatter (`scripts/hooks/check_skills_frontmatter.py`)
- **evolution-cycle** 一致性驗證 (`scripts/hooks/check_evolution_cycle.py`)
- **future-annotations** 強制 `from __future__ import annotations` (`scripts/hooks/check_future_annotations.py`, 自動修復)
- **no-print-in-src** 禁止 src/ 使用 print() (`scripts/hooks/check_no_print.py`)
- **ddd-layer-imports** DDD 層級依賴檢查 (`scripts/hooks/check_ddd_layers.py`)
- **no-type-ignore-bare** 禁止裸 `# type: ignore` (`scripts/hooks/check_type_ignore.py`)
- **docstring-tools** MCP 工具必須有文檔字串 (`scripts/hooks/check_docstring_tools.py`)
- **no-env-inner-layers** 禁止內層 DDD 使用 os.environ (`scripts/hooks/check_env_config.py`)
- **source-counts-guard** 確保每來源 API 回傳量顯示 (`scripts/hooks/check_source_counts.py`)
- **todo-scanner** TODO/FIXME 掃描器 (警告, 不阻擋) (`scripts/hooks/check_todo_scanner.py`)

**Push 階段自動檢查：**
- **mypy** type check (`uv run mypy src/`, 記憶體 500MB-1GB)
- **semgrep** SAST 靜態安全分析 (`p/python` ruleset, 記憶體 300-500MB)
- **pytest** 全套測試 (`-n auto --timeout=60`)

```bash
# 跳過特定 hook
SKIP=mypy git commit -m "quick fix"
# 跳過所有 hooks（慎用）
git commit --no-verify -m "emergency fix"
```

### 🔄 自演化循環 (Self-Evolution Cycle - IMPORTANT)

本專案的 Instruction、Skill、Hook 形成一個自我演化的閉迴系統：

```
Instruction (copilot-instructions.md)
    │ 定義規範、引導 AI 使用 Skills
    ▼
Skill (SKILL.md 檔案)
    │ 確保建構完整、創建新 Hook
    ▼
Hook (.pre-commit-config.yaml + scripts/hooks/)
    │ 自動執行檢查、自動修正
    ▼
evolution-cycle hook (check_evolution_cycle.py)
    │ 驗證三者一致性、報告不同步處
    ▼
Feedback → 更新 Instruction & Skill → 循環完成
```

**新增 Hook 的完整流程：**
1. 創建 hook 腳本 → `scripts/hooks/<name>.py`
2. 註冊到 `.pre-commit-config.yaml`
3. 更新 `copilot-instructions.md` (Commit 階段自動檢查列表)
4. 更新 `git-precommit SKILL.md` (架構圖 + Hook 設定檔案表)
5. 更新 `CONTRIBUTING.md` (hooks 表格)
6. 執行 `uv run python scripts/hooks/check_evolution_cycle.py` 驗證

> ⚠️ 如果只做了 1-2 而沒有 3-5，evolution-cycle hook 會在下次 commit 時報錯。

**套件版本自動演化：**
```bash
uv run pre-commit autoupdate    # 更新 ruff、pre-commit-hooks 等版本
uv run pre-commit run --all-files  # 驗證更新後所有 hook 正常
```

### ⏱️ 測試執行時間 (IMPORTANT - 請務必閱讀)

本專案**強制**使用 **pytest-xdist** 多核平行測試（透過 `addopts = "-n auto --timeout=60"` 全局強制）。

```bash
# ✅ 所有測試命令自動帶 -n auto --timeout=60（不需手動加）
uv run pytest                # 多核執行（~67 秒）
uv run pytest tests/ -q      # 多核 + 簡潔輸出

# ✅ 導向檔案避免 terminal buffer 溢出
uv run pytest tests/ -q --no-header 2>&1 > scripts/_tmp/test_result.txt
# 等待 ~70 秒後再讀取結果

# ✅ 多核 + 覆蓋率（pytest-cov 完全支援 xdist）
uv run pytest --cov -q

# ⚠️ 僅在需要 benchmark 時停用 xdist
uv run pytest tests/test_performance.py --benchmark-only -p no:xdist
```

| 指標 | 數值 |
|------|------|
| 測試檔案數 | 60+ |
| 測試案例數 | 2200+ |
| 測試程式碼行數 | 30,000+ |
| ⚡ 多核執行時間 (`-n auto`) | **~67 秒** |
| 每個測試超時 | 60 秒 (`--timeout=60`) |
| 建議 terminal timeout | **120,000+ ms** |

> 💡 **pytest-xdist** 使用多 process 平行化，每個 worker 為獨立 process，singleton 隔離無衝突。
> ⚠️ `pytest-benchmark` 在 xdist 模式下自動停用（benchmark 需要單核確保精確度）。

### 🔄 Async/Sync 測試一致性檢查 (MANDATORY)

本專案使用 `asyncio_mode = "auto"`，所有 async 方法的測試必須正確使用 `await` 和 `AsyncMock`。
**每次新增或修改測試時，必須執行** `scripts/check_async_tests.py` 確認無 async/sync 不一致。

```bash
# ✅ 必須在 commit 前執行
uv run python scripts/check_async_tests.py

# 詳細模式（查看每個問題的具體位置）
uv run python scripts/check_async_tests.py --verbose

# 自動修復 missing await（僅修復可安全自動修復的問題）
uv run python scripts/check_async_tests.py --fix
```

#### 常見反模式與修正

```python
# ❌ 錯誤：使用 Mock() mock async 方法
mock_searcher = Mock()
mock_searcher.search.return_value = []
result = await searcher.search(...)  # TypeError: can't await Mock

# ✅ 正確：使用 AsyncMock()
mock_searcher = AsyncMock()
mock_searcher.search.return_value = []
result = await searcher.search(...)  # 正常運作

# ❌ 錯誤：忘記 await async 方法
result = client.search(query="test")  # 返回 coroutine，非結果

# ✅ 正確：加上 await
result = await client.search(query="test")  # 返回實際結果

# ❌ 錯誤：sync def 測試呼叫 async 方法
def test_something():
    result = client.search(...)  # 永遠不會正確執行

# ✅ 正確：使用 async def
async def test_something():
    result = await client.search(...)
```

#### 檢查清單（每次寫測試時）

- [ ] async 方法的 mock 是否使用 `AsyncMock()`？
- [ ] 所有 async 方法呼叫是否加了 `await`？
- [ ] 測試函數是否為 `async def`？（當測試呼叫 async 方法時）
- [ ] `scripts/check_async_tests.py` 執行結果為 0 issues？

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
| 文檔 | `README.md`, `README.zh-TW.md`, `CHANGELOG.md`, `CONSTITUTION.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `CONTRIBUTING.md`, `DEPLOYMENT.md`, `CITATION.cff`, `LICENSE` |
| 入口 | `run_copilot.py`, `run_server.py`, `start.sh` |

> ⚠️ **任何不在白名單的檔案出現在根目錄都是錯誤。**

### 🚫 禁止重造輪子與過度設計 (No Reinventing the Wheel - MANDATORY)

AI Agent **必須持續檢查**是否存在以下反模式，並在每次新增或修改程式碼時主動排查：

#### 重造輪子 (Reinventing the Wheel)

```
# ❌ 禁止：自己實作已有標準庫/第三方可完成的功能
手寫 HTTP retry/backoff     → 用 tenacity 或 httpx 內建 retry
手寫 JSON schema 驗證       → 用 pydantic
手寫 rate limiter           → 用現有的 asyncio.Semaphore 或 aiolimiter
手寫 URL 解析/編碼          → 用 urllib.parse / yarl
手寫日期解析                → 用 dateutil.parser
手寫 CSV/XML 解析器         → 用 csv / lxml / xml.etree
自己包裝 logging 框架       → 直接用 logging 標準庫
手寫 LRU cache              → 用 functools.lru_cache / cachetools
```

#### 過度設計 (Over-Engineering)

```
# ❌ 禁止：
- 只有一個實作卻建立 Abstract Base Class + Interface + Factory
- 為了「未來擴展」加入目前未使用的參數/類別/層
- 包裝層只是直接轉發呼叫，沒有增加任何邏輯 (Thin Wrapper 無價值)
- 為只用一次的功能建立獨立模組
- 把 3 行能解決的問題寫成 30 行的 class hierarchy
- 給 cfg/env 變數寫複雜的 getter/setter，直接讀取即可

# ✅ 正確做法：
- YAGNI (You Ain't Gonna Need It) — 只實作當前需要的
- 優先使用函數，不需要狀態就不要用 class
- 先用最簡單的方案，有證據需要時才重構
- 第三方庫已解決的問題，直接 uv add 而非手寫
```

#### 檢查清單 (每次 code review 時)

- [ ] 這個功能有沒有現成的標準庫/第三方能做到？
- [ ] 這個 class 是否可以用簡單的函數取代？
- [ ] 這個抽象層是否真的有多個實作？還是只有一個？
- [ ] 這段程式碼有沒有「只是轉發」的 wrapper？
- [ ] 有沒有為「未來可能」而非「現在需要」而寫的程式碼？

---

## 🏗️ 專案架構 (DDD v0.2.0)

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
    └── async_utils.py      # 非同步工具 (CircuitBreaker, RateLimiter, etc.)
```

### Source Client 設計模式 (BaseAPIClient)

所有外部 API 客戶端（`infrastructure/sources/`）都繼承自 `BaseAPIClient`：

```python
# base_client.py 提供：
# - 自動 retry on 429 (Rate Limit) + Retry-After 支援
# - Rate limiting (configurable min_interval)
# - CircuitBreaker 錯誤容忍
# - 統一的 httpx.AsyncClient 管理

class MySourceClient(BaseAPIClient):
    _service_name = "MyAPI"

    def __init__(self):
        super().__init__(base_url="https://api.example.com", min_interval=0.1)

    # 覆寫 _handle_expected_status() 處理 404 等預期狀態碼
    # 覆寫 _parse_response() 自訂回應解析
    # 覆寫 _execute_request() 自訂請求邏輯 (e.g., POST)
```

**已整合的 8 個客戶端：** CrossRef, OpenAlex, Semantic Scholar, NCBI Extended, Europe PMC, CORE, Open-i, Unpaywall

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
unified_search(query="<topic>", limit=10)
```

When an agent needs a lightweight topic overview in the same response, prefer:
```python
unified_search(query="<topic>", options="context_graph")
```

### Systematic Search
**Trigger**: "comprehensive search", "systematic review", "find all papers"
```python
# Step 1: Get MeSH terms and synonyms
generate_search_queries(topic="<topic>")

# Step 2: Build a Boolean query from MeSH terms and synonyms
# Step 3: Validate the final query
analyze_search_query(query="<combined_boolean_query>")

# Step 4: Execute the search
unified_search(query="<combined_boolean_query>")
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

# Step 4: Validate and execute
analyze_search_query(query="<combined_boolean_query>")
unified_search(query="<combined_boolean_query>")
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
| `read_session` | Read session data through a single facade. |
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


### 研究時間軸
*研究演化追蹤與里程碑偵測*

| Tool | Purpose |
|------|---------|
| `build_research_timeline` | Build a research timeline for a topic OR specific PMIDs. |
| `analyze_timeline_milestones` | Analyze milestone distribution for a research topic. |
| `compare_timelines` | Compare research timelines of multiple topics. |


### 圖表擷取
*文章圖表與視覺資料擷取*

| Tool | Purpose |
|------|---------|
| `get_article_figures` | Get structured figure metadata (label, caption, image URL) and PDF links from a PMC Open Access arti |


### 圖片搜尋
*生物醫學圖片搜尋*

| Tool | Purpose |
|------|---------|
| `search_biomedical_images` | Search biomedical images across Open-i and Europe PMC. |


### Pipeline 管理
*Pipeline 持久化、載入、排程*

| Tool | Purpose |
|------|---------|
| `manage_pipeline` | Manage saved pipelines through a single facade. |
| `save_pipeline` | Save a pipeline configuration for later reuse. |
| `list_pipelines` | List all saved pipeline configurations. |
| `load_pipeline` | Load a pipeline configuration for review or editing. |
| `delete_pipeline` | Delete a saved pipeline configuration and its execution history. |
| `get_pipeline_history` | Get execution history for a saved pipeline. |
| `schedule_pipeline` | Schedule a saved pipeline for periodic execution. |

---

## 📋 Common Workflows

### 1. Find Papers on a Topic
```python
unified_search(query="remimazolam ICU sedation", limit=10)
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
# Structured full text from PMC / Europe PMC
get_fulltext(pmcid="PMC7096777", sections="introduction,results")

# DOI or PMID-based retrieval with broader source fallback
get_fulltext(doi="10.1038/s41586-021-03819-2", extended_sources=True)
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
get_fulltext(pmid="12345678", extended_sources=True)  # Retrieve selected paper full text
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

1. **Tool Progress**: `unified_search`, timeline tools, and Europe PMC fulltext/text-mining tools can emit MCP progress updates when the client provides a progress token.

2. **Session Resources**: Agents that support MCP resources can read `session://last-search`, `session://last-search/pmids`, and `session://last-search/results` instead of reconstructing recent search state from chat context.

3. **Parallel Execution**: When generating search strategies or PICO elements, call `generate_search_queries()` in parallel for efficiency.

4. **MeSH Expansion**: `generate_search_queries()` automatically expands terms using NCBI MeSH database. This finds papers using different terminology but same concepts.

5. **Rate Limits**: The server automatically handles NCBI API rate limits. No manual throttling needed.

6. **Full Text Priority**:
   - Europe PMC: Best for medical/biomedical, structured XML
   - CORE: Best for broader coverage, includes preprints

7. **Citation Metrics**: Use `get_citation_metrics()` with `sort_by="rcr"` to find high-impact papers (RCR = Relative Citation Ratio).

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
