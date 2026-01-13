# PubMed Search MCP × Microsoft Copilot Studio 整合指南

本指南說明如何將 PubMed Search MCP 整合到 Microsoft Copilot Studio，讓您在 **Word、Teams、Outlook** 等 Microsoft 365 應用程式中使用 PubMed 文獻搜尋功能。

## 📋 目錄

- [需求](#需求)
- [方法一：MCP Onboarding Wizard（推薦）](#方法一mcp-onboarding-wizard推薦)
- [方法二：Power Apps Custom Connector](#方法二power-apps-custom-connector)
- [部署選項](#部署選項)
- [在 Word Copilot 中使用](#在-word-copilot-中使用)
- [疑難排解](#疑難排解)

---

## 需求

| 項目 | 需求 |
|------|------|
| **Transport** | Streamable HTTP（SSE 已於 2025/8 起停用）|
| **URL** | 公開可訪問的 HTTPS URL |
| **Endpoint** | `/mcp` |
| **認證** | None、API Key 或 OAuth 2.0 |

---

## 方法一：MCP Onboarding Wizard（推薦）

### 步驟 1：部署 MCP Server

```bash
# 選項 A：使用 ngrok（快速測試）
pip install pubmed-search-mcp
python -m pubmed_search.mcp --transport streamable-http --port 8765 &
ngrok http 8765
# 記下 URL，例如：https://abc123.ngrok.io

# 選項 B：部署到雲端（見「部署選項」章節）
```

### 步驟 2：在 Copilot Studio 中設定

1. 前往 [Copilot Studio](https://web.powerva.microsoft.com/)
2. 創建新 Agent 或選擇現有 Agent
3. 點擊 **Tools** → **Add a tool** → **New tool**
4. 選擇 **Model Context Protocol**

### 步驟 3：填入設定值

| 欄位 | 值 |
|------|-----|
| **Server name** | `PubMed Search` |
| **Server description** | 見下方 |
| **Server URL** | `https://your-server.com/mcp` |
| **Authentication** | `None`（或選擇 API Key） |

**Server description（複製貼上）：**

```
搜尋 PubMed 醫學文獻資料庫（3300萬+篇文章）。功能包括：
- MeSH 詞彙擴展搜尋
- PICO 臨床問題分析
- Europe PMC 和 CORE 全文獲取（2億+ 開放取用論文）
- NCBI 基因、化合物、臨床變異研究
- 引用網路探索（相關文章、引用追蹤）
- 匯出 RIS、BibTeX、CSV 格式
```

### 步驟 4：完成設定

1. 點擊 **Create**
2. 在 "Add tool" 對話框中，選擇 **Create a new connection**
3. 點擊 **Add to agent**
4. 點擊 **Publish** 發布 Agent

---

## 方法二：Power Apps Custom Connector

如果您需要更多控制權，可以使用 OpenAPI schema 建立自訂連接器。

### 步驟 1：準備 Schema 檔案

使用本目錄中的 `openapi-schema.yaml`，並更新 `host` 欄位為您的伺服器網域。

### 步驟 2：建立 Custom Connector

1. 在 Copilot Studio 中，點擊 **Tools** → **Add a tool** → **New tool**
2. 選擇 **Custom connector**（會跳轉到 Power Apps）
3. 選擇 **New custom connector** → **Import OpenAPI file**
4. 上傳 `openapi-schema.yaml`
5. 點擊 **Continue** 完成設定

### 步驟 3：新增到 Agent

1. 返回 Copilot Studio
2. **Tools** → **Add a tool** → **Model Context Protocol**
3. 選擇您剛建立的 connector
4. **Add to agent**

---

## 部署選項

### 選項 A：ngrok（開發/測試）

```bash
# 終端 1：啟動 MCP Server
python run_server.py --transport streamable-http --port 8765

# 終端 2：啟動 ngrok
ngrok http 8765
```

⚠️ 免費版 ngrok 每次重啟 URL 會變更

### 選項 B：Railway（免費額度）

```bash
# 安裝 Railway CLI
npm install -g @railway/cli

# 登入並部署
railway login
railway init
railway up
```

### 選項 C：Azure Container Apps

```bash
# 建立資源群組
az group create --name pubmed-mcp-rg --location eastasia

# 部署容器
az containerapp create \
  --name pubmed-mcp \
  --resource-group pubmed-mcp-rg \
  --image ghcr.io/u9401066/pubmed-search-mcp:latest \
  --target-port 8765 \
  --ingress external \
  --env-vars NCBI_EMAIL=your@email.com MCP_TRANSPORT=streamable-http
```

### 選項 D：Docker + 自有伺服器

```bash
docker run -d \
  --name pubmed-mcp \
  -p 8765:8765 \
  -e NCBI_EMAIL=your@email.com \
  -e MCP_TRANSPORT=streamable-http \
  u9401066/pubmed-search-mcp:latest
```

搭配 Nginx 反向代理提供 HTTPS。

---

## 在 Word Copilot 中使用

發布 Agent 後：

1. 開啟 **Microsoft Word**
2. 點擊右側的 **Copilot** 按鈕
3. 在 Copilot 面板中，選擇您的 **PubMed Search** Agent
4. 開始對話：

### 範例對話

```
用戶：搜尋 diabetes treatment 的最新研究

Copilot：我找到了以下關於糖尿病治療的最新文獻...
[顯示搜尋結果]

用戶：分析這個臨床問題：Metformin vs Insulin 對第二型糖尿病的血糖控制效果

Copilot：[進行 PICO 分析]
- P (Patient): 第二型糖尿病患者
- I (Intervention): Metformin
- C (Comparison): Insulin  
- O (Outcome): 血糖控制效果
[執行搜尋並提供結果]

用戶：幫我把這些文獻匯出成 RIS 格式

Copilot：已準備好 RIS 檔案，您可以下載後匯入 EndNote 或 Zotero。
```

---

## 可用工具（35+）

連接後，Copilot Studio 會自動發現所有工具：

| 類別 | 工具 | 說明 |
|------|------|------|
| **核心搜尋** | `search_literature` | PubMed 文獻搜尋 |
| | `search_europe_pmc` | Europe PMC 搜尋（含開放取用篩選）|
| | `search_core` | CORE 2億+ 開放取用論文搜尋 |
| **發現** | `find_related_articles` | 尋找相似文章 |
| | `find_citing_articles` | 尋找引用此文章的論文 |
| | `get_article_references` | 獲取參考文獻 |
| | `build_citation_tree` | 建立引用網路 |
| **分析** | `parse_pico` | PICO 臨床問題分析 |
| | `generate_search_queries` | 生成 MeSH 擴展查詢 |
| | `merge_search_results` | 合併多次搜尋結果 |
| **全文** | `get_fulltext` | 獲取結構化全文 |
| | `get_fulltext_xml` | 獲取 JATS XML 全文 |
| | `get_core_fulltext` | 從 CORE 獲取全文 |
| **NCBI 延伸** | `search_gene` | 基因搜尋 |
| | `search_compound` | 化合物搜尋（PubChem）|
| | `search_clinvar` | 臨床變異搜尋 |
| **匯出** | `prepare_export` | 匯出 RIS、BibTeX、CSV |

---

## 疑難排解

### 問題：無法連接到 MCP Server

1. 確認 Server URL 是 HTTPS
2. 確認使用 `streamable-http` transport（不是 SSE）
3. 確認 endpoint 是 `/mcp`
4. 測試：`curl -X POST https://your-server.com/mcp`

### 問題：工具沒有顯示

1. 在 Copilot Studio 中，進入 **Tools** 頁面
2. 點擊 PubMed Search MCP connector
3. 確認 **Allow all** 開關已開啟

### 問題：Agent 無法執行工具

確認已啟用 **Generative Orchestration**：
1. 進入 Agent 設定
2. 找到 Generative Orchestration 選項
3. 確認已開啟

---

## 參考資料

- [Copilot Studio MCP 整合文檔](https://learn.microsoft.com/en-us/microsoft-copilot-studio/agent-extend-action-mcp)
- [連接現有 MCP Server](https://learn.microsoft.com/en-us/microsoft-copilot-studio/mcp-add-existing-server-to-agent)
- [新增 MCP 工具到 Agent](https://learn.microsoft.com/en-us/microsoft-copilot-studio/mcp-add-components-to-agent)
- [MCP 官方規範](https://modelcontextprotocol.io/)
