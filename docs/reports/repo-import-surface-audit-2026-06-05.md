# Repo Import Surface / Orphan Audit - 2026-06-05

## Summary

Multi-agent cross-check found few true orphan modules, but several high-cost
package roots were importing unrelated dependency trees. The main optimization
was to preserve public APIs while making package/root exports lazy.

Measured cold-import improvements in an isolated Python process:

| Probe | Before audit | After fixes |
| --- | ---: | ---: |
| `import pubmed_search` | ~800-900 ms | ~5.6 ms |
| `from pubmed_search import LiteratureSearcher` | loaded `httpx`, settings, citation exporter | ~88.8 ms; no `httpx`, MCP, pydantic settings |
| `from pubmed_search import QueryAnalyzer` | ~255 ms; loaded semantic enhancer, sources, settings | ~3.4 ms after root import; no source clients/settings |
| `import pubmed_search.presentation.mcp_server.tools.export` | ~305 ms; loaded settings/httpx transitively | ~9.4 ms after root import; no citation exporter/settings |

## Implemented Optimizations

- Lazy public package exports:
  - `src/pubmed_search/__init__.py`
  - `src/pubmed_search/application/__init__.py`
  - `src/pubmed_search/application/search/__init__.py`
  - `src/pubmed_search/infrastructure/__init__.py`
  - `src/pubmed_search/presentation/__init__.py`
  - `src/pubmed_search/presentation/mcp_server/__init__.py`
  - `src/pubmed_search/shared/__init__.py`
- Lazy MCP tool category registration in
  `src/pubmed_search/presentation/mcp_server/tools/__init__.py`.
- Deferred rarely used heavy imports:
  - `pylatexenc` only loads during LaTeX conversion.
  - `yaml` in pipeline MCP tools only loads on save/load operations.
  - Official citation exporter only loads when official citation export is used.
  - `load_settings()` in source/export paths is loaded only when settings are actually needed.
  - iCite keeps its monkeypatch seam but defers the shared async client import.
- Hardened shared HTTP client shutdown on Windows/pytest closed event loops.
- Updated `scripts/perf/import_surface_audit.py` to recognize lazy export maps so future audits do not mislabel dynamically loaded tool modules as orphaned.
- Added `tests/test_import_surface.py` to guard the optimized import boundaries.

## Orphan / Legacy Findings

Final import-surface audit (`scripts/_tmp/import_surface_audit_final.json`) found:

- Not orphaned:
  - `presentation/mcp_server/copilot_tools.py` is used by `run_copilot.py`.
  - `presentation/mcp_server/http_compat.py` is used by `presentation/mcp_server/http_cli.py`, `run_copilot.py`, and `scripts/run_https_local.py`; `run_server.py` is now a source-tree wrapper around the packaged HTTP CLI.
- Tests-only but intentional compatibility shims:
  - `infrastructure/sources/fulltext_registry.py`
  - `infrastructure/sources/fulltext_service.py`
- Tests-only legacy MCP helpers:
  - `presentation/mcp_server/tools/core.py`
  - `presentation/mcp_server/tools/merge.py`

`tools/core.py` and `tools/merge.py` are not registered in the primary MCP tool
surface. They can be removed in a planned breaking cleanup, but were kept here
to avoid surprising external direct-import users.

## Remaining Heavy Top-Level Imports

These are still intentional because they sit at feature entrypoints:

- Biopython (`Bio`) in NCBI Entrez modules.
- `mcp` in MCP server/tool modules.
- `httpx` in actual network clients.
- `fastapi` in HTTP/broker entrypoints.
- `pydantic`/`pydantic_settings` in settings and pipeline schema modules.
- `yaml` in pipeline store.
- `apscheduler` in pipeline scheduler.

## Verification

Passed:

- `uv run ruff check src tests scripts`
- `uv run ruff format --check src tests scripts`
- `uv run mypy src/ tests/`
- `uv run pytest -vv -m "not integration" --timeout=60 -o addopts="" -x`
  - 3399 passed, 21 skipped, 30 deselected
- `uv run python scripts/check_async_tests.py`
- `uv run python scripts/count_mcp_tools.py`
  - 46 tools, validation passed
- `uv lock --check`
- `uv run python scripts/perf/import_surface_audit.py --output scripts/_tmp/import_surface_audit_final.json`
