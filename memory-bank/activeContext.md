# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

- **v0.4.0 Pipeline System + CORE Integration** — DAG pipeline, 18→7 params, CORE as 6th source

## 📊 測試結果

- **2477+ passed, 0 failed, 27 skipped** (pytest-xdist -n auto)
- ruff src/: `All checks passed!`
- mypy src/: **0 errors** (Success)
- Pipeline tests: 71 passed

## ✅ 已完成本 session

### v0.4.0: Pipeline System + CORE Integration
- **Pipeline System**: DAG-based executor with 4 templates (quick/standard/deep/custom)
- **YAML Support**: Pipeline definitions in YAML format
- **CORE Integration**: 6th search source with 200M+ OA papers
- **Parameter Consolidation**: unified_search 18→7 params (filters, sources, options)
- **Single Entry Point**: unified_search replaces search_literature
- **DDD Fix**: PipelineExecutor dependency injection for infra layer
- **Deprecated**: search_by_icd → convert_icd_mesh + unified_search
- Pre-commit: removed deprecated check-byte-order-marker hook
- Bandit: added nosec for intentional 0.0.0.0 and /tmp bindings

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
