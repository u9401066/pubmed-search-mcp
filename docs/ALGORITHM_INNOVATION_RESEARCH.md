# PubMed Search MCP — 演算法創新差距分析與提升研究

> [!CAUTION]
> **歷史／已取代的內部研究草稿。** 本文件反映 2026-02-15 的設計盤點；其中
> timeline 模組路徑、待建工具與「第一篇」規則不是 v0.6.2 的現行契約。
> 現行入口是 `build_research_chronicle(...)`，已儲存的里程碑與主題比較使用
> `read_research_chronicle(action="milestones")`／
> `read_research_chronicle(action="compare")`。Chronicle 的起點語意是
> `earliest_observed_in_scope`，不證明整個領域的 first report。下文保留作
> 演算法研究與產品決策沿革，不應當成目前工具參考。

> **文件性質**: 內部研究文件  
> **狀態**: 初稿 v1.3  
> **目的**: 誠實評估現有演算法深度，識別學術創新機會，規劃提升路線  
> **建立日期**: 2026-02-12  
> **最後更新**: 2026-02-15  
> **維護者**: Eric

---

## 📋 目錄

1. [動機與背景](#1-動機與背景)
2. [根本痛點：結果不可消化 × 搜尋間無記憶](#2-根本痛點結果不可消化--搜尋間無記憶)
3. [現狀誠實評估](#3-現狀誠實評估)
4. [學術創新機會](#4-學術創新機會)
5. [搜尋詞差異分析：演算法深入探討](#5-搜尋詞差異分析演算法深入探討)
6. [實施路線圖](#6-實施路線圖)
7. [驗證方法論](#7-驗證方法論)
8. [相關文獻](#8-相關文獻)
9. [Technical Spec：Search Rank Fusion & Diff Engine](#9-technical-specsearch-rank-fusion--diff-engine)

---

## 1. 動機與背景

### 1.1 核心問題

> **「我們目前還有哪些是學術創新？只是包裝多個搜尋 API 並且讓 Agent 使用就算？搜尋方法也是擴充關鍵字 + 通用字詞 — 有演算法可以更高效的找出搜尋詞之間的差異？」**

這是一個必須誠實面對的問題。本文件旨在：

1. **客觀盤點**現有系統中哪些組件有演算法深度、哪些只是 API 包裝
2. **識別差距**與學術水準的資訊檢索（IR）研究之間的距離
3. **提出具體演算法**可以帶來真正的學術創新
4. **聚焦搜尋詞差異分析**作為一個被忽視但高價值的方向

### 1.2 競品對比中的定位

| 工具 | 多源整合 | 演算法排序 | 引用分析 | 搜尋詞分析 | 時間軸 |
|------|:--------:|:---------:|:--------:|:---------:|:------:|
| paper-search-mcp (643★) | ✅ 8源 | ❌ | ❌ | ❌ | ❌ |
| BioMCP (413★) | ✅ 10源 | ❌ | ❌ | ❌ | ❌ |
| papersgpt-for-zotero (2k★) | ❌ | ✅ BM25 | ❌ | ❌ | ❌ |
| zotero-mcp (751★) | ❌ | ✅ Embeddings | ❌ | ❌ | ❌ |
| **PubMed-Search-MCP** | ✅ 6源 | ⚠️ term overlap | ⚠️ BFS only | ❌ | ✅ |

**結論**：我們在多源整合和時間軸上領先，但**排序演算法和引用分析是明確弱點**。

---

## 2. 根本痛點：結果不可消化 × 搜尋間無記憶

> **「搜尋返回了 10,000 篇結果 — Agent 也不可能馬上讀完；換一個搜尋詞返回 5,000 篇 — Agent 也不知道差異。所以每次的搜尋只是在不同的大海中撈針！」**

在討論演算法升級之前，必須先面對一個更根本的問題：**即使排序做到完美，Agent 也無法消化大量結果，而多輪搜尋之間沒有認知連續性**。這比「排序不夠好」更根本、更致命。

### 2.1 痛點解剖：三個層次的問題

#### 痛點 1：結果不可消化（Information Overload）

```
現狀的荒謬：

搜尋 "remimazolam sedation" → 10,247 篇
  ├── PubMed API 返回前 100 篇 PMID
  ├── 我們 fetch 前 20 篇的 title + abstract
  ├── Agent 的 context window 能裝 ~10 篇完整 abstract
  └── Agent 實際「看到」的：10 / 10,247 = 0.097%

問題：
  ① 99.9% 的搜尋結果是「不存在」的 — Agent 完全不知道它們
  ② 前 10 篇不一定是「最該看的」 — PubMed 的 relevance 是全域排名，不針對你的研究問題
  ③ 10 篇的 title + abstract 也是線性列表 — Agent 沒有全局概覽
  ④ Agent 無法回答「這個領域大概在研究什麼？」只能回答「這 10 篇在研究什麼」
```

**量化問題的嚴重度**：

| 搜尋結果量 | Agent 實際看到 | 覆蓋率 | 遺漏風險 |
|:----------:|:--------------:|:------:|:--------:|
| 100 篇 | 10 篇 | 10% | 中 |
| 1,000 篇 | 10 篇 | 1% | 高 |
| 10,000 篇 | 10 篇 | 0.1% | 極高 |
| 100,000 篇 | 10 篇 | 0.01% | 近乎隨機 |

當結果超過 1,000 篇時，Agent 展示給用戶的 10 篇本質上是**一個未經驗證的抽樣**，而非有意義的精選。

#### 痛點 2：搜尋間無認知連續性（No Cross-Search Memory）

```
場景：研究者進行 3 輪搜尋

第 1 輪: "remimazolam sedation"          → 10,247 篇 → Agent 看 10 篇
第 2 輪: "CNS 7056 ICU"                  →  5,123 篇 → Agent 看 10 篇
第 3 輪: "remimazolam vs propofol safety" →  3,456 篇 → Agent 看 10 篇

問題：
  ① 第 2 輪的 10 篇中，可能有 6 篇第 1 輪已經看過 → 浪費 60% 的 context
  ② 第 1 輪有 10,247 篇、第 2 輪有 5,123 篇，重疊多少？— 不知道
  ③ 第 2 輪找到了什麼「新的」？— 不知道
  ④ 三輪搜尋加起來覆蓋了多少獨立文章？— 不知道
  ⑤ 還有哪些面向沒搜到？— 完全不知道
```

**現有 Session 系統的不足**：

目前的 `SessionManager`（`application/session/manager.py`）儲存了：

| 有存 | 沒存 |
|------|------|
| ✅ 搜尋歷史（query + PMIDs） | ❌ 跨搜尋 PMID 重疊分析 |
| ✅ 文章快取（避免重複 API 呼叫） | ❌ 搜尋結果的主題分布 |
| ✅ 閱讀清單 | ❌ 累積覆蓋率追蹤 |
| ✅ 排除的 PMID | ❌ 搜尋策略差異報告 |
| | ❌ 「還有什麼沒搜過」的缺口分析 |

Session 的定位是「避免重複 API 呼叫」，而非「跨搜尋認知整合」。它記住了「找過什麼」，但不分析「找到的東西之間有什麼關係」。

#### 痛點 3：排序與研究問題脫節（Relevance ≠ Usefulness）

```
PubMed 的 "relevance" 排序：
  - 基於 query-document 文字匹配（TF-IDF 變體）
  - 全域排名 — 對所有人、所有問題都一樣
  - 不考慮：你的研究階段、已讀文章、研究假設

我們的六維排序：
  - 加入了 quality、recency、impact、source_trust、entity_match
  - 但 relevance 維度依舊用 term overlap（和 PubMed 本質相同）
  - 排序結果仍是一個線性列表 — 沒有結構、沒有分群

根本問題：
  "排序" 假設用戶要看一個有序列表
  但用戶真正需要的是 "理解這個領域的結構"

  ╔══════════════════════════════════════════════════════════════╗
  ║  列表思維：                                                  ║
  ║    1. Paper A (score: 0.95)                                  ║
  ║    2. Paper B (score: 0.93)  ← 這和 A 研究同一個子主題       ║
  ║    3. Paper C (score: 0.91)  ← 這也是                        ║
  ║    4. Paper D (score: 0.89)  ← 這討論完全不同的面向，更有價值 ║
  ║                                                              ║
  ║  結構思維：                                                  ║
  ║    Cluster 1（程序性鎮靜）：A, B, C → 代表作：A              ║
  ║    Cluster 2（ICU 長期鎮靜）：D, E → 代表作：D               ║
  ║    Cluster 3（安全性比較）：F, G, H → 代表作：F              ║
  ║    → Agent 看 3 篇代表作就覆蓋 3 個面向（vs 看前 3 名只覆蓋 1 個）║
  ╚══════════════════════════════════════════════════════════════╝
```

### 2.2 問題的學術定位

這三個痛點對應資訊科學的三個已知問題：

| 痛點 | 學術領域 | 經典問題名稱 | 已有方案 |
|------|---------|-------------|----------|
| 結果不可消化 | Information Retrieval | **Result Diversification** | MMR (Carbonell & Goldstein, 1998)、xQuAD (Santos et al., 2010) |
| 搜尋間無記憶 | Interactive IR | **Session Search** | TREC Session Track (2010-2014) |
| 排序與問題脫節 | Personalized IR | **Task-based Retrieval** | TREC Tasks Track (2015-2017) |

重要發現：**這三個問題在傳統 IR 中已有研究，但在 MCP/Agent 工具生態中完全沒有被實作**。這是真正的創新空間。

### 2.3 解法框架：從「列表返回」到「知識摘要」

核心思路轉變：

```
當前模式（List-oriented）：
  Query → API → 10,000 results → 取前 10 → 丟給 Agent → Agent 只知道 10 篇

目標模式（Knowledge-oriented）：
  Query → API → 10,000 results → MCP 預處理 → 結構化知識包 → Agent 獲得全局視野
```

#### 解法 1：Result Digest（結果摘要）

把 10,000 篇壓縮成 Agent 能消化的**結構化知識包**：

```json
{
  "query": "remimazolam sedation",
  "total_results": 10247,

  "topic_clusters": [
    {
      "label": "程序性鎮靜（Procedural Sedation）",
      "count": 3200,
      "representative_pmids": ["PMID:111", "PMID:222"],
      "top_mesh_terms": ["Conscious Sedation", "Colonoscopy", "Endoscopy"],
      "year_range": "2017-2026",
      "trend": "growing"
    },
    {
      "label": "ICU 長期鎮靜",
      "count": 2100,
      "representative_pmids": ["PMID:333"],
      "top_mesh_terms": ["Intensive Care Units", "Respiration, Artificial"],
      "year_range": "2020-2026",
      "trend": "rapidly_growing"
    },
    {
      "label": "藥物動力學/藥理機制",
      "count": 1800,
      "representative_pmids": ["PMID:444"],
      "top_mesh_terms": ["GABA Modulators", "Pharmacokinetics"],
      "year_range": "2014-2023",
      "trend": "stable"
    }
  ],

  "must_read": [
    {"pmid": "PMID:555", "reason": "最高 RCR (8.2) 的 Meta-analysis", "rcr": 8.2},
    {"pmid": "PMID:666", "reason": "最多引用的 Phase III RCT", "citations": 450},
    {"pmid": "PMID:777", "reason": "最近(2025)的 Systematic Review", "year": 2025}
  ],

  "temporal_trend": {
    "first_publication": 2014,
    "peak_year": 2023,
    "current_trend": "plateau",
    "annual_counts": {"2014": 3, "2015": 8, "...": "...", "2025": 890, "2026": 124}
  },

  "evidence_pyramid": {
    "meta_analyses": 45,
    "systematic_reviews": 120,
    "rcts": 230,
    "observational": 3500,
    "case_reports": 2100,
    "other": 4252
  }
}
```

**技術方案**：MeSH term 共現矩陣 → 分群（k-means 或 hierarchical clustering）→ 每群取 iCite RCR 最高的作為代表

**不需要 ML 模型**：MeSH terms 已經是標準化分類，可以直接用於分群。

#### 解法 2：Search Delta（搜尋增量報告）

每次新搜尋時，自動與 Session 中所有先前搜尋做比較：

```
第 2 次搜尋 "CNS 7056 ICU" 完成後自動產生：

┌─────────────────────────────────────────────────────────┐
│  🔄 Search Delta Report                                 │
│  搜尋 #2 vs 累積結果                                     │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  📊 集合分析：                                           │
│  ├── 搜尋 #2 結果: 5,123 篇                              │
│  ├── 與搜尋 #1 重疊: 2,847 篇 (55.6%)                    │
│  ├── 搜尋 #2 新發現: 2,276 篇 ← 真正的增量價值           │
│  └── 累積獨立文章: 12,523 篇 (10,247 + 2,276)            │
│                                                          │
│  🆕 新發現的主題分布 (2,276 篇)：                        │
│  ├── 早期臨床前研究 (CNS 7056 命名時期): 812 篇           │
│  │   └── 代表: PMID:888 "CNS 7056: a novel..." (2014)    │
│  ├── 日本市場臨床數據: 623 篇                             │
│  │   └── 代表: PMID:999 "Remimazolam in Japanese..."      │
│  └── ICU 專科特異文獻: 841 篇                             │
│      └── 代表: PMID:101 "Prolonged sedation with..."      │
│                                                          │
│  ⚠️ 覆蓋缺口（尚未搜到的面向）：                         │
│  ├── 小兒科使用 (建議搜尋: "remimazolam pediatric")       │
│  ├── 肝腎功能不全 (建議: "remimazolam hepatic impairment")│
│  └── 與其他 benzodiazepines 比較 (建議: "remimazolam vs   │
│      midazolam")                                         │
│                                                          │
│  💡 建議：                                               │
│  搜尋 #2 主要補充了「早期研究」和「日本數據」。            │
│  如果研究重點是 ICU 鎮靜，建議下一輪搜尋聚焦             │
│  「肝腎功能不全患者」和「長期鎮靜安全性」。               │
└─────────────────────────────────────────────────────────┘
```

**技術方案**：

```python
# SessionManager 擴展
class SearchDeltaAnalyzer:
    """分析多輪搜尋之間的增量差異"""

    def analyze_delta(
        self,
        new_pmids: set[str],
        session: ResearchSession,
    ) -> SearchDeltaReport:
        # 1. 集合運算
        all_previous = set()
        for record in session.search_history:
            all_previous.update(record['pmids'])

        overlap = new_pmids & all_previous
        new_only = new_pmids - all_previous
        cumulative = all_previous | new_pmids

        # 2. 新發現的 MeSH 分布
        new_mesh_distribution = self._analyze_mesh_distribution(new_only)

        # 3. 覆蓋缺口推測
        #    - 從 MeSH tree 中找「相鄰但未覆蓋的子樹」
        gaps = self._detect_coverage_gaps(cumulative)

        return SearchDeltaReport(
            new_count=len(new_only),
            overlap_count=len(overlap),
            overlap_rate=len(overlap) / len(new_pmids),
            cumulative_total=len(cumulative),
            new_topic_distribution=new_mesh_distribution,
            coverage_gaps=gaps,
        )
```

#### 解法 3：Smart Top-K（多樣性選取）

取代「按分數取前 K」的線性選取，改用**分群後每群取代表**：

```
傳統 Top-10（同質化問題）：
  1. RCT:  remimazolam 程序性鎮靜 (score: 0.95)   ← Cluster 1
  2. RCT:  remimazolam 結腸鏡鎮靜 (score: 0.93)   ← Cluster 1
  3. RCT:  remimazolam 內視鏡鎮靜 (score: 0.91)   ← Cluster 1
  4. Meta:  remimazolam 程序性鎮靜 (score: 0.90)   ← Cluster 1
  5. RCT:  remimazolam 支氣管鏡 (score: 0.88)      ← Cluster 1
  ...前 5 名全是「程序性鎮靜」！其他面向完全缺失。

Smart Top-10（多樣性保證）：
  Cluster 1 (程序性鎮靜, 3200篇):
    1. PMID:AAA - Meta-analysis (最高 RCR)
    2. PMID:BBB - 最新 RCT (2025)
  Cluster 2 (ICU 鎮靜, 2100篇):
    3. PMID:CCC - Phase III (最高引用)
    4. PMID:DDD - 安全性分析
  Cluster 3 (藥理機制, 1800篇):
    5. PMID:EEE - 機制綜述
  Cluster 4 (安全性, 1500篇):
    6. PMID:FFF - 不良事件薈萃
  Cluster 5 (藥物比較, 1647篇):
    7. PMID:GGG - vs propofol meta-analysis
    8. PMID:HHH - vs midazolam RCT
  額外（跨群高影響力）：
    9. PMID:III  - 系統性回顧 (RCR=8.2)
    10. PMID:JJJ - FDA 審查文件
  → Agent 看 10 篇就覆蓋 5 個面向！
```

**技術方案**：**Maximal Marginal Relevance (MMR)**（Carbonell & Goldstein, 1998）

$$\text{MMR} = \arg\max_{d_i \in R \setminus S} \Big[ \lambda \cdot \text{Sim}(d_i, q) - (1-\lambda) \cdot \max_{d_j \in S} \text{Sim}(d_i, d_j) \Big]$$

其中：
- $R$ = 候選文件集合（搜尋結果）
- $S$ = 已選文件集合（目前的 top-K）
- $\lambda$ = relevance 和 diversity 的平衡參數（0.5-0.7）
- $\text{Sim}(d_i, q)$ = 文件與查詢的相關性
- $\text{Sim}(d_i, d_j)$ = 文件之間的相似度

每次選一篇**既與查詢相關、又與已選文件不同**的文章，自然保證了多樣性。

在生醫領域，$\text{Sim}(d_i, d_j)$ 可以用 **MeSH term 共現** 來計算（不需要嵌入模型）：

```python
def mesh_similarity(article_a, article_b) -> float:
    """基於 MeSH terms 的文章相似度"""
    mesh_a = set(article_a.mesh_terms)
    mesh_b = set(article_b.mesh_terms)
    if not mesh_a or not mesh_b:
        return 0.0
    return len(mesh_a & mesh_b) / len(mesh_a | mesh_b)  # Jaccard
```

#### 解法 4：Cumulative Coverage Tracker（累積覆蓋率追蹤）

回答「搜全了沒？」這個關鍵問題。

```
搜尋進度儀表板：

┌─────────────────────────────────────────────────────────┐
│  📈 Research Coverage Dashboard                          │
│  主題: remimazolam                                       │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  累積搜尋: 3 次 | 累積獨立文章: 14,789 篇                │
│                                                          │
│  MeSH 子樹覆蓋率:                                        │
│  ├── D03.383.129 (Benzodiazepines)     ████████████ 95%  │
│  ├── E01.370.225 (Conscious Sedation)  ████████░░░░ 72%  │
│  ├── E03.155.197 (Critical Care)       ██████░░░░░░ 55%  │
│  ├── C23.888.592 (Drug-Related Effects)████░░░░░░░░ 38%  │
│  └── E05.318.308 (Clinical Trials)     ███░░░░░░░░░ 28%  │
│                                                          │
│  ⚠️ 低覆蓋面向:                                         │
│  ├── N05.300 (Health Services)              ░░░░░░ 5%    │
│  ├── F02.463.425 (Learning/Memory)          ░░░░░░ 3%    │
│  └── G07.690.773 (Pharmacokinetics, 特殊族群)░░░░░ 2%    │
│                                                          │
│  建議下一步搜尋:                                         │
│  "remimazolam pharmacokinetics special populations"       │
│  "remimazolam cognitive outcomes"                         │
└─────────────────────────────────────────────────────────┘
```

**技術方案**：

1. 取得搜尋主題在 MeSH 樹中的**相關子樹**（例如 "remimazolam" 的 MeSH 鄰域）
2. 追蹤累積搜尋結果覆蓋了哪些 MeSH terms
3. 計算每個子樹的覆蓋率 = 已找到的文章含此 MeSH / 該 MeSH 下的已知文章總數
4. 低覆蓋的子樹 → 自動建議搜尋策略

### 2.4 四個解法的比較與優先級

| 解法 | 解決痛點 | 技術難度 | 依賴 | Agent 價值 | 論文潛力 | 優先級 |
|------|---------|:--------:|------|:----------:|:--------:|:------:|
| **Search Delta** | 搜尋間無記憶 | ⭐ 低 | Session 系統已有基礎 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | 🥇 第一 |
| **Smart Top-K (MMR)** | 結果同質化 | ⭐⭐ 低-中 | MeSH terms 已有 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 🥈 第二 |
| **Result Digest** | 結果不可消化 | ⭐⭐⭐ 中 | MeSH 分群 + iCite | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 🥉 第三 |
| **Coverage Tracker** | 不知搜全沒 | ⭐⭐⭐⭐ 中-高 | MeSH 樹結構 + 統計 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 第四 |

**推薦路線**：Search Delta → Smart Top-K → Result Digest → Coverage Tracker

理由：
- **Search Delta** 投入最少（Session 已存 PMID）、效果最直接（Agent 立即知道「新發現了什麼」）
- **Smart Top-K (MMR)** 改善最明顯的痛點（前 10 篇不再是同類文章的重複）
- **Result Digest** 需要實作 MeSH 分群，但提供「全局視野」
- **Coverage Tracker** 最有學術深度，但需要 MeSH 樹結構和統計模型

### 2.5 這些解法與 §4-§6 演算法的關係

痛點分析（本節）和演算法創新（§4-§6）是**互補的兩個維度**：

```
                    演算法深度
                       ↑
        §4 BM25+RRF    │    §4 Citation Burst
        §4 PRF         │    §4 Main Path
                       │
     ───────────────────┼───────────────────→ 架構創新
                       │
        現狀           │    §2 Search Delta
        (term overlap, │    §2 Smart Top-K (MMR)
         線性 top-10)  │    §2 Result Digest
                       │    §2 Coverage Tracker

  左下角 = 現狀（淺演算法 + 線性列表）
  右下角 = 架構創新（改變結果呈現方式，但演算法簡單）← 本節
  左上角 = 演算法升級（BM25 等，但仍返回列表）← §4-§6
  右上角 = 終極目標（BM25 排序 + MMR 多樣性 + 分群摘要 + 增量分析）
```

**關鍵洞察**：只做演算法升級（§4-§6）而不改結果呈現方式，Agent 仍然只看到 10 篇列表。只改呈現方式而不升級演算法，分群和排序品質不夠好。**兩者必須同時推進**。

### 2.6 對論文定位的影響

這個痛點分析可以成為論文（`paper-draft.md`）的**另一個核心貢獻**：

| 原有貢獻 | 本節新增貢獻 |
|---------|-------------|
| Research Timeline Construction | **Agent-Digestible Result Summarization** |
| Milestone Detection | **Cross-Search Delta Analysis** |
| Multi-Source Integration | **Diversity-Aware Top-K Selection (MMR)** |
| | **Cumulative Coverage Tracking** |

論文角度可以重新定義為：

> *「從 List-based Retrieval 到 Knowledge-oriented Retrieval：一個以 AI Agent 為中心的文獻檢索新範式」*

這比「多源整合 + 時間軸」更有學術深度，因為它挑戰了傳統 IR 的「返回排序列表」假設。

---

## 3. 現狀誠實評估

### 2.1 有演算法價值的組件

#### 2.1.1 Union-Find 去重（⭐⭐⭐ 最佳演算法選擇）

**位置**: `application/search/result_aggregator.py`

```
三通道匹配: DOI → PMID → 標題正規化
複雜度: O(n·α(n)) ≈ O(n)，比暴力 O(n²) 大幅改善
策略: STRICT / MODERATE / AGGRESSIVE 三級可調
合併: 基於 identifier 數量 + 元資料完整度 + 來源信任度
```

**評價**: 這是專案中最好的演算法選擇。Union-Find 在學術上是標準做法，但在 MCP 工具生態中極少見。

**限制**: 標題匹配是**精確匹配**（正規化後），無法處理微小差異（"vs" vs "versus"、拼寫變體）。

#### 2.1.2 六維加權排序（⭐⭐ 合理但偏簡單）

**位置**: `application/search/result_aggregator.py`

| 維度 | 演算法 | 權重 | 評價 |
|------|--------|:----:|------|
| **relevance** | term overlap（集合交集比例） | 0.25 | ❌ 最弱環節 — bag-of-words |
| **quality** | 文章類型查表 + 完整度 + OA加分 | 0.20 | ✅ 合理 |
| **recency** | 指數衰減 `0.5^(age/half_life)` | 0.15 | ✅ 標準做法 |
| **impact** | RCR sigmoid `rcr/(rcr+2)` + citation log10 | 0.20 | ✅ 好的飽和曲線 |
| **source_trust** | 來源信任查表 + 多源驗證加分 | 0.10 | ✅ 實用 |
| **entity_match** | PubTator3 實體在文章中出現比例 | 0.10 | ⚠️ 依賴外部 API |

**核心問題**: `relevance` 用 **純 term overlap**（bag-of-words），不考慮：
- 詞頻 (TF) — "cancer" 出現 10 次 vs 1 次
- 逆文件頻率 (IDF) — "the" vs "remimazolam" 的區分力
- 文件長度正規化 — 長 abstract 自然命中更多詞

#### 2.1.3 多策略深度搜尋（⭐⭐ 好的系統設計）

**位置**: `presentation/mcp_server/tools/unified.py`

```
策略: SemanticEnhancer 產生多個 SearchPlan → asyncio.gather() 並行執行
聯合召回率: 1 - ∏(1 - recall_i)  (概率並集)
加權精確度: Σ(precision_i × count_i) / total_count
```

**問題**: recall/precision 是**硬編碼估算值**（如 `expected_precision=0.7`），不是從結果計算的。

#### 2.1.4 六層漸進放寬（⭐⭐ 實用工程方案）

**位置**: `presentation/mcp_server/tools/unified.py`

```
Level 1: 移除進階篩選 (age_group, clinical_query)
Level 2: 移除年份限制
Level 3: 移除出版類型篩選 (RCT, Meta-analysis)  
Level 4: 移除 PubMed 欄位標籤 ([Title], [MeSH Terms])
Level 5: AND → OR
Level 6: 萃取核心關鍵字（最多 3 個）
```

**評價**: 搜尋引擎工程中常見的 query relaxation 策略，系統化做得不錯，但非學術創新。

#### 2.1.5 里程碑偵測（⭐⭐ 有效的規則引擎）

**位置**: `application/timeline/milestone_detector.py`

```
四級管線: 第一篇 → PubMed 出版物類型 → 標題正則 (17種) → 引用數閾值
證據等級: 映射到 Oxford CEBM Level 1-4
時期分組: Discovery → Clinical Development → Regulatory → Evidence Synthesis → Post-Market
```

**限制**:
- 引用閾值是**固定的**（≥500/200），不因領域調整
- 無法偵測「隱含的里程碑」（不含 "FDA" 但描述了批准的文章）
- 第一篇偵測依賴搜尋排序，可能不是真正最早的

### 2.2 本質上是 API 包裝的組件

| 組件 | 位置 | 實際做法 | 為什麼不算創新 |
|------|------|---------|---------------|
| **QueryAnalyzer** | `application/search/query_analyzer.py` | 硬編碼關鍵字集合 + 正則 | 零 NLP，學術上用 BioBERT 分類可達 95%+ |
| **SemanticEnhancer** | `application/search/semantic_enhancer.py` | PubTator3 autocomplete API 薄包裝 + 固定 5 種策略模板 | 只用 autocomplete（非 annotate），策略是靜態的 |
| **Citation Tree** | `presentation/mcp_server/tools/citation_tree.py` | BFS + 資料格式轉換 | 零圖論分析（沒有 PageRank、community detection） |
| **Similarity Scores** | `presentation/mcp_server/tools/unified.py` | `1.0 - (position × 0.9 / (total-1))` + source_boost | **名稱誤導** — 只是排名位置的線性轉換 |
| **precision/recall 估算** | 多處 | 硬編碼常數（如 0.7/0.5） | 非實測值，無統計意義 |
| **ICD-MeSH 轉換** | 各處 | 靜態查表映射 | 標準資料轉換 |
| **所有 Source Clients** | `infrastructure/sources/` | HTTP API → response mapping | 純資料中介層 |

### 2.3 現狀總結

```
┌─────────────────────────────────────────────────────────┐
│            PubMed Search MCP — 演算法深度分布             │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  API 包裝層        ████████████████████████  60%         │
│  (Source Clients, ICD, Similarity Scores)                │
│                                                          │
│  規則引擎          ████████████████         30%         │
│  (QueryAnalyzer, MilestoneDetector, Relaxation)         │
│                                                          │
│  演算法實作        ████                      10%         │
│  (Union-Find, 六維排序, 概率召回率)                       │
│                                                          │
│  學術創新          ░                          0%         │
│  (無突破性演算法)                                         │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

**一句話結論**：工程整合品質高，演算法深度不足。

---

## 4. 學術創新機會

### 4.1 Tier 1：高影響力 + 可發論文

#### 🏆 3.1.1 智能相關性排序：BM25 + Reciprocal Rank Fusion

**問題**: 現有 relevance 計算是 term overlap（bag-of-words），這是資訊檢索領域 1960 年代的水準。

**方案**: 兩階段升級

**Stage 1: BM25 (Okapi BM25)**

BM25 是資訊檢索的事實標準（Robertson & Zaragoza, 2009），考慮：
- **詞頻 (TF)**: 飽和曲線，避免高頻詞主導
- **逆文件頻率 (IDF)**: 稀有詞獲得更高權重
- **文件長度正規化**: 消除長文偏見

$$\text{BM25}(q, d) = \sum_{t \in q} \text{IDF}(t) \cdot \frac{f(t,d) \cdot (k_1 + 1)}{f(t,d) + k_1 \cdot (1 - b + b \cdot \frac{|d|}{avgdl})}$$

其中 $k_1=1.2$, $b=0.75$ 是標準參數。

```python
# 預估實作（~100 行）
from rank_bm25 import BM25Okapi

def bm25_relevance(query: str, articles: list[UnifiedArticle]) -> list[float]:
    """BM25 替代 term overlap 做相關性排序"""
    # 將每篇文章的 title + abstract 做 tokenization
    corpus = [tokenize(a.title + " " + (a.abstract or "")) for a in articles]
    bm25 = BM25Okapi(corpus)
    return bm25.get_scores(tokenize(query))
```

**Stage 2: Reciprocal Rank Fusion (RRF)**

多源結果合併時，用 RRF 替代「排名位置線性轉換」：

$$\text{RRF}(d) = \sum_{r \in R} \frac{1}{k + r(d)}$$

其中 $R$ 是各來源的排名列表，$k=60$ 是常數。

RRF 的優勢（Cormack et al., 2009）：
- **不需要分數校準** — 不同來源的分數量綱不同，RRF 只用排名
- **效果穩定** — 在 TREC 多次評測中表現優異
- **零訓練** — 不需要任何標註資料

```python
# 預估實作（~30 行）
def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],  # 各來源的 PMID 排名列表
    k: int = 60
) -> dict[str, float]:
    """RRF 融合多來源排名"""
    scores = {}
    for ranked in ranked_lists:
        for rank, pmid in enumerate(ranked, 1):
            scores[pmid] = scores.get(pmid, 0) + 1 / (k + rank)
    return dict(sorted(scores.items(), key=lambda x: x[1], reverse=True))
```

**預期效果**: 基於 TREC PM benchmark，BM25+RRF 相比 term overlap 預計提升 nDCG@10 達 **20-30%**。

**實作難度**: 低（`rank_bm25` 套件 + 30 行 RRF）

---

#### 🏆 3.1.2 引用網路進階分析：Main Path Analysis + Community Detection

**問題**: Citation Tree 目前只做 BFS 遍歷 + 格式轉換，沒有任何圖論分析。

**方案**: 三個經典引文學演算法

**Algorithm 1: Main Path Analysis (Hummon & Doreian, 1989)**

在引用網路中找出「研究發展的主幹道」—— 從該領域最初的論文到最新的論文之間，最重要的知識傳承路徑。

步驟：
1. 建構引用 DAG（有向無環圖）
2. 計算每條邊的 **Search Path Count (SPC)** 或 **Search Path Link Count (SPLC)**
3. 從 source（最早論文）到 sink（最新論文），選擇 SPC 最大的路徑

$$\text{SPC}(e_{ij}) = \text{paths}_{\text{source} \to i} \times \text{paths}_{j \to \text{sink}}$$

```python
# 概念（networkx 實作，~150 行）
import networkx as nx

def main_path_analysis(G: nx.DiGraph) -> list[str]:
    """找出引用網路中的研究主幹道"""
    # 1. 計算所有邊的 SPC
    spc = {}
    sources = [n for n in G if G.in_degree(n) == 0]
    sinks = [n for n in G if G.out_degree(n) == 0]

    for u, v in G.edges():
        paths_to_u = sum(nx.has_path(G, s, u) for s in sources)
        paths_from_v = sum(nx.has_path(G, v, s) for s in sinks)
        spc[(u, v)] = paths_to_u * paths_from_v

    # 2. 貪心追蹤最大 SPC 路徑
    main_path = greedy_forward_path(G, spc, sources)
    return main_path
```

**創新點**: 將引文學經典演算法首次整合進 AI Agent 可操作的 MCP 工具。Agent 可以直接告訴用戶「這個領域的研究主線是：A (2010) → B (2013) → C (2018) → D (2024)」。

**Algorithm 2: Community Detection (Louvain, Blondel et al. 2008)**

在引用/被引用網路中發現研究子社群：

```python
from networkx.algorithms.community import louvain_communities

def detect_research_communities(G: nx.Graph) -> list[set]:
    """發現引用網路中的研究子社群"""
    communities = louvain_communities(G, resolution=1.0)
    # 每個社群代表一個研究子領域
    return sorted(communities, key=len, reverse=True)
```

**Algorithm 3: PageRank**

找出引用網路中最「重要」的節點（不只是引用數最高）：

$$\text{PR}(p) = \frac{1-d}{N} + d \sum_{q \in B_p} \frac{\text{PR}(q)}{L(q)}$$

```python
pagerank = nx.pagerank(G, alpha=0.85)
key_papers = sorted(pagerank.items(), key=lambda x: x[1], reverse=True)[:10]
```

**實作難度**: 中（`networkx` 已有 Louvain 和 PageRank 實作，需要包裝和 MCP 工具化）

---

#### 🏆 3.1.3 Citation Burst Detection（引用突發偵測）

**問題**: Milestone Detection 用固定引用閾值（≥500/200），無法區分「穩定高引用」和「突然爆發」。

**方案**: Kleinberg (2003) Burst Detection

Kleinberg 模型將時間序列建模為一個**兩態自動機**：
- **正常態 (q=0)**: 引用以基本速率 $\hat{p}$ 到達
- **突發態 (q=1)**: 引用以加速速率 $s \cdot \hat{p}$ 到達（$s > 1$）

用 Viterbi 演算法找出最可能的狀態序列，識別突發時段。

$$\text{cost}(i, q) = -\ln \binom{d_i}{r_i} p_q^{r_i} (1-p_q)^{d_i - r_i}$$

其中 $d_i$ 是第 $i$ 時段的總文獻數，$r_i$ 是被引次數。

**應用場景**:
- 輸入：某主題每年被引次數序列 `[3, 5, 4, 7, 45, 120, 89, 30, 15, ...]`
- 輸出：突發時段 `[{start: 2019, end: 2021, strength: 4.2}]`
- 意義：「該領域在 2019-2021 年經歷了引用突發，可能對應重大發現或爭議」

```python
def detect_citation_bursts(
    yearly_citations: dict[int, int],
    s: float = 2.0,      # 突發速率倍數
    gamma: float = 1.0,  # 狀態切換懲罰
) -> list[BurstPeriod]:
    """Kleinberg burst detection on yearly citation counts"""
    years = sorted(yearly_citations.keys())
    counts = [yearly_citations[y] for y in years]

    # Viterbi on 2-state automaton
    states = viterbi_two_state(counts, s, gamma)

    # Extract burst periods (consecutive q=1 states)
    bursts = extract_burst_periods(years, states, counts)
    return bursts
```

**與現有 Milestone Detection 的結合**:

| | 現有方案 | + Burst Detection |
|---|---------|-------------------|
| 輸入 | 單篇文章的標題/類型 | 時間序列（整個領域） |
| 方法 | 正則匹配 | 統計模型 (HMM) |
| 能偵測 | 明確的事件（"FDA approved"） | 隱含的趨勢轉折 |
| 無法偵測 | 領域級趨勢變化 | 具體事件類型 |

兩者互補：Milestone 回答「發生了什麼」，Burst 回答「什麼時候領域突然關注」。

**實作難度**: 中（~200 行，Viterbi 演算法需要實作或使用 `burst_detection` 套件）

**論文潛力**: ⭐⭐⭐ 最高。「Agent-Assisted Citation Burst Detection for Research Milestone Discovery」可獨立發表。

---

### 4.2 Tier 2：中等影響力 + 工程提升

#### 🥈 3.2.1 Pseudo-Relevance Feedback (PRF)

**問題**: 查詢擴展只依賴 PubTator3 autocomplete → MeSH 映射 → 固定策略模板。

**方案**: Rocchio (1971) / Lavrenko-Croft (2001) 的 PRF：

1. 執行初始查詢，取前 $N$ 篇結果（假設它們是相關的，"pseudo-relevance"）
2. 從這些結果中提取**高 TF-IDF 的新詞彙**
3. 用新詞彙擴展查詢，重新搜尋

$$\vec{q}_{\text{new}} = \alpha \vec{q}_{\text{orig}} + \frac{\beta}{|D_r|} \sum_{d \in D_r} \vec{d}$$

實際擴展時不需要完整向量空間，只需：

```python
from collections import Counter
import math

def pseudo_relevance_feedback(
    original_query: str,
    top_results: list[UnifiedArticle],
    num_expansion_terms: int = 10,
    top_n: int = 10,
) -> str:
    """PRF: 從首輪搜尋的 top-N 結果中提取擴展詞"""
    # 1. 收集所有 top-N 文章的 title + abstract 詞彙
    doc_freqs = Counter()
    term_freqs = Counter()
    for article in top_results[:top_n]:
        text = f"{article.title} {article.abstract or ''}"
        terms = tokenize(text)
        unique_terms = set(terms)
        for t in terms:
            term_freqs[t] += 1
        for t in unique_terms:
            doc_freqs[t] += 1

    # 2. 計算 TF-IDF
    n_docs = len(top_results[:top_n])
    tfidf = {}
    for term, tf in term_freqs.items():
        idf = math.log(n_docs / (1 + doc_freqs[term]))
        tfidf[term] = tf * idf

    # 3. 排除原始查詢已有的詞 + 停用詞
    query_terms = set(tokenize(original_query))
    expansion = [
        (term, score) for term, score in tfidf.items()
        if term not in query_terms and term not in STOPWORDS and len(term) > 3
    ]
    expansion.sort(key=lambda x: x[1], reverse=True)

    # 4. 構建擴展查詢
    new_terms = [t for t, _ in expansion[:num_expansion_terms]]
    expanded_query = f"({original_query}) AND ({' OR '.join(new_terms)})"
    return expanded_query
```

**效果**: 學術文獻顯示 PRF 可提升 recall@100 達 **15-25%**，在生醫領域尤為有效。

**實作難度**: 低（~150 行，純統計方法）

---

#### 🥈 3.2.2 MinHash 模糊去重

**問題**: 標題匹配是精確匹配（正規化後），無法處理：
- "propofol vs dexmedetomidine" ≠ "propofol versus dexmedetomidine"
- "A randomized trial of X" ≠ "A randomised trial of X"（美式/英式拼寫）
- 副標題差異："X: a systematic review" vs "X — a systematic review"

**方案**: MinHash + LSH (Broder, 1997)

```python
from datasketch import MinHash, MinHashLSH

def fuzzy_dedup(articles: list[UnifiedArticle], threshold: float = 0.85):
    """MinHash LSH 模糊去重"""
    lsh = MinHashLSH(threshold=threshold, num_perm=128)

    for i, article in enumerate(articles):
        m = MinHash(num_perm=128)
        # Character n-grams (3-grams) 比 word-level 更抗拼寫變化
        title_normalized = normalize_title(article.title)
        for ngram in ngrams(title_normalized, n=3):
            m.update(ngram.encode('utf8'))
        lsh.insert(str(i), m)

    # 查詢每篇文章的近似重複
    duplicates = []
    for i, article in enumerate(articles):
        m = create_minhash(article.title)
        results = lsh.query(m)
        # results 包含所有 Jaccard ≥ threshold 的文章
        ...
```

**與現有 Union-Find 的整合**: MinHash 作為 Union-Find 的**第四通道**（DOI → PMID → Exact Title → **Fuzzy Title**），只在前三通道未命中時觸發。

**實作難度**: 低（`datasketch` 套件，~80 行）

---

#### 🥈 3.2.3 搜尋詞差異分析（Query Term Differentiation）

詳見 [§5 專節](#5-搜尋詞差異分析演算法深入探討)。

---

### 4.3 Tier 3：有用但偏工程

#### 🥉 3.3.1 Learning-to-Rank (LTR)

用現有六維特徵訓練 LambdaMART 模型：
- 訓練資料：iCite percentile 做弱監督（高 percentile = 高品質排名）
- 工具：`xgboost` + `scikit-learn`
- 問題：需要足夠的標註資料，冷啟動困難

**實作難度**: 高 | **優先級**: 低

#### 🥉 3.3.2 Dynamic Topic Models (DTM)

追蹤主題隨時間的語義演化（不只是文章數量）：
- 工具：`gensim.models.LdaSeqModel`
- 輸出：「2015 年此領域主要討論 A、B」→「2020 年轉向 C、D」

**實作難度**: 高 | **優先級**: 低

#### 🥉 3.3.3 SPECTER2 語意排序

Allen AI 的論文嵌入模型，專為文獻相似度設計：
- 需要下載模型（~400MB）
- 推論需要 GPU 或較長 CPU 時間
- 效果最好但部署門檻高

**實作難度**: 高 | **優先級**: 低

---

## 5. 搜尋詞差異分析：演算法深入探討

> 這是原始問題的核心：**有演算法可以更高效的找出搜尋詞之間的差異嗎？**

### 5.1 問題定義

目前的搜尋擴展流程：

```
用戶輸入 "remimazolam ICU sedation"
    → PubTator3 autocomplete 得到 MeSH ID
    → 固定策略模板: original / mesh_expanded / entity_semantic / fulltext_epmc / broad_tiab
    → 各策略獨立搜尋 → 結果合併
```

**問題**: 我們不知道：
1. 這些策略之間到底有多大差異？
2. 加入同義詞 "CNS 7056" 是否真的找到了不同的文章，還是高度重疊？
3. 用 "[MeSH Terms]" vs "[Title/Abstract]" 搜尋，各自的盲區在哪？

### 5.2 方案 A：搜尋結果集合差異分析（Set Difference Analysis）

**最直觀、最有價值的方法**。

給定兩個搜尋策略 $A$ 和 $B$（各返回一組文章 PMID），計算：

| 指標 | 公式 | 意義 |
|------|------|------|
| **Jaccard** 相似度 | $J(A,B) = \frac{|A \cap B|}{|A \cup B|}$ | 兩策略結果重疊度 |
| **A 獨佔率** | $\text{Excl}_A = \frac{|A \setminus B|}{|A|}$ | A 能找到但 B 找不到的比例 |
| **B 獨佔率** | $\text{Excl}_B = \frac{|B \setminus A|}{|B|}$ | B 能找到但 A 找不到的比例 |
| **對稱差異** | $\Delta(A,B) = |A \triangle B| = |A \setminus B| + |B \setminus A|$ | 兩策略的不同文章總數 |
| **增益率** | $\text{Gain}_{A \to B} = \frac{|B \setminus A|}{|A|}$ | 從策略 A 切換到 B，額外獲得的文章比例 |

**進階分析**: 對獨佔文章做 MeSH term 分布分析

```python
def analyze_strategy_difference(
    results_a: list[str],  # 策略 A 的 PMIDs
    results_b: list[str],  # 策略 B 的 PMIDs
    articles_cache: dict,  # PMID → article 快取
) -> StrategyDiffReport:
    """分析兩個搜尋策略的結果差異"""
    set_a, set_b = set(results_a), set(results_b)

    overlap = set_a & set_b
    only_a = set_a - set_b
    only_b = set_b - set_a

    # 基本統計
    jaccard = len(overlap) / len(set_a | set_b) if set_a | set_b else 0

    # MeSH 分布差異: 獨佔文章用了哪些 MeSH？
    mesh_only_a = extract_mesh_terms(only_a, articles_cache)
    mesh_only_b = extract_mesh_terms(only_b, articles_cache)
    mesh_unique_to_a = mesh_only_a - mesh_only_b  # A 獨有的 MeSH 主題
    mesh_unique_to_b = mesh_only_b - mesh_only_a  # B 獨有的 MeSH 主題

    # 發表年分布: 獨佔文章是新的還是舊的？
    years_only_a = [articles_cache[p].year for p in only_a if p in articles_cache]
    years_only_b = [articles_cache[p].year for p in only_b if p in articles_cache]

    return StrategyDiffReport(
        jaccard=jaccard,
        overlap_count=len(overlap),
        only_a_count=len(only_a),
        only_b_count=len(only_b),
        mesh_unique_to_a=mesh_unique_to_a,
        mesh_unique_to_b=mesh_unique_to_b,
        year_distribution_a=years_only_a,
        year_distribution_b=years_only_b,
        recommendation=generate_recommendation(jaccard, only_a, only_b),
    )

def generate_recommendation(jaccard, only_a, only_b) -> str:
    """根據分析結果生成建議"""
    if jaccard > 0.9:
        return "兩個策略高度重疊 — 建議只保留其中一個以節省 API 配額"
    elif jaccard > 0.6:
        return "中度重疊 — 兩策略互補，建議合併使用"
    elif jaccard < 0.3:
        return "低重疊 — 兩策略搜尋範圍差異大，可能需要檢查是否有一個過於偏離主題"
```

**MCP 工具化**:

```python
@mcp_tool
async def analyze_search_strategies(
    query_a: str,
    query_b: str,
    limit: int = 100,
) -> StrategyDiffReport:
    """分析兩個搜尋策略的差異：哪個找到了什麼、錯過了什麼"""
```

### 5.3 方案 B：MeSH 階層語意距離

MeSH 是一棵**有 18 個主要分支的階層樹**，可以計算任意兩個 MeSH 術語的語意距離。

```
Tree Structure (excerpt):
D - Chemicals and Drugs
├── D02 - Organic Chemicals
│   ├── D02.455 - Hydrocarbons
│   └── D02.886 - Sulfur Compounds
├── D03 - Heterocyclic Compounds
│   └── D03.383 - Heterocyclic, 1-Ring
│       └── D03.383.129 - Benzodiazepines
│           ├── ...remimazolam...
│           └── ...midazolam...
└── D27 - Chemical Actions and Uses
    └── D27.505 - Pharmacologic Actions
        └── D27.505.696 - Physiological Effects of Drugs
            └── ...propofol...
```

**距離計算方法**:

| 方法 | 公式 | 特點 |
|------|------|------|
| **Path Length** | $\text{dist}(a,b) = \text{shortest\_path}(a, b)$ | 最簡單，不考慮深度 |
| **Wu-Palmer** | $\text{sim}(a,b) = \frac{2 \cdot \text{depth}(\text{LCA})}{depth(a) + depth(b)}$ | 考慮最近公共祖先深度 |
| **Lin** | $\text{sim}(a,b) = \frac{2 \cdot IC(\text{LCA})}{IC(a) + IC(b)}$ | 基於 Information Content |
| **Resnik** | $\text{sim}(a,b) = IC(\text{LCA})$ | 只看 LCA 的 Information Content |

其中 LCA = Lowest Common Ancestor（最近公共祖先），$IC(c) = -\log P(c)$ 是語料庫頻率的信息量。

```python
# 使用 NCBI MeSH API 取得樹號
async def mesh_semantic_distance(
    term_a: str,
    term_b: str,
    method: str = "wu_palmer",
) -> float:
    """計算兩個 MeSH 術語的語意距離"""
    # 1. 查詢 MeSH 樹號
    tree_a = await get_mesh_tree_numbers(term_a)  # e.g., ["D03.383.129.xxx"]
    tree_b = await get_mesh_tree_numbers(term_b)  # e.g., ["D03.383.129.yyy"]

    # 2. 計算最近公共祖先
    lca = lowest_common_ancestor(tree_a, tree_b)

    # 3. Wu-Palmer 相似度
    if method == "wu_palmer":
        depth_lca = len(lca.split("."))
        depth_a = len(tree_a[0].split("."))
        depth_b = len(tree_b[0].split("."))
        return (2 * depth_lca) / (depth_a + depth_b)
```

**應用**: 當 SemanticEnhancer 產生多個同義詞時，計算它們之間的語意距離：
- 距離近（如 remimazolam 和 CNS 7056）→ 近同義詞，OR 連接即可
- 距離中（如 remimazolam 和 midazolam）→ 同類藥物，有意義的擴展
- 距離遠（如 remimazolam 和 propofol）→ 不同類別，比較性搜尋

### 5.4 方案 C：搜尋詞向量距離（BioWordVec）

使用預訓練的生醫詞向量計算搜尋詞之間的語意距離：

```python
# BioWordVec: Zhang et al. (2019), 基於 PubMed + MIMIC-III 訓練
import gensim

model = gensim.models.KeyedVectors.load("BioWordVec_PubMed_MIMICIII_d200.bin")

def query_semantic_distance(query_a: str, query_b: str) -> float:
    """計算兩個搜尋查詢的語意距離"""
    vec_a = average_word_vectors(tokenize(query_a), model)
    vec_b = average_word_vectors(tokenize(query_b), model)
    return cosine_similarity(vec_a, vec_b)
```

**問題**: 需要下載 ~4GB 的模型檔案，不適合輕量部署。

**替代方案**: 使用 NCBI API 線上計算語意相似度，或用更輕量的 TF-IDF 向量。

### 5.5 方案比較

| 方案 | 需要模型？ | 需要搜尋？ | 精確度 | 可解釋性 | 實作難度 |
|------|:---------:|:---------:|:------:|:--------:|:--------:|
| **A. 集合差異** | ❌ | ✅ 需執行搜尋 | ⭐⭐⭐ | ⭐⭐⭐ 最佳 | 低 |
| **B. MeSH 距離** | ❌ | ❌ | ⭐⭐ | ⭐⭐⭐ | 中 |
| **C. 詞向量** | ✅ 4GB | ❌ | ⭐⭐⭐ | ⭐ | 高 |

**推薦**: 先實作方案 A（集合差異），因為它：
1. 不需要模型
2. 結果最直觀、可解釋（「策略 A 比策略 B 多找到 15 篇關於 XXX 的文章」）
3. 可以直接整合進現有的 Deep Search 流程

然後用方案 B（MeSH 距離）做**先驗分析**（搜尋前判斷詞的差異有多大），方案 A 做**後驗分析**（搜尋後看結果差異有多大）。

---

## 6. 實施路線圖

### Phase A：快速勝利（1-2 週）— 無需 ML 模型

| # | 任務 | 替換目標 | 預估行數 | 依賴 |
|---|------|---------|:--------:|------|
| A1 | BM25 排序 | `_calculate_relevance()` 的 term overlap | ~100 | `rank_bm25` |
| A2 | Reciprocal Rank Fusion | `_enrich_with_similarity_scores()` | ~30 | 無 |
| A3 | Pseudo-Relevance Feedback | SemanticEnhancer 策略生成 | ~150 | 無 |
| A4 | MinHash 模糊去重 | Union-Find 第四通道 | ~80 | `datasketch` |

**Phase A 的驗證**: 選 10 個 TREC PM 主題，比較改進前後的 nDCG@10。

### Phase B：核心演算法（2-4 週）— 經典演算法實作

| # | 任務 | 新增 MCP 工具 | 預估行數 | 依賴 |
|---|------|-------------|:--------:|------|
| B1 | Main Path Analysis | `analyze_citation_network` | ~300 | `networkx` |
| B2 | Citation Burst Detection | 增強 `build_research_timeline` | ~200 | 無（自行實作 Viterbi） |
| B3 | MeSH 語意距離 | `compare_search_terms` | ~200 | NCBI MeSH API |
| B4 | 搜尋策略差異分析 | `analyze_search_strategies` | ~150 | 無 |
| B5 | Community Detection | 增強 `build_citation_tree` | ~100 | `networkx` |

**Phase B 的驗證**:
- Main Path: 與 CiteSpace 的 Main Path 結果交叉驗證
- Burst: 與 CiteSpace 的 Burst Detection 結果交叉驗證
- MeSH 距離: 與 UMLS Similarity 服務的結果相關性分析

### Phase C：ML 增強（4-8 週）— 需要模型

| # | 任務 | 預估行數 | 依賴 |
|---|------|:--------:|------|
| C1 | SPECTER2 語意排序 | ~400 | `transformers`, GPU |
| C2 | PubMedBERT 意圖分類 | ~300 | `transformers` |
| C3 | Dynamic Topic Models | ~500 | `gensim` |

### 里程碑

```
2026-02 ─── Phase A 開始 (BM25 + RRF + PRF + MinHash)
   │
2026-03 ─── Phase A 完成 + 驗證
   │        Phase B 開始 (Main Path + Burst + MeSH Distance)
   │
2026-04 ─── Phase B 完成 + 驗證
   │        論文 Evaluation 章節可撰寫
   │
2026-05 ─── Phase C (可選) + 論文投稿準備
```

---

## 7. 驗證方法論

### 7.1 排序品質（Phase A）

**Benchmark**: TREC Precision Medicine (2017-2020)

| 指標 | 說明 |
|------|------|
| **nDCG@10** | 前 10 名的 Normalized Discounted Cumulative Gain |
| **P@10** | 前 10 名的精確率 |
| **MAP** | Mean Average Precision |

**對比組**:
- Baseline: 現有 term overlap（bag-of-words）
- BM25: 僅 BM25
- BM25+RRF: BM25 排序 + 多源 RRF 融合
- BM25+RRF+PRF: 加入 Pseudo-Relevance Feedback

### 7.2 去重品質（Phase A）

**方法**: 人工標註 200 對跨來源文章（是否為同一篇）

| 指標 | 說明 |
|------|------|
| **Precision** | 被判定為重複的文章對中，真正重複的比例 |
| **Recall** | 所有真正重複的文章對中，被正確識別的比例 |
| **F1** | Precision 和 Recall 的調和平均 |

### 7.3 網路分析（Phase B）

**方法**: 選 5 個已被 CiteSpace 分析過的主題，比較結果一致性

| 指標 | 說明 |
|------|------|
| **Main Path 吻合率** | 系統找到的 main path 節點與 CiteSpace 結果的 Jaccard |
| **Burst 時段重疊** | burst period 的 temporal IoU (Intersection over Union) |
| **Community 一致性** | NMI (Normalized Mutual Information) |

### 7.4 搜尋策略差異（Phase B）

**方法**: 定性案例研究（5 個主題），展示差異分析如何幫助用戶理解搜尋結果

---

## 8. 相關文獻

### 資訊檢索 (Information Retrieval)

| 文獻 | 年份 | 貢獻 |
|------|:----:|------|
| Robertson & Zaragoza, "The Probabilistic Relevance Framework: BM25 and Beyond" | 2009 | BM25 演算法的權威綜述 |
| Cormack et al., "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods" | 2009 | RRF 的提出和驗證 |
| Rocchio, "Relevance Feedback in Information Retrieval" | 1971 | 相關性反饋的先驅工作 |
| Lavrenko & Croft, "Relevance-Based Language Models" | 2001 | PRF 的語言模型方法 |
| Broder, "On the Resemblance and Containment of Documents" | 1997 | MinHash 和文件相似度 |

### 引文學 (Bibliometrics)

| 文獻 | 年份 | 貢獻 |
|------|:----:|------|
| Hummon & Doreian, "Connectivity in a citation network" | 1989 | Main Path Analysis 的提出 |
| Liu & Lu, "An integrated approach for main path analysis" | 2012 | Main Path 的改進方法 |
| Blondel et al., "Fast unfolding of communities in large networks" | 2008 | Louvain 社群偵測算法 |
| Kleinberg, "Bursty and Hierarchical Structure in Streams" | 2003 | 突發偵測演算法 |
| Page et al., "The PageRank Citation Ranking" | 1999 | PageRank 演算法 |

### 語意相似度 (Semantic Similarity)

| 文獻 | 年份 | 貢獻 |
|------|:----:|------|
| Pedersen et al., "Measures of semantic similarity and relatedness in the biomedical domain" | 2007 | UMLS 語意相似度評估 |
| Resnik, "Using information content to evaluate semantic similarity in a taxonomy" | 1995 | IC-based 語意距離 |
| Lin, "An information-theoretic definition of similarity" | 1998 | Lin 相似度 |
| Wu & Palmer, "Verb semantics and lexical selection" | 1994 | Wu-Palmer 相似度 |

### 生醫 NLP (Biomedical NLP)

| 文獻 | 年份 | 貢獻 |
|------|:----:|------|
| Gu et al., "Domain-Specific Language Model Pretraining for Biomedical NLP" | 2021 | PubMedBERT |
| Singh et al., "SciRepEval: A Multi-Format Benchmark for Scientific Document Representations" | 2023 | SPECTER2 |
| Zhang et al., "BioWordVec: Improving Biomedical Word Embeddings" | 2019 | BioWordVec |

---

## 附錄 A：與既有 paper-draft.md 的關係

| paper-draft.md 定位 | 本文件定位 |
|--------------------|--------------------|
| 對外論文（投稿用） | 內部研究文件 |
| 聚焦 Timeline 功能 | 聚焦全面的演算法升級 |
| 已有架構但缺驗證 | 提供驗證方法論 |
| Abstract 已成形 | 補充核心 IR 演算法創新 |

**建議**: 論文的 Section 2 (Architecture) 可增加本文件的排序和去重演算法描述，Section 4 (Evaluation) 可採用本文件的驗證方法論。BM25+RRF 和 PRF 是論文中最容易量化展示的貢獻。

---

## 附錄 B：誠實風險評估

| 風險 | 嚴重度 | 對策 |
|------|:------:|------|
| BM25 已是 30 年前的演算法，reviewers 可能認為不夠新 | 中 | 結合 RRF + 多源 + 生醫領域定制，強調「系統層面的創新」 |
| Citation Burst 與 CiteSpace 功能重疊 | 中 | 強調「Agent-accessible」—— CiteSpace 是桌面軟體，我們是 API |
| 沒有真正的 ML 模型 | 低 | Phase A+B 完全不需 ML，反而是優勢（輕量部署、無 GPU 依賴） |
| MinHash 的 `datasketch` 增加部署體積 | 低 | datasketch 是純 Python，體積小 |
| MeSH 距離依賴 NCBI API 穩定性 | 低 | 可快取 MeSH 樹結構到本地 |

---
---

## 9. Technical Spec：Search Rank Fusion & Diff Engine

> **狀態**: 設計討論中 (v0.1)  
> **前置依賴**: 本文件 §2（痛點分析）、§4.1（BM25 + RRF）  
> **目標**: 將 §2 + §4.1 的理論方案落地為可實作的技術規格  
> **建立日期**: 2026-02-15

### 9.1 概述 (Overview)

本模組負責接收來自多個異質學術搜尋 API（如 OpenAlex, CrossRef, Europe PMC, Semantic Scholar, PubMed）的原始結果，執行**標準化、去重、排名融合（RRF）**，並與同一 Session 中的上一次搜尋狀態進行比對。最終輸出一個精簡的、具備「新穎性」與「趨勢性」的 JSON 報告給 AI Agent。

**核心價值**：解決 §2 識別的三大痛點 —— 結果不可消化、搜尋間無記憶、排序與研究問題脫節。

### 9.2 系統架構與資料流 (Architecture)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Fusion Engine Pipeline                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │ OpenAlex │  │ CrossRef │  │  Europe  │  │ Semantic │  ... more   │
│  │ Top 100  │  │ Top 100  │  │   PMC    │  │ Scholar  │             │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘            │
│       │              │              │              │                 │
│       ▼              ▼              ▼              ▼                 │
│  ┌─────────────────────────────────────────────────────┐            │
│  │  Stage 1: Normalization & Deduplication              │            │
│  │  UID = DOI > PMID > Title Hash                       │            │
│  │  Union-Find O(n) 去重 (現有 ResultAggregator 基礎)   │            │
│  └──────────────────────┬──────────────────────────────┘            │
│                         │ List[UnifiedDoc]                          │
│                         ▼                                           │
│  ┌─────────────────────────────────────────────────────┐            │
│  │  Stage 2: RRF Score Calculation                      │            │
│  │  RRF(d) = Σ 1/(k + rank_source(d))                  │            │
│  │  k = 60 (configurable)                               │            │
│  └──────────────────────┬──────────────────────────────┘            │
│                         │ Sorted by rrf_score                       │
│                         ▼                                           │
│  ┌─────────────────────────────────────────────────────┐            │
│  │  Stage 3: Quality Re-ranking (Optional)              │            │
│  │  Blend: α·rrf_score + (1-α)·quality_score            │            │
│  │  quality = f(recency, impact, article_type, ...)     │            │
│  └──────────────────────┬──────────────────────────────┘            │
│                         │ Final ranked list                         │
│                         ▼                                           │
│  ┌─────────────────────────────────────────────────────┐            │
│  │  Stage 4: Differential Analysis                      │            │
│  │  Compare with Session fusion_history[-1]             │            │
│  │  Categorize: NEW / HIGH_RISER / STAGNANT / DROPPING  │            │
│  └──────────────────────┬──────────────────────────────┘            │
│                         │                                           │
│                         ▼                                           │
│  ┌─────────────────────────────────────────────────────┐            │
│  │  Stage 5: Insight Generation                         │            │
│  │  global_consensus_new / high_risers / source_gems    │            │
│  └──────────────────────┬──────────────────────────────┘            │
│                         │                                           │
│                         ▼                                           │
│              AgentSummary (JSON) + Session Update                    │
└─────────────────────────────────────────────────────────────────────┘
```

### 9.3 資料結構定義 (Data Structures)

#### 9.3.1 原始輸入物件 (Raw Search Result)

```python
@dataclass
class RawSearchResult:
    """單一來源 API 返回的原始結果"""
    source: str          # e.g., "openalex", "crossref", "europe_pmc", "semantic_scholar"
    original_rank: int   # 1-based rank from API
    title: str
    doi: str | None      # Normalized DOI (lowercase, no prefix)
    pmid: str | None     # PubMed ID (如有)
    year: int | None
    snippet: str         # Title + abstract 前 200 字
```

> **與現有系統的關係**: 現有 `UnifiedArticle` 的工廠方法 (`from_openalex`, `from_crossref` 等) 已經做了大部分欄位映射。`RawSearchResult` 是 `UnifiedArticle` 的**精簡投影**，僅保留 RRF 融合所需的欄位。可以從 `UnifiedArticle` 直接建構。

#### 9.3.2 統一文檔物件 (Unified Document)

系統內部的處理單元，經去重後產生。

```python
@dataclass
class UnifiedDoc:
    uid: str                    # Unique ID (見 §9.4.1 UID 策略)
    title: str
    rrf_score: float            # Calculated RRF Score
    rrf_rank: int               # Final rank after RRF (1-based)
    sources: list[str]          # e.g., ["openalex:2", "crossref:5"]
    source_count: int           # len(unique sources) — 快速存取
    metadata: dict              # Merged metadata (year, authors, doi, pmid, etc.)
    quality_score: float | None # Optional: from Stage 3 re-ranking
    blended_score: float | None # Optional: α·rrf + (1-α)·quality
```

> **與現有系統的關係**: `UnifiedDoc` 不替代 `UnifiedArticle`，而是 RRF 融合流程的**中間產物**。最終結果仍轉換回 `UnifiedArticle` 返回給 MCP 工具層。

#### 9.3.3 Session 狀態擴展 (Fusion History)

**設計決策**: 不新建 `SessionState`，而是擴展現有 `ResearchSession`。

```python
@dataclass
class FusionTurn:
    """每一輪搜尋的 RRF 融合狀態快照"""
    query: str
    timestamp: float
    rank_map: dict[str, int]        # {uid: final_rank} — 僅 Top 100
    rrf_scores: dict[str, float]    # {uid: rrf_score} — 僅 Top 100
    source_breakdown: dict[str, int]  # {"openalex": 45, "crossref": 38, ...}
    total_fused: int                  # 去重後總數

class ResearchSession:
    # ... 現有欄位保持不變 ...
    # article_cache: dict[str, dict]
    # search_history: list[dict]
    # reading_list: dict[str, dict]
    # excluded_pmids: list[str]

    fusion_history: list[FusionTurn] = field(default_factory=list)  # ← 新增
```

> **記憶體控制**: `rank_map` 和 `rrf_scores` 僅儲存 Top 100（由 `TOP_N_PROCESS` 控制），每輪約 100 × 2 × 50 bytes ≈ 10 KB。即使 50 輪搜尋也僅佔 500 KB。

### 9.4 核心演算法邏輯 (Core Algorithms)

#### 9.4.1 UID 策略：三級識別符 (Normalization)

**目的**: 確保同一篇論文在不同 API 中被視為同一個實體。

**設計決策**: 採用 **DOI > PMID > Title Hash** 三級策略，與現有 `ResultAggregator` 的三通道匹配保持一致。

```python
import hashlib
import re

def compute_uid(article: RawSearchResult) -> str:
    """三級 UID 計算策略

    優先級:
    1. DOI — 全球唯一、跨來源標準化
    2. PMID — PubMed 穩定 ID，消除語言/特殊字元問題
    3. Title Hash — 最後手段，sha256(正規化標題)[:16]
    """
    if article.doi:
        # 移除前綴、小寫、去空格
        doi = article.doi.lower().strip()
        doi = re.sub(r'^https?://(dx\.)?doi\.org/', '', doi)
        return f"doi:{doi}"
    if article.pmid:
        return f"pmid:{article.pmid.strip()}"
    # Fallback: title hash
    normalized = re.sub(r'[^a-z0-9]', '', article.title.lower())
    title_hash = hashlib.sha256(normalized.encode()).hexdigest()[:16]
    return f"hash:{title_hash}"
```

**去重整合**: UID 相同的文章會被合併 — 新的 `source:rank` 追加到 `sources` 列表，metadata 做 union 合併（保留資訊量最豐富的欄位）。這與現有 `ResultAggregator` 的 Union-Find 邏輯一致。

#### 9.4.2 倒數排名融合 (Reciprocal Rank Fusion, RRF)

**目的**: 不依賴 API 的絕對分數（各來源分數量綱不同），僅依賴排名來計算權重。

**公式**:

$$\text{RRF}(d) = \sum_{s \in S_d} \frac{1}{k + \text{rank}_s(d)}$$

其中：
- $k = 60$（經驗常數，避免排名第 1 的權重過大）
- $S_d$ 是文件 $d$ 出現的來源集合
- $\text{rank}_s(d)$ 是文件 $d$ 在來源 $s$ 中的排名（1-based）

**Implementation**:

```python
def reciprocal_rank_fusion(
    source_rankings: dict[str, list[str]],  # {source_name: [uid1, uid2, ...]}
    k: int = 60,
) -> dict[str, float]:
    """RRF 融合多來源排名

    Args:
        source_rankings: 每個來源的 UID 排名列表 (1-based implicit)
        k: 平滑常數 (預設 60)

    Returns:
        {uid: rrf_score}，由高至低排序
    """
    scores: dict[str, float] = {}
    for source, ranked_uids in source_rankings.items():
        for rank_0based, uid in enumerate(ranked_uids):
            rank = rank_0based + 1  # 轉為 1-based
            scores[uid] = scores.get(uid, 0.0) + 1.0 / (k + rank)
    return dict(sorted(scores.items(), key=lambda x: x[1], reverse=True))
```

**未出現來源的處理 — ⚠️ 核心設計議題 (待定)**:

若某文件只在 1 個來源的 Rank 1 出現，其 RRF 分數為：

$$\text{RRF}_{\text{single}} = \frac{1}{60 + 1} = 0.0164$$

若另一文件在 3 個來源都排 Rank 50：

$$\text{RRF}_{\text{multi}} = 3 \times \frac{1}{60 + 50} = 0.0273$$

多來源低排名 > 單來源高排名。這引出兩個對立的設計哲學：

**方案 A：Standard RRF（共識優先）**

```
哲學: 「多來源都認為相關」比「單一來源強推」更可信
優點: 抗噪能力強 — 單一 API 的排序偏差被稀釋
缺點: 可能埋沒「獨家發現」— 僅在某特定來源頂部出現的論文
適用: 一般搜尋（追求穩定、可靠的結果）
```

**方案 B：Source-Boosted RRF（獨家加權）**

對只出現在 1 個來源的高排名文章給予補償：

```python
def source_boosted_rrf(
    source_rankings: dict[str, list[str]],
    k: int = 60,
    single_source_boost: float = 1.5,  # 單來源 top-10 的加成
    boost_rank_threshold: int = 10,     # 只有 top-N 才加成
) -> dict[str, float]:
    scores: dict[str, float] = {}
    uid_source_count: dict[str, int] = {}  # 追蹤每個 UID 出現在幾個來源

    # Pass 1: 標準 RRF
    for source, ranked_uids in source_rankings.items():
        for rank_0based, uid in enumerate(ranked_uids):
            rank = rank_0based + 1
            scores[uid] = scores.get(uid, 0.0) + 1.0 / (k + rank)
            uid_source_count[uid] = uid_source_count.get(uid, 0) + 1

    # Pass 2: 單來源高排名加成
    for source, ranked_uids in source_rankings.items():
        for rank_0based, uid in enumerate(ranked_uids[:boost_rank_threshold]):
            if uid_source_count[uid] == 1:  # 僅出現在此來源
                rank = rank_0based + 1
                original_contribution = 1.0 / (k + rank)
                scores[uid] += original_contribution * (single_source_boost - 1.0)

    return dict(sorted(scores.items(), key=lambda x: x[1], reverse=True))
```

```
哲學: 「獨家高排名」可能是該來源的獨特優勢（如 Europe PMC 的全文搜尋）
優點: 不埋沒可能的 Preprint 或冷門領域論文
缺點: 可能放大單一 API 的排序偏差
適用: 探索性搜尋（追求覆蓋面和新穎性）
```

**方案 C：Hybrid（根據 Insight 類型區分處理）**

```
哲學: 不修改 RRF 分數本身，而是在 Insight 分類階段單獨打撈
做法:
  - RRF 排序仍用標準方案 A
  - 但 source_specific_gems 類別專門收集「單來源 Top-10 但 RRF 排名偏後」的文章
  - 等於在最終輸出中給這些文章一個「敗部復活」的展示機會
優點: RRF 數學性質不被污染，同時保留獨家發現
缺點: insights 中的 source_gems 可能純粹是某 API 的排序雜訊
```

**具體數值分析**（以 k=60, 5 個來源為例）：

| 場景 | 來源分布 | Standard RRF | Boosted RRF (1.5x) | 排名 |
|------|---------|:------------:|:-------------------:|:----:|
| A: 跨源共識 | OA:5, CR:8, EPMC:3, SS:12, PM:6 | 0.0736 | 0.0736 (不觸發) | #1 |
| B: 雙源強推 | OA:1, CR:2 | 0.0327 | 0.0327 (≥2 源) | #2 |
| C: 三源低排名 | OA:50, CR:45, EPMC:55 | 0.0273 | 0.0273 (≥2 源) | #3 |
| D: 單源 #1 | EPMC:1 | 0.0164 | **0.0246** (+50%) | #4→#3? |
| E: 單源 #5 | SS:5 | 0.0154 | **0.0231** (+50%) | #5→#4? |
| F: 單源 #50 | OA:50 | 0.0091 | 0.0091 (>10 位) | #6 |

**待決事項**: 方案 A/B/C 的選擇需要基於實際搜尋數據驗證。建議先實作方案 A + C（標準 RRF + 後置打撈），若驗證顯示獨家發現確實有價值，再考慮方案 B。

> 📌 **此議題將在 §9.10 中深入討論，是系統設計的核心取捨之一。**

#### 9.4.3 品質再排序 (Quality Re-ranking) — Stage 3 (Optional)

**設計決策**: RRF 與現有六維排序是**互補而非替代**。

```
層次 1 (RRF):   跨來源融合排序 — "同一篇文章在不同 API 的排名如何合併？"
層次 2 (品質):  品質維度排序   — "文章本身的品質 (RCR、文章類型、時效) 如何比較？"
```

**兩階段 Pipeline**:

```python
def fuse_and_rank(
    source_rankings: dict[str, list[str]],
    articles: dict[str, UnifiedArticle],
    alpha: float = 0.6,  # RRF 權重 (vs 品質)
    ranking_config: RankingConfig | None = None,
) -> list[UnifiedDoc]:
    """兩階段融合 + 品質排序

    Stage 2: RRF → cross-source consensus score
    Stage 3: Quality → article intrinsic quality score
    Blend:   final = α·rrf_normalized + (1-α)·quality_normalized
    """
    # Stage 2: RRF
    rrf_scores = reciprocal_rank_fusion(source_rankings)

    # Normalize RRF scores to [0, 1]
    max_rrf = max(rrf_scores.values()) if rrf_scores else 1.0
    rrf_normalized = {uid: s / max_rrf for uid, s in rrf_scores.items()}

    # Stage 3: Quality scoring (reuse existing ResultAggregator dimensions)
    # quality = f(recency, impact, article_type, source_trust, entity_match)
    # 只用原始六維中的 5 個維度（排除 relevance，因為 RRF 已取代）
    quality_scores = calculate_quality_scores(rrf_scores.keys(), articles, ranking_config)

    # Blend
    blended = {}
    for uid in rrf_scores:
        rrf_n = rrf_normalized.get(uid, 0.0)
        qual_n = quality_scores.get(uid, 0.0)
        blended[uid] = alpha * rrf_n + (1 - alpha) * qual_n

    # Sort and assign final ranks
    sorted_uids = sorted(blended.keys(), key=lambda u: blended[u], reverse=True)
    results = []
    for rank, uid in enumerate(sorted_uids, 1):
        doc = UnifiedDoc(
            uid=uid,
            title=articles[uid].title,
            rrf_score=rrf_scores[uid],
            rrf_rank=rank,
            sources=get_sources(uid),
            source_count=count_sources(uid),
            metadata=articles[uid].to_dict(),
            quality_score=quality_scores.get(uid),
            blended_score=blended[uid],
        )
        results.append(doc)
    return results
```

**`alpha` 的語意**:
- `alpha=1.0` — 純 RRF（只看跨來源共識）
- `alpha=0.5` — 平衡（RRF + 品質各半）
- `alpha=0.0` — 純品質排序（忽略來源排名，回歸現有行為）
- **預設 `alpha=0.6`** — RRF 略為主導，品質作為校正

#### 9.4.4 差異分析 (Differential Analysis) — Stage 4

**目的**: 計算本次搜尋 (Turn $t$) 與上一次搜尋 (Turn $t-1$) 的變化。

```python
from enum import Enum

class RankChangeType(Enum):
    NEW = "new"                # 首次出現
    HIGH_RISER = "high_riser"  # 排名大幅提升
    STAGNANT = "stagnant"      # 排名變化不大
    DROPPING = "dropping"      # 排名下降

@dataclass
class RankDelta:
    uid: str
    current_rank: int
    previous_rank: int | None  # None = NEW
    delta: int | None          # positive = improved
    change_type: RankChangeType

def differential_analysis(
    current_rank_map: dict[str, int],   # {uid: rank} from current RRF
    previous_rank_map: dict[str, int] | None,  # {uid: rank} from last turn
    config: FusionConfig,
) -> list[RankDelta]:
    """計算排名差異

    對 Current Top N 的每一篇文件：
    1. 若不在 previous → NEW
    2. 若存在且 rank_delta >= threshold → HIGH_RISER
    3. 若存在且 |rank_delta| < threshold → STAGNANT
    4. 若存在且 rank_delta < -threshold → DROPPING
    """
    deltas = []
    for uid, current_rank in current_rank_map.items():
        if current_rank > config.top_n_display:
            continue  # 只分析 Top N

        if previous_rank_map is None or uid not in previous_rank_map:
            deltas.append(RankDelta(
                uid=uid,
                current_rank=current_rank,
                previous_rank=None,
                delta=None,
                change_type=RankChangeType.NEW,
            ))
        else:
            prev_rank = previous_rank_map[uid]
            delta = prev_rank - current_rank  # positive = improved
            if delta >= config.high_riser_threshold:
                change_type = RankChangeType.HIGH_RISER
            elif delta <= -config.high_riser_threshold:
                change_type = RankChangeType.DROPPING
            else:
                change_type = RankChangeType.STAGNANT
            deltas.append(RankDelta(
                uid=uid,
                current_rank=current_rank,
                previous_rank=prev_rank,
                delta=delta,
                change_type=change_type,
            ))
    return deltas
```

#### 9.4.5 Insight 分類 (Insight Categorization) — Stage 5

```python
@dataclass
class FusionInsights:
    global_consensus_new: list[dict]    # 多來源推薦 + 新發現
    high_risers: list[dict]             # 排名大幅提升
    source_specific_gems: list[dict]    # 單來源獨家發現

def categorize_insights(
    docs: list[UnifiedDoc],
    deltas: list[RankDelta],
    config: FusionConfig,
) -> FusionInsights:
    delta_map = {d.uid: d for d in deltas}

    consensus_new = []
    high_risers = []
    source_gems = []

    for doc in docs[:config.top_n_display]:
        delta = delta_map.get(doc.uid)
        if not delta:
            continue

        # Global Consensus: ≥2 sources + NEW + Top N
        if doc.source_count >= 2 and delta.change_type == RankChangeType.NEW:
            consensus_new.append({
                "uid": doc.uid,
                "title": doc.title,
                "rrf_rank": doc.rrf_rank,
                "found_in": doc.sources,
            })

        # High Riser: rank improved ≥ threshold
        if delta.change_type == RankChangeType.HIGH_RISER:
            high_risers.append({
                "uid": doc.uid,
                "title": doc.title,
                "rank_change": f"+{delta.delta} (Prev: {delta.previous_rank} → Curr: {delta.current_rank})",
                "reason": "Relevance spiked for current query context",
            })

    # Source Gems: 單來源 + 在該來源 Top 10 (wider net than top_n_display)
    for doc in docs[:config.top_n_display * 2]:  # 掃描更廣的範圍
        if doc.source_count == 1:
            # 解析該來源中的排名
            source_rank_str = doc.sources[0]  # e.g., "europepmc:3"
            source_name, rank_in_source = source_rank_str.rsplit(":", 1)
            if int(rank_in_source) <= 10:  # 在來源中 Top 10
                source_gems.append({
                    "uid": doc.uid,
                    "title": doc.title,
                    "source": source_rank_str,
                    "rrf_rank": doc.rrf_rank,
                    "note": "Unique to this source — may be preprint or niche finding",
                })

    return FusionInsights(
        global_consensus_new=consensus_new,
        high_risers=high_risers,
        source_specific_gems=source_gems,
    )
```

### 9.5 Agent 輸出格式 (JSON Output Spec)

經過高度壓縮與語意化的最終 Payload：

```json
{
  "meta": {
    "query": "current search query",
    "sources": ["openalex", "crossref", "europepmc", "semantic_scholar", "pubmed"],
    "total_fused": 150,
    "overlap_vs_last": 0.35,
    "overlap_vs_all": 0.72,
    "novelty_rate": 0.28,
    "warning": null
  },
  "insights": {
    "global_consensus_new": [
      {
        "description": "多個來源一致推薦的新發現",
        "items": [
          {
            "uid": "doi:10.1038/s41591-xxx",
            "title": "Large language models encode clinical knowledge",
            "rrf_rank": 1,
            "found_in": ["openalex:2", "europepmc:1", "semantic_scholar:5"]
          }
        ]
      }
    ],
    "high_risers": [
      {
        "description": "在當前關鍵字下排名顯著提升的舊論文",
        "items": [
          {
            "uid": "doi:10.1145/3442188.xxx",
            "title": "On the Dangers of Stochastic Parrots",
            "rank_change": "+45 (Prev: 50 → Curr: 5)",
            "reason": "Relevance spiked for current query context"
          }
        ]
      }
    ],
    "source_specific_gems": [
      {
        "description": "單一來源獨家發現的高排名論文（可能是 Preprint 或冷門領域）",
        "items": [
          {
            "uid": "doi:10.1101/2024.01.xxx",
            "title": "Benchmarking Medical Hallucinations",
            "source": "europepmc:3",
            "rrf_rank": 28,
            "note": "Unique to this source — may be preprint or niche finding"
          }
        ]
      }
    ]
  }
}
```

**Overlap 計算邏輯**:

```python
def calculate_overlaps(
    current_uids: set[str],
    fusion_history: list[FusionTurn],
    config: FusionConfig,
) -> dict[str, float]:
    """計算三種重疊指標"""
    result = {"overlap_vs_last": 0.0, "overlap_vs_all": 0.0, "novelty_rate": 1.0, "warning": None}

    if not fusion_history:
        return result  # Cold start: 全部都是新的

    # vs Last Turn (Jaccard)
    last_uids = set(fusion_history[-1].rank_map.keys())
    if current_uids | last_uids:
        result["overlap_vs_last"] = len(current_uids & last_uids) / len(current_uids | last_uids)

    # vs All History (累積重疊率)
    all_previous = set()
    for turn in fusion_history:
        all_previous.update(turn.rank_map.keys())
    if current_uids:
        overlap_count = len(current_uids & all_previous)
        result["overlap_vs_all"] = overlap_count / len(current_uids)
        result["novelty_rate"] = 1.0 - result["overlap_vs_all"]

    # Warning: 搜尋策略過於重複
    if result["overlap_vs_last"] > config.jaccard_warning_threshold:
        result["warning"] = (
            f"⚠️ 與上次搜尋的重疊率 ({result['overlap_vs_last']:.0%}) 超過閾值 "
            f"({config.jaccard_warning_threshold:.0%})。"
            f"建議調整搜尋策略以獲得更多新結果。"
        )

    return result
```

### 9.6 配置參數 (Configuration)

```python
@dataclass
class FusionConfig:
    """Fusion Engine 配置"""
    # RRF
    rrf_k: int = 60                       # RRF 平滑常數。值越小，Top 1 的影響力越大
    top_n_process: int = 100              # 每個 API 來源只取前 N 筆進入融合流程
    top_n_display: int = 20               # 最終回傳給 Agent 的列表長度

    # Quality Re-ranking
    alpha: float = 0.6                    # RRF vs Quality 的混合比例 (1.0=純RRF)
    enable_quality_reranking: bool = True # 是否啟用 Stage 3

    # Differential Analysis
    high_riser_threshold: int = 15        # 排名提升超過此數值才被視為 High Riser

    # Overlap Detection
    jaccard_warning_threshold: float = 0.85  # 重疊率超過此值時警告 Agent

    # Source Gems
    gem_source_rank_threshold: int = 10   # 在來源中排名 Top N 才視為 Gem

    @classmethod
    def default(cls) -> "FusionConfig":
        return cls()

    @classmethod
    def exploration_mode(cls) -> "FusionConfig":
        """探索模式：更重視多樣性和新穎性"""
        return cls(
            alpha=0.4,            # 降低 RRF 權重，品質更重要
            top_n_display=30,     # 顯示更多結果
            high_riser_threshold=10,  # 更靈敏的 High Riser 偵測
            gem_source_rank_threshold=20,  # 更寬的 Gem 範圍
        )

    @classmethod
    def precision_mode(cls) -> "FusionConfig":
        """精準模式：更重視共識和可靠性"""
        return cls(
            alpha=0.8,            # RRF 主導，共識最重要
            top_n_display=10,     # 只顯示最可靠的
            high_riser_threshold=20,  # 更高的 High Riser 門檻
            gem_source_rank_threshold=5,  # 更嚴格的 Gem 條件
        )
```

### 9.7 邊緣案例處理 (Edge Cases)

| # | 場景 | 處理策略 |
|---|------|----------|
| 1 | **Cold Start** — 首次搜尋，Session 為空 | 所有結果標記為 `NEW`；省略 `high_risers`；Jaccard overlap = 0 |
| 2 | **API Failure** — 某來源 Timeout/Error | Log warning 但繼續融合 (Degraded Mode)。RRF 天生支援缺漏資料 — 少一個加項而已 |
| 3 | **No Results** — 所有 API 都回傳 0 筆 | 返回 `{"meta": {"total_fused": 0}, "insights": null}`，Agent 應嘗試放寬關鍵字 |
| 4 | **Single Source** — 只有 1 個來源有結果 | RRF 退化為該來源的原始排名；`source_specific_gems` 無意義，省略 |
| 5 | **Metadata Mismatch** — 同篇論文在不同來源的 metadata 不一致 | Union 合併策略：保留資訊量最豐富的欄位。年份取最早不為空的值 |
| 6 | **很短的排名列表** — 某來源只返回 5 篇 | 正常處理，這些文章在該來源的排名就是 1-5 |
| 7 | **完全重疊** — 所有來源返回完全相同的文章 | overlap = 1.0，觸發 warning；所有文章的 source_count 都很高，consensus 很強 |

### 9.8 DDD 分層設計 (Architecture Placement)

```
src/pubmed_search/
├── domain/entities/
│   └── fusion.py                     # FusionConfig, UnifiedDoc, FusionTurn,
│                                     # RankDelta, RankChangeType, FusionInsights
│                                     # (Pure data structures, no logic)
│
├── application/
│   └── fusion/                       # ← 新模組
│       ├── __init__.py               # Public API: FusionEngine
│       ├── rrf_engine.py             # reciprocal_rank_fusion()
│       │                             # source_boosted_rrf() (if adopted)
│       │                             # fuse_and_rank() — Stage 2+3
│       ├── diff_engine.py            # differential_analysis() — Stage 4
│       │                             # calculate_overlaps()
│       └── insight_categorizer.py    # categorize_insights() — Stage 5
│                                     # format_agent_summary()
│
├── application/session/
│   └── manager.py                    # 修改：ResearchSession 新增 fusion_history
│                                     # SessionManager 新增 update_fusion_state()
│
└── presentation/mcp_server/tools/
    └── unified.py                    # 修改：在 unified_search 中整合 Fusion Pipeline
                                      # result_aggregator → fusion_engine → session_update
```

**依賴方向** (DDD 嚴格分層):

```
presentation → application → domain
     ↓              ↓           ↓
  unified.py    fusion/     fusion.py
  (MCP tool)    rrf_engine  (entities)
                diff_engine
                insight_cat
```

`application/fusion/` 不依賴 `presentation/`，不依賴 `infrastructure/`。
所有外部 API 呼叫已在 unified.py 完成，fusion 模組只處理**內部資料**。

### 9.9 與現有系統的整合策略

#### 9.9.1 ResultAggregator 的角色轉變

```
現狀: ResultAggregator = 去重 + 六維排序 (全包)
目標: ResultAggregator = Stage 1 (去重)
      FusionEngine     = Stage 2-5 (RRF + 品質 + Diff + Insights)
```

**不破壞現有 API**: `ResultAggregator.aggregate()` 仍然可用，但 `unified_search` 在其後插入 Fusion Pipeline：

```python
# unified.py (修改後)
async def unified_search(query: str, ...):
    # 1. 並行搜尋 (現有)
    raw_results = await asyncio.gather(
        openalex.search(query),
        crossref.search(query),
        europepmc.search(query),
        ...
    )

    # 2. 去重 (現有 ResultAggregator)
    aggregated = result_aggregator.aggregate(raw_results)

    # 3. ← 新增：Fusion Pipeline
    fusion_engine = FusionEngine(config=FusionConfig.default())
    fused_results, insights = fusion_engine.fuse(
        source_rankings=extract_rankings(raw_results),
        articles=aggregated.articles,
        session=session_manager.get_current_session(),
    )

    # 4. 更新 Session fusion_history
    session_manager.update_fusion_state(query, fused_results)

    # 5. 格式化輸出 (在現有 Markdown 輸出中附加 insights)
    return format_output(fused_results, insights)
```

#### 9.9.2 對現有 MCP 工具的影響

| 工具 | 影響 | 說明 |
|------|------|------|
| `unified_search` | **主要修改** | 整合 Fusion Pipeline |
| `get_session_summary` | 輕微修改 | 增加 fusion_history 摘要 |
| `get_session_pmids` | 無變化 | PMID 儲存不受影響 |
| 其他所有工具 | 無變化 | Fusion 只影響搜尋路徑 |

### 9.10 RRF 未出現來源策略：深入分析 (Open Discussion)

> **這是整個設計中最關鍵的取捨決策，值得獨立展開。**

#### 9.10.1 問題本質

RRF 的數學特性使得**多來源低排名 > 單來源高排名**。這是 feature 還是 bug？

```
場景化思考：

假設搜尋 "remimazolam pharmacokinetics elderly"

文章 X: 只出現在 Europe PMC Rank #3
  ├── 可能原因 A: Europe PMC 全文搜尋能力強，找到其他來源索引不到的文獻 → 有價值
  ├── 可能原因 B: Europe PMC 的 relevance 排序錯誤，其他來源正確地沒推薦它 → 噪音
  └── 可能原因 C: 該文章太新（preprint），尚未被其他來源索引 → 有價值但需標註

文章 Y: 出現在 OpenAlex #40, CrossRef #35, Semantic Scholar #50
  ├── 三個獨立來源都認為它有一定相關性（雖然排名不高）→ 可信的中等相關
  └── 但排名 35-50 在每個來源中可能已經是 "noise range" → 可能只是巧合
```

#### 9.10.2 三方案比較矩陣

| 維度 | A: Standard RRF | B: Source-Boosted | C: Hybrid (A + 後置打撈) |
|------|:---:|:---:|:---:|
| 數學純粹性 | ✅ 標準 | ❌ 引入啟發式 | ✅ RRF 不受污染 |
| 共識可靠度 | ✅ 最佳 | ⚠️ 可能被單源偏差放大 | ✅ 主排名可靠 |
| 獨家發現能力 | ❌ 可能埋沒 | ✅ 有補償 | ✅ 在 gems 中展示 |
| 實作複雜度 | ⭐ 最低 | ⭐⭐ 需要額外 pass | ⭐⭐ 需要分類邏輯 |
| 可解釋性 | ✅ 「多來源共識」 | ⚠️ 「為什麼這篇被 boost？」 | ✅ 「主排名 + 獨家推薦」 |
| 參數敏感性 | 只有 k | k + boost + threshold | k + gem_threshold |
| 適合場景 | 一般搜尋 | 探索性搜尋 | **通用** |

#### 9.10.3 各方案對 Agent 行為的影響

```
方案 A 的 Agent 體驗:
  Agent: "以下是多個學術來源共同推薦的論文..."
  → Agent 只展示高共識文章，行為保守
  → 風險: 獨家 preprint 或冷門發現可能永遠不被展示

方案 B 的 Agent 體驗:
  Agent: "以下論文中，#1-#15 為多來源共識，#16-#20 為特定來源強烈推薦..."
  → Agent 需要解釋為什麼某些文章排名被人為提升
  → 風險: boost 導致一些「API 排序 bug」的文章莫名出現在高位

方案 C 的 Agent 體驗:
  Agent: "以下是主要推薦論文(排名基於跨來源共識)..."
  Agent: "此外，以下論文僅在特定來源被高度推薦，可能值得額外關注：..."
  → 最自然的展示方式 — 主結果 + 補充推薦
  → 風險: gems 區塊可能被 Agent 忽略或選擇性展示
```

#### 9.10.4 建議與待驗證假設

**初步建議**: 方案 C (Hybrid) 作為預設

**理由**:
1. RRF 數學性質是其核心價值，不應該被啟發式修改
2. `source_specific_gems` 作為獨立 insight 類別已經覆蓋了「獨家發現」的展示需求
3. Agent 可以自主決定是否展示 gems（而非被強制將 boosted 文章混入主排名）
4. 若未來數據顯示 gems 中有高價值文章長期被 RRF 低估，可以升級到方案 B

**待驗證假設** (需要用實際搜尋數據):

| 假設 | 驗證方法 | 若假設成立 | 若假設不成立 |
|------|---------|-----------|-------------|
| 假設 | 驗證方法 | 若假設成立 | 若假設不成立 |
|------|---------|-----------|-------------|
| H1: 單來源 Top-10 中有 ≥20% 是其他來源完全沒有的 | 統計 5 個主題的來源分布 | Source Gems 有意義 | Source Gems 可能是空集合，無需特殊處理 |
| H2: 這些獨家文章中有 ≥50% 確實與查詢高度相關 | 人工評審 | 方案 C 足夠且正確 | 需要更嚴格的 gem 篩選或放棄 |
| H3: 獨家文章主要出現在 Europe PMC（全文搜尋）和預印本來源 | 來源歸因分析 | 可以按來源設定不同的 gem 信任度 | Gems 來源分布均勻，無法差異化處理 |
| H4: Boosted RRF (方案 B) 比標準 RRF 在 nDCG@10 上有提升 | TREC PM 評測 | 升級到方案 B | 保持方案 C |

#### 9.10.5 實驗驗證結論 (2026-02-15 實驗數據)

> 以下結論基於 §9.14 完整實驗報告的數據。

**H1 驗證結果：✅ 全部 6 個來源皆 >20% 獨家**

| 來源 | 獨家率 | 結論 |
|------|:------:|------|
| PubMed | 61.7% | Source Gems **有意義** — 每個來源都有大量獨家文章 |
| Semantic Scholar | 51.3% | |
| OpenAlex | 54.6% | |
| Europe PMC | 87.9% | |
| CORE | 93.8% | |
| CrossRef | 80.7% | |

但注意：**獨家率過高本身就是問題**（見 §9.14.4 設計改進建議 #5）。

**H3 驗證結果：⚠️ 部分成立**

獨家文章分布**相對均勻**，Europe PMC (21.3%) 和 CORE (19.3%) 佔比最高但未形成壓倒性優勢。CrossRef (18.2%) 也貢獻了大量「獨家」，但其排序品質低（元資料搜尋而非學術排序），這些獨家更可能是噪音。

**→ 決策：採用方案 C (Hybrid) + 以下改進**

1. **Gems 需要品質門檻**（非「獨家即 Gem」）
2. **CrossRef 降級為元資料補充**，不參與 RRF 主排序
3. **Topic-Adaptive Alpha** 取代靜態 alpha（見 §9.14.4 #2）

**H2 與 H4 狀態：** 需要 ground truth 標註和 TREC PM 評測，本次實驗無法驗證。

### 9.11 與其他研究文件演算法的銜接

本 Spec 建立的基礎設施可直接銜接 §2 和 §4 中的其他演算法：

```
本 Spec (Phase 1)          Phase 2                    Phase 3
─────────────────         ───────                    ───────

FusionTurn.rank_map  ───→  Smart Top-K (MMR)   ───→  Result Digest
(每輪的排名快照)           §2.3 解法 3                §2.3 解法 1
                           用 MeSH Jaccard 做          MeSH 分群 +
                           多樣性選取                   代表作選取

FusionTurn.rrf_scores ──→  BM25 整合            ───→  Learning-to-Rank
(可作為 relevance 的       §4.1 Stage 1               §4.3 用 rrf_score
 一個特徵)                替代 term overlap            作為一個特徵

calculate_overlaps() ───→  Coverage Tracker
(overlap_vs_all)           §2.3 解法 4
                           擴展為 MeSH 子樹覆蓋率

source_specific_gems ───→  Preprint Monitor
(獨家來源追蹤)             追蹤特定來源的新發現
```

### 9.12 實作估算

| 檔案 | 預估行數 | 難度 | 依賴 |
|------|:--------:|:----:|------|
| `domain/entities/fusion.py` | ~80 | 低 | 無 |
| `application/fusion/__init__.py` | ~20 | 低 | 無 |
| `application/fusion/rrf_engine.py` | ~120 | 低 | 無（純計算） |
| `application/fusion/diff_engine.py` | ~100 | 低 | 無（純計算） |
| `application/fusion/insight_categorizer.py` | ~80 | 低 | 無 |
| `application/session/manager.py` (修改) | ~30 | 低 | 現有 Session |
| `presentation/mcp_server/tools/unified.py` (修改) | ~50 | 中 | 上述全部 |
| **測試** | ~400 | 中 | pytest |
| **合計** | **~880** | | |

**預估工時**: 2-3 天（含測試）

**零外部依賴**: 此模組完全由純 Python 實作，不需要任何新的第三方套件。

### 9.13 驗證計畫

| 驗證項目 | 方法 | 成功標準 |
|---------|------|----------|
| RRF 正確性 | 手動構造 3 組排名列表，驗算 RRF 分數 | 分數與手算一致 |
| 去重一致性 | 確認 UID 策略與現有 Union-Find 的結果相容 | 0 衝突 |
| Diff 邏輯 | 模擬 3 輪搜尋，驗證 NEW/HIGH_RISER 分類 | 分類符合預期 |
| Overlap 計算 | Cold start + 多輪搜尋的 Jaccard | 數值正確 |
| 效能 | 500 篇文章的融合時間 | < 50ms |
| 整合測試 | 端到端 unified_search → insights JSON | JSON schema 合規 |

### 9.14 RRF Source Behavior 實驗報告

> **實驗日期**: 2026-02-15  
> **實驗腳本**: `scripts/rrf_source_experiment.py`  
> **原始數據**: `scripts/_tmp/rrf_experiment_data.json`  
> **V2 報告**: `scripts/_tmp/rrf_experiment_report_v2.md`  
> **文件版本**: v1.4

#### 9.14.1 實驗目的

驗證 §9.10.4 提出的四個假設 (H1-H4)，並為以下設計決策提供數據基礎：

1. RRF 權重策略：Standard (A) vs Source-Boosted (B) vs Hybrid (C)
2. Source-Weighted RRF 的來源權重校準
3. `source_specific_gems` 是否應該保留
4. CrossRef 和 CORE 在融合管線中的角色

#### 9.14.2 實驗方法

**測試主題** (5 個，覆蓋不同領域和特徵):

| ID | Query | 特徵 |
|----|-------|------|
| T1 | `machine learning diagnosis cancer` | 寬領域、高量 |
| T2 | `remimazolam sedation ICU` | 窄領域、利基 |
| T3 | `CRISPR gene therapy sickle cell` | 尖端遺傳學 |
| T4 | `COVID-19 long COVID neurological` | 快速出版週期 |
| T5 | `gut microbiome obesity metabolic syndrome` | 跨學科 |

**測試來源** (6 個): PubMed, Semantic Scholar, OpenAlex, Europe PMC, CORE, CrossRef

**每個來源取 Top 30 結果**，收集：
- 文章標識符 (DOI, PMID, 標題)
- 元資料完整度 (Abstract, Citation Count)
- 跨來源重疊率 (Jaccard Similarity)
- 獨家文章統計

**UID Matching 策略**: Union-Find 跨欄位匹配，任意共享 DOI/PMID/標準化標題即合併 — 與產品碼 `ResultAggregator` 行為一致。

**實驗修正記錄** (V1→V2):

| 修正 | V1 問題 | V2 修正 |
|------|---------|---------|
| EPMC Abstract | `result_type="lite"` 不含 abstract → 0% | 改用 `result_type="core"` → 88% |
| CORE 301 Redirect | `BaseAPIClient` 不跟隨 redirect → 0 結果 | 加入 `follow_redirects=True` → avg 25.2 結果 |
| UID Matching | 簡單 `DOI>PMID>title` 單一 fallback | Union-Find 三欄位交叉匹配 |
| S2 Rate Limit | T3 三次 429 後放棄 → 0 結果 | 第三次 retry 間隔增加 → 30 結果 |

#### 9.14.3 實驗結果

##### A. 來源能力矩陣

| Source | Avg Count | DOI Rate | PMID Rate | Abstract Rate | Avg Latency | Role |
|--------|:---------:|:--------:|:---------:|:-------------:|:-----------:|------|
| PubMed | 30.0 | 99% | 100% | 95% | 9.7s | 🥇 Gold Standard |
| Semantic Scholar | 30.0 | 99% | 75% | 77% | 4.8s | 🥈 SPECTER 排序 |
| OpenAlex | 30.0 | 99% | 80% | 69% | 1.7s | 🥈 快速+高覆蓋 |
| Europe PMC | 30.0 | 93% | 89% | 88% | 2.4s | 全文搜尋 |
| CORE | 25.2 | 67% | 15% | 92% | 1.7s | 開放取用+預印本 |
| CrossRef | 30.0 | 100% | 0% | 24% | 1.7s | ⚠️ 元資料搜尋 |

**關鍵發現：**
- **PubMed** 在所有指標上都是最完整的（99% DOI, 100% PMID, 95% Abstract）
- **CORE** 現在能正常工作（V1 修正 `follow_redirects` 後），但 DOI 覆蓋只有 67%，PMID 15%
- **CrossRef** DOI 100% 但 PMID 0%，Abstract 只有 24% — 確認其本質是元資料註冊中心
- **Europe PMC** 改用 `result_type="core"` 後 Abstract Rate 從 0% 升至 88%

##### B. 跨來源重疊矩陣 (Avg Jaccard)

```
              PubMed   S2      OA      EPMC    CORE    CR
PubMed        1.000    0.171   0.194   0.023   0.010   0.049
S2            0.171    1.000   0.189   0.063   0.007   0.091
OpenAlex      0.194    0.189   1.000   0.015   0.014   0.073
Europe PMC    0.023    0.063   0.015   1.000   0.007   0.007
CORE          0.010    0.007   0.014   0.007   1.000   0.003
CrossRef      0.049    0.091   0.073   0.007   0.003   1.000
```

**平均跨來源 Jaccard: 0.061** — 極低重疊，各來源高度互補。

**來源聚類分析：**
- **聚類 1 (學術搜尋引擎)**: PubMed ↔ S2 (0.171) ↔ OpenAlex (0.194) — 相互重疊最高
- **聚類 2 (獨立文獻庫)**: Europe PMC, CORE — 與所有來源重疊極低
- **聚類 3 (元資料)**: CrossRef — 與 S2 (0.091) 和 OA (0.073) 有些重疊

##### C. 獨家文章統計

| 來源 | 獨家率 | 獨家數 (avg) | 佔總獨家% |
|------|:------:|:-----------:|:---------:|
| CORE | 93.8% | 23.4 | 19.3% |
| Europe PMC | 87.9% | 25.8 | 21.3% |
| CrossRef | 80.7% | 22.0 | 18.2% |
| PubMed | 61.7% | 18.4 | 15.2% |
| OpenAlex | 54.6% | 16.0 | 13.2% |
| Semantic Scholar | 51.3% | 15.4 | 12.7% |

**總獨家文章數 (avg/topic)**: ~121 / 175 total = **69.1% 獨家率**

##### D. 窄領域 vs 寬領域差異

| 指標 | T2 (窄: remimazolam) | T1 (寬: ML cancer) | 倍率 |
|------|:---:|:---:|:---:|
| PubMed-S2 Jaccard | **0.481** | 0.053 | 9.1x |
| PubMed-OA Jaccard | **0.379** | 0.081 | 4.7x |
| PubMed 獨家率 | **14%** | 87% | 0.16x |
| S2 獨家率 | **13%** | 90% | 0.14x |

**核心洞察**：Topic 類型對來源重疊率的影響**遠大於**來源本身的排序演算法差異。

#### 9.14.4 數據驅動的設計改進建議

##### 改進 #1：來源角色分類 (Source Roles)

基於實驗數據，6 個來源應分為三種角色：

```python
SOURCE_ROLES = {
    # Primary Search — 參與 RRF 融合排序
    "pubmed": "primary",            # MeSH+BestMatch, 最完整
    "semantic_scholar": "primary",  # SPECTER 語意排序
    "openalex": "primary",         # 快速, 高 DOI 覆蓋
    "europe_pmc": "primary",       # 全文搜尋, 高 PMID/Abstract

    # Supplementary — 參與 RRF 但降權
    "core": "supplementary",       # 開放取用, DOI 67%, PMID 15%

    # Metadata Enrichment — 不參與 RRF
    "crossref": "enrichment",      # DOI 100% 但無 PMID, 排序基於元資料
}
```

**理由**：CrossRef 的「排序」是基於元資料文字匹配，不是學術 relevance ranking。其 80.7% 獨家率更可能反映的是「找到了其他來源沒索引的非學術或邊緣文獻」而非「找到了被遺漏的重要論文」。

##### 改進 #2：Topic-Adaptive Alpha

靜態 `alpha=0.6` 無法適應窄/寬領域的極端差異（Jaccard 差 9 倍）。

```python
def compute_adaptive_alpha(
    uid_sets: dict[str, set[str]],
    base_alpha: float = 0.6,
) -> float:
    """根據實際觀測的來源重疊率動態調整 RRF vs Quality 權重

    高重疊 → 來源有共識 → 信任 RRF (alpha ↑)
    低重疊 → 來源各自獨立 → 信任品質排序 (alpha ↓)
    """
    # 計算 primary source 間的平均 pairwise Jaccard
    primary_sources = [s for s in uid_sets if s in PRIMARY_SOURCES]
    if len(primary_sources) < 2:
        return base_alpha

    jaccards = []
    for i in range(len(primary_sources)):
        for j in range(i + 1, len(primary_sources)):
            a, b = uid_sets[primary_sources[i]], uid_sets[primary_sources[j]]
            if a and b:
                jaccards.append(len(a & b) / len(a | b))

    if not jaccards:
        return base_alpha

    avg_jaccard = sum(jaccards) / len(jaccards)

    # 映射: Jaccard 0.0-0.5 → alpha 0.4-0.85
    #   低重疊 (寬Topic): avg_j ≈ 0.05 → alpha ≈ 0.45 (品質主導)
    #   高重疊 (窄Topic): avg_j ≈ 0.40 → alpha ≈ 0.76 (RRF 主導)
    alpha = base_alpha + (avg_jaccard - 0.1) * 0.9
    return max(0.3, min(0.9, alpha))  # clamp to [0.3, 0.9]
```

**實驗數據校準**:

| Topic 類型 | avg Jaccard | Adaptive Alpha | 語意 |
|-----------|:-----------:|:--------------:|------|
| T2 窄領域 | ~0.30 | **0.78** | RRF 共識可靠 |
| T3 前沿領域 | ~0.08 | **0.48** | 品質排序更重要 |
| T1 寬領域 | ~0.05 | **0.45** | 各來源獨立判斷 |

##### 改進 #3：Gems 品質門檻

當所有來源 50-94% 獨家時，「獨家 + Top-10」不夠篩選，需要品質信號：

```python
def is_quality_gem(
    article: UnifiedArticle,
    rank_in_source: int,
    source: str,
    current_year: int,
) -> bool:
    """判斷獨家文章是否值得作為 Gem 推薦"""
    # 必要條件
    if rank_in_source > 10:
        return False

    # 品質信號 (至少滿足 1 個)
    quality_signals = [
        article.citation_count is not None and article.citation_count > 0,
        bool(article.abstract),
        article.year is not None and article.year >= current_year - 3,
        bool(article.doi),  # 有 DOI 表示正式出版
    ]

    # 來源信任度 (CrossRef/CORE 需要更多品質信號)
    min_signals = {
        "pubmed": 1,
        "semantic_scholar": 1,
        "openalex": 1,
        "europe_pmc": 1,
        "core": 2,         # DOI 覆蓋低，需要更多品質信號
        "crossref": 3,     # 不參與 RRF，gems 門檻更高
    }

    return sum(quality_signals) >= min_signals.get(source, 2)
```

##### 改進 #4：EPMC 應使用 `result_type="core"`

實驗揭示：EPMC 預設 `result_type="lite"` 不包含 `abstractText`。
在 `unified_search` 管線中呼叫 EPMC 時應指定 `result_type="core"` 以取得完整元資料。

**影響**：延遲從 ~1.6s 增至 ~2.4s (+50%)，但換來 88% abstract 覆蓋率，對品質排序至關重要。

##### 改進 #5：BaseAPIClient 啟用 redirect 跟隨

已修正 `base_client.py`：`httpx.AsyncClient(follow_redirects=True)`。
影響所有 8 個繼承的 source client，解決 CORE API 301 redirect 問題。

##### 改進 #6：RRF 權重推導

放棄靜態權重精確推導（缺乏 ground truth 標註），改用**運行時自適應**：

```python
SOURCE_BASE_WEIGHTS = {
    # 基礎權重（排序演算法品質 × 資料完整度 / PubMed 基準）
    "pubmed": 1.0,            # Gold standard
    "semantic_scholar": 0.85,  # SPECTER + 高重疊
    "openalex": 0.85,         # 高覆蓋 + 快速
    "europe_pmc": 0.70,       # 全文搜尋 + 高 Abstract (修正後)
    "core": 0.40,             # 低 DOI (67%), 低 PMID (15%)
    # crossref: 不參與 RRF
}

def get_runtime_weights(
    uid_sets: dict[str, set[str]],
    base_weights: dict[str, float] = SOURCE_BASE_WEIGHTS,
) -> dict[str, float]:
    """根據本次搜尋的實際表現微調權重

    如果某來源與 ≥2 個其他來源有 overlap → 它在搜同一空間 → 略微增權
    如果某來源完全獨家 → 降權但保留在 gems 中
    """
    adjusted = dict(base_weights)
    for source, uids in uid_sets.items():
        if source not in adjusted:
            continue
        overlap_count = 0
        for other_source, other_uids in uid_sets.items():
            if other_source != source and other_source in adjusted:
                if uids & other_uids:
                    overlap_count += 1
        if overlap_count >= 2:
            adjusted[source] = min(1.0, adjusted[source] * 1.1)
        elif overlap_count == 0:
            adjusted[source] *= 0.8
    return adjusted
```

#### 9.14.5 實驗局限性

1. **樣本量小**：僅 5 個 topic，無法做統計顯著性檢定
2. **無 ground truth**：無法評估獨家文章的「真正相關性」（H2 未驗證）
3. **API 不穩定**：Semantic Scholar 頻繁 429，CORE 結果數量波動大 (12-30)
4. **時序依賴**：搜尋結果會隨時間改變（新文章索引、排序演算法更新）
5. **未測試預印本**：尚未加入 arXiv/medRxiv/bioRxiv 預印本來源

#### 9.14.6 後續行動

| # | 行動 | 狀態 | 對應改進 |
|---|------|:----:|---------|
| 1 | `BaseAPIClient` 加 `follow_redirects=True` | ✅ 完成 | #5 |
| 2 | CORE client 加 zero-result warning log | ✅ 完成 | #5 |
| 3 | 實作 `compute_adaptive_alpha()` | 待 Fusion Engine 實作時 | #2 |
| 4 | 實作 `is_quality_gem()` | 待 Insight Categorizer 實作時 | #3 |
| 5 | CrossRef 從 RRF 中移除 | 待 `unified_search` 重構時 | #1 |
| 6 | EPMC search 改用 `result_type="core"` | 待確認延遲影響 | #4 |
| 7 | Adaptive RRF weighting | 待 Fusion Engine 實作時 | #6 |

### 9.15 學術研究方法論：如何證明「更好」

> **問題**：如何從學術角度實現一個可驗證的更好的學術搜尋 MCP？
> **日期**: 2026-02-15

#### 9.15.1 現有生態系統調查

對 GitHub 上 59 個 PubMed MCP repos + 43 個 Scholar MCP repos 的完整調查顯示，現有學術搜尋 MCP 分為三種架構模式，**沒有任何一個在做多來源融合排序**：

##### 模式 A：單來源包裝器（90% 的 repos）

| Repo | Stars | 架構 |
|------|:-----:|------|
| `andybrandt/mcp-simple-pubmed` | 156 | PubMed API 薄包裝 |
| `JackKuo666/Google-Scholar-MCP-Server` | 225 | Google Scholar 薄包裝 |
| `zongmin-yu/semantic-scholar-fastmcp-mcp-server` | 92 | S2 API 薄包裝 |
| `Darkroaster/pubmearch` | 144 | PubMed 分析型（關鍵詞趨勢） |
| `adityak74/mcp-scholarly` | 171 | Google Scholar 薄包裝 |

**共同點**：一個 API、一個 tool、零融合邏輯。

##### 模式 B：多來源但不融合（「交給 Agent 自己選」）

| Repo | Stars | 來源數 | 融合策略 |
|------|:-----:|:------:|---------|
| `Dianel555/paper-search-mcp-nodejs` | 95 | **14** | 每個平台一個 tool；`platform="all"` 時**隨機選一個** |
| `afrise/academic-search-mcp-server` | 101 | 2 (S2+CrossRef) | 各 tool 獨立，不合併 |
| `JamesANZ/medical-mcp` | 58 | 4 (FDA+WHO+PubMed+Scholar) | 各 tool 獨立 |

**致命問題**：14 個平台 × 14 個 tool = Agent 需要自己決定呼叫哪個 tool，等同於把融合問題丟給 Agent。Agent 通常只會挑 1-2 個來源呼叫，錯過其餘 12 個來源的獨家文獻。

##### 模式 C：有去重但極簡原始（全 GitHub 唯一）

| Repo | Stars | 來源數 | 融合策略 |
|------|:-----:|:------:|---------|
| `Seelly/scholar_mcp_server` | 10 | 6 (Go) | DOI-only 去重 + 引用數排序 |

實際程式碼（`aggregator.go`）：

```go
// 去重：DOI > 標題（標準化後），無 cross-field matching
func generatePaperKey(paper) string {
    if paper.DOI != "" { return "doi:" + lower(paper.DOI) }
    if paper.Title != "" { return "title:" + lower(trim(paper.Title)) }
    return ""
}

// 排序：引用數 + 開放取用獎勵 10 分，無 RRF
scoreI := papers[i].CitationCount
if papers[i].IsOpenAccess { scoreI += 10 }
```

**問題**：無 RRF、無 source weighting、無 cross-field UID matching、無 adaptive 參數。

##### 學術研究方面

| 論文 | 年份 | 相關性 |
|------|:----:|--------|
| Cormack et al. "RRF outperforms Condorcet" (SIGIR 2009) | 2009 | RRF 原始論文，uniform weighting only |
| `ranx.fuse` (Bassani & Romelli, CIKM 2022) | 2022 | Python metasearch library，用於同 corpus 多模態融合 |
| Mmmorrf (Samuel et al., SIGIR 2025) | 2025 | Adaptive weighted RRF，但用於影片檢索 |
| HySemRAG (Godinez, arXiv 2025) | 2025 | 用 RRF 融合學術文獻，但未分析 source overlap |
| Sun et al. (BMC Bioinformatics 2025) | 2025 | RRF for biomedical IR，同一 TREC 資料集 |
| Mourão et al. "Inverse Square Rank Fusion" (2014) | 2014 | 改進 RRF 公式，仍是 uniform weighting |
| NovaSearch (TREC 2013 Federated Web Search) | 2013 | 最接近「聯邦搜尋」，但用於 web search |

**結論**：沒有任何已發表研究同時處理 (1) 跨多個學術資料庫的 rank fusion with source-specific weighting, (2) query-dependent adaptive fusion, (3) source overlap 分析作為權重推導基礎, (4) 「獨家發現」(Gems) 的識別。

#### 9.15.2 核心難題：Ground Truth 不存在

學術搜尋不像 web search 有 TREC/BEIR 標準 benchmark。根本問題：**沒有人標註過「對於 query X，跨 6 個資料庫的最佳 Top-30 是哪些論文」**。

因此需要**同時解決兩個問題**：
1. 提出比現有方案更好的融合演算法
2. 設計一個可信的評估方法來證明 (1)

#### 9.15.3 三層評估方法論

##### Layer 1：Citation-based Proxy Relevance（自動化、大規模）

**核心洞察**：高被引 + 近期 + 多來源共識的論文大概率是相關的。可構造 pseudo-relevance judgments：

```python
def compute_pseudo_relevance(article, query, current_year=2026):
    """基於客觀信號估計文章相關性（無需人工標註）"""
    signals = {
        # 1. 引用影響力（RCR 比原始引用數更公平）
        "rcr": min(article.relative_citation_ratio / 5.0, 1.0),

        # 2. 標題/摘要與 query 的語意相似度
        "semantic_sim": cosine_sim(
            embed(query), embed(article.title + " " + article.abstract)
        ),

        # 3. 時效性（針對快速發展領域）
        "recency": max(0, 1 - (current_year - article.year) / 10),

        # 4. 元資料完整度（proxy for quality）
        "completeness": sum([
            bool(article.doi), bool(article.abstract),
            bool(article.pmid), article.citation_count is not None
        ]) / 4,

        # 5. 多來源共識（出現在越多來源 = 越可能相關）
        "source_consensus": article.source_count / total_sources,
    }

    return (0.30 * signals["semantic_sim"] +
            0.25 * signals["rcr"] +
            0.20 * signals["source_consensus"] +
            0.15 * signals["recency"] +
            0.10 * signals["completeness"])
```

**優點**：可大規模自動化（1000+ queries），完全可重現。
**缺點**：proxy ≠ true relevance，需在小規模 expert set 上驗證。

##### Layer 2：LLM-as-Judge（中規模、可擴展）

```
流程：
1. 給 LLM (GPT-4/Claude) query + title + abstract
2. 要求判斷 relevance (0-3 scale)
3. 在 expert-annotated subset 上驗證 LLM 判斷的一致性
4. 若 Cohen's κ > 0.6，可作為大規模評估替代
```

**學術依據**：Thomas et al. (2024) "Large Language Models can Accurately Predict Searcher Preferences" (SIGIR 2024) 已證明 LLM 在 TREC-style relevance judgment 上與人類 annotator 一致性達 κ ≈ 0.6-0.7。

**成本估算**：7500 篇 × ~$0.01/判斷 ≈ $75。

##### Layer 3：Expert Annotation（小規模、Gold Standard）

```
設計流程：
1. 選 30-50 個 query（覆蓋窄/寬/跨學科/前沿/經典）
2. 每個 query 從 6 來源各取 Top-30 → 合併去重 → ~120-150 篇/query
3. 邀請 3+ 位領域專家對每篇標註 relevance (0-3 scale)
4. 計算 Fleiss' κ (inter-annotator agreement)
5. 用標註結果算 nDCG@k, MAP, Precision@k
```

**用途**：驗證 Layer 1 和 Layer 2 的 proxy 有效性。

#### 9.15.4 演算法創新點

##### 創新 1：Source-Aware Reciprocal Rank Fusion (SA-RRF)

原始 RRF (Cormack 2009)：

```
RRF(d) = Σ_{s∈S} 1/(k + rank_s(d))
```

SA-RRF：

```
SA-RRF(d) = Σ_{s∈S} w_s(q) · 1/(k + rank_s(d))
```

其中 w_s(q) = w_s^base · φ_s(q)，φ_s(q) 是來源 s 對 query q 的「能力估計」：

- 該來源返回的結果數量（normalized）
- 返回結果的元資料完整度
- 該來源與其他來源的 overlap 程度

**學術新穎性**：RRF 原始論文只證明 uniform weighting。Mmmorrf (SIGIR 2025) 在影片檢索做了 adaptive weighting，但沒有人在跨學術資料庫場景做過。

##### 創新 2：Topic-Adaptive Fusion Parameter

```
α*(q) = f( avg_pairwise_jaccard(S_1(q), S_2(q), ..., S_n(q)) )
```

**直覺**：
- 高 overlap（窄領域）→ 來源有共識 → 信任 RRF → α ↑
- 低 overlap（寬領域）→ 來源各自獨立 → 信任 quality signals → α ↓

§9.14 實驗數據：T2 remimazolam Jaccard=0.481 vs T1 ML cancer=0.053，差 9 倍。

##### 創新 3：Source Complementarity Analysis Framework

純分析貢獻：對 6 個學術資料庫在 N 個 query 上系統性量化 overlap、exclusivity rate、metadata quality，建立「來源能力矩陣」。

本身即有價值的 benchmark contribution，類似 BEIR 對 retrieval model 的貢獻。

#### 9.15.5 實驗設計

##### A. Baselines

| ID | Baseline | 描述 | 代表 |
|----|----------|------|------|
| B1 | Single-PubMed | 只用 PubMed | 90% 現有 MCP |
| B2 | Best-Single | Oracle 選最好的單一來源 | 理論上限 |
| B3 | Naive Merge | 合併去重 + 引用數排序 | Seelly/scholar_mcp_server |
| B4 | Standard RRF | k=60, uniform weights | Cormack 2009 |
| B5 | LLM-Orchestrated | 讓 Agent 選 tool | paper-search-mcp-nodejs 哲學 |
| P1 | SA-RRF | Source-Aware RRF | 本研究 |
| P2 | SA-RRF + Adaptive α | 完整方法 | 本研究 |

##### B. Query Set 設計

```
來源：
- 30 queries from systematic review protocols (Cochrane Library PICO)
- 30 queries from trending topics (NIH Reporter 近期資助)
- 30 queries from cross-disciplinary topics (人工構造)
- 10 edge cases (very narrow / very broad / non-English terms)

每個 query 標註：
- Domain (bio/cs/chem/interdisciplinary)
- Specificity (narrow/medium/broad)
- Temporal profile (established/emerging/declining)
```

##### C. Metrics

| Metric | 衡量什麼 | 計算方式 |
|--------|---------|---------|
| nDCG@10/20/50 | 排序品質 | 需要 relevance judgments |
| Unique Relevant@k | 融合發現的獨家相關文章數 | 跨來源比較 |
| Coverage | 召回了多少 ground truth 相關文章 | Expert set |
| Diversity | 結果的主題多樣性 | Topic model entropy |
| Freshness | 是否包含最新研究 | Median publication year |
| Source Utilization | 每個來源對最終結果的貢獻 | 佔比分析 |
| Latency | 實用性 | Wall clock time |

##### D. Statistical Rigor

- Paired t-test / Wilcoxon signed-rank test（每個 query 是 paired sample）
- Bonferroni correction（多重比較）
- Effect size (Cohen's d)
- 100 queries × 7 methods = 700 runs → 足夠統計功效
- Ablation study：逐一移除 SA-RRF 組件觀察影響

#### 9.15.6 發表路線

| 路線 | 目標 | 內容 | 工作量 |
|------|------|------|--------|
| A: Systems Paper | JCDL / ECIR / CIKM resource track | 完整系統 + SA-RRF + 三層評估 | 3-4 個月 |
| B: Short Paper | JCDL Workshop / BIR@ECIR | 只做 Source Complementarity Analysis | 4-6 週 |
| C: Benchmark | AcademicFuse benchmark (HuggingFace/Zenodo) | 100 queries + expert judgments + baselines | 2-3 個月 |

#### 9.15.7 最小可行實驗 (MVP)

```
Step 1: 擴大 query set（5 → 50），用 Cochrane PICO 做 seed
Step 2: 跑 50 queries × 6 sources × Top-50（~300 API calls）
Step 3: LLM-as-Judge 標註 relevance（~7500 篇 × $0.01 ≈ $75）
Step 4: 隨機抽 200 篇自己標註，驗證 LLM 一致性
Step 5: 跑 7 baselines + ablation，比較 nDCG@10, Coverage
Step 6: 統計顯著性檢定 + 寫 paper
預計時間：2-3 週有初步結果，1-2 個月可提交
```

### 9.16 Agent-Centric Design：MCP 搜尋的根本不同

> **核心觀察**：MCP 的使用者不是人類，是 AI Agent。
> 這根本性地改變了搜尋系統的設計目標。

#### 9.16.1 Agent ≠ Human：搜尋消費者的差異

傳統學術搜尋引擎（PubMed、Google Scholar）為人類設計：

```
Human User:
- 能瀏覽 10 頁結果，自己判斷相關性
- 能讀標題+摘要，快速篩選
- 有領域知識，能辨別低品質/邊緣結果
- 會用篩選器（年份、期刊、文章類型）迭代搜尋
- 能容忍假陽性（跳過不相關文章成本極低）

AI Agent:
- 只看一次結果，通常取 Top-10~30
- 沒有深層領域知識，容易被假陽性誤導  
- 會把搜尋結果直接摘要給最終使用者
- Token 有限，大海撈針的成本是上下文污染
- 無法自主判斷「這篇值不值得深入」
- 搜尋一次就走，很少做 iterative refinement
```

#### 9.16.2 核心問題：上下文污染 (Context Pollution)

Agent 的根本限制不是「找不到好文章」，而是**好文章被淹沒在雜訊中**。

```
情境重現：

Agent 呼叫 unified_search("remimazolam ICU sedation")
→ 返回 30 篇文章
→ Agent 的可用 context window 被 30 篇文章的 metadata 佔據
→ 其中 5 篇高度相關，10 篇略相關，15 篇噪音

結果：Agent 在摘要時把不太相關的文章也混入回答
→ 最終使用者看到的是被噪音稀釋的回答
```

**這就是「在不同的大海中撈針」問題**：6 個來源各返回 30 篇 = 180 篇候選，Agent 的 context window 承受不了，但簡單截斷 Top-30 又可能遺漏某來源的獨家重要發現。

#### 9.16.3 Agent-Centric 設計原則

##### 原則 1：Signal-to-Noise Ratio (SNR) 最大化

> 搜尋系統的目標不是「召回率最高」，而是**在 Agent 的有限 context budget 內，最大化有用資訊密度**。

```python
# 傳統目標（人類優先）
maximize Recall@100  # 越多越好，人類會自己篩

# Agent-Centric 目標
maximize Precision@k * Diversity@k  # 在 k 篇內，最大化相關且多樣
subject to k ≤ context_budget       # k 受 Agent context window 限制
```

**量化 context budget**：

```
Agent 可用 context ≈ 128K tokens (Claude) / 128K (GPT-4o)
每篇文章 metadata (title + authors + abstract + doi + year) ≈ 300-500 tokens
系統 prompt + instruction + 之前對話 ≈ 10K-50K tokens
可用於搜尋結果的空間 ≈ 30K-80K tokens
→ 有效承載量 ≈ 60-160 篇文章

但 Agent 的注意力集中度遠低於 context window 大小：
實務觀察：Agent 通常只有效處理 Top-10~20 篇的資訊
```

##### 原則 2：結構化信號優於原始羅列

Agent 不像人類可以「掃一眼標題就知道相不相關」。Agent 需要**明確的排序信號**：

```python
# ❌ 傳統方式：丟一堆文章讓 Agent 自己判斷
return [article1, article2, ..., article30]  # 全部平等呈現

# ✅ Agent-Centric：分層 + 標記 + 結構化
return {
    "high_confidence": [       # 多來源共識 + 高品質信號
        {"article": a1, "why": "ranked top-5 in 3/6 sources, RCR=8.2"},
        {"article": a2, "why": "ranked top-3 in PubMed+S2, 2025 review"},
    ],
    "source_gems": [           # 獨家發現但高品質
        {"article": a3, "source": "CORE", "why": "only in CORE, OA preprint, 2025"},
    ],
    "supporting": [            # 補充性結果
        {"article": a4, "why": "related but lower confidence"},
    ],
    "meta_insights": {         # Agent 可以直接引用的洞察
        "topic_type": "narrow_niche",
        "source_agreement": "high (Jaccard=0.48)",
        "recommendation": "5 high-consensus papers + 2 unique gems from CORE"
    }
}
```

##### 原則 3：Fusion 即是摘要前處理

> 把 RRF Fusion 想成 Agent 的「前額葉皮層」— 在資訊進入 Agent 的「工作記憶」(context window) 之前，先做好篩選、排序、去噪。

```
傳統 IR pipeline:
  Query → Retrieve → Rank → [Return to User]
                                    ↓
                              User 自己看

Agent-Centric pipeline:
  Query → Retrieve → Rank → Fuse → Filter → Structure → [Return to Agent]
                                                              ↓
                                                        Agent 直接摘要
                                                              ↓
                                                        最終使用者看到

   ^^^^^^^^^^^^^^^^          ^^^^^^^^^^^^^^^^^^^^^^^^
   Server 端負責              新增的 Agent-Centric 層
   （和傳統一樣）              （減少 Agent 認知負擔）
```

#### 9.16.4 Agent-Centric 的具體設計改進

##### 改進 1：Confidence-Tiered Results（信心分層）

不再返回一個扁平的 ranked list，而是**三層結構**：

```python
class TieredResults:
    """Agent-Centric 分層結果"""

    tier_1_consensus: list[RankedArticle]
    # 定義：出現在 ≥2 個 primary source 中，且 SA-RRF score > P75
    # Agent 指引：「這些文章有高度共識，可以直接引用」
    # 數量：通常 3-8 篇

    tier_2_gems: list[GemArticle]
    # 定義：僅出現在 1 個來源，但通過品質門檻 (is_quality_gem)
    # Agent 指引：「這些是獨家發現，值得提及但需標註來源」  
    # 數量：通常 2-5 篇

    tier_3_supporting: list[RankedArticle]
    # 定義：其餘通過基本品質篩選的文章
    # Agent 指引：「如需更多細節可參考，否則可忽略」
    # 數量：通常 10-20 篇

    meta: SearchMeta
    # topic_type, source_agreement, confidence_level, suggested_citation_count
```

**為什麼這對 Agent 重要**：

| 設計 | Agent 行為 | 最終使用者的體驗 |
|------|-----------|----------------|
| 扁平 30 篇 | Agent 嘗試摘要所有 30 篇，混入噪音 | 「回答很長但重點不清楚」 |
| 分層結構 | Agent 先引用 Tier-1，選擇性提及 Tier-2 | 「回答精確且有獨到發現」 |

##### 改進 2：Agent-Readable Annotations（機器可讀標記）

每篇文章附加**明確的信號標記**，減少 Agent 自行判斷的認知負擔：

```python
class ArticleAnnotation:
    """Agent 可直接消費的文章標記"""

    relevance_signals: dict = {
        "source_count": 3,           # 出現在幾個來源
        "best_rank": 2,              # 在所有來源中的最佳排名
        "has_abstract": True,        # Agent 能否摘要此文
        "citation_tier": "high",     # high(>50)/medium(10-50)/low(<10)/unknown
        "recency": "recent",         # recent(≤2yr)/established(3-5yr)/classic(>5yr)
        "open_access": True,         # 全文是否可取得
        "study_type": "RCT",         # RCT/Meta-analysis/Review/Cohort/Case/Other
    }

    agent_guidance: str = (
        "Multi-source consensus article. "
        "Ranked top-5 in PubMed, S2, OpenAlex. "
        "2025 RCT with high RCR. Safe to cite."
    )
```

**關鍵差別**：人類看到 `citation_count=47` 會自己判斷「這算多還是少」，Agent 不會。給 Agent `citation_tier="high"` 比給原始數字有效得多。

##### 改進 3：adaptive k — 根據 topic 類型調整返回數量

```python
def compute_optimal_k(
    topic_type: str,
    source_agreement: float,
    agent_context_budget: int = 30,
) -> dict[str, int]:
    """根據 topic 特性決定各層返回多少篇

    窄領域且高共識 → 少而精（Agent 不需要看很多）
    寬領域且低共識 → 多而廣（每個來源可能有獨家發現）
    """

    if source_agreement > 0.3:  # 窄領域
        return {
            "tier_1_consensus": min(5, agent_context_budget // 3),
            "tier_2_gems": 2,
            "tier_3_supporting": 5,
            # 總共 ~12 篇，精簡但高品質
        }
    elif source_agreement > 0.1:  # 中領域
        return {
            "tier_1_consensus": min(8, agent_context_budget // 3),
            "tier_2_gems": 4,
            "tier_3_supporting": 10,
            # 總共 ~22 篇，平衡
        }
    else:  # 寬領域
        return {
            "tier_1_consensus": min(10, agent_context_budget // 3),
            "tier_2_gems": 6,
            "tier_3_supporting": 14,
            # 總共 ~30 篇，廣泛覆蓋
        }
```

##### 改進 4：Fusion Summary — Agent 的決策支援

在搜尋結果之前提供**一段結構化摘要**，讓 Agent 無需遍歷所有文章就能做初步判斷：

```python
class FusionSummary:
    """搜尋結果的元摘要 — Agent 讀這段就能決定怎麼用結果"""

    query_analysis: str
    # "搜尋 'remimazolam ICU sedation' — 窄利基主題，
    #  文獻集中在 2020-2026，以 RCT 和綜述為主"

    source_landscape: str
    # "6 來源高度一致 (Jaccard=0.48)，PubMed 和 S2 重疊 48%，
    #  CORE 提供 3 篇獨家開放取用預印本"

    top_findings: list[str]
    # ["5 篇多來源共識文章確認 remimazolam 在 ICU 鎮靜的安全性",
    #  "2 篇 CORE 獨家預印本顯示新的劑量調整方案",
    #  "1 篇 2025 meta-analysis 涵蓋 12 個 RCT"]

    suggested_narrative: str
    # "建議引用 Tier-1 的 5 篇共識文章作為主要證據，
    #  提及 Tier-2 的 CORE 預印本作為最新進展，
    #  總共引用 7-8 篇即可全面回答"

    confidence_level: str  # "high" / "medium" / "low"
    # "high — 多來源高度一致，文獻充足"
```

**為 Agent 解決的問題**：

| 沒有 FusionSummary | 有 FusionSummary |
|---|---|
| Agent 逐篇閱讀 30 篇 metadata | Agent 先讀摘要，決定引用策略 |
| 不知道哪些來源重要 | 明確知道來源間的關係 |
| 不知道該引用幾篇 | 有建議的引用數量和策略 |
| 可能過度引用或引用不足 | 引用數量適合 topic 規模 |

#### 9.16.5 Agent-Centric 評估指標

傳統 IR metrics 不完全適用於 Agent-Centric 場景。需要新指標：

##### Metric 1：Agent Answer Quality (AAQ)

```
流程：
1. 給 Agent 搜尋結果（baseline vs 我們的方法）
2. Agent 基於結果生成回答
3. 由 expert / LLM-judge 評估 Agent 回答的品質

AAQ 維度：
- Accuracy: 回答中的事實是否正確？
- Completeness: 是否涵蓋了主要面向？
- Relevance: 引用的論文是否真的支持論點？
- Specificity: 回答是否足夠具體（vs 泛泛而談）？
- Noise Ratio: 有多少引用是不相關的噪音？
```

**這是最致命的指標**：不管 nDCG 多高，如果 Agent 用你的結果生成的回答比用 PubMed 單來源的還差，就沒有意義。

##### Metric 2：Context Efficiency (CE)

```
CE = (Agent 回答中正確引用的文章數) / (返回給 Agent 的文章總數)

理想情況：CE → 1.0（每篇返回的文章都被有效使用）
現實中：CE ≈ 0.2-0.3（大部分結果是噪音）
目標：CE ≥ 0.5（至少一半的結果被有效使用）
```

##### Metric 3：Unique Discovery Rate (UDR)

```
UDR = (Agent 引用的來自非 PubMed 來源的相關文章數) / (Agent 總引用數)

如果 UDR ≈ 0：多來源搜尋毫無意義，PubMed 就夠了
如果 UDR > 0.2：多來源搜尋成功帶來了「否則不會被發現的文章」
```

##### Metric 4：Cognitive Load Reduction (CLR)

```
CLR = 1 - (Agent 生成回答所消耗的 tokens) / (Baseline 的 tokens)

如果 CLR > 0：我們的結構化結果讓 Agent 更高效
如果 CLR < 0：結構太複雜反而增加了 Agent 的處理負擔
```

#### 9.16.6 Agent-Centric 實驗設計

##### 實驗 1：End-to-End Agent Quality Test

```
Setup:
- 50 個 medical questions（sourced from BioASQ / PubMedQA）
- 3 個 Agent configurations：
    A: Agent + PubMed only (baseline)
    B: Agent + 6 sources, flat list (standard multi-source)
    C: Agent + 6 sources, tiered + FusionSummary (our method)

Evaluation:
- 每個問題由 3 位醫學生評分 (1-5 scale)
- 維度：accuracy, completeness, citation quality
- 統計：paired Wilcoxon test on mean scores
```

##### 實驗 2：Context Pollution Measurement

```
Setup:
- 取 Experiment 1 的同一組 questions
- 測量 Agent 回答中：
    - 引用了多少不相關的文章（False Citation Rate）
    - 遺漏了多少重要文章（Missed Citation Rate）
    - 回答中有多少段落是基於噪音文章的（Noise Propagation Rate）

假設：
- Tiered results 應顯著降低 False Citation Rate
- FusionSummary 應降低 Missed Citation Rate
```

##### 實驗 3：Ablation — 哪個 Agent-Centric 組件最重要？

```
Conditions:
C0: Flat list (no agent-centric features)
C1: + Tiered results
C2: + Article annotations
C3: + Adaptive k
C4: + FusionSummary
C5: All features (full method)

預測：
- C4 (FusionSummary) 會帶來最大的 AAQ 提升
  （因為 Agent 的主要瓶頸是「不知道怎麼用結果」）
- C1 (Tiered) 會帶來最大的 CE 提升
  （因為減少了 Agent 需要處理的噪音量）
```

#### 9.16.7 與 §9.15 傳統評估的整合

完整評估框架需要**兩個維度**：

```
                    傳統 IR 評估          Agent-Centric 評估
                    (§9.15)              (§9.16)
                    ─────────            ──────────────────
Level 1 (排序品質)：nDCG@10              Agent Answer Quality
Level 2 (發現能力)：Unique Relevant@k    Unique Discovery Rate
Level 3 (效率)：   Latency              Context Efficiency
Level 4 (實用性)：  Coverage             Cognitive Load Reduction
```

**論文 framing**：

> 我們證明 SA-RRF 不僅在傳統 IR 指標上優於 standard RRF（nDCG@10 提升 X%），
> 更關鍵的是，當搜尋結果以 agent-centric 分層結構返回時，
> 下游 AI Agent 生成的回答品質 (AAQ) 提升了 Y%，
> 同時上下文效率 (CE) 從 0.23 提升至 0.51。

這比單純報告 nDCG 的提升有更強的實際影響力。

#### 9.16.8 這改變了什麼

回到最初的問題：**「不要在不同的大海中找到針」**

| 問題 | 傳統解法 | Agent-Centric 解法 |
|------|---------|-------------------|
| 6 來源各 30 篇 = 180 篇候選 | 融合排序取 Top-30 | 分層：5 共識 + 3 Gems + 10 支持 |
| Agent 不知道哪篇重要 | 靠排名（但 Agent 不一定信任排名） | 每篇附帶 `agent_guidance` 說明 |
| Agent 不知道引用幾篇 | 無指引 | FusionSummary 建議引用策略 |
| 獨家文獻被淹沒 | 混在 Top-30 中 | Tier-2 Gems 獨立展示 |
| Topic 類型影響最佳策略 | 固定 k=30 | Adaptive k 根據共識度調整 |
| 評估只看排序品質 | nDCG@k | nDCG + AAQ + CE + UDR |

**根本思維轉變**：

```
傳統思維：搜尋系統的工作到「返回排序結果」就結束了。
Agent-Centric 思維：搜尋系統的工作到「Agent 能有效使用結果」才結束。
```

這才是學術搜尋 MCP 應該要解決的真正問題：不是「能搜到多少」，而是**「Agent 能用多好」**。
