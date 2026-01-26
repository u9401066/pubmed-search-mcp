# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

<!-- 一句話描述正在做什麼 -->
- **README i18n 同步完成** - 中英文版本結構完全對齊

## 📝 進行中的變更

<!-- 具體的檔案和修改 -->
| 目錄/檔案 | 變更內容 |
|----------|----------|
| `README.md` | 更新 - Middleware 架構圖、MCP 工具 ASCII 圖、PICO 流程、搜尋模式比較 |
| `README.zh-TW.md` | 完整同步 - 與英文版結構對齊、670→663 行 |

## ✅ 已解決問題

<!-- 根本原因和解決方案 -->
**mcp 套件命名衝突**：
- 問題：`mcp/` 目錄與 `mcp` 套件衝突
- 解決：重命名為 `presentation/mcp_server/`

**Python 3.10 相容性**：
- 問題：使用 Python 3.12 語法 (`[T]` type params, `ExceptionGroup`)
- 解決：改用 `TypeVar("T")` + 添加 `ExceptionGroup` fallback

**相對導入深度**：
- 問題：`...infrastructure` 等深層相對導入難維護
- 解決：改用絕對導入 `from pubmed_search.xxx import`

## 💡 關鍵發現

<!-- 本次工作階段的重要發現 -->
- DDD 架構提供清晰的關注點分離
- `presentation/` 層不應有 `..` 相對導入到其他層
- 絕對導入更容易維護和重構
- NCBI Citation Exporter API 提供官方引用格式

## 📁 新增/修改目錄結構

```text
src/pubmed_search/
├── domain/
│   └── entities/article.py          # UnifiedArticle
├── application/
│   ├── search/                       # QueryAnalyzer, ResultAggregator
│   ├── export/                       # formats.py, links.py
│   └── session/                      # SessionManager
├── infrastructure/
│   ├── ncbi/                         # base, search, citation, icite...
│   ├── sources/                      # europe_pmc, crossref, core...
│   └── http/                         # client, pubmed_client
├── presentation/
│   ├── mcp_server/                   # MCP tools, prompts, resources
│   └── api/                          # REST API
└── shared/
    ├── exceptions.py
    └── async_utils.py
```

## 🔜 下一步

<!-- 接下來要做什麼 -->
1. ⏳ Token 效率優化 (Phase 5.8)
2. ⏳ Tool Router 設計 (ToolUniverse 整合)
3. ⏳ 測試覆蓋率恢復至 90%+

---
*Last updated: 2026-01-26 - README i18n 同步完成*