# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

<!-- 一句話描述正在做什麼 -->
- **v0.2.0 DDD 架構重構完成** - 全面重組目錄結構為 DDD 層次

## 📝 進行中的變更

<!-- 具體的檔案和修改 -->
| 目錄/檔案 | 變更內容 |
|----------|----------|
| `src/pubmed_search/domain/` | 新增 - 核心實體 (UnifiedArticle) |
| `src/pubmed_search/application/` | 新增 - 應用服務 (search, export, session) |
| `src/pubmed_search/infrastructure/` | 重組 - ncbi/, sources/, http/ |
| `src/pubmed_search/presentation/mcp_server/` | 重命名 - 避免 mcp 套件衝突 |
| `src/pubmed_search/shared/` | 新增 - 跨層共用 (exceptions, async_utils) |
| `src/pubmed_search/__init__.py` | 更新 - 完整導出 + 詳細文檔 |

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
1. ✅ Git commit + push
2. ⏳ Token 效率優化 (Phase 5.8)
3. ⏳ Tool Router 設計 (ToolUniverse 整合)

---
*Last updated: 2026-01-26 - v0.2.0 DDD 架構重構完成*