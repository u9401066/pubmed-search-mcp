# Phase 3: PubTator3 + E-utilities 智能文獻檢索系統

> **核心理念**: 讓 Agent 用最少的工具調用，獲得最好的文獻答案
> **設計原則**: 內部豐富、外部精簡、智能優先、優雅降級
> **狀態**: 設計完成，準備實作

---

## 🎯 高階理念：什麼是「最好的文獻搜索」？

### 核心價值主張

一個**實戰等級**的文獻搜索系統應該：

```text
1. 精準 (Precision)    → 找到最相關的文獻，不是最多的文獻
2. 全面 (Recall)       → 不遺漏重要文獻，特別是用不同術語描述的相同概念
3. 快速 (Speed)        → 快速回應，不讓用戶等待
4. 智能 (Intelligence) → 理解用戶真正想要什麼，而不只是字面匹配
5. 可靠 (Reliability)  → 穩定運作，API 失敗時優雅降級
```

### 搜索策略：深度 vs 廣度

| 模式 | 策略 | 適用場景 | API 預算 |
|------|------|----------|----------|
| **快速模式** | 廣度優先 | "找幾篇 propofol 文獻" | 低 (1-2 calls) |
| **全面模式** | 深度優先 | "系統性回顧 propofol" | 高 (5-10 calls) |
| **探索模式** | 平衡 | "propofol 有什麼新發現" | 中 (3-5 calls) |

**關鍵洞察**：Agent 不需要每次都用最強的搜索。根據意圖自動選擇策略。

---

## 🧠 對應 Agent 需求分析

### Agent 會怎麼使用這個工具？

| Agent 意圖 | 內部處理 | 期望結果 |
|------------|----------|----------|
| "找 propofol 相關文獻" | 快速模式：PubMed 基本搜索 | 10 篇相關文章 |
| "propofol 和 dexmedetomidine 比較" | 全面模式：實體解析 + 語義搜索 | PICO 結構化結果 |
| "BRCA1 和什麼疾病相關？" | 關係模式：PubTator3 關係查詢 | 疾病列表 + 證據文獻 |
| "這篇文章的相關研究" | 引用模式：Related + Citing | 引用網絡 |
| "propofol 最新臨床試驗" | 時效模式：PubMed + ClinVar | 按時間排序結果 |

### 設計決策

**不要讓 Agent 決定用哪個 API**，而是：

```text
Agent: "propofol sedation"
                ↓
    ┌─────────────────────────────┐
    │  QueryAnalyzer (內部智能)    │
    │  1. 意圖識別：一般搜索       │
    │  2. 複雜度：簡單             │
    │  3. 決策：快速模式           │
    └─────────────────────────────┘
                ↓
         直接 PubMed 搜索，不做語義增強（省時）
                ↓
         返回 Top 10 結果
         
Agent: "propofol versus dexmedetomidine for ICU sedation systematic review"
                ↓
    ┌─────────────────────────────┐
    │  QueryAnalyzer (內部智能)    │
    │  1. 意圖識別：系統性回顧     │
    │  2. 複雜度：複雜 (PICO)      │
    │  3. 決策：全面模式           │
    └─────────────────────────────┘
                ↓
         1. PubTator3 實體解析 (propofol → @CHEMICAL_Propofol)
         2. MeSH 展開 (sedation → Conscious Sedation, Deep Sedation...)
         3. 多策略並行搜索
         4. Union-Find 去重
         5. 證據等級排序
                ↓
         返回結構化結果 + 搜索策略說明
```

---

## ⚡ 效能優化：限流處理策略

### API 速率限制

| API | 限制 | 應對策略 |
|-----|------|----------|
| PubTator3 | 3 req/sec | 請求合併 + 快取 |
| NCBI E-utils | 3 req/sec (無 key) / 10 req/sec (有 key) | 使用 API key |
| Europe PMC | 無官方限制 | 禮貌性延遲 0.1s |

### 內部限流架構

```python
class RateLimitedClient:
    """統一的限流客戶端基礎類"""
    
    def __init__(self, rate_limit: float = 3.0):
        self._rate_limit = rate_limit
        self._semaphore = asyncio.Semaphore(rate_limit)
        self._last_request = 0.0
        
    async def execute_with_limit(self, coro):
        """帶限流的執行"""
        async with self._semaphore:
            # 確保間隔
            elapsed = time.time() - self._last_request
            if elapsed < 1.0 / self._rate_limit:
                await asyncio.sleep(1.0 / self._rate_limit - elapsed)
            self._last_request = time.time()
            return await coro
```

### 智能快取層

```python
class EntityCache:
    """實體解析快取 - 減少 API 調用"""
    
    def __init__(self, max_size: int = 1000, ttl: int = 3600):
        self._cache: dict[str, tuple[Any, float]] = {}
        self._max_size = max_size
        self._ttl = ttl
        
    async def get_or_fetch(self, key: str, fetch_func) -> Any:
        """快取命中或執行查詢"""
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self._ttl:
                return value  # 快取命中，省一次 API 調用
                
        # 快取未命中，執行查詢
        value = await fetch_func()
        self._cache[key] = (value, time.time())
        return value
```

### 請求預算管理

```python
@dataclass
class SearchBudget:
    """每次搜索的 API 調用預算"""
    pubtator_calls: int = 3      # PubTator3 最多 3 次調用
    ncbi_calls: int = 5          # NCBI E-utils 最多 5 次調用
    total_timeout: float = 10.0  # 總超時 10 秒
    
    @classmethod
    def fast(cls) -> "SearchBudget":
        """快速模式預算"""
        return cls(pubtator_calls=0, ncbi_calls=2, total_timeout=3.0)
        
    @classmethod
    def comprehensive(cls) -> "SearchBudget":
        """全面模式預算"""
        return cls(pubtator_calls=5, ncbi_calls=10, total_timeout=15.0)
```

### 優雅降級策略

```python
async def search_with_fallback(query: str, budget: SearchBudget) -> SearchResult:
    """帶降級的搜索"""
    
    # Level 1: 嘗試完整語義搜索
    if budget.pubtator_calls > 0:
        try:
            result = await semantic_search(query, timeout=budget.total_timeout / 2)
            if result.is_satisfactory:
                return result
        except (TimeoutError, APIError):
            pass  # 降級到 Level 2
            
    # Level 2: 嘗試 MeSH 擴展搜索
    try:
        result = await mesh_expanded_search(query, timeout=budget.total_timeout / 2)
        if result.is_satisfactory:
            result.degraded_from = "semantic"
            return result
    except (TimeoutError, APIError):
        pass  # 降級到 Level 3
        
    # Level 3: 基本 PubMed 搜索（最低保證）
    result = await basic_pubmed_search(query)
    result.degraded_from = "mesh_expansion"
    return result
```

---

## 📊 內部排序策略

### 多維度排序（現有 ResultAggregator 增強）

```python
@dataclass
class EnhancedRankingConfig:
    """增強版排序配置"""
    
    # 基礎維度（現有）
    relevance_weight: float = 0.25
    quality_weight: float = 0.20
    recency_weight: float = 0.15
    impact_weight: float = 0.20
    source_trust_weight: float = 0.10
    
    # 新增維度
    entity_match_weight: float = 0.10  # PubTator3 實體匹配度
    
    # 動態調整
    @classmethod
    def for_systematic_review(cls) -> "EnhancedRankingConfig":
        """系統性回顧：重視全面性和證據等級"""
        return cls(
            relevance_weight=0.15,
            quality_weight=0.35,  # 重視證據等級
            recency_weight=0.10,
            impact_weight=0.20,
            source_trust_weight=0.10,
            entity_match_weight=0.10
        )
        
    @classmethod
    def for_latest_research(cls) -> "EnhancedRankingConfig":
        """最新研究：重視時效性"""
        return cls(
            relevance_weight=0.20,
            quality_weight=0.15,
            recency_weight=0.35,  # 重視時效
            impact_weight=0.15,
            source_trust_weight=0.05,
            entity_match_weight=0.10
        )
```

### 證據等級排序

```python
EVIDENCE_LEVEL_SCORES = {
    "meta-analysis": 1.0,
    "systematic-review": 0.95,
    "randomized-controlled-trial": 0.85,
    "clinical-trial": 0.75,
    "cohort-study": 0.65,
    "case-control-study": 0.55,
    "case-report": 0.35,
    "review": 0.50,
    "journal-article": 0.40,
    "preprint": 0.20,
}
```

---

## 🏗️ 簡化的架構設計

### 避免過度設計：YAGNI 檢查

| 功能 | 必要性 | 決定 |
|------|--------|------|
| PubTator3 實體解析 | ⭐⭐⭐⭐⭐ 核心價值 | ✅ Phase 1 |
| PubTator3 關係查詢 | ⭐⭐⭐⭐ 高價值 | ✅ Phase 1 (簡化版) |
| PubTator3 BioNER 標註 | ⭐⭐⭐ 有用但非核心 | ⏳ Phase 2 |
| 智能快取 | ⭐⭐⭐⭐⭐ 性能必須 | ✅ Phase 1 |
| 降級策略 | ⭐⭐⭐⭐⭐ 可靠性必須 | ✅ Phase 1 |
| 所有關係類型 | ⭐⭐ 過度 | ❌ 只保留 treat, associate |

### 精簡後的架構

```text
┌─────────────────────────────────────────────────────────────────────┐
│                    MCP Tools (對外 40 個，不變)                      │
│  unified_search(query, semantic_enhance=False)                      │
│  generate_search_queries(topic, include_relations=False)            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      SearchOrchestrator (新增)                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  職責：                                                      │    │
│  │  1. 意圖分析 → 選擇搜索模式（快速/全面/探索）                 │    │
│  │  2. 預算分配 → 決定 API 調用次數                             │    │
│  │  3. 降級管理 → API 失敗時優雅降級                            │    │
│  │  4. 結果組裝 → 合併多來源結果                                │    │
│  └─────────────────────────────────────────────────────────────┘    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ EntityResolver   │  │ QueryExpander    │  │ ResultRanker     │
│ (PubTator3)      │  │ (MeSH + 同義詞)  │  │ (多維度排序)    │
│                  │  │                  │  │                  │
│ - find_entity()  │  │ - expand_mesh()  │  │ - rank()         │
│ - find_relations │  │ - expand_syns()  │  │ - deduplicate()  │
│ - get_context()  │  │                  │  │                  │
└────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘
         │                     │                     │
         └─────────────────────┼─────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Infrastructure Layer                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │
│  │ PubTatorClient  │  │ NCBIClient      │  │ EntityCache         │  │
│  │ (異步 + 限流)   │  │ (現有 + 異步化) │  │ (TTL 快取)          │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📦 核心模組設計

### 1. SearchOrchestrator (協調器)

```python
"""
SearchOrchestrator - 搜索協調器

職責：
1. 分析意圖，選擇搜索策略
2. 管理 API 預算
3. 協調多個組件
4. 處理降級
"""

from dataclasses import dataclass
from enum import Enum


class SearchMode(Enum):
    FAST = "fast"           # 快速：基本 PubMed，無語義
    ENHANCED = "enhanced"   # 增強：MeSH 展開，無 PubTator3
    SEMANTIC = "semantic"   # 語義：完整 PubTator3 增強


@dataclass
class SearchIntent:
    """解析後的搜索意圖"""
    mode: SearchMode
    is_pico: bool = False
    is_systematic: bool = False
    entities: list[str] = None  # 識別的實體
    budget: "SearchBudget" = None


class SearchOrchestrator:
    """搜索協調器 - 統一入口"""
    
    def __init__(
        self,
        entity_resolver: "EntityResolver",
        query_expander: "QueryExpander", 
        result_ranker: "ResultRanker",
        cache: "EntityCache"
    ):
        self._resolver = entity_resolver
        self._expander = query_expander
        self._ranker = result_ranker
        self._cache = cache
        
    async def search(
        self,
        query: str,
        semantic_enhance: bool = False,  # 預設關閉（快速模式）
        limit: int = 20
    ) -> "SearchResult":
        """
        主搜索入口
        
        Args:
            query: 搜索查詢
            semantic_enhance: 是否啟用語義增強
            limit: 結果數量
            
        Returns:
            SearchResult with articles, metadata, and quality indicators
        """
        # Step 1: 分析意圖
        intent = await self._analyze_intent(query, semantic_enhance)
        
        # Step 2: 執行搜索（帶降級）
        if intent.mode == SearchMode.SEMANTIC:
            result = await self._semantic_search(query, intent, limit)
        elif intent.mode == SearchMode.ENHANCED:
            result = await self._enhanced_search(query, intent, limit)
        else:
            result = await self._fast_search(query, limit)
            
        # Step 3: 排序和後處理
        result.articles = self._ranker.rank(result.articles, intent)
        
        # Step 4: 附加質量指標
        result.quality = self._assess_quality(result, intent)
        
        return result
        
    async def _analyze_intent(self, query: str, semantic_enhance: bool) -> SearchIntent:
        """分析搜索意圖，決定策略"""
        # 使用現有 QueryAnalyzer 的本地分析
        from pubmed_search.application.search import QueryAnalyzer
        
        analyzer = QueryAnalyzer()
        analysis = analyzer.analyze(query)
        
        # 決定模式
        if semantic_enhance:
            mode = SearchMode.SEMANTIC
        elif analysis.complexity.value in ["complex", "ambiguous"]:
            mode = SearchMode.ENHANCED
        else:
            mode = SearchMode.FAST
            
        # 設定預算
        if mode == SearchMode.SEMANTIC:
            budget = SearchBudget.comprehensive()
        elif mode == SearchMode.ENHANCED:
            budget = SearchBudget(pubtator_calls=0, ncbi_calls=5, total_timeout=8.0)
        else:
            budget = SearchBudget.fast()
            
        return SearchIntent(
            mode=mode,
            is_pico=analysis.pico is not None,
            is_systematic="systematic" in query.lower() or "review" in query.lower(),
            budget=budget
        )
        
    async def _semantic_search(self, query: str, intent: SearchIntent, limit: int):
        """語義搜索（完整 PubTator3）"""
        try:
            # 1. 實體解析（帶快取）
            entities = await self._resolve_entities_cached(query)
            
            # 2. 構建語義查詢
            if entities:
                semantic_query = self._build_semantic_query(query, entities)
            else:
                semantic_query = query
                
            # 3. 執行搜索
            articles = await self._execute_search(semantic_query, limit)
            
            return SearchResult(
                articles=articles,
                mode=SearchMode.SEMANTIC,
                entities_found=entities,
                query_used=semantic_query
            )
        except Exception as e:
            # 降級到 enhanced
            return await self._enhanced_search(query, intent, limit)
            
    async def _resolve_entities_cached(self, query: str) -> list:
        """解析實體（帶快取）"""
        cache_key = f"entities:{query.lower()}"
        
        async def fetch():
            return await self._resolver.resolve(query)
            
        return await self._cache.get_or_fetch(cache_key, fetch)
```

### 2. EntityResolver (實體解析器)

```python
"""
EntityResolver - PubTator3 實體解析

精簡設計：只保留核心功能
"""

from dataclasses import dataclass


@dataclass
class ResolvedEntity:
    """解析後的實體"""
    original: str           # 原始文字
    entity_id: str          # PubTator3 ID (e.g., "@CHEMICAL_Propofol")
    name: str               # 標準名稱
    type: str               # Gene, Disease, Chemical, Species, Variant
    mesh_id: str | None     # MeSH ID (如果有)
    
    @property
    def pubmed_query(self) -> str:
        """轉換為 PubMed 查詢"""
        if self.mesh_id:
            return f'"{self.name}"[MeSH Terms]'
        return f'"{self.name}"'


class EntityResolver:
    """實體解析器"""
    
    def __init__(self, pubtator_client: "PubTatorClient"):
        self._client = pubtator_client
        
    async def resolve(self, text: str) -> list[ResolvedEntity]:
        """
        解析文本中的實體
        
        Args:
            text: 要解析的文本
            
        Returns:
            識別到的實體列表
        """
        # 簡單分詞
        import re
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text)
        stop_words = {"and", "or", "the", "for", "with", "from", "about"}
        candidates = [w for w in words if w.lower() not in stop_words]
        
        if not candidates:
            return []
            
        # 並行查詢 PubTator3
        import asyncio
        tasks = [
            self._client.find_entity(word, limit=1)
            for word in candidates[:5]  # 最多 5 個詞
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 收集結果
        entities = []
        for word, result in zip(candidates, results):
            if isinstance(result, Exception) or not result:
                continue
            match = result[0]
            entities.append(ResolvedEntity(
                original=word,
                entity_id=match.entity_id,
                name=match.name,
                type=match.type,
                mesh_id=match.identifier
            ))
            
        return entities
        
    async def get_relations(
        self,
        entity_id: str,
        relation_type: str = "treat"  # 只支持最常用的
    ) -> list[dict]:
        """
        獲取實體關係
        
        Args:
            entity_id: 實體 ID
            relation_type: 關係類型 (treat, associate)
            
        Returns:
            關係列表
        """
        relations = await self._client.find_relations(
            entity_id,
            relation_type=relation_type,
            limit=10
        )
        return [
            {
                "target": r.target_entity,
                "type": r.relation_type,
                "evidence_count": r.evidence_count
            }
            for r in relations
        ]
```

### 3. PubTatorClient (HTTP 客戶端)

```python
"""
PubTatorClient - PubTator3 API 客戶端

特點：
- 異步
- 內建限流
- 優雅降級
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Literal

import httpx


@dataclass
class EntityMatch:
    entity_id: str
    name: str
    type: str
    identifier: str | None
    score: float = 1.0


@dataclass
class RelationMatch:
    source_entity: str
    relation_type: str
    target_entity: str
    evidence_count: int
    pmids: list[str]


class PubTatorClient:
    """PubTator3 API 客戶端"""
    
    BASE_URL = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api"
    RATE_LIMIT = 3.0  # requests per second
    
    def __init__(self, timeout: float = 15.0):
        self._timeout = timeout
        self._last_request = 0.0
        self._lock = asyncio.Lock()
        
    async def _rate_limit(self):
        """執行限流"""
        async with self._lock:
            elapsed = time.time() - self._last_request
            wait_time = 1.0 / self.RATE_LIMIT - elapsed
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self._last_request = time.time()
            
    async def _request(self, url: str, params: dict) -> dict | None:
        """帶重試的請求"""
        await self._rate_limit()
        
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:  # Rate limited
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise
            except httpx.TimeoutException:
                if attempt < 2:
                    continue
                raise
                
        return None
        
    async def find_entity(
        self,
        query: str,
        concept: Literal["gene", "disease", "chemical", "species", "variant"] | None = None,
        limit: int = 5
    ) -> list[EntityMatch]:
        """查找實體"""
        params = {"query": query, "limit": limit}
        if concept:
            params["concept"] = concept
            
        data = await self._request(f"{self.BASE_URL}/entity/autocomplete/", params)
        if not data:
            return []
            
        return [
            EntityMatch(
                entity_id=item.get("id", ""),
                name=item.get("name", ""),
                type=item.get("type", ""),
                identifier=item.get("identifier"),
                score=item.get("score", 1.0)
            )
            for item in data.get("results", [])
        ]
        
    async def find_relations(
        self,
        entity_id: str,
        relation_type: str | None = None,
        target_type: str | None = None,
        limit: int = 20
    ) -> list[RelationMatch]:
        """查詢關係"""
        params = {"e1": entity_id}
        if relation_type:
            params["type"] = relation_type
        if target_type:
            params["e2"] = target_type
            
        data = await self._request(f"{self.BASE_URL}/relations", params)
        if not data:
            return []
            
        return [
            RelationMatch(
                source_entity=r.get("source", ""),
                relation_type=r.get("type", ""),
                target_entity=r.get("target", ""),
                evidence_count=r.get("count", 0),
                pmids=r.get("pmids", [])[:5]
            )
            for r in data.get("results", [])[:limit]
        ]


# Singleton
_client: PubTatorClient | None = None


def get_pubtator_client() -> PubTatorClient:
    global _client
    if _client is None:
        _client = PubTatorClient()
    return _client
```

---

## 📋 實作計劃（精簡版）

### Phase 1: 核心功能 (Week 1)

| 優先級 | 任務 | 檔案 |
|--------|------|------|
| P0 | PubTatorClient | `infrastructure/pubtator/client.py` |
| P0 | EntityCache | `infrastructure/cache/entity_cache.py` |
| P0 | EntityResolver | `application/search/entity_resolver.py` |
| P0 | SearchOrchestrator | `application/search/orchestrator.py` |

### Phase 2: 整合現有 (Week 2)

| 優先級 | 任務 | 檔案 |
|--------|------|------|
| P0 | unified_search 增強 | `presentation/mcp_server/tools/search.py` |
| P1 | generate_search_queries 增強 | `presentation/mcp_server/tools/search.py` |
| P2 | NCBIExtended 異步化 | `infrastructure/sources/ncbi_extended.py` |

### Phase 3: 測試 (Week 3)

| 任務 | 說明 |
|------|------|
| 單元測試 | PubTatorClient, EntityResolver |
| 整合測試 | 端到端語義搜索 |
| 降級測試 | API 失敗場景 |
| 效能測試 | 快取效率、延遲 |

---

## 📊 成功指標

| 指標 | 目標 | 測量方式 |
|------|------|----------|
| 工具數量 | 40（不變） | `count_mcp_tools.py` |
| 快速模式延遲 | <1秒 | E2E 測試 |
| 語義模式延遲 | <3秒 | E2E 測試 |
| 快取命中率 | >80% | 日誌統計 |
| 同義詞召回率 | +30% | AB 測試 |

---

## ✅ 確認後開始實作

文件更新完成，執行：

```bash
git add .
git commit -m "docs: Phase 3 設計完成 - PubTator3 智能搜索架構"
```

然後開始 Phase 1 實作。
