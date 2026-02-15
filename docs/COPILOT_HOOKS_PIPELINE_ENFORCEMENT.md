# Copilot Hooks × Pipeline Enforcement — 設計文件

> **文件性質**: 技術設計文件
> **目的**: 利用 GitHub Copilot Hooks 在 Agent 層創建搜尋反饋迴路，強制正確使用 Pipeline Mode
> **最後更新**: 2026-02-16
> **維護者**: Eric
> **狀態**: PoC 實作完成

---

## 目錄

1. [核心洞見](#1-核心洞見)
2. [架構設計](#2-架構設計)
3. [反饋迴路機制](#3-反饋迴路機制)
4. [Hook 清單與行為](#4-hook-清單與行為)
5. [Pipeline 強制執行邏輯](#5-pipeline-強制執行邏輯)
6. [結果品質評估邏輯](#6-結果品質評估邏輯)
7. [檔案結構](#7-檔案結構)
8. [編碼與健壯性](#8-編碼與健壯性)
9. [使用方式](#9-使用方式)
10. [限制與未來方向](#10-限制與未來方向)

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
| `preToolUse` | **enforce-pipeline.sh/ps1** | ✅ **DENY + reason** | **核心：Pipeline 強制 + 反饋迴路** |
| `postToolUse` | evaluate-results.sh/ps1 | ❌ (output ignored) → 寫 state file | 評估搜尋品質，間接影響下次 preToolUse |
| `sessionEnd` | session-cleanup.sh/ps1 | ❌ (output ignored) | 清理臨時狀態檔 |

---

## 5. Pipeline 強制執行邏輯

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
    ├── last_search_eval.json       # 搜尋品質評估 (postToolUse → next preToolUse)
    └── search_audit.jsonl          # 完整操作日誌

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

## 10. 限制與未來方向

### 目前限制

| 限制 | 原因 | 緩解方案 |
|------|------|---------|
| **preToolUse 只能 deny，不能修改參數** | Copilot Hooks API 限制 | 用 deny reason 引導 Agent 自行修改 |
| **postToolUse output 被忽略** | Copilot Hooks API 限制 | 透過 state file → preToolUse deny 間接影響 |
| **userPromptSubmitted 不能修改 prompt** | Copilot Hooks API 限制 | 只做 logging/analytics |
| **MCP toolName 可能帶前綴** | MCP 工具名稱格式不確定 | 用 regex 匹配 `unified_search` 後綴 |
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
