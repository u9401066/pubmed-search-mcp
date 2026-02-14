# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

- **v0.3.9 品質嚴格化** — ruff `select=["ALL"]` + mypy `strict=true` + pre-commit 17 hooks + noqa 消除

## 📊 測試結果

- **2400 passed, 0 failed, 27 skipped** in ~47s (pytest-xdist -n 4)
- ruff src/: `All checks passed!`
- mypy src/: 176 errors (已知，deferred 修復)

## ✅ 已完成本 session

### Phase 6: Ruff/Mypy 最大嚴格化
- ruff `select = ["ALL"]` — 啟用所有規則，~40 justified global ignores
- mypy `strict = true` — 包含 module overrides
- 修復 16 src/ ruff violations across 9 files
- `format` → `fmt` in `export_articles()` 重命名

### Phase 7: 生產級零例外 (`# noqa` 消除)
- **18 → 9 個 `# noqa`**（消除 9 個根因修復）
  - SLF001 ×3: `_ranking_score` 等欄位重命名為 public
  - A001 ×2: `format` → `fmt` 參數重命名 (ncbi/utils.py)
  - ARG001: 刪除 `retryable_status_codes` 死碼 (http/client.py)
  - ARG001: 移除未使用 `index` 參數 (async_utils.py)
  - S110 ×2: `pass` → `logger.debug()` / `return False`
  - N818: `RateLimitExceeded` → `RateLimitExceededError`
- 剩餘 9 個均為合理例外（monkey-patch, polyfill, security rules）

### Pre-commit Infrastructure (17 hooks)
- ruff lint + format, mypy, file-hygiene, async-test-checker
- tool-count-sync (auto-fix), evolution-cycle 一致性驗證
- pytest pre-push hook

### MCP Performance Profiling
- `shared/profiling.py`: 20 profiling tests
- Monkey-patch BaseAPIClient for request timing

## 📈 Version History
- v0.3.9: 品質嚴格化 + pre-commit + noqa 消除 (current)
- v0.3.8: QueryValidator + JournalMetrics + preprint detection
- v0.3.5: 品質強化 + 測試零失敗
- v0.3.4: async-first migration

## 🔜 下一步 (low priority)
- mypy 176 errors 逐步修復（主要 no-untyped-def, attr-defined）
- ARCHITECTURE.md 更新 (outdated directory tree)
- `type: ignore[import-not-found]` 調查 (core.py, ncbi_extended.py)

---
*Last updated: 2026-02-14 — v0.3.9 quality strictification session*
