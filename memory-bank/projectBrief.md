# Project Brief

> 📌 此檔案描述專案的高層級目標和範圍，建立後很少更改。

## 🎯 專案目的

**PubMed Search MCP Server** - 為 AI Agent 提供專業的 PubMed 文獻搜尋能力：
- MeSH 詞彙標準化搜尋
- PICO 臨床問題解析
- 智慧查詢擴展
- 多策略文獻探索（引用、相關文章）
- 多格式匯出（RIS, BibTeX, CSV）

## 👥 目標用戶

- 醫學研究人員
- 臨床工作者需要文獻回顧
- 使用 AI 助理進行文獻搜尋的開發者
- 系統性文獻回顧 (Systematic Review) 執行者

## 🏆 成功指標

- [x] 90%+ 測試覆蓋率 (✅ 90% - 411 tests)
- [x] 發布到 PyPI (✅ v0.1.8+)
- [x] 支援 SSE/STDIO 兩種 MCP 傳輸協定
- [x] 多來源整合 (PubMed, Semantic Scholar, OpenAlex)
- [ ] Citation Tree 視覺化功能完善

## 🚫 範圍限制

- 不提供全文下載功能（僅提供連結）
- 不儲存文獻資料（僅快取搜尋結果）
- 依賴 NCBI Entrez API 限制（每秒 3 次請求）

## 📝 備註

- NCBI API Key 可提升到每秒 10 次請求
- 遵循 NCBI E-utilities 使用政策

---
*Created: 2025-01-XX | Updated: 2025-01-XX*
