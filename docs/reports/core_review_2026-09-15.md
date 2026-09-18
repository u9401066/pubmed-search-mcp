# 核心程式全量審查：分階段計畫與進度

後續 [v0.7.4 排程與上游保護複查](release_v074_2026-09-18.md)
更新目前清冊與變更審查；本文以下保留 v0.7.3 完成時的歷史分母。

**十個階段已依序完成。** 最終核心為 **223 個 Python 檔案、456 個 class、
2,445 個 function／method／nested function，共 2,901 個定義**。
每項都有自審理由、證據與有效檔案 SHA-256；核心 pending、follow_up、stale_review、
orphan 均為 0。`--require-reviewed src/` 已實際通過。
下方階段表保留起始分母，最終驗收與範圍限制見文末。

## 範圍與基準

依 2026-09-15 的接續要求，核心範圍固定為 **整個 `src/pubmed_search/`**，
起始 222 個 Python 檔案、456 個 class、2,432 個 function/method/nested function，
合計 **2,888 個定義**。包含 wrapper、資料模型、尚未接線的 adapter 與評測支援模組。
測試與 scripts 是驗證證據；本計畫不把它們的全部定義混入核心完成率。

沿用 [symbol inventory](../../scripts/perf/symbol_inventory.py) 與
[逐項審查帳本](code_review_ledger.json)。先前的
[翻新報告](renovation_plan_2026-09-15.md)為歷史快照，不覆寫其測量結果。
本輪新增、移除或修改的定義也必須納入最終清冊，不能凍結分母以掩蓋新程式。

## 階段與順序

以下是起始分配，每個 source 檔案恰好歸屬一個階段。

| 階段 | 範圍 | 檔案 | 定義 | 狀態 |
| --- | --- | ---: | ---: | --- |
| 1 | `shared/`：快取、async、併發、來源契約、設定與安全工具 | 15 | 235 | 已審查、修正與驗證 |
| 2 | `domain/`：識別碼、文章／引用／圖像／時間軸／pipeline 模型與 mapper | 15 | 191 | 已完成；本輪新增後共 195 定義 |
| 3 | `application/search/`、`application/unified/`：查詢、合併、排序與來源執行 | 22 | 251 | 已完成；本輪新增後共 256 定義 |
| 4 | `application/session/`、`application/pipeline/`、`infrastructure/cache/`、`infrastructure/scheduling/` | 21 | 375 | 已完成；本輪新增後共 378 定義 |
| 5 | `application/fulltext/`、`reference_verification/`、`citation_network/`、`visualization/` | 9 | 155 | 已完成；新增後共 156 定義 |
| 6 | `application/chronicle/`、`timeline/`、`export/` | 27 | 303 | 已完成；合併後共 300 定義 |
| 7 | `infrastructure/http/`、`auth/`、`ncbi/`、`pubtator/` | 18 | 174 | 已完成；合併後共 176 定義 |
| 8 | `infrastructure/sources/`、`application/image_search/` | 40 | 705 | 已完成；合併後共 703 定義 |
| 9 | `presentation/`：41 工具、transport、schema、browser broker 與多租戶邊界 | 45 | 433 | 已完成；目前 434 定義，另登錄 application fallback |
| 10 | source 根目錄、application package 根目錄、infrastructure package 根目錄與 `infrastructure/evaluation/` | 10 | 66 | 已完成；新增共同驗證方法後 67 定義 |
| 合計 | 全部 source | 222 | 2,888 | 已完成；最終 223 檔／2,901 定義 |

每階段按完整檔案切成可驗證的小批次，不按函式行數或測試覆蓋率決定結案。
第 10 階段後執行跨模組複查與全套本機驗收；若修改了已審檔案，回到該階段重新檢查差異。

## 每個定義的審查要求

1. 讀取實作、相關資料契約與呼叫端，確認功能必要性及 DDD 責任歸屬。
2. 檢查空值／非法輸入、排序與去重、來源錯誤／部分結果、取消／timeout、
   共享可變狀態、持久化與重放、租戶隔離及敏感資訊處理等適用條件。
3. 對重複程式比較實際契約；確認語意一致後才合併。對僅被測試引用的程式先查公開用途。
4. 在帳本逐一定義寫下 retain／changed 或待解問題、理由與證據。
   不從函式名稱、AST 成功、lint 成功或 test pass 批量推導已審結論。
5. 發現行為錯誤先重現，再修正根因；新增最少且有判別力的回歸測試。
   宣告／單純轉呼叫可用既有契約與消費端證據，不為每個定義添加鏡像測試。

## 各階段完成與最終驗收

- 階段內每個目前存在的定義都有有效檔案雜湊、逐項理由與可定位的證據。
- 已發現問題完成修正，或有經程式契約確認的保留理由；未結案項目維持 follow_up。
- 修改先跑最小相關驗證；跨模組行為修改後跑完整本機 gate，避免每個小改動重跑全套。
- 最終 `uv run python scripts/perf/symbol_inventory.py --require-reviewed src/`
  必須成功，且 source 沒有 pending、follow_up、stale_review 或 orphan。
- 最終 `uv run --frozen python scripts/check_repo.py full` 與 smoke 通過，
  保留 source stdio、HTTP、fresh-wheel 的完整 41 工具 acceptance。
- 只在需要時增加平台／圖形驗證；不以本機成功冒充 Docker、其他 OS 或 live API 成功。
- 文件與 MEM 記錄可接續進度；不啟動未授權的 5,000 題模型長跑，也不在本輪改寫使用者 harness。

## 執行紀錄

- 開始時 source 帳本為 16 reviewed、4 follow_up、2,868 pending。
- 第一階段 15 檔的 **235 個定義全部有逐項審查理由與證據**；
  `--require-reviewed src/pubmed_search/shared/` 實際成功。沒有用測試結果自動產生審查理由。
- 已用程式核對十階段的分配互斥且完整，合計仍為 222 檔／2,888 個定義。
- 第 2 階段完成時核心帳本：**444 reviewed、4 follow_up、2,444 pending**，共 2,892 定義，完成率 **15.35%**。
  第二階段新增 4 個 helper；先前 2 個 domain 定義已重新審查。
  全核心完成斷言仍應失敗，其他階段沒有被批量標記完成。

### 第一階段修正與驗證

| 發現 | 處理與驗證 |
| --- | --- |
| 磁碟快取中的錯誤／空白到期時間可使讀取或列舉失敗 | 載入 envelope 時驗證日期；損壞項目被獨立略過，其他文章仍可讀取 |
| 磁碟 reload 未遵守 max_entries，負容量寫入會崩潰 | 重新載入也套用容量；建構時拒絕負值，0 仍允許作為零容量 cache |
| JSON cache 重用固定 `.tmp` 名稱，會覆寫其他寫入者的暫存資料 | 改用既有 unique-temp／fsync／atomic replace helper；不新增另一套寫檔工具 |
| 總 timeout 未涵蓋 concurrency slot 與 cooldown lock 等待 | 共用同一 monotonic deadline；驗證等待逾時與名額正確釋放 |
| 已逾時時可能先建立未 await 的 coroutine | budget helper 改收 factory，確認剩餘時間後才建立 awaitable |
| 非有限 Retry-After、無效限速更新會污染後續執行 | 拒絕非有限延遲；constructor／reconfigure／共享限速查詢共用正數與有限值驗證 |
| 呼叫端取消被當成 upstream 故障，half-open probe 名額無法釋放 | cancellation 不記失敗並歸還 probe；修正 monotonic 0 的恢復判斷 |
| 負 batch_size 可回傳空成功，漏掉整批工作 | 明確拒絕非正 batch size |
| 空 Authorization 值形成空 secret，讓每個字元前後插入 REDACTED | extraction 與 recursive redaction 都排除空值／純空白值 |
| Retry-After 0 在 JSON／文字／重試建議中被丟掉 | 以 None 區分未提供；保留即時重試的 0 秒值 |
| NCBI API key validator 與 optional-string validator 重複；錯誤類別手動抄 context 欄位 | 合併同語意 validator；以 dataclasses.replace 保留未修改 context 欄位 |

20 個新案例曾在修正前實際失敗；另補上 2 個 batch-size 回歸案例。
保留既有取消、來源錯誤、隱私、租戶隔離及完整 MCP 契約驗證；未替每個宣告新增鏡像測試。

- 第一批相關驗證：318 passed；後續錯誤指引與 context 整理也已納入完整 gate。
- **完整本機 gate：4,598 passed、23 skipped、30 deselected，pytest 104.68 秒。**
  Ruff、格式、async consistency 與 mypy 同時通過。
- **Smoke：165 passed，13.61 秒。** Full 與 smoke 均保留全部 41 工具的
  stdio／HTTP／fresh-wheel acceptance。
- DDD、vulture、Bandit 與 diff whitespace 檢查通過。
- `--require-reviewed src/pubmed_search/shared/` 回傳 0；
  `--require-reviewed src/` 回傳 1，正確反映其他階段仍未完成。
- 程式 snapshot SHA-256：`c2347eeda8ee9c484c0de3337b7a83380817ebaef3dea3623c9bd63f5ac787db`。

快取檔仍是單一 owner 的 best-effort cache，atomic replace 不代表多程序交易式合併。
async timeout 仍依賴 cooperative cancellation；這次修正讓等待階段計入 budget，
不宣稱可以強制停止任意拒絕取消的第三方程式。

### 第二階段修正與驗證

15 個 domain 檔案已全部閱讀（含 4 個沒有定義的 package export 檔），
195 個目前存在的定義逐項記錄理由與證據；`--require-reviewed src/pubmed_search/domain/` 通過。

- 作者：字串先判型別，避免名稱包含 `family`／`display_name` 時走錯 provider 分支；接受空 affiliation。
- 來源 mapper：共用作者解析；合併同語意的 Scopus／WoS mapping，保留原本 Python 入口與來源標記。
- 引用指標：六個來源保留零次引用；合併時保留有效的零值，複製 metric 物件避免修改 donor。
- PubMed 類型：特定 RCT／review 類型優先於一般 Journal Article，避免排名誤分類。
- Crossref：空 title／null 作者與日期不再使 mapping 失敗；一般 PDF/TDM 連結保留於 raw provenance，
  不再自動宣稱 OA。[Crossref 官方文件](https://www.crossref.org/documentation/retrieve-metadata/text-and-data-mining/)
  說明這些 URL 可能仍需要訂閱或登入。
- APA 文字引用：20 位以內保留全部作者；超過時選前 19 位及真正最後一位，修正作者／年份重複句點。
  參考 [University of Portsmouth 引用指南](https://library.port.ac.uk/using-resources/referencing/apa/journal-articles)；
  APA 官方網站在本環境只回傳 iframe，未宣稱成功讀取其內文。
- Timeline：HTML 文字跳脫；Mermaid topic／label 換行與 directive 分隔字元無法新增 diagram 語法。
- Research tree：以單一遞迴流程替代三段重複事件輸出，恢復 Unicode 樹枝符號並保留第三層以上分支。
- Chronicle：完整 title fallback ID 避免長標題前 80 字相同時遺失證據；修正 frozen/persisted 語意文件。
- 日期／DOI：decimal 檢查避免 Unicode superscript 造成 int 例外；拒絕含空 userinfo 的 DOI URL。

本輪 17 個案例在修正前實際失敗（其中 2 個為修正既有錯誤 APA 斷言）；
長標題 identity 與其他小修也納入既有整合驗證，不把它們宣稱為全部 red-first。

- 相關驗證：401 passed。
- 完整本機 gate：**4,613 passed、23 skipped、30 deselected，103.87 秒**；lint、format、async、mypy 通過。
  初次 gate 抓到 `str.maketrans` 型別不相容，已改成明確型別的共用 translation table 後重跑成功。
- Mermaid：一般／含惡意文字的兩個 timeline 實際由 Mermaid 11.16.1 渲染為 SVG。
- Source 新增 4 個定義，分母從 2,888 更新為 2,892，沒有為了完成率固定舊分母。

### 第三階段修正與驗證

22 個檔案與 256 個定義全部閱讀並逐項記錄；search／unified completion gate 通過。
目前核心共 2,897 定義：700 reviewed、4 follow_up、2,193 pending（24.16%）。

- ICD 採單次完整 code 取代，避免重複展開或短 code 破壞長 code；跨來源使用各自支援語法。
- 保留明示來源排除；auto fallback 不把 PubMed 欄位查詢送往不支援來源。
- 前景流程失敗／取消時終止 ClinicalTrials 背景工作；有界等待及 late-exception 回收不依賴 parent task 結束。
- 查詢分析保留 citation tracking／systematic 意圖，避免 `or` 字串誤判；分離 PMC／DOI／PMID 範圍，年份不從 DOI 提取。
- 去重拒絕整個 component 的識別碼衝突；排名保留相同 canonical key 的衝突紀錄，零權重維度不能打破排序平手。
- 合併重複 weighted fallback，移除空 constructor、死掉的 entity import cache、重複 enum validation。
- MMR 拒絕非法／非有限分數和權重；零上限有效；影響力分數不受負值／NaN 污染。
- MeSH constraint 保留完整 Boolean 原查詢，避免產生 `(AND)`；短實體詞不匹配其他詞的子字串。
- provider totals 僅接受非負 ASCII 整數，錯誤診斷不回傳 raw payload。
- reproducibility 明確標為 heuristic／local algorithm scope；回應來源不重複計數、不計入未查來源。
- 保留既有明示 heuristic PICO／relaxation／publication-quality policy，未把它們當成臨床判定或實測 benchmark。

11 個新案例先實際失敗後修正，另重現 MeSH Boolean 破壞；其他修正以既有與新增行為驗證覆蓋。
移除一個只斷言內部 merge mock 被呼叫的冗餘測試；修正舊測試中互相衝突的文章 fixture 與錯誤意圖斷言。

- 最終完整本機 gate：**4,634 passed、23 skipped、30 deselected，104.66 秒**；lint、format、async、mypy 通過。
- 不啟動模型長跑，不宣稱已測得 harness 的 A/B 增益。

### 第四階段修正與驗證

21 檔／378 定義已完整閱讀並逐項記錄；session、pipeline、cache、scheduling gate 通過。
本輪新增 3 個定義，核心分母更新為 2,900；1,074 reviewed、2 follow_up、1,824 pending（37.03%）。

- 合併 warm／add article cache bookkeeping，保留不同事件與 `_skip_save`；兩項原先 follow_up 結案。
- Artifact 檔名改完整比對、保留 manifest.json；逃逸 symlink 不再中斷整批 recovery。
- 移除 artifact lookup 的 10,000 筆 cutoff；query-only cache 不重用 filtered／partial／source-constrained 搜尋。
- Deep artifact 保留 status／allocation／physical query／實際執行旗標，skipped 不再被誤報為 executed；未知預期數量不宣稱 audit pass。
- Pipeline 取消／abort 均清理所持有 tasks，取消等待有界；分支輸入複製避免 metrics／merge 修改另一分支。
- on_error: abort 同時處理 StepResult 與 exception；拒絕非有限 deadline、非法 output/on_error 與 self dependency。
- 交集保留有效空集合與穩定順序；details 合併上游 PMID 時去除合法重複；RRF 遇強 ID 衝突明確失敗。
- Domain 交叉複查發現 `matches_identifier` 仍可能在 DOI 相同時提前返回；改檢查所有共同 namespace，重新核對檔案 hash 與受影響呼叫端。
- comprehensive／gene_drug 移除不存在的 mesh strategy selector，按來源選可用策略；防止 PubMed syntax 傳到其他來源。
- Pipeline config hash 納入 output 與 on_error；load 偵測手改 YAML，重寫同一 run 不增加執行次數；diff 以最近完整 run 為基準。
- Schedule completion 以 store transaction 更新狀態，取消排程後不被跑完的 job 重建，保留並發設定修改；沿用儲存的 timezone。
- 報告顯示 partial outcome／source warning，移除僅憑 publication type 給 evidence grade，以及 IF≈ 的錯誤標示。

13 個案例先重現失敗再修正；其他修正與既有行為一起驗證。舊測試的假文章改承襲真正 domain entity，
移除同一預設 DOI 配上不同 PMID 的矛盾 fixture；不為資料宣告增加鏡像測試。

- 最終完整本機 gate：**4,647 passed、23 skipped、30 deselected，104.38 秒**；lint、format、async、mypy 通過。
- Operation quota 計算的是 provider method，不宣稱是每一個實體 HTTP request。
- Archived report 與最多 100 筆 JSON run history 沿用各自保留規則；這輪沒有刪除使用者歷史檔案。
- 舊式非空 metadata-filter dict 無法直接重放為現行 facade filters，明確拒絕，避免輸出無效或改變原條件的 replay。

### 第五階段修正與驗證

9 檔／156 定義已逐項審查；兩項舊 fulltext follow_up 已結案。核心 **1,230／2,901 reviewed（42.40%）**，0 follow_up、1,671 pending。

- 全文服務按 policy 的來源順序執行，維持各來源的識別碼與 fallback 條件；移除不可達 DOI 分支及未回傳的 CORE section 註記迴圈。
- Europe PMC 同時保留未截斷的選定章節原文與有限預覽；圖像服務的結構化 error 會計入 coverage。
- 引用驗證要求期刊全名或縮寫精確正規化相符，不再用子字串；支援短 PMID 與連續作者 initials。
- 非 list 批次來源回應不再中止整份參考文獻；prefetch 僅接受要求的 PMID。
- 引用分段共用一份實作；引用驗證改用現有 BoundedTaskSupervisor，限制工作容量並在 response deadline 到期後保留／回收未完成工作，避免無界取消等待。
- Citation network 的 traversal limits 與 deadline 收緊型別／finite 邊界，PMID 統一用 domain validator；既有 deterministic BFS 與 Mermaid 修復／fallback 保留。

7 個案例先重現失敗，另驗證不接受取消的來源仍不拖延回應。最終完整本機 gate：**4,655 passed、23 skipped、30 deselected，103.37 秒**；lint、format、async、mypy 通過。
這些數字是回歸驗證，未宣稱公開 benchmark 的 A/B 成效。

### 第六階段修正與驗證

27 檔／300 定義完成；全核心帳本 **1,522／2,898 reviewed（52.52%）**，0 follow_up、1,376 pending。

- 14 個案例先重現失敗，包括 MEDLINE record injection／摘要選項、BibTeX 跳脫與缺少 journal、DOI-only access 誤判、MedPaper 摘要外洩／自動 verified、兩事件上限、Phase IV、零引用數、非有限 citation metrics、revision 假資料夾／身分不一致、Mermaid duplicate key 與 MedPaper 路徑碰撞。
- 本機 MEDLINE 以 Bio.Medline 解析確認 record 邊界；BibTeX 欄位統一一次跳脫、安全唯一 citation key；既有摘要與姓名行為一起驗證。
- 筆記先正規化資料並移除不需要的摘要，所有新檔案共用相同資料；MedPaper 標為 unverified，節錄標為 Abstract Excerpt；預設仍保留既有使用者檔案。
- notes 的兩個重複 ID/path wrapper 移除；Chronicle topic normalization 三處合併為一處。
- Timeline 選文保留兩端而不超出上限；phase regex 加 token 邊界；非有限／格式錯誤 citation metric 不再變成最高分或中止全批。
- 保留 citation zero、真正中位數與 branch confidence zero；diff 相同日期使用穩定原始順序。
- Chronicle 列表排除 symlink 目錄、假 revision 目錄；所有 load 核對儲存身分。來源 returned 大於 available 不能通過 coverage。
- Mermaid 碰撞修復最初破壞穩定 ID，被既有測試抓到後修正；保留既有 ID，只替真正重複的 occurrence 分配不碰撞 suffix。
- 文件、README 以外的匯出使用指南、AGENTS／Copilot／Cline／research agent／skills 與網站、packaged references 已同步；最終 README 與 MEM 總整理仍在十階段驗收時進行。

最終完整本機 gate：**4,669 passed、23 skipped、30 deselected，105.83 秒**；lint、format、async、mypy 通過。
所有審查理由逐項撰寫；300 定義與實際 AST 名單精確相符。未將下一階段預先標為完成。

### 第七階段修正與驗證

已完整閱讀 HTTP outbound、static token auth、NCBI 與 PubTator 的 18 檔／176 定義，逐項理由已登錄。核心 1,698／2,900 reviewed（58.55%），0 follow_up、1,202 pending。

- ECitMatch 改讀實際 `|` 分隔回應，拒絕多列／欄位分隔注入；[NCBI 官方範例](https://www.ncbi.nlm.nih.gov/books/NBK25499/#chapter4.ECitMatch)已實際取得 PMID 2014248。
- PubTator 修正 base URL 缺少斜線、純文字端點誤當 JSON、BioC 巢狀 annotation 與類型 mapping；使用官方 endpoint 的 PMID 19894120 回應確認結構，回歸案例離線執行。
- PubTator 共用既有 bounded streaming；close 可重複呼叫；非 dict JSON 不再偽裝成功空結果。實體搜尋將回傳物件轉成真正 PMID，關聯 confidence 不再當作 evidence count。
- iCite 快取按所需欄位判斷完整度、合併部分欄位、複製讀寫結果並丟棄未要求 PMID；排序與篩選拒絕非法／非有限 metrics。
- 搜尋原題加明確括號後再套用 filters；hydrate 與 summary 保留要求的 PMID 排序，驗證來源 identity；同步實際 physical-query provenance 測試。
- 三個引用查詢共用一個方向感知流程，去重與移除自身後才套用上限；MeSH synonyms 穩定去重，query-ID 分配跳過既有稀疏 ID。
- 官方 citation export 計算實際 RIS/MEDLINE/CSL 筆數，拒絕空內容／HTML／格式錯誤；仍可能回傳有效部分結果，不保證每個要求 PMID 均收錄。
- PDF boolean 與 bytes 方法共用實作；50 MiB／60 秒的既有安全下載邊界、PDF magic bytes，避免 MIME-only 攔截頁覆寫；PMC prefix 正規化避免 PMCPMC URL。
- 靜態 token 禁止同一 secret 對應不同 tenant；修正「記憶體中不會有 token」的過度宣稱。HTTP limits 拒絕 bool／非整數／NaN byte cap。

驗證邊界：Python 已執行的 DNS／Bio.Entrez worker thread 無法強制終止；API 成功與抽取的 relation／publication type 都不等於科研結論正確。未啟動付費模型 benchmark。




11 個新增回歸案例有具體行為判別，其中 10 個（8 個主案例、citation record count、PDF signature）在修正前實際失敗；另有 ordered neighbor 去重驗證。
- 最終完整本機 gate：**4,680 passed、23 skipped、30 deselected，103.69 秒**；lint、format、async、mypy 通過。
- 中途完整測試抓到 physical query 字串斷言與 PDF 改動提早載入 HTTPX；保留原本輕量搜尋匯入契約，修復後整套重跑成功。
- 審查帳本涵蓋 176 個目前定義，沒有把 API 宣告／typed model 的存在當成介接正確性證據。

### 第八階段修正與驗證

40 檔／703 定義已逐項審查；全核心 **2,401／2,898 reviewed（82.85%）**，0 follow_up、497 pending。新增 helper 與移除 wrapper 均已重新納入分母。

- 共用 HTTP 修正空 POST body、Retry-After 0、跨 origin API-key headers 與 typed error preservation。
- WoS 使用官方 Starter endpoint／publishYear／PMID；拒絕不支援的 OA filter。Crossref 不再假裝提供 incoming citations，將 available count 與 retrieval_supported 明確分開。
- EPMC／CORE 原始 Boolean 查詢加括號後才套 filters，並共用 compiler 保持 physical query provenance 一致；S2 保留引號內 AND／OR，bulk 截斷頁不再回傳會跳過資料的 continuation token。
- Unpaywall 的 null location、安全 DOI identity 與 422 contact error；OpenAlex 完整作者、未知年份、finite cost、超過 50 筆 source batch；S2 dataset manifest 身分與連續 diff chain 驗證。
- Preprint 保留完整摘要、驗證 Atom 根與識別碼，broker 在 finally 關閉自有 searcher。arXiv keyword rewrite、Rxiv 最近 90 天第一頁本機篩選的限制仍明示，沒有宣稱完整原生 Boolean／全語料檢索。
- PDF／metadata 使用 bounded outbound；PDF 抽取離開 event loop 並確保 native document 關閉；重複章節合併、不覆寫。Browser／ClinicalKey 串流限制與整體 deadline；institutional cookies 依 target domain／path／expiry 篩選；MIME 不足以判定 PDF。
- PMC BioC 支援真實 list collection root、JATS default namespace、匿名 figure；圖像 URL 精確 stem 配對，圖號引用不再混淆 Figure 1／10 或把 caption 算為正文引用。
- ClinicalTrials 驗證 NCT identity，區分 actual／estimated enrollment，保留 0；image advisor 修正 CT／PET 子字串誤判，移除五個無 caller forwarder 與一個 service dedup wrapper。

來源契約參考：[WoS 官方 Swagger](https://developer.clarivate.com/apis/wos-starter/swagger)、[Crossref 官方 filter 清單](https://github.com/CrossRef/rest-api-doc#filter-names)、[PMC BioC 官方文件](https://www.ncbi.nlm.nih.gov/research/bionlp/APIs/BioC-PMC/)。小量官方回應用於核對協定；回歸測試離線執行，未進行模型 benchmark 長跑。

完整 gate 曾抓到 14 個舊 fixture／physical-query 斷言不符新契約，已核對實際行為後修正，相關 180 項驗證通過。新增 diagram context 案例也先實際失敗再修正。

- 最終完整本機 gate：**4,705 passed、23 skipped、30 deselected，105.01 秒**；lint、format、async、mypy 通過。
- Source ledger 未預先標記介面層或最後評測模組。Native PDF worker／browser 內部配置仍受各自 runtime 限制，不宣稱可強制終止已執行 thread。

### 第九階段修正與驗證

接續完整閱讀 45 檔／433 個 presentation 定義，先檢查 transport、browser broker、tenant 與工具綁定，再審查全部工具、資源與提示內容。

45 個 presentation 檔案已完整閱讀，434 個定義的逐項紀錄與 SHA-256 已核對；
另將查詢 fallback 政策移到 application 新檔並登錄。第 4 階段 pipeline serializer
差異已重新審查。核心目前 **2,834／2,900 reviewed（97.72%）**，66 pending、0 follow_up／stale。

- Browser broker 驗證 token／port／timeout／大小，PDF magic、有限候選與請求 body；
  臨時下載不用 publisher 檔名，取消後清理 download listener，browser lifespan 確保關閉。
- HTTP streamed 202 只回一個完整 JSON body；Host wildcard port 拒絕非法 Unicode／過長數字。
  程式建立 server 時拒絕未知 mode；resolver 設定限制為受信任本機操作，遠端匿名身分也無法修改。
- 原生 MCP 錯誤通道解析 JSON／TOON／TextContent，正確區分失敗、partial 與有效零結果；Retry-After 0 保留。
- 查詢 fallback 保留 Boolean／欄位語法、遵守 include_suggestions；prompt 動態字串安全引用，
  clinical_query 用法與實際契約一致，移除召回／證據品質保證。
- Pipeline 顯示共用 application serializer；dry run 顯示 planned、executed=0，journal 不捏造來源執行；
  report 保存移出 event loop，保留真正開始時間；刪除排程的提示依實際清理結果。
- 搜尋文字移除論文類型直接對應 evidence grade、IF≈，標明 reproducibility 為 heuristic；
  擴展來源範例提醒從 replay 保留原 filters/options。
- 引用指標沿用既有 iCite 篩選／排序，零門檻排除 unknown；圖像 PMID→PMCID 先核對身分；
  GraphML 標題含雙連字號仍可解析，vis 大 PMID 保持 JavaScript 精確身分。
- Export last 不再截成前 100 篇；官方匯出不支援關閉摘要時明確拒絕，改用 explicit local；
  筆記與大量 citation 寫檔移到 worker。Fetch details 接受 TOON，與既有 next-tool hints 一致。
- 圖像 handoff 只提供素材與搜尋提示，由 host agent 依使用者範圍執行；raw base64 不重複解碼。
  移除 7 個只註冊 discovery、未執行或斷言的測試，以及 4 個重複 registry 結構測試。
- 本機 gate 發現 Git tracked deletion 被誤判 unreadable；清冊改排除 worktree deletion，
  仍保留 orphan review 檢查與真正 unreadable／parse error 拒絕。真實臨時 Git repo 案例先失敗後修正。

初次完整 pytest 抓到 9 個舊 fixture／錯誤契約預期，已核對並修正；
相關 **68 passed**，涵蓋全部 41 工具的 stdio／HTTP／fresh-wheel acceptance。
最終第九階段 full gate：**4,722 passed、23 skipped、30 deselected，107.81 秒**；lint、format、async、mypy 通過。
接續第十階段剩餘 10 檔／66 定義，最終全核心驗收尚未完成。

### 第十階段修正與驗證

10 個剩餘檔案已全部閱讀，涵蓋 public SDK、DI container、三個 lazy-export package、
provider error-envelope helper 與 evaluation support；空的 evaluation package root 也已核對。
目前 67 個定義逐項記錄理由，沒有用 AST 清冊自動填寫審查結論。

- SDK：API key 不再出現在 config repr；保留相容的 `data_dir` 欄位並說明不會啟用持久化。
  typed outcome 只保證外層 frozen／tuple，未宣稱內含 domain model 深層不可變。
- Container：確認 server 啟動時依序解析 providers；保留小型、單一 owner 的 DI graph，
  說明 reset／override 不負責關閉資源，不另加不必要的 container 或並行熱更新機制。
- Frozen corpus：數字 `1` 與字串 `"1"` 原本可通過唯一性檢查，再轉為同一評分 ID；
  現在先要求非空字串 ID、唯一性及文字欄位型別。budget／limit 拒絕 bool 和非整數，
  無效參數不先扣額度。初始化失敗會關閉 SQLite。
- Persistence：corpus audit 與 checkpoint 都使用既有 unique-temp／fsync／atomic-replace helper，
  不再維護固定 `.tmp` 或直接覆寫 JSON 的平行版本。取代失敗時舊 audit 保持完整。
- Resume：以 canonical JSON 比較 protocol，避免 Python 的 `True == 1` 掩蓋變更；
  非有限值被拒絕。只接受明確的 pending／terminal 狀態，未知 status 不再被算成完成。
- Checkpoint：評分與資源統計共用完整性驗證，核對 experiment、qid／repeat／arm 路徑及 trace hash；
  失敗嘗試仍計入用量，缺少 result 的中斷嘗試保留為 unknown usage。
- Provenance：只有 evaluation code 的空產品樹不再產生「有效」空 hash。固定語料 runner
  在任何模型執行前確認目前與目標 revision 的 corpus adapter 完全相同，並記錄 evaluator／lockfile hash。
  此檢查不會自動改寫使用者選定的基準 checkout。
- 移除 SDK 的 class-not-None／annotation 鏡像測試，以可重現的 credential repr 案例取代；
  既有實際 SDK 執行、runtime 綁定、雙組 MCP、單一 writer／resume 及 5,000 題 prepare-only 測試保留。

第一批 **14 個案例在修正前失敗**，修正後相關測試 **46 passed**；
後續不同 adapter 的 preflight 案例也先重現失敗，最後相關測試 **47 passed**。
全部是離線測試，沒有呼叫付費模型或啟動公開題庫長跑。

### 最終範圍核對與驗收

| 範圍 | Python 檔案 | class | function／method／nested function | 審查宣告 |
| --- | ---: | ---: | ---: | --- |
| 核心 `src/pubmed_search/` | 223 | 456 | 2,445 | 2,901／2,901 reviewed |
| `tests/` | 207 | 831 | 4,976 | 已清點；不宣稱所有測試定義逐項語意審查 |
| `scripts/` | 35 | 18 | 305 | 已清點；只對相關工具作局部審查 |
| 根目錄 Python | 3 | 0 | 6 | 已清點；不混入核心完成率 |
| 全 repo 可見 Python | 468 | 1,305 | 7,732 | 核心全量完成不代表全 repo 9,037 定義全量完成 |

function 欄位已包含 method 與 nested function，不能再重複加總。
核心起始 2,888 → 最終 2,901，反映新增共用 helper、移除重複實作與驗證方法，
不是固定分母後忽略新增程式。產生的 dataclass methods、lambda、第三方／忽略檔案不在 AST 定義清單內。

完成核對可重跑：

```bash
uv run python scripts/perf/symbol_inventory.py --require-reviewed src/
uv run --frozen python scripts/check_repo.py full
uv run --frozen python scripts/check_repo.py smoke
```

`symbol_inventory` 掃描 Git 可見的 tracked／untracked 程式，排除工作樹中已刪除的檔案，
以完整 lexical owner 與 occurrence 區分同名／巢狀定義。解析失敗、漏審、過期檔案 hash
及已移除定義的 orphan 紀錄都會使完成斷言失敗。來源內容改動後，必須重新讀取差異再更新帳本。
帳本標示 `Codex (self-review)`，它是逐項自審的可追溯證據，不是獨立人工專家認證。

- **最終 full gate：4,736 passed、23 skipped、30 deselected，pytest 111.85 秒。**
  Ruff、格式、async consistency、mypy 一併通過；stdio／HTTP／fresh-wheel 的
  **全部 41 個 MCP 工具**仍在實際協定驗收內。
- **文件同步後 smoke：165 passed，13.78 秒。** 網站生成與來源同步、技能安裝保護、
  SDK／provider 契約及三條完整 MCP acceptance 路徑通過。
- DDD layer check、vulture、deptry、Bandit（medium/high 掃描）與 `git diff --check` 通過。
  Bandit 僅輸出既有未命中的 nosec 提示；deptry 對未安裝 optional 模組的名稱作預設推定，
  沒有報告依賴問題。這不是其他 OS、Docker 或 live-provider 的執行證據。
- 重新載入帳本核對核心 **2,901 reviewed／0 pending／0 follow_up／0 stale_review／0 orphan**，
  所有 evidence 路徑存在。24 個零定義 source 檔案已按各階段核對，列入 223 檔的檔案清冊。
  全 repo 仍有 6,118 個非核心定義 pending；沒有把它們誤標為已審查。
- 最終 Git-visible 程式清冊 snapshot SHA-256：
  `edc4a99c1c31cbed56d9e024a52047480c50117182e5bbe0046cf8c228a60bee`。
  這是清冊內容雜湊，並非 Git commit 或已發布版本標籤。

README（雙語）、benchmark 文件、工具指南、整合說明、CHANGELOG、網站產物與 MEM
同步目前行為；前期 maintenance／renovation 報告保留歷史測量並連到本報告。
保留安裝時不覆蓋既有使用者 skill 目錄的規則，以及本機 full pre-push／一般雲端 smoke 的分工。

本輪沒有發布新版、沒有新的 live-provider 全面驗證，也沒有新的公開 benchmark 增益分數。
固定語料診斷仍只有 title／abstract lexical backend，不涵蓋完整全文與引用 snapshot；
要回答完整套件比原生 Codex 好多少，仍須依已準備的配對 protocol 另行執行與報告。

### v0.7.3 發布準備的複查

使用者於完成審查後授權分段提交、push 與發布 v0.7.3。
發布 metadata 將 `__version__` 改為 0.7.3；另於 export 的兩個 base-directory 讀取處
補上租戶 guard 註解。已重新核對唯一消費端經 `tenant_export_root` → `tenant_data_dir`
才寫入檔案，沒有改變路徑行為，並更新這兩個 source 檔案的審查 hash。
網站測試改依目前套件版本驗證 cache key，避免硬編碼前一版日期／版本。
核心定義數量仍為 2,901，完成斷言再次通過；上方 snapshot 保留為審查結案當時的紀錄。
發布端驗證與實際上架結果另外記錄，不改寫各階段的歷史測試數字。
