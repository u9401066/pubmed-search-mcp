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

| 目標 | 從這裡開始 | 接著使用 |
| --- | --- | --- |
| 快速找文獻 | `unified_search` | `fetch_article_details`, `read_session` |
| 臨床問題 | `parse_pico` | `generate_search_queries`, `unified_search` |
| 改善太吵或太窄的 query | `analyze_search_query` | `generate_search_queries`, `unified_search` |
| 從重要文章往外探索 | `fetch_article_details` | `find_related_articles`, `find_citing_articles`, `get_article_references`, `build_citation_tree` |
| 閱讀更深層證據 | `get_fulltext` | `get_text_mined_terms`, `get_article_figures` |
| 建立本機文獻庫 | `prepare_export` | `save_literature_notes` |
| 重用工作流 | `manage_pipeline` | `save_pipeline`, `load_pipeline`, `schedule_pipeline` |

最重要的規則是：先看研究意圖，不要先看工具清單。

`unified_search` 的參數刻意設計成 agent-friendly strings。`sources`、`filters` 與 `options` 請使用 comma-separated values，不要傳 JSON object。例如：`sources="auto"`、`sources="auto,-semantic_scholar"`、`filters="review,5y"` 或 `options="counts_first,context_graph"`。

## 日常工作流

### 1. 先廣後窄

可以要求 client 先做中等大小的第一輪搜尋：

```text
Use PubMed Search MCP to search for recent literature on SGLT2 inhibitors and heart failure with preserved ejection fraction. Start with a broad search, show the query strategy, and keep the result set in session.
```

Agent 通常應該從 `unified_search` 開始。好的結果會包含使用的 query、article identifiers、source provenance，以及足夠判斷是否要 fetch details 或 refine 的 metadata。

後續處理請優先使用 `read_session` 或 `get_session_pmids`。不要要求模型在對話裡記住一長串 PMID。

### 2. 臨床問題用 PICO

臨床比較問題先做 PICO：

```text
Parse this as PICO, propose PubMed search queries, then run the most specific one:
In adults with type 2 diabetes and CKD, do SGLT2 inhibitors reduce heart failure hospitalization compared with placebo?
```

預期流程：

1. `parse_pico`
2. `generate_search_queries`
3. `unified_search`
4. 如果第一輪太廣或太窄，再用 `analyze_search_query`

Server 能協助 MeSH、synonyms 與 ICD-to-MeSH expansion，但 agent 仍應說明最後選擇哪個 query，以及原因。

### 3. 從 Seed Paper 探索

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

摘要不夠時使用 `get_fulltext`。建議使用明確 identifiers，例如 `pmid=`、`pmcid=` 或 `doi=`，避免 agent 從 raw string 推測 identifier type。全文服務會依可用性整合 open sources，可能包含 Europe PMC、CORE、CrossRef、Unpaywall、publisher links，或根據設定使用 browser-session fallback。

需要 captions、image URLs 或 PDF links 時，對 PMC Open Access 文章使用 `get_article_figures`。圖表擷取取決於 open-access availability；沒有結果不代表文章一定沒有圖。

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

### 5. 匯出引用或本機筆記

要交給 citation manager 時使用 `prepare_export`。Official PubMed-backed formats 是 `ris`、`medline` 與 `csl`；local rendered formats 包含 `bibtex`、`csv` 與 `json`。

常見範例：

```python
prepare_export(pmids="last", format="ris")
prepare_export(pmids="last", format="bibtex")
prepare_export(pmids="last", format="csl_json")
```

如果目標是本機知識庫，而不是單一引用檔，使用 `save_literature_notes`：

```python
save_literature_notes(pmids="last")
save_literature_notes(pmids="last", note_format="medpaper")
save_literature_notes(pmids="last", output_dir="./references")
```

預設 `note_format` 是 `wiki`。輸出目錄解析順序：

1. `output_dir`
2. `PUBMED_NOTES_DIR`
3. `PUBMED_WORKSPACE_DIR/references`
4. `PUBMED_DATA_DIR/references`
5. `~/.pubmed-search-mcp/references`

本機筆記會把可驗證 metadata 放在 frontmatter 與 sidecar files，summary、relevance、limitations、follow-up sections 則保留給人或 agent 編輯。

### 6. 保存可重跑 Pipeline

當研究流程需要重跑或稽核時使用 pipeline。先從 [Pipeline 教學](PIPELINE_MODE_TUTORIAL.md) 開始。

典型 pipeline 任務：

- 每週重跑一次搜尋
- 用文字版本控管搜尋策略
- 比較不同 run 的 pipeline history
- 排程 recurring literature watch

Server 透過 `manage_pipeline` 暴露主要 pipeline operations，也保留 `save_pipeline`、`load_pipeline`、`list_pipelines`、`delete_pipeline`、`get_pipeline_history` 與 `schedule_pipeline` 等相容工具。

Saved pipelines 可以透過 `unified_search(pipeline="saved:<name>")` 重用。Pipeline `config` 應是 YAML 或 JSON string；scheduled pipeline 使用標準 five-field cron string。

## Copilot Studio 注意事項

Copilot 有兩條路：

- 完整 primary MCP surface：透過 `run_server.py --transport streamable-http --copilot-compatible`
- 簡化 Copilot Studio surface：透過 `run_copilot.py` 暴露較小的 11-tool schema

Client 能處理時優先用完整工具面。當 Copilot Studio schema compatibility 是第一優先時，使用簡化工具面。

## 怎樣問 Agent 比較好

好的 prompt 會給任務、範圍與輸出形狀：

```text
Find recent systematic reviews about GLP-1 receptor agonists and cardiovascular outcomes in type 2 diabetes. Use PubMed Search MCP, show the search strategy, keep the result PMIDs in session, then export the final set as RIS.
```

```text
Build a citation tree for this seed PMID, separate direct references from citing papers, and identify which papers look like clinical guidelines, RCTs, or meta-analyses.
```

```text
Save local wiki notes for the last result set. Use the default wiki format and include a collection-level CSL JSON sidecar.
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
