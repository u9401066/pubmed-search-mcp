# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

- **v0.5.6 integration release** — merge local feature work with all reachable release/feature branches, validate the integrated MCP surface, then publish a new version after local and GitHub Actions checks are green

## 📊 測試結果

- `uv run ruff check src/ tests/ scripts/ run_server.py run_copilot.py`: ✅ passed
- `uv run mypy src/ tests/`: ✅ passed
- `uv run python scripts/check_async_tests.py`: ✅ passed
- `uv run pytest -q`: ✅ 3207 passed, 34 skipped
- MCP smoke import/create_server: ✅ `pubmed_search.__version__ == "0.5.6"`; `create_server()` initializes successfully
- `uv build`: ✅ wheel/sdist built for 0.5.6; package metadata has no `dependency-injector`; `requests` is only in the `scripts` extra
- Integration branch: `codex/integrate-local-v0.5.6`

## ✅ 已完成本 session

### v0.5.6: Integrated Local Feature Work + Release Candidate
- **Branch integration**: created `codex/integrate-local-v0.5.6`, committed the local workspace feature set, and merged all reachable remote release/feature branches; they were already contained in the current history.
- **New MCP capability**: added `verify_reference_list` for PubMed-backed reference-list verification using PMID, DOI, ECitMatch, and title-search evidence.
- **Agent workspace assets**: added shared `AGENTS.md`, Cline rules/workflows, Copilot guidance sync, VS Code extension recommendations, and setup harness docs/scripts.
- **Runtime hardening**: tightened Entrez isolation/retry behavior, source-client contracts, fulltext/browser fallback boundaries, cache cleanup, and MCP callback wrappers.
- **Release metadata**: bumped package metadata to 0.5.6 and documented the integrated release scope.

### v0.5.5: Windows Python 3.14 Startup Fix
- **Root cause**: Windows installs using Python 3.14 failed before MCP startup because `dependency-injector` loaded a native DLL extension during `pubmed_search.container` import.
- **Fix**: Replaced the external DI dependency with a pure-Python provider layer preserving config, singleton, override, and reset behavior.
- **Release scope**: version bump to 0.5.5, changelog update, lockfile metadata update, package build metadata verification.

### v0.5.0: Release Candidate Hardening + Docs Site
- **Docs site**: `docs/index.html` + generated `docs/site-content/*` + `scripts/build_docs_site.py`
- **Source contracts**: `docs/SOURCE_CONTRACTS.md` clarifies provenance, rate policy, credentials, and OA/fulltext promises
- **Shared abstractions**: `shared/source_contracts.py` + `shared/cache_substrate.py`
- **Policy extraction**: image search and timeline scoring/detection split into smaller policy/diagnostics modules
- **Release hardening**: deterministic mutation gate, in-memory MCP protocol test, local MCP RC validation, BaseAPIClient param-path fix, Unpaywall email fallback fix

## 📈 Version History
- v0.5.6: integrated local feature work; reference verification tool; AI workspace harness; source/runtime hardening
- v0.5.5: Windows/Python 3.14 MCP startup fix; removed native dependency-injector runtime dependency
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
- Push integration branch, run multi-platform GitHub Actions CI, merge to `master`, then tag and publish `v0.5.6`
- Algorithm innovation implementation (BM25/RRF/PRF)

---
*Last updated: 2026-04-24 — v0.5.6 integrated release candidate*
