# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

<!-- 一句話描述正在做什麼 -->
- **v0.2.0 增強功能完成** - ClinicalTrials.gov 整合 + Study Type 標籤

## 📝 進行中的變更

<!-- 具體的檔案和修改 -->
| 目錄/檔案 | 變更內容 |
|----------|----------|
| `infrastructure/sources/clinical_trials.py` | 新增 - ClinicalTrials.gov API 客戶端 |
| `presentation/mcp_server/tools/unified.py` | 修改 - 整合臨床試驗 + Study Type badge |
| `CHANGELOG.md` | 更新 - 新增功能記錄 |
| `ROADMAP.md` | 更新 - 標記已完成的 Phase |

## ✅ 已解決問題

<!-- 根本原因和解決方案 -->
**Hard-coded 縮寫詞典**：
- 問題：原計畫 hard-code 醫學縮寫
- 解決：改用 PubMed publication_types API 取得研究類型，不做推斷

**商用產品差異化**：
- 問題：如何與 OpenEvidence/SciSpace 競爭
- 解決：整合 ClinicalTrials.gov（**免費 API，競品沒有**）

## 💡 關鍵發現

<!-- 本次工作階段的重要發現 -->
- PubMed 已返回 `publication_types`，不需要 NLP 推斷
- ClinicalTrials.gov API v2 是免費公開的，無需 API key
- 多資料庫整合是我們的核心優勢（7 個 vs 競品 1 個）
- Union-Find 算法讓去重效率達 O(n)

## 📁 新增資料來源

```text
整合資料庫（共 8 個）:
├── PubMed (36M+)              # 主要搜尋
├── Europe PMC (45M+)          # 全文存取
├── CORE (270M+)               # 開放取用
├── OpenAlex (250M+)           # 學術元資料
├── Semantic Scholar (215M+)   # AI 增強
├── CrossRef (150M+)           # DOI 元資料
├── Unpaywall                  # OA 連結查找
└── ClinicalTrials.gov         # 🆕 臨床試驗
```

## 🔜 下一步

<!-- 接下來要做什麼 -->
1. ⏳ PRISMA flow tracking (Phase 5.9)
2. ⏳ Evidence level classification (Oxford CEBM I-V)
3. ⏳ Token 效率優化 (Phase 5.8)

---
*Last updated: 2026-01-26 - ClinicalTrials.gov 整合完成*