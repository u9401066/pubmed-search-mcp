# OpenAlex API Reference

> 官方文檔: https://docs.openalex.org/

## 概述

OpenAlex 是完全開放的學術文獻目錄，命名來自亞歷山大圖書館。
- **收錄量**: 240M+ works，每天新增約 50,000 篇
- **免費**: 無需 API key，每日 100,000 requests
- **Polite Pool**: 加上 `mailto=your@email.com` 可獲得更高限額

## API 基礎

```
Base URL: https://api.openalex.org
```

### Rate Limits
- 無 API key: 100,000 requests/day
- Polite pool (有 email): 更高限額
- 建議: 每個請求加上 `mailto` 參數

## Works 搜尋

### 基本搜尋
```
GET /works?search=<query>
```

搜尋範圍：title, abstract, fulltext

**範例:**
```
https://api.openalex.org/works?search=machine%20learning
```

### 進階搜尋語法

#### Boolean 搜尋
- `AND`, `OR`, `NOT` (必須大寫)
- 引號精確匹配: `"exact phrase"`
- 括號控制優先級

**範例:**
```
/works?search=(diabetes AND treatment) NOT review
/works?search="machine learning" AND healthcare
```

#### 搜尋特定欄位
```
/works?filter=title.search:machine%20learning
/works?filter=abstract.search:deep%20learning
/works?filter=fulltext.search:CRISPR
/works?filter=title_and_abstract.search:neural%20network
```

## Filters 過濾器

### 日期過濾
```
from_publication_date:2020-01-01
to_publication_date:2024-12-31
publication_year:2023
```

### Open Access 過濾
```
is_oa:true                              # 任何 OA
open_access.oa_status:gold              # Gold OA
open_access.oa_status:green             # Green OA
locations.source.is_in_doaj:true        # DOAJ 期刊
has_oa_accepted_or_published_version:true
```

### 識別碼過濾
```
doi:10.1234/example
ids.pmid:12345678                       # 或 pmid:12345678
ids.pmcid:PMC1234567
has_pmid:true
has_doi:true
```

### 引用過濾
```
cited_by_count:>100                     # 被引用超過100次
cites:W2741809807                       # 引用特定論文
cited_by:W2766808518                    # 被特定論文引用
```

### 組合過濾 (邏輯運算)

| 運算 | 符號 | 範例 |
|------|------|------|
| AND | `,` 或 `+` | `is_oa:true,cited_by_count:>10` |
| OR | `|` | `publication_year:2022|2023` |
| NOT | `!` | `country_code:!us` |

## Sort 排序

```
?sort=<field>:<direction>
```

可用欄位:
- `display_name` - 標題
- `cited_by_count` - 引用次數
- `publication_date` - 出版日期
- `relevance_score` - 相關性 (需有 search)

**範例:**
```
/works?search=diabetes&sort=cited_by_count:desc
/works?search=AI&sort=publication_date:desc,relevance_score:desc
```

**注意**: `relevance_score` 只有在有 search 查詢時才能使用！

## 分頁

```
?per_page=50&page=2
```
- `per_page`: 每頁筆數 (最大 200)
- `page`: 頁碼

## Work Object 重要欄位

```json
{
  "id": "https://openalex.org/W2741809807",
  "doi": "https://doi.org/10.1038/s41586-019-1099-1",
  "title": "...",
  "display_name": "...",
  "publication_year": 2019,
  "publication_date": "2019-04-17",
  "type": "article",

  "ids": {
    "openalex": "https://openalex.org/W2741809807",
    "doi": "https://doi.org/10.1038/s41586-019-1099-1",
    "pmid": "https://pubmed.ncbi.nlm.nih.gov/30971826",
    "pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6538672"
  },

  "authorships": [
    {
      "author": {
        "id": "https://openalex.org/A1234567890",
        "display_name": "Author Name",
        "orcid": "https://orcid.org/0000-0001-2345-6789"
      },
      "institutions": [...],
      "is_corresponding": true
    }
  ],

  "primary_location": {
    "source": {
      "id": "https://openalex.org/S123456789",
      "display_name": "Nature",
      "issn_l": "0028-0836",
      "is_in_doaj": false
    },
    "is_oa": true
  },

  "open_access": {
    "is_oa": true,
    "oa_status": "gold",
    "any_repository_has_fulltext": true
  },

  "best_oa_location": {
    "pdf_url": "https://...",
    "is_oa": true,
    "version": "publishedVersion"
  },

  "cited_by_count": 1234,
  "referenced_works": [...],
  "abstract_inverted_index": {...}
}
```

### Abstract Inverted Index

OpenAlex 使用倒排索引儲存摘要以節省空間：

```json
{
  "abstract_inverted_index": {
    "This": [0],
    "study": [1, 15],
    "examines": [2],
    "the": [3, 10],
    ...
  }
}
```

重建方法：
```python
def reconstruct_abstract(inverted_index):
    word_positions = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(word for _, word in word_positions)
```

## 實用查詢範例

### 1. 搜尋最新高引用 OA 論文
```
/works?search=machine%20learning&filter=is_oa:true,cited_by_count:>50,from_publication_date:2020-01-01&sort=cited_by_count:desc&per_page=20
```

### 2. 搜尋有 PMID 的醫學論文
```
/works?search=diabetes%20treatment&filter=has_pmid:true&sort=relevance_score:desc
```

### 3. 搜尋 DOAJ 期刊的 Gold OA 論文
```
/works?search=anesthesia&filter=locations.source.is_in_doaj:true,is_oa:true&sort=publication_date:desc
```

### 4. 找出引用特定論文的文獻
```
/works?filter=cites:W2741809807&sort=cited_by_count:desc
```

### 5. 搜尋特定年份範圍
```
/works?search=propofol&filter=from_publication_date:2020-01-01,to_publication_date:2024-12-31
```

## 與 PubMed 格式對應

| OpenAlex | PubMed |
|----------|--------|
| `id` | - |
| `ids.pmid` | `pmid` |
| `ids.pmcid` | `pmc_id` |
| `ids.doi` | `doi` |
| `display_name` / `title` | `title` |
| `authorships[].author.display_name` | `authors` |
| `abstract_inverted_index` | `abstract` |
| `primary_location.source.display_name` | `journal` |
| `publication_year` | `year` |
| `publication_date` | `pub_date` |
| `cited_by_count` | - |
| `open_access.is_oa` | - |
| `best_oa_location.pdf_url` | - |

## 注意事項

1. **Sort relevance_score**: 只有在有 search 查詢時才能排序，否則會報 400 錯誤
2. **Abstract**: 需要從 inverted_index 重建，或使用 `select` 參數
3. **Rate limit**: 加上 `mailto` 參數可獲得更好的服務
4. **ID 格式**: OpenAlex ID 是完整 URL (e.g., `https://openalex.org/W123`)
5. **PMID/DOI**: 在 `ids` 物件中，格式包含完整 URL
