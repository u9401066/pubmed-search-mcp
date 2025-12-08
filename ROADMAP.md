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

---

## 待實作功能

### Phase 6: Research Prompts ⭐⭐⭐
> **參考**: arxiv-mcp-server (1.9k⭐ 的關鍵功能)

| Prompt | 說明 | 優先度 |
|--------|------|:------:|
| `summarize_paper` | 論文快速摘要 | ⭐⭐⭐ |
| `literature_review` | 文獻回顧生成 | ⭐⭐⭐ |
| `research_questions` | 研究問題建議 | ⭐⭐ |
| `evidence_synthesis` | 證據綜合 (系統性回顧) | ⭐⭐ |
| `clinical_relevance` | 臨床相關性分析 (PubMed 專屬!) | ⭐⭐⭐ |

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

| Tool | 說明 |
|------|------|
| `find_similar_articles` | 找類似文章 (補充 find_related) |
| `get_references` | 取得參考文獻列表 |
| `trace_lineage` | 追蹤研究脈絡 (引用網絡) |

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
