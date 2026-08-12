# 進階研究工作流

這頁把 docs site 導覽裡不該再被藏起來的新工作流集中成同一個入口：研究脈絡時間軸、Open-i 圖片搜尋、上傳圖片 handoff，以及持久化 query memory。

## 快速對照

| 需求 | 從這裡開始 | 接著使用 |
| --- | --- | --- |
| 看一個主題如何演進 | `build_research_chronicle` | `read_research_chronicle` |
| 用文字找 biomedical images | `search_biomedical_images` | `get_article_figures`, `unified_search` |
| 上傳圖片，依圖片語意找相關文獻 | `analyze_figure_for_search` | `search_biomedical_images`, `unified_search` |
| 重新讀取大型搜尋/全文輸出，不重跑外部來源 | `read_session(action="artifact")` | `read_session(action="list_artifacts")` |

## 研究脈絡 / Research Timeline

當使用者問「這個領域怎麼演進？」、「哪些文章像里程碑？」或「兩個研究路線差在哪？」時，用 chronicle tools。

```python
build_research_chronicle(topic="remimazolam ICU sedation", output="tree", max_events=20)
build_research_chronicle(pmids="12345678,23456789", topic="Selected studies", output="mermaid")
read_research_chronicle(action="milestones", chronicle_id="car-t-therapy-...")
read_research_chronicle(action="compare", topics="remimazolam,propofol,dexmedetomidine")
```

`build_research_chronicle` 可以依 topic 搜尋，也可以使用明確的 comma-separated PMID set。`mermaid` 是標準合併圖：年份是橫向主軸，各觀察研究線從本次檢索範圍內最早的有日期論文所在年份分岔；`chronicle_map` 回傳同一座標契約的 JSON。多篇論文共同出現的 MeSH descriptor 與作者 keyword 會用來推導語意主題分支；訊號不足時 audit 會標示為研究階段 fallback，`timeline_mermaid` 則保留舊的平面 timeline。其他格式包括 `summary`、`timeline`、`tree`、`graph`、`evidence`、`milestones`、`mindmap`、`narrative`、`json`。因為 revision 已持久化，`action="milestones"` 與 `action="compare"` 都是讀已儲存證據，不會重跑搜尋。如果只是想在一般搜尋回應裡看輕量分支預覽，用 `unified_search(options="context_graph")`；它只根據本次 PMID-backed ranked set 產生 preview，不是完整 graph。詳見 [Research Chronicle Rebuild Spec](RESEARCH_CHRONICLE_REFACTOR_SPEC.md)。

請把分支解讀為受檢索範圍限制的觀察分組，而不是因果祖譜。branch point 是本次候選集內最早的有日期論文，不一定是整個領域的首篇。單篇獨有的 MeSH term 或 keyword 不足以建立語意分支；訊號不足時會改用研究階段 fallback 並警告。日期 precision 也會保留：兩筆只知道同一年的記錄可以有固定顯示順序，但 graph 不會因此推論其中一篇 `precedes` 或 `supersedes` 另一篇。

Revision 不可變，N+1 的配置與寫入是原子操作。以 topic 比較時使用正規化後的完整 stored-topic 名稱；若同名對應多個 Chronicle，系統會回報 ambiguity 並要求明確的 `chronicle_ids`，重複目標也會拒絕。啟用 session artifact persistence 後若 artifact 寫入失敗，回應會揭露失敗，但已保存的 Chronicle revision 不會遺失。

Topic 年份 filter 會先在 PubMed server-side 套用，再進行有界檢索。event selection 保留觀察到的時序首尾、landmark 與 temporal spread；`returned`／`available` coverage 若受 cap 限制或總量未知，audit 會警告。PubMed error 或零篇 evidence 不發布 revision。PMID／DOI evidence identity 讓 entry ID 在修正後保持穩定，同一套 canonical topic key 負責 ID derivation 與 exact lookup。diff 的缺席只是觀察結果，不是已證實退場。多訊號論文保留 primary assignment 與 cross-links，重疊達 20% 會警告；importance ranking 不使用 milestone detection confidence。Artifact preflight 會檢查實際準備的 payload names。

## Open-i 生醫圖片搜尋

當視覺 finding 已經被文字化，且目標是找 open biomedical image evidence 時，使用 `search_biomedical_images`。

```python
search_biomedical_images("chest X-ray pneumonia", sources="openi", image_type="x", limit=10)
search_biomedical_images("histology liver fibrosis", sources="openi", image_type="mc", license_type="by")
```

Open-i 需要英文醫學詞。中文或其他非英文提示應先由 agent 翻譯 anatomy、finding、modality，再呼叫 `search_biomedical_images`。Open-i 適合 radiology、microscopy、clinical photos、teaching images；如果要抓論文本身的圖表，請對 PMC Open Access 文章使用 `get_article_figures`。

## 上傳圖片到文獻搜尋

`analyze_figure_for_search` 是給 MCP client 上傳圖片或傳 image URL 時使用的 handoff tool。它接受 image URL 或 base64/data-URI image，回傳 MCP `ImageContent` 與給 LLM agent 的搜尋指令。

```python
analyze_figure_for_search(image="data:image/png;base64,...", search_type="medical")
```

Server 本身不做 standalone visual diagnosis。正確流程是：

1. MCP client 把上傳圖片或 image URL 傳給 `analyze_figure_for_search`。
2. LLM agent 用自己的 vision capability 判讀圖片，抽出英文 biomedical search terms。
3. Agent 接著呼叫 `search_biomedical_images` 找相似 biomedical images，或用 `unified_search` 找相關論文。

## 持久化 Query Memory

當 session persistence 有設定時，大型 `unified_search` 與 `get_fulltext` 輸出可以保存成 artifact。即時 tool response 可以保持精簡，同時把可重用 payload 留在 session artifact 裡。

```python
read_session(action="list_artifacts")
read_session(action="artifact", artifact_id="...")
read_session(action="artifact", artifact_uri="artifact://...")
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="audit.json")
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="results.json", offset=0, max_chars=200000)
```

Artifact 是 query memory，不是第二次搜尋。讀取 artifact 不會重跑外部 source calls。Local filesystem paths 預設會被遮蔽，因為 remote client 不能讀 MCP server host path。只有本機 MCP client 真的需要 `local_path` 與 `manifest_path` 時，才設定 `PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS=true`。

對 `unified_search` 來說，artifact files 會比即時 MCP response 更完整。建議先讀 `audit.json` 看完整性警告，再讀 `query_strategy.json` 檢查實際來源與搜尋策略，最後用 `results.json` 或 `results.toon` 取回完整文章清單。這能節省 response token，也讓 agent、sandbox client 與未來遠端 artifact backend 都能重複讀取同一份 evidence。

## 驗證狀態

目前 primary 45-tool MCP server 直接暴露這些功能：

- Research chronicle: `build_research_chronicle`, `read_research_chronicle`
- Image search: `search_biomedical_images`
- 上傳圖片 handoff: `analyze_figure_for_search`
- Query memory: `read_session(action="artifact")`

這些功能有 docs alignment tests、tool registry tests、image-search tests、vision-search tests、timeline tests、session artifact tests 守住。
