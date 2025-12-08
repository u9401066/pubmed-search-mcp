# PubMed Search MCP - Roadmap

> 本文件記錄**待實作**功能。已完成功能請參閱 [CHANGELOG.md](CHANGELOG.md)。

## 願景

**PubMed 為核心，可擴展至其他生醫資料庫**

```
┌─────────────────────────────────────────────────────────────┐
│                    pubmed-search-mcp                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌─────────────────────────────────────────────────────┐   │
│   │              Core: PubMed/NCBI Entrez               │   │
│   │  • 官方 Entrez API                                   │   │
│   │  • 官方查詢語法 [MeSH], [tiab], [dp]                 │   │
│   │  • MeSH 標準詞彙、PICO 結構化查詢                     │   │
│   └─────────────────────────────────────────────────────┘   │
│                           ↓                                 │
│   ┌─────────────────────────────────────────────────────┐   │
│   │           Future Extensions (Phase 9+)              │   │
│   │  • PMC 全文 (同為 NCBI，共用 Entrez)                 │   │
│   │  • ClinicalTrials.gov (NCBI 合作)                   │   │
│   │  • Cochrane Library (系統性回顧)                     │   │
│   └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**設計原則**：
- ✅ 使用各資料庫**官方 API 和語法**（不另創 DSL）
- ✅ PubMed 功能優先完善，再逐步擴展
- ✅ 擴展時保持 API 一致性

## 版本歷程

| 版本 | 日期 | 主要功能 |
|------|------|----------|
| v0.1.0 | 2024-12-05 | 8 個搜尋工具、MeSH、PICO、Session/Cache |
| v0.1.1 | 2025-12-08 | Cache 優化、force_refresh |
| v0.1.2 | 2025-12-08 | Export 系統 (RIS/BibTeX/CSV)、HTTP 下載端點 |
| v0.1.3 | 2025-12-08 | pylatexenc 整合、ISSN/Language/PubType 欄位 |
| v0.1.4 | 2025-12-08 | Query Analysis (estimated_count, pubmed_translation) |
| v0.1.5 | 2025-12-08 | HTTPS 部署 (Nginx + TLS + Rate Limiting) |
| v0.1.6 | 2025-12-08 | Citation Network: `get_article_references` |

---

## 待實作功能

### Phase 6: Research Prompts ⭐⭐⭐
> **參考**: arxiv-mcp-server (1.9k⭐ 的關鍵功能)

#### arxiv-mcp-server 的 Prompts 分析

arxiv-mcp-server 目前只有 **1 個 Prompt**: `deep-paper-analysis`

```
┌─────────────────────────────────────────────────────────────────────┐
│  arxiv-mcp-server 的 Prompt 設計                                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Prompt: deep-paper-analysis                                        │
│  ─────────────────────────                                          │
│  輸入: paper_id (arXiv ID)                                          │
│  輸出: 一個長文字 prompt，引導 Agent 如何分析論文                      │
│                                                                      │
│  內容包含:                                                           │
│  1. AVAILABLE TOOLS 說明 (read_paper, download_paper, search_papers)│
│  2. <workflow-for-paper-analysis> XML 結構                          │
│     - <preparation> 準備步驟                                         │
│     - <comprehensive-analysis> 摘要框架                              │
│     - <research-context> 研究背景                                    │
│     - <methodology-analysis> 方法論分析                              │
│     - <results-analysis> 結果分析                                    │
│     - <practical-implications> 實務意涵                              │
│     - <theoretical-implications> 理論意涵                            │
│     - <future-directions> 未來方向                                   │
│     - <broader-impact> 廣泛影響                                      │
│  3. OUTPUT_STRUCTURE 輸出格式指引                                    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**關鍵發現**: arxiv 的 Prompt 本質上是一個**分析框架模板**，讓 Agent 知道該如何分析論文。

#### 我們 vs arxiv-mcp-server 比較

| 項目 | arxiv-mcp-server | 我們 (pubmed-search-mcp) |
|------|------------------|-------------------------|
| **搜尋智慧** | 基本關鍵字搜尋 | ✅ ESpell + MeSH + PICO |
| **語意理解** | Agent 自行處理 | ✅ `parse_pico()` 結構化解析 |
| **搜尋策略** | 無 | ✅ `generate_search_queries()` 自動產生 |
| **同義詞擴展** | 無 | ✅ MeSH Entry Terms 自動擴展 |
| **分析 Prompt** | ✅ 有 (XML 結構框架) | ❌ 無 |
| **PDF 下載** | ✅ 有 + Markdown 轉換 | ❌ 無 (只有 PMC 連結) |

#### 結論：我們的優勢是「搜尋」，他們的優勢是「分析框架」

我們已經有:
- ✅ **PICO 解析** - Agent 可用自然語言描述問題，自動拆解
- ✅ **MeSH 擴展** - 自動找到標準醫學詞彙和同義詞
- ✅ **批次搜尋** - 並行執行多策略搜尋

我們缺少的:
- ❌ **分析框架 Prompt** - 引導 Agent 如何系統性分析文獻

#### 建議：新增醫學文獻專用 Prompts

| Prompt | 說明 | 醫學特色 |
|--------|------|----------|
| `analyze_clinical_paper` | 臨床研究論文分析 | PICO/證據等級/偏差評估 |
| `systematic_review_guide` | 系統性回顧指引 | PRISMA 流程/納入排除標準 |
| `drug_safety_review` | 藥物安全性回顧 | 副作用/交互作用/警語 |

> **Note**: MeSH 查詢已內建於 `generate_search_queries()` 工具，自動提供 preferred terms 和 synonyms。

### Phase 7: 研究分析功能 ⭐⭐
> **參考**: pubmearch, pubmed-mcp-server

#### 研究熱點分析
| Tool | 說明 |
|------|------|
| `analyze_research_trends` | 關鍵字頻率統計 |
| `track_publication_trend` | 發文趨勢追蹤 |
| `identify_hot_topics` | 熱門主題識別 |

#### 圖表生成 (PNG 輸出)
| Tool | 說明 |
|------|------|
| `generate_chart` | Bar/Line/Pie chart |

#### 研究計畫生成
| Tool | 說明 |
|------|------|
| `generate_research_plan` | 結構化 JSON 研究計畫 |

### Phase 8: 進階分析 ⭐
> **參考**: pubmed-mcp-server, BioMCP

| Tool | 說明 | 狀態 |
|------|------|:----:|
| `find_related_articles` | 找相似文章 (PubMed 演算法) | ✅ v0.1.0 |
| `find_citing_articles` | 找引用這篇的文章 (forward) | ✅ v0.1.0 |
| `get_article_references` | 取得參考文獻列表 (backward) | ✅ v0.1.6 |
| `trace_lineage` | 追蹤研究脈絡 (引用網絡) | ⏳ |
| `visualize_citation_network` | 視覺化引用網絡 (Mermaid) | ⏳ |

### Phase 9: 資料庫擴展 (PubMed 生態系)
> **原則**: 使用各資料庫官方 API，不另創統一 DSL

#### PMC 全文整合 (NCBI)
| Tool | 說明 | API |
|------|------|-----|
| `search_pmc_fulltext` | 全文搜尋 | NCBI Entrez (共用) |
| `get_pmc_fulltext` | 取得全文 XML/PDF | PMC OA Service |

#### ClinicalTrials.gov 整合
| Tool | 說明 | API |
|------|------|-----|
| `search_trials` | 搜尋臨床試驗 | ClinicalTrials.gov API v2 |
| `get_trial_details` | 取得試驗詳情 | 官方 REST API |

> **語法**: 使用 ClinicalTrials.gov 官方查詢語法，如 `AREA[Condition]diabetes`

#### Cochrane Library (選擇性)
| Tool | 說明 |
|------|------|
| `search_cochrane_reviews` | 搜尋系統性回顧 |

### Phase 10: 長期願景

#### 語義搜尋增強
- Embedding 模型整合 (all-MiniLM-L6-v2)
- 向量資料庫 (ChromaDB)
- 概念搜尋 + 傳統關鍵字搜尋混合

#### 跨資料庫關聯
- PubMed ↔ ClinicalTrials.gov 文獻-試驗關聯
- PubMed ↔ PMC 摘要-全文連結

---

## 待改進項目

### 搜尋策略
- [ ] Clinical Query Filters 模組 (`therapy[filter]` 需展開為完整搜尋策略)
- [ ] 策略模板系統 (systematic_review, clinical_evidence, quick_overview)

### 匯出功能
- [ ] 批量 PDF 下載 (`prepare_batch_pdf` - PMC Open Access)
- [ ] APA/MLA 引用格式

---

## 暫不計畫的功能 ❌

| 功能 | 來源 | 原因 |
|------|------|------|
| Google Scholar 爬蟲 | google-scholar-mcp | ToS 風險、IP 封鎖 |
| Sci-Hub 整合 | JackKuo666 | 版權/法律問題 |
| Zotero 整合 | zotero-mcp | 不同定位 |
| 本地 RAG | papersgpt-for-zotero | 複雜度太高 |

---

## 競品參考

| 專案 | Stars | 我們的差異化 |
|------|-------|------------|
| pubmed-mcp-server | 36 | 我們有 MeSH/PICO，他們有圖表生成 |
| arxiv-mcp-server | 1.9k | Research Prompts 是標配功能 |
| BioMCP | 367 | 統一查詢語言是好方向 |

> 詳見 [docs/competitor-analysis.md](docs/competitor-analysis.md)

---

## 貢獻指南

歡迎貢獻！目前優先需要：
1. Phase 6 Research Prompts 設計
2. Phase 7 研究分析功能
3. 測試案例
