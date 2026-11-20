---
name: pubmed-fulltext-access
description: "Full text access using get_fulltext, figure extraction, and institutional link tools. Triggers: 全文, fulltext, PDF, open access, 免費下載, PMC, 開放取用"
---

# 全文取得指南

## 描述
已知文章識別碼時，用 `get_fulltext` 取回可讀正文、來源與連結。若要找出「哪些文章的方法或結果提過某個詞」，先用 Europe PMC 的章節索引找候選，再回到原文核對。

## 觸發條件
- 「我要看全文」
- 「有 PDF 嗎？」
- 「這篇有 open access 嗎？」
- 「幫我抓方法或結果段落」
- 提到 PMC、全文、PDF、開放取用

---

## 核心工具

### 1. `get_fulltext`

```python
get_fulltext(source={"kind":"pmcid","value":"PMC7096777"})
get_fulltext(source={"kind":"pmid","value":"12345678"})
get_fulltext(source={"kind":"doi","value":"10.1038/s41586-021-03819-2"})
```

### 參數重點

- `source`: 必填的 discriminated object；`kind` 明確指定 `pmid`、`pmcid` 或 `doi`，`value` 放對應識別碼
- `sections`: 只抓特定段落，例如 `"introduction,methods,results"`
- `include_pdf_links`: 是否回傳 PDF 連結
- `include_figures`: 是否一起帶 figure metadata
- `extended_sources`: 是否擴展到更多來源

---

## 最常用範例

### 以方法段落找候選文獻

例如研究者想知道哪些復健研究在方法中提到步速，可透過既有入口執行這次補搜。Europe PMC 只對已收錄且可辨認章節的全文提供章節檢索。保留原有的標題／摘要檢索及其中尚無正文的候選，以免排除無法取得全文的早期研究。[Europe PMC 檢索範圍](https://blog.europepmc.org/2025/05/making-sense-of-europe-pmc-answers-to-your-biggest-faqs.html) · [章節欄位](https://dev.europepmc.org/doc/EBI_Europe_PMC_Web_Service_Reference.pdf)

```python
unified_search(
    query='rehabilitation AND METHODS:"gait speed"',
    sources="europe_pmc",
    options="shallow",
    limit=20,
    output_format="json"
)
```

Europe PMC 的 `METHODS:`、`RESULTS:` 語法只用於該來源。記錄執行日期、實際查詢、筆數上限、來源回報的總數或未知狀態與來源錯誤。命中時先標為「章節索引命中」。要主張研究確實量測步速，下一步必須取得該篇的定義、量測方式及段落位置。零筆命中也要保留這次搜尋的範圍。

例如這個查詢曾找回一篇回顧，Methods 裡的 `gait speed` 是書目檢索詞。引用這段可說明作者如何搜尋文獻；若要擷取參與者的步速，仍需追到實際執行量測的原始研究。[原文 Methods](https://pmc.ncbi.nlm.nih.gov/articles/PMC13748176/#Sec2)

### 1. 直接抓 PMC 全文

```python
get_fulltext(source={"kind":"pmcid","value":"PMC7096777"})
```

### 2. 只看方法與結果

```python
get_fulltext(
    source={"kind":"pmid","value":"12345678"},
    sections="methods,results"
)
```

### 3. 用 DOI 找 OA 版本

```python
get_fulltext(
    source={"kind":"doi","value":"10.1038/s41586-021-03819-2"},
    extended_sources=True
)
```

### 4. 全文連同 figures

```python
get_fulltext(
    source={"kind":"pmcid","value":"PMC7096777"},
    include_figures=True
)
```

---

## 圖表與視覺資料

### 取得文章圖表

```python
get_article_figures(source={"kind":"pmcid","value":"PMC12086443"})
get_article_figures(source={"kind":"pmid","value":"40384072"})
```

適合用在：

- 要單獨抽 figure caption 與 image URL
- 想快速找到流程圖、結果圖、顯微圖
- 需要比全文更結構化的圖像資料

---

## 文字探勘

### 取得 text-mined terms

```python
get_text_mined_terms(source={"kind":"pmcid","value":"PMC7096777"})
get_text_mined_terms(source={"kind":"pmid","value":"12345678"}, semantic_type="CHEMICAL")
```

常用 `semantic_type`:

- `GENE_PROTEIN`
- `DISEASE`
- `CHEMICAL`
- `ORGANISM`
- `GO_TERM`

---

## 沒有 open access 時

### 使用已配置的機構連結

```python
get_institutional_link(source={"kind":"pmid","value":"12345678"})
```

連結供研究者透過自己的圖書館權限開啟。只有操作者需要設定 resolver 時，才用 `list_resolver_presets()` 查可用預設，或以 `configure_institutional_access(resolver_url=...)` 設定機構提供的網址。已授權的本地 Zotero 附件也可供核讀；先核對文章與版本，再保存頁碼或小節。機構全文或個人 PDF 的分享範圍依該份授權決定。

### 如何交代實際讀到的證據

| 這次取得的資料 | Agent 可交給下一步的紀錄 |
| --- | --- |
| `get_fulltext` 的 JSON 回應含正文 | 核對 `content_sections` 或 `content` 的實際文字，保存 PMID／DOI、來源（`section_provenance`）、可辨認的文章版本及段落／表格位置。有截斷時讀回傳的 artifact。 |
| 已取得 XML，但指定章節缺失 | 依 `section_selection.available` 修正一次章節名稱，或省略 `sections`；仍缺少時標明哪個章節尚待核對。 |
| 僅有摘要、索引命中或連結 | 逐篇標明實際可讀範圍；保留文章在 Chronicle／篩選清單，將需要方法或結果佐證的陳述標為待核讀。 |
| 來源逾時或限流 | 保留已取得的其他證據及 `coverage_status`、`source_errors`，將受影響的文章列為待補；依來源的等候時間，稍後僅重讀所需的文章。 |

---

## 建議工作流程

### 情境 1：從文章直接拿全文

```python
fetch_article_details(pmids="12345678")
get_fulltext(source={"kind":"pmid","value":"12345678"}, sections="methods,results")
```

### 情境 2：搜尋後挑代表性文章讀全文

搜尋回應每列的 `read_request` 可直接呼叫文字全文；有需要才補 `sections`。
若 `section_selection` 列出未找到的章節，依 `available` 改名或省略篩選後讀取；
不要將摘要當成缺失正文，也不用輪詢背景狀態或重跑搜尋。

若預計深入閱讀，可在 `unified_search` 加上 `fulltext="prefetch"`；只對排名前三篇中已有
PMCID 的候選背景預取 XML。選定後用回應列出的 PMCID 呼叫 `get_fulltext`，會共用快取與
進行中的請求，不必輪詢。只讀文字可加 `include_pdf_links=False`。一般探索保持預設關閉，
避免下載未讀文章；完整限制見 `docs/guides/TOOLS_USAGE_GUIDE.md`。

```python
unified_search(
    query="remimazolam ICU sedation",
    limit=10,
    ranking="quality",
    fulltext="prefetch",
    output_format="json"
)

# 使用所選文章的 read_request.arguments；此 PMCID 僅為格式示例。
get_fulltext(
    source={"kind":"pmcid","value":"PMC7096777"},
    sections="methods,results",
    include_pdf_links=False,
    output_format="json"
)
```

### 情境 3：先抓全文，再抽圖表與實體

```python
get_fulltext(source={"kind":"pmcid","value":"PMC7096777"}, include_figures=True)
get_article_figures(source={"kind":"pmcid","value":"PMC7096777"})
get_text_mined_terms(source={"kind":"pmcid","value":"PMC7096777"}, semantic_type="CHEMICAL")
```

---

## 工具選擇規則

### 只想拿全文或 PDF

先用 `get_fulltext`

### 想抓圖表

用 `get_article_figures`

### 想抽 gene / disease / chemical

用 `get_text_mined_terms`

### 文章不是 OA，但你有圖書館帳號

用 `get_institutional_link` 取得已配置的圖書館入口，讀到所需段落後再更新核讀紀錄。

---

## 最後原則

全文工作流已經收斂成單一公開入口：先用 `get_fulltext`，需要圖表或 text mining 時再補用專用工具。
