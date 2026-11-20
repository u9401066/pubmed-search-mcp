---
name: pubmed-paper-exploration
description: "Explore papers through citations and optional cross-search of public sources and a local Zotero library. Triggers: 這篇論文的相關研究, 誰引用這篇, 館藏全文, 混合檢索, related articles, citation tree, paper exploration"
---

# 論文深度探索

## 描述
這個 workflow 用在「已經有一篇關鍵論文」之後的深挖。你可以沿三個方向展開：相似文獻、這篇引用了誰、誰又引用了它，再進一步建立 citation tree 或研究時間軸。

## 觸發條件
- 「這篇論文的相關研究」
- 「誰引用這篇？」
- 「這篇建立在誰的研究上？」
- 「幫我畫這篇論文的 citation tree」
- 已提供 PMID 或明確的種子論文標題

---

## 如果還沒有 PMID

先用 `unified_search` 找到種子論文：

```python
unified_search(
    query="remimazolam randomized controlled trial",
    limit=5,
    ranking="quality"
)
```

拿到 PMID 後，再進入下面 workflow。

---

## 公開索引與 Zotero 館藏交叉查找

在使用者已指定可查館藏、且 host 連到該使用者的 Zotero Keeper 時，可從兩邊獨立找候選。公開索引可找館外文獻；本機附件可能命中只出現在內文的詞。多人部署時在使用者端執行館藏工具。館藏文字、筆記、附件路徑及本機識別碼留在該使用者的工作範圍，對外查詢使用可公開的主題詞或文獻識別碼。

1. **公開資料庫**：用 `unified_search(query="gait rehabilitation", limit=20, output_format="json")`。記下查詢日期、實際來源、筆數、上限、失敗及截斷狀態；保留 run ID 或 artifact URI 供回查。已有結果可從 `read_session` 讀回。提供者暫停服務時，沿用已取得的文獻並註記覆蓋缺口。
2. **本機索引**：在允許查詢整個已連線書庫的情境，可用 Keeper 的 `advanced_search(q="wearable sensor", qmode="everything", start=0, limit=20)` 搜尋書目與已索引內文。用回傳的 `next_start` 翻頁，或記下預算耗盡時停在哪頁。若只允許特定收藏，改以 `get_collection_items(collection_key=collection_key, limit=limit)` 取得該收藏的候選，再於這些項目內核對；記下讀取上限。Keeper 未連線或索引不完整時，將館藏覆蓋標為未知。[Zotero 查詢範圍](https://www.zotero.org/support/dev/web_api/v3/basics)
3. **核對同一篇報告**：附件或筆記命中時，從 `data.parentItem` 追到所屬書目；以 `get_item(key=item_key)` 核對。若兩邊有相同 PMID 或正規化 DOI（去除 doi.org 前綴、統一大小寫），且其他已知識別碼相容，合併顯示並保留雙方來源。只靠標題、作者與年份相似，或 PMID、DOI 有衝突時，保留兩筆及「待核對」原因。只有一側找到的文獻也保留，分別標明公開索引或本機館藏。已知 PMID 的批次館藏提示可用 `check_articles_owned(pmids=pmids)`；逐篇確認仍依實際館藏項目。
4. **核對內文**：選定項目後，用 `get_item_attachments(item_key=item_key)` 辨認論文原稿、補充材料等附件，再用 `get_item_fulltext(item_key=attachment_key)` 讀取該附件的索引文字。比對回傳的 `content`，記錄 `source`、可用的章節／表格位置及 `indexed_pages`、`total_pages`。有附件但文字空白、只索引一部分、命中筆記、只有摘要或只有連結，各自標明。若館藏不可讀，可用已核對的 PMID／PMCID／DOI 呼叫 `get_fulltext` 嘗試其他可用來源。找不到關鍵段落時，將該項陳述列為未核實。
5. **交給下一位 agent**：每筆保留發表日期、這次觀察日期、原始來源、PMID／DOI、命中位置及可讀範圍。私人工作紀錄可附 Zotero 書庫範圍、item／attachment key 和回傳的 server ID。經費來源等欄位另附可回查的資料庫欄位或致謝段落。共享輸出依使用權提供書目與出處。交給 `build_research_chronicle` 的明列篇目使用已核實 PMID；僅有 DOI 或館藏 key 的候選保留在附表，記下尚未進入該版 Chronicle。

---

## 核心探索方向

| 工具 | 作用 | 方向 |
|------|------|------|
| `fetch_article_details` | 取得文章完整資訊 | 當前論文 |
| `find_related_articles` | 找主題相近文章 | 橫向 |
| `get_article_references` | 找這篇引用了誰 | 往過去 |
| `find_citing_articles` | 找誰引用這篇 | 往未來 |
| `get_citation_metrics` | 看引用影響力 | 評估重要性 |
| `build_citation_tree` | 建立引用網路 | 視覺化 |
| `build_research_chronicle` | 建立研究編年史 | 演化脈絡 |

---

## 最常用範例

### 1. 先拿文章細節

```python
fetch_article_details(pmids="30217674")
```

### 2. 找相似文章

```python
find_related_articles(pmid="30217674", limit=10)
```

### 3. 找這篇引用了誰

```python
get_article_references(pmid="30217674", limit=30)
```

### 4. 找誰引用了這篇

```python
find_citing_articles(pmid="30217674", limit=20)
```

### 5. 看哪幾篇最有影響力

```python
get_citation_metrics(
    pmids="30217674,35678901,34567890",
    sort_by="relative_citation_ratio"
)
```

### 6. 直接建 citation tree

```python
build_citation_tree(
    pmid="30217674",
    depth=2,
    direction="both",
    output_format="mermaid"
)
```

---

## 建議工作流程

### 情境：從一篇關鍵 RCT 往外展開

```python
# Step 1: 當前論文
fetch_article_details(pmids="30217674")

# Step 2: 三個方向同時展開
find_related_articles(pmid="30217674", limit=10)
get_article_references(pmid="30217674", limit=20)
find_citing_articles(pmid="30217674", limit=20)

# Step 3: 對重要 PMIDs 做引用影響力排序
get_citation_metrics(
    pmids="35678901,34567890,33456789",
    sort_by="citation_count"
)

# Step 4: 視覺化引用網路
build_citation_tree(
    pmid="30217674",
    depth=2,
    direction="both",
    output_format="cytoscape"
)
```

---

## 多種子替代方案

從主題搜尋的多篇種子向外擴展，可使用既有 pipeline，不必逐篇手動呼叫：

```python
unified_search(pipeline="""
template: snowball
template_params:
    query: remimazolam ICU sedation
    seed_limit: 5
    limit: 20
""")
```

`snowball` 執行 search → citing + references → union merge（含原始結果）；`seed_limit` 為 1–10、預設 5，`limit` 預設 20。
自訂 DAG 的 `related`／`citing`／`references` 可用 `inputs` + `seed_limit` 取前幾個不重複 PMID，不能同時指定 `pmid`。每個種子消耗一次外部呼叫預算；各 action 合併去重、排除 seeds 後以 `limit` 截斷。

## 如果想看時間演化

### 以單篇或一組 PMID 建編年史

```python
build_research_chronicle(
    pmids="30217674,35678901,34567890",
    topic="Remimazolam Clinical Development",
    output="mermaid"
)
```

### 以主題建編年史

```python
build_research_chronicle(
    topic="remimazolam",
    max_events=20,
    output="summary"
)
```

---

## 想深入讀內容時

### 全文

```python
get_fulltext(source={"kind":"pmid","value":"30217674"}, extended_sources=True)
```

### 圖表

```python
get_article_figures(source={"kind":"pmid","value":"30217674"})
```

---

## 實務判斷

### 找領域核心論文

優先看：

- `find_related_articles` 與 `find_citing_articles` 都常出現的文章
- `get_citation_metrics` 中 RCR 或 citation count 高的文章
- `build_citation_tree` 網路中心位置的節點

### 找最新進展

優先看：

- `find_citing_articles` 的最近年份文章
- `build_research_chronicle` 中最近幾個 milestone

### 找基礎文獻

優先看：

- `get_article_references` 回傳的早期高影響力論文

---

## 常見錯誤

- `fetch_article_details` 不等於引用網路工具；引用與被引用應分別使用 `get_article_references` 和 `find_citing_articles`
- `build_citation_tree` 一次只接受一個 PMID，不要一次傳多篇
- 若沒有種子 PMID，先用 `unified_search` 找，不要直接猜
