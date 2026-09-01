<!-- Synced from docs/PIPELINE_MODE_TUTORIAL.md by scripts/build_docs_site.py -->

# Pipeline Mode Tutorial

> Status: current API tutorial
> Last updated: 2026-08-09
> Language: [English](pipeline-tutorial.md) | **繁體中文**

這份文件只描述目前真的可用的 pipeline mode 行為，不重複 RFC 設計稿。重點是直接可執行、可保存、可排程、可查歷史。

## Pipeline Mode 快速上手

![Pipeline entry points and execution workflow](../../../../docs/images/pipeline-entrypoints-and-dag.svg)

Pipeline mode 有 3 種最常用入口：

1. 直接把 YAML/JSON 丟給 `unified_search(..., pipeline="...")`
2. 先用 `save_pipeline` 保存，再用 `saved:<name>` 執行
3. 保存後交給 `schedule_pipeline` 定期跑

> **先選擇 runtime。** 可信任的本機 stdio/loopback caller 可使用 project workspace
> scope、`file:` source 與 in-process scheduler。認證 service caller 只使用當前
> principal 隔離的 saved-pipeline store：不存取 process-wide workspace，也不讀
> `file:`。Service Compose 會停用 scheduler，直到維運者提供單一 external leader/lease。

### 最短可用範例: inline template

```python
unified_search(
    query="",
    pipeline="""
template: pico
template_params:
  P: ICU patients requiring mechanical ventilation
  I: remimazolam
  C: propofol
  O: sedation adequacy
output:
  format: markdown
  limit: 20
  ranking: balanced
""",
)
```

注意:

- `unified_search` 在函式簽名上仍要求 `query`，但只要設定了 `pipeline`，一般搜尋參數會被忽略。保守寫法就是 `query=""`。
- `output_format="json"` 會強制回 structured JSON。pipeline 內的 `output.format: json` 也會回 structured JSON。
- `dry_run=True` 會預覽解析後的 DAG，不做外部搜尋。`stop_at="<step_id>"` 則只執行到指定 step。

### 最短可用範例: 先保存再執行

```python
save_pipeline(
    name="icu_remi_vs_propofol",
    config="""
template: pico
template_params:
  P: ICU patients requiring mechanical ventilation
  I: remimazolam
  C: propofol
  O: delirium, sedation quality
output:
  limit: 25
  ranking: quality
""",
    tags=["icu", "sedation", "remimazolam"],
    description="ICU sedation comparison",
)

unified_search(query="", pipeline="saved:icu_remi_vs_propofol")
```

### Structured output 與後續工具

Pipeline Markdown report 會包含 filter diagnostics，也會在底部附上後續 handoff 建議：

- `read_session(request={"action":"pmids"})` 取回這次 run 的 PMID set
- `prepare_export(pmids="last", format="ris")` 交給 Zotero/EndNote/Mendeley 類引用管理器
- `save_literature_notes(pmids="last", note_format="wiki")` 存成本機 wiki/Foam-compatible Markdown 筆記

如果要讓另一個 agent 或 extension 直接吃結構化文章資料，用 JSON：

```yaml
output:
  format: json
  limit: 20
  ranking: quality
```

JSON 回應會包含 `summary`、`steps`、每個 step 的 `metadata`、以及 structured `articles`。

### 什麼時候用哪一種

| 情境 | 推薦入口 |
| ---- | -------- |
| 只想快速跑一次 | inline `unified_search(..., pipeline="...")` |
| 想重複使用同一個搜尋策略 | `save_pipeline(...)` |
| 想看歷史 diff 或本機排程 | 先保存，再用 `saved:<name>` / `schedule_pipeline` |
| 可信任的本機 caller 想從 YAML 檔載入 | `load_pipeline(source="file:path/to/pipeline.yaml")` |
| 認證 service caller 要重用 | 存入 tenant store，再用 `saved:<name>` |

## Template Pipeline 教學

Template pipeline 適合 80% 的常見需求。它不是把 YAML 原封不動送進 executor，而是先展開成真正的 step DAG。

### 目前可用的 4 個 templates

| Template | 必填參數 | 常用可選參數 | 用途 |
| -------- | -------- | ------------ | ---- |
| `pico` | `P`, `I` | `C`, `O`, `sources`, `limit` | 臨床比較問題 |
| `comprehensive` | `query` | `sources`, `limit`, `min_year`, `max_year` | 多來源全面搜尋 |
| `exploration` | `pmid` | `limit` | 從一篇 seed paper 往外探索 |
| `gene_drug` | `term` | `sources`, `limit`, `min_year`, `max_year` | 基因或藥物主題搜尋 |

### Canonical `template_params`

Template pipeline 只接受唯一的參數欄位 `template_params`。已退役的頂層
`params` 會直接被拒絕，不會自動改寫；step-based DAG 內每個 step 仍使用
`params`。

### `pico`

```yaml
template: pico
template_params:
  P: ICU patients requiring sedation
  I: remimazolam
  C: propofol
  O: delirium incidence, time to extubation
  sources: [pubmed, europe_pmc]
  limit: 30
output:
  ranking: quality
```

這會自動展開成:

```text
pico -> search_p
     -> search_i
     -> search_c   # 只有設定 C 才會出現
     -> merged -> enriched
```

### `comprehensive`

```yaml
template: comprehensive
template_params:
  query: CRISPR gene therapy clinical trials
  sources: [pubmed, openalex, europe_pmc]
  limit: 30
  min_year: 2020
output:
  ranking: quality
```

注意目前正確欄位是 `query`，不是 `topic`。

這會先做 `expand`，再平行跑原始查詢與擴展查詢，最後 merge + metrics。

### `exploration`

```yaml
template: exploration
template_params:
  pmid: "37076210"
  limit: 25
output:
  ranking: impact
```

這會從同一篇 seed paper 同步拉 `related`、`citing`、`references`。

### `gene_drug`

```yaml
template: gene_drug
template_params:
  term: BRCA1 targeted therapy PARP inhibitors
  sources: [pubmed, openalex]
  limit: 20
  min_year: 2020
output:
  ranking: recency
```

注意目前正確欄位是 `term`，不是 `topic`。

### 範例檔

目前可直接參考這些範例:

- `data/pipeline_examples/pico_remimazolam_vs_propofol.yaml`
- `data/pipeline_examples/comprehensive_crispr_therapy.yaml`
- `data/pipeline_examples/exploration_seed_paper.yaml`
- `data/pipeline_examples/gene_drug_brca1.yaml`

## Custom DAG 教學

![Custom pipeline DAG workflow](../../../../docs/images/custom-pipeline-dag.svg)

當 template 不夠時，直接寫 `steps`。

### 最小結構

```yaml
name: ai_anesthesiology_scan
steps:
  - id: expand
    action: expand
    params:
      topic: artificial intelligence anesthesiology

  - id: search_original
    action: search
    params:
      query: artificial intelligence anesthesiology
      sources: [pubmed, openalex]
      limit: 60
      min_year: 2020

  - id: search_mesh
    action: search
    inputs: [expand]
    params:
      strategy: mesh
      sources: [pubmed, europe_pmc]
      limit: 60
      min_year: 2020

  - id: merged
    action: merge
    inputs: [search_original, search_mesh]
    params:
      method: rrf

  - id: enriched
    action: metrics
    inputs: [merged]

  - id: filtered
    action: filter
    inputs: [enriched]
    params:
      min_year: 2021
      has_abstract: true

output:
  format: markdown
  limit: 30
  ranking: quality
```

### 每個 step 要記得的事

| 欄位 | 必要性 | 說明 |
| ---- | ------ | ---- |
| `id` | 必填 | 精確且唯一的 step ID；不會自動產生或修復 |
| `action` | 必填 | 目前只接受固定 action 集合 |
| `params` | 視 action 而定 | 各 action 需要的參數不同 |
| `inputs` | 視 action 而定 | 只能引用前面已定義的 step |
| `on_error` | 可選 | `skip` 或 `abort`，預設 `skip` |

### 目前可用 actions

| Action | 常用 params | 說明 |
| ------ | ----------- | ---- |
| `search` | `query`, `sources`, `limit`, `min_year`, `max_year` | 一般文獻搜尋 |
| `pico` | `P`, `I`, `C`, `O` | 建立 PICO elements 與組合 query |
| `expand` | `topic` | 做語意擴展與 MeSH strategy |
| `details` | `pmids` | 補抓文章詳情 |
| `related` | `pmid`, `limit` | 找 related articles |
| `citing` | `pmid`, `limit` | 找 citing articles |
| `references` | `pmid`, `limit` | 找 references |
| `metrics` | 無需額外 params | 補 iCite metrics |
| `merge` | `method=union / intersection / rrf` | 合併多路結果 |
| `filter` | `min_year`, `max_year`, `article_types`, `min_citations`, `has_abstract` | 帶 diagnostics 的後處理篩選 |

### Shared globals 與 variables

`globals` 是每個 step 會繼承的預設 params；`variables` 可以在字串中用 `${name}` 替換。step 自己的 params 會覆蓋 globals。

```yaml
name: reusable_remi_pipeline
globals:
  sources: [pubmed, europe_pmc]
  limit: ${per_step_limit}
  min_year: ${start_year}
variables:
  topic: remimazolam ICU sedation
  per_step_limit: 50
  start_year: 2020
steps:
  - id: search_topic
    action: search
    params:
      query: ${topic}
  - id: filtered
    action: filter
    inputs: [search_topic]
    params:
      article_types: [randomized-controlled-trial, systematic-review]
      has_abstract: true
output:
  limit: 20
  ranking: quality
```

`article_types` 支援 canonical 值，例如 `randomized-controlled-trial`，也支援常見 alias，例如 `RCT`、`randomized controlled trial`、`systematic review`、`meta analysis`。未知 article type 會 fail closed 並附 warning，不會默默關掉 type filter。Filter report 會顯示篩選前後數量、排除原因、article type mapping、以及被排除文章範例。

### `search` 會怎麼吃上游結果

`search` 不一定要自己寫 `query`，它也能從上游 step 導出 query:

- 上游是 `pico` 時，可用 `element: P|I|C|O`
- 上游是 `pico` 時，也可用 `use_combined: precision|recall|intervention_outcome|comparison_outcome`
- 上游是 `expand` 時，可用 `strategy: mesh` 或其他 strategy 名稱

### Dry-run 與部分執行

長 pipeline 或正在調整 variables 時，先用 `dry_run=True`：

```python
unified_search(query="", pipeline="<yaml>", dry_run=True)
```

要查看中間結果，用 `stop_at`：

```python
unified_search(query="", pipeline="<yaml>", stop_at="merged")
```

`stop_at` 是 inclusive：指定的 step 會執行，下游 step 會跳過。這很適合先檢查 PICO merge，再決定要不要加 filter 或 metrics。

### 完整 DAG 範例

完整多步驟範例可看:

- `data/pipeline_examples/ai_in_anesthesiology.yaml`

## 單一職責 Pipeline 工具

Pipeline 管理刻意拆成七個 schema-exact tools。每個 operation 只暴露自己的合法
arguments；拼錯或不相關的欄位會依 v3 MCP contract fail closed。

### 列表

```python
list_pipelines()
list_pipelines(tag="sedation")
list_pipelines(scope="workspace")
```

### 保存

```python
save_pipeline(
    name="weekly_remimazolam",
    config="""
template: comprehensive
template_params:
  query: remimazolam ICU sedation
  sources: [pubmed, openalex, europe_pmc]
  limit: 30
""",
    tags=["sedation", "icu"],
    description="Weekly remimazolam surveillance",
    scope="workspace",
)
```

`config` 必須 parse 成 YAML/JSON mapping，不能是 list 或 scalar。`tags` 必須是
最多 20 個 strict strings 的 JSON array；CSV text 會被拒絕。

`scope` 行為:

- 本機 `workspace`：存在專案底下 `.pubmed-search/pipelines/`
- 本機 `global`：存在使用者資料目錄 `~/.pubmed-search-mcp/pipelines/`
- 本機 `auto`：有 workspace 就存 workspace，否則 global
- 認證 service：tenant-derived store 刻意沒有 process-wide workspace root；
  `auto` 會解析到該 principal 隔離的 data root，`workspace` 不可用

### 載入

```python
load_pipeline(source="weekly_remimazolam")
load_pipeline(source="saved:weekly_remimazolam")
load_pipeline(source="file:data/pipeline_examples/pico_remimazolam_vs_propofol.yaml")
```

目前 `load_pipeline` 支援:

- 已保存名稱
- `saved:<name>`
- 僅本機的 `file:path/to/pipeline.yaml`

認證 service caller 不能從 server host 讀取 `file:` path；請先以名稱存入 YAML。
目前不承諾直接從 URL 載入。

### 刪除

```python
delete_pipeline(name="weekly_remimazolam")
```

### 歷史

```python
get_pipeline_history(name="weekly_remimazolam", limit=10)
```

### 排程

```python
schedule_pipeline(
    name="weekly_remimazolam",
    cron="0 9 * * 1",
    diff_mode=True,
    notify=True,
)
```

### 移除排程

```python
unschedule_pipeline(name="weekly_remimazolam")
```

## Schedule 與 History

### 正確流程

1. 先保存 pipeline
2. 手動執行用 `unified_search(query="", pipeline="saved:<name>")`
3. 定期執行用 `schedule_pipeline(...)`
4. 看歷史用 `get_pipeline_history(name="...")`

### 排程

下列範例需要已啟用 scheduler 的可信任本機 process。`docker-compose.service.yml`
會停用 in-process scheduler；在 service 中存下 schedule metadata 不代表它會自動執行。
啟用 recurring execution 前，請改用手動 run 或提供單一 external leader/lease。

```python
schedule_pipeline(name="weekly_remimazolam", cron="0 9 * * 1")
schedule_pipeline(name="monthly_crispr_review", cron="0 8 1 * *")
schedule_pipeline(name="watch_icu_sedation", cron="0 */6 * * *")
```

Cron 格式是標準 5 欄位:

```text
minute hour day month weekday
```

移除排程:

```python
unschedule_pipeline(name="weekly_remimazolam")
```

### history

```python
get_pipeline_history(name="weekly_remimazolam", limit=5)
```

history 會顯示:

- 執行時間
- 文章總數
- 相較前一次新增多少篇
- 移除多少篇
- 成功或失敗狀態

### 現況限制

- 目前沒有獨立的 `list_schedules()` MCP tool
- 想要穩定追蹤 history / diff，請優先使用「已保存 pipeline」而不是臨時 inline pipeline
- Service mode 保持單 process/單 replica，且其 Compose profile 不執行 scheduled pipelines

## 驗證與精確上限

Pipeline identifier、型別與 enum-like 值採 schema-exact contract。Validator 不會
轉換 scalar 型別、裁切明確值，也不會依 alias、拼字相似度或鄰近 step ID 猜測
caller 意圖；公開的安全上下限都是 validation constraint，不是 normalization rule。

`output.format: json` 是 canonical 合法格式，會原樣保留。

### 不修復、直接報錯的情況

| 問題 | 原因 |
| ---- | ---- |
| 已退役的 template 頂層 `params` | 必須改用 canonical `template_params` |
| 未知或拼錯的 template | 只接受四個 canonical template 名稱 |
| 未知或拼錯的 action | 只接受十個 canonical action 名稱 |
| 缺少或重複 step ID | 不會產生或改寫 step identity |
| 未知或指向未來的 dependency ID | 不會猜測或移除 dependency reference |
| 非法 `on_error`、output format 或 ranking | 不會替換 enum-like 值 |
| output/action/template limit 低於或高於公開範圍 | 明確 limit 不會套 default 或被裁切 |
| 錯誤型別或明確 `null` | 不轉成字串、list、mapping 或 integer |
| template 缺少必要參數 | 例如 `pico` 沒有 `P` 或 `I` |
| 沒有任何 steps 也沒有 template | 無法執行 |
| steps 超過 20 | 超過系統上限 |

### 一個故意寫錯的範例

```yaml
template: clinical
template_params:
  P: ICU patients
  I: remimazolam
output:
  format: xml
  limit: 0
  ranking: impac
```

這份 config 會被拒絕。請明確寫出預期的 canonical 值：

```yaml
template: pico
template_params:
  P: ICU patients
  I: remimazolam
output:
  format: markdown
  limit: 20
  ranking: impact
```

### 實務建議

1. 長 pipeline 在保存或排程前，先用 `dry_run=True` 驗證。
2. Template pipeline 只在參數很簡單時 inline；要 review / 版本控管就存 YAML。
3. 自訂 DAG 先從最小可跑版本開始，再逐步加 `merge`、`metrics`、`filter`。
4. 本機模式需要在可信任 repo 共用時，用 `scope="workspace"`。
5. 本機模式只是自己跨專案重用時，用 `scope="global"`。
6. 認證 service mode 省略 workspace/file paths，並從當前 tenant store 重用 named pipeline。
7. Zotero Keeper 整合維持在 PubMed MCP core 外部。PubMed MCP 只負責產生 RIS/CSL/JSON/wiki notes；Zotero 匯入、duplicate policy、library-specific 行為交給 Zotero Keeper 或其他外部 client。
