# Phase 2.1: Agent-Friendly Tool Refactoring

> **目標**: 讓 34 個 MCP Tools 對 Agent（尤其是較弱的模型）更友善
>
> **狀態**: ✅ **已完成** (2025-01-11)

---

## 📊 完成摘要

| 階段 | 狀態 | 提交 |
|------|------|------|
| Phase 2.1.1 InputNormalizer | ✅ 完成 | `98f0b52` |
| Phase 2.1.3 discovery.py (6 tools) | ✅ 完成 | `deef9bb` |
| Phase 2.1.3 export.py (3 tools) | ✅ 完成 | `deef9bb` |
| Phase 2.1.3 europe_pmc.py (5 tools) | ✅ 完成 | `deef9bb` |
| Phase 2.1.3 core.py (5 tools) | ✅ 完成 | `d5ef678` |
| Phase 2.1.3 ncbi_extended.py (7 tools) | ✅ 完成 | `d5ef678` |
| Phase 2.1.3 citation_tree.py (2 tools) | ✅ 完成 | `d5ef678` |
| Phase 2.1.3 strategy.py (2 tools) | ✅ 完成 | `d5ef678` |
| Phase 2.1.3 pico.py (1 tool) | ✅ 完成 | `d5ef678` |
| Phase 2.1.3 merge.py (1 tool) | ✅ 完成 | `d5ef678` |
| Phase 2.1.3 unified.py (2 tools) | ✅ 完成 | `d5ef678` |

**總計: 34/34 工具已套用 InputNormalizer + ResponseFormatter**

---

## 🔍 現況分析

### 工具清單 (34 tools by module)

| Module | Tools | 用途 | 狀態 |
|--------|-------|------|------|
| **discovery** (6) | search_literature, find_related_articles, find_citing_articles, get_article_references, fetch_article_details, get_citation_metrics | 核心搜尋 | ✅ |
| **ncbi_extended** (7) | search_gene, get_gene_details, get_gene_literature, search_compound, get_compound_details, get_compound_literature, search_clinvar | NCBI 擴展 | ✅ |
| **europe_pmc** (5) | search_europe_pmc, get_fulltext, get_fulltext_xml, get_text_mined_terms, get_europe_pmc_citations | Europe PMC | ✅ |
| **core** (5) | search_core, search_core_fulltext, get_core_paper, get_core_fulltext, find_in_core | CORE OA | ✅ |
| **export** (3) | prepare_export, get_article_fulltext_links, analyze_fulltext_access | 匯出 | ✅ |
| **citation_tree** (2) | build_citation_tree, suggest_citation_tree | 引用網絡 | ✅ |
| **unified** (2) | unified_search, analyze_search_query | 統一搜尋 | ✅ |
| **strategy** (2) | generate_search_queries, expand_search_queries | 搜尋策略 | ✅ |
| **pico** (1) | parse_pico | PICO 解析 | ✅ |
| **merge** (1) | merge_search_results | 結果合併 | ✅ |

---

## ❌ 識別出的 Agent 不友善問題

### 1. 參數名稱不一致 (Key Inconsistency)

```python
# 問題: 同樣概念用不同的 key
search_literature(limit=10)        # limit
search_europe_pmc(limit=10)        # limit (OK)
get_citation_metrics(min_citations=5)  # min_citations
build_citation_tree(limit_per_level=5) # limit_per_level (不一致!)

# 問題: 年份參數不一致
search_literature(min_year=2020, max_year=2024)
search_core(year_from=2020, year_to=2024)  # 不同命名!
```

### 2. PMID 格式混亂 (ID Format Chaos)

```python
# 問題: 有的接受單一 PMID，有的接受逗號分隔
find_related_articles(pmid="12345678")         # 單一 PMID
fetch_article_details(pmids="12345678,87654321")  # 逗號分隔
get_citation_metrics(pmids="12345678,87654321")   # 逗號分隔

# 問題: 有的用 pmid，有的用 pmcid
get_fulltext(pmcid="PMC7096777")
get_article_fulltext_links(pmid="12345678")
```

### 3. 缺少輸入驗證和自動修正

```python
# Agent 可能傳入錯誤格式
pmids = "PMID:12345678"  # 多加了 PMID: 前綴
pmids = "12345678 87654321"  # 用空格而非逗號
pmids = ["12345678", "87654321"]  # 用 list 而非字串

# 應該自動校正這些常見錯誤!
```

### 4. 缺少智能預設值

```python
# 問題: 有些工具沒有合理預設值
get_europe_pmc_citations(pmid=None, pmcid=None)  # 兩個都是 None!

# 問題: 預設值太小或太大
find_related_articles(pmid, limit=5)  # 預設 5 太少
get_article_references(pmid, limit=20)  # 可能 20 太多
```

### 5. 回傳格式不統一

```python
# 有的回傳 Markdown，有的回傳 JSON 字串
search_literature()  # 回傳格式化 Markdown
unified_search(output_format="json")  # 可選 JSON
get_gene_details()  # 回傳 JSON 字串
```

### 6. 錯誤訊息不夠友善

```python
# 不好的錯誤訊息
"Error: API call failed"

# 應該是
"Error: PubMed search failed for query 'xxx'.
 Suggestion: Check if the query syntax is correct.
 Example: 'diabetes AND treatment'"
```

---

## ✅ Phase 2.1 重構計畫

### Step 1: 建立 Input Normalizer (`_common.py`)

```python
# 新增: 統一的輸入規範化工具

class InputNormalizer:
    """Agent 友善的輸入規範化器"""

    @staticmethod
    def normalize_pmids(value: str | list | int) -> list[str]:
        """
        接受多種 PMID 格式，統一轉為 list[str]

        支援格式:
        - "12345678"
        - "12345678,87654321"
        - "12345678 87654321"  
        - "PMID:12345678"
        - ["12345678", "87654321"]
        - 12345678 (int)
        """
        pass

    @staticmethod
    def normalize_pmid_single(value: str | int) -> str:
        """單一 PMID 規範化"""
        pass

    @staticmethod  
    def normalize_year(value: str | int | None) -> int | None:
        """
        年份規範化

        支援:
        - 2024 (int)
        - "2024" (str)
        - "2024年"
        """
        pass

    @staticmethod
    def normalize_limit(value: int | str | None, default: int = 10, max_val: int = 100) -> int:
        """限制數量規範化，確保在合理範圍"""
        pass

    @staticmethod
    def normalize_bool(value: bool | str | int | None, default: bool = False) -> bool:
        """
        布林值規範化

        支援:
        - True/False
        - "true"/"false" (case insensitive)
        - "yes"/"no"
        - 1/0
        """
        pass
```

### Step 2: 建立 Response Formatter (`_common.py`)

```python
class ResponseFormatter:
    """統一的回應格式化器"""

    @staticmethod
    def success(
        data: Any,
        message: str = None,
        metadata: dict = None,
        output_format: str = "markdown"
    ) -> str:
        """成功回應"""
        pass

    @staticmethod
    def error(
        error: Exception | str,
        suggestion: str = None,
        example: str = None,
        tool_name: str = None
    ) -> str:
        """
        友善的錯誤回應

        Output:
        ❌ Error in {tool_name}: {error}

        💡 Suggestion: {suggestion}

        📝 Example: {example}
        """
        pass

    @staticmethod
    def no_results(
        query: str = None,
        suggestions: list[str] = None
    ) -> str:
        """無結果回應，附帶建議"""
        pass
```

### Step 3: 參數名稱標準化

```python
# 統一參數命名規範

STANDARD_PARAMS = {
    # ID 類
    "pmid": "單一 PMID (str)",
    "pmids": "多個 PMID, 逗號分隔 (str)",
    "pmcid": "PMC ID (str)",
    "doi": "DOI (str)",

    # 數量類
    "limit": "結果數量上限 (int)",  # 統一用 limit
    "max_results": "DEPRECATED → use limit",
    "limit_per_level": "DEPRECATED → use limit",

    # 年份類
    "min_year": "最小年份 (int)",  # 統一用 min_year
    "max_year": "最大年份 (int)",
    "year_from": "DEPRECATED → use min_year",
    "year_to": "DEPRECATED → use max_year",

    # 格式類
    "output_format": "輸出格式: markdown/json (str)",
    "format": "DEPRECATED → use output_format",
}
```

### Step 4: 工具分類與精簡

```
現有 38 工具 → 建議精簡為核心 + 進階

┌─────────────────────────────────────────────────────────────┐
│  🌟 核心工具 (Agent 最常用, 14 tools)                        │
├─────────────────────────────────────────────────────────────┤
│  unified_search        ← 主入口，自動分流                    │
│  analyze_search_query  ← 查詢分析                           │
│  fetch_article_details ← 取得文章詳情                        │
│  get_article_references← 參考文獻                           │
│  find_citing_articles  ← 引用文章                           │
│  find_related_articles ← 相關文章                           │
│  get_fulltext          ← 全文 (Europe PMC)                  │
│  prepare_export        ← 匯出引用                           │
│  get_citation_metrics  ← 引用指標                           │
│  build_citation_tree   ← 引用網絡                           │
│  get_session_pmids     ← Session PMIDs                     │
│  list_search_history   ← 搜尋歷史                           │
│  generate_search_queries← 搜尋策略                          │
│  parse_pico            ← PICO 解析                          │
├─────────────────────────────────────────────────────────────┤
│  🔧 進階工具 (特定場景, 24 tools)                            │
├─────────────────────────────────────────────────────────────┤
│  search_literature     ← 直接 PubMed (進階用戶)              │
│  search_europe_pmc     ← 直接 Europe PMC                    │
│  search_core           ← 直接 CORE                          │
│  search_gene           ← 基因搜尋                           │
│  search_compound       ← 化合物搜尋                         │
│  ...等                                                      │
└─────────────────────────────────────────────────────────────┘
```

### Step 5: 智能路由 (Smart Routing)

```python
# 在 unified_search 增加更智能的路由

@mcp.tool()
def smart_route(
    query: str = None,
    pmid: str = None,
    doi: str = None,
    action: str = None,  # search/details/related/citing/export
) -> str:
    """
    🧠 智能路由 - 根據輸入自動選擇最佳工具

    Agent 不確定用哪個工具時，可以用這個！

    Examples:
        smart_route(query="diabetes treatment")
        → 自動呼叫 unified_search

        smart_route(pmid="12345678", action="details")
        → 自動呼叫 fetch_article_details

        smart_route(pmid="12345678", action="related")
        → 自動呼叫 find_related_articles

        smart_route(doi="10.1234/example")
        → 解析 DOI，找到 PMID，取得詳情
    """
    pass
```

---

## 📋 實作優先順序

### Phase 2.1.1 - Input Normalizer (2h) ⭐⭐⭐⭐⭐
- [ ] `InputNormalizer` class
- [ ] `normalize_pmids()` - 多格式 PMID 支援
- [ ] `normalize_year()` - 年份格式化
- [ ] `normalize_limit()` - 限制數量規範
- [ ] `normalize_bool()` - 布林值規範
- [ ] Unit tests

### Phase 2.1.2 - Response Formatter (2h) ⭐⭐⭐⭐
- [ ] `ResponseFormatter` class
- [ ] `success()` - 成功回應
- [ ] `error()` - 友善錯誤訊息
- [ ] `no_results()` - 無結果建議
- [ ] Unit tests

### Phase 2.1.3 - 現有工具改造 (4h) ⭐⭐⭐⭐⭐
- [ ] 套用 InputNormalizer 到所有工具
- [ ] 套用 ResponseFormatter 到所有工具
- [ ] 參數名稱標準化 (deprecation warnings)
- [ ] Integration tests

### Phase 2.1.4 - Smart Router (2h) ⭐⭐⭐
- [ ] `smart_route()` 工具
- [ ] 自動意圖偵測
- [ ] 工具選擇邏輯
- [ ] Documentation

---

## 📊 預期成效

| 改進項目 | Before | After |
|----------|--------|-------|
| PMID 格式容錯 | 只接受精確格式 | 自動校正常見錯誤 |
| 年份格式 | 不一致 (min_year/year_from) | 統一 + 自動校正 |
| 錯誤訊息 | "API error" | 含建議和範例 |
| 工具選擇 | Agent 需要記住 38 個工具 | smart_route 自動路由 |
| 預設值 | 部分缺失 | 全部有合理預設 |

---

## 🔗 相依關係

```
Phase 2.0 (unified_search) ✅
       ↓
Phase 2.1 (Tool Refactor) 📋 ← YOU ARE HERE
       ↓
Phase 2.5 (Agent 協作)
       ↓
Phase 3.0 (測試與監控)
```
