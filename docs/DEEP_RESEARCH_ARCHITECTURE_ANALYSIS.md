# Deep Research / Deep Search 開源工具 — 檢索架構深度分析報告

> **文件性質**: 技術分析報告 (內部文件)
> **目的**: 比較主流 Deep Research 開源 repo 的檢索架構，找出我們的改進方向
> **最後更新**: 2026-02-15
> **維護者**: Eric
> **分析對象**: 8 個系統（含本專案）

---

## 目錄

- [Deep Research / Deep Search 開源工具 — 檢索架構深度分析報告](#deep-research--deep-search-開源工具--檢索架構深度分析報告)
  - [目錄](#目錄)
  - [1. 背景與動機](#1-背景與動機)
    - [Deep Research 是什麼？](#deep-research-是什麼)
    - [為什麼要做這個分析？](#為什麼要做這個分析)
  - [2. 競品清單總覽](#2-競品清單總覽)
    - [關鍵觀察](#關鍵觀察)
  - [3. 各系統檢索架構拆解](#3-各系統檢索架構拆解)
    - [Pattern 1: Planner → Executor (GPT Researcher)](#pattern-1-planner--executor-gpt-researcher)
      - [Deep Research 模式（遞迴版本）](#deep-research-模式遞迴版本)
    - [Pattern 2: Perspective-guided Conversation (STORM)](#pattern-2-perspective-guided-conversation-storm)
      - [STORM LLM 分工配置](#storm-llm-分工配置)
    - [Pattern 3: Iterative Search-Read-Reason Loop (Jina DeepResearch)](#pattern-3-iterative-search-read-reason-loop-jina-deepresearch)
      - [Jina 的精妙設計：Token Budget as 停止條件](#jina-的精妙設計token-budget-as-停止條件)
    - [Pattern 4: LangGraph Agent Loop (LangChain Open Deep Research)](#pattern-4-langgraph-agent-loop-langchain-open-deep-research)
      - [架構演化史（值得深思的 Bitter Lesson）](#架構演化史值得深思的-bitter-lesson)
    - [Pattern 5: 極簡遞迴搜尋 (dzhng/deep-research)](#pattern-5-極簡遞迴搜尋-dzhngdeep-research)
    - [Pattern 6: 我們的 5-Layer Pipeline (PubMed Search MCP)](#pattern-6-我們的-5-layer-pipeline-pubmed-search-mcp)
  - [4. 核心差異對比：問題分解策略](#4-核心差異對比問題分解策略)
    - [差距的核心圖示](#差距的核心圖示)
  - [5. 搜尋深度實現方式比較](#5-搜尋深度實現方式比較)
    - [視覺對比](#視覺對比)
  - [6. 資料來源與可靠性比較](#6-資料來源與可靠性比較)
    - [來源詳細清單 (我們的)](#來源詳細清單-我們的)
  - [7. Pipeline / 工作流系統比較](#7-pipeline--工作流系統比較)
  - [8. 成本與依賴分析](#8-成本與依賴分析)
  - [9. 整合生態比較](#9-整合生態比較)
  - [10. 架構模式光譜圖](#10-架構模式光譜圖)
    - [規則驅動 vs LLM 驅動](#規則驅動-vs-llm-驅動)
    - [搜尋基建 vs 智能搜尋迴路](#搜尋基建-vs-智能搜尋迴路)
  - [11. SWOT 分析](#11-swot-分析)
    - [PubMed Search MCP](#pubmed-search-mcp)
  - [12. 改進路線圖](#12-改進路線圖)
    - [核心差距（一句話版）](#核心差距一句話版)
    - [Level 1: 結果反饋迴路（Result Feedback Loop）— 不需 LLM](#level-1-結果反饋迴路result-feedback-loop-不需-llm)
    - [Level 2: 動態查詢擴展（Dynamic Query Expansion）— 不需 LLM](#level-2-動態查詢擴展dynamic-query-expansion-不需-llm)
    - [Level 3: Optional LLM 推理層 — 需要 LLM (opt-in)](#level-3-optional-llm-推理層--需要-llm-opt-in)
    - [Level 4: Perspective-guided 多角度搜尋 — 需要 LLM (opt-in)](#level-4-perspective-guided-多角度搜尋--需要-llm-opt-in)
    - [改進優先級總結](#改進優先級總結)
  - [13. 與 LangChain ODR 的互補關係](#13-與-langchain-odr-的互補關係)
  - [14. 總結](#14-總結)
    - [本報告的核心發現](#本報告的核心發現)
      - [1. 五大檢索架構模式](#1-五大檢索架構模式)
      - [2. 所有系統的共同點](#2-所有系統的共同點)
      - [3. 我們的獨特定位](#3-我們的獨特定位)
  - [參考連結](#參考連結)

---

## 1. 背景與動機

### Deep Research 是什麼？

Deep Research 最早由 Google Gemini 推出（2025 年初），隨後 OpenAI 也跟進。核心概念是：

> **AI 自主地進行多步驟、多來源的深度研究，從問題出發，反覆搜尋、閱讀、推理，直到產出一份完整的研究報告。**

這與傳統的「輸入關鍵字 → 返回列表」模式有根本性區別。

### 為什麼要做這個分析？

我們的 Research Pipeline 目前的模式是：

```
Agent 自己規劃全部 → 寫成文件（Pipeline YAML）→ 開始找！
```

這意味著：
- **搜完就結束**，沒有「看結果不夠好再搜」的能力
- **問題分解靠固定規則**（PICO regex），不是動態推理
- **沒有遞迴深入機制**

本報告深入分析各主流 open source deep research repo 的檢索架構，找出我們可以借鑑的模式。

---

## 2. 競品清單總覽

| # | 系統 | ⭐ Stars | 語言 | 架構類型 | 檢索策略 |
|---|------|---------|------|---------|---------|
| 1 | **Stanford STORM** | 27.9k | Python | dspy Pipeline (4 Modules) | 模擬多觀點對話產生搜尋查詢 |
| 2 | **GPT Researcher** | 25.3k | Python | Planner/Executor Agent (LangGraph) | LLM 分解問題 → 平行搜尋 |
| 3 | **dzhng/deep-research** | 18.4k | TypeScript | 遞迴搜尋 (<500 LoC) | 遞迴展開子問題 |
| 4 | **Qwen-Agent** | 13.3k | Python | LLM Agent Framework | 通用框架 (RAG/工具呼叫) |
| 5 | **LangChain Open Deep Research** | 10.5k | Python | LangGraph Search Agent → Report | Agent loop 自主搜尋+壓縮+報告 |
| 6 | **nickscamara/Open Deep Research** | 6.2k | TypeScript | Firecrawl + Reasoning Model | 搜尋→擷取→推理分析 |
| 7 | **Jina DeepResearch** | 5.1k | TypeScript | 迭代 search-read-reason | Token budget 控制的迭代搜尋 |
| 8 | **HKUDS Auto-Deep-Research** | 1.4k | Python | AutoAgent Framework + Docker | 全自動 agent with browser |
| — | **我們 (PubMed Search MCP)** | — | Python | 5-Layer Pipeline + DAG | 語義分析→多策略→多源平行→融合排名 |

### 關鍵觀察

- **所有系統都需要 LLM**（GPT-4o/o3-mini/Claude/Qwen），除了我們
- **所有系統都有某種形式的迭代反饋**，除了我們
- **所有系統都只用 1-2 個 web search API**，我們用 12+

---

## 3. 各系統檢索架構拆解

### Pattern 1: Planner → Executor (GPT Researcher)

> **來源**: [github.com/assafelovic/gpt-researcher](https://github.com/assafelovic/gpt-researcher) (25.3k ⭐)
> **論文**: Inspired by [Plan-and-Solve](https://arxiv.org/abs/2305.04091) + [RAG](https://arxiv.org/abs/2005.11401)

```
User Query
    │
    ▼
┌─────────────────────────────────┐
│  Planner Agent (LLM)            │  ← 用 LLM 將問題分解為 5-10 個子問題
│  "Generate research questions"  │    (Plan-and-Solve paper inspired)
│                                 │
│  Input: User query              │
│  Output: [Q1, Q2, Q3, ...]     │
└──────────┬──────────────────────┘
           │ 產出 5-10 個子問題
           ▼
┌─────────────────────────────────┐
│  Execution Agents (平行)         │  ← 每個子問題各派一個 agent
│                                 │
│  ┌─────────┐  ┌─────────┐      │
│  │ Agent 1 │  │ Agent 2 │ ...  │     每個 Agent:
│  │ Q1      │  │ Q2      │      │     1. Web Search (Tavily/Bing)
│  │ →搜尋   │  │ →搜尋   │      │     2. 抓取網頁內容
│  │ →抓取   │  │ →抓取   │      │     3. LLM 讀取 + 摘要
│  │ →摘要   │  │ →摘要   │      │     4. Source tracking
│  └─────────┘  └─────────┘      │
└──────────┬──────────────────────┘
           │ 收集所有摘要
           ▼
┌─────────────────────────────────┐
│  Publisher Agent (LLM)           │  ← 彙整所有摘要為最終報告
│  Aggregate → Filter → Report    │     產出 5-6 頁 Markdown
└─────────────────────────────────┘
```

#### Deep Research 模式（遞迴版本）

```
                         User Query
                              │
                  ┌───────────┼───────────┐
                  ▼           ▼           ▼
             子問題 A     子問題 B     子問題 C      ← breadth = 3
                  │           │           │
              搜尋+讀取    搜尋+讀取    搜尋+讀取
                  │           │           │
          ┌───────┤     ┌─────┤     ┌─────┤
          ▼       ▼     ▼     ▼     ▼     ▼          ← depth = 2
        子A1    子A2   子B1  子B2  子C1  子C2
          │       │     │     │     │     │
      搜尋+讀取  ...   ...   ...   ...   ...
          │
     ┌────┤
     ▼    ▼                                           ← depth = 3
   子A1a 子A1b
     │    │
    ...  ...

              最終：所有葉節點結果 → 匯整 → 報告
```

**特點**：
- ✅ 自動問題分解 (LLM-driven)
- ✅ Tree-like 遞迴探索
- ✅ 可控 depth (1-5) 和 breadth (3-10)
- ✅ ~5 分鐘/次，~$0.4/次 (o3-mini)
- ✅ 190 contributors，活躍維護
- ✅ MCP Client 支援
- ❌ 問題分解完全依賴 LLM，不用任何領域知識
- ❌ 搜尋只走 1 個 API (Tavily)，沒有多源融合
- ❌ 沒有去重/排名邏輯，靠 LLM 判斷品質
- ❌ 每次結果不同 (LLM non-deterministic)

---

### Pattern 2: Perspective-guided Conversation (STORM)

> **來源**: [github.com/stanford-oval/storm](https://github.com/stanford-oval/storm) (27.9k ⭐)
> **論文**: NAACL'24
> **進化**: Co-STORM 加入人類協作

```
User Topic: "Remimazolam"
    │
    ▼
┌──────────────────────────────────────────┐
│  Persona Generator (LLM)                 │
│  "為這個主題產出 3-5 個專家觀點"           │
│                                          │
│  Output:                                 │
│    👨‍⚕️ Anesthesiologist                    │
│    👩‍🔬 Pharmacologist                      │
│    👨‍💼 ICU Intensivist                     │
│    👩‍⚕️ Patient Safety Officer              │
└──────────┬───────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────┐
│  Simulated Multi-Perspective Conversations│
│                                          │
│  ┌────────────────────────────────────┐  │
│  │  Perspective 1: Anesthesiologist   │  │
│  │                                    │  │
│  │  Turn 1:                           │  │
│  │    Expert asks: "What is the       │  │
│  │    mechanism of action?"           │  │
│  │    → Generate 3 search queries     │  │
│  │    → Web Search (top-3 results)    │  │
│  │    → LLM reads & answers           │  │
│  │                                    │  │
│  │  Turn 2:                           │  │
│  │    Expert asks: "How does it       │  │
│  │    compare to midazolam?"          │  │
│  │    → 3 more search queries         │  │
│  │    → Search → Read → Answer        │  │
│  │                                    │  │
│  │  Turn 3: (max_conv_turn = 3)       │  │
│  │    Expert asks: "Any adverse       │  │
│  │    effects reported?"              │  │
│  │    → Search → Read → Answer        │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │  Perspective 2: Pharmacologist     │  │
│  │  (Same 3-turn conversation)        │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │  Perspective 3: ICU Intensivist    │  │
│  │  (Same 3-turn conversation)        │  │
│  └────────────────────────────────────┘  │
│                                          │
│  Total: 3 perspectives × 3 turns ×       │
│         3 queries = ~27 searches         │
└──────────┬───────────────────────────────┘
           │ 累積 InformationTable
           ▼
┌──────────────────────────────────────────┐
│  Outline Generation (LLM)                │
│  從 InformationTable 產出文章結構         │
│                                          │
│  1. Introduction                         │
│  2. Mechanism of Action                  │
│  3. Clinical Trials                      │
│  4. Safety Profile                       │
│  5. Comparison with Existing Drugs       │
│  6. Current Status and Future Directions │
└──────────┬───────────────────────────────┘
           ▼
┌──────────────────────────────────────────┐
│  Article Generation (LLM)                │
│  逐節填入內容 + 引用                      │
│                                          │
│  retrieve_top_k = 3 references/section   │
└──────────┬───────────────────────────────┘
           ▼
┌──────────────────────────────────────────┐
│  Article Polishing (LLM)                 │
│  - 加入 Executive Summary                │
│  - 移除重複內容                           │
│  - 最終輸出 Wikipedia 風格文章            │
└──────────────────────────────────────────┘
```

#### STORM LLM 分工配置

```
┌─────────────────────────────────────────────┐
│  5 個不同 LLM 配置：                         │
│                                             │
│  conv_simulator_lm   → gpt-4o-mini (對話)   │
│  question_asker_lm   → gpt-4o-mini (提問)   │
│  outline_gen_lm      → gpt-4-0125  (大綱)   │
│  article_gen_lm      → gpt-4o      (寫文)   │
│  article_polish_lm   → gpt-4o      (潤色)   │
│                                             │
│  不同任務用不同模型 → 成本 vs 品質平衡       │
└─────────────────────────────────────────────┘
```

**特點**：
- ✅ **多觀點設計** (unique!) — 模擬不同領域專家的思考方式
- ✅ 搜尋由「對話」驅動，更像人類研究過程
- ✅ 5 個 LLM 分工，成本最佳化
- ✅ 基於 dspy 框架，模組化設計
- ✅ Co-STORM 支援人機協作
- ❌ 搜尋本身很淺（每輪 3 個 SERP 查詢，top-3 結果）
- ❌ 沒有任何領域知識/MeSH/PICO
- ❌ 完全為寫文章設計，不是為找論文設計
- ❌ Retriever 只支援 web search (You.com/Bing/Google)

---

### Pattern 3: Iterative Search-Read-Reason Loop (Jina DeepResearch)

> **來源**: [github.com/jina-ai/node-DeepResearch](https://github.com/jina-ai/node-DeepResearch) (5.1k ⭐)
> **線上服務**: [search.jina.ai](https://search.jina.ai)
> **設計哲學**: 專注找答案，不寫長報告

```
User Query + Token Budget
    │
    ▼
┌────────────────────────────────────────────────────┐
│                    Main Loop                        │
│                                                    │
│  ┌──────────────────────────────────────────────┐  │
│  │  Step 1: REASON (LLM - Gemini 2.0 Flash)    │  │
│  │                                              │  │
│  │  Input: query + accumulated_context          │  │
│  │                                              │  │
│  │  LLM decides ONE of:                         │  │
│  │    🔍 "search" → 需要搜尋新資料              │  │
│  │    📖 "read"   → 需要讀取某個 URL 全文       │  │
│  │    💡 "answer" → 已有足夠資訊回答            │  │
│  │    🤔 "reflect"→ 需要重新思考方向            │  │
│  │                                              │  │
│  │  Output: structured JSON {action, query/url} │  │
│  └──────────────┬───────────────────────────────┘  │
│                 │                                  │
│       ┌─────────┼─────────┐                        │
│       ▼         ▼         ▼                        │
│  ┌─────────┐ ┌──────┐ ┌────────┐                  │
│  │ Search  │ │ Read │ │ Answer │                   │
│  │(Jina    │ │(Jina │ │(直接   │                   │
│  │ Reader) │ │Reader│ │ 回傳)  │                   │
│  │  API)   │ │ API) │ │        │                   │
│  └────┬────┘ └──┬───┘ └────────┘                   │
│       │         │                                  │
│       ▼         ▼                                  │
│  ┌──────────────────────────────────────────────┐  │
│  │  Step 3: Update Context                      │  │
│  │                                              │  │
│  │  accumulated_context += new_information       │  │
│  │  tokens_used += token_count(new_info)        │  │
│  │                                              │  │
│  │  if tokens_used >= token_budget:             │  │
│  │    → Force "answer" on next iteration        │  │
│  │  else:                                       │  │
│  │    → Continue loop                           │  │
│  └──────────────────────────────────────────────┘  │
│                                                    │
│  Typical: 2-42 steps depending on complexity       │
│                                                    │
└────────────────────────────────────────────────────┘
```

#### Jina 的精妙設計：Token Budget as 停止條件

```
┌──────────────────────────────────────────────────┐
│                                                  │
│  簡單問題 "capital of France?"                    │
│  → Step 1: reason → answer directly (0 searches) │
│  → Total: 1 step, ~100 tokens                    │
│                                                  │
│  中等問題 "latest news from Jina AI?"             │
│  → Step 1: reason → search                       │
│  → Step 2: reason → answer                       │
│  → Total: 2 steps, ~2000 tokens                  │
│                                                  │
│  困難問題 "who will be biggest competitor of X?"  │
│  → Step 1-42: search → read → reflect → search...│
│  → Total: 42 steps, ~50000 tokens                │
│                                                  │
│  ← Token budget 自然控制了搜尋深度 →              │
│                                                  │
└──────────────────────────────────────────────────┘
```

**特點**：
- ✅ **Token budget** 做為自然停止條件（elegant!）
- ✅ LLM 自己決定 search vs read vs answer (真正自主)
- ✅ 極簡架構，TypeScript 實現
- ✅ 提供 OpenAI-compatible API
- ✅ 有 production-ready 線上服務
- ⚠️ 明確表示**不做長報告**，專注精確回答
- ❌ 單一搜尋 API (Jina Reader)
- ❌ 沒有結構化的問題分解

---

### Pattern 4: LangGraph Agent Loop (LangChain Open Deep Research)

> **來源**: [github.com/langchain-ai/open_deep_research](https://github.com/langchain-ai/open_deep_research) (10.5k ⭐)
> **評測**: Deep Research Bench #6 (RACE score 0.4344)
> **演化**: 經歷 3 代架構變革

```
                         User Query
                              │
                              ▼
┌──────────────────────────────────────────────────┐
│  Search Agent (LangGraph ReAct Loop)              │
│                                                  │
│  ┌────────────────────────────────────────────┐  │
│  │  research_model (gpt-4.1)                  │  │
│  │                                            │  │
│  │  Think: "I need to find papers about..."   │  │
│  │    │                                       │  │
│  │    ▼                                       │  │
│  │  Act: search_tool("remimazolam sedation")  │  │
│  │    │                                       │  │
│  │    ▼                                       │  │
│  │  Observe: [result1, result2, ...]          │  │
│  │    │                                       │  │
│  │    ▼                                       │  │
│  │  Think: "I found info on dosing, but need  │  │
│  │         safety data..."                    │  │
│  │    │                                       │  │
│  │    ▼                                       │  │
│  │  Act: search_tool("remimazolam adverse     │  │
│  │       effects safety")                     │  │
│  │    │                                       │  │
│  │    ▼                                       │  │
│  │  Observe: [result3, result4, ...]          │  │
│  │    │                                       │  │
│  │    ▼                                       │  │
│  │  Think: "Now I have enough information."   │  │
│  │    │                                       │  │
│  │    ▼                                       │  │
│  │  STOP                                      │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  Summarization: summarize_model (gpt-4.1-mini)   │
│  Compression:   compression_model (gpt-4.1)      │
│                                                  │
└──────────────┬───────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────┐
│  Report Writer                                    │
│  final_report_model (gpt-4.1)                    │
│                                                  │
│  Compressed findings → Structured Report          │
└──────────────────────────────────────────────────┘
```

#### 架構演化史（值得深思的 Bitter Lesson）

```
┌──────────────────────────────────────────────────────┐
│                                                      │
│  v1: Workflow (legacy/graph.py)                      │
│  ├── Plan-and-Execute                                │
│  ├── Human-in-the-loop (人類審核 outline)             │
│  ├── Sequential: 逐節搜尋 + reflection                │
│  └── 評分: 較低                                       │
│                                                      │
│  v2: Multi-Agent (legacy/multi_agent.py)             │
│  ├── Supervisor + Researcher × N                     │
│  ├── 平行處理                                         │
│  ├── MCP 整合                                         │
│  └── 評分: 中等                                       │
│                                                      │
│  v3: Single Agent Loop (現行)                         │
│  ├── 一個 agent 自己搞定                              │
│  ├── ReAct loop: think → search → observe             │
│  ├── 4 LLM 分工 (summarize/research/compress/report) │
│  └── 評分: 最高! ← ⚠️ 簡單打敗複雜                    │
│                                                      │
│  ⚠️ Bitter Lesson:                                   │
│  "精心設計的 workflow/multi-agent 架構                 │
│   不如簡單的 single agent loop 效果好"                │
│  — LangChain blog (2025-07-30)                       │
│                                                      │
└──────────────────────────────────────────────────────┘
```

**特點**：
- ✅ 經過 Deep Research Bench 評測驗證 (#6)
- ✅ MCP 支援（可外接我們的工具！）
- ✅ 4 個 LLM 分工（summarize vs research vs compress vs report）
- ✅ Open Agent Platform (OAP) UI 支援
- ✅ 支援多種 search API + MCP
- ⚠️ Bitter Lesson — 簡單 agent loop > 複雜 workflow
- ❌ 搜尋策略完全由 agent 即興決定
- ❌ 沒有結構化問題分解步驟
- ❌ 評測成本 $45-$187/100 queries

---

### Pattern 5: 極簡遞迴搜尋 (dzhng/deep-research)

> **來源**: [github.com/dzhng/deep-research](https://github.com/dzhng/deep-research) (18.4k ⭐)
> **設計哲學**: "simplest implementation" — 目標 <500 LoC

```
User Query
    │
    ├── breadth: 4 (default)
    └── depth: 2 (default)
         │
         ▼
┌─────────────────────────────────────────────┐
│  Step 1: Generate Follow-up Questions (LLM) │
│                                             │
│  User: "remimazolam sedation"               │
│  LLM: "What specific aspects interest you?" │
│    1. Clinical trials?                      │
│    2. Comparison with propofol?             │
│    3. Safety profile?                       │
│  User answers → Refine direction            │
└──────────┬──────────────────────────────────┘
           ▼
┌─────────────────────────────────────────────┐
│  Step 2: Deep Research (Recursive)          │
│                                             │
│  function deepResearch(query, depth,        │
│                        breadth, context):   │
│                                             │
│    1. Generate SERP queries (LLM)           │
│       → ["remimazolam vs propofol RCT",     │
│          "remimazolam ICU sedation dose",    │
│          "remimazolam safety adverse",       │
│          "remimazolam onset duration"]       │
│                                             │
│    2. Execute searches (Firecrawl, 平行)     │
│       → [results1, results2, ...]           │
│                                             │
│    3. Process results (LLM)                 │
│       → Extract key learnings               │
│       → Generate follow-up directions       │
│                                             │
│    4. if depth > 0:                         │
│         for each direction:                 │
│           deepResearch(direction,           │
│                       depth - 1,            │
│                       breadth,              │
│                       context + learnings)  │
│                                             │
│    5. return all_learnings                  │
│                                             │
└──────────┬──────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│  Step 3: Generate Report (LLM)              │
│                                             │
│  All learnings → Comprehensive Markdown     │
│  → Save as report.md                        │
└─────────────────────────────────────────────┘
```

**特點**：
- ✅ 極簡（目標 <500 LoC），容易理解和修改
- ✅ Follow-up questions 階段有人機互動
- ✅ 支援 DeepSeek R1 / 自訂 OpenAI-compatible endpoint
- ✅ 18.4k stars 顯示社區認可度高
- ❌ 搜尋只用 Firecrawl，沒有學術來源
- ❌ 架構太簡單，沒有質量控制
- ❌ 沒有去重、排名、引用追蹤

---

### Pattern 6: 我們的 5-Layer Pipeline (PubMed Search MCP)

```
User Query: "Is remimazolam better than propofol for ICU sedation?"
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  Layer 1: QueryAnalyzer (< 1ms, 純 local, 不用 LLM)      │
│                                                          │
│  ┌─ Pattern Analysis ─────────────────────────────────┐  │
│  │  complexity: COMPLEX                                │  │
│  │  intent:     COMPARISON                             │  │
│  │  pico:       {P:"ICU patients",                     │  │
│  │              I:"remimazolam",                       │  │
│  │              C:"propofol",                          │  │
│  │              O:"sedation efficacy"}                 │  │
│  │  identifiers: none                                  │  │
│  │  clinical:   therapy                                │  │
│  │  confidence: 0.85                                   │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                          │
│  方法: 正則表達式 + 醫學詞彙庫 + 規則引擎                  │
│  特點: 確定性、零成本、零延遲                              │
└──────────────┬───────────────────────────────────────────┘
               ▼
┌──────────────────────────────────────────────────────────┐
│  Layer 2: SemanticEnhancer (1-5s, PubTator3 API, 不用 LLM)│
│                                                          │
│  ┌─ Entity Resolution (PubTator3) ─────────────────────┐ │
│  │  "remimazolam" → Chemical {MeSH: D000095234}        │ │
│  │  "propofol"    → Chemical {MeSH: D015742}           │ │
│  │  "ICU"         → Disease  {MeSH: D003422}           │ │
│  │  "sedation"    → Disease  {MeSH: D054198}           │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─ 5 Parallel Search Strategies ──────────────────────┐ │
│  │                                                      │ │
│  │  Strategy 1: original                                │ │
│  │    query: "remimazolam propofol ICU sedation"        │ │
│  │    precision: 0.7  recall: 0.5                       │ │
│  │                                                      │ │
│  │  Strategy 2: mesh_expanded                           │ │
│  │    query: '"Remimazolam"[MeSH] AND "Propofol"[MeSH] │ │
│  │           AND "Sedation"[MeSH]'                      │ │
│  │    precision: 0.8  recall: 0.7                       │ │
│  │                                                      │ │
│  │  Strategy 3: entity_semantic                         │ │
│  │    query: "CNS7056 2-propylphenol GABA receptor      │ │
│  │           agonist procedural sedation"               │ │
│  │    precision: 0.9  recall: 0.4                       │ │
│  │                                                      │ │
│  │  Strategy 4: fulltext_epmc                           │ │
│  │    query: Europe PMC optimized                       │ │
│  │    precision: 0.5  recall: 0.8                       │ │
│  │                                                      │ │
│  │  Strategy 5: broad_tiab                              │ │
│  │    query: high-recall OR-combined                    │ │
│  │    precision: 0.4  recall: 0.9                       │ │
│  │                                                      │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                          │
│  哲學: "Every search is deep AND wide"                   │
└──────────────┬───────────────────────────────────────────┘
               ▼
┌──────────────────────────────────────────────────────────┐
│  Layer 3: DispatchStrategy (< 1ms, 規則, 不用 LLM)       │
│                                                          │
│  ┌─ Source Selection Matrix ───────────────────────────┐ │
│  │                                                      │ │
│  │  ╔══════════╦══════════╦═══════════════════════════╗ │ │
│  │  ║Complexity║  Intent  ║  Selected Sources         ║ │ │
│  │  ╠══════════╬══════════╬═══════════════════════════╣ │ │
│  │  ║ SIMPLE   ║ LOOKUP   ║ [pubmed]                  ║ │ │
│  │  ║ SIMPLE   ║ other    ║ [pubmed]                  ║ │ │
│  │  ║ MODERATE ║ any      ║ [pubmed, crossref]        ║ │ │
│  │  ║ COMPLEX  ║ COMPARE  ║ [pubmed, openalex, s2]    ║ │ │
│  │  ║ COMPLEX  ║ SYSTEMIC ║ [pubmed, openalex, s2,    ║ │ │
│  │  ║          ║          ║  europe_pmc]              ║ │ │
│  │  ║ AMBIGUOUS║ any      ║ [pubmed, openalex]        ║ │ │
│  │  ╚══════════╩══════════╩═══════════════════════════╝ │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─ Ranking Preset Selection ──────────────────────────┐ │
│  │  SYSTEMATIC  → quality_focused (favor RCT/MA)       │ │
│  │  COMPARISON  → impact_focused  (high-cited papers)  │ │
│  │  EXPLORATION → recency_focused (cutting-edge)       │ │
│  │  default     → balanced                             │ │
│  └──────────────────────────────────────────────────────┘ │
└──────────────┬───────────────────────────────────────────┘
               ▼
┌──────────────────────────────────────────────────────────┐
│  Layer 4: PipelineExecutor (DAG, Kahn's Algorithm)       │
│                                                          │
│  ┌─ 10 Available Actions ─────────────────────────────┐  │
│  │                                                     │  │
│  │  🔍 search    → Multi-source parallel search        │  │
│  │  🏥 pico      → Parse PICO elements                 │  │
│  │  🔬 expand    → Semantic enhancement                │  │
│  │  📋 details   → Fetch article details               │  │
│  │  🔗 related   → Find similar articles               │  │
│  │  📊 citing    → Find citing articles                │  │
│  │  📚 references→ Get bibliography                    │  │
│  │  📈 metrics   → Add iCite citation metrics          │  │
│  │  🔀 merge     → Combine results (union/RRF/inter)   │  │
│  │  🔧 filter    → Post-filter by criteria             │  │
│  │                                                     │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌─ DAG Execution Example (PICO template) ─────────────┐ │
│  │                                                      │ │
│  │  Batch 1: [pico]                                     │ │
│  │    └→ Parse P/I/C/O elements                         │ │
│  │                                                      │ │
│  │  Batch 2: [search_p, search_i, search_c]  ← 平行！  │ │
│  │    ├→ search(P: "ICU patients") × 3 sources          │ │
│  │    ├→ search(I: "remimazolam")  × 3 sources          │ │
│  │    └→ search(C: "propofol")     × 3 sources          │ │
│  │                                                      │ │
│  │  Batch 3: [merge]                                    │ │
│  │    └→ RRF combine all results                        │ │
│  │                                                      │ │
│  │  Batch 4: [metrics]                                  │ │
│  │    └→ Add iCite citation metrics                     │ │
│  │                                                      │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                          │
│  Validator: 21 auto-fix rules (self-healing configs)     │
│  Store: dual-scope persistence (workspace + global)      │
└──────────────┬───────────────────────────────────────────┘
               ▼
┌──────────────────────────────────────────────────────────┐
│  Layer 5: ResultAggregator                               │
│                                                          │
│  ┌─ Deduplication ─────────────────────────────────────┐ │
│  │  Pass 1: DOI exact match                            │ │
│  │  Pass 2: PMID exact match                           │ │
│  │  Pass 3: Normalized title match (if > 20 chars)     │ │
│  │  Pass 4: Fuzzy title matching (aggressive mode)     │ │
│  │  Algorithm: O(n) Union-Find                         │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─ 6-Dimensional Ranking ─────────────────────────────┐ │
│  │                                                      │ │
│  │    Dimension       Weight   Measures                 │ │
│  │    ─────────────   ──────   ────────────────────     │ │
│  │    Relevance       0.25     Query term overlap       │ │
│  │    Quality         0.20     Article type score       │ │
│  │                             (RCT > review > case)    │ │
│  │    Recency         0.15     Exp decay (half=5yr)     │ │
│  │    Impact          0.20     Citations + RCR          │ │
│  │    Source Trust    0.10     PubMed(1)>CrossRef(.9)   │ │
│  │    Entity Match    0.10     PubTator3 overlap        │ │
│  │                                                      │ │
│  │  Presets:                                            │ │
│  │    balanced     → default weights                    │ │
│  │    impact       → impact 0.40                        │ │
│  │    recency      → recency 0.40                       │ │
│  │    quality      → quality 0.30                       │ │
│  │                                                      │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─ Search Depth Score (0-100) ─────────────────────────┐│
│  │  Entity resolution:  up to 30 pts                    ││
│  │  MeSH coverage:      up to 30 pts                    ││
│  │  Strategy diversity:  up to 20 pts                   ││
│  │  Recall estimate:     up to 20 pts                   ││
│  │  🟢 Deep ≥ 60 │ 🟡 Moderate ≥ 30 │ 🔴 Shallow < 30 ││
│  └──────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────┘
```

**特點**：
- ✅ **100% 不依賴 LLM** — 所有 5 層都是規則/API 驅動
- ✅ **12+ 學術來源** — 最豐富的資料來源
- ✅ **MeSH/PICO/PubTator3** — 深度生物醫學領域知識
- ✅ **6 維排名** — 超越簡單相關度排序
- ✅ **$0 運行成本** — 學術 API 全免費
- ✅ **可重複性** — 同樣輸入 = 同樣結果
- ✅ **40 個 MCP 工具** — 可被外部 Agent 調用
- ❌ **沒有迭代反饋** — 搜完就結束
- ❌ **固定規則問題分解** — PICO regex，不是 LLM 動態推理
- ❌ **沒有遞迴深入** — 不會從結果中發現新方向

---

## 4. 核心差異對比：問題分解策略

> **這是本報告的核心——各系統「從問題到搜尋查詢」之間的規劃差異。**

| 系統 | 問題分解方式 | 誰決定搜什麼 | 分解是否迭代 | 使用領域知識 |
|------|------------|------------|-----------|------------|
| **GPT Researcher** | LLM 產出子問題 → 平行搜尋 | LLM (Planner) | ✅ Tree 遞迴 | ❌ 無 |
| **STORM** | LLM 模擬專家對話 → 每輪產出查詢 | LLM (Personas) | ✅ 多輪對話 | ❌ 無 |
| **Jina** | LLM 在 loop 中即興決定 | LLM (Reasoning) | ✅ Token budget | ❌ 無 |
| **LangChain ODR** | Agent 自主搜尋 (ReAct loop) | LLM (Agent) | ✅ Agent loop | ❌ 無 |
| **dzhng** | LLM 產出 SERP queries → 遞迴 | LLM | ✅ depth/breadth | ❌ 無 |
| **我們** | QueryAnalyzer + SemanticEnhancer | **規則 + PubTator3** | ❌ **無** | ✅ **MeSH, PICO, PubTator3** |

### 差距的核心圖示

```
┌──────────────────────────────────────────────────────────┐
│  其他系統:                                                │
│                                                          │
│  User ──→ LLM思考 ──→ 搜尋 ──→ LLM看結果 ──→ 再思考     │
│                                      │                   │
│              ↑                       │                   │
│              └───── 反饋循環 ─────────┘                   │
│                                                          │
│  特點: 動態、自適應、但不可控、成本高                       │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  我們:                                                    │
│                                                          │
│  User ──→ 規則分析 ──→ 策略生成 ──→ 搜尋 ──→ 排名 ──→ 結果│
│                                                          │
│           (一次性，無反饋，直線流程)                        │
│                                                          │
│  特點: 確定性、精確、低成本、但無法自適應                    │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

## 5. 搜尋深度實現方式比較

| 系統 | 深度來源 | 廣度來源 | 停止條件 | 典型搜尋次數 |
|------|---------|---------|---------|------------|
| **GPT Researcher** | 遞迴展開子問題 (depth=3) | 每層多個子問題 (breadth=4) | depth 用完 | 64+ (4³) |
| **STORM** | 多輪對話 (turn=3) | 多觀點 (perspective=3) | Conv turn 用完 | ~27 (3×3×3) |
| **Jina** | LLM 持續推理 | LLM 決定搜新方向 | Token budget 耗盡 | 2-42 |
| **LangChain ODR** | Agent 反覆搜尋 | Agent 決定搜新方向 | Agent 判斷 enough | ~10-30 |
| **dzhng** | depth 參數 (1-5) | breadth 參數 (3-10) | depth 用完 | ~10-50 |
| **我們** | 5 平行策略 + 多源 | 12+ API 來源 | **一次性完成** | 5-15 |

### 視覺對比

```
搜尋次數 (每次查詢)

GPT Researcher    ████████████████████████████████████████  64+
dzhng             ██████████████████████████████           ~50
STORM             █████████████████                        ~27
LangChain ODR     §███████████████                         ~20
Jina              ████████ (varies 2-42)                   ~15
我們              ████████ (但命中 12+ 來源)                ~10
                  │         │         │         │
                  0        20        40        60

品質/搜尋 (每次搜尋的資訊品質)

我們              ████████████████████████████████████████  極高
                  (學術 API 結構化資料, MeSH 匹配)
LangChain ODR     ██████████████████████                   高
GPT Researcher    █████████████████                        中高
STORM             ████████████████                         中高
dzhng             ████████████                             中
Jina              ████████████████                         中高
                  │         │         │         │
                 低        中        高        極高
```

---

## 6. 資料來源與可靠性比較

| 維度 | PubMed Search MCP | STORM | GPT Researcher | Jina | LangChain ODR |
|------|-------------------|-------|----------------|------|---------------|
| **來源數量** | **12+ 學術 API** | 1-2 Web | 1 (Tavily) | 1 (Jina Reader) | 1+ (Tavily + MCP) |
| **文獻量** | **480M+** | Web 限制 | Web 限制 | Web 限制 | Web 限制 |
| **資料結構化** | ✅ PMID/DOI/MeSH/IF | ❌ | ❌ | ❌ | ❌ |
| **全文取得** | ✅ PMC + CORE + Unpaywall | ❌ 網頁摘要 | ❌ 網頁抓取 | ✅ 網頁讀取 | ❌ |
| **預印本** | ✅ arXiv/medRxiv/bioRxiv | 間接 | 間接 | 間接 | 間接 |
| **引用追蹤** | ✅ 正向+反向+iCite | ❌ | ❌ | ❌ | ❌ |
| **基因/藥物** | ✅ Gene/PubChem/ClinVar | ❌ | ❌ | ❌ | ❌ |
| **幻覺風險** | ⭐ 極低 (原始API) | ⭐⭐⭐⭐ 高 | ⭐⭐⭐ 高 | ⭐⭐⭐ 高 | ⭐⭐⭐ 高 |
| **可審計性** | ✅ 每筆有 PMID/DOI | ❌ URL 可能失效 | ❌ URL 可能失效 | ❌ | ❌ |

### 來源詳細清單 (我們的)

```
┌──────────────────────────────────────────────────────────┐
│  PubMed Search MCP: 12+ Academic Data Sources            │
│                                                          │
│  ┌─ Primary Literature ─────────────────────────────┐    │
│  │  📚 PubMed          30M+ articles  (NCBI/NLM)    │    │
│  │  📚 Europe PMC       33M+ articles  (EBI)        │    │
│  │  📚 OpenAlex         250M+ works   (OurResearch) │    │
│  │  📚 Semantic Scholar 200M+ papers  (AI2)         │    │
│  │  📚 CrossRef         150M+ records (DOI metadata)│    │
│  │  📚 CORE             200M+ papers  (Open Access) │    │
│  └──────────────────────────────────────────────────┘    │
│                                                          │
│  ┌─ Preprints ──────────────────────────────────────┐    │
│  │  📄 arXiv (physics, CS, math, bio)               │    │
│  │  📄 medRxiv (clinical medicine)                  │    │
│  │  📄 bioRxiv (biology)                            │    │
│  └──────────────────────────────────────────────────┘    │
│                                                          │
│  ┌─ Extended Databases ─────────────────────────────┐    │
│  │  🧬 NCBI Gene    (gene information)              │    │
│  │  💊 PubChem      (chemical compounds)            │    │
│  │  🏥 ClinVar      (clinical variants)             │    │
│  └──────────────────────────────────────────────────┘    │
│                                                          │
│  ┌─ Supplementary ──────────────────────────────────┐    │
│  │  🔓 Unpaywall    (Open Access links)             │    │
│  │  🖼️ Open-i       (biomedical images)             │    │
│  └──────────────────────────────────────────────────┘    │
│                                                          │
│  Total queryable records: 480,000,000+                  │
│  Cost: $0 (all free academic APIs)                      │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

## 7. Pipeline / 工作流系統比較

| 能力 | PubMed Search MCP | STORM | GPT Researcher | Jina | LangChain ODR | dzhng |
|------|-------------------|-------|----------------|------|---------------|-------|
| **Pipeline 定義** | ✅ YAML DAG (10 actions) | ❌ 固定 4 模組 | ❌ 固定流程 | ❌ 固定 loop | ❌ 固定 agent | ❌ 固定遞迴 |
| **可自訂模板** | ✅ 4 內建 + 自訂 | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Pipeline 持久化** | ✅ 儲存/載入/排程 | ❌ | ❌ | ❌ | ❌ | ❌ |
| **自動驗證修復** | ✅ 21 條 auto-fix | ❌ | ❌ | ❌ | ❌ | ❌ |
| **雙作用域存儲** | ✅ workspace + global | ❌ | ❌ | ❌ | ❌ | ❌ |
| **執行歷史** | ✅ 完整追蹤 | ✅ LLM call history | ❌ | ❌ | ✅ LangSmith | ❌ |
| **報告生成** | ✅ 7 區段結構化 | ✅ Wikipedia 文章 | ✅ 5-6 頁報告 | ⚠️ 精確答案 | ✅ 結構化報告 | ✅ report.md |
| **可重複性** | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐ |

---

## 8. 成本與依賴分析

```
┌──────────────────────────────────────────────────────────┐
│  每次搜尋的成本比較                                        │
│                                                          │
│  PubMed Search MCP    [$0.00]                            │
│  Jina DeepResearch    [$0.01-0.10] (Gemini Flash)        │
│  dzhng/deep-research  [$0.10-0.50] (o3-mini + Firecrawl) │
│  GPT Researcher       [$0.40]      (o3-mini + Tavily)     │
│  LangChain ODR        [$0.45-1.87] (gpt-4.1 + Tavily)    │
│  STORM                [$1.00-3.00] (gpt-4o × 5 LLMs)     │
│                                                          │
│  $0.00          $0.50          $1.00          $2.00      │
│  ├─PubMed──┤    ├──GPT-R──┤    ├──STORM────────┤         │
│  │         │    │         │    │               │         │
│  └─────────┘    └─────────┘    └───────────────┘         │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

| 維度 | PubMed Search MCP | STORM | GPT Researcher | Jina | LangChain ODR |
|------|-------------------|-------|----------------|------|---------------|
| **LLM API** | $0 | $$$ (GPT-4o × 5) | ~$0.4/次 | $ (Flash) | $0.45-1.87/次 |
| **Search API** | 免費 (NCBI) | 需付費 | 需付費 (Tavily) | $ (Jina) | 需付費 |
| **外部依賴** | Python + httpx | dspy + LLM + Search | LangGraph + LLM | Node.js + LLM | LangGraph + LLM |
| **Rate Limit** | ✅ 內建處理 | N/A | N/A | RPM 限制 | N/A |
| **離線可用** | 部分 (cache) | ❌ | ❌ | ❌ | ❌ |

---

## 9. 整合生態比較

| 維度 | PubMed Search MCP | STORM | GPT Researcher | Jina | LangChain ODR |
|------|-------------------|-------|----------------|------|---------------|
| **協議** | ✅ MCP | ❌ 自有 | ✅ MCP Client | ✅ OpenAI API | ✅ MCP |
| **MCP 工具數** | **40** | 0 | MCP 消費者 | 0 | MCP 消費者 |
| **AI 助手整合** | Claude/Copilot/Cursor | 獨立 | 獨立 + MCP | 任何 OpenAI client | LangGraph Studio |
| **引用匯出** | ✅ RIS/BibTeX/MEDLINE | ❌ | PDF/Word/MD | ❌ | ❌ |
| **REST API** | ✅ HTTP/SSE | Python API | FastAPI | OpenAI-compatible | LangGraph API |
| **Web UI** | ❌ | Gradio | NextJS | ✅ search.jina.ai | LangGraph Studio |

---

## 10. 架構模式光譜圖

### 規則驅動 vs LLM 驅動

```
規則驅動                                              LLM 驅動
    │                                                     │
    ▼                                                     ▼
    ┌────┐                                          ┌────────┐
    │我們│     ┌──────┐  ┌─────────┐  ┌───────────┐ │LangChain│
    │5層 │     │STORM │  │GPT      │  │dzhng      │ │  ODR   │
    │DAG │     │對話  │  │Researcher│  │遞迴      │ │ Agent  │
    │規則│     │展開  │  │Planner  │  │          │ │ Loop   │
    └────┘     └──────┘  └─────────┘  └───────────┘ └────────┘
                                                     ┌────┐
                                                     │Jina│
                                                     │Loop│
                                                     │推理│
                                                     └────┘
    ┊                                                     ┊
    精確可控                              靈活但不可控
    無反饋迭代                            有反饋迭代
    領域專精                              通用但淺
    $0 LLM                               $0.4-$$$
```

### 搜尋基建 vs 智能搜尋迴路

```
                    智能搜尋迴路 (反饋/迭代能力)
                         ▲
                 強      │
                         │
                    ┌────┤────────────────────┐
                    │    │  LangChain ODR     │
                    │    │    ●               │
                    │    │                    │
                    │ Jina ●    GPT Researcher│
                    │    │       ●             │
                    │    │                    │
                    │    │   STORM ●          │
                    │    │                    │
                    │ dzhng ●                 │
                    │    │                    │
                    └────┤────────────────────┘
                 弱      │
                         │    我們 ●─ ─ ─ ─ ─ ─ ● 目標位置
                         │                        (Level 2 改進後)
                         │
                         └──────────────────────────────────→
                      弱              搜尋基建               強
                              (來源/領域知識/排名)
```

> **我們在右下角（強基建、弱迴路），目標是移動到右上角（兩者兼備）。**

---

## 11. SWOT 分析

### PubMed Search MCP

| | 正面 | 負面 |
|---|---|---|
| **內部** | **Strengths** | **Weaknesses** |
| | • 12+ 專業學術來源 | • 限於生物醫學/學術 |
| | • 40 MCP 工具 | • 不自動產出完整報告文本 |
| | • Pipeline DAG (unique!) | • 無迭代反饋 (一次性搜尋) |
| | • 零 LLM 成本 | • 問題分解依賴固定規則 |
| | • 6D 排名系統 | • 無 Web UI |
| | • MeSH/PICO/PubTator3 | • 無遞迴深入機制 |
| | • 學術嚴謹可審計 | |
| | • MCP 標準協議 | |
| **外部** | **Opportunities** | **Threats** |
| | • MCP 生態快速成長 | • Google Scholar MCP 開放 |
| | • 可與 LangChain ODR 互補 | • Elicit/Consensus 等商業競品 |
| | • 學術 AI 需求激增 | • PubMed 自身 AI 功能擴張 |
| | • 加入反饋迴路成本低 | • LLM 降價使競品成本優勢削弱 |
| | • 可成為其他 deep research 的底層工具 | |

---

## 12. 改進路線圖

### 核心差距（一句話版）

> **我們有最好的搜尋基建，但缺少智能搜尋迴路。**

### Level 1: 結果反饋迴路（Result Feedback Loop）— 不需 LLM

```
現在:
  Query → 搜尋 → 結果 (結束)

改進:
  Query → 搜尋 → 結果 → evaluate → [達標?]
                                      │ No
                                      ▼
                              調整策略 → 再搜
                                      │
                                      ▼
                              結果 → evaluate → [達標?]
                                                │ Yes
                                                ▼
                                              完成
```

**Pipeline 新 action: `evaluate`**
```yaml
steps:
  - id: search_initial
    action: search
    params:
      query: "remimazolam sedation"
      limit: 20

  - id: check_results
    action: evaluate          # ← 新 action
    inputs: [search_initial]
    params:
      min_results: 10         # 最少結果數
      min_rct_count: 3        # 最少 RCT 數量
      min_depth_score: 60     # 最低搜尋深度分數
      max_retry: 2            # 最多重試次數

  - id: search_expanded       # ← 條件執行
    action: search
    inputs: [check_results]   # 只在 evaluate 不通過時執行
    params:
      query: "{auto_expanded_query}"
      sources: ["openalex", "semantic_scholar"]
```

**評估規則（全部可用規則實現，不需 LLM）**：
- 結果數量 < 目標？→ 擴大搜尋範圍
- RCT/Meta-analysis 比例太低？→ 加上 Publication Type 過濾
- 時間分布偏舊？→ 調整 recency 權重
- MeSH coverage 太低？→ 嘗試更多 MeSH terms

---

### Level 2: 動態查詢擴展（Dynamic Query Expansion）— 不需 LLM

```
現在:
  固定 5 策略 (original / mesh / entity / epmc / broad)

改進:
  第一輪搜尋結果
      │
      ▼
  分析結果中的高頻 MeSH terms
      │
      ▼
  發現新的關聯詞彙
  例: 搜 "remimazolam sedation"
      → 結果中 "Dexmedetomidine" 出現 15 次
      → 自動追加: "remimazolam vs dexmedetomidine"
      │
      ▼
  第二輪搜尋（擴展查詢）
      │
      ▼
  合併去重 + 重新排名
```

**Pipeline 新 action: `discover`**
```yaml
steps:
  - id: initial_search
    action: search
    params: { query: "remimazolam sedation" }

  - id: discover_terms
    action: discover          # ← 新 action
    inputs: [initial_search]
    params:
      method: mesh_frequency  # 從結果中提取 MeSH 高頻詞
      min_frequency: 5        # 至少出現 5 次才納入
      exclude_original: true  # 排除原始查詢已包含的詞
      max_new_terms: 3        # 最多產出 3 個新查詢

  - id: expanded_search
    action: search
    inputs: [discover_terms]
    params:
      query: "{discovered_query}"

  - id: final_merge
    action: merge
    inputs: [initial_search, expanded_search]
    params: { method: rrf }
```

---

### Level 3: Optional LLM 推理層 — 需要 LLM (opt-in)

```
Pipeline 新 action: reason (optional, 需要 LLM)

┌────────────────────────────────────────────────────┐
│  action: reason                                    │
│                                                    │
│  Input: 第一輪搜尋結果                              │
│  LLM Prompt:                                      │
│    "Based on these {N} articles about {topic},     │
│     what are the gaps in the current results?      │
│     Suggest 2-3 follow-up search queries."         │
│                                                    │
│  Output: [new_query_1, new_query_2, ...]           │
│                                                    │
│  特點:                                             │
│    - Optional：不加這個 action 也能跑              │
│    - Cost-aware：可以用最便宜的模型                 │
│    - Auditable：LLM 輸入輸出都記錄                 │
│                                                    │
└────────────────────────────────────────────────────┘
```

```yaml
steps:
  - id: initial_search
    action: search
    params: { query: "CRISPR gene therapy" }

  - id: analyze_gaps
    action: reason              # ← 新 action (optional, 需 LLM)
    inputs: [initial_search]
    params:
      model: "gpt-4o-mini"     # 可指定模型
      prompt_template: gap_analysis
      max_suggestions: 3

  - id: followup_search
    action: search
    inputs: [analyze_gaps]
    params:
      query: "{suggested_queries[0]}"

  - id: final_merge
    action: merge
    inputs: [initial_search, followup_search]
```

---

### Level 4: Perspective-guided 多角度搜尋 — 需要 LLM (opt-in)

借鑑 STORM，用學術領域的觀點：

```yaml
steps:
  - id: generate_perspectives
    action: perspectives        # ← 新 action (optional, 需 LLM)
    params:
      topic: "remimazolam"
      domain: "medicine"
      max_perspectives: 3
    # Output: ["pharmacology", "clinical_trials", "safety"]

  - id: search_pharmacology
    action: search
    inputs: [generate_perspectives]
    params:
      query: "remimazolam {perspectives[0]}"

  - id: search_clinical
    action: search
    inputs: [generate_perspectives]
    params:
      query: "remimazolam {perspectives[1]}"

  - id: search_safety
    action: search
    inputs: [generate_perspectives]
    params:
      query: "remimazolam {perspectives[2]}"

  - id: merge_all
    action: merge
    inputs: [search_pharmacology, search_clinical, search_safety]
    params: { method: rrf }
```

---

### 改進優先級總結

| 優先級 | 改進 | 需要 LLM? | 預估開發量 | 價值 |
|--------|------|-----------|----------|------|
| 🥇 P0 | `evaluate` action — 結果品質評估 + 條件重搜 | ❌ 不需要 | 中 | 極高 |
| 🥈 P1 | `discover` action — 從結果中提取新查詢 | ❌ 不需要 | 中 | 高 |
| 🥉 P2 | `reason` action — LLM 分析 gaps (opt-in) | ✅ 需要 | 低 | 中高 |
| 🏅 P3 | `perspectives` action — 多角度搜尋 (opt-in) | ✅ 需要 | 低 | 中 |
| — | 與 LangChain ODR MCP 整合測試 | ❌ 不需要 | 低 | 高 |

---

## 13. 與 LangChain ODR 的互補關係

LangChain Open Deep Research 是**最可能與我們互補**的系統：

```
┌──────────────────────────────────────────────────────────┐
│  理想組合: LangChain ODR + PubMed Search MCP             │
│                                                          │
│  ┌────────────────────────────────────────┐               │
│  │  LangChain ODR (Agent 層)              │               │
│  │                                        │               │
│  │  • 推理 (gpt-4.1)                     │               │
│  │  • 問題分解                            │               │
│  │  • 結果品質判斷                         │               │
│  │  • 報告撰寫                            │               │
│  │  • 迭代反饋循環                         │               │
│  │                                        │               │
│  │  search_api: MCP ─────────┐            │               │
│  └────────────────────────────┤            │               │
│                               │            │               │
│                               ▼            │               │
│  ┌────────────────────────────────────────┐│               │
│  │  PubMed Search MCP (工具層)             ││               │
│  │                                        ││               │
│  │  • unified_search (精確學術搜尋)       ││               │
│  │  • find_related_articles               ││               │
│  │  • get_citation_metrics                ││               │
│  │  • get_fulltext                        ││               │
│  │  • build_citation_tree                 ││               │
│  │  • prepare_export (RIS/BibTeX)        ││               │
│  │  • 12+ academic API sources            ││               │
│  │  • MeSH/PICO/PubTator3               ││               │
│  └────────────────────────────────────────┘│               │
│                                                          │
│  結果: LLM 的推理能力 + 學術 API 的精確性                 │
│         = 最強的學術 Deep Research                         │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

## 14. 總結

### 本報告的核心發現

#### 1. 五大檢索架構模式

| 模式 | 代表系統 | 核心機制 |
|------|---------|---------|
| **Planner → Executor** | GPT Researcher | LLM 分解問題 → 平行搜尋 |
| **Perspective Conversation** | STORM | 多觀點模擬對話 → 逐步搜尋 |
| **Iterative Reason Loop** | Jina DeepResearch | LLM 在 loop 中自主搜尋/讀取 |
| **Agent Search Loop** | LangChain ODR | ReAct agent 反覆搜 + 壓縮 |
| **Layered Pipeline** | 我們 | 規則分析 → 策略生成 → 多源平行搜尋 |

#### 2. 所有系統的共同點

```
✅ 都有某種「思考」步驟（LLM reasoning 或 規則分析）
✅ 都有某種「行動」步驟（搜尋、讀取）
✅ 都有某種「總結」步驟（排名、報告）
❓ 大部分有「反思」步驟（我們沒有!）
```

#### 3. 我們的獨特定位

```
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  我們不是另一個 "Deep Search Agent"                       │
│                                                          │
│  我們是一個 專業學術文獻研究的工具生態系統                  │
│  為 AI 助手提供 40 個精密工具                             │
│  讓它們能夠進行嚴謹、可追溯、可重複的學術研究              │
│                                                          │
│  核心優勢:                                               │
│    1. 資料可靠性 — 原始 API 資料，無 LLM 幻覺風險         │
│    2. 搜尋基建   — 12+ 來源、MeSH、PICO、6D 排名         │
│    3. 可重複性   — Pipeline DAG 可存儲、重執行             │
│    4. 零成本     — 不需 LLM API、不需付費搜尋 API         │
│    5. MCP 生態   — 與任何 MCP Client 無縫協作              │
│    6. 學術完整性 — 每筆結果有 PMID/DOI，支援正式引用匯出   │
│                                                          │
│  最大改進空間:                                            │
│    加入「搜完 → 評估 → 調整 → 再搜」的反饋迴路            │
│    (不一定需要 LLM，規則也能做到基本的迭代)               │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

## 參考連結

| 系統 | GitHub | 文檔 |
|------|--------|------|
| GPT Researcher | [assafelovic/gpt-researcher](https://github.com/assafelovic/gpt-researcher) | [docs.gptr.dev](https://docs.gptr.dev/) |
| Stanford STORM | [stanford-oval/storm](https://github.com/stanford-oval/storm) | [NAACL'24 Paper](https://arxiv.org/abs/2402.14207) |
| dzhng/deep-research | [dzhng/deep-research](https://github.com/dzhng/deep-research) | README |
| LangChain ODR | [langchain-ai/open_deep_research](https://github.com/langchain-ai/open_deep_research) | [Blog](https://blog.langchain.com/open-deep-research/) |
| Jina DeepResearch | [jina-ai/node-DeepResearch](https://github.com/jina-ai/node-DeepResearch) | [Guide](https://jina.ai/news/a-practical-guide-to-implementing-deepsearch-deepresearch) |
| nickscamara/ODR | [nickscamara/open-deep-research](https://github.com/nickscamara/open-deep-research) | README |
| Auto-Deep-Research | [HKUDS/Auto-Deep-Research](https://github.com/HKUDS/Auto-Deep-Research) | [Docs](https://metachain-ai.github.io/docs) |
| Qwen-Agent | [QwenLM/Qwen-Agent](https://github.com/QwenLM/Qwen-Agent) | [QwenAgent Docs](https://qwenlm.github.io/Qwen-Agent/en/) |

---

> **文件結束** — 本文件應隨新的 deep research repo 出現或我們的架構演進而更新。
