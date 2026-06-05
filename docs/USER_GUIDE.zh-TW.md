# PubMed Search MCP 使用者指南

這份指南給透過 VS Code、Claude Desktop、Claude Code、Cursor、Cline、Zed 或 Copilot Studio 使用 PubMed Search MCP 的使用者。它說明如何從研究問題一路走到可重用的證據輸出，而不是要求你背下所有 MCP tool。

需要精確工具名稱時，再搭配 [工具使用指南](TOOLS_USAGE_GUIDE.zh-TW.md) 與 [完整工具索引](../src/pubmed_search/presentation/mcp_server/TOOLS_INDEX.md)。

## 這個 Server 適合做什麼

PubMed Search MCP 是面向 AI agent 的文獻研究 server。它最擅長的不是單次呼叫 PubMed，而是讓 AI client 規劃並執行一段 biomedical literature workflow。

典型任務：

- 把臨床或生醫問題轉成 PubMed 可用的搜尋策略
- 透過 `unified_search` 搜尋多個學術來源
- 追 seed paper、相關文章、引用文章、參考文獻與 citation tree
- 在可用時取得全文、text-mined terms、文章圖表與 open-access image links
- 匯出引用檔或保存本機 Markdown/wiki notes
- 保存、檢視、重跑或排程可重複的研究 pipeline

它不取代人的判讀、機構授權政策、systematic review protocol 設計，也不提供臨床決策。

## 設定檢查表

最低限度本機啟動：

```bash
uvx pubmed-search-mcp
```

最低必要環境變數：

```bash
NCBI_EMAIL=your@email.com
```

`NCBI_EMAIL` 是 NCBI API policy 需要的使用者識別。需要較高 NCBI rate limit 時再加 `NCBI_API_KEY`。其他來源的 key 只有在你使用那些來源時才需要。

常見可選值：

```bash
NCBI_API_KEY=your_ncbi_api_key
CORE_API_KEY=your_core_api_key
CROSSREF_EMAIL=your@email.com
UNPAYWALL_EMAIL=your@email.com
PUBMED_NOTES_DIR=/path/to/references
```

各 client 的設定方式請看 [整合指南](INTEGRATIONS.md)。HTTP、Docker、Copilot Studio 與 GitHub Pages 部署請看 [部署文件](../DEPLOYMENT.md)。

## 先選對路徑

![PubMed Search MCP 研究工作流](images/research-workflow.svg)

| 目標 | 從這裡開始 | 接著使用 |
| --- | --- | --- |
| 快速找文獻 | `unified_search` | `fetch_article_details`, `read_session` |
| 臨床問題 | Agent 抽出 P/I/C/O 後呼叫 `parse_pico` | `generate_search_queries`, `unified_search` |
| 改善太吵或太窄的 query | `analyze_search_query` | `generate_search_queries`, `unified_search` |
| 從重要文章往外探索 | `fetch_article_details` | `find_related_articles`, `find_citing_articles`, `get_article_references`, `build_citation_tree` |
| 閱讀更深層證據 | `get_fulltext` | `get_text_mined_terms`, `get_article_figures` |
| 從視覺證據搜尋 | `analyze_figure_for_search` | `search_biomedical_images`, `unified_search` |
| 建立研究脈絡年表 | `build_research_timeline` | `analyze_timeline_milestones`, `compare_timelines` |
| 重新讀取大型輸出 | `read_session(action="artifact")` | `read_session(action="list_artifacts")` |
| 建立本機文獻庫 | `prepare_export` | `save_literature_notes` |
| 重用工作流 | `manage_pipeline` | `save_pipeline`, `load_pipeline`, `schedule_pipeline` |

最重要的規則是：先看研究意圖，不要先看工具清單。

`unified_search` 的參數刻意設計成 agent-friendly strings。`sources`、`filters` 與 `options` 請使用 comma-separated values，不要傳 JSON object。例如：`sources="auto"`、`sources="auto,-semantic_scholar"`、`filters="year:2020-, clinical:therapy"` 或 `options="counts_first,context_graph"`。

## 日常工作流

### 1. 先廣後窄

![搜尋與查詢智能流程](images/search-query-workflow.svg)

可以要求 client 先做中等大小的第一輪搜尋：

```text
Use PubMed Search MCP to search for recent literature on SGLT2 inhibitors and heart failure with preserved ejection fraction. Start with a broad search, show the query strategy, and keep the result set in session.
```

Agent 通常應該從 `unified_search` 開始。好的結果會包含使用的 query、article identifiers、source provenance，以及足夠判斷是否要 fetch details 或 refine 的 metadata。

後續處理請優先使用 `read_session` 或 `get_session_pmids`。不要要求模型在對話裡記住一長串 PMID。

### 2. 臨床問題用 PICO

臨床比較問題先做 PICO：

```text
請先抽出 P/I/C/O，用 parse_pico 驗證 handoff，提出 PubMed 搜尋 query，然後執行最精準的一個：
在成人第二型糖尿病合併 CKD 病人中，SGLT2 inhibitors 相較 placebo 是否能降低 heart failure hospitalization？
```

預期流程：

1. Agent 從使用者的臨床問題抽出 P/I/C/O。
2. `parse_pico(description=..., p=..., i=..., c=..., o=...)` 驗證 schema 並回傳 `template: pico` pipeline。
3. 可選：用 `generate_search_queries` 將 P/I/C/O 擴展成 MeSH/同義詞 fragments。
4. `unified_search` 執行回傳的 PICO pipeline，或執行 agent 組好的 Boolean query。
5. 如果第一個 query 太廣或太窄，可再用 `analyze_search_query`。

Server 能驗證 PICO handoff、建立後端 PICO 搜尋計畫，並協助 MeSH、同義詞與 ICD-to-MeSH 擴展；語意上的 PICO 抽取仍由 agent 負責，agent 也應說明為什麼選擇最後執行的 query。

### 3. 從 Seed Paper 探索

![論文探索與引用流程](images/discovery-citation-workflow.svg)

有重要 PMID 之後，從搜尋切換到探索：

```text
For PMID 12345678, fetch details, then find related papers, citing papers, and key references. Summarize why each group matters.
```

常用工具：

- `fetch_article_details`
- `find_related_articles`
- `find_citing_articles`
- `get_article_references`
- `build_citation_tree`
- `get_citation_metrics`

當你已經相信某篇 seed paper 值得追，這條路徑可以快速建立周邊證據地圖。

### 4. 取得全文與圖表

![全文擷取流程](images/fulltext-retrieval-flow.svg)

![全文、圖表與生醫圖片流程](images/visual-evidence-workflow.svg)

摘要不夠時使用 `get_fulltext`。建議使用明確 identifiers，例如 `pmid=`、`pmcid=` 或 `doi=`，避免 agent 從 raw string 推測 identifier type。全文服務會依 identifier-aware policy 選路徑：有 PMCID 時先走 Europe PMC XML；DOI 文章會查 Unpaywall OA locations；依設定嘗試 institutional direct/EZproxy；再落到 CORE、optional downloader 與 browser-session fallback。CrossRef 是 metadata / publisher-link route，不是全文主機。

需要 captions、image URLs 或 PDF links 時，對 PMC Open Access 文章使用 `get_article_figures`。圖表擷取取決於 open-access availability；沒有結果不代表文章一定沒有圖。

圖片優先的任務請把視覺工具當成兩段式 agent workflow：

```text
請用 analyze_figure_for_search 分析這張上傳的 microscopy image，抽出英文搜尋詞，接著搜尋相關論文與相似 biomedical images。
```

`analyze_figure_for_search` 可接受 MCP client 提供的 image URL 或 base64/data-URI image。它會回傳 MCP `ImageContent` 加上給 agent 的指令，讓 agent 用自己的 vision capability 解讀圖片、抽出英文 biomedical terms，然後接續呼叫 `search_biomedical_images` 或 `unified_search`。Server 本身不做深度視覺診斷；圖片語意判讀由 LLM agent 負責。

如果已經有文字化的視覺 finding，就直接用 `search_biomedical_images` 找 open biomedical image evidence：

```python
search_biomedical_images("chest X-ray pneumonia", sources="openi", image_type="x", limit=10)
search_biomedical_images("histology liver fibrosis", sources="openi", image_type="mc", license_type="by")
```

Open-i 需要英文醫學詞。非英文使用者提示應先由 agent 翻譯成英文 anatomy / finding / modality，再搜尋。

Browser fallback 需要另外啟動本機 broker：

```bash
uv sync --extra browser-broker
uv run playwright install chromium
uv run pubmed-browser-fetch-broker --token local-dev-token
```

只對你信任且有權存取的 host 啟用 browser-session fallback：

```json
{
  "enabled": true,
  "auto_enabled": true,
  "broker_url": "http://127.0.0.1:8766/fetch",
  "token": "local-dev-token",
  "allowed_hosts": ["jamanetwork.com", "*.jamanetwork.com"]
}
```

### 5. 建立研究脈絡年表

![評估與時間軸流程](images/timeline-evaluation-workflow.svg)

當問題不是「有哪些文章？」而是「這個領域怎麼演進？」時，使用 timeline tools。

```python
build_research_timeline(topic="remimazolam ICU sedation", output_format="tree", max_events=20)
build_research_timeline(pmids="last", topic="Last search chronicle", output_format="mermaid")
analyze_timeline_milestones(topic="CAR-T therapy")
compare_timelines(topics="remimazolam,propofol,dexmedetomidine", max_events_per_topic=10)
```

`build_research_timeline` 可以依 topic 搜尋，也可以使用既有 PMID set，包括 `pmids="last"`。它會偵測 milestone-like papers、可 highlight landmark studies，並支援 `text`、`tree`、`mermaid`、`mindmap`、`json`、`json_tree`、`timeline_js` 與 `d3` 輸出。`unified_search` 的 `options="context_graph"` 適合先看輕量分支預覽；使用者需要完整 research chronicle 時再轉用 `build_research_timeline`。

### 6. 重新讀取持久化 Query Memory

當透過 `PUBMED_DATA_DIR` 設定 session persistence 時，`unified_search` 與 `get_fulltext` 的大型可重用輸出會保存成 artifact。即時 tool response 只放精簡 locator，不強迫 agent 一次吃完整 token。

```python
read_session(action="list_artifacts")
read_session(action="artifact", artifact_id="...")
read_session(action="artifact", artifact_uri="artifact://...")
read_session(action="artifact", artifact_id="...", artifact_file="payload.json", offset=0, max_chars=200000)
```

Local paths 預設會被遮蔽，因為 remote clients 不能讀 MCP server host filesystem。只有本機 MCP client 真的需要 `local_path` 與 `manifest_path` 時，才設定 `PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS=true`。Artifact read 不會重跑搜尋；它只讀已保存的 query/fulltext memory。

### 7. 匯出引用或本機筆記

![匯出與本機筆記流程](images/export-notes-workflow.svg)

要交給 citation manager 時使用 `prepare_export`。Official PubMed-backed formats 是 `ris`、`medline` 與 `csl`；local rendered formats 包含 `bibtex`、`csv` 與 `json`。

常見範例：

```python
prepare_export(pmids="last", format="ris")
prepare_export(pmids="last", format="bibtex", source="local")
prepare_export(pmids="last", format="csl")
```

如果目標是本機知識庫，而不是單一引用檔，使用 `save_literature_notes`：

```python
save_literature_notes(pmids="last")
save_literature_notes(pmids="last", note_format="wiki")
save_literature_notes(pmids="last", note_format="medpaper")
save_literature_notes(pmids="last", output_dir="./references")
```

預設 `note_format` 是 `wiki`。`unified_search` 對 PMID-backed result set 會主動建議 `save_literature_notes(pmids="last", note_format="wiki")`；產生的 LLM wiki/Foam links 會使用 PMID、DOI、PMCID 等穩定 identifier 作為 `[[stable-id|title]]` target，而不是從 title 產生檔名。回應也會包含 `wiki_validation`，讓 agent 在編輯 note library 前先檢查 unresolved wikilinks。

輸出目錄解析順序：

1. `output_dir`
2. `PUBMED_NOTES_DIR`
3. `PUBMED_WORKSPACE_DIR/references`
4. `PUBMED_DATA_DIR/references`
5. `~/.pubmed-search-mcp/references`

本機筆記會把可驗證 metadata 放在 frontmatter 與 sidecar files，summary、relevance、limitations、follow-up sections 則保留給人或 agent 編輯。

### 8. 保存可重跑 Pipeline

![Session 與 Pipeline 流程](images/session-pipeline-workflow.svg)

當研究流程需要重跑或稽核時使用 pipeline。先從 [Pipeline 教學](PIPELINE_MODE_TUTORIAL.md) 開始。

典型 pipeline 任務：

- 每週重跑一次搜尋
- 用文字版本控管搜尋策略
- 比較不同 run 的 pipeline history
- 排程 recurring literature watch

Server 透過 `manage_pipeline` 暴露主要 pipeline operations，也保留 `save_pipeline`、`load_pipeline`、`list_pipelines`、`delete_pipeline`、`get_pipeline_history` 與 `schedule_pipeline` 等相容工具。

Saved pipelines 可以透過 `unified_search(pipeline="saved:<name>")` 重用。Pipeline `config` 應是 YAML 或 JSON string；scheduled pipeline 使用標準 five-field cron string。

## Copilot Studio 注意事項

![Client integration and deployment workflow](images/integration-deployment-workflow.svg)

Copilot 有兩條路：

- 完整 primary MCP surface：透過 `pubmed-search-mcp-http --transport streamable-http --copilot-compatible`
- 簡化 Copilot Studio surface：透過 `run_copilot.py` 暴露較小的 11-tool schema

Client 能處理時優先用完整工具面。當 Copilot Studio schema compatibility 是第一優先時，使用簡化工具面。

## 怎樣問 Agent 比較好

好的 prompt 會給任務、範圍與輸出形狀：

```text
請找第二型糖尿病中 GLP-1 receptor agonists 與 cardiovascular outcomes 的近期 systematic reviews。使用 PubMed Search MCP，顯示搜尋策略，把結果 PMID 保存在 session，最後將篩選後集合匯出成 RIS。
```

```text
請針對這個 seed PMID 建立 citation tree，分開 direct references 與 citing papers，並標出哪些文章看起來像 clinical guidelines、RCTs 或 meta-analyses。
```

```text
請把上一輪結果保存成本機 wiki notes。使用預設 wiki format，並包含 collection-level CSL JSON sidecar。
```

避免只說「find everything about cancer」。請補上 population、intervention、outcome、date range、article type，或你想支援的決策。

## 可靠性邊界

請記住：

- 搜尋結果取決於外部來源行為與可用 metadata。
- 全文取決於 open access、source APIs、publisher pages，以及你設定的 credentials 或 browser session。
- Citation counts 與 citation networks 會因 provider 與更新節奏不同而變動。
- Generated summaries 是 agent interpretation；bibliographic metadata 與 source links 才是證據錨點。
- Commercial connectors 應維持 default-off，並由 credentials gate。
- 臨床用途需要專業審查；這個 server 協助收集證據，不做照護決策。

## 疑難排解第一步

| 症狀 | 先檢查 |
| --- | --- |
| Server 無法啟動 | 在 terminal 確認 `uvx pubmed-search-mcp` 能執行。 |
| Client 找不到 tools | 檢查 [整合指南](INTEGRATIONS.md) 中的 config path 與 JSON syntax。 |
| NCBI warning 或速度慢 | 設定 `NCBI_EMAIL`；需要時加 `NCBI_API_KEY`。 |
| 全文為空或很少 | 先對 PMC Open Access article 測 `get_fulltext`，再確認來源可用性。 |
| 本機筆記存到非預期位置 | 檢查 `output_dir`、`PUBMED_NOTES_DIR`、`PUBMED_WORKSPACE_DIR` 與 `PUBMED_DATA_DIR`。 |
| GitHub Pages 文件看起來沒更新 | 本機跑 `uv run python scripts/build_docs_site.py`，再看 Pages workflow。 |

## 下一步

- [工具使用指南](TOOLS_USAGE_GUIDE.zh-TW.md)：能力導向工具路由
- [Pipeline 教學](PIPELINE_MODE_TUTORIAL.md)：保存與排程工作流
- [整合指南](INTEGRATIONS.md)：client 設定與疑難排解
- [部署文件](../DEPLOYMENT.md)：HTTP、Docker、Copilot Studio 與 Pages
- [開發者指南](DEVELOPER_GUIDE.zh-TW.md)：架構、貢獻流程與驗證
