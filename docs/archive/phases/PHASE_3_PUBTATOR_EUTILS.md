# Phase 3: 深度+廣度 專業文獻檢索系統

> 歷史設計提案：以下「每次搜尋自動執行」等敘述不代表現行預設。
> 目前行為請見 [搜尋架構](../../UNIFIED_SEARCH_ARCHITECTURE.zh-TW.md)。

> **核心理念**: 每次搜索都深度+廣度，這是專業工具該有的樣子
> **設計原則**: 簡單搜索 Agent 有其他工具，我們提供專業級體驗
> **狀態**: 設計完成，準備實作

---

## 🎯 高階設計理念

### 我們是什麼？

```text
❌ 我們不是：簡單的 PubMed 代理
❌ 我們不是：有時快有時慢的搜索工具
❌ 我們不是：需要 Agent 決定用哪個模式

✅ 我們是：專業級文獻檢索系統
✅ 我們是：每次都給出最好答案的工具
✅ 我們是：深度理解 + 廣度覆蓋的智能搜索
```

### 核心價值主張

**簡單搜索 Agent 有 Google、Bing、Perplexity... 我們存在的意義是提供專業級體驗：**

| 維度 | 一般搜索工具 | PubMed Search MCP |
|------|-------------|-------------------|
| **深度** | 字面匹配 | 語義理解 + 實體解析 + 關係網絡 |
| **廣度** | 單一來源 | 多源覆蓋 + 同義詞展開 + 跨庫路由 |
| **精準** | 相關性排序 | 證據等級 × 影響力 × 時效性 × 實體匹配 |
| **專業** | 通用結果 | MeSH 結構化 + PICO 分析 + 引用網絡 |

---

## 🔥 每次搜索自動執行（無例外）

```text
用戶查詢: "propofol ICU sedation"
                │
                ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                    🧠 Phase 1: 深度語義理解 (並行, ~300ms)                  │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────┐   │
│  │  🔬 PubTator3        │  │  📊 E-utilities      │  │  🎯 Local       │   │
│  │  Entity Resolution  │  │  Cross-DB Analysis  │  │  PICO Analysis  │   │
│  ├─────────────────────┤  ├─────────────────────┤  ├─────────────────┤   │
│  │ propofol            │  │ egquery("propofol") │  │ P: ICU patients │   │
│  │  → @CHEMICAL_Propofol│  │   pubmed: 36,000   │  │ I: propofol     │   │
│  │  → MeSH: D015742    │  │   gene: 5          │  │ C: -            │   │
│  │  → Synonyms:        │  │   pccompound: 1    │  │ O: sedation     │   │
│  │    Diprivan         │  │                     │  │                 │   │
│  │    2,6-diisopropyl  │  │ espell check       │  │ Intent:         │   │
│  │                     │  │   → OK             │  │   Therapy       │   │
│  │ sedation            │  │                     │  │                 │   │
│  │  → @DISEASE_Sedation│  │ Suggestions:       │  │ Complexity:     │   │
│  │  → MeSH: D000077227 │  │   "查 Gene 可能    │  │   Moderate      │   │
│  │                     │  │    有 5 筆相關"    │  │                 │   │
│  └─────────────────────┘  └─────────────────────┘  └─────────────────┘   │
│                                                                           │
│  Output: EnhancedQuery {                                                  │
│    original: "propofol ICU sedation",                                     │
│    entities: [{propofol, Chemical, D015742}, {sedation, Disease, ...}],   │
│    synonyms: ["Diprivan", "2,6-diisopropylphenol", "Conscious Sedation"], │
│    mesh_terms: ["D015742", "D000077227"],                                 │
│    cross_db_hints: ["gene:5 results available"],                          │
│  }                                                                        │
└───────────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                    🌐 Phase 2: 廣度多源搜索 (並行, ~500ms)                  │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  Strategy: 同時執行 4 種搜索策略，取聯集                                   │
│                                                                           │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐     │
│  │ 🔵 PubMed    │ │ 🟢 PubMed    │ │ 🟡 PubTator3 │ │ 🟣 Europe PMC│     │
│  │ Original    │ │ MeSH Expand  │ │ Entity Search│ │ Full-text    │     │
│  ├──────────────┤ ├──────────────┤ ├──────────────┤ ├──────────────┤     │
│  │ "propofol   │ │ "Propofol"   │ │ @CHEMICAL_   │ │ propofol AND │     │
│  │  ICU        │ │  [MeSH] AND  │ │ Propofol AND │ │ (ICU OR      │     │
│  │  sedation"  │ │ "Conscious   │ │ @DISEASE_    │ │  "intensive  │     │
│  │             │ │  Sedation"   │ │ Sedation     │ │  care")      │     │
│  │             │ │  [MeSH] AND  │ │              │ │              │     │
│  │             │ │ "ICU"        │ │              │ │ (Full-text!) │     │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘     │
│        │                │                │                │              │
│        └────────────────┼────────────────┼────────────────┘              │
│                         ▼                                                 │
│                  Raw Results Pool                                         │
│                  (可能有重複)                                             │
└───────────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                    🎯 Phase 3: 智能融合排序 (~100ms)                       │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │  Step 1: Union-Find 去重 O(n)                                       │ │
│  │  ─────────────────────────────                                       │ │
│  │  Priority: DOI > PMID > Title Fuzzy > Entity-aware                  │ │
│  │                                                                      │ │
│  │  NEW: Entity-aware 去重                                              │ │
│  │  - "propofol" 和 "Diprivan" 的文章視為同一概念                       │ │
│  │  - 用 MeSH ID 作為聚類鍵                                             │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │  Step 2: 多維度排序                                                  │ │
│  │  ────────────────────                                                │ │
│  │                                                                      │ │
│  │  Score = 0.20 × Relevance     (實體匹配 + 關鍵詞匹配)                │ │
│  │        + 0.25 × Evidence      (證據等級: Meta > RCT > Cohort)        │ │
│  │        + 0.15 × Recency       (指數衰減, 半衰期 5 年)                │ │
│  │        + 0.20 × Impact        (RCR / 引用數)                         │ │
│  │        + 0.10 × Source Trust  (PubMed > PMC > Preprint)             │ │
│  │        + 0.10 × Entity Match  (PubTator3 實體精確匹配)               │ │
│  │                                                                      │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │  Step 3: 豐富元數據                                                  │ │
│  │  ────────────────                                                    │ │
│  │  - 為每篇文章標註識別的實體                                          │ │
│  │  - 標記證據等級                                                      │ │
│  │  - 附加搜索策略說明                                                  │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                    📦 返回結果 (總時間 ~800ms - 1.5s)                      │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  SearchResult {                                                           │
│    articles: [...],           // 排序後的文章列表                         │
│    total_found: 156,          // 總共找到                                 │
│    unique_after_dedup: 89,    // 去重後                                   │
│                                                                           │
│    // 搜索質量指標                                                        │
│    quality: {                                                             │
│      semantic_coverage: 0.85,  // 語義覆蓋度                             │
│      entity_precision: 0.92,   // 實體匹配精度                           │
│      evidence_distribution: {  // 證據等級分布                           │
│        "meta-analysis": 3,                                                │
│        "rct": 12,                                                         │
│        "cohort": 34,                                                      │
│      }                                                                    │
│    },                                                                     │
│                                                                           │
│    // 增強資訊                                                            │
│    enhancement: {                                                         │
│      entities_detected: ["propofol", "sedation"],                         │
│      synonyms_used: ["Diprivan", "2,6-diisopropylphenol"],               │
│      mesh_terms_expanded: ["D015742", "D000077227"],                      │
│      cross_db_suggestions: ["5 related genes found in Gene DB"],          │
│    },                                                                     │
│                                                                           │
│    // 搜索策略說明 (幫助 Agent 理解)                                      │
│    strategy_explanation: "執行了 4 種並行搜索策略...",                    │
│  }                                                                        │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## ⚡ 限流處理：內部智能排隊

### API 速率限制

| API | 限制 | 我們的處理 |
|-----|------|-----------|
| **PubTator3** | 3 req/sec | TokenBucket + 請求合併 |
| **NCBI E-utils** | 3 req/sec (無 key) / 10 req/sec (有 key) | API Key + Semaphore |
| **Europe PMC** | 無官方限制 | 禮貌性 100ms 間隔 |

### 限流架構

```python
class SmartRateLimiter:
    """
    智能限流器 - 最大化吞吐量

    策略:
    1. Token Bucket: 平滑請求速率
    2. 請求合併: 相似請求合併執行
    3. 優先級隊列: 關鍵請求優先
    4. 快取: 減少重複請求
    """

    def __init__(
        self,
        rate: float = 3.0,      # requests per second
        burst: int = 5,          # 允許的突發請求
        cache_ttl: int = 3600    # 快取 1 小時
    ):
        self._rate = rate
        self._burst = burst
        self._tokens = burst
        self._last_update = time.time()
        self._cache = TTLCache(maxsize=1000, ttl=cache_ttl)
        self._pending: dict[str, asyncio.Future] = {}  # 請求合併
        self._lock = asyncio.Lock()

    async def execute(
        self,
        key: str,  # 用於快取和合併的鍵
        coro_factory,  # 生成協程的工廠函數
        priority: int = 0  # 優先級 (越高越優先)
    ):
        """
        智能執行請求

        1. 先查快取
        2. 檢查是否有相同請求正在執行
        3. 等待 token
        4. 執行並快取結果
        """
        # 1. 快取命中
        if key in self._cache:
            return self._cache[key]

        # 2. 請求合併 (相同請求共享結果)
        async with self._lock:
            if key in self._pending:
                # 等待已經在執行的相同請求
                return await self._pending[key]

            # 創建 Future 讓其他相同請求等待
            future = asyncio.get_event_loop().create_future()
            self._pending[key] = future

        try:
            # 3. 等待 Token
            await self._wait_for_token()

            # 4. 執行
            result = await coro_factory()

            # 5. 快取結果
            self._cache[key] = result

            # 6. 通知等待者
            future.set_result(result)

            return result

        except Exception as e:
            future.set_exception(e)
            raise
        finally:
            async with self._lock:
                del self._pending[key]

    async def _wait_for_token(self):
        """Token Bucket 算法"""
        async with self._lock:
            now = time.time()
            # 補充 token
            elapsed = now - self._last_update
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last_update = now

            if self._tokens >= 1:
                self._tokens -= 1
                return

        # 等待下一個 token
        wait_time = (1 - self._tokens) / self._rate
        await asyncio.sleep(wait_time)
        self._tokens = 0
```

### 請求合併示例

```python
# 場景: 同時解析 "propofol" 和 "propofol ICU"
# 普通方式: 2 次 PubTator3 API 調用

# 我們的方式:
# 1. "propofol" 請求先到，開始執行
# 2. "propofol ICU" 請求到，發現 "propofol" 已在執行
# 3. 只需等待第一個請求完成，共享結果
# 結果: 只有 1 次 API 調用！

async def resolve_entities_smart(terms: list[str]) -> dict:
    """智能實體解析 - 自動合併請求"""

    limiter = get_pubtator_limiter()

    # 並行執行，但相同實體會自動合併
    tasks = [
        limiter.execute(
            key=f"entity:{term.lower()}",  # 相同 term 會合併
            coro_factory=lambda t=term: pubtator.find_entity(t)
        )
        for term in terms
    ]

    results = await asyncio.gather(*tasks)
    return dict(zip(terms, results))
```

---

## 🛡️ 優雅降級：保持深度的同時確保可靠

### 降級策略

```text
降級不是放棄深度，而是用不同方式達到深度
```

```python
class GracefulDegrader:
    """
    優雅降級器

    原則:
    1. 總是嘗試最好的方式
    2. 失敗時用替代方式達到相似效果
    3. 記錄降級原因，讓 Agent 知道
    """

    async def resolve_entities(self, query: str) -> EntityResult:
        """實體解析 - 三層降級"""

        # Level 1: PubTator3 (最準確)
        try:
            result = await self._pubtator_resolve(query)
            return EntityResult(
                entities=result,
                source="pubtator3",
                confidence=0.95
            )
        except (TimeoutError, APIError) as e:
            logger.warning(f"PubTator3 failed: {e}, degrading to MeSH")

        # Level 2: NCBI MeSH (次準確)
        try:
            result = await self._mesh_resolve(query)
            return EntityResult(
                entities=result,
                source="ncbi_mesh",
                confidence=0.80,
                degraded_from="pubtator3"
            )
        except (TimeoutError, APIError) as e:
            logger.warning(f"MeSH failed: {e}, degrading to local")

        # Level 3: 本地詞典 (最後保底)
        result = self._local_resolve(query)
        return EntityResult(
            entities=result,
            source="local_dictionary",
            confidence=0.50,
            degraded_from="ncbi_mesh"
        )

    async def search_multi_source(self, query: str) -> SearchResult:
        """多源搜索 - 部分失敗不影響整體"""

        sources = [
            ("pubmed", self._search_pubmed),
            ("europe_pmc", self._search_europe_pmc),
            ("pubtator3_semantic", self._search_pubtator3),
        ]

        results = []
        failures = []

        # 並行執行，收集成功的結果
        tasks = [
            self._safe_execute(name, func, query)
            for name, func in sources
        ]

        for source, result in await asyncio.gather(*tasks):
            if result.success:
                results.extend(result.articles)
            else:
                failures.append({
                    "source": source,
                    "error": str(result.error)
                })

        # 即使部分失敗，仍然返回結果
        return SearchResult(
            articles=results,
            sources_used=[r for r, res in zip(sources, tasks) if res.success],
            sources_failed=failures,
            is_partial=len(failures) > 0
        )
```

---

## 📊 智能排序：專業級結果排序

### 證據等級金字塔

```text
                    ┌─────────────┐
                    │ Meta-       │  Weight: 1.00
                    │ Analysis    │
                    ├─────────────┤
                    │ Systematic  │  Weight: 0.95
                    │ Review      │
                    ├─────────────┤
                    │ RCT         │  Weight: 0.85
                    ├─────────────┤
                    │ Clinical    │  Weight: 0.75
                    │ Trial       │
                    ├─────────────┤
                    │ Cohort      │  Weight: 0.65
                    │ Study       │
                    ├─────────────┤
                    │ Case-       │  Weight: 0.55
                    │ Control     │
                    ├─────────────┤
                    │ Case        │  Weight: 0.35
                    │ Report      │
                    ├─────────────┤
                    │ Review      │  Weight: 0.50
                    │ Article     │
                    ├─────────────┤
                    │ Journal     │  Weight: 0.40
                    │ Article     │
                    └─────────────┴
                    │ Preprint    │  Weight: 0.20
                    └─────────────┘
```

### 排序公式

```python
@dataclass
class DeepSearchRankingConfig:
    """深度搜索排序配置 - 不可調整，這是專業級預設"""

    relevance_weight: float = 0.20      # 查詢匹配度
    evidence_weight: float = 0.25       # 證據等級 (專業核心!)
    recency_weight: float = 0.15        # 時效性
    impact_weight: float = 0.20         # 影響力 (引用/RCR)
    source_trust_weight: float = 0.10   # 來源可信度
    entity_match_weight: float = 0.10   # 實體精確匹配

    def calculate_score(self, article: Article, query_context: QueryContext) -> float:
        """計算文章排序分數"""

        # 1. 相關性分數 (查詢詞匹配 + 實體匹配)
        relevance = self._calc_relevance(article, query_context)

        # 2. 證據等級分數
        evidence = EVIDENCE_LEVEL_SCORES.get(article.article_type, 0.4)

        # 3. 時效性分數 (指數衰減)
        if article.year:
            age = 2026 - article.year
            recency = 0.5 ** (age / 5.0)  # 5 年半衰期
        else:
            recency = 0.3

        # 4. 影響力分數
        if article.rcr:
            impact = min(article.rcr / 4.0, 1.0)  # RCR 4.0 = 滿分
        elif article.citation_count:
            impact = min(math.log10(article.citation_count + 1) / 3, 1.0)
        else:
            impact = 0.3

        # 5. 來源信任度
        source_trust = SOURCE_TRUST_SCORES.get(article.source, 0.5)

        # 6. 實體匹配度 (PubTator3 識別的實體與查詢實體的匹配)
        entity_match = self._calc_entity_match(article, query_context)

        # 加權總分
        return (
            self.relevance_weight * relevance +
            self.evidence_weight * evidence +
            self.recency_weight * recency +
            self.impact_weight * impact +
            self.source_trust_weight * source_trust +
            self.entity_match_weight * entity_match
        )
```

---

## 🏗️ 精簡架構設計

### 核心模組

```text
src/pubmed_search/
├── infrastructure/
│   ├── pubtator/                 # NEW: PubTator3 整合
│   │   ├── __init__.py
│   │   ├── client.py             # 異步 HTTP 客戶端 + 限流
│   │   └── models.py             # EntityMatch, RelationResult
│   │
│   ├── ncbi/                     # EXISTING: 增強
│   │   ├── ...existing...
│   │   └── async_utils.py        # NEW: 異步版 E-utilities
│   │
│   └── cache/                    # NEW: 智能快取
│       ├── __init__.py
│       └── entity_cache.py       # TTL 快取 + 請求合併
│
├── application/
│   └── search/
│       ├── ...existing...
│       ├── semantic_enhancer.py  # NEW: 語義增強協調器
│       └── deep_search.py        # NEW: 深度搜索編排器
│
└── presentation/
    └── mcp_server/
        └── tools.py              # 更新: unified_search 預設深度
```

### 資料流

```text
unified_search(query)
        │
        ▼
┌─────────────────────────────────────┐
│  DeepSearchOrchestrator             │
│  ───────────────────────            │
│  1. 總是執行深度分析                │
│  2. 並行多源搜索                    │
│  3. 智能融合排序                    │
└─────────────────────────────────────┘
        │
        ├──────────────────────────────────┐
        │                                  │
        ▼                                  ▼
┌─────────────────────┐          ┌─────────────────────┐
│  SemanticEnhancer   │          │  MultiSourceSearcher│
│  ─────────────────  │          │  ─────────────────  │
│  - PubTator3 實體   │          │  - PubMed           │
│  - MeSH 展開       │          │  - Europe PMC       │
│  - 同義詞收集      │          │  - PubTator3 Search │
│  - E-utils 跨庫    │          │  - (可選) OpenAlex  │
└─────────────────────┘          └─────────────────────┘
        │                                  │
        └──────────────────────────────────┘
                        │
                        ▼
               ┌─────────────────────┐
               │  ResultAggregator   │
               │  ─────────────────  │
               │  - Union-Find 去重  │
               │  - 多維度排序      │
               │  - Entity-aware    │
               │    聚類            │
               └─────────────────────┘
                        │
                        ▼
                   SearchResult
```

---

## 📋 實作計劃

### Week 1: 基礎設施

| 優先級 | 檔案 | 說明 |
|--------|------|------|
| P0 | `infrastructure/pubtator/client.py` | PubTator3 客戶端 + 限流 |
| P0 | `infrastructure/pubtator/models.py` | 資料模型 |
| P0 | `infrastructure/cache/entity_cache.py` | TTL 快取 + 請求合併 |
| P1 | `infrastructure/ncbi/async_utils.py` | 異步 egquery, espell |

### Week 2: 應用層

| 優先級 | 檔案 | 說明 |
|--------|------|------|
| P0 | `application/search/semantic_enhancer.py` | 語義增強協調器 |
| P0 | `application/search/deep_search.py` | 深度搜索編排器 |
| P1 | `application/search/result_aggregator.py` | 增強: Entity-aware 去重 |

### Week 3: MCP 整合 + 測試

| 優先級 | 檔案 | 說明 |
|--------|------|------|
| P0 | `presentation/mcp_server/tools.py` | 更新 unified_search |
| P0 | `tests/test_deep_search.py` | 端到端測試 |
| P1 | `.github/copilot-instructions.md` | 更新文檔 |

---

## 📊 預期效益

### 每次搜索自動獲得

| 功能 | 說明 |
|------|------|
| ✅ 實體解析 | 自動識別藥物、疾病、基因 |
| ✅ 同義詞展開 | propofol → Diprivan, 2,6-DIP |
| ✅ MeSH 結構化 | 自動使用 MeSH 層次結構 |
| ✅ 多源覆蓋 | PubMed + Europe PMC + PubTator3 |
| ✅ 證據等級排序 | Meta-analysis 優先 |
| ✅ 跨庫建議 | "Gene 資料庫有 5 筆相關" |

### 性能指標

| 指標 | 目標 |
|------|------|
| 首次搜索延遲 | < 1.5s |
| 快取命中搜索 | < 500ms |
| 同義詞召回率 | +30% |
| 搜索精準度 | +25% |

---

## ✅ 設計確認檢查

- [x] 每次搜索都深度+廣度
- [x] 不需要 Agent 選擇模式
- [x] 內部智能限流
- [x] 優雅降級保持可靠
- [x] 專業級證據排序
- [x] 工具數量不變 (40)

---

**狀態**: 設計完成，準備 Git 提交並開始實作
