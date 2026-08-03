---
name: pubmed-research-chronicle
description: "Persistent, versioned research evolution with build_research_chronicle. Triggers: 研究脈絡, 研究演變, 研究編年史, research chronicle, 領域怎麼演進, 上次之後有什麼新的, 追蹤主題, 里程碑, milestone, timeline, 主題比較"
---

# 研究編年史指南

## 描述

`build_research_chronicle` 是研究演化的**唯一入口**，取代了舊的三個 timeline 工具。

和一次性快照最大的差別：chronicle 會以**遞增 revision 持久化儲存**。之後重跑同一個主題會產生 revision N+1，就能做版本比對，回答「上次之後改變了什麼」。

主軸是**時序（線性）**，分支 (lineage) 是**次要組織維度**。兩者都是同一份 snapshot 的投影，所以 `output="timeline"` 和 `output="tree"` 永遠不會互相矛盾。

---

## 快速決策樹

```text
使用者問研究演化？
├── 「這個領域怎麼走到今天」 → build_research_chronicle(topic="...")
├── 「把我剛剛找的整理成脈絡」 → build_research_chronicle(pmids="last", topic="...")
├── 「上次之後有什麼新的」 → read_research_chronicle(action="diff", chronicle_id="...", from_revision=N)
├── 「哪些是里程碑 / 領域分佈」 → read_research_chronicle(action="milestones", chronicle_id="...")
├── 「A 和 B 兩個主題比較」 → read_research_chronicle(action="compare", topics="A,B")
└── 「幫我寫成一段敘述」 → read_research_chronicle(action="narrate", chronicle_id="...", mode="full")
```

---

## 建立與更新

```python
# 建立（重跑同一主題會自動產生 revision N+1）
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
| `timeline` | 時序投影 JSON |
| `tree` | 研究脈絡樹 JSON（分支式演化） |
| `graph` | 型別化 provenance graph（證據溯源） |
| `evidence` | 去重後的證據表 |
| `milestones` | 里程碑分佈與證據品質統計 |
| `mermaid` / `mindmap` | 可直接在 VS Code / GitHub 預覽 |
| `narrative` | 有證據支撐的敘述 |
| `json` | 完整 snapshot |

不論 `output` 選哪個，完整 snapshot、所有投影、證據表、里程碑分析與 audit **一律**寫入 artifact。

---

## 讀取與比對

```python
# 列出已儲存的 chronicles
read_research_chronicle(action="list")

# 讀取某個版本（預設最新）
read_research_chronicle(chronicle_id="remimazolam-9f2b1c4d", output="tree")
read_research_chronicle(chronicle_id="remimazolam-9f2b1c4d", revision=2, output="timeline")

# 版本比對：新增/退場/更新的 entries、證據與分支變化
read_research_chronicle(action="diff", chronicle_id="remimazolam-9f2b1c4d", from_revision=1)

# 里程碑分佈（讀已存證據，不重跑搜尋）
read_research_chronicle(action="milestones", chronicle_id="remimazolam-9f2b1c4d")

# 主題比較（含共用證據分析，最多 5 個）
read_research_chronicle(action="compare", topics="remimazolam,propofol,dexmedetomidine")
```

> `compare` 與 `milestones` 都只讀已儲存的 chronicle，**不會重跑搜尋**。
> 若某個主題還沒建立過，會回傳明確的錯誤告訴你要先 build 哪一個。

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

---

## Audit：知道這份脈絡有多完整

每次 build 都會產生 audit，回報：

- 證據覆蓋率（有沒有 entry 缺證據）
- 識別碼覆蓋率（有沒有文章缺 PMID/DOI/PMCID）
- 分支覆蓋率（空分支、未分派 entry）
- graph 完整性（invariant 違反）
- 時序缺口（無法定年的 entry）
- 各來源回傳量

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
| 忽略 audit warnings | 回答時要說明覆蓋率限制 |
| 每次都重新 build 來看里程碑 | 用 `action="milestones"` 讀已存的 |

---

## 相關 Skills

- `pubmed-quick-search` — 先找到文獻
- `pubmed-systematic-search` — 需要完整覆蓋時
- `pubmed-paper-exploration` — 從單篇論文往外探索
- `pubmed-export-citations` — 把 chronicle 的證據匯出成引用
