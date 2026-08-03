# 與 openags/paper-search-mcp 的比較與借鏡清單

> 撰寫時間：2026-05  
> 對象：[openags/paper-search-mcp](https://github.com/openags/paper-search-mcp)（commit `d499d01`）  
> 本文件目的：明確區分兩個專案的定位、避免重造、列出值得本專案吸收的點。

---

## 1. 一句話定位

| 專案 | 定位 |
|------|------|
| **paper-search-mcp** (openags) | **跨學科廣度型 paper aggregator**：把 20+ 來源（arXiv / bioRxiv / medRxiv / HAL / Zenodo / DOAJ / BASE / OpenAIRE / IEEE / ACM / Sci-Hub …）包成統一 `search_papers` + per-source `search_X / download_X / read_X` 三件套。核心命題：**多源並發搜尋 + OA PDF fallback 下載**。 |
| **pubmed-search-mcp** (本專案) | **生物醫學深度型研究助理**：PICO 解析、MeSH 擴展、引用網絡、研究時間軸、基因/藥物/變異、引用驗證、Pipeline 持久化、機構訂閱直連、本地 wiki 筆記。核心命題：**做臨床/生醫研究的整套工作流**。 |

兩者重疊只在最表層的「也搜得到論文」這一層。

---

## 2. 來源覆蓋對比

### 2.1 paper-search-mcp 的來源（依 `academic_platforms/`）

```
arxiv, pubmed, biorxiv, medrxiv, google_scholar, iacr,
semantic_scholar, crossref, openalex, pmc, core, europe_pmc,
dblp, openaire, citeseerx, doaj, base, zenodo, hal, ssrn,
unpaywall, scihub (optional), ieee (key required), acm (key required)
```

### 2.2 本專案的來源

```
pubmed, europe_pmc, openalex, semantic_scholar, crossref, core,
+ NCBI Gene / PubChem / ClinVar（非文獻資料庫）
+ Open-i / Europe PMC images（圖片）
+ NIH iCite（引用指標）
+ NCBI Citation Exporter（官方引用格式）
+ Unpaywall（DOI OA 解析）
+ Institutional direct fetch / EZproxy / OpenURL（機構訂閱）
```

### 2.3 差距總結

| 我們**沒有**他們有 | 評估 |
|---|---|
| arXiv, bioRxiv, medRxiv | ⚠️ unified_search 支援 `options="preprints"` 但目前是用 Europe PMC 代為查詢預印本，沒有直接 arXiv/bioRxiv connector |
| HAL, Zenodo, OpenAIRE, DOAJ, BASE | 🟡 補洞點：repository 型 OA 來源能擴大 `get_fulltext` 的命中率 |
| dblp, CiteSeerX | ❌ CS 領域為主，與本專案定位無關 |
| IACR, SSRN | ❌ 領域無關 |
| Google Scholar | ❌ 反爬太重、合法性曖昧、Bot detection 一直壞 |
| IEEE, ACM | ❌ 都是 skeleton，沒有實際功能 |
| Sci-Hub | ❌ 法律風險，本專案明確不做 |

| 他們**沒有**我們有 | 評估 |
|---|---|
| PICO 解析、MeSH 同義詞擴展 | ✅ 護城河 |
| ICD ↔ MeSH 轉換 | ✅ 護城河 |
| 引用網絡（citation tree, citing, references）| ✅ 護城河 |
| 研究時間軸 + 里程碑偵測 | ✅ 護城河 |
| NCBI Gene / PubChem / ClinVar | ✅ 護城河 |
| PubTator text mining | ✅ 護城河 |
| 引用驗證（verify_reference_list）| ✅ 護城河 |
| Pipeline 持久化 + 排程 | ✅ 護城河 |
| Session 自動暫存（`pmids="last"`）| ✅ 護城河 |
| wiki / Foam / MedPaper 本地筆記 | ✅ 護城河 |
| 機構訂閱 direct / EZproxy / OpenURL | ✅ 護城河（剛整合進 get_fulltext）|
| 圖片搜尋 + 圖表擷取 | ✅ 護城河 |
| NIH iCite RCR 指標 | ✅ 護城河 |
| Citation Exporter（RIS/MEDLINE/CSL）| ✅ 護城河 |
| MCP Prompts + Resources（session://...）| ✅ 護城河 |
| DDD 分層架構、pre-commit 自演化框架、2200+ tests | ✅ 工程護城河 |

---

## 3. 架構對比

### 3.1 paper-search-mcp

```
paper_search_mcp/
├── server.py              # ~50KB 單檔，所有 MCP 工具註冊在此
├── cli.py                 # ~10KB CLI（給 Claude Code skill 用）
├── config.py              # env 設定
├── paper.py               # Paper dataclass（統一格式）
├── utils.py
└── academic_platforms/    # 平的 connectors
    ├── arxiv.py, pubmed.py, biorxiv.py, ...
    └── (each: search, download, read 三方法)
```

- 風格：**平面化**、無分層、connector 各自獨立。
- 優點：容易新增來源、心智負擔低。
- 缺點：跨來源邏輯（去重、合併、policy）只能塞進 server.py。

### 3.2 本專案

```
src/pubmed_search/
├── domain/                # UnifiedArticle, TimelineEvent
├── application/           # QueryAnalyzer, FulltextService, TimelineBuilder, SessionManager
├── infrastructure/        # NCBI, sources/, http/
├── presentation/          # mcp_server tools/prompts/resources
└── shared/                # exceptions, async_utils (CircuitBreaker, RateLimiter)
```

- 風格：**DDD 四層**。
- 優點：跨來源策略（policy、registry、aggregator）有專屬層級；新功能不污染 MCP 工具層。
- 缺點：架構成本高、新人 onboarding 慢。

> **不需要改方向**。我們的功能複雜度（PICO + timeline + pipeline + session）必須要這個架構。

---

## 4. 值得借鏡的具體點（按優先順序）

### 🟢 高優先 — 補洞、低風險、用戶有感

#### A. 擴充 `get_fulltext` 的 OA 來源 fallback chain

他們的 `download_with_fallback` 鏈：
```
source-native download → OpenAIRE → CORE → Europe PMC → PMC → Unpaywall → (optional Sci-Hub)
```

我們目前 `FulltextRegistry` 的 `expanded_discovery` policy：
```
europe_pmc → unpaywall → institutional → core → openalex_oa_locations
```

**可加入：**
- [ ] **OpenAIRE**（`https://api.openaire.eu/search/publications`）：歐洲 OA repository 聚合，跟 CORE 互補。
- [ ] **HAL**（`https://api.archives-ouvertes.fr/search/`）：法國 CNRS repository，生醫論文也不少（特別是法國團隊）。
- [ ] **Zenodo**（`https://zenodo.org/api/records`）：CERN 維運，常被當作 supplementary data + preprint OA 鏡像。
- [ ] **DOAJ**（`https://doaj.org/api/v2/search/articles`）：純 OA 期刊清單，是「確定 OA」的權威來源。

**做法**：在 `infrastructure/sources/` 新增 4 個 client，加入 `extended_sources` policy，不需要新 MCP 工具。

預期效益：`get_fulltext` 命中率 +10~20%（粗估），特別是 Europe PMC 找不到的歐洲 / 法國 / 跨領域論文。

#### B. arXiv / bioRxiv / medRxiv 直接 connector

我們目前 `options="preprints"` 是 routed 到 Europe PMC 的預印本欄位，但：
- arXiv 上的物理/CS/數學/統計類論文 Europe PMC 不一定有
- bioRxiv / medRxiv 在 Europe PMC 索引有時間 lag

**做法**：`infrastructure/sources/arxiv.py`, `biorxiv.py`，在 `unified_search` 的 `sources` 列舉中加入。

預期效益：preprint 搜尋的覆蓋率與即時性。

### 🟡 中優先 — 體驗、分發

#### C. Smithery + Claude Code Skill 分發

他們提供了 7 種安裝方式（Smithery, uvx, uv, pip, npx, Docker, source），還註冊到 [smithery.ai](https://smithery.ai/server/@openags/paper-search-mcp)。

我們目前只有 uv + Docker。

**做法**：
- [ ] 註冊 Smithery
- [ ] 寫 `claude-code/SKILL.md`（給 Claude Code 用，不是給我們的 `.claude/skills/` 內部用）
- [ ] PyPI 發佈（讓 `uvx pubmed-search-mcp` 可用）

#### D. CLI 包裝

他們的 `cli.py` 讓 MCP server 也能當 command-line tool 用（給 Claude Code skill 包裝）。我們有 `run_server.py` 但沒有 CLI subcommands。

**做法**：用 `click` 或 `typer` 包裝 `pubmed-search query "..."`, `pubmed-search export pmids.txt --format ris` 之類的子命令。

優先度低，因為 MCP client 已經夠用。

### 🔵 低優先 — 思路、不需立刻做

#### E. Platform Capability Matrix

他們的 README 有一個 `Platform | Search | Download | Read | Notes` 表格，明確標示每個來源的能力 / 已知問題 / 解法。

我們的 `unified_search` doc 沒有這種「每個 source 的能力光譜」說明。

**做法**：在 `docs/SOURCE_CONTRACTS.md`（已存在）加入類似 matrix。

#### F. 一致 Paper schema 對外輸出

他們的 `paper.py` 強制所有 connector 都回傳同樣的 `Paper` dataclass。我們有 `UnifiedArticle` 但內部欄位較複雜。

**做法**：為 MCP 工具回傳格式 freeze 一個更精簡的 `ArticleSummary` schema，方便下游 LLM 處理。

優先度低，因為我們 session resource (`session://last-search/results`) 已經是 stable schema。

### ❌ 不該學的

| 反例 | 原因 |
|---|---|
| 把所有 MCP 工具塞進單一 `server.py`（50KB） | DDD 反模式 |
| 平面 `academic_platforms/` connectors（無 base class，每個檔案各自 retry / rate limit / parse） | 我們已用 `BaseAPIClient` 統一，更乾淨 |
| Sci-Hub integration | 法律 / 政策風險 |
| IEEE / ACM skeleton（沒實作的 placeholder） | 違反 YAGNI |
| Google Scholar scraping | Bot detection 永遠在跑回歸測試 |

---

## 5. 行動清單（提案，不主動執行）

按優先度排序：

1. **[FULLTEXT] 加入 OpenAIRE / HAL / Zenodo / DOAJ 到 `extended_sources` policy**  
   - 影響：`get_fulltext` 命中率
   - 工作量：4 個 BaseAPIClient 子類，每個 ~150 行
   - 風險：低（純加，policy 控制）

2. **[SOURCES] 加入 arXiv / bioRxiv / medRxiv 直接 connector**  
   - 影響：`unified_search(options="preprints")` 的覆蓋率
   - 工作量：3 個 client + `unified_search` 路由更新
   - 風險：低

3. **[DISTRIBUTION] PyPI 發佈 + Smithery 註冊**  
   - 影響：採用門檻
   - 工作量：pyproject 修一下、Smithery 註冊表單
   - 風險：低，但要先決定發佈節奏

4. **[DOCS] 把 Platform Capability Matrix 加入 `SOURCE_CONTRACTS.md`**  
   - 影響：使用者透明度
   - 工作量：純文件
   - 風險：零

5. **[CLI] subcommand 包裝（給未來 Claude Code skill 整合）**  
   - 影響：分發
   - 工作量：中
   - 風險：低，但 MCP 已夠用，可緩

---

## 6. 結論

**不是輪子之爭，是定位不同：**

- 對方做的是 **「論文搜尋與下載」工具箱**，廣度勝。
- 我們做的是 **「生醫研究工作流」助理**，深度勝。

兩者**沒有實質競爭關係**。他們的存在反而幫我們驗證了「multi-source paper search」的市場需求是真的。

值得吸收的只有：**更多 OA repository 來源**、**preprint 直接 connector**、**Smithery 分發**。其他都是我們的護城河，不必動搖。
