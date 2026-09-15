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

方法 A — Agent 提供 PICO handoff (推薦):
```
pico = validate_pico_plan(
  description="remimazolam vs propofol ICU sedation",
  p="ICU patients requiring sedation",
  i="remimazolam",
  c="propofol",
  o="sedation quality, delirium, extubation time"
)
unified_search(
  query="remimazolam vs propofol ICU sedation",
  pipeline="<pipeline field from validate_pico_plan response>"
)
```

方法 B — 手動 inline PICO pipeline:
1. Agent 先從臨床問題抽出 P/I/C/O；不確定時先詢問使用者
2. validate_pico_plan(description, p, i, c, o) → 驗證 agent-provided PICO 並產生 pipeline
3. 可選：對每個 PICO 元素並行呼叫 generate_search_queries() 取得 MeSH/同義詞
4. unified_search(query=原問題, pipeline=validate_pico_plan 回傳的 template:pico pipeline)

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
- options="include_detected_preprints": 保留啟發式規則偵測為預印本的項目；
  此規則只能辨認已知預印本，不能證明其他項目已經同儕審查

範例:
```
# 包含預印本搜尋（預設不包含）
unified_search(query="CRISPR base editing", options="preprints")

# 不額外搜尋預印本來源，但保留其他來源中偵測到的預印本
unified_search(query="CRISPR gene therapy", options="include_detected_preprints")

# 指定來源 + 預印本
unified_search(query="remimazolam sedation", sources="pubmed,europe_pmc", options="preprints")
```

注意：預印本**未經同行審查**，引用時應特別標註。

## 情境 6️⃣: 指定搜尋來源
───────────────────────────────────────────────────────────────────────────────
unified_search 的來源依 registry 與部署設定決定，可透過 sources 指定；Crossref 用於補充 metadata：

| 來源 | sources 值 | 特色 |
|------|-----------|------|
| PubMed | pubmed | 生物醫學索引與 MeSH |
| Europe PMC | europe_pmc | 生物醫學索引與可取得的全文 XML |
| OpenAlex | openalex | 跨領域學術 metadata |
| Semantic Scholar | semantic_scholar | 學術檢索與引用關聯 |
| CrossRef | crossref | DOI 元資料補充與引用計數；不是 primary search |
| CORE | core | repository metadata 與可取得的全文 |
| Scopus | scopus | 需設定授權與 enable flag |
| Web of Science | web_of_science | 需設定授權與 enable flag |

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

## 情境 8️⃣: 研究脈絡（可持久化、可版本比對）
───────────────────────────────────────────────────────────────────────────────
觸發條件: "研究脈絡", "研究演變", "這個領域怎麼走到今天", "上次之後有什麼新的",
          "幫我追蹤這個主題", "research chronicle", "研究編年史"

**build_research_chronicle 是研究演化的唯一入口**，也是可以持續回頭維護的
研究脈絡。它會以遞增 revision 持久化儲存，所以之後重跑就能做版本比對。

每個 chronicle entry 都帶有：一句附引用的 claim、supporting/contradicting/
updating 證據、所屬研究分支 (lineage)、confidence。型別化 provenance graph 以
Topic → Branch → Entry → EvidenceArticle 相連並驗證 edge invariants。audit 會
回報證據覆蓋率、識別碼覆蓋率、分支覆蓋率、graph 完整性與時序缺口。

```
# 建立/更新研究脈絡（重跑會產生 revision N+1）
build_research_chronicle(topic="remimazolam")
build_research_chronicle(pmids="last", topic="My Reading List")

# 只給 chronicle_id 就是「照原本的檢索範圍再跑一次」：
# topic/pmids 與 max_events/min_year/max_year 都沿用上一版，
# 所以 diff 看到的是研究進展，而不是被悄悄改掉的檢索窗口。
build_research_chronicle(chronicle_id="remimazolam-9f2b1c4d")

# 讀取
read_research_chronicle(request={"action":"list"})
read_research_chronicle(request={"action":"load","chronicle_id":"remimazolam-9f2b1c4d","output":"tree"})

# 版本比對：上次之後新增/未觀察到/更新了什麼
read_research_chronicle(request={"action":"diff","chronicle_id":"remimazolam-9f2b1c4d","from_revision":1})

# 有證據支撐的敘事（每句 claim 都附 entry ID 與 PMID/DOI）
read_research_chronicle(request={"action":"narrate","chronicle_id":"remimazolam-9f2b1c4d","mode":"full"})
```

output 可選: summary（預設）, json, chronicle_map, timeline, tree, graph,
evidence, milestones, mermaid, narrative。啟用 durable
artifact 且寫入成功時，會保存完整 snapshot、投影、證據表與 audit；artifact 失敗
不會回滾已提交的 Chronicle revision，回應會明確警告。

═══════════════════════════════════════════════════════════════════════════════
📜 研究脈絡輸出格式與 Lineage Tree
═══════════════════════════════════════════════════════════════════════════════

編年史的**主軸是時序**（線性），**分支 (lineage) 是次要組織維度**。兩者都是
同一份 snapshot 的投影，timeline 與 tree 共享來源；不同投影可能省略不同細節，應以 snapshot 與 audit 核對。

### 輸出格式 (output 參數)
| 格式 | 說明 | 適用場景 |
|------|------|----------|
| summary | 緊湊 Markdown，含時序主軸（預設） | 一般閱讀 |
| timeline | 時序投影 JSON | 程式處理 |
| tree | 🌳 研究脈絡樹 JSON | 分支式研究演化 |
| graph | 型別化 provenance graph | 證據溯源 / 視覺化 |
| evidence | 去重後的證據表 | 核對引用 |
| milestones | 里程碑分佈與證據品質統計 | 領域診斷 |
| chronicle_map | 橫向時間主軸與研究分支座標 JSON | 完整可稽核視覺資料 |
| mermaid | 橫向年份主軸與觀察到的主題分支 | 標準嵌入圖 |
| narrative | 有證據支撐的敘事 | 寫作 / 報告 |
| json | 完整 snapshot | API 整合 |

### Research Lineage Tree (tree 格式)
主題分支優先由多篇論文重複出現的 MeSH descriptor 與作者 keyword 建立；一篇
論文只有一個 primary branch，但可用 matched signals 與 cross-links 保留跨主題
關聯。當只有 singleton 或語意訊號不足時，才使用研究階段 fallback，並在 audit
明確警告。Branch point 只表示本次範圍內最早觀察到的有日期證據，不代表因果、
研究取代關係或整個領域的 first report。

```
# 產生研究脈絡樹
build_research_chronicle(topic="pembrolizumab", output="tree")

# 橫向時間主軸與主題分支圖（經結構驗證與自動降階修正）
build_research_chronicle(topic="CRISPR", output="mermaid")
```

### Landmark Detection
里程碑分析優先使用 evidence provider 儲存的明確
`landmark_importance_score`，缺少時才以引用數作 fallback。Milestone detection
confidence 只描述分類信心，不會被當成科學重要性。

```
# 里程碑分佈統計（讀已儲存的 chronicle，不重跑搜尋）
read_research_chronicle(request={"action":"milestones","chronicle_id":"remimazolam-9f2b1c4d"})

# 比較多個主題（含共用證據分析）
read_research_chronicle(request={"action":"compare","selection":{"kind":"topics","values":["remimazolam","propofol","dexmedetomidine"]}})
```

═══════════════════════════════════════════════════════════════════════════════
🌳 引用網絡 — Citation Tree
═══════════════════════════════════════════════════════════════════════════════

從一篇論文出發，建構引用網路（向前引用 + 向後參考文獻）。

```
build_citation_tree(pmid="12345678", depth=2, direction="both")
```

### 輸出格式 (output_format 參數)
| 格式 | 工具 | 適用場景 |
|------|------|----------|
| cytoscape | Cytoscape.js | 學術標準（預設） |
| g6 | AntV G6 | 現代 TypeScript |
| d3 | D3.js | 自訂視覺化 |
| vis | vis-network | 快速原型 |
| graphml | GraphML XML | 桌面工具 (Gephi, VOSviewer) |
| mermaid | Mermaid (NEW) | VS Code / Markdown 預覽 |

═══════════════════════════════════════════════════════════════════════════════
📦 匯出工具 (搜尋完成後)
═══════════════════════════════════════════════════════════════════════════════

- prepare_export(pmids, format): 匯出引用格式；official 支援 ris/medline/csl，local 支援 ris/bibtex/csv/medline/json
- save_literature_notes(pmids="last"): 將搜尋結果保存成本機 wiki note（預設，Foam-compatible）/Markdown/MedPaper-style 筆記與 CSL JSON；可用 PUBMED_NOTES_DIR 指定 wiki references 目錄

═══════════════════════════════════════════════════════════════════════════════
📄 全文取得與文本挖掘
═══════════════════════════════════════════════════════════════════════════════

### 全文取得
- get_fulltext(source={kind,value}): 📄 以明確 PMID/PMCID/DOI 來源物件取得解析後的全文 (分段顯示；Europe PMC XML, Unpaywall OA locations, institutional direct/EZproxy, CORE, extended fallback)

### 文本挖掘
- get_text_mined_terms(source={kind,value}): 🔬 以明確 PMID/PMCID 來源物件取得標註 (基因、疾病、藥物，來自 Europe PMC)

### 使用範例
```
# 搜尋後，對感興趣的文章取得全文
unified_search(query="CRISPR gene therapy", sources="europe_pmc")
get_fulltext(source={"kind":"pmcid","value":"PMC7096777"}, sections="introduction,results")

# 找出文章提到的所有基因
get_text_mined_terms(source={"kind":"pmid","value":"12345678"}, semantic_type="GENE_PROTEIN")
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

搜尋結果會自動暫存在 session 中，不需要記住所有 PMID！所有讀取都走唯一的
`read_session(request={...})`，每個 action 只接受自己的欄位：

- `read_session(request={"action":"pmids","search_index":-1})`: 取得指定搜尋的 PMID 列表
- `read_session(request={"action":"article","pmid":"12345678"})`: 從快取取得文章詳情 (不消耗 API)
- `read_session(request={"action":"summary"})`: 查看 session 狀態和可用資料
- `read_session(request={"action":"log"})`: 查看 activity log 與搜尋歷史摘要

### Research Artifact Envelope
- `unified_search` returns a compact answer plus `artifact_summary` / `artifact`
  when durable artifacts were written. The response summary should be detailed
  enough to answer the user immediately.
- The artifact locator includes `artifact_id`, `artifact_uri`,
  `primary_file`, `read_order`, audit status, file inventory, and
  `read_session(...)` retrieval hints.
- Use `read_session(request={"action":"artifact","locator":{"kind":"artifact_uri","value":"artifact://session-123/artifact-123"}})` or
  `read_session(request={"action":"artifact","locator":{"kind":"artifact_id","value":"artifact-123"}})` to page through complete
  evidence without filling the MCP response token budget.
- For `unified_search`, read `audit.json` first to check source-count and
  completeness warnings, then `query_strategy.json`, then `results.json` or
  `results.toon` for the full record list.
- `read_session` redacts `local_path` and `manifest_path` by default. Set
  `PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS=true` only for local MCP clients that
  should receive server-local paths.
- Large `get_fulltext` responses may return an inline preview when an artifact
  exists; use the locator to retrieve the saved full content.
- When replying to users, mention the summary and tell them that full artifacts
  are available for deeper inspection.

### 快捷用法
- `pmids="last"` - 在 prepare_export, get_citation_metrics 等工具中使用
- `read_session(request={"action":"pmids"})` 回傳 `pmids_csv` 可直接複製使用

═══════════════════════════════════════════════════════════════════════════════
🔧 所有可用工具
═══════════════════════════════════════════════════════════════════════════════

### 搜尋工具
- unified_search: Unified Search - Single entry point for multi-source academic search.

### 查詢智能
- validate_pico_plan: Validate agent-provided P/I/C/O and return a runnable PICO pipeline.
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
- read_session: Read session data through one schema-exact discriminated request.

### 機構訂閱
- configure_institutional_access: Configure your institution's link resolver for full-text access.
- get_institutional_link: Generate institutional access link (OpenURL) for an article.
- list_resolver_presets: List available institutional link resolver presets.
- test_institutional_access: Test your institutional link resolver configuration.
- diagnose_institutional_access: Diagnose why institutional fulltext access succeeds or fails for an article.

### 視覺搜索
- prepare_figure_search: Analyze a scientific figure or image for literature search.

### ICD 轉換
- convert_icd_mesh: Query the curated ICD/MeSH crosswalk in one explicit direction.

### 引用驗證
- verify_reference_list: Verify a plain-text reference list against PubMed evidence.

### 圖表擷取
- get_article_figures: Get structured figure metadata (label, caption, image URL) and PDF links from a PMC Open Access arti

### 研究編年史
- build_research_chronicle: Build a persisted, versioned, evidence-backed Research Chronicle.
- read_research_chronicle: Read stored Research Chronicles: load, list, diff, narrate, analyze, compare.

### 圖片搜尋
- search_biomedical_images: Search biomedical images from NLM Open-i.

### Pipeline 管理
- save_pipeline: Save a pipeline configuration for later reuse.
- list_pipelines: List all saved pipeline configurations.
- load_pipeline: Load a pipeline configuration for review or editing.
- delete_pipeline: Permanently delete a saved pipeline configuration and execution history.
- get_pipeline_history: Get execution history for a saved pipeline.
- schedule_pipeline: Schedule a saved pipeline for periodic execution.
- unschedule_pipeline: Remove the active schedule for a saved pipeline.

NOTE: 搜尋結果自動暫存，使用 session 工具可隨時取回，不需依賴 Agent 記憶。

NOTE: 每次搜尋結果會顯示各來源的 API 回傳量（如 **Sources**: pubmed (8/500), openalex (5)）。
這些數字是實際回傳數與可得的 provider 匹配總數。未知總數、來源失敗與部分結果須另外查看；它們不是以完整 ground truth 計算的 recall。

═══════════════════════════════════════════════════════════════════════════════
💡 進階使用提示
═══════════════════════════════════════════════════════════════════════════════

1. **Chronicle + Citation Tree 組合**：先用 build_research_chronicle(output="tree")
   看研究脈絡，再用 build_citation_tree 深入探索關鍵論文的引用網絡。

2. **多源資料核對**：比對不同來源的識別碼、日期與引用資訊；多來源收錄數不等於
   科學重要性或研究品質，heuristic 排名仍需要人工評讀。

3. **Research Lineage Tree 適合**：藥物開發歷程、技術演化追蹤、
   文獻回顧的結構化整理。

4. **Mermaid 預覽**：`output="mermaid"` 會產生橫向時序主軸與研究分支，並經
   結構驗證、自動修正與安全降階，可直接在 VS Code 或 GitHub Markdown 中預覽。
"""

__all__ = ["SERVER_INSTRUCTIONS"]
