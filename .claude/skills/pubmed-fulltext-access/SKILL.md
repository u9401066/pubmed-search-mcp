---
name: pubmed-fulltext-access
description: "Full text access using get_fulltext, its fulltext_plan, register_fulltext for host- or user-supplied text, figure extraction, and institutional link tools. Triggers: 全文, fulltext, PDF, open access, 免費下載, PMC, 開放取用, 讀不到全文, register_fulltext"
---

# 全文取得指南

## 描述
已知文章識別碼時，用 `get_fulltext` 取回可讀正文、來源與連結。伺服器拿不到正文時，回應的 `fulltext_plan` 會列出適用於這篇的下一步，由 host agent 用自己的 WebFetch、使用者的瀏覽器、asset-aware-mcp 或 Zotero Keeper 完成，最後以 `register_fulltext` 登錄，之後的 `get_fulltext`、筆記與 Chronicle 都會重用。若要找出「哪些文章的方法或結果提過某個詞」，先用 Europe PMC 的章節索引找候選，再回到原文核對。

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
- `use_registered_fulltext`: 預設 `true`，先用已登錄的 agent／使用者提供全文；`false` 會重新查詢 provider

### 來源順序

1. 只有 PMID 時先解析 PMCID／DOI：Europe PMC metadata（`europe_pmc_metadata`）優先，失敗或過慢時改用 NCBI ESummary（`ncbi_metadata`）。
0. 這篇若已用 `register_fulltext` 登錄過，直接回傳該段文字（`registered_fulltext`，標示 `agent_supplied`／`user_supplied` 與 `supplied_not_verified`），不再查 provider。
2. 有 PMCID 時取結構化 JATS：Europe PMC（`europe_pmc`）優先；它失敗、沒有正文或數秒內未回應時，改向 PMC 正式主機 NCBI E-utilities `efetch db=pmc`（`ncbi_pmc`）。先取得正文者勝出，另一路標為 `superseded`。
3. XML 都失敗、沒有正文或只有 `front_matter_only` 時，才讀公開的 PMC 文章頁（`pmc_html`）。只在明確單篇的 `get_fulltext` 進行，搜尋預取與批次流程永遠不會讀；限速、快取，可用 `PUBMED_FULLTEXT_PMC_HTML=false` 關閉。回應的 `fulltext_retrieval` 記錄網址、`retrieved_at` 與頁面顯示的授權文字。
4. 之後才是 Unpaywall、institutional、CORE 與 PDF fallback；已取得正文時不再下載 PDF。
5. 整個請求有一個總時限（預設 90 秒）。時限內未開始的來源列在 `sources_skipped`，不是「上游不可用」。

### 判讀來源狀態

| 欄位／代碼 | 意義 | 下一步 |
| --- | --- | --- |
| `source_errors[].code = rate_limited` | 上游限流，`retry_after_seconds` 為已套用的冷卻秒數 | 冷卻後只重讀這篇 |
| `upstream_retries_exhausted` / `upstream_connection_error` / `timeout` | 上游重試後仍失敗、連線中斷或逾時 | 稍後重讀；其他來源的正文仍可用 |
| `deadline_exceeded` 或 `sources_skipped` | 總時限到了，該來源沒查完或沒開始 | 不可據此判定沒有全文 |
| `cache_error` | 本機全文快取故障，上游狀態未知 | 重讀一次；持續發生再回報 |
| `source_notices[].code = front_matter_only` | PMC 有這篇，但出版者不允許 XML 下載，只回傳前置資料 | 不當成全文；伺服器會在單篇請求改讀 PMC 文章頁，仍失敗時照 `fulltext_plan` 的 `host_fetch` 進行 |
| `source_notices[].code = no_body` | 該來源完成但沒有正文 | 看其他來源結果 |
| `source_notices[].code = supplied_not_verified` | 回傳的是 `register_fulltext` 登錄的文字，伺服器沒有比對 provider 版本 | 引用時註明來源與取得方式；要重查 provider 用 `use_registered_fulltext=false` |
| `source_errors[]` 的 `pmc_html` = `rate_limited` | PMC 網站限速或出現機器人驗證，伺服器已退避 | 不要重試迴圈；照 plan 用 host 端讀單篇頁面 |

---

## 拿不到正文時：`fulltext_plan` 決策流程

`get_fulltext` 沒有可用正文（或只有無結構的 PDF 抽取文字）時，JSON 會帶 `fulltext_plan`（Markdown 會出現「🧭 Fulltext plan」）。每一步都附 `why`、`legal`，只列出適用於這篇的步驟，依 `order` 執行，取得文字就停：

| `step` | 何時出現 | Agent 用什麼做 |
| --- | --- | --- |
| `retry_later` | 有來源逾時、限流或被總時限略過 | 等 `retry_after_seconds` 後只重讀這一篇；不要迴圈或批次重試 |
| `host_fetch` | 有 PMCID 而伺服器沒讀到 PMC 頁面，或找到公開 OA landing page | host 的 WebFetch 讀該網址，要求**逐字**正文而非摘要；接著 `register_fulltext(... retrieval_method="host_fetch")` |
| `download_oa_pdf` | 找到開放 PDF | 用 host 下載工具存到允許的資料夾；有 asset-aware-mcp 時 `ingest_documents` 取得 citation-ready spans；再 `register_fulltext(file_path=...)` |
| `expand_discovery` | 尚未跑擴展來源 | `get_fulltext(..., extended_sources=true)` |
| `institutional` | 伺服器已設定 OpenURL、EZproxy 或 browser broker | `get_institutional_link` 或 `allow_browser_session=true`；只在使用者自己的登入工作階段 |
| `zotero_attachment` | 有 DOI 或 PMID 可比對 | Zotero Keeper `check_articles_owned`；有附件就 `register_fulltext(file_path=附件, supplied_by="user", retrieval_method="zotero_attachment")` |
| `ask_user_for_pdf` | 永遠最後一步 | 請使用者提供他有權使用的 PDF |

每個建議登錄的步驟都附 `register_with`（已填好 `source` 與 `provenance` 的引數骨架）。

```python
# 1. 伺服器端讀不到（例如出版者禁止 XML、PMC 頁面出現驗證）
plan = get_fulltext(source={"kind":"pmid","value":"30721296"}, output_format="json")["fulltext_plan"]
# 2. host_fetch：用 host 的 WebFetch 讀公開 PMC 頁面（逐字正文）
# 3. 登錄，之後 get_fulltext／筆記／Chronicle 都會重用
register_fulltext(
    source={"kind":"pmcid","value":"PMC6439616"},
    content="## Results\n...逐字正文...",
    content_format="markdown",
    provenance={
        "retrieval_method": "host_fetch",
        "source_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC6439616/",
        "retrieved_at": "2026-11-25T08:00:00Z",
        "license": "頁面顯示的授權或著作權聲明（照抄）"
    }
)
```

### `register_fulltext` 規則

- 必填 provenance：`retrieval_method`、`retrieved_at`，以及 `source_url` 或檔案。授權照抄頁面所示，不要推測。
- `content` 與 `file_path` 二選一。`file_path` 只能是工作區（`PUBMED_WORKSPACE_DIR`）、筆記資料夾、tenant 資料夾或 `PUBMED_FULLTEXT_INTAKE_ROOTS` 內的 `.pdf`／`.txt`／`.md`／`.html`／`.xml`，不能含 `..`；遠端服務呼叫者只能送 `content`。
- 登錄的文字一律標示 `agent_supplied`（agent 取得）或 `user_supplied`（使用者提供），`provider_verified=false`；不會被當成 provider 全文。
- PDF 會抽取純文字但沒有頁碼或行號。需要逐句引用時，同一份 PDF 交給 asset-aware-mcp（`ingest_documents`／`parse_pdf_structure`）取得 citation-ready spans。
- 只登錄逐字正文；WebFetch 若回傳的是摘要，就不要登錄。

### 授權與同意

- **單篇、個人研究用途**：只讀這次問題需要的那一篇。不要對搜尋結果逐篇迴圈 WebFetch 或開瀏覽器，不要鏡像或批次下載。NCBI 允許個別閱讀 PMC 文章，但禁止從 PMC 網站系統性或大量下載；大量使用請改用 PMC Open Access subset／OA Web Service 等授權管道。
- **瀏覽器只用使用者自己的工作階段**，且需使用者同意；不得繞過付費牆、CAPTCHA 或存取控制，也不得使用影子圖書館或未授權副本。
- 保留宣告的授權與出處；機構全文與使用者 PDF 的分享範圍依其授權，不要再散布。

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

連結供研究者透過自己的圖書館權限開啟。只有操作者需要設定 resolver 時，才用 `list_resolver_presets()` 查可用預設，或以 `configure_institutional_access(resolver_url=...)` 設定機構提供的網址。已授權的本地 Zotero 附件也可供核讀：Zotero Keeper `check_articles_owned` 找到附件後，以 `register_fulltext(file_path=..., supplied_by="user", provenance={"retrieval_method":"zotero_attachment", ...})` 登錄（Zotero storage 需列在 `PUBMED_FULLTEXT_INTAKE_ROOTS`）。先核對文章與版本，再保存頁碼或小節。機構全文或個人 PDF 的分享範圍依該份授權決定。

### 如何交代實際讀到的證據

| 這次取得的資料 | Agent 可交給下一步的紀錄 |
| --- | --- |
| `get_fulltext` 的 JSON 回應含正文 | 核對 `content_sections` 或 `content` 的實際文字，保存 PMID／DOI、來源（`section_provenance`）、可辨認的文章版本及段落／表格位置。有截斷時讀回傳的 artifact。 |
| 已取得 XML，但指定章節缺失 | 依 `section_selection.available` 修正一次章節名稱，或省略 `sections`；仍缺少時標明哪個章節尚待核對。 |
| 僅有摘要、索引命中或連結 | 逐篇標明實際可讀範圍；照 `fulltext_plan` 補取單篇並 `register_fulltext`；保留文章在 Chronicle／篩選清單，將需要方法或結果佐證的陳述標為待核讀。 |
| `fulltext_origin` 為 `agent_supplied`／`user_supplied` | 註明取得方式（`fulltext_retrieval.retrieval_method`、`source_url`、`retrieved_at`）與未經 provider 驗證；PDF 需要逐句引用時改用 asset-aware-mcp 的 spans。 |
| 來源逾時、限流或被總時限略過 | 保留已取得的其他證據及 `coverage_status`、`source_errors[].code`、`sources_skipped`，將受影響的文章列為待補；依 `retry_after_seconds` 等候後，僅重讀所需的文章。 |

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

用 `get_institutional_link` 取得已配置的圖書館入口；在使用者自己的瀏覽器工作階段讀到所需段落後，以 `register_fulltext(retrieval_method="host_browser")` 登錄並更新核讀紀錄。

### `get_fulltext` 沒有正文

照回應的 `fulltext_plan` 依序執行，取得逐字正文後用 `register_fulltext` 登錄；PDF 另交 asset-aware-mcp 取得 citation-ready spans。

---

## 最後原則

全文工作流已經收斂成單一公開入口：先用 `get_fulltext`；拿不到時照 `fulltext_plan` 用 host 工具補取單篇，再以 `register_fulltext` 登錄供後續重用。需要圖表或 text mining 時再補用專用工具。
