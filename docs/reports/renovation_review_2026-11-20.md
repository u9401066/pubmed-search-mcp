# PubMed Search MCP 翻新審查・第一輪

2026-11-20，以已發布的 v0.8.0、commit `d8ddc6a0fa9e87a5c9bbc25fa5a496223192eec3` 為基線。本輪考察策略重用、從 Chronicle 辨認值得追蹤的方向，以及多站點部署。容量試驗假設有 3–5 套部署，每套有 100–300 位使用者；實際併發量另行量測。本輪完成程式追查、Windows 定向回歸、合成分支對照與既有論文證據審讀。[正式版本](https://github.com/u9401066/pubmed-search-mcp/releases/tag/v0.8.0) · [九月核心審查](core_review_2026-09-15.md) · [既有外部工具比較](../reference-repositories/README.md)

## 1. Chronicle 的「新分支」從哪裡來？

現在的工具從 MeSH 與作者關鍵詞取訊號，每個主題分支至少要有兩筆主要事件；至少形成兩個分支且覆蓋達 60% 才採主題分類，否則退回研究階段分類。它會記錄次要歸屬、重疊、未歸類事件及使用的分類方式。兩個 revision 的差異由分支 ID、事件、證據和輸入範圍各自比較。這些都是可供判讀的觀察值。[分支規則](../../src/pubmed_search/application/chronicle/lineage.py) · [版本比較](../../src/pubmed_search/application/chronicle/differ.py)

**本輪離線實驗。** 輸入是合成的復健研究資料。六筆事件的年份為 2017–2022，前兩筆的關鍵詞是 `Balance training`，中間兩筆是 `Gait analysis`，末兩筆無關鍵詞。主題、查詢範圍與第一版固定，三組各自與同一第一版比較。透過實際的 `build_chronicle_lineage`、`assemble_chronicle`、`diff_chronicles` 執行，未向外部資料庫查詢。

| 第二版唯一改動 | 新增分支 | 新增文獻識別碼數 | scope_changed |
| --- | --- | ---: | --- |
| 原樣重建 | 無 | 0 | false |
| 在原本無詞的兩篇舊文獻補上 `Home monitoring` | Home monitoring | 0 | false |
| 保留原有六篇，加入 2025、2026 各一篇帶該詞的新文獻 | Home monitoring | 2 | false |

第二組的兩筆事件改了歸屬，原有的 `Cross-cutting / Other` 也退出這次分支清單。同一個分支名稱可以讓研究者發現過去忽略的工作，也可以帶來近期研究進展，但兩者適合的後續行動不同。這個實驗辨認出提醒需要附帶的證據；真實領域中的誤報率與有用程度仍待量測。

**下一輪的設計提案。** 先沿用現有 diff。對每個候選呈現「這次新增了哪些文獻、哪些舊紀錄改了歸屬、最早可觀察的日期、檢索範圍及覆蓋是否改變、來源是否截斷或失效」，並連回兩版 evidence ID。新收錄的舊文獻要同時顯示發表時間與本系統首次觀察時間。日期或變動原因未知時保留未知。研究者或上層 agent 決定另開追蹤、併入既有主題或暫緩。維護者提到的「JEV-like」暫留為待討論的決策模型；可先比較具名規則與單純分支差異，有增益再決定模型與實作位置。

**怎樣驗收。** 第一階段取一個熟悉主題，如原有 remimazolam 案例，以及一個不同主題，先做小規模方法試驗。固定兩個時間截點、候選資料和每題可檢閱的提醒數。兩位領域研究者先獨立閱讀相同證據，記錄值得另開或併入的方向，再盲看不同方法的提醒。記錄固定提醒數內被採用幾條、漏掉多少已標記方向、判讀耗時與評閱者分歧。加入無變化、補標、提高檢索上限、來源暫時缺失等對照。回看歷史時，MeSH、引用數及引用邊也要符合當時可得資訊；缺少歷史版本的欄位應遮蔽或改做前瞻快照。若要衡量一條線索日後是否持續發展，另留第三個時間點。既有 remimazolam 報告是 v0.6.4 的單題功能案例。[歷史案例](research_chronicle_remimazolam_evaluation_report.md) · [NLM 歷史與更新檔](https://pubmed.ncbi.nlm.nih.gov/download/)

## 2. 統合分析前端已有什麼？何處值得擴充？

**已實測。** 命名策略可保存、載入、執行並留下歷史與報告。排程能比較前次成功 run，且有部分失敗處理。這次另跑 12 個案例，全部通過，涵蓋命名策略往返、以保存名稱產生報告、排程差異與通知、安裝版 stdio 程序重啟，以及 `snowball` inline／儲存後執行的四種組合。檢索結果與引文擴展使用受控輸入，安裝版測試則確實重啟程序。[策略重用](../../tests/test_pipeline_report_save.py) · [引文擴展](../../tests/test_pipeline.py) · [排程](../../tests/test_pipeline_scheduler.py) · [安裝版重啟](../../tests/test_release_transport_smoke.py)

**值得擴充的驗收案例。** 同名策略先執行 v1，再修改條件執行 v2。請接手者只拿 v1 的 run ID，交出當時展開的完整策略、各來源實際查詢、限制、日期、去重後去向及部分失敗原因，再重現凍結資料上的候選集。現行同名 YAML 可覆寫，`PipelineMeta.config_hash` 指向現有設定，`PipelineRun` 沒有保存展開版本；MCP journal 對 `saved:名稱` 計算的 hash 也只涵蓋傳入字串。另一個明確差距是 saved-run 差異集合取自 PMID。可在 v2 中加入一篇僅有 DOI 的報告及一筆試驗登錄，再對照每筆輸出的身分及處置。正式回顧還需處理同一研究的多篇報告。[策略儲存](../../src/pubmed_search/application/pipeline/store.py) · [run 模型](../../src/pubmed_search/domain/entities/pipeline.py) · [異動識別](../../src/pubmed_search/application/pipeline/runner.py) · [journal](../../src/pubmed_search/presentation/mcp_server/tools/search_run_journal.py)

`systematic` 模式現支援 OpenAlex 與 Semantic Scholar，每個來源上限 100；明確指定 PubMed 加此模式會在查詢前被拒。PubMed 可另走 keyword 策略。正式回顧應按題目列明必查資料庫、未能取得的來源、檢索日期／完整語法、截斷與補搜，再由資訊專家用 PRESS 審策略、用 PRISMA-S 查報告完整度。[來源合約](../architecture/SOURCE_CONTRACTS.md) · [PRESS](https://doi.org/10.1016/j.jclinepi.2016.01.021) · [PRISMA-S](https://www.prisma-statement.org/prisma-search) · [Cochrane 檢索方法](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-04)

若要研究引文擴展的附加價值，可用 Wang 等人的 40 個回顧主題，對照原始 Boolean 策略及加入前後向引文的版本。在同一截止日、候選庫、篩讀量與來源呼叫預算下，逐回顧計算找回多少**原納入且非種子**的報告，以及多帶來多少待篩紀錄。預先說明當時可索引分母，另報不可取得者。先分清人工已知種子與 `snowball` 由查詢取前幾篇作種子的差異，兩種流程分開評估。[作者資料集及程式](https://github.com/ielab/sysrev-seed-collection/tree/3d4e36ee6697cb4825e691c51ff062a9ab88c644) · [原始論文](https://doi.org/10.1145/3477495.3531748)

**EBM 的另一個驗收單位是「一項結果」。** PICO、文獻類型、引用核對與筆記匯出可協助整理候選資料。以一個 PICO 的一項 outcome 取樣，讓兩位評閱者從輸出的陳述回查原研究、比較組、段落或表格，分別標支持、矛盾、資訊不足或無法取得。若進一步提供效果量或確定性評讀，必須連回資料擷取和偏差風險判斷。引用數、出版類型或 bibliography match 各自能回答的問題比這個窄。[PICO 計畫](../../src/pubmed_search/application/search/pico_plan.py) · [參考文獻核對](../../src/pubmed_search/application/reference_verification/service.py) · [Cochrane 結果層級評讀](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-14)

## 3. 架構、套件、擴充與維運的驗收表

| 面向 | v0.8.0 目前的證據 | 下一輪用來做決定的工作 |
| --- | --- | --- |
| 核心與入口 | Python SDK 與 MCP 一般搜尋共用 `UnifiedSearchUseCase`。MCP 加入 journal、呈現與 artifacts。傳入 pipeline 另走 DAG 路徑。 | 固定輸入比較三條路徑的識別碼、實際查詢、截斷和部分失敗。標出各自承諾的欄位，再決定應共享哪段 application 邏輯。[呼叫圖](../architecture/UNIFIED_SEARCH_ARCHITECTURE.md) |
| 加入資料來源 | registry 宣告能力，broker 的靜態對照表接上 adapter。部分 port 仍接受 `Any`。 | 用一個模擬來源記錄必須改哪些檔、能否傳遞額度／續頁／缺憑證／來源異常。依改動成本決定要不要提供第三方 provider 介面。[registry](../../src/pubmed_search/infrastructure/sources/registry.py) · [broker](../../src/pubmed_search/infrastructure/sources/unified_broker.py) |
| 通用 agent plugin | 已有固定版本的 stdio launcher、11 個 skills，以及 wheel 與 MCP protocol 的 smoke。 | 以兩個實際 host 的新設定，各自測「安裝 → 發現並觸發適當 skill → 搜尋 → 重開後讀回 artifact」。記錄 host、版本、設定差異和人工步驟。[plugin](../../plugins/pubmed-search/plugin.json) · [安裝測試](../../tests/test_release_transport_smoke.py) |
| 套件 | FastAPI 屬基本依賴，產品碼的直接使用點在 browser broker。兩個 HTTP 入口直接 import uvicorn，安裝則依賴間接相依；Playwright 已有獨立 extra。 | 對 stdio、HTTP service、browser broker 的乾淨 wheel 安裝量大小、啟動時間、必要依賴及支援的 Python 版本。依證據決定直接宣告、保留或移入 extra。[套件清單](../../pyproject.toml) · [HTTP](../../src/pubmed_search/presentation/mcp_server/http_cli.py) · [broker](../../src/pubmed_search/presentation/browser_fetch_broker.py) |
| 恢復與多人使用 | 有 tenant 目錄、principal 隔離和中斷標記。`replay_search` 可取回參數以開新 run。Chronicle revision 有檔鎖；服務 Compose 固定一副本，停用排程。 | 同站兩人、同一 principal 兩個專案交錯執行，驗證 `last` 的歸屬及明確 run ID 的回查。分別量讀舊證據、整次重跑、步驟／頁面續作的成本。最後一項是待評估需求。[部署契約](../../DEPLOYMENT.md) · [搜尋恢復](../architecture/SOURCE_CONTRACTS.md) |

**3–5 套部署的第一個維運試驗。** 先將每套視作一個獨立站點、一個程序與自己的持久化空間，這是待驗證的拓樸假設。每站 100–300 是使用人數；尖峰同時到達的研究工作數、每項工作呼叫多少 provider、各站是否共用上游 key 或出口，才決定容量。先在一站的 HTTP 入口以本地 provider fixture 混合短查、pipeline、讀 artifact，在 1、4、8、16、32 個在途任務記完成率、p95 等待、每工作外部呼叫、429／重試、記憶體與磁碟，再用試營運的工作量校準。合成 100／300 個 principal 先後使用可另量常駐狀態成本。這些並行數是測點，服務能力仍待量測。[單站配置](../../docker-compose.service.yml) · [既有離線延遲量測](search_execution_2026-09-18.md)

初期最值得維護者做的一次演練，是從備份開乾淨的程序，請同事用原 run ID 找回策略、文獻、Chronicle revision 和附件。分同路徑還原及搬到新路徑兩次，核對 checksum、資料遺失時間範圍與恢復耗時。現有 artifact manifest 含實體路徑，重啟能讀回與異機搬遷須各自驗收。若瓶頸是共同上游配額，增加站內 worker 無助於增加該配額；若瓶頸是單站持久化或確實有跨站接手需求，再討論共享儲存、工作佇列與排程協調。[ArtifactStore](../../src/pubmed_search/application/session/artifacts.py)

## 4. 品質與可重現性紀錄

Windows、Python 3.12.12、專案的 `uv.lock`。第一次選七個檔案，175 passed、2 failed。plugin 測試檢出四份檔案位元組不一致，逐行文字相符；本機 `core.autocrlf=true`。另一例在建立測試所需的目錄 symlink 時收到 WinError 1314，該環境未執行到 Chronicle 的安全斷言。另跑上一節所述的 pipeline／安裝測試，8 passed，再跑 snowball 的四種組合，4 passed。這是定向回歸，沒有執行全套或 live providers。

```text
uv run --frozen pytest -q tests/test_agent_plugin_package.py tests/test_multi_tenant_deployment.py tests/test_search_run_history.py tests/test_unified_pipeline_recovery.py tests/test_chronicle_revision_integrity.py tests/test_pico_plan.py tests/test_source_adapter_failure_contracts.py
uv run --frozen pytest -q tests/test_pipeline_tools.py::TestToolsIntegration::test_save_and_load_roundtrip tests/test_pipeline_report_save.py::TestAutoSavePipelineReport::test_execute_saved_template_pipeline_records_run_under_saved_name tests/test_pipeline_runner.py::TestStoredPipelineRunner::test_saved_report_diff_lists_changes_with_bounded_new_articles tests/test_pipeline_scheduler.py::TestAPSPipelineScheduler::test_real_scheduled_runs_persist_safe_notifications_and_reset_when_disabled tests/test_release_transport_smoke.py::test_installed_stdio_persists_across_restart_and_isolates_data_roots
uv run --frozen pytest -q tests/test_pipeline.py::test_snowball_template_runs_inline_and_saved
```

**出版前檢查有同一個換行問題。** 現有工作樹五份歷史 JSON 的 SHA-256 與 manifest 相符 0/5。直接取同一 commit 的 Git blob 則相符 5/5。將建置輸入按 Git 原始位元組寫到臨時目錄，`build_agent_plugin.py --check` 與 `build_publication.py --prepare-only` 皆成功；目前工作樹的相同檢查皆失敗。建議第一個小修以乾淨 Windows 與 Linux checkout 驗證相同輸入位元組，保留歷史雜湊。上述 preflight 只產生論文來源，未編譯 PDF。[建置器](../../scripts/build_publication.py) · [證據雜湊](../publication/evidence.json) · [plugin 同步器](../../scripts/build_agent_plugin.py)

## 5. 學術主張、引用與公開順序

目前最能寫清楚的是「agent 如何取得可追溯的生醫檢索證據，以及研究者如何接手」。BioMCP 已做多來源生醫資料存取，ASReview 已針對候選集進行篩選。對本專案，較有辨識度且可反駁的主張，是有版本的證據與提醒原因能否提高**研究者採用線索的比例**，或降低**接手並複核查詢的成本**。一篇研究先選一個主要終點。[BioMCP](https://github.com/genomoncology/biomcp) · [ASReview](https://asreview.nl/) · [既有主張對照表](../publication/evidence.md)

現有 TeX 稿及證據表以 v0.7.4 時期為背景。歷史 NFCorpus 的詞彙排序 test nDCG@10 從 0.293357 到 0.297831，recall@100 的配對區間跨零。三題 agent 先導中，原生搜尋與加本套件兩組各有 2/3 答案完全相符、1/3 命中來源 PMID。這些結果不能估計整套 plugin 的增益。原生／舊版／現版三組控制方案尚待預先登錄和正式執行；若採用它，必須固定 host、模型、語料和底層呼叫／閱讀預算，失敗保留在分母。[原稿與結果範圍](../publication/README.md) · [控制方案](../publication/evaluation-protocol.md)

| 被引用的對象 | 作者或重跑者應取得的資訊 |
| --- | --- |
| 軟體 | **Gau, T.-P. (2026). PubMed Search MCP (v0.8.0) [Computer software].** 隨研究記錄使用的 commit。CFF 目前提供軟體作者、版本、日期與 repo，待版本封存取得 DOI 後再補。論文識別碼另記。[CITATION.cff](../../CITATION.cff) · [release](https://github.com/u9401066/pubmed-search-mcp/releases/tag/v0.8.0) · [軟體引用原則](https://doi.org/10.7717/peerj-cs.86) |
| 實驗與資料 | 每項數字連回同版 protocol、資料版本／授權、時間截點、模型與 host、provider、參數、run 與原始輸出雜湊。引用資料集作者及原始方法，BM25、RRF、MMR 各歸原作者。現有 PaperSearchQA 書目採 preprint，可在修稿時補 EACL 正式出版資料。[現有書目核對](../publication/references-review.md) · [EACL 原文](https://aclanthology.org/2026.eacl-long.88/) |
| 研究結果中的陳述 | 附原始文獻身分、DOI／PMID、全文段落／表格或摘要位置、支持關係與複核狀態。對外釋出的重現包可保存識別碼與允許散布的證據，不宜假設取回全文即有再散布權。[現有證據核對方案](../publication/evaluation-protocol.md) |

**建議公開順序。** v0.8.0 已公開，repo 也已有可讀的工作稿。先讓現有稿清楚標明各結果的歷史版本，修完跨平台 preflight，與作者確認主要問題、署名與草稿狀態，再將方法／protocol 以有日期的公開草稿供評論。若要做驗證性研究，在看正式組間結果前登錄終點、樣本與分析。軟體可獨立封存並取得版本 DOI；下一個軟體 release 隨實際相容性變更決定。面向成效的論文等評估完成再報告，包括零差異或退步。[出版工作區](../publication/README.md) · [Zenodo 軟體封存](https://help.zenodo.org/docs/github/)

## 6. 多輪工作與決策

| 輪次 | 可交付的結果 | 要共同作的決定 |
| --- | --- | --- |
| 1・本輪 | 版本基線、實測紀錄、分支出現的兩種成因、能力及證據缺口 | 暫以 Chronicle 的候選提醒作第一個研究驗收，pipeline 以已驗證的重用能力為基線 |
| 2・產品與方法 | 用兩個主題寫出真實任務、候選提醒範例、負對照與評閱表。另做一次同名 pipeline 改版後的歷史策略還原 | 提醒限額與採用條件；補標造成的新連結是否值得提醒；接手需要哪一層恢復 |
| 3・工程與維運 | 一個模擬 provider、兩個 host 的 plugin 驗收、套件安裝量測、單站併發與備份還原紀錄 | 哪些責任放核心、轉接層或可選模組；哪些問題已足以支持架構變更 |
| 4・實作與驗證 | 只實作前輪採用的變更，在凍結案例重跑基線與改版，整理相容性、成本與失敗情境 | 哪些功能保留、改善、試驗性提供或退場；草稿可以支持哪個主張 |
| 5・研究與發布 | 版本化方法草稿、作者確認的引用、預先登錄及後續成效結果、可重跑的研究材料 | 分別決定草稿、軟體版與結果論文的公開時機 |

每輪以同一組問題收尾：誰用它做了哪個決定、目前依據是程式或真實使用、什麼觀察會改變我們的判斷、下一輪最便宜且具辨識力的驗證是什麼。下一輪首先需要的是研究者對「值得再開一條追蹤」的具體例子。
