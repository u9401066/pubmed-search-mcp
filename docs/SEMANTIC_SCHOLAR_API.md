# Semantic Scholar API Reference

> 官方文檔: https://api.semanticscholar.org/api-docs/

## 概述

Semantic Scholar 是 Allen Institute for AI 提供的學術搜尋引擎。
- **收錄量**: 200M+ papers
- **免費**: 基本使用無需 API key
- **特色**: Citation graph, Influential citations, Author disambiguation

## API 基礎

```
Base URL: https://api.semanticscholar.org/graph/v1
```

### Rate Limits
- 無 API key: 100 requests / 5 minutes
- 有 API key: 1 request/second (1000 requests/5min)
- 申請 key: https://www.semanticscholar.org/product/api#api-key-form

### 認證
```
Header: x-api-key: <your-api-key>
```

## Paper Search

### 基本搜尋
```
GET /paper/search?query=<query>&fields=<fields>
```

**範例:**
```
/paper/search?query=machine+learning&limit=10&fields=paperId,title,year,authors
```

### 可用 Fields

#### 基本欄位 (免費)
| Field | 說明 |
|-------|------|
| `paperId` | S2 Paper ID (40 char hex) |
| `title` | 論文標題 |
| `abstract` | 摘要 |
| `year` | 出版年份 |
| `venue` | 發表場所/期刊 |
| `publicationVenue` | 詳細場所資訊 (object) |
| `authors` | 作者列表 |

#### 識別碼
| Field | 說明 |
|-------|------|
| `externalIds` | 外部 ID (DOI, PubMed, ArXiv, etc.) |

`externalIds` 包含:
- `DOI`: Digital Object Identifier
- `PubMed`: PMID
- `PubMedCentral`: PMC ID
- `ArXiv`: ArXiv ID
- `DBLP`: DBLP ID
- `MAG`: Microsoft Academic Graph ID

#### 引用指標
| Field | 說明 |
|-------|------|
| `citationCount` | 總引用次數 |
| `influentialCitationCount` | 有影響力的引用次數 |
| `referenceCount` | 參考文獻數量 |

#### Open Access
| Field | 說明 |
|-------|------|
| `isOpenAccess` | 是否為 OA |
| `openAccessPdf` | OA PDF 資訊 (url, status) |

### 搜尋參數

| 參數 | 說明 | 範例 |
|------|------|------|
| `query` | 搜尋詞 (必填) | `machine+learning` |
| `limit` | 結果數量 (max 100) | `10` |
| `offset` | 分頁偏移 | `0` |
| `fields` | 要取得的欄位 | `title,year,authors` |
| `year` | 年份過濾 | `2020-2024` 或 `2020-` 或 `-2020` |
| `openAccessPdf` | 只搜 OA 論文 | (空值即可) |
| `fieldsOfStudy` | 領域過濾 | `Medicine` |

### Year Filter 格式
```
year=2020-2024   # 2020 到 2024
year=2020-       # 2020 以後
year=-2020       # 2020 以前
```

### Fields of Study
- Medicine
- Biology
- Chemistry
- Computer Science
- Physics
- Mathematics
- Engineering
- ... etc.

## Get Single Paper

### By Paper ID
```
GET /paper/{paper_id}?fields=<fields>
```

支援的 ID 格式:
- S2 Paper ID: `649def34f8be52c8b66281af98ae884c09aef38b`
- DOI: `DOI:10.1234/example`
- PubMed: `PMID:12345678`
- ArXiv: `ARXIV:2106.01234`
- CorpusId: `CorpusId:12345678`

**範例:**
```
/paper/DOI:10.1038/nature12373?fields=title,year,citationCount
/paper/PMID:23903654?fields=title,authors,abstract
```

## Citations & References

### 取得引用此論文的文獻
```
GET /paper/{paper_id}/citations?fields=<fields>&limit=100
```

**Response:**
```json
{
  "data": [
    {
      "citingPaper": { ... paper object ... }
    }
  ]
}
```

### 取得此論文的參考文獻
```
GET /paper/{paper_id}/references?fields=<fields>&limit=100
```

**Response:**
```json
{
  "data": [
    {
      "citedPaper": { ... paper object ... }
    }
  ]
}
```

## Paper Object 結構

```json
{
  "paperId": "649def34f8be52c8b66281af98ae884c09aef38b",
  "externalIds": {
    "DOI": "10.1038/nature12373",
    "PubMed": "23903654",
    "PubMedCentral": "PMC3906836"
  },
  "title": "Paper Title Here",
  "abstract": "Abstract text...",
  "year": 2019,
  "venue": "Nature",
  "publicationVenue": {
    "id": "...",
    "name": "Nature",
    "type": "journal",
    "alternate_names": ["Nat"]
  },
  "authors": [
    {
      "authorId": "1234567",
      "name": "John Smith"
    }
  ],
  "citationCount": 1234,
  "influentialCitationCount": 89,
  "referenceCount": 45,
  "isOpenAccess": true,
  "openAccessPdf": {
    "url": "https://...",
    "status": "GREEN"
  }
}
```

## 與 PubMed 格式對應

| Semantic Scholar | PubMed |
|------------------|--------|
| `paperId` | - |
| `externalIds.PubMed` | `pmid` |
| `externalIds.PubMedCentral` | `pmc_id` |
| `externalIds.DOI` | `doi` |
| `title` | `title` |
| `authors[].name` | `authors` |
| `abstract` | `abstract` |
| `venue` / `publicationVenue.name` | `journal` |
| `year` | `year` |
| `citationCount` | - |
| `influentialCitationCount` | - |
| `isOpenAccess` | - |
| `openAccessPdf.url` | - |

## 實用查詢範例

### 1. 搜尋醫學領域論文
```
/paper/search?query=diabetes+treatment&fieldsOfStudy=Medicine&limit=20&fields=paperId,title,year,authors,citationCount,externalIds,isOpenAccess
```

### 2. 只搜尋 Open Access
```
/paper/search?query=machine+learning&openAccessPdf&limit=10&fields=title,year,openAccessPdf
```

### 3. 指定年份範圍
```
/paper/search?query=COVID-19&year=2020-2024&limit=20&fields=title,year,citationCount
```

### 4. 用 PMID 取得論文
```
/paper/PMID:33674215?fields=paperId,title,abstract,year,authors,citationCount,externalIds
```

### 5. 用 DOI 取得論文
```
/paper/DOI:10.1038/s41586-020-2012-7?fields=title,year,citationCount
```

### 6. 取得高引用論文的引用清單
```
/paper/PMID:33674215/citations?limit=50&fields=paperId,title,year,citationCount
```

## 注意事項

1. **Rate Limit**: 無 API key 時很容易觸發 429 Too Many Requests
2. **Fields**: 必須明確指定要取得的欄位，否則只回傳 paperId
3. **Year Filter**: 格式是 `YYYY-YYYY`，單邊範圍用 `YYYY-` 或 `-YYYY`
4. **Author Name**: 只有 display name，沒有 first/last name 分離
5. **Venue vs PublicationVenue**: `venue` 是字串，`publicationVenue` 是物件
6. **Influential Citations**: S2 獨有指標，表示對引用論文有實質貢獻的引用

## Error Responses

```json
{
  "message": "Too Many Requests. Please wait and try again...",
  "code": "429"
}
```

```json
{
  "error": "Paper not found",
  "code": "404"
}
```
