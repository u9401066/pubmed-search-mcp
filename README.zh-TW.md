# PubMed Search MCP

[![PyPI version](https://badge.fury.io/py/pubmed-search-mcp.svg)](https://badge.fury.io/py/pubmed-search-mcp)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)
[![Test Coverage](https://img.shields.io/badge/coverage-84%25-green.svg)](https://github.com/u9401066/pubmed-search-mcp)

> **AI Agent 的專業文獻研究助理** - 不只是 API 包裝器

基於 Domain-Driven Design (DDD) 架構的 MCP 伺服器，作為 AI Agent 的智慧研究助理，提供任務導向的文獻搜尋與分析能力。

**✨ 包含內容：**
- 🔧 **40 個 MCP 工具** - 精簡的 PubMed、Europe PMC、CORE、NCBI 資料庫存取，及**研究時間軸 / 脈絡圖**功能
- 📚 **24 個 Claude Skills** - AI Agent 可直接使用的工作流程指南（Claude Code 專屬）
- 📖 **Copilot 整合指南** - VS Code GitHub Copilot 使用說明

**🌐 語言**: [English](README.md) | **繁體中文**

---

## 🚀 快速安裝

### 前置需求

- **Python 3.10+** — [下載](https://www.python.org/downloads/)
- **uv**（推薦）— [安裝 uv](https://docs.astral.sh/uv/getting-started/installation/)
  ```bash
  # macOS / Linux
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # Windows
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
- **NCBI Email** — [NCBI API 政策](https://www.ncbi.nlm.nih.gov/books/NBK25497/#chapter2.Usage_Guidelines_and_Requiremen)要求，任何有效的電子郵件地址
- **NCBI API Key**（*選填*）— [在此取得](https://www.ncbi.nlm.nih.gov/account/settings/)，可提高 API 限額（10 req/s vs 3 req/s）

### 安裝與執行

```bash
# 方式 1：使用 uvx 免安裝（推薦新手嘗試用）
uvx pubmed-search-mcp

# 方式 2：加入專案依賴
uv add pubmed-search-mcp

# 方式 3：pip 安裝
pip install pubmed-search-mcp
```

---

## ⚙️ 設定方式

本 MCP 伺服器可與**任何 MCP 相容的 AI 工具**配合使用。選擇您偏好的客戶端：

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

> **設定檔位置**：
> - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
> - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
> - Linux: `~/.config/Claude/claude_desktop_config.json`

### Claude Code

```bash
claude mcp add pubmed-search -- uvx pubmed-search-mcp
```

或在專案根目錄的 `.mcp.json` 中新增：

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

### Zed AI (`settings.json`)

Zed 編輯器（[z.ai](https://zed.dev)）原生支援 MCP 伺服器。在 Zed 的 `settings.json` 中新增：

```json
{
  "context_servers": {
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

> **提示**：開啟命令面板 → `zed: open settings` 編輯，或前往 Agent Panel → Settings →「Add Custom Server」。

### OpenClaw 🦞 (`~/.openclaw/openclaw.json`)

[OpenClaw](https://docs.openclaw.ai/) 透過 [mcp-adapter 插件](https://github.com/androidStern-personal/openclaw-mcp-adapter)支援 MCP 伺服器。先安裝 adapter：

```bash
openclaw plugins install mcp-adapter
```

然後新增到 `~/.openclaw/openclaw.json`：

```json
{
  "plugins": {
    "entries": {
      "mcp-adapter": {
        "enabled": true,
        "config": {
          "servers": [
            {
              "name": "pubmed-search",
              "transport": "stdio",
              "command": "uvx",
              "args": ["pubmed-search-mcp"],
              "env": {
                "NCBI_EMAIL": "your@email.com"
              }
            }
          ]
        }
      }
    }
  }
}
```

設定後重啟 gateway：

```bash
openclaw gateway restart
openclaw plugins list  # 應顯示: mcp-adapter | loaded
```

### Cline (`cline_mcp_settings.json`)

```json
{
  "mcpServers": {
    "pubmed-search": {
      "command": "uvx",
      "args": ["pubmed-search-mcp"],
      "env": {
        "NCBI_EMAIL": "your@email.com"
      },
      "alwaysAllow": [],
      "disabled": false
    }
  }
}
```

### 其他 MCP 客戶端

任何 MCP 相容客戶端都可以透過 stdio transport 使用此伺服器：

```bash
# 指令
uvx pubmed-search-mcp

# 搭配環境變數
NCBI_EMAIL=your@email.com uvx pubmed-search-mcp
```

> **注意**: `NCBI_EMAIL` 是 NCBI API 政策要求的必填項。可選擇性設定 `NCBI_API_KEY` 以獲得更高的 API 限額（10 req/s vs 3 req/s）。

> 📖 **完整整合指南**：詳見 [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md)，包含所有環境變數、Copilot Studio 設定、Docker 部署、代理設定與疑難排解。

---

## 🎯 設計理念

> **核心定位**：AI Agent 與學術搜尋引擎之間的**智慧中介層**。

### 為什麼選擇這個伺服器？

其他工具給你原始 API 存取。我們給你**詞彙翻譯 + 智慧路由 + 研究分析**：

| 挑戰 | 我們的解決方案 |
|------|---------------|
| Agent 用 ICD 碼，PubMed 要 MeSH | ✅ **自動 ICD→MeSH 轉換** |
| 多資料庫，不同 API | ✅ **Unified Search** 單一入口 |
| 臨床問題需結構化搜尋 | ✅ **PICO 工具組** (`parse_pico` + `generate_search_queries`，由 Agent 驅動) |
| 醫學術語打錯字 | ✅ **ESpell 自動校正** |
| 單一來源結果太多 | ✅ **平行多源搜尋** + 去重 |
| 需要追蹤研究演進脈絡 | ✅ **研究時間軸 & 脈絡樹** + 重要文獻偵測 + 子議題分支 |
| 引用上下文不清楚 | ✅ **引用樹** 前向/後向/網路分析 |
| 無法取得全文 | ✅ **多源全文取得** (Europe PMC, CORE, CrossRef) |
| 基因/藥物資訊散布不同資料庫 | ✅ **NCBI 延伸** (Gene, PubChem, ClinVar) |
| 匯出到文獻管理軟體 | ✅ **一鍵匯出** (RIS, BibTeX, CSV, MEDLINE) |
| 需要最新預印本研究 | ✅ **預印本搜尋** (arXiv, medRxiv, bioRxiv) 含同儕審查過濾 |

### 核心差異化

1. **詞彙翻譯層** - Agent 自然語言表達，我們翻譯成各資料庫術語 (MeSH, ICD-10, text-mined entities)
2. **統一搜尋閘道** - 一個 `unified_search()` 呼叫，自動分流到 PubMed/Europe PMC/CORE/OpenAlex
3. **PICO 工具組** - `parse_pico()` 將臨床問題分解為 P/I/C/O 元素；Agent 再對每個元素呼叫 `generate_search_queries()` 並組合 Boolean 查詢
4. **研究時間軸 & 脈絡樹** - 自動偵測里程碑、多訊號重要文獻評分（引用影響力+多源交叉驗證+引用速度）、按子議題分支可視化研究演進
5. **引用網路分析** - 從單篇論文建構多層引用樹，繪製完整研究版圖
6. **完整研究生命週期** - 從搜尋 → 探索 → 全文 → 分析 → 匯出，一站完成
7. **Agent-First 設計** - 輸出優化機器決策，非人類閱讀

---

## 📡 外部 API 與資料來源

本 MCP 伺服器整合多個學術資料庫和 API：

### 核心資料來源

| 來源 | 收錄量 | 詞彙系統 | 自動轉換 | 說明 |
|------|--------|----------|----------|------|
| **NCBI PubMed** | 36M+ 文章 | MeSH | ✅ 原生支援 | 主要生醫文獻 |
| **NCBI Entrez** | 多資料庫 | MeSH | ✅ 原生支援 | Gene, PubChem, ClinVar |
| **Europe PMC** | 33M+ | Text-mined | ✅ 擷取 | 全文 XML 存取 |
| **CORE** | 200M+ | 無 | ➡️ 自由文字 | 開放取用聚合器 |
| **Semantic Scholar** | 200M+ | S2 Fields | ➡️ 自由文字 | AI 驅動推薦 |
| **OpenAlex** | 250M+ | Concepts | ➡️ 自由文字 | 開放學術元資料 |
| **NIH iCite** | PubMed | N/A | N/A | 引用指標 (RCR) |

> **🔑 說明**: ✅ = 完整詞彙支援 | ➡️ = 查詢直接傳遞（無控制詞彙）
>
> **ICD 碼**：自動偵測並在 PubMed 搜尋前轉換為 MeSH

### 環境變數

```bash
# 必填
NCBI_EMAIL=your@email.com          # NCBI 政策要求

# 選填 - 提高 API 限額
NCBI_API_KEY=your_ncbi_api_key     # 取得：https://www.ncbi.nlm.nih.gov/account/settings/
CORE_API_KEY=your_core_api_key     # 取得：https://core.ac.uk/services/api
S2_API_KEY=your_s2_api_key         # 取得：https://www.semanticscholar.org/product/api

# 選填 - 網路設定
HTTP_PROXY=http://proxy:8080       # HTTP 代理
HTTPS_PROXY=https://proxy:8080     # HTTPS 代理
```

---

## 🔄 運作原理：中介層架構

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AI AGENT                                        │
│                                                                              │
│   「找 I10 高血壓在糖尿病患者的治療論文」                                         │
│                                                                              │
└─────────────────────────────────────────┬───────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     🔄 PUBMED SEARCH MCP (中介層)                            │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │  1️⃣ 詞彙翻譯                                                            ││
│  │     • ICD-10 "I10" → MeSH "Hypertension"                                ││
│  │     • "糖尿病" → MeSH "Diabetes Mellitus"                               ││
│  │     • ESpell: "hypertention" → "hypertension"                           ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │  2️⃣ 智慧路由                                                            ││
│  │     ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐             ││
│  │     │ PubMed   │  │Europe PMC│  │   CORE   │  │ OpenAlex │             ││
│  │     │  36M+    │  │   33M+   │  │  200M+   │  │  250M+   │             ││
│  │     │  (MeSH)  │  │(全文)    │  │  (OA)    │  │(元資料)  │             ││
│  │     └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘             ││
│  │          └──────────────┴──────────────┴──────────────┘                 ││
│  │                              ▼                                          ││
│  │  3️⃣ 結果聚合：去重 + 排序 + 補充                                         ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────┬───────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         統一結果                                              │
│   • 150 篇唯一論文（從 4 個來源去重）                                          │
│   • 按相關性 + 引用影響力 (RCR) 排序                                          │
│   • 全文連結從 Europe PMC 補充                                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🛠️ MCP 工具概覽

### 🔍 搜尋與查詢智能

```
┌─────────────────────────────────────────────────────────────────┐
│                        搜尋入口                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   unified_search()          ← 🌟 單一入口，涵蓋所有來源            │
│        │                                                         │
│        ├── 快速搜尋     → 直接多源查詢                             │
│        ├── PICO 提示    → 偵測比較結構，顯示 P/I/C/O               │
│        └── ICD 擴展     → 自動 ICD→MeSH 轉換                      │
│                                                                  │
│   來源: PubMed · Europe PMC · CORE · OpenAlex                    │
│   自動: 去重 → 排序 → 補充全文連結                                  │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│   查詢智能                                                        │
│                                                                  │
│   generate_search_queries() → MeSH 擴展 + 同義詞發現              │
│   parse_pico()              → PICO 元素分解                       │
│   analyze_search_query()    → 查詢分析（不執行搜尋）                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 🔬 探索工具（找到關鍵論文後）

```
                        找到重要論文 (PMID)
                                   │
           ┌───────────────────────┼───────────────────────┐
           │                       │                       │
           ▼                       ▼                       ▼
    ┌─────────────┐        ┌─────────────┐        ┌─────────────┐
    │  往前追溯   │        │   相似主題   │        │  往後追蹤   │
    │  ◀──────    │        │  ≈≈≈≈≈≈     │        │  ──────▶    │
    │             │        │             │        │             │
    │ get_article │        │find_related │        │find_citing  │
    │ _references │        │ _articles   │        │ _articles   │
    │             │        │             │        │             │
    │  基礎論文   │        │  相似主題   │        │  後續研究   │
    └─────────────┘        └─────────────┘        └─────────────┘

    fetch_article_details()   → 詳細文章元資料
    get_citation_metrics()    → iCite RCR, 引用百分位
    build_citation_tree()     → 完整網絡視覺化（6 種格式）

```

### 📚 全文與匯出

| 類別 | 工具 |
|------|------|
| **全文** | `get_fulltext` → 多源取得（Europe PMC、CORE、PubMed、CrossRef） |
| **文字探勘** | `get_text_mined_terms` → 擷取基因、疾病、化學物質 |
| **匯出** | `prepare_export` → RIS、BibTeX、CSV、MEDLINE、JSON |

### 🧬 NCBI 延伸資料庫

| 工具 | 說明 |
|------|------|
| `search_gene` | 搜尋 NCBI Gene 資料庫 |
| `get_gene_details` | 依 NCBI Gene ID 取得基因詳情 |
| `get_gene_literature` | 取得與基因相關的 PubMed 文章 |
| `search_compound` | 搜尋 PubChem 化合物 |
| `get_compound_details` | 依 PubChem CID 取得化合物詳情 |
| `get_compound_literature` | 取得與化合物相關的 PubMed 文章 |
| `search_clinvar` | 搜尋 ClinVar 臨床變異 |

### 🕰️ 研究時間軸 & 脈絡樹

| 工具 | 說明 |
|------|------|
| `build_research_timeline` | 建構時間軸/脈絡樹，支援重要文獻偵測。格式：text, tree, mermaid, mindmap, json |
| `analyze_timeline_milestones` | 分析里程碑分佈 |
| `compare_timelines` | 比較多個主題的時間軸 |

### 🏥 機構訂閱與 ICD 轉換

| 工具 | 說明 |
|------|------|
| `configure_institutional_access` | 設定機構的 Link Resolver |
| `get_institutional_link` | 產生 OpenURL 存取連結 |
| `list_resolver_presets` | 列出 Resolver 預設值 |
| `test_institutional_access` | 測試 Resolver 設定 |
| `convert_icd_mesh` | ICD 碼與 MeSH 詞彙雙向轉換 |
| `unified_search` | 在查詢中自動偵測 ICD 代碼並擴展成 MeSH |

### 💾 Session 管理

| 工具 | 說明 |
|------|------|
| `get_session_pmids` | 取得暫存的 PMID 列表 |

| `get_cached_article` | 從 Session 快取取得文章（不消耗 API） |
| `get_session_summary` | Session 狀態概覽 |

若 MCP client 支援直接讀取 resources，也可使用以下動態 session resources：
- `session://context` — 目前 session 狀態
- `session://last-search` — 最近一次搜尋 metadata
- `session://last-search/pmids` — 最近一次 PMID 清單與 CSV 形式
- `session://last-search/results` — 最近一次搜尋對應的快取文章內容

### � Pipeline 管理

| 工具 | 說明 |
|------|------|
| `save_pipeline` | 保存 Pipeline 配置供後續重複使用（YAML/JSON，自動驗證） |
| `list_pipelines` | 列出已保存的 Pipeline（可按標籤/範圍過濾） |
| `load_pipeline` | 從名稱或檔案載入 Pipeline 以檢視/編輯 |
| `delete_pipeline` | 刪除 Pipeline 及其執行歷史 |
| `get_pipeline_history` | 查看執行歷史與文章 diff 分析 |
| `schedule_pipeline` | 排程定期執行（Phase 4） |

### �👁️ 視覺搜尋與圖片搜尋

| 工具 | 說明 |
|------|------|
| `analyze_figure_for_search` | 分析科學圖片以進行搜尋 |
| `search_biomedical_images` | 跨來源生物醫學圖片搜尋（X光、顯微鏡、照片、圖表） |

### 📄 預印本搜尋

透過 `unified_search` 的 `options` 旗標搜尋 **arXiv**、**medRxiv**、**bioRxiv** 預印本伺服器：

- `preprints`: 啟用專門的預印本搜尋，並把結果放在獨立區段。
- `all_types`: 在主結果中保留非同儕審查內容。

**建議組合：**

- 空白 `options`: 僅同儕審查結果。
- `options="preprints"`: 主結果維持同儕審查，加上額外預印本區段。
- `options="preprints, all_types"`: 有獨立預印本區段，且主結果也保留非同儕審查內容。
- `options="all_types"`: 不額外爬預印本伺服器，但保留各來源中的非同儕審查項目。

**預印本偵測方式** — 透過以下條件辨識預印本：

- 來源 API 的文章類型（OpenAlex、CrossRef、Semantic Scholar）
- 有 arXiv ID 但無 PubMed ID
- 已知預印本伺服器來源或期刊名稱
- DOI 前綴匹配預印本伺服器（如 `10.1101/` → bioRxiv/medRxiv、`10.48550/` → arXiv）

### 🌳 研究脈絡圖預覽

`unified_search` 現在可直接在同一次搜尋回應中附帶 PMID-based 的研究脈絡圖預覽：

| 選項旗標 | 說明 |
|----------|------|
| `context_graph` | Markdown 輸出附帶 Research Context Graph；JSON 輸出附帶 `research_context` 欄位 |

這適合 Agent 在不額外呼叫 `build_research_timeline` 的情況下，先快速掌握主題分支。

### ⏱️ MCP 進度回報

當 MCP client 提供 progress token 時，`unified_search`、`build_research_timeline`、`analyze_timeline_milestones`、`compare_timelines`、`get_fulltext`、`get_text_mined_terms` 都會回報主要階段進度，降低 Agent 長時間等待時的黑箱感。

---

## 📋 Agent 使用範例

### 1️⃣ 快速搜尋（最簡單）

```python
# Agent 自然語言詢問 - 中介層處理一切
unified_search(query="remimazolam ICU sedation", limit=20)

# 或使用臨床代碼 - 自動轉換為 MeSH
unified_search(query="I10 treatment in E11.9 patients")
#                     ↑ ICD-10           ↑ ICD-10
#                     高血壓             第二型糖尿病
```

### 2️⃣ PICO 臨床問題

**簡單路徑** — `unified_search` 可直接搜尋（不做 PICO 拆解）：

```python
# unified_search 直接搜尋；偵測「A vs B」模式並在 metadata 中顯示 PICO 提示
unified_search(query="remimazolam 在 ICU 鎮靜比 propofol 好嗎？")
# → 多源關鍵字搜尋 + 輸出中附帶 PICO 提示 metadata
# ⚠️ 這不會自動拆解 PICO 或擴展 MeSH！
# 結構化 PICO 搜尋請用下方 Agent 工作流程
```

**Agent 工作流程** — PICO 拆解 + MeSH 擴展（臨床問題建議使用）：

```
┌─────────────────────────────────────────────────────────────────────────┐
│  「remimazolam 在 ICU 鎮靜比 propofol 好嗎？」                            │
└─────────────────────────────────────────┬───────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         parse_pico()                                     │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐                     │
│  │    P    │  │    I    │  │    C    │  │    O    │                     │
│  │  ICU    │  │remimaz- │  │propofol │  │ 鎮靜    │                     │
│  │  病人   │  │  olam   │  │         │  │  結果   │                     │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘                     │
└───────┼────────────┼────────────┼────────────┼──────────────────────────┘
        │            │            │            │
        ▼            ▼            ▼            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              generate_search_queries() × 4（平行）                       │
│                                                                          │
│  P → "Intensive Care Units"[MeSH]                                        │
│  I → "remimazolam" [Supplementary Concept], "CNS 7056"                   │
│  C → "Propofol"[MeSH], "Diprivan"                                        │
│  O → "Conscious Sedation"[MeSH], "Deep Sedation"[MeSH]                   │
└─────────────────────────────────────────┬───────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              Agent 用 Boolean 邏輯組合                                   │
│                                                                          │
│  (P) AND (I) AND (C) AND (O)  ← 高精確度                                 │
│  (P) AND (I OR C) AND (O)     ← 高召回率                                 │
└─────────────────────────────────────────┬───────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              unified_search()（自動多源 + 去重）                          │
│                                                                          │
│  PubMed + Europe PMC + CORE + OpenAlex → 自動去重排序                     │
└─────────────────────────────────────────────────────────────────────────┘
```

```python
# Step 1: 解析臨床問題
parse_pico("remimazolam 在 ICU 鎮靜比 propofol 好嗎？")
# 返回: P=ICU 病人, I=remimazolam, C=propofol, O=鎮靜結果

# Step 2: 對每個元素取得 MeSH（平行！）
generate_search_queries(topic="ICU patients")   # P
generate_search_queries(topic="remimazolam")    # I
generate_search_queries(topic="propofol")       # C
generate_search_queries(topic="sedation")       # O

# Step 3: Agent 用 Boolean 組合
query = '("Intensive Care Units"[MeSH]) AND (remimazolam OR "CNS 7056") AND propofol AND sedation'

# Step 4: 搜尋（自動多源、去重、排序）
unified_search(query=query)
```

### 3️⃣ 從關鍵論文探索

```python
# 找到里程碑論文 PMID: 33475315
find_related_articles(pmid="33475315")   # 類似方法論
find_citing_articles(pmid="33475315")    # 誰引用了這篇？
get_article_references(pmid="33475315")  # 基礎是什麼？

# 建構完整研究脈絡
build_citation_tree(pmid="33475315", depth=2, output_format="mermaid")
```

### 4️⃣ 基因/藥物研究

```python
# 研究基因
search_gene(query="BRCA1", organism="human")
get_gene_literature(gene_id="672", limit=20)

# 研究藥物化合物
search_compound(query="propofol")
get_compound_literature(cid="4943", limit=20)
```

### 5️⃣ 匯出結果

```python
# 匯出上次搜尋結果
prepare_export(pmids="last", format="ris")      # → EndNote/Zotero
prepare_export(pmids="last", format="bibtex")   # → LaTeX

# 對上次搜尋中的指定文章抓全文
get_fulltext(pmid="12345678", extended_sources=True)
```

### 6️⃣ 預印本搜尋

```python
# 同時搜尋同儕審查文獻與預印本
unified_search(query="COVID-19 vaccine efficacy", options="preprints")
# → 主結果（同儕審查）+ 獨立預印本區段（arXiv, medRxiv, bioRxiv）

# 保留主結果中的非同儕審查內容
unified_search(query="CRISPR gene therapy", options="preprints, all_types")
# → 獨立預印本區段 + 主結果保留非同儕審查內容

# 僅同儕審查（預設行為）
unified_search("diabetes treatment")
# → 自動過濾來自任何來源的預印本

# 同一個搜尋回應附帶研究脈絡圖預覽
unified_search("remimazolam ICU sedation", options="context_graph")
```

### 7️⃣ Pipeline（可重複使用的搜尋計畫）

```python
# 保存模板式 pipeline
save_pipeline(
    name="icu_sedation_weekly",
    config="template: pico\nparams:\n  P: ICU patients\n  I: remimazolam\n  C: propofol\n  O: delirium",
    tags="anesthesia,sedation",
    description="每週 ICU 鎮靜藥物監控"
)

# 保存自訂 DAG pipeline
save_pipeline(
    name="brca1_comprehensive",
    config="""
steps:
  - id: expand
    action: expand
    params: { topic: BRCA1 breast cancer }
  - id: pubmed
    action: search
    params: { query: BRCA1, sources: pubmed, limit: 50 }
  - id: expanded
    action: search
    inputs: [expand]
    params: { strategy: mesh, sources: pubmed,openalex, limit: 50 }
  - id: merged
    action: merge
    inputs: [pubmed, expanded]
    params: { method: rrf }
  - id: enriched
    action: metrics
    inputs: [merged]
output:
  limit: 30
  ranking: quality
"""
)

# 執行已保存的 pipeline
unified_search(pipeline="saved:icu_sedation_weekly")

# 管理
list_pipelines(tag="anesthesia")
load_pipeline(source="brca1_comprehensive")  # 檢視 YAML
get_pipeline_history(name="icu_sedation_weekly")  # 查看過去執行
```

---

## 🔍 搜尋模式比較

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        搜尋模式決策樹                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   「我需要什麼樣的搜尋？」                                                 │
│         │                                                                │
│         ├── 確切知道要搜什麼？                                            │
│         │   └── unified_search(query="主題關鍵字")                        │
│         │       → 快速，自動路由到最佳來源                                 │
│         │                                                                │
│         ├── 有臨床問題（A vs B）？                                        │
│         │   └── parse_pico() → generate_search_queries() × N             │
│         │       → Agent 組合 Boolean → unified_search()                 │
│         │                                                                │
│         ├── 需要全面系統性覆蓋？                                          │
│         │   └── generate_search_queries() → 平行搜尋                     │
│         │       → MeSH 擴展，多策略，合併                                 │
│         │                                                                │
│         └── 從關鍵論文探索？                                              │
│             └── find_related/citing/references → build_citation_tree     │
│                 → 引用網絡，研究脈絡                                      │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

| 模式 | 入口 | 適用情境 | 自動功能 |
|------|------|----------|----------|
| **快速** | `unified_search()` | 快速主題搜尋 | ICD→MeSH, 多源, 去重 |
| **PICO** | `parse_pico()` → Agent | 臨床問題 | Agent: 拆解 → MeSH 擴展 → Boolean |
| **系統** | `generate_search_queries()` | 文獻回顧 | MeSH 擴展, 同義詞 |
| **探索** | `find_*_articles()` | 從關鍵論文 | 引用網絡, 相關 |

---

## 🤖 Claude Skills（AI Agent 工作流程）

預建工作流程指南位於 `.claude/skills/`，分為**使用 Skills**（使用 MCP server）和**開發 Skills**（維護專案）：

### 📚 使用 Skills (10) — 給使用此 MCP Server 的 AI Agent

| Skill | 說明 |
|-------|------|
| `pubmed-quick-search` | 基本搜尋含篩選 |
| `pubmed-systematic-search` | MeSH 擴展，全面性 |
| `pubmed-pico-search` | 臨床問題分解 |
| `pubmed-paper-exploration` | 引用樹，相關文章 |
| `pubmed-gene-drug-research` | Gene/PubChem/ClinVar |
| `pubmed-fulltext-access` | Europe PMC, CORE 全文 |
| `pubmed-export-citations` | RIS/BibTeX/CSV 匯出 |
| `pubmed-multi-source-search` | 跨資料庫統一搜尋 |
| `pubmed-mcp-tools-reference` | 完整工具參考指南 |
| `pipeline-persistence` | 保存、載入、重複使用搜尋計畫 |

### 🔧 開發 Skills (13) — 給專案貢獻者

| Skill | 說明 |
|-------|------|
| `changelog-updater` | 自動更新 CHANGELOG.md |
| `code-refactor` | DDD 架構重構 |
| `code-reviewer` | 程式碼品質與安全審查 |
| `ddd-architect` | 新功能 DDD 腳手架 |
| `git-doc-updater` | 提交前同步文件 |
| `git-precommit` | Pre-commit 工作流程編排 |
| `memory-checkpoint` | 儲存上下文到 Memory Bank |
| `memory-updater` | 更新 Memory Bank 檔案 |
| `project-init` | 初始化新專案 |
| `readme-i18n` | 多語言 README 同步 |
| `readme-updater` | 同步 README 與程式碼變更 |
| `roadmap-updater` | 更新 ROADMAP.md 狀態 |
| `test-generator` | 產生測試套件 |

> 📁 **位置**: `.claude/skills/*/SKILL.md`（Claude Code 專屬，也是 repo skills 的唯一來源）
> 不要再另外鏡像或拆分到 `.github/skills/`。
> 這些 repo skills 屬於 project-scoped 自訂內容，應納入版本控制。跨專案的個人 skills 則應放在 `~/.copilot/skills/` 或 `~/.claude/skills/` 之類的使用者目錄，不要提交到本 repository。

---

## 🏗️ 架構（DDD）

本專案採用 **Domain-Driven Design (DDD)** 架構，以文獻研究領域知識為核心模型。

```
src/pubmed_search/
├── domain/                     # 核心業務邏輯
│   └── entities/article.py     # UnifiedArticle, Author 等
├── application/                # 用例
│   ├── search/                 # QueryAnalyzer, ResultAggregator
│   ├── export/                 # 引用匯出（RIS, BibTeX...）
│   └── session/                # SessionManager
├── infrastructure/             # 外部系統
│   ├── ncbi/                   # Entrez, iCite, Citation Exporter
│   ├── sources/                # Europe PMC, CORE, CrossRef...
│   └── http/                   # HTTP 客戶端
├── presentation/               # 使用者介面
│   ├── mcp_server/             # MCP 工具、prompts、resources
│   │   └── tools/              # discovery, strategy, pico, export...
│   └── api/                    # REST API（Copilot Studio）
└── shared/                     # 跨切面關注
    ├── exceptions.py           # 統一錯誤處理
    └── async_utils.py          # Rate limiter, retry, circuit breaker
```

### 內部機制（對 Agent 透明）

| 機制 | 說明 |
|------|------|
| **Session** | 自動建立、自動切換 |
| **Cache** | 搜尋結果自動快取，避免重複 API 呼叫 |
| **Rate Limit** | 自動遵守 NCBI API 限制 (0.34s/0.1s) |
| **MeSH Lookup** | `generate_search_queries()` 自動查詢 NCBI MeSH 資料庫 |
| **ESpell** | 自動拼字校正（`remifentanyl` → `remifentanil`）|
| **Query Analysis** | 每個建議查詢都顯示 PubMed 實際如何詮釋 |

### 詞彙轉換層（核心功能）

> **核心價值**：我們是 **Agent 與 Search Engine 之間的智慧中介層**，自動處理詞彙標準化，讓 Agent 無需了解各資料庫的術語系統。

不同資料來源使用不同的控制詞彙系統。本伺服器提供自動轉換：

| API / 資料庫 | 詞彙系統 | 自動轉換 |
|--------------|----------|----------|
| **PubMed / NCBI** | MeSH (醫學主題詞表) | ✅ 完整支援 `expand_with_mesh()` |
| **ICD 碼** | ICD-10-CM / ICD-9-CM | ✅ 自動偵測並轉換為 MeSH |
| **Europe PMC** | 文字探勘實體 (Gene, Disease, Chemical) | ✅ `get_text_mined_terms()` 擷取 |
| **OpenAlex** | OpenAlex Concepts (已棄用) | ❌ 僅支援自由文字 |
| **Semantic Scholar** | S2 Field of Study | ❌ 僅支援自由文字 |
| **CORE** | 無 | ❌ 僅支援自由文字 |
| **CrossRef** | 無 | ❌ 僅支援自由文字 |

#### 自動 ICD → MeSH 轉換

當搜尋包含 ICD 碼時（例如 `I10` 代表高血壓），`unified_search()` 會自動：
1. 透過 `detect_and_expand_icd_codes()` 偵測 ICD-10/ICD-9 模式
2. 從內部映射表查詢對應 MeSH 詞彙 (`ICD10_TO_MESH`, `ICD9_TO_MESH`)
3. 以 MeSH 同義詞擴展查詢，提供更完整的搜尋結果

```python
# Agent 使用臨床術語呼叫 unified_search
unified_search(query="I10 treatment outcomes")

# 伺服器自動擴展為 PubMed 相容查詢
"(I10 OR Hypertension[MeSH]) treatment outcomes"
```

> 📖 **完整架構說明**：[ARCHITECTURE.md](ARCHITECTURE.md)

### MeSH 自動擴展 + 查詢分析

呼叫 `generate_search_queries("remimazolam sedation")` 時，內部會：

1. **ESpell 校正** - 修正拼字錯誤
2. **MeSH 查詢** - `Entrez.esearch(db="mesh")` 取得標準詞彙
3. **同義詞擷取** - 從 MeSH Entry Terms 取得同義詞
4. **查詢分析** - 分析 PubMed 如何詮釋每個查詢

```json
{
  "mesh_terms": [
    {
      "input": "remimazolam",
      "preferred": "remimazolam [Supplementary Concept]",
      "synonyms": ["CNS 7056", "ONO 2745"]
    }
  ],
  "all_synonyms": ["CNS 7056", "ONO 2745", ...],
  "suggested_queries": [
    {
      "id": "q1_title",
      "query": "(remimazolam sedation)[Title]",
      "purpose": "精確標題匹配 - 最高精確度",
      "estimated_count": 8,
      "pubmed_translation": "\"remimazolam sedation\"[Title]"
    },
    {
      "id": "q3_and",
      "query": "(remimazolam AND sedation)",
      "purpose": "所有關鍵字必須出現",
      "estimated_count": 561,
      "pubmed_translation": "(\"remimazolam\"[Supplementary Concept] OR \"remimazolam\"[All Fields]) AND (\"sedate\"[All Fields] OR ...)"
    }
  ]
}
```

> **查詢分析的價值**：Agent 認為 `remimazolam AND sedation` 只搜尋這兩個詞，但 PubMed 實際上擴展到 Supplementary Concept + 同義詞，結果從 8 篇變成 561 篇。這幫助 Agent 理解**意圖**與**實際搜尋**的差異。

---

## 🔒 HTTPS 部署

為生產環境啟用 HTTPS 安全通訊。

### 快速開始

```bash
# Step 1: 生成 SSL 憑證
./scripts/generate-ssl-certs.sh

# Step 2: 啟動 HTTPS 服務（Docker）
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

### Claude Desktop 設定

```json
{
  "mcpServers": {
    "pubmed-search": {
      "url": "https://localhost/sse"
    }
  }
}
```

---

## 🏢 Microsoft Copilot Studio 整合

將 PubMed Search MCP 與 **Microsoft 365 Copilot**（Word, Teams, Outlook）整合！

### 快速開始

```bash
# 使用 Streamable HTTP transport 啟動（Copilot Studio 要求）
python run_server.py --transport streamable-http --port 8765

# 若要保留完整工具 schema，同時開啟 Copilot 相容 HTTP 行為
python run_server.py --transport streamable-http --copilot-compatible --port 8765

# 或使用專用腳本搭配 ngrok
./scripts/start-copilot-studio.sh --with-ngrok
```

### Copilot Studio 設定

| 欄位 | 值 |
|------|---|
| **Server name** | `PubMed Search` |
| **Server URL** | `https://your-server.com/mcp` |
| **Authentication** | `None`（或 API Key）|

> 📖 **完整文件**: [copilot-studio/README.md](copilot-studio/README.md)
>
> 若只需要 Copilot 相容 HTTP 行為，用 `run_server.py --copilot-compatible`；若還需要簡化後的工具 schema，使用 `run_copilot.py`。
>
> ⚠️ **注意**: SSE transport 自 2025 年 8 月起棄用。使用 `streamable-http`。

---

> 📖 **更多文件**:
> - 架構 → [ARCHITECTURE.md](ARCHITECTURE.md)
> - 部署指南 → [DEPLOYMENT.md](DEPLOYMENT.md)
> - Copilot Studio → [copilot-studio/README.md](copilot-studio/README.md)

---

## 🔐 安全性

### 安全功能

| 層級 | 功能 | 說明 |
|------|------|------|
| **HTTPS** | TLS 1.2/1.3 加密 | 所有流量透過 Nginx 加密 |
| **Rate Limiting** | 30 req/s | Nginx 層級保護 |
| **Security Headers** | XSS/CSRF 防護 | X-Frame-Options, X-Content-Type-Options |
| **SSE Optimization** | 24h timeout | 即時長連線 |
| **No Database** | 無狀態 | 無 SQL 注入風險 |
| **No Secrets** | 僅記憶體 | 不儲存憑證 |

詳見 [DEPLOYMENT.md](DEPLOYMENT.md) 完整部署說明。

---

## 📤 匯出格式

匯出搜尋結果為各大參考文獻管理軟體相容的格式：

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

### 特殊字元處理
- BibTeX 匯出使用 **pylatexenc** 進行正確的 LaTeX 編碼
- 北歐字元 (ø, æ, å)、變音符號 (ü, ö, ä) 和重音符號都能正確轉換
- 範例: `Søren Hansen` → `S{\o}ren Hansen`

---

## 📚 引用

GitHub 會根據 [CITATION.cff](CITATION.cff) 顯示 **Cite this repository**。若你在論文、methods section、技術報告或內部研究文件中使用 PubMed Search MCP，建議直接使用 GitHub 產生的引用格式，或重用這份 repository citation metadata。

```bibtex
@software{pubmed_search_mcp,
  title = {PubMed Search MCP},
  author = {u9401066},
  url = {https://github.com/u9401066/pubmed-search-mcp}
}
```

---

## 📄 授權

Apache License 2.0 - 詳見 [LICENSE](LICENSE)

---

## 🔗 相關連結

- [GitHub Repository](https://github.com/u9401066/pubmed-search-mcp)
- [PyPI Package](https://pypi.org/project/pubmed-search-mcp/)
- [NCBI Entrez Programming Utilities](https://www.ncbi.nlm.nih.gov/books/NBK25497/)
