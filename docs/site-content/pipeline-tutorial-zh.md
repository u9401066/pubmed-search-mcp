<!-- Generated from docs/PIPELINE_MODE_TUTORIAL.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# Pipeline Mode Tutorial

> Status: current API tutorial
> Last updated: 2026-04-29
> Language: [English](#/pipeline-tutorial) | **繁體中文**

這份文件只描述目前真的可用的 pipeline mode 行為，不重複 RFC 設計稿。重點是直接可執行、可保存、可排程、可查歷史。

## Pipeline Mode 快速上手

Pipeline mode 有 3 種最常用入口：

1. 直接把 YAML/JSON 丟給 `unified_search(..., pipeline="...")`
2. 先用 `manage_pipeline` 或 `save_pipeline` 保存，再用 `saved:<name>` 執行
3. 保存後交給 `schedule_pipeline` 或 `manage_pipeline(action="schedule")` 定期跑

### 最短可用範例: inline template

```python
unified_search(
    query="",
    pipeline="""
template: pico
params:
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
manage_pipeline(
    action="save",
    name="icu_remi_vs_propofol",
    config="""
template: pico
params:
  P: ICU patients requiring mechanical ventilation
  I: remimazolam
  C: propofol
  O: delirium, sedation quality
output:
  limit: 25
  ranking: quality
""",
    tags="icu,sedation,remimazolam",
    description="ICU sedation comparison",
)

unified_search(query="", pipeline="saved:icu_remi_vs_propofol")
```

### Structured output 與後續工具

Pipeline Markdown report 會包含 filter diagnostics，也會在底部附上後續 handoff 建議：

- `get_session_pmids()` 取回這次 run 的 PMID set
- `prepare_export(pmids="last", format="ris")` 交給 Zotero/EndNote/Mendeley 類引用管理器
- `save_literature_notes(pmids="last", format="wiki")` 存成本機 wiki/Foam-compatible Markdown 筆記

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
| 想重複使用同一個搜尋策略 | `manage_pipeline(action="save")` |
| 想看歷史 diff 或排程 | 先保存，再用 `saved:<name>` / `schedule_pipeline` |
| 想從本機 YAML 檔載入再調整 | `load_pipeline(source="file:path/to/pipeline.yaml")` |

## Template Pipeline 教學

Template pipeline 適合 80% 的常見需求。它不是把 YAML 原封不動送進 executor，而是先展開成真正的 step DAG。

### 目前可用的 4 個 templates

| Template | 必填參數 | 常用可選參數 | 用途 |
| -------- | -------- | ------------ | ---- |
| `pico` | `P`, `I` | `C`, `O`, `sources`, `limit` | 臨床比較問題 |
| `comprehensive` | `query` | `sources`, `limit`, `min_year`, `max_year` | 多來源全面搜尋 |
| `exploration` | `pmid` | `limit` | 從一篇 seed paper 往外探索 |
| `gene_drug` | `term` | `sources`, `limit`, `min_year`, `max_year` | 基因或藥物主題搜尋 |

### `params` 與 `template_params`

- inline YAML 最短寫法用 `params`
- `save_pipeline` / `manage_pipeline(save)` / `load_pipeline` 也接受 `template_params`
- 載入已保存 pipeline 時，系統通常會輸出成 `template_params`

建議:

- 手寫 inline pipeline 時用 `params`
- 要長期保存或 review 的 YAML，用 `template_params` 可讀性比較穩定

### `pico`

```yaml
template: pico
params:
  P: ICU patients requiring sedation
  I: remimazolam
  C: propofol
  O: delirium incidence, time to extubation
  sources: pubmed,europe_pmc
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
  sources: pubmed,openalex,europe_pmc
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
params:
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
  sources: pubmed,openalex
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
      sources: pubmed,openalex
      limit: 60
      min_year: 2020

  - id: search_mesh
    action: search
    inputs: [expand]
    params:
      strategy: mesh
      sources: pubmed,europe_pmc
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
| `id` | 建議必填 | 不填也會 auto-fix，但最好自己取名 |
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
  sources: pubmed,europe_pmc
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
      article_types: [RCT, systematic review]
      has_abstract: true
output:
  limit: 20
  ranking: quality
```

`article_types` 支援 canonical 值，例如 `randomized-controlled-trial`，也支援常見 alias，例如 `RCT`、`randomized controlled trial`、`systematic review`、`meta analysis`。未知 article type 會 fail closed 並附 warning，不會默默關掉 type filter。Filter report 會顯示篩選前後數量、排除原因、article type mapping、以及被排除文章範例。

### `search` 會怎麼吃上游結果

`search` 不一定要自己寫 `query`，它也能從上游 step 導出 query:

- 上游是 `pico` 時，可用 `element: P|I|C|O`
- 上游是 `pico` 時，也可用 `use_combined: precision|recall`
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

## manage_pipeline 用法

`manage_pipeline` 是目前最推薦的 facade。舊工具仍保留，但新教學都以 facade 為主。

### `action="list"`

```python
manage_pipeline()
manage_pipeline(action="list")
manage_pipeline(action="list", tag="sedation")
manage_pipeline(action="list", scope="workspace")
```

### `action="save"`

```python
manage_pipeline(
    action="save",
    name="weekly_remimazolam",
    config="""
template: comprehensive
template_params:
  query: remimazolam ICU sedation
  sources: pubmed,openalex,europe_pmc
  limit: 30
""",
    tags="sedation,icu",
    description="Weekly remimazolam surveillance",
    scope="workspace",
)
```

`config` 必須 parse 成 YAML/JSON mapping，不能是 list 或 scalar。如果某個 client 很難正確 quote 多行 YAML 給 `manage_pipeline(action="save")`，可以改用 `save_pipeline(name=..., config=...)` 傳同一段 YAML；兩個工具共用同一套 validator。

`scope` 行為:

- `workspace`: 存在專案底下 `.pubmed-search/pipelines/`
- `global`: 存在使用者資料目錄 `~/.pubmed-search-mcp/pipelines/`
- `auto`: 有 workspace 就存 workspace，否則 global

### `action="load"`

```python
manage_pipeline(action="load", source="weekly_remimazolam")
manage_pipeline(action="load", source="saved:weekly_remimazolam")
manage_pipeline(action="load", source="file:data/pipeline_examples/pico_remimazolam_vs_propofol.yaml")
```

目前 `load_pipeline` / `manage_pipeline(load)` 支援:

- 已保存名稱
- `saved:<name>`
- `file:path/to/pipeline.yaml`

目前不承諾直接從 URL 載入。

### `action="delete"`

```python
manage_pipeline(action="delete", name="weekly_remimazolam")
```

### `action="history"`

```python
manage_pipeline(action="history", name="weekly_remimazolam", limit=10)
```

### `action="schedule"`

```python
manage_pipeline(
    action="schedule",
    name="weekly_remimazolam",
    cron="0 9 * * 1",
    diff_mode=True,
    notify=True,
)
```

### 舊工具對照

| Facade | 舊工具 |
| ------ | ------ |
| `manage_pipeline(action="save", ...)` | `save_pipeline(...)` |
| `manage_pipeline(action="list", ...)` | `list_pipelines(...)` |
| `manage_pipeline(action="load", ...)` | `load_pipeline(...)` |
| `manage_pipeline(action="delete", ...)` | `delete_pipeline(...)` |
| `manage_pipeline(action="history", ...)` | `get_pipeline_history(...)` |
| `manage_pipeline(action="schedule", ...)` | `schedule_pipeline(...)` |

## Schedule 與 History

### 正確流程

1. 先保存 pipeline
2. 手動執行用 `unified_search(query="", pipeline="saved:<name>")`
3. 定期執行用 `schedule_pipeline(...)` 或 `manage_pipeline(action="schedule", ...)`
4. 看歷史用 `get_pipeline_history(name="...")` 或 facade 的 `history`

### 排程

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
schedule_pipeline(name="weekly_remimazolam", cron="")
```

### history

```python
get_pipeline_history(name="weekly_remimazolam", limit=5)
manage_pipeline(action="history", name="weekly_remimazolam", limit=5)
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

## 常見錯誤與 Auto-fix 行為

目前 auto-fix 主要發生在 schema parse 與 semantic validation。也就是說，系統會先修資料形狀，再修語意問題。

### 會自動修正的情況

| 問題 | 輸入 | 修正結果 |
| ---- | ---- | -------- |
| action alias | `find` | `search` |
| action typo | `searc` | `search` |
| template alias | `clinical` | `pico` |
| template typo | `comprehensiv` | `comprehensive` |
| 單一字串 inputs | `inputs: s1` | `inputs: [s1]` |
| 非 dict 的 params | `params: "oops"` | `params: {}` |
| 缺少 step id | `id: ""` | 自動補 `step_1` 之類 |
| 重複 step id | `search`, `search` | 第二個改成 `search_2` |
| 引用不存在的 step | `inputs: [missing]` | 該引用移除 |
| 引用未來 step | `inputs: [later_step]` | 該引用移除 |
| `on_error` 非法 | `retry` | `skip` |
| output format 非法 | `xml` | `markdown` |
| output ranking typo | `impac` | `impact` |
| output limit 非法 | `0` 或負數 | `20` |

`output.format: json` 是合法格式，不會再被 auto-fix 成 Markdown。

### 不會自動修正，會直接報錯的情況

| 問題 | 原因 |
| ---- | ---- |
| template 名稱完全無法辨識 | 沒有 alias 或 fuzzy match 可套用 |
| action 名稱完全無法辨識 | 沒有 alias 或 fuzzy match 可套用 |
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

目前系統會自動把它修成等價於:

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

1. 想吃到 auto-fix、history、schedule，先保存再跑。
2. Template pipeline 只在參數很簡單時 inline；要 review / 版本控管就存 YAML。
3. 自訂 DAG 先從最小可跑版本開始，再逐步加 `merge`、`metrics`、`filter`。
4. 需要團隊共享時用 `scope="workspace"`。
5. 只想跨專案重用自己的搜尋習慣時用 `scope="global"`。
6. Zotero Keeper 整合維持在 PubMed MCP core 外部。PubMed MCP 只負責產生 RIS/CSL/JSON/wiki notes；Zotero 匯入、duplicate policy、library-specific 行為交給 Zotero Keeper 或其他外部 client。
