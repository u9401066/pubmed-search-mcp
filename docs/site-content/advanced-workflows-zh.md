<!-- Generated from docs/ADVANCED_RESEARCH_WORKFLOWS.zh-TW.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# 進階研究工作流

這頁把 docs site 導覽裡的核心進階工作流集中成同一個入口：**Research Chronicle（研究編年史與脈絡樹）**、**Open-i 圖片搜尋**、**上傳圖片 handoff**，以及**持久化 query memory**。

## 快速對照

| 需求 | 從這裡開始 | 接著使用 |
| --- | --- | --- |
| 看一個主題如何隨時間演進、分支與沉澱 | `build_research_chronicle` | `read_research_chronicle` |
| 用文字找生物醫學圖片（放射線、病理切片） | `search_biomedical_images` | `get_article_figures`, `unified_search` |
| 上傳圖片，依圖片視覺語意找相關文獻 | `analyze_figure_for_search` | `search_biomedical_images`, `unified_search` |
| 重新讀取大型搜尋/全文輸出，不重跑外部來源 | `read_session(action="artifact")` | `read_session(action="list_artifacts")` |

---

## 研究編年史 / Research Chronicle

![Research Chronicle 架構與脈絡流程](images/research-chronicle-lineage-flow.svg)

### 1. 核心設計理念與認識論模型

傳統文獻搜尋回傳的是「扁平的列表」，無法回答「這個領域如何從早期地基走向現代臨床應用？」、「關鍵分水嶺在哪裡？」以及「上次搜尋之後有什麼新進展？」。**Research Chronicle** 是 PubMed Search MCP 的核心研究演化系統：

- **以時序為主脊柱（X 軸）**：年代（Years）構成橫向主軸，串聯起整個領域的歷史演進。
- **以語意分支為組織維度（Y 軸）**：由多篇論文重複出現的 MeSH descriptors 與作者關鍵字自動聚類出研究路線（Research Lines），從該路線最早觀察到的文獻年份分岔展開。
- **單一事實來源（Single Source of Truth）**：所有輸出（時序、樹狀圖、心智圖、Mermaid、敘事、JSON）均來自同一份 `ChronicleSnapshot`，保證不同檢視角度絕不相互矛盾。如果只是想在一般搜尋回應裡看輕量分支預覽，可使用 `unified_search(options="context_graph")`（只根據本次 PMID-backed ranked set 產生 preview，而非完整的持久化編年史）。
- **不可變版本持久化（Immutable Revision Store）**：每次重跑同一主題或給定 `chronicle_id` 時，系統以原子鎖寫入 `Revision N+1`，支援版本比對（Diff）。
- **認識論嚴謹性（Epistemic Audit）**：文獻在不同版本中的缺席嚴格標記為 `not_observed_in_revision`（檢索範圍未觀察到），而非斷言該論文「被學界淘汰」；每份 Chronicle 皆附帶完整度審計報告（Audit）。

![評估與時間軸流程](images/timeline-evaluation-workflow.svg)

---

### 2. 兩大門面工具與輸出格式

#### 🛠️ `build_research_chronicle` — 建立或更新編年史

```python
# 1. 依主題建立（自動檢索 PubMed、計算 Landmark 分數並聚類分支）
build_research_chronicle(topic="remimazolam intraoperative", max_events=30)

# 2. 從既有搜尋結果或自訂 PMID 清單建立
build_research_chronicle(pmids="last", topic="My Reading List")
build_research_chronicle(pmids="32417976,34999964,36712948", topic="Selected Studies")

# 3. 延續既有編年史（自動繼承前版的 topic 與檢索範圍，建立 Revision N+1）
build_research_chronicle(chronicle_id="remimazolam-intraoperative-08c229f3")
```

#### 📖 `read_research_chronicle` — 讀取、比對與深度分析（不重跑搜尋）

| Action | 說明 | 適用情境與範例 |
| --- | --- | --- |
| `load` | 載入特定版本並以指定格式輸出（預設 latest） | `read_research_chronicle(chronicle_id="...", output="mermaid")` |
| `list` | 列出已保存的所有編年史清單與最新版本號 | `read_research_chronicle(action="list")` |
| `diff` | 比較兩個版本（新增、未觀察到、角色轉變、審計狀態） | `read_research_chronicle(action="diff", chronicle_id="...", from_revision=1)` |
| `milestones` | 統計條目分佈、歷年趨勢、證據品質與重大地基論文 | `read_research_chronicle(action="milestones", chronicle_id="...")` |
| `compare` | 橫向比對 2–5 個主題編年史（含共同證據分析） | `read_research_chronicle(action="compare", topics="remimazolam,propofol")` |
| `narrate` | 輸出帶有完整引用（PMID/DOI）的連貫學術敘事 Markdown | `read_research_chronicle(action="narrate", chronicle_id="...", mode="full")` |

#### 🎨 支援的 12 種輸出格式 (`output` 參數)

| 輸出格式 | 類型 | 說明與適用場景 |
| --- | :---: | --- |
| `summary` | Markdown | 緊湊摘要（預設）。包含時序主軸、研究分支列表與重大亮點。 |
| `mermaid` | 圖表 | **標準 X-Y 軸演化樹**。橫向年份軸 + 主題分支 + 論文區塊（Mermaid Flowchart LR）。 |
| `mindmap` | 圖表 | **研究分支心智圖**。放射狀展示主題聚類與重要文獻（Mermaid Mindmap）。 |
| `timeline_mermaid` | 圖表 | 平面時序圖（Mermaid Timeline 語法）。 |
| `chronicle_map` | JSON | 包含完整圖形座標契約的結構化 JSON（前端視覺化與繪圖專用）。 |
| `timeline` | JSON | 時序投影 JSON，依時間嚴格排列。 |
| `tree` | JSON | 樹狀分支投影 JSON，依主題與子主題層級組織。 |
| `graph` | JSON | 型別化 Provenance Graph（Topic → Branch → Entry → EvidenceArticle）。 |
| `evidence` | JSON | 去重後的完整證據論文清單與各來源計數。 |
| `milestones` | JSON | 里程碑統計、證據分佈、引用量統計與 Landmark 排名。 |
| `narrative` | Markdown | 具學術引用的結構化敘事文字。 |
| `json` | JSON | 包含所有欄位與原始資料的完整快照（Snapshot）。 |

---

### 3. 完整實例示範：Remimazolam 術中應用研究脈絡

以下以新型靜脈麻醉藥 **Remimazolam（瑞馬唑侖）於手術中麻醉與鎮靜** 為實例，展示各項視覺化與分析產出：

#### 範例 1：X 軸時間線 + Y 軸主題分支樹狀圖 (`output="mermaid"`)

```mermaid
flowchart LR
    n_topic["研究主題: Remimazolam 術中麻醉與鎮靜 (2020-2026)"]

    %% 橫向時間軸 (X-axis Time Spine)
    n_y2020["2020 年"]
    n_y2021["2021 年"]
    n_y2022["2022 年"]
    n_y2023["2023 年"]
    n_y2024["2024 年"]
    n_y2025["2025 年"]
    n_y2026["2026 年"]

    n_topic ==> n_y2020
    n_y2020 --> n_y2021
    n_y2021 --> n_y2022
    n_y2022 --> n_y2023
    n_y2023 --> n_y2024
    n_y2024 --> n_y2025
    n_y2025 --> n_y2026

    %% Y 軸研究主題分支 (Y-axis Lineage Branches)
    b_propofol["分支: Propofol 對比試驗與血流動力學 (24 篇)"]
    b_remi["分支: Remimazolam 適應症與專屬研究 (3 篇)"]
    b_general["分支: 全身麻醉與複雜心血管術式 (5 篇)"]
    b_sedatives["分支: 催眠鎮靜機制與腦電深度監測 (6 篇)"]
    b_benzo["分支: 苯二氮䓬類特性與特異性拮抗 (2 篇)"]

    %% 分支分岔時間點
    n_y2020 --> b_propofol
    n_y2021 --> b_remi
    n_y2022 --> b_sedatives
    n_y2024 --> b_general
    n_y2025 --> b_benzo

    %% 關鍵文獻區塊 (Entry Blocks)
    e_2020_phase2["[2020-08] Phase 2/3 Trial (PMID: 32417976)<br/>Doi et al. 全身麻醉療效不劣於 Propofol，低血壓發生率顯著降低"]
    e_2021_cardiac["[2021-03] Case Study (PMID: 33677710)<br/>心臟外科體外循環 (CPB) 麻醉初探"]
    e_2022_sedation["[2022-04] Observational Study (PMID: 34999964)<br/>全身麻醉期間腦電 (EEG/BIS) 鎮靜監測特徵"]
    e_2023_delirium["[2023-01] Safety Alert / RCT (PMID: 36712948)<br/>老年骨科手術術後譫妄 (Delirium) 預防效果"]
    e_2023_sleep["[2023-08] RCT (PMID: 37055671)<br/>術中應用改善老年全膝置換術後睡眠品質"]
    e_2024_rct["[2024-03] RCT (PMID: 38541158)<br/>胸腔鏡與腹腔鏡微創手術血流動力學穩定性"]
    e_2024_meta["[2024-07] Meta-Analysis (PMID: 39069837)<br/>複雜手術對比丙泊酚安全性統合分析"]
    e_2025_sr["[2025-01] Systematic Review (PMID: 39832842)<br/>圍術期器官保護與神經認知結局回顧"]
    e_2025_tavi["[2025-03] RCT (PMID: 39715979)<br/>經導管主動脈瓣置換術 (TAVI) 對比 Sevoflurane"]
    e_2026_seizure["[2026] Clinical Cohort (PMID: 42299573)<br/>清醒開顱手術 (Awake Craniotomy) 術中癲癇發生率比較"]

    %% 連接關鍵論文至其分支與時間軸
    b_propofol --> e_2020_phase2
    b_remi --> e_2021_cardiac
    b_sedatives --> e_2022_sedation
    b_propofol --> e_2023_delirium
    b_remi --> e_2023_sleep
    b_propofol --> e_2024_rct
    b_propofol --> e_2024_meta
    b_propofol --> e_2025_sr
    b_general --> e_2025_tavi
    b_sedatives --> e_2026_seizure

    n_y2020 -.-> e_2020_phase2
    n_y2021 -.-> e_2021_cardiac
    n_y2022 -.-> e_2022_sedation
    n_y2023 -.-> e_2023_delirium
    n_y2024 -.-> e_2024_meta
    n_y2025 -.-> e_2025_tavi
    n_y2026 -.-> e_2026_seizure

    %% 樣式設定
    classDef topic fill:#0f172a,color:#ffffff,stroke:#0f172a,stroke-width:2px;
    classDef spine fill:#dbeafe,color:#1e3a8a,stroke:#2563eb,stroke-width:2px;
    classDef branch fill:#ecfeff,color:#164e63,stroke:#0891b2,stroke-width:2px;
    classDef event fill:#ffffff,color:#111827,stroke:#94a3b8,stroke-width:1px;
    classDef landmark fill:#fef3c7,color:#92400e,stroke:#f59e0b,stroke-width:2px;

    class n_topic topic;
    class n_y2020,n_y2021,n_y2022,n_y2023,n_y2024,n_y2025,n_y2026 spine;
    class b_propofol,b_remi,b_general,b_sedatives,b_benzo branch;
    class e_2021_cardiac,e_2022_sedation,e_2023_delirium,e_2023_sleep,e_2024_rct,e_2025_tavi,e_2026_seizure event;
    class e_2020_phase2,e_2024_meta,e_2025_sr landmark;
```

---

#### 範例 2：研究分支心智圖 (`output="mindmap"`)

```mermaid
mindmap
  root["Remimazolam 術中應用研究脈絡"]
    branch_propofol["Propofol 對比試驗"]
      entry_p1["2020 — Phase 2b/3 關鍵地基試驗 (PMID: 32417976)"]
      entry_p2["血流動力學: 低血壓發生率顯著降低"]
      entry_p3["注射痛 (Injection Pain) 顯著減少"]
      entry_p4["2024-2025 多中心 Meta-Analysis 統合分析"]
    branch_neuro["麻醉深度與神經監測"]
      entry_n1["EEG / BIS 腦電雙頻指數監測指標"]
      entry_n2["術後譫妄 (Delirium) 發生率降低"]
      entry_n3["老年圍術期神經認知障礙 (PND) 改善"]
    branch_cardio["心血管與複雜手術"]
      entry_c1["經導管主動脈瓣置換術 (TAVI)"]
      entry_c2["體外循環冠狀動脈搭橋 (CABG)"]
      entry_c3["重症高風險患者全身麻醉管理"]
    branch_antidote["甦醒管理與特異性拮抗"]
      entry_a1["Flumazenil (氟馬西尼) 特異性快速逆轉"]
      entry_a2["甦醒期躁動 (Emergence Agitation) 評估"]
      entry_a3["組織羧酸酯酶 (CES-1) 水解特性"]
```

---

#### 範例 3：核心關鍵論文雙向引用網絡圖 (`build_citation_tree`)

以 2020 年奠基性臨床試驗 **Doi et al. (PMID: 32417976)** 為根節點，向前追蹤後續最新引用，向後回溯基礎藥理學奠基文獻：

```mermaid
graph TD
    %% Root Paper
    pmid_32417976(["<b>Doi Matsuyuki et al. (2020)</b><br/>Efficacy & safety of remimazolam vs propofol<br/>[PMID: 32417976 | Phase IIb/III 關鍵試驗]"])

    %% 後續前向引用 (Forward Citations - 最新臨床應用)
    pmid_42225960["Ni et al. (2026)<br/>體重調整劑量比例比較"]
    pmid_41987344["Kimura et al. (2026)<br/>小兒鎮靜與麻醉應用"]
    pmid_41954614["Morimoto et al. (2026)<br/>效應部位濃度監測 (Ce)"]
    pmid_41926002["Kotani et al. (2026)<br/>術後血流動力學與器官保護"]

    %% 基礎後向參考 (Backward References - 藥物研發與藥理地基)
    pmid_23653886("Chitilian et al. (2013)<br/>新型酯鍵代謝麻醉藥物研發")
    pmid_10215689("Tuk et al. (1999)<br/>GABAA 藥效動力學建模")
    pmid_22531340("Egan et al. (2012)<br/>代謝不穩定型新型鎮靜劑架構")

    %% 連線
    pmid_42225960 --> pmid_32417976
    pmid_41987344 --> pmid_32417976
    pmid_41954614 --> pmid_32417976
    pmid_41926002 --> pmid_32417976

    pmid_32417976 --> pmid_23653886
    pmid_32417976 --> pmid_10215689
    pmid_23653886 --> pmid_22531340

    %% 樣式
    style pmid_32417976 fill:#e74c3c,stroke:#c0392b,stroke-width:3px,color:#fff
    style pmid_42225960 fill:#3498db,stroke:#2980b9,color:#fff
    style pmid_41987344 fill:#3498db,stroke:#2980b9,color:#fff
    style pmid_41954614 fill:#3498db,stroke:#2980b9,color:#fff
    style pmid_41926002 fill:#3498db,stroke:#2980b9,color:#fff
    style pmid_23653886 fill:#2ecc71,stroke:#27ae60,color:#fff
    style pmid_10215689 fill:#2ecc71,stroke:#27ae60,color:#fff
    style pmid_22531340 fill:#2ecc71,stroke:#27ae60,color:#fff
```

---

#### 範例 4：跨主題橫向比較 (`action="compare"`)

比較 `remimazolam intraoperative`（新藥，2020–2026）與 `propofol intraoperative`（經典對照組，1991–2026）：

```json
{
  "projection": "comparison",
  "summary": {
    "earliest_research": 1991,
    "latest_research": 2026,
    "shared_evidence_count": 7
  },
  "shared_evidence": [
    { "evidence_id": "pmid:32417976", "shared_by": ["remimazolam", "propofol"] },
    { "evidence_id": "pmid:36712948", "shared_by": ["remimazolam", "propofol"] },
    { "evidence_id": "pmid:38494158", "shared_by": ["remimazolam", "propofol"] },
    { "evidence_id": "pmid:39832842", "shared_by": ["remimazolam", "propofol"] }
  ]
}
```

---

## Open-i 生醫圖片搜尋

當視覺 finding 已經被文字化，且目標是找 open biomedical image evidence 時，使用 `search_biomedical_images`。

```python
search_biomedical_images("chest X-ray pneumonia", sources="openi", image_type="x", limit=10)
search_biomedical_images("histology liver fibrosis", sources="openi", image_type="mc", license_type="by")
```

Open-i 需要英文醫學詞。中文或其他非英文提示應先由 agent 翻譯 anatomy、finding、modality，再呼叫 `search_biomedical_images`。Open-i 適合 radiology、microscopy、clinical photos、teaching images；如果要抓論文本身的圖表，請對 PMC Open Access 文章使用 `get_article_figures`。

---

## 上傳圖片到文獻搜尋

`analyze_figure_for_search` 是給 MCP client 上傳圖片或傳 image URL 時使用的 handoff tool。它接受 image URL 或 base64/data-URI image，回傳 MCP `ImageContent` 與給 LLM agent 的搜尋指令。

```python
analyze_figure_for_search(image="data:image/png;base64,...", search_type="medical")
```

Server 本身不做 standalone visual diagnosis。正確流程是：

1. MCP client 把上傳圖片或 image URL 傳給 `analyze_figure_for_search`。
2. LLM agent 用自己的 vision capability 判讀圖片，抽出英文 biomedical search terms。
3. Agent 接著呼叫 `search_biomedical_images` 找相似 biomedical images，或用 `unified_search` 找相關論文。

---

## 持久化 Query Memory

當 session persistence 有設定時，大型 `unified_search` 與 `get_fulltext` 輸出可以保存成 artifact。即時 tool response 可以保持精簡，同時把可重用 payload 留在 session artifact 裡。

```python
read_session(action="list_artifacts")
read_session(action="artifact", artifact_id="...")
read_session(action="artifact", artifact_uri="artifact://...")
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="audit.json")
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="results.json", offset=0, max_chars=200000)
```

Artifact 是 query memory，不是第二次搜尋。讀取 artifact 不會重跑外部 source calls。Local filesystem paths 預設會被遮蔽，因為 remote client 不能讀 MCP server host path。只有本機 MCP client 真的需要 `local_path` 與 `manifest_path` 時，才設定 `PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS=true`。

對 `unified_search` 來說，artifact files 會比即時 MCP response 更完整。建議先讀 `audit.json` 看完整性警告，再讀 `query_strategy.json` 檢查實際來源與搜尋策略，最後用 `results.json` 或 `results.toon` 取回完整文章清單。這能節省 response token，也讓 agent、sandbox client 與未來遠端 artifact backend 都能重複讀取同一份 evidence。

---

## 驗證狀態

目前 primary 45-tool MCP server 直接暴露這些功能：

- Research chronicle: `build_research_chronicle`, `read_research_chronicle`
- Image search: `search_biomedical_images`
- 上傳圖片 handoff: `analyze_figure_for_search`
- Query memory: `read_session(action="artifact")`

這些功能有 docs alignment tests、tool registry tests、image-search tests、vision-search tests、timeline tests、session artifact tests 守住。
