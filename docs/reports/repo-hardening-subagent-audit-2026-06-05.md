# Repo Hardening Subagent Audit - 2026-06-05

This report records the follow-up hardening pass after the complexity and
performance work. Four subagents reviewed independent areas of the repository,
then the findings were implemented and verified in this workspace.

## Scope

- Presentation/MCP session tools and tool registry
- Test/config/CI hygiene
- Application/domain export and cache compatibility
- Infrastructure fulltext retrieval paths

The local untracked `data/doc_2601_08815v3_3c60df/` directory was intentionally
left untouched.

## Findings Fixed

### Session and MCP Surface

- `read_session(action="artifact", max_chars=0)` could bypass inline response
  limits. The presentation layer now clamps non-positive values to
  `DEFAULT_ARTIFACT_READ_MAX_CHARS`.
- Artifact local paths are returned only when both requested and enabled through
  `PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS`.
- `read_session(action="log")` now separates event limit from history limit.
- `session://last-search/results` now inlines at most 20 cached payloads and
  returns `truncated`, `omitted_pmids`, and `resource_limit` metadata.
- `merge_search_results` was confirmed as a legacy helper. It remains importable
  for direct/legacy tests, but is intentionally absent from the 46-tool primary
  MCP surface. A registry sync test now protects that boundary.

### Export and Cache Compatibility

- RIS, BibTeX, CSV, MEDLINE, and JSON export now accept
  `UnifiedArticle.to_dict()` payloads with nested `identifiers`, nested `urls`,
  and dict-shaped authors.
- `ArticleCache` can read legacy raw article cache payloads that are not wrapped
  as `CachedArticle` and may contain extra fields.

### Fulltext Retrieval

- Retryable 429/503 landing-page PDF candidate failures now preserve retry
  metadata instead of collapsing into a generic failure.
- Browser-session broker success responses must contain PDF bytes beginning with
  `%PDF`.
- Non-direct landing pages now try the HTTP resolver before requiring browser
  assistance when browser fallback is disabled.
- Institutional direct/EZproxy probes that already return PDF content are treated
  as successful PDF retrieval metadata.
- CrossRef DOI lookup strips DOI URL prefixes and URL-encodes slashes.
- Biopython no longer exposes `Entrez.egquery`; an eGQuery endpoint shim now
  keeps `get_database_counts()` functional and typed.

### Test and CI Hygiene

- Removed default pytest xdist `-n 4` from `pyproject.toml` to reduce OOM risk.
- CI now runs `uv run mypy src/ tests/`.
- CI pytest now excludes integration tests with `-m "not integration"`.
- Live URL tests are marked `integration`.
- The pre-commit ruff hook is aligned with the locked ruff version.

## Verification

Completed:

- `uv run ruff check src tests`
- `uv run ruff format --check src tests`
- `uv run mypy src/ tests/`
- `uv run pytest -q -m "not integration" --timeout=60 -o addopts=""`
  - Result: `3393 passed, 21 skipped, 30 deselected`
- `uv run pytest --collect-only -q -o addopts=""`
  - Result: `3444 tests collected`
- `uv run python scripts/check_async_tests.py`
- `uv lock --check`
- `uv run python scripts/count_mcp_tools.py`
  - Result: `46 tools`, registry validation passed
- `uv run pytest tests/benchmarks/test_benchmarks.py -q --benchmark-only -p no:xdist`

## Residual Notes

- Full `pytest` without `-m "not integration"` was intentionally not used
  because live/network integration tests remain excluded from CI and are not
  appropriate for OOM-safe default validation.
- `merge_search_results` remains importable for legacy/direct tests but is
  intentionally absent from the primary MCP registry.
