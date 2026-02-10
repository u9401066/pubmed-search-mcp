# 競品賣點分析 (內部文件)

> **文件性質**: 內部參考  
> **目的**: 收集其他專案的亮點功能，供未來擴展參考  
> **最後更新**: 2026-02-10  
> **維護者**: Eric

---

# 目錄

1. [專案總覽](#專案總覽)
2. [各專案賣點](#各專案賣點)
3. [功能清單 (可學習)](#功能清單-可學習)
4. [大型學術 MCP 構想](#大型學術-mcp-構想)
5. [更新日誌](#更新日誌)

---

# 專案總覽

| # | 專案名稱 | GitHub | 特色定位 |
|---|---------|--------|----------|
| 1 | paper-search-mcp | [openags/paper-search-mcp](https://github.com/openags/paper-search-mcp) | 多來源瑞士刀 (8 個資料庫) ⭐643 |
| 2 | semantic-scholar-fastmcp-mcp-server | [zongmin-yu](https://github.com/zongmin-yu/semantic-scholar-fastmcp-mcp-server) | 引用分析 + 推薦系統 |
| 3 | google-scholar-mcp | [mochow13](https://github.com/mochow13/google-scholar-mcp) | Google Scholar 爬蟲 (TypeScript) + Gemini 整合 |
| 4 | **JackKuo666 系列** | [JackKuo666](https://github.com/JackKuo666) | 生醫領域 MCP 專家 (15+ 專案) |
| 5 | **Scientific-Papers-MCP** ⭐ | [benedict2310](https://github.com/benedict2310/Scientific-Papers-MCP) | 6 來源整合 + 全文提取 + DOI 解析 (TypeScript) |
| 6 | **arxiv-mcp-server** ⭐⭐⭐ | [blazickjp](https://github.com/blazickjp/arxiv-mcp-server) | arXiv 專精 + 研究分析 Prompts (1.9k stars!) |
| 7 | arxiv-paper-mcp | [daheepk](https://github.com/daheepk/arxiv-paper-mcp) | arXiv 輕量 + MCP Resources + 課項架構 |
| 8 | **Google-Search-MCP-Server** ⭐⭐ | [mixelpixx](https://github.com/mixelpixx/Google-Search-MCP-Server) | Google 研究綜合 + Agent 模式 + 品質評估 (175 stars) |
| 9 | **papersgpt-for-zotero** ⭐⭐⭐ | [papersgpt/papersgpt-for-zotero](https://github.com/papersgpt/papersgpt-for-zotero) | Zotero AI 外掛 + C++ MCP + BM25 全文搜尋 (2k stars!) |
| 10 | **zotero-mcp** ⭐⭐ | [54yyyu/zotero-mcp](https://github.com/54yyyu/zotero-mcp) | Zotero 語義搜尋 + Embeddings + PDF 註釋 (751 stars) |
| 11 | **pubmearch** | [Darkroaster/pubmearch](https://github.com/Darkroaster/pubmearch) | PubMed 熱點分析 + 趨勢追蹤 + 發文統計 (142 stars) |
| 12 | **mcp-simple-pubmed** | [andybrandt/mcp-simple-pubmed](https://github.com/andybrandt/mcp-simple-pubmed) | PubMed 輕量 + 全文取得 + Smithery (142 stars) |
| 13 | **BioMCP** ⭐⭐⭐ | [genomoncology/biomcp](https://github.com/genomoncology/biomcp) | 生醫全局 (24 Tools + 10 數據源 + 統一查詢語言) (413 stars) |
| 14 | **pubmedmcp** | [grll/pubmedmcp](https://github.com/grll/pubmedmcp) | PubMed 極簡 + uvx 一鍵運行 (95 stars) |
| 15 | **pubmed-mcp-server** ⭐ | [cyanheads/pubmed-mcp-server](https://github.com/cyanheads/pubmed-mcp-server) | PubMed TypeScript + 圖表生成 + HTTP (52 stars) |
| 16 | **paper-search-mcp-nodejs** | [Dianel555/paper-search-mcp-nodejs](https://github.com/Dianel555/paper-search-mcp-nodejs) | 14 平台搜尋 + 安全特性 (91 stars) 🆕 |
| 17 | **healthcare-mcp-public** | [Cicatriiz/healthcare-mcp-public](https://github.com/Cicatriiz/healthcare-mcp-public) | 醫療健康 MCP (FDA+PubMed+ICD-10) (87 stars) 🆕 |

---

# 各專案賣點

## 1. paper-search-mcp (openags) ⭐ 469 stars

### 核心賣點

| 賣點 | 說明 | 可學習度 |
|------|------|:--------:|
| **多資料來源整合** | 8 個學術資料庫一站式搜尋 | ⭐⭐⭐ |
| **PDF 下載 + 文字提取** | PyPDF2 直接讀取 PDF 內容 | ⭐⭐ |
| **Smithery 整合** | 一鍵安裝，降低使用門檻 | ⭐⭐⭐ |
| **PyPI 發布** | `uv add paper-search-mcp` | ⭐⭐⭐ |
| **社群活躍** | 469 stars, 5 contributors | - |

### 支援的資料來源

```
✅ arXiv        - 搜尋 + 下載 + 閱讀
✅ PubMed       - 搜尋 (淺層)
✅ bioRxiv      - 搜尋 + 下載 + 閱讀
✅ medRxiv      - 搜尋 + 下載 + 閱讀
✅ Semantic Scholar - 搜尋 + 下載 + 閱讀
✅ Google Scholar   - 搜尋
✅ IACR (密碼學)    - 搜尋 + 下載 + 閱讀
✅ CrossRef     - 搜尋 + DOI 查詢
```

### 值得參考的設計

```python
# PDF 文字提取
read_arxiv_paper(paper_id) -> str  # 下載 PDF 並提取文字

# DOI 跨來源查詢
get_crossref_paper_by_doi(doi) -> Paper
```

---

## 2. semantic-scholar-fastmcp-mcp-server (zongmin-yu)

### 核心賣點

| 賣點 | 說明 | 可學習度 |
|------|------|:--------:|
| **推薦系統 (正/負例)** ⭐ | 給「想要的」和「不想要的」論文，找類似的 | ⭐⭐⭐ |
| **完整引用分析** | citations, references, influential | ⭐⭐⭐ |
| **作者分析** | h-index, 論文列表, 引用數 | ⭐⭐ |
| **TLDR 摘要** | AI 生成的論文摘要 | ⭐⭐ |
| **多種 ID 支援** | 可用 PMID/PMCID 查詢 | ⭐⭐⭐ |
| **進階篩選** | 引用數、年份、期刊、學科 | ⭐⭐ |

### 推薦系統 (最強功能)

```python
# 單篇推薦 - 找類似論文
get_paper_recommendations_single(
    paper_id="649def34f8be52c8b66281af98ae884c09aef38b",
    from_pool="recent",  # 或 "all-cs"
    limit=20
)

# 多篇推薦 - 正例 + 負例 (非常強大！)
get_paper_recommendations_multi(
    positive_paper_ids=["好論文1", "好論文2"],  # 想要類似的
    negative_paper_ids=["不想要的論文"],         # 想要排除的
    limit=20
)
```

### 支援的 Paper ID 格式

```
PMID:19872477       ← 可用 PubMed ID！
PMCID:2323736       ← 可用 PMC ID！
DOI:10.18653/v1/N18-3011
ARXIV:2106.15928
CorpusId:215416146
URL:https://arxiv.org/abs/2106.15928v1
```

### 進階搜尋參數

```python
paper_relevance_search(
    query="...",
    year="2020-2024",           # 年份範圍
    min_citation_count=50,       # 引用數門檻
    publication_types=["Review", "ClinicalTrial"],
    fields_of_study=["Medicine", "Biology"],
    venue="Nature",              # 期刊篩選
    open_access_pdf=True,        # 僅開放取用
    sort="citationCount:desc"    # 排序
)
```

### 可返回的特殊欄位

```python
"influentialCitationCount"  # 有影響力的引用數 ⭐
"tldr"                      # AI 生成摘要 ⭐
"openAccessPdf"             # PDF 連結
"fieldsOfStudy"             # 學科分類
```

---

## 3. semanticscholar-MCP-Server (JackKuo666)

### 核心賣點

| 賣點 | 說明 | 可學習度 |
|------|------|:--------:|
| **極簡設計** | 200 行完成核心功能 | ⭐ |
| **使用官方 SDK** | `semanticscholar` Python 套件 | ⭐⭐ |
| **h-index 支援** | 作者分析有價值 | ⭐⭐ |

### SDK 使用範例

```python
from semanticscholar import SemanticScholar
sch = SemanticScholar()
results = sch.search_paper(query, limit=limit, fields=fields)
```

---

## 4. JackKuo666 MCP 專案系列 🔥

> **作者**: JackKuo666 (浙江實驗室, 杭州)  
> **專長**: 生物醫學 + LLM + MCP  
> **GitHub**: https://github.com/JackKuo666  
> **專案數量**: 15+ 個學術 MCP Server

### 專案總覽

| 專案 | Stars | 資料來源 | 說明 |
|------|:-----:|---------|------|
| **Google-Scholar-MCP-Server** | ⭐ 175 | Google Scholar | 爬蟲 (風險高) |
| **PubMed-MCP-Server** | ⭐ 82 | PubMed | **直接競品** ⚠️ |
| **Sci-Hub-MCP-Server** | ⭐ 45 | Sci-Hub | PDF 下載 (法律風險) |
| **semanticscholar-MCP-Server** | ⭐ 35 | Semantic Scholar | 官方 SDK |
| **ClinicalTrials-MCP-Server** | ⭐ 13 | ClinicalTrials.gov | 臨床試驗 |
| **PubTator-MCP-Server** | ⭐ 8 | PubTator3 | 生醫實體標註 |
| **PubChem-MCP-Server** | ⭐ 4 | PubChem | 化學化合物 |
| **Crossref-MCP-Server** | ⭐ 3 | CrossRef | DOI 查詢 |
| **PyPI-MCP-Server** | ⭐ 2 | PyPI | Python 套件 |
| **ChEMBL-MCP-Server** | ⭐ 1 | ChEMBL | 藥物資料庫 |
| **ChemRxiv-MCP-Server** | ⭐ 1 | ChemRxiv | 化學預印本 |
| **arXiv-Search-MCP-Server** | - | arXiv | 預印本搜尋 |
| **paperscraper-MCP-Server** | ⭐ 1 | 多來源 | PubMed/arXiv/bioRxiv |
| **pdffigures2-MCP-Server** | - | PDF | 圖表提取 |
| **Bioconda-MCP-Server** | ⭐ 1 | Bioconda | 生物資訊套件 |
| **BioMed-MCP-Server** | - | 多來源 | 生醫文獻整合 |

### 重點分析

#### PubMed-MCP-Server ⚠️ 直接競品

| 項目 | 說明 |
|------|------|
| **Stars** | ⭐ 82 (有一定用戶) |
| **Forks** | 32 |
| **GitHub** | https://github.com/JackKuo666/PubMed-MCP-Server |

**Tools 清單 (4 個 tools + 1 個 prompt)**:

| Tool | 說明 |
|------|------|
| `search_pubmed_key_words` | 關鍵字搜尋 |
| `search_pubmed_advanced` | 進階搜尋 (term, title, author, journal, date) |
| `get_pubmed_article_metadata` | 取得文章 metadata |
| `download_pubmed_pdf` | 嘗試下載 PMC PDF |
| `deep_paper_analysis` (prompt) | 生成論文分析提示詞 |

**進階搜尋參數**:
```python
search_pubmed_advanced(
    term="COVID-19",
    title="vaccine",
    author="Smith",
    journal="Nature",
    start_date="2020/01/01",
    end_date="2021/12/31",
    num_results=10
)
```

**與我們的比較**:

| 功能 | 我們 | JackKuo666 |
|------|:----:|:----------:|
| 基本搜尋 | ✅ | ✅ |
| 進階搜尋 | ✅ MeSH/tiab/pt | ⚠️ 僅欄位篩選 |
| **PICO 解析** | ✅ | ❌ |
| **MeSH 擴展** | ✅ | ❌ |
| **拼字校正** | ✅ ESpell | ❌ |
| **搜尋策略生成** | ✅ | ❌ |
| **ELink 相關文章** | ✅ | ❌ |
| PDF 下載 | ✅ PMC | ✅ PMC |
| Deep Analysis | ❌ | ✅ (Prompt) |
| 排序選項 | ✅ 4 種 | ❌ |
| 日期類型 | ✅ edat/pdat/mdat | ⚠️ 僅 Publication Date |

**我們的優勢**:
- ✅ 更完整的 PubMed Entrez API 整合
- ✅ PICO 解析 (他們沒有)
- ✅ MeSH 自動擴展 (他們沒有)
- ✅ 拼字校正 (他們沒有)
- ✅ 搜尋策略生成 (他們沒有)
- ✅ DDD 架構 (他們是平面設計)

**他們的優勢**:
- ✅ 已有 82 stars (市場先行優勢)
- ✅ Smithery 整合完成
- ✅ Deep Paper Analysis prompt

#### Sci-Hub-MCP-Server (法律風險)

| 項目 | 說明 |
|------|------|
| **Stars** | ⭐ 45 |
| **功能** | 透過 Sci-Hub 下載論文 PDF |
| **風險** | ⚠️ 法律問題 (侵犯版權) |

#### PubTator-MCP-Server (獨特功能)

| 項目 | 說明 |
|------|------|
| **Stars** | ⭐ 8 |
| **功能** | 生醫實體標註 (基因、疾病、藥物、物種) |
| **來源** | PubTator3 API (NCBI 官方) |
| **可學習** | ⭐⭐⭐ 實體識別功能 |

#### ClinicalTrials-MCP-Server

| 項目 | 說明 |
|------|------|
| **Stars** | ⭐ 13 |
| **功能** | 搜尋臨床試驗 |
| **來源** | ClinicalTrials.gov API (官方) |
| **可學習** | ⭐⭐ 臨床研究整合 |

#### paperscraper-MCP-Server (多來源)

| 項目 | 說明 |
|------|------|
| **功能** | 整合 PubMed, arXiv, bioRxiv, medRxiv, ChemRxiv |
| **特點** | 使用 paperscraper 套件 |
| **可學習** | ⭐⭐ 多來源整合參考 |

### JackKuo666 的設計模式

所有專案都遵循相同的模板：
- FastMCP 框架
- 極簡設計 (~200 行)
- Smithery 整合
- 多平台支援 (Claude, Cursor, Windsurf, CLine)

### 可學習的獨特功能

| 功能 | 來源專案 | 說明 | 可學習度 |
|------|---------|------|:--------:|
| **生醫實體標註** | PubTator-MCP | 基因、疾病、藥物識別 | ⭐⭐⭐ |
| **臨床試驗搜尋** | ClinicalTrials-MCP | 整合臨床研究 | ⭐⭐ |
| **DOI 查詢** | Crossref-MCP | 跨來源 ID 解析 | ⭐⭐ |
| **化學化合物** | PubChem-MCP | 藥物/化合物資訊 | ⭐ |
| **PDF 圖表提取** | pdffigures2-MCP | 論文圖表擷取 | ⭐⭐ |

### ⚠️ 風險專案

| 專案 | 風險 | 說明 |
|------|:----:|------|
| Google-Scholar-MCP | 🔴 高 | 爬蟲違反 ToS |
| Sci-Hub-MCP | 🔴 高 | 版權問題 |

---

## 5. Google-Scholar-MCP-Server (JackKuo666)

### 核心賣點

| 賣點 | 說明 | 風險 |
|------|------|:----:|
| **Google Scholar 存取** | 唯一能搜的方案 | ⚠️ 高 |
| **作者資訊** | 引用數、研究興趣 | ⚠️ 高 |
| **進階搜尋** | 作者 + 年份篩選 | ⚠️ 高 |

### ⚠️ 風險警告

```
❌ 使用網頁爬蟲，可能違反 Google ToS
❌ IP 容易被封鎖
❌ HTML 結構改變就壞掉
❌ 不建議生產環境使用
```

---

## 6. google-scholar-mcp (mochow13)

### 核心賣點

| 賣點 | 說明 | 可學習度 |
|------|------|:--------:|
| **TypeScript 實作** | 完整的 TS MCP Server | ⭐⭐ |
| **Streamable HTTP Transport** ⭐ | 支援 SSE 即時串流 | ⭐⭐⭐ |
| **Multi-session 支援** | 多用戶同時連線 | ⭐⭐⭐ |
| **Gemini 整合示範** | 完整的 AI Client 範例 | ⭐⭐ |
| **Smithery 整合** | 一鍵安裝 | ⭐⭐⭐ |
| **Docker 支援** | 容器化部署 | ⭐⭐ |

### 架構亮點

```
server/
├── src/
│   ├── index.ts              # Express server (端口可配置)
│   ├── server.ts             # MCPServer 類別 (session 管理)
│   ├── tools.ts              # Tool 定義 + 驗證
│   └── google-scholar-search.ts  # 爬蟲邏輯 (cheerio)
client/
└── index.ts                  # Gemini AI 整合範例
```

### Streamable HTTP Transport (值得學習)

```typescript
// 支援 POST (請求) + GET (SSE 串流)
router.post("/mcp", handlePostRequest);  // 主要通訊
router.get("/mcp", handleGetRequest);    // SSE 即時更新

// Session 管理
const SESSION_ID_HEADER_NAME = "mcp-session-id";
transports: { [sessionId: string]: StreamableHTTPServerTransport } = {};
```

### Multi-session 架構

```typescript
// 每個 client 有獨立 session
if (sessionId && this.transports[sessionId]) {
    transport = this.transports[sessionId];  // 複用現有連線
}

// 新連線自動分配 session ID
const transport = new StreamableHTTPServerTransport({
    sessionIdGenerator: () => randomUUID(),
});
```

### Tool 定義 (完整驗證)

```typescript
export const googleScholarTools = [{
    name: "search_google_scholar",
    description: "Search Google Scholar for academic papers...",
    inputSchema: {
        type: "object",
        properties: {
            query: { type: "string", description: "..." },
            numResults: { 
                type: "number", 
                minimum: 1, 
                maximum: 20,
                default: 10 
            },
            author: { type: "string", description: "Filter by author" },
            startYear: { type: "number", minimum: 1900 },
            endYear: { type: "number", maximum: 2025 }
        },
        required: ["query"]
    }
}]

// 完整的參數驗證
function validateSearchGoogleScholarArgs(args) {
    if (startYear > endYear) {
        throw new Error("Start year cannot be greater than end year");
    }
}
```

### Gemini Client 整合範例 (值得參考)

```typescript
class MCPClient {
    private mcp: Client;
    private genAI: GoogleGenAI;
    private conversationHistory: any[] = [];  // 對話歷史

    async processQuery(query: string) {
        // 1. 加入對話歷史
        this.conversationHistory.push({ role: "user", parts: [{ text: query }] });
        
        // 2. 轉換 MCP tools 為 Gemini function declarations
        const config = { tools: [{ functionDeclarations: this.tools }] };
        
        // 3. 呼叫 Gemini
        const response = await this.genAI.models.generateContent({
            model: "gemini-2.5-flash",
            contents: this.conversationHistory,
            config
        });
        
        // 4. 處理 function calls
        for (const toolCall of response.functionCalls) {
            const result = await this.mcp.callTool({
                name: toolCall.name,
                arguments: toolCall.args
            });
            // 加入對話歷史...
        }
    }
}
```

### 與 JackKuo666 比較

| 指標 | mochow13 | JackKuo666 |
|------|:--------:|:----------:|
| 語言 | TypeScript | Python |
| Transport | Streamable HTTP | stdio |
| Multi-session | ✅ | ❌ |
| AI 整合範例 | ✅ Gemini | ❌ |
| Docker | ✅ | ❌ |
| 爬蟲穩定性 | ⚠️ 相同風險 | ⚠️ 相同風險 |

### 可學習

| 功能 | 說明 |
|------|------|
| **Streamable HTTP** | 支援 SSE，比 stdio 更適合 web 部署 |
| **Session 管理** | 多用戶同時使用 |
| **參數驗證** | 完整的 inputSchema + validate |
| **AI Client 範例** | Gemini 整合參考 |

### ⚠️ 風險警告 (同 JackKuo666)

```
❌ 使用 cheerio 爬蟲，同樣違反 Google ToS 風險
❌ IP 封鎖風險
❌ 不建議生產環境
```

---

## 7. Scientific-Papers-MCP (benedict2310) ⭐⭐⭐ 重點專案

> **定位**: 最完整的多來源整合 MCP Server (TypeScript)
> **Stars**: ⭐ 31 | **Forks**: 5 | **npm**: `@futurelab-studio/latest-science-mcp`

### 核心賣點

| 賣點 | 說明 | 可學習度 |
|------|------|:--------:|
| **6 大學術資料庫整合** ⭐⭐⭐ | arXiv, OpenAlex, PMC, Europe PMC, bioRxiv/medRxiv, CORE | ⭐⭐⭐ |
| **全文提取 (>90% 成功率)** ⭐⭐⭐ | 智能 fallback + DOI 解析鏈 | ⭐⭐⭐ |
| **DOI 多重解析** ⭐⭐ | Unpaywall → Crossref → Semantic Scholar | ⭐⭐⭐ |
| **引用分析** | OpenAlex 的 top cited papers 查詢 | ⭐⭐ |
| **完整 TypeScript** | 類型安全 + ESM 模組 | ⭐⭐ |
| **Dual Interface** | MCP + CLI 雙介面 | ⭐⭐ |
| **npm 發布** | 一鍵安裝 `npx` | ⭐⭐⭐ |

### 資料來源覆蓋

| 來源 | 論文數 | 學科 | 全文 | 引用數據 | 預印本 |
|------|--------|------|:----:|:--------:|:------:|
| arXiv | 2.3M+ | STEM | ✅ HTML | 有限 | ✅ |
| OpenAlex | 200M+ | 全領域 | 不穩定 | ✅ 完整 | ✅ |
| PMC | 7M+ | 生醫 | ✅ XML/HTML | 有限 | ❌ |
| Europe PMC | 40M+ | 生命科學 | ✅ HTML | 有限 | ✅ |
| bioRxiv/medRxiv | 500K+ | 生醫 | ✅ HTML | 有限 | ✅✅✅ |
| CORE | 200M+ | 全領域 | ✅ PDF/HTML | 有限 | ✅ |

### 6 個 MCP Tools

```typescript
// 1. 列出來源的分類
list_categories(source: "arxiv" | "openalex" | "pmc" | "europepmc" | "biorxiv" | "core")

// 2. 取得最新論文 (metadata only)
fetch_latest(source, category, count)
// 範例: source="arxiv", category="cs.AI", count=10

// 3. 高引用論文 (OpenAlex only)
fetch_top_cited(concept, since, count)
// 範例: concept="machine learning", since="2024-01-01", count=20

// 4. 搜尋論文 (進階欄位搜尋)
search_papers(source, query, field, count, sortBy)
// field: "all" | "title" | "abstract" | "author" | "fulltext"
// sortBy: "relevance" | "date" | "citations"

// 5. 取得單篇全文
fetch_content(source, paper_id)
// 完整文字提取 + metadata

// 6. PDF 全文提取
fetch_pdf_content(url)
// 直接從 PDF URL 提取文字
```

### 全文提取策略 (最大亮點)

```typescript
// 每個來源有專屬提取策略
arXiv:       arxiv.org/html → ar5iv.labs.arxiv.org fallback
OpenAlex:    HTML sources → DOI resolver fallback chain
PMC:         E-utilities API → XML/HTML extraction
Europe PMC:  REST API → multiple URL strategies
bioRxiv:     Direct HTML → abstract fallback
CORE:        PDF/HTML → source URL fallback
```

### DOI 解析鏈 (高價值功能)

```typescript
// 三層 fallback 確保最高成功率
1. Unpaywall API  → 免費全文來源
2. Crossref API   → 出版商 metadata + DOIs
3. Semantic Scholar → 替代存取 URLs

// 24 小時 LRU 緩存，避免重複查詢
```

### Rate Limiting 設計

```typescript
// 每個來源獨立限速
arXiv:      5 req/min
OpenAlex:  10 req/min
PMC:        3 req/sec
Europe PMC: 10 req/min
bioRxiv:    5 req/min
CORE:      10 req/min (public), higher with API key
```

### Paper Metadata 格式

```typescript
interface PaperMetadata {
  id: string;                    // Paper ID
  title: string;                 // 標題
  authors: string[];             // 作者列表
  date: string;                  // ISO 格式日期
  pdf_url?: string;              // PDF 連結
  text: string;                  // 提取的全文
  textTruncated?: boolean;       // 文字被截斷警告 (6MB 限制)
  textExtractionFailed?: boolean; // 提取失敗警告
}
```

### 與其他專案比較

| 指標 | Scientific-Papers-MCP | paper-search-mcp | 我們 |
|------|:--------------------:|:----------------:|:----:|
| 語言 | TypeScript | Python | Python |
| 資料來源 | 6 個 | 8 個 | 1 個 (PubMed) |
| 全文提取 | ✅ 智能 fallback | ✅ PyPDF2 | ✅ PMC |
| MeSH 支援 | ❌ | ❌ | ✅ |
| PICO 解析 | ❌ | ❌ | ✅ |
| 引用分析 | ✅ OpenAlex | ⚠️ 有限 | ❌ |
| DOI 解析鏈 | ✅ 3 層 | ⚠️ CrossRef only | ❌ |
| CLI | ✅ | ✅ | ❌ |
| npm/PyPI | ✅ npm | ✅ PyPI | ⏳ |

### 可學習

| 功能 | 說明 | 優先度 |
|------|------|:------:|
| **DOI 解析鏈** | Unpaywall → Crossref → S2 三層 fallback | ⭐⭐⭐ |
| **全文提取策略** | 每個來源專屬 + 智能 fallback | ⭐⭐⭐ |
| **Top Cited 查詢** | OpenAlex 引用分析 | ⭐⭐ |
| **統一 Rate Limiter** | Token bucket + 每來源獨立 | ⭐⭐ |
| **TypeScript 架構** | Modular driver system | ⭐⭐ |
| **CLI 介面** | 同時支援 MCP + CLI | ⭐⭐ |

### 我們的競爭優勢 vs Scientific-Papers-MCP

```
✅ 我們: PubMed 專精，MeSH 支援完整
✅ 我們: PICO 解析 (系統性文獻回顧必備)
✅ 我們: ESpell 拼字校正
✅ 我們: ELink 相關文章推薦
✅ 我們: 搜尋策略生成 (Boolean query)
✅ 我們: DDD 架構 (更好的可維護性)

❌ 我們: 只有 1 個資料來源
❌ 我們: 沒有 DOI 解析功能
❌ 我們: 沒有引用分析
❌ 我們: 沒有 CLI 介面
```

### 結論

**Scientific-Papers-MCP 是目前最完整的學術論文 MCP**，特別是：
- 6 來源整合 + 統一介面
- 智能全文提取 (>90% 成功率)
- DOI 三層解析鏈
- 完整的 TypeScript 實作

**對我們的啟示**：
1. 如果要做多來源整合，這是最好的參考
2. DOI 解析鏈的設計非常值得學習
3. 全文提取的 fallback 策略很實用
4. 但我們在 PubMed 專精領域 (MeSH/PICO/ESpell) 仍有優勢

---

## 8. arxiv-mcp-server (blazickjp) ⭐⭐⭐ 最熱門專案

> **定位**: arXiv 專精 MCP Server + 研究分析 Prompts  
> **Stars**: ⭐ **1.9k** (最高！) | **Forks**: 145 | **PyPI**: `arxiv-mcp-server`  
> **獲獎**: Pulse MCP Top Pick

### 核心賣點

| 賣點 | 說明 | 可學習度 |
|------|------|:--------:|
| **最高 Star 數** ⭐⭐⭐ | 1.9k stars, 學術 MCP 最熱門 | 參考架構 |
| **研究分析 Prompts** ⭐⭐⭐ | 深度論文分析、文獻綜述、研究問題生成 | ⭐⭐⭐ |
| **PDF → Markdown 轉換** ⭐⭐ | 使用 pymupdf4llm 智能提取 | ⭐⭐ |
| **本地儲存 + 快取** | 下載後儲存，重複使用 | ⭐⭐ |
| **進階搜尋語法** | Boolean operators, field-specific | ⭐⭐ |
| **Smithery 整合** | 一鍵安裝 | ⭐⭐⭐ |
| **PyPI 發布** | `uv tool install arxiv-mcp-server` | ⭐⭐⭐ |

### 4 個 MCP Tools

```python
# 1. 搜尋論文 (進階語法)
search_papers(
    query="transformer architecture",  # 支援 ti:, au:, abs:, AND, OR, ANDNOT
    max_results=10,
    date_from="2023-01-01",
    date_to="2024-12-31",
    categories=["cs.AI", "cs.LG"],  # arXiv 分類
    sort_by="relevance"  # 或 "date"
)

# 2. 下載論文 (PDF → Markdown)
download_paper(paper_id="2401.12345")
# 下載 PDF，轉換為 Markdown，儲存到本地

# 3. 列出已下載論文
list_papers()
# 返回已下載論文的 metadata (title, summary, authors)

# 4. 讀取論文內容
read_paper(paper_id="2401.12345")
# 返回完整 Markdown 內容
```

### 進階搜尋語法 (最大亮點之一)

```python
# 欄位搜尋
ti:"reinforcement learning"    # 標題包含
au:"Hinton"                    # 作者搜尋
abs:"transformer"              # 摘要搜尋
cat:cs.AI                      # 分類篩選

# Boolean 組合
"deep learning" AND "neural networks"
"machine learning" ANDNOT "survey"  # 排除 survey
ti:"attention" AND abs:"transformer"

# 範例: 找 Hinton 的深度學習論文
au:"Hinton" AND "deep learning" categories:["cs.LG"]
```

### 研究分析 Prompts (獨家功能) ⭐⭐⭐

這是這個專案最獨特的功能：內建研究工作流程 Prompts

```python
# 深度論文分析
call_prompt("deep-paper-analysis", {"paper_id": "2401.12345"})

# Prompt 提供的分析結構:
# - Executive Summary
# - Research Context
# - Methodology Analysis
# - Results Evaluation
# - Practical & Theoretical Implications
# - Future Research Directions
# - Broader Impacts
```

### Deep Paper Analysis Prompt 內容 (值得學習)

```
<workflow-for-paper-analysis>
  <preparation>
    - First, use list_papers to check if downloaded
    - If not, use download_paper
    - Then use read_paper to get content
    - Use search_papers to find related papers
  </preparation>
  
  <comprehensive-analysis>
    - Executive Summary (2-3 sentences)
    - Main contribution
    - Main problem solved
    - Methodology
    - Main results
    - Conclusion
  </comprehensive-analysis>
  
  <research-context>
    - Research area
    - Key prior approaches and limitations
    - How this paper advances the field
  </research-context>
  
  <methodology-analysis>
    - Step-by-step breakdown
    - Key innovations
    - Theoretical foundations
    - Technical implementation details
    - Algorithmic complexity
  </methodology-analysis>
</workflow-for-paper-analysis>
```

### 其他 Prompts

```python
# 文獻綜述
call_prompt("literature-synthesis", {
    "paper_ids": "2401.12345,2401.67890",
    "synthesis_type": "comprehensive",  # themes/methods/timeline/gaps
    "domain": "computer_science"
})

# 研究問題生成
call_prompt("research-question", {
    "paper_ids": "2401.12345,2401.67890"
})

# 研究探索
call_prompt("research-discovery", {
    "topic": "multi-agent systems",
    "expertise_level": "intermediate",  # beginner/intermediate/expert
    "time_period": "2023-present",
    "domain": "computer_science"
})
```

### PDF → Markdown 轉換

```python
# 使用 pymupdf4llm
import pymupdf4llm

markdown = pymupdf4llm.to_markdown(
    paper_pdf_path, 
    show_progress=False
)

# 儲存到本地
async with aiofiles.open(paper_md_path, "w") as f:
    await f.write(markdown)
```

### 本地儲存策略

```python
# 預設儲存路徑
~/.arxiv-mcp-server/papers/

# Paper 檔案結構
papers/
├── 2401.12345.md    # 轉換後的 Markdown
├── 2401.67890.md
└── ...

# PDF 下載後自動刪除，只保留 Markdown
```

### 與其他專案比較

| 指標 | arxiv-mcp-server | Scientific-Papers | 我們 |
|------|:----------------:|:-----------------:|:----:|
| **Stars** | **1.9k** ⭐⭐⭐ | 31 | - |
| 語言 | Python | TypeScript | Python |
| 資料來源 | 1 (arXiv) | 6 | 1 (PubMed) |
| Tools | 4 | 6 | 8 |
| **Research Prompts** | ✅ ⭐⭐⭐ | ❌ | ❌ |
| **PDF→Markdown** | ✅ pymupdf4llm | ✅ 智能提取 | ⚠️ PMC only |
| 進階搜尋語法 | ✅ Boolean | ✅ field search | ✅ MeSH/PICO |
| 本地快取 | ✅ | ❌ | ❌ |
| Smithery | ✅ | ❌ | ❌ |
| PyPI | ✅ | ✅ npm | ⏳ |

### 可學習

| 功能 | 說明 | 優先度 |
|------|------|:------:|
| **Research Prompts** ⭐ | 深度分析、文獻綜述、研究問題生成 | ⭐⭐⭐ |
| **PDF→Markdown** | pymupdf4llm 智能轉換 | ⭐⭐ |
| **本地儲存策略** | 下載後快取，避免重複 | ⭐⭐ |
| **進階搜尋語法** | Boolean operators + field search | ⭐⭐ |
| **Smithery 整合** | 一鍵安裝體驗 | ⭐⭐⭐ |

### 我們的競爭優勢 vs arxiv-mcp-server

```
✅ 我們: PubMed 專精 (生醫領域)
✅ 我們: MeSH hierarchical search (醫學主題詞)
✅ 我們: PICO 解析 (系統性文獻回顧)
✅ 我們: ESpell 拼字校正
✅ 我們: 更多 Tools (8 vs 4)

❌ 我們: 沒有 Research Prompts
❌ 我們: 沒有 PDF→Markdown 智能轉換
❌ 我們: 沒有本地快取
❌ 我們: 沒有 Smithery/PyPI
```

### 結論

**arxiv-mcp-server 是目前最成功的學術 MCP** (1.9k stars!)

成功因素：
1. **聚焦單一來源 (arXiv)** — 做深做精
2. **Research Prompts** — 獨特價值，不只是 API wrapper
3. **完善的開發者體驗** — Smithery + PyPI + 文檔
4. **社群活躍** — 145 forks, 9 contributors

**對我們的核心啟示**：
1. ⭐ **Research Prompts 是關鍵差異化** — 我們應該為 PubMed 設計專屬 Prompts
   - 系統性文獻回顧 (Systematic Review)
   - 臨床問題分析 (Clinical Question)
   - 文獻品質評估 (Critical Appraisal)
2. ⭐ **單一來源做深比多來源淺更成功**
3. ⭐ **Smithery + PyPI 發布是必要的**

---

## 9. arxiv-paper-mcp (daheepk) - 輕量級架構參考

> **定位**: arXiv 輕量級 MCP Server (韓文介面)  
> **Stars**: ⭐ 8 | **PyPI**: `arxiv-paper-mcp`

### 核心賣點

| 賣點 | 說明 | 可學習度 |
|------|------|:--------:|
| **MCP Resources 架構** | 使用 `@mcp.resource()` 設計 URI-based 存取 | ⭐⭐ |
| **清晰的專案結構** | resources/, tools/, prompts/ 分離 | ⭐⭐ |
| **FastMCP 框架** | 極簡 MCP Server 實作 | ⭐⭐ |
| **Web Scraping** | 爬取 arXiv recent 頁面取得最新論文 | ⭐ |

### MCP Resources 設計 (值得參考)

```python
# 使用 URI-based 資源存取
@mcp.resource("arxiv://{category}")
def get_papers_by_category(category: str) -> str:
    """特定カテゴリーの最新arXiv論文を取得"""
    papers = utils.fetch_arxiv_papers(category)
    # ...

@mcp.resource("author://{name}")
def get_papers_by_author(name: str) -> str:
    """特定の著者のarXiv論文を取得"""
    # ...
```

### 4 個 Tools + 2 個 Prompts

```python
# Tools
scrape_recent_category_papers(category, max_results)  # 爬取 recent 頁面
search_papers(keyword, max_results)                   # 關鍵字搜尋
get_paper_info(paper_id)                              # 論文詳情
analyze_trends(category, days)                        # 趨勢分析 (mock data)

# Prompts
summarize_paper(paper_id)     # 論文摘要生成
compare_papers(id1, id2)      # 兩篇論文比較
```

### 與 arxiv-mcp-server (blazickjp) 比較

| 指標 | arxiv-paper-mcp | arxiv-mcp-server |
|------|:---------------:|:----------------:|
| **Stars** | 8 | **1.9k** |
| 語言 | Python | Python |
| 框架 | FastMCP | mcp.server |
| Tools | 4 | 4 |
| Prompts | 2 | 4+ (更完整) |
| Resources | ✅ URI-based | ❌ |
| PDF→Markdown | ❌ | ✅ pymupdf4llm |
| 本地快取 | ❌ | ✅ |
| 成熟度 | 基礎 | 生產級 |

### 可學習

| 功能 | 說明 | 優先度 |
|------|------|:------:|
| **MCP Resources** | `@mcp.resource("uri://{param}")` 設計模式 | ⭐⭐ |
| **專案結構** | resources/tools/prompts 分離 | ⭐⭐ |

### 結論

這是一個**學習型專案**，適合參考：
- MCP Resources 的 URI-based 設計
- FastMCP 框架的極簡用法
- 清晰的專案目錄結構

但功能和成熟度遠不及 arxiv-mcp-server (blazickjp)。

---

## 10. Google-Search-MCP-Server (mixelpixx) ⭐⭐ 研究綜合典範

> **定位**: Google 研究綜合 MCP Server (非學術專用，但研究功能完整)  
> **Stars**: ⭐ **175** | **Forks**: 52 | **Version**: v3.0.0  
> **GitHub**: https://github.com/mixelpixx/Google-Search-MCP-Server

### 核心賣點

| 賣點 | 說明 | 可學習度 |
|------|------|:--------:|
| **Agent-Based Synthesis** ⭐⭐⭐ | 利用現有 Claude 對話來綜合研究 (不需額外 API Key) | ⭐⭐⭐ |
| **Source Quality Assessment** ⭐⭐ | 自動評估來源權威性、新鮮度、可信度 | ⭐⭐⭐ |
| **Deduplication Service** ⭐⭐ | 智能去重 (~30% 重複移除率) | ⭐⭐ |
| **Research Depth Levels** ⭐⭐ | basic/intermediate/advanced 三層研究深度 | ⭐⭐⭐ |
| **Focus Area Analysis** | 可指定特定面向深入分析 | ⭐⭐ |
| **Content Extraction** | 網頁內容提取 (Markdown/HTML/Text) | ⭐⭐ |
| **Dual Transport** | stdio + HTTP 支援 | ⭐⭐ |

### 4 個 MCP Tools

```typescript
// 1. 進階 Google 搜尋 (品質評分 + 去重)
google_search({
  query: "docker security best practices",
  num_results: 10,           // 預設 5, 最多 10
  dateRestrict: "y1",        // 限制日期 (y1=過去一年, m6=六個月)
  site: "github.com",        // 限定網域
  language: "en",            // ISO 639-1 語言代碼
  exactTerms: "container",   // 精確詞組
  sort: "relevance"          // 或 "date"
})
// 返回: 品質評分結果 + 去重統計 + 來源分類

// 2. 單頁內容提取
extract_webpage_content({
  url: "https://kubernetes.io/docs/...",
  format: "markdown",        // markdown/html/text
  full_content: true,        // 完整內容
  max_length: 5000,          // 最大長度
  preview_length: 300        // 預覽長度
})
// 返回: 清理後內容 + metadata + 統計 + 快取資訊

// 3. 批次內容提取 (最多 5 URLs)
extract_multiple_webpages({
  urls: ["url1", "url2", "url3"],
  format: "markdown"
})

// 4. 研究綜合 ⭐ (最強功能)
research_topic({
  topic: "Kubernetes security",
  depth: "advanced",         // basic/intermediate/advanced
  num_sources: 8,            // 來源數量
  focus_areas: ["RBAC", "network policies", "pod security"]  // 特定面向
})
// 返回: Executive Summary, Key Findings, Common Themes,
//       Focus Area Analysis, Contradictions, Recommendations,
//       Quality Metrics, Source List
```

### Research Depth Levels (設計亮點)

| 深度 | 來源數 | 分析內容 | 用途 |
|------|:------:|---------|------|
| **basic** | 3 | 簡短總覽、3-5 個發現 | 快速比較、初步研究 |
| **intermediate** | 5 | 完整分析、5-7 個發現 | 標準研究任務 |
| **advanced** | 8-10 | 深度分析、7-10 個發現、矛盾點檢測 | 決策制定、全面審查 |

### 3 個 MCP Prompts

```typescript
// 1. 研究主題
prompt: "research-topic"
// 引導進行系統性研究

// 2. 來源比較
prompt: "compare-sources"
// 比較多個來源的觀點差異

// 3. 事實查核
prompt: "fact-check"
// 驗證資訊的準確性
```

### Agent-Based Synthesis (最大亮點)

```typescript
// 不需要額外 Anthropic API Key！
// 利用現有 Claude 對話來綜合分析

工作流程:
1. Research Gathering  → MCP server 搜尋 + 去重 + 排序
2. Content Extraction  → 從最佳來源提取完整內容
3. Agent Prompt Generation → 所有研究資料打包成結構化 prompt
4. Agent Launch → Claude 自動啟動 agent 分析
5. Synthesis → Agent 分析來源並生成綜合報告

好處:
✅ 不需額外 API Key (用現有 Claude 訂閱)
✅ 完整上下文 (Agent 可存取對話歷史)
✅ 透明過程 (即時看到分析過程)
```

### Source Quality Assessment (品質評估)

```typescript
// 自動評估來源品質
評估維度:
- Authority (權威性) - 域名、發布者
- Recency (新鮮度) - 發布日期
- Credibility (可信度) - 引用、認證

來源分類:
- academic    → 學術來源
- official    → 官方文檔
- news        → 新聞報導
- forums      → 論壇討論
- blogs       → 部落格
```

### 服務架構 (TypeScript)

```typescript
src/
├── google-search-v3.ts              # Main MCP server (v3)
├── services/
│   ├── google-search.service.ts     # Google Custom Search API
│   ├── content-extractor.service.ts # 網頁內容提取 (Mozilla Readability)
│   ├── source-quality.service.ts    # 來源品質評估
│   ├── deduplication.service.ts     # 去重服務
│   └── research-synthesis.service.ts # Agent-based 研究綜合
└── types.ts                         # TypeScript interfaces
```

### 效能指標

| 操作 | 時間 | 說明 |
|------|------|------|
| google_search | 1-2s | 含品質評分 + 去重 |
| extract_webpage_content | 2-3s | 每 URL |
| research_topic (basic) | 8-10s | 3 來源 + agent 綜合 |
| research_topic (intermediate) | 12-15s | 5 來源 + 完整分析 |
| research_topic (advanced) | 18-25s | 8-10 來源 + 深度分析 |

### v3 vs v2 改進

| 指標 | v2 | v3 | 提升 |
|------|:--:|:--:|:----:|
| Summary Quality | 2/10 | 9/10 | 350% |
| Source Diversity | 未追蹤 | 優化 | 新功能 |
| Duplicate Removal | 0% | ~30% | 新功能 |
| Source Ranking | 隨機 | 品質排序 | 新功能 |
| Focus Area Support | 通用 | 專屬分析 | 新功能 |

### 與其他專案比較

| 指標 | Google-Search-MCP | arxiv-mcp-server | 我們 |
|------|:-----------------:|:----------------:|:----:|
| **Stars** | **175** | **1.9k** | - |
| 語言 | TypeScript | Python | Python |
| 資料來源 | Google Search | arXiv | PubMed |
| **Agent Synthesis** | ✅ ⭐⭐⭐ | ❌ | ❌ |
| **Source Quality** | ✅ | ❌ | ❌ |
| **Deduplication** | ✅ | ❌ | ❌ |
| **Research Prompts** | ✅ 3 個 | ✅ 4+ 個 | ❌ |
| **Research Depth** | ✅ 3 層 | ❌ | ❌ |
| 學術專精 | ❌ 通用搜尋 | ✅ arXiv | ✅ PubMed |

### 可學習

| 功能 | 說明 | 優先度 |
|------|------|:------:|
| **Agent-Based Synthesis** ⭐ | 利用現有 Claude 對話綜合研究 | ⭐⭐⭐ |
| **Source Quality Assessment** | 自動評估來源品質 | ⭐⭐⭐ |
| **Deduplication Service** | 智能去重 | ⭐⭐ |
| **Research Depth Levels** | basic/intermediate/advanced 分層 | ⭐⭐⭐ |
| **Focus Area Analysis** | 指定特定面向深入分析 | ⭐⭐ |
| **Research Prompts** | fact-check, compare-sources | ⭐⭐ |

### 我們的競爭優勢 vs Google-Search-MCP

```
✅ 我們: PubMed 專精 (結構化醫學資料)
✅ 我們: MeSH hierarchical search
✅ 我們: PICO 解析 (系統性文獻回顧)
✅ 我們: ESpell 拼字校正
✅ 我們: 官方 API (穩定性高)

❌ 我們: 沒有 Agent-Based Synthesis
❌ 我們: 沒有 Source Quality 評估
❌ 我們: 沒有 Deduplication
❌ 我們: 沒有 Research Depth 分層
```

### 結論

**Google-Search-MCP-Server 是研究綜合功能的典範**，特別是：
- **Agent-Based Synthesis** — 不需額外 API Key，利用現有對話
- **Source Quality Assessment** — 自動評估來源品質
- **Research Depth Levels** — 三層研究深度設計

**對我們的啟示**：
1. ⭐ **Agent-Based Synthesis 是創新方向** — 利用現有 Claude 對話來綜合分析
2. ⭐ **Source Quality 評估可套用** — PubMed 來源品質評估 (期刊 IF、引用數、證據等級)
3. ⭐ **Research Depth Levels 設計優秀** — 可為系統性文獻回顧設計類似分層
4. Deduplication 對 PubMed 重複論文也有用

**注意**: 此專案非學術專用，但研究功能設計非常值得參考。

---

## 11. papersgpt-for-zotero (papersgpt) ⭐⭐⭐ Zotero AI 生態圈

> **定位**: Zotero AI 外掛 + MCP Server 雙重身份  
> **GitHub**: https://github.com/papersgpt/papersgpt-for-zotero  
> **Stars**: ⭐ 2,000+ | **Forks**: 66  
> **語言**: C++ (MCP Server), Zotero Plugin (JS)  
> **數據來源**: 本地 Zotero 文獻庫

### 核心賣點

| 賣點 | 說明 | 可學習度 |
|------|------|:--------:|
| **C++ MCP Server** | 極速響應，無需 Python/Node.js runtime | ⭐⭐ |
| **BM25 全文搜尋** | 標題、作者、標籤、摘要、筆記、註釋、收藏 | ⭐⭐⭐ |
| **5x PDF 讀取速度** | 100+ 頁文檔快速處理 | ⭐⭐ |
| **本地 RAG 架構** | embeddings + 向量數據庫 + rerank | ⭐⭐⭐ |
| **隱私安全** | 100% 本地處理，無數據洩漏，離線可用 | ⭐⭐ |
| **多 PDF 同時對話** | 跨多個文檔的智能問答 | ⭐⭐ |

### 技術架構

```
┌─────────────────────────────────────────────────────────────┐
│                    PapersGPT for Zotero                     │
├─────────────────────┬───────────────────────────────────────┤
│   Zotero Plugin     │           MCP Server (C++)            │
│   (UI + 整合)       │         SSE: localhost:9080           │
├─────────────────────┼───────────────────────────────────────┤
│                     │  ┌───────────────────────────────┐    │
│   多 LLM 支援       │  │  BM25 Full-Text Search       │    │
│   ─────────────     │  │  • Title, Author, Tags        │    │
│   • GPT-5.1        │  │  • Abstract, Notes            │    │
│   • Claude 4.5     │  │  • Annotations, Collections   │    │
│   • Gemini 3       │  └───────────────────────────────┘    │
│   • DeepSeek V3.2  │                                        │
│   • Grok 4         │  ┌───────────────────────────────┐    │
│   • Qwen3          │  │  Local RAG Pipeline           │    │
│                     │  │  • Embeddings (本地)          │    │
│   本地 LLM         │  │  • Vector DB                  │    │
│   ─────────────     │  │  • Rerank                     │    │
│   • Gemma 3        │  └───────────────────────────────┘    │
│   • Qwen 3         │                                        │
│   • DeepSeek Distill│  ┌───────────────────────────────┐    │
│   • Phi-4          │  │  PDF Processing (5x faster)   │    │
│   • Mistral 7b     │  │  • 100+ page docs             │    │
│   • Llama 3.1      │  │  • Multi-PDF chat             │    │
│                     │  └───────────────────────────────┘    │
└─────────────────────┴───────────────────────────────────────┘
```

### MCP Server 特點

**連接方式**:
```json
{
  "mcpServers": {
    "papersgpt": {
      "url": "http://localhost:9080/sse",
      "transport": "sse"
    }
  }
}
```

**搜尋能力 (BM25)**:
- 標題 (Title)
- 作者 (Author)  
- 標籤 (Tags)
- 摘要 (Abstract)
- 筆記 (Notes)
- 註釋 (Annotations)
- 收藏集 (Collections)

### 內建 Research Prompts

```
┌──────────────────────────────────────────────────────────┐
│                   研究分析 Prompts                        │
├──────────────────────────────────────────────────────────┤
│  📝 Summary              → 快速摘要                       │
│  📚 Background           → 背景介紹                       │
│  📖 Literature Review    → 文獻回顧                       │
│  🔬 Theoretical Frameworks → 理論框架分析                 │
│  🔮 Future Directions    → 未來研究方向                   │
└──────────────────────────────────────────────────────────┘
```

### 隱私與安全

| 特點 | 說明 |
|------|------|
| **100% 本地處理** | 所有數據在本機處理 |
| **無數據洩漏** | 不會傳送文獻到外部伺服器 |
| **離線可用** | 搭配本地 LLM 完全離線運行 |
| **本地 Embeddings** | 向量化在本地執行 |

### 支援的 LLM

**商業 LLM**:
- OpenAI GPT-5.1
- Anthropic Claude 4.5
- Google Gemini 3
- DeepSeek V3.2
- xAI Grok 4
- Alibaba Qwen3

**本地 LLM (一鍵運行)**:
- Google Gemma 3
- Alibaba Qwen 3
- DeepSeek Distill
- Microsoft Phi-4
- Mistral 7b
- Meta Llama 3.1
- Ollama 兼容

### 與我們的比較

```diff
✅ 我們: PubMed 專業搜尋 (MeSH、PICO、ESpell)
✅ 我們: 8 個專業 Tools
✅ 我們: 跨論文批次查詢

❌ 我們: 沒有 C++ MCP Server (極速響應)
❌ 我們: 沒有 BM25 全文搜尋
❌ 我們: 沒有本地 RAG 架構
❌ 我們: 沒有 Zotero 整合
❌ 我們: 沒有本地 LLM 支援
❌ 我們: 沒有 Research Prompts
```

### 結論

**papersgpt-for-zotero 是 Zotero 生態圈的標竿**，特別是：
- **C++ MCP Server** — 極速響應，無需 runtime
- **BM25 全文搜尋** — 深度搜尋文獻庫
- **本地 RAG** — 隱私安全，離線可用
- **Research Prompts** — 內建研究分析功能

**對我們的啟示**:
1. ⭐ **Research Prompts 必須有** — 這已是標配功能
2. ⭐ **BM25 搜尋可參考** — 對 PubMed 結果的本地二次搜尋
3. ⭐ **本地 RAG 是趨勢** — 隱私安全 + 離線能力
4. SSE Transport 是另一種連接方式選項
5. Zotero 整合是重要生態圈 (2k+ stars 證明需求)

**注意**: 這是 Zotero 外掛，不是獨立的學術搜尋 MCP，但其 MCP 架構設計非常值得參考。

---

## 12. zotero-mcp (54yyyu) ⭐⭐ 完整 Zotero MCP

> **定位**: Zotero 文獻庫 AI 助理 — 語義搜尋 + PDF 註釋  
> **GitHub**: https://github.com/54yyyu/zotero-mcp  
> **Stars**: ⭐ 751 | **Forks**: 71 | **Contributors**: 14  
> **語言**: Python 99.8%  
> **數據來源**: 本地 Zotero + Web API

### 核心賣點

| 賣點 | 說明 | 可學習度 |
|------|------|:--------:|
| **語義搜尋 (Embeddings)** | 多種嵌入模型: Default/OpenAI/Gemini | ⭐⭐⭐ |
| **PDF 註釋提取** | 直接處理 PDF 註釋 + 圖片註釋 | ⭐⭐⭐ |
| **雙重連接方式** | 本地 API + Web API | ⭐⭐ |
| **13 個專業 Tools** | 搜尋、內容、註釋、語義分類 | ⭐⭐⭐ |
| **Smithery 整合** | 一鍵安裝 | ⭐⭐⭐ |
| **智能更新系統** | 自動偵測安裝方式 + 保留配置 | ⭐⭐ |

### 完整 Tools 清單 (13 個)

**🧠 語義搜尋 (3)**:
```
zotero_semantic_search          # AI 相似度搜尋
zotero_update_search_database   # 更新語義數據庫
zotero_get_search_database_status # 檢查數據庫狀態
```

**🔍 搜尋 Tools (7)**:
```
zotero_search_items             # 關鍵字搜尋
zotero_advanced_search          # 複雜多條件搜尋
zotero_get_collections          # 列出收藏集
zotero_get_collection_items     # 獲取收藏集內容
zotero_get_tags                 # 列出所有標籤
zotero_get_recent               # 獲取最近新增
zotero_search_by_tag            # 標籤過濾搜尋
```

**📚 內容 Tools (3)**:
```
zotero_get_item_metadata        # 詳細 metadata + BibTeX 導出
zotero_get_item_fulltext        # 取得全文
zotero_get_item_children        # 取得附件和筆記
```

**📝 註釋 Tools (4)**:
```
zotero_get_annotations          # PDF 註釋提取
zotero_get_notes                # 獲取筆記
zotero_search_notes             # 搜尋筆記和註釋
zotero_create_note              # 建立新筆記 (beta)
```

### 語義搜尋架構

```
┌──────────────────────────────────────────────────────────┐
│                    Semantic Search                        │
├───────────────────┬───────────────────┬──────────────────┤
│  Default (Free)     │  OpenAI            │  Gemini           │
│  all-MiniLM-L6-v2   │  text-embedding-3- │  text-embedding-  │
│  本地運行           │  small/large       │  004              │
└───────────────────┴───────────────────┴──────────────────┘
                            │
                            ▼
              ┌───────────────────────────┐
              │  ChromaDB Vector Store   │
              │  • Metadata-only (快速)   │
              │  • Full-text (完整)      │
              └───────────────────────────┘
                            │
                            ▼
              ┌───────────────────────────┐
              │  更新排程                  │
              │  • Manual                │
              │  • Auto on startup       │
              │  • Daily                 │
              │  • Every N days          │
              └───────────────────────────┘
```

### PDF 註釋功能

| 功能 | 說明 |
|------|------|
| **直接 PDF 處理** | 即使 Zotero 未索引也能提取 |
| **註釋搜尋** | 搜尋 PDF 註釋和評論 |
| **圖片註釋** | 支援提取圖片註釋 |
| **Better BibTeX 整合** | 增強功能 + BibTeX 導出 |

### 連接方式

**本地連接 (推薦)**:
```json
{
  "mcpServers": {
    "zotero": {
      "command": "zotero-mcp",
      "env": {
        "ZOTERO_LOCAL": "true"
      }
    }
  }
}
```

**Web API 連接**:
```bash
zotero-mcp setup --no-local --api-key YOUR_KEY --library-id YOUR_ID
```

**Transport 選項**:
- stdio (預設)
- streamable-http
- sse

### CLI 功能

```bash
# 安裝和設定
uv tool install "git+https://github.com/54yyyu/zotero-mcp.git"
zotero-mcp setup           # 自動配置

# 語義搜尋數據庫
zotero-mcp update-db                    # 快速 (metadata-only)
zotero-mcp update-db --fulltext         # 完整 (全文)
zotero-mcp update-db --force-rebuild    # 重建
zotero-mcp db-status                    # 檢查狀態

# 更新
zotero-mcp update                       # 更新到最新版
zotero-mcp update --check-only          # 僅檢查
```

### 與我們的比較

```diff
✅ 我們: PubMed 專業搜尋 (MeSH、PICO、ESpell)
✅ 我們: 8 個專業 PubMed Tools
✅ 我們: 跨論文批次查詢

❌ 我們: 沒有語義搜尋 (Embeddings)
❌ 我們: 沒有 PDF 註釋提取
❌ 我們: 沒有 Zotero 整合
❌ 我們: 沒有多種 Embedding 模型選項
❌ 我們: 沒有 CLI + Smithery
❌ 我們: 沒有智能更新系統
```

### 結論

**zotero-mcp 是最完整的 Zotero MCP 實作**，特別是：
- **多種 Embedding 模型** — Free/OpenAI/Gemini 三選
- **13 個專業 Tools** — 完整覆蓋 Zotero 功能
- **PDF 註釋提取** — 直接處理 PDF 檔案
- **CLI + Smithery** — 完整的安裝/更新體驗

**對我們的啟示**:
1. ⭐ **語義搜尋是重要趨勢** — 多種 Embedding 模型選項
2. ⭐ **PDF 註釋提取很實用** — 可考慮加入 PMC 全文註釋
3. ⭐ **CLI 體驗很重要** — 安裝/設定/更新一條龍
4. ChromaDB 是常用的向量資料庫選擇
5. 數據庫更新排程是好設計 (manual/startup/daily/N days)

**注意**: 這是 Zotero 專用 MCP，不整合外部學術數據庫。

---

## 13. pubmearch (Darkroaster) 💥 直接競品

> **定位**: PubMed 熱點分析 + 趨勢追蹤 MCP  
> **GitHub**: https://github.com/Darkroaster/pubmearch  
> **Stars**: ⭐ 142 | **Forks**: 25  
> **語言**: Python 100%  
> **數據來源**: PubMed (通過 Entrez API)

### 核心賣點

| 賣點 | 說明 | 可學習度 |
|------|------|:--------:|
| **研究熱點分析** | 統計關鍵字頻率，識別熱門方向 | ⭐⭐⭐ |
| **趨勢追蹤** | 追蹤關鍵字隨時間變化 | ⭐⭐⭐ |
| **發文數量分析** | 靈活時間週期設定 | ⭐⭐ |
| **綜合報告生成** | 一鍵生成完整分析報告 | ⭐⭐⭐ |
| **高級檢索語法** | 支援 PubMed 高級檢索語法 | ⭐⭐ |

### Tools 清單 (5 個)

```
search_pubmed                    # PubMed 搜尋 + 儲存結果
list_result_files                # 列出結果檔案
analyze_research_keywords        # 研究熱點 + 趨勢分析
analyze_publication_count        # 發文數量分析
generate_comprehensive_analysis  # 綜合報告生成
```

### 工作流程

```
1. search_pubmed           → 搜尋並儲存結果檔
                           │
2. analyze_research_keywords ← 分析儲存的結果
   analyze_publication_count│
                           │
3. generate_comprehensive_analysis → 綜合報告
```

### 與我們的比較

```diff
✅ 我們: MeSH 詞彙整合 (mesh_lookup)
✅ 我們: PICO 結構化查詢
✅ 我們: 拼寫糾正 (espell)
✅ 我們: 跨論文批次查詢
✅ 我們: 8 個專業 Tools (vs 5 個)

❌ 我們: 沒有熱點/趨勢分析
❌ 我們: 沒有綜合報告生成
❌ 我們: 沒有發文數量統計
```

### 結論

**pubmearch 專注於研究趨勢分析**，而不是搜尋功能。這是一個很好的差異化方向！

**對我們的啟示**:
1. ⭐ **熱點分析是獨特賣點** — 我們可以考慮加入
2. ⭐ **趨勢追蹤很實用** — 研究方向演變分析
3. ⭐ **綜合報告生成** — 一鍵生成完整分析
4. 結果檔儲存機制可參考

**差異化**: 我們專注「精準搜尋」，他們專注「趨勢分析」。可以共存。

---

## 14. mcp-simple-pubmed (andybrandt) 💥 直接競品

> **定位**: PubMed 輕量版 MCP + 全文取得  
> **GitHub**: https://github.com/andybrandt/mcp-simple-pubmed  
> **Stars**: ⭐ 142 | **Forks**: 34 | **Contributors**: 6  
> **語言**: Python 98.8%  
> **數據來源**: PubMed (通過 Entrez API)

### 核心賣點

| 賣點 | 說明 | 可學習度 |
|------|------|:--------:|
| **輕量簡潔** | 只做三件事: 搜尋、摘要、全文 | ⭐⭐ |
| **XML 全文輸出** | AI 可理解文檔結構 | ⭐⭐ |
| **Smithery 整合** | 一鍵安裝 | ⭐⭐⭐ |
| **MseeP 認證** | 第三方安全認證 | ⭐ |
| **PyPI 發布** | pip install mcp-simple-pubmed | ⭐⭐⭐ |

### 功能簡單但定位清晰

```
┌────────────────────────────────────────┐
│           mcp-simple-pubmed               │
├─────────────┬─────────────┬─────────────┤
│   Search    │   Abstract  │  Full Text  │
│   關鍵字搜尋  │   摘要取得  │  全文取得   │
│             │             │  (Open     │
│             │             │   Access)  │
└─────────────┴─────────────┴─────────────┘
```

### 與我們的比較

```diff
✅ 我們: MeSH 詞彙整合 (mesh_lookup)
✅ 我們: PICO 結構化查詢
✅ 我們: 拼寫糾正 (espell)
✅ 我們: 跨論文批次查詢
✅ 我們: Citation 查詢 (elink)
✅ 我們: 8 個專業 Tools
✅ 我們: DDD 架構模組化

❌ 我們: 沒有 Smithery
❌ 我們: 沒有 PyPI 發布
~ 兩者: 都支援全文取得 (Open Access)
```

### 結論

**mcp-simple-pubmed 是極簡主義典範** — 只做三件事但做得很好。

**對我們的啟示**:
1. ⭐ **Smithery + PyPI 很重要** — 降低使用門檻
2. ⭐ **XML 全文格式** — AI 可理解文檔結構
3. MseeP 認證是新的信任標誌
4. 「輕量」本身就是賣點

**差異化**: 我們是「專業版」，他們是「簡易版」。定位不衝突。

---

## 15. BioMCP (genomoncology) ⭐⭐⭐ 生醫全局型

> **定位**: 生醫領域全局型 MCP — 多數據源 + 統一查詢語言  
> **GitHub**: https://github.com/genomoncology/biomcp  
> **Stars**: ⭐ 367 | **Forks**: 67 | **Contributors**: 9  
> **語言**: Python 95.2%  
> **網站**: https://biomcp.org/  
> **數據來源**: 10+ 個生醫資料庫

### 核心賣點

| 賣點 | 說明 | 可學習度 |
|------|------|:--------:|
| **24 個專業 Tools** | 3 Core + 21 Individual | ⭐⭐⭐ |
| **10+ 數據來源** | PubMed + ClinicalTrials + MyVariant + OncoKB... | ⭐⭐⭐ |
| **統一查詢語言** | gene:BRAF AND trials.condition:melanoma | ⭐⭐⭐ |
| **Think Tool** | 強制順序思考 (ALWAYS USE FIRST) | ⭐⭐ |
| **多 Transport** | STDIO, SSE, Streamable HTTP | ⭐⭐ |
| **MCPHub 認證** | 第三方最佳實踐認證 | ⭐⭐ |
| **企業版 OncoMCP** | HIPAA + EHR 整合 | - |

### 數據來源全景

```
┌─────────────────────────────────────────────────────────────┐
│                         BioMCP                               │
├────────────────────┬────────────────────┬───────────────────┤
│  📚 Literature       │  🏥 Clinical         │  🧬 Genomic        │
├────────────────────┼────────────────────┼───────────────────┤
│  • PubTator3/PubMed │  • ClinicalTrials  │  • MyVariant.info │
│  • bioRxiv/medRxiv  │  • NCI CTS API     │  • MyGene.info    │
│  • Europe PMC      │  • OpenFDA         │  • MyDisease.info │
│                    │                    │  • MyChem.info    │
│                    │                    │  • cBioPortal     │
│                    │                    │  • OncoKB         │
│                    │                    │  • TCGA/GDC       │
│                    │                    │  • 1000 Genomes   │
└────────────────────┴────────────────────┴───────────────────┘
```

### Tools 架構 (24 個)

**Core Tools (3)** — 基本操作:
```
think     # 順序思考 (ALWAYS USE FIRST!)
search    # 統一搜尋 (query 或 domain 模式)
fetch     # 取得詳細資料
```

**Individual Tools (21)**:
- Article (2): article_searcher, article_getter
- Trial (5): trial_searcher, trial_getter, trial_protocol/references/outcomes/locations_getter
- Variant (2): variant_searcher, variant_getter
- NCI (6): nci_organization/intervention/biomarker/disease_searcher/getter
- BioThings (3): gene_getter, disease_getter, drug_getter

### 統一查詢語言 (Unified Query Language)

```python
# 簡單自然語言
search(query="BRAF melanoma")

# 欄位特定搜尋
search(query="gene:BRAF AND trials.condition:melanoma")

# 複雜查詢
search(query="gene:BRAF AND variants.significance:pathogenic AND articles.date:>2023")

# 取得 schema
search(get_schema=True)

# 解釋查詢
search(query="gene:BRAF", explain_query=True)
```

**支援欄位**:
- 跨域: `gene:`, `variant:`, `disease:`
- 試驗: `trials.condition:`, `trials.phase:`, `trials.status:`
- 文章: `articles.author:`, `articles.journal:`, `articles.date:`
- 變異: `variants.significance:`, `variants.rsid:`, `variants.frequency:`

### Think Tool 設計

```python
# 強制第一步: 順序思考
think(
    thought="Breaking down the query about BRAF mutations in melanoma...",
    thoughtNumber=1,
    totalThoughts=3,
    nextThoughtNeeded=True
)
```

這是很獨特的設計 — 強制 AI 先思考再行動！

### 與我們的比較

```diff
✅ 我們: PubMed 專精 (MeSH, PICO, ESpell)
✅ 我們: DDD 架構模組化

❌ 我們: 沒有多數據源整合 (ClinicalTrials, MyVariant...)
❌ 我們: 沒有統一查詢語言
❌ 我們: 沒有 Think Tool
❌ 我們: 沒有 Streamable HTTP Transport
❌ 我們: 沒有企業版支援
❌ 我們: Tools 數量 (8 vs 24)
```

### 結論

**BioMCP 是生醫領域最完整的 MCP 實作**，是「大型學術 MCP」的標框！

**亮點**:
- **統一查詢語言** — 我們的 Tool Router 構想的另一種實作
- **Think Tool** — 強制順序思考的創新設計
- **企業版 OncoMCP** — HIPAA + EHR 整合的商業化路線

**對我們的啟示**:
1. ⭐⭐⭐ **統一查詢語言是答案** — 不需要 Tool Router，用 Query Language
2. ⭐⭐ **Think Tool 設計很創新** — 強制 AI 先思考
3. ⭐⭐ **多數據源整合** — 它們做到了 10+ 個
4. ⭐ **企業版是可行的** — 開源 + 企業版共存
5. MCPHub/Smithery 認證是信任標誌

**重要**: BioMCP 是我們「大型學術 MCP」構想的最佳參考！

---

## 16. pubmedmcp (grll) 💥 直接競品

> **定位**: PubMed 極簡版 MCP  
> **GitHub**: https://github.com/grll/pubmedmcp  
> **Stars**: ⭐ 84 | **Forks**: 16  
> **語言**: Python 100%  
> **數據來源**: PubMed (通過 pubmedclient 庫)

### 核心賣點

| 賣點 | 說明 | 可學習度 |
|------|------|:--------:|
| **uvx 一鍵運行** | `uvx pubmedmcp@latest` 即可 | ⭐⭐⭐ |
| **極度輕量** | 依賴 pubmedclient 庫 | ⭐⭐ |
| **零配置** | 不需要 API Key | ⭐⭐⭐ |
| **PyPI 發布** | 版本管理完善 (v0.1.4) | ⭐⭐⭐ |

### 使用方式

```json
{
  "mcpServers": {
    "pubmedmcp": {
      "command": "uvx",
      "args": ["pubmedmcp@latest"],
      "env": {
        "UV_PRERELEASE": "allow",
        "UV_PYTHON": "3.12"
      }
    }
  }
}
```

### 與我們的比較

```diff
✅ 我們: MeSH 詞彙整合 (mesh_lookup)
✅ 我們: PICO 結構化查詢
✅ 我們: 拼寫糾正 (espell)
✅ 我們: 跨論文批次查詢
✅ 我們: Citation 查詢 (elink)
✅ 我們: 8 個專業 Tools

❌ 我們: 沒有 uvx 一鍵運行
❌ 我們: 沒有 PyPI 發布
```

### 結論

**pubmedmcp 是「Hello World」等級的簡潔實作**。

**對我們的啟示**:
1. ⭐ **uvx 是最簡便的部署方式** — 用戶零配置
2. ⭐ **依賴現有庫** — pubmedclient 庫處理底層
3. 「極簡」本身就是賣點

**差異化**: 我們是「專業版」，它是「入門版」。定位不衝突。

---

## 17. pubmed-mcp-server (cyanheads) 💥 直接競品 ⭐

> **定位**: PubMed 專業版 MCP (TypeScript) — 圖表 + 研究計劃  
> **GitHub**: https://github.com/cyanheads/pubmed-mcp-server  
> **Stars**: ⭐ 36 | **Forks**: 13  
> **語言**: TypeScript 91.2%  
> **NPM**: @cyanheads/pubmed-mcp-server  
> **數據來源**: PubMed (通過 NCBI E-utilities)

### 核心賣點

| 賣點 | 說明 | 可學習度 |
|------|------|:--------:|
| **圖表生成** | PNG 圖表 (bar, line, scatter, pie, bubble, radar) | ⭐⭐⭐ |
| **研究計劃生成** | 結構化 JSON 研究計劃 | ⭐⭐⭐ |
| **引用網絡分析** | cited by, similar, references | ⭐⭐⭐ |
| **多種輸出格式** | JSON, MEDLINE, XML, RIS, BibTeX, APA, MLA | ⭐⭐ |
| **HTTP Transport** | 支援 STDIO + HTTP | ⭐⭐ |
| **企業級架構** | mcp-ts-template 基礎, JWT/OAuth | ⭐ |
| **NPM 發布** | npx @cyanheads/pubmed-mcp-server | ⭐⭐⭐ |

### Tools 清單 (5 個)

```
pubmed_search_articles      # 搜尋文章 (查詢 + 日期範圍 + 排序)
pubmed_fetch_contents       # 取得詳細資料 (metadata + MeSH + Grant)
pubmed_article_connections  # 引用網絡 (cited by, similar, references)
pubmed_research_agent       # 生成研究計劃 JSON
pubmed_generate_chart       # 生成圖表 (PNG)
```

### 圖表生成功能

```
┌───────────────────────────────────────────────────┐
│              pubmed_generate_chart               │
├──────────┬─────────┬──────────┬─────────┬─────────┤
│   Bar    │  Line   │ Scatter  │   Pie   │ Bubble  │
├──────────┴─────────┼──────────┴─────────┼─────────┤
│          Radar          │       PolarArea       │
└─────────────────────────┴─────────────────────────┘
                      輸出 PNG 檔案
```

### 企業級架構

**基於 mcp-ts-template**:
- 結構化 Logging (輪替 + JSON + MCP notifications)
- 集中式錯誤處理 (McpError)
- Zod Schema 驗證
- JWT/OAuth 認證
- Request Context (AsyncLocalStorage)
- Docker 部署支援

### 與我們的比較

```diff
✅ 我們: MeSH 詞彙整合 (mesh_lookup)
✅ 我們: PICO 結構化查詢
✅ 我們: 拼寫糾正 (espell)
✅ 我們: Python (vs TypeScript)
✅ 我們: DDD 架構模組化

❌ 我們: 沒有圖表生成功能
❌ 我們: 沒有研究計劃生成
❌ 我們: 沒有引用網絡分析 (cited by, similar)
❌ 我們: 沒有多種輸出格式 (RIS, BibTeX, APA)
❌ 我們: 沒有 HTTP Transport
❌ 我們: 沒有 NPM 發布
```

### 結論

**pubmed-mcp-server 是 TypeScript 生態的最完整 PubMed MCP**！

**亮點**:
- **圖表生成** — 獨特功能，其他競品沒有
- **研究計劃生成** — AI 研究助理的重要功能
- **企業級架構** — JWT/OAuth + 完整 logging

**對我們的啟示**:
1. ⭐⭐⭐ **圖表生成是獨特賣點** — 研究趨勢可視化
2. ⭐⭐⭐ **研究計劃生成** — AI 研究助理的方向
3. ⭐⭐ **引用網絡分析** — cited by, similar, references
4. ⭐⭐ **多種輸出格式** — RIS, BibTeX, APA, MLA
5. ⭐ **HTTP Transport** — 除了 STDIO 還支援 HTTP

**重要**: 這是功能最豐富的 PubMed 直接競品，很多功能值得參考！

---

# 功能清單 (可學習)

## 高優先 ⭐⭐⭐

| 功能 | 來源 | 說明 | 實作難度 |
|------|------|------|:--------:|
| **Research Prompts** ⭐⭐⭐ | arxiv-mcp-server, papersgpt | 深度分析、文獻綜述、研究問題生成 | 中 |
| **圖表生成** ⭐⭐⭐ | pubmed-mcp-server | PNG 圖表 (bar, line, scatter, pie, bubble, radar) | 中 |
| **研究計劃生成** ⭐⭐⭐ | pubmed-mcp-server | 結構化 JSON 研究計劃 | 中 |
| **引用網絡分析** ⭐⭐ | pubmed-mcp-server | cited by, similar, references | 中 |
| **統一查詢語言** ⭐⭐⭐ | BioMCP | gene:BRAF AND trials.condition:melanoma | 中 |
| **研究熱點分析** ⭐⭐⭐ | pubmearch | 關鍵字頻率統計 + 趨勢追蹤 | 中 |
| **Think Tool** ⭐⭐ | BioMCP | 強制順序思考 (ALWAYS USE FIRST) | 低 |
| **Agent-Based Synthesis** ⭐⭐⭐ | Google-Search-MCP | 利用現有 Claude 對話綜合研究 | 中 |
| **BM25 全文搜尋** ⭐⭐⭐ | papersgpt-for-zotero | 標題、作者、標籤、摘要、筆記搜尋 | 中 |
| **本地 RAG 架構** ⭐⭐ | papersgpt-for-zotero | embeddings + 向量 DB + rerank | 高 |
| **語義搜尋 (Embeddings)** ⭐⭐ | zotero-mcp | 多種嵌入模型 + ChromaDB | 高 |
| **PDF 註釋提取** ⭐⭐ | zotero-mcp | 直接處理 PDF 註釋 + 圖片 | 中 |
| **Source Quality Assessment** ⭐⭐ | Google-Search-MCP | 評估來源品質 (期刊 IF、證據等級) | 中 |
| **Research Depth Levels** ⭐⭐ | Google-Search-MCP | basic/intermediate/advanced 三層深度 | 低 |
| **PDF→Markdown 轉換** ⭐ | arxiv-mcp-server | pymupdf4llm 智能轉換 | 中 |
| **本地論文快取** | arxiv-mcp-server | 下載後儲存，避免重複 | 低 |
| **DOI 三層解析鏈** ⭐ | Scientific-Papers-MCP | Unpaywall → Crossref → S2 fallback | 中 |
| **智能全文提取** ⭐ | Scientific-Papers-MCP | 每來源專屬策略 + fallback | 中 |
| **推薦系統 (正/負例)** | Semantic Scholar | 給論文找類似的，排除不要的 | 中 |
| **PMID/PMCID 跨來源查詢** | Semantic Scholar | 用 PubMed ID 查 Semantic Scholar | 低 |
| **生醫實體標註** | JackKuo666/PubTator | 基因、疾病、藥物識別 (PubTator3) | 中 |
| **Smithery 整合** | arxiv-mcp, paper-search | 一鍵安裝 | 低 |
| **PyPI 發布** | arxiv-mcp, paper-search | pip install | 低 |
| **Streamable HTTP Transport** | mochow13, papersgpt | 支援 SSE + 多 session | 中 |
| **C++ MCP Server** | papersgpt-for-zotero | 極速響應，無需 Python/Node | 高 |

## 中優先 ⭐⭐

| 功能 | 來源 | 說明 | 實作難度 |
|------|------|------|:--------:|
| **Deduplication Service** | Google-Search-MCP | 智能去重 (~30% 移除率) | 低 |
| **Focus Area Analysis** | Google-Search-MCP | 指定特定面向深入分析 | 低 |
| **Content Extraction** | Google-Search-MCP | 網頁內容提取 (Markdown/HTML) | 中 |
| **進階搜尋語法** | arxiv-mcp-server | Boolean operators + field search | 低 |
| **Top Cited 查詢** | Scientific-Papers-MCP | OpenAlex 引用分析 | 中 |
| **統一 Rate Limiter** | Scientific-Papers-MCP | Token bucket + 每來源獨立 | 低 |
| **CLI 介面** | Scientific-Papers-MCP | 同時支援 MCP + CLI | 中 |
| **TLDR 摘要** | Semantic Scholar | AI 生成摘要 | 中 |
| **引用數篩選** | Semantic Scholar | min_citation_count | 低 |
| **參考文獻列表** | Semantic Scholar | 取得 references | 中 |
| **有影響力引用** | Semantic Scholar | influential citation count | 中 |
| **PDF 文字提取** | paper-search | PyPDF2 讀取 | 中 |
| **Multi-session 支援** | mochow13 | 多用戶同時連線 | 中 |
| **完整參數驗證** | mochow13 | inputSchema + validate | 低 |

## 低優先 ⭐

| 功能 | 來源 | 說明 | 實作難度 |
|------|------|------|:--------:|
| **6 來源整合** | Scientific-Papers-MCP | arXiv, OpenAlex, PMC, EuropePMC, bioRxiv, CORE | 高 |
| **作者分析** | Semantic Scholar | h-index, 論文列表 | 高 |
| **arXiv 整合** | paper-search, JackKuo666, Scientific-Papers | 預印本搜尋 | 中 |
| **bioRxiv/medRxiv** | paper-search, Scientific-Papers | 生醫預印本 | 中 |
| **臨床試驗搜尋** | JackKuo666/ClinicalTrials | ClinicalTrials.gov | 中 |
| **DOI 查詢** | JackKuo666/Crossref | 跨來源 ID 解析 | 低 |
| **PDF 圖表提取** | JackKuo666/pdffigures2 | 論文圖表擷取 | 高 |

## 可嘗試但有風險 ⚠️

| 功能 | 來源 | 風險 |
|------|------|------|
| **Google Scholar 搜尋** | JackKuo666, mochow13 | 爬蟲違反 ToS、IP 封鎖 |
| **Sci-Hub PDF 下載** | JackKuo666/Sci-Hub | 🔴 版權/法律問題 |

---

# 大型學術 MCP 構想

## 願景

> 一個 MCP Server 整合所有學術資料來源，內建 Tool Router 智能分派

## 可能架構

```
academic-mcp/
├── router/
│   ├── intent_classifier.py   # 判斷用戶意圖
│   └── source_selector.py     # 選擇最佳資料來源
├── sources/
│   ├── pubmed/                # 深度整合
│   ├── semantic_scholar/      # 引用 + 推薦
│   ├── arxiv/                 # 預印本
│   ├── biorxiv/
│   ├── crossref/              # DOI 查詢
│   └── google_scholar/        # 爬蟲 (可選)
└── tools/
    ├── search.py              # 統一搜尋介面
    ├── recommend.py           # 論文推薦
    ├── citation.py            # 引用分析
    └── author.py              # 作者分析
```

## 潛在優勢

| 優勢 | 說明 |
|------|------|
| **統一介面** | 一個 search tool，自動選來源 |
| **跨來源聚合** | 合併 PubMed + Semantic Scholar 結果 |
| **智能路由** | 醫學問題 → PubMed，CS 問題 → arXiv |
| **減少 Tools** | 不用 32+ tools，只需 8-10 個 |

## 風險與挑戰

| 風險 | 嚴重度 | 說明 | 緩解方案 |
|------|:------:|------|---------|
| **複雜度爆炸** | 🔴 高 | 多來源維護成本高 | 漸進式加入，先做 2-3 個 |
| **Rate Limiting** | 🔴 高 | 每個 API 限制不同 | 統一排程器 + 緩存 |
| **資料格式不一** | 🟡 中 | 每個來源返回不同 | 統一 Paper 模型 |
| **錯誤處理** | 🟡 中 | 部分來源失敗怎麼辦 | 降級策略 + 重試 |
| **爬蟲風險** | 🔴 高 | Google Scholar 無 API | 不整合或標註風險 |
| **Tool Router 準確度** | 🟡 中 | 選錯來源怎麼辦 | 允許用戶指定來源 |
| **維護成本** | 🟡 中 | 5+ 個 API 要追蹤 | 自動化測試 + 監控 |

## 建議路線

### Phase 1: 深化 PubMed (目前)
- ✅ 完成 DDD 重構
- ⏳ 加入 Clinical Query
- ⏳ PyPI 發布

### Phase 2: 加入 Semantic Scholar
- 推薦系統 (正/負例)
- PMID 跨來源查詢
- TLDR 摘要

### Phase 3: 評估多來源
- 先做 arXiv (官方 API 穩定)
- 考慮 CrossRef (DOI 查詢)
- 暫不做 Google Scholar (風險高)

### Phase 4: Tool Router (可選)
- 等 Phase 2-3 穩定後再考慮
- 先用簡單規則，再用 LLM 分類

---

# 更新日誌

| 日期 | 更新內容 |
|------|---------|
| 2024-12-04 | 初始版本，分析 4 個競品 |
| 2024-12-04 | 精簡為「賣點分析」格式，加入大型 MCP 構想 |
| 2024-12-04 | 新增 google-scholar-mcp (mochow13) - TypeScript 版 |
| 2024-12-04 | 整理 JackKuo666 完整專案系列 (15+ 個 MCP) |
| 2024-12-04 | 詳細分析 JackKuo666/PubMed-MCP-Server (直接競品) |
| 2024-12-04 | 新增 Scientific-Papers-MCP (benedict2310) - 最完整的多來源 MCP |
| 2024-12-04 | 新增 arxiv-mcp-server (blazickjp) - 最熱門 MCP Server (1.9k stars!) |
| 2024-12-04 | 新增 arxiv-paper-mcp (daheepk) - MCP Resources 架構參考 |
| 2024-12-04 | 新增 Google-Search-MCP-Server (mixelpixx) ⭐175 - Agent-Based Synthesis + Source Quality |
| 2024-12-05 | 新增 papersgpt-for-zotero ⭐2k - C++ MCP + BM25 全文搜尋 + 本地 RAG |
| 2024-12-05 | 新增 zotero-mcp (54yyyu) ⭐751 - 語義搜尋 + PDF 註釋 + 13 Tools |
| 2024-12-05 | 新增 pubmearch (Darkroaster) ⭐142 - PubMed 熱點分析 + 趨勢追蹤 (直接競品) |
| 2024-12-05 | 新增 mcp-simple-pubmed (andybrandt) ⭐142 - PubMed 輕量版 + Smithery (直接競品) |
| 2024-12-05 | 新增 BioMCP (genomoncology) ⭐367 - 生醫全局型 (24 Tools + 10 數據源 + 統一查詢語言) |
| 2024-12-05 | 新增 pubmedmcp (grll) ⭐84 - PubMed 極簡版 + uvx 一鍵運行 (直接競品) |
| 2024-12-05 | 新增 pubmed-mcp-server (cyanheads) ⭐36 - TypeScript + 圖表生成 + 研究計劃 (直接競品) |
| 2025-01-28 | 新增 第二批 4 個 repos：suppr-mcp, findpapers, EasyPubMed, paperscraper |
| 2026-02-10 | 🔥 大規模星星更新：paper-search-mcp 469→643, BioMCP 367→413, cyanheads 36→52 |
| 2026-02-10 | 新增 paper-search-mcp-nodejs (Dianel555) ⭐91 — 14 學術平台 MCP |
| 2026-02-10 | 新增 healthcare-mcp-public (Cicatriiz) ⭐87 — 醫療健康 MCP |
| 2026-02-10 | suppr-mcp 星星更新 → 247★，重新評估定位 |

---

## 📊 第二批分析（用戶指定 repos - 2025-01）

### 1. WildDataX/suppr-mcp ⭐???

**類型**: MCP Server (商業服務)
**語言**: TypeScript/Node.js

**重要發現**：
- ⚠️ **這是商業付費服務** - 需要 API Key，不是開源工具
- 底層服務是「超能文獻 Suppr」（suppr.wilddata.cn）
- 主要功能：翻譯 + AI 語義搜尋

**Tools 清單**:
| Tool | 功能 |
|------|------|
| `create_translation` | 創建文檔翻譯任務 |
| `get_translation` | 獲取翻譯結果 |
| `list_translations` | 列出翻譯歷史 |
| `search_documents` | PubMed 語義搜尋 |

**技術特點**:
```typescript
// 主要返回欄位
interface PubMedResult {
  pmid: string;
  doi: string;
  title: string;
  abstract: string;
  authors: string[];
}
```

**可學習**:
- ❌ 商業服務，不可借鏡
- 但「翻譯 + 搜尋」組合是個思路

**與我們的差異**:
| 維度 | suppr-mcp | 我們 |
|------|-----------|------|
| 價格 | 付費 API | 免費開源 |
| 功能數 | 4 | 21+ |
| 離線使用 | ✗ | ✓ |

---

### 2. jonatasgrosman/findpapers ⭐???

**類型**: Python Library（非 MCP）
**語言**: Python

**重要發現**：
- ⚠️ **這是 Python 函式庫**，不是 MCP Server
- 專為系統性文獻回顧設計
- 支援 7 個資料庫！

**支援資料庫**:
| 資料庫 | 說明 |
|--------|------|
| ACM | 計算機科學 |
| arXiv | 預印本 |
| bioRxiv | 生物預印本 |
| IEEE | 電機工程 |
| medRxiv | 醫學預印本 |
| PubMed | 生醫文獻 |
| Scopus | 跨領域索引 |

**CLI 工具**:
```bash
findpapers search -q "query" -o results.json
findpapers refine results.json
findpapers download results.json -o pdfs/
findpapers generate_bibtex results.json -o refs.bib
```

**亮點功能**:
- ✅ **掠奪性期刊檢測** - 內建黑名單比對
- ✅ **論文去重** - 跨資料庫相似度閾值
- ✅ **BibTeX 自動生成**

**可學習**:
- 🎯 掠奪性期刊檢測是好功能
- 🎯 跨資料庫去重演算法

**程式碼片段**:
```python
# PubMed searcher 實作
class PubMedSearcher:
    def __init__(self):
        self.base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    
    def search(self, query, limit=100):
        # 使用 esearch + efetch 標準流程
        pass
```

---

### 3. naivenaive/EasyPubMed ⭐???

**類型**: Chrome Extension（非 MCP）
**語言**: JavaScript

**重要發現**：
- ⚠️ **這是瀏覽器擴充套件**，不是 MCP Server
- 增強 PubMed 網站 UI
- 很受歡迎的實用工具

**核心功能**:
| 功能 | 說明 |
|------|------|
| Journal Info | 顯示 IF、JCR/CAS 分區、引用數 |
| PDF Retrieval | 透過 Unpaywall/Sci-Hub 取得全文 |
| Translation | 整合 DeepL/Google/Baidu 翻譯 |
| Reference Manager | 匯出到 EndNote/Zotero |
| Filter Manager | 自訂期刊篩選器 |
| Literature Detector | 在任何網頁偵測 DOI/PMID |

**可學習**:
- 🎯 期刊 IF/分區顯示是用戶剛需
- 🎯 Unpaywall 整合取得 OA 連結
- 🎯 多翻譯源選擇

**與我們的比較**:
- EasyPubMed 是「被動增強」（在網站上）
- 我們是「主動查詢」（透過 AI 對話）
- 不同場景，不直接競爭

---

### 4. jannisborn/paperscraper ⭐400+

**類型**: Python Library（非 MCP）
**語言**: Python
**版本**: v0.3.3

**重要發現**：
- ⚠️ **這是 Python 爬蟲庫**，不是 MCP Server
- 被學術論文引用，有一定知名度
- 功能相當完整

**支援來源**:
| 來源 | 功能 |
|------|------|
| PubMed | 搜尋 + 全文 |
| arXiv | 搜尋 + PDF |
| bioRxiv | 搜尋 |
| medRxiv | 搜尋 |
| chemRxiv | 搜尋 |
| Google Scholar | 搜尋 |

**亮點功能**:
- ✅ **全文取得** - BioC-PMC, eLife, Elsevier/Wiley API 多重 fallback
- ✅ **引用搜尋** - 透過 Semantic Scholar API
- ✅ **期刊 IF 查詢** - Impactor class + 模糊匹配
- ✅ **作者 Email 提取** - 從 PubMed 文章

**程式碼亮點**:
```python
from paperscraper import search_papers

# 多來源搜尋
papers = search_papers(
    "machine learning drug discovery",
    sources=["pubmed", "arxiv", "biorxiv"],
    start_date="2023-01-01",
    limit=100
)

# 期刊 IF 查詢
from paperscraper.impact import Impactor
impactor = Impactor()
if_score = impactor.search("nature medicine")  # 模糊匹配
```

**可學習**:
- 🎯 多重 fallback 取全文機制
- 🎯 期刊 IF 模糊查詢
- 🎯 作者聯繫資訊提取

---

## 🔍 第二批分析總結

### 類型分布

| Repo | 類型 | 是 MCP？ | 直接競品？ |
|------|------|----------|-----------|
| suppr-mcp | MCP Server | ✓ | ❌ 商業服務 |
| findpapers | Python Library | ✗ | ❌ 函式庫 |
| EasyPubMed | Chrome Extension | ✗ | ❌ 瀏覽器擴充 |
| paperscraper | Python Library | ✗ | ❌ 函式庫 |

**重要結論**：
> 用戶指定的這 4 個 repos 中，只有 suppr-mcp 是 MCP Server，但它是商業服務。
> 其他 3 個都是 Python 函式庫或瀏覽器擴充，不是我們的直接競品。

### 可借鏡功能

| 功能 | 來源 | 可行性 |
|------|------|--------|
| 掠奪性期刊檢測 | findpapers | ⭐⭐⭐ 高 |
| 期刊 IF/分區顯示 | EasyPubMed | ⭐⭐⭐ 高 |
| 多重全文 Fallback | paperscraper | ⭐⭐⭐ 已有 |
| 作者 Email 提取 | paperscraper | ⭐⭐ 中 |
| 跨資料庫去重 | findpapers | ⭐⭐ 已有 merge_search_results |

---

# 2026-02 新增分析

## 18. paper-search-mcp-nodejs (Dianel555) 🆕

> **定位**: 14 學術平台整合 MCP Server (Node.js/TypeScript)
> **GitHub**: https://github.com/Dianel555/paper-search-mcp-nodejs
> **Stars**: ⭐ 91 | **語言**: TypeScript/Node.js

### 核心賣點

| 賣點 | 說明 | 可學習度 |
|------|------|:--------:|
| **14 學術平台整合** ⭐⭐⭐ | 覆蓋面最廣的 MCP Server | ⭐⭐⭐ |
| **18+ MCP Tools** | 每平台獨立工具 | ⭐⭐ |
| **安全特性** | DOI 驗證、HTML 清理 | ⭐⭐ |
| **Rate Limiting + Cache** | 內建速率限制和快取 | ⭐⭐ |

### 支援的 14 個平台

| 平台 | 類型 | 說明 |
|------|------|------|
| arXiv | 預印本 | CS/Physics |
| WoS (Web of Science) | 索引 | 需付費 |
| PubMed | 生醫 | 標準 |
| Google Scholar | 通用 | 爬蟲風險 |
| bioRxiv | 生物預印本 | 免費 |
| medRxiv | 醫學預印本 | 免費 |
| Semantic Scholar | AI 學術 | 引用分析 |
| IACR | 密碼學 | 專業 |
| Sci-Hub | 全文 | ⚠️ 法律風險 |
| ScienceDirect | 出版商 | Elsevier |
| Springer | 出版商 | Springer Nature |
| Wiley | 出版商 | Wiley |
| Scopus | 索引 | 需付費 |
| Crossref | DOI | 免費 |

### 與我們的比較

```diff
✅ 我們: PubMed 專精 (MeSH/PICO/ESpell) — 深度遠超
✅ 我們: 34 tools vs 18+, 功能更完整
✅ 我們: Citation Tree, iCite, Timeline — 分析能力強

❌ 我們: 沒有出版商直接搜尋 (Elsevier, Springer, Wiley)
❌ 我們: 沒有 WoS/Scopus 整合
```

### 結論

**paper-search-mcp-nodejs 走「廣度」路線**，14 平台但每個都是淺層整合。
我們走「深度」路線，PubMed 一個深挖。**不直接競爭，定位互補。**

---

## 19. healthcare-mcp-public (Cicatriiz) 🆕

> **定位**: 醫療健康 MCP Server (Node.js) — 多 API 整合
> **GitHub**: https://github.com/Cicatriiz/healthcare-mcp-public
> **Stars**: ⭐ 87 | **語言**: Node.js | **版本**: v2.1.1

### 核心賣點

| 賣點 | 說明 | 可學習度 |
|------|------|:--------:|
| **醫療健康全覆蓋** | 不只文獻，包含 FDA/ICD/BMI 等 | ⭐⭐ |
| **9 MCP Tools** | 覆蓋不同醫療資訊需求 | ⭐⭐ |
| **雙 Transport** | HTTP/SSE + stdio | ⭐⭐ |
| **Connection Pooling + Cache** | 企業級效能 | ⭐⭐ |

### Tools 清單 (9 個)

| Tool | 功能 | 說明 |
|------|------|------|
| `search_fda_drugs` | FDA 藥物查詢 | OpenFDA API |
| `search_pubmed` | PubMed 搜尋 | 基本搜尋 |
| `search_health_topics` | 健康主題搜尋 | MedlinePlus |
| `search_clinical_trials` | 臨床試驗 | ClinicalTrials.gov |
| `lookup_icd_code` | ICD-10 查詢 | 診斷碼 |
| `search_medrxiv` | medRxiv 預印本 | 醫學預印本 |
| `calculate_bmi` | BMI 計算 | 工具型 |
| `search_ncbi_bookshelf` | NCBI Bookshelf | 醫學教科書 |
| `get_dicom_metadata` | DICOM metadata | 醫學影像 |

### 與我們的比較

```diff
✅ 我們: PubMed 搜尋 FAR 更強 (MeSH/PICO/Citation)
✅ 我們: 34 vs 9 tools
✅ 我們: 已有 ICD↔MeSH 轉換 (更進階)
✅ 我們: 已有 Gene/PubChem/ClinVar

❌ 我們: 沒有 FDA 藥物查詢 (OpenFDA)
❌ 我們: 沒有 MedlinePlus 健康主題
❌ 我們: 沒有 NCBI Bookshelf
❌ 我們: 沒有 DICOM metadata
```

### 可學習

| 功能 | 說明 | 優先度 |
|------|------|:------:|
| **OpenFDA 整合** | 藥物不良事件、標籤 | ⭐⭐ (BioMCP 也有) |
| **MedlinePlus** | 患者友善健康資訊 | ⭐ |
| **NCBI Bookshelf** | 醫學教科書搜尋 | ⭐⭐ |

### 結論

**healthcare-mcp-public 是「醫療健康」而非「文獻研究」MCP**。
覆蓋面廣但每個功能都很淺。PubMed 搜尋只是其中之一。**不是直接競品。**

---

# 2025 年 8-9 月更新

> **更新日期**: 2025-09-15

## 🔥 重大發現：cyanheads/pubmed-mcp-server

**版本**: v1.4.4 (2025-09-15)
**星星**: 36★ (持續成長中)
**語言**: TypeScript

### 這是我們的直接競品！

**5 個 MCP Tools**:
| Tool | 功能 | 與我們比較 |
|------|------|-----------|
| `pubmed_search_articles` | PubMed 搜尋 | ≈ `search_literature` |
| `pubmed_fetch_contents` | 取得文章詳情 | ≈ `get_article_details` |
| `pubmed_article_connections` | 相關文章/引用 | ≈ `find_related_articles` |
| `pubmed_research_agent` | ⭐ **研究計劃生成器** | 🆕 我們沒有 |
| `pubmed_generate_chart` | ⭐ **圖表生成 (PNG)** | 🆕 我們沒有 |

### 主要更新 (2025 v1.4.x)

1. **OpenTelemetry 整合** - 分散式追蹤
2. **Hono HTTP 框架** - 取代 Express
3. **OAuth 2.1 認證** - JWT + OAuth 雙模式
4. **ESLint + Vitest** - 完整測試框架
5. **Multi-stage Docker build** - 最佳化容器

### 🎯 可學習功能

| 功能 | 說明 | 優先級 |
|------|------|:------:|
| **Research Agent** | 4 階段結構化研究計劃生成 | ⭐⭐⭐ |
| **Chart Generation** | Chart.js 生成 PNG 圖表 | ⭐⭐ |
| **OpenTelemetry** | 分散式追蹤 | ⭐ |

**Research Agent 4 階段**:
```
Phase 1: 問題定義與設計
Phase 2: 數據收集與處理
Phase 3: 分析與解讀
Phase 4: 傳播與迭代
```

---

## 🔥 BioMCP 大幅擴展 (v0.6.5)

**星星**: 367★
**重大更新**: 從 ~10 工具擴展到 **24 個工具**！

### 新增整合

| 整合 | 新增工具數 | 功能 |
|------|:----------:|------|
| **OpenFDA** | 12 | 不良事件、藥物標籤、醫療器材 |
| **NCI Clinical Trials** | 6 | 組織、介入、生物標記 |
| **BioThings** | 3 | gene_getter, drug_getter, disease_getter |
| **AlphaGenome** | 1 | 變異效應預測 |
| **cBioPortal** | 自動 | 基因搜尋自動整合 |

### 🎯 最值得學習的功能

#### 1. Think Tool (強制性)

```python
# BioMCP 的 Think Tool 必須先執行！
# 這是一種 "先計劃再行動" 的架構

# ❌ 直接搜尋會被警告
search(query="BRAF mutation")

# ✅ 必須先 think
think(topic="I need to understand BRAF mutation...")
search(query="BRAF mutation")
```

**Think Tool 實現思路**:
- 強制用戶在搜尋前思考需求
- 產生更精確的搜尋策略
- 類似我們的 `generate_search_queries` 但更強制

#### 2. 統一查詢語言

```python
# BioMCP 的統一查詢語法
search("gene:BRAF")           # 基因
search("drug:pembrolizumab")  # 藥物
search("disease:melanoma")    # 疾病
search("trial:NCT12345678")   # 臨床試驗
```

**可學習點**:
- 簡化多來源查詢
- 統一輸入格式
- 自動路由到正確的 API

#### 3. Performance 優化

- Connection pooling
- Request batching
- Smart caching

---

## 🔥 zotero-mcp 更新 (751★)

### 新功能：語義搜尋

```python
# ChromaDB 向量資料庫
zotero_semantic_search(
    query="machine learning for drug discovery",
    embedding_model="default",  # MiniLM, OpenAI, Gemini
    include_fulltext=True       # PDF 全文
)
```

### 新功能：ChatGPT Connector

```python
# ChatGPT 介面包裝器
zotero_chatgpt_search()  # 專為 ChatGPT 優化
zotero_chatgpt_fetch()   # 簡化輸出格式
```

### 可學習

| 功能 | 技術 | 我們可用 |
|------|------|----------|
| 語義搜尋 | ChromaDB + Embeddings | ⭐⭐ 可考慮 |
| ChatGPT 包裝 | 簡化介面 | ⭐ 已有 copilot_tools |
| PDF 註釋提取 | pdfannots | ⭐⭐ 可考慮 |

---

## 📊 競品星星更新

| Repo | 2024-12 | 2025-09 | 2026-02 | 變化 |
|------|:-------:|:-------:|:-------:|:----:|
| arxiv-mcp-server | 1.9k | 1.9k | ~2k | 穩定 |
| papersgpt-for-zotero | 2k | 2k | ~2k | 穩定 |
| zotero-mcp | 751 | 751 | ~750+ | 穩定 |
| paper-search-mcp | 469 | 469 | **643** | +37% 🔥 |
| BioMCP | 367 | 367 | **413** | +13% |
| suppr-mcp | N/A | N/A | **247** | 🆕 |
| mcp-simple-pubmed | 142 | 142 | **156** | +10% |
| pubmearch | 142 | 142 | **144** | +1% |
| JackKuo666/PubMed-MCP | 82 | 82 | **96** | +17% |
| pubmedmcp | 84 | 84 | **95** | +13% |
| paper-search-mcp-nodejs | N/A | N/A | **91** | 🆕 |
| healthcare-mcp-public | N/A | N/A | **87** | 🆕 |
| **cyanheads/pubmed-mcp-server** | N/A | 36 | **52** | +44% 🔥 |

---

## 🎯 Action Items (基於此次更新)

### 高優先級

1. **Think/Plan Tool 概念**
   - 參考 BioMCP 的 Think Tool
   - 結合我們的 `generate_search_queries`
   - 考慮強制性或建議性

2. **Research Agent**
   - 參考 cyanheads 的結構化研究計劃
   - 4 階段方法論可借鏡

3. **統一查詢語法**
   - `gene:BRAF`, `drug:propofol` 格式
   - 自動路由到正確的搜尋工具

### 中優先級

4. **圖表生成**
   - Chart.js 生成 PNG
   - 視覺化搜尋結果/趨勢

5. **語義搜尋 (Local)**
   - ChromaDB 向量存儲
   - 搜尋結果本地緩存

### 低優先級

6. **OpenTelemetry**
   - 分散式追蹤
   - 效能監控

---

## 🔍 真正的 PubMed/生醫 MCP 競品 (2026-02 更新)

經過完整分析，所有 PubMed/生醫相關 MCP Server：

| Repo | Stars | 語言 | 工具數 | 獨特功能 |
|------|:-----:|:----:|:------:|----------|
| **我們** | — | Python | **34** | MeSH/PICO/Citation Tree/iCite/Timeline/ICD/多源 |
| [paper-search-mcp](https://github.com/openags/paper-search-mcp) | 643 | Python | ~14 | 8 資料庫一站搜尋, PDF 下載 |
| [BioMCP](https://github.com/genomoncology/biomcp) | 413 | Python | 24 | Think Tool, 統一查詢語法, 10+ 數據源 |
| [suppr-mcp](https://github.com/WildDataX/suppr-mcp) | 247 | TS | 4 | AI 語義搜尋 + 文件翻譯 (商業) |
| [mcp-simple-pubmed](https://github.com/andybrandt/mcp-simple-pubmed) | 156 | Python | 3 | uvx 一鍵, Smithery 整合 |
| [pubmearch](https://github.com/Darkroaster/pubmearch) | 144 | Python | 5 | 熱點追蹤, 趨勢分析 |
| [PubMed-MCP-Server](https://github.com/JackKuo666/PubMed-MCP-Server) | 96 | Python | 5 | 進階搜尋, PDF 下載, Smithery |
| [pubmedmcp](https://github.com/grll/pubmedmcp) | 95 | Python | ~2 | uvx 一行安裝, 零配置 |
| [paper-search-mcp-nodejs](https://github.com/Dianel555/paper-search-mcp-nodejs) | 91 | TS | 18+ | 14 平台 (WoS, Scopus, Sci-Hub 等) |
| [healthcare-mcp-public](https://github.com/Cicatriiz/healthcare-mcp-public) | 87 | Node | 9 | FDA, ICD-10, DICOM, BMI |
| [pubmed-mcp-server](https://github.com/cyanheads/pubmed-mcp-server) | 52 | TS | 5 | 圖表生成 (PNG), Research Agent, JWT |

### 關鍵觀察

1. **我們功能最豐富 (34 tools)**，但缺乏推廣 — 無 PyPI/Smithery 發布
2. **paper-search-mcp (643★)** 靠多源廣度 + Smithery 取勝，PubMed 整合淺
3. **BioMCP (413★)** 是功能最接近的競品，但偏向腫瘤基因組學
4. **極簡也能高星** — mcp-simple (3 tools) = 156★，uvx 一鍵是關鍵
5. **Smithery/PyPI 發布是推廣最大瓶頸**
6. **TypeScript 生態活躍** — cyanheads, paper-nodejs, healthcare 都是 TS/Node

---

*本文件為內部參考*
