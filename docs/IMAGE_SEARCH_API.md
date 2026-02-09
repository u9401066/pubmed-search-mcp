# Image Search API Reference

> 生物醫學圖片搜尋 API 參考文件
> 初始測試: 2026-02-09 | 最後更新: 2026-02-09 (it 參數行為變更)

## 概述

本專案整合兩個圖片搜尋來源：

| 來源 | 收錄量 | 圖片來源 | 認證 | 特色 |
|------|--------|----------|------|------|
| **Open-i** (NLM) | ~133K 圖片 | PMC + MedPix + Indiana | 無需 | 專業醫學影像分類 |
| **Europe PMC** | 33M+ 文獻 | PMC 開放取用文獻 | 無需 | 圖片說明搜尋 + XML 圖片提取 |

---

## 1. Open-i API (NLM)

> 官方頁面: https://openi.nlm.nih.gov/
> 維護: National Library of Medicine (NLM)

### 基礎資訊

```
Base URL: https://openi.nlm.nih.gov/api/search
Method: GET
Format: JSON
Auth: 無需
```

### Rate Limits
- 未觀察到嚴格的速率限制
- 回應時間: 2-9 秒/請求
- 建議: 間隔 1-2 秒以示禮貌

### ⚠️ 重要限制
- **索引凍結**: 索引似乎停止在 ~2020 年，搜尋 "covid" 回傳 0 結果，但 "coronavirus" 有 4,600+ 結果
- **可能已停止更新**: 不適合搜尋最新文獻圖片

### 搜尋參數

| 參數 | 類型 | 說明 | 範例 |
|------|------|------|------|
| `q` | string | 搜尋查詢詞 | `lung cancer` |
| `m` | int | **起始偏移量** (注意：不是最大結果數) | `1`, `11`, `21` |
| `it` | string | ⚠️ **必填** — 圖片類型篩選 (見下方) | `xg`, `mc`, `ph`, `gl` |
| `n` | int | 每頁回傳數量 (覆蓋預設 10) | `3`, `20` |
| `coll` | string | 集合篩選 | `pmc`, `mpx`, `iu` |
| `fields` | string | 回傳欄位 (未測試) | - |

### 圖片類型篩選 (`it` 參數)

> ⚠️ **2026-02-09 重要發現**: `it` 參數現在是 **必填**！
> 省略 `it` 參數會回傳 `{"total": 0, "Query-Error": "Invalid request type."}` 
> 這是 API 行為變更（之前省略 `it` 等同搜尋所有類型）

#### 有效的 `it` 值 (2026-02-09 實測)

| 代碼 | 類型 | 結果數量 (q=pneumonia) | 狀態 |
|------|------|------------------------|------|
| `xg` | X-ray / 放射影像 | ~1,541,988 | ✅ **有效** — 涵蓋最廣 |
| `mc` | Microscopy / 顯微鏡 | ~768,198 | ✅ **有效** |
| `ph` | Photo / 臨床照片 | ~816,743 | ✅ **有效** |
| `gl` | Graphics / 圖表線稿 | ~0 (q=pneumonia) | ✅ **有效** (query-dependent) |

#### 無效的 `it` 值

| 代碼 | 類型 | 結果 | 狀態 |
|------|------|------|------|
| `ct` | CT scan | `Query-Error: "Invalid request type."` | ❌ **回傳錯誤** |
| `mr` | MRI | `Query-Error: "Invalid request type."` | ❌ **回傳錯誤** |
| `us` | Ultrasound | `Query-Error: "Invalid request type."` | ❌ **回傳錯誤** |
| `all` | All types | `Query-Error: "Invalid request type."` | ❌ **回傳錯誤** |
| (省略) | — | `Query-Error: "Invalid request type."` | ❌ **回傳錯誤** |
| (空字串) | — | `Query-Error: "Invalid request type."` | ❌ **回傳錯誤** |

> **注意**: 與初始測試 (2026-02-09 早期) 相比，API 行為已改變。
> 之前 `gr`, `rn`, `ul`, `mr`, `ct` 等回傳等同無篩選的結果。
> 現在這些值直接回傳錯誤，且省略 `it` 也會錯誤。

**程式碼因應**: `OpenIClient` 預設 `it=xg`（涵蓋最廣），無效值 fallback 到 `xg`。

### 集合篩選 (`coll` 參數)

| 代碼 | 來源 | 結果數量 | 說明 |
|------|------|----------|------|
| `pmc` | PubMed Central | ~41,000 | 生物醫學期刊文章 |
| `mpx` | MedPix | ~641 | 臨床教學影像，品質高 |
| `iu` | Indiana University | ~7,400 | 放射報告資料集 |
| (無) | 全部 | ~133,000 | 所有集合 |

### 分頁機制

```
m=1   → 回傳第 1-10 筆 (min=1, max=10)
m=11  → 回傳第 11-21 筆 (min=11, max=21)
m=21  → 回傳第 21-31 筆
```

- `m` = 起始偏移量（**不是** "最大結果數"），1-based
- 預設每頁回傳 ~10 筆
- 可用 `n` 參數覆蓋每頁數量 (e.g., `n=3` 只回傳 3 筆)
- 頁間無重疊

### 查詢格式

```bash
# 基本搜尋 (必須指定 it!)
curl "https://openi.nlm.nih.gov/api/search?q=lung+cancer&it=xg"

# X-ray 圖片
curl "https://openi.nlm.nih.gov/api/search?q=pneumonia&it=xg"

# 顯微鏡圖片
curl "https://openi.nlm.nih.gov/api/search?q=histology&it=mc"

# 臨床照片
curl "https://openi.nlm.nih.gov/api/search?q=skin+lesion&it=ph"

# MedPix 集合
curl "https://openi.nlm.nih.gov/api/search?q=chest+pneumonia&it=xg&coll=mpx"

# 第二頁
curl "https://openi.nlm.nih.gov/api/search?q=lung+cancer&it=xg&m=11"

# 組合篩選 + 指定每頁 5 筆
curl "https://openi.nlm.nih.gov/api/search?q=fracture&it=xg&coll=pmc&m=1&n=5"
```

### 回應結構

```json
{
  "total": 133000,
  "list": [
    {
      "uid": "e12345",
      "pmcid": "PMC1234567",
      "pmid": "12345678",
      "title": "Radiographic findings in...",
      "authors": "Smith J, Doe A",
      "journal_title": "Radiology",
      "imgLarge": "/multimedia/img/nlm/pmc/...",
      "imgThumb": "/multimedia/thumb/nlm/pmc/...",
      "MeSH": {
        "major": ["Lung Neoplasms"],
        "minor": ["Radiography"]
      },
      "Problems": "lung cancer",
      "image": {
        "caption": "Figure 1. CT scan showing..."
      }
    }
  ]
}
```

### 圖片 URL 建構

圖片路徑是**相對路徑**，需要加上前綴：

```
Base: https://openi.nlm.nih.gov

縮圖: https://openi.nlm.nih.gov{imgThumb}    → ~23KB
大圖: https://openi.nlm.nih.gov{imgLarge}    → ~592KB
```

**已驗證**: 圖片可直接存取，無需認證。

### 完整請求範例

```bash
# 搜尋 X-ray 胸部影像 (it 必填!)
curl -s "https://openi.nlm.nih.gov/api/search?q=chest+pneumonia&it=xg&m=1" | python -m json.tool

# 指定每頁回傳 3 筆
curl -s "https://openi.nlm.nih.gov/api/search?q=pneumonia&it=xg&n=3&m=1" | python -m json.tool

# 搜尋照片類型 (ph)
curl -s "https://openi.nlm.nih.gov/api/search?q=skin+lesion&it=ph&m=1" | python -m json.tool

# ❌ 省略 it → 回傳錯誤
curl -s "https://openi.nlm.nih.gov/api/search?q=pneumonia&m=1" | python -m json.tool
# → {"total": 0, "Query-Error": "Invalid request type."}

# 預期回應欄位
# .total → 結果總數
# .list[] → 結果陣列
# .list[].uid → 唯一識別碼
# .list[].pmcid → PMC ID
# .list[].pmid → PubMed ID
# .list[].imgLarge → 大圖相對路徑
# .list[].imgThumb → 縮圖相對路徑
# .list[].image.caption → 圖片說明
# .list[].MeSH → MeSH 標籤
```

---

## 2. Europe PMC — 圖片說明搜尋 (FIG:)

> 官方文檔: https://europepmc.org/RestfulWebService
> 維護: EMBL-EBI

### 基礎資訊

```
Base URL: https://www.ebi.ac.uk/europepmc/webservices/rest/search
Method: GET
Format: JSON / XML
Auth: 無需
```

### FIG: 查詢語法

Europe PMC 支援 `FIG:` 前綴搜尋圖片說明 (figure captions)：

```
FIG:"search terms"
```

這會搜尋文章中所有圖片的 caption 文字。

### 搜尋範例

```bash
# 搜尋含有 "kaplan meier" 圖片的文章
curl "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=FIG:%22kaplan%20meier%22&format=json&pageSize=5"
# → 254,000+ 結果

# 搜尋 CT scan 相關圖片
curl "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=FIG:%22CT%20scan%22&format=json&pageSize=10"

# 組合文章主題 + 圖片說明
curl "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=lung%20cancer%20AND%20FIG:%22survival%20curve%22&format=json"

# 只搜尋開放取用
curl "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=FIG:%22MRI%22%20AND%20OPEN_ACCESS:y&format=json"
```

### 回應結構 (文章層級)

```json
{
  "resultList": {
    "result": [
      {
        "id": "12345678",
        "pmid": "12345678",
        "pmcid": "PMC1234567",
        "doi": "10.1000/example",
        "title": "...",
        "authorString": "Smith J, Doe A.",
        "journalTitle": "Nature",
        "pubYear": "2023",
        "isOpenAccess": "Y",
        "inEPMC": "Y",
        "inPMC": "Y"
      }
    ]
  }
}
```

**注意**: FIG: 搜尋回傳的是**文章**列表，不是個別圖片  要取得實際圖片需要進一步使用 XML 全文提取。

---

## 3. Europe PMC — XML 全文圖片提取

### 全文 XML API

```
GET https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML
```

### 提取步驟

```bash
# Step 1: 取得全文 XML
curl -s "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC7096777/fullTextXML" > article.xml

# Step 2: 從 XML 中提取 <fig> 元素
# 每個 <fig> 包含:
#   - <label>: 圖片標籤 (e.g., "Figure 1")
#   - <caption>: 圖片說明
#   - <graphic>: 圖片檔案參考 (@xlink:href)
```

### XML 圖片結構 (`<fig>` 元素)

```xml
<fig id="fig1">
  <label>Figure 1</label>
  <caption>
    <title>CT scan findings</title>
    <p>Axial CT scan showing ground-glass opacities...</p>
  </caption>
  <graphic xlink:href="fcaa123-fig1" />
</fig>
```

### 圖片 URL 建構

從 `<graphic xlink:href>` 建構完整 URL：

```
Pattern: https://europepmc.org/articles/{pmcid}/bin/{href}.jpg

範例:
  pmcid = PMC7096777
  href  = fcaa123-fig1
  URL   = https://europepmc.org/articles/PMC7096777/bin/fcaa123-fig1.jpg
```

**已驗證**: 圖片可直接存取（測試下載 ~345KB jpg），無需認證。

### 完整提取流程 (Python 偽碼)

```python
import xml.etree.ElementTree as ET
import httpx

async def extract_figures(pmcid: str) -> list[dict]:
    """從 Europe PMC XML 提取圖片資訊。"""
    
    # 1. 取得全文 XML
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
    resp = await client.get(url)
    root = ET.fromstring(resp.text)
    
    # 2. 解析 <fig> 元素
    # 注意: 需處理 namespace
    ns = {'xlink': 'http://www.w3.org/1999/xlink'}
    figures = []
    
    for fig in root.iter('fig'):
        label = fig.findtext('label', '')
        caption_el = fig.find('caption')
        caption = ''
        if caption_el is not None:
            caption = ET.tostring(caption_el, method='text', encoding='unicode').strip()
        
        graphic = fig.find('.//graphic')
        href = graphic.get('{http://www.w3.org/1999/xlink}href', '') if graphic is not None else ''
        
        # 3. 建構圖片 URL
        image_url = f"https://europepmc.org/articles/{pmcid}/bin/{href}.jpg" if href else None
        
        figures.append({
            'id': fig.get('id', ''),
            'label': label,
            'caption': caption,
            'image_url': image_url,
            'pmcid': pmcid,
        })
    
    return figures
```

---

## 4. MedPix (透過 Open-i)

### 概述

MedPix 是 NLM 的臨床教學影像庫，透過 Open-i API 的 `coll=mpx` 篩選存取。

```bash
# 搜尋 MedPix 臨床影像
curl "https://openi.nlm.nih.gov/api/search?q=chest+pneumonia&coll=mpx"
# → ~641 結果，品質高的臨床教學影像
```

### 與一般 PMC 圖片的差異

| 特性 | PMC 圖片 | MedPix |
|------|----------|--------|
| 來源 | 期刊文章 | 臨床教學案例 |
| 數量 | ~41,000 | ~641 |
| 品質 | 混合 | 高品質臨床影像 |
| 標註 | MeSH 標籤 | MeSH + Problems + 臨床資訊 |
| 用途 | 研究參考 | 教學與診斷輔助 |

---

## 5. 來源比較與選擇指南

### 功能比較

| 功能 | Open-i | EPMC FIG: | EPMC XML |
|------|--------|-----------|----------|
| 搜尋方式 | 關鍵字 | 圖片說明搜尋 | 全文 XML 解析 |
| 結果類型 | 個別圖片 | 文章列表 | 個別圖片 |
| 圖片 URL | ✅ 直接 | ❌ 需二次提取 | ✅ 可建構 |
| 影像分類 | ✅ xg/mc/ph/gl (必填) | ❌ | ❌ |
| 索引時效性 | ❌ ~2020 | ✅ 持續更新 | ✅ 持續更新 |
| 回應速度 | 2-9 秒 | <1 秒 | 1-3 秒 |
| 適用場景 | X-ray/Photo/顯微鏡 | 找含特定圖的文章 | 提取文章所有圖 |

### 推薦策略

1. **通用圖片搜尋**: Open-i（直接回傳圖片 URL，一步到位）
2. **最新文獻圖片**: Europe PMC FIG: + XML 提取（索引持續更新）
3. **X-ray / 顯微鏡**: Open-i `it=xg` 或 `it=mc`
4. **臨床教學影像**: Open-i `coll=mpx`（MedPix）
5. **特定文章的圖片**: Europe PMC XML（已知 PMCID 時最佳）

---

## 6. 與現有 PubMed 資料整合

### 識別碼對應

兩個來源都回傳 `pmid` 和 `pmcid`，可與現有 `UnifiedArticle` 實體整合：

```python
# Open-i 結果 → UnifiedArticle 關聯
article = session.get_cached_article(pmid=openi_result['pmid'])

# Europe PMC FIG → 文章詳情
article_details = fetch_article_details(pmid=epmc_result['pmid'])
```

### 圖片資料結構 (建議)

```python
@dataclass
class ImageResult:
    """統一圖片搜尋結果。"""
    image_url: str          # 完整圖片 URL
    thumbnail_url: str | None = None
    caption: str = ""
    label: str = ""         # e.g., "Figure 1"
    source: str = ""        # "openi" | "epmc"
    
    # 關聯文章資訊
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    article_title: str = ""
    journal: str = ""
    authors: str = ""
    
    # Open-i 特有
    image_type: str | None = None   # "xg", "mc"
    mesh_terms: list[str] = field(default_factory=list)
    collection: str | None = None   # "pmc", "mpx", "iu"
```

---

## 7. 錯誤處理

### Open-i

| HTTP 狀態 | 原因 | 處理 |
|-----------|------|------|
| 200 + `total=0` | 無結果 | 回傳空列表 |
| 500 | 伺服器錯誤 | 重試 1 次後放棄 |
| Timeout (>10s) | 慢查詢 | 設定 15s timeout |

### Europe PMC

| HTTP 狀態 | 原因 | 處理 |
|-----------|------|------|
| 200 + `hitCount=0` | 無結果 | 回傳空列表 |
| 400 | 查詢語法錯誤 | 檢查 FIG: 格式 |
| 404 (fullTextXML) | 無全文 | 標記為無圖片 |
| 429 | 速率限制 | 等待後重試 |

---

## 附錄: 測試記錄

### Open-i 測試 — Round 1 (2026-02-09 早期，初始探索)

```
測試 1 — 圖片類型篩選 (省略 it 時仍可搜尋):
  q=lung+cancer, it=xg → 47,000 (有效)
  q=lung+cancer, it=mc → 26,000 (有效)  
  q=lung+cancer, it=gr → 133,000 (= 無篩選，無效)
  q=lung+cancer, it=ct → 133,000 (= 無篩選，無效)
  q=lung+cancer, it=abc123 → 133,000 (隨機值也無效)

測試 2 — 查詢格式:
  q=covid → 0 結果 (索引停止 ~2020)
  q=coronavirus → 4,600+ 結果
  q=lung+cancer → 133,000 結果
  q="lung cancer" → 支援引號短語

測試 3 — 分頁:
  m=1  → min=1, max=10 (10 筆)
  m=11 → min=11, max=21 (10 筆)  
  頁間無重疊

測試 4 — 集合篩選:
  coll=pmc → 41,000
  coll=mpx → 641
  coll=iu → 7,400

測試 5 — 回應速度:
  平均 2-9 秒/請求，無嚴格速率限制

測試 6 — 圖片可存取性:
  thumbnail → 23KB, 可直接下載
  large → 592KB, 可直接下載
```

### Open-i 測試 — Round 2 (2026-02-09，API 行為變更發現)

> ⚠️ 發現 API 行為變更：`it` 參數從「可選」變為「必填」

```
觸發原因: E2E 測試 OpenIClient.search("chest pneumonia") 時回傳 0 結果

測試 1 — 省略 it 參數:
  curl "https://openi.nlm.nih.gov/api/search?q=pneumonia&m=1"
  → {"total": 0, "Query-Error": "Invalid request type."}
  結論: it 參數現在是必填！

測試 2 — 逐一測試所有 it 值 (q=pneumonia):
  it=xg → total=1,541,988 ✅ (X-ray，涵蓋最廣)
  it=mc → total=768,198   ✅ (Microscopy)
  it=ph → total=816,743   ✅ (Photo)
  it=gl → total=0         ✅ (Graphics，但 pneumonia 無此類結果)
  it=ct → Query-Error     ❌
  it=mr → Query-Error     ❌
  it=us → Query-Error     ❌
  it=all → Query-Error    ❌

測試 3 — n 參數 (控制每頁數量):
  n=3  → 回傳 3 筆結果 (而非預設 10)
  n=20 → 回傳 20 筆結果
  結論: n 參數可控制每頁回傳數量

測試 4 — E2E 驗證修復後:
  OpenIClient.search("chest pneumonia", max_results=3)
  → total=1,541,988, images=3 ✅
  ImageSearchService.search("chest pneumonia CT", limit=3)
  → total=1,541,988, images=3, sources=["openi"], errors=[] ✅

修復方案:
  - OpenIClient: 預設 it=xg，無效值 fallback 到 xg
  - VALID_IMAGE_TYPES: {"xg", "mc"} → {"xg", "mc", "ph", "gl"}
  - 新增 DEFAULT_IMAGE_TYPE = "xg"
  - 加入 n 參數動態控制每頁數量
  - commit a2ef214
```

### Europe PMC 測試 (2026-02-09)

```
測試 1 — FIG: 搜尋:
  FIG:"kaplan meier" → 254,000+ 結果
  回應時間 < 1 秒

測試 2 — XML 圖片提取:
  PMC7096777 → 成功提取 <fig> 元素
  含 id, label, caption, graphic href
  
測試 3 — 圖片 URL:
  https://europepmc.org/articles/PMC{id}/bin/{href}.jpg
  → 成功下載 345KB jpg，無需認證
```
