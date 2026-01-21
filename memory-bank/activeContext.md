# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

<!-- 一句話描述正在做什麼 -->
- **Phase 2.2 完成** - ICD 自動偵測、Preprint 搜尋整合、Advanced Filters 修復

## 📝 進行中的變更

<!-- 具體的檔案和修改 -->
| 檔案 | 變更內容 |
|------|----------|
| `src/pubmed_search/sources/preprints.py` | 新增 - arXiv, medRxiv, bioRxiv 搜尋整合 |
| `src/pubmed_search/mcp/tools/unified.py` | 更新 - ICD 自動偵測、include_preprints 參數 |
| `src/pubmed_search/mcp/resources.py` | 更新 - ICD↔MeSH 雙向轉換工具 |
| `tests/test_preprints.py` | 新增 - 7 個 preprint/ICD 測試 |
| `README.md` | 更新 - Phase 2.2 功能說明 |

## ✅ 已解決問題

<!-- 根本原因和解決方案 -->
**Clinical Query Filter 語法**：
- 問題：`therapy[Filter]` 返回 0 結果
- 解決：改為 `(Therapy/Broad[filter])` 格式

**Preprint 搜尋**：
- ✅ arXiv API 整合 (Atom XML 解析)
- ✅ medRxiv/bioRxiv API 整合 (JSON)
- ✅ 統一 PreprintSearcher 介面

**ICD 自動偵測**：
- ✅ ICD-10 正則: `r'\b([A-Z]\d{2}(?:\.\d{1,4})?)\b'`
- ✅ ICD-9 正則: `r'\b(\d{3}(?:\.\d{1,2})?)\b'`
- ✅ 自動擴展為 MeSH 詞彙

## 💡 關鍵發現

<!-- 本次工作階段的重要發現 -->
- arXiv 使用 Atom XML 格式，需特殊解析
- medRxiv/bioRxiv 共用 API 結構
- ICD 代碼可包含小數點 (如 E11.9)
- PubMed Clinical Query 有 Broad/Narrow 變體

## 📁 新增/修改檔案

```text
src/pubmed_search/sources/preprints.py    # 新增 - preprint 搜尋客戶端
src/pubmed_search/mcp/tools/unified.py    # 更新 - ICD 偵測 + preprint 參數
src/pubmed_search/mcp/resources.py        # 更新 - ICD↔MeSH 轉換
tests/test_preprints.py                    # 新增 - 7 個測試
README.md                                  # 更新 - Phase 2.2 功能
```

## 🔜 下一步

<!-- 接下來要做什麼 -->
1. ⏳ Git commit + push
2. ⏳ Token 效率優化 (Phase 5.8)
3. ⏳ 競品學習功能 (Phase 5.7)

---
*Last updated: 2026-01-21 - Phase 2.2 ICD + Preprint 整合完成*