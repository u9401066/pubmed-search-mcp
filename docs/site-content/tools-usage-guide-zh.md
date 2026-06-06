<!-- Generated from docs/TOOLS_USAGE_GUIDE.zh-TW.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# PubMed Search MCP 工具使用指南

這是一份能力導向指南，目標是讓 agent 和使用者不用死背 46 個 MCP tool，也能穩定選到正確流程。

**語言**: [English](#/tools-usage-guide) | **繁體中文**

## 閱讀順序

1. 先用使用者意圖對應能力族。
2. 用 session tools 取回上一輪結果，不要要求模型記住所有 PMID。
3. 先確認 evidence set，再匯出引用或本機筆記。
4. 需要查精確工具名時，再看[完整工具索引](#/quick-reference)。

## 8 個能力族

![PubMed Search MCP 能力族地圖](images/tool-capability-map.svg)

| 能力 | 主要工具 | 何時使用 |
| --- | --- | --- |
| 搜尋入口 | `unified_search` | 使用者要找論文、文章、或先對主題做第一輪搜尋。 |
| 查詢智能 | `analyze_search_query`, `parse_pico`, `generate_search_queries` | 需要 MeSH、agent-provided PICO handoff、同義詞擴展、或搜尋策略。 |
| 論文探索 | `fetch_article_details`, `find_related_articles`, `find_citing_articles`, `get_article_references`, `build_citation_tree` | 已有 seed PMID，要查脈絡、相關研究、引用網路。 |
| 全文與圖表 | `get_fulltext`, `get_text_mined_terms`, `get_article_figures` | 需要文章段落、證據區段、實體標註、caption 或 image URL。 |
| 外部生醫資料 | `search_gene`, `get_gene_details`, `search_compound`, `get_compound_details`, `search_clinvar` | 問題從文獻延伸到 NCBI gene、compound、clinical variant。 |
| 評估與時間軸 | `get_citation_metrics`, `build_research_timeline`, `analyze_timeline_milestones`, `compare_timelines` | 使用者問哪些重要、領域如何演進、或多主題比較。 |
| 持久化與 session | `read_session`, `get_session_pmids`, `get_cached_article`, `get_session_summary`, pipeline tools | 使用者要恢復、重跑、審計、排程、保存搜尋流程。 |
| 匯出與本機筆記 | `prepare_export`, `save_literature_notes` | 使用者要 Zotero/EndNote/BibTeX，或本機 Markdown/wiki 筆記。 |

## 意圖路由

| 使用者意圖 | 建議流程 |
| --- | --- |
| 快速搜尋文獻 | `unified_search(query=..., limit=...)` |
| 臨床 A vs B 比較 | Agent P/I/C/O -> `parse_pico` -> `unified_search(pipeline="template: pico...")` |
| 系統性回顧起手式 | `analyze_search_query` -> `generate_search_queries` -> `unified_search` -> `save_pipeline` |
| 深挖重要論文 | `fetch_article_details` -> `find_related_articles` / `find_citing_articles` / `get_article_references` |
| 全文 synthesis | `get_fulltext` -> `get_text_mined_terms` -> 結構化摘要 |
| Zotero handoff | `prepare_export(pmids="last", format="ris")` 或 Zotero Keeper import tools |
| 本機知識庫筆記 | `save_literature_notes(pmids="last")` |
| 可重複搜尋流程 | `save_pipeline` -> `unified_search(pipeline="saved:<name>")` |

Zotero Keeper 應維持在外部整合邊界。PubMed Search MCP 負責產生 official RIS/MEDLINE/CSL JSON、local RIS/BibTeX/CSV/MEDLINE/JSON 匯出與本機 wiki notes；Zotero 匯入、duplicate 處理、library-specific policy 交給 Zotero Keeper 或其他 client。

## 能力工作流程圖

每個功能族都補上 workflow 圖，讓使用者與開發者能看出工具在完整研究流程中的位置。

### 搜尋入口與查詢智能

![搜尋與查詢智能流程](images/search-query-workflow.svg)

這條路徑涵蓋 `unified_search`、`parse_pico`、`generate_search_queries`、`analyze_search_query` 與 ICD-aware search preparation。重點邊界是：agent 負責語意上的 PICO 抽取，`parse_pico` 驗證結構化 handoff 並回傳後端 `template: pico` pipeline。

### 論文探索與引用脈絡

![論文探索與引用流程](images/discovery-citation-workflow.svg)

已有 seed PMID 後使用這條路徑。它涵蓋 `fetch_article_details`、`find_related_articles`、`find_citing_articles`、`get_article_references`、`build_citation_tree` 與 `get_citation_metrics`。

### 引用驗證

![引用驗證流程](images/reference-verification-workflow.svg)

當 manuscript、bibliography 或 agent 產生的回答需要 PubMed-backed citation checking 時，使用 `verify_reference_list`。match / mismatch 應視為 audit trail，而不是只看生成摘要。

### 全文、圖表與圖片證據

![全文、圖表與生醫圖片流程](images/visual-evidence-workflow.svg)

這條路徑涵蓋 `get_fulltext`、`get_text_mined_terms`、`get_article_figures`、`analyze_figure_for_search` 與 `search_biomedical_images`。全文、figure metadata、image search 是不同證據通道，各自有不同可得性限制。

當使用者提供 image URL 或上傳圖片 payload，且需要 agent 從視覺內容推論搜尋詞時，使用 `analyze_figure_for_search`。這個 tool 會回傳 MCP `ImageContent`；實際圖片語意解讀由 LLM agent 完成，agent 應接續呼叫 `search_biomedical_images` 或 `unified_search`。

當視覺問題已經文字化時，直接用 `search_biomedical_images`。目前主要來源是 Open-i，支援 `image_type`、`collection`、`article_type`、`specialty`、`license_type`、`search_fields` 等 filter，且需要英文醫學術語。

### 外部生醫資料

![NCBI 延伸生醫資料流程](images/ncbi-extended-workflow.svg)

當問題從文獻延伸到 NCBI biomedical records 時，使用 `search_gene`、`get_gene_details`、`get_gene_literature`、`search_compound`、`get_compound_details`、`get_compound_literature` 與 `search_clinvar`。

### 評估、時間軸與比較

![評估與時間軸流程](images/timeline-evaluation-workflow.svg)

使用者問「哪些重要」、「領域何時改變」、「不同主題如何分歧」時，使用 `get_citation_metrics`、`build_research_timeline`、`analyze_timeline_milestones` 與 `compare_timelines`。

`build_research_timeline` 是目前的 timeline / lineage-tree 工具。它接受 `topic=...` 或明確的 comma-separated `pmids=...`，會偵測 milestone-like papers，並可回傳 `text`、`tree`、`mermaid`、`mindmap`、`json`、`json_tree`、`timeline_js` 或 `d3`。`analyze_timeline_milestones` 用於里程碑分佈 diagnostics；`compare_timelines` 用於最多五個 topic tracks 的比較。

用詞請保持精準：

- **Timeline**：按時間排序的 milestone projection。
- **Lineage tree**：由 timeline events 分支而成的主題樹。
- **Context graph preview**：`unified_search(options="context_graph")`，只根據本次 PMID-backed ranked set 產生輕量預覽。
- **Citation tree**：`build_citation_tree`，從單一 seed PMID 建立 forward/backward citation network。
- **Research Chronicle**：規劃中的持久化、版本化 artifact；詳見 [Research Chronicle Rebuild Spec](#/research-chronicle-rebuild-spec)。

### Session、Pipeline 與排程重用

![Session 與 Pipeline 流程](images/session-pipeline-workflow.svg)

這條路徑涵蓋 `read_session`、`get_session_pmids`、`get_cached_article`、`get_session_summary`、`get_session_log`、`manage_pipeline`、`save_pipeline`、`list_pipelines`、`load_pipeline`、`delete_pipeline`、`get_pipeline_history` 與 `schedule_pipeline`。

### 機構存取

![機構存取流程](images/institutional-access-workflow.svg)

這條路徑涵蓋 `configure_institutional_access`、`get_institutional_link`、`list_resolver_presets`、`test_institutional_access` 與 `diagnose_institutional_access`。OpenURL 是 browser handoff；direct DOI 與 EZproxy 只有在環境已設定、且使用者有權存取時才是 agent-fetchable。

### 匯出與本機筆記

![匯出與本機筆記流程](images/export-notes-workflow.svg)

這條路徑涵蓋 `prepare_export` 與 `save_literature_notes`。Citation exports 供 reference manager 使用；local notes 則是帶有 machine-readable metadata、可被人與 agent 後續編輯的 literature-review artifacts。

## 大型輸出的持久化 Query Memory

當 session persistence 已設定時，`unified_search` 與 `get_fulltext` 會把完整可重用輸出保存為 artifact，tool response 只回傳精簡 locator。請把 tool response 視為索引卡：它會有足夠的 counts、warnings 與 artifact hints 讓 agent 先回覆使用者；完整 evidence payload 則留在可重複讀取的 artifact files。Remote client 請透過 `read_session` facade 讀取；只有本機 MCP client 真的需要 server path 時，才設定 `PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS=true`：

```python
read_session(action="list_artifacts")
read_session(action="artifact", artifact_id="...")
read_session(action="artifact", artifact_uri="artifact://...")
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="audit.json")
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="results.json", offset=0, max_chars=200000)
```

`unified_search` artifacts 會使用 research envelope。建議先讀 `audit.json` 確認完整性警告，再讀 `query_strategy.json` 檢查實際搜尋策略，最後用 `results.json` / `results.toon` 取回完整結果清單。這樣不需要把長篇 article list 塞進 MCP response token，也保留可審計、可重現的搜尋紀錄。

`local_path` 與 `manifest_path` 是 MCP server host 上的路徑，預設會被遮蔽。大型 `get_fulltext` 在已有 artifact 時會先回 inline preview；完整內容請用 locator 讀取。這就是持久化 query memory：agent 可以用 artifact ID 重新打開同一份已保存的 search/fulltext output，不必重跑外部來源呼叫。全文 artifact 可能包含文章正文，保存與分享時請遵守 publisher license 與機構授權條款。

## 本機 Wiki Note 匯出

![匯出與本機筆記流程](images/export-notes-workflow.svg)

搜尋完成後，如果使用者要留下受指引、半格式化、可被 agent 繼續編輯的檔案，使用 `save_literature_notes`。這比讓 agent 用一般 write file 自己拼 Markdown 穩定。

預設呼叫：

```python
save_literature_notes(pmids="last")
```

預設 `note_format` 是 `wiki`，每篇文章會輸出一個 `.md`，包含：

- YAML frontmatter：title、PMID、DOI、PMCID、journal、year、citation key、aliases、tags
- 產生 index note 時使用 Foam-compatible wikilinks
- wiki/Foam link target 使用 PMID、DOI、PMCID 或 fallback identifier；title 只作為 link label 與 alias
- 回應會包含 `wiki_validation`，列出產生的 wikilinks 與 unresolved targets
- triage 欄位：status、relevance、decision
- summary、key findings、methods/population、limitations、follow-up questions
- PubMed、DOI、PMC source links
- 預設會在 notes 或 index artifacts 建立時寫出 collection-level `references.csl.json` sidecar，方便接引用管理器

當 `unified_search` 回傳 PMID-backed results 時，next-tool suggestions 會主動包含：

```python
save_literature_notes(pmids="last", note_format="wiki")
```

這讓 agent 能直接交接到本機 LLM wiki，不需要自己從搜尋結果發明檔名或 wikilink。

支援格式：

| Format | 連結樣式 | 排版 | 適合情境 |
| --- | --- | --- | --- |
| `wiki` | `[[stable-id|title]]` | 預設 guided literature note | Foam、Obsidian-style、一般 wiki workflow |
| `foam` | `[[stable-id|title]]` | 與 `wiki` 相容 | 既有 Foam 使用者 |
| `markdown` | `[title](note.md)` | 同樣 guided sections | 純 Markdown repo |
| `medpaper` | `[[citation_key|title]]` | per-reference directory，內含 `<citation_key>.md` 與 `metadata.json` | MedPaper-style 或 Zotero Keeper-compatible reference library |

目錄解析順序：

1. `output_dir`
2. `PUBMED_NOTES_DIR`
3. `PUBMED_WORKSPACE_DIR/references`
4. `PUBMED_DATA_DIR/references`
5. `~/.pubmed-search-mcp/references`

## 好的 Markdown 文獻筆記排版

好的文獻筆記要把「可驗證書目資料」和「人/agent 的判讀」分開：

```markdown
---
title: "Article title"
pmid: "12345678"
doi: "10.xxxx/example"
citation_key: "smith2024_12345678"
source: "PubMed"
note_format: "wiki"
tags: ["literature", "pubmed"]
aliases: ["smith2024_12345678", "Article title", "12345678", "Smith 2024"]
---

# Article title

## Metadata
- PMID: [12345678](https://pubmed.ncbi.nlm.nih.gov/12345678/)
- DOI: [10.xxxx/example](https://doi.org/10.xxxx/example)
- Journal: Journal name
- Year: 2024
- Authors: Smith J; Doe J

## Triage
- Status:
- Relevance:
- Decision:

## Summary
-

## Key Findings
-

## Methods And Population
-

## Limitations
-

## Follow Up Questions
-

## Citation
- Smith J; Doe J. Article title. Journal name. 2024. doi:10.xxxx/example
```

frontmatter 和 sidecar 放 verified metadata；正文區塊留給摘要、判讀、限制、後續問題。

## 自訂 Template

使用者有自己的排版時，用 `template_file`：

```python
save_literature_notes(
    pmids="last",
    output_dir="./references",
    template_file="./reference-template.md"
)
```

可用 placeholder 包含 `{title}`, `{pmid}`, `{doi}`, `{pmc_id}`, `{journal}`, `{journal_abbrev}`, `{year}`, `{volume}`, `{issue}`, `{pages}`, `{authors}`, `{abstract}`, `{citation_key}`, `{reference_id}`, `{note_format}`, `{created}`, `{pubmed_url}`, `{doi_url}`, `{citation}`, `{keywords}`, `{mesh_terms}`, `{csl_json}`。

## Pipeline 與 Agent Bundle 參考文件

Pipeline tutorial 的正式來源是：

- `docs/PIPELINE_MODE_TUTORIAL.en.md`
- `docs/PIPELINE_MODE_TUTORIAL.md`

`scripts/build_docs_site.py` 會另外同步到 `.claude/skills/pipeline-persistence/references/`，讓不會打包 `docs/site-content/` 的外部 agent bundle 或 VSIX 也能讀到。
