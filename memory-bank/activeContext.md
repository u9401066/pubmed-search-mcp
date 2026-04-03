# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

- **v0.5.0 release preparation** — docs site + source contracts + shared adapter/cache substrate + local MCP release validation

## 📊 測試結果

- `uv run pre-commit run --all-files`: ✅ passed
- Local MCP smoke validation: ✅ build/install smoke test + Copilot tool calls + targeted fix validation (181 tests)
- Release branch: `release/v0.5.0`

## ✅ 已完成本 session

### v0.5.0: Release Candidate Hardening + Docs Site
- **Docs site**: `docs/index.html` + generated `docs/site-content/*` + `scripts/build_docs_site.py`
- **Source contracts**: `docs/SOURCE_CONTRACTS.md` clarifies provenance, rate policy, credentials, and OA/fulltext promises
- **Shared abstractions**: `shared/source_contracts.py` + `shared/cache_substrate.py`
- **Policy extraction**: image search and timeline scoring/detection split into smaller policy/diagnostics modules
- **Release hardening**: deterministic mutation gate, in-memory MCP protocol test, local MCP RC validation, BaseAPIClient param-path fix, Unpaywall email fallback fix

## 📈 Version History
- v0.5.0: docs site + source contracts + shared adapter/cache substrate + release hardening
- v0.4.5: MCP SDK expansion + anti-reinvention cleanup
- v0.4.4: Article Figure Extraction (40 tools / 15 categories)
- v0.4.3: Landmark Paper Detection + Research Lineage Tree
- v0.3.10: mypy 168→0 + pre-commit 41 hooks
- v0.3.9: 品質嚴格化 + pre-commit 17 hooks + noqa 消除
- v0.3.8: QueryValidator + JournalMetrics + preprint detection
- v0.3.5: 品質強化 + 測試零失敗
- v0.3.4: async-first migration

## 🔜 下一步 (low priority)
- Push/tag `v0.5.0` and let release pipeline publish artifacts
- Algorithm innovation implementation (BM25/RRF/PRF)

---
*Last updated: 2026-04-03 — v0.5.0 release preparation*
