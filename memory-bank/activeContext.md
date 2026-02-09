# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

- **v0.3.0 Release** — Phase 4.1 Image Search MVP + Open-i API fix + dev tooling + docs

## 📝 進行中的變更

| 目錄/檔案 | 變更內容 |
|----------|----------|
| `infrastructure/sources/openi.py` | 修復 — `it` 參數現為必填，預設 `xg`，新增 `ph`/`gl` 類型，加 `n` 參數 |
| `tools/image_search.py` | 更新 — image_type 文檔加入 ph/gl/預設說明 |
| `tests/test_image_search.py` | 新增 — 3 個測試 (default_xg, invalid_defaults, ph, gl)，共 44 個 |
| `CHANGELOG.md` | 重整 — 合併 v0.3.0 所有條目，加入 5 個新 commit |
| `README.md + README.zh-TW.md` | 修正 — PICO 描述 5 處改為 Agent-driven |
| `pyproject.toml` | 統一 mypy 配置，移除 .mypy.ini |

## ✅ 已完成本 session

- Open-i API `it` 參數修復 (default xg, add ph/gl)
- ruff 0.14.13 + mypy 1.19.1 升級，109 lint 錯誤修復
- PICO README 描述全面修正
- test_perf.py 搬移至 tests/
- CHANGELOG v0.3.0 整合
- Memory Bank 更新
- 2093 tests passed, 44 image tests, 41 MCP tools / 13 categories

## 🔜 下一步

1. Phase 14 - Research Gap Detection
2. Phase 5.8 - Token 效率優化
3. Phase 13.2 - NLP 增強里程碑偵測

---
*Last updated: 2026-02-09 — v0.3.0 release session*