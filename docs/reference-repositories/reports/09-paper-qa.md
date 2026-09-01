# PaperQA 深度分析

## 查證快照

| 欄位 | 查證結果 |
|---|---|
| 查證日期 | 2026-09-01 |
| Repository | [Future-House/paper-qa](https://github.com/Future-House/paper-qa) |
| 固定版本 | [`57e89f7223b0960d5ee5ea048c69e3c47e088572`](https://github.com/Future-House/paper-qa/tree/57e89f7223b0960d5ee5ea048c69e3c47e088572) |
| 主要語言 | Python |
| 授權 | Apache-2.0 |
| 維護訊號 | GitHub `pushed_at` 為 2026-08-26；固定的 `main` commit 與 release `v2026.08.12` 均為 2026-08-12；具 CI、typed package、provider cassettes、document fixtures 與多個 reader subpackages |

PaperQA2 是以科學文獻為重點的 agentic RAG package：取得或載入文件、補 metadata、建立全文索引、收集 query-specific evidence，再產生帶 in-text citations 的回答。它與本專案互補，但邊界必須清楚：`unified_search` 的責任是可稽核地找到與排序學術紀錄；RAG 是消費既有 evidence 的可選 synthesis layer，不能反過來成為搜尋真相來源。

## 定位與主要流程

固定版本 [`README.md`](https://github.com/Future-House/paper-qa/blob/57e89f7223b0960d5ee5ea048c69e3c47e088572/README.md) 明列三階段：paper search、gather evidence、generate answer。它使用 metadata-aware embeddings、LLM reranking 與 contextual summarization，並可讓 agent 反覆改寫 query 或追加 evidence。

```mermaid
flowchart LR
    Q["Research question"] --> S["Candidate paper search"]
    S --> M["Metadata providers"]
    M --> I["Document index and manifest"]
    I --> C["Relevant chunks"]
    C --> E["Contextual evidence summaries"]
    E --> R["Rerank and select"]
    R --> A["Answer with citations"]
```

## 值得學習的實作

### Provider interface 與 typed query

[`src/paperqa/clients/client_models.py`](https://github.com/Future-House/paper-qa/blob/57e89f7223b0960d5ee5ea048c69e3c47e088572/src/paperqa/clients/client_models.py) 以 `MetadataProvider`、`MetadataPostProcessor` 與 `DOIOrTitleBasedProvider` 表達外部 metadata 能力，並用 Pydantic 的 `DOIQuery`、`TitleAuthorQuery` 驗證欄位、threshold 與 DOI URL normalization。具體 adapters 分在 [`src/paperqa/clients/`](https://github.com/Future-House/paper-qa/tree/57e89f7223b0960d5ee5ea048c69e3c47e088572/src/paperqa/clients)，包含 Crossref、OpenAlex、Semantic Scholar、Unpaywall、retractions 與 journal quality。

這種 provider-neutral protocol 與本專案既有 ports 方向一致；更值得借鏡的是 provider query／postprocessor 分開，以及 metadata enrichment 可平行且應 idempotent 的明確註解。然而 `DOIOrTitleBasedProvider.query()` 捕捉 DOI not found、HTTP request、retry、timeout 後一律回傳 `None`。這是方便上層繼續工作的 fail-soft，但同時抹平 `not_found`、`provider_down`、`timeout` 與 `retries_exhausted`。對 coverage-first 的 `unified_search`，這種 silent absence 不能照搬。

### 可重用索引與文件生命週期

[`src/paperqa/docs.py`](https://github.com/Future-House/paper-qa/blob/57e89f7223b0960d5ee5ea048c69e3c47e088572/src/paperqa/docs.py) 管理文件、索引目錄、file hash、manifest、writer/searcher 與重複加入判斷。以內容 hash 判定檔案是否改變，使下一次 query 可以重用索引，而不是每次重切 PDF。程式也明確處理 async index cache 與 writer race 的限制。這對本專案 future full-text index 很有價值：artifact identity 應以內容 checksum 與 parser/version 組成，而非只靠檔名或 PMID。

[`packages/`](https://github.com/Future-House/paper-qa/tree/57e89f7223b0960d5ee5ea048c69e3c47e088572/packages) 將 Docling、Nemotron、PyMuPDF、PyPDF readers 做成額外 packages，說明重型或供應商特定 parser 可以放在 optional adapter，不必污染 core install。

### Search、evidence 與 answer 是不同階段

[`src/paperqa/agents/search.py`](https://github.com/Future-House/paper-qa/blob/57e89f7223b0960d5ee5ea048c69e3c47e088572/src/paperqa/agents/search.py) 處理 agent search/index 行為；[`src/paperqa/agents/tools.py`](https://github.com/Future-House/paper-qa/blob/57e89f7223b0960d5ee5ea048c69e3c47e088572/src/paperqa/agents/tools.py) 把搜尋、evidence gathering 與回答能力提供給 agent；[`src/paperqa/core.py`](https://github.com/Future-House/paper-qa/blob/57e89f7223b0960d5ee5ea048c69e3c47e088572/src/paperqa/core.py) 保留核心 evidence/answer orchestration。此分段能避免「模型直接讀全部全文後憑印象回答」。

測試使用大量錄製的 provider cassettes，例如 [`tests/cassettes/test_bad_dois.yaml`](https://github.com/Future-House/paper-qa/blob/57e89f7223b0960d5ee5ea048c69e3c47e088572/tests/cassettes/test_bad_dois.yaml)、[`tests/cassettes/test_s2_title_search_empty_data.yaml`](https://github.com/Future-House/paper-qa/blob/57e89f7223b0960d5ee5ea048c69e3c47e088572/tests/cassettes/test_s2_title_search_empty_data.yaml) 與 [`tests/cassettes/test_crossref_retraction_status.yaml`](https://github.com/Future-House/paper-qa/blob/57e89f7223b0960d5ee5ea048c69e3c47e088572/tests/cassettes/test_crossref_retraction_status.yaml)。這比只 mock client method 更能捕捉上游 payload edge cases。

### Evidence contract 比漂亮回答更重要

PaperQA 的回答示例會把引用放在敘述旁，方向正確；但對本專案，最低可接受單位應再往下落到 claim-to-span。每個 claim 必須能回到特定 paper、頁面或 section、原始 excerpt hash 與 parser revision。若 evidence 只支持相近主題而非該 claim，系統要能標成 unsupported，而不是因引用格式存在就通過。評估也應分成 retrieval recall、evidence relevance、citation entailment 與 answer completeness，避免用單一 LLM judge 分數掩蓋漏搜。

這項設計也讓外接模型可替換：模型只負責從 frozen evidence 提議摘要，citation verifier 與 artifact reader 仍可在沒有該模型的情況下獨立工作。

## 對本專案的採用判斷

| 類別 | 判斷 |
|---|---|
| 採用 | search／evidence／answer 階段分離、typed provider query、content-hash manifest、optional readers、錄製的 HTTP contract fixtures、claim 旁的 evidence locator |
| 調整後採用 | 所有 provider call 回傳 `ProviderOutcome`，保留 success／empty／partial／failed、retryability 與 coverage；synthesis 只讀 session artifacts |
| 不採用 | 不把 agentic RAG 放進 `unified_search`，不讓 LLM 自動擴寫 query 卻不保存 strategy，也不以生成答案取代 results/audit artifact |
| 不照搬 | 不接受 exception→`None` 的 silent fail-soft；不把全域本地 index、LLM settings 或 PaperQA CalVer model behavior 變成核心依賴 |

合理預留方式是 `EvidenceSynthesisPort`：輸入 frozen search/full-text artifact、問題、budget 與模型設定；輸出 claims、逐 claim evidence spans、paper IDs、未支持內容、cost 與 model/prompt versions。MCP 可日後增加明確 synthesis capability，但 `unified_search` 仍只負責 retrieval。任何 agent-generated follow-up query 都要變成新的 search run，完整保存 query strategy 與來源 coverage。

## 風險與授權

- README 明示 2025 年底改用 CalVer，基本上不承諾跨 release backward compatibility；整合必須 pin version 與 contract tests。
- LLM、embedding、reranker 與 parser 會造成非決定性、費用、隱私及供應商依賴；預設不應把未公開 PDF 傳給外部模型。
- fail-soft 的 `None` 可讓回答繼續產生，卻可能讓使用者看不到某 metadata provider 已中斷；我們必須 fail-visible。
- chunk-level evidence 可能失去 section、table、negation 或 study-context；citation 存在不等於 claim 被支持。
- Apache-2.0 可改作，但實際使用的模型、datasets、readers 與 API 各有獨立授權及條款。

## 可執行 backlog

1. 定義 `EvidenceBundle` 與 `EvidenceSpan`，包含 artifact checksum、PMID/DOI、頁碼／section、原文 hash、parser version 與可讀 locator。
2. 新增 optional `EvidenceSynthesisPort`，第一版只接受既有 artifact，不自行網路搜尋；provider 擴搜必須回到 `unified_search` 建立新 run。
3. 將 metadata enrichment outcome 改為 typed success／empty／partial／failed，補 outage、timeout、bad DOI 與 contradictory metadata tests。
4. 建立 content-addressed full-text index manifest；document、parser、chunker、embedding 任一版本改變都產生新 revision。
5. 以 deterministic stub model 做 MCP acceptance，再以 opt-in live eval 檢查 citation entailment、unsupported claims、cost 與 latency。
6. 在公開文件標示 synthesis 是外接能力；核心搜尋輸出與 evidence audit 即使沒有 LLM key 也必須完整可用。
