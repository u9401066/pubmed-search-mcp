"""
MCP Server Instructions - Agent 使用指南

此模組包含 MCP Server 的詳細使用說明，供 AI Agent 參考。
從 server.py 獨立出來以便維護和查詢。
"""

from __future__ import annotations

SERVER_INSTRUCTIONS = """
PubMed Search MCP Server - AI Agent 的文獻搜尋助理

═══════════════════════════════════════════════════════════════════════════════
🎯 搜尋策略選擇指南 (IMPORTANT - 所有文獻搜尋統一使用 unified_search)
═══════════════════════════════════════════════════════════════════════════════

⚠️ 重要原則：unified_search 是唯一的文獻搜尋入口。
   所有搜尋情境都從 unified_search 開始，不需要其他搜尋工具。

## 情境 1️⃣: 快速搜尋 (用戶只是想找幾篇文章看看)
───────────────────────────────────────────────────────────────────────────────
觸發條件: "幫我找...", "搜尋...", "有沒有關於..."
流程: 直接呼叫 unified_search()

範例:
```
unified_search(query="remimazolam sedation", limit=10)
```

## 情境 2️⃣: 精確搜尋 (用戶要求專業/精確/完整的搜尋)
───────────────────────────────────────────────────────────────────────────────
觸發條件: "系統性搜尋", "完整搜尋", "文獻回顧", "精確搜尋",
          或用戶提到 MeSH、同義詞、專業搜尋策略

流程:
1. generate_search_queries(topic) → 取得 MeSH 詞彙和同義詞
2. 根據返回的 suggested_queries 選擇最佳策略
3. unified_search(query=優化後的查詢)

範例:
```
# Step 1: 取得搜尋材料
generate_search_queries("anesthesiology artificial intelligence")

# Step 2: 用 MeSH 標準化查詢 (從結果中選擇)
unified_search(query='"Artificial Intelligence"[MeSH] AND "Anesthesiology"[MeSH]')
```

## 情境 3️⃣: PICO 臨床問題搜尋 (用戶問的是比較性問題)
───────────────────────────────────────────────────────────────────────────────
觸發條件: "A比B好嗎?", "...相比...", "...對...的效果", "在...病人中..."

方法 A — Pipeline 自動化 (推薦):
```
unified_search(
  query="remimazolam vs propofol ICU sedation",
  pipeline='template: pico\\ntopic: remimazolam vs propofol for ICU sedation'
)
```

方法 B — 手動 PICO 流程:
1. parse_pico(description) → 解析 PICO 元素
2. 對每個 PICO 元素並行呼叫 generate_search_queries()
3. 組合 Boolean 查詢: (P) AND (I) AND (C) AND (O)
4. unified_search(query=組合查詢)

## 情境 4️⃣: 深入探索 (用戶找到一篇重要論文，想看相關的)
───────────────────────────────────────────────────────────────────────────────
觸發條件: "這篇文章的相關研究", "有誰引用這篇", "類似的文章"

流程:
```
find_related_articles(pmid="12345678")  # PubMed 演算法找相似文章
find_citing_articles(pmid="12345678")   # 引用這篇的後續研究 (forward)
get_article_references(pmid="12345678") # 這篇文章的參考文獻 (backward)
```

## 情境 5️⃣: 預印本搜尋 (用戶想找最新尚未同行審查的研究)
───────────────────────────────────────────────────────────────────────────────
觸發條件: "最新研究", "preprint", "預印本", "arXiv", "medRxiv", "bioRxiv",
          "尚未發表的", "最前沿的研究"

unified_search 支援透過 options 參數控制預印本行為：
- options="preprints": 額外搜尋 arXiv、medRxiv、bioRxiv 預印本伺服器
- options="all_types": 包含非同行審查的文章（預印本、社論等）

範例:
```
# 包含預印本搜尋（預設不包含）
unified_search(query="CRISPR base editing", options="preprints")

# 預印本 + 包含非同行審查文章
unified_search(query="CRISPR gene therapy", options="preprints, all_types")

# 指定來源 + 預印本
unified_search(query="remimazolam sedation", sources="pubmed,europe_pmc", options="preprints")
```

注意：預印本**未經同行審查**，引用時應特別標註。

## 情境 5.5️⃣: 同一回應附帶研究脈絡圖
───────────────────────────────────────────────────────────────────────────────
觸發條件: "研究脈絡", "context graph", "分支", "研究樹", "先給我整體脈絡"

`unified_search` 支援透過 options 參數附帶輕量級研究脈絡圖：
- options="context_graph": 從本次 PMID-backed 結果附帶 Research Context Graph

範例:
```
unified_search(query="remimazolam ICU sedation", options="context_graph")
unified_search(query="propofol delirium ICU", options="context_graph, preprints")
```

注意：這是輕量預覽；若需要完整時間軸/樹/mermaid，改用 `build_research_timeline`。

## 情境 6️⃣: 指定搜尋來源
───────────────────────────────────────────────────────────────────────────────
unified_search 支援 6 個學術資料來源，可透過 sources 參數指定：

| 來源 | sources 值 | 特色 |
|------|-----------|------|
| PubMed | pubmed | 生物醫學金標準，30M+ 文獻 |
| Europe PMC | europe_pmc | 歐洲文獻，33M+ 文獻，6.5M 開放取用 |
| OpenAlex | openalex | 全球學術，250M+ works |
| Semantic Scholar | semantic_scholar | AI 語義搜尋，200M+ 論文 |
| CrossRef | crossref | DOI 元資料，引用計數 |
| CORE | core | 開放取用聚合，200M+ 論文，42M+ 全文 |

範例:
```
# 自動選擇最佳來源（預設）
unified_search(query="machine learning healthcare")

# 指定多個來源
unified_search(query="AI diagnosis", sources="pubmed,openalex,core")

# 使用 CORE 找開放取用論文
unified_search(query="deep learning radiology", sources="core")
```

## 情境 7️⃣: ICD 代碼搜尋
───────────────────────────────────────────────────────────────────────────────
unified_search 會自動偵測查詢中的 ICD-9/ICD-10 代碼並轉換為 MeSH 術語：

```
# ICD 代碼自動偵測 + MeSH 擴展
unified_search(query="E11")        # 自動識別為 Type 2 Diabetes
unified_search(query="I21")        # 自動識別為 Myocardial Infarction
unified_search(query="E11 treatment outcomes")  # 混合 ICD + 文字也可以
```

如需手動轉換 ICD ↔ MeSH（不搜尋），使用 convert_icd_mesh。

═══════════════════════════════════════════════════════════════════════════════
📦 匯出工具 (搜尋完成後)
═══════════════════════════════════════════════════════════════════════════════

- prepare_export(pmids, format): 匯出引用格式 (ris/bibtex/csv/medline/json)
- save_literature_notes(pmids="last"): 將搜尋結果保存成本機 wiki note（預設，Foam-compatible）/Markdown/MedPaper-style 筆記與 CSL JSON；可用 PUBMED_NOTES_DIR 指定 wiki references 目錄

═══════════════════════════════════════════════════════════════════════════════
📄 全文取得與文本挖掘
═══════════════════════════════════════════════════════════════════════════════

### 全文取得
- get_fulltext(pmcid): 📄 取得解析後的全文 (分段顯示，多源：Europe PMC, Unpaywall, CORE)

### 文本挖掘
- get_text_mined_terms(pmid/pmcid): 🔬 取得標註 (基因、疾病、藥物，來自 Europe PMC)

### 使用範例
```
# 搜尋後，對感興趣的文章取得全文
unified_search(query="CRISPR gene therapy", sources="europe_pmc")
get_fulltext(pmcid="PMC7096777", sections="introduction,results")

# 找出文章提到的所有基因
get_text_mined_terms(pmid="12345678", semantic_type="GENE_PROTEIN")
```

═══════════════════════════════════════════════════════════════════════════════
🧬 NCBI 延伸資料庫工具 (Gene, PubChem, ClinVar)
═══════════════════════════════════════════════════════════════════════════════

這些工具搜尋的是**非文獻資料庫**（基因、化合物、臨床變異），與文獻搜尋互補。

### Gene 資料庫 - 基因資訊
```
search_gene("BRCA1", organism="human", limit=5)
get_gene_details(gene_id="672")
get_gene_literature(gene_id="672", limit=20)  # 返回 PMID 列表
```

### PubChem - 化合物/藥物資訊
```
search_compound("aspirin", limit=5)
get_compound_details(cid="2244")
get_compound_literature(cid="2244", limit=20)
```

### ClinVar - 臨床變異
```
search_clinvar("BRCA1", limit=10)
```

═══════════════════════════════════════════════════════════════════════════════
💾 Session 管理工具 (解決記憶滿載問題)
═══════════════════════════════════════════════════════════════════════════════

搜尋結果會自動暫存在 session 中，不需要記住所有 PMID！

- get_session_pmids(search_index=-1): 取得指定搜尋的 PMID 列表
- get_cached_article(pmid): 從快取取得文章詳情 (不消耗 API)
- get_session_summary(): 查看 session 狀態和可用資料

### 快捷用法
- `pmids="last"` - 在 prepare_export, get_citation_metrics 等工具中使用
- `get_session_pmids()` 回傳 `pmids_csv` 可直接複製使用

═══════════════════════════════════════════════════════════════════════════════
🔧 所有可用工具
═══════════════════════════════════════════════════════════════════════════════

### 搜尋工具
- unified_search: Unified Search - Single entry point for multi-source academic search.

### 查詢智能
- parse_pico: Parse a clinical question into PICO elements OR accept pre-parsed PICO.
- generate_search_queries: Gather search intelligence for a topic - returns RAW MATERIALS for Agent to decide.
- analyze_search_query: Analyze a search query without executing the search.

### 文章探索
- fetch_article_details: Fetch detailed information for one or more PubMed articles.
- find_related_articles: Find articles related to a given PubMed article.
- find_citing_articles: Find articles that cite a given PubMed article.
- get_article_references: Get the references (bibliography) of a PubMed article.
- get_citation_metrics: Get citation metrics from NIH iCite for articles.

### 全文工具
- get_fulltext: Enhanced multi-source fulltext retrieval.
- get_text_mined_terms: Get text-mined annotations from Europe PMC.

### NCBI 延伸
- search_gene: Search NCBI Gene database for gene information.
- get_gene_details: Get detailed information about a gene by NCBI Gene ID.
- get_gene_literature: Get PubMed articles linked to a gene.
- search_compound: Search PubChem for chemical compounds.
- get_compound_details: Get detailed information about a compound by PubChem CID.
- get_compound_literature: Get PubMed articles linked to a compound.
- search_clinvar: Search ClinVar for clinical variants.

### 引用網絡
- build_citation_tree: Build a citation tree (network) from a single article.

### 匯出工具
- prepare_export: Export citations to reference manager formats.
- save_literature_notes: Save searched articles as guided local wiki/Foam/Markdown notes.

### Session 管理
- read_session: Read session data through a single facade.
- get_session_pmids: 取得 session 中暫存的 PMID 列表。
- get_cached_article: 從 session 快取取得文章詳情。
- get_session_summary: 取得當前 session 的摘要資訊。
- get_session_log: 取得當前 session 的 activity log 與搜尋歷史摘要。

### 機構訂閱
- configure_institutional_access: Configure your institution's link resolver for full-text access.
- get_institutional_link: Generate institutional access link (OpenURL) for an article.
- list_resolver_presets: List available institutional link resolver presets.
- test_institutional_access: Test your institutional link resolver configuration.

### 視覺搜索
- analyze_figure_for_search: Analyze a scientific figure or image for literature search.

### ICD 轉換
- convert_icd_mesh: Convert between ICD codes and MeSH terms (bidirectional).

### 研究時間軸
- build_research_timeline: Build a research timeline for a topic OR specific PMIDs.
- analyze_timeline_milestones: Analyze milestone distribution for a research topic.
- compare_timelines: Compare research timelines of multiple topics.

### 引用驗證
- verify_reference_list: Verify a plain-text reference list against PubMed evidence.

### 圖表擷取
- get_article_figures: Get structured figure metadata (label, caption, image URL) and PDF links from a PMC Open Access arti

### 圖片搜尋
- search_biomedical_images: Search biomedical images across Open-i and Europe PMC.

### Pipeline 管理
- manage_pipeline: Manage saved pipelines through a single facade.
- save_pipeline: Save a pipeline configuration for later reuse.
- list_pipelines: List all saved pipeline configurations.
- load_pipeline: Load a pipeline configuration for review or editing.
- delete_pipeline: Delete a saved pipeline configuration and its execution history.
- get_pipeline_history: Get execution history for a saved pipeline.
- schedule_pipeline: Schedule a saved pipeline for periodic execution.

NOTE: 搜尋結果自動暫存，使用 session 工具可隨時取回，不需依賴 Agent 記憶。

NOTE: 每次搜尋結果會顯示各來源的 API 回傳量（如 **Sources**: pubmed (8/500), openalex (5)）。
這些數字代表每個來源實際回傳的文章數和該來源的總匹配數，是評估搜尋覆蓋率的重要依據。
"""

__all__ = ["SERVER_INSTRUCTIONS"]
