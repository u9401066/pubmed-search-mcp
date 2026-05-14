# Research Workflow Guide for Copilot

> 這份指南幫助 Copilot 理解如何正確使用 Zotero + PubMed MCP tools

## 🔍 文獻搜尋流程

### 步驟 1: 了解研究問題
使用 `parse_pico` 將研究問題拆解為 PICO 結構：
- **P**opulation: 研究對象
- **I**ntervention: 介入措施
- **C**omparison: 對照組
- **O**utcome: 結果指標

### 步驟 2: 生成搜尋策略
使用 `generate_search_queries` 產生專業的搜尋策略，包含：
- MeSH terms
- Boolean operators
- Field tags

### 步驟 3: 執行搜尋
使用 `unified_search` 執行搜尋，注意：
- 結果會自動快取到 Session
- 使用 `get_session_pmids` 取得已搜尋的 PMID
- **不要重複搜尋相同的關鍵字**
- `unified_search` 會自動合併去重多個來源的結果

### 步驟 4: 過濾已有文獻
使用 `check_articles_owned` 檢查搜尋結果中的 PMID 哪些已存在於 Zotero

---

## 📥 匯入 Zotero 流程

### ⚠️ 重要：先詢問 Collection！
在匯入任何文獻前，**必須先詢問用戶**要存入哪個 Collection。

### 匯入方式選擇

| 情境 | 推薦工具 | 說明 |
|------|----------|------|
| pubmed-search-mcp JSON 結果 | `import_articles` | 預設推薦，直接接 `unified_search(..., output_format="json")` |
| RIS 匯出文字 | `import_articles` | 傳入 `ris_text`，由 keeper 統一解析匯入 |
| 需要舊版 keeper 單機橋接流程 | legacy tools | 僅在啟用 `ZOTERO_KEEPER_ENABLE_LEGACY_PUBMED_TOOLS=1` 時使用 |

### 匯入前確認清單
1. ✅ 已詢問目標 Collection
2. ✅ 已確認文章或 PMID 來源（例如 `unified_search` 結果或 `get_session_pmids`）
3. ✅ 已提醒用戶文獻數量

---

## 🔄 Session 管理

### 為什麼需要 Session？
- PubMed 搜尋結果會快取
- 避免重複 API 呼叫
- 保持 PMID 追蹤，不依賴 Agent 記憶

### Session 工具使用時機

| 工具 | 何時使用 |
|------|----------|
| `get_session_pmids` | 需要取得之前搜尋的 PMID |
| `list_search_history` | 查看本次對話的搜尋紀錄 |
| `get_cached_article` | 取得已快取的文章詳情（避免重複 fetch） |
| `get_session_summary` | 檢查 Session 狀態 |

---

## 📚 Zotero 書庫管理

### 查詢現有文獻
1. `list_collections` - 先看有哪些 Collections
2. `get_collection_items` - 取得特定 Collection 的文獻
3. `search_items` - 在書庫中搜尋

### 避免重複匯入
使用 `check_articles_owned` 檢查 PMID 是否已存在

### 書庫分析
- `get_library_stats` - 統計分析
- `find_orphan_items` - 找出孤兒文獻（未分類）

---

## ⚠️ 常見錯誤避免

### ❌ 錯誤做法
1. 搜尋後直接匯入，沒問 Collection
2. 重複搜尋相同關鍵字
3. 匯入時沒確認 PMID 列表
4. 從 PubMed 重新取摘要（Zotero 已有）

### ✅ 正確做法
1. 搜尋 → 確認結果 → 詢問 Collection → 匯入
2. 用 `get_session_pmids` 取得已有的 PMID
3. 用 `get_item` 從 Zotero 讀取已存文獻的詳情
4. 匯入前用 `check_articles_owned` 檢查重複，再用 `import_articles` 存入 Zotero

---

## 🎯 典型對話流程範例

```
用戶: 幫我找最近的 AI 麻醉研究

Copilot 動作:
1. parse_pico: 分析研究問題
2. generate_search_queries: 產生搜尋策略
3. unified_search: 執行搜尋
4. [回報結果，詢問是否要存入 Zotero]
5. list_collections: 取得 Collection 列表
6. [詢問用戶要存入哪個 Collection]
7. import_articles: 匯入到指定 Collection
8. [確認完成]
```
