# 學術檢索參考 Repository 地圖

本目錄是 PubMed Search MCP 的外部設計研究，而不是套件推薦榜或可直接搬用的程式碼清單。調查以 **2026-09-01 UTC** 可取得的 GitHub repository、授權檔、原始碼、測試與工作流程為準；舊有的 [`competitor-analysis.md`](../competitor-analysis.md) 與 [`DEEP_RESEARCH_ARCHITECTURE_ANALYSIS.md`](../DEEP_RESEARCH_ARCHITECTURE_ANALYSIS.md) 保留為歷史資料，不作為本次現況判斷的依據。

## 結論先行

值得採用的不是另一套「很多 provider、很多 MCP tools」外殼，而是把目前的 `unified_search` 強化成單一學術搜尋主幹：provider capability 規劃、canonical work identity、欄位級 provenance、citation evidence graph、可重播 session，以及可稽核的後續篩選。向量資料庫、PDF parser、Zotero、實體知識庫與答案生成都應接在 ports/adapters 或後處理 pipeline，不應取代搜尋核心。

```mermaid
flowchart LR
    U["Agent 或 SDK"] --> S["unified_search"]
    S --> P["查詢規劃與能力選源"]
    P --> A["學術來源 adapters"]
    A --> C["Canonical works 與 evidence ledger"]
    C --> R["排序 去重 覆蓋率"]
    R --> X["Session artifacts 與可重播輸出"]
    X --> E["可選外接：全文 圖譜 篩選 Zotero RAG"]
```

## 交付物

- [`candidates.md`](candidates.md)：**60 個**候選 repository；分為直接學術 MCP、鄰接學術引擎，以及通用檢索 adapter reserve。
- [`recommended-direction.md`](recommended-direction.md)：跨 repository 綜合後，對本專案的目標架構、資料契約、編年史、測試與分期 backlog 建議。
- [`reports/`](reports/)：10 份逐 repo 深讀，每份都有固定 commit、重要程式碼 permalink、架構圖、採用／改造／拒絕判斷與可執行 backlog。

## 深讀選擇方式

候選先按五個面向判讀，再以「互補性」選出十個；因此這不是用 star 數或單一總分排出的 Top 10。

| 面向 | 權重 | 判斷問題 |
| --- | ---: | --- |
| 學術搜尋核心契合 | 35% | 是否改善查詢、來源規劃、去重、排序、引用或全文證據？ |
| 架構可移植性 | 25% | 概念能否放進既有 DDD 與 ports/adapters，而不把邏輯塞進 MCP tool？ |
| Provenance 與重現性 | 15% | 是否保留來源、版本、失敗、時間、合併決策或可重播狀態？ |
| 外接邊界品質 | 15% | 是否示範可替換 provider、plugin、artifact 或 pipeline contract？ |
| 維護與授權風險 | 10% | 測試、CI、活動度、授權與合規是否足以供參考？ |

## 十個深讀與各自角色

| # | Repository | 為何入選 | 對本專案最重要的啟示 |
| ---: | --- | --- | --- |
| 1 | [`cyanheads/pubmed-mcp-server`](reports/01-cyanheads-pubmed-mcp-server.md) | PubMed MCP 的完整服務與錯誤契約 | 全文 fallback provenance、bounded response、schema fuzz |
| 2 | [`cyanheads/openalex-mcp-server`](reports/02-cyanheads-openalex-mcp-server.md) | OpenAlex capability 面最完整的 MCP 實作之一 | self-describing fields、projection、budget telemetry |
| 3 | [`carsten-streb/openalex-mcp`](reports/03-carsten-streb-openalex-mcp.md) | 線上 provider contract 測試特別成熟 | weekly live checks、cross-tool invariants、release bundle smoke |
| 4 | [`blazickjp/arxiv-mcp-server`](reports/04-blazickjp-arxiv-mcp-server.md) | 搜尋後 artifact 與持續監測設計完整 | outline/section 漸進揭露、alerts cursor、部分成功 |
| 5 | [`genomoncology/biomcp`](reports/05-genomoncology-biomcp.md) | 多來源生醫規劃與 domain pivot 的強範例 | candidate/enrichment 分工、來源狀態、typed small surface |
| 6 | [`ASReview/asreview`](reports/06-asreview.md) | 主動學習式系統性篩選的成熟引擎 | 可重播 screening cycle、plugin components、schema migration |
| 7 | [`ourresearch/openalex-guts`](reports/07-openalex-guts.md) | 大規模學術紀錄融合的實戰 domain model | work/record 分離、欄位級來源優先序、redirect identity |
| 8 | [`opencitations/oc_meta`](reports/08-opencitations-oc-meta.md) | 引用 metadata 與 provenance 工作流 | merge history、可逆合併、獨立 provenance store |
| 9 | [`Future-House/paper-qa`](reports/09-paper-qa.md) | 學術 evidence retrieval 與選配 synthesis | manifest/hash index、MMR evidence、無證據時 abstain |
| 10 | [`LocalCitationNetwork/LocalCitationNetwork.github.io`](reports/10-local-citation-network.md) | 時序化 citation graph 的直接 UX 參考 | 年份分層、seed links、缺漏節點與匯出 provenance |

## 閱讀界線

- 「值得學習」不等於可複製程式碼。每份報告都另外標示授權、耦合、測試與合規風險。
- GitHub 的最近更新時間只代表活動訊號，不代表品質；報告以固定 commit permalink 讓結論可重現。
- Google Scholar scraping、Sci-Hub、把 citation count 當品質分數、無來源的 LLM metadata，以及隱藏部分失敗，均不列為建議方向。
- 深讀內容是設計輸入。真正導入仍須有 ADR、domain contract、migration 與本專案自己的測試。
