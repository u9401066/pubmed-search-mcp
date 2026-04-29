# PubMed Search MCP 工具使用指南

這是一份能力導向指南，目標是讓 agent 和使用者不用死背 45 個 MCP tool，也能穩定選到正確流程。

## 閱讀順序

1. 先用使用者意圖對應能力族。
2. 用 session tools 取回上一輪結果，不要要求模型記住所有 PMID。
3. 先確認 evidence set，再匯出引用或本機筆記。
4. 需要查精確工具名時，再看[完整工具索引](../src/pubmed_search/presentation/mcp_server/TOOLS_INDEX.md)。

## 8 個能力族

| 能力 | 主要工具 | 何時使用 |
| --- | --- | --- |
| 搜尋入口 | `unified_search` | 使用者要找論文、文章、或先對主題做第一輪搜尋。 |
| 查詢智能 | `analyze_search_query`, `parse_pico`, `generate_search_queries` | 需要 MeSH、PICO、同義詞擴展、或搜尋策略。 |
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
| 臨床 A vs B 比較 | `parse_pico` -> `generate_search_queries` -> `unified_search` |
| 系統性回顧起手式 | `analyze_search_query` -> `generate_search_queries` -> `unified_search` -> `save_pipeline` |
| 深挖重要論文 | `fetch_article_details` -> `find_related_articles` / `find_citing_articles` / `get_article_references` |
| 全文 synthesis | `get_fulltext` -> `get_text_mined_terms` -> 結構化摘要 |
| Zotero handoff | `prepare_export(pmids="last", format="ris")` 或 Zotero Keeper import tools |
| 本機知識庫筆記 | `save_literature_notes(pmids="last")` |
| 可重複搜尋流程 | `save_pipeline` -> `unified_search(pipeline="saved:<name>")` |

Zotero Keeper 應維持在外部整合邊界。PubMed Search MCP 負責產生 RIS/CSL/JSON 匯出與本機 wiki notes；Zotero 匯入、duplicate 處理、library-specific policy 交給 Zotero Keeper 或其他 client。

## 本機 Wiki Note 匯出

搜尋完成後，如果使用者要留下受指引、半格式化、可被 agent 繼續編輯的檔案，使用 `save_literature_notes`。這比讓 agent 用一般 write file 自己拼 Markdown 穩定。

預設呼叫：

```python
save_literature_notes(pmids="last")
```

預設 `note_format` 是 `wiki`，每篇文章會輸出一個 `.md`，包含：

- YAML frontmatter：title、PMID、DOI、PMCID、journal、year、citation key、aliases、tags
- 產生 index note 時使用 Foam-compatible wikilinks
- triage 欄位：status、relevance、decision
- summary、key findings、methods/population、limitations、follow-up questions
- PubMed、DOI、PMC source links
- CSL JSON sidecar，方便接引用管理器

支援格式：

| Format | 連結樣式 | 排版 | 適合情境 |
| --- | --- | --- | --- |
| `wiki` | `[[note|title]]` | 預設 guided literature note | Foam、Obsidian-style、一般 wiki workflow |
| `foam` | `[[note|title]]` | 與 `wiki` 相容 | 既有 Foam 使用者 |
| `markdown` | `[title](note.md)` | 同樣 guided sections | 純 Markdown repo |
| `medpaper` | `[[citation_key|title]]` | verified reference note + `metadata.json` | MedPaper-style 或 Zotero Keeper-compatible reference library |

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
aliases: ["smith2024_12345678", "12345678", "Smith 2024"]
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

可用 placeholder 包含 `{title}`, `{pmid}`, `{doi}`, `{pmc_id}`, `{journal}`, `{year}`, `{authors}`, `{abstract}`, `{citation_key}`, `{reference_id}`, `{note_format}`, `{created}`, `{pubmed_url}`, `{doi_url}`, `{citation}`, `{keywords}`, `{mesh_terms}`, `{csl_json}`。

## Pipeline 與 Agent Bundle 參考文件

Pipeline tutorial 的正式來源是：

- `docs/PIPELINE_MODE_TUTORIAL.en.md`
- `docs/PIPELINE_MODE_TUTORIAL.md`

`scripts/build_docs_site.py` 會另外同步到 `.claude/skills/pipeline-persistence/references/`，讓不會打包 `docs/site-content/` 的外部 agent bundle 或 VSIX 也能讀到。
