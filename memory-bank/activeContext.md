# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

- **v0.2.8 FulltextDownloader 增強** - Retry, Rate Limiting, Streaming 下載
- **Code Review 完成** - 套件導入、Mypy 錯誤修復

## 📝 進行中的變更

| 目錄/檔案 | 變更內容 |
|----------|----------|
| `infrastructure/sources/fulltext_download.py` | 新增 - Retry (exponential backoff), Rate Limiting (semaphore), Streaming Download |
| `tools/europe_pmc.py` | 更新 - get_fulltext 新增 `extended_sources` 參數 (15 sources) |
| `sources/__init__.py` | 更新 - 新增 `get_fulltext_downloader()` 工廠函數 |
| `session/manager.py` | 修復 - Mypy 型別錯誤 |
| `sources/openurl.py` | 修復 - Mypy 型別註解 |
| `tests/test_package_imports.py` | 修復 - API 簽名更新 |
| `tests/test_fulltext_urls.py` | 新增 - 17 個 URL 驗證測試 |

## ✅ 已實現功能

**FulltextDownloader 增強**:
- ✅ Rate Limiting: `asyncio.Semaphore(5)` 限制並行請求
- ✅ Retry: 指數退避 (1s, 2s, 4s...) 最多 3 次
- ✅ Streaming: 分塊下載 (8KB chunks) 避免記憶體爆炸
- ✅ 429 處理: 全域 Rate Limit 等待

**get_fulltext 工具擴展**:
- ✅ `extended_sources=True`: 啓用 15 個來源（預設 3 個）
- ✅ 來源優先順序: Europe PMC > Unpaywall > CORE > CrossRef > DOAJ > Zenodo...

## 💡 關鍵發現

- PDF 下載不需要外部套件，內建 `asyncio.Semaphore` + `httpx.stream` 即可
- Zenodo API 有 Cloudflare 保護，可能返回 403
- bioRxiv/medRxiv URL 需要版本後綴 (v1.full.pdf)
- 測試文件 API 簽名要與實際程式碼同步

## 🔜 下一步

1. ✅ Git commit + push v0.2.8
2. ⏳ Phase 14 - Research Gap Detection
3. ⏳ 帶遍測試覆蓋率到 50%+

---
*Last updated: 2026-02-06 - FulltextDownloader 增強 + Code Review*