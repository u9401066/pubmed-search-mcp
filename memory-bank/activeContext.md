# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

- **v0.3.5 已完成** — 品質強化、測試零失敗、準備 git commit + tag

## 📊 測試結果

- **2181 passed, 0 failed, 27 skipped** in 107.81s
- 94 files modified (14 production + 80 test files)

## ✅ 已完成本 session (v0.3.5)

### Production Code
- batch.py: `await _rate_limit()` 在 Entrez.esearch/efetch 前
- 8 source clients: 429 retry (指數退避 1s→2s→4s, max 3) + safe Retry-After
- copilot_tools.py: 完整重寫 (移除 11 重複工具, proper async)
- Code review fixes: exception handlers, error messages

### Test Code
- 60+ test files 修復 (async compatibility)
- MagicMock→AsyncMock, with→async with, urllib→httpx mocks
- 4 integration tests marked skip (real API calls)

### Governance
- CONSTITUTION.md: 第 7.1.1 條 File Hygiene
- copilot-instructions.md: 🧹 檔案衛生規範
- .gitignore: temp file exclusion patterns

## 📈 Version History
- v0.3.5: 品質強化 + 測試零失敗 (current)
- v0.3.4: async-first migration
- v0.3.3: Open-i 搜尋修復
- v0.3.2: UnifiedArticle dataclass fix
- v0.3.1: 41→34 tools consolidation

## 🔜 下一步 (low priority)
- ARCHITECTURE.md 更新 (outdated directory tree)
- run_copilot.py / run_server.py import path fixes
- clinical_trials.py + preprints.py → async httpx

---
*Last updated: 2026-02-10 — v0.3.5 release session*