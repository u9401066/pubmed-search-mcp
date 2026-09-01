# PubMed Search MCP - Tools Index

Quick reference for all 41 available MCP tools. Auto-generated from `tool_registry.py`.

Use `docs/TOOLS_USAGE_GUIDE.md` for the capability-first usage manual, not just the raw inventory.

---

## Capability Compression

The current surface is 41 tools, but the practical comprehension model is 8 capability families.

- Theoretical lower bound without removing capability: 6 multiplexed meta-tools
- Practical minimum for human/agent understanding: 8 capability families
- Recommended reading order: capability guide first, inventory second

## 搜尋工具

Unified multi-source literature search gateway

| Tool | Description |
| --- | --- |
| `unified_search` | Unified Search - Single entry point for multi-source academic search. |

## 查詢智能

MeSH expansion, agent-provided PICO handoff, and query analysis

| Tool | Description |
| --- | --- |
| `validate_pico_plan` | Validate agent-provided P/I/C/O and return a runnable PICO pipeline. |
| `generate_search_queries` | Gather search intelligence for a topic - returns RAW MATERIALS for Agent to decide. |
| `analyze_search_query` | Analyze a search query without executing the search. |

## 文章探索

相關文章、引用網路

| Tool | Description |
| --- | --- |
| `fetch_article_details` | Fetch detailed information for one or more PubMed articles. |
| `find_related_articles` | Find articles related to a given PubMed article. |
| `find_citing_articles` | Find articles that cite a given PubMed article. |
| `get_article_references` | Get the references (bibliography) of a PubMed article. |
| `get_citation_metrics` | Get citation metrics from NIH iCite for articles. |

## 全文工具

全文取得與文本挖掘

| Tool | Description |
| --- | --- |
| `get_fulltext` | Enhanced multi-source fulltext retrieval. |
| `get_text_mined_terms` | Get text-mined annotations from Europe PMC. |

## NCBI 延伸

Gene, PubChem, ClinVar

| Tool | Description |
| --- | --- |
| `search_gene` | Search NCBI Gene database for gene information. |
| `get_gene_details` | Get detailed information about a gene by NCBI Gene ID. |
| `get_gene_literature` | Get PubMed articles linked to a gene. |
| `search_compound` | Search PubChem for chemical compounds. |
| `get_compound_details` | Get detailed information about a compound by PubChem CID. |
| `get_compound_literature` | Get PubMed articles linked to a compound. |
| `search_clinvar` | Search ClinVar for clinical variants. |

## 引用網絡

引用樹建構與探索

| Tool | Description |
| --- | --- |
| `build_citation_tree` | Build a citation tree (network) from a single article. |

## 匯出工具

引用格式匯出與本機文獻筆記保存

| Tool | Description |
| --- | --- |
| `prepare_export` | Export citations to reference manager formats. |
| `save_literature_notes` | Save searched articles as guided local wiki/Foam/Markdown notes. |

## Session 管理

PMID 暫存與歷史

| Tool | Description |
| --- | --- |
| `read_session` | Read session data through one schema-exact discriminated request. |

## 機構訂閱

OpenURL Link Resolver

| Tool | Description |
| --- | --- |
| `configure_institutional_access` | Configure your institution's link resolver for full-text access. |
| `get_institutional_link` | Generate institutional access link (OpenURL) for an article. |
| `list_resolver_presets` | List available institutional link resolver presets. |
| `test_institutional_access` | Test your institutional link resolver configuration. |
| `diagnose_institutional_access` | Diagnose why institutional fulltext access succeeds or fails for an article. |

## 視覺搜索

圖片分析與搜索 (實驗性)

| Tool | Description |
| --- | --- |
| `prepare_figure_search` | Analyze a scientific figure or image for literature search. |

## ICD 轉換

ICD-10 與 MeSH 轉換

| Tool | Description |
| --- | --- |
| `convert_icd_mesh` | Query the curated ICD/MeSH crosswalk in one explicit direction. |

## 引用驗證

Reference list verification with PubMed evidence

| Tool | Description |
| --- | --- |
| `verify_reference_list` | Verify a plain-text reference list against PubMed evidence. |

## 圖表擷取

文章圖表與視覺資料擷取

| Tool | Description |
| --- | --- |
| `get_article_figures` | Get structured figure metadata (label, caption, image URL) and PDF links from a PMC Open Access arti |

## 研究編年史

研究演化脈絡：持久化、可版本比對、證據支撐的時序主軸與分支投影

| Tool | Description |
| --- | --- |
| `build_research_chronicle` | Build a persisted, versioned, evidence-backed Research Chronicle. |
| `read_research_chronicle` | Read stored Research Chronicles: load, list, diff, narrate, analyze, compare. |

## 圖片搜尋

生物醫學圖片搜尋

| Tool | Description |
| --- | --- |
| `search_biomedical_images` | Search biomedical images from NLM Open-i. |

## Pipeline 管理

Pipeline 持久化、載入、排程

| Tool | Description |
| --- | --- |
| `save_pipeline` | Save a pipeline configuration for later reuse. |
| `list_pipelines` | List all saved pipeline configurations. |
| `load_pipeline` | Load a pipeline configuration for review or editing. |
| `delete_pipeline` | Permanently delete a saved pipeline configuration and execution history. |
| `get_pipeline_history` | Get execution history for a saved pipeline. |
| `schedule_pipeline` | Schedule a saved pipeline for periodic execution. |
| `unschedule_pipeline` | Remove the active schedule for a saved pipeline. |

---

## 檔案結構

```text
mcp_server/
├── TOOLS_INDEX.md
├── __init__.py
├── __main__.py
├── auth.py
├── http_cli.py
├── http_compat.py
├── http_security.py
├── instructions.py
├── prompts.py
├── resources.py
├── server.py
├── session_tools.py
├── tenancy.py
├── tool_contracts.py
├── tool_registry.py
└── tools/
    ├── __init__.py
    ├── _common.py
    ├── agent_output.py
    ├── article_source.py
    ├── artifact_memory.py
    ├── chronicle.py
    ├── citation_tree.py
    ├── discovery.py
    ├── europe_pmc.py
    ├── export.py
    ├── figure_tools.py
    ├── icd.py
    ├── image_search.py
    ├── ncbi_extended.py
    ├── openurl.py
    ├── pico.py
    ├── pipeline_tools.py
    ├── reference_verification.py
    ├── search_run_journal.py
    ├── strategy.py
    ├── tool_input.py
    ├── tool_response.py
    ├── tool_runtime.py
    ├── tool_session.py
    ├── unified.py
    ├── unified_formatting.py
    ├── unified_pipeline.py
    ├── unified_runner.py
    └── vision_search.py
```

---

*Total: 41 tools in 16 categories*
*Auto-generated by `scripts/count_mcp_tools.py --update-docs`*
