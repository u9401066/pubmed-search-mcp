---
name: pubmed-research-chronicle
description: "Persistent, versioned research evolution with build_research_chronicle. Triggers: 研究脈絡, 研究演變, 研究編年史, research chronicle, 領域怎麼演進, 上次之後有什麼新的, 追蹤主題, 里程碑, milestone, timeline, 主題比較"
---

# 研究編年史指南

## 描述

`build_research_chronicle` 是研究演化的**唯一入口**，取代了舊的三個 timeline 工具。

和一次性快照最大的差別：chronicle 會以**遞增 revision 持久化儲存**。之後重跑同一個主題會產生 revision N+1，就能做版本比對，回答「上次之後改變了什麼」。

主軸是**時序（線性）**，分支 (lineage) 是**次要組織維度**。兩者都是同一份 snapshot 的投影，所以 `output="timeline"` 和 `output="tree"` 使用同一組 entry。這裡的 lineage 是檢索結果中的可解釋分組，不是引用或科學上的因果譜系。

標準視覺輸出是 `output="mermaid"`：年份形成橫向 chronological spine，各 lineage 從**本次檢索範圍內最早的有日期論文**所在年份分岔，分支內的論文仍依時間排序。這不代表它是整個領域的首篇論文；`output="chronicle_map"` 是同一圖形座標契約的 JSON。

---

## 快速決策樹

```text
使用者問研究演化？
├── 「這個領域怎麼走到今天」 → build_research_chronicle(topic="...")
├── 「把我剛剛找的整理成脈絡」 → build_research_chronicle(pmids="last", topic="...")
├── 「上次之後有什麼新的」 → read_research_chronicle(action="diff", chronicle_id="...", from_revision=N)
├── 「哪些是里程碑 / 領域分佈」 → read_research_chronicle(action="milestones", chronicle_id="...")
├── 「畫出主軸如何分岔」 → read_research_chronicle(chronicle_id="...", output="mermaid")
├── 「A 和 B 兩個主題比較」 → read_research_chronicle(action="compare", topics="A,B")
└── 「幫我寫成一段敘述」 → read_research_chronicle(action="narrate", chronicle_id="...", mode="full")
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
```

回傳的 `summary` 開頭就是**時序主軸 (Chronological Spine)**，下面才是研究分支。
Chronicle ID 會出現在 summary 裡，後續 `read_research_chronicle` 都要用它。

### 輸出格式 (`output`)

| 格式 | 用途 |
| --- | --- |
| `summary` | 預設。緊湊 Markdown，含時序主軸 |
| `chronicle_map` | 橫向年份 spine + lineage branch point 的 JSON 座標契約 |
| `timeline` | 時序投影 JSON |
| `tree` | 研究脈絡樹 JSON（分支式演化） |
| `graph` | 型別化 provenance graph（證據溯源） |
| `evidence` | 去重後的證據表 |
| `milestones` | 里程碑分佈與證據品質統計 |
| `mermaid` | 標準合併圖：橫向年份 spine + 主題 lineage 分岔 |
| `timeline_mermaid` | 舊式平面 Mermaid timeline |
| `mindmap` | 只看 lineage 階層、不保留時間座標 |
| `narrative` | 有證據支撐的敘述 |
| `json` | 完整 snapshot |

不論 `output` 選哪個，Chronicle revision 都會先保存；若 session artifact persistence 已啟用，系統再寫入包含完整 snapshot、投影、證據表、里程碑分析與 audit 的 artifact bundle。若這一步失敗，Markdown 會顯示警告，structured output 則帶 `artifact.status="failed"`，不可假裝 locator 已建立。

### Mermaid 自動修正與降級

- `chronicle.mmd` 永遠只含可直接交給 Mermaid 的純 source；MCP 的 artifact 註記放在 code fence 外，不會污染圖檔。
- label 會清除控制／雙向文字字元、跳脫 Mermaid delimiter，node ID 使用不透明且不碰撞的穩定格式；孤兒 parent、循環、重複 ID 與過大圖也會先結構化修正。
- renderer 依序嘗試 rich 圖、只含基本 node/edge 的 safe 圖，最後回傳一定可讀的 minimal notice；完整資料仍保存在 `chronicle_map.json`、`timeline.json` 與 `snapshot.json`。
- 讀 `mermaid_validation.json` 可查看 `status`、`tier`、source digest、corrections、omitted counts 與 warnings。若有 fallback 或視覺項目被省略，回答時必須揭露；不可把摘要圖說成完整圖。
- Runtime 使用 deterministic structural lint，不要求 Node。CI 另以固定版本 Mermaid 11.16.1 實際 parse 並 render SVG，涵蓋 rich / repaired / safe / minimal / timeline / mindmap。

### Lineage 的依據

- 優先使用多篇論文共同出現、且具有區辨力的 MeSH descriptor 與作者 keyword。
- 每個 branch 保存 `lineage_basis`、signal source 與 confidence；每個 entry 保存 global order 與 branch order。
- 同一篇論文可符合多個 selected signals，但 tree 只給它一個 primary branch；其他符合項保存在 `cross_signal_links`，避免假裝 branches 完全互斥。全部或已分派 entries 的 overlap 達 20% 時，audit 會警告。
- 單篇論文獨有的 singleton term 不足以建立語意 branch。若訊號不能支持至少兩個主題分支，會退回 Discovery / Clinical / Safety 等研究階段分類並產生 audit warning；不可把它描述成「發現出的語意主題演化」。

### 時序與檢索範圍

- `earliest_observed_in_scope` 只表示檢索候選集中最早的有日期文章，不證明它是整個領域的 first report；topic query、PMID set、年份限制與來源可用性都會改變可觀察範圍。
- 排序會保留 year / month / day precision。兩筆記錄若只知道同一年，或日期區間重疊，畫面可有 deterministic display order，但 graph 不會據此建立 `precedes` / `supersedes`。沒有可靠日期者標示為 `Undated`、排在 dated entries 後面，且不計入 year span。
- Topic mode 會把 `min_year`／`max_year` 送到 PubMed，再做 bounded retrieval；最後保留觀察到的首篇、末篇、landmark 與 temporal spread。audit 的 `source_counts.pubmed` 分開記錄 `returned`／`available`；總量未知、來源有 cap 或後續 selection 截斷時必須揭露 warning。
- PubMed error 或完全沒有 article evidence 時不建立空 snapshot，也不發布 revision。明確 PMID 只接受正 ASCII digits（最多 20 位）或 `PMID:` prefix；不可把 DOI 或混合文字抽數字後當 PMID。
- entry ID 依 PMID、其次 DOI 的 evidence identity 保持穩定；日期或 milestone reclassification 應出現在 `updated`，不應造成假的 remove/add。topic identity、exact lookup、compare 與 continuity 共用 Unicode normalization、case-folding、空白折疊後的 canonical key。

---

## 讀取與比對

```python
# 列出已儲存的 chronicles
read_research_chronicle(action="list")

# 讀取某個版本（預設最新）
read_research_chronicle(chronicle_id="remimazolam-9f2b1c4d", output="tree")
read_research_chronicle(chronicle_id="remimazolam-9f2b1c4d", revision=2, output="timeline")

# 版本比對：新增/更新/本次未觀察到的 entries、證據與分支變化
read_research_chronicle(action="diff", chronicle_id="remimazolam-9f2b1c4d", from_revision=1)

# 里程碑分佈（讀已存證據，不重跑搜尋）
read_research_chronicle(action="milestones", chronicle_id="remimazolam-9f2b1c4d")

# 主題比較（含共用證據分析，最多 5 個）
read_research_chronicle(action="compare", topics="remimazolam,propofol,dexmedetomidine")
```

> `compare` 與 `milestones` 都只讀已儲存的 chronicle，**不會重跑搜尋**。
> 若某個主題還沒建立過，會回傳明確的錯誤告訴你要先 build 哪一個。

`compare(topics=...)` 使用 Unicode、大小寫與空白正規化後的**完整 topic 名稱比對**，不是模糊搜尋。同名 topic 對應多個 chronicle 時會回報 ambiguity，必須改傳 `chronicle_ids=...`；重複的 topic / ID 不算兩個可比較對象。

`diff` 的 `retired` 是向後相容 alias；請讀 `not_observed_in_revision`／`removed_from_view`。即使 input scope 未變，PubMed indexing、citation metrics 與 ranked/capped retrieval 仍可能改變，因此缺席永遠不能當成已證實的研究退場。

---

## 每個 entry 帶什麼

| 欄位 | 說明 |
| --- | --- |
| `summary_claim` | 一句附引用的主張（含 PMID/DOI） |
| `evidence` | supporting / contradicting / updating 三類證據 |
| `branch_id` | 所屬研究分支（lineage） |
| `confidence` | 信心分數 |
| `status` | `active` / `superseded` / `contested` / `background` |

型別化 provenance graph 以 `Topic → Branch → Entry → EvidenceArticle` 相連，並依 edge invariants 驗證。

`confidence` 的精確語意是 milestone detection confidence，不是 scientific importance。landmark ranking 先看 `provenance.landmark_importance_score`，沒有才退回 citation count；不可用 detection confidence 排「最重要論文」。

---

## Audit：知道這份脈絡有多完整

每次 build 都會產生 audit，回報：

- 證據覆蓋率（有沒有 entry 缺證據）
- 識別碼覆蓋率（有沒有文章缺 PMID/DOI/PMCID）
- 分支覆蓋率（空分支、未分派 entry）
- lineage 語意依據與覆蓋率（MeSH/keyword 或研究階段 fallback）
- Mermaid renderability（修正、fallback tier、被摘要的 visual items）
- graph 完整性（invariant 違反）
- 時序缺口（無法定年的 entry）
- 各來源回傳量
- 實際 artifact payload builder 產出的 required file names（加上 store 產生的 manifest）；這是 preparation preflight，不等於 persistence 成功

audit 狀態為 `pass` / `warn` / `fail`。**回答使用者時要一併說明 caveats**，不要把 `warn` 當成完整答案。

---

## 敘述輸出

```python
read_research_chronicle(action="narrate", chronicle_id="...", mode="brief")  # 每分支挑最高信心
read_research_chronicle(action="narrate", chronicle_id="...", mode="full")   # 全部 entry
```

輸出的**每一句 claim 都附 entry ID 與文獻識別碼**，可直接查證，適合寫作與報告。

---

## 常見錯誤

| 錯誤 | 正確做法 |
| --- | --- |
| 用 `build_research_timeline` | 已移除；改用 `build_research_chronicle` |
| 用 `output_format=` | 參數名是 `output=` |
| 直接 `action="compare"` 但沒先 build | 先對每個主題各 build 一次 |
| 把同年排列解讀成先後關係 | 只在日期 precision 足以證明時宣稱先後 |
| topic compare 回報 ambiguity | 先 `action="list"`，再傳兩個以上不同的 `chronicle_ids` |
| 忽略 audit warnings | 回答時要說明覆蓋率限制 |
| 每次都重新 build 來看里程碑 | 用 `action="milestones"` 讀已存的 |

---

## 相關 Skills

- `pubmed-quick-search` — 先找到文獻
- `pubmed-systematic-search` — 需要完整覆蓋時
- `pubmed-paper-exploration` — 從單篇論文往外探索
- `pubmed-export-citations` — 把 chronicle 的證據匯出成引用
