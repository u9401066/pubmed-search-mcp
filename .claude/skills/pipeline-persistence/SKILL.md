---
name: pipeline-persistence
description: "Pipeline persistence — save, load, and reuse structured search plans. Triggers: pipeline, 管道, search plan, 搜尋計畫, 重複搜尋, saved search, 排程, schedule, workflow, DAG"
---

# Pipeline 持久化 — 結構化搜尋計畫管理

## 描述
將複雜的搜尋流程保存為可重複使用的 Pipeline YAML 配置。支援：
- 從模板快速建立（PICO、comprehensive、exploration、gene_drug）
- 自訂 DAG（有向無環圖）多步驟管道
- 雙層儲存（workspace + global）
- 自動驗證 + 激進式自動修正（21 條規則）

## 觸發條件
- 「把這個搜尋存起來」、「建立搜尋計畫」
- 「每週跑一次這個搜尋」、「保存這個 pipeline」
- 「列出我的管道」、「上次的搜尋可以再跑嗎」
- 「把剛才的搜尋轉成 search plan」

---

## 🌟 快速開始

### 方法 1: 用模板（最簡單）

```python
# 保存一個 PICO 模板 pipeline
save_pipeline(
    name="icu_remimazolam_vs_propofol",
    config="""
template: pico
params:
  P: ICU patients requiring sedation
  I: remimazolam
  C: propofol
  O: delirium incidence, sedation quality
""",
    tags="anesthesia,sedation,ICU",
    description="Weekly monitoring: remimazolam vs propofol ICU sedation"
)

# 執行已保存的 pipeline
unified_search(pipeline="saved:icu_remimazolam_vs_propofol")
```

### 方法 2: 自訂 DAG（完整控制）

```python
save_pipeline(
    name="brca1_comprehensive",
    config="""
steps:
  - id: expand
    action: expand
    params:
      topic: BRCA1 breast cancer
  - id: pubmed
    action: search
    params:
      query: BRCA1 breast cancer
      sources: pubmed
      limit: 50
  - id: expanded
    action: search
    inputs: [expand]
    params:
      strategy: mesh
      sources: pubmed,openalex
      limit: 50
  - id: merged
    action: merge
    inputs: [pubmed, expanded]
    params:
      method: rrf
  - id: enriched
    action: metrics
    inputs: [merged]
output:
  format: markdown
  limit: 30
  ranking: quality
""",
    tags="genetics,oncology",
    description="BRCA1 breast cancer comprehensive search with MeSH expansion"
)
```

---

## 6 個 MCP 工具

### save_pipeline — 保存管道

```python
save_pipeline(
    name="weekly_remimazolam",     # 唯一名稱 (英數 + _ -, max 64)
    config="<YAML or JSON>",       # Pipeline 配置
    tags="tag1,tag2",              # 逗號分隔標籤
    description="...",             # 人類可讀描述
    scope="auto"                   # "workspace" | "global" | "auto"
)
```

**自動修正範例：**
- `action: "find"` → 自動修正為 `action: "search"`（別名解析）
- `action: "serach"` → 自動修正為 `action: "search"`（模糊匹配）
- 缺少 step ID → 自動生成 `step_1`, `step_2`...
- 重複 step ID → 自動重命名 `s1` → `s1_2`
- 循環依賴 → 自動移除問題引用

### list_pipelines — 列出管道

```python
list_pipelines()                    # 列出所有
list_pipelines(tag="ICU")           # 按標籤過濾
list_pipelines(scope="workspace")   # 只看工作區
```

### load_pipeline — 載入管道

```python
load_pipeline(source="weekly_remimazolam")            # 從已保存
load_pipeline(source="file:path/to/pipeline.yaml")    # 從檔案
```

### delete_pipeline — 刪除管道

```python
delete_pipeline(name="old_search")  # 刪除配置 + 歷史
```

### get_pipeline_history — 查看執行歷史

```python
get_pipeline_history(name="weekly_remimazolam", limit=5)
# 顯示：日期、文章數、新增/移除文章、狀態
```

### schedule_pipeline — 排程（Phase 4 尚未實作）

```python
schedule_pipeline(name="weekly_remimazolam", cron="0 9 * * 1")
# ⚠️ 目前返回使用說明，建議手動執行或使用 OS 排程
```

---

## 4 個內建模板

### pico — PICO 臨床問題

```yaml
template: pico
params:
  P: ICU patients requiring sedation
  I: remimazolam
  C: propofol
  O: delirium incidence
  sources: pubmed        # 可選，預設 pubmed
  limit: 20              # 可選
```

**自動產生的 DAG：**
```
pico → search_p  ──┐
     → search_i  ──┤
     → search_c  ──┼→ merged → enriched
```

### comprehensive — 多資料庫 + MeSH 擴展

```yaml
template: comprehensive
params:
  query: CRISPR gene therapy safety
  sources: pubmed,openalex,europe_pmc  # 可選
  limit: 30                             # 可選
  min_year: 2020                        # 可選
```

**自動產生的 DAG：**
```
expand → search_expanded  ──┐
         search_original  ──┼→ merged → enriched
```

### exploration — 種子論文探索

```yaml
template: exploration
params:
  pmid: "33475315"
  limit: 20        # 每個方向的限制
```

**自動產生的 DAG：**
```
related  ──┐
citing   ──┼→ merged → enriched
refs     ──┘
```

### gene_drug — 基因/藥物搜尋

```yaml
template: gene_drug
params:
  term: BRCA1
  sources: pubmed,openalex  # 可選
  limit: 20                  # 可選
  min_year: 2020             # 可選
```

---

## 10 個可用 Action

| Action | 說明 | 主要參數 |
|--------|------|----------|
| `search` | 文獻搜尋 | `query`, `sources`, `limit`, `min_year`, `max_year` |
| `pico` | PICO 元素解析 | `P`, `I`, `C`, `O` |
| `expand` | MeSH/同義詞擴展 | `topic` |
| `details` | 取得文章詳情 | `pmids` |
| `related` | 相關文章 | `pmid`, `limit` |
| `citing` | 引用文章 | `pmid`, `limit` |
| `references` | 參考文獻 | `pmid`, `limit` |
| `metrics` | iCite 引用指標 | （從 inputs 取得） |
| `merge` | 合併結果 | `method`: `union` / `intersection` / `rrf` |
| `filter` | 過濾結果 | `min_year`, `max_year`, `article_types`, `min_citations`, `has_abstract` |

---

## 雙層儲存模型

```
Workspace scope (.pubmed-search/pipelines/)
├── 每個專案獨立
├── 可納入 git 追蹤
└── 團隊共享

Global scope (~/.pubmed-search-mcp/pipelines/)
├── 跨專案共用
├── 個人偏好
└── 通用模板
```

**解析順序：** workspace 優先 → global fallback

---

## 生產級範例

### 範例 1: 週報搜尋 — 麻醉藥物監控

```yaml
name: weekly_anesthesia_monitoring
steps:
  - id: search_remimazolam
    action: search
    params:
      query: remimazolam
      sources: pubmed,europe_pmc
      limit: 50
      min_year: 2024
  - id: search_dex
    action: search
    params:
      query: dexmedetomidine ICU sedation
      sources: pubmed
      limit: 50
      min_year: 2024
  - id: merged
    action: merge
    inputs: [search_remimazolam, search_dex]
    params:
      method: union
  - id: filtered
    action: filter
    inputs: [merged]
    params:
      has_abstract: true
      article_types: "Journal Article,Clinical Trial,Randomized Controlled Trial"
  - id: enriched
    action: metrics
    inputs: [filtered]
output:
  format: markdown
  limit: 30
  ranking: recency
```

### 範例 2: 種子論文深度探索

```yaml
name: explore_landmark_paper
steps:
  - id: seed_details
    action: details
    params:
      pmids: "33475315"
  - id: related
    action: related
    params:
      pmid: "33475315"
      limit: 30
  - id: citing
    action: citing
    params:
      pmid: "33475315"
      limit: 30
  - id: refs
    action: references
    params:
      pmid: "33475315"
      limit: 30
  - id: merged
    action: merge
    inputs: [related, citing, refs]
    params:
      method: rrf
  - id: enriched
    action: metrics
    inputs: [merged]
output:
  format: markdown
  limit: 25
  ranking: impact
```

### 範例 3: 系統性文獻回顧 — SGLT2 + 心衰竭

```yaml
name: sglt2_heart_failure_review
steps:
  - id: pico
    action: pico
    params:
      P: Type 2 diabetes with heart failure
      I: SGLT2 inhibitors
      C: standard care
      O: hospitalization, mortality
  - id: mesh_expand
    action: expand
    params:
      topic: SGLT2 inhibitors heart failure outcomes
  - id: search_pico_p
    action: search
    inputs: [pico]
    params:
      element: P
      sources: pubmed,europe_pmc
      limit: 100
  - id: search_pico_i
    action: search
    inputs: [pico]
    params:
      element: I
      sources: pubmed,europe_pmc
      limit: 100
  - id: search_expanded
    action: search
    inputs: [mesh_expand]
    params:
      strategy: mesh
      sources: pubmed,openalex
      limit: 100
  - id: merged
    action: merge
    inputs: [search_pico_p, search_pico_i, search_expanded]
    params:
      method: rrf
  - id: filtered
    action: filter
    inputs: [merged]
    params:
      min_year: 2018
      has_abstract: true
  - id: enriched
    action: metrics
    inputs: [filtered]
output:
  format: markdown
  limit: 50
  ranking: quality
```

---

## Agent 產生 Pipeline 的最佳實踐

### 將對話搜尋轉為 Pipeline

Agent 在完成一次成功搜尋後，可以：

```python
# 1. 回顧剛才的搜尋策略
# 2. 轉化為 Pipeline YAML
save_pipeline(
    name="auto_from_session",
    config="""
steps:
  - id: main_search
    action: search
    params:
      query: "<剛才的查詢>"
      sources: pubmed,openalex
      limit: 50
  - id: enriched
    action: metrics
    inputs: [main_search]
output:
  limit: 20
  ranking: balanced
""",
    description="Auto-generated from search session"
)

# 3. 下次直接重複
# unified_search(pipeline="saved:auto_from_session")
```

### 常見模式

| 場景 | 推薦模板 | 說明 |
|------|----------|------|
| 臨床問題 A vs B | `pico` | 自動解析 PICO、並行搜尋 |
| 主題綜合搜尋 | `comprehensive` | 多源 + MeSH 擴展 |
| 已知重要論文 | `exploration` | 三方向探索（related/citing/refs） |
| 基因/藥物研究 | `gene_drug` | 詞彙擴展 + 多源 |
| 複雜工作流 | 自訂 DAG | 完全控制每個步驟 |
