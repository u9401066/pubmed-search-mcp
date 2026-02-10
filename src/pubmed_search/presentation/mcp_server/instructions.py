"""
MCP Server Instructions - Agent 使用指南

此模組包含 MCP Server 的詳細使用說明，供 AI Agent 參考。
從 server.py 獨立出來以便維護和查詢。
"""

SERVER_INSTRUCTIONS = """
PubMed Search MCP Server - AI Agent 的文獻搜尋助理

═══════════════════════════════════════════════════════════════════════════════
🎯 搜尋策略選擇指南 (IMPORTANT - 請根據用戶需求選擇正確流程)
═══════════════════════════════════════════════════════════════════════════════

## 情境 1️⃣: 快速搜尋 (用戶只是想找幾篇文章看看)
───────────────────────────────────────────────────────────────────────────────
觸發條件: "幫我找...", "搜尋...", "有沒有關於..."
流程: 直接呼叫 search_literature()

範例:
```
search_literature(query="remimazolam sedation", limit=10)
```

## 情境 2️⃣: 精確搜尋 (用戶要求專業/精確/完整的搜尋)
───────────────────────────────────────────────────────────────────────────────
觸發條件: "系統性搜尋", "完整搜尋", "文獻回顧", "精確搜尋", 
          或用戶提到 MeSH、同義詞、專業搜尋策略

流程:
1. generate_search_queries(topic) → 取得 MeSH 詞彙和同義詞
2. 根據返回的 suggested_queries 選擇最佳策略
3. search_literature(query=優化後的查詢)

範例:
```
# Step 1: 取得搜尋材料
generate_search_queries("anesthesiology artificial intelligence")

# Step 2: 用 MeSH 標準化查詢 (從結果中選擇)
search_literature(query='"Artificial Intelligence"[MeSH] AND "Anesthesiology"[MeSH]')
```

## 情境 3️⃣: PICO 臨床問題搜尋 (用戶問的是比較性問題)
───────────────────────────────────────────────────────────────────────────────
觸發條件: "A比B好嗎?", "...相比...", "...對...的效果", "在...病人中..."

流程:
1. parse_pico(description) → 解析 PICO 元素
2. 對每個 PICO 元素並行呼叫 generate_search_queries()
3. 組合 Boolean 查詢: (P) AND (I) AND (C) AND (O)
4. search_literature() 執行搜尋
5. merge_search_results() 合併結果

範例:
```
# Step 1: 解析 PICO
parse_pico(description="remimazolam 在 ICU 鎮靜比 propofol 好嗎")
→ P=ICU patients, I=remimazolam, C=propofol, O=sedation outcome

# Step 2: 並行取得各元素的 MeSH
generate_search_queries("ICU patients")
generate_search_queries("remimazolam") 
generate_search_queries("propofol")

# Step 3: 組合搜尋
search_literature(query='("Intensive Care Units"[MeSH]) AND (remimazolam OR CNS7056) AND (propofol)')
```

## 情境 4️⃣: 深入探索 (用戶找到一篇重要論文，想看相關的)
───────────────────────────────────────────────────────────────────────────────
觸發條件: "這篇文章的相關研究", "有誰引用這篇", "類似的文章"

流程:
```
find_related_articles(pmid="12345678")  # PubMed 演算法找相似文章
find_citing_articles(pmid="12345678")   # 引用這篇的後續研究 (forward)
get_article_references(pmid="12345678") # 這篇文章的參考文獻 (backward)
```

═══════════════════════════════════════════════════════════════════════════════
📦 匯出工具 (搜尋完成後)
═══════════════════════════════════════════════════════════════════════════════

- prepare_export(pmids, format): 匯出引用格式 (ris/bibtex/csv/medline/json)
- get_article_fulltext_links(pmid): 取得全文連結 (PMC/DOI)
- analyze_fulltext_access(pmids): 分析哪些文章有免費全文

═══════════════════════════════════════════════════════════════════════════════
🇪🇺 Europe PMC 工具 (全文存取 + 文本挖掘)
═══════════════════════════════════════════════════════════════════════════════

Europe PMC 提供 33M+ 文獻，6.5M 開放取用全文。最適合：找全文、歐洲研究。

### 搜尋與全文
- search_europe_pmc(query, open_access_only=True): 搜尋 Europe PMC
- get_fulltext(pmcid): 📄 取得解析後的全文 (分段顯示)
- get_fulltext_xml(pmcid): 取得原始 JATS XML

### 文本挖掘與引用
- get_text_mined_terms(pmid/pmcid): 🔬 取得標註 (基因、疾病、藥物)
- get_europe_pmc_citations(pmid/pmcid, direction): 引用網路

### 使用範例
```
# 找到文章後，直接閱讀全文
search_europe_pmc("CRISPR gene therapy", has_fulltext=True, limit=5)
get_fulltext(pmcid="PMC7096777", sections="introduction,results")

# 找出文章提到的所有基因
get_text_mined_terms(pmid="12345678", semantic_type="GENE_PROTEIN")
```

═══════════════════════════════════════════════════════════════════════════════
📚 CORE 開放取用工具 (200M+ 論文)
═══════════════════════════════════════════════════════════════════════════════

CORE 聚合全球 14,000+ 機構庫的開放取用研究，42M+ 有全文。

### 使用時機
- 需要開放取用版本的論文
- 搜尋預印本和機構庫內容
- 在論文全文中搜尋特定內容
- 用 DOI/PMID 找到文章的開放版本

### 搜尋語法
- title:"machine learning"    → 標題搜尋
- authors:"John Smith"        → 作者搜尋
- fullText:"neural network"  → 全文內容搜尋

### 使用範例
```
# 找開放取用論文
search_core("machine learning healthcare", has_fulltext=True, limit=10)

# 在全文中搜尋
search_core_fulltext("propofol dose calculation", limit=5)

# 用 DOI 找開放版本
find_in_core(identifier="10.1038/s41586-021-03819-2", identifier_type="doi")

# 取得全文
get_core_fulltext(core_id="123456789")
```

═══════════════════════════════════════════════════════════════════════════════
🧬 NCBI 延伸資料庫工具 (Gene, PubChem, ClinVar)
═══════════════════════════════════════════════════════════════════════════════

這些工具讓你從 NCBI 其他資料庫取得相關資訊，與文獻搜尋互補。

### Gene 資料庫 - 基因資訊
```
# 搜尋基因
search_gene("BRCA1", organism="human", limit=5)

# 取得基因詳情
get_gene_details(gene_id="672")  # BRCA1

# 找基因相關文獻
get_gene_literature(gene_id="672", limit=20)
→ 返回 PMID 列表，可用 fetch_article_details 取得文章
```

### PubChem - 化合物/藥物資訊
```
# 搜尋化合物
search_compound("aspirin", limit=5)
search_compound("remimazolam", limit=3)

# 取得化合物詳情 (分子式、SMILES、InChI 等)
get_compound_details(cid="2244")  # aspirin

# 找化合物相關文獻
get_compound_literature(cid="2244", limit=20)
```

### ClinVar - 臨床變異
```
# 搜尋臨床變異
search_clinvar("BRCA1", limit=10)
search_clinvar("cystic fibrosis", limit=10)
→ 返回變異紀錄，包含臨床意義和相關疾病
```

═══════════════════════════════════════════════════════════════════════════════
💾 Session 管理工具 (解決記憶滿載問題)
═══════════════════════════════════════════════════════════════════════════════

搜尋結果會自動暫存在 session 中，不需要記住所有 PMID！

- get_session_pmids(search_index=-1): 取得指定搜尋的 PMID 列表
  - search_index=-1: 最近一次搜尋
  - search_index=-2: 前一次搜尋
  - query_filter="BJA": 篩選包含 "BJA" 的搜尋

- list_search_history(limit=10): 列出搜尋歷史

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

### Session 管理
- get_session_pmids: 取得 session 中暫存的 PMID 列表。
- get_cached_article: 從 session 快取取得文章詳情。
- get_session_summary: 取得當前 session 的摘要資訊。

### 機構訂閱
- configure_institutional_access: Configure your institution's link resolver for full-text access.
- get_institutional_link: Generate institutional access link (OpenURL) for an article.
- list_resolver_presets: List available institutional link resolver presets.
- test_institutional_access: Test your institutional link resolver configuration.

### 視覺搜索
- analyze_figure_for_search: Analyze a scientific figure or image for literature search.

### ICD 轉換
- convert_icd_mesh: Convert between ICD codes and MeSH terms (bidirectional).
- search_by_icd: Search PubMed using ICD code (auto-converts to MeSH).

### 研究時間軸
- build_research_timeline: Build a research timeline for a topic OR specific PMIDs.
- analyze_timeline_milestones: Analyze milestone distribution for a research topic.
- compare_timelines: Compare research timelines of multiple topics.

### 圖片搜尋
- search_biomedical_images: Search biomedical images across Open-i and Europe PMC.

NOTE: 搜尋結果自動暫存，使用 session 工具可隨時取回，不需依賴 Agent 記憶。
"""

__all__ = ["SERVER_INSTRUCTIONS"]
