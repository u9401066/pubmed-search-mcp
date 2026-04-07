# MCP Tool Consolidation Design

## Goal

Reduce public MCP surface area where multiple tools are thin variations of the same resource access pattern, while preserving backward compatibility for existing agents and prompts.

Current state after this change:

- `manage_pipeline()` is the new facade for pipeline CRUD/history/scheduling.
- `read_session()` is the new facade for session reads.
- Legacy tools remain available as compatibility wrappers.

## Consolidation Principles

1. Good facade candidates share one backing aggregate.
2. Good facade candidates differ mainly by `action`, not by payload shape or data source.
3. Do not merge tools when the resulting action matrix becomes harder to understand than the current API.
4. Keep read-heavy and write-heavy operations separate unless they operate on the same backing object and have the same mental model.
5. Prefer facade-first internals plus thin legacy wrappers over duplicated tool logic.

## 適合收

| Tool family | Current tools | Proposed facade | Why it fits | Recommendation |
| --- | --- | --- | --- | --- |
| Session 管理 | `get_session_pmids`, `get_cached_article`, `get_session_summary` | `read_session(action=pmids\|article\|summary)` | Same backing object (`SessionManager`), same user mental model, all are read-only accessors into one active session | 已實作，保留 legacy wrappers |
| Pipeline 管理 | `save_pipeline`, `list_pipelines`, `load_pipeline`, `delete_pipeline`, `get_pipeline_history`, `schedule_pipeline` | `manage_pipeline(action=save\|list\|load\|delete\|history\|schedule)` | Same backing object (`PipelineStore`), same resource type, clear CRUD/history lifecycle | 已實作，保留 legacy wrappers |
| 機構訂閱 | `configure_institutional_access`, `get_institutional_link`, `list_resolver_presets`, `test_institutional_access` | `manage_institutional_access(action=configure\|link\|list_presets\|test)` | Same configuration domain, one resolver profile lifecycle, current split mostly reflects implementation not API needs | 適合下一波收斂 |

## 不適合收

| Tool family | Current tools | Why not consolidate now |
| --- | --- | --- |
| 搜尋入口 | `unified_search` | Already the facade. Wrapping it again would add naming noise without reducing complexity. |
| 查詢智能 | `parse_pico`, `generate_search_queries`, `analyze_search_query` | These are distinct stages with distinct outputs: decomposition, term expansion, query analysis. Merging would create a vague meta-tool. |
| 文章探索 | `fetch_article_details`, `find_related_articles`, `find_citing_articles`, `get_article_references`, `get_citation_metrics` | Inputs are similar but semantics differ substantially: detail fetch, similarity, forward citation, backward citation, impact scoring. One `explore_article(action=...)` tool would be broader but less legible. |
| 全文工具 | `get_fulltext`, `get_text_mined_terms` | Same article target, but one is content retrieval and the other is annotation extraction. Different payload contracts and usage cadence. |
| 圖表擷取 | `get_article_figures` | Single focused capability; no adjacent tool family worth merging into today. |
| NCBI 延伸 | `search_gene`, `get_gene_details`, `get_gene_literature`, `search_compound`, `get_compound_details`, `get_compound_literature`, `search_clinvar` | Domain objects differ materially: gene, compound, variant. A single `research_biomedical_entity` facade would hide important entity-specific constraints. |
| 引用網絡 | `build_citation_tree` | Single focused capability. |
| 匯出工具 | `prepare_export` | Single focused capability. |
| 視覺搜索 | `analyze_figure_for_search` | Single focused capability with distinct multimodal input. |
| ICD 轉換 | `convert_icd_mesh` | Single focused bidirectional converter; already compact. |
| 研究時間軸 | `build_research_timeline`, `analyze_timeline_milestones`, `compare_timelines` | These are related but intentionally separate: build, analyze, compare. A single timeline mega-tool would become mode-heavy and harder to validate. |
| 圖片搜尋 | `search_biomedical_images` | Single focused capability. |

## 應淘汰 legacy wrapper

These wrappers should stay in place for compatibility until prompts, docs, tests, and downstream agents have migrated to the facade names.

| Legacy tool | Replaced by | Status | Retirement rule |
| --- | --- | --- | --- |
| `get_session_pmids` | `read_session(action="pmids")` | 保留中 | After two minor releases with no prompt/doc dependency |
| `get_cached_article` | `read_session(action="article", pmid=...)` | 保留中 | Same as above |
| `get_session_summary` | `read_session(action="summary")` | 保留中 | Same as above |
| `save_pipeline` | `manage_pipeline(action="save", ...)` | 保留中 | After all saved examples and prompts switch to facade |
| `list_pipelines` | `manage_pipeline(action="list", ...)` | 保留中 | Same as above |
| `load_pipeline` | `manage_pipeline(action="load", ...)` | 保留中 | Same as above |
| `delete_pipeline` | `manage_pipeline(action="delete", ...)` | 保留中 | Same as above |
| `get_pipeline_history` | `manage_pipeline(action="history", ...)` | 保留中 | Same as above |
| `schedule_pipeline` | `manage_pipeline(action="schedule", ...)` | 保留中 | Same as above |
| `configure_institutional_access` | future `manage_institutional_access(action="configure", ...)` | 候選 | Only after facade exists and docs migrate |
| `get_institutional_link` | future `manage_institutional_access(action="link", ...)` | 候選 | Same as above |
| `list_resolver_presets` | future `manage_institutional_access(action="list_presets")` | 候選 | Same as above |
| `test_institutional_access` | future `manage_institutional_access(action="test")` | 候選 | Same as above |

## Migration Plan

### Phase 1

- Add facade tools.
- Move implementation logic behind facade dispatch helpers.
- Keep legacy tools as thin wrappers.
- Update registry, instructions, and generated tool documentation.

### Phase 2

- Switch prompts, README examples, and tests to prefer facade names.
- Mark legacy wrappers as compatibility aliases in docs.

### Phase 3

- Emit deprecation warnings in wrapper docstrings or descriptions if MCP host UX allows it.
- Remove wrappers only after release-window and usage review.

## Non-Goals

- Do not collapse all search-related tools into one giant action router.
- Do not merge tools that cross different domain aggregates only to reduce tool count.
- Do not change output schemas of existing legacy tools during the compatibility phase.
