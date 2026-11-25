---
name: pubmed-research-chronicle
description: "Persistent, versioned research evolution with build_research_chronicle. Triggers: 研究脈絡, 研究演變, 研究編年史, research chronicle, 領域怎麼演進, 上次之後有什麼新的, 追蹤主題, 里程碑, milestone, timeline, 主題比較"
---

# 研究編年史指南

## 描述

`build_research_chronicle` 是研究演化的**唯一入口**，取代了舊的三個 timeline 工具。

和一次性快照最大的差別：chronicle 會以**遞增 revision 持久化儲存**。之後重跑同一個主題會產生 revision N+1，就能做版本比對，回答「上次之後改變了什麼」。

主軸是**時序（線性）**，分支 (lineage) 是**次要組織維度**。兩者都是同一份 snapshot 的投影，所以 `output="timeline"` 和 `output="tree"` 使用同一組 entry。這裡的 lineage 是檢索結果中的可解釋分組，不是引用或科學上的因果譜系。

標準視覺輸出 `output="mermaid"` 依年份排列。每個分支接在該線或其子線**於本版最早能定年的紀錄**，支內論文依時間排序。`output="chronicle_map"` 提供相同座標，也列出可進一步查證的分歧候選。

---

## 快速決策樹

```text
使用者問研究演化？
├── 「這個領域怎麼走到今天」 → build_research_chronicle(topic="...")
├── 「把我剛剛找的整理成脈絡」 → build_research_chronicle(pmids="last", topic="...")
├── 「上次之後有什麼新的」 → read_research_chronicle(request={"action":"diff","chronicle_id":"...","from_revision":N})
├── 「哪些是里程碑 / 領域分佈」 → read_research_chronicle(request={"action":"milestones","chronicle_id":"..."})
├── 「畫出主軸如何分岔」 → read_research_chronicle(request={"action":"load","chronicle_id":"...","output":"mermaid"})
├── 「A 和 B 兩個主題比較」 → read_research_chronicle(request={"action":"compare","selection":{"kind":"topics","values":["A","B"]}})
└── 「幫我寫成一段敘述」 → read_research_chronicle(request={"action":"narrate","chronicle_id":"...","mode":"full"})
```

---

## 建立與更新

```python
# 建立（重跑同一主題會以原子操作追加不可變的 revision N+1）
build_research_chronicle(topic="remimazolam ICU sedation")

# 從上一輪搜尋結果建立
build_research_chronicle(pmids="last", topic="My Reading List")

# 明確接續某個 chronicle
build_research_chronicle(topic="remimazolam", chronicle_id="remimazolam-9f2b1c4d")

# 只給 chronicle_id：照原本的檢索範圍再跑一次。
# topic/pmids 以及 max_events/min_year/max_year 都沿用上一版，
# 逐版比對時，也要考慮資料補標、來源排序及涵蓋範圍。
build_research_chronicle(chronicle_id="remimazolam-9f2b1c4d")
```

回傳的 `summary` 開頭就是**時序主軸 (Chronological Spine)**，下面才是研究分支。
Chronicle ID 會出現在 summary 裡，後續 `read_research_chronicle` 都要用它。

重建時，預設 `output="summary"` 附上 `Changes since revision N-1`，列出 entry、證據、分支、scope 與 audit 的變動，以及最多 5 個新增標題。新增分支同時顯示前一版已有與本次新觀察的證據數量。完整時序讀 `output="timeline"`，完整變動讀 `action="diff"`。每週提醒可以節選；編年紀錄應保留觀察到的舊文獻重分類與新文獻。
若前一版無法讀取，摘要顯示 `Change summary unavailable`；這不會放寬 store 對損壞最新 revision 的錯誤處理。本次未觀察到不代表研究已退場。

### 輸出格式 (`output`)

| 格式 | 用途 |
| --- | --- |
| `summary` | 預設。緊湊 Markdown，含時序主軸 |
| `chronicle_map` | 分支與年表座標、分流候選及反例、逐年直接歸類篇數 |
| `timeline` | 時序投影 JSON |
| `tree` | 研究脈絡樹 JSON（分支式演化） |
| `graph` | 型別化 provenance graph（證據溯源） |
| `evidence` | 去重後的證據表 |
| `milestones` | 關鍵文章及其評選依據、各支線代表篇目與分佈統計 |
| `mermaid` | 橫向年份主軸與依據收錄日期繪製的各支線 |
| `narrative` | 有證據支撐的敘述 |
| `json` | 完整 snapshot |

不論 `output` 選哪個，Chronicle revision 都會先保存；若 session artifact persistence 已啟用，系統再寫入包含完整 snapshot、投影、證據表、里程碑分析與 audit 的 artifact bundle。若這一步失敗，Markdown 會顯示警告，structured output 則帶 `artifact.status="failed"`，不可假裝 locator 已建立。

### Mermaid 自動修正與降級

- `chronicle.mmd` 永遠只含可直接交給 Mermaid 的純 source；MCP 的 artifact 註記放在 code fence 外，不會污染圖檔。
- label 會清除控制／雙向文字字元、跳脫 Mermaid delimiter，node ID 使用不透明且不碰撞的穩定格式；孤兒 parent、循環、重複 ID 與過大圖也會先結構化修正。
- renderer 依序嘗試 rich 圖、只含基本 node/edge 的 safe 圖，最後回傳一定可讀的 minimal notice；完整資料仍保存在 `chronicle_map.json`、`timeline.json` 與 `snapshot.json`。
- 讀 `mermaid_validation.json` 可查看 `status`、`tier`、source digest、corrections、omitted counts 與 warnings。若有 fallback 或視覺項目被省略，回答時必須揭露；不可把摘要圖說成完整圖。
- Runtime 使用 deterministic structural lint，不要求 Node。CI 另以固定版本 Mermaid 11.16.1 實際 parse 並 render SVG，涵蓋 rich / repaired / safe / minimal tiers。

### Lineage 的依據

- 優先使用多篇論文共同出現、且具有區辨力的 MeSH descriptor 與作者 keyword。
- 只是重述主題的詞不能形成分支：詞彙或多字縮寫已出現在 topic 中（例如 topic 有 `PACU`、`EEG` 時的 `post-anesthesia care unit`、`EEG`）、出現在每一筆 entry，或在 8 筆以上的版本中出現於至少一半 entries 且與其他重複 descriptor 的共現接近其基準比例（橫跨各線而非分開它們，例如 EEG 主題中的 `Electroencephalography`）。被排除的詞、比例與理由列在 `lineage_diagnostics.excluded_topic_signals`。
- 分支依「新覆蓋論文」的 inverse-frequency 權重逐輪挑選（`signal_selection="greedy_marginal_coverage"`，MeSH 同分優先），所以每條線至少有兩篇先前線條沒有涵蓋的論文；仍然同時符合的訊號保存在 `cross_signal_links`。
- 每個 branch 保存 `lineage_basis`、signal source 與 confidence；每個 entry 保存 global order 與 branch order。
- 同一篇論文可符合多個 selected signals，但 tree 只給它一個 primary branch；其他符合項保存在 `cross_signal_links`，避免假裝 branches 完全互斥。全部或已分派 entries 的 overlap 達 20% 時，audit 會警告。
- 單篇論文獨有的 singleton term 不足以建立語意 branch。若訊號不能支持至少兩個主題分支，會退回 Discovery / Clinical / Safety 等研究階段分類並產生 audit warning；不可把它描述成「發現出的語意主題演化」。

### 時序與檢索範圍

- `earliest_observed_in_scope` 只表示檢索候選集中最早的有日期文章，不證明它是整個領域的 first report；topic query、PMID set、年份限制與來源可用性都會改變可觀察範圍。
- 排序會保留 year / month / day precision。兩筆記錄若只知道同一年，或日期區間重疊，畫面可有 deterministic display order，但 graph 不會據此建立 `precedes` / `supersedes`。沒有可靠日期者標示為 `Undated`、排在 dated entries 後面，且不計入 year span。
- Topic mode 會把 `min_year`／`max_year` 送到 PubMed，再做 bounded retrieval；最後保留觀察到的首篇、末篇、landmark 與 temporal spread。audit 的 `source_counts.pubmed` 分開記錄 `returned`／`available`；總量未知、來源有 cap 或後續 selection 截斷時必須揭露 warning。
- Topic mode 的 retrieval provenance 會分開保存 `ranking_requested` 與實際 `ranking`。只有至少一筆經驗證的 iCite `citation_count` 真正套用後，才可宣稱 `icite_citation_count_then_pubmed_relevance`；否則有效排序仍是 `pubmed_relevance`。
- `citation_metrics` 使用 `citation-metrics-coverage/v1`，分辨 `complete`、`partial`、`empty`、`error` 與 `not_requested`，並列出 requested／returned／applied／sortable-count 數量。outage 或 malformed response 不是零引用，也不能寫成已完成 enrichment。
- PMID 模式同樣以一次批次、有快取的 iCite 請求套用經驗證的 metrics，並記錄同一個 envelope；`evidence_selection="explicit_pmid_set_without_ranking"` 表示指定的 PMID 集合不會被重新排序或截斷。metrics 用於 landmark score 與引用門檻 milestone。若 iCite 沒有可用資料，就不計算 landmark 綜合分數，highlights 改依已存引用數、再依時序排列，summary 與 audit 都會說明原因。
- 建版的 JSON 錯誤中，`category="api"` 表示 PubMed 取證失敗，`category="data"` 且訊息為零筆文章則表示本次搜尋沒有可建版的證據。兩種情況都可依 `example` 讀取先前保存的版本。明確 PMID 只接受正 ASCII digits（最多 20 位）或 `PMID:` prefix。
- entry ID 依 PMID、其次 DOI 的 evidence identity 保持穩定；日期或 milestone reclassification 應出現在 `updated`，不應造成假的 remove/add。topic identity、exact lookup、compare 與 continuity 共用 Unicode normalization、case-folding、空白折疊後的 canonical key。

---

## 讀取與比對

```python
# 列出已儲存的 chronicles
read_research_chronicle(request={"action":"list"})

# 讀取某個版本（預設最新）
read_research_chronicle(request={"action":"load","chronicle_id":"remimazolam-9f2b1c4d","output":"tree"})
read_research_chronicle(request={"action":"load","chronicle_id":"remimazolam-9f2b1c4d","revision":2,"output":"timeline"})

# 版本比對：新增/更新/本次未觀察到的 entries、證據與分支變化
read_research_chronicle(request={"action":"diff","chronicle_id":"remimazolam-9f2b1c4d","from_revision":1})

# 里程碑分佈（讀已存證據，不重跑搜尋）
read_research_chronicle(request={"action":"milestones","chronicle_id":"remimazolam-9f2b1c4d"})

# 主題比較（含共用證據分析，最多 5 個）
read_research_chronicle(request={"action":"compare","selection":{"kind":"topics","values":["remimazolam","propofol","dexmedetomidine"]}})
```

> `compare` 與 `milestones` 都只讀已儲存的 chronicle，**不會重跑搜尋**。
> 若某個主題還沒建立過，會回傳明確的錯誤告訴你要先 build 哪一個。

`request={"action":"compare","selection":{"kind":"topics","values":[...]}}` 使用 Unicode、大小寫與空白正規化後的**完整 topic 名稱比對**，不是模糊搜尋。同名 topic 對應多個 chronicle 時會回報 ambiguity，必須改用 `selection={"kind":"chronicle_ids","values":[...]}`；重複的 topic / ID 不算兩個可比較對象。

`diff` 只使用 `not_observed_in_revision` 描述本次缺席。即使 input scope 未變，PubMed indexing、citation metrics 與 ranked/capped retrieval 仍可能改變，因此缺席永遠不能當成已證實的研究退場。

判讀新增分支時，檢查 `branches.added_details[].evidence_observation` 的 `previously_observed`、`newly_observed` 與每筆 `publication_year`。若兩篇五年前的研究已在比較起點，應按原發表年列入時序，並註明這次才辨認出關聯。只有證據紀錄確實顯示補標時才如此歸因。`basis="undetermined"` 表示分支成員證據不足，可查看兩版 snapshot。這組欄位只比較指定的起訖版本。

公開來源逾時或沒有查到文獻時，若已有 revision，先用 `action="load"` 讀取並標出版本。從 `output="evidence"` 取得逐篇 `fulltext_lookup_source`，有值時可交給 `get_fulltext(source=..., output_format="json")`。記錄實際取得的段落及來源；摘要、書目與只含連結的資料各自標記。授權 Zotero 館藏的查找與比對見 `pubmed-paper-exploration`，章節補搜與全文讀取見 `pubmed-fulltext-access`。尚未對上 PMID 的地方文獻保留在附表。

### 使用者問到分歧、關鍵文章或主流時

1. 讀 `output="chronicle_map"`。圖上 `branch_point` 是分支或後代最早能定年的紀錄。`divergence_review.candidates` 提供跨兩個主題的文獻，以及後來各線的一篇；看 `earlier_single_signal_papers` 是否顯示兩線早已存在。若只憑標引，寫成「待核對的分流候選」。
2. 查看同一輸出的 `sources_for_review`。即使主題詞不足，仍可找到標為比較研究或共識文件的篇目。讀當時作者實際比較的對象、方法及理由，記下 PMID／DOI、文件日期、章節與不同讀法。要說某篇改變了做法，還需指出誰在何時採用、修正或反駁它。若無法取得原文，明列目前證據層級。
3. 讀 `milestones` 的 `landmark_entries` 及 `branch_representatives`，讓小支線也有文章可讀。`score_components` 顯示保存的評分依據；`observed_max_citations` 未知時保留未知。區分提出方法的原始研究、同時代比較、反例與後來回顧，讓每篇文獻的歷史角色有出處。
4. 說明「主流」涉及哪個年代、群體與指標。可用 `direct_activity.by_year` 寫「此版該年共 Y 筆，其中 X 筆直接歸在這條線」。若要寫「多數中心已採用」，再找有母數的當時調查或登錄。當兩種解釋都合理時，把支持各自解釋的來源並列。

重建「當時看得到什麼」時，發表年截止只限制篇目。今天取得的主題標引與累積引用可能包含後來資訊。能取得當年的索引版本就註明日期；只能依現存材料回顧時，請直接說明。

---

## 每個 entry 帶什麼

| 欄位 | 說明 |
| --- | --- |
| `title` | 研究設計標籤。優先採 PubMed PublicationType（RCT、Meta-Analysis、Systematic Review、Observational Study、Guideline 等），其次 MeSH 研究設計 descriptor（如 `Prospective Studies`）；只有 PubMed 尚未標引設計時才用標題或摘要文字推斷，並標 `[heuristic]`。`non-randomized`／`quasi-randomised` 不算 RCT；試驗 protocol（含同時標 RCT 的 `Clinical Trial Protocol`）標成 protocol，勘誤、撤回通知與 expression of concern 標成 publication notice，兩者都不是 milestone |
| `summary_claim` | 一行附引用的主張。有摘要時直接引用該論文摘要的結論句（逐字摘錄，附章節與字元位置；註冊、經費、利益衝突、授權與出版社聲明不會被引用）；沒有摘要時才用保守模板 |
| `provenance.study_design` | 標籤依據 `basis`（`pubmed_publication_type`／`mesh_study_design_descriptor`／`text_pattern_heuristic`／未標引）、符合的類型與 retracted 等旗標 |
| `provenance.extractive_highlight` | 摘錄句、`char_start`／`char_end`（指向 `EvidenceArticle.abstract` 的 Unicode code point 位置）、章節、選句規則、摘要 SHA-256 與 `abstract_truncated` |
| `provenance.abstract_truncation` | 摘要不完整時（PubMed 的 `ABSTRACT TRUNCATED` 註記，或只保存了前 20,000 字元）記錄原因與長度；截斷處的殘句不會被引用，結論段可能缺失 |
| `evidence` | supporting / contradicting / updating 三類證據 |
| `branch_id` | 所屬研究分支（lineage） |
| `confidence` | 信心分數 |
| `status` | `active` / `superseded` / `contested` / `background` |

型別化 provenance graph 以 `Topic → Branch → Entry → EvidenceArticle` 相連，並依 edge invariants 驗證。

`confidence` 的精確語意是 milestone detection confidence，不是 scientific importance。landmark ranking 先看 `provenance.landmark_importance_score`，沒有才退回 citation count；不可用 detection confidence 排「最重要論文」。

PubMed PublicationType 標引的研究設計優先於文字樣式推斷。標題或摘要樣式只能補充 PublicationType 沒有的資訊（例如試驗 phase），不能把已標引的 RCT 或統合分析改標成 Safety Alert、核准、爭議或突破；觀察性研究（以及 Comparative／Multicenter Study 等泛用類型）仍可帶試驗 phase 或明確的 safety signal（藥物安全監視）。只有 MeSH 設計 descriptor 時不會擋掉文字 milestone。摘要提到 adverse events 不構成安全警訊；`Safety Alert` 需要明確的安全通報、safety signal 或 boxed warning。摘要樣式只採用自我描述的句子（如「In this phase 3 trial」「We performed a meta-analysis」），「A recent meta-analysis suggested…」這類背景引述不算。

引用摘錄句時，要說明它是作者摘要中的原句，而不是你的詮釋；可用 `output="evidence"` 取得完整摘要，以 `abstract[char_start:char_end]` 核對。

---

## Audit：知道這份脈絡有多完整

每次 build 都會產生 audit，回報：

- 證據覆蓋率（有沒有 entry 缺證據）
- 研究設計標籤來源（`study_design_labels`）：列出 `[heuristic]` 標籤與來自摘要文字的類別（`abstract_pattern_categories`），並在已標引研究設計卻帶不相容的 safety／debate 類別時警告
- 摘錄句完整性（`extractive_highlights`）：每句引文都必須能以字元位置對回保存的摘要，否則 fail；摘要被截斷時警告（`truncated_abstracts`）
- 識別碼覆蓋率（有沒有文章缺 PMID/DOI/PMCID）
- 分支覆蓋率（空分支、未分派 entry）
- lineage 語意依據與覆蓋率（MeSH/keyword 或研究階段 fallback）
- Mermaid renderability（修正、fallback tier、被摘要的 visual items）
- graph 完整性（invariant 違反）
- 時序缺口（無法定年的 entry）
- 各來源回傳量
- iCite coverage 與 requested/effective ranking 是否一致（topic 與 PMID 模式皆檢查）；outage、partial、empty 會警告，無有效 citation count 卻宣稱 iCite ranking 會失敗
- 實際 artifact payload builder 產出的 required file names（加上 store 產生的 manifest）；這是 preparation preflight，不等於 persistence 成功

audit 狀態為 `pass` / `warn` / `fail`。**回答使用者時要一併說明 caveats**，不要把 `warn` 當成完整答案。

---

## 敘述輸出

```python
read_research_chronicle(request={"action":"narrate","chronicle_id":"...","mode":"brief"})  # 依 landmark 排序選讀各分支
read_research_chronicle(request={"action":"narrate","chronicle_id":"...","mode":"full"})   # 全部 entry
```

輸出的**每一句 claim 都附 entry ID 與文獻識別碼**，可直接查證，適合寫作與報告。有摘要的 entry 會逐字引用作者的結論句並標示章節與字元位置；這是摘錄，不是詮釋。

---

## 常見錯誤

| 錯誤 | 正確做法 |
| --- | --- |
| 用 `build_research_timeline` | 已移除；改用 `build_research_chronicle` |
| 用 `output_format=` | 參數名是 `output=` |
| 直接送 `request={"action":"compare",...}` 但沒先 build | 先對每個主題各 build 一次 |
| 把同年排列解讀成先後關係 | 只在日期 precision 足以證明時宣稱先後 |
| topic compare 回報 ambiguity | 先送 `request={"action":"list"}`，再用 `selection.kind="chronicle_ids"` 傳兩個以上不同 ID |
| 忽略 audit warnings | 回答時要說明覆蓋率限制 |
| 把 `[heuristic]` 標籤當成 PubMed 標引 | 說明它來自標題或摘要文字，並對照原文確認設計 |
| 把摘錄句改寫後仍當成引文 | 引用時保留原句與 PMID、章節、字元位置；自己的歸納另外標示 |
| 每次都重新 build 來看里程碑 | 用 `request={"action":"milestones","chronicle_id":"..."}` 讀已存的 |

---

## 相關 Skills

- `pubmed-quick-search` — 先找到文獻
- `pubmed-systematic-search` — 需要完整覆蓋時
- `pubmed-paper-exploration` — 從單篇論文往外探索
- `pubmed-export-citations` — 把 chronicle 的證據匯出成引用
