# Repository Separation Principles

> Status: repo-level design guide
> Last updated: 2026-04-06

這份文件定義本 repo 後續重構與新功能設計時必須維持的三條主分離線。它的目的不是把大檔拆成小檔，而是讓系統在功能持續增加時，仍然能穩定演化。

## Goal

我們要追的完整性是：

1. structural correctness 和 semantic correctness 分離
2. policy decision 和 runtime side effect 分離
3. tool surface 和 application service 分離

如果這三條線沒有被守住，fulltext、query planning、timeline policy、Copilot hooks、pipeline orchestration 之後都會重新糾纏在一起。

## Non-Goal

這份文件不是檔案切割指南。

把一個 800 行檔案拆成 4 個 200 行檔案，如果責任邊界還是混在一起，架構上沒有任何實質改善。

真正的目標是讓每一層回答不同問題：

- structural layer 回答「這個輸入形狀是否可被接受、正規化、建模？」
- semantic layer 回答「這個輸入在領域語意上是否合理、可修正、可規劃？」
- policy layer 回答「在既有規則下應該做哪種決策？」
- runtime layer 回答「決策確定後，真正要執行哪些 I/O、狀態更新、排程或輸出？」
- tool surface 回答「對外 API 如何穩定暴露？」
- application service 回答「實際 use case 如何被協調執行？」

## Why This Matters

當這三條分離線成立時，系統會得到三個可持續的好處：

1. 可測性上升。policy、schema、semantic validator、service orchestration 可以各自獨立測。
2. 演化成本下降。新增來源、改 ranking、換 heuristics，不需要反覆動 MCP tool surface。
3. 相容性變好。presentation layer 可以保留 legacy wrappers，但內部服務與 policy 可以持續演進。

## Principle 1: Structural Correctness vs Semantic Correctness

### Structural vs Semantic Definition

Structural correctness 是「資料形狀正不正確」。

它處理：

- raw mapping 是否為 dict
- type coercion
- alias shape normalization
- default values
- discriminated union / mode detection
- 基本欄位存在性與長度限制

Semantic correctness 是「資料語意合不合理」。

它處理：

- fuzzy alias resolution
- domain-specific auto-fix
- dependency repair
- ranking / template / strategy semantic correction
- query planning intent correction
- workflow-level consistency

### Structural vs Semantic Rule

Structural correctness 必須先於 semantic correctness，而且兩者不能混在同一個主要入口中。

標準流程應該是：

```text
raw input
  -> structural parser / schema
  -> typed config or normalized request
  -> semantic validator / planner
  -> executable domain/application object
```

### Structural vs Semantic Current Example

pipeline 已經是這個模式的第一個正式樣板：

- [src/pubmed_search/application/pipeline/schema.py](src/pubmed_search/application/pipeline/schema.py) 處理 structural parsing
- [src/pubmed_search/application/pipeline/validator.py](src/pubmed_search/application/pipeline/validator.py) 處理 semantic auto-fix

這個分離要被視為 repo pattern，不是 pipeline 特例。

### Structural vs Semantic Future Targets

- fulltext request normalization: identifier shape 與 semantic retrieval intent 應分離
- query planning: request schema、semantic planner、dispatch policy 應分離
- timeline: request schema、semantic validation、milestone policy 應分離

### Structural vs Semantic Anti-Patterns

- 在 schema parser 裡做 fuzzy semantic repair
- 在 semantic validator 裡回頭處理 raw JSON shape 錯誤
- 用單一函式同時做 parse、autofix、execute

## Principle 2: Policy Decision vs Runtime Side Effect

### Policy vs Runtime Definition

Policy decision 是「應該怎麼決定」。

它包含：

- tool classification
- threshold tables
- source participation rules
- milestone heuristics
- dispatch profiles
- retry / fallback / expansion strategy selection

Runtime side effect 是「決定做完後，真正去執行什麼」。

它包含：

- HTTP calls
- filesystem writes
- session state updates
- scheduler registration
- audit logging
- hook deny / allow output
- formatted MCP responses

### Policy vs Runtime Rule

Policy 必須是可單獨載入、可單獨測試、可單獨替換的決策層。

Runtime code 只能消費 policy 的結果，不應把 policy table 和 side effect 混寫在同一段流程控制裡。

標準流程應該是：

```text
request / context
  -> policy resolver
  -> decision / plan / classification
  -> runtime executor
  -> side effects
```

### Policy vs Runtime Current Examples

- Copilot hooks:
  - [/.github/hooks/copilot-tool-policy.json](.github/hooks/copilot-tool-policy.json) 持有 policy
  - [scripts/hooks/copilot/enforce-pipeline.ps1](scripts/hooks/copilot/enforce-pipeline.ps1) 與 [scripts/hooks/copilot/evaluate-results.ps1](scripts/hooks/copilot/evaluate-results.ps1) 執行 runtime side effects
- source selection:
  - [src/pubmed_search/infrastructure/sources/registry.py](src/pubmed_search/infrastructure/sources/registry.py) 持有 source policy 與 gating metadata
  - [src/pubmed_search/presentation/mcp_server/tools/unified.py](src/pubmed_search/presentation/mcp_server/tools/unified.py) 消費決策結果後才做實際 dispatch

### Policy vs Runtime Expected Extensions

- timeline 應維持 milestone policy / landmark policy 與 builder / detector / formatter 的分離
- fulltext 應把 retrieval policy 與 fetch / extract / persistence side effect 分離
- query planning 應把 planning policy 與 actual search execution 分離

### Policy vs Runtime Anti-Patterns

- 在 runtime function 內硬編 threshold 與分類規則
- policy 檔本身依賴 filesystem 或 network state
- side effect function 同時負責決定規則與執行規則

## Principle 3: Tool Surface vs Application Service

### Tool vs Service Definition

Tool surface 是對 MCP client 暴露的公開介面。

它的責任是：

- 參數命名與 backward compatibility
- input normalization
- progress / task / permission integration
- output formatting
- facade action routing

Application service 是用例編排層。

它的責任是：

- orchestration
- repository / store / scheduler / source client coordination
- domain object assembly
- report generation
- application-level result objects

### Tool vs Service Rule

presentation tool 不應長期持有 use case orchestration、cross-source branching、state persistence policy。

tool 可以是 facade，但 facade 之下必須盡量落到 application service，而不是讓 tool module 自己長成 orchestration center。

標準流程應該是：

```text
MCP tool
  -> normalize request
  -> call application service
  -> format stable response
```

### Tool vs Service Current Examples

- facade pattern:
  - [src/pubmed_search/presentation/mcp_server/session_tools.py](src/pubmed_search/presentation/mcp_server/session_tools.py) 的 `read_session`
  - [src/pubmed_search/presentation/mcp_server/tools/pipeline_tools.py](src/pubmed_search/presentation/mcp_server/tools/pipeline_tools.py) 的 `manage_pipeline`
- application service direction:
  - [src/pubmed_search/application/pipeline/runner.py](src/pubmed_search/application/pipeline/runner.py)
  - [src/pubmed_search/infrastructure/scheduling/pipeline_scheduler.py](src/pubmed_search/infrastructure/scheduling/pipeline_scheduler.py)

### Tool vs Service Next Target

fulltext 是下一個應該明確落實這條分離線的地方。

目標狀態已在 [docs/FULLTEXT_REGISTRY_REFACTOR.md](docs/FULLTEXT_REGISTRY_REFACTOR.md) 定義：

- `get_fulltext` tool 只保留 normalization / progress / formatting
- orchestration 移入 FulltextService
- source capability 與 retrieval policy 進入 registry / policy layer

### Tool vs Service Anti-Patterns

- tool function 直接長出多來源 orchestration tree
- tool function 同時做 schema parse、semantic fix、policy choose、network fallback、response formatting
- 為了保留 surface 相容性，把所有新邏輯都堆進 wrapper tool

## Placement Rules

| Concern | Preferred location | Should not live in |
| --- | --- | --- |
| structural parsing | `application/*/schema.py` or equivalent parser module | MCP tool, runtime hook executor |
| semantic correction | `application/*/validator.py`, planner, domain-aware validator | raw schema module |
| policy tables / metadata | registry file, policy module, JSON policy file | side-effect executor |
| orchestration | application service | public tool facade |
| I/O side effects | infrastructure executor, scheduler, store, hook runtime | policy file |
| response formatting | presentation tool / formatter | application service |

## Standard Refactor Template

當某個子系統開始變複雜時，預設拆法應該是責任拆法，而不是檔案大小拆法：

1. 定義 request schema 或 structural parser
2. 定義 semantic validator / planner
3. 定義 policy objects 或 policy registry
4. 把 orchestration 收到 application service
5. 讓 tool surface 只做 facade、progress、formatting
6. 保留 legacy wrappers，但不要把新邏輯塞回 wrapper

## Adoption Targets

### Fulltext

- structural: identifier normalization
- semantic: retrieval intent correction
- policy: source eligibility / structured-first / expanded discovery
- runtime: fetch, extract, persist, report provenance
- tool: `get_fulltext` formatting only

### Query Planning

- structural: request schema and normalized filters
- semantic: intent refinement, contradiction repair, plan shaping
- policy: dispatch profiles, expansion strategy, source participation
- runtime: actual search execution and session writes
- tool: stable MCP entrypoint and output contract

### Timeline

- structural: topic / PMID / option parsing
- semantic: milestone selection semantics, compare mode validation
- policy: milestone tables, landmark weights, threshold rules
- runtime: event building, citation fetching, rendering
- tool: response formatting and optional export surface

## PR Review Checklist

在 review 任何新功能或重構時，至少要問這幾個問題：

1. structural correctness 和 semantic correctness 是否已分成不同責任？
2. policy decision 是否可以在不碰 network / filesystem 的情況下單獨測試？
3. runtime executor 是否只是消費 policy 結果，而不是重算 policy？
4. MCP tool 是否只保留 surface 責任，而沒有成為 orchestration center？
5. application service 是否可以在不經過 MCP tool 的情況下被直接呼叫？
6. backward compatibility 是否留在 tool facade，而不是污染 service 核心？

如果以上任何一點回答是「否」，那通常代表這次變更還沒有真正完成架構分離。

## Related Documents

- [ARCHITECTURE.md](../ARCHITECTURE.md): 目前系統分層與入口總覽
- [docs/TOOL_CONSOLIDATION_DESIGN.md](TOOL_CONSOLIDATION_DESIGN.md): facade / wrapper 的 surface 設計原則
- [docs/FULLTEXT_REGISTRY_REFACTOR.md](FULLTEXT_REGISTRY_REFACTOR.md): fulltext service / registry / policy 分離目標
- [docs/COPILOT_HOOKS_PIPELINE_ENFORCEMENT.md](COPILOT_HOOKS_PIPELINE_ENFORCEMENT.md): hook runtime policy 與執行層的案例
