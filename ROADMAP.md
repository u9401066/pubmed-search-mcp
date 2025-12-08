# PubMed Search MCP - Roadmap

> 本文件記錄**待實作**功能。已完成功能請參閱 [CHANGELOG.md](CHANGELOG.md)。

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
| `mesh_analysis` | MeSH 詞彙分析 (我們獨特!) | ⭐⭐ |

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

### Phase 9: 長期願景
> **參考**: BioMCP, zotero-mcp

#### 語義搜尋
- Embedding 模型整合 (all-MiniLM-L6-v2)
- 向量資料庫 (ChromaDB)
- 概念搜尋而非關鍵字

#### 統一查詢語言 (BioMCP 設計)
- Query DSL: `mesh:diabetes AND date:>2023`
- Schema 查詢、Query 解釋

#### 多資料庫整合
- ClinicalTrials.gov
- Cochrane
- PMC 全文

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
