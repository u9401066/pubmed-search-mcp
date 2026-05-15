<!-- Generated from docs/ADVANCED_RESEARCH_WORKFLOWS.zh-TW.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# 進階研究工作流

這頁把 docs site 導覽裡不該再被藏起來的新工作流集中成同一個入口：研究脈絡時間軸、Open-i 圖片搜尋、上傳圖片 handoff，以及持久化 query memory。

## 快速對照

| 需求 | 從這裡開始 | 接著使用 |
| --- | --- | --- |
| 看一個主題如何演進 | `build_research_timeline` | `analyze_timeline_milestones`, `compare_timelines` |
| 用文字找 biomedical images | `search_biomedical_images` | `get_article_figures`, `unified_search` |
| 上傳圖片，依圖片語意找相關文獻 | `analyze_figure_for_search` | `search_biomedical_images`, `unified_search` |
| 重新讀取大型搜尋/全文輸出，不重跑外部來源 | `read_session(action="artifact")` | `read_session(action="list_artifacts")` |

## 研究脈絡 / Research Timeline

當使用者問「這個領域怎麼演進？」、「哪些文章像里程碑？」或「兩個研究路線差在哪？」時，用 timeline tools。

```python
build_research_timeline(topic="remimazolam ICU sedation", output_format="tree", max_events=20)
build_research_timeline(pmids="last", topic="Last search chronicle", output_format="mermaid")
analyze_timeline_milestones(topic="CAR-T therapy")
compare_timelines(topics="remimazolam,propofol,dexmedetomidine")
```

`build_research_timeline` 可以依 topic 搜尋，也可以使用既有 PMID set，包括 `pmids="last"`。輸出格式支援 `text`、`tree`、`mermaid`、`mindmap`、`json`、`json_tree`、`timeline_js`、`d3`。如果只是想在一般搜尋回應裡看輕量分支預覽，用 `unified_search(options="context_graph")`；若需要完整 research chronicle，請用 `build_research_timeline`。

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
read_session(action="artifact", artifact_id="...", artifact_file="payload.json", offset=0, max_chars=200000)
```

Artifact 是 query memory，不是第二次搜尋。讀取 artifact 不會重跑外部 source calls。Local filesystem paths 預設會被遮蔽，因為 remote client 不能讀 MCP server host path。只有本機 MCP client 真的需要 `local_path` 與 `manifest_path` 時，才設定 `PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS=true`。

## 驗證狀態

目前 primary 46-tool MCP server 直接暴露這些功能：

- Timeline: `build_research_timeline`, `analyze_timeline_milestones`, `compare_timelines`
- Image search: `search_biomedical_images`
- 上傳圖片 handoff: `analyze_figure_for_search`
- Query memory: `read_session(action="artifact")`

這些功能有 docs alignment tests、tool registry tests、image-search tests、vision-search tests、timeline tests、session artifact tests 守住。
