# Phase 4: Biomedical Image Search

> **目標**: 整合 Open-i 和 Europe PMC 圖片搜尋，提供統一的生物醫學圖片搜尋 MCP 工具
>
> **狀態**: ✅ **已完成** (v0.3.0, 2026-02-09)
>
> **API 參考**: [docs/IMAGE_SEARCH_API.md](IMAGE_SEARCH_API.md)

---

## ✅ 完成摘要

| 階段 | 狀態 | 說明 |
|------|------|------|
| Phase 4.1 Open-i MVP | ✅ 完成 | `search_biomedical_images` tool, OpenIClient, ImageResult entity |
| Phase 4.2 Advisor 智慧化 | ✅ 完成 | `ImageQueryAdvisor` 查詢分析、image_type 推薦、時序警告 |
| Phase 4.3 Europe PMC XML | 🔜 未來 | 從全文 XML 提取圖片 |
| Phase 4.4 多來源聚合 | 🔜 未來 | Open-i + Europe PMC 合併去重 |

### 實作成果

- **1 個新 MCP Tool**: `search_biomedical_images`
- **DDD 分層架構**:
  - Domain: [image.py](../src/pubmed_search/domain/entities/image.py) (`ImageResult`, `ImageSource`)
  - Infrastructure: [openi.py](../src/pubmed_search/infrastructure/sources/openi.py) (`OpenIClient`)
  - Application: [service.py](../src/pubmed_search/application/image_search/service.py) + [advisor.py](../src/pubmed_search/application/image_search/advisor.py)
  - Presentation: [image_search.py](../src/pubmed_search/presentation/mcp_server/tools/image_search.py)
- **測試覆蓋**: 44 + 48 = 92 個測試 (unit + advisor)
- **Live E2E 測試**: 6 個 integration 測試 (`test_integration.py`)

### 關鍵發現 (API 行為變更)

> ⚠️ **2026-02 發現**: Open-i API 的 `it` 參數現在是**必填**！
> - 省略 `it` → `{"total": 0, "Query-Error": "Invalid request type."}`
> - 有效值: `xg` (X-ray), `mc` (Microscopy), `ph` (Photo), `gl` (Graphics)
> - 無效值 (`ct`, `mr`, `us`, `all`) 全部返回錯誤
> - 詳見 [IMAGE_SEARCH_API.md](IMAGE_SEARCH_API.md) Round 2 測試紀錄

---

## 📊 設計概要 (實際實作)

| 項目 | 說明 |
|------|------|
| **新增 MCP Tool** | 1 個 (`search_biomedical_images`) |
| **新增 Infrastructure** | 1 個 client (`OpenIClient`) |
| **新增 Domain** | 1 個 entity (`ImageResult`) + 1 個 enum (`ImageSource`) |
| **新增 Application** | 2 個 module (`ImageSearchService`, `ImageQueryAdvisor`) |
| **資料來源** | Open-i (NLM) — Phase 4.3+ 將加入 Europe PMC |
| **智慧化功能** | 查詢適合性評分、image_type 推薦、2020 時序警告 |
| **測試** | 92 個單元測試 + 6 個 Live E2E 測試 |

---

## 🔍 背景與動機

### 使用案例

1. **臨床教學**: 醫師搜尋 X-ray / CT / MRI 教學影像
2. **文獻回顧**: 研究者尋找含有特定圖表（存活曲線、流程圖）的論文
3. **視覺輔助搜尋**: 使用者上傳圖片 → Agent VLM 分析 → 搜尋相似文獻圖片
4. **特定文章圖片提取**: 已知某篇論文，提取所有圖片及說明

### 與現有功能的關係

```
現有 vision_search.py:
├── analyze_figure_for_search  → 使用者上傳圖片 → Agent VLM 分析
└── reverse_image_search_pubmed → 分析結果 → 文字搜尋

新增 Phase 4:
└── search_biomedical_images → 直接關鍵字搜尋 → 回傳圖片 URL + metadata
```

現有 `vision_search.py` 是「圖片 → 文字」流程，Phase 4 是「文字 → 圖片」流程，互補。

---

## 🏗️ DDD 架構設計

基於[架構審查報告](#架構審查建議)，本次設計遵循以下原則：
- Domain 實體**不**放來源耦合的工廠方法
- Infrastructure client **使用** `http/client.py` 共用客戶端
- Presentation **透過** Application 層呼叫
- 新增 Infrastructure 的 mapper 負責來源格式轉換

### 分層結構

```
src/pubmed_search/
├── domain/
│   └── entities/
│       └── image.py              # [新] ImageResult 實體
├── application/
│   └── image_search/
│       ├── __init__.py           # [新] 公開 API
│       └── service.py            # [新] ImageSearchService
├── infrastructure/
│   └── sources/
│       ├── openi.py              # [新] OpenIClient
│       └── europe_pmc.py         # [修改] 擴展圖片功能
├── presentation/
│   └── mcp_server/
│       └── tools/
│           └── image_search.py   # [新] MCP tool 註冊
```

---

## 📐 Domain 層設計

### ImageResult 實體

```python
# src/pubmed_search/domain/entities/image.py

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class ImageSource(str, Enum):
    """圖片來源 (與 ArticleType/MilestoneType 一致使用 Enum)。"""
    OPENI = "openi"
    EUROPE_PMC = "europe_pmc"
    MEDPIX = "medpix"


@dataclass
class ImageResult:
    """
    統一的生物醫學圖片搜尋結果。

    純 Domain 實體 — 不包含任何來源特定的工廠方法。
    來源轉換由 Infrastructure mapper 負責。
    """
    # 圖片資訊
    image_url: str
    thumbnail_url: str | None = None
    caption: str = ""
    label: str = ""                    # e.g., "Figure 1"

    # 來源資訊
    source: str = ""                   # ImageSource 常數
    source_id: str = ""                # 來源內部 ID

    # 關聯文章資訊
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    article_title: str = ""
    journal: str = ""
    authors: str = ""
    pub_year: int | None = None

    # 圖片分類 (Open-i 特有，其他來源可為空)
    image_type: str | None = None      # "xg" (X-ray), "mc" (Microscopy)
    mesh_terms: list[str] = field(default_factory=list)
    collection: str | None = None      # "pmc", "mpx", "iu"

    @property
    def has_article_link(self) -> bool:
        """是否有關聯的文章識別碼。"""
        return bool(self.pmid or self.pmcid or self.doi)

    @property
    def best_identifier(self) -> str:
        """最佳識別碼。"""
        if self.pmid:
            return f"PMID:{self.pmid}"
        if self.pmcid:
            return self.pmcid
        if self.doi:
            return f"DOI:{self.doi}"
        return self.source_id

    def to_dict(self) -> dict:
        """序列化為字典。"""
        return {
            "image_url": self.image_url,
            "thumbnail_url": self.thumbnail_url,
            "caption": self.caption,
            "label": self.label,
            "source": self.source,
            "pmid": self.pmid,
            "pmcid": self.pmcid,
            "doi": self.doi,
            "article_title": self.article_title,
            "journal": self.journal,
            "authors": self.authors,
            "pub_year": self.pub_year,
            "image_type": self.image_type,
            "mesh_terms": self.mesh_terms,
            "collection": self.collection,
        }
```

**設計要點**:
- 純 dataclass，只用 stdlib
- `ImageSource` 使用 `str, Enum`（與 `ArticleType`、`MilestoneType` 一致）
- **不**放 `from_openi()` / `from_epmc()` 工廠方法 — 這是**刻意的架構改進**，mapper 在 Infrastructure 層。現有 `UnifiedArticle.from_pubmed()` 等為歷史遺留，未來應回溯重構
- `to_dict()` 是唯一的序列化邏輯
- 需在 `domain/entities/__init__.py` 新增 `ImageResult`、`ImageSource` 匯出

---

## 🔌 Infrastructure 層設計

### OpenIClient

```python
# src/pubmed_search/infrastructure/sources/openi.py

class OpenIClient:
    """
    Open-i (NLM) 圖片搜尋客戶端。

    使用 infrastructure/http/client.py 共用 HTTP 客戶端。

    API 限制:
    - 索引停止於 ~2020
    - 圖片類型篩選只有 xg (X-ray) 和 mc (Microscopy) 有效
    - 每頁固定 ~10 筆結果
    - m 參數是偏移量，不是最大結果數
    """

    BASE_URL = "https://openi.nlm.nih.gov"
    API_URL = f"{BASE_URL}/api/search"

    VALID_IMAGE_TYPES = {"xg", "mc"}      # 實測有效的
    VALID_COLLECTIONS = {"pmc", "mpx", "iu"}
    PAGE_SIZE = 10  # 固定每頁筆數

    def __init__(self):
        # 沿用既有 source client pattern (urllib.request + _make_request)
        # 與 EuropePMCClient, COREClient, OpenAlexClient 一致
        self.timeout = 15  # Open-i 回應較慢 (2-9s)
        self.user_agent = "PubMedSearchMCP/0.3.0"

    def search(
        self,
        query: str,
        image_type: str | None = None,
        collection: str | None = None,
        max_results: int = 10,
    ) -> tuple[list[ImageResult], int]:
        """
        搜尋圖片。

        Args:
            query: 搜尋關鍵字
            image_type: 圖片類型 ("xg"=X-ray, "mc"=Microscopy, None=全部)
            collection: 集合 ("pmc", "mpx"=MedPix, "iu"=Indiana, None=全部)  
            max_results: 最大結果數 (API 每頁固定 10 筆，
                         內部自動計算需要幾頁: pages = ceil(max_results/10))

        Returns:
            (images, total_count)

        Note:
            分頁停止條件:
            1. 已取得 max_results 筆
            2. 某頁結果少於 10 筆 (已到尾頁)
            3. 超過 total 總數
        """
        ...

    @staticmethod
    def _map_to_image_result(item: dict) -> ImageResult:
        """將 Open-i API 回應轉換為 Domain 實體 (Mapper)。"""
        # 圖片 URL — 需處理空值
        img_large = item.get('imgLarge', '')
        img_thumb = item.get('imgThumb', '')

        return ImageResult(
            image_url=f"https://openi.nlm.nih.gov{img_large}" if img_large else "",
            thumbnail_url=f"https://openi.nlm.nih.gov{img_thumb}" if img_thumb else None,
            caption=item.get("image", {}).get("caption", ""),
            label="",
            source=ImageSource.OPENI,
            source_id=item.get("uid", ""),
            pmid=item.get("pmid"),
            pmcid=item.get("pmcid"),
            article_title=item.get("title", ""),
            journal=item.get("journal_title", ""),
            authors=item.get("authors", ""),
            image_type=None,  # API 不回傳圖片類型
            mesh_terms=OpenIClient._extract_mesh(item),
            collection=None,  # 可從 query 推斷
        )

    @staticmethod
    def _extract_mesh(item: dict) -> list[str]:
        """從 Open-i 回應提取 MeSH 詞彙。

        API 回傳格式: {"MeSH": {"major": [...], "minor": [...]}}
        展平為單一列表。
        """
        mesh = item.get("MeSH", {})
        if not isinstance(mesh, dict):
            return []
        major = mesh.get("major", [])
        minor = mesh.get("minor", [])
        return list(major) + list(minor)
```

### Lazy Init (sources/__init__.py)

```python
# src/pubmed_search/infrastructure/sources/__init__.py (修改)

_openi_client = None

def get_openi_client():
    """Get or create Open-i client (lazy initialization)."""
    global _openi_client
    if _openi_client is None:
        from .openi import OpenIClient
        _openi_client = OpenIClient()
    return _openi_client
```

### EuropePMCClient 擴展

```python
# src/pubmed_search/infrastructure/sources/europe_pmc.py (修改)
# 新增 ~50 行，當前 ~665 行 → ~715 行，可接受

class EuropePMCClient:
    # ... 現有方法 ...

    # [新增] 圖片說明搜尋
    def search_figure_captions(
        self,
        query: str,
        open_access_only: bool = True,
        limit: int = 10,
    ) -> list[dict]:
        """
        搜尋含有特定圖片說明的文章。
        使用 Europe PMC 的 FIG: 查詢語法。

        Returns: 文章列表 (非圖片)
        """
        search_query = f'FIG:"{query}"'
        if open_access_only:
            search_query += " AND OPEN_ACCESS:y"
        return self.search(search_query, limit=limit)

    # [新增] 從全文 XML 提取圖片
    def extract_figures(self, pmcid: str) -> list[dict]:
        """
        從 Europe PMC 全文 XML 提取所有圖片。

        回傳 raw dict 列表 (與其他方法一致)，
        由 Application 層 mapper 轉換為 ImageResult。

        Returns:
            list[dict]: [{"id", "label", "caption", "href", "pmcid"}, ...]
        """
        ...
```

---

## 🎯 Application 層設計

### ImageSearchService

```python
# src/pubmed_search/application/image_search/service.py

class ImageSearchService:
    """
    圖片搜尋應用服務。

    協調 Open-i 和 Europe PMC 圖片搜尋，
    負責多來源結果合併和去重。
    """

    def search(
        self,
        query: str,
        sources: list[str] | None = None,    # ["openi", "europe_pmc"]
        image_type: str | None = None,        # "xg", "mc"
        collection: str | None = None,        # "pmc", "mpx", "iu"
        open_access_only: bool = True,
        limit: int = 10,
    ) -> ImageSearchResult:
        """
        統一圖片搜尋。

        自動選擇來源或按 sources 參數指定。
        合併結果並按 PMID/PMCID 去重。
        """
        ...

    def extract_article_figures(
        self,
        pmcid: str,
    ) -> list[ImageResult]:
        """提取特定文章的所有圖片。"""
        ...

    def _merge_results(
        self,
        *result_lists: list[ImageResult],
    ) -> list[ImageResult]:
        """合併多來源結果，按 PMID 去重。"""
        ...


@dataclass
class ImageSearchResult:
    """圖片搜尋結果包裝。"""
    images: list[ImageResult]
    total_count: int
    sources_used: list[str]
    query: str
```

---

## 🖥️ Presentation 層設計

### MCP Tool

```python
# src/pubmed_search/presentation/mcp_server/tools/image_search.py

def register_image_search_tools(mcp: FastMCP):
    """Register biomedical image search MCP tools.

    Note: 不需要 searcher 參數，ImageSearchService 自行管理 client。
    與 register_vision_tools(mcp) 模式一致。
    """

    @mcp.tool()
    def search_biomedical_images(
        query: str,
        sources: str = "auto",
        image_type: str | None = None,
        collection: str | None = None,
        open_access_only: Union[bool, str] = True,
        limit: Union[int, str] = 10,
    ) -> str:
        """
        🖼️ Search biomedical images across Open-i and Europe PMC.

        Searches medical/scientific images from multiple sources and returns
        image URLs with metadata (caption, article info, MeSH terms).

        ═══════════════════════════════════════════════════════════════
        SOURCES:
        ═══════════════════════════════════════════════════════════════
        - Open-i (NLM): X-ray, microscopy, clinical images (~133K)
        - Europe PMC: Figure captions from 33M+ articles
        - MedPix: Clinical teaching images (via Open-i coll=mpx)

        ═══════════════════════════════════════════════════════════════
        EXAMPLES:
        ═══════════════════════════════════════════════════════════════

        General image search:
            search_biomedical_images("chest pneumonia CT scan")

        X-ray only:
            search_biomedical_images("fracture", image_type="xg")

        Clinical teaching images:
            search_biomedical_images("pneumothorax", collection="mpx")

        Survival curves / charts:
            search_biomedical_images("kaplan meier survival", sources="europe_pmc")

        ═══════════════════════════════════════════════════════════════

        Args:
            query: Search query (e.g., "chest X-ray pneumonia")
            sources: Image sources to search:
                - "auto": Select best sources (default)
                - "openi": Open-i only (best for medical images)
                - "europe_pmc": Europe PMC only (best for figure captions)
                - "all": Search all sources
            image_type: Filter by image type (Open-i only):
                - "xg": X-ray images
                - "mc": Microscopy images
                - None: All types (default)
            collection: Filter by collection (Open-i only):
                - "pmc": PubMed Central articles
                - "mpx": MedPix clinical teaching images
                - "iu": Indiana University radiology reports
                - None: All collections (default)
            open_access_only: Only return open access images (default True)
            limit: Maximum number of images to return (default 10)

        Returns:
            Formatted image results with URLs, captions, and article metadata
        """
        # 1. 輸入驗證 (InputNormalizer)
        query = InputNormalizer.normalize_query(query)
        limit = InputNormalizer.normalize_limit(limit, default=10, max_val=50)
        open_access_only = InputNormalizer.normalize_bool(open_access_only, default=True)

        # 2. sources 字串 → 列表映射
        # "auto" → None (service 自行選源)
        # "openi" → ["openi"]
        # "europe_pmc" → ["europe_pmc"]
        # "all" → ["openi", "europe_pmc"]
        source_map = {
            "auto": None,
            "openi": ["openi"],
            "europe_pmc": ["europe_pmc"],
            "all": ["openi", "europe_pmc"],
        }
        source_list = source_map.get(sources, None)

        # 3. 呼叫 ImageSearchService
        service = ImageSearchService()
        result = service.search(
            query=query, sources=source_list,
            image_type=image_type, collection=collection,
            open_access_only=open_access_only, limit=limit,
        )

        # 4. 格式化輸出 (ResponseFormatter)
        return _format_image_results(result)
        ...
```

**設計要點**:
- 使用 `InputNormalizer` / `ResponseFormatter` (與現有 tools 一致)
- 透過 `ImageSearchService` 呼叫，不直接呼叫 Infrastructure
- 文件風格遵循現有 `unified_search` 的 docstring 格式

---

## 📋 實作計劃 (4 階段)

### Phase 4.1: Open-i 基礎整合 ⭐ MVP
> 預計影響: 4 個新檔案

| 步驟 | 檔案 | 說明 |
|------|------|------|
| 1 | `domain/entities/image.py` | `ImageResult` dataclass |
| 2 | `infrastructure/sources/openi.py` | `OpenIClient` + mapper |
| 3 | `application/image_search/service.py` | `ImageSearchService` (Open-i only) |
| 4 | `presentation/mcp_server/tools/image_search.py` | `search_biomedical_images` tool |
| 5 | 修改 `infrastructure/sources/__init__.py` | 新增 `get_openi_client()` lazy init |
| 6 | 修改 `domain/entities/__init__.py` | 匯出 `ImageResult`, `ImageSource` |
| 7 | 修改 `presentation/mcp_server/tools/__init__.py` | import + `register_all_tools()` 加入呼叫 |
| 8 | 修改 `presentation/mcp_server/tool_registry.py` | `TOOL_CATEGORIES["image_search"]` 新增分類 |
| 9 | 測試 | `tests/test_image_search.py` |

**驗收標準**:
- `search_biomedical_images("chest pneumonia")` 回傳圖片 URL + metadata
- `image_type="xg"` 篩選有效
- `collection="mpx"` 篩選有效

### Phase 4.2: Europe PMC 圖片說明搜尋
> 預計影響: 修改 2 個檔案

| 步驟 | 檔案 | 說明 |
|------|------|------|
| 1 | 修改 `infrastructure/sources/europe_pmc.py` | 新增 `search_figure_captions()` |
| 2 | 修改 `application/image_search/service.py` | 整合 EPMC 來源 |
| 3 | 測試 | 新增 EPMC 圖片搜尋測試 |

**驗收標準**:
- `search_biomedical_images("kaplan meier", sources="europe_pmc")` 回傳含圖片說明的文章

### Phase 4.3: Europe PMC XML 圖片提取
> 預計影響: 修改 2 個檔案

| 步驟 | 檔案 | 說明 |
|------|------|------|
| 1 | 修改 `infrastructure/sources/europe_pmc.py` | 新增 `extract_figures()` |
| 2 | 修改 `application/image_search/service.py` | 新增 `extract_article_figures()` |
| 3 | 可選: 新增 tool `extract_article_figures` | 提取指定文章的所有圖片 |

**驗收標準**:
- 輸入 PMCID → 提取所有圖片 URL + caption
- 圖片 URL 可直接存取

### Phase 4.4: 多來源聚合 + 去重
> 預計影響: 修改 1 個檔案

| 步驟 | 檔案 | 說明 |
|------|------|------|
| 1 | 修改 `application/image_search/service.py` | `sources="auto"` 智慧選源 + PMID 去重 |
| 2 | 測試 | 多來源合併測試 |

**驗收標準**:
- `sources="all"` 合併 Open-i + EPMC 結果
- 同一 PMID 的結果不重複

---

## 📝 與現有 vision_search.py 的整合

Phase 4 完成後，`reverse_image_search_pubmed` 的 workflow 可以增強為：

```
使用者上傳圖片
  → analyze_figure_for_search (VLM 分析)
  → Agent 理解圖片內容
  → search_biomedical_images (Phase 4, 直接圖片搜尋)  ← 新增
  → 回傳相似圖片 + 關聯文獻
```

而非目前的「VLM 分析 → 純文字搜尋 PubMed」流程。

---

## ⚠️ 已知限制

| 限制 | 來源 | 影響 | 應對 |
|------|------|------|------|
| 索引停止 ~2020 | Open-i | 無法搜尋近期文獻圖片 | 使用 Europe PMC 補充 |
| 每頁固定 10 筆 | Open-i | 大量結果需要多次請求 | 分頁邏輯處理 |
| 只有 xg/mc 有效 | Open-i `it` 參數 | 無法篩選 CT/MRI/超音波 | 文件中說明 |
| FIG: 回傳文章非圖片 | Europe PMC | 需要二次 XML 提取 | Phase 4.3 實作 |
| 圖片無語義搜尋 | 全部 | 只能關鍵字匹配 | 搭配 VLM 使用 |
| 回應速度 2-9 秒 | Open-i | 較慢 | 設定 15s timeout |

---

## 📊 測試策略

```
tests/
├── test_image_search.py             # Application 層測試
├── test_openi_client.py             # Infrastructure 單元測試  
└── test_image_search_tool.py        # Presentation 工具測試
```

**測試方法**:
- Mock HTTP 回應 (與現有 test_europe_pmc.py, test_core.py 一致)
- 不依賴外部 API 的離線測試
- 依照 `IMAGE_SEARCH_API.md` 附錄的測試數據建構 fixtures

---

## 🔗 相關文件

| 文件 | 說明 |
|------|------|
| [docs/IMAGE_SEARCH_API.md](IMAGE_SEARCH_API.md) | API 參考 + 測試記錄 |
| [ARCHITECTURE.md](../ARCHITECTURE.md) | DDD 架構概覽 |
| [docs/PHASE_2.1_TOOL_REFACTOR.md](PHASE_2.1_TOOL_REFACTOR.md) | 工具重構參考 |
| [docs/PHASE_3_PUBTATOR_EUTILS.md](PHASE_3_PUBTATOR_EUTILS.md) | Phase 3 設計參考 |
