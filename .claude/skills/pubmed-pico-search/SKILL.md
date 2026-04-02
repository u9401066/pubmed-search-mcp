---
name: pubmed-pico-search
description: "PICO-based clinical question search using parse_pico and unified_search. Triggers: PICO, 臨床問題, A比B好嗎, treatment comparison, clinical question, 療效比較"
---

# PICO 臨床問題搜尋

## 描述
這個 workflow 用在臨床比較問題。先把自然語言拆成 PICO，再對各元素做術語擴展，最後組成一個可以執行的臨床查詢並用 unified_search 搜尋。

## 觸發條件
- 「A 比 B 好嗎？」
- 「哪個治療效果更好？」
- 「在某類病人中，某藥是否改善某結果？」
- 提到 PICO、臨床問題、療效比較

---

## PICO 元素

| 元素 | 說明 | 例子 |
|------|------|------|
| `P` | Population | ICU patients |
| `I` | Intervention | remimazolam |
| `C` | Comparison | propofol |
| `O` | Outcome | delirium |

---

## 正確工作流程

```text
parse_pico
→ generate_search_queries × 每個 PICO 元素
→ 組合 Boolean 查詢
→ analyze_search_query
→ unified_search
```

> 這個流程不再依賴舊的逐步搜尋與合併流程。臨床問題的重點是把 PICO 結構轉成一個清楚的臨床查詢，再用 unified_search 執行。

---

## Step 1: 解析 PICO

### 自然語言輸入

```python
parse_pico(
    description="remimazolam 在 ICU 鎮靜比 propofol 好嗎？會減少 delirium 嗎？"
)
```

### 或直接提供結構化欄位

```python
parse_pico(
    description="",
    p="ICU patients",
    i="remimazolam",
    c="propofol",
    o="delirium"
)
```

你要關注的輸出是：

- `pico`: 解析出的 P/I/C/O
- `question_type`: 例如 `therapy`, `diagnosis`, `prognosis`, `etiology`
- `suggested_filter`: 後續可轉進 `filters="clinical:..."`

---

## Step 2: 擴展各元素術語

```python
generate_search_queries(topic="ICU patients")
generate_search_queries(topic="remimazolam")
generate_search_queries(topic="propofol")
generate_search_queries(topic="delirium")
```

實務上，只對有值的元素呼叫即可。如果 `C` 不明確，就不要硬塞進查詢。

---

## Step 3: 組 Boolean 查詢

### 高精確度版本

```python
query = '''
("intensive care"[Title/Abstract] OR ICU[Title/Abstract])
AND
(remimazolam[Title/Abstract] OR "CNS 7056"[Title/Abstract])
AND
(propofol[Title/Abstract] OR Diprivan[Title/Abstract])
AND
(delirium[Title/Abstract] OR "Delirium"[MeSH Terms])
'''
```

### 高召回版本

```python
query = '''
("intensive care"[Title/Abstract] OR ICU[Title/Abstract])
AND
((remimazolam[Title/Abstract] OR "CNS 7056"[Title/Abstract])
 OR
 (propofol[Title/Abstract] OR Diprivan[Title/Abstract]))
AND
(delirium[Title/Abstract] OR sedation[Title/Abstract])
'''
```

---

## Step 4: 執行前分析

```python
analyze_search_query(query=query)
```

這一步可以先檢查查詢是否合理，再決定要不要執行。

---

## Step 5: 執行搜尋

```python
unified_search(
    query=query,
    limit=50,
    ranking="quality",
    filters="year:2018-2025, species:humans, clinical:therapy",
    output_format="json"
)
```

### `question_type` 對應的 `clinical` 篩選

| 問題類型 | filters 建議 |
|----------|--------------|
| `therapy` | `clinical:therapy` |
| `diagnosis` | `clinical:diagnosis` |
| `prognosis` | `clinical:prognosis` |
| `etiology` | `clinical:etiology` |

---

## 完整範例

### 情境：remimazolam vs propofol in ICU sedation

```python
# Step 1: 解析問題
pico = parse_pico(
    description="remimazolam 在 ICU 鎮靜比 propofol 好嗎？會減少 delirium 嗎？"
)

# Step 2: 為 P/I/C/O 擴展詞彙
generate_search_queries(topic="ICU patients")
generate_search_queries(topic="remimazolam")
generate_search_queries(topic="propofol")
generate_search_queries(topic="delirium")

# Step 3: 組查詢
query = '''
("intensive care"[Title/Abstract] OR ICU[Title/Abstract])
AND
(remimazolam[Title/Abstract] OR "CNS 7056"[Title/Abstract])
AND
(propofol[Title/Abstract])
AND
(delirium[Title/Abstract] OR "Delirium"[MeSH Terms])
'''

# Step 4: 先分析
analyze_search_query(query=query)

# Step 5: 再搜尋
unified_search(
    query=query,
    limit=50,
    ranking="quality",
    filters="year:2018-2025, species:humans, clinical:therapy"
)
```

---

## 常見判斷

### 沒有 Comparison

這很常見。直接用 `P + I + O` 即可，不要為了湊 PICO 硬塞對照組。

### 結果太少

- 拿掉 `C`
- 拿掉最窄的 outcome 詞
- 放寬成較高召回版本

### 結果太多

- 增加 outcome 限制
- 加 `filters="clinical:therapy"`
- 把 `ranking` 改成 `quality`
