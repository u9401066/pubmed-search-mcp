# Copilot Hooks × Pipeline Enforcement — 設計文件

> **文件性質**: 技術設計文件
> **目的**: 利用 GitHub Copilot Hooks 在 Agent 層創建搜尋反饋迴路，強制正確使用 Pipeline Mode
> **最後更新**: 2026-04-06
> **維護者**: Eric
> **狀態**: PoC 實作完成 + Workflow Tracker
> **Scope Boundary**: 這套 Hook 約束只在 GitHub Copilot 載入 [.github/hooks/pipeline-enforcer.json](.github/hooks/pipeline-enforcer.json) 的執行路徑生效。它不是 MCP server 對所有 client 的通用約束；其他 MCP host 仍只會看到 server 端本身的工具行為。

---

## 目錄

1. [核心洞見](#1-核心洞見)
2. [架構設計](#2-架構設計)
3. [反饋迴路機制](#3-反饋迴路機制)
4. [Hook 清單與行為](#4-hook-清單與行為)
5. [Tool-Aware preToolUse 強制邏輯](#5-tool-aware-pretooluse-強制邏輯)
6. [結果品質評估邏輯](#6-結果品質評估邏輯)
7. [檔案結構](#7-檔案結構)
8. [編碼與健壯性](#8-編碼與健壯性)
9. [使用方式](#9-使用方式)
10. [Research Workflow Tracker](#10-research-workflow-tracker)
11. [限制與未來方向](#11-限制與未來方向)

---

## 1. 核心洞見

### 問題回顧

在 [Deep Research 架構分析報告](DEEP_RESEARCH_ARCHITECTURE_ANALYSIS.md) 中，我們發現：

> **我們有最好的搜尋基建（12+ sources, MeSH, 6D ranking），但缺少智能搜尋迴路。**

所有競品（GPT Researcher, STORM, Jina, LangChain ODR）都有「搜完 → 評估 → 調整 → 再搜」的反饋循環，而我們是一次性直線執行。

### Copilot Hooks 的關鍵特性

GitHub Copilot Hooks 在 **Agent 執行層** 攔截工具呼叫：

```
User → Copilot Agent → [preToolUse HOOK] → MCP Tool → Our Server
                             ↑
                        可以 DENY！
                        Agent 看到 reason
                        然後調整行為
```

**`preToolUse` 是唯一能影響 Agent 行為的 Hook** — 它可以：
- 返回 `permissionDecision: "deny"` 拒絕工具呼叫
- 附帶 `permissionDecisionReason` 告訴 Agent 為什麼+怎麼改
- Agent 看到拒絕原因後，會自動調整並重試

### 解決方案：三級並行策略 (Three-Tier Parallel Strategy)

**核心設計原則：簡易搜尋與 Pipeline 搜尋並行共存。**

```
┌──────────────────────────────────────────────────────────────────┐
│  Tier 1 (score 0-2): 簡單查詢 → 直通快速搜尋                     │
│  "CRISPR", "remimazolam" → unified_search → 即時結果             │
│  零干預，不寫任何狀態                                             │
├──────────────────────────────────────────────────────────────────┤
│  Tier 2 (score 3-4): 中等複雜度 → 並行雙軌                       │
│  "remimazolam sedation efficacy" → unified_search → 快速結果     │
│  preToolUse: ALLOW (放行) + 寫 pending_complexity 標記            │
│  postToolUse: 評估結果 → quality = suggest_supplement             │
│  Agent 下次操作 → preToolUse 建議: "也跑 pipeline 搜尋"          │
│  Agent 可選擇: 只用快速結果 OR 追加 pipeline 搜尋                  │
├──────────────────────────────────────────────────────────────────┤
│  Tier 3 (score 5+): 明確結構化搜尋 → 強制 Pipeline               │
│  "remimazolam vs propofol ICU sedation" → preToolUse DENY        │
│  Agent 自動重試: unified_search(pipeline="template: pico")       │
│  (明確的 PICO 比較 / 系統性回顧，直接走 pipeline)                  │
└──────────────────────────────────────────────────────────────────┘
```

**並行雙軌 = 快速結果先到手 + Pipeline 完整搜尋可選加掛。不是非此即彼。**

---

## 2. 架構設計

### 層級關係

```
┌─────────────────────────────────────────────────────────────┐
│  User Layer                                                 │
│  用戶提交研究問題                                            │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Copilot Agent Layer                                        │
│  Agent 規劃搜尋策略、呼叫工具                                │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  🔴 Copilot Hooks Layer (NEW!)                        │  │
│  │                                                       │  │
│  │  sessionStart  → 初始化狀態                            │  │
│  │  promptSubmit  → 分析意圖 (logging)                    │  │
│  │  preToolUse    → 強制 Pipeline / 反饋迴路 (DENY/ALLOW) │  │
│  │  postToolUse   → 評估結果品質 → 寫狀態                 │  │
│  │  sessionEnd    → 清理                                  │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  MCP Tool Layer                                             │
│  40 MCP 工具 (unified_search, find_related, etc.)           │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Pipeline Engine (DAG Executor)                     │    │
│  │  QueryAnalyzer → SemanticEnhancer → DispatchStrategy│    │
│  │  → PipelineExecutor → ResultAggregator              │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Data Source Layer                                          │
│  PubMed, OpenAlex, Semantic Scholar, Europe PMC, CORE, ... │
│  480,000,000+ records                                      │
└─────────────────────────────────────────────────────────────┘
```

### 與競品的對比定位

```
                    智能搜尋迴路
                         ▲
                 強      │
                         │       LangChain ODR
                         │         ●
                    Jina ●    GPT Researcher
                         │       ●
                    STORM●
                         │
                  dzhng ●│
                         │                  ● 我們 + Copilot Hooks
                         │                    (Agent-level feedback loop)
                 弱      │
                         │    ● 我們 (原始)
                         │
                         └──────────────────────────────────→
                      弱              搜尋基建               強
```

**Copilot Hooks 讓我們不需要重寫搜尋引擎，就能獲得反饋迴路能力。**

---

## 3. 反饋迴路機制

### Loop 1: Pipeline 強制 (preToolUse Deny)

```
┌─────────────────────────────────────────────────────────┐
│  Agent: "我要搜尋 remimazolam vs propofol ICU sedation"  │
│                                                         │
│  Agent 呼叫:                                            │
│    unified_search(query="remimazolam vs propofol ...")   │
│    (沒有 pipeline 參數)                                  │
│                                                         │
│  enforce-pipeline.sh 攔截:                               │
│    1. toolName 匹配 unified_search ✓                    │
│    2. 解析 query: 包含 "vs" ✓                           │
│    3. 複雜度分數 = 3+ ✓                                  │
│    4. pipeline 參數 = null ✓ (缺少)                      │
│    5. 推薦模板 = "pico" (因為有 "vs")                    │
│    6. → DENY                                            │
│                                                         │
│  Agent 看到:                                             │
│    "Complex query detected without pipeline mode.       │
│     Please retry with:                                  │
│     pipeline='template: pico\ntopic: remimazolam...'"   │
│                                                         │
│  Agent 自動重試:                                         │
│    unified_search(                                      │
│      query="remimazolam vs propofol ICU sedation",      │
│      pipeline="template: pico\ntopic: ..."              │
│    )                                                    │
│                                                         │
│  enforce-pipeline.sh 攔截:                               │
│    pipeline 參數存在 → ALLOW ✓                          │
│                                                         │
│  結果: Pipeline mode 執行，自動 PICO 分解 + 平行搜尋     │
└─────────────────────────────────────────────────────────┘
```

### Loop 2: 結果品質反饋 (postToolUse → State File → preToolUse)

```
┌─────────────────────────────────────────────────────────┐
│  Step 1: 搜尋完成 (postToolUse)                          │
│                                                         │
│  evaluate-results.sh 攔截:                               │
│    toolName: unified_search ✓                           │
│    結果分析:                                             │
│      - PMID 數量: 2 (< 3 → poor)                       │
│      - 來源數: 1 (只有 pubmed)                           │
│      - depth score: 25 (shallow)                        │
│                                                         │
│    寫入: .github/hooks/_state/last_search_eval.json     │
│    {                                                    │
│      "quality": "poor",                                 │
│      "result_count": 2,                                 │
│      "suggestion": "Only 2 articles found. Try...",     │
│      "nudged": false                                    │
│    }                                                    │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  Step 2: Agent 準備做其他事 (preToolUse)                  │
│                                                         │
│  Agent 呼叫: edit("report.md", ...)                     │
│                                                         │
│  enforce-pipeline.sh 攔截:                               │
│    1. toolName = "edit" (非搜尋工具)                     │
│    2. 檢查狀態檔 → quality = "poor" ✓                   │
│    3. nudged = false → 第一次提醒                        │
│    4. → DENY + 建議                                     │
│                                                         │
│  Agent 看到:                                             │
│    "⚠️ Previous search returned only 2 results.         │
│     Consider:                                           │
│     1. Retry with pipeline mode                         │
│     2. find_related_articles(pmid=...)                   │
│     3. Try broader query"                               │
│                                                         │
│  Agent 決定: 追加搜尋                                    │
│    find_related_articles(pmid="12345678")                │
│                                                         │
│  enforce-pipeline.sh 攔截:                               │
│    toolName 匹配 "related" → 清除狀態 → ALLOW           │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  Step 3: 追加結果合併                                    │
│                                                         │
│  Agent 現在有更完整的文獻 → 繼續報告                      │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 反饋迴路的安全閥

為避免無限 deny loop，設計了多道安全閥：

| 安全閥 | 機制 | 目的 |
|--------|------|------|
| **nudged flag** | 每個品質問題只提示一次 | 避免 Agent 陷入死循環 |
| **搜尋工具放行** | 如果 Agent 正在做搜尋相關操作 → ALLOW | 讓 Agent 的追加搜尋正常進行 |
| **pipeline 已指定** | 有 pipeline 參數 → 立即 ALLOW | 避免 pipeline 模式被自己阻擋 |
| **簡單查詢跳過** | 複雜度 < 3 → ALLOW | 不對簡單搜尋過度干預 |
| **State file 清理** | sessionStart 清除舊狀態 | 跨 session 不殘留 |

---

## 4. Hook 清單與行為

| Hook Event | 腳本 | 能影響 Agent? | 目的 |
|------------|------|-------------|------|
| `sessionStart` | session-init.sh/ps1 | ❌ (output ignored) | 初始化狀態目錄，清除舊狀態 |
| `userPromptSubmitted` | analyze-prompt.sh/ps1 | ❌ (output ignored) | 記錄用戶意圖分類 (audit) |
| `preToolUse` | **enforce-pipeline.sh/ps1** | ✅ **DENY + reason** | **核心：unified_search 複雜度強制 + 其他 research tools 的 evidence/workflow guard** |
| `postToolUse` | evaluate-results.sh/ps1 | ❌ (output ignored) → 寫 state file | 評估 result-bearing research tools 的品質，間接影響下次 preToolUse |
| `sessionEnd` | session-cleanup.sh/ps1 | ❌ (output ignored) | 清理臨時狀態檔 |

---

## 5. Tool-Aware preToolUse 強制邏輯

### 現況摘要

- `unified_search` 仍保留三層複雜度閾值與 pipeline 強制。
- 其他 result-bearing MCP tools 不再是「未命中 unified_search 就直接放行」，而是依據共享政策檔做明確分組。
- 下游工具如 `get_fulltext`、`find_related_articles`、`prepare_export`、`save_literature_notes`、`read_session`、`get_pipeline_history` 會檢查是否已有 evidence context，或是否提供明確 identifier/PMID/DOI/name 等參數。
- 這些規則是 **Copilot runtime hook**，不是 server-wide policy。

### 三級複雜度閾值 (Three-Tier Thresholds)

```
┌─────────┬──────────┬────────────┬──────────────────────────┐
│ Tier    │ Score    │ preToolUse │ 行為                     │
├─────────┼──────────┼────────────┼──────────────────────────┤
│ T1 簡單 │ 0 - 2    │ ALLOW      │ 直通快速搜尋，零干預      │
│ T2 中等 │ 3 - 4    │ ALLOW      │ 快速結果 + 建議 pipeline  │
│ T3 結構 │ 5+       │ DENY       │ 強制 pipeline 模式        │
└─────────┴──────────┴────────────┴──────────────────────────┘
```

### 複雜度評分 (Query Complexity Score)

```
評分項目:
┌─────────────────────────────────────┬────────┐
│ 模式                                │ 分數   │
├─────────────────────────────────────┼────────┤
│ Comparison: vs, versus, compared to │ +3     │
│ PICO elements: patient, outcome...  │ +2     │
│ Clinical: efficacy, safety, adverse │ +1     │
│ Systematic: comprehensive, review   │ +2     │
│ Word count > 6                      │ +1     │
│ Boolean: AND, OR, NOT               │ +1     │
│ MeSH notation: [MeSH], [tiab]       │ +1     │
└─────────────────────────────────────┴────────┘
Note: Chinese regex patterns removed from scoring to avoid
encoding issues. Chinese queries with English medical terms
still score correctly via the English patterns above.

範例:
  "CRISPR gene therapy"              → score=1 → Tier 1 (直通)
  "remimazolam sedation efficacy"    → score=3 → Tier 2 (放行+建議)
  "remimazolam vs propofol ICU safety" → score=6 → Tier 3 (強制)
```

### 模板推薦邏輯

```
Query contains "vs/compare/比較" → template: pico
Query contains "systematic/review/文獻回顧" → template: comprehensive
Query contains "gene/BRCA/drug/藥物" → template: gene_drug
Default for other complex queries → template: comprehensive
```

---

## 6. 結果品質評估邏輯

### 評估範圍

postToolUse 不再只評估 `unified_search`。目前會對所有 **result-bearing research tools** 寫入通用 `last_research_eval.json` 狀態，例如：

- Search / retrieval: `unified_search`, `search_gene`, `search_compound`, `search_clinvar`, `search_biomedical_images`
- Discovery / expansion: `fetch_article_details`, `find_related_articles`, `find_citing_articles`, `get_article_references`, `build_citation_tree`
- Fulltext / figures: `get_fulltext`, `get_text_mined_terms`, `get_article_figures`
- Session / evaluation / synthesis: `read_session`, `get_session_pmids`, `get_cached_article`, `get_session_summary`, `get_citation_metrics`, `prepare_export`, `save_literature_notes`, timeline tools

不同工具家族使用不同啟發式：article-count、source diversity、fulltext availability、session/detail presence。

### 品質等級

| 品質 | 條件 | 觸發反饋? |
|------|------|----------|
| **good** | 結果 ≥ 8 && 來源 ≥ 2 && 非 Tier 2 | ❌ |
| **suggest_supplement** | Tier 2 查詢 + 結果尚可 | 💡 溫和建議追加 pipeline |
| **acceptable** | 結果 3-7 或 來源 = 1 | ⚠️ 輕微 (首次提醒) |
| **insufficient** | depth score < 30 | ✅ 建議擴展 |
| **poor** | 結果 < 3 或 搜尋失敗 | ✅ 強制建議 pipeline |

### 評估指標

```
1. Result Count    → 從結果文字中計算 PMID 數量
2. Source Diversity → 偵測有幾個不同來源的結果
3. Depth Score     → 從結果文字中提取 depth score (if available)
4. Had Pipeline?   → 是否已經使用 pipeline (影響建議方向)
```

---

## 7. 檔案結構

```
.github/hooks/
├── pipeline-enforcer.json          # Hook 設定檔 (Copilot 讀取)
└── _state/                         # 執行時狀態 (gitignored)
    ├── pending_complexity.json     # Tier 2 待評估標記 (preToolUse → postToolUse)
    ├── last_research_eval.json     # 通用 research tool 品質評估 (postToolUse → next preToolUse)
    └── search_audit.jsonl          # 完整操作日誌

    # backward compatibility
    └── last_search_eval.json       # 舊版 unified_search-only state (讀取時仍相容)

scripts/hooks/copilot/
├── enforce-pipeline.sh             # preToolUse: Pipeline 強制 (bash)
├── enforce-pipeline.ps1            # preToolUse: Pipeline 強制 (PowerShell)
├── evaluate-results.sh             # postToolUse: 結果品質評估 (bash)
├── evaluate-results.ps1            # postToolUse: 結果品質評估 (PowerShell)
├── analyze-prompt.sh               # userPromptSubmitted: 意圖分析 (bash)
├── analyze-prompt.ps1              # userPromptSubmitted: 意圖分析 (PowerShell)
├── session-init.sh                 # sessionStart: 初始化 (bash)
├── session-init.ps1                # sessionStart: 初始化 (PowerShell)
├── session-cleanup.sh              # sessionEnd: 清理 (bash)
└── session-cleanup.ps1             # sessionEnd: 清理 (PowerShell)
```

---

## 8. 編碼與健壯性

### 跨平台編碼問題

Copilot Hooks 可在不同環境執行：
- **GitHub Coding Agent**: Linux 容器 (UTF-8 預設)
- **Copilot CLI / VS Code**: Windows (預設 Big5/CP950 或 GBK)
- **macOS / Linux 本機**: UTF-8 預設

**核心風險**: 如果 Hook 輸出的 JSON 包含非 ASCII 字元 (emoji、中文)，在 Windows 非 UTF-8 環境下會產生亂碼 (mojibake)，導致 JSON 解析失敗，Hook 整體失效。

### 設計原則

| 原則 | 說明 |
|------|------|
| **ASCII-only stdout** | `permissionDecisionReason` 及所有 JSON 輸出只用 ASCII 字元 |
| **No emoji in output** | 🔬→`[PIPELINE]`、💡→`[TIP]`、⚠️→`[WARNING]`、•→`-` |
| **中文可用於內部邏輯** | grep/regex 匹配模式可用中文 (不影響輸出) |
| **UTF-8 宣告** | Bash: script 層級 (grep 模式依賴 locale)；PowerShell: `[Console]::OutputEncoding = UTF8` |
| **Fail-open** | 任何錯誤都 `exit 0` (ALLOW)，絕不因 Hook 錯誤阻擋 Agent |

### Bash 腳本規範

```bash
#!/bin/bash
set -e

# 前置檢查: jq 必須存在，否則跳過
if ! command -v jq >/dev/null 2>&1; then
    exit 0  # Graceful skip
fi

# 所有 jq 呼叫加 2>/dev/null 和 || fallback
TOOL_NAME=$(echo "$INPUT" | jq -r '.toolName // empty' 2>/dev/null) || exit 0

# REASON 字串只用 ASCII
REASON="[PIPELINE REQUIRED] Highly structured query detected."
```

### PowerShell 腳本規範

```powershell
$ErrorActionPreference = "Stop"

# 強制 UTF-8 輸出 (必須在任何輸出前設定)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# 安全讀取 JSON
$rawInput = [Console]::In.ReadToEnd()
if (-not $rawInput -or $rawInput.Trim().Length -eq 0) { exit 0 }
$inputJson = $rawInput | ConvertFrom-Json -ErrorAction Stop

# Fail-open: 任何錯誤都 ALLOW
catch { exit 0 }
```

### 健壯性措施

| 措施 | 適用腳本 | 說明 |
|------|---------|------|
| `jq` 可用性檢查 | 所有 bash | 無 jq 則 `exit 0` |
| 空輸入保護 | 所有 PS1 | `$rawInput.Trim().Length -eq 0 → exit 0` |
| State file 損壞容錯 | enforce/evaluate | JSON parse 失敗時刪除並繼續 |
| `pending_complexity.json` 清理 | session-init/cleanup | 防止跨 session 泄漏 |
| 單次提醒 (nudged flag) | enforce-pipeline | 避免無限 deny loop |
| Fail-open 錯誤處理 | 所有 PS1 | `catch { exit 0 }` 取代 `Write-Error; exit 1` |
| `-Encoding UTF8` | 所有 PS1 state writes | `Set-Content` / `Add-Content` 加 `-Encoding UTF8` |

---

## 9. 使用方式

### 啟用條件

Copilot Hooks 讀取 `.github/hooks/*.json`，需滿足：

1. **JSON 檔案在 default branch 上** — 合併到 main/master 後自動生效
2. **Bash 腳本需要 executable 權限** — `git add --chmod=+x scripts/hooks/copilot/*.sh`
3. **需要 `jq` 命令** — GitHub Coding Agent 容器已預裝

### 本地測試

```bash
# Tier 1: 簡單查詢 → ALLOW (無輸出)
echo '{"timestamp":1704614600000,"cwd":"/tmp","toolName":"unified_search","toolArgs":"{\"query\":\"CRISPR\"}"}'  | bash scripts/hooks/copilot/enforce-pipeline.sh
# 預期輸出: (空, 即 allow)

# Tier 2: 中等複雜度 → ALLOW + 寫 pending_complexity
echo '{"timestamp":1704614600000,"cwd":"/tmp","toolName":"unified_search","toolArgs":"{\"query\":\"remimazolam sedation efficacy safety\"}"}'  | bash scripts/hooks/copilot/enforce-pipeline.sh
# 預期輸出: (空, 即 allow。但 .github/hooks/_state/pending_complexity.json 被寫入)

# Tier 3: 高複雜度 → DENY (強制 pipeline)
echo '{"timestamp":1704614600000,"cwd":"/tmp","toolName":"unified_search","toolArgs":"{\"query\":\"remimazolam vs propofol ICU sedation efficacy\"}"}'  | bash scripts/hooks/copilot/enforce-pipeline.sh
# 預期輸出: {"permissionDecision":"deny","permissionDecisionReason":"...pipeline..."}

# Pipeline 已指定 → ALLOW (任何 tier)
echo '{"timestamp":1704614600000,"cwd":"/tmp","toolName":"unified_search","toolArgs":"{\"query\":\"test\",\"pipeline\":\"template: pico\"}"}' | bash scripts/hooks/copilot/enforce-pipeline.sh
# 預期輸出: (空, 即 allow)
```

```powershell
# PowerShell 測試
'{"timestamp":1704614600000,"cwd":"/tmp","toolName":"unified_search","toolArgs":"{\"query\":\"remimazolam vs propofol ICU\"}"}' | pwsh -File scripts/hooks/copilot/enforce-pipeline.ps1
```

### 與 GitHub Coding Agent / Copilot CLI 搭配

```
# Coding Agent (GitHub Issues/PRs)
# 自動：合併到 default branch 後生效

# Copilot CLI (本地)
# 自動：從 .github/hooks/ 讀取
```

---

## 10. Research Workflow Tracker

### 概述

利用 Copilot Hooks 的 `instructions` 注入能力，在每次使用者提交 prompt 時注入 TODO 風格的研究工作流程進度，引導 AI Agent 按照結構化步驟進行文獻搜尋。

### 核心機制

```
userPromptSubmitted hook
  ├─ 偵測研究意圖 (analyze-prompt)
  │   └─ 建立 workflow_tracker.json (7 步驟)
  ├─ 生成 instructions JSON
  │   └─ [x] 已完成 / [ ] 未完成 / <-- NEXT 提示
  └─ 注入到 AI context

postToolUse hook (evaluate-results)
  ├─ 偵測 toolName → 對應步驟
  └─ 更新 workflow_tracker.json 中的步驟狀態
```

### 7 步結構化研究流程

| Step | 名稱 | 觸發工具 | 說明 |
|------|------|---------|------|
| 1 | Query Analysis | `analyze_search_query`, `parse_pico` | 分析查詢複雜度，拆解 PICO |
| 2 | Strategy Formation | `generate_search_queries` | 取得 MeSH 詞彙、同義詞 |
| 3 | Initial Search | `unified_search` (無 pipeline) | 初始搜尋，評估結果 |
| 4 | Pipeline Search | `unified_search` (有 pipeline) | 使用 pipeline template 進行精確搜尋 |
| 5 | Result Evaluation | `get_citation_metrics`, `get_session_summary` | 評估結果品質 (RCR, 引用數) |
| 6 | Deep Exploration | `find_related_articles`, `find_citing_articles`, `get_fulltext`, `build_citation_tree` | 深入探索重要文獻 |
| 7 | Export & Synthesis | `prepare_export`, `save_literature_notes`, `build_research_timeline` | 匯出引用、本機 wiki note、建構時間軸 |

### State File Schema

```json
// .github/hooks/_state/workflow_tracker.json
{
  "topic": "remimazolam vs propofol ICU sedation",
  "intent": "comparison",
  "template": "pico",
  "created_at": "2026-02-17T10:30:00Z",
  "steps": {
    "query_analysis": "completed",
    "strategy_formation": "completed",
    "initial_search": "not-started",
    "pipeline_search": "not-started",
    "result_evaluation": "not-started",
    "deep_exploration": "not-started",
    "export_synthesis": "not-started"
  }
}
```

### Instructions 注入範例

`userPromptSubmitted` hook 回傳的 JSON：

```json
{
  "instructions": "RESEARCH WORKFLOW (2/7 steps done)\n[x] 1. Query Analysis\n[x] 2. Strategy Formation\n[ ] 3. Initial Search  <-- NEXT: Use unified_search\n[ ] 4. Pipeline Search\n[ ] 5. Result Evaluation\n[ ] 6. Deep Exploration\n[ ] 7. Export & Synthesis\nTopic: remimazolam vs propofol ICU sedation\nTemplate: pico"
}
```

AI Agent 會在 context 中看到這段 instructions，自動理解當前進度並跟隨 NEXT 提示。

### 意圖偵測與 Template 映射

| 偵測關鍵字 | 意圖 | 建議 Template |
|-----------|------|-------------|
| `vs`, `compared`, `comparison` | comparison | pico |
| `systematic`, `comprehensive`, `review` | systematic | comprehensive |
| `explore`, `related`, `citing` | exploration | exploration |
| `gene`, `drug`, `compound`, `BRCA` | gene_drug | gene_drug |
| 其他 | general | (無預設) |

### Session 生命週期

```
sessionStart hook
  └─ 清除 workflow_tracker.json (重置工作流程)

userPromptSubmitted hook
  └─ 偵測研究意圖 → 建立新 tracker (僅一次，已存在則跳過)

postToolUse hook
  └─ 每次工具呼叫後更新對應步驟狀態

下次 userPromptSubmitted
  └─ 讀取 tracker → 生成更新後的 instructions
```

### 與 Pipeline Enforcement 的互補

```
Pipeline Enforcement (preToolUse)
  → 強制: 複雜查詢必須用 pipeline
  → 目的: 確保搜尋品質

Workflow Tracker (userPromptSubmitted + postToolUse)
  → 引導: 顯示研究進度，建議下一步
  → 目的: 結構化研究流程
```

兩者獨立運作，互不干擾。Pipeline enforcement 確保搜尋品質，workflow tracker 確保研究流程完整性。

---

## 11. 限制與未來方向

### 目前限制

| 限制 | 原因 | 緩解方案 |
|------|------|---------|
| **preToolUse 只能 deny，不能修改參數** | Copilot Hooks API 限制 | 用 deny reason 引導 Agent 自行修改 |
| **postToolUse output 被忽略** | Copilot Hooks API 限制 | 透過 state file → preToolUse deny 間接影響 |
| **userPromptSubmitted 可注入 instructions** | Copilot Hooks API 支援 | 用 `{"instructions": "..."}` 注入工作流程進度到 AI context |
| **這是 Copilot-only runtime layer** | Hook 是 Copilot host 能力，不是 MCP server API | 在文件中明確標示 scope boundary；server 行為仍以工具實作為準 |
| **MCP tool coverage 可能漂移** | 新工具加入後，hook 常常忘記同步 | 改為讀取共享 tool policy，並以測試驗證 policy 覆蓋所有已註冊工具 |
| **品質評估只能解析文字** | 不能直接存取結構化結果 | 用 PMID 計數、source 檢測等啟發式方法 |

### 未來方向

#### Phase 2: 更智能的反饋

```yaml
# 如果 Copilot Hooks 未來支援 preToolUse 修改參數：
preToolUse:
  - 偵測複雜查詢 → 自動注入 pipeline 參數 (不用 deny)
  - 偵測重複搜尋 → 自動添加 "排除已見 PMID" 條件

# 如果未來支援 postToolUse 注入 context：
postToolUse:
  - 搜尋完成後 → 直接告訴 Agent "結果不足，建議..."
  - 不再需要 state file 間接機制
```

#### Phase 3: 跨 Session 學習

```yaml
# 分析 search_audit.jsonl 歷史：
# - 哪些 query 經常結果不佳 → 預設用 pipeline
# - 哪些 template 效果最好 → 動態推薦
# - 用戶常搜的領域 → 預載相關 MeSH 詞彙
```

#### Phase 4: 與 Pipeline evaluate/discover action 整合

結合 [改進路線圖](DEEP_RESEARCH_ARCHITECTURE_ANALYSIS.md#12-改進路線圖) 中的 `evaluate` 和 `discover` action：

```
Copilot Hook (Agent 層反饋)
  ↕ 互補
Pipeline evaluate action (搜尋引擎層反饋)

Hook 負責: 是否該用 pipeline？結果夠不夠好？
evaluate action 負責: 結果的 MeSH 覆蓋率夠嗎？RCT 比例夠嗎？
```

---

## 附錄：與競品反饋機制的對比

| 系統 | 反饋迴路在哪一層 | 機制 | 我們的 Copilot Hook |
|------|----------------|------|-------------------|
| **GPT Researcher** | Agent 代碼內 | Tree 遞迴 (depth/breadth) | preToolUse deny → Agent retry |
| **STORM** | Agent 代碼內 | 多輪對話 (max_conv_turn) | postToolUse → state → preToolUse deny |
| **Jina** | Agent 代碼內 | Token budget loop | State file quality check |
| **LangChain ODR** | LangGraph Agent 內 | ReAct loop | 最接近的模式：Agent 自主循環 |
| **我們 + Hooks** | **Agent 外部 (Hook 層)** | Deny + state file | 不改任何搜尋代碼 |

**核心差異：我們的反饋迴路是在搜尋引擎外部、Agent 通訊層實現的，而非嵌入搜尋代碼。**

這意味著：
- ✅ 不需修改任何 MCP 工具或搜尋代碼
- ✅ 可以和任何 Copilot-compatible Agent 搭配
- ✅ Hook 腳本可以獨立演化、測試
- ⚠️ 但反饋粒度受限於 Hook API 的能力

---

> **文件結束** — 本設計應隨 Copilot Hooks API 演進和 Pipeline system 擴展而更新。
