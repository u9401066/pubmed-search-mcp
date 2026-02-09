# Image Search API Reference

> 生物醫學圖片搜尋 API 參考文件
> 初始測試: 2026-02-09 | 最後更新: 2026-02-10 (完整參數文件 + 正確 enum 對照表)
> 資料來源: Swagger `/v2/api-docs` + Angular 前端 `main-B2TBBBVR.js` 反向工程

## 概述

本專案整合兩個圖片搜尋來源：

| 來源 | 收錄量 | 圖片來源 | 認證 | 特色 |
|------|--------|----------|------|------|
| **Open-i** (NLM) | ~133K 圖片 | PMC + MedPix + Indiana | 無需 | 專業醫學影像分類 |
| **Europe PMC** | 33M+ 文獻 | PMC 開放取用文獻 | 無需 | 圖片說明搜尋 + XML 圖片提取 |

---

## 1. Open-i API (NLM)

> 官方頁面: https://openi.nlm.nih.gov/
> Swagger: https://openi.nlm.nih.gov/v2/api-docs
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

---

## 2. 完整 API 參數一覽

> 從 Swagger `/v2/api-docs` + Angular 前端反向工程取得完整對照

### 參數總表

| 參數 | 類型 | 必填 | 說明 | 範例 |
|------|------|------|------|------|
| `query` | string | ✅ | 搜尋查詢詞 | `lung cancer` |
| `m` | int | ❌ | Start Index (1-based 起始索引，預設 1) | `1`, `11`, `21` |
| `n` | int | ❌ | End Index (結束索引，預設 10) | `10`, `20` |
| `it` | string | ❌ | 圖片類型篩選（省略 = 全部類型） | `x`, `mc`, `ph`, `g` |
| `coll` | string | ❌ | 集合篩選 | `pmc`, `cxr`, `mpx` |
| `favor` | string | ❌ | 結果排序方式 | `r`, `o`, `d` |
| `at` | string | ❌ | 文章類型篩選 | `cr`, `ra`, `rw` |
| `sp` | string | ❌ | 醫學專科篩選 | `r`, `ca`, `n` |
| `sub` | string | ❌ | 子集篩選 | `b`, `c`, `e`, `s`, `x` |
| `lic` | string | ❌ | 授權類型篩選 | `by`, `bync` |
| `fields` | string | ❌ | 搜尋欄位限定 | `t`, `ab`, `msh` |
| `hmp` | string | ❌ | HMD 出版物類型（History of Medicine） | `ph`, `pt`, `po` |
| `vid` | int | ❌ | 是否只搜尋影片 | `0`, `1` |

---

### 2.1 圖片類型 `it` — Image Type

> ⚠️ **重要修正 (2026-02-10)**:
> - `xg` = **Exclude Graphics**（排除圖表），NOT "X-ray general"
> - `xm` = **Exclude Multipanel**（排除多格圖片），NOT "X-ray misc"
> - `m` = **MRI**，NOT "Microscopy alt"
> - `p` = **PET**，NOT "Photo alt"
> - 正確的 X-ray 類型碼是 `x`

#### 正向篩選（只顯示該類型）

| 代碼 | 類型 (EN) | 類型 (中文) | 粗分類 | 說明 |
|------|-----------|------------|--------|------|
| `c` | CT Scan | CT 掃描 | 放射影像 | 電腦斷層掃描影像 |
| `g` | Graphics | 圖表 | 圖表 | 流程圖、示意圖、線稿、Algorithm |
| `m` | MRI | 磁振造影 | 放射影像 | 磁振造影 (MRI) 影像 |
| `mc` | Microscopy | 顯微鏡 | 顯微鏡 | 組織學、病理切片、顯微影像 |
| `p` | PET | 正子造影 | 放射影像 | 正子斷層掃描 (PET) 影像 |
| `ph` | Photographs | 臨床照片 | 照片 | 皮膚、傷口、術中、內視鏡照片 |
| `u` | Ultrasound | 超音波 | 超音波 | 超音波影像、心臟超音波 |
| `x` | X-ray | X 光 | 放射影像 | 一般 X 光影像 |

#### 排除篩選（排除特定類型）

| 代碼 | 類型 (EN) | 說明 |
|------|-----------|------|
| `xg` | Exclude Graphics | 排除圖表/示意圖，只保留實際醫學影像 |
| `xm` | Exclude Multipanel | 排除多格組合圖片 |

#### 影片（獨立參數 `vid`）

| 代碼 | 類型 | 說明 |
|------|------|------|
| `vid=1` | Video | 只顯示影片 |
| `vid=0` | 非影片 | 排除影片 |

> **注意**: 在 UI 中 Video 顯示在 Image Type 選單，但 API 使用獨立的 `vid` 參數

---

### 2.2 排序方式 `favor` — Rank By

| 代碼 | 排序方式 (EN) | 排序方式 (中文) |
|------|------|------|
| `r` | Newest | 最新優先 |
| `o` | Oldest | 最舊優先 |
| `d` | Diagnosis | 依診斷相關性 |
| `e` | Etiology | 依病因相關性 |
| `g` | Genetic | 依遺傳相關性 |
| `oc` | Outcome | 依預後相關性 |
| `pr` | Prevention | 依預防相關性 |
| `pg` | Prognosis | 依預後相關性 |
| `t` | Treatment | 依治療相關性 |

> **注意**: `r` (Newest) 是按日期排序給予更多權重，不是嚴格排序

---

### 2.3 文章類型 `at` — Article Type

| 代碼 | 類型 (EN) | 代碼 | 類型 (EN) |
|------|-----------|------|-----------|
| `ab` | Abstract | `ne` | News |
| `bk` | Book Review | `ob` | Obituary |
| `bf` | Brief Report | `pr` | Product Review |
| `cr` | Case Report | `or` | Oration |
| `dp` | Data Paper | `re` | Reply |
| `di` | Discussion | `ra` | Research Article |
| `ed` | Editorial | `rw` | Review Article |
| `ib` | In Brief | `sr` | Systematic Review |
| `in` | Introduction | `rr` | Radiology Report |
| `lt` | Letter | `os` | Orthopedic Slide |
| `mr` | Meeting Report | `hs` | Historical Slide |
| `ma` | Methods Article | `ot` | Others |

---

### 2.4 子集 `sub` — Subsets

| 代碼 | 子集 (EN) | 子集 (中文) |
|------|-----------|------------|
| `b` | Basic Science | 基礎科學 |
| `c` | Clinical Journals | 臨床期刊 |
| `e` | Ethics | 倫理學 |
| `s` | Systematic Reviews | 系統性回顧 |
| `x` | Chest X-rays | 胸部 X 光 |

---

### 2.5 集合 `coll` — Collections

| 代碼 | 集合名稱 | 說明 |
|------|----------|------|
| `pmc` | PubMed Central | 生物醫學期刊文章圖片 |
| `cxr` | Indiana U. Chest X-rays | 印第安那大學胸部 X 光專集 |
| `usc` | USC Orthopedic Surgical Anatomy | USC 骨科手術解剖圖片 |
| `hmd` | Images from the History of Medicine (NLM) | NLM 醫學史圖片 |
| `mpx` | MedPix | 高品質臨床教學影像 |

---

### 2.6 授權類型 `lic` — License Type

| 代碼 | 授權類型 | 說明 |
|------|----------|------|
| `by` | Attribution | CC BY |
| `bync` | Attribution NonCommercial | CC BY-NC |
| `byncnd` | Attribution NonCommercial NoDerivatives | CC BY-NC-ND |
| `byncsa` | Attribution NonCommercial ShareAlike | CC BY-NC-SA |

---

### 2.7 醫學專科 `sp` — Specialties

| 代碼 | 專科 (EN) | 代碼 | 專科 (EN) |
|------|-----------|------|-----------|
| `b` | Behavioral Sciences | `i` | Immunology |
| `bc` | Biochemistry | `id` | Infectious Diseases |
| `c` | Cancer | `im` | Internal Medicine |
| `ca` | Cardiology | `n` | Nephrology |
| `cc` | Critical Care | `ne` | Neurology |
| `d` | Dentistry | `nu` | Nursing |
| `de` | Dermatology | `o` | Ophthalmology |
| `dt` | Drug Therapy | `or` | Orthopedics |
| `e` | Emergency Medicine | `ot` | Otolaryngology |
| `en` | Endocrinology | `p` | Pediatrics |
| `f` | Family Practice | `py` | Psychiatry |
| `eh` | Environmental Health | `pu` | Pulmonary Diseases |
| `g` | Gastroenterology | `r` | Rheumatology |
| `ge` | Genetics | `s` | Surgery |
| `gr` | Geriatrics | `t` | Toxicology |
| `gy` | Gynecology and Obstetrics | `u` | Urology |
| `h` | Hematology | `v` | Vascular Diseases |
|  |  | `vi` | Virology |

---

### 2.8 搜尋欄位 `fields` — Search In

| 代碼 | 搜尋欄位 (EN) | 說明 |
|------|--------------|------|
| `t` | Titles | 只搜尋標題 |
| `m` | Mentions | 搜尋提及 |
| `ab` | Abstracts | 只搜尋摘要 |
| `msh` | MeSH | 只搜尋 MeSH 標籤 |
| `c` | Captions | 只搜尋圖片說明 |
| `a` | Authors | 只搜尋作者 |

---

### 2.9 HMD 出版物類型 `hmp` — History of Medicine Publication Type

> 僅在 `coll=hmd` 時有效

| 代碼 | 類型 | 代碼 | 類型 |
|------|------|------|------|
| `ad` | Advertisements | `lt` | Letter |
| `ar` | Architectural Drawings | `mp` | Maps |
| `at` | Atlases | `nw` | Newspaper Article |
| `bi` | Book Illustrations | `pn` | Personal Narratives |
| `br` | Broadsides | `ph` | Photographs |
| `cr` | Caricatures | `pi` | Pictorial Works |
| `ca` | Cartoons | `po` | Poetry |
| `ch` | Charts | `pt` | Portraits |
| `cg` | Congresses | `pc` | Postcards |
| `cd` | Consensus Development Conference | `ps` | Posters |
| `dr` | Drawings | | |
| `ep` | Ephemera | | |
| `ex` | Exhibitions | | |
| `hr` | Herbals | | |
| `hu` | Humor | | |

---

## 3. 分頁機制

```
m=1, n=10   → 回傳第 1-10 筆
m=11, n=20  → 回傳第 11-20 筆
m=21, n=30  → 回傳第 21-30 筆
```

- `m` = Start Index（1-based）
- `n` = End Index（預設 10）
- 每頁結果數 = n - m + 1
- 頁間無重疊

---

## 4. 查詢格式範例

```bash
# 基本搜尋 (所有類型)
curl "https://openi.nlm.nih.gov/api/search?query=lung+cancer&m=1&n=10"

# X-ray 圖片 (正確的代碼是 x，不是 xg！)
curl "https://openi.nlm.nih.gov/api/search?query=pneumonia&it=x&m=1&n=10"

# CT 掃描
curl "https://openi.nlm.nih.gov/api/search?query=lung+nodule&it=c&m=1&n=10"

# MRI 影像
curl "https://openi.nlm.nih.gov/api/search?query=brain+tumor&it=m&m=1&n=10"

# 顯微鏡圖片
curl "https://openi.nlm.nih.gov/api/search?query=histology&it=mc&m=1&n=10"

# 臨床照片
curl "https://openi.nlm.nih.gov/api/search?query=skin+lesion&it=ph&m=1&n=10"

# 圖表/流程圖
curl "https://openi.nlm.nih.gov/api/search?query=algorithm+flowchart&it=g&m=1&n=10"

# 超音波
curl "https://openi.nlm.nih.gov/api/search?query=cardiac&it=u&m=1&n=10"

# PET 掃描
curl "https://openi.nlm.nih.gov/api/search?query=lymphoma&it=p&m=1&n=10"

# 排除圖表（只要醫學影像）
curl "https://openi.nlm.nih.gov/api/search?query=pneumonia&it=xg&m=1&n=10"

# MedPix 集合
curl "https://openi.nlm.nih.gov/api/search?query=chest+pneumonia&coll=mpx&m=1&n=10"

# 組合篩選：Case Report + X-ray + 最新
curl "https://openi.nlm.nih.gov/api/search?query=fracture&it=x&at=cr&favor=r&m=1&n=10"

# 篩選專科 + 授權
curl "https://openi.nlm.nih.gov/api/search?query=melanoma&sp=de&lic=by&m=1&n=10"
```

---

## 5. 回應結構

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

```
Base: https://openi.nlm.nih.gov
縮圖: https://openi.nlm.nih.gov{imgThumb}    → ~23KB
大圖: https://openi.nlm.nih.gov{imgLarge}    → ~592KB
```

---

## 6. Europe PMC — 圖片說明搜尋 (FIG:)

```
Base URL: https://www.ebi.ac.uk/europepmc/webservices/rest/search
FIG: 搜尋回傳文章列表，需 XML 全文提取才能取得圖片。
```

---

## 7. 錯誤處理

| 情境 | 回應 | 處理 |
|------|------|------|
| 無結果 | `{"total": 0}` | 回傳空列表 |
| 無效 `it` 值 | `{"Query-Error": "Invalid request type."}` | 忽略篩選或報錯 |
| 伺服器錯誤 | HTTP 500 | 重試 1 次 |
| 逾時 | >10s | 設定 15s timeout |

---

## 附錄 A: 無效的 it 值

| 無效代碼 | 可能意圖 | 正確代碼 |
|----------|----------|----------|
| `ct` | CT Scan | `c` |
| `mr` | MRI | `m` |
| `us` | Ultrasound | `u` |
| `gl` | Graphics | `g` |
| `all` | 全部類型 | 省略 `it` |
| `pet` | PET | `p` |

---

## 附錄 B: Angular 前端逆向工程方法

本文檔中的 enum code → label 對照表透過以下步驟取得：

1. 下載 Angular main bundle: `curl -s "https://openi.nlm.nih.gov/main-B2TBBBVR.js" -o main.js`
2. 解析 Angular Ivy 編譯模板中的 `ie(n, "li", constRef)` + `fe(n, "Label")` 對
3. 從 `consts:` 陣列中提取 `["type", "code", ...]` 映射
4. 交叉比對 constRef 索引得到 code → label 對照

UI 的 `selectOption(event)` 方法使用 `o.attr("type")` 取得 `<li>` 的 type 屬性值作為 API 參數值，
`parent().parent().attr("type")` 取得 `<ul>` 的 type 屬性值作為 API 參數名稱。
