# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

- **v0.3.10 mypy 完全修復 + Pre-commit 41 hooks** — mypy 168→0, 2 real bugs found & fixed

## 📊 測試結果

- **2372 passed, 0 failed, 27 skipped** in ~47s (pytest-xdist -n auto)
- ruff src/: `All checks passed!`
- mypy src/: **0 errors** (Success: no issues found in 91 source files)

## ✅ 已完成本 session

### Phase 12: 14 new pre-commit hooks (17→41 total)
- bandit (security), vulture (dead code), deptry (dependency hygiene), semgrep (SAST)
- 7 custom hooks: future-annotations, no-print-in-src, ddd-layer-imports, no-type-ignore-bare, docstring-tools, no-env-inner-layers, todo-scanner
- 10 additional standard hooks from pre-commit-hooks repo

### Phase 13: mypy 168→0 comprehensive fix
- **2 real bugs**: missing `await` in fulltext_download.py (Semantic Scholar & OpenAlex PDF links silently broken)
- **1 logic bug**: timeline_builder.py iterated citation_data keys instead of .items()
- **Key discovery**: `disallow_untyped_defs = false` in overrides does NOT override `strict = true` — use `disable_error_code` instead
- **Key discovery**: mypy glob `*` only matches ONE module depth level
- **Key discovery**: `float.__pow__(float)` returns `Any` in typeshed — wrap in `float()`
- 30+ source files with proper type annotations
- 3 test fixes: Mock→AsyncMock, citation_data list→dict

## 📈 Version History
- v0.3.10: mypy 168→0 + pre-commit 41 hooks (current)
- v0.3.9: 品質嚴格化 + pre-commit 17 hooks + noqa 消除
- v0.3.8: QueryValidator + JournalMetrics + preprint detection
- v0.3.5: 品質強化 + 測試零失敗
- v0.3.4: async-first migration

## 🔜 下一步 (low priority)
- ARCHITECTURE.md 更新 (outdated directory tree)
- Algorithm innovation implementation (BM25/RRF/PRF)

---
*Last updated: 2026-02-14 — v0.3.10 mypy complete fix + hooks expansion*
