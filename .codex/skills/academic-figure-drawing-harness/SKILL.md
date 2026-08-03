---
name: academic-figure-drawing-harness
description: "Codex drawing harness integration. Triggers: 繪圖, draw, figure, chart, plot, mermaid, SVG, Gemini, graph, 生成圖表."
---

# Academic Figures MCP: Codex Drawing Harness

這個技能專為整合 Codex 原生繪圖能力與 MCP 提供的 Gemini 圖像生成、PubMed 學術圖表檢索而設計。

## 核心策略 (Core Strategies)

1. **原生與生成結合 (Hybrid Rendering)**
   - **結構化與流程圖**: 優先使用 Codex 原生的 Markdown mermaid 語法、SVG 或 Python matplotlib/plotly 繪製精確的架構圖、長條圖、散佈圖與數據模型。
   - **複雜醫學/生物插圖**: 使用 MCP 工具（如 mcp_academic-figu_generate_figure 或 Gemini tools）生成高度複雜的 3D 解剖圖、顯微組織圖、或不規則概念圖。
   - **雙重驗證**: 如果需要，使用 mcp_academic-figu_plan_figure 來規劃最適切的呈現路由（決定應該用程式繪圖還是 AI 生成）。

2. **學術級距要求 (Citation-Ready & Provenance)**
   - 引用的出處必須準確，可利用 PubMed 工具 unified_search 或 get_article_figures 索取參考來源或範例圖片。
   - 生成的文字標題 (Caption) 必須符合學術期刊規範 (包含圖號、簡短標題、詳細說明、與 PMID 出處)。

3. **編輯與優化 (Iterative Refinement)**
   - 當產生初步圖表後，利用互動工具 mcp_academic-figu_evaluate_figure (8 維度品質評估) 或 mcp_academic-figu_edit_figure 根據使用者回饋進行微調 (例如改顏色、調佈局)。
   - 原生 SVG/Mermaid 代碼請直接利用 Codex 的 text edit 能力與 replace_string_in_file 重構並更新。

## 操作流程 (Workflow)

- **Step 1: 規劃圖表 (Plan)**
  取得需求或文獻內容後，分析合適的圖表類型 (figure_type: flowchart, mechanism, comparison, data_visualization 等)。
- **Step 2: 選擇路由 (Route Selection)**
  - 若能用程式化表達 (如統計數據)，引導 Codex 撰寫 Python 腳本或 Mermaid。
  - 若需精美點陣圖，呼叫 generate_figure。
- **Step 3: 附加上下文與組裝 (Assemble)**
  產生最終圖片的 Markdown 嵌入格式 ![Figure Name](output_path)，並加上完整的學術來源與 PICO/MeSH 背景說明。
