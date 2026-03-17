# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

- **v0.4.5 MCP SDK expansion + anti-reinvention refactor** — FastMCP progress/log, dynamic session resources, shared transport/cache cleanup

## 📊 測試結果

- **2970 passed, 0 failed, 28 skipped** (pytest-xdist -n 4, ~58s)
- ruff: `All checks passed!`
- mypy: **0 errors** (Success)
- async-test-checker: no mismatches

## ✅ 已完成本 session

### v0.4.5: MCP SDK Expansion + Anti-Reinvention
- **FastMCP Context support**: `build_research_timeline`, `analyze_timeline_milestones`, `compare_timelines`, `get_fulltext`, `get_text_mined_terms`
- **Dynamic session resources**: `session://last-search`, `session://last-search/pmids`, `session://last-search/results`
- **Dependency floor**: `mcp>=1.23.3`
- **PubTator refactor**: `PubTatorClient` now reuses `BaseAPIClient`
- **iCite cache refactor**: handwritten TTL cache replaced with `cachetools.TTLCache`
- **Docs synced**: README / README.zh-TW / copilot-instructions / CHANGELOG

## 📈 Version History
- v0.4.5: MCP SDK expansion + anti-reinvention cleanup
- v0.4.4: Article Figure Extraction (40 tools / 15 categories)
- v0.4.3: Landmark Paper Detection + Research Lineage Tree
- v0.3.10: mypy 168→0 + pre-commit 41 hooks
- v0.3.9: 品質嚴格化 + pre-commit 17 hooks + noqa 消除
- v0.3.8: QueryValidator + JournalMetrics + preprint detection
- v0.3.5: 品質強化 + 測試零失敗
- v0.3.4: async-first migration

## 🔜 下一步 (low priority)
- ARCHITECTURE.md 更新 (outdated directory tree)
- Algorithm innovation implementation (BM25/RRF/PRF)

---
*Last updated: 2026-03-17 — v0.4.5 MCP SDK expansion + anti-reinvention cleanup*
