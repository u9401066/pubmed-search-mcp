# PubMed Search MCP - Tools Index

Quick reference for all 40 available MCP tools. Auto-generated from `tool_registry.py`.

---

## 搜尋工具
*文獻搜索入口*

| Tool | Description |
|------|-------------|
| `unified_search` | Unified Search - Single entry point for multi-source academic search. |

## 查詢智能
*MeSH 擴展、PICO 解析*

| Tool | Description |
|------|-------------|
| `parse_pico` | Parse a clinical question into PICO elements OR accept pre-parsed PICO. |
| `generate_search_queries` | Gather search intelligence for a topic - returns RAW MATERIALS for Agent to decide. |
| `analyze_search_query` | Analyze a search query without executing the search. |

## 文章探索
*相關文章、引用網路*

| Tool | Description |
|------|-------------|
| `fetch_article_details` | Fetch detailed information for one or more PubMed articles. |
| `find_related_articles` | Find articles related to a given PubMed article. |
| `find_citing_articles` | Find articles that cite a given PubMed article. |
| `get_article_references` | Get the references (bibliography) of a PubMed article. |
| `get_citation_metrics` | Get citation metrics from NIH iCite for articles. |

## 全文工具
*全文取得與文本挖掘*

| Tool | Description |
|------|-------------|
| `get_fulltext` | Enhanced multi-source fulltext retrieval. |
| `get_text_mined_terms` | Get text-mined annotations from Europe PMC. |

## NCBI 延伸
*Gene, PubChem, ClinVar*

| Tool | Description |
|------|-------------|
| `search_gene` | Search NCBI Gene database for gene information. |
| `get_gene_details` | Get detailed information about a gene by NCBI Gene ID. |
| `get_gene_literature` | Get PubMed articles linked to a gene. |
| `search_compound` | Search PubChem for chemical compounds. |
| `get_compound_details` | Get detailed information about a compound by PubChem CID. |
| `get_compound_literature` | Get PubMed articles linked to a compound. |
| `search_clinvar` | Search ClinVar for clinical variants. |

## 引用網絡
*引用樹建構與探索*

| Tool | Description |
|------|-------------|
| `build_citation_tree` | Build a citation tree (network) from a single article. |
| `suggest_citation_tree` | After fetching article details, suggest whether to build a citation tree. |

## 匯出工具
*引用格式匯出*

| Tool | Description |
|------|-------------|
| `prepare_export` | Export citations to reference manager formats. |

## Session 管理
*PMID 暫存與歷史*

| Tool | Description |
|------|-------------|
| `get_session_pmids` | 取得 session 中暫存的 PMID 列表。 |
| `list_search_history` | 列出搜尋歷史，方便回顧和取得特定搜尋的 PMIDs。 |
| `get_cached_article` | 從 session 快取取得文章詳情。 |
| `get_session_summary` | 取得當前 session 的摘要資訊。 |

## 機構訂閱
*OpenURL Link Resolver*

| Tool | Description |
|------|-------------|
| `configure_institutional_access` | Configure your institution's link resolver for full-text access. |
| `get_institutional_link` | Generate institutional access link (OpenURL) for an article. |
| `list_resolver_presets` | List available institutional link resolver presets. |
| `test_institutional_access` | Test your institutional link resolver configuration. |

## 視覺搜索
*圖片分析與搜索 (實驗性)*

| Tool | Description |
|------|-------------|
| `analyze_figure_for_search` | Analyze a scientific figure or image for literature search. |
| `reverse_image_search_pubmed` | Reverse image search for scientific literature. |

## ICD 轉換
*ICD-10 與 MeSH 轉換*

| Tool | Description |
|------|-------------|
| `convert_icd_to_mesh` | Convert ICD-9 or ICD-10 code to MeSH term for PubMed search. |
| `convert_mesh_to_icd` | Convert MeSH term to ICD-9 and ICD-10 codes. |
| `search_by_icd` | Search PubMed using ICD code (auto-converts to MeSH). |

## 研究時間軸
*研究演化追蹤與里程碑偵測*

| Tool | Description |
|------|-------------|
| `build_research_timeline` | Build a research timeline for a topic showing key milestones. |
| `get_timeline_visualization` | Generate timeline visualization code. |
| `analyze_timeline_milestones` | Analyze milestone distribution for a research topic. |
| `compare_timelines` | Compare research timelines of multiple topics. |
| `list_milestone_patterns` | List all milestone detection patterns. |
| `build_timeline_from_pmids` | Build a timeline from a specific list of PMIDs. |

---

## 檔案結構

```
mcp_server/
├── server.py           # Server 創建與配置
├── instructions.py     # AI Agent 使用說明
├── tool_registry.py    # 工具註冊中心
├── session_tools.py    # Session 管理工具
├── resources.py        # MCP Resources
├── prompts.py          # MCP Prompts
├── TOOLS_INDEX.md      # 本檔案 (工具索引)
└── tools/              # 工具實作
    ├── __init__.py     # 統一入口
    ├── _common.py      # 共用工具函數
    ├── unified.py      # unified_search
    ├── discovery.py    # 搜尋與探索
    ├── strategy.py     # MeSH/查詢策略
    ├── pico.py         # PICO 解析
    ├── export.py       # 匯出工具
    ├── europe_pmc.py   # Europe PMC 全文
    ├── core.py         # CORE 開放取用
    ├── ncbi_extended.py # Gene/PubChem/ClinVar
    ├── citation_tree.py # 引用網路
    ├── openurl.py      # 機構訂閱
    ├── vision_search.py # 視覺搜索
    └── icd.py          # ICD 轉換工具
```

---

*Total: 40 tools in 12 categories*
*Last updated: 2026-02-05 (auto-generated by scripts/count_mcp_tools.py)*