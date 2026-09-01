# 60 個學術與文件檢索 Repository 候選

這是 **2026-09-01 UTC** 的初篩快照。每個項目都以官方 GitHub repository 為入口，檢查了可見原始碼、根目錄授權資訊、測試或 workflow 與主要能力。`★` 代表本輪另有逐 repo 深讀報告；它不是品質排名。授權欄是調查時 repository 的可見狀態，真正引用或移植前仍須重新核對檔案與依賴的授權。

## A. 直接學術搜尋或文獻管理 MCP（30）

| # | Repository | 語言／可見授權 | 值得檢查的設計 | 主要界線或風險 |
| ---: | --- | --- | --- | --- |
| 1 | ★ [`cyanheads/pubmed-mcp-server`](https://github.com/cyanheads/pubmed-mcp-server) | TypeScript／Apache-2.0 | typed error、全文分層 fallback、request queue、schema fuzz | provider orchestration 不宜留在 tool layer |
| 2 | [`ncukondo/pubmed-mcp`](https://github.com/ncukondo/pubmed-mcp) | TypeScript／package 標 MIT | cache、rate control、PubMed 基本面 | 未見對等根授權檔；需覆核發佈契約 |
| 3 | [`grll/pubmedmcp`](https://github.com/grll/pubmedmcp) | Python／MIT | 極薄 FastMCP adapter | 測試與失敗語意不足，較像最小範例 |
| 4 | [`andybrandt/mcp-simple-pubmed`](https://github.com/andybrandt/mcp-simple-pubmed) | Python／MIT | prompts、測試、簡潔工具面 | rate limit 與 resilience 尚非完整產品契約 |
| 5 | [`JackKuo666/PubMed-MCP-Server`](https://github.com/JackKuo666/PubMed-MCP-Server) | Python／MIT | 小型 PubMed MCP 入門 | 檔案少、測試與 domain boundary 弱 |
| 6 | [`BioContext/PubMed-MCP`](https://github.com/BioContext/PubMed-MCP) | 未形成可審原始碼／未標 | 需求與定位名稱 | 調查時幾乎只有 README，不可當實作依據 |
| 7 | [`Augmented-Nature/PubMed-MCP-Server`](https://github.com/Augmented-Nature/PubMed-MCP-Server) | TypeScript／自訂非商用 | 較廣 PubMed tool catalog | 授權限制與缺少測試；避免 tool explosion |
| 8 | [`openpharma-org/pubmed-mcp`](https://github.com/openpharma-org/pubmed-mcp) | JavaScript／MIT | 單一 multiplexed tool 的表面設計 | 一個 tool 內的 action 分派也可能隱藏複雜度 |
| 9 | ★ [`blazickjp/arxiv-mcp-server`](https://github.com/blazickjp/arxiv-mcp-server) | Python／Apache-2.0 | source artifact、outline、alerts、citation graph | arXiv 特化能力應成為搜尋後 adapter |
| 10 | [`openags/paper-search-mcp`](https://github.com/openags/paper-search-mcp) | Python／MIT | 多來源 adapter 廣度 | 全域協調與來源品質差異需要重新分層 |
| 11 | [`matsjfunke/paperclip`](https://github.com/matsjfunke/paperclip) | Python／MIT | 多學術來源的統一入口構想 | 已封存；只能作歷史設計參考 |
| 12 | [`benedict2310/Scientific-Papers-MCP`](https://github.com/benedict2310/Scientific-Papers-MCP) | TypeScript／package 標 MIT | 六來源整合 | 未見根授權檔且曾納入產物；供應鏈需審慎 |
| 13 | [`Dianel555/paper-search-mcp-nodejs`](https://github.com/Dianel555/paper-search-mcp-nodejs) | TypeScript／MIT | 多平台搜尋與格式統一 | `all` 策略與來源合規需覆核；不可依賴 Sci-Hub |
| 14 | [`Silung/scholar-search-mcp`](https://github.com/Silung/scholar-search-mcp) | Python／MIT | Semantic Scholar 與 arXiv 雙來源 | 去重、coverage 與部分失敗契約仍可加強 |
| 15 | [`afrise/academic-search-mcp-server`](https://github.com/afrise/academic-search-mcp-server) | Python／AGPL-3.0 | 無 key 的學術搜尋體驗 | copyleft 邊界與測試成熟度需評估 |
| 16 | [`xiuyechen/semantic-scholar-mcp`](https://github.com/xiuyechen/semantic-scholar-mcp) | Python／MIT | token bucket 與 Semantic Scholar adapter | 缺少足夠 contract tests |
| 17 | [`akapet00/semantic-scholar-mcp`](https://github.com/akapet00/semantic-scholar-mcp) | Python／MIT | session、export、cache、circuit breaker | 要避免把 persistence 與 presentation 綁死 |
| 18 | [`zongmin-yu/semantic-scholar-fastmcp-mcp-server`](https://github.com/zongmin-yu/semantic-scholar-fastmcp-mcp-server) | Python／MIT | 模組化服務、較廣工具與測試 | provider 工具數仍需對照 capability-first 表面 |
| 19 | [`JackKuo666/semanticscholar-MCP-Server`](https://github.com/JackKuo666/semanticscholar-MCP-Server) | Python／README 標 MIT | 簡易 Semantic Scholar 接法 | 未見對等根授權檔；產品 contract 偏薄 |
| 20 | ★ [`cyanheads/openalex-mcp-server`](https://github.com/cyanheads/openalex-mcp-server) | TypeScript／Apache-2.0 | entity search、fields 描述、budget telemetry | 不直接照搬 provider-specific tool catalog |
| 21 | ★ [`carsten-streb/openalex-mcp`](https://github.com/carsten-streb/openalex-mcp) | JavaScript／MIT | live contract、parity、stress、bundle smoke | server 為大型單檔；查詢 logging 有隱私風險 |
| 22 | [`SMABoundless/openalex-mcp-server-public`](https://github.com/SMABoundless/openalex-mcp-server-public) | Python／README 標 MIT | OpenAlex 薄 adapter | 未見對等根授權檔，測試面有限 |
| 23 | [`oksure/openalex-research-mcp`](https://github.com/oksure/openalex-research-mcp) | JavaScript／MIT | trends、presets、廣 OpenAlex 能力 | 工具過多；推論或可信度 gate 必須可解釋 |
| 24 | [`ResearchHubFoundation-Dev/openalex-mcp-server`](https://github.com/ResearchHubFoundation-Dev/openalex-mcp-server) | Python／MIT | OpenAlex FastMCP 基線 | 薄封裝，韌性與測試不足 |
| 25 | [`54yyyu/zotero-mcp`](https://github.com/54yyyu/zotero-mcp) | Python／MIT | local/web/hybrid、語意索引、library handoff | Zotero 是下游 library port，不是外部 discovery 核心 |
| 26 | [`cookjohn/zotero-mcp`](https://github.com/cookjohn/zotero-mcp) | TypeScript／MIT | Zotero plugin bridge | client/plugin 耦合與較大工具面需控制 |
| 27 | [`kujenga/zotero-mcp`](https://github.com/kujenga/zotero-mcp) | Python／MIT | 窄而清楚的 Zotero Web API adapter | 搜尋核心能力有限，適合 export/integration port |
| 28 | ★ [`genomoncology/biomcp`](https://github.com/genomoncology/biomcp) | Rust／MIT | capability planner、多來源狀態、entity pivots | 生醫實體功能應外接，不能稀釋 paper search 主軸 |
| 29 | [`wp-a/nature-academic-search`](https://github.com/wp-a/nature-academic-search) | Python／MIT | 多來源、provenance 與 verification ledger | 仍需驗證來源 coverage 與 ranking contract |
| 30 | [`45645678a/Scholar-mcp`](https://github.com/45645678a/Scholar-mcp) | Python／MIT | 多來源、去重、ranking、graph | Google Scholar scraping 與 Sci-Hub 有合規風險 |

## B. 鄰接學術搜尋核心（22）

這組不一定是 MCP server，但它們解決 identity、citation、systematic review、全文解析、evidence retrieval 與 reference management 等真正困難的問題。

| # | Repository | 語言／可見授權 | 值得檢查的設計 | 對本專案的合理位置 |
| ---: | --- | --- | --- | --- |
| 31 | ★ [`ourresearch/openalex-guts`](https://github.com/ourresearch/openalex-guts) | Python／MIT | source records 合成 canonical work、redirect | identity 與欄位級 merge 規則的 domain 參考 |
| 32 | [`opencitations/index`](https://github.com/opencitations/index) | Python、C++／ISC | citation tuple、provenance、RDF 與壓縮 pipeline | citation evidence ingestion adapter |
| 33 | ★ [`opencitations/oc_meta`](https://github.com/opencitations/oc_meta) | Python、RDF／ISC | curate、dedupe、merge history、PROV | evidence ledger 與可逆 identity merge |
| 34 | ★ [`LocalCitationNetwork/LocalCitationNetwork.github.io`](https://github.com/LocalCitationNetwork/LocalCitationNetwork.github.io) | JavaScript／GPL-3.0 | seed citation graph、年份層級、匯出來源 | research chronicle 的互動與資料語意參考 |
| 35 | [`allenai/S2AND`](https://github.com/allenai/S2AND) | Python、Rust／CC-BY-4.0 | author disambiguation | 選配 identity resolver；授權對 code 使用不典型 |
| 36 | [`allenai/s2orc-doc2json`](https://github.com/allenai/s2orc-doc2json) | Python／Apache-2.0 | 多 parser 正規化到共同文件 schema | full-text normalization adapter；版本與測試要自管 |
| 37 | ★ [`ASReview/asreview`](https://github.com/asreview/asreview) | Python、JavaScript／Apache-2.0 | active learning cycle、plugins、project migration | unified search 後的可重播 screening pipeline |
| 38 | [`mjwestgate/revtools`](https://github.com/mjwestgate/revtools) | R／GPL-3.0 | 文獻匯入、去重、主題探索與篩選 UI | systematic-review UX 與人工決策記錄參考 |
| 39 | [`elizagrames/litsearchr`](https://github.com/elizagrames/litsearchr) | R、Rcpp／GPL-3.0 | citation network 輔助關鍵詞生成 | query expansion 實驗，不直接自動改寫正式查詢 |
| 40 | [`datakind/permanent-colandr-back`](https://github.com/datakind/permanent-colandr-back) | Python／MIT | systematic review backend 與協作狀態 | 可選多人 screening service 參考 |
| 41 | [`prisma-flowdiagram/PRISMA2020`](https://github.com/prisma-flowdiagram/PRISMA2020) | R、Shiny／MIT | PRISMA 2020 flow data 與輸出 | 可稽核 search/screen counts 的 reporting adapter |
| 42 | ★ [`Future-House/paper-qa`](https://github.com/Future-House/paper-qa) | Python／Apache-2.0 | manifest index、MMR evidence、citation-grounded QA | optional synthesis pipeline，不藏進搜尋結果 |
| 43 | [`AkariAsai/OpenScholar`](https://github.com/AkariAsai/OpenScholar) | Python／Apache-2.0 | retrieval-augmented scholarly synthesis | 離線 eval 與 synthesis 研究，不作 provider of record |
| 44 | [`stanford-oval/storm`](https://github.com/stanford-oval/storm) | Python／MIT | 多階段研究與引用文章生成 | orchestration/pipeline 參考，需限制生成式事實風險 |
| 45 | [`grobidOrg/grobid`](https://github.com/grobidOrg/grobid) | Java／Apache-2.0 | PDF 結構、引用與 header 解析 | 外部 extractor service port，不嵌入搜尋 domain |
| 46 | [`sciunto-org/python-bibtexparser`](https://github.com/sciunto-org/python-bibtexparser) | Python／MIT | 容錯 BibTeX parsing 與資料模型 | import/export infrastructure adapter |
| 47 | [`citation-js/citation-js`](https://github.com/citation-js/citation-js) | JavaScript／MIT | 多 citation format plugin pipeline | website/client-side format conversion 參考 |
| 48 | [`manubot/manubot`](https://github.com/manubot/manubot) | Python／自訂，需覆核 | identifier-driven citation 與可重現 manuscript | citation normalization 概念；不可先假定授權相容 |
| 49 | [`zotero/zotero`](https://github.com/zotero/zotero) | JavaScript／AGPL-3.0 | 成熟 library、attachment、sync 與 translators 邊界 | 外部 reference-manager integration contract |
| 50 | [`zotero/translation-server`](https://github.com/zotero/translation-server) | JavaScript／AGPL-3.0 | translators 的 HTTP service 化 | optional metadata translation adapter |
| 51 | [`JabRef/jabref`](https://github.com/JabRef/jabref) | Java／MIT | bibliography domain、import/export、quality checks | 參考管理輸出與品質檢查設計 |
| 52 | [`metapub/metapub`](https://github.com/metapub/metapub) | Python／Apache-2.0 | PubMed/PMC identifier 與 metadata utilities | infrastructure 細節參考，不取代本案 domain model |

## C. 通用檢索與索引 adapter reserve（8）

這些專案技術成熟，但不具學術 provenance、provider coverage 或 citation semantics。只有在 corpus 規模、離線檢索或部署需求明確時才應接入。

| # | Repository | 語言／可見授權 | 可借鏡能力 | 不應成為核心的原因 |
| ---: | --- | --- | --- | --- |
| 53 | [`qdrant/mcp-server-qdrant`](https://github.com/qdrant/mcp-server-qdrant) | Python／Apache-2.0 | vector store MCP adapter 與 payload filters | 向量相似度不是學術檢索完整性或證據來源 |
| 54 | [`elastic/mcp-server-elasticsearch`](https://github.com/elastic/mcp-server-elasticsearch) | Rust／Apache-2.0 | production search transport、schema 與安全邊界 | 索引產品不提供 canonical scholarly semantics |
| 55 | [`opensearch-project/opensearch-mcp-server-py`](https://github.com/opensearch-project/opensearch-mcp-server-py) | Python／Apache-2.0 | OpenSearch MCP 與查詢治理 | 應藏在 retrieval port 後，不增加公開 provider tool |
| 56 | [`chroma-core/chroma-mcp`](https://github.com/chroma-core/chroma-mcp) | Python／Apache-2.0 | 小型向量 collection MCP | 缺少學術 identity、coverage 與 citation evidence |
| 57 | [`zilliztech/mcp-server-milvus`](https://github.com/zilliztech/mcp-server-milvus) | Python／Apache-2.0 | 大型 vector database adapter | 運維成本高，且不是 discovery provider |
| 58 | [`deepset-ai/haystack`](https://github.com/deepset-ai/haystack) | Python／Apache-2.0 | component pipeline、retriever/ranker ports | 可借鏡 composition，不應平行重建現有 application layer |
| 59 | [`run-llama/llama_index`](https://github.com/run-llama/llama_index) | Python／MIT | connector/index/query abstractions | surface 過廣；學術契約仍須由本案掌握 |
| 60 | [`microsoft/graphrag`](https://github.com/microsoft/graphrag) | Python／MIT | graph extraction 與分層 retrieval | 生成出的 graph 不能冒充 observed citation graph |

## 初篩後的方向

1. 優先吸收「可證明搜尋做了什麼」：來源能力、查詢計畫、coverage、部分失敗、identifier/merge evidence、引用邊 provenance。
2. 其次吸收「搜尋後仍能重播」：artifact manifest、stable section ID、screening state、cursor、export metadata。
3. 最後才接通用 index、RAG 與生成；這些一律是可關閉、可替換、明示來源的 extension。

具體取捨與分期見 [`recommended-direction.md`](recommended-direction.md)。
