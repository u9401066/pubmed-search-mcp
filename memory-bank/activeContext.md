# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

- **v0.4.4 Article Figure Extraction** — 圖表擷取工具 + domain entity + FigureClient

## 📊 測試結果

- **2956+ passed, 0 failed, 27 skipped** (pytest-xdist -n auto, ~55s)
- ruff: `All checks passed!`
- mypy: **0 errors** (Success)
- Figure tests: 58 passed

## ✅ 已完成本 session

### v0.4.4: Article Figure Extraction
- **New tool**: `get_article_figures` — PMC OA figure metadata + image URLs + PDF links
- **Domain**: `ArticleFigure` + `ArticleFiguresResult` dataclasses
- **Infrastructure**: `FigureClient(BaseAPIClient)` with 3-source fallback (EPMC/efetch/BioC)
- **SSRF**: URL whitelist validation for allowed academic domains
- **get_fulltext**: `include_figures=True` parameter for inline figure data
- **Spec**: `docs/MCP_Visual_Data_Retrieval_Spec.md` v1.1.0 with Appendix C review

## 📈 Version History
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
*Last updated: 2026-02-25 — v0.4.4 Article Figure Extraction*
