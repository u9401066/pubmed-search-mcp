# Research Chronicle Refactor Spec

Status: Draft v1  
Author: Copilot (GPT-5.3-Codex)  
Last Updated: 2026-04-23

---

## 1. Problem Statement

目前專案已具備強健的 timeline substrate，但尚未形成可持久化、可版本化、可敘事、可追溯來源的 chronicle layer。

已存在能力（可重用）：
- Timeline domain model（事件、里程碑類型、分期、landmark score）
- Timeline builder（topic/PMID 建構、milestone detection、diagnostics）
- Timeline MCP tools（build/analyze/compare）
- Session activity log/resource
- Session history persistence
- Pipeline history persistence

核心缺口（本規格要解決）：
1. 缺少跨 session 的研究記憶資產（只有一次建構結果與當前 session log）
2. TimelineEvent 仍偏單篇文章驅動，缺 EvidenceBundle 聚合
3. 缺少 revision / diff 機制（無法回答「上次之後變了什麼」）
4. 缺少 evidence-backed narrative 輸出層
5. 缺少 typed provenance graph（關係語義未被限制與持久化）

---

## 2. Current Surface Audit

### 2.1 Timeline 子系統（已存在）
- Domain entities: `TimelineEvent`, `ResearchTimeline`, `MilestoneType`, `LandmarkScore`
  - 檔案：`src/pubmed_search/domain/entities/timeline.py`
- Builder orchestration: topic 搜尋、PMID 建構、milestone detection、diagnostics
  - 檔案：`src/pubmed_search/application/timeline/timeline_builder.py`
- MCP tool surface:
  - `build_research_timeline`
  - `analyze_timeline_milestones`
  - `compare_timelines`
  - 檔案：`src/pubmed_search/presentation/mcp_server/tools/timeline.py`

### 2.2 Session（已存在但偏 session-local）
- Session persistence + event log + search history
  - 檔案：`src/pubmed_search/application/session/manager.py`
- MCP 可讀取摘要/事件，但定位偏 debug/history
  - 檔案：`src/pubmed_search/presentation/mcp_server/session_tools.py`

### 2.3 Pipeline（已存在但偏執行記錄）
- Pipeline run history/reports/schedules persistence
  - 檔案：`src/pubmed_search/application/pipeline/store.py`

### 2.4 Unified Search Context Preview（已存在）
- `options="context_graph"` 提供輕量 preview
- 定位為「快速脈絡預覽」，不是完整 chronicle asset

### 2.5 結論
- 現況是「多個強能力孤島」：timeline、session、pipeline 各自成熟，但沒有統一資產層承接。

---

## 3. Target Domain Model (Chronicle)

新增 `chronicle` bounded context（application/domain/presentation 分層），避免把 timeline tool 變 mega-tool。

### 3.1 Aggregate: ChronicleSnapshot
表示某個 topic 在某個 revision 的完整編年史快照。

建議欄位（草案）：
- `chronicle_id: str`
- `topic: str`
- `revision: int`
- `created_at: str`
- `derived_from: dict`（來源：pipeline run id、session ids、search queries）
- `entries: list[ChronicleEntry]`
- `branches: list[ChronicleBranch]`
- `graph: ChronicleGraph`
- `metadata: dict`

### 3.2 ChronicleEntry
編年史條目，不等於單篇 paper；可對應研究階段、爭議、轉折、共識等。

建議欄位：
- `entry_id: str`
- `entry_type: ChronicleEntryType`
- `title: str`
- `time_start: str | int`
- `time_end: str | int | None`
- `summary_claim: str`
- `branch_id: str | None`
- `confidence: float`
- `evidence: EvidenceBundle`
- `tags: list[str]`
- `status: Literal["active", "superseded", "contested"]`

### 3.3 EvidenceBundle
一個 entry 綁多篇支持/反對/更新證據。

建議欄位：
- `supporting_articles: list[EvidenceArticle]`
- `contradicting_articles: list[EvidenceArticle]`
- `updating_articles: list[EvidenceArticle]`
- `verification_summary: dict`（reference verification、fulltext/figure 可用性）

`EvidenceArticle` 草案：
- `pmid`, `doi`, `source`
- `claim_excerpt`
- `figure_links`, `fulltext_links`
- `reference_verification_status`

### 3.4 ChronicleBranch
穩定研究支線（長期），非一次輸出的視覺分桶。

建議欄位：
- `branch_id`, `name`, `description`
- `root_entry_id`
- `entry_ids`
- `parent_branch_id | None`

### 3.5 ChronicleRevision / ChronicleDelta
- `ChronicleRevision`: 同一 topic 的版本節點
- `ChronicleDelta`: 兩版本差異（新增/移除/改判/支線變化/矛盾升降）

---

## 4. Typed Provenance Graph

Graph 必須採 typed edges，限制語義避免 generic KG 失控。

### 4.1 Node Types
- `Topic`
- `Branch`
- `ChronicleEntry`
- `EvidenceArticle`
- `SessionEvent`（可選，僅 provenance）
- `PipelineRun`（可選，僅 provenance）

### 4.2 Edge Types（白名單）
- `precedes`
- `branches_from`
- `supports`
- `contradicts`
- `updates`
- `supersedes`
- `observed_in_session`
- `derived_from_pipeline_run`

### 4.3 Graph Invariants
- `supports|contradicts|updates` 只能由 `EvidenceArticle -> ChronicleEntry`
- `branches_from` 只能在 `Branch -> Branch`
- `precedes|supersedes` 只能在 `ChronicleEntry -> ChronicleEntry`
- 每個 `ChronicleEntry` 至少要有一個 evidence article

---

## 5. Projection Model

Chronicle 是 source-of-truth；timeline/tree/text/json 皆為 projection。

支援投影：
- `timeline`（現有 timeline 視圖）
- `tree`（branch-centric）
- `mindmap`
- `mermaid`
- `narrative`（brief/detailed/clinical/regulatory）
- `json`（完整 snapshot）
- `delta_report`（revision 比較）

關鍵原則：
- `build_research_timeline` 維持輕量入口
- Chronicle 層負責資產持久化、版本、差異、敘事

---

## 6. Persistence Model

### 6.1 儲存位置（建議）
- Workspace scope: `<workspace>/.pubmed-search/chronicles/`
- Global scope: `~/.pubmed-search-mcp/chronicles/`

### 6.2 檔案結構（建議）
- `index.json`（topic -> latest_revision / metadata）
- `<topic_slug>/snapshot_<revision>.json`
- `<topic_slug>/delta_<rev_a>_<rev_b>.json`
- `<topic_slug>/narrative_<revision>_<mode>.md`（可選 cache）

### 6.3 Revision 規則
- 同 topic 每次 `build/update` 產生 monotonically increasing revision
- `update_research_chronicle` 預設以 latest revision 為基底
- 必須記錄 `derived_from_pipeline_run` 與 session 關聯（若可得）

### 6.4 Diff 規則
`ChronicleDelta` 至少包含：
- `new_entries`
- `updated_entries`
- `retired_entries`
- `branch_changes`
- `evidence_flip`（supports ↔ contradicts）
- `consensus_shift`
- `unresolved_conflicts`

---

## 7. MCP Tool Design

## 7.1 保留並重定位（不破壞相容）
- `build_research_timeline`: 定位為 Chronicle projection（timeline view builder）
- `compare_timelines`: 定位為 Chronicle 快速比較器
- `analyze_timeline_milestones`: 定位為 analytics 子工具
- `unified_search options=context_graph`: 定位為 preview，不是 asset
- `get_session_log` / session summary: 定位為 provenance input

### 7.2 新增 Chronicle Tool Surface
1. `build_research_chronicle`
- from topic / pmids / pipeline config
- 產出第一個或指定策略的 snapshot revision

2. `load_research_chronicle`
- 載入指定 chronicle_id + revision（預設 latest）

3. `update_research_chronicle`
- 以最新資料重建並產生新 revision

4. `diff_research_chronicle`
- 比較兩個 revision，輸出 `ChronicleDelta`

5. `narrate_research_chronicle`
- 產出 evidence-backed narrative
- mode: `brief|detailed|clinical|regulatory`

6. `list_research_chronicles`
- 列出可重用 chronicle assets

### 7.3 為何不做 mega-tool
- 可維持 timeline 工具可預測、單一責任
- Chronicle workflow 可以獨立演進與持久化
- 避免 mode-heavy 參數地獄

---

## 8. Integration Design (Timeline / Session / Pipeline)

### 8.1 Timeline 整合
- 重用 `TimelineBuilder` 與 `MilestoneDetector` 產生初始 event candidates
- 由 Chronicle assembler 將 event 升級為 `ChronicleEntry + EvidenceBundle`

### 8.2 Session 整合
- 使用 `SessionManager` 的 `search_history` 與 `event_log` 作為 provenance 邊
- 不把 session log 直接當 chronicle storage

### 8.3 Pipeline 整合
- 使用 pipeline run history（run_id, report）作為 `derived_from_pipeline_run`
- `update_research_chronicle` 可接受 pipeline name / run id 作增量來源

### 8.4 Reference Verification / Fulltext / Figures（Phase 3）
- 進入 `EvidenceBundle.verification_summary`
- 支援 narrative 輸出中的 evidence quality 註記

---

## 9. Migration Strategy

### Phase 1: Chronicle Snapshot Foundation
目標：先把 timeline + session/pipeline provenance 收束成可保存資產。

範圍：
- 新增 Chronicle domain entities（最小可用）
- 新增 Chronicle store（revision/index/delta 檔案）
- 新增 `build/load/list` 三個工具
- timeline 只做 projection，不動 milestone 規則

不做：
- 複雜 evidence 關係推理
- narrative 自動生成優化

### Phase 2: Evidence-backed Entries
目標：由 article event 升級成 evidence bundle 條目。

範圍：
- entry 聚合（supports/contradicts/updates）
- `diff_research_chronicle`
- `narrate_research_chronicle` 初版

### Phase 3: Living Chronicle
目標：持續更新與工作流閉環。

範圍：
- 與 schedule / pipeline execution 深度整合
- reference verification / fulltext / figures 信號進入 evidence 層
- unresolved conflict queue 與 narrative 更新

---

## 10. Validation Plan

### 10.1 Domain & Service 測試
- Chronicle entities round-trip（to_dict/from_dict）
- revision monotonicity
- delta correctness（新增/更新/撤回/翻轉）

### 10.2 Integration 測試
- topic -> timeline -> chronicle snapshot
- chronicle update with new pipeline run
- session provenance edge linkage

### 10.3 Tool 合約測試
- 新工具輸入規範化與錯誤訊息
- projection 一致性（同 revision 的 timeline/text/json 對齊）

### 10.4 品質指標（相對於現況 timeline）
- 可回放性：可重建歷史 revision
- 可追溯性：entry 能追到 evidence 與來源 run/session
- 可敘事性：同一資料可生成 mode-specific narrative
- 可維護性：timeline tool complexity 不明顯膨脹

---

## 11. Proposed Module Layout

```text
src/pubmed_search/
  domain/entities/
    chronicle.py                # ChronicleSnapshot/Entry/Branch/Revision/Delta
  application/chronicle/
    assembler.py                # timeline/session/pipeline -> chronicle snapshot
    store.py                    # persistence + revision index + delta cache
    projector.py                # timeline/tree/mindmap/mermaid/json projections
    differ.py                   # ChronicleDelta logic
    narrator.py                 # evidence-backed narrative generation
  presentation/mcp_server/tools/
    chronicle.py                # build/load/update/diff/narrate/list tools
```

---

## 12. Backward Compatibility

- 不移除既有 timeline MCP tools
- 不改變 `build_research_timeline` 既有輸入/輸出契約（僅語意重定位）
- `context_graph` 保留 preview 定位
- session/pipeline 既有資料格式不破壞，採讀取整合策略

---

## 13. Risks & Guardrails

風險：
- timeline 與 chronicle 功能重疊導致雙軌混亂
- graph 關係過度自由造成推理失控
- narrative 生成若不綁 evidence 會產生 hallucination 風險

Guardrails：
- typed edge 白名單 + invariants
- narrative 必須引用 evidence ids / PMIDs
- 保持 timeline 為 projection，chronicle 才是 source-of-truth

---

## 14. Implementation Checklist (Actionable)

Phase 1 checklist：
- [ ] 新增 `chronicle.py` domain entities
- [ ] 新增 Chronicle store + index/revision persistence
- [ ] 新增 `build_research_chronicle`
- [ ] 新增 `load_research_chronicle`
- [ ] 新增 `list_research_chronicles`
- [ ] 新增基礎測試（domain/store/tools）

Phase 2 checklist：
- [ ] 新增 EvidenceBundle 聚合流程
- [ ] 新增 `diff_research_chronicle`
- [ ] 新增 `narrate_research_chronicle`
- [ ] 對接 reference verification 狀態

Phase 3 checklist：
- [ ] 對接 pipeline scheduling 與 run history
- [ ] 對接 fulltext/figure signals
- [ ] 增量更新策略與 conflict queue

---

## 15. Decision Summary

本 spec 採「在既有 timeline 子系統上方新增 Research Chronicle layer」策略，而非改造單一 mega timeline tool。

這個方案可保留現有 timeline 投影能力與工具穩定性，同時補齊：
- 跨 session 研究記憶
- 多證據聚合條目
- revision/diff
- evidence-backed narrative
- typed provenance graph
