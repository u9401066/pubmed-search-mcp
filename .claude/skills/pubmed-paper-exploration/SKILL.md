---
name: pubmed-paper-exploration
description: "Deep exploration from a key paper using related, citing, reference, and citation tree tools. Triggers: 這篇論文的相關研究, 誰引用這篇, 類似文章, related articles, citation tree, paper exploration"
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

## 核心探索方向

| 工具 | 作用 | 方向 |
|------|------|------|
| `fetch_article_details` | 取得文章完整資訊 | 當前論文 |
| `find_related_articles` | 找主題相近文章 | 橫向 |
| `get_article_references` | 找這篇引用了誰 | 往過去 |
| `find_citing_articles` | 找誰引用這篇 | 往未來 |
| `get_citation_metrics` | 看引用影響力 | 評估重要性 |
| `build_citation_tree` | 建立引用網路 | 視覺化 |
| `build_research_timeline` | 建立時間軸 | 演化脈絡 |

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

## 如果想看時間演化

### 以單篇或一組 PMID 建時間軸

```python
build_research_timeline(
    pmids="30217674,35678901,34567890",
    topic="Remimazolam Clinical Development",
    output_format="mermaid"
)
```

### 以主題建時間軸

```python
build_research_timeline(
    topic="remimazolam",
    max_events=20,
    output_format="text"
)
```

---

## 想深入讀內容時

### 全文

```python
get_fulltext(pmid="30217674", extended_sources=True)
```

### 圖表

```python
get_article_figures(pmid="30217674")
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
- `build_research_timeline` 中最近幾個 milestone

### 找基礎文獻

優先看：

- `get_article_references` 回傳的早期高影響力論文

---

## 常見錯誤

- `fetch_article_details` 不等於引用網路工具；引用與被引用應分別使用 `get_article_references` 和 `find_citing_articles`
- `build_citation_tree` 一次只接受一個 PMID，不要一次傳多篇
- 若沒有種子 PMID，先用 `unified_search` 找，不要直接猜
