# Pipeline 持久化與排程搜尋設計文件

> **Status**: RFC（Request for Comments）
> **Created**: 2026-02-15
> **Scope**: Pipeline 持久化、MCP 檔案傳輸、排程搜尋

---

## 1. 問題描述

### 現狀

目前 Pipeline 系統（v0.4.0）是**完全無狀態的**：

```
Agent 傳入 YAML/JSON → _parse_pipeline_config() → PipelineExecutor → 結果 → 丟棄配置
```

| 面向 | 現狀 | 期望 |
|------|------|------|
| Pipeline 配置 | 每次需要 inline 傳入 | 可保存、命名、重複使用 |
| 執行結果 | 僅一次性回傳 | 可比對歷史結果、追蹤變化 |
| 排程執行 | 不存在 | 定期自動搜尋、新文獻通知 |
| 外部輸入 | 僅 `pipeline` 參數字串 | 可載入檔案、URL |
| MCP 檔案交換 | 無 | Agent 可讀寫 pipeline 檔案 |

### 使用者故事

1. **研究者 A**：「我每週都搜尋同樣的 PICO 問題（remimazolam vs propofol in ICU），能不能存下來一鍵重跑？」
2. **研究者 B**：「我想設定每月自動搜尋 CRISPR gene therapy 的新文獻，有新結果時通知我。」
3. **Lab PI**：「我有 5 個不同主題的搜尋策略，想分享給學生使用。」
4. **系統管理員**：「需要一個 cron-like 機制定期更新文獻資料庫。」

---

## 2. MCP 協議能力分析

### 2.1 MCP Resource 機制

MCP 規範定義了 **Resources** — server 暴露給 client 的唯讀資料：

| 能力 | 支援 | 備註 |
|------|------|------|
| 靜態 Resource (`@mcp.resource`) | ✅ | 固定 URI，如 `pubmed://filters/all` |
| Resource Template (`@mcp.resource("uri/{param}")`) | ✅ | 動態 URI，server 端可讀檔回傳 |
| Client 讀取 Resource | ✅ | `resources/read` method |
| Client 寫入 Resource | ❌ | MCP 規範**無寫入 API** |
| Resource 訂閱/變更通知 | ✅ | `resources/subscribe` + `notifications/resources/updated` |
| Binary content (非文字) | ✅ | 可用 `BlobResourceContents` 回傳 base64 |

**關鍵限制**：MCP Resources 是**唯讀的**。Client（Agent）無法透過 MCP 直接「上傳檔案」或「寫入 Resource」。

### 2.2 MCP Sampling

MCP 2025-03-26 規範新增 **Sampling** 能力，但這是 server 請求 client 做 LLM 推理，非檔案交換。

### 2.3 實際可行的檔案交換方式

| 方法 | 方向 | 實作 |
|------|------|------|
| **Tool 參數（inline）** | Agent → Server | 現行方式：`pipeline="yaml: ..."` |
| **Tool 參數（file path）** | Agent → Server | Agent 提供本地路徑，server 讀取 |
| **Tool 參數（URL）** | Agent → Server | Agent 提供 URL，server `httpx.get()` |
| **Resource Template** | Server → Agent | `pipeline://saved/{name}` 動態讀取 |
| **Tool 回傳值** | Server → Agent | 回傳 YAML/JSON 文字或檔案路徑 |
| **Notification** | Server → Agent | `resources/updated` 通知新結果 |

---

## 3. 架構設計

### 3.1 分層架構（DDD）

```
┌─────────────────────────────────────────────────────────────┐
│ Presentation Layer (MCP)                                     │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ MCP Tools                                               │ │
│  │  • save_pipeline(name, config)     → 保存              │ │
│  │  • list_pipelines()                → 列舉              │ │
│  │  • load_pipeline(name|url|path)    → 載入              │ │
│  │  • delete_pipeline(name)           → 刪除              │ │
│  │  • schedule_pipeline(name, cron)   → 排程              │ │
│  │  • list_schedules()                → 列舉排程          │ │
│  │  • get_pipeline_history(name)      → 執行歷史          │ │
│  ├─────────────────────────────────────────────────────────┤ │
│  │ MCP Resources (唯讀)                                    │ │
│  │  • pipeline://saved/{name}         → 讀取已存 pipeline │ │
│  │  • pipeline://templates/{name}     → 模板參考          │ │
│  │  • pipeline://history/{name}/latest → 最新執行結果     │ │
│  ├─────────────────────────────────────────────────────────┤ │
│  │ MCP Notifications                                       │ │
│  │  • resources/updated               → Pipeline 結果更新 │ │
│  └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│ Application Layer                                            │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ PipelineStore                                           │ │
│  │  • save(name, config, scope) → PipelineMeta            │ │
│  │  • load(name) → PipelineConfig  (workspace → global)   │ │
│  │  • load_from_url(url) → PipelineConfig                 │ │
│  │  • load_from_path(path) → PipelineConfig               │ │
│  │  • list(scope?) → list[PipelineMeta]                   │ │
│  │  • delete(name)                                         │ │
│  │  • get_history(name, limit) → list[PipelineRun]        │ │
│  ├─────────────────────────────────────────────────────────┤ │
│  │ PipelineScheduler                                       │ │
│  │  • schedule(name, cron_expr) → ScheduleEntry           │ │
│  │  • unschedule(name)                                     │ │
│  │  • list_schedules() → list[ScheduleEntry]              │ │
│  │  • _tick() → 檢查到期任務                              │ │
│  ├─────────────────────────────────────────────────────────┤ │
│  │ PipelineExecutor (已有)                                 │ │
│  │  + run_and_store(config) → 執行 + 儲存結果             │ │
│  └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│ Domain Layer                                                 │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Entities                                                │ │
│  │  • PipelineConfig (已有)                                │ │
│  │  • PipelineMeta(name, created, updated, tags, hash)     │ │
│  │  • PipelineRun(id, pipeline_name, started, finished,    │ │
│  │    status, article_count, result_summary)               │ │
│  │  • ScheduleEntry(pipeline_name, cron, next_run,         │ │
│  │    enabled, last_run, last_status)                      │ │
│  └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│ Infrastructure Layer                                         │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ File Storage                                            │ │
│  │  Workspace scope (優先):                                │ │
│  │  • {workspace}/.pubmed-search/pipelines/{name}.yaml    │ │
│  │  • {workspace}/.pubmed-search/pipeline_runs/{name}/    │ │
│  │  Global scope (fallback):                               │ │
│  │  • ~/.pubmed-search-mcp/pipelines/{name}.yaml          │ │
│  │  • ~/.pubmed-search-mcp/pipelines/_index.json          │ │
│  │  • ~/.pubmed-search-mcp/pipeline_runs/{name}/          │ │
│  │    └── {run_id}.json                                    │ │
│  │  • ~/.pubmed-search-mcp/schedules.json                 │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 檔案結構（雙層儲存）

> **決策 D7**：採用 workspace + global 雙層儲存。
> Workspace scope 可 git 追蹤、分享給協作者；Global scope 跨專案共用。

#### 解析優先順序

```
load(name) → 先查 workspace/.pubmed-search/pipelines/{name}.yaml
           → 沒找到 → 查 ~/.pubmed-search-mcp/pipelines/{name}.yaml
           → 都沒有 → 404 error
```

#### Workspace scope（專案級，可 git 追蹤）

```
{workspace}/                         # VS Code workspace root
└── .pubmed-search/                  # 專案級設定目錄
    ├── pipelines/                   # Pipeline 儲存
    │   ├── weekly_remimazolam.yaml   # 已存 pipeline
    │   └── pico_icu_sedation.yaml
    └── pipeline_runs/               # 執行歷史（建議 .gitignore）
        └── weekly_remimazolam/
            └── 20260215_143022.json
```

#### Global scope（使用者級，跨專案）

```
~/.pubmed-search-mcp/               # data_dir (現有)
├── sessions.json                    # 現有
├── article_cache.json               # 現有
├── pipelines/                       # 新增：Pipeline 儲存
│   ├── _index.json                  # 索引：{name → PipelineMeta}
│   ├── weekly_remimazolam.yaml      # 已存 pipeline
│   └── crispr_monthly.yaml
├── pipeline_runs/                   # 新增：執行歷史
│   ├── weekly_remimazolam/
│   │   ├── 20260215_143022.json     # 每次執行的結果摘要
│   │   └── 20260222_143015.json
│   └── pico_icu_sedation/
│       └── 20260215_090000.json
└── schedules.json                   # 新增：排程設定
```

#### Scope 選擇邏輯

| 操作 | 預設 scope | 可覆寫 |
|------|-----------|--------|
| `save_pipeline` | workspace（若有）→ global | `scope` 參數 |
| `load_pipeline` | workspace → global fallback | 自動 |
| `list_pipelines` | 合併顯示（標註 scope） | `scope` 參數過濾 |
| `delete_pipeline` | 精確匹配（先 workspace） | 自動 |
| `get_pipeline_history` | 跟隨 pipeline 所在 scope | 自動 |
| `schedule_pipeline` | 僅 global（排程需跨 workspace） | 固定 |

### 3.3 Pipeline YAML 格式（持久化版本）

```yaml
# ~/.pubmed-search-mcp/pipelines/weekly_remimazolam.yaml
# 與 unified_search pipeline 參數格式完全相容

name: "Weekly Remimazolam Review"
tags: [anesthesia, sedation, remimazolam]

# 方式一：使用模板
template: comprehensive
template_params:
  query: "remimazolam sedation ICU"
  sources: "pubmed,openalex,europe_pmc"
  limit: 30
  min_year: 2024

# 方式二：自定義 steps（與現行格式完全一致）
# steps:
#   - id: s1
#     action: search
#     params: { query: "remimazolam", sources: "pubmed", limit: 20 }
#   ...

output:
  format: markdown
  limit: 20
  ranking: quality

# 持久化特有欄位（不影響執行）
schedule:
  cron: "0 9 * * 1"        # 每週一 09:00
  enabled: true
  notify: true             # 有新結果時通知
  diff_mode: true          # 只顯示與上次不同的結果
```

---

## 4. MCP 工具設計

### 4.1 Pipeline 管理工具

```python
@mcp.tool()
async def save_pipeline(
    name: str,
    config: str,               # YAML/JSON 字串（與 unified_search pipeline 參數規格相同）
    tags: str = "",            # 逗號分隔標籤
    description: str = "",
) -> str:
    """Save a pipeline configuration for reuse.

    The config format is identical to unified_search's pipeline parameter.
    Saved pipelines can be loaded by name in unified_search:
        unified_search(pipeline="saved:weekly_remimazolam")
    """

@mcp.tool()
async def list_pipelines(
    tag: str = "",             # 按標籤過濾
) -> str:
    """List all saved pipeline configurations."""

@mcp.tool()
async def load_pipeline(
    source: str,               # name | file:///path | https://url | saved:name
) -> str:
    """Load a pipeline from name, file path, or URL.

    Supports:
    - Saved pipeline: "weekly_remimazolam" or "saved:weekly_remimazolam"
    - Local file: "file:///path/to/pipeline.yaml"
    - URL: "https://example.com/pipelines/my_search.yaml"

    Returns the pipeline YAML for review before execution.
    To execute, pass the result to unified_search(pipeline=...).
    """

@mcp.tool()
async def delete_pipeline(name: str) -> str:
    """Delete a saved pipeline configuration."""
```

### 4.2 排程工具

```python
@mcp.tool()
async def schedule_pipeline(
    name: str,                 # 已存 pipeline 名稱
    cron: str = "",            # cron 表達式（空 = 停止排程）
    diff_mode: bool = True,    # 只顯示新增文章
    notify: bool = True,       # 有結果時通知
) -> str:
    """Schedule a saved pipeline for periodic execution.

    Cron format: "minute hour day month weekday"
    Examples:
    - "0 9 * * 1"    → Every Monday 9:00 AM
    - "0 0 1 * *"    → First day of each month
    - "0 */6 * * *"  → Every 6 hours
    - ""             → Remove schedule
    """

@mcp.tool()
async def list_schedules() -> str:
    """List all scheduled pipeline executions with next run times."""

@mcp.tool()
async def get_pipeline_history(
    name: str,
    limit: int = 5,
) -> str:
    """Get execution history for a saved pipeline.

    Shows: date, article count, new articles vs. previous run, status.
    """
```

### 4.3 unified_search 擴展

```python
# 現有的 pipeline 參數擴展支援 saved: 和 url: 前綴
async def unified_search(
    ...,
    pipeline: str | None = None,
    # 新增支援格式：
    # "saved:weekly_remimazolam"   → 從持久化載入
    # "url:https://example.com/p.yaml" → 從 URL 載入
    # "file:///path/to/p.yaml"    → 從本地載入（需要 Agent 有 fs 存取）
    # 原有 inline YAML/JSON 仍然支援
):
```

### 4.4 MCP Resource Templates

```python
@mcp.resource("pipeline://saved/{name}")
async def get_saved_pipeline(name: str) -> str:
    """Read a saved pipeline configuration."""
    store = _get_pipeline_store()
    config = store.load(name)
    return yaml.dump(dataclasses.asdict(config))

@mcp.resource("pipeline://templates/{name}")
async def get_template_info(name: str) -> str:
    """Read template reference with parameters and example."""
    entry = PIPELINE_TEMPLATES.get(name)
    return json.dumps(entry, indent=2)

@mcp.resource("pipeline://history/{name}/latest")
async def get_latest_run(name: str) -> str:
    """Read the latest execution result for a pipeline."""
    store = _get_pipeline_store()
    run = store.get_latest_run(name)
    return json.dumps(dataclasses.asdict(run))
```

---

## 5. 排程機制設計

### 5.1 方案比較

| 方案 | 優點 | 缺點 |
|------|------|------|
| **A. 內建 asyncio scheduler** | 零依賴、與 MCP server 同生命週期 | 需 server 持續運行、重啟失去排程 |
| **B. OS cron + CLI entrypoint** | 穩定、系統級排程 | 需要額外 CLI、無法動態管理 |
| **C. APScheduler** | 功能完整、支援 persistence | 新依賴、可能過度設計 |
| **D. 混合方案：內建 tick + JSON state** | 輕量、可恢復 | 精度受限於 tick 間隔 |

### 5.2 推薦方案：D（混合方案）

```
                    ┌─────────────────────────┐
                    │  MCP Server Lifespan     │
                    │                          │
                    │  startup:                │
                    │    load schedules.json   │
                    │    start _tick_loop()    │
                    │                          │
                    │  _tick_loop (每60秒):     │
                    │    for schedule in sched: │
                    │      if should_run():    │
                    │        asyncio.create_   │
                    │          task(execute()) │
                    │        update next_run   │
                    │                          │
                    │  shutdown:               │
                    │    save schedules.json   │
                    │    cancel background     │
                    └─────────────────────────┘
```

**核心邏輯**：

```python
class PipelineScheduler:
    def __init__(self, store: PipelineStore, executor: PipelineExecutor):
        self._store = store
        self._executor = executor
        self._schedules: dict[str, ScheduleEntry] = {}
        self._task: asyncio.Task | None = None

    async def start(self):
        """Load schedules and start tick loop."""
        self._schedules = self._load_schedules()
        self._task = asyncio.create_task(self._tick_loop())

    async def _tick_loop(self):
        """Check every 60 seconds for due pipelines."""
        while True:
            await asyncio.sleep(60)
            now = datetime.now(UTC)
            for name, entry in self._schedules.items():
                if entry.enabled and entry.next_run <= now:
                    asyncio.create_task(self._execute_scheduled(name, entry))
                    entry.next_run = self._compute_next_run(entry.cron)
            self._save_schedules()

    async def _execute_scheduled(self, name: str, entry: ScheduleEntry):
        """Execute a scheduled pipeline and store results."""
        config = self._store.load(name)
        results = await self._executor.execute(config)
        run = PipelineRun(
            pipeline_name=name,
            started=datetime.now(UTC),
            article_count=len(results.articles),
            # diff with previous run...
        )
        self._store.save_run(name, run)
        # Notify via MCP resource update
        if entry.notify:
            await self._notify_resource_updated(name)
```

### 5.3 Diff Mode（增量比對）

```python
def compute_diff(current: list[str], previous: list[str]) -> PipelineDiff:
    """Compare PMID lists between runs.

    Returns:
        new_pmids: 本次新出現的
        removed_pmids: 上次有但本次沒有的
        unchanged_count: 兩次都有的
    """
    current_set = set(current)
    previous_set = set(previous)
    return PipelineDiff(
        new_pmids=sorted(current_set - previous_set),
        removed_pmids=sorted(previous_set - current_set),
        unchanged_count=len(current_set & previous_set),
    )
```

---

## 6. 安全性考量

| 風險 | 緩解措施 |
|------|---------|
| URL 資源注入（SSRF） | 白名單域名：github.com, gist.github.com, raw.githubusercontent.com |
| 本地路徑穿越 | 限制在 `data_dir` 下，禁止 `..` 和符號連結 |
| 排程資源耗盡 | 最小間隔 1 小時、同時最多 5 個排程、執行超時 5 分鐘 |
| 磁碟空間 | 每個 pipeline 最多保留 100 次執行歷史 |
| API Rate Limit | 排程執行使用降級模式（減少 sources、降低 limit） |

---

## 7. 實作階段

### Phase 1: Pipeline 持久化（核心，低風險）

> 預估：2-3 個工作日

| 任務 | 層 | 檔案 |
|------|-----|-----|
| `PipelineMeta`, `PipelineRun` entities | Domain | `domain/entities/pipeline.py` |
| `PipelineStore` (save/load/list/delete) | Application | `application/pipeline/store.py` |
| `save_pipeline`, `list_pipelines`, `load_pipeline`, `delete_pipeline` tools | Presentation | `tools/pipeline_tools.py` |
| Resource templates `pipeline://saved/{name}` | Presentation | `resources.py` |
| DI Container 整合 | Infrastructure | `container.py` |
| Tests | Tests | `tests/test_pipeline_store.py` |

**此階段完成後**：Agent 可以存/取/列舉 pipeline 配置，`unified_search(pipeline="saved:xxx")` 可載入已存方案。

### Phase 2: 外部載入（URL / 檔案路徑）

> 預估：1 個工作日

| 任務 | 層 | 備註 |
|------|-----|-----|
| `load_from_url(url)` | Application | `httpx.get()` + YAML/JSON parse + 域名白名單 |
| `load_from_path(path)` | Application | `pathlib.Path.read_text()` + 路徑驗證 |
| `unified_search` pipeline 參數支援 `url:` `file:` 前綴 | Presentation | 路由到 store |
| 安全測試 | Tests | SSRF 防護、路徑穿越測試 |

### Phase 3: 執行歷史與 Diff

> 預估：1-2 個工作日

| 任務 | 層 | 備註 |
|------|-----|-----|
| `PipelineRun` 持久化 | Application | `pipeline_runs/{name}/{run_id}.json` |
| Diff 計算 | Application | PMID 集合差異 |
| `get_pipeline_history` tool | Presentation | 顯示歷史 + diff |
| Resource `pipeline://history/{name}/latest` | Presentation | 最新結果 |

### Phase 4: 排程搜尋

> 預估：2-3 個工作日（最複雜）

| 任務 | 層 | 備註 |
|------|-----|-----|
| `ScheduleEntry` entity | Domain | cron + state |
| `PipelineScheduler` | Application | tick loop + execute + notify |
| Lifespan 整合 | Presentation | startup/shutdown |
| `schedule_pipeline`, `list_schedules` tools | Presentation | |
| Cron 解析（`croniter` 或自實作） | Infrastructure | 輕量 cron parser |
| Resource 更新通知 | Presentation | `resources/updated` |

---

## 8. 替代方案

### 8.1 不做排程，僅做持久化 + CLI runner

若排程複雜度過高，可改用 OS 級方案：

```bash
# 使用者自行設定 OS cron / Windows Task Scheduler
# 提供 CLI entrypoint 讓 cron 呼叫

# crontab -e
0 9 * * 1  pubmed-search run-pipeline weekly_remimazolam --diff

# 或 Windows Task Scheduler
schtasks /create /tn "WeeklyPubMed" /tr "uv run python -m pubmed_search.cli run-pipeline weekly_remimazolam" /sc weekly /d MON /st 09:00
```

此方案降低內部複雜度，但使用者體驗較差（需手動設定 OS 排程）。

### 8.2 不做獨立工具，擴展 unified_search

不新增 MCP tools，僅擴展 `unified_search` 的 `pipeline` 參數：

```python
# 直接在 pipeline 參數中支援所有操作
unified_search(pipeline="save:my_plan")           # 保存當前搜尋
unified_search(pipeline="saved:my_plan")           # 載入已存
unified_search(pipeline="url:https://example.com") # 從 URL
unified_search(pipeline="list")                    # 列舉
```

優點：不增加 MCP tool 數量。缺點：pipeline 參數語義過載。

---

## 9. 未解決問題

1. **通知機制**：排程執行完成後如何通知 Agent？MCP `resources/updated` 需要 client 有 subscription 支援，目前多數 MCP client (Claude Desktop, Copilot) 可能不支援。替代方案：下次 Agent 連線時在 session 中顯示未讀結果。

2. **多 Server 實例**：Docker 部署中可能有多個 server 副本，排程需避免重複執行。建議使用 file lock 或僅允許一個實例啟用排程。

3. **YAML 依賴**：目前 pipeline 解析已經做了 YAML（`_parse_pipeline_config` 用 `yaml.safe_load`），但 `pyyaml` 是 optional dependency。持久化儲存格式是否統一用 YAML？或允許 JSON/YAML 雙格式？

4. **結果儲存容量**：每次執行的結果摘要存多少？建議存 PMID 列表 + 前 5 篇 metadata（標題/年份/期刊），不存完整 abstract。

5. ~~**Agent 體驗**：新增 4-7 個 MCP tools 是否會造成工具過多？考慮合併為 2 個工具（`pipeline_manage` + `pipeline_schedule`）用 `action` 參數區分。~~
   **✅ 已決策 (D3)**：採用 **Option B — 5 個獨立工具**。見 Section 10 D3 與 Section 11 詳細設計。

---

## 10. 決策記錄

> 在實作前，需要對以下問題做出決策：

| # | 決策 | 選項 | 建議 |
|---|------|------|------|
| D1 | 儲存格式 | JSON / YAML / 兩者 | YAML（人類可讀，與現行 pipeline 參數一致） |
| D2 | 排程實作 | 內建 / OS cron / APScheduler | 內建 tick loop（Phase 4） |
| D3 | 工具數量 | **✅ Option B: 6 個獨立工具** | `save_pipeline`, `list_pipelines`, `load_pipeline`, `delete_pipeline`, `get_pipeline_history`, `schedule_pipeline`。見 Section 11。 |
| D4 | URL 載入安全 | 白名單 / 任意 / 禁止 | 白名單 + 使用者可配置 |
| D5 | 結果儲存 | 完整/摘要/僅PMID | 摘要（PMID + top-5 metadata） |
| D6 | 是否需要 `croniter` 依賴 | 是/自實作 | 視複雜度，簡單 cron 可自實作 |
| D7 | 儲存位置範圍 | **✅ 雙層：workspace + global** | workspace 優先（可 git 追蹤/分享），global 作為跨專案 fallback。見 Section 3.2。 |

---

## 11. Option B 詳細設計：6 個獨立 MCP 工具

> **決策日期**：2026-02-15
> **決策者**：專案維護者
> **理由**：每個工具職責單一明確，符合 MCP 工具的語義設計哲學（一個工具 = 一個動作）。
> 相較 Option A（2 個合併工具用 action 參數區分）語義更清晰，Agent 不需理解 action 子命令。
> 相較 Option C（全合併進 unified_search）避免 unified_search 參數過載。

### 11.1 工具總覽

| # | 工具名稱 | Phase | 類別 | 用途 |
|---|----------|-------|------|------|
| 1 | `save_pipeline` | 1 | pipeline | 保存 pipeline 配置（支援 scope 選擇） |
| 2 | `list_pipelines` | 1 | pipeline | 列舉已存 pipeline（合併 workspace + global） |
| 3 | `load_pipeline` | 1 | pipeline | 載入 pipeline（name / URL / path） |
| 4 | `delete_pipeline` | 1 | pipeline | 刪除已存 pipeline |
| 5 | `get_pipeline_history` | 3 | pipeline | 查詢執行歷史與 diff |
| 6 | `schedule_pipeline` | 4 | pipeline | 排程 / 解除排程 / 查看排程 |

**新增 TOOL_CATEGORIES 條目**：

```python
TOOL_CATEGORIES = {
    ...,
    "pipeline": [
        save_pipeline,
        list_pipelines,
        load_pipeline,
        delete_pipeline,
        get_pipeline_history,
        schedule_pipeline,
    ],
}
```

工具總數變化：33 → 39（+6）

### 11.2 各工具詳細規格

#### Tool 1: `save_pipeline`

```python
@mcp.tool()
async def save_pipeline(
    name: str,
    config: str,
    tags: str = "",
    description: str = "",
    scope: str = "auto",
) -> str:
    """Save a pipeline configuration for later reuse.

    The config format is identical to unified_search's pipeline parameter
    (YAML or JSON). Saved pipelines can be loaded later by name:
        unified_search(pipeline="saved:weekly_remimazolam")

    Args:
        name: Unique identifier (alphanumeric + hyphens/underscores, max 64 chars).
              Overwrites if name already exists (upsert semantics).
        config: Pipeline YAML/JSON string. Same format as unified_search pipeline param.
        tags: Comma-separated tags for filtering (e.g., "anesthesia,sedation").
        description: Human-readable description of the pipeline's purpose.
        scope: Storage scope - "workspace" (project-level, git-trackable),
               "global" (user-level, cross-project), or "auto" (workspace if
               available, otherwise global). Default: "auto".

    Returns:
        Confirmation with pipeline metadata (name, scope, created/updated timestamp, step count).
    """
```

**回傳格式**：

```
✅ Pipeline "weekly_remimazolam" saved successfully.

📋 Metadata:
  Name: weekly_remimazolam
  Description: Weekly remimazolam sedation literature review
  Tags: anesthesia, sedation
  Steps: 3 (search → filter → rank)
  Created: 2026-02-15 14:30:22 UTC
  Config hash: a1b2c3d4

💡 Usage:
  • Execute: unified_search(pipeline="saved:weekly_remimazolam")
  • View: load_pipeline(source="weekly_remimazolam")
  • Schedule: schedule_pipeline(name="weekly_remimazolam", cron="0 9 * * 1")
```

**驗證規則**：
- `name` 匹配 `^[a-zA-Z0-9_-]{1,64}$`
- `config` 必須是有效 YAML/JSON 且可解析為 `PipelineConfig`
- 重複 `name` 時執行 upsert（更新 + 保留歷史）

---

#### Tool 2: `list_pipelines`

```python
@mcp.tool()
async def list_pipelines(
    tag: str = "",
    scope: str = "",
) -> str:
    """List all saved pipeline configurations.

    Args:
        tag: Filter by tag (e.g., "sedation"). Empty = show all.
        scope: Filter by scope: "workspace", "global", or "" (show all). Default: "".

    Returns:
        Table of saved pipelines with name, scope, description, tags, last modified, execution count.
    """
```

**回傳格式**：

```
📦 Saved Pipelines (3 total, 2 workspace + 1 global):

| Name                   | Scope     | Description                          | Tags                  | Modified            | Runs |
|------------------------|-----------|--------------------------------------|-----------------------|---------------------|------|
| weekly_remimazolam     | workspace | Weekly remimazolam sedation review   | anesthesia, sedation  | 2026-02-15 14:30    | 12   |
| pico_icu_sedation      | workspace | PICO: remimazolam vs propofol in ICU | pico, icu             | 2026-02-10 09:00    | 3    |
| crispr_monthly         | global    | Monthly CRISPR gene therapy update   | gene_therapy, crispr  | 2026-02-01 00:00    | 5    |

💡 Load: load_pipeline(source="<name>")
💡 Execute: unified_search(pipeline="saved:<name>")
```

---

#### Tool 3: `load_pipeline`

```python
@mcp.tool()
async def load_pipeline(
    source: str,
) -> str:
    """Load a pipeline configuration for review or editing.

    Loads from one of three sources:
    - Saved name: "weekly_remimazolam" or "saved:weekly_remimazolam"
    - Local file: "file:path/to/pipeline.yaml" (relative to data_dir or absolute)
    - URL: "url:https://example.com/pipelines/my_search.yaml"

    The returned YAML can be reviewed, modified, and then:
    - Executed directly: unified_search(pipeline="<yaml>")
    - Saved with changes: save_pipeline(name="...", config="<yaml>")

    Args:
        source: Pipeline source identifier (see above).

    Returns:
        Full pipeline YAML content + metadata.
    """
```

**回傳格式**：

```
📄 Pipeline: weekly_remimazolam
📍 Source: saved (local)
📅 Last modified: 2026-02-15 14:30:22 UTC

---
template: comprehensive
template_params:
  query: "remimazolam sedation ICU"
  sources: "pubmed,openalex,europe_pmc"
  limit: 30
  min_year: 2024
output:
  format: markdown
  limit: 20
  ranking: quality
---

💡 Execute: unified_search(pipeline="saved:weekly_remimazolam")
💡 Edit & re-save: save_pipeline(name="weekly_remimazolam", config="<modified yaml>")
```

**URL 安全**：
- 白名單域名：`github.com`, `gist.github.com`, `raw.githubusercontent.com`
- 使用者可透過環境變數 `PIPELINE_URL_ALLOWLIST` 擴充
- 回應 Content-Type 必須為 text/plain, text/yaml, application/json, application/yaml
- 最大下載大小：100 KB

---

#### Tool 4: `delete_pipeline`

```python
@mcp.tool()
async def delete_pipeline(
    name: str,
) -> str:
    """Delete a saved pipeline configuration and its execution history.

    Args:
        name: Name of the saved pipeline to delete.

    Returns:
        Confirmation of deletion.
    """
```

**回傳格式**：

```
🗑️ Pipeline "weekly_remimazolam" deleted.
  - Configuration removed
  - 12 execution history records removed
  - Schedule removed (was: every Monday 09:00)
```

**行為**：
- 刪除 `~/.pubmed-search-mcp/pipelines/{name}.yaml`
- 刪除 `~/.pubmed-search-mcp/pipeline_runs/{name}/` 整個目錄
- 若有排程，同時移除排程條目
- 不存在時回傳 404 語義錯誤訊息

---

#### Tool 5: `get_pipeline_history`

```python
@mcp.tool()
async def get_pipeline_history(
    name: str,
    limit: int = 5,
) -> str:
    """Get execution history for a saved pipeline.

    Shows past execution results with diff analysis: which articles are new
    compared to the previous run.

    Args:
        name: Name of the saved pipeline.
        limit: Maximum number of history entries to return (default: 5).

    Returns:
        Execution history with date, article count, new/removed articles, status.
    """
```

**回傳格式**：

```
📊 Execution History for "weekly_remimazolam" (showing 5 of 12):

| # | Date                | Articles | New | Removed | Status |
|---|---------------------|----------|-----|---------|--------|
| 12| 2026-02-15 09:00    | 15       | +3  | -0      | ✅ OK  |
| 11| 2026-02-08 09:00    | 12       | +1  | -0      | ✅ OK  |
| 10| 2026-02-01 09:00    | 11       | +2  | -1      | ✅ OK  |
|  9| 2026-01-25 09:00    | 10       | +0  | -0      | ✅ OK  |
|  8| 2026-01-18 09:00    | 10       | +4  | -0      | ✅ OK  |

Latest new articles (run #12):
  1. PMID 39876543 - "Remimazolam vs propofol for ICU sedation..." (2026)
  2. PMID 39876100 - "Safety profile of remimazolam in critically..." (2026)
  3. PMID 39875999 - "Pharmacokinetics of remimazolam in renal..." (2026)

💡 Full details: fetch_article_details(pmids="39876543,39876100,39875999")
```

**行為**：
- 從 pipeline 所在 scope（workspace 或 global）讀取 `pipeline_runs/{name}/` 目錄
- 每筆執行記錄儲存：PMID 列表 + 前 5 篇 metadata（標題/年份/期刊）
- Diff 計算：與前一次執行的 PMID 集合差異
- 不存在執行歷史時回傳提示「尚未執行過」

---

#### Tool 6: `schedule_pipeline`

```python
@mcp.tool()
async def schedule_pipeline(
    name: str,
    cron: str = "",
    diff_mode: bool = True,
    notify: bool = True,
    action: str = "set",
) -> str:
    """Schedule a saved pipeline for periodic execution, or list all schedules.

    Args:
        name: Saved pipeline name. Use "*" with action="list" to list all schedules.
        cron: Cron expression (5-field). Empty string with action="set" removes schedule.
              Examples: "0 9 * * 1" (Mon 9am), "0 0 1 * *" (monthly), "0 */6 * * *" (6h).
              Minimum interval: 1 hour.
        diff_mode: When True, only report articles not seen in previous run.
        notify: When True, emit MCP resource notification on new results.
        action: "set" (default) to create/update/remove schedule,
                "list" to list all active schedules,
                "status" to show specific pipeline schedule status.

    Returns:
        Schedule confirmation, list of schedules, or status details.
    """
```

**action="set" 回傳**：

```
⏰ Schedule set for "weekly_remimazolam":
  Cron: 0 9 * * 1 (Every Monday at 09:00 UTC)
  Next run: 2026-02-17 09:00 UTC
  Diff mode: enabled (only new articles)
  Notify: enabled
```

**action="list" 回傳**：

```
📅 Active Schedules (2 total):

| Pipeline               | Cron          | Next Run            | Last Run            | Status  |
|------------------------|---------------|---------------------|---------------------|---------|
| weekly_remimazolam     | 0 9 * * 1     | 2026-02-17 09:00    | 2026-02-10 09:00    | ✅ OK   |
| crispr_monthly         | 0 0 1 * *     | 2026-03-01 00:00    | 2026-02-01 00:00    | ✅ OK   |

💡 Modify: schedule_pipeline(name="<name>", cron="<new>")
💡 Remove: schedule_pipeline(name="<name>", cron="")
```

**action="status" 回傳**：

```
📊 Schedule status for "weekly_remimazolam":
  Cron: 0 9 * * 1 (Every Monday at 09:00 UTC)
  Enabled: true
  Next run: 2026-02-17 09:00 UTC
  Last run: 2026-02-10 09:00 UTC
  Last status: ✅ Success (15 articles, 3 new)
  Total runs: 12
  Diff mode: enabled
```

**約束**：
- `name` 必須是已存在的 saved pipeline
- 最小 cron 間隔：1 小時
- 同時最多 5 個活躍排程
- 每次排程執行超時：5 分鐘

### 11.3 兩路由模型完整流程

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Agent 使用流程圖                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  使用者問題 ───┬──── 簡單查詢 ────────────────────────────────────────┐     │
│               │     "搜尋 remimazolam"                                │     │
│               │                                                       ▼     │
│               │                          ┌──────────────────────────────┐   │
│               │                          │ unified_search(query=...)    │   │
│               │                          │ → 即時回傳結果               │   │
│               │                          └──────────────────────────────┘   │
│               │                                                              │
│               └──── 複雜/重複需求 ────────────────────────────────┐         │
│                     "每週搜尋 remimazolam vs propofol"            │         │
│                                                                    ▼         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │ Step 1: 建立 pipeline                                              │    │
│  │   save_pipeline(name="weekly_remi", config="template: pico\n...")  │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │ Step 2: 測試執行                                                   │    │
│  │   unified_search(pipeline="saved:weekly_remi")                     │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │ Step 3: 設定排程（可選）                                            │    │
│  │   schedule_pipeline(name="weekly_remi", cron="0 9 * * 1")          │    │
│  ├─────────────────────────────────────────────────────────────────────┤    │
│  │ Step 4: 之後任何時候                                                │    │
│  │   unified_search(pipeline="saved:weekly_remi")  → 手動重跑         │    │
│  │   load_pipeline(source="weekly_remi")           → 查看/編輯        │    │
│  │   list_pipelines()                              → 列舉所有         │    │
│  │   schedule_pipeline(name="*", action="list")    → 查看排程         │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  關鍵原則：                                                                  │
│  • unified_search 是唯一的「搜尋執行」入口                                    │
│  • Pipeline 工具只做 CRUD + 排程管理，不直接執行搜尋                           │
│  • 排程觸發時由 PipelineScheduler 內部呼叫 PipelineExecutor                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 11.4 DDD 實作檔案對照

| 層 | 新增/修改 | 檔案路徑 | 說明 |
|----|-----------|----------|------|
| Domain | 新增 | `domain/entities/pipeline.py` | 新增 `PipelineMeta`, `PipelineRun`, `ScheduleEntry` |
| Application | 新增 | `application/pipeline/store.py` | `PipelineStore` CRUD + 雙層 scope 解析 |
| Application | 新增 | `application/pipeline/scheduler.py` | `PipelineScheduler` tick loop |
| Application | 修改 | `application/pipeline/executor.py` | 新增 `run_and_store()` 方法 |
| Presentation | 新增 | `presentation/mcp_server/tools/pipeline_tools.py` | 6 個 MCP 工具 |
| Presentation | 修改 | `presentation/mcp_server/tools/__init__.py` | 註冊 pipeline tools |
| Presentation | 修改 | `presentation/mcp_server/tool_registry.py` | 新增 `pipeline` category |
| Presentation | 修改 | `presentation/mcp_server/resources.py` | 新增 Resource templates |
| Presentation | 修改 | `presentation/mcp_server/server.py` | Lifespan 整合 scheduler |
| Infrastructure | 修改 | `container.py` | DI 註冊 PipelineStore + Scheduler |
| Tests | 新增 | `tests/test_pipeline_store.py` | Store CRUD + scope 測試 |
| Tests | 新增 | `tests/test_pipeline_scheduler.py` | Scheduler 測試 |
| Tests | 新增 | `tests/test_pipeline_tools.py` | MCP 工具整合測試 |
| Tests | 新增 | `tests/test_pipeline_history.py` | 執行歷史 + diff 測試 |

### 11.5 曾考慮但未採用的方案

#### Option A: 2 個合併工具

```python
pipeline_manage(action="save|list|load|delete", name=..., config=...)
pipeline_schedule(action="set|remove|list|status", name=..., cron=...)
```

**未採用原因**：`action` 參數讓 Agent 需要理解子命令語義，增加認知負擔。不符合 MCP 工具「一個工具 = 一個動作」的設計哲學。

#### Option C: 全合併進 unified_search

```python
unified_search(pipeline="save:my_plan")
unified_search(pipeline="list")
unified_search(pipeline="delete:my_plan")
```

**未採用原因**：`unified_search` 的語義是「執行搜尋」，CRUD 操作語義不符。pipeline 參數過載導致用途模糊。

---

## 附錄 A：現有 Pipeline 系統互動範例

```yaml
# 現行方式：Agent 在 unified_search 中 inline 傳入
# unified_search(pipeline="...")

template: comprehensive
template_params:
  query: "remimazolam sedation"
  sources: "pubmed,openalex"
  limit: 20
```

```yaml
# 提議的持久化方式
# Step 1: save_pipeline(name="weekly_remi", config="...")
# Step 2: unified_search(pipeline="saved:weekly_remi")
# Step 3: schedule_pipeline(name="weekly_remi", cron="0 9 * * 1")
```

## 附錄 B：MCP Resource Template 範例

```python
# MCP SDK v2 MCPServer resource template decorator 語法
@mcp.resource("pipeline://saved/{name}")
async def read_saved_pipeline(name: str) -> str:
    """MCP clients can read saved pipelines via resources/read."""
    store: PipelineStore = ctx.request_context.lifespan_context["pipeline_store"]
    config = store.load(name)
    return yaml.dump(config.to_dict(), allow_unicode=True)
```

## 附錄 C：Cron 表達式參考

| 表達式 | 含義 |
|--------|------|
| `0 9 * * 1` | 每週一 09:00 |
| `0 0 1 * *` | 每月 1 日 00:00 |
| `0 */6 * * *` | 每 6 小時 |
| `30 8 * * 1-5` | 週一至五 08:30 |
| `0 0 * * 0` | 每週日 00:00 |
