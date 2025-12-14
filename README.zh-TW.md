# PubMed Search MCP

[![PyPI version](https://badge.fury.io/py/pubmed-search-mcp.svg)](https://badge.fury.io/py/pubmed-search-mcp)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)
[![Smithery](https://smithery.ai/badge/pubmed-search-mcp)](https://smithery.ai/server/pubmed-search-mcp)

> **AI Agent 的專業文獻研究助理** - 不只是 API 包裝器

基於 Domain-Driven Design (DDD) 架構的 MCP 伺服器，作為 AI Agent 的智慧研究助理，提供任務導向的文獻搜尋與分析能力。

**🌐 語言**: [English](README.md) | **繁體中文**

---

## 🚀 快速安裝

### 透過 Smithery（推薦給 Claude Desktop 用戶）

```bash
npx -y @smithery/cli install pubmed-search-mcp --client claude
```

### 透過 pip

```bash
pip install pubmed-search-mcp
```

### 透過 uv

```bash
uv add pubmed-search-mcp
```

### 透過 uvx（免安裝）

```bash
uvx pubmed-search-mcp
```

---

## ⚙️ 設定方式

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "pubmed-search": {
      "command": "uvx",
      "args": ["pubmed-search-mcp"],
      "env": {
        "NCBI_EMAIL": "your@email.com"
      }
    }
  }
}
```

### VS Code / Cursor (`.vscode/mcp.json`)

```json
{
  "servers": {
    "pubmed-search": {
      "type": "stdio",
      "command": "uvx",
      "args": ["pubmed-search-mcp"],
      "env": {
        "NCBI_EMAIL": "your@email.com"
      }
    }
  }
}
```

> **注意**: `NCBI_EMAIL` 是 NCBI API 政策要求的必填項。可選擇性設定 `NCBI_API_KEY` 以獲得更高的 API 限額。

---

## 🎯 設計理念

- **Agent-First** - 為 AI Agent 設計，輸出優化為機器決策
- **任務導向** - Tool 以研究任務為單位，而非底層 API
- **DDD 架構** - 以文獻研究領域知識為核心建模
- **上下文感知** - 透過 Session 維持研究狀態

**定位**：PubMed 專精的 AI 研究助理
- ✅ MeSH 專業詞彙整合 ← 其他來源沒有
- ✅ PICO 結構化查詢 ← 醫學專業
- ✅ ESpell 拼字校正 ← 自動糾錯
- ✅ 批次並行搜尋 ← 高效率

---

## 🛠️ MCP 工具（14 個）

### 探索型工具 (Discovery)

| 工具 | 說明 | 方向 |
|------|------|------|
| `search_literature` | 搜尋 PubMed 文獻 | - |
| `find_related_articles` | 尋找主題相似文章（PubMed 演算法）| 相似性 |
| `find_citing_articles` | 尋找引用此文的論文（後續研究）| Forward ➡️ |
| `get_article_references` | 取得此文的參考文獻（研究基礎）| Backward ⬅️ |
| `fetch_article_details` | 取得文章完整資訊 | - |
| `get_citation_metrics` | 取得引用指標（iCite RCR/Percentile）| - |
| `build_citation_tree` | 建構引用網絡樹（6 種格式）| Both ↔️ |
| `suggest_citation_tree` | 評估是否值得建構引用樹 | - |

### 批次搜尋工具 (Parallel Search)

| 工具 | 說明 |
|------|------|
| `parse_pico` | 解析 PICO 臨床問題（搜尋入口）|
| `generate_search_queries` | 產生多個搜尋策略（ESpell + MeSH）|
| `merge_search_results` | 合併去重搜尋結果 |
| `expand_search_queries` | 擴展搜尋策略 |

### 匯出工具 (Export)

| 工具 | 說明 |
|------|------|
| `prepare_export` | 匯出引用格式（RIS/BibTeX/CSV/MEDLINE/JSON）|
| `get_article_fulltext_links` | 取得全文連結（PMC/DOI）|
| `analyze_fulltext_access` | 分析開放取用可用性 |

> **設計原則**: 專注搜尋。Session/Cache/Reading List 皆為**內部機制**，自動運作，Agent 無需管理。

---

## 📋 Agent 使用流程

### 快速搜尋

```python
search_literature(query="remimazolam ICU sedation", limit=10)
```

### 使用 PubMed 官方語法

```python
# MeSH 標準詞彙
search_literature(query='"Diabetes Mellitus"[MeSH]')

# 欄位限定
search_literature(query='(BRAF[Gene Name]) AND (melanoma[Title/Abstract])')

# 日期範圍
search_literature(query='COVID-19[Title] AND 2024[dp]')

# 文章類型
search_literature(query='propofol sedation AND Review[pt]')

# 組合搜尋
search_literature(query='("Intensive Care Units"[MeSH]) AND (remimazolam[tiab] OR "CNS 7056"[tiab])')
```

### PubMed 官方欄位標籤

| 標籤 | 說明 | 範例 |
|------|------|------|
| `[Title]` 或 `[ti]` | 標題 | `COVID-19[ti]` |
| `[Title/Abstract]` 或 `[tiab]` | 標題+摘要 | `sedation[tiab]` |
| `[MeSH]` 或 `[mh]` | MeSH 標準詞彙 | `"Diabetes Mellitus"[MeSH]` |
| `[MeSH Major Topic]` 或 `[majr]` | MeSH 主要主題 | `"Anesthesia"[majr]` |
| `[Author]` 或 `[au]` | 作者 | `Smith J[au]` |
| `[Journal]` 或 `[ta]` | 期刊縮寫 | `Nature[ta]` |
| `[Publication Type]` 或 `[pt]` | 文章類型 | `Review[pt]`, `Clinical Trial[pt]` |
| `[Date - Publication]` 或 `[dp]` | 出版日期 | `2024[dp]`, `2020:2024[dp]` |

> **完整語法參考**: [PubMed Search Field Tags](https://pubmed.ncbi.nlm.nih.gov/help/#search-tags)

### 深入探索（找到重要論文後）

```python
find_related_articles(pmid="12345678")   # 相關文章（PubMed 演算法）
find_citing_articles(pmid="12345678")    # 引用這篇的後續研究（forward in time）
get_article_references(pmid="12345678")  # 這篇的參考文獻（backward in time）
```

---

## 🔬 引用探索指南

找到重要論文後，有 **5 種工具** 可以探索相關文獻：

### 工具對比表

| 工具 | 方向 | 資料來源 | 用途 | API 呼叫量 |
|------|------|----------|------|------------|
| `find_related_articles` | 相似性 | PubMed algorithm | 找主題/方法相似的文章 | 1 次 |
| `find_citing_articles` | Forward ➡️ | PMC citations | 找引用此文的後續研究 | 1 次 |
| `get_article_references` | Backward ⬅️ | PMC references | 找此文引用的參考文獻 | 1 次 |
| `build_citation_tree` | Both ↔️ | PMC (BFS 遍歷) | 建構完整引用網絡圖 | 多次 |
| `suggest_citation_tree` | - | 文章資訊 | 評估是否值得建樹 | 1 次 |

### 使用場景決策樹

```
找到一篇重要論文 (PMID: 12345678)
    │
    ├── 想找「類似主題」的文章？
    │   └── ✅ find_related_articles(pmid="12345678")
    │
    ├── 想知道「後續研究怎麼發展」？
    │   └── ✅ find_citing_articles(pmid="12345678")
    │
    ├── 想了解「這篇文章的基礎是什麼」？
    │   └── ✅ get_article_references(pmid="12345678")
    │
    └── 想建立「完整的研究脈絡網絡」？
        ├── 先評估: suggest_citation_tree(pmid="12345678")
        └── 建構網絡: build_citation_tree(pmid="12345678", depth=2)
```

### Citation Tree 輸出格式

| 格式 | 用途 | 工具 |
|------|------|------|
| `mermaid` | VS Code Markdown 預覽 | 內建 Mermaid 擴充 |
| `cytoscape` | 學術標準、生物資訊 | Cytoscape.js |
| `g6` | 現代網頁視覺化 | AntV G6 |
| `d3` | 靈活客製化 | D3.js force layout |
| `vis` | 快速原型 | vis-network |
| `graphml` | 桌面分析軟體 | Gephi, VOSviewer, yEd |

---

## 🔍 深度搜尋：兩種入口模式

### 入口 1️⃣：關鍵字導向

**適用場景**: 已知要搜尋的關鍵字或主題

```python
# Step 1: 取得搜尋素材（ESpell + MeSH + 同義詞）
generate_search_queries(topic="remimazolam ICU sedation")

# Step 2: 並行執行搜尋
search_literature(query="(remimazolam icu sedation)[Title]")
search_literature(query="(remimazolam icu sedation)[Title/Abstract]")
# ...（並行）

# Step 3: 合併結果
merge_search_results(results_json='[["pmid1","pmid2"],["pmid2","pmid3"]]')
```

### 入口 2️⃣：PICO 臨床問題

**適用場景**: 有臨床問題需要拆解成結構化搜尋

```python
# Step 1: 解析 PICO 結構
parse_pico(description="remimazolam 在 ICU 鎮靜比 propofol 好嗎？")
# → P=ICU patients, I=remimazolam, C=propofol, O=sedation outcome

# Step 2: 對每個 PICO 元素取得搜尋素材（並行）
generate_search_queries(topic="ICU patients")   # P
generate_search_queries(topic="remimazolam")    # I
generate_search_queries(topic="propofol")       # C

# Step 3: Agent 用 Boolean 邏輯組合查詢
query = '("Intensive Care Units"[MeSH]) AND (remimazolam[tiab]) AND (propofol[tiab])'

# Step 4: 搜尋 + 合併
search_literature(query=query)
merge_search_results(...)
```

### 兩種入口對比

| 特性 | 關鍵字導向 | PICO 臨床問題 |
|------|-----------|---------------|
| **入口工具** | `generate_search_queries(topic)` | `parse_pico(description)` |
| **適用場景** | 知道要搜什麼詞 | 有臨床問題需要拆解 |
| **MeSH 擴展** | 1 次呼叫 | 4 次呼叫（P/I/C/O 各一次）|
| **查詢組合** | 使用 suggested_queries | Agent 用 Boolean 組合 |

> **設計哲學**: 工具提供素材（MeSH terms, synonyms），Agent 做決策（如何組合查詢）

---

## 🏗️ 架構（DDD）

```
src/pubmed_search/
├── mcp/
│   └── tools/
│       ├── discovery.py    # 探索型（search, related, citing）
│       ├── strategy.py     # 策略型（generate_queries, expand）
│       ├── pico.py         # PICO 解析
│       ├── merge.py        # 結果合併
│       ├── export.py       # 匯出工具
│       └── citation_tree.py # 引用網絡視覺化
├── entrez/                 # NCBI Entrez API 封裝
├── exports/                # 匯出格式（RIS, BibTeX, CSV）
└── session.py              # Session 管理（內部機制）
```

### 內部機制（對 Agent 透明）

| 機制 | 說明 |
|------|------|
| **Session** | 自動建立、自動切換 |
| **Cache** | 搜尋結果自動快取，避免重複 API |
| **Rate Limit** | 自動遵守 NCBI API 限制 |
| **MeSH Lookup** | 自動查詢 NCBI MeSH 資料庫 |
| **ESpell** | 自動拼字校正 |

> 📖 **完整架構說明**：[ARCHITECTURE.md](ARCHITECTURE.md)

---

## 📤 匯出格式

| 格式 | 相容軟體 | 用途 |
|------|----------|------|
| **RIS** | EndNote, Zotero, Mendeley | 通用匯入 |
| **BibTeX** | LaTeX, Overleaf, JabRef | 學術寫作 |
| **CSV** | Excel, Google Sheets | 資料分析 |
| **MEDLINE** | PubMed 原生格式 | 存檔 |
| **JSON** | 程式存取 | 自訂處理 |

### 匯出欄位
- **核心**: PMID, 標題, 作者, 期刊, 年份, 卷期頁碼
- **識別碼**: DOI, PMC ID, ISSN
- **內容**: 摘要（HTML 標籤已清除）
- **詮釋資料**: 語言, 文章類型, 關鍵詞
- **存取**: DOI URL, PMC URL, 全文可用性

---

## 🔒 HTTPS 部署

為生產環境啟用 HTTPS 安全通訊：

```bash
# Step 1: 生成 SSL 憑證
./scripts/generate-ssl-certs.sh

# Step 2: 啟動 HTTPS 服務
./scripts/start-https-docker.sh up

# 驗證部署
curl -k https://localhost/
```

### HTTPS 端點

| 服務 | URL | 說明 |
|------|-----|------|
| MCP SSE | `https://localhost/sse` | SSE 連線（MCP）|
| Messages | `https://localhost/messages` | MCP POST |
| Health | `https://localhost/health` | 健康檢查 |

> 📖 **部署指南**: [DEPLOYMENT.md](DEPLOYMENT.md)

---

## 🔐 安全性

| 層級 | 功能 | 說明 |
|------|------|------|
| **HTTPS** | TLS 1.2/1.3 加密 | 所有流量透過 Nginx 加密 |
| **Rate Limiting** | 30 req/s | Nginx 層級保護 |
| **Security Headers** | XSS/CSRF 防護 | X-Frame-Options 等 |
| **No Database** | 無狀態 | 無 SQL 注入風險 |
| **No Secrets** | 僅記憶體 | 不儲存憑證 |

---

## 📦 安裝方式

### 基本安裝（僅函式庫）

```bash
pip install pubmed-search
```

### 含 MCP 伺服器支援

```bash
pip install "pubmed-search[mcp]"
```

### 從原始碼安裝

```bash
git clone https://github.com/u9401066/pubmed-search-mcp.git
cd pubmed-search-mcp
pip install -e ".[all]"
```

### 作為 Git Submodule

```bash
# 加入專案作為 submodule
git submodule add https://github.com/u9401066/pubmed-search-mcp.git src/pubmed_search

# 安裝相依套件
pip install biopython requests mcp
```

---

## 📚 Python 函式庫用法

```python
from pubmed_search import PubMedClient

client = PubMedClient(email="your@email.com")

# 搜尋論文
results = client.search("anesthesia complications", limit=10)
for paper in results:
    print(f"{paper.pmid}: {paper.title}")

# 取得相關文章
related = client.find_related("12345678", limit=5)

# 取得引用文章
citing = client.find_citing("12345678")
```

---

## 🔗 相關連結

- [GitHub Repository](https://github.com/u9401066/pubmed-search-mcp)
- [PyPI Package](https://pypi.org/project/pubmed-search/)
- [NCBI Entrez Programming Utilities](https://www.ncbi.nlm.nih.gov/books/NBK25497/)

---

## 📄 授權

Apache License 2.0 - 詳見 [LICENSE](LICENSE)

## 🤝 貢獻

1. Fork 此專案
2. 建立功能分支
3. 進行修改
4. 執行測試: `pytest`
5. 提交 Pull Request
